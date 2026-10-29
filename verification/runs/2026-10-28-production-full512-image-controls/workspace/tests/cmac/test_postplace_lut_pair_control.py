"""Fixed A6-mode contracts; do not weaken old pre-placement negatives."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import audit_postplace_lut_pairs as audit


class PostplaceLUTPairControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = audit.QUALIFICATION.parent / 'valid-forced-placed.json'
        cls.module = next(iter(json.loads(path.read_text())['modules'].values()))
        cls.first, cls.second = 'captured_pair_lut0', 'captured_pair_lut1'

    def test_actual_fixed_pair_has_five_shared_inputs_plus_synthetic_A6(self):
        before = deepcopy(self.module)
        result = audit.audit_pairs(self.module)
        pair = result['pairs'][self.first]
        self.assertEqual(pair['fixed_shared_input_count'], 5)
        self.assertEqual(pair['naive_tag_input_union_count'], 6)
        self.assertTrue(pair['synthetic_A6_VCC_not_a_shared_input'])
        self.assertFalse(result['native_validity_rescan_executed'])
        self.assertEqual(self.module, before)

    def test_actual_corrected_DSP_BRAM_placement_pairs(self):
        path = audit.CHECKPOINT.parent / 'placed.json'
        module = next(iter(json.loads(path.read_text())['modules'].values()))
        result = audit.audit_pairs(module)
        self.assertEqual(result['cells_observed'], 286)
        self.assertGreater(result['logic_pairs_compared'], 0)

    def test_actual_corrected_routed_export_is_read_only_target_not_checkpoint(self):
        path = audit.RESUME.parent / 'routed.json'
        module = next(iter(json.loads(path.read_text())['modules'].values()))
        before = deepcopy(module)
        result = audit.audit_export(module)
        self.assertEqual(result['cells_observed'], 286)
        self.assertFalse(result['full_board_placement_or_route_admitted'])
        self.assertEqual(result['postRoute_metadata_view']['exact_5LUT_A6_VCC_mirrors_omitted_in_comparison'], 98)
        self.assertEqual(module, before)

    def test_original_raw_postroute_rejection_is_preserved(self):
        path = audit.RESUME.parent / 'routed.json'
        module = next(iter(json.loads(path.read_text())['modules'].values()))
        with self.assertRaisesRegex(AssertionError, '5LUT has a connected A6'):
            audit.audit_pairs(module)

    def test_wrong_postroute_mirror_not_silently_omitted(self):
        path = audit.RESUME.parent / 'routed.json'
        module = next(iter(json.loads(path.read_text())['modules'].values()))
        cell = next(cell for cell in module['cells'].values()
                    if cell['attributes']['NEXTPNR_BEL'].endswith('5LUT') and cell['connections'].get('A6'))
        cell['connections']['A6'] = [audit.constant_drivers(module)['GND']]
        with self.assertRaisesRegex(AssertionError, 'VCC mirror'): audit.audit_export(module)

    def test_postroute_logical_A6_not_silently_omitted(self):
        path = audit.RESUME.parent / 'routed.json'
        module = next(iter(json.loads(path.read_text())['modules'].values()))
        cell = next(cell for cell in module['cells'].values()
                    if cell['attributes']['NEXTPNR_BEL'].endswith('5LUT') and cell['connections'].get('A6'))
        cell['attributes']['X_ORIG_PORT_A6'] = 'I0'
        with self.assertRaisesRegex(AssertionError, 'logical mapping'): audit.audit_export(module)

    def test_wrong_A6_mode_tie_rejected(self):
        bad = deepcopy(self.module)
        bad['cells'][self.second]['connections']['A6'] = [audit.constant_drivers(bad)['GND']]
        # Original-logical projection alone does not check this mode tie.
        audit.logical_lut(bad['cells'][self.second])
        with self.assertRaisesRegex(AssertionError, 'VCC mode'): audit.audit_pairs(bad)

    def test_missing_A6_mode_tie_rejected(self):
        bad = deepcopy(self.module)
        bad['cells'][self.second]['connections']['A6'] = []
        with self.assertRaisesRegex(AssertionError, 'VCC mode'): audit.audit_pairs(bad)

    def test_changed_shared_physical_pin_net_rejected(self):
        bad = deepcopy(self.module)
        bad['cells'][self.second]['connections']['A3'] = bad['netnames']['count[4]']['bits']
        with self.assertRaisesRegex(AssertionError, 'same shared physical'): audit.audit_pairs(bad)

    def test_real_logical_A6_mapping_not_treated_as_synthetic(self):
        bad = deepcopy(self.module)
        bad['cells'][self.second]['attributes']['X_ORIG_PORT_A6'] = 'I3'
        with self.assertRaises(AssertionError): audit.audit_pairs(bad)

    def test_connected_A6_on_5LUT_rejected(self):
        bad = deepcopy(self.module)
        bad['cells'][self.first]['connections']['A6'] = [audit.constant_drivers(bad)['VCC']]
        bad['cells'][self.first]['port_directions']['A6'] = 'input'
        with self.assertRaisesRegex(AssertionError, '5LUT has'): audit.audit_pairs(bad)

    def test_duplicate_BEL_rejected(self):
        bad = deepcopy(self.module)
        bad['cells'][self.second]['attributes']['NEXTPNR_BEL'] = bad['cells'][self.first]['attributes']['NEXTPNR_BEL']
        with self.assertRaisesRegex(AssertionError, 'Duplicate'): audit.audit_pairs(bad)

    def test_memory_or_SRL_mode_not_silently_admitted(self):
        bad = deepcopy(self.module)
        bad['cells'][self.first]['attributes']['X_LUT_AS_SRL'] = '1'
        with self.assertRaisesRegex(AssertionError, 'unsupported'): audit.audit_pairs(bad)


if __name__ == '__main__':
    unittest.main()
