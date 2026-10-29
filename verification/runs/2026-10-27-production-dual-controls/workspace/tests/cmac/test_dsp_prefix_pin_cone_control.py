"""Admission/control tests only; the separate runner must use actual Yosys models."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import audit_dsp_prefix_pin_cone as audit


def fixture():
    ports = {name: dict(direction=direction, bits=list(range(start, start + width)))
        for name, direction, start, width in (('A', 'input', 100, 30), ('B', 'input', 200, 18),
            ('omitted', 'input', 300, 26), ('P', 'output', 400, 48))}
    cells = dict(multiply=dict(type='$mul', connections=dict(A=list(range(100, 125)),
        B=list(range(200, 218)), Y=list(range(500, 543))), port_directions=dict(A='input', B='input', Y='output')),
        add=dict(type='$add', connections=dict(A=list(range(500, 543)), B=['0'] * 48,
            Y=list(range(400, 448))), port_directions=dict(A='input', B='input', Y='output')))
    return dict(modules={audit.TOP: dict(ports=ports, cells=cells)})


class PinConeControls(unittest.TestCase):
    def test_independent_exact_operands_and_unused_controls(self):
        cone = audit.output_cone(fixture())
        self.assertEqual(audit.validate_positive(cone), cone)
        self.assertEqual(cone['input_dependencies'], dict(A=list(range(25)), B=list(range(18)), omitted=[]))

    def test_omitted_input_reaching_output_is_rejected(self):
        bad = fixture()
        bad['modules'][audit.TOP]['cells']['add']['connections']['B'][0] = 300
        cone = audit.output_cone(bad)
        self.assertEqual(cone['input_dependencies']['omitted'], [0])
        with self.assertRaisesRegex(AssertionError, 'Omitted primitive inputs'):
            audit.validate_positive(cone)

    def test_upper_a_bit_or_missing_operand_is_rejected(self):
        for mode in ('upper', 'missing'):
            bad = fixture()
            bits = bad['modules'][audit.TOP]['cells']['multiply']['connections']['A']
            if mode == 'upper': bits.append(125)
            else: bits.pop()
            with self.subTest(mode=mode), self.assertRaisesRegex(AssertionError, '25x18 operands'):
                audit.validate_positive(audit.output_cone(bad))

    def test_opaque_modules_stateful_or_unknown_cells_are_rejected(self):
        for kind in ('$dff', 'DSP48E1', '$unknown'):
            bad = fixture()
            bad['modules'][audit.TOP]['cells']['add']['type'] = kind
            with self.subTest(kind=kind), self.assertRaisesRegex(AssertionError, 'Stateful or unknown'):
                audit.validate_positive(audit.output_cone(bad))
        bad = fixture(); bad['modules']['DSP48E1'] = {}
        with self.assertRaisesRegex(AssertionError, 'flattened'):
            audit.output_cone(bad)

    def test_multiple_drivers_unparsed_directions_or_undriven_output_are_rejected(self):
        for mode in ('driver', 'direction', 'undriven'):
            bad = fixture(); module = bad['modules'][audit.TOP]
            if mode == 'driver':
                module['cells']['duplicate'] = deepcopy(module['cells']['add'])
            elif mode == 'direction':
                module['cells']['add']['port_directions']['B'] = 'inout'
            else:
                module['ports']['P']['bits'][0] = 999
            with self.subTest(mode=mode), self.assertRaises(AssertionError):
                audit.output_cone(bad)

    def test_declared_shapes_and_primitive_count_cannot_be_silently_changed(self):
        for mode in ('port', 'width', 'multiply'):
            bad = fixture(); module = bad['modules'][audit.TOP]
            if mode == 'port': module['ports']['extra'] = dict(direction='input', bits=[900])
            elif mode == 'width': module['ports']['P']['bits'].pop()
            else: module['cells']['multiply']['type'] = '$and'
            with self.subTest(mode=mode), self.assertRaises(AssertionError):
                audit.validate_positive(audit.output_cone(bad))


if __name__ == '__main__':
    unittest.main()
