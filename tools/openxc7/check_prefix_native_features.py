"""Strict source-defined native feature comparisons, not silicon signoff.

Expected values are comparison data only. DSP packing/FASM semantics come
from the pinned pack.cc, pins.cc, pack_dsp_xc7.cc and fasm.cc. They do not
establish the physical USE_MULT default, startup independence or timing.
"""
import re

from audit_prefix_config_contract import dsp_contract, bram_contract, bram_half_init


def dsp_expectations(original):
    """The actual zero-register/direct/ONE48 contract, including zero ties.

    pack_constants converts each invertible literal-zero input to VCC plus
    IS_<pin>_INVERTED=1; DSP bus inversion parameters retain their brackets.
    CLK is not in the DSP invertible-pin set. Missing CE/RST/CLK pins are
    supplied with the exact default-zero ties in pins.cc, not new clocks.
    """
    dsp_contract(original)
    conns = original['connections']
    extra_params, flags = {}, {'AREG_0', 'BREG_0', 'ZIS_CLK_INVERTED'}
    flags.update(('ZADREG[0]', 'ZALUMODEREG[0]', 'ZAREG_2_ACASCREG_1',
                  'ZBREG_2_BCASCREG_1', 'ZCARRYINREG[0]', 'ZCARRYINSELREG[0]',
                  'ZCREG[0]', 'ZDREG[0]', 'ZINMODEREG[0]', 'ZMREG[0]',
                  'ZOPMODEREG[0]', 'ZPREG[0]'))
    for pin, width in (('ALUMODE', 4), ('INMODE', 5), ('OPMODE', 7)):
        assert len(conns[pin]) == width and set(conns[pin]) <= {'0', '1'}
        for i, bit in enumerate(conns[pin]):
            if bit == '0': extra_params[f'IS_{pin}[{i}]_INVERTED'] = 1
            else: flags.add(f'ZIS_{pin}_INVERTED[{i}]')
    assert conns['CARRYIN'] == ['0']
    extra_params['IS_CARRYIN_INVERTED'] = 1
    # pack_dsps disconnects these literal/default zero pins and records the
    # dedicated tile ties. Other constants remain ordinary routed nets.
    assert conns['D'] == ['0'] * 25 and conns['CARRYINSEL'] == ['0'] * 3
    ties = {f'D{i}': 'GND' for i in range(25)}
    ties.update({p: 'GND' for p in ('CARRYINSEL2', 'RSTD', 'CED', 'CEAD',
                                   'CEINMODE', 'CEALUMODE')})
    return dict(parameters=original['parameters'], extra_inversion_parameters=extra_params,
                DSP48_features=flags, dedicated_constant_pins=ties)


def compare_dsp(features, placement, original, packed):
    expected = dsp_expectations(original)
    assert placement['type'] == packed['type'] == 'DSP48E1_DSP48E1'
    assert placement['bel'] == 'DSP48E1'
    match = re.fullmatch(r'DSP48_X\d+Y(\d+)', placement['site'])
    assert match, 'Unsupported physical DSP site name'
    tile = placement['tile']
    assert re.fullmatch(r'DSP_[LR]_X\d+Y\d+', tile)
    side, slot = tile[4], int(match.group(1)) % 2
    prefix = f'{tile}.DSP48.DSP_{slot}.'
    actual = {k[len(prefix):]: value for k, value in features.items() if k.startswith(prefix)}
    assert actual == dict.fromkeys(expected['DSP48_features'], '1'), 'DSP configuration feature mismatch'
    params = packed['parameters']
    assert set(params) == set(expected['parameters']) | set(expected['extra_inversion_parameters']), 'Unmodeled packed DSP parameter'
    for k, v in expected['parameters'].items(): assert params[k] == v, 'Changed literal DSP parameter'
    for k, v in expected['extra_inversion_parameters'].items():
        assert re.fullmatch('[01]+', params[k]) and int(params[k], 2) == v, 'Wrong packed DSP pin inversion'
    attrs = packed['attributes']
    pins = {}
    for level in ('GND', 'VCC'):
        names = attrs['DSP_' + level + '_PINS'].split()
        assert len(names) == len(set(names)) and not (set(names) & set(pins)), 'Duplicate/conflicting DSP constant pin'
        pins.update(dict.fromkeys(names, level))
    assert pins == expected['dedicated_constant_pins'], 'Packed DSP dedicated ties differ from literal/default pins'
    tie_prefix = f'{tile}.DSP_{slot}_'
    actual_ties = {k: v for k, v in features.items() if k.startswith(tie_prefix) and '.DSP_' in k[len(tie_prefix):]}
    required_ties = {tie_prefix + pin + '.DSP_' + level + '_' + side: '1' for pin, level in pins.items()}
    assert actual_ties == required_ties, 'DSP dedicated constant-pin feature mismatch'
    return dict(DSP48_configuration_features_compared=len(actual), dedicated_constant_pins_compared=len(pins),
                literal_parameters_preserved=True, source_defined_pin_inversions_matched=True,
                USE_MULT_physical_default_verified=False, ordinary_constant_net_routing_verified=False,
                numerical_or_silicon_acceptance=False)


def compare_bram(features, placement, original):
    bram_contract(original)
    assert placement['type'] == 'RAMB36E1_RAMB36E1' and placement['bel'] == 'RAMB36E1'
    tile = placement['tile']
    params = original['parameters']
    halves, unknown = bram_half_init(params)
    for half in range(2):
        prefix = f'{tile}.RAMB18_Y{half}.'
        required = {'IN_USE': '1'}
        required.update({k + '[255:0]': v for k, v in halves[half].items()})
        required.update({k + '[17:0]': '1' * 18 for k in ('ZINIT_A', 'ZINIT_B', 'ZSRVAL_A', 'ZSRVAL_B')})
        for key in ('READ_WIDTH_A', 'READ_WIDTH_B', 'WRITE_WIDTH_A', 'WRITE_WIDTH_B'):
            if int(params[key], 2) == 9: required[key + '_4'] = '1'
        required.update({key + '_READ_FIRST': '1' for key in ('WRITE_MODE_A', 'WRITE_MODE_B')})
        def compared(key):
            return key == 'IN_USE' or key in ('DOA_REG', 'DOB_REG', 'SDP_READ_WIDTH_36', 'SDP_WRITE_WIDTH_36',
                                            'ZINV_REGCLKARDRCLK', 'ZINV_REGCLKB') or bool(re.fullmatch(
                r'(?:INITP?_[0-9A-F]{2}\[255:0\]|Z(?:INIT|SRVAL)_[AB]\[17:0\]|(?:READ|WRITE)_WIDTH_[AB]_\d+|WRITE_MODE_[AB]_(?:READ_FIRST|WRITE_FIRST|NO_CHANGE))', key))
        actual = {k[len(prefix):]: v for k, v in features.items() if k.startswith(prefix) and compared(k[len(prefix):])}
        assert actual == required, 'BRAM memory/width/mode/output-register feature mismatch'
    for key in ('READ_WIDTH_A', 'READ_WIDTH_B', 'WRITE_WIDTH_A', 'WRITE_WIDTH_B'):
        name = tile + '.RAMB36.BRAM36_' + key + '_1'
        assert features.get(name) == ('1' if int(params[key], 2) == 9 else None), 'Missing/extra odd-width tile feature'
    return dict(memory_vectors_compared=sum(map(len, halves)), unknown_memory_bits_coerced_to_zero=sum(unknown.values()),
                source_defined_memory_width_mode_output_features_matched=True,
                observable_startup_reset_independence_proved=False, numerical_or_silicon_acceptance=False)
