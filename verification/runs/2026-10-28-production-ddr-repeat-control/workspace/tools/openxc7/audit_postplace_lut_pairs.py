#!/usr/bin/env python3
"""Read-only fixed LUT-pair/A6-mode audit, not a native validity rescan.

The pinned fixup_placement connects a paired 6LUT's unannotated A6 to VCC;
A1..A5 are the five shared physical inputs. Preserve the old pre-placement
legality checker. This audit changes no tags, circuit, route or FPGA input.
Saved small outputs are parser/contract controls, not full-board acceptance.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_prefix_board import ROOT, digest, timestamp
from route_prefix_board import logical_lut
from correct_placed_dsp_constants import constant_drivers
from place_prefix_board import verify_bindings
from evidence import source_revision

PAIR_SOURCE = Path('/home/fedora/soDLA/build/ypcb/lut-pair-engine-1791377260734986151/himbaechel/uarch/xilinx/xilinx_place.cc')
TAG_SOURCE = Path('/home/fedora/soDLA/build/ypcb/heap-beta-engine-1791307049291727187/himbaechel/uarch/xilinx/xilinx.cc')
CONTROL = ROOT / 'tests/cmac/test_postplace_lut_pair_control.py'
QUALIFICATION = ROOT / 'build/openxc7/dsp-constant-qualification-1791414657664905509/report.json'
CHECKPOINT = ROOT / 'build/openxc7/corrected-dsp-checkpoint-control-1791417172851071744/report.json'
RESUME = ROOT / 'build/openxc7/corrected-dsp-checkpoint-resume-1791418453459203706/report.json'
FIRST_FAILED = ROOT / 'build/openxc7/postplace-LUT-pair-audit-1791421025029697685'


def audit_pairs(module):
    """Physical pair incidence/mode only; never rewrite a native input."""
    cells = module['cells']
    by_bel = {}
    for name, cell in cells.items():
        bel = cell['attributes']['NEXTPNR_BEL']
        assert bel not in by_bel, 'Duplicate physical BEL'
        by_bel[bel] = name
    vcc = constant_drivers(module)['VCC']
    pairs = {}
    for bel, name in by_bel.items():
        if not bel.endswith('5LUT'):
            continue
        first = cells[name]
        assert first['type'] == 'SLICE_LUTX', 'Unmodeled 5LUT resource'
        assert not any(key in first['attributes'] for key in ('X_LUT_AS_DRAM', 'X_LUT_AS_SRL')), 'Memory/SRL pair profile unsupported'
        assert not first['connections'].get('A6'), '5LUT has a connected A6'
        other = by_bel.get(bel[:-4] + '6LUT')
        if other is None:
            continue
        second = cells[other]
        assert second['type'] == 'SLICE_LUTX'
        assert not any(key in second['attributes'] for key in ('X_LUT_AS_DRAM', 'X_LUT_AS_SRL')), 'Memory/SRL pair profile unsupported'
        for cell in (first, second):
            assert re.fullmatch(r'LUT[1-5]', cell['attributes']['X_ORIG_TYPE']), 'Unsupported paired logical LUT kind'
            logical_lut(cell)  # Complete original logical pin annotations stay strict.
        assert first['connections'].get('O5') and not first['connections'].get('O6'), 'Changed 5LUT output role'
        assert second['connections'].get('O6') and not second['connections'].get('O5'), 'Changed 6LUT output role'
        assert 'X_ORIG_PORT_A6' not in second['attributes'], 'A6 is a logical input, not synthetic pair mode'
        assert second['port_directions'].get('A6') == 'input' and second['connections'].get('A6') == [vcc], 'Paired A6 is not the source-defined VCC mode tie'
        shared = set()
        for index in range(1, 6):
            pin = 'A' + str(index)
            a, b = first['connections'].get(pin, []), second['connections'].get(pin, [])
            for cell, bits in ((first, a), (second, b)):
                assert len(bits) <= 1 and (pin not in cell['connections'] or cell['port_directions'][pin] == 'input')
            assert not a or not b or a == b, 'Different nets on the same shared physical LUT pin'
            shared.update(a + b)
        assert len(shared) <= 5, 'More than five shared physical inputs'
        all_inputs = {bit for cell in (first, second) for index in range(1, 7)
                      for bit in cell['connections'].get('A' + str(index), [])}
        pairs[name] = dict(other_cell=other, fixed_shared_input_count=len(shared),
            naive_tag_input_union_count=len(all_inputs), synthetic_A6_VCC_not_a_shared_input=True,
            same_physical_shared_pin_incidence_checked=True)
    return dict(cells_observed=len(cells), logic_pairs_compared=len(pairs), pairs=pairs,
        six_input_naive_tag_unions=sum(record['naive_tag_input_union_count'] == 6 for record in pairs.values()),
        circuit_or_tags_modified=False, native_validity_rescan_executed=False,
        full_board_placement_or_route_admitted=False, numerical_or_physical_signoff=False)


def audit_export(module):
    """Separate source-defined postRoute metadata view; strict core unchanged.

    fixup_routing mirrors each permutation's connection onto both LUT records,
    even when one has no logical mapping. It can add the paired 6LUT's A6 mode
    tie to the 5LUT record. Only that exact unannotated, matching VCC mirror
    is omitted for the physical pair comparison. This view is never executed.
    """
    route = module.get('settings', {}).get('route', '0')
    assert re.fullmatch('[01]{1,32}', route), 'Unknown route-stage encoding'
    if int(route, 2) == 0:
        return audit_pairs(module)
    assert int(route, 2) == 1, 'Unknown route stage'
    cells = module['cells']
    by_bel = {}
    for name, cell in cells.items():
        bel = cell['attributes']['NEXTPNR_BEL']
        assert bel not in by_bel, 'Duplicate physical BEL'
        by_bel[bel] = name
    vcc = constant_drivers(module)['VCC']
    view = dict(cells)
    mirrored = 0
    for bel, name in by_bel.items():
        cell = cells[name]
        if not bel.endswith('5LUT') or not cell['connections'].get('A6'):
            continue
        other = by_bel.get(bel[:-4] + '6LUT')
        assert other is not None, 'Unpaired routed 5LUT A6 connection'
        partner = cells[other]
        assert cell['type'] == partner['type'] == 'SLICE_LUTX'
        for item in (cell, partner):
            assert 'X_ORIG_PORT_A6' not in item['attributes'], 'Routed A6 has a logical mapping'
            assert item['port_directions'].get('A6') == 'input'
            assert item['connections']['A6'] == [vcc], 'Wrong/mismatched routed A6 VCC mirror'
            logical_lut(item)
        connections, directions = dict(cell['connections']), dict(cell['port_directions'])
        del connections['A6'], directions['A6']
        view[name] = dict(cell, connections=connections, port_directions=directions)
        mirrored += 1
    result = audit_pairs(dict(module, cells=view))
    result['postRoute_metadata_view'] = dict(
        contract='PINNED_FIXUP_ROUTING_MIRRORS_UNANNOTATED_PERMUTATION_CONNECTIONS_TO_BOTH_LUT_RECORDS',
        exact_5LUT_A6_VCC_mirrors_omitted_in_comparison=mirrored,
        hardware_execution_input_modified=False, comparison_view_executed=False,
        logical_A6_mapping_or_non_VCC_mirror_admitted=False)
    return result


def main():
    out = ROOT / f'build/openxc7/postplace-LUT-pair-audit-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), scope=__doc__,
        source={}, commands=[], source_inference_not_native_validity_execution=True,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
        drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        production_source_before=source_revision(), python_version=sys.version)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(out / 'report.json', flush=True)
    save()
    try:
        q = json.loads(QUALIFICATION.read_text())
        files = [Path(__file__), CONTROL, PAIR_SOURCE, TAG_SOURCE, Path(sys.executable).resolve(strict=True)]
        failed = json.loads((FIRST_FAILED / 'report.json').read_text())
        assert failed['status'] == 'FAIL' and '5LUT has a connected A6' in failed['error']
        for name, source in [('executed_source.py', Path(__file__)), ('executed_control_source.py', CONTROL)]:
            path = FIRST_FAILED / name
            assert digest(path) == failed['source'][str(source.resolve())], 'Changed original failed source snapshot'
            files.append(path)
        for name, sha in failed['artifacts'].items():
            path = ROOT / name
            assert path.is_relative_to(FIRST_FAILED) and digest(path) == sha
            files.append(path)
        files.append(FIRST_FAILED / 'report.json')
        report['original_failure_report_preserved'] = str(FIRST_FAILED / 'report.json')
        targets = [(QUALIFICATION, 'valid-forced-placed.json'), (CHECKPOINT, 'placed.json'), (RESUME, 'routed.json')]
        for parent_path, name in targets:
            parent = json.loads(parent_path.read_text())
            path = parent_path.parent / name
            assert digest(path) == parent['artifacts'][str(path.relative_to(ROOT))], 'Changed saved native target'
            files.extend((parent_path, path))
        for path in (PAIR_SOURCE, TAG_SOURCE):
            assert digest(path) == q['source'][str(path)], 'Changed compiled source contract'
        files.extend(Path(module.__file__).resolve() for module in list(sys.modules.values())
                     if getattr(module, '__file__', None) and Path(module.__file__).resolve().is_relative_to(ROOT / 'tools'))
        report['source'] = {str(path.resolve(strict=True)): digest(path) for path in files}
        verify_bindings(report['source'])
        for label, argv in [('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v']),
                            ('generated_check', ['make', 'generated-check'])]:
            step = dict(label=label, argv=argv, log=str(out / (label + '.log')), status='RUNNING')
            report['commands'].append(step)
            save()
            start = time.monotonic()
            with Path(step['log']).open('w') as stream:
                result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
            step.update(returncode=result.returncode, seconds=round(time.monotonic() - start, 3),
                        status='PASS_SOFTWARE_ONLY' if result.returncode == 0 else 'FAIL')
            assert result.returncode == 0, Path(step['log']).read_text()[-3000:]
        report['stage'] = 'saved_native_pair_contract_audit'
        report['target_comparisons'] = {}
        for parent_path, name in targets:
            path = parent_path.parent / name
            module = next(iter(json.loads(path.read_text())['modules'].values()))
            report['target_comparisons'][str(path)] = audit_export(module)
        verify_bindings(report['source'])
        report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status='AUDITED_SAVED_FIXED_LUT_PAIR_MODE_AND_SHARED_INPUT_CONTRACT_NOT_NATIVE_VALIDITY_OR_SIGNOFF', stage='complete')
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
