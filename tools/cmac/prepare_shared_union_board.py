#!/usr/bin/env python3
"""Reversible whole C32/K16 union-LUT preparation; no HDL or physical pass.

Consume only the completed hash-bound shared-board analysis. Repair the
existing direct O6 conflicts by splitting or reorienting those old pairs.
All other hardware and metadata must restore literally. This structural
candidate remains inadmissible to numerical/physical flows until its new
function domain and complete board behavior are independently validated.
"""
from collections import Counter
from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from analyze_shared_union_lut_pairs import IMPLEMENTATIONS, TOP, load_parent
from analyze_union_lut_pairs import union_function, verify_proposals
from audit_lut_pair_sinks import audit_module, multiplicities
from pair_board_luts import implementation_module_aliases, value
from prepare_shared_board import physical_counts
from export_board_netlist import structural_board_verilog
from test_fixed_array_board import verify_manifest
from test_fixed_mapped_array import circuit_signature, hardware_instance_aliases


def key(function):
    return json.dumps(function, sort_keys=True, separators=(',', ':'))


def validate_analysis(report):
    assert report['status'] == 'ANALYZED_SHARED_BOARD_UNION_FANIN_LUT_OPPORTUNITIES_ONLY'
    assert report['stage'] == 'complete'
    assert (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
    copies = report['implementation_copies']
    assert set(copies) == IMPLEMENTATIONS and copies[TOP] == 1
    assert sorted(copies.values()) == [1, 1, 16]
    assert set(report['module_statistics']) == IMPLEMENTATIONS
    total = sum(copies[n] * report['module_statistics'][n]['proposed_pairs'] for n in copies)
    assert total > 0 and total == report['weighted_opportunities']['additional_disjoint_pairs']
    assert report['projected_lut_primitives'] == report['candidate_lut_primitives'] - total
    for field in ('netlist_changed', 'function_classes_hdl_acceptance', 'numerical_netlist_acceptance',
            'packed_resource_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[field] is False, 'Misrepresented analysis acceptance'


def union_cell(a, b, fanins, function):
    actual_pins, actual = union_function(a, b)
    assert actual_pins == fanins and actual == function
    return dict(hide_name=0, type='LUT6_2', parameters={'INIT': function['init']}, attributes={},
        port_directions={**{f'I{i}': 'input' for i in range(6)}, 'O5': 'output', 'O6': 'output'},
        connections={**{f'I{i}': [fanins[i] if i < len(fanins) else '0'] for i in range(5)},
            'I5': ['1'], 'O5': list(a['connections']['O']), 'O6': list(b['connections']['O'])})


def role_replacement(cell, mode):
    # audit_module has established the exact binary 64-bit INIT/I5=1 schema.
    assert cell['type'] == 'LUT6_2' and cell['connections']['I5'] == ['1']
    init = cell['parameters']['INIT']
    assert len(init) == 64 and set(init) <= {'0', '1'}
    if mode == 'swap':
        result = deepcopy(cell)
        result['parameters']['INIT'] = init[32:] + init[:32]
        result['connections']['O5'], result['connections']['O6'] = (
            result['connections']['O6'], result['connections']['O5'])
        return [result]
    assert mode == 'split', 'Unknown role repair'
    result = []
    for output, half in [('O5', init[32:]), ('O6', init[:32])]:
        result.append(dict(hide_name=0, type='LUT5', parameters={'INIT': half}, attributes={},
            port_directions={**{f'I{i}': 'input' for i in range(5)}, 'O': 'output'},
            connections={**{f'I{i}': list(cell['connections'][f'I{i}']) for i in range(5)},
                'O': list(cell['connections'][output])}))
    return result


def role_function(cell, mode):
    pins = [cell['connections'][f'I{i}'][0] for i in range(5)]
    fanins = sorted(b for b in pins if type(b) is int)
    assert len(set(fanins)) == len(fanins) and 1 <= len(fanins) <= 5
    assert all(type(b) is int or b in ('0', '1') for b in pins)
    init = cell['parameters']['INIT']
    first, second = (init[:32], init[32:]) if mode == 'swap' else (init[32:], init[:32])
    specs = [dict(kind='LUT5', init=half,
        pins=[fanins.index(b) if type(b) is int else b for b in pins]) for half in (first, second)]
    return dict(fanins=len(fanins), first=specs[0], second=specs[1], init=second + first)


def transform(original, proposals, classes, implementations):
    assert set(proposals) == set(implementations)
    candidate, certificate, functions = deepcopy(original), {}, {}
    union_domain = {r['function_key'] for records in proposals.values() for r in records}
    assert union_domain == set(classes), 'Unlisted or missing union function domain'
    for module in sorted(implementations):
        old = original['modules'][module]
        local = {r['function_key']: classes[r['function_key']] for r in proposals[module]}
        verify_proposals(old, proposals[module], local)
        functions.update(local)
        cells = candidate['modules'][module]['cells']
        unions, repairs = [], []
        for i, record in enumerate(proposals[module]):
            name = f'rk_union_pair_{i}'
            assert name not in old['cells'], 'Union instance collision'
            a, b = [old['cells'][record[f]] for f in ('first', 'second')]
            cells[name] = union_cell(a, b, record['fanins'], classes[record['function_key']])
            del cells[record['first']]; del cells[record['second']]
            unions.append(dict(record, name=name))
        for i, item in enumerate(audit_module(old)):
            if not item['o5_has_dedicated_o6_sink']:
                continue
            mode = 'split' if item['both_outputs_need_o6'] else 'swap'
            replacements = role_replacement(old['cells'][item['cell']], mode)
            names = [f'rk_union_role_{i}_{j}' for j in range(len(replacements))]
            assert not set(names) & set(cells) and not set(names) & set(old['cells']), 'Role instance collision'
            del cells[item['cell']]
            cells.update(zip(names, replacements))
            function = role_function(old['cells'][item['cell']], mode)
            functions[key(function)] = function
            repairs.append(dict(cell=item['cell'], mode=mode, names=names, function_key=key(function)))
        certificate[module] = dict(unions=unions, roles=repairs)
    verify_transform(original, candidate, certificate, functions, implementations)
    return candidate, certificate, functions


def verify_transform(original, candidate, certificate, classes, implementations):
    assert set(certificate) == set(implementations)
    restored, actual = deepcopy(candidate), {}
    for module, records in certificate.items():
        old, new = original['modules'][module]['cells'], restored['modules'][module]['cells']
        local = {r['function_key']: classes[r['function_key']] for r in records['unions']}
        verify_proposals(original['modules'][module], records['unions'], local)
        actual.update(local)
        used = set()
        for record in records['unions']:
            a, b = [old[record[f]] for f in ('first', 'second')]
            assert record['name'] not in old
            assert new.pop(record['name']) == union_cell(a, b, record['fanins'], classes[record['function_key']])
            for field in ('first', 'second'):
                name = record[field]
                assert name not in new and name not in used
                used.add(name); new[name] = deepcopy(old[name])
        expected = {r['cell']: 'split' if r['both_outputs_need_o6'] else 'swap'
            for r in audit_module(original['modules'][module]) if r['o5_has_dedicated_o6_sink']}
        assert {r['cell']: r['mode'] for r in records['roles']} == expected
        assert len(records['roles']) == len(expected), 'Duplicate or missing role repair'
        for record in records['roles']:
            name, mode = record['cell'], record['mode']
            assert name not in new and name not in used
            replacements = role_replacement(old[name], mode)
            assert len(record['names']) == len(replacements) and len(set(record['names'])) == len(replacements)
            for replacement_name, cell in zip(record['names'], replacements):
                assert replacement_name not in old and new.pop(replacement_name) == cell
            function = role_function(old[name], mode)
            assert record['function_key'] == key(function)
            actual[key(function)] = function
            new[name] = deepcopy(old[name]); used.add(name)
        assert not any(r['o5_has_dedicated_o6_sink'] for r in audit_module(candidate['modules'][module]))
    assert actual == classes, 'Function domain does not cover exactly all changes'
    for function in actual.values():
        for index in range(32):
            assignment = [(index >> bit) & 1 for bit in range(function['fanins'])]
            for half, field in [(0, 'first'), (32, 'second')]:
                assert value(function[field], assignment) == int(function['init'][-(index + half) - 1])
    assert restored == original, 'Nonreplacement hardware, boundary or metadata changed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis-report', type=Path, required=True)
    args = parser.parse_args(); analysis_path = args.analysis_report.resolve()
    assert analysis_path.is_relative_to(ROOT)
    analysis = json.loads(analysis_path.read_text()); validate_analysis(analysis)
    verify_manifest(analysis['source']); verify_manifest(analysis['artifacts'])
    parent_path = ROOT / analysis['parent_report']
    parent, modules, copies, dependencies = load_parent(parent_path.resolve())
    assert dict(copies) == analysis['implementation_copies']
    assert parent['lut_count'] == analysis['candidate_lut_primitives']
    paths = [analysis_path.parent / name for name in ('proposals.json', 'function_classes.json', 'dedicated_sink_records.json')]
    assert all(str(p.relative_to(ROOT)) in analysis['artifacts']['files'] for p in paths)
    proposals, listed, roles = [json.loads(p.read_text()) for p in paths]
    assert len({key(f) for f in listed}) == len(listed) == analysis['unique_proposed_function_classes']
    for name in IMPLEMENTATIONS:
        assert len(proposals[name]) == analysis['module_statistics'][name]['proposed_pairs']
        assert roles[name] == audit_module(modules[name])
    candidate_path = parent_path.parent / 'paired_hierarchy.json'
    original = json.loads(candidate_path.read_text())
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [Path(__file__).resolve(), analysis_path, *paths, *dependencies, *imported]
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-shared-union-board-prepare/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='transform', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, commands=[],
        analysis_report=str(analysis_path.relative_to(ROOT)), parent_report=str(parent_path.relative_to(ROOT)),
        channels=32, kernels=16, parallel_products=512, implementation_copies=dict(copies),
        seed='none; exact completed analysis proposals and direct O6-role repairs',
        function_classes_hdl_acceptance=False, numerical_netlist_acceptance=False,
        packed_resource_acceptance=False, physical_fit_verified=False, bitstream_emitted=False,
        hardware_programmed=False, scope='Literal restoration, binary tables and full structural export only. All 512 products and 16 kernels retained. New exhaustive four-state class proof, full board numerical/reset/fault replay, placed fit, timing/electrical/DRC and bitstream acceptance remain required.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            assert code == 0 and 'ERROR:' not in text, text[-3000:]
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save()
    generated = []
    try:
        for path in sorted(set(tracked)):
            if path == candidate_path: continue
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())
            generated.append(target)
        candidate, certificate, classes = transform(original, proposals, {key(f): f for f in listed}, IMPLEMENTATIONS)
        counts = dict(physical_counts(candidate['modules'], TOP, IMPLEMENTATIONS))
        split = sum(copies[n] * sum(r['mode'] == 'split' for r in certificate[n]['roles']) for n in copies)
        swap = sum(copies[n] * sum(r['mode'] == 'swap' for r in certificate[n]['roles']) for n in copies)
        assert split == analysis['weighted_roles']['both_outputs_need_o6']
        assert swap + split == analysis['weighted_roles']['o5_has_dedicated_o6_sink']
        lut_count = sum(v for k, v in counts.items() if k.startswith('LUT'))
        assert lut_count == analysis['projected_lut_primitives'] + split
        assert multiplicities(candidate['modules'], TOP, IMPLEMENTATIONS) == copies
        report.update(cells_after=counts, lut_count=lut_count, weighted_split_pairs=split,
            weighted_swapped_pairs=swap, unique_function_classes=len(classes), literal_restoration_verified=True,
            binary_tables_verified=True, direct_o5_conflicts_remaining=0, nominal_part_lut_sites=298600)
        new_json, cert_json, classes_json = [out / name for name in
            ('union_hierarchy.json', 'union_certificate.json', 'function_classes.json')]
        new_json.write_text(json.dumps(candidate) + '\n'); cert_json.write_text(json.dumps(certificate, indent=2) + '\n')
        classes_json.write_text(json.dumps([classes[k] for k in sorted(classes)], indent=2) + '\n')
        generated += [new_json, cert_json, classes_json]
        implementation = dict(candidate, modules={n: candidate['modules'][n] for n in sorted(IMPLEMENTATIONS)})
        module_export, module_aliases = implementation_module_aliases(implementation)
        exported, aliases = hardware_instance_aliases(module_export)
        for name, data in [('module_name_aliases.json', module_aliases), ('hardware_instance_aliases.json', aliases)]:
            path = out / name; path.write_text(json.dumps(data, indent=2) + '\n'); generated.append(path)
        sv, roundtrip, script, check = [out / name for name in ('union_board.v', 'export_roundtrip.json', 'export.ys', 'check.ys')]
        sv.write_text(structural_board_verilog(exported))
        script.write_text('read_verilog -sv ' + json.dumps(str(sv)) + '\nwrite_json ' + json.dumps(str(roundtrip)) + '\n')
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['tool_version'] == parent['tool_version']
        report['stage'] = 'export'; save(); run(['yosys', '-Q', '-T', '-s', script], 'export')
        assert circuit_signature(json.loads(roundtrip.read_text())) == circuit_signature(exported), 'Export changed circuit'
        report['export_circuit_identity'] = 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
        check.write_text('read_verilog -lib +/xilinx/cells_sim.v\nread_verilog -sv ' + json.dumps(str(sv)) +
            '\nhierarchy -check -top ' + TOP + '\ncheck -assert\nstat -tech xilinx\n')
        report['stage'] = 'hierarchy'; save(); run(['yosys', '-Q', '-T', '-s', check], 'elaborate_check')
        verify_transform(original, json.loads(new_json.read_text()), json.loads(cert_json.read_text()),
            {key(f): f for f in json.loads(classes_json.read_text())}, IMPLEMENTATIONS)
        assert fingerprint(tracked) == before, 'Changed preparation dependency'
        generated += [sv, roundtrip, script, check, *(out.glob('*.log'))]
        report.update(status='PREPARED_SHARED_UNION_LUT_STRUCTURAL_CANDIDATE_ONLY', stage='complete',
            finished_utc=timestamp(), artifacts=fingerprint(generated))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *(out.glob('*.log'))] if p.is_file()]))
        raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
