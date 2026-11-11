#!/usr/bin/env python3
"""Validate the exact captured raw-command profile for C8 minimum pooling."""
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
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ppu.run_pool_min import (  # noqa: E402
    CASE, FIXTURE, fixture_check,
)
from tools.ppu.run_pool_pad1_raw_profile import (  # noqa: E402
    EMITTER_SOURCE, FATAL_RE, POOL_SOURCE, REGISTER_SOURCE, SOURCE_HASHES,
    sha, sha_bytes, tool_version,
)

RTL = ROOT / 'rtl/ppu/rk_ppu_pool_min_raw_profile.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_min_raw_profile.sv'
RUNNER = Path(__file__).resolve()
FILE_NAMES = ('capture.json', 'device_out.bin', 'expected.bin', 'in.bin',
              'job.json', 'out_init.bin', 'regcmd.bin', 'regcmd.txt')
ERROR_MODES = {1: 2, 2: 3, 3: 1, 4: 1, 5: 3, 6: 3,
               7: 1, 8: 2, 9: 3, 10: 2, 11: 2, 12: 2}
PASS_RE = re.compile(r'^PASS ppu_min_raw_profile mode=(?P<mode>\d+) (?P<details>.*)$')


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def load_contract() -> tuple[dict, dict, dict, bytes, bytes]:
    fixture_check()
    for name, path in (('pooling.py', POOL_SOURCE),
                       ('rockchip.py', REGISTER_SOURCE),
                       ('pool.py', EMITTER_SOURCE)):
        if sha(path) != SOURCE_HASHES[name]:
            raise ValueError(f'pinned RK3588 source differs: {name}')
    manifest = json.loads((FIXTURE / 'manifest.json').read_text())
    job = json.loads((FIXTURE / 'job.json').read_text())
    capture = json.loads((FIXTURE / 'capture.json').read_text())
    if set(manifest.get('files', {})) != set(FILE_NAMES):
        raise ValueError('minimum fixture file census differs from the pinned case')
    for name in FILE_NAMES:
        path = FIXTURE / name
        row = manifest['files'][name]
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError(f'minimum fixture provenance mismatch: {name}')
    if (capture.get('case'), capture.get('status'), capture.get('submit_ret')) != (CASE, 'OK', 0):
        raise ValueError('minimum device capture is not successful')
    patches = job.get('patches')
    if patches != [
            {'buffer': 'out', 'kind': 'value32', 'regcmd_index': 13},
            {'buffer': 'in', 'kind': 'value32', 'regcmd_index': 20}]:
        raise ValueError('only the two captured address relocation entries are admitted')
    addresses = capture.get('addresses', {}).get('buffers', {})
    if addresses != {'in': 4096, 'out': 8192}:
        raise ValueError('captured minimum input/output addresses differ')
    raw = (FIXTURE / 'regcmd.bin').read_bytes()
    if len(raw) != 26 * 8 or sha_bytes(raw) != manifest['command_stream']['source_regcmd_sha256']:
        raise ValueError('minimum raw command differs from the 26-QWORD source stream')
    if capture.get('hashes', {}).get('regcmd_source') != sha_bytes(raw):
        raise ValueError('minimum capture does not bind the raw source command')
    patched = bytearray(raw)
    for index, name in ((13, 'out'), (20, 'in')):
        offset = index * 8
        word = int.from_bytes(patched[offset:offset + 8], 'little')
        patched[offset:offset + 8] = (
            (word & ~(0xffffffff << 16)) | (addresses[name] << 16)
        ).to_bytes(8, 'little')
    patched_bytes = bytes(patched)
    expected_hash = manifest['command_stream']['device_patched_regcmd_sha256']
    if sha_bytes(patched_bytes) != expected_hash:
        raise ValueError('QWORD 13/20 relocation does not reproduce captured command')
    if capture['hashes']['command_stream']['sha256'] != sha_bytes(patched_bytes):
        raise ValueError('minimum capture does not bind the relocated command')
    changed = [i for i in range(26)
               if raw[i*8:i*8+8] != patched_bytes[i*8:i*8+8]]
    if changed != [13, 20]:
        raise ValueError(f'address relocation changed unexpected QWORDs: {changed}')
    return manifest, job, capture, raw, patched_bytes


def save_report(outdir: Path, report: dict) -> None:
    (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def run_command(name: str, argv: list[str], outdir: Path, report: dict,
                timeout: int = 180) -> str:
    log = outdir / f'{name}.log'
    row = {'name': name, 'argv': [str(arg) for arg in argv],
           'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(row)
    save_report(outdir, report)
    started = time.monotonic()
    with log.open('w') as stream:
        result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, check=False, timeout=timeout)
    text = log.read_text(errors='replace')
    fatals = [line for line in text.splitlines() if FATAL_RE.search(line)]
    row.update(status='PASS' if result.returncode == 0 and not fatals else 'FAIL',
               returncode=result.returncode,
               seconds=round(time.monotonic() - started, 3),
               fatal_lines=fatals, log_sha256=sha(log),
               warnings=[line for line in text.splitlines()
                         if line.startswith('%Warning') or 'warning:' in line.lower()])
    save_report(outdir, report)
    if result.returncode or fatals:
        raise RuntimeError(f'{name} failed (exit={result.returncode}):\n{text[-5000:]}')
    return text


def run_simulator(simulator: str, outdir: Path, keep_build: bool,
                  contract: tuple[dict, dict, dict, bytes, bytes]) -> dict:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} or its runtime is unavailable')
    manifest, _job, capture, raw, patched = contract
    outdir.mkdir(parents=True, exist_ok=False)
    patched_path = outdir / 'patched_regcmd.bin'
    patched_path.write_bytes(patched)
    inputs = [RTL, TB, RUNNER, ROOT/'tools/ppu/run_pool_min.py',
              ROOT/'tools/ppu/run_pool_pad1_raw_profile.py'] + [
        FIXTURE/name for name in FILE_NAMES] + [POOL_SOURCE, REGISTER_SOURCE, EMITTER_SOURCE]
    before = {str(path): sha(path) for path in inputs}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    report = {
        'status': 'RUNNING', 'started_utc': now(), 'case': CASE,
        'simulator': simulator, 'source_revision': revision,
        'tool_version': tool_version([compiler, '--version'] if simulator == 'verilator'
                                     else [compiler, '-V']),
        'runtime_version': tool_version([runtime, '-V']) if runtime else None,
        'python_version': platform.python_version(), 'source_hashes_before': before,
        'scope': 'Strict 26-QWORD minimum-pooling raw-command profile; no DMA/compute/hardware in this profile-only test.',
        'hardware_accessed': False, 'vivado_executed': False, 'bitstream_emitted': False,
        'fixture': {'raw_command_sha256': sha_bytes(raw),
                    'patched_command_sha256': sha_bytes(patched),
                    'capture_json_sha256': manifest['device_capture']['capture_json_sha256'],
                    'device_output_sha256': manifest['comparison']['device_output_sha256'],
                    'source_base': capture['addresses']['buffers']['in'],
                    'destination_base': capture['addresses']['buffers']['out']},
        'expected_contract': {'qwords': 26, 'relocatable_qwords': [13, 20],
                              'input_bytes': 256, 'output_bytes': 144,
                              'method_qword': 8, 'method_value': 18,
                              'unsupported_fields_fail': True},
        'commands': [], 'runs': [],
    }
    save_report(outdir, report)
    build: Path | None = None
    try:
        if simulator == 'iverilog':
            build = outdir/'tb.vvp'
            prefix = [runtime, str(build)]
            run_command('compile', [compiler, '-g2012', '-Wall', '-s',
                                    'tb_ppu_pool_min_raw_profile', '-o', str(build),
                                    str(RTL), str(TB)], outdir, report, 600)
        else:
            build = outdir/'obj'
            run_command('compile', [compiler, '--binary', '--timing', '--assert', '-Wall',
                                    '-j', '2', '--top-module', 'tb_ppu_pool_min_raw_profile',
                                    '--Mdir', str(build), '-o', 'sim', str(RTL), str(TB)],
                        outdir, report, 600)
            prefix = [str(build/'sim')]
        for mode in range(13):
            error = ERROR_MODES.get(mode, 0)
            output = run_command(f'mode-{mode}', prefix +
                                 [f'+COMMAND_BIN={patched_path}', f'+MODE={mode}',
                                  f'+EXPECT_ERROR={error}'], outdir, report)
            markers = [match for line in output.splitlines()
                       if (match := PASS_RE.match(line))]
            if len(markers) != 1 or int(markers[0].group('mode')) != mode:
                raise RuntimeError(f'mode {mode} did not produce one unique PASS marker')
            details = markers[0].group('details')
            if mode == 0 and details != (
                    'accepted_words=26 src=00001000 dst=00002000 input_bytes=256 '
                    'output_bytes=144 profile_stall_cycles=3'):
                raise RuntimeError(f'minimum profile geometry differs: {details}')
            if mode and f'rejected_code={error}' not in details:
                raise RuntimeError(f'negative mode {mode} returned the wrong code: {details}')
            report['runs'].append({'mode': mode, 'expected_error': error, 'details': details})
            save_report(outdir, report)
        after = {str(path): sha(path) for path in inputs}
        if before != after:
            raise RuntimeError('minimum profile RTL, runner or fixture changed during simulation')
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
        contract = load_contract()
    except Exception as exc:
        print(f'CONTRACT FAIL: {exc}', file=sys.stderr)
        return 1
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for simulator in simulators:
        outdir = ROOT/'build/ppu-pooling'/f'min-raw-profile-{simulator}-{stamp}'
        try:
            run_simulator(simulator, outdir, args.keep_build, contract)
        except Exception as exc:
            print(f'FAIL minimum raw profile {simulator}: {exc}', file=sys.stderr)
            return 1
        print(f'PASS minimum raw profile {simulator}: 26 QWORDs, relocations [13,20], '
              f'{len(ERROR_MODES)} negative controls; report={outdir/"report.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
