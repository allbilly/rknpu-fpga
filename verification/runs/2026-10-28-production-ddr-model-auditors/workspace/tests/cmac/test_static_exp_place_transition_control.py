"""Exact source-transition controls; not native placement or physical signoff."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from place_prefix_board import precision_source_transition, placement_argv

ORIGINAL = 'a = std::exp(emin);\nb = std::exp(emax);\nNPNR_ASSERT(std::isfinite(b));\ncoefficient = 0.5f;\n'
CHANGED = ORIGINAL.replace('std::exp(emin)', 'std::exp(static_cast<double>(emin))').replace(
    'std::exp(emax)', 'std::exp(static_cast<double>(emax))')


class StaticExpPlaceTransitionControl(unittest.TestCase):
    def test_only_two_overload_selections_accepted(self):
        precision_source_transition(ORIGINAL, CHANGED)

    def test_original_or_partial_fix_and_any_extra_edit_rejected(self):
        for text in (ORIGINAL, ORIGINAL.replace('std::exp(emin)', 'std::exp(static_cast<double>(emin))'),
                     CHANGED.replace('NPNR_ASSERT', 'assert_removed'), CHANGED.replace('0.5f', '0.25f'),
                     CHANGED + '\nadditional edit'):
            with self.subTest(text=text), self.assertRaises(AssertionError): precision_source_transition(ORIGINAL, text)

    def test_missing_or_duplicate_original_call_rejected(self):
        for text in (ORIGINAL.replace('std::exp(emin)', 'unknown'), ORIGINAL + 'std::exp(emin)'):
            with self.assertRaises(AssertionError): precision_source_transition(text, CHANGED)

    def test_full_retry_keeps_original_input_geometry_clock_and_no_waivers(self):
        argv = placement_argv('precision-qualified', 'full-original-input', 'literal.xdc', 'placed')
        for key, value in (('--device', 'xc7k480tffg1156-2'), ('--json', 'full-original-input'),
                           ('--freq', '50'), ('--seed', '3588'), ('--placer', 'static')):
            self.assertEqual(argv[argv.index(key) + 1], value)
        for key in ('--Werror', '--no-route'): self.assertIn(key, argv)
        for key in ('--force', '--timing-allow-fail', '--no-pack', '--no-place', '--fasm',
                    '--placer-static-refine-max-iterations'): self.assertNotIn(key, argv)


if __name__ == '__main__': unittest.main()
