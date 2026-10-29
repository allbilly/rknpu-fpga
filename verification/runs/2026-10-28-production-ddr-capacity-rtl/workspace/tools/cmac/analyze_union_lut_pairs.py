#!/usr/bin/env python3
"""Suggest disjoint residual LUT pairs; no netlist, placement or fit acceptance.

UG474 permits two <=5-input functions with A6 high. Their *union* may fit
the five pins even when their variable input sets differ. A pair must not
feed itself and may have at most one output requiring dedicated O6 routing.
The proposals and projected primitive counts do not establish physical fit.
"""
from collections import Counter, defaultdict, deque
from itertools import combinations
import argparse
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from pair_board_luts import lut_inputs, value
from test_fixed_array_board import verify_manifest
from test_paired_mapped_array import validate_pair_metadata, validate_pair_proof_metadata
from prepare_shared_board import physical_counts
from audit_lut_pair_sinks import multiplicities, DOCS


def dedicated_users(module):
    """Necessary O6 consumers only, not a complete BEL-placement model."""
    users = defaultdict(list)
    for name, cell in sorted(module['cells'].items()):
        if cell['type'] == 'CARRY4':
            pins = {'S': 4}
        elif cell['type'] == 'MUXF7':
            pins = {'I0': 1, 'I1': 1}
        else:
            continue
        for pin, width in pins.items():
            assert cell['port_directions'][pin] == 'input'
            assert len(cell['connections'][pin]) == width
            for index, bit in enumerate(cell['connections'][pin]):
                if type(bit) is int:
                    users[bit].append(dict(cell=name, kind=cell['type'], pin=pin, index=index))
    return users


def union_function(a, b):
    """O5=a/O6=b, preserving pin order/constants in a full union truth table."""
    inputs = [lut_inputs(cell) for cell in (a, b)]
    wires = [[bit for bit in pins if type(bit) is int] for pins in inputs]
    assert all(len(bits) == len(set(bits)) for bits in wires), 'Correlated repeated input'
    fanins = sorted(set(wires[0]) | set(wires[1]))
    assert len(fanins) <= 5, 'More than five union inputs'
    outputs = [cell['connections']['O'][0] for cell in (a, b)]
    assert outputs[0] != outputs[1], 'Multiple output drivers'
    assert not set(outputs) & set(fanins), 'Pair would feed its own input'
    functions = [dict(kind=cell['type'], init=cell['parameters']['INIT'],
        pins=[fanins.index(bit) if type(bit) is int else bit for bit in pins])
        for cell, pins in zip((a, b), inputs)]
    halves = []
    for function in functions:
        half = sum(value(function, [(index >> bit) & 1 for bit in range(len(fanins))]) << index
            for index in range(32))
        halves.append(half)
    return fanins, dict(fanins=len(fanins), first=functions[0], second=functions[1],
        init=format((halves[1] << 32) | halves[0], '064b'))


def proposals(module):
    """Deterministic greedy matching, not a maximum matching or packing proof.

    Index each small LUT by input subsets. For sizes n and m, a legal union
    needs at least n+m-5 shared variables. This avoids an all-pairs scan.
    Existing LUT6_2 instances are retained and their conflicts are not repaired.
    """
    users = dedicated_users(module)
    primary = {bit for port in module['ports'].values() if port['direction'] == 'input'
        for bit in port['bits']}
    eligible = {}
    skipped = Counter()
    for name, cell in sorted(module['cells'].items()):
        if not re.fullmatch('LUT[1-5]', cell['type']):
            continue
        pins = lut_inputs(cell)
        output = cell['connections']['O'][0]
        assert output not in primary, 'LUT drives primary input'
        wires = [bit for bit in pins if type(bit) is int]
        if len(wires) != len(set(wires)):
            skipped['repeated_correlated_input_luts'] += 1
            continue
        eligible[name] = dict(fanins=tuple(sorted(wires)), output=output,
            needs_o6=bool(users[output]))
    index = defaultdict(deque)
    for name, item in eligible.items():
        for size in range(len(item['fanins']) + 1):
            for subset in combinations(item['fanins'], size):
                index[(len(item['fanins']), subset, item['needs_o6'])].append(name)
    used = set()
    records, classes = [], {}
    order = sorted(eligible, key=lambda name: (-len(eligible[name]['fanins']),
        -int(eligible[name]['needs_o6']), name))
    for name in order:
        if name in used:
            continue
        item = eligible[name]
        partner = None
        for size in range(5, -1, -1):
            shared = max(0, len(item['fanins']) + size - 5)
            if shared > len(item['fanins']):
                continue
            for subset in combinations(item['fanins'], shared):
                for needs_o6 in (False, True):
                    if item['needs_o6'] and needs_o6:
                        continue
                    queue = index.get((size, subset, needs_o6))
                    if not queue:
                        continue
                    while queue and queue[0] in used:
                        queue.popleft()
                    for other in queue:
                        if other == name or other in used:
                            continue
                        peer = eligible[other]
                        fanins = set(item['fanins']) | set(peer['fanins'])
                        assert len(fanins) <= 5
                        if item['output'] in fanins or peer['output'] in fanins:
                            continue
                        # No driven input can wake the procedural vendor models
                        # for two constant-only functions. Retain them explicitly.
                        if not fanins:
                            continue
                        assert item['output'] != peer['output'], 'Multiple output drivers'
                        partner = other
                        break
                    if partner is not None:
                        break
                if partner is not None:
                    break
            if partner is not None:
                break
        if partner is None:
            continue
        first, second = (partner, name) if item['needs_o6'] else (name, partner)
        a, b = [module['cells'][n] for n in (first, second)]
        fanins, function = union_function(a, b)
        assert not users[a['connections']['O'][0]], 'O5 output requires dedicated O6'
        key = json.dumps(function, sort_keys=True, separators=(',', ':'))
        classes[key] = function
        records.append(dict(first=first, second=second, fanins=fanins, function_key=key,
            dedicated_o6_sinks={'O5': [], 'O6': list(users[b['connections']['O'][0]])}))
        used.update((name, partner))
    skipped['unmatched_eligible_luts'] = len(eligible) - len(used)
    skipped['retained_constant_only_luts'] = sum(not v['fanins'] for n, v in eligible.items() if n not in used)
    return records, classes, dict(skipped)


def verify_proposals(module, records, classes):
    """Independent replay of each proposal's wiring, function and O6 role."""
    users, used, actual = dedicated_users(module), set(), {}
    for record in records:
        first, second = record['first'], record['second']
        assert first != second and not {first, second} & used, 'Reused LUT'
        a, b = module['cells'][first], module['cells'][second]
        fanins, function = union_function(a, b)
        assert record['fanins'] == fanins and fanins
        assert not users[a['connections']['O'][0]], 'O5 output requires dedicated O6'
        assert record['dedicated_o6_sinks'] == {'O5': [], 'O6': list(users[b['connections']['O'][0]])}
        key = json.dumps(function, sort_keys=True, separators=(',', ':'))
        assert record['function_key'] == key
        actual[key] = function
        used.update((first, second))
    assert actual == classes, 'Proposal function domain changed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paired-report', required=True, type=Path)
    args = parser.parse_args()
    parent_path = args.paired_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text())
    validate_pair_metadata(parent)
    # This read-only opportunity analysis binds the completed parent's exact
    # source/artifacts/proof inputs. It does not rerun full pair restoration,
    # primitive proof or export and cannot promote this or that netlist.
    verify_manifest(parent['source'])
    verify_manifest(parent['artifacts'])
    validate_pair_proof_metadata(parent, parent_path.parent)
    candidate_path = parent_path.parent / 'paired_hierarchy.json'
    assert str(candidate_path.relative_to(ROOT)) in parent['artifacts']['files']
    original_path = ROOT / parent['parent_report']
    original = json.loads(original_path.read_text())
    assert original['status'] == 'PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY'
    assert original['source']['sha256'] == parent['parent_source_sha256']
    verify_manifest(original['source'])
    modules = json.loads(candidate_path.read_text())['modules']
    top, kernel = 'ypcb_cmac_array_top', original['preserved_kernel']
    implementations = {top, kernel}
    copies = multiplicities(modules, top, implementations)
    assert copies == Counter({top: 1, kernel: 16})
    assert dict(physical_counts(modules, top, implementations)) == parent['cells_after']
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [Path(__file__).resolve(), parent_path, original_path, candidate_path, *imported]
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-union-lut-opportunities/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='selection', started_utc=timestamp(), source=before,
        python_version=sys.version, seed='none; deterministic size/subset/name greedy order',
        parent_report=str(parent_path.relative_to(ROOT)), channels=32, kernels=16, parallel_products=512,
        implementation_copies=dict(copies), candidate_lut_primitives=parent['lut_count'], source_documents=DOCS,
        netlist_changed=False, function_classes_hdl_acceptance=False, numerical_netlist_acceptance=False,
        packed_resource_acceptance=False, physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Read-only disjoint residual LUT1..5 union-fanin proposals on exact hash-bound completed paired-board artifacts. Binary truth tables and direct necessary O6 roles only. Original LUT6_2 conflicts remain; projection is not packed LUT sites, a maximum matching, four-state function-class proof, full circuit/export verification, full array/board numerical acceptance, physical fit/timing/DRC, bitstream or hardware acceptance.')
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    try:
        records, all_classes, statistics = {}, {}, {}
        weighted = Counter()
        for name in sorted(implementations):
            proposed, classes, skipped = proposals(modules[name])
            verify_proposals(modules[name], proposed, classes)
            records[name] = proposed
            all_classes.update(classes)
            statistics[name] = dict(proposed_pairs=len(proposed), **skipped)
            weighted['additional_disjoint_pairs'] += copies[name] * len(proposed)
            weighted['different_fanin_pairs'] += copies[name] * sum(
                {b for b in lut_inputs(modules[name]['cells'][r['first']]) if type(b) is int} !=
                {b for b in lut_inputs(modules[name]['cells'][r['second']]) if type(b) is int}
                for r in proposed)
            print(name, json.dumps(statistics[name], sort_keys=True), flush=True)
        paths = [out / 'proposals.json', out / 'function_classes.json']
        paths[0].write_text(json.dumps(records, indent=2) + '\n')
        paths[1].write_text(json.dumps([all_classes[k] for k in sorted(all_classes)], indent=2) + '\n')
        assert fingerprint(tracked) == before, 'Changed analysis dependency'
        report.update(status='ANALYZED_UNION_FANIN_LUT_OPPORTUNITIES_ONLY', stage='complete',
            finished_utc=timestamp(), weighted_opportunities=dict(weighted), module_statistics=statistics,
            unique_proposed_function_classes=len(all_classes),
            projected_lut_primitives=parent['lut_count'] - weighted['additional_disjoint_pairs'],
            artifacts=fingerprint(paths))
    except BaseException:
        report.update(status='FAIL', stage='analysis_failure', finished_utc=timestamp())
        raise
    finally:
        save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
