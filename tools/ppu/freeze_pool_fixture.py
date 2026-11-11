#!/usr/bin/env python3
"""Freeze a captured pooling bundle into a pinned fixture.

Reads the host bundle (``in.bin``/``expected.bin``/``out_init.bin``/
``regcmd.bin``/``regcmd.txt``/``job.json``) and the matching device run under
``build/rk3588-example-captures/results/pooling-*/pooling/<case>/``, then writes
``tests/ppu_pooling/fixtures/<case>/`` with a hash-bound manifest.

Only verified facts are recorded: file hashes, the device capture status, the
command stream with its declared relocations, and the PPU geometry from the
family manifest (cross-checked against the bundle's own register dump). The
device BO is the oracle and must equal the host ``expected.bin`` byte for byte,
otherwise the case is rejected.

Usage:
    python3 tools/ppu/freeze_pool_fixture.py --case <case>
    python3 tools/ppu/freeze_pool_fixture.py --all-missing
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
BUNDLES = ROOT / 'build/rk3588-example-captures/pooling/cases'
RESULTS = ROOT / 'build/rk3588-example-captures/results'
FIXTURES = ROOT / 'tests/ppu_pooling/fixtures'
FAMILY = ROOT / 'build/rk3588-example-captures/pooling/manifest.json'
SOURCE_FILES = ('in.bin', 'expected.bin', 'out_init.bin', 'regcmd.bin',
                'regcmd.txt', 'job.json')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_device_dir(case: str) -> Path:
    for candidate in sorted(RESULTS.glob('pooling-*/pooling')):
        directory = candidate / case
        if (directory / 'out.bin').exists() and (directory / 'capture.json').exists():
            return directory
    raise SystemExit(f'no device capture for {case}')


def parse_regcmd_fields(path: Path) -> list[dict]:
    fields = []
    for line in path.read_text().splitlines():
        if line.startswith('#') or not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        index, target, offset, value, field = parts[:5]
        fields.append({'index': int(index), 'target': int(target, 16),
                       'offset': int(offset, 16), 'value': int(value, 16),
                       'field': field})
    return fields


def freeze(case: str, family_row: dict) -> Path:
    bundle = BUNDLES / case
    device = find_device_dir(case)
    fixture = FIXTURES / case
    if (fixture / 'manifest.json').exists():
        raise SystemExit(f'{case}: fixture already exists')
    if fixture.exists():
        # An earlier failed run copied files but never wrote a manifest; that
        # partial directory is not a fixture and is safe to rebuild.
        shutil.rmtree(fixture)
    for name in SOURCE_FILES:
        if not (bundle / name).exists():
            raise SystemExit(f'{case}: bundle is missing {name}')
    if sha(device / 'out.bin') != sha(bundle / 'expected.bin'):
        raise SystemExit(f'{case}: device output differs from the host oracle')
    capture = json.loads((device / 'capture.json').read_text())
    if capture['status'] != 'OK' or capture['submit_ret'] != 0:
        raise SystemExit(f'{case}: device capture did not succeed')
    job = json.loads((bundle / 'job.json').read_text())
    fields = parse_regcmd_fields(bundle / 'regcmd.txt')
    ppu = family_row['ppu']
    shapes = family_row['shapes']
    oracle = family_row['oracle']

    # Cross-check the register dump against the manifest geometry so a stale
    # bundle cannot be frozen under a mismatched description.
    def field(name: str, default: int | None = None) -> int:
        for row in fields:
            if row['field'] == name:
                return row['value']
        if default is None:
            raise SystemExit(f'{case}: missing {name} in regcmd.txt')
        return default

    expected_in_w = shapes['in_w'] - 1
    expected_in_h = shapes['in_h'] - 1
    expected_out_w = shapes['out_w'] - 1
    expected_out_h = shapes['out_h'] - 1
    expected_channels = shapes['channels'] - 1
    if (field('PPU_DATA_CUBE_IN_WIDTH') != expected_in_w or
            field('PPU_DATA_CUBE_IN_HEIGHT') != expected_in_h or
            field('PPU_DATA_CUBE_OUT_WIDTH') != expected_out_w or
            field('PPU_DATA_CUBE_OUT_HEIGHT') != expected_out_h or
            field('PPU_DATA_CUBE_IN_CHANNEL') != expected_channels):
        raise SystemExit(f'{case}: register dump disagrees with manifest geometry')
    kernel_cfg = field('PPU_POOLING_KERNEL_CFG')
    kernel = [(kernel_cfg >> 8) & 0xf, kernel_cfg & 0xf]
    if [k + 1 for k in kernel] != list(ppu['kernel']):
        raise SystemExit(f'{case}: kernel_cfg does not match the manifest kernel')
    stride = [(kernel_cfg >> 20) & 0xf, (kernel_cfg >> 16) & 0xf]
    if [s + 1 for s in stride] != list(ppu['stride']):
        raise SystemExit(f'{case}: kernel_cfg stride does not match the manifest')

    fixture.mkdir(parents=True)
    for name in SOURCE_FILES:
        shutil.copyfile(bundle / name, fixture / name)
    shutil.copyfile(device / 'out.bin', fixture / 'device_out.bin')
    shutil.copyfile(device / 'capture.json', fixture / 'capture.json')

    addresses = {row['buffer']: row['dma_address'] for row in capture['patches']}
    sizes = {row['name']: row['size'] for row in job['buffers']}
    manifest = {
        'case': case,
        'status': 'READY_CAPTURE_BOUNDED_CANDIDATE',
        'description': family_row['description'],
        'source_example': family_row['source_example'],
        'source_bundle': str(bundle.relative_to(ROOT)),
        'device_capture': {
            'capture_json_sha256': sha(fixture / 'capture.json'),
            'started_utc': capture['started_utc'],
            'status': capture['status'],
            'submit_ret': capture['submit_ret'],
            'device': capture['device_path'],
            'device_path': capture['device']['sysfs_device'],
            'kernel': capture['device']['kernel'],
            'board_compatible': capture['device']['board_compatible'],
            'runner': 'rocket_run.py 1.0.0',
        },
        'command_stream': {
            'source_regcmd_sha256': sha(fixture / 'regcmd.bin'),
            'device_patched_regcmd_sha256':
                capture['hashes']['command_stream']['sha256'],
            'job_json_sha256': sha(fixture / 'job.json'),
            'qwords': len((fixture / 'regcmd.bin').read_bytes()) // 8,
            'address_relocations': [row['regcmd_index'] for row in job['patches']],
            'addresses': addresses,
        },
        'ppu': {
            'dtype': ppu['dtype'],
            'method': ppu['method'],
            'method_selector': ppu['method_selector'],
            'channels': ppu['channels'],
            'kernel': ppu['kernel'],
            'stride': ppu['stride'],
            'padding': ppu['padding'],
            'padding_value': ppu['padding_value'],
            'index_en': ppu['index_en'],
            'use_cnt': ppu['use_cnt'],
            'in_shape': ppu['in_shape'],
            'out_shape': ppu['out_shape'],
            'kernel_cfg': kernel_cfg,
            'operation_mode_cfg': field('PPU_OPERATION_MODE_CFG'),
            'precision_name': ppu.get('precision_name'),
            'rdma_width': ppu.get('rdma_width'),
            'output_precision': ppu.get('output_precision'),
        },
        'layout': family_row['layout'],
        'files': {path.name: {'bytes': path.stat().st_size, 'sha256': sha(path)}
                  for path in sorted(fixture.iterdir()) if path.is_file()},
        'comparison': {
            'scope': f'complete {sizes["out"]}-byte output BO including untouched tail',
            'logical_value_bytes': oracle['logical_output_bytes'],
            'mismatches_expected': 0,
            'tolerance': oracle['tolerance'],
            'note': ('The device output SHA256 equals the host expected.bin '
                     'SHA256; the testbench compares the real device BO.'),
            'device_output_sha256': sha(fixture / 'device_out.bin'),
            'source_expected_sha256': sha(fixture / 'expected.bin'),
        },
        'oracle': oracle,
        'source': {
            'example': oracle.get('source_example', family_row['source_example']),
            'lines': oracle.get('source_lines') or family_row.get('source_lines', []),
            'job_sha256': sha(fixture / 'job.json'),
        },
    }
    (fixture / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--all-missing', action='store_true')
    args = parser.parse_args()
    family = json.loads(FAMILY.read_text())['cases']
    rows = {row['case']: row for row in family}
    targets = list(args.case)
    if args.all_missing:
        targets += [row['case'] for row in family
                    if row['status'] == 'READY'
                    and not (FIXTURES / row['case'] / 'manifest.json').exists()]
    if not targets:
        print('nothing to do; pass --case or --all-missing', file=sys.stderr)
        return 2
    for case in targets:
        if case not in rows:
            print(f'{case}: not in the pooling family manifest', file=sys.stderr)
            return 1
        if rows[case]['status'] != 'READY':
            print(f'{case}: family status is {rows[case]["status"]}', file=sys.stderr)
            return 1
        fixture = freeze(case, rows[case])
        manifest = json.loads((fixture / 'manifest.json').read_text())
        print(f'froze {fixture.relative_to(ROOT)}: '
              f'{manifest["ppu"]["method"]} {manifest["ppu"]["dtype"]} '
              f'{"x".join(str(v) for v in manifest["ppu"]["in_shape"])} -> '
              f'{"x".join(str(v) for v in manifest["ppu"]["out_shape"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
