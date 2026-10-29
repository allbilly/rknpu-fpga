#!/usr/bin/env python3
"""Generate a separate chipdb candidate with unique hidden-routing BEL z IDs.

Preserves every placeable BEL coordinate, every resource and every other byte.
This repairs a database identity collision; it is not architecture acceptance.
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from chipdb_layout import ChipDB
checkout = ROOT / 'build/reference/nextpnr-xilinx'
revision = subprocess.check_output(['git', '-C', checkout, 'rev-parse', 'HEAD'], text=True).strip()
assert revision == 'd486d8ef6a1c756ca72b2ba495e7e18e4c24815d'
assert not subprocess.check_output(['git', '-C', checkout, 'status', '--porcelain'], text=True).strip()
base = ROOT / 'build/openxc7'
original = base / 'xc7k480tffg1156-2.bin'
def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
original_sha = digest(original)
assert original_sha == '98f43994365b465b70f33b17ba9a9e2489f17f3eee4c2be332bea0cbbbe17bf2'
constids = checkout / 'xilinx/constids.inc'
sources = [Path(__file__).resolve(), Path(__file__).with_name('chipdb_layout.py'), constids,
           checkout / 'xilinx/arch.h', checkout / 'xilinx/python/bels.py', checkout / 'xilinx/python/nextpnr_structs.py']
source = fingerprint(sources)
out = base / f'routing-z-repair-{time.time_ns()}'
out.mkdir(exist_ok=False)
candidate = out / 'xc7k480tffg1156-2.bin'
changes = []
with ChipDB(original, constids) as db:
    assert db.device == 'xc7k480tffg1156-2'
    for type_index in range(db.type_count):
        name, bels = db.bels(type_index)
        used = {bel['z'] for bel in bels}
        assert all(0 <= z < 256 for z in used)
        groups = defaultdict(list)
        for bel in bels:
            groups[bel['z']].append(bel)
        for z, group in groups.items():
            if len(group) < 2:
                continue
            placeable = [bel for bel in group if not bel['routing']]
            assert len(placeable) <= 1, ('refuse to move a placeable BEL', name, group)
            retained = placeable[0] if placeable else group[0]
            for bel in group:
                if bel is retained:
                    continue
                assert bel['routing']
                free = [slot for slot in range(255, -1, -1) if slot not in used]
                assert free, ('no free internal z identifier', name)
                replacement = free[0]; used.add(replacement)
                changes.append(dict(tile_type=name, type_index=type_index, **bel, old_z=z, new_z=replacement))
    assert len(changes) == 8 and {entry['tile_type'] for entry in changes} == {'BRAM_L', 'BRAM_R'}, changes
    shutil.copyfile(original, candidate)
    with candidate.open('r+b') as stream:
        for entry in changes:
            stream.seek(entry['z_byte_offset'])
            assert stream.read(2) == struct.pack('<h', entry['old_z'])
            stream.seek(entry['z_byte_offset']); stream.write(struct.pack('<h', entry['new_z']))
    with ChipDB(candidate, constids) as repaired:
        assert (db.device, db.width, db.height, db.type_count, db.tile_count, db.node_count) == \
               (repaired.device, repaired.width, repaired.height, repaired.type_count, repaired.tile_count, repaired.node_count)
        for type_index in range(db.type_count):
            name, before = db.bels(type_index)
            name2, after = repaired.bels(type_index)
            assert name == name2 and len(before) == len(after)
            assert len({bel['z'] for bel in after}) == len(after), (name, 'remaining collision')
            for old, new in zip(before, after):
                assert {key: value for key, value in old.items() if key != 'z'} == {key: value for key, value in new.items() if key != 'z'}
                assert 0 <= new['z'] < 256
                if not old['routing']:
                    assert old['z'] == new['z'], (name, old)
        # Whole-file proof: normalize only the eight recorded 16-bit fields
        # back to their original values, then compare every byte to input.
        for start in range(0, len(db.data), 1024*1024):
            stop = min(start+1024*1024, len(db.data))
            chunk = bytearray(repaired.data[start:stop])
            for entry in changes:
                offset = entry['z_byte_offset']
                if start <= offset < stop:
                    assert offset+2 <= stop
                    chunk[offset-start:offset-start+2] = struct.pack('<h', entry['old_z'])
            assert bytes(chunk) == db.data[start:stop], start
assert digest(original) == original_sha and fingerprint(sources) == source
report = dict(status='GENERATED_ROUTING_Z_REPAIR_CANDIDATE', created_utc=timestamp(), source=source,
              original_chipdb_sha256=original_sha, candidate_chipdb_sha256=digest(candidate),
              candidate=str(candidate.relative_to(ROOT)), changes=changes, patched_bytes=2*len(changes),
              checked_tile_types=97, all_bels_retained=True, all_placeable_coordinates_unchanged=True,
              all_other_bytes_unchanged=True,
              scope='Only eight hidden routing BEL z identities changed in separate candidate. All physical resource/site/timing/pin data preserved. Original chipdb unchanged. Full nextpnr archcheck and physical signoff still required.')
(out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
print(out / 'report.json')
print(report['status'], report['candidate_chipdb_sha256'], 'patched bytes', report['patched_bytes'])
