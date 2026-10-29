"""Separate a662c08 DSP tie policy for the actual zero-register profile.

The old source-defined comparator remains unchanged. The corrected packer
disconnects eight extra tile-only pins; its FASM writer encodes their logical
zero as a GND tie with the physical inverter disabled, even though packing
represented that zero as VCC plus a per-bit inversion. No general DSP modes,
ordinary constant routing, physical USE_MULT default or silicon are admitted.
"""
import re

from check_prefix_native_features import dsp_expectations as old_expectations
from audit_upstream_dsp_constants import requirements


def corrected_expectations(original):
    expected = old_expectations(original)
    extra = requirements(original)
    packed_ties = dict(expected['dedicated_constant_pins'])
    logical_ties = dict(packed_ties)
    for pin, spec in extra.items():
        assert pin not in packed_ties
        packed_ties[pin] = 'VCC'
        logical_ties[pin] = 'GND'
        expected['DSP48_features'].add(f"ZIS_{spec['bus']}_INVERTED[{spec['bit']}]")
    assert len(packed_ties) == len(logical_ties) == 39
    return dict(**expected, packed_tile_constant_nets=packed_ties, logical_tile_constant_values=logical_ties)


def verify_corrected_packed(original, packed):
    expected = corrected_expectations(original)
    assert packed['type'] == 'DSP48E1_DSP48E1'
    params = packed['parameters']
    assert set(params) == set(expected['parameters']) | set(expected['extra_inversion_parameters']), 'Unmodeled packed DSP parameter'
    for key, value in expected['parameters'].items():
        assert params[key] == value, 'Changed literal DSP parameter'
    for key, value in expected['extra_inversion_parameters'].items():
        assert re.fullmatch('[01]+', params[key]) and int(params[key], 2) == value, 'Wrong packed DSP pin inversion'
    pins = {}
    for level in ('GND', 'VCC'):
        names = packed['attributes']['DSP_' + level + '_PINS'].split()
        assert len(names) == len(set(names)) and not set(names) & set(pins), 'Duplicate/conflicting DSP tile pin'
        pins.update(dict.fromkeys(names, level))
    assert pins == expected['packed_tile_constant_nets'], 'Corrected packed DSP tile ties mismatch'
    return expected


def compare_corrected_dsp(features, placement, original, packed):
    expected = verify_corrected_packed(original, packed)
    assert placement['type'] == packed['type'] and placement['bel'] == 'DSP48E1'
    match = re.fullmatch(r'DSP48_X\d+Y(\d+)', placement['site'])
    tile = placement['tile']
    assert match and re.fullmatch(r'DSP_[LR]_X\d+Y\d+', tile), 'Unsupported physical DSP site'
    side, slot = tile[4], int(match.group(1)) % 2
    prefix = f'{tile}.DSP48.DSP_{slot}.'
    actual = {k[len(prefix):]: value for k, value in features.items() if k.startswith(prefix)}
    assert actual == dict.fromkeys(expected['DSP48_features'], '1'), 'Corrected DSP configuration feature mismatch'
    tie_prefix = f'{tile}.DSP_{slot}_'
    actual_ties = {k: value for k, value in features.items() if k.startswith(tie_prefix) and '.DSP_' in k[len(tie_prefix):]}
    required = {tie_prefix + pin + '.DSP_' + level + '_' + side: '1'
                for pin, level in expected['logical_tile_constant_values'].items()}
    assert actual_ties == required, 'Corrected DSP logical tie feature mismatch'
    return dict(DSP48_configuration_features_compared=len(actual), dedicated_constant_pins_compared=39,
                extra_tile_only_pins_compared=8, logical_GND_and_physical_inverter_disabled_matched=True,
                literal_parameters_preserved=True, USE_MULT_physical_default_verified=False,
                ordinary_constant_net_routing_verified=False, numerical_or_silicon_acceptance=False)
