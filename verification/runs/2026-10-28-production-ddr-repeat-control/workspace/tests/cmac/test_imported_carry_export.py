"""Actual saved native exports and corruption controls, not new HDL/P&R."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from compare_imported_carry_export import carry_export_view, empty_input_view
from probe_imported_placement_checker import NATIVE
from probe_corrected_dsp_checkpoint import assert_circuit_identity, proof_module

FAILED = Path(__file__).resolve().parents[2] / 'build/openxc7/imported-placement-checker-qualification-1791426415757842131'


class ImportedCarryExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = next(iter(json.loads((NATIVE.parent / 'valid-forced-placed.json').read_text())['modules'].values()))
        cls.after = next(iter(json.loads((FAILED / 'fixed_49-routed.json').read_text())['modules'].values()))
        cls.carry = next(n for n, c in cls.before['cells'].items() if c['type'] == 'CARRY4')

    def test_actual_saved_route_preserves_all_logical_incidence(self):
        before, after = deepcopy(self.before), deepcopy(self.after)
        view, info = carry_export_view(before, after)
        self.assertEqual(info['restored_empty_CARRY4_ports_by_direction'], {'input': 2, 'output': 6})
        self.assertFalse(info['comparison_view_used_for_execution'])
        self.assertFalse(info['missing_connected_ports_restored'])
        self.assertFalse(info['existing_ports_rewritten'])
        result = assert_circuit_identity(proof_module(before), proof_module(view, before['ports']))
        self.assertEqual(result['logical_board']['cells'], 49)
        self.assertEqual(before, self.before); self.assertEqual(after, self.after)

    def test_old_gate_still_refuses_the_same_export(self):
        with self.assertRaisesRegex(AssertionError, 'Unmodeled empty-input primitive'):
            empty_input_view(self.before, self.after, include_luts=False)

    def test_missing_connected_input_cannot_be_restored(self):
        bad = deepcopy(self.after)
        bad['cells'][self.carry]['connections'].pop('DI0')
        bad['cells'][self.carry]['port_directions'].pop('DI0')
        with self.assertRaisesRegex(AssertionError, 'Missing connected carry pin'): carry_export_view(self.before, bad)

    def test_missing_connected_output_cannot_be_restored(self):
        bad = deepcopy(self.after)
        bad['cells'][self.carry]['connections'].pop('O0')
        bad['cells'][self.carry]['port_directions'].pop('O0')
        with self.assertRaisesRegex(AssertionError, 'Missing connected carry pin'): carry_export_view(self.before, bad)

    def test_wrong_original_empty_direction_fails(self):
        bad = deepcopy(self.before); bad['cells'][self.carry]['port_directions']['CO0'] = 'input'
        with self.assertRaisesRegex(AssertionError, 'Wrong original empty carry direction'): carry_export_view(bad, self.after)

    def test_existing_direction_is_not_repaired(self):
        bad = deepcopy(self.after); bad['cells'][self.carry]['port_directions']['DI0'] = 'output'
        with self.assertRaisesRegex(AssertionError, 'Explicit checkpoint pin direction changed'): carry_export_view(self.before, bad)

    def test_unmodeled_empty_pin_fails(self):
        bad = deepcopy(self.before)
        bad['cells'][self.carry]['connections']['UNSUPPORTED'] = []
        bad['cells'][self.carry]['port_directions']['UNSUPPORTED'] = 'input'
        with self.assertRaisesRegex(AssertionError, 'Unsupported empty CARRY4 pin'): carry_export_view(bad, self.after)

    def test_extra_export_pin_fails(self):
        bad = deepcopy(self.after)
        bad['cells'][self.carry]['connections']['UNSUPPORTED'] = []
        bad['cells'][self.carry]['port_directions']['UNSUPPORTED'] = 'input'
        with self.assertRaisesRegex(AssertionError, 'Extra carry pin'): carry_export_view(self.before, bad)

    def test_parameters_cannot_change_or_expand(self):
        for where in ('before', 'after'):
            a, b = deepcopy(self.before), deepcopy(self.after)
            (a if where == 'before' else b)['cells'][self.carry]['parameters']['UNSUPPORTED'] = '1'
            with self.subTest(where=where), self.assertRaisesRegex(AssertionError, 'Unsupported/changed CARRY4 parameters'):
                carry_export_view(a, b)

    def test_empty_mapping_cannot_change(self):
        bad = deepcopy(self.after); bad['cells'][self.carry]['attributes']['X_ORIG_PORT_CO0'] = 'O[0]'
        with self.assertRaisesRegex(AssertionError, 'Changed empty carry mapping'): carry_export_view(self.before, bad)

    def test_changed_primitive_type_fails(self):
        bad = deepcopy(self.after); bad['cells'][self.carry]['type'] = 'unsupported'
        with self.assertRaisesRegex(AssertionError, 'Changed carry primitive type'): carry_export_view(self.before, bad)

    def test_changed_connected_wire_is_not_repaired_and_fails_identity(self):
        bad = deepcopy(self.after); cell = bad['cells'][self.carry]
        cell['connections']['DI0'] = list(cell['connections']['DI1'])
        view, _ = carry_export_view(self.before, bad)
        self.assertEqual(view['cells'][self.carry]['connections']['DI0'], cell['connections']['DI0'])
        with self.assertRaises(AssertionError): assert_circuit_identity(proof_module(self.before), proof_module(view, self.before['ports']))


if __name__ == '__main__':
    unittest.main()
