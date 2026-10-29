"""Fresh test fixture controls, retaining all original probe controls."""
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_empty_output_checker_probe as old_tests
import fixed_empty_output_fixture as fixed
from probe_imported_empty_lut import BASE, NAME, actual_empty_lut, fixture as old_fixture
from probe_empty_output_checker import compare_route

FAILED = Path(__file__).resolve().parents[2] / 'build/openxc7/empty-output-checker-qualification-1791433199135092252'


class FixedEmptyOutputFixture(old_tests.EmptyOutputProbe):
    def test_only_new_unused_test_cell_gets_explicit_effective_strength(self):
        original = json.loads(BASE.read_text()); before = deepcopy(original)
        old, details = old_fixture(original, actual_empty_lut())
        new, new_details = fixed.fixture(original, actual_empty_lut())
        self.assertEqual(original, before); self.assertEqual(details, new_details)
        old_cell = next(iter(old['modules'].values()))['cells'][NAME]
        new_cell = next(iter(new['modules'].values()))['cells'][NAME]
        self.assertNotIn('BEL_STRENGTH', old_cell['attributes'])
        self.assertEqual(new_cell['attributes']['BEL_STRENGTH'], fixed.USER_STRENGTH)
        del new_cell['attributes']['BEL_STRENGTH']; self.assertEqual(new, old)

    def test_existing_declared_strength_is_not_overwritten(self):
        leaf = actual_empty_lut(); leaf['attributes']['BEL_STRENGTH'] = format(7, '032b')
        with self.assertRaises(AssertionError): fixed.fixture(json.loads(BASE.read_text()), leaf)

    def test_actual_failed_route_is_not_relabelled_or_accepted_by_old_gate(self):
        report = json.loads((FAILED / 'report.json').read_text())
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(report['error'], "AssertionError('Changed resource properties: test_only_declared_empty_XORCY_LUT2')")
        before = next(iter(json.loads((FAILED / 'test-only-50.json').read_text())['modules'].values()))
        after = next(iter(json.loads((FAILED / 'v2_50-routed.json').read_text())['modules'].values()))
        with self.assertRaisesRegex(AssertionError, 'Changed resource properties: ' + NAME): compare_route(before, after)

    def test_diagnostic_default_semantics_preserve_all_fifty_bels_and_logic(self):
        # A comparison-only diagnostic of the saved output, not a new native
        # run/qualification. Fresh corrected execution is still mandatory.
        design, _ = fixed.fixture(json.loads(BASE.read_text()), actual_empty_lut())
        before = next(iter(design['modules'].values()))
        after = next(iter(json.loads((FAILED / 'v2_50-routed.json').read_text())['modules'].values()))
        compared = compare_route(before, after)
        self.assertEqual(compared['footprint']['unchanged_physical_bel_assignments'], 50)
        self.assertEqual(compared['logical_identity']['logical_board']['cells'], 50)
        self.assertEqual(compared['comparison_only_port_annotations']['restored_empty_plain_LUT_outputs'], 0)
