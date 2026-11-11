#!/usr/bin/env python3
"""Replay the strict 54-QWORD convolution descriptor-fetch wrappers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.conv import run_3x3_valid_c4 as raw

RUNNER = Path(__file__).resolve()
TB = ROOT / 'tests/conv/tb_conv_3x3_c4_dma.sv'
DMA_RTL = ROOT / 'rtl/cmac/rk_conv_3x3_c4_dma.sv'
PASS_RE = re.compile(
    r'^PASS CONV_3X3_DMA profile=(\d+) mode=(\d+) command_reads=(\d+) reads=(\d+) writes=(\d+)$'
)
PROFILE_IDS = {'VALID': 0, 'STRIDE2': 1, 'PAD1': 2}


def profile_ids() -> dict[str, int]:
    """Cases the descriptor wrapper can select by exact profile id."""
    return {case: PROFILE_IDS[name] for case, name in raw.CASES.items()
            if name in PROFILE_IDS}


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def run_one(simulator: str, stamp: str, keep_build: bool,
            case: str, manifest: dict, patched: bytes, fixture: Path) -> Path:
    name = raw.CASES[case]
    profile = PROFILE_IDS[name]
    shape = manifest['shape']
    execution = manifest.get('execution_geometry', shape)
    input_pixels = execution['input_height'] * execution['input_width']
    output_pixels = shape['output_height'] * shape['output_width']
    input_reads = input_pixels * 4
    operand_reads = 576 + input_reads
    all_reads = 216 + operand_reads
    writes = output_pixels * 8
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')

    outdir = (ROOT / 'build/convolution-3x3-c4-dma' / case /
              f'{simulator}-{stamp}')
    outdir.mkdir(parents=True, exist_ok=False)
    fixture_dir = outdir / 'fixture-hex'
    raw.fixture_hex(fixture_dir, patched, fixture)
    rtl_paths = [ROOT / path for path in raw.RTL] + [DMA_RTL, TB]
    donor_paths = [raw.DONOR_RTL / name for name in raw.SOURCES]
    fixture_paths = [fixture / name for name in raw.FIXTURE_FILES]
    paths = [*donor_paths, *rtl_paths, RUNNER, *fixture_paths]
    hashes_before = {str(p.relative_to(ROOT)): raw.sha(p) for p in paths}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    git_status = subprocess.run(['git', 'status', '--short', '--untracked-files=all'],
                                 cwd=ROOT, text=True, capture_output=True,
                                 check=True).stdout.splitlines()
    report = {
        'status': 'RUNNING', 'started_utc': now(), 'case': case,
        'profile': name, 'profile_id': profile, 'simulator': simulator,
        'tool_version': raw.tool_version([compiler, '--version'] if simulator == 'verilator'
                                         else [compiler, '-V']),
        'runtime_version': raw.tool_version([runtime, '-V']) if runtime else None,
        'python_version': platform.python_version(), 'source_revision': revision,
        'source_worktree_status': git_status,
        'seed': '0x3c4c9a31',
        'seed_policy': 'fixed memory-handshake LCG in the SystemVerilog testbench',
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'command_contract': {
            'descriptor_amount_qwords': 54, 'raw_qwords_fetched': 54,
            'raw_qword_order_preserved': True, 'halfword_reads': 216,
            'task_end_sideband_qword': 53, 'relocations': [21, 27, 35],
            'command_vs_operand_overlap_rejected': True,
        },
        'traffic_contract': {
            'command_halfword_reads': 216, 'weight_halfword_reads': 576,
            'input_halfword_reads': input_reads, 'total_halfword_reads': all_reads,
            'output_halfword_writes': writes, 'logical_output_elements': output_pixels * 4,
            'complete_output_bo_bytes': (fixture / 'device_out.bin').stat().st_size,
        },
        'negative_controls': {
            'wrong_amount': {'mode': 1, 'code': 7},
            'command_address_overflow': {'mode': 2, 'code': 7},
            'command_operand_overlap': {'mode': 3, 'code': 4},
            'command_read_error': {'mode': 4, 'code': 5},
            'command_read_timeout': {'mode': 5, 'code': 8},
            'invalid_raw_register': {'mode': 6, 'code': 2},
        },
        'source_hashes_before': hashes_before, 'runs': [],
    }
    build: Path | None = None
    try:
        donor_sources = [str(p) for p in donor_paths]
        rtl_sources = [str(p) for p in rtl_paths]
        if simulator == 'iverilog':
            build = outdir / 'sim.vvp'
            command = [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                       f'-Ptb_conv_3x3_c4_dma.PROFILE={profile}', f'-I{raw.DONOR_RTL}',
                       '-s', 'tb_conv_3x3_c4_dma', '-o', str(build),
                       *donor_sources, *rtl_sources]
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                                    check=False, timeout=300)
            text = result.stdout + result.stderr
            (outdir / 'compile.log').write_text(text)
            if result.returncode or re.search(r'warning:|sorry:', text, re.I):
                raise RuntimeError(f'Icarus compile failed/warned: {text[-6000:]}')
            prefix = [runtime, str(build)]
        else:
            build = outdir / 'obj_dir'
            command = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                       '-j', '2', '--timescale-override', '1ns/1ps',
                       '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-GPROFILE={profile}',
                       f'-I{raw.DONOR_RTL}', '--top-module', 'tb_conv_3x3_c4_dma',
                       '--Mdir', str(build), '-o', 'sim', *donor_sources, *rtl_sources]
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                                    check=False, timeout=600)
            text = result.stdout + result.stderr
            (outdir / 'compile.log').write_text(text)
            if result.returncode:
                raise RuntimeError(f'Verilator compile failed: {text[-6000:]}')
            report['compile_warning_headers'] = sum(
                line.startswith('%Warning-') for line in text.splitlines())
            prefix = [str(build / 'sim')]

        for mode in range(7):
            result = subprocess.run(prefix + [f'+FIXTURE={fixture_dir}', f'+MODE={mode}'],
                                    cwd=ROOT, text=True, capture_output=True,
                                    check=False, timeout=300)
            output = result.stdout + result.stderr
            (outdir / f'mode-{mode}.log').write_text(output)
            matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
                       if line.startswith('PASS CONV_3X3_DMA ')]
            if (result.returncode or len(matches) != 1 or
                    int(matches[0].group(1)) != profile or
                    int(matches[0].group(2)) != mode):
                raise RuntimeError(f'mode {mode} failed: {output[-5000:]}')
            counts = tuple(int(matches[0].group(i)) for i in range(3, 6))
            if mode == 0 and counts != (216, all_reads, writes):
                raise RuntimeError(f'successful raw-DMA traffic differs: {counts}')
            report['runs'].append({'mode': mode, 'status': 'PASS', 'result': output.strip()})

        hashes_after = {str(p.relative_to(ROOT)): raw.sha(p) for p in paths}
        if hashes_before != hashes_after:
            raise RuntimeError('RTL, fixture or runner changed during the simulation')
        report.update(status='PASS', finished_utc=now(), source_hashes_after=hashes_after,
                       summary={'raw_qwords': 54, 'command_halfword_reads': 216,
                                'operand_halfword_reads': operand_reads,
                                'output_halfword_writes': writes,
                                'negative_controls': 6, 'hardware_accessed': False})
    except Exception as exc:
        report.update(status='FAIL', finished_utc=now(), failure=str(exc))
        raise
    finally:
        if not keep_build and build is not None:
            if build.is_dir():
                shutil.rmtree(build)
            else:
                build.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return outdir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=tuple(raw.CASES),
                        default='conv_3x3_valid_c4_h9_w9_oc4')
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'), default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    try:
        manifest, _job, _command, patched, fixture = raw.load_contract(args.case)
    except Exception as exc:
        print(f'CONTRACT FAIL: {exc}', file=sys.stderr)
        return 1
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    try:
        for simulator in simulators:
            outdir = run_one(simulator, stamp, args.keep_build, args.case,
                             manifest, patched, fixture)
            print(f'PASS raw 54-QWORD convolution DMA {args.case} {simulator}: '
                  f'216 command reads, 6 negative controls; report={outdir / "report.json"}')
    except Exception as exc:
        print(f'FAIL raw 54-QWORD convolution DMA {args.case}: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
