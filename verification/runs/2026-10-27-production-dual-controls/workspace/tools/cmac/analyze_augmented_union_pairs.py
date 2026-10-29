#!/usr/bin/env python3
"""Read-only length-three augmentations of completed shared-board LUT pairs.

Replace one proposed edge a--b by u--a and b--v, where u/v were unmatched.
Every replacement keeps the exact union<=5, no self-feedback and O6-role
contracts. This deterministic local matching is NOT a maximum matching,
changed circuit, four-state proof, packed resource or physical-fit result.
"""
from collections import Counter, defaultdict
from itertools import combinations
import argparse
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from analyze_union_lut_pairs import dedicated_users, union_function, verify_proposals
from prepare_shared_union_board import IMPLEMENTATIONS, key, load_parent, validate_analysis
from audit_lut_pair_sinks import DOCS, audit_module
from pair_board_luts import lut_inputs
from test_fixed_array_board import verify_manifest


def eligible_graph(module):
    users = dedicated_users(module)
    primary = {b for p in module['ports'].values() if p['direction'] == 'input' for b in p['bits']}
    nodes, index = {}, defaultdict(list)
    for name, cell in sorted(module['cells'].items()):
        if not re.fullmatch('LUT[1-5]', cell['type']): continue
        pins = lut_inputs(cell); wires = [b for b in pins if type(b) is int]
        assert cell['connections']['O'][0] not in primary
        if len(set(wires)) != len(wires): continue
        fanins = tuple(sorted(wires)); needs_o6 = bool(users[cell['connections']['O'][0]])
        nodes[name] = dict(fanins=fanins, output=cell['connections']['O'][0], needs_o6=needs_o6)
        for size in range(len(fanins) + 1):
            for subset in combinations(fanins, size):
                index[(len(fanins), subset, needs_o6)].append(name)
    return nodes, index, users


def neighbors(name, nodes, index):
    item = nodes[name]; seen = set()
    for size in range(5, -1, -1):
        shared = max(0, len(item['fanins']) + size - 5)
        if shared > len(item['fanins']): continue
        for subset in combinations(item['fanins'], shared):
            for needs_o6 in (False, True):
                if item['needs_o6'] and needs_o6: continue
                for other in index.get((size, subset, needs_o6), []):
                    if other == name or other in seen: continue
                    seen.add(other); peer = nodes[other]
                    fanins = set(item['fanins']) | set(peer['fanins'])
                    assert len(fanins) <= 5
                    if not fanins or item['output'] in fanins or peer['output'] in fanins: continue
                    assert item['output'] != peer['output'], 'Multiple LUT output drivers'
                    yield other


def augment(module, records, classes):
    verify_proposals(module, records, classes)
    nodes, index, users = eligible_graph(module)
    mate = {}
    for record in records:
        a, b = record['first'], record['second']
        assert a in nodes and b in nodes and a not in mate and b not in mate
        mate[a] = b; mate[b] = a
    unmatched = set(nodes) - set(mate); changes = []
    initial_unmatched = len(unmatched)
    # Dynamic membership ensures every accepted path still has two unmatched
    # endpoints. Already augmented edges may be improved again without reuse.
    for u in sorted(unmatched):
        if u not in unmatched: continue
        found = False
        for a in neighbors(u, nodes, index):
            if a not in mate: continue
            b = mate[a]
            for v in neighbors(b, nodes, index):
                if v == u or v not in unmatched: continue
                assert len({u, a, b, v}) == 4
                del mate[a]; del mate[b]
                mate[u] = a; mate[a] = u; mate[b] = v; mate[v] = b
                unmatched.remove(u); unmatched.remove(v)
                changes.append(dict(removed=[a, b], added=[[u, a], [b, v]]))
                found = True; break
            if found: break
    result, functions = [], {}
    for a in sorted(mate):
        b = mate[a]
        assert mate[b] == a
        if b < a: continue
        first, second = (b, a) if nodes[a]['needs_o6'] else (a, b)
        fanins, function = union_function(module['cells'][first], module['cells'][second])
        assert not users[module['cells'][first]['connections']['O'][0]]
        function_key = key(function); functions[function_key] = function
        result.append(dict(first=first, second=second, fanins=fanins, function_key=function_key,
            dedicated_o6_sinks={'O5': [], 'O6': list(users[module['cells'][second]['connections']['O'][0]])}))
    assert len(result) == len(records) + len(changes)
    assert len(unmatched) == initial_unmatched - 2 * len(changes)
    verify_proposals(module, result, functions)
    verify_augmentations(module, records, result, changes)
    return result, functions, changes, dict(initial_pairs=len(records), proposed_pairs=len(result),
        additional_pairs=len(changes), initial_unmatched_luts=initial_unmatched,
        unmatched_eligible_luts=len(unmatched), retained_constant_only_luts=sum(
            not nodes[n]['fanins'] for n in unmatched))


def verify_augmentations(module, original, revised, changes):
    """Replay graph edits independently, including every edge legality."""
    nodes, index, _ = eligible_graph(module)
    def edge(a, b): return tuple(sorted((a, b)))
    current = {edge(r['first'], r['second']) for r in original}
    assert len(current) == len(original)
    for change in changes:
        assert set(change) == {'removed', 'added'}
        a, b = change['removed']; old = edge(a, b)
        assert old in current and len(change['added']) == 2
        (u, aa), (bb, v) = change['added']
        assert aa == a and bb == b and len({u, a, b, v}) == 4
        occupied = {n for pair in current for n in pair}
        assert u in nodes and v in nodes and u not in occupied and v not in occupied
        assert a in set(neighbors(u, nodes, index)) and v in set(neighbors(b, nodes, index))
        current.remove(old); current.update((edge(u, a), edge(b, v)))
    expected = {edge(r['first'], r['second']) for r in revised}
    assert len(expected) == len(revised) and current == expected, 'Changed matching/certificate'
    assert len({n for pair in current for n in pair}) == 2 * len(current), 'Reused LUT'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis-report', type=Path, required=True)
    args = parser.parse_args(); old_path = args.analysis_report.resolve(); assert old_path.is_relative_to(ROOT)
    old = json.loads(old_path.read_text()); validate_analysis(old)
    verify_manifest(old['source']); verify_manifest(old['artifacts'])
    parent_path = (ROOT / old['parent_report']).resolve()
    parent, modules, copies, dependencies = load_parent(parent_path)
    assert dict(copies) == old['implementation_copies'] and parent['lut_count'] == old['candidate_lut_primitives']
    paths = [old_path.parent / n for n in ('proposals.json', 'function_classes.json', 'dedicated_sink_records.json')]
    assert all(str(p.relative_to(ROOT)) in old['artifacts']['files'] for p in paths)
    previous, listed, audits = [json.loads(p.read_text()) for p in paths]
    domain = {key(f): f for f in listed}; assert len(domain) == len(listed) == old['unique_proposed_function_classes']
    assert set(previous) == set(audits) == IMPLEMENTATIONS
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [Path(__file__).resolve(), old_path, *paths, *dependencies, *imported]
    before = fingerprint(tracked); out = ROOT / f'build/rknpu-augmented-union-lut-opportunities/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='augmentation', started_utc=timestamp(), source=before,
        original_analysis_report=str(old_path.relative_to(ROOT)), parent_report=str(parent_path.relative_to(ROOT)),
        channels=32, kernels=16, parallel_products=512, implementation_copies=dict(copies),
        candidate_lut_primitives=parent['lut_count'], source_documents=DOCS, nominal_part_lut_sites=298600,
        python_version=sys.version, seed='none; deterministic length-three augmenting paths',
        matching_method='length_three_augmentations_of_exact_completed_union_proposals',
        netlist_changed=False, function_classes_hdl_acceptance=False, numerical_netlist_acceptance=False,
        packed_resource_acceptance=False, physical_fit_verified=False, bitstream_emitted=False,
        hardware_programmed=False, scope='Read-only reversible graph proposal edits, not a netlist transform or maximum matching. Exact original boundary and necessary O6 roles retained. New class, full numerical, packed fit, physical timing/electrical/DRC and bitstream gates remain required.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    try:
        records, functions, statistics, certificates, actual_old, roles = {}, {}, {}, {}, {}, Counter()
        for name in sorted(IMPLEMENTATIONS):
            local = {r['function_key']: domain[r['function_key']] for r in previous[name]}; actual_old.update(local)
            assert len(previous[name]) == old['module_statistics'][name]['proposed_pairs']
            assert audits[name] == audit_module(modules[name])
            proposed, classes, changes, stats = augment(modules[name], previous[name], local)
            records[name] = proposed; functions.update(classes); statistics[name] = stats; certificates[name] = changes
            for item in audits[name]:
                roles['pairs'] += copies[name]
                for field in ('o5_has_dedicated_o6_sink', 'both_outputs_need_o6', 'o6_has_dedicated_sink'):
                    roles[field] += int(item[field]) * copies[name]
            print(name, json.dumps(stats, sort_keys=True), flush=True)
        assert actual_old == domain and dict(roles) == old['weighted_roles']
        total = sum(copies[n] * len(records[n]) for n in copies)
        extra = total - old['weighted_opportunities']['additional_disjoint_pairs']
        assert extra == sum(copies[n] * len(certificates[n]) for n in copies)
        outputs = []
        for filename, data in [('proposals.json', records), ('function_classes.json',
                [functions[k] for k in sorted(functions)]), ('dedicated_sink_records.json', audits),
                ('augmentation_certificate.json', certificates)]:
            target = out / filename; target.write_text(json.dumps(data, indent=2) + '\n'); outputs.append(target)
        for path in sorted(set(tracked)):
            if path.name == 'paired_hierarchy.json': continue
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); outputs.append(target)
        assert fingerprint(tracked) == before
        report.update(status='ANALYZED_SHARED_BOARD_UNION_FANIN_LUT_OPPORTUNITIES_ONLY', stage='complete',
            finished_utc=timestamp(), weighted_opportunities={'additional_disjoint_pairs': total},
            weighted_additional_pairs_vs_original=extra, weighted_roles=dict(roles), module_statistics=statistics,
            unique_proposed_function_classes=len(functions), projected_lut_primitives=parent['lut_count'] - total,
            repaired_role_lut_projection=parent['lut_count'] - total + roles['both_outputs_need_o6'],
            artifacts=fingerprint(outputs))
        validate_analysis(report)
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error)); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
