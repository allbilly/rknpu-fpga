"""Necessary-bound reader controls; never a fit or a new numerical result."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'tools/openxc7')]
from packed_lut_bound import LUTInputs, physical_positions
from pack_prefix_shared_board import native_census, QUALIFICATION, TOP


def lut(width, bits=None):
    bits = list(range(2, 2 + width)) if bits is None else bits
    attrs = dict(X_ORIG_TYPE='LUT' + str(width), X_ORIG_PORT_O6='O')
    attrs.update({'X_ORIG_PORT_A' + str(i + 1): 'I' + str(i) for i in range(width)})
    connections = {'A' + str(i + 1): [bit] for i, bit in enumerate(bits)}
    connections['O6'] = [50]
    directions = {name: 'input' for name in connections}
    directions['O6'] = 'output'
    return dict(type='SLICE_LUTX', parameters={'INIT': '0' * (1 << width)}, attributes=attrs,
                connections=connections, port_directions=directions)


class PackedLUTBound(unittest.TestCase):
    def test_plain_groups_and_no_input_mutation(self):
        cell = lut(3)
        before = deepcopy(cell)
        collector = LUTInputs()
        collector.observe(cell)
        self.assertEqual(cell, before)
        measured = collector.bound(1, 1)
        self.assertEqual(measured['necessary_position_lower_bound'], 1)
        self.assertEqual(collector.groups, {frozenset((2, 3, 4)): 1})
        self.assertFalse(measured['physical_fit_verified'])
        self.assertFalse(measured['hardware_execution_input_changed'])

    def test_identical_five_groups_can_relax_to_one_position(self):
        collector = LUTInputs()
        collector.observe(lut(5))
        collector.observe(lut(5))
        self.assertEqual(collector.bound(2, 1)['necessary_position_lower_bound'], 1)

    def test_six_connected_pins_are_whole_even_with_duplicate_nets(self):
        collector = LUTInputs()
        collector.observe(lut(6, [2] * 6))
        self.assertEqual(collector.whole, 1)
        self.assertEqual(collector.groups, {})
        self.assertEqual(collector.bound(1, 1)['whole_input_LUTs'], 1)

    def test_dual_output_and_memory_modes_rejected(self):
        cell = lut(3)
        cell['connections']['O5'] = [51]
        cell['port_directions']['O5'] = 'output'
        cell['attributes']['X_ORIG_PORT_O5'] = 'O'
        with self.assertRaises(AssertionError):
            LUTInputs().observe(cell)
        for attribute in ('X_LUT_AS_SRL', 'X_LUT_AS_DRAM'):
            cell = lut(3)
            cell['attributes'][attribute] = '0'
            with self.assertRaises(AssertionError):
                LUTInputs().observe(cell)

    def test_non_net_or_boolean_input_rejected(self):
        for bit in ('0', 'x', 0, 1, True):
            with self.assertRaises(AssertionError):
                LUTInputs().observe(lut(1, [bit]))

    def test_missing_logical_input_changed_init_or_unknown_port_rejected(self):
        cells = [lut(3) for _ in range(3)]
        cells[0]['attributes'].pop('X_ORIG_PORT_A1')
        cells[1]['parameters']['INIT'] = 'not-binary'
        cells[2]['connections']['UNKNOWN'] = [9]
        cells[2]['port_directions']['UNKNOWN'] = 'input'
        for cell in cells:
            with self.assertRaises(AssertionError):
                LUTInputs().observe(cell)

    def test_incomplete_total_census_rejected(self):
        collector = LUTInputs()
        collector.observe(lut(3))
        with self.assertRaises(AssertionError):
            collector.bound(2, 1)

    def test_actual_capacity_report_required_without_percent_assumption(self):
        line = 'Info:       SLICE_LUTX:    431206/ 597200    72%\n'
        self.assertEqual(physical_positions(line, 431206), 298600)
        for text, count in (('', 431206), (line + line, 431206), (line, 431205),
                            (line.replace('597200', '597202'), 431206)):
            with self.assertRaises(AssertionError):
                physical_positions(text, count)

    def test_complete_saved_small_native_observer(self):
        report = json.loads(QUALIFICATION.read_text())
        design = json.loads((QUALIFICATION.parent / 'test-only-config-input.json').read_text())
        selected = {n: c for n, c in design['modules'][TOP]['cells'].items() if c['type'] in ('DSP48E1', 'RAMB36E1')}
        collector = LUTInputs()
        census, primitives = native_census(QUALIFICATION.parent / 'clock-admitted-packed.json', selected,
                                          report['native_version'], collector.observe)
        self.assertEqual(set(primitives), set(selected))
        measured = collector.bound(census['primitive_counts']['SLICE_LUTX'], 298600)
        self.assertEqual(measured['lut_cells'], census['primitive_counts']['SLICE_LUTX'])
        self.assertFalse(measured['native_placement_executed'])


if __name__ == '__main__':
    unittest.main()
