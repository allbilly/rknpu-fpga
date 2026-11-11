#!/usr/bin/env python3
"""Replay the captured padded FP16 pooling stragglers in both simulators.

Three exact profiles:

  0  fp16_max_k3s2_pad1_c8_h4w4              3x3/stride-2, -inf pad
  1  fp16_avg_k2s1_pad1_use_cnt0_c8_h1w1     2x2/stride-1, +0 pad
  2  fp16_avg_k2s1_pad1_use_cnt7_c8_h1w1     same leaf, USE_CNT=7

Each run compares the complete 4096-byte output BO against the frozen device
capture and adds two negative controls (one mutated expected byte, one mutated
input byte) that must be rejected.
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
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_pad_tail.sv'
LEAVES = [
    ROOT / 'rtl/ppu/rk_ppu_pool_max3x3s2_pad1_c8_h4w4.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_avg2x2s1_pad1_c8_h1w1.sv',
]
CASES = {
    'fp16_max_k3s2_pad1_c8_h4w4': {
        'id': 0, 'in_atoms': 16, 'out_atoms': 4, 'use_cnt': 0,
        'method': 'maximum', 'pad': '-inf'},
    'fp16_avg_k2s1_pad1_use_cnt0_c8_h1w1': {
        'id': 1, 'in_atoms': 1, 'out_atoms': 4, 'use_cnt': 0,
        'method': 'average', 'pad': '+0'},
    'fp16_avg_k2s1_pad1_use_cnt7_c8_h1w1': {
        'id': 2, 'in_atoms': 1, 'out_atoms': 4, 'use_cnt': 7,
        'method': 'average', 'pad': '+0'},
}
PASS_RE = re.compile(
    r'^PASS PPU_POOL_PAD_TAIL case=(\d+) in_atoms=(\d+) out_atoms=(\d+) '
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


def load(case: str) -> tuple[Path, dict]:
    fixture = ROOT / 'tests/ppu_pooling/fixtures' / case
    manifest = json.loads((fixture / 'manifest.json').read_text())
    if manifest['case'] != case:
        raise ValueError(f'{case}: fixture identity mismatch')
    for name, record in manifest['files'].items():
        path = fixture / name
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError(f'{case}: fixture file changed: {name}')
    return fixture, manifest


def hex_dir(fixture: Path, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for source, target in (('in.bin', 'in.hex'), ('out_init.bin', 'out_init.hex'),
                           ('device_out.bin', 'device.hex')):
        (directory / target).write_text(
            ''.join(f'{value:02x}\n' for value in (fixture / source).read_bytes()))
    return directory


def mutate(directory: Path, kind: str) -> Path:
    target = directory.parent / f'negative-{kind}'
    target.mkdir(parents=True, exist_ok=True)
    for name in ('in.hex', 'out_init.hex', 'device.hex'):
        shutil.copyfile(directory / name, target / name)
    name = 'device.hex' if kind == 'expected' else 'in.hex'
    text = (target / name).read_text()
    if kind == 'expected':
        first = next(line for line in text.splitlines() if line.strip() != '00')
        (target / name).write_text(text.replace(first, 'ff', 1))
    else:
        # The last input atom always participates in a window; raise its first
        # definite FP16 value to a larger normal so the maximum must change.
        lines = text.splitlines()
        last = max(i for i, line in enumerate(lines) if line.strip() != '00')
        lines[last] = '7bff'          # 65504: maximum finite FP16
        (target / name).write_text('\n'.join(lines) + '\n')
    return target


def build(simulator: str, spec: dict, outdir: Path) -> list[str]:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    if simulator == 'iverilog':
        binary = outdir / 'sim.vvp'
        argv = [compiler, '-g2012', '-s', 'tb_ppu_pool_pad_tail',
                f'-Ptb_ppu_pool_pad_tail.CASE_ID={spec["id"]}', '-o', str(binary),
                *[str(p) for p in LEAVES], str(TB)]
        prefix = [runtime, str(binary)]
    else:
        binary = outdir / 'obj_dir'
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', '--timescale-override', '1ns/1ps',
                f'-GCASE_ID={spec["id"]}', '--top-module', 'tb_ppu_pool_pad_tail',
                '--Mdir', str(binary), '-o', 'sim',
                *[str(p) for p in LEAVES], str(TB)]
        prefix = [str(binary / 'sim')]
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=900)
    text = result.stdout + result.stderr
    (outdir / 'compile.log').write_text(text)
    if result.returncode or re.search(r'%Error', text):
        raise RuntimeError(f'{simulator} compile failed: {text[-4000:]}')
    return prefix


def run_one(simulator: str, case: str, outdir: Path, keep_build: bool) -> dict:
    spec = CASES[case]
    fixture, manifest = load(case)
    if outdir.exists():
        raise ValueError('output directory already exists')
    outdir.mkdir(parents=True)
    hexdir = hex_dir(fixture, outdir / 'fixture-hex')
    tracked = [*LEAVES, TB, RUNNER, fixture / 'manifest.json']
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'case': case,
        'simulator': simulator, 'python_version': platform.python_version(),
        'source_hashes_before': {str(p.relative_to(ROOT)): sha(p) for p in tracked},
        'fixture': {'manifest': str((fixture / 'manifest.json').relative_to(ROOT)),
                    'device_output_sha256': manifest['comparison']['device_output_sha256'],
                    'method': spec['method'], 'padding_value': spec['pad'],
                    'use_cnt': spec['use_cnt']},
        'scope': ('Captured padded FP16 pooling: complete 4096-byte output BO '
                  'comparison plus one mutated-expectation and one '
                  'mutated-input control. Simulation only; no FPGA execution.'),
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False, 'negative_controls': [],
    }
    (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                   sort_keys=True) + '\n')
    try:
        prefix = build(simulator, spec, outdir)
        report['tool_version'] = tool_version(
            [shutil.which(simulator), '--version'] if simulator == 'verilator'
            else [shutil.which(simulator), '-V'])
        result = subprocess.run(prefix + [f'+FIXTURE={hexdir}'], cwd=ROOT,
                                text=True, capture_output=True, check=False,
                                timeout=900)
        output = result.stdout + result.stderr
        (outdir / 'run.log').write_text(output)
        matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
                   if line.startswith('PASS PPU_POOL_PAD_TAIL')]
        if result.returncode or len(matches) != 1:
            raise RuntimeError(f'replay failed: {output[-4000:]}')
        counts = tuple(int(matches[0].group(i)) for i in range(1, 5))
        if counts != (spec['id'], spec['in_atoms'], spec['out_atoms'], 4096):
            raise RuntimeError(f'replay contract differs: {counts}')
        report['match'] = dict(zip(('case_id', 'in_atoms', 'out_atoms', 'bo_bytes'),
                                   counts))
        for kind in ('expected', 'input'):
            negative = mutate(hexdir, kind)
            result = subprocess.run(prefix + [f'+FIXTURE={negative}'], cwd=ROOT,
                                    text=True, capture_output=True, check=False,
                                    timeout=900)
            text = result.stdout + result.stderr
            (outdir / f'negative-{kind}.log').write_text(text)
            if 'whole-BO mismatch' not in text:
                raise RuntimeError(f'negative {kind} did not reject: {text[-3000:]}')
            report['negative_controls'].append(
                {'kind': kind, 'result': 'REJECTED_WHOLE_BO_MISMATCH'})
        after = {str(p.relative_to(ROOT)): sha(p) for p in tracked}
        if after != report['source_hashes_before']:
            raise RuntimeError('RTL or fixture changed during the run')
        report.update(status='PASS', finished_utc=utc_now(),
                      source_hashes_after=after)
    except Exception as exc:
        report.update(status='FAIL', failure=str(exc))
        raise
    finally:
        if not keep_build:
            for leftover in list(outdir.glob('obj_dir')):
                if leftover.is_dir():
                    shutil.rmtree(leftover)
            for leftover in list(outdir.glob('*.vvp')):
                leftover.unlink(missing_ok=True)
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
            outdir = (ROOT / 'build/ppu-pool-pad-tail' /
                      f'{simulator}-{stamp}-{CASES[case]["id"]}')
            try:
                report = run_one(simulator, case, outdir, args.keep_build)
            except Exception as exc:
                print(f'FAIL {case} {simulator}: {exc}', file=sys.stderr)
                failures += 1
                continue
            print(f'PASS {case} {simulator}: complete 4096-byte BO, '
                  f'2 negative controls; report={outdir / "report.json"}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
