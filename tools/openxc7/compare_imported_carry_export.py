"""Comparison-only reconstruction of source-defined empty CARRY4 ports.

frontend_base.h imports a port only while iterating its vector bits. An []
declaration therefore has no imported port in the fresh routed context.
Represent only that absent metadata; never create an endpoint, rewrite an
existing pin or execute this view. The earlier empty-input gate is unchanged.
"""
from collections import Counter
from resume_corrected_dsp_checkpoint import empty_input_view

CARRY_PINS = {
    'CIN': ('input', 'CI'), 'CYINIT': ('input', 'CYINIT'),
    **{f'DI{i}': ('input', f'DI[{i}]') for i in range(4)},
    **{f'S{i}': ('input', f'S[{i}]') for i in range(4)},
    **{f'CO{i}': ('output', f'CO[{i}]') for i in range(4)},
    **{f'O{i}': ('output', f'O[{i}]') for i in range(4)},
}


def carry_export_view(original, exported, include_luts=False):
    assert set(original['cells']) == set(exported['cells']), 'Changed hardware instance membership'
    cells = dict(exported['cells']); restored = Counter()
    for name, source in original['cells'].items():
        if source['type'] != 'CARRY4':
            continue
        cell = cells[name]
        assert cell['type'] == 'CARRY4', 'Changed carry primitive type'
        assert cell['parameters'] == source['parameters'] == {}, 'Unsupported/changed CARRY4 parameters'
        assert source['attributes']['X_ORIG_TYPE'] == cell['attributes']['X_ORIG_TYPE'] == 'CARRY4'
        assert set(source['connections']) == set(source['port_directions'])
        assert set(cell['connections']) == set(cell['port_directions'])
        assert set(cell['connections']) <= set(source['connections']), 'Extra carry pin'
        connections, directions = dict(cell['connections']), dict(cell['port_directions'])
        for pin in set(source['connections']) - set(cell['connections']):
            assert pin in CARRY_PINS, 'Unsupported empty CARRY4 pin'
            direction, annotation = CARRY_PINS[pin]
            assert source['connections'][pin] == [], 'Missing connected carry pin'
            assert source['port_directions'][pin] == direction, 'Wrong original empty carry direction'
            key = 'X_ORIG_PORT_' + pin
            assert source['attributes'][key] == cell['attributes'][key] == annotation, 'Changed empty carry mapping'
            connections[pin], directions[pin] = [], direction
            restored[direction] += 1
        cells[name] = dict(cell, connections=connections, port_directions=directions)
    view, metadata = empty_input_view(original, dict(exported, cells=cells), include_luts=include_luts)
    metadata.update(restored_empty_CARRY4_ports_by_direction=dict(restored),
        CARRY4_contract='SCALAR_PACKED_CARRY4_EMPTY_VECTOR_IMPORT_OMISSION_ONLY',
        missing_connected_ports_restored=False, existing_ports_rewritten=False)
    return view, metadata
