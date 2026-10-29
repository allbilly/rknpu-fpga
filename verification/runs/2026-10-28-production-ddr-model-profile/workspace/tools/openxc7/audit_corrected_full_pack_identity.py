#!/usr/bin/env python3
"""Compare every old/corrected full packed cell and the complete net-name table.

Only eight scalar DSP control pins may move from the packer's VCC net to
dedicated tile attributes. Their retained per-bit inversion represents the
same logical zero. Every other cell byte, DSP field/pin and named wire must
remain identical. This proves packed logical preservation, not physically
correct full FASM, placement transfer, numerical acceptance or signoff.
The current qualification report is snapshotted, never treated as terminal.
No input is edited and no SHA256SUMS manifest is written.
"""
from collections import Counter
import itertools
import json
import mmap
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_prefix_board import ROOT, TOP, DATABASE, JSON_WRITER, digest, timestamp
from place_prefix_board import verify_packed_metadata, verify_bindings
from build_dsp_constant_candidate import BUILT
from check_corrected_dsp_features import verify_corrected_packed
from check_prefix_native_features import dsp_expectations
from audit_upstream_dsp_constants import requirements, declared_ties
from probe_prefix_native_config import SELECTED
from evidence import source_revision

OLD = ROOT / 'build/openxc7/full-prefix-native-pack-1791394643587130253/report.json'
NATIVE = ROOT / 'build/openxc7/dsp-constant-qualification-1791414657664905509/report.json'
CONTROL = ROOT / 'tests/cmac/test_corrected_full_pack_identity_control.py'
SMALL = ROOT / 'build/openxc7/prefix-native-config-control-1791407940428316242'
FIRST_FAILED = ROOT / 'build/openxc7/corrected-full-pack-identity-1791415396100917123'
CELL_START = b'\n      "cells": {'
CELL_END = b'\n      },\n      "netnames": {'
RECORD = re.compile(rb'(?m)^        ("(?:[^"\\\r\n]|\\.)*"): \{$')


def layout(data):
    start = data.find(CELL_START)
    assert start >= 0 and data.find(CELL_START, start + 1) < 0, 'Unsupported native module/cell table'
    begin = start + len(CELL_START)
    end = data.find(CELL_END, begin)
    assert end > begin and data.find(CELL_END, end + 1) < 0, 'Incomplete/extra native cell table'
    assert data[-len(b'\n      }\n    }\n  }\n}\n'):] == b'\n      }\n    }\n  }\n}\n', 'Incomplete native export'
    return begin, end


def equal_ranges(left, a, b, right, c, d):
    assert b - a == d - c, 'Changed native export section length'
    for offset in range(0, b - a, 4 * 1024 * 1024):
        size = min(4 * 1024 * 1024, b - a - offset)
        assert left[a + offset:a + offset + size] == right[c + offset:c + offset + size], 'Changed named-wire/header data'


def records(data, begin, end):
    cursor, first = begin, True
    for match in RECORD.finditer(data, begin, end):
        assert data[cursor:match.start()] == (b'\n' if first else b',\n'), 'Unparsed native cell data'
        close = data.find(b'\n        }', match.end(), end)
        assert close >= 0, 'Incomplete native cell'
        close += len(b'\n        }')
        yield json.loads(match[1]), data[match.start():close]
        cursor, first = close, False
    assert not first and cursor == end, 'Missing/trailing native cell data'


def cell_value(record):
    item = json.loads(b'{' + record + b'}')
    assert len(item) == 1
    return next(iter(item.values()))


def constant_net(data, end, level):
    marker = b'        "$PACKER_' + level.encode() + b'_NET": {'
    start = data.find(marker, end)
    assert start >= 0 and data.find(marker, start + 1) < 0, 'Missing/duplicate packer constant net'
    close = data.find(b'\n        }', start)
    assert close > start, 'Incomplete packer constant net record'
    close += len(b'\n        }')
    value = cell_value(data[start:close])
    assert set(value) == {'hide_name', 'bits', 'attributes'} and len(value['bits']) == 1
    assert type(value['bits'][0]) is int and value['bits'][0] >= 2
    return value['bits'][0]


def compare_dsp_delta(old, new, original, vcc):
    verify_corrected_packed(original, new)
    assert set(old) == set(new) == {'hide_name', 'type', 'parameters', 'attributes', 'port_directions', 'connections'}
    for key in ('hide_name', 'type', 'parameters', 'port_directions'):
        assert old[key] == new[key], 'Changed DSP non-tie field: ' + key
    assert declared_ties(old) == dsp_expectations(original)['dedicated_constant_pins'], 'Changed old 31-tie profile'
    assert {k: v for k, v in old['attributes'].items() if k not in ('DSP_GND_PINS', 'DSP_VCC_PINS')} == {
        k: v for k, v in new['attributes'].items() if k not in ('DSP_GND_PINS', 'DSP_VCC_PINS')}, 'Changed DSP non-tie attributes'
    assert set(old['connections']) == set(new['connections']), 'Changed DSP pin membership'
    allowed = requirements(original)
    changed = set()
    for pin, before in old['connections'].items():
        after = new['connections'][pin]
        if pin in allowed:
            assert old['port_directions'][pin] == 'input' and before == [vcc] and after == [], 'Wrong DSP tile-pin disconnect'
            changed.add(pin)
        else:
            assert before == after, 'Changed ordinary DSP pin wire: ' + pin
    assert changed == set(allowed) and len(changed) == 8
    return len(changed)


def compare_exports(left, right, selected):
    """Generic exact comparator; only main's census admits the full target."""
    a, b = layout(left)
    c, d = layout(right)
    equal_ranges(left, 0, a, right, 0, c)
    equal_ranges(left, b, len(left), right, d, len(right))
    vcc, gnd = constant_net(left, b, 'VCC'), constant_net(left, b, 'GND')
    assert vcc != gnd
    counts, seen, dsps, constants = Counter(), set(), set(), {}
    unchanged, changed = 0, 0
    for old, new in itertools.zip_longest(records(left, a, b), records(right, c, d)):
        assert old is not None and new is not None and old[0] == new[0], 'Changed native cell membership/order'
        name, raw_old = old
        raw_new = new[1]
        assert name not in seen, 'Duplicate native cell name'
        seen.add(name)
        match = re.search(rb'\n          "type": "([^"]+)",\n', raw_old)
        assert match, 'Unsupported native cell type field'
        kind = match[1].decode()
        counts[kind] += 1
        if kind == 'DSP48E1_DSP48E1':
            assert name in selected and selected[name]['type'] == 'DSP48E1', 'Unexpected full DSP'
            changed += compare_dsp_delta(cell_value(raw_old), cell_value(raw_new), selected[name], vcc)
            dsps.add(name)
        else:
            assert raw_old == raw_new, 'Changed non-DSP cell: ' + name
            unchanged += 1
            if kind in ('PSEUDO_GND', 'PSEUDO_VCC'):
                value = cell_value(raw_old)
                level = kind.removeprefix('PSEUDO_')
                assert level not in constants and value['port_directions'] == {'Y': 'output'}
                assert value['connections'] == {'Y': [gnd if level == 'GND' else vcc]}, 'Changed constant-net driver'
                constants[level] = name
    assert set(constants) == {'GND', 'VCC'}
    assert dsps == {name for name, cell in selected.items() if cell['type'] == 'DSP48E1'}, 'Incomplete actual DSP membership'
    return dict(cells_compared=len(seen), unchanged_non_DSP_cell_records=unchanged,
        changed_DSP_records=len(dsps), source_defined_tile_pin_disconnections_compared=changed,
        primitive_counts=dict(counts), complete_named_wire_table_byte_identical=True,
        public_ports_and_packing_settings_byte_identical=True, ordinary_pin_wire_ids_unchanged=True,
        literal_DSP_parameters_and_non_tie_attributes_unchanged=True,
        disconnected_pin_normalization_used=False, comparison_view_executed=False)


def verify_native_pack_stage(report):
    assert report['part'] == 'xc7k480tffg1156-2' and report['full_target_parallel_products'] == 512
    assert report['full_board_native_pack_executed'] is True
    assert (report['full_packed_DSPs_compared'], report['full_packed_extra_tile_only_ties_compared']) == (515, 4120)
    assert report['full_pack_changed_ordinary_wire_identity_admitted'] is False
    assert len(report['full_packed_kernel_inventory']) == 16 and set(report['full_packed_kernel_inventory'].values()) == {32}
    commands = [step for step in report['commands'] if step['label'] == 'full_native_pack']
    assert len(commands) == 1
    step = commands[0]
    assert step['status'] == 'PASS_TOOL_EXECUTION_ONLY' and step['returncode'] == 0
    argv = step['argv']
    assert argv[0] == report['executable']['path']
    for flag, value in (('--chipdb', str(DATABASE)), ('--device', 'xc7k480tffg1156-2'), ('--top', TOP),
                        ('--freq', '50'), ('--seed', '3588')):
        assert argv.count(flag) == 1 and argv[argv.index(flag) + 1] == value
    assert '--pack-only' in argv and '--Werror' in argv and '--timing-allow-fail' not in argv
    for key in ('full_board_native_placement_executed', 'full_board_native_routing_executed',
                'full_board_native_FASM_executed', 'full_circuit_equivalence_claimed', 'full_board_numerical_acceptance',
                'old_full_placement_reuse_admitted', 'physical_fit_verified', 'timing_signoff', 'electrical_verified',
                'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert report[key] is False, 'Unsupported native-pack acceptance: ' + key
    return step


def main():
    out = ROOT / f'build/openxc7/corrected-full-pack-identity-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    report = dict(status='RUNNING', started_utc=timestamp(), scope=__doc__, source={}, full_parallel_products=512,
        full_native_qualification_acceptance_claimed=False, old_full_placement_transfer_admitted=False,
        native_placement_executed=False, native_routing_executed=False, numerical_acceptance=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False, drc_signoff=False,
        bitstream_emitted=False, hardware_programmed=False, production_source_before=source_revision())
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(out / 'report.json', flush=True)
    save()
    try:
        old = json.loads(OLD.read_text())
        verify_packed_metadata(old)
        native = json.loads(NATIVE.read_text())
        step = verify_native_pack_stage(native)
        snapshot = out / 'qualification-report-at-audit-launch.json'
        snapshot.write_text(json.dumps(native, indent=2, sort_keys=True) + '\n')
        build_path = Path(native['candidate_build_report'])
        built = json.loads(build_path.read_text())
        assert built['status'] == BUILT and built['executable'] == native['executable']
        original = ROOT / old['packed_design']
        corrected = Path(step['argv'][step['argv'].index('--write') + 1]).resolve(strict=True)
        assert corrected == NATIVE.parent / 'full-packed.json'
        before = dict(native['source'])
        paths = [Path(__file__), CONTROL, snapshot, OLD, original, corrected, Path(step['log']),
                 SELECTED, JSON_WRITER, Path(sys.executable).resolve(strict=True), SMALL / 'report.json',
                 SMALL / 'routed.json', SMALL / 'clock-admitted-packed.json',
                 FIRST_FAILED / 'report.json', FIRST_FAILED / 'executed_source.py',
                 FIRST_FAILED / 'control-source-at-failed-run.py']
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename and Path(filename).resolve().is_relative_to(ROOT / 'tools'):
                paths.append(Path(filename).resolve())
        for path in paths:
            path = path.resolve(strict=True)
            sha = digest(path)
            assert str(path) not in before or before[str(path)] == sha, 'Changed inherited native input'
            before[str(path)] = sha
        assert before[str(original)] == old['artifacts'][str(original.relative_to(ROOT))]
        small = json.loads((SMALL / 'report.json').read_text())
        for filename in ('routed.json', 'clock-admitted-packed.json'):
            path = SMALL / filename
            assert before[str(path)] == small['artifacts'][str(path.relative_to(ROOT))], 'Changed saved native parser-control input'
        failed = json.loads((FIRST_FAILED / 'report.json').read_text())
        assert failed['status'] == 'FAIL' and failed['error'] == "AssertionError('Incomplete/extra native cell table')"
        assert before[str(FIRST_FAILED / 'control-source-at-failed-run.py')] == failed['source'][str(CONTROL)]
        verify_bindings(before)
        report.update(source=before, original_pack_report=str(OLD), corrected_pack_report_snapshot=str(snapshot),
                      live_qualification_report=str(NATIVE), corrected_pack_path=str(corrected),
                      earlier_failed_attempt_preserved=str(FIRST_FAILED / 'report.json'),
                      exact_pinned_cell_table_delimiter='one newline before netnames, per jsonwrite.cc')
        save()
        argv = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v']
        report['software_control_argv'] = argv
        started = time.monotonic()
        with (out / 'software_controls.log').open('w') as log:
            subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        report['software_control_seconds'] = round(time.monotonic() - started, 3)
        selected = json.loads(SELECTED.read_text())
        started = time.monotonic()
        with original.open('rb') as one, corrected.open('rb') as two, \
                mmap.mmap(one.fileno(), 0, access=mmap.ACCESS_READ) as left, \
                mmap.mmap(two.fileno(), 0, access=mmap.ACCESS_READ) as right:
            comparison = compare_exports(left, right, selected)
        report['comparison_seconds'] = round(time.monotonic() - started, 3)
        assert comparison['primitive_counts'] == old['native_packed_cell_counts'], 'Changed full native resource counts'
        assert (comparison['changed_DSP_records'], comparison['source_defined_tile_pin_disconnections_compared']) == (515, 4120)
        groups = Counter(name.split('.')[0] for name, cell in selected.items() if cell['type'] == 'DSP48E1' and '.' in name)
        assert dict(groups) == old['retained_kernel_dsps'] == native['full_packed_kernel_inventory']
        report['comparison'] = comparison
        verify_bindings(before)
        report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status='PASS_FULL_PACKED_LOGICAL_IDENTITY_EXCEPT_EXACT_DSP_TILE_CONSTANT_REPRESENTATION_NOT_PLACEMENT_TRANSFER_OR_SIGNOFF')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(path.relative_to(ROOT)): digest(path) for path in out.iterdir()
                               if path.is_file() and path.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
