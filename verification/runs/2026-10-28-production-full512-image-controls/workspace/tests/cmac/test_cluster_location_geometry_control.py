"""Exact typed location cases, not a full native or physical FPGA test."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/openxc7'))
from cluster_location_geometry import Grid, find_witness, geometry_key


def member(name, kind, x=0, y=0, z=0, absolute=False):
    return dict(name=name, type=kind, x=x, y=y, z=z, abs_z=absolute)


class ClusterLocationGeometryControls(unittest.TestCase):
    def test_root_relative_xyz_ignored_but_absolute_z_enforced(self):
        grid = Grid(1, 1, (0,), ({3: 'R', 5: 'R', 6: 'C'},))
        rows = [member('root', 'R', x=999, y=999, z=999), member('child', 'C', z=1)]
        self.assertTrue(find_witness(rows, grid)['compatible'])
        rows[0].update(abs_z=True, z=3)
        self.assertTrue(find_witness(rows, grid)['zero_proven'])
        rows[0]['z'] = 5
        self.assertEqual(find_witness(rows, grid)['locations'][0], (0, 0, 5, 'R'))

    def test_child_absolute_z_is_not_added_to_root(self):
        grid = Grid(1, 1, (0,), ({4: 'R', 1: 'C'},))
        rows = [member('root', 'R'), member('child', 'C', z=1, absolute=True)]
        self.assertTrue(find_witness(rows, grid)['compatible'])
        rows[1]['abs_z'] = False
        self.assertTrue(find_witness(rows, grid)['zero_proven'])

    def test_nonzero_xy_uses_real_neighbors_not_tile_type_only(self):
        grid = Grid(2, 2, (0, 1, 0, 0), ({2: 'R'}, {7: 'C'}))
        rows = [member('root', 'R'), member('child', 'C', x=1, z=7, absolute=True)]
        result = find_witness(rows, grid)
        self.assertEqual(result['locations'], [(0, 0, 2, 'R'), (1, 0, 7, 'C')])
        rows[1]['y'] = 1
        self.assertTrue(find_witness(rows, grid)['zero_proven'])

    def test_negative_xy_and_die_bounds(self):
        grid = Grid(1, 2, (1, 0), ({4: 'R'}, {5: 'C'}))
        rows = [member('root', 'R'), member('child', 'C', y=-1, z=1)]
        self.assertTrue(find_witness(rows, grid)['compatible'])
        rows[1]['y'] = -2
        self.assertTrue(find_witness(rows, grid)['zero_proven'])

    def test_internal_duplicate_bel_and_wrong_type_rejected(self):
        grid = Grid(1, 1, (0,), ({0: 'R', 1: 'C'},))
        rows = [member('root', 'R'), member('child', 'R')]
        self.assertTrue(find_witness(rows, grid)['zero_proven'])
        rows[1].update(type='wrong', z=1)
        self.assertTrue(find_witness(rows, grid)['zero_proven'])

    def test_only_actual_used_tile_types_are_candidates(self):
        grid = Grid(1, 1, (0,), ({0: 'R'}, {0: 'R', 1: 'C'}))
        rows = [member('root', 'R'), member('child', 'C', z=1)]
        self.assertTrue(find_witness(rows, grid)['zero_proven'])
        grid = Grid(2, 1, (0, 1), grid.bels)
        self.assertTrue(find_witness(rows, grid)['compatible'])

    def test_geometry_key_keeps_absolute_and_offsets_ignores_names_order(self):
        rows = [member('root', 'R'), member('a', 'A', y=1, z=2), member('b', 'B', z=3, absolute=True)]
        other = [member('different', 'R', x=88), rows[2], rows[1]]
        self.assertEqual(geometry_key(rows), geometry_key(other))
        changed = deepcopy(rows)
        changed[2]['abs_z'] = False
        self.assertNotEqual(geometry_key(rows), geometry_key(changed))

    def test_invalid_input_and_no_physical_scope(self):
        rows = [member('root', 'R')]
        for grid in (Grid(0, 1, (), ({0: 'R'},)), Grid(1, 1, (9,), ({0: 'R'},))):
            with self.assertRaises(AssertionError):
                find_witness(rows, grid)
        rows[0]['abs_z'] = 1
        with self.assertRaises(AssertionError):
            find_witness(rows, Grid(1, 1, (0,), ({0: 'R'},)))
        rows[0]['abs_z'] = False
        result = find_witness(rows, Grid(1, 1, (0,), ({0: 'R'},)))
        self.assertFalse(result['occupancy_or_fixed_bels_checked'])
        self.assertFalse(result['control_sets_or_timing_checked'])
        self.assertFalse(result['physical_fit_verified'])


if __name__ == '__main__':
    unittest.main()
