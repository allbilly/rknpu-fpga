"""Native-array prerequisite/marker controls; not actual array simulation."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import test_dsp_array_native as runner


def leaf():
    labels = ['yosys_version', 'iverilog_version', 'vvp_version', 'datadir', 'export', 'roundtrip'] + [
        p + '_' + m + '_' + a for p in ('native', 'mapped') for m in ('negative', 'actual') for a in ('compile', 'test')]
    return dict(status='PASS_ISOLATED_ACTUAL_DSP_MAPPED_BINARY_FIXTURES_ONLY', stage='complete',
        isolated_mapped_binary_fixture_acceptance=True, relevant_binary_input_bits=37, compared_binary_output_bits=40,
        expected_comparisons_per_phase=135680, export_circuit_identity='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE',
        mapped_cells={'DSP48E1': 1}, results={'native_actual_test': runner.MARKER, 'mapped_actual_test': runner.MARKER},
        commands=[dict(log=n+'.log', status='PASS', returncode=1 if n.endswith('negative_test') else 0) for n in labels],
        **{n: False for n in ('binary_lane_sum_equivalence', 'full_array_numerical_acceptance',
            'raw_board_numerical_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')})


class DspArrayNativeControls(unittest.TestCase):
    def test_running_missing_or_misrepresented_leaf_acceptance_rejected(self):
        original = leaf(); runner.validate_leaf_metadata(original)
        for mutation in ('status', 'stage', 'mapped', 'dsp', 'count', 'marker', 'command', 'negative', 'formal', 'physical'):
            report = deepcopy(original)
            if mutation == 'status': report['status'] = 'RUNNING'
            elif mutation == 'stage': report['stage'] = 'mapped'
            elif mutation == 'mapped': report['isolated_mapped_binary_fixture_acceptance'] = False
            elif mutation == 'dsp': report['mapped_cells']['DSP48E1'] = 0
            elif mutation == 'count': report['expected_comparisons_per_phase'] = 1
            elif mutation == 'marker': report['results']['mapped_actual_test'] = 'PASS other'
            elif mutation == 'command': report['commands'].pop()
            elif mutation == 'negative': report['commands'][7]['returncode'] = 0
            elif mutation == 'formal': report['binary_lane_sum_equivalence'] = True
            else: report['physical_fit_verified'] = True
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError): runner.validate_leaf_metadata(report)

    def test_exact_full_c32k16_corpus_and_categories_are_required(self):
        report = dict(status='PASS_SIZED_CMAC_VECTOR_GENERATION', channels=32, kernels=16, frames=208, outputs=3328,
            seed='0x35883216', categories={'uniform_edges': 16, 'one_channel': 32, 'random_bits': 64,
                'random_finite': 64, 'masked_edges': 32})
        runner.validate_vectors(report)
        for field, value in [('channels', 8), ('kernels', 1), ('frames', 1), ('outputs', 16),
                ('seed', 'different'), ('categories', {})]:
            changed = dict(report, **{field: value})
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_vectors(changed)

    def test_exact_3328_outputs_hold_reset_and_x_fault_marker_required(self):
        self.assertEqual(runner.validate_result(runner.EXPECTED, 0), runner.EXPECTED)
        for text, code in [(runner.EXPECTED, 1), (runner.EXPECTED.replace('faults=1', 'faults=0'), 0),
                (runner.EXPECTED.replace('3328', '16'), 0), (runner.EXPECTED.replace('held_cycles=520', 'held_cycles=0'), 0),
                (runner.EXPECTED + '\nPASS other', 0)]:
            with self.subTest(text=text), self.assertRaises(AssertionError): runner.validate_result(text, code)

    def test_real_first_frame_negative_not_tool_failure_required(self):
        runner.validate_result('FATAL: sized array mismatch frame=0 got=0', 1, True)
        for text, code in [('sized array mismatch frame=1', 1), ('sized array mismatch frame=0', 2),
                ('missing vectors', 1), ('sized array mismatch frame=0\nPASS other', 1)]:
            with self.subTest(text=text), self.assertRaises(AssertionError): runner.validate_result(text, code, True)


if __name__ == '__main__': unittest.main()
