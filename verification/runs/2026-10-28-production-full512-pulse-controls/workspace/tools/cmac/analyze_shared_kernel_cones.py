#!/usr/bin/env python3
"""Read-only identical-input cone analysis; never mapping or physical acceptance."""
from collections import Counter, defaultdict, deque
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from xc7_primitive_counts import PRIMITIVE, TIMING

COMBINATIONAL = re.compile(r'LUT[1-6]|LUT6_2|INV|CARRY4|MUXF[78]')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def shared_cones(modules, top, kernel, expected_instances):
    """Induct only through unchanged combinational primitives, not FF state.

    Each kernel is the same module. An input bit must connect to the identical
    parent bit in every instance. A cell is eligible only when every input is
    binary constant or an already established identical bit. All output pins
    become identical by the unchanged cell type/parameters/function. Nothing
    is removed, serialized, retimed, normalized or resynthesized here.
    """
    instances = [cell for cell in modules[top]['cells'].values() if cell['type'] == kernel]
    assert len(instances) == expected_instances >= 2, 'Wrong actual kernel multiplicity'
    assert all(not cell['parameters'] for cell in instances), 'Instance parameter override'
    body = modules[kernel]
    shared, primary, positions, bindings = set(), set(), {}, {}
    for port, spec in body['ports'].items():
        if spec['direction'] != 'input':
            assert spec['direction'] == 'output', 'Unsupported bidirectional port'
            continue
        assert all(cell['port_directions'][port] == 'input' and
                   len(cell['connections'][port]) == len(spec['bits']) for cell in instances)
        positions[port] = []
        for index, bit in enumerate(spec['bits']):
            assert type(bit) is int, 'Constant implementation input'
            parent = tuple(cell['connections'][port][index] for cell in instances)
            assert all(type(value) is int or value in ('0', '1') for value in parent), 'Unknown parent input'
            assert bit not in bindings or bindings[bit] == parent, 'Inconsistent input aliases'
            bindings[bit] = parent
            primary.add(bit)
            if len(set(parent)) == 1:
                positions[port].append(index)
                shared.add(bit)

    cells, drivers, fanins, total = {}, {}, {}, Counter()
    state_outputs = set()
    for name, cell in body['cells'].items():
        kind = cell['type']
        if kind == '$scopeinfo':
            continue
        assert PRIMITIVE.fullmatch(kind), ('Unknown kernel hardware', kind)
        definition = modules[kind]
        assert int(definition['attributes'].get('blackbox', '0'), 2) == 1
        assert {c['type'] for c in definition.get('cells', {}).values()} <= TIMING
        assert set(cell['connections']) == set(cell['port_directions']), 'Missing pin direction'
        assert set(cell['connections']) == set(definition['ports']), 'Missing primitive pin'
        inputs, outputs = set(), set()
        for pin, bits in cell['connections'].items():
            assert pin in definition['ports'], ('Unknown primitive pin', kind, pin)
            direction = cell['port_directions'][pin]
            assert direction == definition['ports'][pin]['direction']
            assert len(bits) == len(definition['ports'][pin]['bits']), 'Changed primitive pin width'
            assert direction in ('input', 'output'), 'Bidirectional hardware pin'
            for bit in bits:
                assert type(bit) is int or bit in ('0', '1'), 'Unknown primitive connection'
                if direction == 'input':
                    inputs.add(bit)
                else:
                    assert type(bit) is int and bit not in primary
                    assert bit not in drivers, 'Multiple hardware drivers'
                    drivers[bit] = name
                    outputs.add(bit)
        total[kind] += 1
        if COMBINATIONAL.fullmatch(kind):
            cells[name] = (cell, outputs)
            fanins[name] = inputs
        else:
            # Stateful primitives and DSPs are barriers, never shared here.
            state_outputs.update(outputs)

    for inputs in fanins.values():
        assert all(type(bit) is not int or bit in primary or bit in drivers for bit in inputs), 'Undriven kernel input'

    def close(available):
        pending = {name: inputs - available for name, inputs in fanins.items()}
        users = defaultdict(set)
        for name, bits in pending.items():
            for bit in bits:
                users[bit].add(name)
        ready = deque(name for name, bits in pending.items() if not bits)
        completed = set()
        while ready:
            name = ready.popleft()
            if name in completed:
                continue
            completed.add(name)
            for bit in cells[name][1]:
                if bit in available:
                    continue
                available.add(bit)
                for user in users[bit]:
                    pending[user].discard(bit)
                    if not pending[user]:
                        ready.append(user)
        return completed

    # Validate the entire combinational graph, not merely the useful subgraph.
    assert close(primary | state_outputs | {'0', '1'}) == set(cells), 'Combinational cycle or unresolved input'
    names = sorted(close(shared | {'0', '1'}))
    eligible = Counter(cells[name][0]['type'] for name in names)
    return dict(instances=len(instances), shared_input_positions=positions,
                per_kernel_cells=dict(total), eligible_per_kernel_cells=dict(eligible),
                eligible_cell_names=names,
                potentially_removable_cells={kind: count*(len(instances)-1) for kind, count in eligible.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping-report', type=Path, required=True)
    args = parser.parse_args()
    parent_path = args.mapping_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text())
    assert parent['status'] == 'PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY'
    assert (parent['channels'], parent['kernels'], parent['parallel_products']) == (32, 16, 512)
    assert all(step['status'] == 'PASS' and step['returncode'] == 0 for step in parent['commands'])
    for name, sha in parent['source']['files'].items():
        assert digest(ROOT / name) == sha, ('Stale mapping source', name)
    netlist = parent_path.parent / 'mapped_hierarchy.json'
    rel = str(netlist.relative_to(ROOT))
    assert digest(netlist) == parent['artifacts']['files'][rel], 'Changed completed mapped circuit'
    before = {str(path.relative_to(ROOT)): digest(path) for path in (parent_path, netlist, Path(__file__).resolve())}
    design = json.loads(netlist.read_text())
    tops = [name for name, module in design['modules'].items()
            if int(module.get('attributes', {}).get('top', '0'), 2)]
    assert len(tops) == 1
    kernel = parent['preserved_kernel']
    ports = design['modules'][kernel]['ports']
    assert {name: len(spec['bits']) for name, spec in ports.items()} == {
        'data': 512, 'weight': 512, 'data_mask': 32, 'weight_mask': 32, 'result': 44, 'invalid': 1}
    analysis = shared_cones(design['modules'], tops[0], kernel, 16)
    removable_luts = sum(count for kind, count in analysis['potentially_removable_cells'].items() if kind.startswith('LUT'))
    assert all(digest(ROOT / name) == sha for name, sha in before.items()), 'Inputs changed during analysis'
    out = ROOT / f'build/rknpu-shared-kernel-cones/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='PASS_SHARED_INPUT_CONE_ANALYSIS_ONLY', completed_utc=timestamp(),
                  source=fingerprint([Path(__file__).resolve(), ROOT/'tools/evidence.py', ROOT/'tools/cmac/xc7_primitive_counts.py']),
                  mapping_report=str(parent_path.relative_to(ROOT)), mapping_source_sha256=parent['source']['sha256'],
                  input_sha256=before, tool='Python structural dependency closure; no mapper, simulator or P&R invoked',
                  analysis=analysis, potentially_removable_lut_primitives=removable_luts,
                  hypothetical_remaining_lut_primitives=parent['lut_count']-removable_luts,
                  circuit_modified=False, numerical_netlist_acceptance=False, physical_fit_verified=False,
                  bitstream_emitted=False, hardware_programmed=False,
                  scope='Read-only opportunity analysis of identical-input combinational cones across all sixteen actual C32 kernels. No cells have been removed, and no transformed netlist, packed utilization, timing, DRC, FPGA or RK result is accepted.')
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(out/'report.json')
    print(json.dumps({key: report[key] for key in ('status','potentially_removable_lut_primitives','hypothetical_remaining_lut_primitives')}))


if __name__ == '__main__':
    main()
