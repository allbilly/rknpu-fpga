#!/usr/bin/env python3
"""Validate the exact captured raw-command profile for padded C8 max pooling."""
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
CASE = 'fp16_max_k2s1_pad1_neg_c8_h2w2'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures' / CASE
RTL = ROOT / 'rtl/ppu/rk_ppu_pool_pad1_raw_profile.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_pad1_raw_profile.sv'
RUNNER = Path(__file__).resolve()
POOL_SOURCE = Path('/home/fedora/rk3588/examples/expt/pooling.py')
REGISTER_SOURCE = Path('/home/fedora/rk3588/experimental/rockchip.py')
EMITTER_SOURCE = Path('/home/fedora/rk3588/experimental/pool.py')
SOURCE_HASHES = {
    'pooling.py': '2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e',
    'rockchip.py': '6b5630f962e2f38dc96936ad8c39bb374124584bd68a136f34db8c92af421e4d',
    'pool.py': 'dfe39e86686d1133e5731ecbc7056ae7d10163bc9af9db52aacf92f1f9482d70',
}
FILE_NAMES = ('capture.json', 'device_out.bin', 'in.bin', 'job.json',
              'out_init.bin', 'regcmd.bin', 'regcmd.txt')
ERROR_MODES = {1: 2, 2: 3, 3: 1, 4: 1, 5: 3, 6: 3,
               7: 1, 8: 2, 9: 3, 10: 2, 11: 2, 12: 2}
FATAL_RE = re.compile(r'(?:%Fatal|\bFATAL\b|\$fatal)', re.IGNORECASE)
PASS_RE = re.compile(r'^PASS ppu_pad1_raw_profile mode=(?P<mode>\d+) (?P<details>.*)$')


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def tool_version(argv: list[str]) -> str:
    result = subprocess.run(argv, text=True, capture_output=True, check=False, timeout=30)
    return (result.stdout or result.stderr).splitlines()[0]


def load_contract() -> tuple[dict, dict, dict, bytes, bytes]:
    manifest = json.loads((FIXTURE / 'manifest.json').read_text())
    job = json.loads((FIXTURE / 'job.json').read_text())
    capture = json.loads((FIXTURE / 'capture.json').read_text())
    if (manifest.get('case'), manifest.get('status')) != (CASE, 'READY'):
        raise ValueError('wrong padded C8 case or fixture status')
    if set(manifest.get('files', {})) != set(FILE_NAMES):
        raise ValueError('padded C8 fixture file census differs from manifest')
    for name in FILE_NAMES:
        path = FIXTURE / name
        row = manifest['files'][name]
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError(f'padded C8 fixture provenance mismatch: {name}')
    source_evidence = manifest.get('source_evidence', {})
    for name, source, key in (
            ('pooling.py', POOL_SOURCE, 'example_sha256'),
            ('rockchip.py', REGISTER_SOURCE, 'register_header_sha256'),
            ('pool.py', EMITTER_SOURCE, 'raw_emitter_sha256')):
        if source_evidence.get(key) != SOURCE_HASHES[name] or sha(source) != SOURCE_HASHES[name]:
            raise ValueError(f'pinned RK3588 source differs: {name}')
    if (capture.get('case'), capture.get('status'), capture.get('submit_ret')) != (CASE, 'OK', 0):
        raise ValueError('padded C8 device capture is not successful')
    if sha(FIXTURE / 'capture.json') != manifest['device_capture']['capture_json_sha256']:
        raise ValueError('capture JSON hash differs from manifest')
    if sha(FIXTURE / 'job.json') != manifest['command_stream']['job_json_sha256']:
        raise ValueError('job JSON hash differs from manifest')

    raw = (FIXTURE / 'regcmd.bin').read_bytes()
    if len(raw) != 208 or sha_bytes(raw) != manifest['command_stream']['source_regcmd_sha256']:
        raise ValueError('raw command bytes differ from the pinned 26-QWORD stream')
    if capture.get('hashes', {}).get('regcmd_source') != sha_bytes(raw):
        raise ValueError('capture JSON does not bind the original command stream')
    patches = job.get('patches')
    if patches != [
            {'buffer': 'out', 'kind': 'value32', 'regcmd_index': 13},
            {'buffer': 'in', 'kind': 'value32', 'regcmd_index': 20}]:
        raise ValueError('only the two captured address relocation entries are admitted')
    addresses = capture.get('addresses', {}).get('buffers', {})
    if addresses != {'in': 4096, 'out': 8192}:
        raise ValueError('captured padded C8 address map differs')
    buffers = {row['name']: row for row in capture.get('buffers', [])}
    if set(buffers) != {'in', 'out'} or any(
            buffers[name]['dma_address'] != addresses[name] or buffers[name]['size'] != 4096
            for name in ('in', 'out')):
        raise ValueError('captured padded C8 BO allocation map differs')

    patched = bytearray(raw)
    for index, name in ((13, 'out'), (20, 'in')):
        offset = index * 8
        original = int.from_bytes(patched[offset:offset + 8], 'little')
        patched[offset:offset + 8] = (
            (original & ~(0xffffffff << 16)) | (addresses[name] << 16)
        ).to_bytes(8, 'little')
    patched_bytes = bytes(patched)
    if sha_bytes(patched_bytes) != manifest['command_stream']['device_patched_regcmd_sha256']:
        raise ValueError('QWORD 13/20 relocation does not reproduce device command hash')
    if capture.get('hashes', {}).get('command_stream', {}).get('sha256') != sha_bytes(patched_bytes):
        raise ValueError('device capture does not bind the relocated command stream')
    if [index for index in range(26)
            if raw[index*8:index*8+8] != patched_bytes[index*8:index*8+8]] != [13, 20]:
        raise ValueError('relocation modified a non-address QWORD')
    if (addresses['in'] + 64 > 0x100000000 or addresses['out'] + 144 > 0x100000000 or
            addresses['in'] < addresses['out'] + 144 and
            addresses['out'] < addresses['in'] + 64):
        raise ValueError('padded C8 input/output windows overlap or overflow')

    if manifest['ppu'] != {
            'dtype': 'float16', 'method': 'maximum', 'channels': 8,
            'kernel': [2, 2], 'stride': [1, 1], 'padding': [1, 1, 1, 1],
            'padding_value_fp16_bits': 'fc00', 'index_en': False, 'use_cnt': 0,
            'in_shape': [2, 2], 'out_shape': [3, 3],
            'input_value_contract': 'The 32 captured input halfwords are finite negative FP16 values. No general MAX special-value policy is inferred.'}:
        raise ValueError('unsupported padded C8 PPU profile fields')
    layout = manifest['layout']
    if (layout['atom_bytes'], layout['atom_channels'], layout['input']['line_stride_bytes'],
            layout['input']['surface_stride_bytes'], layout['input']['logical_bytes'],
            layout['output']['line_stride_bytes'], layout['output']['surface_stride_bytes'],
            layout['output']['value_bytes']) != (16, 8, 32, 64, 64, 48, 144, 144):
        raise ValueError('padded C8 layout differs from the capture')
    input_bo = (FIXTURE / 'in.bin').read_bytes()
    for offset in range(0, 64, 2):
        word = int.from_bytes(input_bo[offset:offset + 2], 'little')
        if not (word & 0x8000) or (word & 0x7fff) == 0 or ((word >> 10) & 0x1f) == 0x1f:
            raise ValueError(f'input lane at byte {offset} is not finite negative FP16')
    device = (FIXTURE / 'device_out.bin').read_bytes()
    initial = (FIXTURE / 'out_init.bin').read_bytes()
    if (len(device) != 4096 or len(initial) != 4096 or device[144:] != initial[144:] or
            manifest['comparison']['device_output_sha256'] != sha_bytes(device)):
        raise ValueError('padded C8 device output BO/tail contract differs')
    return manifest, job, capture, raw, patched_bytes


def save_report(outdir: Path, report: dict) -> None:
    (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def run_command(name: str, argv: list[str], outdir: Path, report: dict, timeout: int = 180) -> str:
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
               returncode=result.returncode, seconds=round(time.monotonic()-started, 3),
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
    source_paths = [RTL, TB, RUNNER, FIXTURE/'manifest.json', FIXTURE/'capture.json',
                    FIXTURE/'job.json', FIXTURE/'regcmd.bin', FIXTURE/'regcmd.txt',
                    FIXTURE/'in.bin', FIXTURE/'out_init.bin', FIXTURE/'device_out.bin',
                    POOL_SOURCE, REGISTER_SOURCE, EMITTER_SOURCE]
    hashes_before = {str(path): sha(path) for path in source_paths}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    report = {
        'status': 'RUNNING', 'started_utc': now(), 'case': CASE, 'simulator': simulator,
        'source_revision': revision,
        'tool_version': tool_version([compiler, '--version'] if simulator == 'verilator'
                                     else [compiler, '-V']),
        'runtime_version': tool_version([runtime, '-V']) if runtime else None,
        'python_version': platform.python_version(), 'source_hashes_before': hashes_before,
        'scope': 'Strict 26-QWORD padded-C8 raw-command validator; no DMA, pooling compute, Vivado or hardware access.',
        'hardware_accessed': False, 'vivado_executed': False, 'bitstream_emitted': False,
        'fixture': {'raw_command_sha256': sha_bytes(raw),
                    'patched_command_sha256': sha_bytes(patched),
                    'capture_json_sha256': manifest['device_capture']['capture_json_sha256'],
                    'device_output_sha256': manifest['comparison']['device_output_sha256'],
                    'source_base': capture['addresses']['buffers']['in'],
                    'destination_base': capture['addresses']['buffers']['out']},
        'expected_contract': {'qwords': 26, 'relocatable_qwords': [13, 20],
                              'input_bytes': 64, 'output_bytes': 144,
                              'unsupported_fields_fail': True},
        'commands': [], 'runs': [],
    }
    save_report(outdir, report)
    build_path: Path | None = None
    try:
        if simulator == 'iverilog':
            build_path = outdir / 'tb.vvp'
            run_command('compile', [compiler, '-g2012', '-Wall', '-s',
                                    'tb_ppu_pool_pad1_raw_profile', '-o', str(build_path),
                                    str(RTL), str(TB)], outdir, report, 600)
            prefix = [runtime, str(build_path)]
        else:
            build_path = outdir / 'obj'
            run_command('compile', [compiler, '--binary', '--timing', '--assert', '-Wall',
                                    '-j', '2', '--top-module', 'tb_ppu_pool_pad1_raw_profile',
                                    '--Mdir', str(build_path), '-o', 'sim', str(RTL), str(TB)],
                        outdir, report, 600)
            prefix = [str(build_path/'sim')]
        for mode in range(13):
            expected_error = ERROR_MODES.get(mode, 0)
            output = run_command(f'mode-{mode}', prefix +
                                 [f'+COMMAND_BIN={patched_path}', f'+MODE={mode}',
                                  f'+EXPECT_ERROR={expected_error}'], outdir, report)
            markers = [match for line in output.splitlines()
                       if (match := PASS_RE.match(line))]
            if len(markers) != 1 or int(markers[0].group('mode')) != mode:
                raise RuntimeError(f'mode {mode} did not produce one unique PASS marker')
            details = markers[0].group('details')
            if mode == 0 and details != (
                    'accepted_words=26 src=00001000 dst=00002000 input_bytes=64 '
                    'output_bytes=144 profile_stall_cycles=3'):
                raise RuntimeError(f'valid padded C8 profile fields differ: {details}')
            if mode and f'rejected_code={expected_error}' not in details:
                raise RuntimeError(f'negative mode {mode} error code differs: {details}')
            report['runs'].append({'mode': mode, 'expected_error': expected_error,
                                   'details': details})
            save_report(outdir, report)
        hashes_after = {str(path): sha(path) for path in source_paths}
        if hashes_before != hashes_after:
            raise RuntimeError('RTL, runner or capture fixture changed during simulation')
        report['source_hashes_after'] = hashes_after
        report.update(status='PASS', finished_utc=now(),
                      summary={'valid_profile': True, 'negative_controls': len(ERROR_MODES),
                               'only_relocations': [13, 20], 'hardware_accessed': False})
    except Exception as exc:
        report.update(status='FAIL', finished_utc=now(), failure=str(exc))
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
        contract = load_contract()
    except Exception as exc:
        print(f'CONTRACT FAIL: {exc}', file=sys.stderr)
        return 1
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for simulator in simulators:
        outdir = ROOT / 'build/ppu-pooling' / f'pad1-raw-profile-{simulator}-{stamp}'
        try:
            run_simulator(simulator, outdir, args.keep_build, contract)
        except Exception as exc:
            print(f'FAIL padded C8 raw profile {simulator}: {exc}', file=sys.stderr)
            return 1
        print(f'PASS padded C8 raw profile {simulator}: 26 QWORDs, two address relocations, '
              f'12 negative controls; report={outdir/"report.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
