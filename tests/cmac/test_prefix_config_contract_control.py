"""Configuration inventory/bit-interleaving controls, not native FASM or FPGA proof."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/openxc7'))
from audit_prefix_config_contract import (PARAMETERS, selected_cells, dsp_contract,
    bram_contract, bram_half_init, reconstruct_half_init)


def dsp():
    return dict(type='DSP48E1', parameters={key: format(value, '032b') if type(value) is int else value
        for key, value in PARAMETERS.items()}, connections={}, port_directions={})


def bram():
    values = dict(DOA_REG=0, DOB_REG=0, READ_WIDTH_A=9, READ_WIDTH_B=0,
                  WRITE_WIDTH_A=0, WRITE_WIDTH_B=0)
    values = {key: format(value, '032b') for key, value in values.items()}
    values.update(RAM_EXTENSION_A='NONE', RAM_EXTENSION_B='NONE', RAM_MODE='TDP',
                  WRITE_MODE_A='READ_FIRST', WRITE_MODE_B='READ_FIRST')
    for key in ('INIT_A', 'INIT_B', 'SRVAL_A', 'SRVAL_B'):
        values[key] = '0' * 63 + 'x' * 9
    values['INIT_00'] = '0' * 247 + 'x' * 9
    return dict(type='RAMB36E1', parameters=values, connections={}, port_directions={})


class PrefixConfigContractControl(unittest.TestCase):
    def test_actual_DSP_schema_does_not_claim_physical_mode_proof(self):
        result = dsp_contract(dsp())
        self.assertTrue(result['all_actual_register_stages_zero'])
        self.assertEqual(result['unverified_physical_parameter_defaults'], ['USE_MULT=MULTIPLY'])
        self.assertFalse(result['physical_feature_match_verified'])

    def test_changed_DSP_stage_mode_or_unknown_parameter_fails(self):
        for key, value in (('AREG', format(1, '032b')), ('USE_MULT', 'NONE'), ('USE_SIMD', 'TWO24'),
                           ('USE_DPORT', 'TRUE'), ('IS_CLK_INVERTED', '0')):
            cell = dsp()
            cell['parameters'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): dsp_contract(cell)
        cell = dsp()
        cell['parameters'].pop('CREG')
        with self.assertRaises(AssertionError): dsp_contract(cell)

    def test_bram_unknown_startup_and_memory_symbols_remain_explicit(self):
        cell = bram()
        saved = deepcopy(cell)
        result = bram_contract(cell)
        self.assertEqual(cell, saved)
        self.assertEqual(result['unknown_memory_INIT_bits_by_parameter']['INIT_00'], 9)
        self.assertEqual(sum(v['unknown_bits'] for v in result['unknown_initial_reset_output_symbols'].values()), 36)
        self.assertFalse(result['observable_startup_reset_independence_proved'])
        self.assertFalse(result['physical_feature_match_verified'])
        self.assertEqual(result['expected_RAMB18_memory_INIT_vectors'][0]['INIT_00'], '0' * 256)

    def test_unmodeled_BRAM_fields_modes_widths_or_initial_output_values_fail(self):
        for key, value in (('READ_WIDTH_A', format(18, '032b')), ('DOA_REG', format(1, '032b')),
                           ('RAM_MODE', 'SDP'), ('RAM_EXTENSION_A', 'UPPER'), ('WRITE_MODE_A', 'WRITE_FIRST'),
                           ('EN_ECC_READ', 'TRUE'), ('INIT_A', '1' + '0' * 71), ('SRVAL_B', '0' * 36)):
            cell = bram()
            cell['parameters'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): bram_contract(cell)
        cell = bram()
        cell['parameters'].pop('INIT_B')
        with self.assertRaises(AssertionError): bram_contract(cell)

    def test_all_2048_one_hot_data_parity_bits_and_boundary_words_roundtrip(self):
        checked = 0
        for key in ('INIT_00', 'INIT_01', 'INIT_7E', 'INIT_7F', 'INITP_00', 'INITP_01', 'INITP_0E', 'INITP_0F'):
            for bit in range(256):
                original = format(1 << bit, '0256b')
                halves, symbols = bram_half_init({key: original})
                result = reconstruct_half_init(halves)
                self.assertEqual(result[key], original)
                self.assertEqual(symbols[key], 0)
                self.assertEqual(sum(value.count('1') for half in halves for value in half.values()), 1)
                checked += 1
        self.assertEqual(checked, 2048)

    def test_literal_half_bit_positions_and_initial_byte_order(self):
        for key, index in (('INIT_00', 0), ('INIT_01', 128)):
            for bit, half in ((0, 0), (1, 1), (254, 0), (255, 1)):
                halves, _ = bram_half_init({key: format(1 << bit, '0256b')})
                self.assertEqual(int(halves[half]['INIT_00'], 2), 1 << (index + bit // 2))
                self.assertEqual(int(halves[1 - half]['INIT_00'], 2), 0)

    def test_seeded_complete_144_word_memory_and_short_padding_roundtrip(self):
        rng = random.Random(0x3588e1d4)
        keys = [f'INIT_{i:02X}' for i in range(128)] + [f'INITP_{i:02X}' for i in range(16)]
        for _ in range(16):
            original = {key: format(rng.getrandbits(256), '0256b') for key in keys}
            halves, symbols = bram_half_init(original)
            self.assertEqual(reconstruct_half_init(halves), original)
            self.assertEqual(sum(symbols.values()), 0)
        for length in (1, 9, 32, 255, 256):
            bits = '1' * length
            halves, _ = bram_half_init({'INIT_7F': bits})
            self.assertEqual(reconstruct_half_init(halves)['INIT_7F'], bits.zfill(256))

    def test_out_of_range_or_nonliteral_memory_encoding_fails(self):
        for key, bits in (('INIT_80', '0' * 256), ('INITP_10', '0' * 256),
                           ('INIT_00', '0' * 257), ('INIT_00', ''), ('INIT_00', 'z' * 256)):
            with self.subTest(key=key, length=len(bits)), self.assertRaises(AssertionError): bram_half_init({key: bits})

    def test_selected_pretty_input_inventory_and_direction_contract(self):
        design = dict(modules={'ypcb_cmac_array_top': dict(cells={'dsp': dsp(), 'ram': bram(),
                       'logic': dict(type='LUT1', parameters={}, connections={}, port_directions={})})})
        counts, selected = selected_cells(json.dumps(design, indent=2).encode())
        self.assertEqual(counts, {'DSP48E1': 1, 'RAMB36E1': 1, 'LUT1': 1})
        self.assertEqual(set(selected), {'dsp', 'ram'})
        self.assertEqual(selected['ram'], bram())
        bad = deepcopy(design)
        bad['modules']['ypcb_cmac_array_top']['cells']['ram']['connections']['missing_direction'] = [2]
        with self.assertRaises(AssertionError): selected_cells(json.dumps(bad, indent=2).encode())


if __name__ == '__main__':
    unittest.main()
