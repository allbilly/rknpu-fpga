"""Synthetic feature corruption tests, not new native execution evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from probe_prefix_native_config import SELECTED, representatives
from check_prefix_native_features import compare_dsp, compare_bram, dsp_expectations
from audit_prefix_config_contract import bram_half_init


class PrefixNativeFeatureControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.chosen = representatives(json.loads(SELECTED.read_text()))

    def dsp_case(self, original, side='L', slot=0):
        expected = dsp_expectations(original)
        tile = f'DSP_{side}_X1Y2'
        placement = dict(type='DSP48E1_DSP48E1', bel='DSP48E1', tile=tile, site=f'DSP48_X0Y{2 + slot}')
        features = {f'{tile}.DSP48.DSP_{slot}.' + k: '1' for k in expected['DSP48_features']}
        features.update({f'{tile}.DSP_{slot}_{p}.DSP_{v}_{side}': '1' for p, v in expected['dedicated_constant_pins'].items()})
        packed = dict(type=placement['type'], parameters=dict(original['parameters']), attributes=dict(
            DSP_GND_PINS=' '.join(expected['dedicated_constant_pins']), DSP_VCC_PINS=''))
        packed['parameters'].update({k: str(v) for k, v in expected['extra_inversion_parameters'].items()})
        return features, placement, packed

    def bram_case(self, original):
        tile = 'BRAM_L_X1Y2'
        placement = dict(type='RAMB36E1_RAMB36E1', bel='RAMB36E1', tile=tile)
        params = original['parameters']
        features = {}
        halves, _ = bram_half_init(params)
        for h in range(2):
            p = f'{tile}.RAMB18_Y{h}.'
            features[p + 'IN_USE'] = '1'
            features.update({p + k + '[255:0]': v for k, v in halves[h].items()})
            features.update({p + k + '[17:0]': '1' * 18 for k in ('ZINIT_A', 'ZINIT_B', 'ZSRVAL_A', 'ZSRVAL_B')})
            features.update({p + k + '_READ_FIRST': '1' for k in ('WRITE_MODE_A', 'WRITE_MODE_B')})
            for k in ('READ_WIDTH_A', 'READ_WIDTH_B', 'WRITE_WIDTH_A', 'WRITE_WIDTH_B'):
                if int(params[k], 2) == 9:
                    features[p + k + '_4'] = '1'
                    features[tile + '.RAMB36.BRAM36_' + k + '_1'] = '1'
        return features, placement

    def test_all_four_literal_dsp_representatives_and_both_tile_sides_slots(self):
        for name, original in self.chosen.items():
            if original['type'] != 'DSP48E1': continue
            for side in ('L', 'R'):
                for slot in (0, 1):
                    features, placed, packed = self.dsp_case(original, side, slot)
                    with self.subTest(name=name, side=side, slot=slot):
                        result = compare_dsp(features, placed, original, packed)
                        self.assertFalse(result['USE_MULT_physical_default_verified'])
                        self.assertEqual(result['dedicated_constant_pins_compared'], 31)

    def test_dsp_missing_extra_register_simd_inversion_tie_and_mode_fail(self):
        original = next(c for c in self.chosen.values() if c['type'] == 'DSP48E1')
        for change in ('missing', 'extra', 'simd', 'inversion', 'tie', 'tie_attr', 'mode', 'slot'):
            f, p, c = self.dsp_case(original)
            prefix = p['tile'] + '.DSP48.DSP_0.'
            if change == 'missing': f.pop(prefix + 'AREG_0')
            elif change == 'extra': f[prefix + 'AREG_2'] = '1'
            elif change == 'simd': f[prefix + 'USE_SIMD_FOUR12'] = '1'
            elif change == 'inversion': c['parameters']['IS_CARRYIN_INVERTED'] = '0'
            elif change == 'tie': f[p['tile'] + '.DSP_0_D0.DSP_VCC_L'] = '1'
            elif change == 'tie_attr': c['attributes']['DSP_VCC_PINS'] = 'D0'
            elif change == 'mode': c['parameters']['USE_MULT'] = 'NONE'
            else: p['site'] = 'DSP48_X0Y3'
            with self.subTest(change=change), self.assertRaises((AssertionError, KeyError)): compare_dsp(f, p, original, c)

    def test_all_six_bram_contracts_including_explicit_startup_gap(self):
        total_unknown = 0
        for name, original in self.chosen.items():
            if original['type'] != 'RAMB36E1': continue
            f, p = self.bram_case(original)
            with self.subTest(name=name):
                result = compare_bram(f, p, original)
                self.assertFalse(result['observable_startup_reset_independence_proved'])
                total_unknown += result['unknown_memory_bits_coerced_to_zero']
        self.assertEqual(total_unknown, 90112)

    def test_bram_memory_width_mode_register_reset_and_extra_init_fail(self):
        original = next(c for c in self.chosen.values() if c['type'] == 'RAMB36E1')
        for change in ('init', 'width', 'extra_width', 'mode', 'extra_mode', 'register', 'reset', 'extra_init'):
            f, p = self.bram_case(original)
            prefix = p['tile'] + '.RAMB18_Y0.'
            if change == 'init':
                key = prefix + 'INIT_00[255:0]'; f[key] = ('1' if f[key][0] == '0' else '0') + f[key][1:]
            elif change == 'width': f.pop(p['tile'] + '.RAMB36.BRAM36_READ_WIDTH_A_1')
            elif change == 'extra_width': f[prefix + 'READ_WIDTH_A_18'] = '1'
            elif change == 'mode': f.pop(prefix + 'WRITE_MODE_A_READ_FIRST')
            elif change == 'extra_mode': f[prefix + 'WRITE_MODE_A_WRITE_FIRST'] = '1'
            elif change == 'register': f[prefix + 'DOA_REG'] = '1'
            elif change == 'reset': f[prefix + 'ZSRVAL_A[17:0]'] = '0' + '1' * 17
            else: f[prefix + 'INIT_7F[255:0]'] = '0' * 256
            with self.subTest(change=change), self.assertRaises((AssertionError, KeyError)): compare_bram(f, p, original)


if __name__ == '__main__': unittest.main()
