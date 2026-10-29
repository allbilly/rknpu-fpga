#!/usr/bin/env python3
"""Read-only audit of BEL z collisions in the pinned XC7K480T chipdb.

Decodes the packed structs and four-byte-scaled RelPtr layout from the pinned
arch.h/bbaexport.py. Does not modify the database or propose a routing pass.
"""
from collections import defaultdict
import hashlib
import json
import mmap
from pathlib import Path
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
checkout = ROOT / 'build/reference/nextpnr-xilinx'
assert subprocess.check_output(['git', '-C', checkout, 'rev-parse', 'HEAD'], text=True).strip() == 'd486d8ef6a1c756ca72b2ba495e7e18e4c24815d'
assert not subprocess.check_output(['git', '-C', checkout, 'status', '--porcelain'], text=True).strip()
chipdb = ROOT / 'build/openxc7/xc7k480tffg1156-2.bin'
with chipdb.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
assert digest == '98f43994365b465b70f33b17ba9a9e2489f17f3eee4c2be332bea0cbbbe17bf2'
sources = [Path(__file__).resolve()] + [checkout / name for name in
          ('xilinx/arch.h', 'xilinx/constids.inc', 'xilinx/python/constid.py', 'xilinx/python/bbaexport.py', 'xilinx/python/bels.py', 'xilinx/python/nextpnr_structs.py')]
source = fingerprint(sources)
with chipdb.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as db:
    def integer(offset):
        assert 0 <= offset <= len(db)-4, offset
        return struct.unpack_from('<i', db, offset)[0]
    def pointer(offset):
        target = offset + 4*integer(offset)
        assert 0 <= target < len(db), (offset, target)
        return target
    def string(offset):
        end = db.find(b'\0', offset, min(offset+4096, len(db)))
        assert end >= offset, offset
        return db[offset:end].decode('ascii')
    root = pointer(0)
    device, generator = string(pointer(root)), string(pointer(root+4))
    version, width, height, tile_count, type_count, node_count = struct.unpack_from('<6i', db, root+8)
    assert version == 1 and device == 'xc7k480tffg1156-2' and generator == 'prjxray'
    assert width*height == tile_count and 0 < type_count < 1000 and node_count > 0
    types, tiles, extra = pointer(root+32), pointer(root+36), pointer(root+44)
    known, additional = integer(extra), integer(extra+4)
    strings = pointer(extra+8)
    names = ['']
    for line in (checkout / 'xilinx/constids.inc').read_text().splitlines():
        line = line.strip()
        if line.startswith('X('):
            assert line.endswith(')'), line
            names.append(line[2:-1])
    assert len(names) == known, (len(names), known)
    names += [string(pointer(strings+4*i)) for i in range(additional)]
    def constid(index):
        assert 0 <= index < len(names), index
        return names[index]
    def bels(type_index):
        descriptor = types + type_index*32
        count, start = integer(descriptor+4), pointer(descriptor+8)
        result = []
        for index in range(count):
            addr = start + index*32
            name, kind, native = struct.unpack_from('<3i', db, addr)
            z, site, variant, routing = struct.unpack_from('<4h', db, addr+24)
            assert routing in (0, 1)
            result.append(dict(index=index, name=constid(name), type=constid(kind), native_type=constid(native),
                               z=z, site=site, variant=variant, routing=bool(routing)))
        return result
    # Cross-check the binary schema against the two executed C++ diagnostics.
    tile = tiles + 328*24
    sample = bels(integer(tile+4))[24]
    assert sample['name'] == 'CE1USED'
    sites = pointer(tile+20)
    assert string(pointer(sites+sample['site']*32)) == 'ILOGIC_X0Y399'
    sample_tile = tiles + 1654*24
    sample_bels = bels(integer(sample_tile+4))
    assert sample_bels[10]['name'] == 'ENARDENINV' and sample_bels[10]['z'] == sample_bels[0]['z'] == 10
    collisions, bounds, sizes = [], [], []
    for type_index in range(type_count):
        type_name = constid(integer(types+type_index*32))
        groups = defaultdict(list)
        entries = bels(type_index)
        sizes.append(dict(type=type_name, count=len(entries)))
        for bel in entries:
            groups[bel['z']].append(bel)
            if not 0 <= bel['z'] < 256:
                bounds.append(dict(tile_type=type_name, bel=bel))
        for z, entries_at_z in groups.items():
            if len(entries_at_z) > 1:
                collisions.append(dict(tile_type=type_name, z=z, bels=entries_at_z,
                                       nonrouting_count=sum(not bel['routing'] for bel in entries_at_z)))
    report = dict(status='COMPLETED_READ_ONLY_BEL_LOCATION_AUDIT', created_utc=timestamp(), source=source,
                  chipdb_sha256=digest, device=device, dimensions=[width, height], tile_types=type_count,
                  collision_groups=len(collisions), nonrouting_collision_groups=sum(c['nonrouting_count'] > 1 for c in collisions),
                  z_out_of_bounds=bounds, max_bels_in_tile_type=max(sizes, key=lambda entry: entry['count']),
                  collisions=collisions, schema_crosschecks=['ILOGIC_X0Y399/CE1USED index24', 'RAMB18 ENARDENINV index10 z10'],
                  scope='Read-only binary database structure audit cross-checked against executed diagnostics. No database modification, architecture acceptance, physical placement or timing claim.')
assert fingerprint(sources) == source
out = ROOT / f'build/openxc7/bel-location-audit-{time.time_ns()}.json'
out.write_text(json.dumps(report, indent=2)+'\n')
print(out)
print(json.dumps({key: report[key] for key in ('device', 'dimensions', 'tile_types', 'collision_groups', 'nonrouting_collision_groups', 'max_bels_in_tile_type')}))
for collision in collisions:
    print(collision['tile_type'], collision['z'], [(bel['name'], bel['site'], bel['variant'], bel['routing']) for bel in collision['bels']])
