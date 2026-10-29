#!/usr/bin/env python3
"""Inspect a qualified candidate's actual timing tables; never physical signoff.

Reads the packed little-endian version-6 Himbaechel database, using the
RelPtr/RelSlice and ChipInfoPOD layouts in the qualified source. Does not
execute the donor's scripts, rebuild tools, place/route, emit bits or program.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, timestamp

QUALIFIED = 'PASS_DISTINCT_LUT_PAIR_LEGALITY_AND_NATIVE_PLACEMENT_PROBES_NOT_FULL_CORE_PNR'
HOST_DEPENDENCIES = {
    '/home/linuxbrew/.linuxbrew/Cellar/yosys/0.65/bin/yosys', '/usr/bin/c++',
    *[f'/usr/lib64/libboost_{name}.so.1.90.0' for name in
      ('atomic', 'chrono', 'container', 'date_time', 'iostreams',
       'program_options', 'random', 'regex', 'thread')],
}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def timing_inventory(data, known_names):
    """Return table presence and arc counts, not correctness/coverage of a design."""
    def checked(offset, size):
        if offset < 0 or size < 0 or offset + size > len(data):
            raise ValueError(f'Database range outside blob: {offset}, {size}')
        return offset

    def integer(offset):
        return struct.unpack_from('<i', data, checked(offset, 4))[0]

    def pointer(offset, size):
        relative = integer(offset)
        if relative == 0:
            raise ValueError(f'Null required pointer at {offset}')
        return checked(offset + relative, size)

    def array(offset, stride):
        relative, count = struct.unpack_from('<iI', data, checked(offset, 8))
        if count and not relative:
            raise ValueError(f'Null nonempty slice at {offset}')
        start = checked(offset + relative, count * stride)
        return [start + i * stride for i in range(count)]

    def string(offset):
        start = pointer(offset, 1)
        end = data.find(b'\0', start)
        if end == -1:
            raise ValueError('Unterminated database string')
        return data[start:end].decode('ascii')

    root = pointer(0, 84)
    if (integer(root), integer(root + 4)) != (0x00ca7ca7, 6):
        raise ValueError('Only packed little-endian Himbaechel schema version 6 is supported')
    if string(root + 16) != 'xilinx' or string(root + 20) != 'xc7k480t':
        raise ValueError('Expected exact xc7k480t Xilinx database')
    constids = pointer(root + 76, 12)
    if integer(constids) != len(known_names):
        raise ValueError('ConstID count does not match the qualified enum')
    names = list(known_names) + [string(p) for p in array(constids + 4, 4)]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate ConstID names')

    def name(index):
        if not 0 <= index < len(names):
            raise ValueError(f'Invalid ConstID {index}')
        return names[index]

    grades = []
    for grade in array(root + 68, 32):
        cells = {}
        for cell in array(grade + 20, 12):
            cell_name = name(integer(cell))
            if cell_name in cells:
                raise ValueError('Duplicate timing cell type')
            pins = {}
            for pin in array(cell + 4, 24):
                pin_name = name(integer(pin))
                if pin_name in pins:
                    raise ValueError('Duplicate timing pin')
                comb = array(pin + 8, 20)
                reg = array(pin + 16, 56)
                # Validate every referenced signal/clock, not just table totals.
                for arc in comb:
                    name(integer(arc))
                for arc in reg:
                    name(integer(arc))
                    if integer(arc + 4) not in (0, 1):
                        raise ValueError('Unknown clock edge')
                pins[pin_name] = dict(combinational_arcs=len(comb),
                                      sequential_arcs=len(reg),
                                      clock_flag=bool(integer(pin + 4) & 1))
            cells[cell_name] = dict(pins=pins,
                combinational_arcs=sum(p['combinational_arcs'] for p in pins.values()),
                sequential_arcs=sum(p['sequential_arcs'] for p in pins.values()))
        grades.append(dict(name=name(integer(grade)), cell_types=cells,
            pip_timing_classes=len(array(grade + 4, 52)),
            node_timing_classes=len(array(grade + 12, 48))))
    if not grades or len({g['name'] for g in grades}) != len(grades):
        raise ValueError('Missing or duplicate speed grades')
    return dict(device=string(root + 20), generator=string(root + 24),
                schema_version=6, known_constids=len(known_names),
                dynamic_constids=len(names) - len(known_names), speed_grades=grades)


def audit(qualification_path, database_path, constids_path):
    q = json.loads(qualification_path.read_text())
    if q['status'] != QUALIFIED or q['part'] != 'xc7k480tffg1156-2':
        raise ValueError('Candidate is not the exact-part narrow legality qualification')
    if (q['native_positive_placements'], q['lut_output_comparisons']) != (3, 1024):
        raise ValueError('Unexpected qualification scope')
    observed = {}
    for path, expected in q['inputs'].items():
        source = Path(path).resolve(strict=True)
        if path not in HOST_DEPENDENCIES and not any(source.is_relative_to(base) for base in
                   (Path('/home/fedora/soDLA'), Path('/home/fedora/tiny-gpu'))):
            raise ValueError('Out-of-scope candidate dependency')
        actual = digest(source)
        if actual != expected:
            raise ValueError(f'Changed candidate dependency: {path}')
        observed[path] = actual
    for path in (database_path, constids_path, Path(q['executable']['path'])):
        if str(path) not in observed or digest(path) != observed[str(path)]:
            raise ValueError(f'Unbound selected input: {path}')
    text = constids_path.read_text()
    known = [''] + re.findall(r'^X\((\w+)\)\s*$', text, re.MULTILINE)
    inventory = timing_inventory(database_path.read_bytes(), known)
    # Pin the inspected bytes around parsing; this is not an atomic snapshot
    # of the donor checkout or a rerun of its historical native probes.
    for path in (database_path, constids_path):
        if digest(path) != observed[str(path)]:
            raise ValueError('Selected input changed during timing inventory')
    return dict(candidate_status=q['status'], candidate_scope=q['scope'],
        candidate_source_revision=q['source_revision'],
        checked_candidate_dependency_count=len(observed),
        checked_candidate_dependency_sha256=hashlib.sha256(json.dumps(
            observed, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        selected_database_sha256=observed[str(database_path)],
        selected_constids_sha256=observed[str(constids_path)], inventory=inventory,
        native_probes_rerun=False, whole_architecture_revalidated=False,
        full_rknpu_design_timing_coverage_verified=False, physical_fit_verified=False,
        electrical_verified=False, timing_signoff=False, bitstream_emitted=False,
        hardware_programmed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualification', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--constids', type=Path, required=True)
    args = parser.parse_args()
    paths = [p.resolve(strict=True) for p in
             (args.qualification, args.database, args.constids)]
    out = ROOT / f'build/openxc7/himbaechel-timing-inventory-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    before = {str(p): digest(p) for p in paths + [Path(__file__)]}
    # Preserve the actual parser behind this observation, including failures.
    (out / 'audit_source.py').write_bytes(Path(__file__).read_bytes())
    report = dict(status='RUNNING', started_utc=timestamp(),
        python_version=platform.python_version(), inputs=before,
        scope='Read-only actual binary timing-table inventory and current per-file '
        'candidate hash checks only. No native qualification rerun, cell/port coverage '
        'of the full RKNPU circuit, placement/route, speed-grade timing, electrical '
        'signoff, bitstream or FPGA programming.')
    try:
        report.update(audit(*paths), status='AUDITED_BINARY_TIMING_TABLES_NOT_SIGNOFF')
        if any(digest(p) != sha for p, sha in before.items()):
            raise ValueError('Audit input changed')
    except Exception as error:
        report.update(status='FAIL_TIMING_INVENTORY', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
