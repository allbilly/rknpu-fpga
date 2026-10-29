"""New v2 harness controls; actual qualification requires fresh native runs."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from probe_empty_output_checker import NEW_REASONS, new_corruption, reject_log, compare_route
from probe_imported_empty_lut import BASE, fixture, actual_empty_lut, NAME
from empty_output_candidate import literal_outputs
from route_strict_search_board import SMALL, small
from audit_postplace_lut_pairs import audit_pairs


class EmptyOutputProbe(unittest.TestCase):
    def test_all_new_corruptions_change_only_test_copies_and_remain_invalid(self):
        design, _ = fixture(json.loads(BASE.read_text()), actual_empty_lut()); before = deepcopy(design)
        for kind in NEW_REASONS:
            bad = new_corruption(design, kind); self.assertNotEqual(bad, design); self.assertEqual(design, before)
            cells = next(iter(bad['modules'].values()))['cells']
            if kind not in ('missing_connected_output', 'incomplete_empty_input_mapping'):
                with self.assertRaises(AssertionError): literal_outputs(cells[NAME])
        with self.assertRaises(AssertionError): new_corruption(design, 'not_modeled')

    def test_no_wrong_code_error_warning_or_route_is_an_expected_rejection(self):
        reason = NEW_REASONS['unknown_empty_output']; text = 'ERROR: ' + reason
        reject_log(125, text, reason)
        for code, log in ((0, text), (-6, text), (125, 'ERROR: different'),
                          (125, text + '\nInfo: Routing complete.'), (125, text + '\nWARNING: ignored')):
            with self.assertRaises(AssertionError): reject_log(code, log, reason)

    def test_saved_small_native_routes_keep_exact_original_comparison_proofs(self):
        report = json.loads(SMALL.read_text())
        before49 = next(iter(json.loads(BASE.read_text())['modules'].values()))
        after49 = next(iter(json.loads((small.PARENT.parent / 'fixed_49-routed.json').read_text())['modules'].values()))
        new = compare_route(before49, after49)
        old = report['saved_native_49_comparison']
        self.assertEqual(new['footprint'], old['footprint']); self.assertEqual(new['logical_identity'], old['logical_identity'])

    def test_old_pair_audit_still_rejects_disconnected_fifty_cell_fixture(self):
        design, _ = fixture(json.loads(BASE.read_text()), actual_empty_lut())
        with self.assertRaisesRegex(AssertionError, 'Changed 5LUT output role'):
            audit_pairs(next(iter(design['modules'].values())))


if __name__ == '__main__': unittest.main()
