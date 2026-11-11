#!/usr/bin/env python3
"""Replay a frozen GEMM capture through the host-drivable FP32 AXI endpoint.

The datapath is the same one `run_gemm_fp32.py` already validates, but driven
the way a host actually drives it:

    host AXI4-Lite -> rk_cmac_job_control -> rk_cmac_nvdla_dma(OUTPUT_FP16=0)
        -> rk_cmac_profile(OUTPUT_FP16=0)
        -> operand front / address walker (OUTPUT_FP32=1)
        -> CMAC groups + CACC
        -> rk_cmac_output_fp32
        -> rk_cmac_axi_mem -> AXI4 memory adapter -> memory model

The bench compares the complete 4096-byte output BO, checks the result
registers, and pins the negative paths (memory admission, wrong body amount,
premature ACK, read-only writes). No hardware, no Vivado, no bitstream.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNNER = Path(__file__).resolve()
TB = ROOT / 'tests/cmac/tb_cmac_gemm_fp32_axi.sv'
DONOR = ROOT / 'rtl/vendor/nvdla'
DONOR_SOURCES = [
    'compat/nv_assert_never.v', 'compat/nv_assert_no_x.v', 'NV_DW_lsd.v',
    'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
    'NV_NVDLA_CACC_CALC_fp_48b.v', 'HLS_fp32_to_fp16.v',
]
# Both output tails are listed so one source list serves both parameter
# choices; only the selected generate branch is elaborated.
RTL = [
    'rtl/rk_cmac_profile.sv', 'rtl/rk_cmac_address.sv', 'rtl/rk_cmac_reader.sv',
    'rtl/rk_cmac_operand_front.sv',
    'rtl/cmac/rk_nvdla_cmac_group.sv', 'rtl/cmac/rk_nvdla_cacc.sv',
    'rtl/cmac/rk_nvdla_fp32_to_fp16.sv', 'rtl/cmac/rk_cmac_writer.sv',
    'rtl/cmac/rk_cmac_output_nvdla.sv', 'rtl/cmac/rk_cmac_fp32_writer.sv',
    'rtl/cmac/rk_cmac_output_fp32.sv', 'rtl/cmac/rk_nvdla_cmac_pipe.sv',
    'rtl/cmac/rk_cmac_nvdla_core.sv', 'rtl/cmac/rk_cmac_nvdla_dma.sv',
    'rtl/cmac/rk_cmac_job_control.sv',
    # The endpoint presents AXI4 on its memory master; its own halfword adapter
    # is that direction. The board bridge is the reverse direction.
    'rtl/cmac/rk_cmac_axi_mem.sv', 'rtl/cmac/rk_cmac_nvdla_axi.sv',
    'rtl/rk_axi_mem_slave.sv',
]
FIXTURES = ROOT / 'tests/conv/fixtures'
CASES = {
    'gemm_m2_n2_k1': {'rows': 2, 'ai': 32, 'ao': 32, 'k': 1, 'tolerance': 0.0},
    'gemm_m1_n16_k32': {'rows': 1, 'ai': 32, 'ao': 32, 'k': 32, 'tolerance': 0.1},
    'gemm_m2_n16_k32': {'rows': 2, 'ai': 32, 'ao': 32, 'k': 32, 'tolerance': 0.1},
    'gemm_m4_n32_k64': {'rows': 4, 'ai': 64, 'ao': 32, 'k': 64, 'tolerance': 0.1},
}
# The DMA fetches the 45-QWORD body plus four CMAC tail QWORDs.
FETCH_BYTES = 392
OUTPUT_BYTES = 4096
MODES = {
    0: {'kind': 'job', 'starts': 1},
    1: {'kind': 'reject', 'starts': 0},
    2: {'kind': 'reject', 'starts': 1},
    3: {'kind': 'reject', 'starts': 0},
    4: {'kind': 'reject', 'starts': 0},
}
PASS_RE = re.compile(
    r'^PASS CMAC_GEMM_FP32_AXI mode=(\d+) reads=(\d+) writes=(\d+) '
    r'bo_bytes=(\d+)$')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def tool_version(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=30)
    text = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(f'tool version command failed: {argv}: {text}')
    return text.splitlines()[0] if text else 'unknown'


def prepare(case: str, directory: Path) -> dict:
    """Write the bench fixture. The three value32 fields are relocated from the
    capture's own patch list; no other byte is touched."""
    fixture = FIXTURES / case
    manifest = json.loads((fixture / 'manifest.json').read_text())
    for name, record in manifest['files'].items():
        path = fixture / name
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError(f'{case}: fixture file changed: {name}')
    spec = dict(CASES[case])
    addresses = manifest['command_stream']['addresses']
    if addresses['input'] % 2 or addresses['weight'] % 2 or addresses['output'] % 4:
        raise ValueError(f'{case}: captured BO addresses are not naturally aligned')
    raw = bytearray((fixture / 'regcmd.bin').read_bytes())
    if len(raw) < FETCH_BYTES:
        raise ValueError(f'{case}: command stream shorter than the fetched body')
    job = json.loads((fixture / 'job.json').read_text())
    vendor = {'input': 0x10000000, 'weight': 0x20000000,
              'out': 0x30000000, 'output': 0x30000000}
    for patch in job['patches']:
        if patch.get('kind') != 'value32':
            raise ValueError(f'{case}: unexpected patch kind {patch.get("kind")}')
        offset = patch['regcmd_index'] * 8
        current = struct.unpack_from('<Q', bytes(raw), offset)[0]
        if (current >> 16) & 0xFFFFFFFF != vendor[patch['buffer']]:
            raise ValueError(f'{case}: field {patch["regcmd_index"]} changed '
                             f'from the vendor default')
        raw[offset + 2:offset + 6] = addresses[patch['buffer']].to_bytes(4, 'little')
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'command.hex').write_text(
        ''.join(f'{v:02x}\n' for v in raw[:FETCH_BYTES]))
    (directory / 'input.hex').write_text(
        ''.join(f'{v:04x}\n' for v in struct.unpack(f'<{len((fixture / "input.bin").read_bytes())//2}H', (fixture / "input.bin").read_bytes())))
    (directory / 'weight.hex').write_text(
        ''.join(f'{v:04x}\n' for v in struct.unpack(f'<{len((fixture / "weight.bin").read_bytes())//2}H', (fixture / "weight.bin").read_bytes())))
    captured = (fixture / 'device_out.bin').read_bytes()
    if len(captured) != OUTPUT_BYTES:
        raise ValueError(f'{case}: capture is not a full output BO')
    (directory / 'expected.hex').write_text(
        ''.join(f'{v:02x}\n' for v in captured))
    spec.update(input_base=addresses['input'], weight_base=addresses['weight'],
                output_base=addresses['output'],
                input_halfwords=(fixture / 'input.bin').stat().st_size // 2,
                weight_halfwords=(fixture / 'weight.bin').stat().st_size // 2)
    return spec


def run_mode(simulator: str, case: str, mode: int, outdir: Path,
             keep_build: bool) -> dict:
    spec = prepare(case, outdir / 'fixture')
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    sources = [str(DONOR / n) for n in DONOR_SOURCES] + \
              [str(ROOT / n) for n in RTL] + [str(TB)]
    common = [f'MODE={mode}', f'TOLERANCE_ABS={spec["tolerance"]}',
              f'ROWS={spec["rows"]}', f'AO={spec["ao"]}',
              # Deep shapes take far longer to sweep; the bench polls status
              # and the harness allows a longer wall clock.
              f'POLL_LIMIT={200000 if spec["k"] == 1 else 2000000}']
    binary = outdir / ('sim.vvp' if simulator == 'iverilog' else 'obj_dir')
    if simulator == 'iverilog':
        argv = [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-Itests',
                '-s', 'tb_cmac_gemm_fp32_axi',
                *[f'-Ptb_cmac_gemm_fp32_axi.{c}' for c in common],
                '-o', str(binary), *sources]
        prefix = [runtime, str(binary)]
    else:
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', '--timescale-override', '1ns/1ps',
                '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-Itests',
                '--top-module', 'tb_cmac_gemm_fp32_axi', '--Mdir', str(binary),
                '-o', 'sim', *[f'-G{c}' for c in common], *sources]
        prefix = [str(binary / 'sim')]
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'case': case,
        'mode': mode, 'simulator': simulator,
        'python_version': platform.python_version(),
        'output_fp16': False, 'tolerance_abs': spec['tolerance'],
        'scope': ('Frozen conv-gemm-vendor GEMM job through the host-drivable '
                  'AXI endpoint with the FP32 output variant; complete '
                  '4096-byte output BO compared. Simulation only.'),
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'source_hashes_before': {str(p.relative_to(ROOT)): sha(p)
                                 for p in [*[ROOT / n for n in RTL], TB, RUNNER,
                                           FIXTURES / case / 'manifest.json']},
    }
    try:
        result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                                check=False, timeout=1800)
        text = result.stdout + result.stderr
        (outdir / 'compile.log').write_text(text)
        if result.returncode or re.search(r'%Error', text):
            raise RuntimeError(f'compile failed: {text[-4000:]}')
        report['tool_version'] = tool_version(
            [compiler, '--version'] if simulator == 'verilator' else [compiler, '-V'])
        result = subprocess.run(
            prefix + [f'+FIXTURE={outdir / "fixture"}', f'+MODE={mode}'],
            cwd=ROOT, text=True, capture_output=True, check=False,
            # Deep shapes walk more address space; this is a wall-clock cap,
            # not a correctness signal.
            timeout=7200 if spec['k'] == 1 else 18000)
        output = result.stdout + result.stderr
        (outdir / 'run.log').write_text(output)
        matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
                   if line.startswith('PASS CMAC_GEMM_FP32_AXI')]
        if result.returncode or len(matches) != 1:
            raise RuntimeError(f'mode {mode} failed: {output[-4000:]}')
        counts = tuple(int(matches[0].group(i)) for i in range(1, 5))
        if counts[0] != mode or counts[3] != OUTPUT_BYTES:
            raise RuntimeError(f'mode {mode} contract differs: {counts}')
        if mode == 0 and spec['k'] == 1:
            # Two halfword writes per output value, and the complete capture
            # byte-compared inside the bench. A deeper shape walks its output
            # with the same address rule, so the count still holds.
            if counts[2] != spec['rows'] * spec['ao'] * 2:
                raise RuntimeError(f'mode 0 write count {counts[2]} is not two '
                                   f'per output value')
        tolerance_lines = [line for line in output.splitlines()
                           if line.startswith('TOLERANCE CMAC_GEMM_FP32_AXI')]
        if tolerance_lines:
            m = re.search(r'worst_abs=([0-9.]+) limit=([0-9.]+)', tolerance_lines[0])
            if not m:
                raise RuntimeError('unrecognized tolerance report')
            if float(m.group(1)) > float(m.group(2)):
                raise RuntimeError('measured deviation exceeds the declared bound')
            report['worst_abs'] = float(m.group(1))
        after = {name: sha(ROOT / name) for name in report['source_hashes_before']}
        if after != report['source_hashes_before']:
            raise RuntimeError('RTL or fixture changed during the run')
        report.update(status='PASS', finished_utc=utc_now(),
                      counts=dict(mode=counts[0], reads=counts[1],
                                  writes=counts[2], bo_bytes=counts[3]),
                      source_hashes_after=after)
    except Exception as exc:
        report.update(status='FAIL', failure=str(exc))
        raise
    finally:
        if not keep_build:
            if binary.is_dir():
                shutil.rmtree(binary)
            else:
                binary.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                       sort_keys=True) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=tuple(CASES), action='append', default=None)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'),
                        default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    cases = args.case or list(CASES)
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    failures = 0
    for case in cases:
        for simulator in simulators:
            base = ROOT / 'build/cmac-gemm-fp32-axi' / f'{simulator}-{stamp}-{case}'
            ok = True
            for mode in MODES:
                try:
                    run_mode(simulator, case, mode, base / f'mode-{mode}',
                             args.keep_build)
                except Exception as exc:
                    print(f'FAIL {case} mode {mode} {simulator}: {exc}',
                          file=sys.stderr)
                    failures += 1
                    ok = False
                    break
            if ok:
                print(f'ALL {len(MODES)} modes PASS: {case} {simulator}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
