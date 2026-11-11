#!/usr/bin/env python3
"""FP32 GEMM replay of a frozen `conv-gemm-vendor` fixture.

The job runs through the real datapath, with the FP32 output variant selected
at elaboration:

    raw 50-QWORD stream -> rk_cmac_nvdla_dma(OUTPUT_FP16=0)
        -> rk_cmac_profile(OUTPUT_FP16=0)   FP32 output register values
        -> rk_cmac_address(OUTPUT_FP32=1)   contiguous 4-byte output layout
        -> rk_nvdla_cmac_pipe(OUTPUT_FP16=0) CMAC groups + CACC
        -> rk_cmac_output_fp32              two halfwords per value, no convert

The comparison is the complete captured 4096-byte output BO. Out-of-window
writes are rejected by the model rather than absorbed, so the test also proves
the job wrote nowhere else.

Nothing here touches hardware, Vivado or a bitstream.
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
TB = ROOT / 'tests/cmac/tb_cmac_gemm_fp32.sv'
DONOR = ROOT / 'rtl/vendor/nvdla'
DONOR_SOURCES = [
    'compat/nv_assert_never.v', 'compat/nv_assert_no_x.v', 'NV_DW_lsd.v',
    'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
    'NV_NVDLA_CACC_CALC_fp_48b.v', 'HLS_fp32_to_fp16.v',
]
# Both output tails are included so one source list serves both parameter
# choices; only the selected generate branch is elaborated.
RTL = [
    'rtl/rk_cmac_profile.sv', 'rtl/rk_cmac_address.sv', 'rtl/rk_cmac_reader.sv',
    'rtl/rk_cmac_operand_front.sv',
    'rtl/cmac/rk_nvdla_cmac_group.sv', 'rtl/cmac/rk_nvdla_cacc.sv',
    'rtl/cmac/rk_nvdla_fp32_to_fp16.sv', 'rtl/cmac/rk_cmac_writer.sv',
    'rtl/cmac/rk_cmac_output_nvdla.sv', 'rtl/cmac/rk_cmac_fp32_writer.sv',
    'rtl/cmac/rk_cmac_output_fp32.sv', 'rtl/cmac/rk_nvdla_cmac_pipe.sv',
    'rtl/cmac/rk_cmac_nvdla_core.sv', 'rtl/cmac/rk_cmac_nvdla_dma.sv',
]
FIXTURES = ROOT / 'tests/conv/fixtures'
CASES = {
    # `k` decides whether byte-exactness is even achievable: with a single
    # product per output value there is no accumulation-order freedom, so the
    # compare is exact. Deeper shapes carry the family's declared tolerance,
    # because the NVDLA CACC and the device DPU round the accumulator
    # differently.
    'gemm_m2_n2_k1': {'rows': 2, 'ai': 32, 'ao': 32, 'k': 1, 'tolerance': 0.0},
    'gemm_m1_n16_k32': {'rows': 1, 'ai': 32, 'ao': 32, 'k': 32, 'tolerance': 0.1},
    'gemm_m2_n16_k32': {'rows': 2, 'ai': 32, 'ao': 32, 'k': 32, 'tolerance': 0.1},
    'gemm_m4_n32_k64': {'rows': 4, 'ai': 64, 'ao': 32, 'k': 64, 'tolerance': 0.1},
}
# The DMA fetches the 45-QWORD body plus the four CMAC tail QWORDs.
FETCH_BYTES = 392
OUTPUT_BYTES = 4096
PASS_RE = re.compile(
    r'^PASS CMAC_GEMM_FP32 rows=(\d+) ai=(\d+) ao=(\d+) reads=(\d+) '
    r'writes=(\d+) bo_bytes=(\d+) worst_abs=([0-9.]+) tolerance=([0-9.]+)$')


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


def hex_words(payload: bytes, width: int) -> list[str]:
    """Little-endian hex lines of `width` bytes (2 or 4)."""
    if width == 2:
        return [f'{v:04x}' for v in struct.unpack(f'<{len(payload)//2}H', payload)]
    if width == 4:
        return [f'{v:08x}' for v in struct.unpack(f'<{len(payload)//4}I', payload)]
    raise ValueError('unsupported width')


def prepare(case: str, directory: Path) -> dict:
    fixture = FIXTURES / case
    manifest = json.loads((fixture / 'manifest.json').read_text())
    for name, record in manifest['files'].items():
        path = fixture / name
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError(f'{case}: fixture file changed: {name}')
    spec = dict(CASES[case])
    # The command BO is relocatable: the capture's own buffer bases are written
    # into the three declared value32 fields, exactly as the capture's own
    # patch list records (`before 0x10000000 -> after 0x1000`). No other byte
    # is touched.
    raw = bytearray((fixture / 'regcmd.bin').read_bytes())
    if len(raw) < FETCH_BYTES:
        raise ValueError(f'{case}: command stream shorter than the fetched body')
    addresses = manifest['command_stream']['addresses']
    if addresses['input'] % 2 or addresses['weight'] % 2 or addresses['output'] % 4:
        raise ValueError(f'{case}: captured BO addresses are not naturally aligned')
    job = json.loads((fixture / 'job.json').read_text())
    for patch in job['patches']:
        if patch.get('kind') != 'value32':
            raise ValueError(f'{case}: unexpected patch kind {patch.get("kind")}')
        expected_before = {'input': 0x10000000, 'weight': 0x20000000,
                           'out': 0x30000000, 'output': 0x30000000}.get(patch['buffer'])
        offset = patch['regcmd_index'] * 8
        current = struct.unpack_from('<Q', bytes(raw), offset)[0]
        if (current >> 16) & 0xFFFFFFFF != expected_before:
            raise ValueError(f'{case}: field {patch["regcmd_index"]} changed '
                             f'from the vendor default')
        raw[offset + 2:offset + 6] = \
            addresses[patch['buffer']].to_bytes(4, 'little')
    spec['input_base'] = addresses['input']
    spec['weight_base'] = addresses['weight']
    spec['output_base'] = addresses['out'] if 'out' in addresses else addresses['output']

    directory.mkdir(parents=True, exist_ok=True)
    # Byte-per-line hex for the command BO: the DMA fetches QWORD-aligned
    # halfwords, and the bench indexes them as bytes.
    (directory / 'command.hex').write_text(
        ''.join(f'{v:02x}\n' for v in raw[:FETCH_BYTES]))
    (directory / 'input.hex').write_text(
        ''.join(f'{w}\n' for w in hex_words((fixture / 'input.bin').read_bytes(), 2)))
    (directory / 'weight.hex').write_text(
        ''.join(f'{w}\n' for w in hex_words((fixture / 'weight.bin').read_bytes(), 2))
    )
    captured = (fixture / 'device_out.bin').read_bytes()
    # The capture defines only the meaningful prefix; the rest of the 4096-byte
    # BO must stay zero, so pad it and compare the whole BO.
    padded = captured + b'\0' * (OUTPUT_BYTES - len(captured))
    (directory / 'expected.hex').write_text(
        ''.join(f'{v:02x}\n' for v in padded))
    return {
        'case': case, 'rows': spec['rows'], 'ai': spec['ai'], 'ao': spec['ao'],
        'k': spec['k'], 'tolerance': spec['tolerance'],
        'input_base': spec['input_base'], 'weight_base': spec['weight_base'],
        'output_base': spec['output_base'],
        'input_halfwords': (fixture / 'input.bin').stat().st_size // 2,
        'weight_halfwords': (fixture / 'weight.bin').stat().st_size // 2,
        'captured_bytes': len(captured),
        'output_sha256': sha(fixture / 'device_out.bin'),
    }


def run_case(simulator: str, case: str, outdir: Path, keep_build: bool) -> dict:
    spec = prepare(case, outdir / 'fixture')
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    sources = [str(DONOR / n) for n in DONOR_SOURCES] + \
              [str(ROOT / n) for n in RTL] + [str(TB)]
    common = [
        'START_ADDRESS=0', 'AMOUNT=45',
        f'ROWS={spec["rows"]}', f'AI={spec["ai"]}', f'AO={spec["ao"]}',
        f'INPUT_BASE={spec["input_base"]}',
        f'WEIGHT_BASE={spec["weight_base"]}',
        f'OUTPUT_BASE={spec["output_base"]}',
        f'INPUT_HALFWORDS={spec["input_halfwords"]}',
        f'WEIGHT_HALFWORDS={spec["weight_halfwords"]}',
        f'OUTPUT_BYTES={OUTPUT_BYTES}',
        f'TOLERANCE_ABS={spec["tolerance"]}',
    ]
    binary = outdir / ('sim.vvp' if simulator == 'iverilog' else 'obj_dir')
    if simulator == 'iverilog':
        argv = [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-Itests',
                '-s', 'tb_cmac_gemm_fp32',
                *[f'-Ptb_cmac_gemm_fp32.{c}' for c in common],
                '-o', str(binary), *sources]
        prefix = [runtime, str(binary)]
    else:
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', '--timescale-override', '1ns/1ps',
                '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-Itests',
                '--top-module', 'tb_cmac_gemm_fp32', '--Mdir', str(binary),
                '-o', 'sim', *[f'-G{c}' for c in common], *sources]
        prefix = [str(binary / 'sim')]
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'case': case,
        'simulator': simulator, 'python_version': platform.python_version(),
        'fixture': spec,
        'scope': ('Frozen conv-gemm-vendor GEMM job through the real CMAC/CACC '
                  'datapath with the FP32 output variant; complete 4096-byte '
                  'output BO compared. Simulation only.'),
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
        result = subprocess.run(prefix + [f'+FIXTURE={outdir / "fixture"}'],
                                cwd=ROOT, text=True, capture_output=True,
                                check=False, timeout=3600)
        output = result.stdout + result.stderr
        (outdir / 'run.log').write_text(output)
        matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
                   if line.startswith('PASS CMAC_GEMM_FP32')]
        if result.returncode or len(matches) != 1:
            raise RuntimeError(f'{case} failed: {output[-4000:]}')
        counts = tuple(int(matches[0].group(i)) for i in range(1, 7))
        worst_abs = float(matches[0].group(7))
        reported_tolerance = float(matches[0].group(8))
        if counts[0] != spec['rows'] or counts[1] != spec['ai'] or counts[2] != spec['ao']:
            raise RuntimeError(f'{case} shape differs: {counts[:3]}')
        if counts[5] != OUTPUT_BYTES:
            raise RuntimeError(f'{case} BO size differs: {counts[5]}')
        # Exactly two halfwords per logical output element.
        if counts[4] != spec['rows'] * spec['ao'] * 2:
            raise RuntimeError(f'{case} write count {counts[4]} is not 2 per value')
        if abs(reported_tolerance - spec['tolerance']) > 1e-9:
            raise RuntimeError(f'{case} bench tolerance differs from the fixture')
        if worst_abs > spec['tolerance']:
            raise RuntimeError(f'{case} worst abs {worst_abs} exceeds {spec["tolerance"]}')
        after = {name: sha(ROOT / name) for name in report['source_hashes_before']}
        if after != report['source_hashes_before']:
            raise RuntimeError('RTL or fixture changed during the run')
        report.update(status='PASS', finished_utc=utc_now(),
                      counts=dict(rows=counts[0], ai=counts[1], ao=counts[2],
                                  reads=counts[3], writes=counts[4],
                                  bo_bytes=counts[5], worst_abs=worst_abs,
                                  tolerance=spec['tolerance'], k=spec['k']),
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
            outdir = ROOT / 'build/cmac-gemm-fp32' / f'{simulator}-{stamp}-{case}'
            try:
                run_case(simulator, case, outdir, args.keep_build)
            except Exception as exc:
                print(f'FAIL {case} {simulator}: {exc}', file=sys.stderr)
                failures += 1
                continue
            print(f'PASS {case} {simulator}: complete 4096-byte BO; '
                  f'report={outdir / "report.json"}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
