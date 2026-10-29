"""Admission controls only; these synthetic strings are not board evidence."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('ypcb_reference', ROOT / 'tools/openxc7/audit_ypcb_configuration_reference_archive.py')
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


def fixture():
    missing = 'Neither the CFGBVS nor CONFIG_VOLTAGE voltage property is set in the current_design.'
    return {
        'constraints': 'set_property IOSTANDARD LVCMOS33 [get_ports reset_rtl_0]\n',
        'implementation_log': '\n'.join([
            'Loading part xc7k480tffg1156-2', '****** Vivado v2022.1.2 (64-bit)',
            'WARNING: [DRC CFGBVS-1] Missing CFGBVS and CONFIG_VOLTAGE Design Properties: ' + missing,
            'CRITICAL WARNING: [Timing 38-282] The design failed to meet the timing requirements.',
            'INFO: [Vivado 12-1842] Bitgen Completed Successfully.']),
        'routed_drc': '| CFGBVS-1 | Warning | Missing CFGBVS and CONFIG_VOLTAGE Design Properties | 1 |\n' + missing,
        'placed_io': '\n'.join(['| G14 | VCCO_0 | any** |', '| H13 | VCCO_0 | any** |', '| AL15 | CFGBVS_0 |']),
    }


class Controls(unittest.TestCase):
    def test_historical_bitgen_does_not_promote_electrical_or_timing(self):
        r = HELPER.reference_contract(fixture())
        self.assertTrue(r['historical_bitgen_completed'])
        self.assertFalse(r['historical_timing_requirements_met'])
        self.assertFalse(r['physical_bank_0_voltage_verified'])
        self.assertFalse(r['physical_cfgbvs_strap_verified'])

    def test_changed_target_or_missing_actual_diagnostic_rejected(self):
        for old, new in [('xc7k480tffg1156-2', 'xc7k480tffg1156-1'), ('CFGBVS-1', 'CFGBVS-X')]:
            texts = fixture()
            texts['implementation_log'] = texts['implementation_log'].replace(old, new)
            with self.assertRaises(AssertionError):
                HELPER.reference_contract(texts)

    def test_numeric_bank_value_cannot_be_called_unspecified(self):
        texts = fixture()
        texts['placed_io'] = texts['placed_io'].replace('any**', '3.30')
        with self.assertRaises(AssertionError):
            HELPER.reference_contract(texts)

    def test_contradictory_constraint_or_duplicate_pin_rejected(self):
        texts = fixture()
        texts['constraints'] += 'set_property CONFIG_VOLTAGE 3.3 [current_design]\n'
        with self.assertRaises(AssertionError):
            HELPER.reference_contract(texts)
        texts = fixture()
        texts['placed_io'] += '\n| H13 | VCCO_0 | any** |'
        with self.assertRaises(AssertionError):
            HELPER.reference_contract(texts)


if __name__ == '__main__':
    unittest.main()
