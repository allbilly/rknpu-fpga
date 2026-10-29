"""Synthetic graph/INIT corruption controls, not full-board execution."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from audit_prefix_bram_outputs import (SELECTED, TOP, output_bindings, classify_memory, memory_words)


class PrefixBramOutputControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        selected = json.loads(SELECTED.read_text())
        cls.original = deepcopy(next(c for c in selected.values() if c['type'] == 'RAMB36E1'))

    def case(self, lanes=tuple(range(9))):
        original = deepcopy(self.original)
        wires = original['connections']['DOADO'][:8] + original['connections']['DOPADOP'][:1]
        cells = {'bram': original}
        for lane in lanes:
            cells[f'consumer_{lane}'] = dict(type='INV', parameters={}, attributes={}, hide_name=0,
                port_directions=dict(I='input', O='output'), connections=dict(I=[wires[lane]], O=[1000000 + lane]))
        module = dict(ports=dict(output=dict(direction='output', bits=[1000000])), cells=cells)
        data = json.dumps(dict(modules={TOP: module}), indent=2).encode()
        return original, cells, module, data

    def test_all_output_bits_checked_and_live_parity_not_called_padding(self):
        original, _, _, data = self.case()
        counts, bound = output_bindings(data, {'bram': original}, {'RAMB36E1': 1, 'INV': 9})
        result = classify_memory(original, bound['bram'])
        self.assertEqual(sum(map(len, bound['bram'].values())), 72)
        self.assertEqual(result['directly_consumed_memory_lanes'], list(range(9)))
        self.assertEqual(result['memory_bit_classification']['unknown_with_direct_consumer'], 36864)
        self.assertFalse(result['observable_startup_reset_independence_proved'])

    def test_data_and_parity_padding_require_no_consumers(self):
        original, _, _, data = self.case(tuple(range(7)))
        _, bound = output_bindings(data, {'bram': original})
        stats = classify_memory(original, bound['bram'])['memory_bit_classification']
        self.assertEqual(stats['unknown_with_direct_consumer'], 7 * 4096)
        self.assertEqual(stats['unknown_without_consumer'], 2 * 4096)

    def test_top_level_output_consumer_is_not_ignored(self):
        original, _, module, _ = self.case(tuple(range(7)))
        module['ports']['extra'] = dict(direction='output', bits=original['connections']['DOPADOP'][:1])
        data = json.dumps(dict(modules={TOP: module}), indent=2).encode()
        _, bound = output_bindings(data, {'bram': original})
        self.assertIn(8, classify_memory(original, bound['bram'])['directly_consumed_memory_lanes'])

    def test_missing_driver_alias_changed_cell_inout_and_incomplete_census_fail(self):
        for change in ('missing', 'alias', 'changed', 'inout', 'count'):
            original, cells, module, _ = self.case()
            if change == 'missing': cells.pop('bram')
            elif change == 'alias': original['connections']['DOADO'][1] = original['connections']['DOADO'][0]
            elif change == 'changed': cells['bram'] = deepcopy(original); cells['bram']['connections']['DOADO'][0] += 1
            elif change == 'inout': cells['consumer_0']['port_directions']['I'] = 'inout'
            data = json.dumps(dict(modules={TOP: module}), indent=2).encode()
            with self.subTest(change=change), self.assertRaises((AssertionError, KeyError)):
                output_bindings(data, {'bram': original}, {'RAMB36E1': 1, 'INV': 8} if change == 'count' else None)

    def test_lsb_first_memory_lane_order_and_complete_init_contract(self):
        original, _, _, _ = self.case()
        params = deepcopy(original['parameters'])
        for k in params:
            if k.startswith('INIT_') and len(k) == 7 or k.startswith('INITP_'): params[k] = '0' * 256
        params['INIT_00'] = '0' * 248 + '10100101'
        params['INITP_00'] = '0' * 255 + '1'
        self.assertEqual(memory_words(params)[0], '101001011')
        self.assertEqual(memory_words(params)[1], '0' * 9)
        params.pop('INIT_7F')
        with self.assertRaises(AssertionError): memory_words(params)

    def test_inactive_output_and_unknown_rom_consumer_fail(self):
        original, _, _, data = self.case()
        _, bound = output_bindings(data, {'bram': original})
        wrong = deepcopy(bound['bram'])
        wrong['DOADO'][9]['consumers'] = [dict(test='synthetic invalid lane')]
        with self.assertRaises(AssertionError): classify_memory(original, wrong)
        readonly = deepcopy(original)
        readonly['parameters']['WRITE_WIDTH_A'] = readonly['parameters']['WRITE_WIDTH_B'] = '0' * 32
        with self.assertRaises(AssertionError): classify_memory(readonly, bound['bram'], [0] * 4096)


if __name__ == '__main__': unittest.main()
