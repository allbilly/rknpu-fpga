#!/usr/bin/env python3
"""Read-only residual LUT6/cofactor opportunities, not a transformed circuit.

A LUT6_2's O5 uses INIT[31:0]; O6 uses the full INIT with a live I5.
An existing small function can share that table only if it is exactly the
zero cofactor of the existing six-input function after pin permutation.
Exclude every previously proposed union pair and every existing LUT6_2.
Binary proposals do not establish four-state equivalence or physical fit.
The current local nextpnr packer does NOT constrain live-I5 halves together.
"""
from collections import Counter, defaultdict
from functools import lru_cache
import argparse
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from analyze_union_lut_pairs import dedicated_users, verify_proposals
from prepare_shared_union_board import IMPLEMENTATIONS, key, load_parent, validate_analysis
from audit_lut_pair_sinks import DOCS, PACKER, audit_module
from test_fixed_array_board import verify_manifest


def lut_pins(cell):
    assert re.fullmatch('LUT[1-6]', cell['type'])
    size = int(cell['type'][-1]); names = [f'I{i}' for i in range(size)]
    assert set(cell['connections']) == set(names + ['O'])
    assert cell['port_directions'] == {**{p: 'input' for p in names}, 'O': 'output'}
    assert all(len(bits) == 1 for bits in cell['connections'].values())
    assert set(cell['parameters']) == {'INIT'}
    init = cell['parameters']['INIT']
    assert re.fullmatch('[01]+', init) and len(init) == 2 ** size
    pins = [cell['connections'][p][0] for p in names]
    assert all(type(b) is int or b in ('0', '1') for b in pins)
    output = cell['connections']['O'][0]
    assert type(output) is int and output not in pins
    return pins


def function_spec(cell, fanins):
    return dict(kind=cell['type'], init=cell['parameters']['INIT'],
        pins=[fanins.index(b) if type(b) is int else b for b in lut_pins(cell)])


@lru_cache(maxsize=65536)
def truth_table(init, pins, width):
    """Actual pin permutation/constants; cache does not use circuit wire IDs."""
    result = 0
    for assignment in range(2 ** width):
        address = sum((((assignment >> pin) & 1) if type(pin) is int else int(pin)) << i
            for i, pin in enumerate(pins))
        result |= int(init[-address - 1]) << assignment
    return result


def binary_support(fanins, table):
    """Lookup key only. Never drop these pins from a proposed circuit/class."""
    size = len(fanins)
    support = [i for i in range(size) if any(
        ((table >> a) & 1) != ((table >> (a ^ (1 << i))) & 1) for a in range(2 ** size))]
    reduced = 0
    for a in range(2 ** len(support)):
        address = sum(((a >> j) & 1) << i for j, i in enumerate(support))
        reduced |= ((table >> address) & 1) << a
    return tuple(fanins[i] for i in support), reduced


def cofactor_function(small, large, selector):
    small_pins, large_pins = lut_pins(small), lut_pins(large)
    assert large['type'] == 'LUT6'
    assert all(type(b) is int for b in large_pins) and len(set(large_pins)) == 6
    assert selector in large_pins
    wires = [b for b in small_pins if type(b) is int]
    assert len(set(wires)) == len(wires)
    fanins = sorted(set(large_pins) - {selector}) + [selector]
    assert set(wires) <= set(fanins[:5])
    outputs = [cell['connections']['O'][0] for cell in (small, large)]
    assert outputs[0] != outputs[1] and not set(outputs) & set(fanins)
    first, second = [function_spec(cell, fanins) for cell in (small, large)]
    low = truth_table(first['init'], tuple(first['pins']), 5)
    whole = truth_table(second['init'], tuple(second['pins']), 6)
    assert whole & ((1 << 32) - 1) == low, 'Small function is not the zero cofactor'
    return fanins, dict(mode='live_selector_zero_cofactor', fanins=6, first=first, second=second,
        init=format(whole, '064b'))


def proposals(module, excluded):
    assert set(excluded) <= set(module['cells'])
    users = dedicated_users(module)
    primary = {b for p in module['ports'].values() if p['direction'] == 'input' for b in p['bits']}
    small_index, eligible_large, statistics = defaultdict(list), {}, Counter()
    for name, cell in sorted(module['cells'].items()):
        if name in excluded or not re.fullmatch('LUT[1-6]', cell['type']): continue
        pins = lut_pins(cell); wires = [b for b in pins if type(b) is int]
        output = cell['connections']['O'][0]
        assert output not in primary, 'LUT drives primary input'
        if len(set(wires)) != len(wires):
            statistics['retained_repeated_correlated_inputs'] += 1; continue
        if cell['type'] == 'LUT6':
            if len(wires) != 6:
                statistics['retained_constant_pin_lut6'] += 1; continue
            eligible_large[name] = pins
        elif users[output]:
            statistics['small_luts_requiring_dedicated_o6'] += 1
        else:
            fanins = sorted(wires); spec = function_spec(cell, fanins)
            lookup = binary_support(fanins, truth_table(spec['init'], tuple(spec['pins']), len(fanins)))
            small_index[lookup].append((name, set(wires)))
    records, classes, used = [], {}, set()
    for name, pins in eligible_large.items():
        for selector in sorted(pins):
            fanins = sorted(set(pins) - {selector}) + [selector]
            large = module['cells'][name]; spec = function_spec(large, fanins)
            whole = truth_table(spec['init'], tuple(spec['pins']), 6)
            lookup = binary_support(fanins[:5], whole & ((1 << 32) - 1))
            found = False
            for peer, wires in small_index.get(lookup, []):
                if peer in used or not wires <= set(fanins[:5]): continue
                small = module['cells'][peer]
                outputs = {small['connections']['O'][0], large['connections']['O'][0]}
                if outputs & set(fanins): continue
                actual_pins, function = cofactor_function(small, large, selector)
                function_key = key(function); classes[function_key] = function
                records.append(dict(first=peer, second=name, selector=selector, fanins=actual_pins,
                    function_key=function_key,
                    dedicated_o6_sinks={'O5': [], 'O6': list(users[large['connections']['O'][0]])}))
                used.update((peer, name)); found = True; break
            if found: break
    statistics.update(eligible_six_input_luts=len(eligible_large),
        eligible_small_luts=sum(map(len, small_index.values())), proposed_pairs=len(records))
    verify_proposals_cofactor(module, excluded, records, classes)
    return records, classes, dict(statistics)


def verify_proposals_cofactor(module, excluded, records, classes):
    users, used, actual = dedicated_users(module), set(), {}
    for record in records:
        first, second = record['first'], record['second']
        assert first != second and not {first, second} & (used | set(excluded)), 'Reused/excluded LUT'
        small, large = [module['cells'][n] for n in (first, second)]
        assert re.fullmatch('LUT[1-5]', small['type'])
        fanins, function = cofactor_function(small, large, record['selector'])
        assert record['fanins'] == fanins and record['function_key'] == key(function)
        assert not users[small['connections']['O'][0]], 'O5 requires dedicated O6'
        assert record['dedicated_o6_sinks'] == {'O5': [], 'O6': list(users[large['connections']['O'][0]])}
        actual[key(function)] = function; used.update((first, second))
        # Independent direct address evaluation, including all 64 live-I5 assignments.
        for assignment in range(64):
            for spec, width in [(function['first'], 5), (function['second'], 6)]:
                address = sum((((assignment >> p) & 1) if type(p) is int else int(p)) << i
                    for i, p in enumerate(spec['pins']))
                expected = int(spec['init'][-address - 1])
                assert expected == int(function['init'][-(assignment % (2 ** width)) - 1])
    assert actual == classes, 'Wrong cofactor function domain'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis-report', type=Path, required=True)
    args = parser.parse_args(); analysis_path = args.analysis_report.resolve()
    assert analysis_path.is_relative_to(ROOT)
    analysis = json.loads(analysis_path.read_text()); validate_analysis(analysis)
    verify_manifest(analysis['source']); verify_manifest(analysis['artifacts'])
    parent_path = (ROOT / analysis['parent_report']).resolve()
    parent, modules, copies, dependencies = load_parent(parent_path)
    assert dict(copies) == analysis['implementation_copies']
    assert parent['lut_count'] == analysis['candidate_lut_primitives']
    paths = [analysis_path.parent / n for n in ('proposals.json', 'function_classes.json', 'dedicated_sink_records.json')]
    assert all(str(p.relative_to(ROOT)) in analysis['artifacts']['files'] for p in paths)
    unions, listed, roles = [json.loads(p.read_text()) for p in paths]
    domain = {key(f): f for f in listed}
    assert len(domain) == len(listed) == analysis['unique_proposed_function_classes']
    assert set(unions) == set(roles) == IMPLEMENTATIONS
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [Path(__file__).resolve(), analysis_path, *paths, *dependencies, *imported, PACKER]
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-cofactor-lut-opportunities/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='selection', started_utc=timestamp(), source=before,
        analysis_report=str(analysis_path.relative_to(ROOT)), python_version=sys.version,
        seed='none; deterministic module, LUT name and zero-selector order', source_documents=DOCS,
        channels=32, kernels=16, parallel_products=512, implementation_copies=dict(copies),
        netlist_changed=False, function_classes_hdl_acceptance=False, numerical_netlist_acceptance=False,
        packed_resource_acceptance=False, physical_fit_verified=False, bitstream_emitted=False,
        hardware_programmed=False, current_local_packer_shares_live_i5_pairs=False,
        scope='Read-only disjoint residual zero-cofactor opportunities after excluding every prior union pair. Binary tables only. No transform, four-state proof, packed savings, placement/timing/electrical/DRC or bitstream acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    try:
        all_records, classes, statistics, excluded, split, union_keys = {}, {}, {}, {}, 0, set()
        for name in sorted(IMPLEMENTATIONS):
            local = {r['function_key']: domain[r['function_key']] for r in unions[name]}
            verify_proposals(modules[name], unions[name], local); union_keys.update(local)
            assert len(unions[name]) == analysis['module_statistics'][name]['proposed_pairs']
            assert roles[name] == audit_module(modules[name])
            split += copies[name] * sum(r['both_outputs_need_o6'] for r in roles[name])
            omitted = {r[f] for r in unions[name] for f in ('first', 'second')}
            assert len(omitted) == 2 * len(unions[name]); excluded[name] = sorted(omitted)
            records, functions, stats = proposals(modules[name], omitted)
            all_records[name] = records; classes.update(functions); statistics[name] = stats
            print(name, json.dumps(stats, sort_keys=True), flush=True)
        assert union_keys == set(domain) and split == analysis['weighted_roles']['both_outputs_need_o6']
        weighted = sum(copies[n] * len(all_records[n]) for n in copies)
        output = []
        for filename, data in [('proposals.json', all_records), ('function_classes.json',
                [classes[k] for k in sorted(classes)]), ('excluded_union_cells.json', excluded)]:
            target = out / filename; target.write_text(json.dumps(data, indent=2) + '\n'); output.append(target)
        for path in sorted(set(tracked)):
            if path.name == 'paired_hierarchy.json': continue
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); output.append(target)
        assert fingerprint(tracked) == before, 'Changed cofactor analysis dependency'
        report.update(status='ANALYZED_RESIDUAL_ZERO_COFACTOR_LUT_OPPORTUNITIES_ONLY', stage='complete',
            finished_utc=timestamp(), weighted_additional_disjoint_pairs=weighted,
            module_statistics=statistics, unique_function_classes=len(classes),
            base_repaired_union_lut_projection=analysis['projected_lut_primitives'] + split,
            conditional_lut_primitive_projection=analysis['projected_lut_primitives'] + split - weighted,
            nominal_part_lut_sites=298600, artifacts=fingerprint(output))
    except BaseException as error:
        report.update(status='FAIL', stage='analysis_failure', finished_utc=timestamp(), error=repr(error)); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
