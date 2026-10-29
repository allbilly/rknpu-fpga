"""Literal DSP-array substitution controls, not HDL/area/FPGA acceptance."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import dsp_array_contract as runner


class DspArrayContractControls(unittest.TestCase):
    def test_current_candidates_have_only_exact_declared_leaf_substitution(self):
        runner.validate_sources()

    def test_array_reset_tags_warmup_and_error_logic_are_unchanged(self):
        original = runner.FIXED_ARRAY.read_text(); candidate = runner.expected_array(original)
        restored = candidate.removeprefix(runner.PREFIX).replace('rk_cmac_fp16_array_dsp #',
            'rk_cmac_fp16_array_fixed #').replace('rk_cmac_fp16_cell_dsp #', 'rk_cmac_fp16_cell_fixed #')
        self.assertEqual(restored, original)
        for text in ('configured<=1;', 'out_groups<=groups;out_tag<=in_tag;',
                'error<=1;out_valid<=0;', "===1'bx) legal=0;", 'for(genvar k=0;k<ATOMIC_K;k=k+1)'):
            self.assertIn(text, candidate)

    def test_mask_mantissa_exponent_nan_priority_and_fp44_layout_are_retained(self):
        candidate = runner.expected_cell(runner.FIXED_CELL.read_text())
        for text in ('data_mask[i]&&weight_mask[i]', 'maximum-exponent[i]',
                '.op_a({b[i][15],bm}),.op_b({a[i][15],am})', 'sum=sum+{{6{lane_sum[31]}},lane_sum};',
                "{6'h3f,nan_payload,27'd0}:{maximum,2'b0,sum}", 'default:invalid=1;'):
            self.assertIn(text, candidate)
        self.assertLess(candidate.index('!nan_found&&weight_mask'), candidate.index('!nan_found&&data_mask'))
        self.assertNotIn('lane_sum=row_a[i]+row_b[i]+compensation;', candidate)

    def test_changed_original_compensation_domain_or_interface_is_not_silently_transformed(self):
        original = runner.FIXED_CELL.read_text()
        for before, after in [("8'hf0:compensation", "8'hf1:compensation"),
                ('row_b[ATOMIC_C]', 'rows[ATOMIC_C]'), ('rk_cmac_fp16_rows donor(', 'different donor(')]:
            with self.subTest(before=before), self.assertRaises(AssertionError):
                runner.expected_cell(original.replace(before, after))

    def test_bench_assertions_and_input_faults_are_preserved_literally(self):
        original = runner.BENCH.read_text(); changed = runner.array_bench(original)
        self.assertEqual(changed.replace('rk_cmac_fp16_array_dsp #', 'rk_cmac_fp16_array #'), original)
        self.assertEqual(changed.count('$fatal'), original.count('$fatal'))
        with self.assertRaises(AssertionError): runner.array_bench(changed)


if __name__ == '__main__': unittest.main()
