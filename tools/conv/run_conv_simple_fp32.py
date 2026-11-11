#!/usr/bin/env python3
"""Replay the frozen FP32 conv-simple capture through real RTL.

This is the last data-only conv-simple fixture: its device output is FP32, so
none of the FP16 writers could ever reproduce it. The job now runs end to end
with the FP32 output variant selected at elaboration:

    raw 52-QWORD stream -> rk_conv_simple_dma(PROFILE=3, OUTPUT_FP16=0)
        -> decoder profile 3 (the capture's own register template)
        -> spatial front (1x1, C4, H8W8, OC16)
        -> CMAC/CACC arithmetic
        -> rk_conv_output_c1c2_fp32 (RTL placement into the captured
                                     [c1][pixel][c2=4] surface)

The comparison covers the complete 4096-byte captured output BO.
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
TB = ROOT / 'tests/conv/tb_conv_simple_fp32.sv'
CASE = 'conv_simple_fp16_1x1_c4_h8_w8_oc16'
PROFILE = 3
FIXTURE = ROOT / 'tests/conv/fixtures' / CASE
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
    'rtl/cmac/rk_cmac_fp32_writer.sv', 'rtl/cmac/rk_cmac_output_fp32.sv',
    'rtl/cmac/rk_cmac_frame_output.sv', 'rtl/cmac/rk_conv_output_atom.sv',
    'rtl/cmac/rk_conv_output_c1c2_fp32.sv', 'rtl/cmac/rk_cmac_rw_arbiter.sv',
    'rtl/cmac/rk_conv_simple_profile.sv', 'rtl/cmac/rk_conv_3x3_valid_c4_front.sv',
    'rtl/cmac/rk_conv_simple_core.sv', 'rtl/cmac/rk_conv_simple_dma.sv',
]
# The capture's oracle is float64 rounded to float32; this RTL accumulates in
# the NVDLA CACC, so the bound is absolute and explicit, and the measured
# deviation is recorded in every receipt.
TOLERANCE_ABS = 0.001
PASS_RE = re.compile(
    r'^PASS CONV_SIMPLE_FP32 profile=(\d+) bo_bytes=(\d+) writes=(\d+) '
    r'differing_words=(\d+) worst_abs=([0-9.]+) tolerance=([0-9.]+)$')


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


def load() -> tuple[dict, bytes]:
    manifest = json.loads((FIXTURE / 'manifest.json').read_text())
    if manifest['case'] != CASE:
        raise ValueError('fixture identity mismatch')
    for name, record in manifest['files'].items():
        path = FIXTURE / name
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError(f'fixture file changed: {name}')
    job = json.loads((FIXTURE / 'job.json').read_text())
    if [p['regcmd_index'] for p in job['patches']] != [18, 24, 32]:
        raise ValueError('relocation set changed')
    addresses = manifest['command_stream']['addresses']
    raw = bytearray((FIXTURE / 'regcmd.bin').read_bytes())
    if len(raw) != 52 * 8:
        raise ValueError('command stream is not 52 QWORDs')
    # The frozen table zeroes the three address fields; a non-zero value means
    # the fixture was mutated and the relocation is no longer trustworthy.
    for patch in job['patches']:
        offset = patch['regcmd_index'] * 8
        current = struct.unpack_from('<Q', bytes(raw), offset)[0]
        if (current >> 16) & 0xFFFFFFFF != 0:
            raise ValueError(f'{patch["buffer"]}: address field is not the '
                             f'frozen zero placeholder')
        raw[offset + 2:offset + 6] = \
            addresses[patch['buffer']].to_bytes(4, 'little')
    return manifest, bytes(raw)


def write_fixture(directory: Path, patched: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'command.hex').write_text(
        ''.join(f'{v:08x}\n' for v in struct.unpack('<104I', patched)))
    for source, target, halfwords in (('input.bin', 'input.hex', 256),
                                      ('weight.bin', 'weight.hex', 128),
                                      ('device_out.bin', 'expected.hex', None)):
        payload = (FIXTURE / source).read_bytes()
        if halfwords is not None:
            words = struct.unpack(f'<{halfwords}H', payload)
            (directory / target).write_text(
                ''.join(f'{w:04x}\n' for w in words))
        else:
            # The FP32 expectation is 1024 little-endian words; the bench reads
            # it as 32-bit values.
            words = struct.unpack(f'<{len(payload)//4}I', payload)
            (directory / target).write_text(
                ''.join(f'{w:08x}\n' for w in words))


def run(simulator: str, outdir: Path, keep_build: bool) -> dict:
    manifest, patched = load()
    outdir.mkdir(parents=True)
    write_fixture(outdir / 'fixture', patched)
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    sources = [str(DONOR / n) for n in DONOR_SOURCES] + \
              [str(ROOT / n) for n in RTL] + [str(TB)]
    common = [f'PROFILE={PROFILE}', 'OUTPUT_FP16=0', 'INPUT_H=8', 'INPUT_W=8',
              'KH=1', 'KW=1', 'INPUT_CHANNELS=4', 'KERNELS=8', 'C1_BLOCKS=2',
              'ALIGN_C=8', 'PACK_C2=4', 'CHUNK_LANES=16',
              f'TOLERANCE_ABS={TOLERANCE_ABS}']
    binary = outdir / ('sim.vvp' if simulator == 'iverilog' else 'obj_dir')
    if simulator == 'iverilog':
        argv = [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-Itests',
                '-s', 'tb_conv_simple_fp32',
                *[f'-Ptb_conv_simple_fp32.{c}' for c in common],
                '-o', str(binary), *sources]
        prefix = [runtime, str(binary)]
    else:
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', '--timescale-override', '1ns/1ps',
                '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-Itests',
                '--top-module', 'tb_conv_simple_fp32', '--Mdir', str(binary),
                '-o', 'sim', *[f'-G{c}' for c in common], *sources]
        prefix = [str(binary / 'sim')]
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'case': CASE,
        'profile': PROFILE, 'simulator': simulator,
        'python_version': platform.python_version(),
        'output_sha256': sha(FIXTURE / 'device_out.bin'),
        'scope': ('Frozen FP32 conv-simple capture through the real conv datapath '
                  'with the captured [c1][pixel][c2] FP32 output stage; '
                  'complete 4096-byte BO '
                  'compared. Simulation only.'),
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'source_hashes_before': {str(p.relative_to(ROOT)): sha(p)
                                 for p in [*[ROOT / n for n in RTL], TB, RUNNER,
                                           FIXTURE / 'manifest.json']},
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
                   if line.startswith('PASS CONV_SIMPLE_FP32')]
        if result.returncode or len(matches) != 1:
            raise RuntimeError(f'replay failed: {output[-4000:]}')
        counts = tuple(int(matches[0].group(i)) for i in range(1, 4))
        differing = int(matches[0].group(4))
        worst_abs = float(matches[0].group(5))
        reported_tolerance = float(matches[0].group(6))
        if counts[0] != PROFILE or counts[1] != 4096:
            raise RuntimeError(f'replay contract differs: {counts}')
        if counts[2] != 1024 * 2:
            raise RuntimeError(f'write count {counts[2]} is not two per value')
        if abs(reported_tolerance - TOLERANCE_ABS) > 1e-12:
            raise RuntimeError('bench tolerance differs from the runner')
        if worst_abs > TOLERANCE_ABS:
            raise RuntimeError(f'worst abs {worst_abs} exceeds {TOLERANCE_ABS}')
        after = {name: sha(ROOT / name) for name in report['source_hashes_before']}
        if after != report['source_hashes_before']:
            raise RuntimeError('RTL or fixture changed during the run')
        report.update(status='PASS', finished_utc=utc_now(),
                      counts=dict(profile=counts[0], bo_bytes=counts[1],
                                  writes=counts[2], differing_words=differing,
                                  worst_abs=worst_abs, tolerance=TOLERANCE_ABS),
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
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'),
                        default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    failures = 0
    for simulator in simulators:
        outdir = ROOT / 'build/conv-simple-fp32' / f'{simulator}-{stamp}'
        try:
            run(simulator, outdir, args.keep_build)
        except Exception as exc:
            print(f'FAIL {simulator}: {exc}', file=sys.stderr)
            failures += 1
            continue
        print(f'PASS {simulator}: complete 4096-byte BO; '
              f'report={outdir / "report.json"}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
