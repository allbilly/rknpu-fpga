#!/usr/bin/env python3
"""Validate the exact captured raw-command profile for C8 MAX+INDEX."""
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
sys.path.insert(0, str(ROOT))

from tools.ppu.run_pool_index import (  # noqa: E402
    CASE, FIXTURE, FIXTURE_FILES, MANIFEST, fixture_check, now, sha, sha_bytes,
    tool_version,
)

RTL = ROOT / 'rtl/ppu/rk_ppu_pool_index_raw_profile.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_index_raw_profile.sv'
RUNNER = Path(__file__).resolve()
FATAL_RE = re.compile(r'(?:%Fatal|\bFATAL\b|\$fatal)', re.IGNORECASE)
ERROR_MODES = {1: 2, 2: 3, 3: 1, 4: 1, 5: 3, 6: 3, 7: 1, 8: 3, 9: 3, 10: 2}
PASS_RE = re.compile(r'^PASS ppu_index_raw_profile mode=(?P<mode>\d+) (?P<details>.*)$')


def load_contract() -> tuple[dict, dict, dict, bytes, bytes]:
    fixture_check()
    manifest = json.loads(MANIFEST.read_text())
    job = json.loads((FIXTURE / 'job.json').read_text())
    capture = json.loads((FIXTURE / 'capture.json').read_text())
    raw = (FIXTURE / 'regcmd.bin').read_bytes()
    if len(raw) != 26 * 8 or sha_bytes(raw) != manifest['source']['regcmd_sha256']:
        raise ValueError('MAX+INDEX raw stream differs from the pinned 26-QWORD capture')
    if job.get('patches') != [
            {'buffer': 'out', 'kind': 'value32', 'regcmd_index': 13},
            {'buffer': 'in', 'kind': 'value32', 'regcmd_index': 20}]:
        raise ValueError('only captured address relocations at QWORDs 13 and 20 are admitted')
    addresses = capture.get('addresses', {}).get('buffers', {})
    if addresses != {'in': 4096, 'out': 8192}:
        raise ValueError('captured MAX+INDEX input/output addresses differ')
    patched = bytearray(raw)
    for index, name in ((13, 'out'), (20, 'in')):
        offset = index * 8
        word = int.from_bytes(patched[offset:offset + 8], 'little')
        patched[offset:offset + 8] = (
            (word & ~(0xffffffff << 16)) | (addresses[name] << 16)
        ).to_bytes(8, 'little')
    patched_bytes = bytes(patched)
    if sha_bytes(patched_bytes) != manifest['command_stream']['device_patched_regcmd_sha256']:
        raise ValueError('QWORD 13/20 relocation does not reproduce device command')
    if capture.get('hashes', {}).get('command_stream', {}).get('sha256') != sha_bytes(patched_bytes):
        raise ValueError('capture metadata does not bind relocated command')
    changed = [i for i in range(26) if raw[i*8:i*8+8] != patched_bytes[i*8:i*8+8]]
    if changed != [13, 20]:
        raise ValueError(f'address relocation changed unexpected QWORDs: {changed}')
    return manifest, job, capture, raw, patched_bytes


def save_report(outdir: Path, report: dict) -> None:
    (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def run_one(name: str, argv: list[str], outdir: Path, report: dict) -> str:
    log = outdir / f'{name}.log'
    row = {'name': name, 'argv': [str(item) for item in argv],
           'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(row)
    save_report(outdir, report)
    with log.open('w') as stream:
        result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, check=False, timeout=600)
    text = log.read_text(errors='replace')
    fatals = [line for line in text.splitlines() if FATAL_RE.search(line)]
    row.update(returncode=result.returncode,
               status='PASS' if result.returncode == 0 and not fatals else 'FAIL',
               fatal_lines=fatals, log_sha256=sha(log),
               warnings=[line for line in text.splitlines()
                         if line.startswith('%Warning') or 'warning:' in line.lower()])
    save_report(outdir, report)
    if result.returncode or fatals:
        raise RuntimeError(f'{name} failed: {text[-5000:]}')
    return text


def run_simulator(simulator: str, outdir: Path, keep_build: bool,
                  fixture: tuple[dict, dict, dict, bytes, bytes]) -> dict:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} or its runtime is unavailable')
    manifest, _job, capture, raw, patched = fixture
    outdir.mkdir(parents=True, exist_ok=False)
    patched_path = outdir / 'patched_regcmd.bin'
    patched_path.write_bytes(patched)
    inputs = [RTL, TB, RUNNER, *[FIXTURE / name for name in FIXTURE_FILES]]
    before = {str(path): sha(path) for path in inputs}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    status = subprocess.run(['git', 'status', '--short', '--untracked-files=all'], cwd=ROOT,
                            text=True, capture_output=True, check=True).stdout.splitlines()
    report = {
        'status': 'RUNNING', 'started_utc': now(), 'case': CASE,
        'simulator': simulator, 'source_revision': revision,
        'source_worktree_status': status,
        'tool_version': tool_version([compiler, '--version'] if simulator == 'verilator'
                                     else [compiler, '-V']),
        'runtime_version': tool_version([runtime, '-V']) if runtime else None,
        'python_version': platform.python_version(), 'source_hashes_before': before,
        'scope': 'Strict captured 26-QWORD C8 MAX+INDEX profile only; no DMA, compute or hardware in this test.',
        'hardware_accessed': False, 'vivado_executed': False, 'bitstream_emitted': False,
        'fixture': {'raw_command_sha256': sha_bytes(raw),
                    'patched_command_sha256': sha_bytes(patched),
                    'capture_json_sha256': manifest['device_capture']['capture_json_sha256'],
                    'device_output_sha256': manifest['comparison']['device_output_sha256'],
                    'source_base': capture['addresses']['buffers']['in'],
                    'destination_base': capture['addresses']['buffers']['out']},
        'expected_contract': {'qwords': 26, 'relocatable_qwords': [13, 20],
                              'input_bytes': 64, 'output_span_bytes': 48,
                              'value_offset': 0, 'index_offset': 32,
                              'unique_maximum_per_channel': True},
        'commands': [], 'runs': [],
    }
    save_report(outdir, report)
    build: Path | None = None
    try:
        if simulator == 'iverilog':
            build = outdir / 'tb.vvp'
            run_one('compile', [compiler, '-g2012', '-Wall', '-s',
                                'tb_ppu_pool_index_raw_profile', '-o', str(build),
                                str(RTL), str(TB)], outdir, report)
            prefix = [runtime, str(build)]
        else:
            build = outdir / 'obj'
            run_one('compile', [compiler, '--binary', '--timing', '--assert', '-Wall',
                                '-j', '2', '--top-module', 'tb_ppu_pool_index_raw_profile',
                                '--Mdir', str(build), '-o', 'sim', str(RTL), str(TB)],
                    outdir, report)
            prefix = [str(build / 'sim')]
        for mode in range(11):
            expected_error = ERROR_MODES.get(mode, 0)
            text = run_one(f'mode-{mode}', prefix +
                           [f'+COMMAND_BIN={patched_path}', f'+MODE={mode}',
                            f'+EXPECT_ERROR={expected_error}'], outdir, report)
            matches = [match for line in text.splitlines() if (match := PASS_RE.match(line))]
            if len(matches) != 1 or int(matches[0].group('mode')) != mode:
                raise RuntimeError(f'mode {mode} did not produce one unique PASS marker')
            details = matches[0].group('details')
            if mode == 0 and details != (
                    'accepted_words=26 src=00001000 dst=00002000 input_bytes=64 '
                    'output_span_bytes=48 profile_stall_cycles=3'):
                raise RuntimeError(f'valid profile geometry differs: {details}')
            if mode and f'rejected_code={expected_error}' not in details:
                raise RuntimeError(f'mode {mode} returned an unexpected error: {details}')
            report['runs'].append({'mode': mode, 'expected_error': expected_error,
                                   'details': details})
            save_report(outdir, report)
        after = {str(path): sha(path) for path in inputs}
        if before != after:
            raise RuntimeError('profile RTL, runner or fixture changed during simulation')
        report.update(status='PASS', finished_utc=now(), source_hashes_after=after,
                      summary={'valid_profile': True, 'negative_controls': len(ERROR_MODES),
                               'only_relocations': [13, 20], 'hardware_accessed': False})
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
        save_report(outdir, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'), default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    try:
        fixture = load_contract()
    except Exception as exc:
        print(f'CONTRACT FAIL: {exc}', file=sys.stderr)
        return 1
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for simulator in simulators:
        outdir = ROOT / 'build/ppu-pooling' / f'index-raw-profile-{simulator}-{stamp}'
        try:
            run_simulator(simulator, outdir, args.keep_build, fixture)
        except Exception as exc:
            print(f'FAIL MAX+INDEX raw profile {simulator}: {exc}', file=sys.stderr)
            return 1
        print(f'PASS MAX+INDEX raw profile {simulator}: 26 QWORDs, relocations [13,20], '
              f'{len(ERROR_MODES)} negative controls; report={outdir/"report.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
