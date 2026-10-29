"""New encoder-policy controls; old error expectations are not altered."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from check_corrected_dsp_features import corrected_expectations, compare_corrected_dsp
from check_prefix_native_features import compare_dsp
from probe_prefix_native_config import SELECTED, representatives


class CorrectedDSPFeatureControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.originals = [c for c in representatives(json.loads(SELECTED.read_text())).values() if c['type'] == 'DSP48E1']

    def fixture(self, original=None):
        original = deepcopy(original or self.originals[0])
        expected = corrected_expectations(original)
        placement = dict(type='DSP48E1_DSP48E1', bel='DSP48E1', site='DSP48_X0Y2', tile='DSP_L_X1Y5')
        packed = dict(type=placement['type'], parameters={**original['parameters'],
            **{key: str(value) for key, value in expected['extra_inversion_parameters'].items()}}, attributes={
            'DSP_' + level + '_PINS': ' '.join(pin for pin, net in expected['packed_tile_constant_nets'].items() if net == level)
            for level in ('GND', 'VCC')})
        features = {'DSP_L_X1Y5.DSP48.DSP_0.' + key: '1' for key in expected['DSP48_features']}
        features.update({'DSP_L_X1Y5.DSP_0_' + pin + '.DSP_' + level + '_L': '1'
                         for pin, level in expected['logical_tile_constant_values'].items()})
        return features, placement, original, packed

    def test_all_four_actual_profiles(self):
        for original in self.originals:
            result = compare_corrected_dsp(*self.fixture(original))
            self.assertEqual(result['dedicated_constant_pins_compared'], 39)
            self.assertEqual(result['extra_tile_only_pins_compared'], 8)
            self.assertFalse(result['numerical_or_silicon_acceptance'])

    def test_old_comparator_still_rejects_new_encoding(self):
        with self.assertRaises(AssertionError):
            compare_dsp(*self.fixture())

    def test_missing_inverter_disable_rejected(self):
        args = self.fixture()
        del args[0]['DSP_L_X1Y5.DSP48.DSP_0.ZIS_INMODE_INVERTED[1]']
        with self.assertRaises(AssertionError): compare_corrected_dsp(*args)

    def test_wrong_physical_VCC_rejected(self):
        args = self.fixture()
        del args[0]['DSP_L_X1Y5.DSP_0_INMODE1.DSP_GND_L']
        args[0]['DSP_L_X1Y5.DSP_0_INMODE1.DSP_VCC_L'] = '1'
        with self.assertRaises(AssertionError): compare_corrected_dsp(*args)

    def test_missing_declared_tile_tie_rejected(self):
        args = self.fixture()
        args[3]['attributes']['DSP_VCC_PINS'] = args[3]['attributes']['DSP_VCC_PINS'].replace('INMODE1', '')
        with self.assertRaises(AssertionError): compare_corrected_dsp(*args)

    def test_unsupported_nonzero_tile_profile_rejected(self):
        original = deepcopy(self.originals[0])
        original['connections']['INMODE'][1] = '1'
        with self.assertRaises(AssertionError): corrected_expectations(original)


if __name__ == '__main__':
    unittest.main()
