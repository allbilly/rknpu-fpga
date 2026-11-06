#!/usr/bin/env python3
"""Derive C32/K8 CMAC vectors from the unchanged C32/K16 208-frame corpus.

This is an arithmetic lower-slice only: each K8 row is the lower eight kernels
of the corresponding K16 row. It introduces no new RK semantics, no layout
change and no runtime fixup. K16 remains the reference profile.
"""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

SOURCE_KERNELS = 16
TARGET_KERNELS = 8
CHANNELS = 32
SOURCE = ROOT / 'build/rknpu-cmac-array/c32k16'
OUT = ROOT / 'build/rknpu-cmac-array/c32k8-lower-slice'


def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name


def mask(width):
    return (1 << width) - 1


def pack(words, widths):
    value = 0
    for word, width in zip(words, widths):
        value = (value << width) | word
    return value


source_report = json.loads((SOURCE / 'vectors_report.json').read_text())
verify(source_report['source'])
verify(source_report['artifacts'])
assert (source_report['channels'], source_report['kernels']) == (CHANNELS, SOURCE_KERNELS)
assert source_report['frames'] == 208
lines = (SOURCE / 'vectors.hex').read_text().splitlines()
assert len(lines) == source_report['frames']

data_bits = CHANNELS * 16
weight_bits = SOURCE_KERNELS * CHANNELS * 16
data_mask_bits = CHANNELS
weight_mask_bits = SOURCE_KERNELS * CHANNELS
group_bits = SOURCE_KERNELS * 44
expected_bits = data_bits + weight_bits + data_mask_bits + weight_mask_bits + group_bits
assert expected_bits == 9952

target_data_mask_bits = CHANNELS
target_weight_bits = TARGET_KERNELS * CHANNELS * 16
target_weight_mask_bits = TARGET_KERNELS * CHANNELS
target_group_bits = TARGET_KERNELS * 44
target_bits = data_bits + target_weight_bits + target_data_mask_bits + target_weight_mask_bits + target_group_bits

rows = []
for index, line in enumerate(lines):
    row = int(line, 16)
    assert row.bit_length() <= expected_bits
    groups = row & mask(group_bits)
    weight_masks = (row >> group_bits) & mask(weight_mask_bits)
    data_mask = (row >> (group_bits + weight_mask_bits)) & mask(data_mask_bits)
    weights = (row >> (group_bits + weight_mask_bits + data_mask_bits)) & mask(weight_bits)
    data = (row >> (group_bits + weight_mask_bits + data_mask_bits + weight_bits)) & mask(data_bits)
    lower_groups = groups & mask(target_group_bits)
    lower_weight_masks = weight_masks & mask(target_weight_mask_bits)
    lower_weights = weights & mask(target_weight_bits)
    target = pack((data, lower_weights, data_mask, lower_weight_masks, lower_groups),
                  (data_bits, target_weight_bits, target_data_mask_bits,
                   target_weight_mask_bits, target_group_bits))
    assert target.bit_length() <= target_bits
    rows.append(target)

OUT.mkdir(parents=True, exist_ok=False)
vectors = OUT / 'vectors.hex'
vectors.write_text(''.join(f'{row:0{(target_bits + 3) // 4}x}\n' for row in rows))
report = dict(status='GENERATED_K8_LOWER_SLICE_REFERENCE_ONLY', created_utc=timestamp(),
              channels=CHANNELS, kernels=TARGET_KERNELS, source_kernels=SOURCE_KERNELS,
              frames=len(rows), outputs=len(rows) * TARGET_KERNELS,
              frame_bits=target_bits, lower_slice_bits=TARGET_KERNELS * 44,
              source=fingerprint([Path(__file__).resolve(), SOURCE / 'vectors_report.json',
                                  SOURCE / 'vectors.hex']),
              artifacts=fingerprint([vectors]),
              scope='Test-only lower-eight-kernel slice of the unchanged C32/K16 208-frame CMAC corpus. No new RK semantics, RTL, raw-command, layout, FPGA or RK pass.')
(OUT / 'vectors_report.json').write_text(json.dumps(report, indent=2) + '\n')
print(OUT / 'vectors_report.json')
print(f'Generated {len(rows)} C32/K8 rows from the C32/K16 corpus, {report["outputs"]} checked groups')
