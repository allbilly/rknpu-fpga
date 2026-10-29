"""Component-domain admission controls, not actual SAT lemma evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import prove_lane_dsp_components as runner


def graph(top):
    inputs, width, conditional = runner.DOMAINS[top]; offset = 2; ports = {}
    for name, size in inputs.items():
        ports[name] = dict(direction='input', bits=list(range(offset, offset + size))); offset += size
    for name, size in [('difference', width), ('mismatch', 1)] + ([('sum_overflow', 1)] if conditional else []):
        ports[name] = dict(direction='output', bits=list(range(offset, offset + size))); offset += size
    cells = {'adder': {'type': '$add'}}
    if conditional:
        binary = lambda number: format(number, '032b')
        cells['guard'] = dict(type='$logic_and', parameters={name: binary(number) for name, number in
            {'A_SIGNED': 0, 'B_SIGNED': 0, 'A_WIDTH': 1, 'B_WIDTH': 1, 'Y_WIDTH': 1}.items()},
            port_directions={'A': 'input', 'B': 'input', 'Y': 'output'},
            connections={'A': [100000], 'B': [100001], 'Y': ports['mismatch']['bits']})
        for name, kind, source, size, bit in [('not_overflow', '$logic_not', 'sum_overflow', 1, 100000),
                ('any_difference', '$reduce_or', 'difference', width, 100001)]:
            cells[name] = dict(type=kind, parameters={key: binary(value) for key, value in
                {'A_SIGNED': 0, 'A_WIDTH': size, 'Y_WIDTH': 1}.items()},
                port_directions={'A': 'input', 'Y': 'output'},
                connections={'A': ports[source]['bits'], 'Y': [bit]})
    return {'modules': {top: dict(ports=ports, cells=cells)}}


class ComponentProofControls(unittest.TestCase):
    def test_exact_independent_binary_domains(self):
        self.assertEqual([sum(d[0].values()) for d in runner.DOMAINS.values()], [19, 120, 128, 16, 67])
        for top in runner.DOMAINS:
            original = graph(top); runner.validate_graph(original, top)
            changed = deepcopy(original)
            name = next(iter(runner.DOMAINS[top][0])); changed['modules'][top]['ports'][name]['bits'][0] = '0'
            with self.subTest(top=top), self.assertRaises(AssertionError): runner.validate_graph(changed, top)

    def test_assumptions_state_blackboxes_and_full_mul_rejected(self):
        top = next(iter(runner.DOMAINS))
        for kind in ('$assume', '$dff', '$memrd', '$mul', 'donor_blackbox'):
            changed = graph(top); changed['modules'][top]['cells']['unmodeled'] = {'type': kind}
            with self.subTest(kind=kind), self.assertRaises(AssertionError): runner.validate_graph(changed, top)

    def test_overflow_condition_is_explicit_not_full_lane_claim(self):
        top = 'cmac_discarded_carry_lemma'; original = graph(top); runner.validate_graph(original, top)
        self.assertTrue(runner.DOMAINS[top][2])
        original['modules'][top]['ports'].pop('sum_overflow')
        with self.assertRaises(AssertionError): runner.validate_graph(original, top)
        text = runner.MITERS.read_text()
        self.assertIn('assign mismatch = !sum_overflow && (|difference);', text)
        self.assertNotIn('$assume', text)

    def test_real_countermodel_and_actual_success_required(self):
        failure = 'SAT proof finished - model found: FAIL!\nCalled with -verify and proof did fail!'
        success = 'SAT proof finished - no model found: SUCCESS!'
        runner.validate_sat(failure, 1, True); runner.validate_sat(success, 0, False)
        for text, code, negative in [(failure, 0, True), ('tool missing', 1, True),
                (success, 1, False), ('timeout', 0, False), ('Warning: invalid\n'+success, 0, False)]:
            with self.subTest(text=text), self.assertRaises(AssertionError): runner.validate_sat(text, code, negative)

    def test_only_exact_source_bound_no_overflow_guard_is_admitted(self):
        top = 'cmac_discarded_carry_lemma'; original = graph(top); runner.validate_graph(original, top)
        for mutation in ('width', 'target', 'predicate', 'reduction', 'extra', 'other_top'):
            changed = deepcopy(original); module = changed['modules'][top]; cells = module['cells']
            if mutation == 'width': cells['guard']['parameters']['A_WIDTH'] = format(2, '032b')
            elif mutation == 'target': cells['guard']['connections']['Y'] = [123456]
            elif mutation == 'predicate': cells['not_overflow']['connections']['A'] = module['ports']['row_a']['bits'][:1]
            elif mutation == 'reduction': cells['any_difference']['connections']['A'].pop()
            elif mutation == 'extra': cells['extra_guard'] = deepcopy(cells['guard'])
            else:
                changed = graph('cmac_booth_recoding_lemma')
                changed['modules']['cmac_booth_recoding_lemma']['cells']['guard'] = deepcopy(cells['guard'])
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                runner.validate_graph(changed, 'cmac_booth_recoding_lemma' if mutation == 'other_top' else top)


if __name__ == '__main__': unittest.main()
