#!/usr/bin/env python3
"""Accumulate existing C32/K16 CMAC goldens in independent per-kernel states."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from cacc_reference import add, final

base = ROOT / 'build/rknpu-cmac-array/c32k16'
manifest = base / 'vectors_report.json'
vr = json.loads(manifest.read_text())
assert (vr['channels'], vr['kernels']) == (32, 16)
for kind in ('source', 'artifacts'):
    for name, sha in vr[kind]['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
# Check extraction against every unchanged direct-donor oracle vector before
# generating a new corpus. This is Python reference evidence, not an RTL run.
audit = ROOT / 'build/cacc_donor_audit/vectors.hex'
checked = 0
for line in audit.read_text().splitlines():
    row = int(line, 16)
    expected_final = row & ((1 << 32) - 1)
    expected_partial = (row >> 32) & ((1 << 48) - 1)
    valid = (row >> 80) & 1
    operand = (row >> 81) & ((1 << 48) - 1)
    data = row >> 129
    result = add(data, operand, valid)
    assert result == expected_partial and final(result) == expected_final
    checked += 1
assert checked == 9144
groups = [int(line, 16) & ((1 << (16 * 44)) - 1) for line in (base / 'vectors.hex').read_text().splitlines()]
rows, partials, stream, remaining = [], [0] * 16, 0, 0
lengths = (1, 2, 3, 7, 8, 9, 31, 32, 33, 65)
for index, group in enumerate(groups):
    first = remaining == 0
    if first:
        remaining = min(lengths[stream % len(lengths)], len(groups) - index)
        stream += 1
    remaining -= 1
    last = remaining == 0
    values = 0
    for k in range(16):
        partials[k] = add((group >> (44 * k)) & ((1 << 44) - 1), partials[k], not first)
        values |= final(partials[k]) << (32 * k)
    tag = (0x10040000 + stream * 32) << 1
    # group704, first1, last1, tag33, expected final512 (only checked on last).
    rows.append((group << 547) | (int(first) << 546) | (int(last) << 545) | (tag << 512) | values)
out = ROOT / 'build/rknpu-cacc-array/c32k16'
out.mkdir(parents=True, exist_ok=False)
path = out / 'vectors.hex'
path.write_text(''.join(f'{row:0313x}\n' for row in rows))
report = dict(status='GENERATED_REFERENCE_ONLY', created_utc=timestamp(), kernels=16, channels=32,
              frames=len(rows), streams=stream, outputs=stream*16, oracle_extraction_checks=checked,
              source=fingerprint([Path(__file__).resolve(), Path(__file__).with_name('cacc_reference.py'),
                                  manifest, base / 'vectors.hex', audit]), artifacts=fingerprint([path]),
              scope='Test-only per-kernel ordered reduction of existing CMAC goldens; no RTL or RK pass.')
(out / 'vectors_report.json').write_text(json.dumps(report, indent=2)+'\n')
print(out / 'vectors_report.json')
print(f'Generated {len(rows)} frames, {stream} complete K16 reductions; {checked} oracle extraction checks')
