"""Fail-closed DSP board admission/marker controls, not board simulation."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import replay_dsp_board as runner


def commands(labels, negative=()):
    return [dict(log=n + '.log', status='PASS', returncode=int(n in negative)) for n in labels]


def native_report():
    return dict(status='PASS_FULL_C32K16_DSP_ARRAY_NATIVE_FIXTURES_ONLY', stage='complete',
        finished_utc='CONTROL_ONLY', native_array_fixture_acceptance=True,
        channels=32, kernels=16, parallel_products=512, frames=208, expected_outputs=3328,
        seed='0x35883216', expected_result=runner.native.EXPECTED, result=runner.native.EXPECTED,
        commands=commands(('iverilog_version', 'vvp_version', 'compile', 'negative_test', 'actual_test'), ('negative_test',)),
        **{n: False for n in (*runner.UNPROVEN, 'raw_board_numerical_acceptance', 'binary_lane_sum_equivalence')})


def prepared_report():
    return dict(status='PREPARED_COMPILED_FULL_C32K16_DSP_RAW_BOARD_ONLY', stage='complete',
        finished_utc='CONTROL_ONLY', channels=32, kernels=16, parallel_products=512,
        compiled_hierarchy={'rk_cmac_fp16_cell_dsp': 16, 'rk_cmac_fp16_lane_dsp': 512},
        commands=commands(('rom_check', 'version', 'compile')),
        **{n: False for n in ('native_array_fixture_acceptance', 'raw_board_numerical_acceptance',
            'mapped_array_numerical_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')})


def proof_report():
    return dict(status='PASS_COMPOSED_BINARY_LANE_SUM_TAG_CERTIFICATE_ONLY', stage='complete',
        finished_utc='CONTROL_ONLY', relevant_binary_input_bits=37, compared_binary_output_bits=40,
        commands=commands(('version', 'actual_lowering', 'negative_lowering', 'negative_sat'), ('negative_sat',)),
        **{n: True for n in ('binary_lane_sum_equivalence', 'composed_lane_proof',
            'candidate_multiply_binding_proved', 'shift_compensation_binding_proved')},
        **{n: False for n in ('new_positive_monolithic_sat_proof', 'full_array_numerical_acceptance',
            'raw_board_numerical_acceptance', 'isolated_mapped_binary_fixture_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')})


def marker(mode):
    good = mode in (0, 3, 4, 5, 6)
    checked, cmds, reads, writes, acks = ((4096, 196, 6528, 64, 64) if good else
        (0, 1, 0, 0, 0) if mode == 1 else (0, 196, 20, 0, 0) if mode == 8 else (1, 196, 6528, 64, 64))
    return (f'PASS C32 K16 BRAM board RTL mode={mode} success={2 if mode == 6 else int(good)} '
        f'resets={int(mode in (3, 4, 5, 6))} faults={int(not good)} init=4096 check={checked} '
        f'cmd_reads={cmds} operand_reads={reads} writes={writes} acks={acks} cycles=90000; no physical FPGA test')


class DspBoardReplayControls(unittest.TestCase):
    def test_full_native_numerical_hold_reset_and_x_fault_gate(self):
        original = native_report(); runner.validate_native_metadata(original)
        mutations = [('status', 'RUNNING'), ('stage', 'simulation'), ('finished_utc', None),
            ('native_array_fixture_acceptance', False), ('channels', 8), ('kernels', 1),
            ('parallel_products', 32), ('frames', 1), ('expected_outputs', 16), ('seed', 'other'),
            ('expected_result', 'PASS other'), ('result', runner.native.EXPECTED.replace('faults=1', 'faults=0'))]
        mutations += [(n, True) for n in (*runner.UNPROVEN, 'raw_board_numerical_acceptance', 'binary_lane_sum_equivalence')]
        for field, value in mutations:
            changed = deepcopy(original); changed[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_native_metadata(changed)

    def test_preparation_is_full_compile_not_native_or_board_acceptance(self):
        original = prepared_report(); runner.validate_prepared_metadata(original)
        mutations = [('status', 'PASS'), ('channels', 8), ('kernels', 1), ('parallel_products', 1),
            ('compiled_hierarchy', {'rk_cmac_fp16_cell_dsp': 16, 'rk_cmac_fp16_lane_dsp': 511})]
        mutations += [(n, True) for n in ('native_array_fixture_acceptance', 'raw_board_numerical_acceptance',
            'mapped_array_numerical_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')]
        for field, value in mutations:
            changed = deepcopy(original); changed[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_prepared_metadata(changed)

    def test_actual_composition_domain_bindings_and_scope_are_required(self):
        original = proof_report(); runner.validate_composed_metadata(original)
        for field, value in [('status', 'RUNNING'), ('stage', 'lowering'), ('relevant_binary_input_bits', 16),
            ('compared_binary_output_bits', 1), ('candidate_multiply_binding_proved', False),
            ('shift_compensation_binding_proved', False), ('composed_lane_proof', False),
            ('new_positive_monolithic_sat_proof', True), ('full_array_numerical_acceptance', True)]:
            changed = deepcopy(original); changed[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_composed_metadata(changed)

    def test_missing_extra_reordered_failed_and_false_negative_commands_rejected(self):
        for factory, validator in ((native_report, runner.validate_native_metadata),
            (prepared_report, runner.validate_prepared_metadata), (proof_report, runner.validate_composed_metadata)):
            original = factory()
            for mutation in ('missing', 'extra', 'reordered', 'running', 'returncode', 'negative'):
                changed = deepcopy(original)
                if mutation == 'missing': changed['commands'].pop()
                elif mutation == 'extra': changed['commands'].append(deepcopy(changed['commands'][-1]))
                elif mutation == 'reordered': changed['commands'].reverse()
                elif mutation == 'running': changed['commands'][-1]['status'] = 'RUNNING'
                elif mutation == 'returncode': changed['commands'][0]['returncode'] = 1
                else:
                    step = next((s for s in changed['commands'] if s['returncode'] == 1), changed['commands'][-1])
                    step['returncode'] = 0 if step['returncode'] == 1 else 1
                with self.subTest(factory=factory.__name__, mutation=mutation), self.assertRaises(AssertionError): validator(changed)

    def test_all_nine_original_board_markers_and_fault_contracts(self):
        for mode in runner.MODES:
            text = marker(mode)
            self.assertEqual(runner.validate_board_result(text, 0, mode), text)
            for wrong in (text.replace('init=4096', 'init=1'), text.replace('cycles=90000', 'cycles=0'),
                text.replace(f'mode={mode}', f'mode={(mode + 1) % 9}'), text.replace('faults=', 'faults=1')):
                with self.subTest(mode=mode, wrong=wrong), self.assertRaises(AssertionError): runner.validate_board_result(wrong, 0, mode)

    def test_tool_errors_warnings_duplicate_results_and_wrong_exit_rejected(self):
        text = marker(0)
        for bad, code in ((text, 1), (text + '\nPASS other', 0), ('FATAL: mismatch\n' + text, 0),
            ('warning: unchecked input\n' + text, 0), ('ERROR: failed\n' + text, 0), ('sorry: unsupported\n' + text, 0)):
            with self.subTest(bad=bad), self.assertRaises(AssertionError): runner.validate_board_result(bad, code, 0)

    def test_four_state_x_mode_and_all_reset_fault_modes_cannot_be_dropped(self):
        tests = [dict(mode=m, status='PASS', result=marker(m)) for m in runner.MODES]
        runner.validate_suite(tests)
        for bad in (tests[:-1], [t for t in tests if t['mode'] != 7], list(reversed(tests)), tests + [tests[-1]]):
            with self.subTest(modes=[t['mode'] for t in bad]), self.assertRaises(AssertionError): runner.validate_suite(bad)
        bad = deepcopy(tests); bad[4]['status'] = 'RUNNING'
        with self.assertRaises(AssertionError): runner.validate_suite(bad)

    def test_every_nested_compile_execution_stimulus_and_source_binding_is_verified(self):
        manifests = [dict(files={str(i): 'CONTROL_ONLY'}, sha256=str(i)) for i in range(5)]
        report = dict(source=manifests[0], artifacts=manifests[1], compile_inputs=manifests[2],
            execution_inputs=manifests[3], nested=[dict(stimulus=manifests[4])])
        with patch.object(runner, 'verify_manifest') as verify:
            runner.verify_evidence(report)
            self.assertEqual(verify.call_count, 5)
            self.assertEqual([c.args[0] for c in verify.call_args_list], manifests)
        with patch.object(runner, 'verify_manifest', side_effect=AssertionError('stale')):
            with self.assertRaises(AssertionError): runner.verify_evidence(report)

    def test_actual_parent_paths_cannot_escape_the_workspace(self):
        self.assertEqual(runner.workspace_path('README.md'), ROOT / 'README.md')
        for name in ('/etc/passwd', '../tinygrad/README.md', 'build/NO_SUCH_CONTROL_REPORT.json'):
            with self.subTest(name=name), self.assertRaises(AssertionError): runner.workspace_path(name)


if __name__ == '__main__': unittest.main()
