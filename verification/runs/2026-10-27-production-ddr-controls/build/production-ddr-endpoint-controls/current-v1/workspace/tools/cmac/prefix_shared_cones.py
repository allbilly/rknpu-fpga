"""Lift identical-input combinational cones without sharing DSPs or state.

The prefix DSP graph has intentionally omitted DSP pins. Treat every DSP
output as a barrier and record those omissions; never default pins or infer
DSP behavior. Eligible combinational primitives require complete ports and
recognized timing-only blackbox declarations. This is a structural circuit
transformation, not numerical, placement, timing or FPGA acceptance.
"""
from collections import Counter, defaultdict, deque
from copy import deepcopy
import re

COMBINATIONAL = re.compile(r'LUT[1-6]|LUT6_2|INV|CARRY4|MUXF[78]')
BARRIERS = {'DSP48E1', 'FDCE', 'FDRE', 'FDSE', 'FDPE'}
TIMING = {'$specify2', '$specify3', '$specrule'}
PRIVATE = 'rk_cmac_fp16_cell_dsp_prefix_shared_xc7'
SHARED = 'rk_cmac_fp16_prefix_data_shared_xc7'
INSTANCE = 'rk_prefix_shared_data_cones'
NODES = 'prefix_shared_nodes'


def output_bits(cell):
    return {b for pin, bits in cell['connections'].items()
            if cell['port_directions'][pin] == 'output' for b in bits}


def all_bits(module):
    values = [*(p['bits'] for p in module.get('ports', {}).values()),
              *(p['bits'] for p in module.get('netnames', {}).values()),
              *(bits for c in module.get('cells', {}).values()
                for bits in c.get('connections', {}).values())]
    return {b for bits in values for b in bits if type(b) is int}


def analyze(modules, top, kernel, instances):
    assert type(instances) is int and instances >= 2
    callers = {n: c for n, c in modules[top]['cells'].items() if c['type'] == kernel}
    assert len(callers) == instances, 'Changed kernel multiplicity'
    body = modules[kernel]
    directions = {n: p['direction'] for n, p in body['ports'].items()}
    for caller in callers.values():
        assert not caller.get('parameters'), 'Kernel parameter override'
        assert set(caller['connections']) == set(directions), 'Changed kernel boundary'
        assert caller['port_directions'] == directions
        assert all(len(caller['connections'][n]) == len(p['bits']) for n, p in body['ports'].items())
    primary, shared, bindings, positions = set(), set(), {}, {}
    for name, port in body['ports'].items():
        assert port['direction'] in ('input', 'output'), 'Bidirectional kernel port'
        if port['direction'] == 'output':
            continue
        positions[name] = []
        for index, bit in enumerate(port['bits']):
            assert type(bit) is int and bit >= 2
            values = tuple(c['connections'][name][index] for c in callers.values())
            assert all(type(v) is int and v >= 2 or v in ('0', '1') for v in values)
            assert bit not in bindings or bindings[bit] == values, 'Conflicting primary alias'
            bindings[bit] = values
            primary.add(bit)
            if len(set(values)) == 1:
                positions[name].append(index)
                shared.add(bit)

    fanins, outputs, drivers, barriers = {}, {}, {}, set()
    total, omitted = Counter(), {}
    for name, cell in body['cells'].items():
        kind = cell['type']
        if kind == '$scopeinfo':
            assert not cell.get('connections') and not cell.get('port_directions')
            continue
        assert COMBINATIONAL.fullmatch(kind) or kind in BARRIERS, 'Unmodeled kernel primitive'
        definition = modules[kind]
        assert int(definition['attributes'].get('blackbox', '0'), 2) == 1
        assert set(cell['connections']) == set(cell['port_directions'])
        assert set(cell['connections']) <= set(definition['ports']), 'Unknown primitive pin'
        inputs, driven = set(), set()
        for pin, bits in cell['connections'].items():
            spec = definition['ports'][pin]
            direction = cell['port_directions'][pin]
            assert direction == spec['direction'] and direction in ('input', 'output')
            assert len(bits) == len(spec['bits']), 'Changed primitive pin width'
            assert all(type(b) is int and b >= 2 or b in ('0', '1') for b in bits)
            (inputs if direction == 'input' else driven).update(bits)
        for bit in driven:
            assert type(bit) is int and bit not in primary and bit not in drivers, 'Multiple/constant driver'
            drivers[bit] = name
        total[kind] += 1
        missing = sorted(set(definition['ports']) - set(cell['connections']))
        if COMBINATIONAL.fullmatch(kind):
            assert not missing, 'Incomplete eligible primitive'
            assert {c['type'] for c in definition.get('cells', {}).values()} <= TIMING
            fanins[name], outputs[name] = inputs, driven
        else:
            # No behavior/defaulting is inferred from these declarations.
            # Even a combinational DSP's connected outputs are NOT eligible.
            assert not missing or kind == 'DSP48E1', 'Incomplete non-DSP state primitive'
            if missing:
                omitted[name] = missing
            barriers.update(driven)
    assert all(type(b) is not int or b in primary or b in drivers
               for bits in fanins.values() for b in bits), 'Undriven combinational pin'

    def close(available):
        pending = {n: bits - available for n, bits in fanins.items()}
        users = defaultdict(set)
        for name, bits in pending.items():
            for bit in bits:
                users[bit].add(name)
        queue = deque(n for n, bits in pending.items() if not bits)
        done = set()
        while queue:
            name = queue.popleft()
            if name in done:
                continue
            done.add(name)
            for bit in outputs[name] - available:
                available.add(bit)
                for user in users[bit]:
                    pending[user].discard(bit)
                    if not pending[user]:
                        queue.append(user)
        return done

    assert close(primary | barriers | {'0', '1'}) == set(fanins), 'Unresolved/cyclic combinational graph'
    names = sorted(close(shared | {'0', '1'}))
    eligible = Counter(body['cells'][n]['type'] for n in names)
    return dict(instances=instances, shared_input_positions=positions,
                eligible_cell_names=names, eligible_per_kernel_cells=dict(eligible),
                per_kernel_cells=dict(total), omitted_DSP_pins_barriered=omitted,
                removable_cells={k: v * (instances - 1) for k, v in eligible.items()})


def shared_ports(body, analysis, nodes):
    ports = {}
    for name, indices in analysis['shared_input_positions'].items():
        if indices:
            spec = body['ports'][name]
            assert not spec.get('offset', 0) and not spec.get('upto', 0)
            ports[name] = dict(direction='input', bits=[spec['bits'][i] for i in indices])
    assert NODES not in ports and nodes
    ports[NODES] = dict(direction='output', bits=nodes)
    return ports


def lift(original, top, kernel, instances):
    assert not {PRIVATE, SHARED} & set(original['modules']), 'Module collision'
    assert INSTANCE not in original['modules'][top]['cells'], 'Instance collision'
    analysis = analyze(original['modules'], top, kernel, instances)
    names = set(analysis['eligible_cell_names'])
    assert names, 'No shared combinational cells'
    body = original['modules'][kernel]
    nodes = sorted({b for n in names for b in output_bits(body['cells'][n])})
    assert NODES not in body['ports']
    candidate = deepcopy(original)
    private = candidate['modules'].pop(kernel)
    private['ports'][NODES] = dict(direction='input', bits=nodes)
    private['cells'] = {n: c for n, c in private['cells'].items() if n not in names}
    candidate['modules'][PRIVATE] = private
    candidate['modules'][SHARED] = dict(attributes={'keep_hierarchy': '1', 'hdlname': SHARED},
        ports=shared_ports(body, analysis, nodes),
        cells={n: deepcopy(body['cells'][n]) for n in sorted(names)})
    board = candidate['modules'][top]
    first = next(c for c in board['cells'].values() if c['type'] == kernel)
    start = max(all_bits(board)) + 1
    wires = list(range(start, start + len(nodes)))
    inputs = {p: [first['connections'][p][i] for i in indices]
              for p, indices in analysis['shared_input_positions'].items() if indices}
    board['cells'][INSTANCE] = dict(type=SHARED, parameters={},
        port_directions={**{p: 'input' for p in inputs}, NODES: 'output'},
        connections={**inputs, NODES: wires})
    for cell in board['cells'].values():
        if cell['type'] == kernel:
            cell['type'] = PRIVATE
            cell['connections'][NODES] = list(wires)
            cell['port_directions'][NODES] = 'input'
    certificate = dict(top=top, kernel=kernel, instances=instances, analysis=analysis,
                       original_output_nodes=nodes, shared_parent_wires=wires)
    verify_lift(original, candidate, certificate)
    return candidate, certificate


def verify_lift(original, candidate, certificate):
    """Duplicate the lifted hardware back; require literal original circuit data."""
    assert set(certificate) == {'top', 'kernel', 'instances', 'analysis',
                                'original_output_nodes', 'shared_parent_wires'}
    top, kernel, instances = (certificate[k] for k in ('top', 'kernel', 'instances'))
    analysis = analyze(original['modules'], top, kernel, instances)
    assert certificate['analysis'] == analysis
    names = set(analysis['eligible_cell_names'])
    body = original['modules'][kernel]
    nodes = sorted({b for n in names for b in output_bits(body['cells'][n])})
    assert nodes == certificate['original_output_nodes']
    assert set(candidate['modules']) == (set(original['modules']) - {kernel}) | {PRIVATE, SHARED}
    shared = candidate['modules'][SHARED]
    assert shared == dict(attributes={'keep_hierarchy': '1', 'hdlname': SHARED},
        ports=shared_ports(body, analysis, nodes), cells={n: body['cells'][n] for n in sorted(names)})
    private = deepcopy(candidate['modules'][PRIVATE])
    assert private['ports'].pop(NODES) == dict(direction='input', bits=nodes)
    assert set(private['cells']) == set(body['cells']) - names
    private['cells'].update(shared['cells'])
    assert private == body, 'Private kernel/state/DSP changed'
    board = deepcopy(candidate['modules'][top])
    instance = board['cells'].pop(INSTANCE)
    wires = certificate['shared_parent_wires']
    assert wires and len(wires) == len(nodes) and len(set(wires)) == len(wires)
    assert all(type(b) is int and b >= 2 for b in wires)
    assert not set(wires) & all_bits(original['modules'][top]), 'Fresh wire collision'
    assert instance['type'] == SHARED and instance['parameters'] == {}
    assert instance['connections'][NODES] == wires
    assert instance['port_directions'] == {p: s['direction'] for p, s in shared['ports'].items()}
    assert set(instance['connections']) == set(shared['ports'])
    callers = {n: c for n, c in original['modules'][top]['cells'].items() if c['type'] == kernel}
    assert {n for n, c in board['cells'].items() if c['type'] == PRIVATE} == set(callers)
    for name, old in callers.items():
        new = board['cells'][name]
        assert new['connections'].pop(NODES) == wires
        assert new['port_directions'].pop(NODES) == 'input'
        new['type'] = kernel
        assert new == old, 'Original caller changed'
        for port, indices in analysis['shared_input_positions'].items():
            if indices:
                assert instance['connections'][port] == [old['connections'][port][i] for i in indices]
    assert board == original['modules'][top], 'Raw command/board shell changed'
    restored = deepcopy(candidate)
    restored['modules'].pop(PRIVATE)
    restored['modules'].pop(SHARED)
    restored['modules'][kernel], restored['modules'][top] = private, board
    assert restored == original, 'Reverse expansion did not restore every original field'
