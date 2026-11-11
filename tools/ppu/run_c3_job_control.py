#!/usr/bin/env python3
"""Exercise the optional RKPP page and its result/ACK ownership lifecycle."""
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
import time

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / 'rtl/ddr/framework/rk_layout_job_control.sv'
ADMISSION_RTL = ROOT / 'rtl/ddr/capacity/rk_job_control_admission.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_c3_job_control.sv'
RUNNER = Path(__file__).resolve()
PASS_MARKER = 'PASS ppu_c3_job_control RKPP=0x300 kind=3 ready-gate=SLVERR success-ACK=fault-held'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version(argv: list[str]) -> str:
    result = subprocess.run(argv, text=True, capture_output=True,
                            check=False, timeout=30)
    return (result.stdout or result.stderr).splitlines()[0]


def save_report(outdir: Path, report: dict) -> None:
    (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def run_logged(name: str, argv: list[str], outdir: Path, report: dict,
               timeout: int) -> str:
    log = outdir / f'{name}.log'
    record = {'name': name, 'argv': [str(arg) for arg in argv],
              'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(record)
    save_report(outdir, report)
    started = time.monotonic()
    with log.open('w') as stream:
        result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, check=False,
                                timeout=timeout)
    text = log.read_text()
    fatal = [line for line in text.splitlines()
             if '%Fatal' in line or '$fatal' in line or 'FATAL:' in line]
    record.update(status='PASS' if result.returncode == 0 and not fatal else 'FAIL',
                  returncode=result.returncode,
                  seconds=round(time.monotonic() - started, 3),
                  log_sha256=sha(log), fatal_lines=fatal)
    save_report(outdir, report)
    if result.returncode or fatal:
        raise RuntimeError(f'{name} failed (exit={result.returncode}, fatal={len(fatal)}):\n{text[-5000:]}')
    return text


def run_one(simulator: str, outdir: Path, keep_build: bool) -> None:
    compiler = shutil.which(simulator)
    if not compiler:
        raise RuntimeError(f'{simulator} is unavailable')
    if simulator == 'iverilog' and not shutil.which('vvp'):
        raise RuntimeError('vvp is unavailable')
    outdir.mkdir(parents=True, exist_ok=False)
    source_paths = [ADMISSION_RTL, RTL, TB, RUNNER]
    source_hashes = {str(path): sha(path) for path in source_paths}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                              text=True, capture_output=True, check=False).stdout.strip()
    worktree = subprocess.run(['git', 'status', '--short', '--untracked-files=all'],
                              cwd=ROOT, text=True, capture_output=True,
                              check=False).stdout.splitlines()
    report = {
        'status': 'RUNNING',
        'started_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'case': 'rkpp_control_page_owner_lifecycle', 'simulator': simulator,
        'source_revision': revision, 'source_worktree_status': worktree,
        'source_hashes_before': source_hashes,
        'seed_policy': 'not applicable: deterministic AXI-Lite lifecycle sequence',
        'scope': 'RKPP CSR bank selection, start-kind 3 ownership, readiness rejection, success ACK and held fault; no memory DMA or hardware.',
        'hardware_accessed': False, 'commands': [],
    }
    save_report(outdir, report)
    build: Path | None = None
    try:
        if simulator == 'iverilog':
            binary = outdir / 'tb.vvp'
            build = binary
            run_logged('compile', [compiler, '-g2012', '-Wall', '-s',
                                   'tb_ppu_c3_job_control', '-o', str(binary),
                                   str(ADMISSION_RTL), str(RTL), str(TB)],
                       outdir, report, 600)
            run_cmd = [shutil.which('vvp'), str(binary)]
            report['tool_version'] = version([compiler, '-V'])
            report['runtime_version'] = version([shutil.which('vvp'), '-V'])
        else:
            mdir = outdir / 'obj'
            build = mdir
            run_logged('compile', [compiler, '--binary', '--timing', '--assert',
                                   '-Wall', '-j', '2', '--top-module',
                                   'tb_ppu_c3_job_control', '--Mdir', str(mdir),
                                   '-o', 'sim', str(ADMISSION_RTL), str(RTL), str(TB)],
                       outdir, report, 600)
            run_cmd = [str(mdir / 'sim')]
            report['tool_version'] = version([compiler, '--version'])
        report['python_version'] = platform.python_version()
        text = run_logged('test', run_cmd, outdir, report, 120)
        if sum(line == PASS_MARKER for line in text.splitlines()) != 1:
            raise RuntimeError('missing unique RKPP control PASS marker')
        report['source_hashes_after'] = {str(path): sha(path) for path in source_paths}
        if report['source_hashes_before'] != report['source_hashes_after']:
            raise RuntimeError('control RTL/testbench changed during simulation')
        report['status'] = 'PASS'
        report['finished_utc'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        report['summary'] = {
            'page': '0x300', 'identity': 'RKPP/0x524b5050', 'dispatch_kind': 3,
            'layout_page_0x400_unchanged': True,
            'not_ready_submit_rejected': True,
            'successful_result_requires_ack': True,
            'fault_result_remains_owned_and_unacknowledgeable': True,
            'hardware_accessed': False,
        }
    except Exception as exc:
        report['status'] = 'FAIL'
        report['failure'] = str(exc)
        report['finished_utc'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        raise
    finally:
        if not keep_build and build is not None:
            if build.is_dir():
                shutil.rmtree(build)
            else:
                build.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        save_report(outdir, report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'), default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    for simulator in simulators:
        outdir = ROOT / 'build/ppu-pooling' / f'c3-job-control-{simulator}-{stamp}'
        try:
            run_one(simulator, outdir, args.keep_build)
        except Exception as exc:
            print(f'FAIL C3 PPU job control {simulator}: {exc}', file=sys.stderr)
            return 1
        print(f'PASS C3 PPU job control {simulator}: RKPP page 0x300, kind 3 owner lifecycle; report={outdir / "report.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
