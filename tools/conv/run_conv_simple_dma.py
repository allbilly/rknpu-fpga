#!/usr/bin/env python3
"""Replay the conv-simple 52-QWORD descriptor endpoint in both simulators.

Each mode runs the endpoint forward of the frozen fixture operands through a
serialized 16-bit memory model. Modes 0 and 7 compare the complete output BO
against the captured device bytes.
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
TB = ROOT / 'tests/conv/tb_conv_simple_dma.sv'
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
    'rtl/cmac/rk_conv_output_atom.sv', 'rtl/cmac/rk_conv_simple_profile.sv',
    'rtl/cmac/rk_conv_3x3_valid_c4_front.sv', 'rtl/cmac/rk_conv_simple_core.sv',
    'rtl/cmac/rk_conv_simple_dma.sv',
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
}
MODES = {
    0: 'pass', 1: 'amount', 2: 'alignment', 3: 'aperture', 4: 'overlap',
    5: 'bus fault', 6: 'timeout', 7: 'repeat',
}
PASS_RE = re.compile(
    r'^PASS CONV_SIMPLE_DMA mode=(\d+) commands=(\d+) input_reads=(\d+) '
    r'weight_reads=(\d+) output_writes=(\d+) error_code=(\d+)$')


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


def load(case: str) -> tuple[Path, dict, bytes]:
    spec = CASES[case]
    fixture = ROOT / 'tests/conv/fixtures' / case
    manifest = json.loads((fixture / 'manifest.json').read_text())
    job = json.loads((fixture / 'job.json').read_text())
    if manifest['command_stream']['qwords'] != 52:
        raise ValueError(f'{case}: command length changed')
    if manifest['command_stream']['address_qwords'] != [18, 24, 32]:
        raise ValueError(f'{case}: relocation set changed')
    addresses = manifest['command_stream']['addresses']
    if addresses != {'input': 0x1000, 'weight': 0x2000,
                     'out': {'conv_simple_fp16_3x3_c4_h8_w8_oc16': 0x3000,
                             'conv_simple_fp16_5x5_c4_h8_w8_oc16': 0x4000,
                             'conv_simple_fp16_3x3_c16_h8_w8_oc32': 0x5000}[case]}:
        raise ValueError(f'{case}: captured BO placement changed: {addresses}')
    for name, record in manifest['files'].items():
        path = fixture / name
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError(f'{case}: fixture file changed: {name}')
    raw = bytearray((fixture / 'regcmd.bin').read_bytes())
    if len(raw) != 52 * 8:
        raise ValueError(f'{case}: raw stream is not 52 QWORDs')
    for patch in job['patches']:
        offset = patch['regcmd_index'] * 8
        raw[offset + 2:offset + 6] = addresses[patch['buffer']].to_bytes(4, 'little')
    return fixture, manifest, bytes(raw)


def write_hex(fixture: Path, patched: bytes, directory: Path, spec: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    halfwords = struct.unpack(f'<{len(patched)//2}H', patched)
    (directory / 'commands.hex').write_text(''.join(f'{w:04x}\n' for w in halfwords))
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
             keep_build: bool, trace: bool = False) -> dict:
    spec = CASES[case]
    fixture, manifest, patched = load(case)
    if outdir.exists():
        raise ValueError('mode directory already exists')
    outdir.mkdir(parents=True)
    hexdir = outdir / 'fixture-hex'
    write_hex(fixture, patched, hexdir, spec)
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    sources = [str(DONOR / n) for n in DONOR_SOURCES] + [str(ROOT / n) for n in RTL]
    common = [
        f'-Ptb_conv_simple_dma.PROFILE={spec["profile"]}',
        f'-Ptb_conv_simple_dma.MODE={mode}',
        f'-Ptb_conv_simple_dma.KH={spec["kh"]}',
        f'-Ptb_conv_simple_dma.KW={spec["kw"]}',
        f'-Ptb_conv_simple_dma.INPUT_CHANNELS={spec["in_c"]}',
        f'-Ptb_conv_simple_dma.KERNELS={spec["kernels"]}',
        f'-Ptb_conv_simple_dma.C1_BLOCKS={spec["c1_blocks"]}',
        f'-Ptb_conv_simple_dma.ALIGN_C={spec["align_c"]}',
        f'-Ptb_conv_simple_dma.PACK_C2={spec["pack_c2"]}',
        f'-Ptb_conv_simple_dma.CHUNK_LANES={spec["chunk_lanes"]}',
        f'-Ptb_conv_simple_dma.WEIGHT_HALFWORDS={spec["weight_halfwords"]}',
        f'-Ptb_conv_simple_dma.INPUT_HALFWORDS={spec["input_halfwords"]}',
        f'-Ptb_conv_simple_dma.OUTPUT_BYTES={spec["output_bytes"]}',
    ]
    if simulator == 'iverilog':
        binary = outdir / 'sim.vvp'
        argv = [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-s', 'tb_conv_simple_dma',
                *common, '-o', str(binary), *sources, str(TB)]
        prefix = [runtime, str(binary)]
    else:
        binary = outdir / 'obj_dir'
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', '--timescale-override', '1ns/1ps',
                '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', '-Irtl', '-Irtl/vendor/nvdla',
                '--top-module', 'tb_conv_simple_dma', '--Mdir', str(binary),
                '-o', 'sim',
                *[f'-G{a.split("=")[0][len('-Ptb_conv_simple_dma.'):]}={a.split("=", 1)[1]}'
                  for a in common if a.startswith('-Ptb')],
                *sources, str(TB)]
        prefix = [str(binary / 'sim')]
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(),
        'case': case, 'mode': mode, 'scenario': MODES[mode],
        'simulator': simulator,
        'fixture_manifest': str((fixture / 'manifest.json').relative_to(ROOT)),
        'patched_command_sha256': hashlib.sha256(patched).hexdigest(),
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
        report['tool_version'] = tool_version(
            [compiler, '--version'] if simulator == 'verilator' else [compiler, '-V'])
        extra = ['+TRACE=1'] if mode == 0 and trace else []
        result = subprocess.run(prefix + [f'+FIXTURE={hexdir}', f'+MODE={mode}'] + extra,
                                cwd=ROOT, text=True, capture_output=True,
                                check=False, timeout=900)
        output = result.stdout + result.stderr
        (outdir / 'run.log').write_text(output)
        matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
                   if line.startswith('PASS CONV_SIMPLE_DMA')]
        if result.returncode or len(matches) != 1:
            raise RuntimeError(f'mode {mode} failed: {output[-4000:]}')
        counts = tuple(int(matches[0].group(i)) for i in range(1, 7))
        if counts[0] != mode:
            raise RuntimeError(f'mode mismatch {counts}')
        report.update(status='PASS', finished_utc=utc_now(),
                      counts=dict(commands=counts[1], input_reads=counts[2],
                                  weight_reads=counts[3], output_writes=counts[4],
                                  error_code=counts[5]))
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
    parser.add_argument('--trace', action='store_true',
                        help='dump per-cycle endpoint state for mode 0')
    args = parser.parse_args()
    cases = args.case or list(CASES)
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    failures = 0
    for case in cases:
        for simulator in simulators:
            base = ROOT / 'build/conv-dma' / f'{simulator}-{stamp}-{CASES[case]["profile"]}'
            for mode in MODES:
                outdir = base / f'mode-{mode}'
                try:
                    report = run_mode(simulator, case, mode, outdir, args.keep_build, args.trace)
                except Exception as exc:
                    print(f'FAIL {case} mode {mode} {simulator}: {exc}', file=sys.stderr)
                    failures += 1
                    break
                if mode in (0, 7):
                    print(f'PASS {case} mode {mode} ({MODES[mode]}) {simulator}: '
                          f'complete output BO exact; report={outdir / "report.json"}')
            if not failures:
                print(f'ALL {len(MODES)} modes PASS: {case} {simulator}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
