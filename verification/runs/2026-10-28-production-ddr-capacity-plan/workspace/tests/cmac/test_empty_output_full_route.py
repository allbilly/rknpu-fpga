"""Prepared v2 full-route controls, including all fifteen original controls."""
import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_strict_search_route as old_tests
import route_empty_output_board as new
from verify_empty_output_evidence import verify_metadata
from test_empty_output_evidence import metadata_fixture

# Include every original export control without changing its error expectations.
FullImportedExport = old_tests.FullImportedExport


class EmptyOutputFullRoute(old_tests.StrictSearchRoute):
    def test_source_changes_are_exact_reversible_and_do_not_modify_old_module(self):
        old = inspect.getsource(new.original.main); restored = new.MAIN_SOURCE
        for original, modified in reversed(new.REPLACEMENTS):
            restored = restored.replace(modified, original)
        self.assertEqual(restored, old)
        self.assertEqual(new.original.CONTROL.name, 'test_strict_search_route.py')
        self.assertNotEqual(new.original.SMALL, new.QUALIFIED)
        self.assertEqual(new.original.verify_small_evidence.__module__, 'route_strict_search_board')
        with self.assertRaises(AssertionError): new.prepared_main_source(old + '\n')

    def test_native_v2_import_count_is_exact_ordered_and_not_small_or_duplicated(self):
        marker = 'Info: RKNPU empty-output import: preserved 24 literal disconnected LUT outputs; connected graph unchanged.\n'
        text = marker + old_tests.NATIVE_GOOD
        new.check_import_count(text, 24)
        for bad in (old_tests.NATIVE_GOOD, text.replace('preserved 24', 'preserved 1'),
                    text + marker, old_tests.NATIVE_GOOD + '\n' + marker):
            with self.assertRaises(AssertionError): new.check_import_count(bad, 24)
        with self.assertRaises(AssertionError): new.check_import_count(text, True)

    def test_v2_qualification_is_mandatory_and_running_or_old_profile_is_not_qualified(self):
        fixture = metadata_fixture(); verify_metadata(fixture)  # Software shape only.
        fixture['status'] = 'RUNNING'
        with self.assertRaises(AssertionError): verify_metadata(fixture)
        self.assertIn('support, built = verify_small_evidence(before)', new.MAIN_SOURCE)
        self.assertIn('verify_placed_metadata(placed)', new.MAIN_SOURCE)
        self.assertIn('verify_full_features(', new.MAIN_SOURCE)

    def test_execution_stays_literal_v2_checkpoint_with_original_full_target_and_gates(self):
        self.assertEqual(new.MAIN_SOURCE.count(new.NEW_PROFILE), 1)
        self.assertNotIn(new.OLD_PROFILE, new.MAIN_SOURCE)
        self.assertIn('resume_argv(executable, design_path,', new.MAIN_SOURCE)
        self.assertIn("run('native_scan_and_route', argv, 43200)", new.MAIN_SOURCE)
        self.assertIn('original_logical_circuit_identity', new.MAIN_SOURCE)
        self.assertIn('full_DSP_BRAM_source_defined_features_compared=True', new.MAIN_SOURCE)
        self.assertIn('prepared_main_source_sha256', new.MAIN_SOURCE)
        self.assertNotEqual(new.ROUTED, new.original.ROUTED)
