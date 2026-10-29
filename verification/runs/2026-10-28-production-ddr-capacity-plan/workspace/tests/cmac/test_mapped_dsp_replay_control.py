"""Bound replay admission controls; not numerical execution evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import replay_mapped_lane_dsp as runner


def report():
    steps = [dict(log=label+'.log', status='PASS', returncode=1 if label.endswith('negative_test') else 0)
        for label in runner.LABELS]
    steps[-1] = dict(log=runner.LABELS[-1]+'.log', status='FAIL', returncode=None, seconds=1800.264,
        argv=['vvp', '/tmp/fixture/mapped_actual.vvp', '+SAMPLES=4096'])
    return dict(status='FAIL', stage='mapped', finished_utc='2026-10-06T03:11:12Z',
        error="TimeoutExpired(['vvp', '/tmp/fixture/mapped_actual.vvp', '+SAMPLES=4096'], 1800)",
        relevant_binary_input_bits=37, compared_binary_output_bits=40, expected_comparisons_per_phase=135680,
        export_circuit_identity='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE',
        mapped_cells={'DSP48E1': 1}, results={'native_actual_test': runner.MARKER}, commands=steps,
        **{name: False for name in ('binary_lane_sum_equivalence', 'isolated_mapped_binary_fixture_acceptance',
            'full_array_numerical_acceptance', 'raw_board_numerical_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')})


class ReplayControls(unittest.TestCase):
    def test_only_terminal_actual_full_corpus_timeout_is_admitted(self):
        original = report(); runner.validate_parent(original)
        for key, value in [('status', 'RUNNING'), ('error', 'numerical mismatch'), ('finished_utc', None),
                ('stage', 'native'), ('expected_comparisons_per_phase', 32), ('isolated_mapped_binary_fixture_acceptance', True)]:
            changed = deepcopy(original); changed[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): runner.validate_parent(changed)

    def test_all_native_export_and_real_negative_stages_required(self):
        original = report()
        for mutation in ('native', 'negative', 'domain', 'identity', 'dsp', 'missing'):
            changed = deepcopy(original)
            if mutation == 'native': changed['results']['native_actual_test'] = 'PASS other'
            elif mutation == 'negative': changed['commands'][7]['returncode'] = 0
            elif mutation == 'domain': changed['relevant_binary_input_bits'] = 36
            elif mutation == 'identity': changed['export_circuit_identity'] = 'unknown'
            elif mutation == 'dsp': changed['mapped_cells']['DSP48E1'] = 0
            else: changed['commands'].pop(4)
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError): runner.validate_parent(changed)

    def test_timed_out_positive_not_inherited_or_relabelled(self):
        original = report(); inherited = runner.inherited_commands(original)
        self.assertEqual(len(inherited), 13)
        self.assertEqual([c['inherited_from_parent_command_index'] for c in inherited], list(range(13)))
        self.assertNotIn('mapped_actual_test', [Path(c['log']).stem for c in inherited])
        self.assertEqual(original['commands'][-1]['status'], 'FAIL')
        inherited[0]['status'] = 'changed'; self.assertEqual(original['commands'][0]['status'], 'PASS')

    def test_partial_or_successful_last_stage_cannot_be_used_as_timeout(self):
        for key, value in [('status', 'PASS'), ('returncode', 0), ('seconds', 10),
                ('argv', ['vvp', '/tmp/fixture/mapped_actual.vvp', '+SAMPLES=1'])]:
            changed = report(); changed['commands'][-1][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): runner.validate_parent(changed)


if __name__ == '__main__': unittest.main()
