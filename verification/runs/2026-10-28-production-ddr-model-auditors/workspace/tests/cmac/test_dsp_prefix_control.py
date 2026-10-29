"""Isolated prefix harness controls, not numerical or FPGA acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import test_dsp_prefix_carry as runner


def graph_fixture():
    ports = {}; bit = 2
    for name, direction, width in (('first_row', 'input', 32), ('total', 'input', 32),
        ('shift', 'input', 3), ('reference_carry', 'output', 1),
        ('actual_carry', 'output', 1), ('mismatch', 'output', 1)):
        ports[name] = dict(direction=direction, bits=list(range(bit, bit + width)))
        bit += width
    selector = dict(type='$shiftx', parameters={k: f'{v:032b}' for k, v in {
        'A_SIGNED': 0, 'A_WIDTH': 8, 'B_SIGNED': 0, 'B_WIDTH': 3, 'Y_WIDTH': 1}.items()},
        port_directions={'A': 'input', 'B': 'input', 'Y': 'output'},
        connections={'A': ['0', *range(100, 107)], 'B': ports['shift']['bits'][:],
            'Y': ports['actual_carry']['bits'][:]})
    return {'modules': {runner.TOP: dict(ports=ports, cells={'selection': selector})}}


def known_notices():
    donor = runner.lane.SOURCES[0]
    return '\n'.join([
        f'Warning: Replacing memory \\temp_array with list of registers. See {donor}:41, {donor}:33',
        f'Warning: Replacing memory \\input_array with list of registers. See {donor}:33, {donor}:28'] * 3) + (
        '\nABC: + scorr \nABC: Warning: The network is combinational (run "fraig" or "fraig_sweep").\nABC: + dc2 ')


class PrefixControls(unittest.TestCase):
    def test_candidate_has_only_the_three_audited_text_changes(self):
        runner.validate_sources()
        original = runner.lane.SOURCES[3].read_text()
        self.assertEqual(runner.candidate_source(original), runner.CANDIDATE.read_text())
        for old in ('module rk_cmac_fp16_lane_dsp (',
            "    wire [31:0] low_mask = (32'h00000001 << shift_amount) - 32'd1;\n",
            '    wire discarded_carry = (original_row_a & low_mask) > (biased_sum & low_mask);'):
            with self.subTest(old=old), self.assertRaises(AssertionError):
                runner.candidate_source(original.replace(old, '', 1))

    def test_comparator_domain_retains_all_67_independent_binary_inputs(self):
        good = graph_fixture(); original = deepcopy(good)
        self.assertEqual(runner.validate_graph(good), {'$shiftx': 1})
        self.assertEqual(good, original)
        for change in ('constant', 'alias', 'direction', 'width', 'port', 'hierarchy', 'output'):
            bad = deepcopy(good); ports = bad['modules'][runner.TOP]['ports']
            if change == 'constant': ports['total']['bits'][0] = '0'
            elif change == 'alias': ports['total']['bits'][0] = ports['first_row']['bits'][0]
            elif change == 'direction': ports['shift']['direction'] = 'output'
            elif change == 'width': ports['first_row']['bits'].pop()
            elif change == 'port': ports['hidden'] = dict(direction='input', bits=[150])
            elif change == 'hierarchy': bad['modules']['unused'] = dict(ports={}, cells={})
            else: ports['reference_carry']['bits'][0] = '0'
            with self.subTest(change=change), self.assertRaises(AssertionError): runner.validate_graph(bad)

    def test_state_assumptions_multiply_and_unmodeled_cells_are_rejected(self):
        for kind in ('$assume', '$assert', '$dff', '$adff', '$mul', '$mystery', 'blackbox'):
            bad = graph_fixture(); bad['modules'][runner.TOP]['cells']['hidden'] = dict(type=kind)
            with self.subTest(kind=kind), self.assertRaises(AssertionError): runner.validate_graph(bad)

    def test_unsigned_selector_width_range_wiring_and_constant_zero_are_audited(self):
        for change in ('missing', 'duplicate', 'signed_a', 'signed_b', 'a_width', 'b_width',
            'y_width', 'direction', 'index', 'output', 'prefix_width', 'prefix_zero', 'prefix_alias'):
            bad = graph_fixture(); cells = bad['modules'][runner.TOP]['cells']; c = cells['selection']
            if change == 'missing': cells.clear()
            elif change == 'duplicate': cells['second'] = deepcopy(c)
            elif change in ('signed_a', 'signed_b', 'a_width', 'b_width', 'y_width'):
                key = {'signed_a': 'A_SIGNED', 'signed_b': 'B_SIGNED', 'a_width': 'A_WIDTH',
                    'b_width': 'B_WIDTH', 'y_width': 'Y_WIDTH'}[change]
                c['parameters'][key] = f'{99:032b}'
            elif change == 'direction': c['port_directions']['B'] = 'output'
            elif change == 'index': c['connections']['B'][0] = 1234
            elif change == 'output': c['connections']['Y'][0] = 1234
            elif change == 'prefix_width': c['connections']['A'].pop()
            elif change == 'prefix_zero': c['connections']['A'][0] = '1'
            else: c['connections']['A'][2] = c['connections']['A'][1]
            with self.subTest(change=change), self.assertRaises(AssertionError): runner.validate_graph(bad)

    def test_only_exact_measured_donor_mapping_notices_are_admitted(self):
        good = known_notices()
        self.assertEqual(sum(runner.mapping_diagnostics(good).values()), 7)
        for bad in (good + '\nWarning: hidden optimization', good.replace(':41', ':42'),
            good.replace('NV_DW02_tree.v', 'other.v'), '\n'.join(good.splitlines()[1:]),
            good + '\n' + good.splitlines()[0], good.lower(), good + '\nERROR: failed',
            good + '\nFATAL: failed', good + '\nsorry: not implemented',
            good.replace('ABC: + scorr ', 'ABC: + other '),
            good.replace('ABC: + dc2 ', 'ABC: + other '), ''):
            with self.subTest(bad=bad[-100:]), self.assertRaises(AssertionError): runner.mapping_diagnostics(bad)

    def test_original_native_bench_has_full_count_seed_case_inequality_and_watchdog(self):
        text = runner.lane.BENCH.read_text()
        for fragment in ("reg [31:0] random_state = 32'h3588d501;", 'integer samples = 4096;',
            'reference_lane !== compared || reference_tag !== actual_tag',
            'comparisons != 4608 + 32 * samples', '#3000000; $fatal(1, "LANE_DSP_WATCHDOG")',
            'for(integer a = 0; a < 12;', 'for(integer b = 0; b < 12;',
            'for(integer s = 0; s < 16;', 'for(integer nz = 0; nz < 2;'):
            self.assertIn(fragment, text)
        self.assertEqual(4608 + 32 * 4096, 135680)
        self.assertEqual(runner.EXPECTED, 'PASS LANE_DSP_BINARY_FIXTURES comparisons=135680 seed=3588d501 samples=4096')


if __name__ == '__main__': unittest.main()
