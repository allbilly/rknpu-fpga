"""Harness-only controls; synthetic metadata never claims HDL acceptance."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
from test_fixed_rows_mapped import mapped_bench


class MappedRowsControls(unittest.TestCase):
    def setUp(self):
        self.original = (ROOT / 'tests/cmac/tb_cmac_fp16_rows.sv').read_text()

    def test_row_and_tag_case_inequality_unchanged(self):
        generated = mapped_bench(self.original)
        check = self.original.split('    task automatic check_rows;')[1].split('    endtask')[0]
        self.assertIn(check, generated)
        self.assertIn('!==', check)

    def test_operand_corpus_and_coverage_counts_unchanged(self):
        generated = mapped_bench(self.original)
        corpus = self.original.split('        // Sweep every')[1].split('        $display')[0]
        self.assertIn(corpus, generated)
        self.assertIn("32'h3588f016", generated)
        for name in ('randomize_operands', 'configure'):
            task = self.original.split(f'    task automatic {name};')[1].split('    endtask')[0]
            self.assertIn(task, generated)

    def test_input_initialization_after_parameter_initialization(self):
        generated = mapped_bench(self.original)
        self.assertNotIn('logic [15:0] op_a=0,op_b=0;', generated)
        self.assertIn('#1; // Drive after vendor primitive INIT_REG initialization.', generated)
        self.assertLess(generated.index('#1; // Drive'), generated.index('pair_nz=0;op_a=0;op_b=0;exp_sft=0;'))
        self.assertIn('#200; // Preserve default vendor GSR through 100 ns.', generated)
        self.assertIn('fp16_rows_area_top dut(.*);', generated)

    def test_changed_bench_is_rejected(self):
        with self.assertRaises(AssertionError):
            mapped_bench(self.original.replace('    rk_cmac_fp16_rows dut(.*);', '    another_dut dut(.*);'))

    def test_ambiguous_instance_is_rejected(self):
        with self.assertRaises(AssertionError):
            mapped_bench(self.original + '\n    rk_cmac_fp16_rows dut(.*);\n')


if __name__ == '__main__':
    unittest.main()
