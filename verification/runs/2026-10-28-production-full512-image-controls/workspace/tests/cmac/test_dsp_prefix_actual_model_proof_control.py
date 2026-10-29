"""Proof source/result guards, not full-array numerical or physical acceptance."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import prove_dsp_prefix_actual_model as proof


class ActualModelProofControls(unittest.TestCase):
    def test_exact_unconstrained_model_and_mathematical_golden_source(self):
        text = proof.MITER.read_text()
        proof.validate_miter(text)
        for before, after in (('A[24:0]', 'A[23:0]'), ('$signed(B)', '$unsigned(B)'),
            ("48'h000055550000", "48'h000055550001"),
            ('actual == expected', 'actual == actual'), ('actual_model(', 'other_model(')):
            with self.subTest(before=before), self.assertRaises(AssertionError):
                proof.validate_miter(text.replace(before, after))
        with self.assertRaises(AssertionError):
            proof.validate_miter(text + '\ninitial assume(A == 0);\n')

    def test_positive_requires_one_actual_success_and_zero_exit(self):
        proof.validate_result(proof.SUCCESS, 0)
        for text, code in ((proof.SUCCESS, 1), ('', 0), (proof.SUCCESS * 2, 0),
            (proof.SUCCESS + '\nERROR: unrelated', 0), (proof.FAILURE, 0)):
            with self.subTest(text=text, code=code), self.assertRaises(AssertionError):
                proof.validate_result(text, code)

    def test_negative_requires_actual_counterexample_and_exact_verify_failure(self):
        text = proof.FAILURE + '\nERROR: Called with -verify and proof did fail!'
        proof.validate_result(text, 1, True)
        for bad, code in ((text, 0), (proof.FAILURE, 1), ('ERROR: missing model', 1),
            (text + '\nERROR: unrelated', 1), (text + '\n' + proof.SUCCESS, 1)):
            with self.subTest(text=bad, code=code), self.assertRaises(AssertionError):
                proof.validate_result(bad, code, True)

    def test_warnings_timeout_or_unknown_cell_never_establish_proof(self):
        for suffix in ('\nWarning: unknown model', '\nwarning: unrelated',
            '\ntimed out', '\ntimeout reached', '\nunknown cell DSP48E1'):
            with self.subTest(suffix=suffix), self.assertRaises(AssertionError):
                proof.validate_result(proof.SUCCESS + suffix, 0)


if __name__ == '__main__':
    unittest.main()
