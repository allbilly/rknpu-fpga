"""Full counter-safe placement handoff guards, not native placement results."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(Path(__file__).parent)]
import place_counter_safe_prefix_shared_board as placement
import test_prefix_shared_place_control as shared
import test_native_heap_board_control as native
from test_native_heap_placement_control import POSITIVE

ExistingSharedAdmission = shared.SharedPlacementAdmission
ExistingSharedPlacementChecks = shared.SharedPlacementChecks
ExistingNativeHeAPGuards = native.Controls


class CounterSafeFullPlacementControls(unittest.TestCase):
    def log(self):
        return ('Info: Checksum: 0x0f489b2b\n' + POSITIVE +
                'Info: Running main analytical placer, max placement attempts per cell = 2147483646.\n')

    def test_only_reversible_engine_selection_and_extra_actual_log_checks(self):
        text = placement.MAIN_SOURCE
        for old, new in reversed(placement.REPLACEMENTS):
            self.assertEqual(text.count(new), 1)
            text = text.replace(new, old)
        import inspect
        self.assertEqual(text, inspect.getsource(placement.previous.main))
        for key in ('validate_pack', 'compare_placement', 'verify_full_argv', 'verify_corrected_packed',
                    'packed_names', 'verify_clock_admission'):
            self.assertIs(placement.NAMESPACE[key], getattr(placement.previous, key))
        self.assertEqual(placement.NATIVE_TIMEOUT, 43200)

    def test_exact_native_finite_limit_and_actual_saved_pack_checksum(self):
        result = placement.full_log_checks(self.log())
        self.assertEqual(result['actual_full_packed_cells'], 523410)
        self.assertEqual(result['actual_logged_maximum_attempts_per_cell'], 2147483646)
        self.assertFalse(result['physical_fit_verified'])
        placement.check_heap_log(0, self.log())

    def test_wrong_zero_old_limit_duplicate_or_missing_log_rejected(self):
        text = self.log()
        line = 'Info: Running main analytical placer, max placement attempts per cell = 2147483646.\n'
        for bad in (text.replace('2147483646', '10000'), text.replace('2147483646', '0'),
                    text.replace('2147483646', '2147483647'), text + line, text.replace(line, ''),
                    text.replace('0x0f489b2b', '0x0f489b2a'), text.replace('Info: Checksum: 0x0f489b2b\n', ''),
                    text + 'Creating initial analytic placement for 47 cells\n'):
            with self.subTest(log=bad[-120:]), self.assertRaises(AssertionError):
                placement.full_log_checks(bad)

    def test_original_normal_refinement_warnings_and_error_gates_still_apply(self):
        text = self.log()
        for marker in ('HeAP Placer Time:', 'Running simulated annealing placer for refinement.',
                       'Running post-placement legalisation...', 'Program finished normally.'):
            with self.subTest(marker=marker), self.assertRaises(AssertionError):
                placement.check_heap_log(0, text.replace(marker, ''))
        for code, bad in ((125, text), (0, text + 'WARNING: waived\n'), (0, text + 'ERROR: different failure\n')):
            with self.assertRaises(AssertionError):
                placement.check_heap_log(code, bad)

    def test_missing_new_qualification_rejected_without_execution(self):
        self.assertLess(placement.MAIN_SOURCE.index('admit_qualification(qp)'), placement.MAIN_SOURCE.index('out.mkdir'))
        for report in ({'status': 'RUNNING'}, {'status': 'FAIL'}, {'status': placement.previous.PACKED}):
            with self.assertRaises((AssertionError, KeyError)):
                placement.qualification.verify_metadata(report)
        self.assertNotIn('--placer-heap-cell-placement-timeout', placement.MAIN_SOURCE)
        self.assertNotIn('--timing-allow-fail', placement.MAIN_SOURCE)


if __name__ == '__main__':
    unittest.main()
