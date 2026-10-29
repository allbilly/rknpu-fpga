"""Exact eight-pin DSP correction of an unrouted native placement copy.

Only apply the already qualified DSP tile-constant representation change.
All BELs, ordinary wires, parameters, other attributes and named nets remain
unchanged. Inputs are never mutated. This structural preparation is not
native transfer legality: tag initialization and routing must run separately.
"""
from collections import Counter

from audit_corrected_full_pack_identity import compare_dsp_delta, declared_ties
from check_corrected_dsp_features import corrected_expectations, verify_corrected_packed
from check_prefix_native_features import dsp_expectations
from place_prefix_board import verify_placed_module


def constant_drivers(module):
    result = {}
    for level in ('GND', 'VCC'):
        names = [name for name, cell in module['cells'].items() if cell['type'] == 'PSEUDO_' + level]
        assert len(names) == 1, 'Missing/duplicate native constant driver'
        driver = module['cells'][names[0]]
        assert driver['port_directions'] == {'Y': 'output'} and set(driver['connections']) == {'Y'}
        bits = driver['connections']['Y']
        assert len(bits) == 1 and type(bits[0]) is int and bits[0] >= 2
        net = module['netnames']['$PACKER_' + level + '_NET']
        assert net['bits'] == bits, 'Constant named net differs from driver'
        result[level] = bits[0]
    assert result['GND'] != result['VCC'], 'Aliased native constants'
    return result


def verify_delta(original, corrected, selected):
    """Complete structural delta, not a permissive disconnected-pin view."""
    assert set(original) == set(corrected)
    assert all(original[key] == corrected[key] for key in original if key != 'cells'), 'Changed checkpoint header/named nets'
    assert set(original['cells']) == set(corrected['cells']), 'Changed checkpoint cell membership'
    constants = constant_drivers(original)
    dsps = {name for name, cell in original['cells'].items() if cell['type'] == 'DSP48E1_DSP48E1'}
    assert dsps == set(selected), 'Incomplete/extra DSP correction inventory'
    changed = 0
    for name, old in original['cells'].items():
        new = corrected['cells'][name]
        if name not in dsps:
            assert old == new, 'Changed non-DSP checkpoint cell'
            continue
        assert old['attributes']['NEXTPNR_BEL'] == new['attributes']['NEXTPNR_BEL'], 'Changed DSP BEL'
        changed += compare_dsp_delta(old, new, selected[name], constants['VCC'])
        policy = corrected_expectations(selected[name])
        assert all(value == 'GND' for pin, value in policy['logical_tile_constant_values'].items()
                   if pin not in dsp_expectations(selected[name])['dedicated_constant_pins'])
    assert changed == 8 * len(dsps)
    return dict(cells_compared=len(original['cells']), DSPs_corrected=len(dsps),
        tile_pin_disconnections_compared=changed, all_physical_BELs_unchanged=True,
        all_parameters_ordinary_wires_other_attributes_and_named_nets_unchanged=True,
        extra_packed_VCC_with_inversion_preserves_logical_GND=True,
        native_transfer_legality_admitted=False, full_route_admitted=False,
        numerical_or_physical_signoff=False)


def correct_placement(module, selected):
    counts = dict(Counter(cell['type'] for cell in module['cells'].values()))
    verify_placed_module(module, counts)
    constants = constant_drivers(module)
    dsps = {name for name, cell in module['cells'].items() if cell['type'] == 'DSP48E1_DSP48E1'}
    assert dsps == set(selected) and dsps, 'Incomplete/empty DSP correction inventory'
    cells = dict(module['cells'])
    for name in dsps:
        old = cells[name]
        expected = corrected_expectations(selected[name])
        baseline = dsp_expectations(selected[name])['dedicated_constant_pins']
        assert declared_ties(old) == baseline, 'Not the exact original 31-tie DSP representation'
        extra = set(expected['packed_tile_constant_nets']) - set(baseline)
        assert len(extra) == 8
        connections = dict(old['connections'])
        for pin in extra:
            assert old['port_directions'][pin] == 'input' and connections[pin] == [constants['VCC']], 'Wrong old tile-only pin wire'
            connections[pin] = []
        attributes = dict(old['attributes'])
        for level in ('GND', 'VCC'):
            attributes['DSP_' + level + '_PINS'] = ' '.join(sorted(
                pin for pin, value in expected['packed_tile_constant_nets'].items() if value == level))
        cells[name] = dict(old, connections=connections, attributes=attributes)
        verify_corrected_packed(selected[name], cells[name])
    corrected = dict(module, cells=cells)
    return corrected, verify_delta(module, corrected, selected)
