#!/usr/bin/env python3
"""Validate the exact captured 28-QWORD C8 global-average command profile."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ppu.run_pool_avg_global3x5 import (  # noqa: E402
    CASE, DONOR, FILES, FIXTURE, MANIFEST, load_contract, now, sha,
    sha_bytes, tool_version,
)

RTL = ROOT / 'rtl/ppu/rk_ppu_pool_global_avg_raw_profile.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_global_avg_raw_profile.sv'
RUNNER = Path(__file__).resolve()
ERROR_MODES = {1: 2, 2: 2, 3: 1, 4: 1, 5: 3, 6: 3, 7: 1,
               8: 2, 9: 2, 10: 3, 11: 3, 12: 2, 13: 2}


def run(simulator: str, keep_build: bool, stamp: str) -> Path:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    manifest, job, patched = load_contract()
    outdir = ROOT / 'build/ppu-pooling' / f'global-average-raw-profile-{simulator}-{stamp}'
    outdir.mkdir(parents=True, exist_ok=False)
    command_path = outdir / 'captured_patched_regcmd.bin'
    command_path.write_bytes(patched)
    inputs = [RTL, TB, RUNNER, DONOR, MANIFEST,
              *[FIXTURE / name for name in FILES]]
    before = {str(path): sha(path) for path in inputs}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                              text=True, capture_output=True, check=True).stdout.strip()
    status = subprocess.run(['git', 'status', '--short', '--untracked-files=all'],
                            cwd=ROOT, text=True, capture_output=True,
                            check=True).stdout.splitlines()
    report = {
        'status': 'RUNNING', 'started_utc': now(), 'case': CASE,
        'simulator': simulator, 'source_revision': revision,
        'source_worktree_status': status,
        'tool_version': tool_version([compiler, '--version'] if simulator == 'verilator'
                                     else [compiler, '-V']),
        'runtime_version': tool_version([runtime, '-V']) if runtime else None,
        'python_version': platform.python_version(),
        'scope': 'Strict captured raw profile only; no DMA, arithmetic leaf or hardware in this test.',
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'fixture': {'raw_command_sha256': sha(FIXTURE / 'regcmd.bin'),
                    'patched_command_sha256': sha_bytes(patched),
                    'device_output_sha256': manifest['comparison']['device_output_sha256'],
                    'relocatable_qwords': [15, 22],
                    'addresses': {'in': 0x1000, 'out': 0x2000}},
        'contract': {'qwords': 28, 'input_bytes': 240, 'output_bytes': 16,
                     'kernel': [3, 5], 'stride': [3, 5], 'channels': 8,
                     'reciprocals': ['0x7266', '0x7555'],
                     'unsupported_writes_fail': True},
        'seed_policy': 'deterministic captured QWORD stream and fixed modes 0..13',
        'source_hashes_before': before, 'runs': [],
    }
    build = outdir / ('obj' if simulator == 'verilator' else 'sim.vvp')
    try:
        if simulator == 'iverilog':
            compile_argv = [compiler, '-g2012', '-Wall', '-s',
                            'tb_ppu_pool_global_avg_raw_profile', '-o', str(build),
                            str(RTL), str(TB)]
            prefix = [runtime, str(build)]
        else:
            compile_argv = [compiler, '--binary', '--timing', '--assert', '-Wall',
                            '-j', '2', '--top-module', 'tb_ppu_pool_global_avg_raw_profile',
                            '--Mdir', str(build), '-o', 'sim', str(RTL), str(TB)]
            prefix = [str(build / 'sim')]
        result = subprocess.run(compile_argv, cwd=ROOT, text=True,
                                capture_output=True, check=False, timeout=600)
        (outdir / 'compile.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'compile failed: {(result.stdout + result.stderr)[-5000:]}')
        for mode in range(14):
            expected_error = ERROR_MODES.get(mode, 0)
            argv = prefix + [f'+COMMAND_BIN={command_path}', f'+MODE={mode}',
                             f'+EXPECT_ERROR={expected_error}']
            run_result = subprocess.run(argv, cwd=ROOT, text=True,
                                        capture_output=True, check=False, timeout=180)
            output = run_result.stdout + run_result.stderr
            (outdir / f'mode-{mode}.log').write_text(output)
            if run_result.returncode or f'PASS ppu_global_avg_raw_profile mode={mode} ' not in output:
                raise RuntimeError(f'mode {mode} failed: {output[-3000:]}')
            if expected_error and f'rejected_code={expected_error}' not in output:
                raise RuntimeError(f'mode {mode} returned the wrong rejection: {output.strip()}')
            if mode == 0 and ('accepted_words=28' not in output or
                               'input_bytes=240 output_bytes=16 profile_stall_cycles=3' not in output):
                raise RuntimeError(f'valid geometry differs: {output.strip()}')
            report['runs'].append({'mode': mode, 'expected_error': expected_error,
                                   'output': output.strip(),
                                   'status': 'PASS'})
        after = {str(path): sha(path) for path in inputs}
        if before != after:
            raise RuntimeError('profile RTL, runner or fixture changed during simulation')
        report.update(status='PASS', finished_utc=now(),
                      source_hashes_after=after,
                      summary={'accepted_words': 28,
                               'relocations_only': [15, 22],
                               'negative_controls': len(ERROR_MODES),
                               'hardware_accessed': False})
    except Exception as exc:
        report.update(status='FAIL', finished_utc=now(), failure=str(exc))
        raise
    finally:
        if not keep_build:
            if build.is_dir():
                shutil.rmtree(build)
            else:
                build.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return outdir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'), default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    try:
        load_contract()
        for simulator in simulators:
            outdir = run(simulator, args.keep_build, stamp)
            print(f'PASS global-average raw profile {simulator}: 28 QWORDs, relocations [15,22], '
                  f'{len(ERROR_MODES)} negative controls; report={outdir / "report.json"}')
    except Exception as exc:
        print(f'FAIL global-average raw profile: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
