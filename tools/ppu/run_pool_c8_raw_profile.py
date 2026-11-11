#!/usr/bin/env python3
"""Replay and validate the captured C8 PPU raw-command profile."""
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

CASE = 'fp16_max_k2s1_valid_c8_h4w4'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures' / CASE
MANIFEST = FIXTURE / 'manifest.json'
JOB = FIXTURE / 'job.json'
CAPTURE = FIXTURE / 'capture.json'
RAW_COMMAND = FIXTURE / 'regcmd.bin'
RTL = ROOT / 'rtl/ppu/rk_ppu_pool_c8_raw_profile.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_c8_raw_profile.sv'
POOL_SOURCE = Path('/home/fedora/rk3588/examples/expt/pooling.py')
REGISTER_SOURCE = Path('/home/fedora/rk3588/experimental/rockchip.py')
EMITTER_SOURCE = Path('/home/fedora/rk3588/experimental/pool.py')
TOP = 'tb_ppu_pool_c8_raw_profile'
FILE_NAMES = ('capture.json', 'device_out.bin', 'in.bin', 'job.json',
              'out_init.bin', 'regcmd.bin', 'regcmd.txt')
SOURCE_HASHES = {
    'pooling.py': '2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e',
    'rockchip.py': '6b5630f962e2f38dc96936ad8c39bb374124584bd68a136f34db8c92af421e4d',
    'pool.py': 'dfe39e86686d1133e5731ecbc7056ae7d10163bc9af9db52aacf92f1f9482d70',
}
ERROR_MODES = {1: 2, 2: 3, 3: 1, 4: 1, 5: 3,
               6: 3, 7: 1, 8: 2, 9: 3, 10: 2}
FATAL_RE = re.compile(r'(?:%Fatal|\bFATAL\b|\$fatal)', re.IGNORECASE)
PASS_RE = re.compile(r'^PASS ppu_c8_raw_profile mode=(?P<mode>\d+) (?P<details>.*)$')


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def version(argv: list[str]) -> str:
    result = subprocess.run(argv, text=True, capture_output=True,
                            check=False, timeout=30)
    return (result.stdout or result.stderr).splitlines()[0]


def load_contract() -> tuple[dict, dict, dict, bytes, bytes]:
    manifest = json.loads(MANIFEST.read_text())
    job = json.loads(JOB.read_text())
    capture = json.loads(CAPTURE.read_text())
    if manifest.get('case') != CASE or manifest.get('status') != 'READY_CAPTURE_BOUNDED_CANDIDATE':
        raise ValueError('wrong C8 case or fixture status')
    if set(manifest.get('files', {})) != set(FILE_NAMES):
        raise ValueError('C8 fixture file census differs from the manifest')
    for name in FILE_NAMES:
        path = FIXTURE / name
        row = manifest['files'][name]
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError(f'C8 fixture provenance mismatch: {name}')
    if sha(POOL_SOURCE) != SOURCE_HASHES['pooling.py']:
        raise ValueError('pooling.py source hash changed')
    if sha(REGISTER_SOURCE) != SOURCE_HASHES['rockchip.py']:
        raise ValueError('PPU register-header source hash changed')
    if sha(EMITTER_SOURCE) != SOURCE_HASHES['pool.py']:
        raise ValueError('raw QWORD emitter source hash changed')
    if (capture.get('case'), capture.get('status'), capture.get('submit_ret')) != (CASE, 'OK', 0):
        raise ValueError('device capture is not a successful C8 run')
    if sha(CAPTURE) != manifest['device_capture']['capture_json_sha256']:
        raise ValueError('capture JSON hash differs from manifest')

    raw = RAW_COMMAND.read_bytes()
    if len(raw) != 26 * 8 or sha_bytes(raw) != manifest['command_stream']['source_regcmd_sha256']:
        raise ValueError('captured C8 command stream size/hash differs')
    if capture['hashes']['regcmd_source'] != sha_bytes(raw):
        raise ValueError('capture metadata does not bind original C8 QWORD bytes')
    expected_patches = [
        {'buffer': 'out', 'kind': 'value32', 'regcmd_index': 13},
        {'buffer': 'in', 'kind': 'value32', 'regcmd_index': 20},
    ]
    if job.get('patches') != expected_patches:
        raise ValueError('C8 relocation table is not exactly QWORDs 13 and 20')
    addresses = capture.get('addresses', {}).get('buffers', {})
    if addresses != {'in': 4096, 'out': 8192}:
        raise ValueError('C8 captured address map differs from pinned buffers')
    captured_buffers = {row['name']: row for row in capture.get('buffers', [])}
    if set(captured_buffers) != {'in', 'out'} or any(
            captured_buffers[name]['size'] != 4096 or
            captured_buffers[name]['dma_address'] != addresses[name]
            for name in ('in', 'out')):
        raise ValueError('C8 captured BO allocation map/size differs')
    patched = bytearray(raw)
    patch_values = []
    for index, name in ((13, 'out'), (20, 'in')):
        start = index * 8
        before = int.from_bytes(patched[start:start+8], 'little')
        after = (before & ~(0xffffffff << 16)) | (addresses[name] << 16)
        patched[start:start+8] = after.to_bytes(8, 'little')
        patch_values.append({'regcmd_index': index, 'buffer': name,
                             'address': addresses[name], 'before': before, 'after': after})
    patched_bytes = bytes(patched)
    if sha_bytes(patched_bytes) != manifest['command_stream']['device_patched_regcmd_sha256']:
        raise ValueError('only the two declared relocations do not reproduce capture command hash')
    if capture['hashes']['command_stream']['sha256'] != sha_bytes(patched_bytes):
        raise ValueError('capture command hash differs from patched raw stream')
    if (addresses['in'] + 256 > 0x100000000 or addresses['out'] + 144 > 0x100000000 or
            addresses['in'] < addresses['out'] + 144 and
            addresses['out'] < addresses['in'] + 256):
        raise ValueError('C8 input/output windows overlap or overflow')

    ppu = manifest['ppu']
    if ppu != {
            'dtype': 'float16', 'method': 'maximum', 'method_selector': 1,
            'channels': 8, 'kernel': [2, 2], 'stride': [1, 1],
            'padding': [0, 0, 0, 0], 'index_en': False, 'use_cnt': 0,
            'in_shape': [4, 4], 'out_shape': [3, 3]}:
        raise ValueError('unsupported C8 PPU mode/shape fields')
    layout = manifest['layout']
    if (layout['atom_bytes'], layout['atom_channels'],
            layout['input']['line_stride_bytes'], layout['input']['surface_stride_bytes'],
            layout['input']['logical_bytes'], layout['input']['buffer_bytes'],
            layout['output']['line_stride_bytes'], layout['output']['surface_stride_bytes'],
            layout['output']['value_bytes'], layout['output']['buffer_bytes']) != (
            16, 8, 64, 256, 256, 4096, 48, 144, 144, 4096):
        raise ValueError('C8 captured input/output surface geometry differs')
    comparison = manifest['comparison']
    if comparison['device_output_sha256'] != sha(FIXTURE / 'device_out.bin') or comparison['tolerance'] != 0:
        raise ValueError('C8 complete device-output comparison contract differs')
    return manifest, job, capture, raw, patched_bytes


def save_report(outdir: Path, report: dict) -> None:
    (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def run_logged(name: str, argv: list[str], outdir: Path, report: dict, timeout: int) -> str:
    log = outdir / f'{name}.log'
    row = {'name': name, 'argv': [str(arg) for arg in argv],
           'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(row)
    save_report(outdir, report)
    started = time.monotonic()
    with log.open('w') as stream:
        result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, check=False, timeout=timeout)
    text = log.read_text()
    fatals = [line for line in text.splitlines() if FATAL_RE.search(line)]
    row.update(status='PASS' if result.returncode == 0 and not fatals else 'FAIL',
               returncode=result.returncode, seconds=round(time.monotonic()-started, 3),
               fatal_lines=fatals, log_sha256=sha(log),
               warnings=[line for line in text.splitlines()
                         if line.startswith('%Warning') or 'warning:' in line.lower()])
    save_report(outdir, report)
    if result.returncode or fatals:
        raise RuntimeError(f'{name} failed (exit={result.returncode}):\n{text[-5000:]}')
    return text


def run_simulator(simulator: str, outdir: Path, keep_build: bool, fixture_data: tuple) -> dict:
    compiler = shutil.which(simulator)
    if not compiler or (simulator == 'iverilog' and not shutil.which('vvp')):
        raise RuntimeError(f'{simulator} or its runtime is unavailable')
    manifest, _job, capture, raw, patched = fixture_data
    outdir.mkdir(parents=True, exist_ok=False)
    patched_path = outdir / 'patched_regcmd.bin'
    patched_path.write_bytes(patched)
    tracked = [RTL, TB, Path(__file__).resolve(), MANIFEST, JOB, CAPTURE,
               RAW_COMMAND, POOL_SOURCE, REGISTER_SOURCE, EMITTER_SOURCE]
    tracked += [FIXTURE / name for name in FILE_NAMES]
    hashes_before = {str(path): sha(path) for path in tracked}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                              text=True, capture_output=True, check=True).stdout.strip()
    dirty = subprocess.run(['git', 'status', '--short', '--untracked-files=all'], cwd=ROOT,
                           text=True, capture_output=True, check=True).stdout.splitlines()
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'case': CASE,
        'simulator': simulator, 'source_revision': revision,
        'source_worktree_status': dirty,
        'seed_policy': 'not applicable: deterministic captured QWORD stream and directed controls',
        'scope': 'C8 strict raw-command profile decoder only; DMA and pooling execution are tested separately.',
        'hardware_accessed': False, 'vivado_executed': False, 'bitstream_emitted': False,
        'source_hashes_before': hashes_before,
        'fixture': {'raw_qwords': 26, 'raw_sha256': sha_bytes(raw),
                    'patched_sha256': sha_bytes(patched),
                    'device_output_sha256': manifest['comparison']['device_output_sha256'],
                    'patched_command': str(patched_path.relative_to(ROOT)),
                    'address_relocations': [13, 20],
                    'captured_buffers': capture['addresses']['buffers']},
        'profile_contract': {'input_bytes': 256, 'output_bytes': 144,
                             'input_shape': [4, 4, 8], 'output_shape': [3, 3, 8],
                             'input_line_stride_bytes': 64,
                             'input_surface_stride_bytes': 256,
                             'output_line_stride_bytes': 48,
                             'output_surface_stride_bytes': 144},
        'commands': [], 'runs': [],
    }
    save_report(outdir, report)
    build_path = None
    try:
        if simulator == 'iverilog':
            binary = outdir / 'tb.vvp'
            build_path = binary
            run_logged('compile', [compiler, '-g2012', '-Wall', '-s', TOP,
                                   '-o', str(binary), str(RTL), str(TB)], outdir, report, 600)
            run_prefix = [shutil.which('vvp'), str(binary)]
            report['tool_version'] = version([compiler, '-V'])
            report['runtime_version'] = version([shutil.which('vvp'), '-V'])
        else:
            mdir = outdir / 'obj'
            build_path = mdir
            run_logged('compile', [compiler, '--binary', '--timing', '--assert', '-Wall',
                                   '-j', '2', '--top-module', TOP, '--Mdir', str(mdir),
                                   '-o', 'sim', str(RTL), str(TB)], outdir, report, 600)
            run_prefix = [str(mdir / 'sim')]
            report['tool_version'] = version([compiler, '--version'])
        report['python_version'] = platform.python_version()
        save_report(outdir, report)
        for mode in range(11):
            expected = 0 if mode == 0 else ERROR_MODES[mode]
            text = run_logged(f'mode-{mode}', run_prefix +
                              [f'+COMMAND_BIN={patched_path}', f'+MODE={mode}',
                               f'+EXPECT_ERROR={expected}'], outdir, report, 120)
            markers = [match for line in text.splitlines()
                       if (match := PASS_RE.match(line))]
            if len(markers) != 1 or int(markers[0].group('mode')) != mode:
                raise RuntimeError(f'mode {mode} missing exact PASS marker')
            report['runs'].append({'mode': mode,
                                   'result': 'PASS_PROFILE' if mode == 0 else 'PASS_REJECT',
                                   'details': markers[0].group('details'),
                                   'error_code': expected})
            save_report(outdir, report)
        hashes_after = {str(path): sha(path) for path in tracked}
        if hashes_before != hashes_after:
            raise RuntimeError('C8 profile RTL, runner, source or fixture changed during tests')
        report['source_hashes_after'] = hashes_after
        report['status'] = 'PASS'
        report['finished_utc'] = utc_now()
        report['summary'] = {'valid_qwords': 26, 'only_address_qwords_relocated': [13, 20],
                             'negative_controls': 10, 'dma_executed': False,
                             'full_bo_compared': False, 'hardware_accessed': False}
    except Exception as exc:
        report['status'] = 'FAIL'
        report['failure'] = str(exc)
        report['finished_utc'] = utc_now()
        raise
    finally:
        if not keep_build and build_path is not None:
            if build_path.is_dir():
                shutil.rmtree(build_path)
            else:
                build_path.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        save_report(outdir, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'), default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    try:
        fixture_data = load_contract()
    except Exception as exc:
        print(f'CONTRACT FAIL: {exc}', file=sys.stderr)
        return 1
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for simulator in simulators:
        outdir = ROOT / 'build/ppu-pooling' / f'c8-raw-profile-{simulator}-{stamp}'
        try:
            run_simulator(simulator, outdir, args.keep_build, fixture_data)
        except Exception as exc:
            print(f'FAIL C8 raw profile {simulator}: {exc}', file=sys.stderr)
            return 1
        print(f'PASS C8 raw profile {simulator}: 26 captured QWORDs, 10 strict negative controls; '
              f'report={outdir / "report.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
