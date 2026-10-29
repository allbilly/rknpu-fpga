"""Read-only graph augmentation controls, not HDL or physical acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import analyze_augmented_union_pairs as runner
from test_board_lut_pair import lut


def fixture():
    # a--b is legal but leaves u/v unpaired. u--a and b--v are legal;
    # u--b, a--v, and u--v all exceed five union variables.
    sets = {'a': [2, 3, 4, 5], 'b': [2, 3, 4, 6],
        'u': [2, 3, 5, 7], 'v': [2, 4, 6, 8]}
    cells = {n: lut('LUT4', pins, 20 + i, '0110100110010110') for i, (n, pins) in enumerate(sets.items())}
    module = dict(ports={'in': dict(direction='input', bits=list(range(2, 9))),
        'out': dict(direction='output', bits=list(range(20, 24)))}, cells=cells)
    fanins, function = runner.union_function(cells['a'], cells['b'])
    key = runner.key(function)
    return module, [dict(first='a', second='b', fanins=fanins, function_key=key,
        dedicated_o6_sinks={'O5': [], 'O6': []})], {key: function}


class AugmentedUnionControls(unittest.TestCase):
    def test_real_length_three_path_increases_matching_without_source_mutation(self):
        module, original, classes = fixture(); before = deepcopy(module)
        revised, functions, changes, stats = runner.augment(module, original, classes)
        self.assertEqual(module, before); self.assertEqual(stats['additional_pairs'], 1)
        self.assertEqual(len(revised), 2); self.assertEqual(len(changes), 1)
        self.assertEqual({frozenset((r['first'], r['second'])) for r in revised},
            {frozenset(('u', 'a')), frozenset(('b', 'v'))})
        runner.verify_proposals(module, revised, functions)

    def test_direct_o6_roles_prevent_illegal_augmentation(self):
        module, original, classes = fixture()
        module['cells']['carry'] = dict(type='CARRY4', connections={'S': [20, 22, '0', '0']},
            port_directions={'S': 'input'})
        original[0]['first'], original[0]['second'] = 'b', 'a'
        fanins, function = runner.union_function(module['cells']['b'], module['cells']['a'])
        key = runner.key(function); original[0].update(fanins=fanins, function_key=key,
            dedicated_o6_sinks={'O5': [], 'O6': [dict(cell='carry', kind='CARRY4', pin='S', index=0)]})
        revised, _, changes, _ = runner.augment(module, original, {key: function})
        self.assertEqual(changes, []); self.assertEqual(len(revised), 1)

    def test_reused_endpoints_missing_paths_and_changed_edges_rejected(self):
        for mutation in ('endpoint', 'removed', 'missing', 'duplicate', 'revised', 'illegal'):
            module, original, classes = fixture()
            revised, _, changes, _ = runner.augment(module, original, classes)
            if mutation == 'endpoint': changes[0]['added'][1][1] = 'u'
            elif mutation == 'removed': changes[0]['removed'] = ['u', 'v']
            elif mutation == 'missing': changes.clear()
            elif mutation == 'duplicate': changes += deepcopy(changes)
            elif mutation == 'revised': revised.pop()
            else: changes[0]['added'][0] = ['v', 'a']
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                runner.verify_augmentations(module, original, revised, changes)

    def test_correlated_input_lut_and_self_feeding_edge_are_not_added(self):
        module, original, classes = fixture()
        module['cells']['u']['connections']['I3'] = [2]
        self.assertEqual(runner.augment(module, original, classes)[2], [])
        module, original, classes = fixture()
        module['cells']['u']['connections']['I3'] = [20]
        self.assertEqual(runner.augment(module, original, classes)[2], [])

    def test_invalid_original_domain_or_double_used_original_rejected(self):
        module, original, classes = fixture()
        with self.assertRaises(AssertionError): runner.augment(module, original + original, classes)
        with self.assertRaises(AssertionError): runner.augment(module, original, {})


if __name__ == '__main__': unittest.main()
