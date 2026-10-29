#!/usr/bin/env python3
"""Read-only root-BEL geometry audit for the actually observed live mux cluster.

Bind the current native worker, executable, version-6 database, source layout
and debugger snapshot. Check EVERY root BEL of the observed type in EVERY
database tile type, including optimistic non-slice roots. Zero candidates
proves this observed cluster cannot be placed, not whole-design infeasibility.
No process signals, engine/RTL/constraint repair, P&R, FPGA access or checksum
manifest. Source-bound diagnostics do not accept a corrected implementation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_himbaechel_timing import timing_inventory
from pack_prefix_board import ROOT, digest, timestamp
from evidence import source_revision

LIVE = ROOT / 'build/openxc7/full-prefix-shared-counter-safe-heap-place-1791488628202327384/report.json'
SNAPSHOT = ROOT / 'build/full_counter_safe_heap_readonly_cluster_actual_20261009.log'
DATABASE = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-build/share/himbaechel/xilinx/chipdb-xc7k480t.bin')
SOURCE = Path('/home/fedora/tiny-gpu/build/ypcb/nextpnr-himbaechel')
CONSTIDS = SOURCE / 'himbaechel/uarch/xilinx/constids.inc'
HEADER = SOURCE / 'himbaechel/chipdb.h'
CELL = 'rk_mapped_cell_86668.rk_mapped_cell_22977'
CONTROL = ROOT / 'tests/cmac/test_native_mux_cluster_geometry_control.py'


def snapshot_rows(text):
    assert text.count('READ_ONLY_CLUSTER_ROOT ' + CELL + '\n') == 1
    assert text.count('[Inferior 1 (process 1467616) detached]') == 1
    assert not re.search(r'(?im)error|traceback|optimized out.*ci', text)
    counts = re.findall(r'(?m)^attempts=(\d+) radius=(\d+) entries=(\d+) children=(\d+)$', text)
    assert len(counts) == 1 and tuple(map(int, counts[0][1:])) == (415, 2335, 8)
    pattern = r'(?m)^(.+) type=(\w+) cluster=(.+) relative=\((-?\d+),(-?\d+),(-?\d+)\) abs_z=(true|false) bel=\{tile = -1, index = -1\}$'
    found = re.findall(pattern, text)
    assert len(found) == 9 and found[0][0] == CELL
    assert len({r[0] for r in found}) == 9
    assert all(r[2] == CELL and r[3:5] == ('0', '0') and r[6] == 'false' for r in found)
    return [dict(name=r[0], type=r[1], z=int(r[5])) for r in found]


def candidate_geometry(rows, bels):
    """Optimistic role/relative-location check; no occupancy or timing claims."""
    assert rows and rows[0]['z'] == 0
    assert len({r['z'] for r in rows}) == len(rows)
    result = []
    for root_z, root in bels.items():
        if root['type'] != rows[0]['type']:
            continue
        missing = []
        for row in rows:
            target_z = root_z + row['z']
            target = bels.get(target_z)
            if target is None or target['type'] != row['type']:
                missing.append(dict(member=row['name'], wanted_z=target_z,
                                    wanted_type=row['type'], actual=target))
        result.append(dict(root_z=root_z, root_name=root['name'], missing=missing))
    return result


def database_bels(data, known):
    timing_inventory(data, known)  # Existing strict schema/device/ConstID validation.
    def integer(offset):
        assert 0 <= offset <= len(data) - 4
        return struct.unpack_from('<i', data, offset)[0]
    def pointer(offset):
        target = offset + integer(offset)
        assert 0 <= target < len(data)
        return target
    def array(offset, stride):
        start = pointer(offset)
        count = struct.unpack_from('<I', data, offset + 4)[0]
        assert start + count * stride <= len(data)
        return range(start, start + count * stride, stride)
    def string(offset):
        start = pointer(offset); end = data.find(b'\0', start)
        assert end >= start
        return data[start:end].decode('ascii')
    root = pointer(0); extra = pointer(root + 76)
    names = known + [string(p) for p in array(extra + 4, 4)]
    def name(offset):
        index = integer(offset)
        assert 0 <= index < len(names)
        return names[index]
    # Actual packed layouts: TileTypePOD=40 bytes, BelDataPOD=36 bytes.
    for tile in array(root + 28, 40):
        bels = {}
        for bel in array(tile + 4, 36):
            z = struct.unpack_from('<h', data, bel + 8)[0]
            assert z not in bels, 'Non-bijective native BEL locations'
            bels[z] = dict(name=name(bel), type=name(bel + 4))
        yield name(tile), bels


def main():
    native = json.loads(LIVE.read_text())
    assert native['status'] == 'RUNNING' and native['stage'] == 'native_place'
    assert (native['channels'], native['kernels'], native['parallel_products']) == (32, 16, 512)
    command = native['commands'][-1]
    assert command['label'] == 'native_place' and command['pid'] == 1467616
    argv = command['argv']; executable = Path(argv[0])
    assert argv[argv.index('--device') + 1] == 'xc7k480tffg1156-2'
    assert argv[argv.index('--seed') + 1] == '3588'
    assert Path(os.readlink('/proc/1467616/exe')) == executable
    assert Path('/proc/1467616/cmdline').read_bytes().split(b'\0')[:-1] == [a.encode() for a in argv]
    assert source_revision() == native['production_source_before']
    files = [DATABASE, CONSTIDS, HEADER, executable]
    before = {str(p): digest(p) for p in files}
    assert all(native['source'][name] == sha for name, sha in before.items())
    for p in (SNAPSHOT, CONTROL, Path(__file__), ROOT / 'tools/openxc7/read_heap_mux_cluster.gdb',
              ROOT / 'tools/openxc7/audit_himbaechel_timing.py'):
        before[str(p.resolve())] = digest(p)
    observed = SNAPSHOT.read_text()
    rows = snapshot_rows(observed)
    known = [''] + re.findall(r'^X\((\w+)\)\s*$', CONSTIDS.read_text(), re.M)
    candidates = []
    for tile, bels in database_bels(DATABASE.read_bytes(), known):
        candidates += [dict(tile_type=tile, **c) for c in candidate_geometry(rows, bels)]
    assert candidates
    compatible = [c for c in candidates if not c['missing']]
    assert not compatible, 'The observed cluster has a geometric candidate; do not claim intrinsic conflict'
    assert all(digest(name) == sha for name, sha in before.items())
    out = ROOT / f'build/openxc7/observed-native-mux-geometry-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    (out / 'observed-native-report.json').write_text(json.dumps(native, indent=2, sort_keys=True) + '\n')
    (out / 'observed-cluster.log').write_text(observed)
    (out / 'executed_source.py').write_bytes(Path(__file__).read_bytes())
    report = dict(status='CONFIRMED_OBSERVED_NATIVE_MUX_CLUSTER_ZERO_ROOT_GEOMETRY_NO_PROCESS_SIGNALLED',
                  finished_utc=timestamp(), scope=__doc__, source=before, current_native_pid=1467616,
                  native_report_at_observation=str(LIVE), source_cluster=rows,
                  production_source=source_revision(), candidate_type_root_pairs=len(candidates),
                  compatible_candidates=compatible, root_geometry_candidates=candidates,
                  full_design_infeasibility_proven=False, corrected_implementation_accepted=False,
                  processes_signalled=False, hardware_programmed=False,
                  artifacts={str(p.relative_to(ROOT)):digest(p) for p in out.iterdir() if p.is_file()})
    (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(out / 'report.json', flush=True)
    print(report['status'], flush=True)


if __name__ == '__main__':
    main()
