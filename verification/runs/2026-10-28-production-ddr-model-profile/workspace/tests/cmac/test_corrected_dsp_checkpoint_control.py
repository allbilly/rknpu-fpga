"""Strict argv and annotation controls, not new native placement evidence."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import probe_corrected_dsp_checkpoint as probe


class CorrectedDSPCheckpointControl(unittest.TestCase):
    def test_normal_full_scope_clock_and_placer_argv(self):
        argv = probe.native_placement_argv('/engine', '/literal-input', '/literal.xdc', '/placed.json')
        for flag, value in (('--device', 'xc7k480tffg1156-2'), ('--freq', '50'), ('--seed', '3588'), ('--placer', 'static')):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertIn('--Werror', argv)
        self.assertIn('--no-route', argv)
        for forbidden in ('--no-pack', '--force', '--timing-allow-fail'):
            self.assertNotIn(forbidden, argv)

    def test_reload_keeps_real_checkpoint_and_skips_repacking(self):
        argv = probe.resume_argv('/engine', '/placed.json', 'top', '/literal.xdc', '/reloaded.json')
        self.assertEqual(argv[argv.index('--json') + 1], '/placed.json')
        for required in ('--no-pack', '--no-place', '--no-route', '--Werror'):
            self.assertIn(required, argv)

    def test_route_keeps_physical_checkpoints_and_normal_router(self):
        argv = probe.resume_argv('/engine', '/placed.json', 'top', '/literal.xdc', '/routed.json', route=True)
        self.assertEqual(argv[argv.index('--router') + 1], 'router2')
        self.assertIn('--no-place', argv)
        self.assertNotIn('--no-route', argv)
        self.assertNotIn('--timing-allow-fail', argv)

    def test_wrong_duplicate_bel_failure_rejected(self):
        with self.assertRaises(AssertionError): probe.duplicate_bel_rejection(1, 'ordinary error')


if __name__ == '__main__':
    unittest.main()
