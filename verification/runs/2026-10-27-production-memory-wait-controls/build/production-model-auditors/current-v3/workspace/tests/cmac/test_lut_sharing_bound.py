"""Exact small matching controls; not native placement or FPGA acceptance."""
from collections import Counter
from functools import lru_cache
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from lut_sharing_bound import sharing_bound

def exact_positions(nodes, whole=0):
    nodes = list(map(frozenset, nodes))
    @lru_cache(None)
    def matching(mask):
        if not mask:
            return 0
        first = (mask & -mask).bit_length() - 1
        rest = mask & ~(1 << first)
        best = matching(rest)
        for other in range(first + 1, len(nodes)):
            if rest & (1 << other) and len(nodes[first] | nodes[other]) <= 5:
                best = max(best, 1 + matching(rest & ~(1 << other)))
        return best
    return whole + len(nodes) - matching((1 << len(nodes)) - 1)

def bound(nodes, whole=0, positions=100):
    return sharing_bound(Counter(map(frozenset, nodes)), whole, positions)

class SharingBoundControl(unittest.TestCase):
    def test_competition_is_stronger_than_individual_neighbors(self):
        five = [{2, *range(10 + i * 4, 14 + i * 4)} for i in range(8)]
        result = bound(five + [{2}], positions=6)
        self.assertEqual(result['maximum_five_to_smaller_matching'], 1)
        self.assertEqual(result['minimum_cut_capacity'], 1)
        self.assertEqual(result['necessary_position_lower_bound'], 8)
        self.assertTrue(result['lower_bound_exceeds_device'])

    def test_group_counts_are_capacities_not_single_vertices(self):
        five = {2, 3, 4, 5, 6}
        result = bound([five] * 4 + [{2}] * 3)
        self.assertEqual(result['maximum_five_to_smaller_matching'], 3)
        self.assertLessEqual(result['necessary_position_lower_bound'], exact_positions([five] * 4 + [{2}] * 3))

    def test_residual_reassignment_finds_both_partners(self):
        nodes = [{2, 3, 4, 5, 6}, {2, 3, 4, 5, 7}, {2}, {6}]
        result = bound(nodes)
        self.assertEqual(result['maximum_five_to_smaller_matching'], 2)
        self.assertEqual(result['minimum_cut_capacity'], 2)
        self.assertLessEqual(result['necessary_position_lower_bound'], exact_positions(nodes))

    def test_identical_five_internal_pairs(self):
        result = bound([{2, 3, 4, 5, 6}] * 4)
        self.assertEqual(result['optimistic_independent_identical_five_pairs'], 2)
        self.assertEqual(result['necessary_position_lower_bound'], 2)

    def test_unshared_five_inputs(self):
        result = bound([{2, 3, 4, 5, 6}, {7, 8, 9, 10, 11}])
        self.assertEqual(result['necessary_position_lower_bound'], 2)

    def test_ignores_small_matching_conflicts_optimistically(self):
        result = bound([{2, 3, 4, 5}, {6, 7, 8, 9}])
        self.assertEqual(result['necessary_position_lower_bound'], 1)
        self.assertEqual(exact_positions([{2, 3, 4, 5}, {6, 7, 8, 9}]), 2)
        self.assertFalse(result['physical_fit_verified'])

    def test_whole_lut_inputs_are_not_eligible_partners(self):
        result = bound([{2, 3, 4, 5, 6}], whole=2)
        self.assertEqual(result['necessary_position_lower_bound'], 3)

    def test_invalid_or_unmodeled_profiles_fail(self):
        for groups, whole, positions in (({frozenset(range(2, 8)): 1}, 0, 100),
                ({frozenset({2}): True}, 0, 100), ({frozenset({2}): -1}, 0, 100),
                ({frozenset({1}): 1}, 0, 100), ({frozenset(): 1}, 0, 100), ({}, -1, 100), ({}, 0, 0)):
            with self.subTest(groups=groups, whole=whole, positions=positions), self.assertRaises(AssertionError):
                sharing_bound(groups, whole, positions)

    def test_250_seeded_exhaustive_full_relaxed_matchings(self):
        rng = random.Random(3588)
        for case in range(250):
            nodes = [set(rng.sample(range(2, 14), rng.randrange(1, 6))) for _ in range(rng.randrange(10))]
            whole = rng.randrange(3)
            with self.subTest(case=case):
                result = bound(nodes, whole)
                self.assertLessEqual(result['necessary_position_lower_bound'], exact_positions(nodes, whole))
                self.assertEqual(result['maximum_five_to_smaller_matching'], result['minimum_cut_capacity'])

if __name__ == '__main__':
    unittest.main()
