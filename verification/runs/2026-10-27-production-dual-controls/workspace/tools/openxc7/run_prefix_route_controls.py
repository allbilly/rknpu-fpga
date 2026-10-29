#!/usr/bin/env python3
"""Source-bound full-routing gate controls using saved small exports only.

No new native placement/routing, full-board acceptance, bitstream or hardware
action. Revalidate old artifact/source bindings before read-only comparison;
old route execution remains old evidence, not copied as a new tool run.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route_prefix_board as gate
from place_prefix_board import PACK_PARENT
from evidence import ROOT, fingerprint, source_revision, timestamp

CONTROL = ROOT / 'tests/cmac/test_prefix_full_route_control.py'
FEATURE_TEST = ROOT / 'tests/cmac/test_prefix_full_feature_control.py'


def packed_lut_inventory(path, expected, selected):
    """Bounded read-only scan of the qualified jsonwrite.cc pretty format.

    Decode each complete cell as JSON; assert full primitive counts rather
    than relying on regex matches. This inventory validates each real logical
    LUT schema, not packing circuitry identity or routed acceptance.
    """
    counts, widths = Counter(), Counter()
    logical_luts = 0
    selected_primitives = {}
    with path.open() as stream:
        for line in stream:
            if line == '      "cells": {\n': break
        else: raise AssertionError('Missing qualified native cells object')
        for line in stream:
            if line.startswith('      }'): break
            assert re.match(r'^        "', line), 'Unexpected native cell formatting'
            block = [line]
            for line in stream:
                block.append(line)
                if line.startswith('        }'): break
            else: raise AssertionError('Incomplete native cell object')
            record = json.loads('{' + ''.join(block).rstrip().removesuffix(',') + '}')
            assert len(record) == 1
            name, cell = next(iter(record.items()))
            counts[cell['type']] += 1
            if cell['type'] in ('DSP48E1_DSP48E1', 'RAMB36E1_RAMB36E1'):
                assert name not in selected_primitives, 'Duplicate packed DSP/BRAM record'
                selected_primitives[name] = cell
            if cell['type'] == 'SLICE_LUTX':
                gate.logical_lut(cell)
                logical_luts += 1
                widths[(cell['attributes']['X_ORIG_TYPE'], len(cell['parameters']['INIT']))] += 1
        else: raise AssertionError('Missing native cells object terminator')
    assert dict(counts) == expected, 'Incomplete/changed full native primitive inventory'
    from check_full_native_features import full_inventory
    groups = full_inventory(selected, selected_primitives)
    return dict(primitive_counts=dict(counts), logical_luts_checked=logical_luts,
        full_packed_DSP_BRAM_inventory=dict(kernel_dsps=groups, selected_primitives=len(selected_primitives)),
        native_INIT_representations=[dict(original_type=kind, literal_bits=width, cells=count)
            for (kind, width), count in sorted(widths.items())],
        original_pin_contract='PINNED_FIXUP_ROUTING_AND_FASM_GET_LUT_INIT_LUT1_TO_LUT6_ONLY',
        full_native_routing_executed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--small-route', type=Path, required=True,
                        help='Completed source-bound small routing control for the precision engine')
    args = parser.parse_args()
    small_path = (ROOT / args.small_route).resolve(strict=True)
    assert small_path.is_relative_to(ROOT / 'build/openxc7')
    out = ROOT / f'build/openxc7/prefix-route-gate-controls-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', started_utc=timestamp(), scope=__doc__,
        commands=[], full_board_native_routing_executed=False,
        new_small_native_routing_executed=False, physical_fit_verified=False,
        new_native_configuration_execution=False, full_native_FASM_comparison_executed=False,
        numerical_netlist_acceptance=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False,
        hardware_programmed=False, production_source_before=source_revision())

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    save()
    print(out / 'report.json', flush=True)
    before = {}
    try:
        # Independently revalidate saved qualification/placed/routed artifacts.
        small = json.loads(small_path.read_text())
        gate.verify_small_route_metadata(small)
        gate.bind_report(small_path, small, before)
        packed = json.loads(PACK_PARENT.read_text())
        gate.verify_packed_metadata(packed)
        gate.bind_report(PACK_PARENT, packed, before)
        qualification_path = Path(small['native_tool_transition']['selected_qualification']).resolve(strict=True)
        assert str(qualification_path) in before, 'Unbound small-routing engine'
        inventory, candidate, transition = gate.verify_native_tool_transition(qualification_path)
        assert transition == small['native_tool_transition'], 'Changed selected routing engine'
        feature = json.loads(gate.FEATURE_CONTROL.read_text())
        gate.verify_feature_control_metadata(feature, transition)
        gate.bind_report(gate.FEATURE_CONTROL, feature, before)
        for name, sha in candidate['inputs'].items():
            assert name not in before or before[name] == sha, 'Conflicting qualified input binding'
        before.update(candidate['inputs'])
        paths = {Path(__file__).resolve(), CONTROL, FEATURE_TEST}
        paths.update(Path(module.__file__).resolve() for module in list(sys.modules.values())
                     if getattr(module, '__file__', None)
                     and Path(module.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in paths:
            sha = gate.digest(path)
            assert str(path) not in before or before[str(path)] == sha, 'Changed admitted helper source'
            before[str(path)] = sha
            frozen = out / 'sources' / path.relative_to(ROOT)
            frozen.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, frozen)
        before[str(qualification_path)] = gate.digest(qualification_path)
        report.update(source=before, saved_small_route_report=str(small_path.relative_to(ROOT)),
                      native_tool_transition=transition,
                      saved_native_feature_control_report=str(gate.FEATURE_CONTROL.relative_to(ROOT)),
                      admitted_full_pack_report=str(PACK_PARENT.relative_to(ROOT)))
        save()
        gate.verify_bindings(before)
        report['timing_inventory'] = inventory
        for label, argv in (
            ('python_version', [sys.executable, '--version']),
            ('controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v']),
            ('full_feature_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', FEATURE_TEST.name, '-v']),
            ('generated_check', ['make', 'generated-check'])):
            log = out / (label + '.log')
            step = dict(label=label, argv=argv, cwd=str(ROOT), log=str(log.relative_to(ROOT)), status='RUNNING')
            report['commands'].append(step)
            save()
            start = time.monotonic()
            try:
                with log.open('w') as stream:
                    result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                        stderr=subprocess.STDOUT, timeout=300, check=False)
                step.update(returncode=result.returncode, status='PASS' if result.returncode == 0 else 'FAIL')
                assert result.returncode == 0, log.read_text()[-3500:]
            except BaseException:
                step['status'] = 'FAIL'
                raise
            finally:
                step['seconds'] = round(time.monotonic() - start, 3)
                save()
        # This is a fresh read-only identity validation, not re-execution of
        # the historical small router. Both levels are explicitly separate.
        sys.path.insert(0, str(CONTROL.parent))
        from test_prefix_full_route_control import small_export_identity
        report['saved_small_export_validation'] = small_export_identity(small_path)
        packed_path = (ROOT / packed['packed_design']).resolve(strict=True)
        assert str(packed_path) in before and packed_path.is_relative_to(PACK_PARENT.parent)
        selected = json.loads(gate.SELECTED.read_text())
        report['full_packed_LUT_contract_inventory'] = packed_lut_inventory(packed_path, packed['native_packed_cell_counts'], selected)
        gate.verify_bindings(before)
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='PASS_FULL_ROUTING_GATE_SOFTWARE_AND_SAVED_SMALL_EXPORT_CONTROLS_NOT_FULL_ROUTE_OR_SIGNOFF')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([path for path in out.rglob('*') if path.is_file() and path.name != 'report.json'])
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
