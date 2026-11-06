#!/usr/bin/env python3
"""Derive one C32/K8 raw-command core case from the C32/K16 reference case.

The host command stream is unchanged: it still describes one logical OC16 job
with 0x10014024=16. The K8 weight image is repacked as (N/8, K/32, 8, 32),
the front-end read order is regenerated for two OC8 frames per OC16 block, and
the expected writes are re-chunked into 8-halfword OC8 frames. Numerical
values come from the existing K16 case; this is a lower-slice derivation, not
a new RK oracle or a runtime CPU layout fixup.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

CASE = 'm2_n17_k65_finite'
SOURCE = ROOT / 'build/rknpu-array-core-vectors'
OUT = ROOT / 'build/rknpu-array-core-vectors-k8'
ATOMIC_C = 32
ATOMIC_K = 8


def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name


def read_hex(path, width):
    values = [int(line, 16) for line in path.read_text().splitlines()]
    assert all(0 <= value < (1 << width) for value in values)
    return values


source_report = json.loads((SOURCE / 'vectors_report.json').read_text())
verify(source_report['source'])
verify(source_report['artifacts'])
case = next(c for c in source_report['cases'] if c['name'] == CASE)
rows, ai, ao = case['rows'], case['ai'], case['ao']
assert ai % 32 == 0 and ao % 16 == 0
source_dir = SOURCE / CASE
commands = read_hex(source_dir / 'commands.hex', 64)
inputs = read_hex(source_dir / 'input.hex', 16)
weights16 = read_hex(source_dir / 'weight.hex', 16)
reads16 = read_hex(source_dir / 'reads.hex', 48)
writes16 = read_hex(source_dir / 'writes.hex', 48)
assert len(commands) == 49
assert commands[32] == 0x1001000000104024, 'host kernel_group field must remain 16'
assert [((word >> 48) << 16) | (word & 0xffff) for word in commands[45:49]] == [
    0x00010000, 0x01010014, 0x00410000, 0x00810008]
assert hashlib.sha256(struct.pack('<49Q', *commands)).hexdigest() == case['commands_sha256']
assert len(inputs) == rows * ai
assert len(weights16) == ai * ao
assert len(reads16) == case['reads']
assert len(writes16) == case['writes'] == rows * ao

# K16 weight layout per logical OC16 block is (K/32, 16, 32). K8 is
# (N/8, K/32, 8, 32): for each OC8 block, IC32 group then eight kernels.
weights8 = [0] * (ai * ao)
for n8 in range(ao // ATOMIC_K):
    for j in range(ai // 32):
        for kernel in range(ATOMIC_K):
            for channel in range(32):
                k16_kernel = (n8 % 2) * ATOMIC_K + kernel
                source = (n8 // 2) * 16 * ai + j * 16 * 32 + k16_kernel * 32 + channel
                target = n8 * (ai // 32) * (ATOMIC_K * 32) + j * ATOMIC_K * 32 + kernel * 32 + channel
                weights8[target] = weights16[source]

# K8 front traversal: row -> physical OC8 group -> IC32 group. Each frame
# reads 32 input halfwords and ATOMIC_K*32 weight halfwords.
reads8 = []
for row in range(rows):
    for oc in range(0, ao, ATOMIC_K):
        for group in range(ai // 32):
            ic = group * 32
            reads8 += [((0x10010000 + 2 * (row * ai + ic + lane)) << 16) |
                       inputs[row * ai + ic + lane] for lane in range(32)]
            weight_base = oc * ai + group * ATOMIC_K * 32
            reads8 += [((0x10020000 + 2 * (weight_base + lane)) << 16) |
                       weights8[weight_base + lane] for lane in range(ATOMIC_K * 32)]

# The K16 writer order is row -> OC16 block -> kernel 0..15. K8 re-chunks
# each 16-halfword OC16 block into two 8-halfword OC8 frames. Addresses and
# numerical values are unchanged.
writes8 = []
for block in range(len(writes16) // 16):
    expected_base = None
    for frame in range(2):
        for lane in range(ATOMIC_K):
            record = writes16[block * 16 + frame * ATOMIC_K + lane]
            address, value = record >> 16, record & 0xffff
            if lane == 0:
                assert expected_base is None or address == expected_base
                expected_base = address
            assert address == expected_base + 2 * lane
            writes8.append((address << 16) | value)
        expected_base += 16

operand_frames = rows * (ao // ATOMIC_K) * (ai // 32)
output_frames = rows * (ao // ATOMIC_K)
assert len(reads8) == operand_frames * (32 + ATOMIC_K * 32) == 6912
assert len(writes8) == output_frames * ATOMIC_K == rows * ao
assert {record >> 16 for record in reads8 if (record >> 16) >= 0x10020000} <= \
       set(0x10020000 + 2 * index for index in range(ai * ao))
assert {record >> 16 for record in writes8} <= \
       set(0x10040000 + 2 * index for index in range(rows * ao * 2))

OUT.mkdir(parents=True, exist_ok=False)
out_dir = OUT / CASE
out_dir.mkdir()
files = {'commands.hex': (commands, 16), 'input.hex': (inputs, 4),
         'weight.hex': (weights8, 4), 'reads.hex': (reads8, 12),
         'writes.hex': (writes8, 12)}
artifacts = []
for name, (values, width) in files.items():
    path = out_dir / name
    path.write_text(''.join(f'{value:0{width}x}\n' for value in values))
    artifacts.append(path)
derivation = out_dir / 'derivation.json'
derivation.write_text(json.dumps({
    'source_case': CASE,
    'atomic_c': ATOMIC_C,
    'atomic_k': ATOMIC_K,
    'rows': rows,
    'ai': ai,
    'ao': ao,
    'operand_frames': operand_frames,
    'output_frames': output_frames,
    'read_count': len(reads8),
    'write_count': len(writes8),
    'commands_sha256': hashlib.sha256(struct.pack('<49Q', *commands)).hexdigest(),
    'weight_layout': '(N/8, K/32, 8, 32)',
    'write_layout': '8 halfwords at OC16 base+0 and OC16 base+16 bytes; 64-byte block stride preserved',
    'scope': 'Test-only lower-slice derivation from the unchanged C32/K16 core case; no new RK semantics.',
}, indent=2) + '\n')
artifacts.append(derivation)
report = dict(status='GENERATED_C32_K8_RAW_CORE_LOWER_SLICE_ONLY', created_utc=timestamp(),
              case=dict(name=CASE, atomic_c=ATOMIC_C, atomic_k=ATOMIC_K,
                        rows=rows, ai=ai, ao=ao, operand_frames=operand_frames,
                        output_frames=output_frames, reads=len(reads8), writes=len(writes8),
                        commands_sha256=hashlib.sha256(struct.pack('<49Q', *commands)).hexdigest()),
              source=fingerprint([Path(__file__).resolve(), SOURCE / 'vectors_report.json',
                                  source_dir / 'commands.hex', source_dir / 'input.hex',
                                  source_dir / 'weight.hex', source_dir / 'reads.hex',
                                  source_dir / 'writes.hex']),
              artifacts=fingerprint(artifacts),
              scope='Test-only C32/K8 raw-command core derivation from the unchanged C32/K16 reference case. No new RK oracle, RTL, FPGA or RK pass.')
(OUT / 'vectors_report.json').write_text(json.dumps(report, indent=2) + '\n')
print(OUT / 'vectors_report.json')
print(f'Derived {CASE}: operand_frames={operand_frames} reads={len(reads8)} writes={len(writes8)}')
