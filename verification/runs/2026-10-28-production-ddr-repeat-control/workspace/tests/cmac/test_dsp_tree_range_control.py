"""Conditional tree-domain controls, not actual donor range/whole-lane proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import prove_lane_dsp_tree_ranges as runner


def graph(top):
    inputs, width, conditional = runner.DOMAINS[top]; assert conditional
    ports = {}; offset = 2; binary = lambda n: format(n, '032b')
    for name, size in inputs.items():
        ports[name] = dict(direction='input', bits=list(range(offset, offset + size))); offset += size
    for name, size in [('difference', width), ('mismatch', 1), ('sum_overflow', 1)]:
        ports[name] = dict(direction='output', bits=list(range(offset, offset + size))); offset += size
    cells = {'adder': {'type': '$add'}, 'guard': dict(type='$logic_and',
        parameters={n: binary(v) for n, v in {'A_SIGNED': 0, 'B_SIGNED': 0, 'A_WIDTH': 1,
            'B_WIDTH': 1, 'Y_WIDTH': 1}.items()}, port_directions={'A': 'input', 'B': 'input', 'Y': 'output'},
        connections={'A': [100000], 'B': [100001], 'Y': ports['mismatch']['bits']})}
    for name, kind, source, size, bit in [('not_overflow', '$logic_not', 'sum_overflow', 1, 100000),
            ('difference_reduction', '$reduce_or', 'difference', width, 100001)]:
        cells[name] = dict(type=kind, parameters={n: binary(v) for n, v in
            {'A_SIGNED': 0, 'A_WIDTH': size, 'Y_WIDTH': 1}.items()},
            port_directions={'A': 'input', 'Y': 'output'}, connections={'A': ports[source]['bits'], 'Y': [bit]})
    return {'modules': {top: dict(ports=ports, cells=cells)}}


class TreeRangeControls(unittest.TestCase):
    def test_full_integer_not_modular_output_widths_and_all_inputs(self):
        self.assertEqual([(sum(d[0].values()), d[1]) for d in runner.DOMAINS.values()], [(120, 25), (128, 33)])
        for top in runner.DOMAINS:
            original = graph(top); runner.validate_graph(original, top)
            changed = deepcopy(original); changed['modules'][top]['ports']['words']['bits'][0] = '0'
            with self.subTest(top=top), self.assertRaises(AssertionError): runner.validate_graph(changed, top)
            changed = deepcopy(original); changed['modules'][top]['ports']['difference']['bits'].pop()
            with self.subTest(top=top), self.assertRaises(AssertionError): runner.validate_graph(changed, top)

    def test_only_exact_explicit_overflow_and_full_difference_guard(self):
        for top in runner.DOMAINS:
            for mutation in ('overflow', 'reduction', 'output', 'extra', 'width'):
                changed = graph(top); module = changed['modules'][top]; cells = module['cells']
                if mutation == 'overflow': cells['not_overflow']['connections']['A'] = module['ports']['words']['bits'][:1]
                elif mutation == 'reduction': cells['difference_reduction']['connections']['A'] = module['ports']['words']['bits'][:runner.DOMAINS[top][1]]
                elif mutation == 'output': cells['guard']['connections']['Y'] = [123456]
                elif mutation == 'extra': cells['extra_guard'] = deepcopy(cells['guard'])
                else: cells['guard']['parameters']['A_WIDTH'] = format(2, '032b')
                with self.subTest(top=top, mutation=mutation), self.assertRaises(AssertionError): runner.validate_graph(changed, top)

    def test_no_assumptions_state_or_multiplier_abstractions(self):
        for top in runner.DOMAINS:
            for kind in ('$assume', '$dff', '$mul', '$memrd', 'blackbox_arithmetic'):
                changed = graph(top); changed['modules'][top]['cells']['unexpected'] = {'type': kind}
                with self.subTest(top=top, kind=kind), self.assertRaises(AssertionError): runner.validate_graph(changed, top)

    def test_actual_sat_negative_and_success_are_required(self):
        failure = 'SAT proof finished - model found: FAIL!\nCalled with -verify and proof did fail!'
        success = 'SAT proof finished - no model found: SUCCESS!'
        runner.validate_sat(failure, 1, True); runner.validate_sat(success, 0, False)
        for text, code, negative in [('tool failure', 1, True), (failure, 0, True),
                (success, 1, False), ('timeout', 0, False)]:
            with self.subTest(text=text), self.assertRaises(AssertionError): runner.validate_sat(text, code, negative)


if __name__ == '__main__': unittest.main()
