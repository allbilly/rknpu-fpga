"""Qualified census continuation controls; not full numerical acceptance."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'tools/cmac'),
                str(Path(__file__).resolve().parents[2] / 'tools/openxc7')]
import continue_prefix_shared_replay as new
import test_prefix_shared_replay_input_control as previous
import test_lane_dsp_library as library

ExistingDSPReplayGuards = previous.ExistingDSPReplayGuards
SharedReplayInputs = previous.SharedReplayInputs


class QualifiedCounterContinuation(unittest.TestCase):
    def test_actual_failure_metadata_is_not_relabelled_or_running(self):
        report = json.loads(new.FAILED.read_text())
        before = deepcopy(report)
        new.verify_failure(report)
        self.assertEqual(report, before)
        for key, value in (('status', 'RUNNING'), ('status', new.previous.PREPARED), ('finished_utc', None),
                           ('stage', 'compile'), ('error', 'different'), ('parallel_products', 256),
                           ('intended_clock_period_ns', 40), ('full_board_compilation_executed', True),
                           ('numerical_netlist_acceptance', True), ('old_numerical_result_inherited', True)):
            changed = deepcopy(report)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                new.verify_failure(changed)

    def test_derivation_preserves_all_hardware_export_model_and_bench_guards(self):
        restored = new.MAIN_SOURCE
        for old, replacement in reversed(new.REPLACEMENTS):
            self.assertEqual(restored.count(replacement), 1)
            restored = restored.replace(replacement, old)
        self.assertEqual(restored, inspect.getsource(new.previous.main))
        for marker in ('configuration(implementation)', 'verify_bound_bench(', 'exact_export(',
                       'models.freeze_models(', 'negative_golden(', 'validate_export(parent)',
                       'original.verify_carry_report(carry)', 'all(digest(p) == sha', 'physical_counts('):
            self.assertEqual(new.MAIN_SOURCE.count(marker), inspect.getsource(new.previous.main).count(marker))
            self.assertGreater(new.MAIN_SOURCE.count(marker), 0)
        self.assertIn("qualifiers == parent['counter_timing_qualifiers']", new.MAIN_SOURCE)
        self.assertIn("report['counter_view_used_for_export_or_simulation'] = False", new.MAIN_SOURCE)
        self.assertIs(new.NAMESPACE['exact_export'], new.previous.exact_export)
        self.assertIs(new.NAMESPACE['configuration'], new.previous.configuration)


# Retain the original timing qualifier rejection expectations as well.
ExistingTimingControls = library.LaneDspLibraryControls


if __name__ == '__main__':
    unittest.main()
