"""Cofactor HDL harness admission and marker controls; no real model claim."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import test_cofactor_lut_functions as runner


class CofactorFunctionControls(unittest.TestCase):
    def classes(self):
        _, classes, _ = runner.proposals(runner.fixture(), set())
        return list(classes.values())

    def test_all_six_live_pins_and_every_four_state_pattern_are_checked(self):
        classes = self.classes(); text = runner.four_state_bench(classes)
        self.assertIn('pattern<4096', text); self.assertIn('comparisons!=8192', text)
        self.assertIn("reg [5:0] c0_inputs=6'bx", text)
        self.assertIn('.I5(c0_inputs[5])', text); self.assertNotIn(".I5(1'b1)", text)
        self.assertIn(' !== ', text); self.assertIn("1'bz", text); self.assertIn("1'bx", text)
        self.assertNotEqual(text, runner.four_state_bench(classes, True))

    def test_false_binary_cofactor_wrong_selector_and_unknown_tables_rejected(self):
        for mutation in ('init', 'first_pin', 'second_pin', 'fanins', 'mode', 'extra', 'unknown'):
            function = deepcopy(self.classes()[0])
            if mutation == 'init': function['init'] = '0' * 64
            elif mutation == 'first_pin': function['first']['pins'][0] = 5
            elif mutation == 'second_pin': function['second']['pins'][0] = 1
            elif mutation == 'fanins': function['fanins'] = 5
            elif mutation == 'mode': function['mode'] = 'constant_i5'
            elif mutation == 'extra': function['extra'] = True
            else: function['second']['init'] = 'x' * 64
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError): runner.validate_function(function)

    def test_empty_duplicate_or_wrong_class_domain_rejected(self):
        with self.assertRaises(AssertionError): runner.four_state_bench([])
        classes = self.classes()
        with self.assertRaises(AssertionError): runner.four_state_bench(classes + classes)

    def test_real_negative_marker_and_exact_assertion_exit_required(self):
        runner.validate_result('FATAL: LUT_COFACTOR_MISMATCH class=0 pattern=0\n', 1, 1, True)
        for text, code in [('LUT_COFACTOR_MISMATCH class=0 pattern=1', 1),
                ('LUT_COFACTOR_MISMATCH class=1 pattern=0', 1),
                ('LUT_COFACTOR_MISMATCH class=0 pattern=0', 2), ('compiler crash', 1),
                ('LUT_COFACTOR_MISMATCH class=0 pattern=0\nPASS other', 1)]:
            with self.subTest(text=text, code=code), self.assertRaises(AssertionError):
                runner.validate_result(text, code, 1, True)

    def test_positive_exact_count_no_warning_and_zero_exit_required(self):
        marker = 'PASS LUT_COFACTOR_FOUR_STATE classes=1 comparisons=8192'
        self.assertEqual(runner.validate_result(marker, 0, 1), marker)
        for text, code in [(marker, 1), (marker.replace('8192', '4096'), 0),
                (marker + '\n' + marker, 0), (marker + '\nwarning: vendor', 0),
                (marker + '\nFATAL: mismatch', 0)]:
            with self.subTest(text=text, code=code), self.assertRaises(AssertionError): runner.validate_result(text, code, 1)


if __name__ == '__main__': unittest.main()
