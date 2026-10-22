#!/usr/bin/env python3
"""Measure FP16 CMAC stimulus coverage without modifying any golden value.

This reports input categories, not simulator code/functional coverage. Only
numeric groups without a selected NaN contribute to exponent-gap coverage.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--channels', type=int, choices=(8, 32, 64), default=32)
p.add_argument('--kernels', type=int, choices=(1, 8, 16, 32), default=16)
a = p.parse_args()
C, K = a.channels, a.kernels
base = ROOT / 'build/rknpu-cmac-array' / f'c{C}k{K}'
vectors = base / 'vectors.hex'
manifest = base / 'vectors_report.json'
vr = json.loads(manifest.read_text())
assert (vr['channels'], vr['kernels']) == (C, K)
for group in ('source', 'artifacts'):
    for name, sha in vr[group]['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
def nan(x):
    return (x & 0x7c00) == 0x7c00 and (x & 1023) != 0
def kind(x):
    e, m = (x >> 10) & 31, x & 1023
    return 'nan' if e == 31 and m else 'infinity' if e == 31 else 'normal' if e else 'subnormal' if m else 'zero'
classes, gaps, selections = Counter(), Counter(), Counter()
sign_pairs, channel_active, kernel_distinct = Counter(), Counter(), Counter()
masked_nans = 0
rows = vectors.read_text().splitlines()
assert len(rows) == vr['frames']
for frame, row in enumerate(rows):
    value = int(row, 16)
    assert value.bit_length() <= vr['frame_bits']
    def take(bits):
        global value
        result = value & ((1 << bits) - 1)
        value >>= bits
        return result
    expected = take(K * 44)
    wm, dm = take(K * C), take(C)
    packed_w, packed_d = take(K * C * 16), take(C * 16)
    assert value == 0
    data = [(packed_d >> (16 * i)) & 65535 for i in range(C)]
    if len({(expected >> (44 * k)) & ((1 << 44) - 1) for k in range(K)}) > 1:
        kernel_distinct['frames_with_distinct_kernel_results'] += 1
    for k in range(K):
        weight = [(packed_w >> (16 * (k * C + i))) & 65535 for i in range(C)]
        weights_nan = [i for i in range(C) if nan(weight[i]) and (wm >> (k * C + i)) & 1]
        data_nan = [i for i in range(C) if nan(data[i]) and (dm >> i) & 1]
        selections['both_weight_and_data_nan' if weights_nan and data_nan else
                   'weight_nan_only' if weights_nan else 'data_nan_only' if data_nan else 'numeric'] += 1
        if len(weights_nan) > 1 or (not weights_nan and len(data_nan) > 1):
            selections['multiple_priority_candidates'] += 1
        active = []
        for i, (d, w) in enumerate(zip(data, weight)):
            de, we = (dm >> i) & 1, (wm >> (k * C + i)) & 1
            masked_nans += int(nan(d) and not de) + int(nan(w) and not we)
            if de:
                classes['data_' + kind(d)] += 1
            if we:
                classes['weight_' + kind(w)] += 1
            if de and we and d & 0x7fff and w & 0x7fff:
                active.append((((d >> 12) & 7) + ((w >> 12) & 7), i, d, w))
        if not weights_nan and not data_nan and active:
            maximum = max(x[0] for x in active)
            for exponent, i, d, w in active:
                gaps[maximum - exponent] += 1
                sign_pairs[f'{d >> 15}{w >> 15}'] += 1
                channel_active[i] += 1
report = dict(status='PASS_STIMULUS_AUDIT_ONLY', created_utc=timestamp(), channels=C, kernels=K,
              frames=len(rows), seed=vr['seed'], source=fingerprint([Path(__file__).resolve(), vectors, manifest]),
              operand_classes=dict(classes), numeric_exponent_gap_counts=dict(sorted(gaps.items())),
              numeric_sign_pairs=dict(sign_pairs), nan_selection=dict(selections), masked_nan_operands=masked_nans,
              numeric_active_channels=sorted(channel_active), kernel_distinction=dict(kernel_distinct),
              missing_numeric_exponent_gaps=sorted(set(range(15)) - set(gaps)),
              scope='Input stimulus audit only; not RTL coverage or an arithmetic comparison. Goldens are unchanged.')
out = base / f'stimulus-audit-{time.time_ns()}.json'
out.write_text(json.dumps(report, indent=2) + '\n')
print(out)
print(json.dumps({k: report[k] for k in ('numeric_exponent_gap_counts', 'numeric_sign_pairs', 'nan_selection', 'masked_nan_operands', 'missing_numeric_exponent_gaps')}, indent=2))
