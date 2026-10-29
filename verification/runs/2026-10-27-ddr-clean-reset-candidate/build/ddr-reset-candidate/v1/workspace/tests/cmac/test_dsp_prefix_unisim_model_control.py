"""Pinned-source/startup/result controls only; actual model run is separate."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/cmac')]
import check_dsp_prefix_unisim_models as control


class PrefixUnisimModelControl(unittest.TestCase):
    def test_only_global_startup_and_operand_settling_changes_bench(self):
        original = control.primitive.BENCH.read_text()
        adapted = control.startup_bench(original)
        self.assertEqual(adapted.replace(control.STARTUP, '', 1), original)
        self.assertEqual(adapted.count(control.STARTUP), 1)
        for marker in ('4259904', '1048576', '35883216', 'NEG_DSP', 'NEG_CARRY'):
            self.assertEqual(adapted.count(marker), original.count(marker))

    def test_missing_or_repeated_startup_boundary_rejected(self):
        original = control.primitive.BENCH.read_text()
        for text in (original + original, original.replace('edge_a[0]=0;', 'edge_a[0]=1;')):
            with self.assertRaises(AssertionError):
                control.startup_bench(text)

    def test_pinned_actual_vendor_sources(self):
        paths = control.model_sources()
        self.assertEqual({path.name for path in paths}, {'LICENSE', 'glbl.v', 'DSP48E1.v', 'CARRY4.v'})

    def test_complete_marker_and_real_negative_required(self):
        positive = control.primitive.expected('iverilog') + '\n'
        control.validate_result(positive, 0)
        control.validate_result('FATAL: primitive DSP mismatch case=0 got=000055550000 expected=000055550001\n', 1, 'DSP')
        control.validate_result('FATAL: primitive CARRY mismatch case=0 got=0/0 expected=1/0\n', 1, 'CARRY')
        for text, code, kind in ((positive, 0, 'DSP'), (positive.replace('4259904', '4'), 0, None),
                                  ('FATAL: other failure\n', 1, 'DSP')):
            with self.assertRaises(AssertionError):
                control.validate_result(text, code, kind)

    def test_unknown_or_wrong_actual_negative_is_rejected(self):
        for text, kind in (('primitive DSP mismatch case=0 got=xxxxxxxxxxxx expected=000055550001', 'DSP'),
                           ('primitive DSP mismatch case=0 got=000055550002 expected=000055550001', 'DSP'),
                           ('primitive CARRY mismatch case=0 got=x/x expected=1/0', 'CARRY')):
            with self.assertRaises(AssertionError):
                control.validate_result('FATAL: ' + text + '\n', 1, kind)

    def test_startup_transition_precedes_unchanged_first_zero_vector(self):
        adapted = control.startup_bench(control.primitive.BENCH.read_text())
        self.assertIn("a = 30'b1; b = 18'b1;\n        #1;\n        edge_a[0]=0;", adapted)
        self.assertLess(adapted.index(control.STARTUP), adapted.index('for (i=0; i<8;'))

    def test_vendor_drc_warning_not_hidden_by_whitespace(self):
        positive = control.primitive.expected('iverilog') + '\n'
        with self.assertRaises(AssertionError):
            control.validate_result('DRC warning : illegal OPMODE\n' + positive, 0)


if __name__ == '__main__':
    unittest.main()
