"""Shared full-board runner guards; host tests, not actual HDL execution."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/cmac'), str(ROOT / 'tools/openxc7'), str(Path(__file__).parent)]
import test_prefix_shared_observed_board as runner
import test_dsp_prefix_observed_mapped_board_control as existing

ExistingReplayControls = existing.PrefixObservedMappedBoardControls


def prepared():
    report = dict(status=runner.preparation.PREPARED, stage='complete', finished_utc='test-fixture-only',
        channels=32, kernels=16, parallel_products=512, intended_part='xc7k480tffg1156-2',
        intended_clock_period_ns=20, seed=3588, modes=list(range(9)), physical_primitive_counts=runner.COUNTS,
        configurations=dict(kernel_dsp_configurations=32, shell_dsp_configurations=3,
            physical_cmac_dsps=512, total_physical_dsps=515, shared_combinational_cells=981,
            shared_module_omitted_from_execution=False, DSP_configuration_view_only=True),
        observation_signal_count=22, upstream_model_commit=runner.models.COMMIT,
        production_source_before='test-only', production_source_after='test-only', counter_timing_qualifiers=[{}] * 4,
        unchanged_writes=str(runner.original.WRITES), unchanged_reads=str(runner.original.READS),
        commands=[dict(label=n, status='PASS_TOOL_OR_SOFTWARE_CONTROL_ONLY', returncode=0)
                  for n in ('software_controls', 'generated_check', 'yosys_version', 'iverilog_version',
                            'vvp_version', 'model_commit', 'model_clean')])
    report.update({n: True for n in ('default_global_startup_preserved', 'all_three_hardware_modules_preserved',
                                   'actual_full_literal_export_byte_identity', 'actual_full_wire_only_bench_binding')})
    report.update({n: False for n in (*runner.PHYSICAL_FLAGS, 'old_numerical_result_inherited',
        'full_board_compilation_executed', 'numerical_netlist_acceptance', 'runtime_CPU_arithmetic_or_layout_fixup',
        'counter_view_used_for_export_or_simulation', 'original_failure_relabelled')})
    return deepcopy(report)


def completed():
    commands = [dict(label='compile', status='PASS', returncode=0),
                dict(label='negative', status='PASS', returncode=1, result='REJECTED_EXACT_FIRST_OUTPUT_GOLDEN_BIT')]
    tests = []
    for mode in range(9):
        result = existing.result(mode).strip()
        commands.append(dict(label='mode' + str(mode), status='PASS', returncode=0, result=result))
        tests.append(dict(mode=mode, status='PASS', result=result))
    return commands, tests


class SharedNumericalRunnerControls(unittest.TestCase):
    def test_complete_own_full_target_and_exact_counts(self):
        report = prepared()
        runner.verify_prepared(report)
        self.assertEqual(sum(runner.COUNTS.values()), 488407)
        for key, value in (('status', 'RUNNING'), ('stage', 'compile'), ('finished_utc', None),
                           ('channels', 16), ('kernels', 8), ('parallel_products', 256),
                           ('intended_part', 'xc7a100t'), ('intended_clock_period_ns', 100), ('seed', 1),
                           ('modes', [0]), ('observation_signal_count', 21), ('upstream_model_commit', 'wrong'),
                           ('production_source_after', 'changed'), ('counter_timing_qualifiers', []),
                           ('physical_primitive_counts', {}), ('configurations', {}),
                           ('unchanged_writes', '/tmp/other-goldens'), ('unchanged_reads', '/tmp/other-commands')):
            changed = deepcopy(report)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                runner.verify_prepared(changed)

    def test_no_inherited_result_or_execution_view_or_physical_pass(self):
        report = prepared()
        for key, value in report.items():
            if type(value) is not bool:
                continue
            changed = deepcopy(report)
            changed[key] = not value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                runner.verify_prepared(changed)
        for key, value in (('shared_combinational_cells', 0), ('physical_cmac_dsps', 256),
                           ('shared_module_omitted_from_execution', True), ('DSP_configuration_view_only', False)):
            changed = deepcopy(report)
            changed['configurations'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                runner.verify_prepared(changed)

    def test_all_preparation_commands_completed(self):
        for key, value in (('status', 'RUNNING'), ('returncode', 1), ('label', 'compile')):
            report = prepared()
            report['commands'][-1][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                runner.verify_prepared(report)
        report = prepared()
        report['commands'].pop()
        with self.assertRaises(AssertionError):
            runner.verify_prepared(report)

    def test_execution_path_confined_and_bytes_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            inside, outside = folder / 'own-input', folder / 'outside'
            inside.mkdir()
            for path in (inside / 'file.v', outside):
                path.write_text('test fixture only\n')
            selected = inside / 'file.v'
            manifest = {str(p): runner.digest(p) for p in (selected, outside)}
            self.assertEqual(runner.checked_file(selected, inside, manifest), selected)
            for path, bindings in ((outside, manifest), (selected, {}), (selected, {str(selected): '0' * 64})):
                with self.subTest(path=path, bindings=bindings), self.assertRaises(AssertionError):
                    runner.checked_file(path, inside, bindings)
            selected.write_text('changed fixture\n')
            with self.assertRaises(AssertionError):
                runner.checked_file(selected, inside, manifest)

    def test_all_nine_modes_and_actual_negative_required(self):
        commands, tests = completed()
        runner.full_result(commands, tests)
        for index in range(len(commands)):
            changed = deepcopy(commands)
            changed.pop(index)
            with self.subTest(missing=index), self.assertRaises(AssertionError):
                runner.full_result(changed, tests)
        for index in range(len(tests)):
            changed = deepcopy(tests)
            changed.pop(index)
            with self.subTest(missing_mode=index), self.assertRaises(AssertionError):
                runner.full_result(commands, changed)
        with self.assertRaises(AssertionError):
            runner.full_result(commands + [commands[-1]], tests)

    def test_no_green_compile_only_running_or_wrong_negative(self):
        commands, tests = completed()
        for index, key, value in ((0, 'status', 'RUNNING'), (0, 'returncode', 1),
                                   (1, 'returncode', 0), (1, 'result', 'OTHER_FAILURE'),
                                   (2, 'status', 'RUNNING'), (2, 'returncode', 1)):
            changed = deepcopy(commands)
            changed[index][key] = value
            with self.subTest(index=index, key=key), self.assertRaises(AssertionError):
                runner.full_result(changed, tests)
        with self.assertRaises(AssertionError):
            runner.full_result(commands[:1], [])

    def test_results_rechecked_against_unchanged_mode_oracle(self):
        commands, tests = completed()
        for result in (existing.result(0).replace('init=4096', 'init=1').strip(),
                       existing.result(0).strip() + '\nwarning: ignored'):
            changed, altered = deepcopy(commands), deepcopy(tests)
            changed[2]['result'] = altered[0]['result'] = result
            with self.subTest(result=result), self.assertRaises(AssertionError):
                runner.full_result(changed, altered)


if __name__ == '__main__':
    unittest.main()
