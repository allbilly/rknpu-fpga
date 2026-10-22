"""Corrected-frame readback guards; these controls are not physical evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import probe_corrected_frame_database as control


class CorrectedFrameDatabaseControl(unittest.TestCase):
    def test_actual_completed_native_FASM_contains_all_64_added_features(self):
        q = json.loads(control.NATIVE.read_text())
        self.assertEqual(len(control.required_features(q)), 64)

    def test_input_requests_not_defaults_must_supply_each_required_feature_once(self):
        required = {'DSP_L_X1Y2.DSP_0_INMODE0.DSP_GND_L': '1'}
        request = dict(feature=next(iter(required)), value=1, start=None, end=None, kind='input_lines')
        self.assertEqual(control.verify_requests([request], required), {'input_lines': 1, 'injected_lines': 0})
        for requests in ([], [request, request], [dict(request, value=0)], [dict(request, kind='injected_lines')]):
            with self.subTest(requests=requests), self.assertRaises(AssertionError):
                control.verify_requests(requests, required)

    def test_scalar_single_bit_and_vector_request_canonicalization(self):
        r = dict(feature='DSP_L_X1Y2.DSP48.DSP_0.ZIS_INMODE_INVERTED', value=5, start=0, end=2, kind='input_lines')
        self.assertEqual(control.request_features(r), [r['feature'] + '[0]', r['feature'] + '[2]'])
        self.assertEqual(control.request_features(dict(r, start=4, end=None, value=1)), [r['feature'] + '[4]'])
        for change in ({'value': -1}, {'value': 8}, {'end': -1}, {'start': None}, {'kind': 'ignored'}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                control.request_features(dict(r, **change))

    def test_set_and_clear_bits_are_both_required(self):
        locations = {'set': [(0x123, 2, 7, True)], 'clear': [(0x123, 2, 8, False)]}
        words = {0x123: [0] * 101}
        words[0x123][2] = 1 << 7
        result = control.check_feature_bits(locations, words)
        self.assertEqual((result['features_compared'], result['physical_DB_bits_compared']), (2, 2))
        for bit in (7, 8):
            bad = deepcopy(words)
            bad[0x123][2] ^= 1 << bit
            with self.subTest(bit=bit), self.assertRaises(AssertionError):
                control.check_feature_bits(locations, bad)

    def test_no_empty_missing_truncated_or_out_of_range_bit_locations(self):
        good = {'one': [(0x123, 0, 0, True)]}
        for locations, words in (({}, {}), ({'empty': []}, {}), (good, {}), (good, {0x123: [1]}),
                ({'badword': [(0x123, 101, 0, True)]}, {0x123: [0] * 101}),
                ({'badbit': [(0x123, 0, 32, True)]}, {0x123: [0] * 101})):
            with self.subTest(locations=locations), self.assertRaises(AssertionError):
                control.check_feature_bits(locations, words)


if __name__ == '__main__':
    unittest.main()
