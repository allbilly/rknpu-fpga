#!/usr/bin/env python3
"""Replay the captured Q16 average / k1s1 identity leaves in both simulators.

Five exact profiles share two leaves:

  0  int8_avg_q16_k2s2_valid_c16_h2w2   area 4, 16 x INT8 lanes
  1  int8_avg_q16_k3x3_valid_c16_h3w3   area 9, 16 x INT8 lanes
  2  int16_avg_q16_k2s2_valid_c8_h2w2   area 4,  8 x INT16 lanes
  3  int16_avg_q16_k3x3_valid_c8_h3w3   area 9,  8 x INT16 lanes
  4  int8_max_k1s1_valid_c32_h1w1       1x1 identity, 32 x INT8 lanes

Each run compares the complete 4096-byte output BO against the frozen device
capture, then mutates one expected byte and one input pixel to prove the
comparison is load-bearing rather than vacuous.
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
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_int_avg.sv'
LEAVES = [
    ROOT / 'rtl/ppu/rk_ppu_pool_int_avg.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_avg_q16_i8_c16_k2s2.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_avg_q16_i8_c16_k3x3.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_avg_q16_i16_c8_k2s2.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_avg_q16_i16_c8_k3x3.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_max_k1s1_i8_c32.sv',
]
CASES = {
    'int8_avg_q16_k2s2_valid_c16_h2w2': {'id': 0, 'elem_w': 8, 'lanes': 16,
                                         'kh': 2, 'kw': 2},
    'int8_avg_q16_k3x3_valid_c16_h3w3': {'id': 1, 'elem_w': 8, 'lanes': 16,
                                         'kh': 3, 'kw': 3},
    'int16_avg_q16_k2s2_valid_c8_h2w2': {'id': 2, 'elem_w': 16, 'lanes': 8,
                                         'kh': 2, 'kw': 2},
    'int16_avg_q16_k3x3_valid_c8_h3w3': {'id': 3, 'elem_w': 16, 'lanes': 8,
                                         'kh': 3, 'kw': 3},
    'int8_max_k1s1_valid_c32_h1w1': {'id': 4, 'elem_w': 8, 'lanes': 16,
                                     'kh': 1, 'kw': 1},
}
PASS_RE = re.compile(
    r'^PASS PPU_INT_AVG case=(\d+) elem=(\d+) lanes=(\d+) area=(\d+) bo_bytes=(\d+)$')


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
        payload = (fixture / source).read_bytes()
        (directory / target).write_text(
            ''.join(f'{value:02x}\n' for value in payload))
    return directory


def mutate(directory: Path, kind: str) -> Path:
    """Copy the hex fixture with one deliberate change."""
    target = directory.parent / f'negative-{kind}'
    target.mkdir(parents=True, exist_ok=True)
    for name in ('in.hex', 'out_init.hex', 'device.hex'):
        shutil.copyfile(directory / name, target / name)
    if kind == 'expected':
        text = (target / 'device.hex').read_text()
        # The captured result is non-zero somewhere for every case.
        first = next(line for line in text.splitlines() if line.strip() != '00')
        (target / 'device.hex').write_text(
            text.replace(first, 'ff', 1))
    elif kind == 'input':
        text = (target / 'in.hex').read_text()
        first = next(line for line in text.splitlines() if line.strip() != '00')
        replacement = '00' if first.strip() != '00' else '01'
        (target / 'in.hex').write_text(text.replace(first, replacement, 1))
    else:
        raise ValueError(f'unknown negative control {kind}')
    return target


def build(simulator: str, spec: dict, outdir: Path, tb: Path = TB,
          sources: list[Path] | None = None) -> list[str]:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    rtl = sources or LEAVES
    if simulator == 'iverilog':
        binary = outdir / 'sim.vvp'
        prefix = [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-s',
                  'tb_ppu_pool_int_avg', '-o', str(binary),
                  f'-Ptb_ppu_pool_int_avg.CASE_ID={spec["id"]}',
                  f'-Ptb_ppu_pool_int_avg.ELEM_W={spec["elem_w"]}',
                  f'-Ptb_ppu_pool_int_avg.LANES={spec["lanes"]}',
                  f'-Ptb_ppu_pool_int_avg.KH={spec["kh"]}',
                  f'-Ptb_ppu_pool_int_avg.KW={spec["kw"]}',
                  *[str(p) for p in rtl], str(tb)]
    else:
        binary = outdir / 'obj_dir'
        prefix = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                  '-j', '2', '--timescale-override', '1ns/1ps',
                  f'-GCASE_ID={spec["id"]}', f'-GELEM_W={spec["elem_w"]}',
                  f'-GLANES={spec["lanes"]}', f'-GKH={spec["kh"]}',
                  f'-GKW={spec["kw"]}', '--top-module', 'tb_ppu_pool_int_avg',
                  '--Mdir', str(binary), '-o', 'sim',
                  *[str(p) for p in rtl], str(tb)]
    result = subprocess.run(prefix, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=900)
    text = result.stdout + result.stderr
    (outdir / 'compile.log').write_text(text)
    if result.returncode or re.search(r'%Error', text):
        raise RuntimeError(f'{simulator} compile failed: {text[-4000:]}')
    return [runtime, str(binary)] if simulator == 'iverilog' else [str(binary / 'sim')]


def run_one(simulator: str, case: str, outdir: Path, keep_build: bool) -> dict:
    spec = CASES[case]
    fixture, manifest = load(case)
    if outdir.exists():
        raise ValueError('output directory already exists')
    outdir.mkdir(parents=True)
    hexdir = hex_dir(fixture, outdir / 'fixture-hex')
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'case': case,
        'simulator': simulator, 'python_version': platform.python_version(),
        'source_hashes_before': {str(p.relative_to(ROOT)): sha(p)
                                 for p in [*LEAVES, TB, RUNNER] +
                                 [fixture / 'manifest.json', fixture / 'in.bin',
                                  fixture / 'out_init.bin', fixture / 'device_out.bin']},
        'fixture': {'manifest': str((fixture / 'manifest.json').relative_to(ROOT)),
                    'device_output_sha256': manifest['comparison']['device_output_sha256']},
        'scope': ('Captured signed-integer Q16 average / 1x1 identity pooling '
                  'leaf: complete 4096-byte output BO comparison plus one '
                  'mutated-expectation and one mutated-input control. '
                  'Simulation only; no FPGA execution.'),
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False, 'negative_controls': [],
    }
    (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                   sort_keys=True) + '\n')
    build_dir: Path | None = None
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
                   if line.startswith('PASS PPU_INT_AVG')]
        if result.returncode or len(matches) != 1:
            raise RuntimeError(f'replay failed: {output[-4000:]}')
        counts = tuple(int(matches[0].group(i)) for i in range(1, 6))
        if counts != (spec['id'], spec['elem_w'], spec['lanes'],
                      spec['kh'] * spec['kw'], 4096):
            raise RuntimeError(f'replay contract differs: {counts}')
        report['match'] = dict(zip(('case_id', 'elem_w', 'lanes', 'area', 'bo_bytes'),
                                   counts))
        for kind in ('expected', 'input'):
            negdir = mutate(hexdir, kind)
            neg = outdir / f'negative-{kind}'
            result = subprocess.run(prefix + [f'+FIXTURE={negdir}'], cwd=ROOT,
                                    text=True, capture_output=True, check=False,
                                    timeout=900)
            text = result.stdout + result.stderr
            (neg / 'run.log').write_text(text)
            if 'whole-BO mismatch' not in text:
                raise RuntimeError(f'negative {kind} did not reject: {text[-3000:]}')
            report['negative_controls'].append(
                {'kind': kind, 'result': 'REJECTED_WHOLE_BO_MISMATCH'})
        report['source_hashes_after'] = {name: sha(ROOT / name)
                                         for name in report['source_hashes_before']}
        if report['source_hashes_before'] != report['source_hashes_after']:
            raise RuntimeError('RTL or fixture changed during the run')
        report.update(status='PASS', finished_utc=utc_now())
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
            outdir = (ROOT / 'build/ppu-pool-int-avg' /
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
