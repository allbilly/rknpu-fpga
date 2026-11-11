#!/usr/bin/env python3
"""Host-drivable AXI-Lite endpoint replay for one frozen conv-simple profile.

Eight modes exercise the transport page end to end: full job, incomplete
descriptor, wrong amount, premature acknowledge, read-only writes, submit while
active, two sequential jobs, and memory-not-ready. Modes 0, 5 and 6 compare the
complete output BO against the frozen device capture.
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
TB = ROOT / 'tests/conv/tb_conv_simple_axi.sv'
DONOR = ROOT / 'rtl/vendor/nvdla'
DONOR_SOURCES = [
    'compat/nv_assert_never.v', 'compat/nv_assert_no_x.v', 'NV_DW_lsd.v',
    'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
    'NV_NVDLA_CACC_CALC_fp_48b.v', 'HLS_fp32_to_fp16.v',
]
RTL = [
    'rtl/cmac/rk_cmac_fp16_cell.sv', 'rtl/cmac/rk_cmac_fp16_array.sv',
    'rtl/cmac/rk_nvdla_cacc.sv', 'rtl/cmac/rk_cacc_fp16_array.sv',
    'rtl/cmac/rk_cmac_cacc_fp16_array.sv', 'rtl/cmac/rk_nvdla_fp32_to_fp16.sv',
    'rtl/cmac/rk_cmac_writer.sv', 'rtl/cmac/rk_cmac_output_nvdla.sv',
    'rtl/cmac/rk_cmac_frame_output.sv', 'rtl/cmac/rk_cmac_rw_arbiter.sv',
    'rtl/cmac/rk_conv_output_atom.sv',
    'rtl/cmac/rk_cmac_fp32_writer.sv', 'rtl/cmac/rk_cmac_output_fp32.sv',
    'rtl/cmac/rk_conv_output_c1c2_fp32.sv', 'rtl/cmac/rk_conv_simple_profile.sv',
    'rtl/cmac/rk_conv_3x3_valid_c4_front.sv', 'rtl/cmac/rk_frame_stage.sv',
    'rtl/cmac/rk_conv_simple_core.sv',
    'rtl/cmac/rk_conv_simple_dma.sv', 'rtl/cmac/rk_conv_simple_axi.sv',
]
CASES = {
    'conv_simple_fp16_3x3_c4_h8_w8_oc16': dict(
        profile=0, kh=3, kw=3, in_c=4, kernels=8, c1_blocks=2, align_c=8,
        pack_c2=4, chunk_lanes=16, weight_halfwords=1152,
        input_halfwords=256, output_bytes=1152),
    'conv_simple_fp16_5x5_c4_h8_w8_oc16': dict(
        profile=1, kh=5, kw=5, in_c=4, kernels=8, c1_blocks=2, align_c=8,
        pack_c2=4, chunk_lanes=16, weight_halfwords=3200,
        input_halfwords=256, output_bytes=512),
    'conv_simple_fp16_3x3_c16_h8_w8_oc32': dict(
        profile=2, kh=3, kw=3, in_c=16, kernels=8, c1_blocks=4, align_c=16,
        pack_c2=8, chunk_lanes=16, weight_halfwords=4608,
        input_halfwords=1024, output_bytes=2304),
    # FP32 output. Byte-exactness is not available here: the capture's oracle
    # is float64 rounded to float32 while this RTL accumulates in the NVDLA
    # CACC, so the measured absolute bound applies (see the standalone runner).
    'conv_simple_fp16_1x1_c4_h8_w8_oc16': dict(
        profile=3, kh=1, kw=1, in_c=4, kernels=8, c1_blocks=2, align_c=8,
        pack_c2=4, chunk_lanes=16, weight_halfwords=128,
        input_halfwords=256, output_bytes=4096,
        output_fp16=0, tolerance_abs=0.001),
}
# Expected per-mode start counts. Transactions are checked only where the mode
# completes a job; the exact totals depend on the profile's operand size, so
# they are derived from that profile's BO sizes at run time.
MODES = {
    0: {'kind': 'bo', 'starts': 1},
    1: {'kind': 'reject', 'starts': 0},
    2: {'kind': 'reject', 'starts': 1},
    3: {'kind': 'reject', 'starts': 0},
    4: {'kind': 'reject', 'starts': 0},
    5: {'kind': 'bo', 'starts': 1},
    6: {'kind': 'bo', 'starts': 2},
    7: {'kind': 'reject', 'starts': 0},
}
PASS_RE = re.compile(
    r'^PASS CONV_SIMPLE_AXI mode=(\d+) starts=(\d+) transactions=(\d+) '
    r'output_bytes=(\d+)$')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def path_key(path: Path) -> str:
    """Workspace-relative key for a tracked source, or the absolute path."""
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def tracked_sources(fixture: Path, manifest: dict) -> list[Path]:
    """Every file whose content this mode's compile/run depends on.

    The RTL and donor sources are compiled, the testbench and this runner are
    part of the measurement, and the fixture bytes are the numerical oracle.
    They are hashed before and after the run so a concurrent edit is reported
    as a failure instead of producing an unbound PASS.
    """
    return ([DONOR / name for name in DONOR_SOURCES] +
            [ROOT / name for name in RTL] +
            [TB, RUNNER, fixture / 'manifest.json'] +
            [fixture / name for name in manifest['files']])


def tool_version(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=30)
    text = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(f'tool version command failed: {argv}: {text}')
    return text.splitlines()[0] if text else 'unknown'


def load(case: str) -> tuple[Path, dict, bytes, dict]:
    spec = CASES[case]
    fixture = ROOT / 'tests/conv/fixtures' / case
    manifest = json.loads((fixture / 'manifest.json').read_text())
    job = json.loads((fixture / 'job.json').read_text())
    if manifest['command_stream']['qwords'] != 52:
        raise ValueError(f'{case}: command length changed')
    if manifest['command_stream']['address_qwords'] != [18, 24, 32]:
        raise ValueError(f'{case}: relocation set changed')
    for name, record in manifest['files'].items():
        path = fixture / name
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError(f'{case}: fixture file changed: {name}')
    addresses = manifest['command_stream']['addresses']
    if not addresses:
        raise ValueError(f'{case}: fixture has no captured BO placement')
    raw = bytearray((fixture / 'regcmd.bin').read_bytes())
    if len(raw) != 52 * 8:
        raise ValueError(f'{case}: raw stream is not 52 QWORDs')
    for patch in job['patches']:
        offset = patch['regcmd_index'] * 8
        raw[offset + 2:offset + 6] = addresses[patch['buffer']].to_bytes(4, 'little')
    return fixture, manifest, bytes(raw), addresses


def write_hex(fixture: Path, patched: bytes, directory: Path, spec: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'commands.hex').write_text(
        ''.join(f'{v:04x}\n' for v in struct.unpack(f'<{len(patched)//2}H', patched)))
    for source, target, count in (
            ('input.bin', 'input.hex', spec['input_halfwords']),
            ('weight.bin', 'weight.hex', spec['weight_halfwords']),
            ('device_out.bin', 'expected.hex', spec['output_bytes'] // 2)):
        payload = (fixture / source).read_bytes()
        words = struct.unpack(f'<{len(payload)//2}H', payload)
        if len(words) != count:
            raise ValueError(f'{source}: expected {count} halfwords, got {len(words)}')
        (directory / target).write_text(''.join(f'{w:04x}\n' for w in words))


def run_mode(simulator: str, case: str, mode: int, outdir: Path,
             keep_build: bool) -> dict:
    spec = dict(CASES[case])
    fixture, manifest, patched, addresses = load(case)
    spec['input_base'] = addresses['input']
    spec['weight_base'] = addresses['weight']
    spec['output_base'] = addresses['out']
    outdir.mkdir(parents=True)
    hexdir = outdir / 'fixture-hex'
    write_hex(fixture, patched, hexdir, spec)
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    sources = [str(DONOR / n) for n in DONOR_SOURCES] + [str(ROOT / n) for n in RTL]
    tracked = tracked_sources(fixture, manifest)
    hashes_before = {path_key(path): sha(path) for path in tracked}
    common = [
        f'PROFILE={spec["profile"]}', f'MODE={mode}',
        f'KH={spec["kh"]}', f'KW={spec["kw"]}',
        f'INPUT_H=8', f'INPUT_W=8',
        f'INPUT_CHANNELS={spec["in_c"]}', f'KERNELS={spec["kernels"]}',
        f'C1_BLOCKS={spec["c1_blocks"]}', f'ALIGN_C={spec["align_c"]}',
        f'PACK_C2={spec["pack_c2"]}', f'CHUNK_LANES={spec["chunk_lanes"]}',
        f'WEIGHT_HALFWORDS={spec["weight_halfwords"]}',
        f'INPUT_HALFWORDS={spec["input_halfwords"]}',
        f'OUTPUT_BYTES={spec["output_bytes"]}',
        f'INPUT_BASE={spec["input_base"]}',
        f'WEIGHT_BASE={spec["weight_base"]}',
        f'OUTPUT_BASE={spec["output_base"]}',
        f'OUTPUT_FP16={spec.get("output_fp16", 1)}',
        f'TOLERANCE_ABS={spec.get("tolerance_abs", 0.0)}',
    ]
    binary = outdir / ('sim.vvp' if simulator == 'iverilog' else 'obj_dir')
    if simulator == 'iverilog':
        argv = [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-Itests', '-s', 'tb_conv_simple_axi',
                *[f'-Ptb_conv_simple_axi.{c}' for c in common],
                '-o', str(binary), *sources, str(TB)]
        prefix = [runtime, str(binary)]
    else:
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', '--timescale-override', '1ns/1ps',
                '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', '-Irtl', '-Irtl/vendor/nvdla',
                '-Itests', '--top-module', 'tb_conv_simple_axi', '--Mdir', str(binary),
                '-o', 'sim', *[f'-G{c}' for c in common], *sources, str(TB)]
        prefix = [str(binary / 'sim')]
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'case': case,
        'mode': mode, 'simulator': simulator,
        'tool_version': tool_version(
            [compiler, '--version'] if simulator == 'verilator' else [compiler, '-V']),
        'fixture_manifest': str((fixture / 'manifest.json').relative_to(ROOT)),
        'patched_command_sha256': hashlib.sha256(patched).hexdigest(),
        'output_fp16': bool(spec.get('output_fp16', 1)),
        'tolerance_abs': spec.get('tolerance_abs', 0.0),
        'source_hashes_before': hashes_before,
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
    }
    try:
        result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                                check=False, timeout=900)
        text = result.stdout + result.stderr
        (outdir / 'compile.log').write_text(text)
        if result.returncode or re.search(r'%Error', text):
            raise RuntimeError(f'compile failed: {text[-4000:]}')
        # Icarus needs real wall-clock time for the two-job modes at the
        # largest geometry (mode 5 alone is ~8 minutes); this is a cap, not a
        # correctness signal.
        result = subprocess.run(prefix + [f'+FIXTURE={hexdir}'], cwd=ROOT,
                                text=True, capture_output=True, check=False,
                                timeout=7200)
        output = result.stdout + result.stderr
        (outdir / 'run.log').write_text(output)
        matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
                   if line.startswith('PASS CONV_SIMPLE_AXI')]
        if result.returncode or len(matches) != 1:
            raise RuntimeError(f'mode {mode} failed: {output[-4000:]}')
        counts = tuple(int(matches[0].group(i)) for i in range(1, 5))
        if counts[0] != mode or counts[3] != spec['output_bytes']:
            raise RuntimeError(f'mode {mode} contract differs: {counts}')
        if counts[1] != MODES[mode]['starts']:
            raise RuntimeError(f'mode {mode} start count differs: {counts}')
        if 'transactions' in MODES[mode] and counts[2] != MODES[mode]['transactions']:
            raise RuntimeError(f'mode {mode} transaction count differs: {counts}')
        tolerance_lines = [line for line in output.splitlines()
                           if line.startswith('TOLERANCE CONV_SIMPLE_AXI')]
        if not spec.get('output_fp16', 1):
            # An FP32 comparison must report its measured deviation, and it must
            # stay inside the declared bound.
            if mode == 0 and len(tolerance_lines) != 1:
                raise RuntimeError(f'mode {mode} did not report its FP32 deviation')
            if tolerance_lines:
                import re as _re
                m = _re.search(r'worst_abs=([0-9.]+) limit=([0-9.]+)',
                               tolerance_lines[0])
                if not m:
                    raise RuntimeError('unrecognized tolerance report')
                if float(m.group(1)) > float(m.group(2)):
                    raise RuntimeError('FP32 deviation exceeds the declared bound')
                report['worst_abs'] = float(m.group(1))
        # A PASS is only evidence for the files that were compiled and run.
        # If any tracked source or fixture changed underneath this mode, the
        # receipt must serialize as a failure, never as a PASS.
        hashes_after = {path_key(path): sha(path) for path in tracked}
        if hashes_after != hashes_before:
            changed = sorted(name for name in hashes_before
                             if hashes_before[name] != hashes_after.get(name))
            raise RuntimeError(f'source/fixture changed during the run: {changed}')
        report.update(status='PASS', finished_utc=utc_now(),
                      source_hashes_after=hashes_after,
                      counts=dict(mode=counts[0], starts=counts[1],
                                  transactions=counts[2],
                                  output_bytes=counts[3]))
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
            base = ROOT / 'build/conv-axi' / f'{simulator}-{stamp}-{CASES[case]["profile"]}'
            ok = True
            for mode in MODES:
                try:
                    run_mode(simulator, case, mode, base / f'mode-{mode}', args.keep_build)
                except Exception as exc:
                    print(f'FAIL {case} mode {mode} {simulator}: {exc}', file=sys.stderr)
                    failures += 1
                    ok = False
                    break
            if ok:
                print(f'ALL {len(MODES)} modes PASS: {case} {simulator}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
