"""Direct-sink and hierarchy audit controls, not physical or full HDL proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import audit_lut_pair_sinks as runner


def fixture():
    pair = dict(type='LUT6_2', parameters={'INIT': '01' * 32},
        connections={**{f'I{i}': [i + 2] for i in range(5)}, 'I5': ['1'], 'O5': [10], 'O6': [11]},
        port_directions={**{f'I{i}': 'input' for i in range(6)}, 'O5': 'output', 'O6': 'output'})
    carry = dict(type='CARRY4', connections={'S': [11, '0', '0', '0'], 'DI': [10, '0', '0', '0']},
        port_directions={'S': 'input', 'DI': 'input'})
    return dict(cells={'pair': pair, 'carry': carry})


class LutPairSinkControls(unittest.TestCase):
    def test_o6_carry_select_and_o5_generate_are_distinguished(self):
        item, = runner.audit_module(fixture())
        self.assertFalse(item['o5_has_dedicated_o6_sink'])
        self.assertFalse(item['both_outputs_need_o6'])
        self.assertTrue(item['o6_has_dedicated_sink'])
        self.assertEqual(item['dedicated_o6_sinks']['O6'][0], dict(cell='carry', kind='CARRY4', pin='S', index=0))

    def test_o5_carry_select_is_recorded_without_assuming_repacking(self):
        module = fixture(); module['cells']['carry']['connections']['S'] = [10, '0', '0', '0']
        item, = runner.audit_module(module)
        self.assertTrue(item['o5_has_dedicated_o6_sink']); self.assertFalse(item['both_outputs_need_o6'])
        self.assertFalse(item['o6_has_dedicated_sink'])

    def test_both_output_select_positions_need_distinct_o6_resources(self):
        module = fixture(); module['cells']['carry']['connections']['S'] = [10, 11, '0', '0']
        item, = runner.audit_module(module)
        self.assertTrue(item['both_outputs_need_o6'])
        self.assertEqual(item['dedicated_o6_sinks']['O5'][0]['index'], 0)
        self.assertEqual(item['dedicated_o6_sinks']['O6'][0]['index'], 1)

    def test_all_mux_fanin_and_multiple_sinks_are_retained(self):
        module = fixture(); module['cells']['mux'] = dict(type='MUXF7',
            connections={'I0': [10], 'I1': [11]}, port_directions={'I0': 'input', 'I1': 'input'})
        item, = runner.audit_module(module)
        self.assertEqual(item['dedicated_o6_sinks']['O5'], [dict(cell='mux', kind='MUXF7', pin='I0', index=0)])
        self.assertEqual(len(item['dedicated_o6_sinks']['O6']), 2)

    def test_two_five_input_contract_mutations_are_rejected(self):
        for case in ('i5', 'init', 'output', 'direction', 'carry_width', 'mux_direction'):
            module = fixture(); cell = module['cells']['pair']
            if case == 'i5': cell['connections']['I5'] = [2]
            elif case == 'init': cell['parameters']['INIT'] = '0' * 63
            elif case == 'output': cell['connections']['O5'] = [11]
            elif case == 'direction': cell['port_directions']['O5'] = 'input'
            elif case == 'carry_width': module['cells']['carry']['connections']['S'] = [11]
            else: module['cells']['mux'] = dict(type='MUXF7', connections={'I0': [10], 'I1': [11]},
                port_directions={'I0': 'output', 'I1': 'input'})
            with self.subTest(case=case), self.assertRaises(AssertionError): runner.audit_module(module)

    def test_actual_hierarchy_multiplicity_and_recursion_unreachable_rejection(self):
        modules = {'top': dict(cells={str(i): dict(type='kernel') for i in range(16)}), 'kernel': fixture()}
        self.assertEqual(runner.multiplicities(modules, 'top', {'top', 'kernel'}), {'top': 1, 'kernel': 16})
        bad = deepcopy(modules); bad['kernel']['cells']['cycle'] = dict(type='top')
        with self.assertRaises(AssertionError): runner.multiplicities(bad, 'top', {'top', 'kernel'})
        with self.assertRaises(AssertionError): runner.multiplicities(modules, 'kernel', {'top', 'kernel'})


if __name__ == '__main__': unittest.main()
