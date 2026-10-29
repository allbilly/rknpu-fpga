"""Recognize only the DSP48E1 declaration's four CEP timing qualifiers.

This is a resource-counter view, not simulation or timing signoff. The source
library and actual instance graph remain unchanged. No hardware arithmetic or
unknown cell is excluded. Global CMAC counters keep their existing contract.
"""
from collections import Counter
from xc7_primitive_counts import TIMING


def timing_only_view(modules):
    module = modules.get('DSP48E1', {})
    cells = module.get('cells', {})
    qualifiers = {name: cell for name, cell in cells.items() if cell['type'] not in TIMING}
    if not qualifiers:
        return modules, []
    assert int(module.get('attributes', {}).get('blackbox', '0'), 2) == 1
    assert len(qualifiers) == 4, 'Unexpected DSP timing-qualifier domain'
    ports = module['ports']
    for name, direction, width in [('CEP', 'input', 1), ('CLK', 'input', 1),
            ('P', 'output', 48), ('PCOUT', 'output', 48)]:
        assert ports[name]['direction'] == direction and len(ports[name]['bits']) == width
    port_bits = {b for p in ports.values() for b in p['bits']}
    used, roles, audit = set(), Counter(), []
    for name, cell in sorted(qualifiers.items()):
        assert cell['type'] == '$logic_and', 'Non-timing logic in DSP declaration'
        assert cell['port_directions'] == {'A': 'input', 'B': 'input', 'Y': 'output'}
        assert {k: int(v, 2) for k, v in cell['parameters'].items()} == {
            'A_SIGNED': 0, 'B_SIGNED': 0, 'A_WIDTH': 1, 'B_WIDTH': 1, 'Y_WIDTH': 1}
        connections = cell['connections']
        assert set(connections) == {'A', 'B', 'Y'}
        assert connections['A'] in (['0'], ['1']) and connections['B'] == ports['CEP']['bits']
        assert len(connections['Y']) == 1
        bit = connections['Y'][0]
        assert type(bit) is int and bit not in port_bits and bit not in used, 'Qualifier drives primitive port'
        used.add(bit)
        sinks = [(other_name, pin) for other_name, other in cells.items() if other_name != name
            for pin, bits in other['connections'].items() if bit in bits]
        assert len(sinks) == 1 and sinks[0][1] == 'EN', 'Qualifier feeds non-enable or additional logic'
        sink_name, _ = sinks[0]; sink = cells[sink_name]
        assert sink['type'] == '$specify3' and sink['port_directions']['EN'] == 'input'
        assert sink['connections']['SRC'] == ports['CLK']['bits']
        assert sink['connections']['DAT'] == ['x'] * 48
        destination = [n for n in ('P', 'PCOUT') if sink['connections']['DST'] == ports[n]['bits']]
        assert len(destination) == 1, 'Unknown qualified timing destination'
        roles[(connections['A'][0], destination[0])] += 1
        audit.append(dict(cell=name, output=bit, constant_enable=connections['A'][0],
            sink=sink_name, timing_destination=destination[0]))
    assert roles == Counter({('0', 'P'): 1, ('1', 'P'): 1, ('0', 'PCOUT'): 1, ('1', 'PCOUT'): 1})
    view = dict(modules)
    view['DSP48E1'] = dict(module, cells={name: cell for name, cell in cells.items() if name not in qualifiers})
    return view, audit
