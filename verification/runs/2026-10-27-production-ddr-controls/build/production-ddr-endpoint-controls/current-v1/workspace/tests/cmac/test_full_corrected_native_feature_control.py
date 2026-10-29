"""Actual saved corrected DSP/BRAM reader controls, never a full-route PASS."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/openxc7'))
import check_full_corrected_native_features as check
from check_full_native_features import compare_selected as old_compare
from probe_prefix_native_config import SELECTED

PARENT = ROOT / 'build/openxc7/corrected-dsp-checkpoint-resume-1791418453459203706/report.json'


class FullCorrectedNativeFeatureControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        report = json.loads(PARENT.read_text())
        assert report['status'] == 'PASS_CORRECTED_DSP_BRAM_PLACED_RELOAD_AND_ROUTE_WITH_EXACT_EMPTY_INPUT_METADATA_VIEW_NOT_FULL_TRANSFER_OR_SIGNOFF'
        assert report['stage'] == 'complete' and report['finished_utc']
        cls.files = [PARENT.parent / name for name in ('control.fasm', 'placement.json', 'routed.json')]
        for path in cls.files:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == report['artifacts'][str(path.relative_to(ROOT))]
        assert hashlib.sha256(SELECTED.read_bytes()).hexdigest() == report['source'][str(SELECTED.resolve())]
        cls.full_selected = json.loads(SELECTED.read_text())
        cls.selected = {name: cls.full_selected[source] for name, source in report['control_origins'].items()}
        cls.features, cls.repeated = check.parse_native_features(cls.files[0].read_text())
        cls.placed = check.placed_primitives(cls.files[1], cls.selected)
        cls.packed = check.routed_primitives(cls.files[2], cls.selected)
        cls.db = check.SiteBELMap(check.DATABASE, check.CONSTIDS)
        cls.db.__enter__()
        cls.dsp = next(name for name, cell in cls.selected.items() if cell['type'] == 'DSP48E1')

    @classmethod
    def tearDownClass(cls):
        cls.db.__exit__(None, None, None)

    def compare(self, features=None, placements=None, packed=None, selected=None):
        return check.compare_selected(self.features if features is None else features,
            self.placed if placements is None else placements, self.selected if selected is None else selected,
            self.packed if packed is None else packed, self.db.global_label)

    def test_actual_saved_reader_and_all_ten_corrected_primitive_configurations(self):
        result = self.compare()
        self.assertEqual(len(result), 10)
        self.assertEqual(len(self.features), 7655)
        # The pinned parser records each repeated STEPDOWN's two line numbers.
        self.assertEqual(len(self.repeated), 5)
        self.assertTrue(all(len(lines) == 2 for lines in self.repeated.values()))
        self.assertEqual(sum(v.get('extra_tile_only_pins_compared', 0) for v in result.values()), 32)
        self.assertEqual(sum(v.get('dedicated_constant_pins_compared', 0) for v in result.values()), 156)

    def test_old_actual_gate_still_rejects_corrected_encoding(self):
        with self.assertRaises(AssertionError):
            old_compare(self.features, self.placed, self.selected, self.packed, self.db.global_label)

    def test_saved_small_control_cannot_pass_full_target_census(self):
        with self.assertRaises(AssertionError):
            check.verify_full_features(*self.files, self.selected, {})

    def test_full_source_census_is_16_by_32_plus_three_shell_dsps_not_small(self):
        packed = {name: dict(type='DSP48E1_DSP48E1' if cell['type'] == 'DSP48E1' else 'RAMB36E1_RAMB36E1')
                  for name, cell in self.full_selected.items()}
        groups = check.full_inventory(self.full_selected, packed)
        self.assertEqual(len(groups), 16)
        self.assertEqual(set(groups.values()), {32})
        del packed[next(name for name in packed if '.' in name)]
        with self.assertRaisesRegex(AssertionError, 'membership'): check.full_inventory(self.full_selected, packed)

    def test_missing_selected_primitive_rejected(self):
        packed = deepcopy(self.packed)
        del packed[self.dsp]
        with self.assertRaisesRegex(AssertionError, 'membership'): self.compare(packed=packed)

    def test_duplicate_physical_bel_rejected(self):
        placed = deepcopy(self.placed)
        a, b = list(placed)[:2]
        placed[b]['nextpnr_bel'] = placed[a]['nextpnr_bel']
        with self.assertRaisesRegex(AssertionError, 'Aliased'): self.compare(placements=placed)

    def test_changed_routed_bel_rejected(self):
        packed = deepcopy(self.packed)
        packed[self.dsp]['attributes']['NEXTPNR_BEL'] = 'NOT_A_NATIVE_BEL'
        with self.assertRaisesRegex(AssertionError, 'differs'): self.compare(packed=packed)

    def test_missing_actual_tile_tie_rejected(self):
        features = dict(self.features)
        pin = next(key for key in features if '_INMODE1.DSP_GND_' in key)
        del features[pin]
        with self.assertRaises(AssertionError): self.compare(features=features)

    def test_actual_wrong_vcc_tie_rejected(self):
        features = dict(self.features)
        pin = next(key for key in features if '_INMODE1.DSP_GND_' in key)
        features[pin.replace('.DSP_GND_', '.DSP_VCC_')] = features.pop(pin)
        with self.assertRaises(AssertionError): self.compare(features=features)

    def test_missing_actual_inverter_disable_rejected(self):
        features = dict(self.features)
        del features[next(key for key in features if key.endswith('.ZIS_INMODE_INVERTED[1]'))]
        with self.assertRaises(AssertionError): self.compare(features=features)

    def test_actual_bram_configuration_corruption_rejected(self):
        features = dict(self.features)
        # Source-defined RAMB36 INIT emission uses two RAMB18_Y halves.
        pin = next(key for key in features if '.RAMB18_Y' in key and '.INIT_' in key)
        value = features[pin]
        self.assertEqual(len(value), 256)
        features[pin] = ('1' if value[0] == '0' else '0') + value[1:]
        with self.assertRaises(AssertionError): self.compare(features=features)

    def test_unsupported_nonzero_tile_profile_rejected(self):
        selected = deepcopy(self.selected)
        selected[self.dsp]['connections']['INMODE'][1] = '1'
        with self.assertRaises(AssertionError): self.compare(selected=selected)


if __name__ == '__main__':
    unittest.main()
