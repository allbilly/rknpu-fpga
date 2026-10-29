#!/usr/bin/env python3
"""OC16 output frames from CACC goldens and directed donor-conversion edges."""
import hashlib
import json
from pathlib import Path
import struct
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

def convert(bits):
    # Test-only donor policy: finite RNE, saturating overflow/Inf, low ten NaN
    # payload bits. A truncated-zero NaN payload may encode infinity.
    if bits & 0x7f800000 == 0x7f800000 and bits & 0x7fffff:
        return ((bits >> 16) & 0x8000) | 0x7c00 | (bits & 0x3ff)
    value = struct.unpack('<f', struct.pack('<I', bits))[0]
    try:
        result = struct.unpack('<H', struct.pack('<e', value))[0]
        return (result & 0x8000) | 0x7bff if result & 0x7fff == 0x7c00 else result
    except OverflowError:
        return ((bits >> 16) & 0x8000) | 0x7bff

base = ROOT / 'build/rknpu-cacc-array/c32k16'
vr = json.loads((base / 'vectors_report.json').read_text())
for group in ('source', 'artifacts'):
    for name, sha in vr[group]['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
frames = []
for line in (base / 'vectors.hex').read_text().splitlines():
    row = int(line, 16)
    if (row >> 545) & 1:
        frames.append(row & ((1 << 512) - 1))
assert len(frames) == vr['streams']
edge = [0, 0x80000000, 0x33000000, 0x33000001, 0x337fffff, 0x33800000,
        0x387fc000, 0x387fe000, 0x38800000, 0x3f801000, 0x3f803000,
        0x477fe000, 0x477fefff, 0x477ff000, 0xc77ff000, 0x7f800000,
        0xff800000, 0x7fc00000, 0x7f800001, 0xffc00123, 1]
for offset in (0, 16):
    frames.append(sum(edge[(offset+k) % len(edge)] << (32*k) for k in range(16)))
rows = []
for values in frames:
    expected = sum(convert((values >> (32*k)) & 0xffffffff) << (16*k) for k in range(16))
    rows.append((values << 256) | expected)
out = ROOT / 'build/rknpu-frame-output'
out.mkdir(exist_ok=False)
path = out / 'vectors.hex'
path.write_text(''.join(f'{row:0192x}\n' for row in rows))
report = dict(status='GENERATED_REFERENCE_ONLY', created_utc=timestamp(), frames=len(rows),
              cacc_frames=vr['streams'], source=fingerprint([Path(__file__).resolve(), base / 'vectors.hex', base / 'vectors_report.json']),
              artifacts=fingerprint([path]), scope='Independent test-only FP16 conversion reference. No RTL or hardware execution.')
(out / 'vectors_report.json').write_text(json.dumps(report, indent=2)+'\n')
print(f'Generated {len(rows)} OC16 frames / {len(rows)*16} halfword goldens')
