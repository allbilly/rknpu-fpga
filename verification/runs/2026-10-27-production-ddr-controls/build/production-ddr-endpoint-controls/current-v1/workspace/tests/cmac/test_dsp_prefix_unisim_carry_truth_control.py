"""Result/scope controls; actual complete vendor truth-table run is separate."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/cmac')]
import check_dsp_prefix_unisim_carry_truth as control


class PrefixVendorCarryTruthControl(unittest.TestCase):
    def positive(self, differences='9', first='3'):
        return ('PASS pinned UNISIM CARRY truth binary=1024 four_state=1048576 '
                f'yosys_four_state_differences={differences} first_difference={first}; '
                'not Yosys four-state equivalence or FPGA acceptance\n')

    def test_full_corpus_and_explicit_non_equivalence_required(self):
        result = control.validate_result(self.positive(), 0)
        self.assertFalse(result['four_state_yosys_vendor_equivalence'])
        self.assertTrue(result['binary_yosys_vendor_equivalence'])
        for text in (self.positive().replace('1048576', '1'), self.positive('0'),
                     self.positive('1048577'), self.positive(first='1048576'),
                     self.positive().replace('not Yosys four-state equivalence', 'Yosys equivalence'),
                     self.positive() + self.positive()):
            with self.assertRaises(AssertionError):
                control.validate_result(text, 0)

    def test_exact_known_wrong_golden_negative(self):
        control.validate_result('FATAL: vendor CARRY mismatch case=0 got=0/0 expected=1/0\n', 1, True)
        for text, code in (('FATAL: vendor CARRY mismatch case=0 got=x/x expected=1/0', 1),
                           ('FATAL: other failure', 1), (self.positive(), 0),
                           ('FATAL: vendor CARRY mismatch case=0 got=0/0 expected=1/0', 0)):
            with self.assertRaises(AssertionError):
                control.validate_result(text, code, True)

    def test_diagnostics_do_not_establish_pass(self):
        for prefix in ('DRC warning : model issue\n', 'error: issue\n', 'FATAL: issue\n'):
            with self.assertRaises(AssertionError):
                control.validate_result(prefix + self.positive(), 0)

    def test_original_primitive_oracle_unchanged(self):
        original = (ROOT / 'tests/cmac/tb_dsp_prefix_primitive_model_control.sv').read_text()
        self.assertIn('carry = merge_mux(s[bit_index], carry, di[bit_index]);', original)
        self.assertIn('carry_four_state != 1048576', original)
        vendor = control.BENCH.read_text()
        self.assertIn("ci === 1'bz ? 1'b0 : ci", vendor)
        self.assertIn('Binary Yosys/vendor carry disagreement', vendor)
        self.assertIn('first_difference = four_count', vendor)


if __name__ == '__main__':
    unittest.main()
