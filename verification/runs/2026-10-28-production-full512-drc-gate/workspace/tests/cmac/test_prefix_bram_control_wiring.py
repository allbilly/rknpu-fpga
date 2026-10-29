"""Binary local-control/corruption tests, not HDL or startup evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from audit_prefix_bram_control_wiring import (SIGNALS, SELECTED, control_roots,
    selected_drivers, binary_control_contract, translate_controls)
from audit_prefix_memory_wiring import TOP, CONSUMER


class PrefixBramControlWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.selected = {n: c for n, c in json.loads(SELECTED.read_text()).items() if c['type'] == 'RAMB36E1'}
        cls.classification = json.loads(CONSUMER.read_text())['BRAM_memory_classification']

    def case(self):
        brams, info = deepcopy(self.selected), deepcopy(self.classification)
        signals = dict(zip(SIGNALS, range(1000, 1000 + len(SIGNALS))))
        for name, cell in brams.items():
            if not info[name]['readonly']:
                c = cell['connections']
                c['ENARDEN'], c['ENBWREN'] = [signals['host_fire']], [signals['core_fire']]
                c['WEA'], c['WEBWE'] = [1010] * 4, [1011] * 4 + ['0'] * 4
        def lut(output, inputs, init):
            ports = {'I' + str(i): [w] for i, w in enumerate(inputs)}
            ports['O'] = [output]
            return dict(cell='control_' + str(output), output_pin='O', primitive=dict(hide_name=0,
                type='LUT' + str(len(inputs)), parameters=dict(INIT=init), attributes={},
                port_directions={p: ('output' if p == 'O' else 'input') for p in ports}, connections=ports))
        s = signals
        drivers = {
            s['host_ready']: lut(s['host_ready'], [s['host_rsp_valid'], s['rst_n']], '0100'),
            s['req_ready']: lut(s['req_ready'], [s['rsp_valid'], s['rst_n']], '0100'),
            s['host_fire']: lut(s['host_fire'], [1020, s['host_ready']], '1000'),
            s['core_fire']: lut(s['core_fire'], [1021, s['req_valid'], s['req_ready']], '10000000'),
            1010: lut(1010, [s['host_ready'], s['host_write']], '1000'),
            1011: lut(1011, [1021, s['req_valid'], s['req_ready'], s['req_write']], '1000000000000000')}
        return brams, info, signals, drivers

    def test_positive_complete_binary_cut_with_explicit_temporal_gap(self):
        result = binary_control_contract(*self.case())
        self.assertEqual(result['binary_cut_assignments'], 256)
        self.assertEqual(result['binary_assertions_compared'], 2048)
        self.assertEqual(result['control_driver_cells'], 6)
        self.assertTrue(result['write_enables_match_declared_fire_and_write'])
        self.assertFalse(result['write_before_read_proved'])
        self.assertFalse(result['temporal_port_ownership_proved'])
        self.assertFalse(result['observable_startup_reset_independence_proved'])

    def test_changed_effective_write_truth_tables_fail(self):
        for output in (1010, 1011):
            args = self.case()
            p = args[3][output]['primitive']['parameters']
            p['INIT'] = '1' * len(p['INIT'])
            with self.subTest(output=output), self.assertRaisesRegex(AssertionError, 'Effective BRAM write mismatch'):
                binary_control_contract(*args)

    def test_reset_and_ready_handshake_corruptions_fail(self):
        for signal in ('host_ready', 'req_ready', 'host_fire', 'core_fire'):
            args = self.case()
            p = args[3][args[2][signal]]['primitive']['parameters']
            p['INIT'] = '1' * len(p['INIT'])
            with self.subTest(signal=signal), self.assertRaises(AssertionError): binary_control_contract(*args)

    def test_bram_pin_policy_corruptions_fail(self):
        for change in ('enable', 'mixed_we', 'unused_we', 'reset', 'register_enable', 'rom_write', 'missing'):
            brams, info, signals, drivers = self.case()
            ram = next(c for n, c in brams.items() if not info[n]['readonly'])
            rom = next(c for n, c in brams.items() if info[n]['readonly'])
            if change == 'enable': ram['connections']['ENARDEN'] = [signals['core_fire']]
            elif change == 'mixed_we': ram['connections']['WEA'][1] = 99999
            elif change == 'unused_we': ram['connections']['WEBWE'][7] = '1'
            elif change == 'reset': ram['connections']['RSTRAMB'] = ['1']
            elif change == 'register_enable': ram['connections']['REGCEB'] = ['1']
            elif change == 'rom_write': rom['connections']['WEA'][0] = '1'
            else: brams.pop(next(iter(brams)))
            with self.subTest(change=change), self.assertRaises(AssertionError):
                binary_control_contract(brams, info, signals, drivers)

    def test_unmodeled_lut_fields_unknowns_and_cycles_fail(self):
        for change in ('type', 'pin', 'width', 'direction', 'parameter', 'unknown', 'short', 'cycle', 'missing_driver'):
            args = self.case(); cell = args[3][1010]['primitive']
            if change == 'type': cell['type'] = 'FDRE'
            elif change == 'pin': cell['connections']['EXTRA'] = ['0']
            elif change == 'width': cell['connections']['I0'] = [1005, 1006]
            elif change == 'direction': cell['port_directions']['I0'] = 'output'
            elif change == 'parameter': cell['parameters']['OTHER'] = '0'
            elif change == 'unknown': cell['parameters']['INIT'] = 'x000'
            elif change == 'short': cell['parameters']['INIT'] = '1'
            elif change == 'cycle': cell['connections']['I0'] = [1010]
            else: args[3].pop(1010)
            with self.subTest(change=change), self.assertRaises(AssertionError): binary_control_contract(*args)

    def test_full_census_and_duplicate_driver_are_required(self):
        brams, info, signals, drivers = self.case()
        cells = dict(brams)
        cells.update({r['cell']: r['primitive'] for r in drivers.values()})
        counts = {}
        for cell in cells.values(): counts[cell['type']] = counts.get(cell['type'], 0) + 1
        data = json.dumps(dict(modules={TOP: dict(cells=cells)}), indent=2).encode()
        roots, _ = control_roots(brams, info, signals)
        actual, _ = selected_drivers(data, roots, brams, counts)
        self.assertEqual(actual, drivers)
        with self.assertRaisesRegex(AssertionError, 'census'):
            selected_drivers(data, roots, brams, {**counts, 'RAMB36E1': 5})
        cells['duplicate'] = deepcopy(cells['control_1010'])
        bad = json.dumps(dict(modules={TOP: dict(cells=cells)}), indent=2).encode()
        with self.assertRaisesRegex(AssertionError, 'Multiple'):
            selected_drivers(bad, roots, brams, counts)

    def test_extra_high_literal_init_bits_do_not_change_actual_lut_addressing(self):
        args = self.case()
        p = args[3][1010]['primitive']['parameters']
        p['INIT'] = '1' * 28 + p['INIT']
        self.assertEqual(binary_control_contract(*args)['binary_cut_assignments'], 256)

    def test_literal_control_alias_translation_and_corruptions(self):
        record = lambda bits: dict(hide_name=0, bits=bits, attributes={})
        source = {'demo.memory.' + s: record([i]) for i, s in enumerate(SIGNALS, 2)}
        aliases = {'n_' + str(i): record([i + 1000]) for i in range(2, len(SIGNALS) + 2)}
        original = json.dumps(dict(modules={TOP: dict(netnames=source)}), indent=2).encode()
        physical = json.dumps(dict(modules={TOP: dict(netnames=aliases)}), indent=2).encode()
        signals, _ = translate_controls(original, physical)
        self.assertEqual(signals['rst_n'], 1002)
        for change in ('missing', 'aliased', 'width', 'offset'):
            bad = deepcopy(aliases)
            if change == 'missing': bad.pop('n_2')
            elif change == 'aliased': bad['n_3']['bits'] = bad['n_2']['bits']
            elif change == 'width': bad['n_2']['bits'] = [1002, 1003]
            else: bad['n_2']['offset'] = 1
            corrupt = json.dumps(dict(modules={TOP: dict(netnames=bad)}), indent=2).encode()
            with self.subTest(change=change), self.assertRaises(AssertionError): translate_controls(original, corrupt)


if __name__ == '__main__':
    unittest.main()
