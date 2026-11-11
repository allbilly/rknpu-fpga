#!/usr/bin/env python3
"""Whole-BO replay of a frozen `conv-simple` capture in Icarus and Verilator.

Runs both simulators for one profile at a time; each run compares every output
halfword with the frozen device BO and checks the operand read order, traffic
count and frame metadata. Modes 1-7 are raw-profile rejections, 8-11 are
memory-fault controls, 12 is a second-stream rejection after a complete job.
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
TB = ROOT / 'tests/conv/tb_conv_simple.sv'
DONOR = ROOT / 'rtl/vendor/nvdla'
PROFILES = {
    0: {'case': 'conv_simple_fp16_3x3_c4_h8_w8_oc16', 'kh': 3, 'kw': 3,
        'in_c': 4, 'kernels': 8, 'c1_blocks': 2, 'align_c': 8, 'pack_c2': 4,
        'weight_halfwords': 1152, 'input_halfwords': 256, 'output_bytes': 1152},
    1: {'case': 'conv_simple_fp16_5x5_c4_h8_w8_oc16', 'kh': 5, 'kw': 5,
        'in_c': 4, 'kernels': 8, 'c1_blocks': 2, 'align_c': 8, 'pack_c2': 4,
        'weight_halfwords': 3200, 'input_halfwords': 256, 'output_bytes': 512},
    2: {'case': 'conv_simple_fp16_3x3_c16_h8_w8_oc32', 'kh': 3, 'kw': 3,
        'in_c': 16, 'kernels': 8, 'c1_blocks': 4, 'align_c': 16, 'pack_c2': 8,
        'weight_halfwords': 4608, 'input_halfwords': 1024, 'output_bytes': 2304},
}
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
]
FIXTURE_FILES = ('input.bin', 'weight.bin', 'expected.bin', 'regcmd.bin',
                 'device_out.bin', 'manifest.json', 'job.json', 'capture.json',
                 'oracle_recomputed.bin')
PASS_RE = re.compile(
    r'^PASS CONV_SIMPLE profile=(\d+) mode=(\d+) commands=(\d+) reads=(\d+) '
    r'writes=(\d+) frames=(\d+) output_bytes=(\d+)$')
MODES = {
    0: {'kind': 'pass'},
    1: {'error': 2}, 2: {'error': 1}, 3: {'error': 3}, 4: {'error': 2},
    5: {'error': 2}, 6: {'error': 4}, 7: {'error': 4},
    8: {'error': 5}, 9: {'error': 8}, 10: {'error': 5}, 11: {'error': 8},
    12: {'kind': 'second_stream'},
}


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


def load(profile: int) -> tuple[Path, dict, bytes]:
    spec = PROFILES[profile]
    fixture = ROOT / 'tests/conv/fixtures' / spec['case']
    manifest = json.loads((fixture / 'manifest.json').read_text())
    job = json.loads((fixture / 'job.json').read_text())
    if manifest['case'] != spec['case']:
        raise ValueError('fixture identity mismatch')
    if manifest['command_stream']['qwords'] != 52:
        raise ValueError('fixture command length changed')
    if manifest['command_stream']['address_qwords'] != [18, 24, 32]:
        raise ValueError('fixture relocations changed')
    for name, record in manifest['files'].items():
        path = fixture / name
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError(f'fixture file changed: {name}')
    addresses = manifest['command_stream'].get('buffers')
    if addresses not in (None, ['input', 'weight', 'out']):
        raise ValueError('fixture address buffers changed')
    if [p['regcmd_index'] for p in job['patches']] != [18, 24, 32]:
        raise ValueError('job relocations changed')
    raw = (fixture / 'regcmd.bin').read_bytes()
    if len(raw) != 52 * 8:
        raise ValueError('raw stream is not 52 QWORDs')
    addresses = manifest['command_stream'].get('addresses')
    if not addresses:
        raise ValueError('fixture has no captured BO placement')
    patched = bytearray(raw)
    for patch in job['patches']:
        offset = patch['regcmd_index'] * 8
        patched[offset + 2:offset + 6] = addresses[patch['buffer']].to_bytes(4, 'little')
    return fixture, manifest, bytes(patched)


def write_hex(fixture: Path, patched: bytes, directory: Path, spec: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for source, target, halfwords in (
            ('input.bin', 'input.hex', spec['input_halfwords']),
            ('weight.bin', 'weight.hex', spec['weight_halfwords']),
            ('expected.bin', 'expected.hex', None),
            ('device_out.bin', 'device.hex', None)):
        payload = (fixture / source).read_bytes()
        words = struct.unpack(f'<{len(payload)//2}H', payload)
        if halfwords is not None and len(words) != halfwords:
            raise ValueError(f'{source}: expected {halfwords} halfwords, got {len(words)}')
        (directory / target).write_text(''.join(f'{w:04x}\n' for w in words))
    qwords = struct.unpack('<52Q', patched)
    (directory / 'commands.hex').write_text(
        ''.join(f'{word:016x}\n' for word in qwords))


def run_profile(simulator: str, profile: int, outdir: Path, keep_build: bool) -> dict:
    spec = dict(PROFILES[profile])
    fixture, manifest, patched = load(profile)
    spec['input_base'] = manifest['command_stream']['addresses']['input']
    spec['weight_base'] = manifest['command_stream']['addresses']['weight']
    spec['output_base'] = manifest['command_stream']['addresses']['out']
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    hexdir = outdir / 'fixture-hex'
    write_hex(fixture, patched, hexdir, spec)

    sources = [DONOR / name for name in DONOR_SOURCES] + [ROOT / name for name in RTL]
    inputs = ([ROOT / 'tests/conv/tb_conv_simple.sv', RUNNER, ROOT / 'rtl/cmac/rk_conv_simple_profiles.svh',
               ROOT / 'tools/conv/gen_conv_simple_profiles.py', ROOT / 'tools/conv/freeze_simple_fixtures.py',
               ROOT / 'fpga/ppu/sources.json'] +
              [fixture / name for name in FIXTURE_FILES])
    hashes_before = {str(p.relative_to(ROOT)): sha(p) for p in sources + inputs}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    status = subprocess.run(['git', 'status', '--short', '--untracked-files=all'],
                            cwd=ROOT, text=True, capture_output=True,
                            check=True).stdout.splitlines()
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'case': spec['case'],
        'profile': profile, 'simulator': simulator, 'source_revision': revision,
        'source_worktree_status': status,
        'scope': ('Frozen conv-simple capture through the raw 52-QWORD endpoint, '
                  'parameterised spatial front, donor CMAC/CACC arithmetic and '
                  'FP16 output atom writer. Complete output BO comparison and '
                  'negative controls. Simulation only; no FPGA execution.'),
        'fixture': {'manifest': str((fixture / 'manifest.json').relative_to(ROOT)),
                    'device_output_sha256': manifest['output']['device_sha256'],
                    'recomputed_oracle_sha256': manifest['output']['oracle_recomputed_sha256'],
                    'patched_command_sha256': hashlib.sha256(patched).hexdigest()},
        'geometry': spec, 'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'source_hashes_before': hashes_before, 'modes': [],
    }
    build: Path | None = None
    if simulator == 'iverilog':
        build = outdir / 'sim.vvp'
        argv = [compiler, '-g2012', '-Wall', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-s', 'tb_conv_simple',
                f'-Ptb_conv_simple.PROFILE={profile}',
                f'-Ptb_conv_simple.KH={spec["kh"]}', f'-Ptb_conv_simple.KW={spec["kw"]}',
                f'-Ptb_conv_simple.INPUT_CHANNELS={spec["in_c"]}',
                f'-Ptb_conv_simple.KERNELS={spec["kernels"]}',
                f'-Ptb_conv_simple.C1_BLOCKS={spec["c1_blocks"]}',
                f'-Ptb_conv_simple.ALIGN_C={spec["align_c"]}',
                f'-Ptb_conv_simple.PACK_C2={spec["pack_c2"]}',
                f'-Ptb_conv_simple.WEIGHT_HALFWORDS={spec["weight_halfwords"]}',
                f'-Ptb_conv_simple.INPUT_HALFWORDS={spec["input_halfwords"]}',
                f'-Ptb_conv_simple.OUTPUT_BYTES={spec["output_bytes"]}',
                f'-Ptb_conv_simple.INPUT_BASE={spec["input_base"]}',
                f'-Ptb_conv_simple.WEIGHT_BASE={spec["weight_base"]}',
                f'-Ptb_conv_simple.OUTPUT_BASE={spec["output_base"]}',
                '-o', str(build), *[str(p) for p in sources],
                str(ROOT / 'tests/conv/tb_conv_simple.sv')]
        prefix = [runtime, str(build)]
    else:
        build = outdir / 'obj_dir'
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', '--timescale-override', '1ns/1ps', '-DDESIGNWARE_NOEXIST',
                '-DASSERT_ON', '-Irtl', '-Irtl/vendor/nvdla',
                f'-GPROFILE={profile}', f'-GKH={spec["kh"]}', f'-GKW={spec["kw"]}',
                f'-GINPUT_CHANNELS={spec["in_c"]}', f'-GKERNELS={spec["kernels"]}',
                f'-GC1_BLOCKS={spec["c1_blocks"]}', f'-GALIGN_C={spec["align_c"]}',
                f'-GPACK_C2={spec["pack_c2"]}',
                f'-GWEIGHT_HALFWORDS={spec["weight_halfwords"]}',
                f'-GINPUT_HALFWORDS={spec["input_halfwords"]}',
                f'-GOUTPUT_BYTES={spec["output_bytes"]}',
                f'-GINPUT_BASE={spec["input_base"]}',
                f'-GWEIGHT_BASE={spec["weight_base"]}',
                f'-GOUTPUT_BASE={spec["output_base"]}',
                '--top-module', 'tb_conv_simple', '--Mdir', str(build), '-o', 'sim',
                *[str(p) for p in sources], str(ROOT / 'tests/conv/tb_conv_simple.sv')]
        prefix = [str(build / 'sim')]
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=900)
    text = result.stdout + result.stderr
    (outdir / 'compile.log').write_text(text)
    if result.returncode or re.search(r'%Error', text):
        raise RuntimeError(f'{simulator} compile failed: {text[-4000:]}')
    report['tool_version'] = tool_version(
        [compiler, '--version'] if simulator == 'verilator' else [compiler, '-V'])

    try:
        for mode, expect in MODES.items():
            result = subprocess.run(prefix + [f'+FIXTURE={hexdir}', f'+MODE={mode}'],
                                    cwd=ROOT, text=True, capture_output=True,
                                    check=False, timeout=900)
            output = result.stdout + result.stderr
            (outdir / f'mode-{mode}.log').write_text(output)
            matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
                       if line.startswith('PASS CONV_SIMPLE')]
            if result.returncode or len(matches) != 1:
                raise RuntimeError(f'mode {mode} run failed: {output[-4000:]}')
            counts = tuple(int(matches[0].group(i)) for i in range(1, 8))
            if counts[0] != profile or counts[1] != mode or counts[6] != spec['output_bytes']:
                raise RuntimeError(f'mode {mode} contract differs: {counts}')
            report['modes'].append({'mode': mode, 'counts': counts,
                                    'expect': expect})
            (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                           sort_keys=True) + '\n')
        after = {str(p.relative_to(ROOT)): sha(p) for p in sources + inputs}
        if after != hashes_before:
            raise RuntimeError('RTL, fixture or runner changed during the run')
        report.update(status='PASS', finished_utc=utc_now(), source_hashes_after=after)
    except Exception as exc:
        report.update(status='FAIL', failure=str(exc), finished_utc=utc_now())
        raise
    finally:
        if not keep_build and build is not None:
            shutil.rmtree(build, ignore_errors=True) if build.is_dir() else build.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                       sort_keys=True) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=int, action='append',
                        choices=tuple(PROFILES), default=None)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'),
                        default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    profiles = args.profile or list(PROFILES)
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    failures = 0
    for profile in profiles:
        for simulator in simulators:
            outdir = ROOT / 'build/convolution-simple' / f'{simulator}-{stamp}-p{profile}'
            try:
                outdir.mkdir(parents=True, exist_ok=False)
                report = run_profile(simulator, profile, outdir, args.keep_build)
            except Exception as exc:
                print(f'FAIL conv-simple profile {profile} {simulator}: {exc}',
                      file=sys.stderr)
                failures += 1
                continue
            print(f'PASS conv-simple profile {profile} ({PROFILES[profile]["case"]}) '
                  f'{simulator}: 13 modes, complete output BO exact; '
                  f'report={outdir / "report.json"}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
