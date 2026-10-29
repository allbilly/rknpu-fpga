"""Binary cofactor selection controls, not HDL/board/physical evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import analyze_cofactor_lut_pairs as runner
from test_board_lut_pair import lut


def fixture():
    # O5 = XOR of two variables. O6's zero-selector half is the same XOR,
    # while its other half is unrelated. Small pin order includes a constant.
    low = sum(((a & 1) ^ ((a >> 1) & 1)) << a for a in range(32))
    large = lut('LUT6', [2, 3, 4, 5, 6, 7], 21, format((0x13579bdf << 32) | low, '064b'))
    small = lut('LUT3', [3, '1', 2], 20, '01011010')
    return dict(ports={'in': dict(direction='input', bits=[2, 3, 4, 5, 6, 7]),
        'out': dict(direction='output', bits=[20, 21])}, cells={'small': small, 'large': large})


class CofactorLutPairControls(unittest.TestCase):
    def test_all_64_binary_assignments_and_literal_input_preservation(self):
        module = fixture(); before = deepcopy(module)
        records, classes, stats = runner.proposals(module, set())
        self.assertEqual(module, before)
        self.assertEqual(stats['proposed_pairs'], 1)
        self.assertEqual(records[0]['selector'], 7)
        function = next(iter(classes.values()))
        self.assertEqual(function['first']['pins'], [1, '1', 0])
        runner.verify_proposals_cofactor(module, set(), records, classes)

    def test_permuted_lut6_pin_order_preserves_actual_function(self):
        module = fixture(); old = module['cells']['large']; order = [7, 4, 2, 6, 3, 5]
        spec = runner.function_spec(old, order)
        module['cells']['large'] = lut('LUT6', order, 21,
            format(runner.truth_table(spec['init'], tuple(spec['pins']), 6), '064b'))
        records, classes, _ = runner.proposals(module, set())
        self.assertEqual(len(records), 1); self.assertEqual(records[0]['selector'], 7)
        runner.verify_proposals_cofactor(module, set(), records, classes)

    def test_one_cofactor_does_not_count_as_zero_cofactor(self):
        module = fixture(); large = module['cells']['large']
        large['parameters']['INIT'] = large['parameters']['INIT'][32:] + large['parameters']['INIT'][:32]
        with self.assertRaisesRegex(AssertionError, 'zero cofactor'):
            runner.cofactor_function(module['cells']['small'], large, 7)

    def test_prior_union_exclusion_and_direct_o6_sink_are_not_pairable(self):
        module = fixture(); self.assertEqual(runner.proposals(module, {'small'})[0], [])
        module['cells']['carry'] = dict(type='CARRY4', connections={'S': [20, '0', '0', '0']},
            port_directions={'S': 'input'})
        self.assertEqual(runner.proposals(module, set())[0], [])
        with self.assertRaises(AssertionError): runner.proposals(fixture(), {'nonexistent'})

    def test_repeated_inputs_and_constant_pin_lut6_are_explicitly_retained(self):
        for pin in (2, '0'):
            module = fixture(); module['cells']['large']['connections']['I5'] = [pin]
            records, _, stats = runner.proposals(module, set()); self.assertEqual(records, [])
            field = 'retained_repeated_correlated_inputs' if type(pin) is int else 'retained_constant_pin_lut6'
            self.assertEqual(stats[field], 1)

    def test_mutated_domain_wiring_roles_and_reused_cells_rejected(self):
        for mutation in ('init', 'pins', 'selector', 'roles', 'duplicate', 'missing', 'orphan', 'excluded'):
            module = fixture(); records, classes, _ = runner.proposals(module, set()); excluded = set()
            if mutation == 'init': next(iter(classes.values()))['init'] = '0' * 64
            elif mutation == 'pins': records[0]['fanins'].reverse()
            elif mutation == 'selector': records[0]['selector'] = 6
            elif mutation == 'roles': records[0]['dedicated_o6_sinks']['O5'] = [{'invalid': True}]
            elif mutation == 'duplicate': records.append(deepcopy(records[0]))
            elif mutation == 'missing': records.clear()
            elif mutation == 'orphan': classes['unlisted'] = deepcopy(next(iter(classes.values())))
            else: excluded = {'small'}
            with self.subTest(mutation=mutation), self.assertRaises((AssertionError, KeyError)):
                runner.verify_proposals_cofactor(module, excluded, records, classes)

    def test_malformed_schema_and_primary_input_driver_rejected(self):
        for mutation in ('width', 'unknown', 'direction', 'parameter', 'pin', 'primary'):
            module = fixture(); cell = module['cells']['large']
            if mutation == 'width': cell['parameters']['INIT'] = '01'
            elif mutation == 'unknown': cell['connections']['I5'] = ['x']
            elif mutation == 'direction': cell['port_directions']['I0'] = 'output'
            elif mutation == 'parameter': cell['parameters']['OTHER'] = '0'
            elif mutation == 'pin': cell['connections']['OTHER'] = [7]
            else: module['ports']['in']['bits'].append(21)
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError): runner.proposals(module, set())


if __name__ == '__main__': unittest.main()
