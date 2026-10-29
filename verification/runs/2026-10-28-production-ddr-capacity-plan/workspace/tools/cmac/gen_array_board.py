#!/usr/bin/env python3
"""Package a pinned C32/K16 K65 test fixture and derive its board ROM.

This is an offline self-test image, never a runtime arithmetic/layout fallback.
Import is explicit and refuses to overwrite an existing fixture. Regeneration
and --check need only packaged files, not a live backend or scratch build tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--import-from', type=Path)
p.add_argument('--check', action='store_true')
a = p.parse_args()
base = ROOT / 'tests/cmac/array_data'
names = ('commands.hex', 'input.hex', 'weight.hex', 'reads.hex', 'writes.hex', 'groups.hex', 'fp32.hex')

def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name

if a.import_from:
    assert not a.check and not base.exists(), 'import is only allowed into a new fixture directory'
    original = a.import_from.resolve()
    report_path = original / 'vectors_report.json'
    report = json.loads(report_path.read_text())
    assert report['status'] == 'GENERATED_C32_RAW_CORE_REFERENCE_ONLY'
    verify(report['source']); verify(report['artifacts'])
    case = next(case for case in report['cases'] if case['name'] == 'm2_n17_k65_finite')
    assert (case['rows'], case['ai'], case['ao'], case['frames'], case['reads'], case['writes']) == (2, 96, 32, 12, 6528, 64)
    assert case['finite_variant'] and case['nan_outputs'] == 0 and case['unique_outputs'] > 16
    base.mkdir()
    for name in names:
        (base / name).write_bytes((original / case['name'] / name).read_bytes())
    (base / 'source_report.json').write_bytes(report_path.read_bytes())
    packaged = [base / name for name in (*names, 'source_report.json')]
    manifest = dict(status='PACKAGED_C32_K65_SYNTHETIC_FIXTURE_ONLY', imported_utc=timestamp(), case=case,
                    files=fingerprint(packaged),
                    provenance='Original reference report sources and artifacts verified at import. Packaged bytes retain their hashes. No RK hardware capture, RTL pass, runtime conversion or C64 golden reuse.')
    (base / 'fixture.json').write_text(json.dumps(manifest, indent=2)+'\n')

fixture = json.loads((base / 'fixture.json').read_text())
verify(fixture['files'])
case = fixture['case']
words = [int(line, 16) for line in (base / 'commands.hex').read_text().splitlines()]
assert len(words) == 49 and hashlib.sha256(struct.pack('<49Q', *words)).hexdigest() == case['commands_sha256']
# The unchanged synchronous trace RAM maps these exact physical windows.
windows = ((0x10010000, 448, 0), (0x10020000, 6208, 448),
           (0x10040000, 320, 6656), (0x100e0000, 448, 6976))

def index(address):
    hits = [(address-start+offset)//2 for start, size, offset in windows if start <= address < start+size and address % 2 == 0]
    assert len(hits) == 1, hex(address)
    return hits[0]

initial = [0xa55a]*4096
occupied = set()
for name, address, count in (('input.hex', 0x10010000, 192), ('weight.hex', 0x10020000, 3072)):
    values = [int(line, 16) for line in (base / name).read_text().splitlines()]
    assert len(values) == count
    for i, value in enumerate(values):
        flat = index(address+2*i)
        assert flat not in occupied and 0 <= value <= 65535
        occupied.add(flat); initial[flat] = value
for i, value in enumerate(struct.unpack('<196H', struct.pack('<49Q', *words))):
    flat = index(0x100e0000+2*i)
    assert flat not in occupied
    occupied.add(flat); initial[flat] = value
reads = [int(line, 16) for line in (base / 'reads.hex').read_text().splitlines()]
assert len(reads) == 6528 and all(initial[index(value >> 16)] == value & 65535 for value in reads)
expected = initial.copy()
written = set()
for line in (base / 'writes.hex').read_text().splitlines():
    value = int(line, 16); address = value >> 16; flat = index(address)
    assert 0x10040000 <= address < 0x10040100 and flat not in occupied and flat not in written
    assert value & 0x7c00 != 0x7c00, 'finite board corpus required'
    written.add(flat); expected[flat] = value & 65535
assert len(written) == 64 and len(set(expected[i] for i in written)) > 16
text = ''.join(f'{check:04x}{value:04x}\n' for value, check in zip(initial, expected))
rom = base / 'board_rom.hex'
if a.check:
    assert rom.read_text() == text, 'stale C32 board ROM'
else:
    rom.write_text(text)
print('PASS C32 K16 board ROM consistency: 49 unchanged QWORDs, 6528 oracle reads, 64 finite writes, 4096 checked halfwords; not RTL or FPGA validation')
