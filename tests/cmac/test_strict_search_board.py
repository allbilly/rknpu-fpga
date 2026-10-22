"""Full-target admission controls; no native execution or placed-fit claim."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from place_strict_search_board import FAILED, NATIVE_TIMEOUT, verify_previous_failure, verify_full_argv
from place_prefix_board import placement_argv


class StrictSearchBoard(unittest.TestCase):
    def test_actual_previous_attempt_is_terminal_failure_not_placed_fit(self):
        previous = json.loads(FAILED.read_text()); verify_previous_failure(previous)
        self.assertFalse((FAILED.parent / 'placed.json').exists())
        self.assertEqual(NATIVE_TIMEOUT, 43200)

    def test_completed_or_unrelated_failure_or_target_cannot_be_relabelled(self):
        previous = json.loads(FAILED.read_text())
        for key, value in [('status', 'RUNNING'), ('status', 'PLACED'), ('stage', 'admission'),
                ('parallel_products', 32), ('intended_clock_period_ns', 40), ('error', 'other failure')]:
            r = deepcopy(previous); r[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): verify_previous_failure(r)
        for key, value in [('returncode', 0), ('status', 'PASS_TOOL_EXECUTION_ONLY'), ('timeout_seconds', 43200), ('seconds', 1)]:
            r = deepcopy(previous); r['commands'][-1][key] = value
            with self.assertRaises(AssertionError): verify_previous_failure(r)

    def test_full_argv_keeps_actual_repacking_target_50MHz_seed_and_validity(self):
        argv = placement_argv('isolated', 'original-prepared-input', 'literal.xdc', 'placed.json'); verify_full_argv(argv)
        self.assertEqual(argv[argv.index('--json') + 1], 'original-prepared-input')
        for option in ('--no-pack', '--no-place', '--force', '--timing-allow-fail', '--placer-static-refine-max-iterations'):
            with self.subTest(option=option), self.assertRaises(AssertionError): verify_full_argv(argv + [option])
        for option, value in [('--device', 'xc7k480tffg1156-1'), ('--freq', '25'), ('--seed', '1'), ('--placer', 'heap')]:
            broken = list(argv); broken[broken.index(option) + 1] = value
            with self.assertRaises(AssertionError): verify_full_argv(broken)
        for option in ('--Werror', '--no-route'):
            with self.assertRaises(AssertionError): verify_full_argv([v for v in argv if v != option])


if __name__ == '__main__': unittest.main()
