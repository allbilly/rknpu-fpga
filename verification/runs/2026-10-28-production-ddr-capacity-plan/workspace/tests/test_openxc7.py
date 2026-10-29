"""Fail-closed constraint/characterization checks; not physical signoff tests."""
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from run_openxc7 import EXCEPTIONS, PINS, check_timing_report, normalized_xdc, package_pins


class TestOpenXC7(unittest.TestCase):
    def test_exact_board_constraints_expand_all_ports(self):
        normalized, exceptions = normalized_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        self.assertEqual(exceptions, list(EXCEPTIONS))
        self.assertEqual(normalized.count('PACKAGE_PIN'), 5)
        self.assertEqual(normalized.count('IOSTANDARD LVCMOS18'), 5)
        self.assertIn('create_clock -name sys_clk -period 20.000 [get_ports SYS_CLK]', normalized)
        self.assertNotIn('*', normalized)

    def test_modified_missing_duplicate_or_unknown_constraints_fail(self):
        source = (ROOT / 'fpga/ypcb.xdc').read_text()
        for changed in (source.replace('20.000', '40.000'), source.replace('AA28', 'AA29'),
                        source.replace('LVCMOS18', 'LVCMOS33'), source.replace(EXCEPTIONS[0], ''),
                        source + '\n' + EXCEPTIONS[0], source + '\nset_false_path -through [get_cells *]',
                        source + '\nset_property CFGBVS GND [current_design]'):
            with self.subTest(changed=changed[-80:]), self.assertRaises(ValueError):
                normalized_xdc(changed)

    def test_package_pin_sites_and_clock_capability(self):
        rows = ['pin,bank,site,tile,pin_function']
        rows += [f'{pin},{14 if port == "SYS_CLK" else 15},IOB_X0Y1,LIOB33_X0Y1,IO_MRCC_14'
                 for port, pin in PINS.items()]
        source = '\n'.join(rows)
        self.assertEqual(set(package_pins(source)), set(PINS))
        for bad in (source.replace('AA28', 'AA29'), source + '\n' + rows[1],
                    source.replace('AA28,14', 'AA28,15'), source.replace('MRCC', 'DATA'),
                    source.replace('LIOB33_', 'RIOB18_')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                package_pins(bad)

    def test_clock_result_must_be_finite_constrained_and_pass(self):
        def result(achieved=51, constraint=50):
            return {'fmax': {'SYS_CLK': {'achieved': achieved, 'constraint': constraint}}}
        self.assertEqual(check_timing_report(result()), {'achieved': 51, 'constraint': 50})
        for bad in ({}, {'fmax': {}}, {'fmax': {'other': {}}}, result(49), result(51, 25),
                    result(math.nan), result(math.inf), result(0), result(None), result(True), result('51')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                check_timing_report(bad)

    def test_no_bitstream_command_line_option(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'tools/run_openxc7.py'), '--emit-bitstream'],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('unrecognized arguments', proc.stderr)


if __name__ == '__main__':
    unittest.main()
