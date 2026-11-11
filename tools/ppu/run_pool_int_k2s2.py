#!/usr/bin/env python3
"""Replay the captured signed-integer 2x2/stride-2 pooling cases.

Four exact profiles share one parameterized reducer
(`rk_ppu_pool_int_k2s2`): INT8 C16 max/min and INT16 C8 max/min, each C H2 W2
-> H1 W1. Every replay compares the complete 4096-byte output BO against the
frozen device capture.
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
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNNER = Path(__file__).resolve()
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_int_k2s2.sv'
CORE = ROOT / 'rtl/ppu/rk_ppu_pool_int_k2s2.sv'
CASES = {
    'int8_max_k2s2_valid_c16_h2w2': {
        'elem_w': 8, 'lanes': 16, 'method': 0,
        'wrapper': ROOT / 'rtl/ppu/rk_ppu_pool_max_k2s2_i8_c16_h2w2.sv',
        'module': 'rk_ppu_pool_max_k2s2_i8_c16_h2w2',
    },
    'int8_min_k2s2_valid_c16_h2w2': {
        'elem_w': 8, 'lanes': 16, 'method': 1,
        'wrapper': ROOT / 'rtl/ppu/rk_ppu_pool_min_k2s2_i8_c16_h2w2.sv',
        'module': 'rk_ppu_pool_min_k2s2_i8_c16_h2w2',
    },
    'int16_max_k2s2_valid_c8_h2w2': {
        'elem_w': 16, 'lanes': 8, 'method': 0,
        'wrapper': ROOT / 'rtl/ppu/rk_ppu_pool_max_k2s2_i16_c8_h2w2.sv',
        'module': 'rk_ppu_pool_max_k2s2_i16_c8_h2w2',
    },
    'int16_min_k2s2_valid_c8_h2w2': {
        'elem_w': 16, 'lanes': 8, 'method': 1,
        'wrapper': ROOT / 'rtl/ppu/rk_ppu_pool_min_k2s2_i16_c8_h2w2.sv',
        'module': 'rk_ppu_pool_min_k2s2_i16_c8_h2w2',
    },
}
PASS_RE = re.compile(
    r'^PASS PPU_INT_K2S2 elem=(\d+) lanes=(\d+) method=(\d+) beats=(\d+) '
    r'bo_bytes=(\d+)$')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _first_line(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=30)
    text = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(f'tool version command failed: {argv}: {text}')
    return text.splitlines()[0] if text else 'unknown'


def byte_hex(source: Path, target: Path) -> None:
    data = source.read_bytes()
    target.write_text(''.join(f'{value:02x}\n' for value in data))


def validate(case: str, manifest: dict) -> None:
    expected = CASES[case]
    ppu = manifest['ppu']
    if manifest['case'] != case:
        raise SystemExit(f'{case}: fixture identity mismatch')
    if ppu['dtype'] != ('int8' if expected['elem_w'] == 8 else 'int16'):
        raise SystemExit(f'{case}: dtype changed')
    if ppu['channels'] != expected['lanes']:
        raise SystemExit(f'{case}: lane count changed')
    if ppu['method'] != ('maximum' if expected['method'] == 0 else 'minimum'):
        raise SystemExit(f'{case}: method changed')
    if ppu['in_shape'] != [2, 2] or ppu['out_shape'] != [1, 1]:
        raise SystemExit(f'{case}: geometry changed')
    if list(ppu['kernel']) != [2, 2] or list(ppu['stride']) != [2, 2]:
        raise SystemExit(f'{case}: kernel/stride changed')
    if ppu['padding'] != [0, 0, 0, 0]:
        raise SystemExit(f'{case}: padding changed')
    if manifest['comparison']['tolerance'] != 0.0:
        raise SystemExit(f'{case}: fixture is not an exact comparison')
    if manifest['comparison']['mismatches_expected'] != 0:
        raise SystemExit(f'{case}: fixture expects mismatches')


def run_one(simulator: str, stamp: str, case: str, keep_build: bool) -> Path:
    fixture = ROOT / 'tests/ppu_pooling/fixtures' / case
    manifest = json.loads((fixture / 'manifest.json').read_text())
    validate(case, manifest)
    for name, record in manifest['files'].items():
        path = fixture / name
        if not path.is_file():
            raise SystemExit(f'{case}: fixture file missing: {name}')
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise SystemExit(f'{case}: fixture file changed: {name}')

    spec = CASES[case]
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')

    outdir = ROOT / 'build/ppu-pool-int-k2s2' / case / f'{simulator}-{stamp}'
    outdir.mkdir(parents=True, exist_ok=False)
    hexdir = outdir / 'fixture-hex'
    hexdir.mkdir(parents=True)
    for source, target in (('in.bin', 'in.hex'), ('out_init.bin', 'out_init.hex'),
                           ('device_out.bin', 'device.hex')):
        byte_hex(fixture / source, hexdir / target)

    rtl = [CORE, spec['wrapper']]
    paths = [*rtl, TB, RUNNER, fixture / 'manifest.json', fixture / 'in.bin',
             fixture / 'out_init.bin', fixture / 'device_out.bin']
    hashes_before = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    git_status = subprocess.run(['git', 'status', '--short', '--untracked-files=all'],
                                cwd=ROOT, text=True, capture_output=True,
                                check=True).stdout.splitlines()
    report = {
        'status': 'RUNNING', 'started_utc': now(), 'case': case,
        'profile': spec['module'], 'elem_width': spec['elem_w'],
        'lanes': spec['lanes'], 'method': spec['method'],
        'simulator': simulator, 'python_version': platform.python_version(),
        'source_revision': revision, 'source_worktree_status': git_status,
        'source_hashes_before': hashes_before,
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'scope': ('Captured signed-integer pooling, C H2 W2 -> H1 W1, '
                  '2x2/stride-2, exact whole-4096-byte-BO comparison. '
                  'Standalone leaf, not a PPU endpoint or FPGA result.'),
        'contract': {
            'input_atoms': 4, 'value_bytes': 16, 'bo_bytes': 4096,
            'elem_width': spec['elem_w'], 'lanes': spec['lanes'],
            'signed_compare': True, 'seeded_from_first_atom': True,
            'tolerance': 0.0,
        },
        'runs': [],
    }
    build: Path | None = None
    try:
        if simulator == 'iverilog':
            build = outdir / 'sim.vvp'
            command = [compiler, '-g2012',
                       f'-Ptb_ppu_pool_int_k2s2.ELEM_W={spec["elem_w"]}',
                       f'-Ptb_ppu_pool_int_k2s2.LANES={spec["lanes"]}',
                       f'-Ptb_ppu_pool_int_k2s2.METHOD={spec["method"]}',
                       '-s', 'tb_ppu_pool_int_k2s2', '-o', str(build),
                       *[str(p) for p in rtl], str(TB)]
            result = subprocess.run(command, cwd=ROOT, text=True,
                                    capture_output=True, check=False, timeout=300)
            text = result.stdout + result.stderr
            (outdir / 'compile.log').write_text(text)
            if result.returncode or re.search(r'warning:|sorry:', text, re.I):
                raise RuntimeError(f'Icarus compile failed/warned: {text[-4000:]}')
            prefix = [runtime, str(build)]
            report['tool_version'] = _first_line([compiler, '-V'])
            report['runtime_version'] = _first_line([runtime, '-V'])
        else:
            build = outdir / 'obj_dir'
            command = [compiler, '--binary', '--timing', '--assert', '-Wall',
                       '-Wno-fatal', '-j', '2', '--timescale-override', '1ns/1ps',
                       f'-GELEM_W={spec["elem_w"]}', f'-GLANES={spec["lanes"]}',
                       f'-GMETHOD={spec["method"]}',
                       '--top-module', 'tb_ppu_pool_int_k2s2',
                       '--Mdir', str(build), '-o', 'sim',
                       *[str(p) for p in rtl], str(TB)]
            result = subprocess.run(command, cwd=ROOT, text=True,
                                    capture_output=True, check=False, timeout=600)
            text = result.stdout + result.stderr
            (outdir / 'compile.log').write_text(text)
            if result.returncode:
                raise RuntimeError(f'Verilator compile failed: {text[-4000:]}')
            report['compile_warning_headers'] = sum(
                line.startswith('%Warning-') for line in text.splitlines())
            prefix = [str(build / 'sim')]
            report['tool_version'] = _first_line([compiler, '--version'])

        result = subprocess.run(prefix + [f'+FIXTURE={hexdir}'], cwd=ROOT,
                                text=True, capture_output=True, check=False,
                                timeout=300)
        output = result.stdout + result.stderr
        (outdir / 'run.log').write_text(output)
        matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
                   if line.startswith('PASS PPU_INT_K2S2')]
        if result.returncode or len(matches) != 1:
            raise RuntimeError(f'replay failed: {output[-4000:]}')
        counts = tuple(int(matches[0].group(index)) for index in range(1, 6))
        if counts != (spec['elem_w'], spec['lanes'], spec['method'], 4, 4096):
            raise RuntimeError(f'replay contract differs: {counts}')
        report['runs'].append({'status': 'PASS', 'result': output.strip()})

        hashes_after = {str(p.relative_to(ROOT)): sha(p) for p in paths}
        if hashes_before != hashes_after:
            raise RuntimeError('RTL, fixture or runner changed during the run')
        report.update(status='PASS', finished_utc=now(),
                      source_hashes_after=hashes_after,
                      summary={'input_atoms': 4, 'bo_bytes': 4096,
                               'mismatched_bytes': 0, 'hardware_accessed': False})
    except Exception as exc:
        report.update(status='FAIL', finished_utc=now(), failure=str(exc))
        raise
    finally:
        if not keep_build and build is not None:
            shutil.rmtree(build, ignore_errors=True)
            report['build_products_pruned'] = True
        (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                       sort_keys=True) + '\n')
    return outdir


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
    try:
        for case in cases:
            for simulator in simulators:
                outdir = run_one(simulator, stamp, case, args.keep_build)
                print(f'PASS captured {case} {simulator}: 4 input atoms, '
                      f'whole 4096-byte BO exact; '
                      f'report={outdir / "report.json"}')
    except Exception as exc:
        print(f'FAIL captured signed-integer k2s2 pooling: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
