"""Processed-frontend mapping contracts only; not numerical/physical acceptance."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/cmac')]
import map_dsp_prefix_observed_board as mapping


class PrefixObservedMappingControl(unittest.TestCase):
    def prepared(self):
        return json.loads((ROOT / mapping.PARENT).read_text())

    def text(self):
        kernel = self.prepared()['preserved_kernel']
        return ('Executing XILINX_DSP pass\n' +
                f"1. Extracting gate netlist of module `{kernel}' to control.blif\n" +
                'Extracted 0 gates and 0 wires to a netlist network with 0 inputs and 0 outputs.\n' +
                "Don't call ABC as there is nothing to map.\n" +
                "2. Extracting gate netlist of module `\\ypcb_cmac_array_top' to control.blif\n" +
                'Extracted 10 gates and 20 wires to a netlist network with 3 inputs and 4 outputs.\n' +
                mapping.mapper.array.ABC_CONTEXT + '\nABC: YOSYS_ABC_DONE \nRe-integrating ABC results.\n' +
                'Found and reported 0 problems.\n' * 4)

    def test_actual_completed_full_profile_required(self):
        report = self.prepared()
        mapping.verify_prepared_metadata(report)
        for field, value in (('status', 'RUNNING'), ('parallel_products', 32),
                              ('original_four_bit_state_preserved', False), ('bitstream_emitted', True)):
            bad = deepcopy(report)
            bad[field] = value
            with self.assertRaises(AssertionError):
                mapping.verify_prepared_metadata(bad)

    def test_both_actual_help_contracts_required(self):
        self.assertEqual(mapping.HELP_COMMAND, 'help flatten; help synth_xilinx')
        original = ROOT / mapping.ram.PARENT
        text = (original.parent / 'help.log').read_text()
        expected = [line.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for line in mapping.mapper.array.COARSE if line != 'share']
        self.assertEqual(mapping.mapper.array.unshared_coarse(text), expected)

    def test_actual_missing_flatten_help_failure_remains_rejected(self):
        path = ROOT / 'build/rknpu-dsp-prefix-observed-board-mapping/1791308508029625672/help.log'
        with self.assertRaises(AssertionError):
            mapping.mapper.array.unshared_coarse(path.read_text())

    def test_all_original_observations_and_successful_frontend_required(self):
        for kind in ('binding', 'execution'):
            report = self.prepared()
            if kind == 'binding':
                report['bindings'].pop('demo.host_rdata')
            else:
                report['commands'][-1]['returncode'] = 1
            with self.assertRaises(AssertionError):
                mapping.verify_prepared_metadata(report)

    def test_full_stage_geometry_and_restored_ram_capture(self):
        report = self.prepared()
        coarse = [line.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for line in mapping.mapper.array.COARSE if line != 'share']
        text = mapping.mapping_script(ROOT / 'build/control-not-executed.json', ROOT / 'build/control-not-executed',
                                      report['preserved_kernel'], coarse)
        self.assertIn('select -assert-count 16 ', text)
        self.assertIn('select -assert-count 32 ', text)
        self.assertIn('-run map_memory:check;', text)
        self.assertIn('design -load rk_observed_prefix_ram_capture;\nsynth_xilinx ', text)
        self.assertIn('check -assert;', text)
        self.assertNotIn('read_verilog -sv', text)
        self.assertNotIn('share;', text)
        self.assertNotIn('setundef', text)

    def test_changed_coarse_or_kernel_geometry_rejected(self):
        report = self.prepared()
        coarse = [line.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for line in mapping.mapper.array.COARSE if line != 'share']
        for kernel, commands in ((report['preserved_kernel'], coarse + ['share']), ('wrong_kernel', coarse)):
            with self.assertRaises(AssertionError):
                mapping.mapping_script(ROOT / 'build/not-executed.json', ROOT / 'build/not-executed', kernel, commands)

    def test_processed_source_and_abc_contract(self):
        result = mapping.audit_mapping_log(self.text(), self.prepared()['preserved_kernel'], {})
        self.assertEqual(result['all_check_problem_counts'], [0] * 4)

    def test_unknown_repeated_and_native_source_warnings_rejected(self):
        for extra in ('Warning: unmodeled input\n', mapping.mapper.array.ABC_NOTICE + '\n',
                      'Warning: Wire top.temporary is used but has no driver.\n',
                      'Warning: Replacing memory \\regs with list of registers.\n'):
            with self.assertRaises(AssertionError):
                mapping.audit_mapping_log(self.text() + extra, self.prepared()['preserved_kernel'], {})

    def test_ram_notice_needs_exact_proved_site_and_width(self):
        line = 'Warning: Resizing cell port ypcb_cmac_array_top.ram.WEBWE from 4 bits to 8 bits.\n'
        text = self.text() + line
        mapping.audit_mapping_log(text, self.prepared()['preserved_kernel'], {('ram', 'WEBWE'): (4, 8)})
        for notices in ({}, {('ram', 'WEBWE'): (4, 9)}, {('other', 'WEBWE'): (4, 8)}):
            with self.assertRaises(AssertionError):
                mapping.audit_mapping_log(text, self.prepared()['preserved_kernel'], notices)

    def test_nonzero_check_or_reoptimized_kernel_rejected(self):
        for text in (self.text().replace('Found and reported 0', 'Found and reported 1', 1),
                     self.text().replace('Extracted 0 gates and 0 wires', 'Extracted 1 gates and 1 wires')):
            with self.assertRaises(AssertionError):
                mapping.audit_mapping_log(text, self.prepared()['preserved_kernel'], {})


if __name__ == '__main__':
    unittest.main()
