"""Literal native-encoder fixture/feature controls, not numerical or signoff."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from probe_prefix_native_config import (SELECTED, representatives, config_fixture, verify_fixture,
    parse_features, parse_native_features, verify_clock_admission, native_budget)


class PrefixNativeConfigControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.selected = json.loads(SELECTED.read_text())

    def test_actual_full_census_and_all_six_literal_bram_configs_selected(self):
        chosen = representatives(self.selected)
        self.assertEqual(len(chosen), 10)
        self.assertEqual(sum(c['type'] == 'RAMB36E1' for c in chosen.values()), 6)

    def test_control_keeps_exact_parameters_pin_widths_and_constant_bits(self):
        design, origins = config_fixture(self.selected)
        verify_fixture(design, origins, self.selected)
        for name, source in origins.items(): self.assertEqual(design['modules'][next(iter(design['modules']))]['cells'][name]['parameters'], self.selected[source]['parameters'])

    def test_changed_params_missing_resource_pin_width_or_literal_constant_fail(self):
        for change in ('parameter', 'missing', 'width', 'constant'):
            design, origins = config_fixture(self.selected)
            cells = next(iter(design['modules'].values()))['cells']
            name = next(n for n in origins if cells[n]['type'] == 'DSP48E1')
            if change == 'parameter': cells[name]['parameters']['AREG'] = '1'
            elif change == 'missing': cells.pop(name)
            elif change == 'width': cells[name]['connections']['A'].pop()
            else: cells[name]['connections']['OPMODE'][0] = '0'
            with self.subTest(change=change), self.assertRaises((AssertionError, KeyError)): verify_fixture(design, origins, self.selected)

    def test_fasm_parser_rejects_duplicate_bad_width_and_unknown_syntax(self):
        self.assertEqual(parse_features("# producer\nT.IN_USE\nT.INIT[3:0] = 4'b1010\n"), {'T.IN_USE': '1', 'T.INIT[3:0]': '1010'})
        for text in ("T.X\nT.X\n", "T.X[3:0] = 3'b1010\n", 'bad syntax'):
            with self.assertRaises(AssertionError): parse_features(text)

    def test_native_host_wall_budget_is_bounded_without_timing_waiver(self):
        for budget in (600, 3600, 7200): self.assertEqual(native_budget(budget), budget)
        for budget in (True, 599, 7201, -1, 3600.0):
            with self.assertRaises(AssertionError): native_budget(budget)

    def test_public_port_aliases_match_literal_bits_and_missing_or_changed_fail(self):
        design, origins = config_fixture(self.selected)
        module = next(iter(design['modules'].values()))
        for name, port in module['ports'].items():
            self.assertEqual(module['netnames'][name]['bits'], port['bits'])
        for change in ('missing', 'wrong_wire', 'hidden', 'port'):
            corrupt = deepcopy(design)
            m = next(iter(corrupt['modules'].values()))
            if change == 'missing': m['netnames'].pop('SYS_CLK')
            elif change == 'wrong_wire': m['netnames']['SYS_CLK']['bits'] = [3]
            elif change == 'hidden': m['netnames']['SYS_CLK']['hide_name'] = 1
            else: m['ports']['SYS_CLK']['bits'] = [3]
            with self.subTest(change=change), self.assertRaises(AssertionError):
                verify_fixture(corrupt, origins, self.selected)

    def test_native_fasm_only_folds_source_defined_equal_stepdown_pair(self):
        name = 'LIOB33_X0Y173.IOB_Y0.LVCMOS12_LVCMOS15_LVCMOS18_SSTL135_SSTL15.STEPDOWN'
        features, repeated = parse_native_features(name + '\n' + name + '\nT.IN_USE\n')
        self.assertEqual(features, {name: '1', 'T.IN_USE': '1'})
        self.assertEqual(repeated, {name: [1, 2]})
        for text in ('T.X\nT.X\n', name + '\n' + name + " = 1'b0\n",
                     (name + '\n') * 3, "T.X[3:0] = 3'b1010\n", 'bad syntax'):
            with self.subTest(text=text), self.assertRaises(AssertionError): parse_native_features(text)

    def test_clock_admission_requires_exact_literal_target_and_period(self):
        log = "Info: applying clock period constraint on net 'SYS_CLK' (on line 11)\n"
        verify_clock_admission(log, {'target_period_ns': 20.0})
        for corrupt in ('', log.replace('SYS_CLK', 'SYS_RSTN'), log * 2,
                        log + 'ERROR: clock not applied\n', log + 'target is ignored\n'):
            with self.subTest(log=corrupt), self.assertRaises(AssertionError):
                verify_clock_admission(corrupt, {'target_period_ns': 20.0})
        with self.assertRaises(AssertionError): verify_clock_admission(log, {'target_period_ns': 10.0})


if __name__ == '__main__': unittest.main()
