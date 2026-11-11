#!/usr/bin/env python3
"""Board-image replay for the first pooling FPGA profile.

Runs `tb_ypcb_ppu_i8` (the autonomous self-test that will run on power-up) in
both simulators and compares the captured result. This does NOT synthesise,
place, route, program or read any FPGA; it only proves the image's RTL logic
reaches PASS from reset release.
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
TB = ROOT / 'tests/tb_ypcb_ppu_i8.sv'
RTL = [
    ROOT / 'rtl/ppu/rk_ppu_pool_self_test.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_demo_rom.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_i8_k2s2_dma.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_i8_k2s2_profile.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_int_k2s2.sv',
    ROOT / 'rtl/rk_bram.sv',
    ROOT / 'rtl/rk_startup_reset.sv',
    ROOT / 'fpga/ypcb_ppu_i8_top.sv',
]
SPEC = ROOT / 'fpga/ppu/sources.json'
XDC = ROOT / 'fpga/ypcb_ppu_i8.xdc'
GEN = ROOT / 'tools/ppu/gen_pool_demo.py'
TOP = 'tb_ypcb_ppu_i8'
PASS_LINE = ('PASS YPCB PPU INT8 image: 64-cycle hold, captured C16 H2W2 max '
             'whole-BO, both LED polarities')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def first_line(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=30)
    text = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(f'tool version command failed: {argv}: {text}')
    return text.splitlines()[0] if text else 'unknown'


def mutate_rom(rom: Path, target: Path, kind: str) -> None:
    """Write a deliberately broken ROM copy for a negative control."""
    text = rom.read_text()
    if kind == 'expected':
        # One captured output halfword changed: the checker must reject it.
        needle = "3'd0: expected_data = 16'h3164;"
        replacement = "3'd0: expected_data = 16'h3165;"
    elif kind == 'input':
        # Raise lane 0 of pixel 1 above the current maximum so the leaf's
        # computed value changes by exactly one.
        needle = "5'd8: input_data = 16'h3132;"
        replacement = "5'd8: input_data = 16'h3170;"
    else:
        raise RuntimeError(f'unknown negative control {kind}')
    if text.count(needle) != 1:
        raise RuntimeError(f'negative control {kind}: ROM pattern changed')
    target.write_text(text.replace(needle, replacement))


def run(simulator: str, outdir: Path, rom: Path = RTL[1],
        expect_pass: bool = True, tag: str = '') -> None:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    sources = [rom if path == RTL[1] else path for path in RTL]
    build_stem = f'tb{tag}'
    if simulator == 'iverilog':
        build = outdir / f'{build_stem}.vvp'
        argv = [compiler, '-g2012', '-Wall', '-s', TOP, '-o', str(build),
                *[str(p) for p in sources], str(TB)]
        prefix = [runtime, str(build)]
    else:
        build = outdir / f'obj_dir{tag}'
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', '--timescale-override', '1ns/1ps',
                '--top-module', TOP, '--Mdir', str(build), '-o', 'sim',
                *[str(p) for p in sources], str(TB)]
        prefix = [str(build / 'sim')]
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=600)
    text = result.stdout + result.stderr
    (outdir / f'compile{tag}.log').write_text(text)
    if result.returncode or re.search(r'%Error', text):
        raise RuntimeError(f'{simulator} compile failed: {text[-4000:]}')
    result = subprocess.run(prefix, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=600)
    output = result.stdout + result.stderr
    (outdir / f'run{tag}.log').write_text(output)
    if expect_pass:
        if result.returncode or PASS_LINE not in output.splitlines():
            raise RuntimeError(f'{simulator} board replay failed: {output[-4000:]}')
    else:
        # A negative control must terminate with the self-test's own error code,
        # not merely crash or hang.
        if 'board self-test FAILED code=51' not in output:
            raise RuntimeError(
                f'{simulator} negative control did not fail with code 0x51: {output[-4000:]}')
        if PASS_LINE in output.splitlines():
            raise RuntimeError(f'{simulator} negative control wrongly passed')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'),
                        default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()

    spec = json.loads(SPEC.read_text())
    if spec['top'] != 'ypcb_ppu_i8_top':
        raise SystemExit('sources.json top changed')
    result = subprocess.run([sys.executable, str(GEN), '--check'], cwd=ROOT,
                            text=True, capture_output=True, check=False, timeout=120)
    if result.returncode:
        raise SystemExit(f'generated ROM is stale: {result.stdout}{result.stderr}')

    paths = [*RTL, TB, RUNNER, SPEC, XDC, GEN,
             ROOT / 'tests/ppu_pool_demo_fixture.json']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    try:
        for simulator in simulators:
            outdir = ROOT / 'build/ppu-pool-board' / f'{simulator}-{stamp}'
            outdir.mkdir(parents=True, exist_ok=False)
            compiler = shutil.which(simulator)
            report = {
                'status': 'RUNNING',
                'started_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'simulator': simulator, 'python_version': platform.python_version(),
                'source_revision': subprocess.run(
                    ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                    capture_output=True, check=True).stdout.strip(),
                'source_hashes_before': {str(p.relative_to(ROOT)): sha(p) for p in paths},
                'top': spec['top'], 'part': spec['part'],
                'clock_period_ns': spec['clock_period_ns'],
                'scope': ('Autonomous board self-test logic: ROM-loaded captured '
                          '26-QWORD command stream, strict profile, serialized '
                          'memory, captured INT8 C16 H2W2 max, complete output '
                          'BO check, startup reset and LED polarity. '
                          'Simulation only; no synthesis, bitstream or board.'),
                'hardware_accessed': False, 'vivado_executed': False,
                'bitstream_emitted': False,
                'negative_controls': [],
            }
            (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                           sort_keys=True) + '\n')
            try:
                report['tool_version'] = first_line(
                    [compiler, '--version'] if simulator == 'verilator' else [compiler, '-V'])
                run(simulator, outdir)
                for kind in ('expected', 'input'):
                    mutated = outdir / f'negative-{kind}.sv'
                    mutate_rom(ROOT / 'rtl/ppu/rk_ppu_pool_demo_rom.sv', mutated, kind)
                    run(simulator, outdir, mutated, expect_pass=False, tag=f'-{kind}')
                    report['negative_controls'].append(
                        {'kind': kind, 'result': 'REJECTED_WITH_CODE_51'})
                after = {str(p.relative_to(ROOT)): sha(p) for p in paths}
                if after != report['source_hashes_before']:
                    raise RuntimeError('RTL or generated ROM changed during the run')
                report.update(status='PASS', finished_utc=datetime.now(
                    timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    source_hashes_after=after, result=PASS_LINE)
            except Exception as exc:
                report.update(status='FAIL', failure=str(exc),
                              finished_utc=datetime.now(timezone.utc).strftime(
                                  '%Y-%m-%dT%H:%M:%SZ'))
                raise
            finally:
                if not args.keep_build:
                    for leftover in list(outdir.glob('obj_dir*')):
                        if leftover.is_dir():
                            shutil.rmtree(leftover)
                    for leftover in list(outdir.glob('tb*.vvp')):
                        leftover.unlink(missing_ok=True)
                    report['build_products_pruned'] = True
                (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                               sort_keys=True) + '\n')
            print(f'PASS board image logic {simulator}: {PASS_LINE}; '
                  f'report={outdir / "report.json"}')
    except Exception as exc:
        print(f'FAIL board image logic: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
