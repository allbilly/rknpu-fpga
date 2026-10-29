"""Boolean proof admission controls, not arithmetic or FPGA proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import prove_lane_dsp_boolean as runner
from test_lane_dsp_control import graph


class LaneDspBooleanControls(unittest.TestCase):
    def test_whole_graph_direct_aig_lowering_has_no_selection_or_constraints(self):
        script = runner.boolean_lowering_script(Path('/tmp/input with spaces.json'), Path('/tmp/out.json'))
        self.assertEqual(script.splitlines(), [
            'read_json "/tmp/input with spaces.json"', 'techmap', 'opt -full',
            'aigmap', 'opt_clean', 'check -assert', 'write_json "/tmp/out.json"'])

    def test_exact_free_input_domain_and_gate_only_view(self):
        value = graph(); value['modules'][runner.TOP]['cells'] = {
            'gate': dict(type='$_AND_'), 'invert': dict(type='$_NOT_')}
        before = deepcopy(value)
        self.assertEqual(runner.validate_boolean_graph(value), {'$_AND_': 1, '$_NOT_': 1})
        self.assertEqual(value, before)

    def test_constant_coupled_ports_widths_library_state_or_assumptions_rejected(self):
        for case in ('constant', 'coupled', 'input_width', 'output_width', 'library', 'state', 'assumption', 'unknown', 'word_multiply'):
            value = graph(); module = value['modules'][runner.TOP]
            module['cells'] = {'gate': dict(type='$_AND_')}
            if case == 'constant': module['ports']['op_a']['bits'][0] = '0'
            elif case == 'coupled': module['ports']['op_a']['bits'][0] = module['ports']['op_b']['bits'][0]
            elif case == 'input_width': module['ports']['op_b']['bits'].pop()
            elif case == 'output_width': module['ports']['difference']['bits'].pop()
            elif case == 'library': value['modules']['extra'] = dict(cells={})
            else: module['cells']['unexpected'] = dict(type={
                'state': '$_DFF_P_', 'assumption': '$assume', 'unknown': 'unmodeled', 'word_multiply': '$mul'}[case])
            with self.subTest(case=case), self.assertRaises(AssertionError): runner.validate_boolean_graph(value)


if __name__ == '__main__': unittest.main()
