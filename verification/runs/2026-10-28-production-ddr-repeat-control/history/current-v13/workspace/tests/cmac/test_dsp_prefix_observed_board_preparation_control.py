"""Original observation retention script controls; no HDL/FPGA acceptance."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/cmac')]
import prepare_dsp_prefix_observed_board as prepare


class PrefixObservationRetentionControl(unittest.TestCase):
    def original(self):
        import json
        report = json.loads((ROOT / prepare.admission.ram.PARENT).read_text())
        source = (ROOT / prepare.admission.ram.PARENT).parent / 'mapping.ys'
        return source.read_text(), report['preserved_kernel']

    def test_literal_original_full_import_and_geometry_retained(self):
        text, kernel = self.original()
        result = prepare.retention_script(text, ROOT / 'build/control-not-executed.json', kernel)
        marker = f'synth_xilinx {prepare.admission.ram.FLAGS} -run begin:coarse;\n'
        self.assertTrue(result.startswith(text.split(marker)[0]))
        self.assertIn('select -assert-count 16 ', result)
        self.assertIn('select -assert-mod-count 2 %;', result)

    def test_all_original_observation_and_force_names_kept_before_optimization(self):
        text, kernel = self.original()
        result = prepare.retention_script(text, ROOT / 'build/control-not-executed.json', kernel)
        for name in prepare.WIDTHS:
            self.assertIn('setattr -set keep 1 ypcb_cmac_array_top/w:' + name + ';', result)
        self.assertLess(result.index('proc;\nflatten;'), result.index('setattr -set keep 1 '))
        self.assertLess(result.rindex('setattr -set keep 1 '), result.index('opt_expr -keepdc'))

    def test_original_four_bit_state_not_recoded_and_check_not_disabled(self):
        text, kernel = self.original()
        result = prepare.retention_script(text, ROOT / 'build/control-not-executed.json', kernel)
        self.assertIn('setattr -set fsm_encoding "none" ypcb_cmac_array_top/w:demo.state;', result)
        self.assertIn('check -assert;', result)
        self.assertIn('write_json -selected ', result)
        self.assertNotIn('setundef', result)

    def test_missing_repeated_or_reduced_mapping_boundary_rejected(self):
        text, kernel = self.original()
        marker = f'synth_xilinx {prepare.admission.ram.FLAGS} -run begin:coarse;\n'
        for bad in (text.replace(marker, ''), text + marker, text.replace('select -assert-count 16 ', 'select -assert-count 1 ')):
            with self.assertRaises(AssertionError):
                prepare.retention_script(bad, ROOT / 'build/control-not-executed.json', kernel)


if __name__ == '__main__':
    unittest.main()
