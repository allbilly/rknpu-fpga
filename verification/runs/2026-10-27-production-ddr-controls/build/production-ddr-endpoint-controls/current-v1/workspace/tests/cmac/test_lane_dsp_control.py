"""Binary proof-domain admission controls; fixtures are not FPGA proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import check_lane_dsp as runner


def graph():
    start = 2; ports = {}
    for name, width, direction in [('op_a', 16, 'input'), ('op_b', 16, 'input'),
            ('exp_sft', 4, 'input'), ('pair_nz', 1, 'input'), ('reference_lane', 32, 'output'),
            ('actual_lane', 32, 'output'), ('reference_tag', 8, 'output'), ('actual_tag', 8, 'output'),
            ('difference', 40, 'output'), ('mismatch', 1, 'output')]:
        ports[name] = dict(direction=direction, bits=list(range(start, start + width)))
        start += width
    return dict(modules={runner.TOP: dict(ports=ports, cells={'multiply': dict(type='$mul'),
        'comparison': dict(type='$gt')})})


class LaneDspProofControls(unittest.TestCase):
    def test_exact_fixture_graph_and_inputs_retained(self):
        value = graph(); before = deepcopy(value)
        self.assertEqual(runner.validate_graph(value), {'$mul': 1, '$gt': 1})
        self.assertEqual(value, before)

    def test_input_domain_output_width_and_sequential_or_assumption_mutations_rejected(self):
        for case in ('constant', 'coupled', 'input_width', 'output_width', 'library',
                'state', 'assumption', 'blackbox', 'missing_multiply', 'extra_multiply'):
            value = graph(); module = value['modules'][runner.TOP]
            if case == 'constant': module['ports']['op_a']['bits'][0] = '0'
            elif case == 'coupled': module['ports']['op_a']['bits'][0] = module['ports']['op_b']['bits'][0]
            elif case == 'input_width': module['ports']['exp_sft']['bits'].pop()
            elif case == 'output_width': module['ports']['difference']['bits'].pop()
            elif case == 'library': value['modules']['unexpected'] = dict(ports={}, cells={})
            elif case == 'missing_multiply': del module['cells']['multiply']
            elif case == 'extra_multiply': module['cells']['other'] = dict(type='$mul')
            else: module['cells']['bad'] = dict(type={'state': '$dff', 'assumption': '$assume', 'blackbox': 'unmodeled'}[case])
            with self.subTest(case=case), self.assertRaises(AssertionError): runner.validate_graph(value)

    def test_exact_one_bit_formal_negative_and_unknown_miter_refusal(self):
        source = (ROOT / 'tests/cmac/cmac_lane_dsp_miter.sv').read_text()
        changed = runner.sanity_miter(source)
        self.assertNotEqual(changed, source)
        self.assertEqual(changed.replace("actual_lane ^ 32'h00000001", 'actual_lane'), source)
        for value in ('missing', source + source):
            with self.assertRaises(AssertionError): runner.sanity_miter(value)

    def test_area_script_flattens_both_selected_lanes_without_disabling_dsp(self):
        for label in ('reference', 'actual'):
            top = 'cmac_lane_' + label + '_area'
            text = runner.area_script(runner.SOURCES, top, ROOT / 'build/unused-area.json')
            self.assertIn('synth_xilinx -family xc7 -top ' + top + ' -flatten -noiopad\n', text)
            self.assertIn('check -assert\n', text)
            self.assertNotIn('-nodsp', text)
        with self.assertRaises(AssertionError): runner.area_script([], 'unknown_top', 'unused.json')

    def test_area_signature_primitives_dsp_count_and_domain_mutations_rejected(self):
        top = 'cmac_lane_actual_area'; ports = {}; start = 2
        for direction, fields in [('input', runner.AREA_INPUTS), ('output', runner.AREA_OUTPUTS)]:
            for name, width in fields.items():
                ports[name] = dict(direction=direction, bits=list(range(start, start + width)))
                start += width
        value = dict(modules={top: dict(ports=ports, cells={
            'multiply': dict(type='DSP48E1'), 'logic': dict(type='LUT6')}),
            'DSP48E1': dict(attributes={'blackbox': '1'}),
            'LUT6': dict(attributes={'blackbox': '1'})})
        before = deepcopy(value)
        self.assertEqual(runner.validate_area(value, top, 1), {'DSP48E1': 1, 'LUT6': 1})
        self.assertEqual(value, before)
        for case in ('constant', 'coupled', 'input_width', 'output_width', 'direction',
                'lost_dsp', 'extra_dsp', 'lost_lut', 'hierarchy', 'unknown', 'nonblackbox', 'library_logic'):
            changed = deepcopy(value); module = changed['modules'][top]
            if case == 'constant': module['ports']['op_a']['bits'][0] = '0'
            elif case == 'coupled': module['ports']['op_a']['bits'][0] = module['ports']['op_b']['bits'][0]
            elif case == 'input_width': module['ports']['exp_sft']['bits'].pop()
            elif case == 'output_width': module['ports']['lane_sum']['bits'].pop()
            elif case == 'direction': module['ports']['lane_sum']['direction'] = 'input'
            elif case == 'lost_dsp': del module['cells']['multiply']
            elif case == 'extra_dsp': module['cells']['extra'] = dict(type='DSP48E1')
            elif case == 'lost_lut': del module['cells']['logic']
            elif case == 'hierarchy':
                module['cells']['retained_miter'] = dict(type=runner.TOP)
                changed['modules'][runner.TOP] = dict(cells={})
            elif case == 'unknown': module['cells']['unexpected'] = dict(type='unmodeled')
            elif case == 'nonblackbox': changed['modules']['DSP48E1']['attributes']['blackbox'] = '0'
            elif case == 'library_logic': changed['modules']['DSP48E1']['cells'] = {'bad': dict(type='$mul')}
            with self.subTest(case=case), self.assertRaises(AssertionError): runner.validate_area(changed, top, 1)


if __name__ == '__main__': unittest.main()
