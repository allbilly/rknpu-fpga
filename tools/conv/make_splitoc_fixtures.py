#!/usr/bin/env python3
"""Derive the promoted one-task split-OC fixtures from the validated parent."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / 'build/rk3588-example-captures/conv-fp16/cases/conv_splitoc_3x3_c16_h9_w9_oc16'
BUNDLES = ROOT / 'build/rk3588-example-captures/conv-fp16-task-diagnostic/bundles'
BOARD = (ROOT / 'build/rk3588-example-captures/results/'
         'conv-fp16-task-diagnostic-20261105T211500Z/board-out')
PROMOTED = ROOT / 'build/rk3588-example-captures/conv-fp16/cases'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    for group in ('0', '1'):
        case = f'conv_splitoc_3x3_c16_h9_w9_oc16_task{group}'
        source = PROMOTED / case
        fixture = ROOT / 'tests/conv/fixtures' / case
        fixture.mkdir(parents=True, exist_ok=True)
        bundle = BUNDLES / f'diag_splitoc_task{group}'
        board = BOARD / f'diag_splitoc_task{group}'
        mappings = {
            'a.bin': bundle / 'a0.bin',
            'w.bin': bundle / f'w{group}.bin',
            'regcmd.bin': bundle / 'regcmd.bin',
            'expected.bin': bundle / f'expected_out{group}.bin',
            'device_out.bin': board / f'out{group}.bin',
            'device_capture.json': board / 'capture.json',
            'provenance.json': source / 'provenance.json',
            'source_input_nchw.bin': PARENT / 'source_input_nchw.bin',
            'source_weight_nchw.bin': PARENT / 'source_weight_nchw.bin',
        }
        for name, origin in mappings.items():
            shutil.copyfile(origin, fixture / name)
        capture = json.loads((fixture / 'device_capture.json').read_text())
        provenance = json.loads((fixture / 'provenance.json').read_text())
        patched = bytearray((fixture / 'regcmd.bin').read_bytes())
        job_source = json.loads((source / 'job.json').read_text())
        rectified = {
            'case': case,
            'description': (
                'One-task promotion of the split-OC FP16 C16 9x9 -> OC8 7x7 '
                f'task {group}/2. The parent two-task job is blocked because '
                'Rocket left task 1 output all zero.'),
            'source_example': job_source['source_example'],
            'timeout_ns': job_source['timeout_ns'],
            'tasks': [{'regcmd_offset_words': 0, 'regcmd_words': 54}],
            'buffers': [
                {'name': 'a', 'size': 2592, 'input': 'a.bin', 'direction': 'in'},
                {'name': 'w', 'size': 2304, 'input': 'w.bin', 'direction': 'in'},
                {'name': 'out', 'size': 3328, 'direction': 'out',
                 'output': 'out.bin'},
            ],
            'patches': [
                {'regcmd_index': 21, 'buffer': 'a', 'kind': 'value32'},
                {'regcmd_index': 27, 'buffer': 'w', 'kind': 'value32'},
                {'regcmd_index': 35, 'buffer': 'out', 'kind': 'value32'},
            ],
        }
        (fixture / 'job.json').write_text(json.dumps(rectified, indent=2) + '\n')
        import struct
        for index, value in ((21, 0x1000), (27, 0x2000), (35, 0x3000)):
            qword, = struct.unpack_from('<Q', patched, index * 8)
            qword = (qword & ~(0xffffffff << 16)) | (value << 16)
            struct.pack_into('<Q', patched, index * 8, qword)
        files = {name: {'bytes': (fixture / name).stat().st_size,
                        'sha256': sha(fixture / name)}
                 for name in sorted(p.name for p in fixture.iterdir())}
        manifest = {
            'case': case,
            'command': {
                'address_qwords': [21, 27, 35],
                'addresses': {'a': 0x1000, 'w': 0x2000, 'out': 0x3000},
                'captured_patched_sha256': hashlib.sha256(bytes(patched)).hexdigest(),
                'qwords': 54,
                'template_sha256': sha(fixture / 'regcmd.bin'),
            },
            'device': {
                'board': 'Orange Pi 5 / RK3588S',
                'capture_finished_utc': capture['finished_utc'],
                'capture_started_utc': capture['started_utc'],
                'device': capture['device_path'],
                'kernel': capture['device']['kernel'],
                'runner': 'rocket_run.py 1.0.0',
                'status': capture['status'],
                'submit_ret': capture['submit_ret'],
                'task_count': 1,
            },
            'files': files,
            'layout': {
                'input_bytes': 2592,
                'input_c1_plane_stride_bytes': 1296,
                'input_packed': (
                    'NC1HWC2 C2=8; first C1 plane has C0..C7, second has '
                    'C8..C15; each pixel advances 16 bytes in a plane'),
                'input_pixel_stride_bytes': 16,
                'input_real_value_bytes': 2592,
                'output_bytes': 3328,
                'output_layout': (
                    'NC1HWC2, c2=8, output width stride=52 atoms, '
                    'align_out_c=32'),
                'output_logical_bytes': 784,
                'output_logical_elements': 392,
                'weight_bytes': 2304,
                'weight_halfwords_per_kernel_position': 128,
                'weights_packed': 'kh-major [ky][kx][OC][align_C=16]',
            },
            'numeric': {
                'defined_elements_exact': True,
                'device_defined_output_sha256': sha(fixture / 'expected.bin'),
                'device_output_bo_bytes': 3328,
                'device_output_bo_sha256': sha(fixture / 'device_out.bin'),
                'hardware_special_value_policy': (
                    'not established beyond this pinned finite capture'),
                'padding_is_not_numerical_oracle': True,
                'source_expected_sha256': sha(fixture / 'expected.bin'),
                'tolerance_atol': 0.2,
            },
            'scope': (
                'One promoted FP16 split-OC C16/H9/W9 -> OC8/H7/W7 task; raw '
                '54-QWORD command and three declared address relocations.'),
            'shape': {
                'batch': 1, 'dtype': 'float16', 'groups': 1,
                'input_channels': 16, 'input_height': 9, 'input_width': 9,
                'kernel': [3, 3], 'output_channels': 8,
                'output_height': 7, 'output_width': 7,
                'padding': 'valid', 'stride': [1, 1],
            },
            'source': {
                'builder': 'make_conv2d_regs / write_regs_to_npu_task',
                'example': provenance['source_example'],
                'oracle': (
                    'compute_expected_nchw; float64 accumulation of FP16 '
                    'operands rounded once to FP16'),
                'seed': provenance['seed'],
                'sha256': provenance['source_sha256'],
                'source_lines': {
                    'builder': [445, 629], 'input_pack': [388, 401],
                    'oracle': [1010, 1021], 'task_tail': [631, 676],
                    'weight_pack': [346, 386],
                },
                'source_revision': provenance['source_git_revision'],
            },
            'status': 'READY_CAPTURE_BOUNDED_CANDIDATE',
        }
        (fixture / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(case, 'patched', manifest['command']['captured_patched_sha256'][:16],
              'template', manifest['command']['template_sha256'][:16])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
