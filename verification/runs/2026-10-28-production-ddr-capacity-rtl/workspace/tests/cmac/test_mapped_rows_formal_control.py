"""Synthetic proof-graph safety checks, not formal or physical evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
from prove_fixed_rows_mapped import TOP, check_boolean_design, sanity_miter


class MappedRowsFormalControls(unittest.TestCase):
    def fixture(self):
        widths = {'clk': 1, 'rst_n': 1, 'pair_nz': 1, 'op_a': 16, 'op_b': 16, 'exp_sft': 4}
        ports, start = {}, 2
        for name, width in widths.items():
            ports[name] = dict(direction='input', bits=list(range(start, start+width)))
            start += width
        ports['difference'] = dict(direction='output', bits=[0]*72)
        ports['mismatch'] = dict(direction='output', bits=[0])
        for name, width in {'reference_a': 32, 'reference_b': 32, 'mapped_a': 32,
                            'mapped_b': 32, 'reference_tag': 8, 'mapped_tag': 8}.items():
            ports[name] = dict(direction='output', bits=[0]*width)
        return {'modules': {TOP: {'ports': ports, 'cells': {'gate': {'type': '$_AND_'}}}}}

    def test_binary_only_graph_is_accepted_without_mutation(self):
        graph = self.fixture()
        before = deepcopy(graph)
        self.assertEqual(check_boolean_design(graph), {'$_AND_': 1})
        self.assertEqual(graph, before)

    def test_assumptions_state_and_unmodeled_cells_are_rejected(self):
        for kind in ('$assume', '$dff', 'FDCE', 'unknown_multiplier', 'LUT6'):
            with self.subTest(kind=kind):
                graph = self.fixture()
                graph['modules'][TOP]['cells']['bad'] = {'type': kind}
                with self.assertRaises(AssertionError): check_boolean_design(graph)

    def test_unflattened_blackbox_is_rejected(self):
        graph = self.fixture()
        graph['modules']['unknown_arithmetic'] = {'attributes': {'blackbox': '1'}}
        with self.assertRaises(AssertionError): check_boolean_design(graph)

    def test_reduced_or_constant_input_domain_is_rejected(self):
        for change in ('short_operand', 'constant_operand', 'extra_input'):
            with self.subTest(change=change):
                graph = self.fixture()
                ports = graph['modules'][TOP]['ports']
                if change == 'short_operand': ports['op_a']['bits'].pop()
                elif change == 'constant_operand': ports['op_a']['bits'][0] = '0'
                else: ports['mode'] = dict(direction='input', bits=[999])
                with self.assertRaises(AssertionError): check_boolean_design(graph)

    def test_all_seventy_two_comparison_bits_are_required(self):
        graph = self.fixture()
        graph['modules'][TOP]['ports']['difference']['bits'].pop()
        with self.assertRaises(AssertionError): check_boolean_design(graph)

    def test_coupled_input_variables_are_rejected(self):
        graph = self.fixture()
        ports = graph['modules'][TOP]['ports']
        ports['op_b']['bits'][0] = ports['op_a']['bits'][0]
        with self.assertRaises(AssertionError): check_boolean_design(graph)

    def test_complete_reference_and_mapped_outputs_are_required(self):
        graph = self.fixture()
        graph['modules'][TOP]['ports']['mapped_b']['bits'].pop()
        with self.assertRaises(AssertionError): check_boolean_design(graph)

    def test_sanity_mutation_changes_only_the_comparison(self):
        source = (ROOT / 'tests/cmac/cmac_fixed_rows_mapped_miter.sv').read_text()
        changed = sanity_miter(source)
        self.assertEqual(changed.replace("reference_tag ^ mapped_tag ^ 8'h01};",
                                         'reference_tag ^ mapped_tag};'), source)
        self.assertEqual(changed.count("reference_tag ^ mapped_tag ^ 8'h01};"), 1)
        with self.assertRaises(AssertionError): sanity_miter('changed comparison')


if __name__ == '__main__':
    unittest.main()
