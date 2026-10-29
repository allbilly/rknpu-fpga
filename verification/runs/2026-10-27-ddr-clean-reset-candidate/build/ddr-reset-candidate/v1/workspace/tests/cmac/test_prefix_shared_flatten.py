"""Small literal-expansion controls, not full packing or FPGA evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'tools/cmac'),
                str(Path(__file__).resolve().parents[2] / 'tools/openxc7'),
                str(Path(__file__).resolve().parent)]
import test_shared_kernel_cones as baseline
from prefix_shared_cones import lift, PRIVATE, SHARED, INSTANCE
from prefix_shared_flatten import flatten_shared


class PrefixSharedFlattenControl(unittest.TestCase):
    def fixture(self):
        original = dict(modules=baseline.SharedConeControls().fixture())
        original['modules']['top']['ports'] = {
            'data': dict(direction='input', bits=[100]),
            'weights': dict(direction='input', bits=[200, 201]),
            'results': dict(direction='output', bits=[300, 301])}
        candidate, _ = lift(original, 'top', 'kernel', 2)
        return dict(modules={n: candidate['modules'][n] for n in ('top', PRIVATE, SHARED)})

    def test_every_private_and_shared_cell_expanded_once_without_input_mutation(self):
        design = self.fixture()
        before = deepcopy(design)
        flat, audit = flatten_shared(design, 'top', PRIVATE, SHARED, 2)
        self.assertEqual(design, before)
        self.assertEqual(audit['cells'], {'LUT1': 5})
        self.assertEqual(audit['retained_private_instances'], ['k0', 'k1'])
        self.assertEqual(audit['retained_shared_instances'], [INSTANCE])
        self.assertEqual(set(flat['modules']['top']['cells']),
            {'k0.private', 'k1.private', INSTANCE + '.shared', INSTANCE + '.shared_next', INSTANCE + '.constant'})
        self.assertEqual(flat['modules']['top']['cells']['k0.private']['connections']['I0'], [200])
        self.assertEqual(flat['modules']['top']['cells']['k1.private']['connections']['I0'], [201])

    def test_shared_instance_missing_rejected(self):
        design = self.fixture()
        design['modules']['top']['cells'].pop(INSTANCE)
        with self.assertRaises(AssertionError):
            flatten_shared(design, 'top', PRIVATE, SHARED, 2)

    def test_private_multiplicity_change_rejected(self):
        design = self.fixture()
        with self.assertRaises(AssertionError):
            flatten_shared(design, 'top', PRIVATE, SHARED, 16)

    def test_unknown_nested_or_shell_hardware_rejected(self):
        for module in (PRIVATE, 'top'):
            design = self.fixture()
            cell = next(iter(design['modules'][module]['cells'].values()))
            cell['type'] = 'unmodeled'
            with self.assertRaises(AssertionError):
                flatten_shared(design, 'top', PRIVATE, SHARED, 2)

    def test_unknown_extra_implementation_rejected(self):
        design = self.fixture()
        design['modules']['extra'] = {}
        with self.assertRaises(AssertionError):
            flatten_shared(design, 'top', PRIVATE, SHARED, 2)

    def test_shared_bus_pin_width_change_rejected(self):
        design = self.fixture()
        design['modules']['top']['cells'][INSTANCE]['connections']['prefix_shared_nodes'].pop()
        with self.assertRaises(AssertionError):
            flatten_shared(design, 'top', PRIVATE, SHARED, 2)


if __name__ == '__main__':
    unittest.main()
