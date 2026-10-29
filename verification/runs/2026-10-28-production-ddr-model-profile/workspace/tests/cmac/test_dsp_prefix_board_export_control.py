"""Literal export controls, not full-board circuit or numerical acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import export_dsp_prefix_board_netlist as export
import check_dsp_prefix_board_export as control


def fixture():
    return dict(modules={'fixture': dict(ports={'a': dict(direction='input', bits=[2]),
                                              'p': dict(direction='output', bits=[3])},
        cells={'cell': dict(type='LUT1', parameters={'INIT': '10'}, connections={'I0': [2], 'O': [3]})},
        netnames={})})


class PrefixBoardExportControl(unittest.TestCase):
    def test_non_dsp_export_is_byte_identical(self):
        for kind, parameters in (('LUT1', {'INIT': '10'}),
                                  ('RAMB36E1', {'RAM_MODE': 'TDP', 'INIT_FILE': 'NONE'})):
            design = fixture()
            cell = design['modules']['fixture']['cells']['cell']
            cell.update(type=kind, parameters=parameters)
            self.assertEqual(export.structural_board_verilog(design), export.original.structural_board_verilog(design))

    def test_only_actual_dsp_strings_added_without_defaults(self):
        for key, value in export.DSP_STRINGS.items():
            self.assertEqual(export.literal(value, 'DSP48E1', key), '"' + value + '"')
            with self.assertRaises(AssertionError):
                export.literal('UNKNOWN', 'DSP48E1', key)
            with self.assertRaises(AssertionError):
                export.literal(value, 'LUT1', key)
        with self.assertRaises(AssertionError):
            export.literal('NO_RESET', 'DSP48E1', 'AUTORESET_PATDET')
        with self.assertRaises(AssertionError):
            export.literal('0101', 'DSP48E1', 'A_INPUT')
        self.assertEqual(export.literal('0000', 'DSP48E1', 'AREG'), "4'b0000")

    def test_actual_supplied_parameters_and_connections_preserved(self):
        design = fixture()
        cell = design['modules']['fixture']['cells']['cell']
        cell.update(type='DSP48E1', parameters={**export.DSP_STRINGS, 'AREG': '0'})
        cell['connections'] = {'A': [2, '0'], 'P': [3]}
        before = deepcopy(design)
        text = export.structural_board_verilog(design)
        self.assertEqual(design, before)
        self.assertIn('.\\A ({1\'b0, n_2})', text)
        self.assertIn('.\\P (n_3)', text)
        self.assertIn('.\\AREG (1\'b0)', text)
        self.assertNotIn('BREG', text)

    def test_invalid_direction_constant_input_and_unknown_bits_rejected(self):
        for value in ('inout', 'other'):
            design = fixture()
            design['modules']['fixture']['ports']['a']['direction'] = value
            with self.assertRaises(AssertionError):
                export.structural_board_verilog(design)

    def test_private_instance_aliases_are_reversible_without_circuit_edits(self):
        design = fixture()
        module = design['modules']['fixture']
        module['cells']['$private\\dsp'] = module['cells'].pop('cell')
        aliased, maps = control.hardware_instance_aliases(design)
        inverse = {value: key for key, value in maps['fixture'].items()}
        restored = deepcopy(aliased)
        restored['modules']['fixture']['cells'] = {inverse[name]: cell for name, cell in restored['modules']['fixture']['cells'].items()}
        self.assertEqual(restored, design)
        self.assertNotEqual(control.circuit_signature(aliased), control.circuit_signature(design))

    def test_boundary_rejects_changed_configuration_or_unmodeled_direction(self):
        design = fixture()
        body = design['modules']['fixture']
        cell = body['cells']['cell']
        cell.update(type='DSP48E1', parameters={key: format(value, '032b') if type(value) is int else value
                    for key, value in control.primitive.PARAMETERS.items()},
                    connections={'A': [2], 'P': [3]}, port_directions={'A': 'input', 'P': 'output'})
        self.assertEqual(len(control.dsp_boundary(body)['cells']), 1)
        for key, value in (('AREG', '1'), ('USE_MULT', 'NONE')):
            changed = deepcopy(body)
            changed['cells']['cell']['parameters'][key] = value
            with self.assertRaises(AssertionError):
                control.dsp_boundary(changed)
        changed = deepcopy(body)
        changed['cells']['cell']['port_directions']['A'] = 'inout'
        with self.assertRaises(AssertionError):
            control.dsp_boundary(changed)
        for value in ('0', 'bad'):
            design = fixture()
            design['modules']['fixture']['ports']['a']['bits'] = [value]
            with self.assertRaises(AssertionError):
                export.structural_board_verilog(design)


if __name__ == '__main__':
    unittest.main()
