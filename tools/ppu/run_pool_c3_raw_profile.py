#!/usr/bin/env python3
"""Replay the captured C3 PPU raw command through its strict profile gate.

This validates register/relocation/DMA-profile decoding only. It does not
execute DMA, connect the pooling datapath, access the FPGA, or run RK hardware.
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
import time

ROOT = Path(__file__).resolve().parents[2]
CASE = 'fp16_max_k2s2_c3_tail_h2w2'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures' / CASE
MANIFEST = FIXTURE / 'manifest.json'
JOB = FIXTURE / 'job.json'
CAPTURE = FIXTURE / 'capture.json'
RAW_COMMAND = FIXTURE / 'regcmd.bin'
RTL = ROOT / 'rtl/ppu/rk_ppu_pool_c3_raw_profile.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_c3_raw_profile.sv'
TOP = 'tb_ppu_pool_c3_raw_profile'
POOL_SOURCE = Path('/home/fedora/rk3588/examples/expt/pooling.py')
REGISTER_SOURCE = Path('/home/fedora/rk3588/experimental/rockchip.py')
EMITTER_SOURCE = Path('/home/fedora/rk3588/experimental/pool.py')
FILE_NAMES = (
    'capture.json', 'device_out.bin', 'expected.bin', 'in.bin', 'job.json',
    'out_init.bin', 'regcmd.bin', 'regcmd.txt',
)
SOURCE_HASHES = {
    'pooling.py': '2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e',
    'rockchip.py': '6b5630f962e2f38dc96936ad8c39bb374124584bd68a136f34db8c92af421e4d',
    'pool.py': 'dfe39e86686d1133e5731ecbc7056ae7d10163bc9af9db52aacf92f1f9482d70',
}
ERROR_MODES = {1: 2, 2: 3, 3: 1, 4: 1, 5: 3, 6: 3, 7: 1, 8: 2, 9: 2, 10: 3}
PASS_RE = re.compile(
    r'^PASS ppu_c3_raw_profile mode=(?P<mode>\d+) '
    r'(?:(?:accepted_words=(?P<accepted>\d+) src=(?P<src>[0-9a-fA-F]+) '
    r'dst=(?P<dst>[0-9a-fA-F]+) rdma_line=(?P<line>\d+) '
    r'rdma_surface=(?P<surface>\d+) output_bytes=(?P<output_bytes>\d+) '
    r'profile_stall_cycles=(?P<stalls>\d+))|'
    r'(?:rejected_code=(?P<rejected>\d+) words=(?P<words>\d+) profile=0))$'
)
FATAL_RE = re.compile(r'(?:%Fatal|\bFATAL\b|\$fatal)', re.IGNORECASE)


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
    expected_files = manifest['files']
    if set(expected_files) != set(FILE_NAMES):
        raise ValueError('C3 fixture census differs from the pinned manifest')
    for name in FILE_NAMES:
        path = FIXTURE / name
        if path.stat().st_size != expected_files[name]['bytes'] or sha(path) != expected_files[name]['sha256']:
            raise ValueError(f'fixture provenance mismatch: {name}')

    if (manifest.get('case'), manifest.get('status')) != (
            CASE, 'READY_CAPTURE_BOUNDED_CANDIDATE'):
        raise ValueError('wrong case or candidate status')
    if (capture.get('case'), capture.get('status'), capture.get('submit_ret')) != (
            CASE, 'OK', 0):
        raise ValueError('device capture is not a successful C3 run')
    if sha(POOL_SOURCE) != SOURCE_HASHES['pooling.py']:
        raise ValueError('pooling.py source hash changed')
    if sha(REGISTER_SOURCE) != SOURCE_HASHES['rockchip.py']:
        raise ValueError('PPU register-header source hash changed')
    if sha(EMITTER_SOURCE) != SOURCE_HASHES['pool.py']:
        raise ValueError('raw QWORD emitter source hash changed')

    raw = RAW_COMMAND.read_bytes()
    if len(raw) != 26 * 8:
        raise ValueError('captured command stream must remain 26 QWORDs')
    patches = job.get('patches')
    if patches != [
        {'buffer': 'out', 'kind': 'value32', 'regcmd_index': 13},
        {'buffer': 'in', 'kind': 'value32', 'regcmd_index': 20},
    ]:
        raise ValueError('job relocation table is not the two pinned address patches')
    addresses = capture.get('addresses', {}).get('buffers', {})
    if set(addresses) != {'in', 'out'}:
        raise ValueError('capture DMA address census differs')
    source_base = int(addresses['in'])
    destination_base = int(addresses['out'])
    captured_buffers = {item['name']: item for item in capture.get('buffers', [])}
    if set(captured_buffers) != {'in', 'out'}:
        raise ValueError('capture buffer allocation census differs')
    if any(captured_buffers[name]['dma_address'] != address
           for name, address in (('in', source_base), ('out', destination_base))):
        raise ValueError('capture DMA address map differs from buffer allocation records')
    if any(captured_buffers[name]['size'] != 4096
           for name in ('in', 'out')):
        raise ValueError('captured buffer allocation is not the pinned 4096 bytes')
    if (not 0 < source_base <= 0xffffffff or not 0 < destination_base <= 0xffffffff or
            source_base + 64 > 0x100000000 or
            destination_base + 16 > 0x100000000 or
            source_base < destination_base + 16 and
            destination_base < source_base + 64):
        raise ValueError('capture DMA windows overflow or overlap')
    patched = bytearray(raw)
    patch_rows = []
    for entry, name, address in (
            (patches[0], 'out', destination_base),
            (patches[1], 'in', source_base)):
        qword_index = entry['regcmd_index']
        start = qword_index * 8
        before = int.from_bytes(patched[start:start + 8], 'little')
        after = (before & ~(0xffffffff << 16)) | (address << 16)
        patched[start:start + 8] = after.to_bytes(8, 'little')
        patch_rows.append({'index': qword_index, 'buffer': name,
                           'address': address, 'before': before, 'after': after})

    patched_hash = sha_bytes(bytes(patched))
    if patched_hash != capture['hashes']['command_stream']['sha256']:
        raise ValueError('two source-prescribed relocations do not reproduce captured command stream')
    if capture['hashes']['regcmd_source'] != sha_bytes(raw):
        raise ValueError('capture metadata does not bind original raw command bytes')
    metadata_patches = capture.get('patches', [])
    for row in patch_rows:
        found = [item for item in metadata_patches if item.get('regcmd_index') == row['index']]
        if len(found) != 1 or (found[0].get('before'), found[0].get('after'),
                               found[0].get('dma_address'), found[0].get('buffer')) != (
                               row['before'], row['after'], row['address'], row['buffer']):
            raise ValueError(f'capture relocation metadata mismatch at QWORD {row["index"]}')

    # Fixed, capture-backed geometry is independently represented in the JSON
    # fixture and command words. Do not infer other PPU modes from this profile.
    ppu = manifest['ppu']
    layout = manifest['layout']
    if ppu != {
        'dtype': 'float16', 'method': 'maximum', 'method_selector': 1,
        'channels': 3, 'kernel': [2, 2], 'stride': [2, 2],
        'padding': [0, 0, 0, 0], 'index_en': False, 'use_cnt': 0,
        'in_shape': [2, 2], 'out_shape': [1, 1],
    }:
        raise ValueError('unsupported PPU mode/shape fields')
    if (layout.get('atom_bytes'), layout.get('atom_channels'),
            layout['input']['line_stride_bytes'],
            layout['input']['surface_stride_bytes'], layout['input']['surfaces'],
            layout['input']['logical_channels'], layout['input']['logical_bytes'],
            layout['input']['buffer_bytes'], layout['output']['line_stride_bytes'],
            layout['output']['surface_stride_bytes'], layout['output']['surfaces'],
            layout['output']['value_bytes'], layout['output']['index_bytes'],
            layout['output']['logical_bytes'], layout['output']['buffer_bytes']) != (
            16, 8, 32, 64, 1, 3, 64, 4096, 16, 16, 1, 16, 0, 16, 4096):
        raise ValueError('captured RDMA/output buffer layout changed')
    return manifest, job, capture, raw, bytes(patched)


def save_report(outdir: Path, report: dict) -> None:
    (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def run_logged(name: str, argv: list[str], outdir: Path, report: dict,
               timeout: int) -> str:
    log = outdir / f'{name}.log'
    record = {'name': name, 'argv': [str(x) for x in argv],
              'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(record)
    save_report(outdir, report)
    started = time.monotonic()
    with log.open('w') as stream:
        result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, check=False,
                                timeout=timeout)
    text = log.read_text()
    fatal_lines = [line for line in text.splitlines() if FATAL_RE.search(line)]
    record.update(status='PASS' if result.returncode == 0 and not fatal_lines else 'FAIL',
                  returncode=result.returncode,
                  seconds=round(time.monotonic() - started, 3),
                  log_sha256=sha(log),
                  fatal_lines=fatal_lines,
                  warnings=[line for line in text.splitlines()
                            if line.startswith('%Warning') or 'warning:' in line.lower()])
    save_report(outdir, report)
    if result.returncode or fatal_lines:
        raise RuntimeError(
            f'{name} failed (exit={result.returncode}, fatal_lines={len(fatal_lines)}):\n'
            f'{text[-5000:]}')
    return text


def run_simulator(simulator: str, outdir: Path, keep_build: bool,
                  fixture_data: tuple) -> dict:
    compiler = shutil.which(simulator)
    if not compiler:
        raise RuntimeError(f'{simulator} is unavailable')
    if simulator == 'iverilog' and not shutil.which('vvp'):
        raise RuntimeError('vvp is unavailable')
    manifest, job, capture, raw, patched = fixture_data
    outdir.mkdir(parents=True, exist_ok=False)
    patched_path = outdir / 'patched_regcmd.bin'
    patched_path.write_bytes(patched)
    paths = [RTL, TB, Path(__file__).resolve(), MANIFEST, JOB, CAPTURE,
             RAW_COMMAND, POOL_SOURCE, REGISTER_SOURCE, EMITTER_SOURCE]
    paths += [FIXTURE / name for name in FILE_NAMES]
    hashes_before = {str(path): sha(path) for path in paths}
    source_revision = subprocess.run(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
        capture_output=True, check=False).stdout.strip()
    worktree_status = subprocess.run(
        ['git', 'status', '--short', '--untracked-files=all'], cwd=ROOT,
        text=True, capture_output=True, check=False).stdout.splitlines()
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'case': CASE,
        'simulator': simulator,
        'source_revision': source_revision,
        'source_worktree_status': worktree_status,
        'seed_policy': 'not applicable: deterministic raw-stream replay and fixed negative controls',
        'scope': 'RTL raw-command/profile decoder only; no PPU datapath, memory DMA, K8 top, FPGA or RK execution.',
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'source_hashes_before': hashes_before,
        'fixture': {'manifest': str(MANIFEST.relative_to(ROOT)),
                    'source_regcmd_sha256': sha_bytes(raw),
                    'patched_regcmd_sha256': sha_bytes(patched),
                    'patched_regcmd': str(patched_path.relative_to(ROOT)),
                    'patches': [
                        {'index': 13, 'buffer': 'out', 'address': capture['addresses']['buffers']['out']},
                        {'index': 20, 'buffer': 'in', 'address': capture['addresses']['buffers']['in']},
                    ],
                    'captured_device_output_sha256': capture['hashes']['outputs']['out']['sha256']},
        'register_contract': {
            'qwords': 26, 'target_offsets_checked_exactly': True,
            'address_relocations': [13, 20], 'final_trigger': {'target': '0x0081', 'offset': '0x0008', 'value': '0x00000060'},
            'input': {'shape': [2, 2, 3], 'atom_bytes': 16, 'line_stride_bytes': 32,
                      'surface_stride_bytes': 64, 'transfer_bytes': 64,
                      'rdma_format': 2},
            'pool': {'method': 'maximum', 'method_selector': 1, 'flying': True,
                     'kernel': [2, 2], 'stride': [2, 2],
                     'padding': [0, 0, 0, 0], 'index_en': False, 'use_cnt': 0},
            'output': {'shape': [1, 1, 3], 'physical_lanes': 8,
                       'data_format_raw': '0x00000012',
                       'surface_stride_bytes': 16, 'value_bytes': 16,
                       'write_bytes': 16, 'misc_ctrl_raw': '0x00000003',
                       'buffer_bytes': 4096},
        },
        'commands': [], 'runs': [],
    }
    save_report(outdir, report)
    build_path = None
    try:
        if simulator == 'iverilog':
            binary = outdir / 'tb.vvp'
            build_path = binary
            run_logged('compile', [compiler, '-g2012', '-Wall', '-s', TOP,
                                   '-o', str(binary), str(RTL), str(TB)],
                       outdir, report, 600)
            run_prefix = [shutil.which('vvp'), str(binary)]
            report['tool_version'] = version([compiler, '-V'])
            report['runtime_version'] = version([shutil.which('vvp'), '-V'])
        else:
            mdir = outdir / 'obj'
            build_path = mdir
            run_logged('compile', [compiler, '--binary', '--timing', '--assert',
                                   '-Wall', '-j', '2', '--top-module', TOP,
                                   '--Mdir', str(mdir), '-o', 'sim', str(RTL), str(TB)],
                       outdir, report, 600)
            binary = mdir / 'sim'
            run_prefix = [str(binary)]
            report['tool_version'] = version([compiler, '--version'])
        report['python_version'] = platform.python_version()
        save_report(outdir, report)

        report['runs'] = []
        for mode in range(11):
            expected = 0 if mode == 0 else ERROR_MODES[mode]
            text = run_logged(
                f'mode-{mode}',
                run_prefix + [f'+COMMAND_BIN={patched_path}', f'+MODE={mode}',
                              f'+EXPECT_ERROR={expected}'],
                outdir, report, 120)
            markers = [match.groupdict() for line in text.splitlines()
                       if (match := PASS_RE.match(line))]
            if len(markers) != 1 or int(markers[0]['mode']) != mode:
                raise RuntimeError(f'mode {mode} missing exact PASS marker')
            result = markers[0]
            if mode == 0:
                if (result['accepted'], result['src'].lower(), result['dst'].lower(),
                        result['line'], result['surface'], result['output_bytes'], result['stalls']) != (
                        '26', '00001000', '00002000', '32', '64', '16', '3'):
                    raise RuntimeError(f'valid-profile results differ: {result!r}')
                report['runs'].append({'mode': mode, 'result': 'PASS_PROFILE',
                                       'accepted_qwords': 26, 'error_code': 0,
                                       'profile_backpressure_cycles': 3})
            else:
                if int(result['rejected']) != expected:
                    raise RuntimeError(f'mode {mode}: rejected code {result["rejected"]} != {expected}')
                report['runs'].append({'mode': mode, 'result': 'PASS_REJECT',
                                       'rejected_error_code': expected,
                                       'accepted_qwords_before_reject': int(result['words'])})
            save_report(outdir, report)

        hashes_after = {str(path): sha(path) for path in paths}
        if hashes_before != hashes_after:
            raise RuntimeError('RTL, testbench, source or capture bytes changed during tests')
        report['source_hashes_after'] = hashes_after
        report['status'] = 'PASS'
        report['finished_utc'] = utc_now()
        report['summary'] = {
            'valid_original_task_words': 26, 'source_command_preserved': True,
            'only_job_address_relocations_applied': True,
            'address_relocations': 2, 'negative_controls': 10,
            'dma_contract_published': True, 'dma_executed': False,
            'full_bo_compared': False, 'hardware_accessed': False,
        }
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
        outdir = ROOT / 'build/ppu-pooling' / f'c3-raw-profile-{simulator}-{stamp}'
        try:
            report = run_simulator(simulator, outdir, args.keep_build, fixture_data)
        except Exception as exc:
            print(f'FAIL C3 raw profile {simulator}: {exc}', file=sys.stderr)
            return 1
        print(f"PASS C3 raw profile {simulator}: 26 captured QWORDs, "
              f"10 unsupported-stream controls rejected, DMA contract decoded; "
              f"report={outdir / 'report.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
