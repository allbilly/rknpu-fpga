"""Separate read-only v2 audits; old guards and native inputs stay untouched."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import audit_empty_output_pairs as new
from probe_imported_empty_lut import BASE, NAME, fixture, actual_empty_lut
from probe_empty_output_checker import NEW_REASONS, new_corruption
from route_strict_search_board import checker


class EmptyOutputPairAudit(unittest.TestCase):
    def test_exact_source_replacements_preserve_all_other_guards(self):
        self.assertEqual(new.PAIR_SOURCE.replace(new.DECLARATIONS, '').replace(new.NEW_LOWER, new.LOWER).replace(new.NEW_UPPER, new.UPPER),
                         inspect.getsource(new.old_pairs.audit_pairs))
        self.assertEqual(new.ROLE_SOURCE.replace(new.DECLARATIONS, '').replace(new.NEW_ROLE, new.ROLE), inspect.getsource(new.old_roles.local_carry_roles))
        with self.assertRaises(AssertionError): new.source_shaped('different', ((new.LOWER, new.NEW_LOWER),))

    def test_saved_49_and_286_results_equal_original_audits_without_mutation(self):
        for path in (BASE, checker.TRANSFER.parent / 'corrected-transfer-input.json'):
            module = next(iter(json.loads(path.read_text())['modules'].values())); before = deepcopy(module)
            self.assertEqual(new.audit_pairs(module), new.old_pairs.audit_pairs(module))
            self.assertEqual(new.local_carry_roles(module), new.old_roles.local_carry_roles(module))
            self.assertEqual(module, before)

    def test_test_only_50_declared_empty_pair_has_ten_pairs_and_original_eight_roles(self):
        design, _ = fixture(json.loads(BASE.read_text()), actual_empty_lut()); module = next(iter(design['modules'].values()))
        before = deepcopy(module); result = new.audit_pairs(module)
        self.assertEqual((result['cells_observed'], result['logic_pairs_compared']), (50, 10))
        self.assertFalse(result['circuit_or_tags_modified']); self.assertFalse(result['native_validity_rescan_executed'])
        self.assertEqual(len(new.local_carry_roles(module)), 8); self.assertEqual(module, before)
        with self.assertRaisesRegex(AssertionError, 'Changed 5LUT output role'): new.old_pairs.audit_pairs(module)
        with self.assertRaises(AssertionError): new.old_roles.local_carry_roles(module)

    def test_all_eight_new_literal_and_input_mapping_corruptions_remain_errors(self):
        design, _ = fixture(json.loads(BASE.read_text()), actual_empty_lut())
        for kind in NEW_REASONS:
            with self.subTest(kind=kind):
                bad = next(iter(new_corruption(design, kind)['modules'].values()))
                with self.assertRaises(AssertionError): new.audit_pairs(bad)
                with self.assertRaises(AssertionError): new.local_carry_roles(bad)

    def test_wrong_shared_pin_or_A6_mode_still_fails(self):
        design, details = fixture(json.loads(BASE.read_text()), actual_empty_lut())
        for mode in ('mode', 'shared', 'logical_mode'):
            bad = deepcopy(next(iter(design['modules'].values())))
            upper, lower = bad['cells'][details['upper_cell']], bad['cells'][NAME]
            if mode == 'mode': upper['connections']['A6'] = list(lower['connections']['A1'])
            elif mode == 'logical_mode': upper['attributes']['X_ORIG_PORT_A6'] = 'I1'
            else: upper['connections']['A1'] = list(bad['cells']['captured_pair_lut0']['connections']['A2'])
            with self.assertRaises(AssertionError): new.audit_pairs(bad)


if __name__ == '__main__': unittest.main()
