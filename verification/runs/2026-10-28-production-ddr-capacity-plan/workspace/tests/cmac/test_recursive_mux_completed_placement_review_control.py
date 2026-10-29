"""Prepared complete-output review controls; fixtures are not native evidence."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools')]
import review_recursive_mux_completed_placement as review


def completed_fixture():
    # Fabricated future terminal metadata only; no file/producer is rewritten.
    packed = json.loads((ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json').read_text())
    directory = ROOT / 'build/openxc7/test-only-completed-placement-fixture'
    argv = review.placement.NAMESPACE['placement_argv'](packed['executable']['path'], packed['execution_input'],
        directory / 'literal.xdc', directory / 'placed.json')
    report = dict(status=review.PARENT_FAILED, stage='native_place', error=review.PARENT_ERROR,
        finished_utc='test-only-terminal-fixture', channels=32, kernels=16, parallel_products=512,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        executable=packed['executable'], native_packing_executed=True, native_placement_executed=True,
        original_prepared_input_repacked=True, native_source_or_executable_changed=True,
        only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent=True,
        counter_safe_HeAP_parent_retained=True, old_native_result_inherited=False,
        commands=[dict(label=label, status='PASS_TOOL_EXECUTION_ONLY', returncode=0,
                       pid=12345, timeout_seconds=43200, argv=argv if label == 'native_place' else [])
                  for label in review.LABELS])
    for flag in ('native_routing_executed', 'old_placement_reused', 'input_group_assignment_used',
                 'numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff',
                 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        report[flag] = False
    return report


class CompletedPlacementReviewControls(unittest.TestCase):
    def test_metadata_only_narrow_error_zero_native_code_fixture(self):
        report = completed_fixture(); before = deepcopy(report)
        self.assertIs(review.verify_parent_metadata(report), report['commands'][-1])
        self.assertEqual(report, before)

    def test_current_running_native_report_is_rejected(self):
        # Status under test is explicit, not dependent on a mutable live file.
        report = completed_fixture(); report['status'] = 'RUNNING'; report.pop('finished_utc')
        with self.assertRaises(AssertionError): review.verify_parent_metadata(report)

    def test_unrelated_failure_timeout_signal_or_wrong_stage_rejected(self):
        for field, bad in (('status', 'PASS'), ('status', 'FAIL_OTHER'), ('stage', 'complete'),
                           ('error', 'TimeoutExpired(native, 43200)'), ('error', 'SystemExit(143)'),
                           ('error', 'AssertionError()'), ('finished_utc', '')):
            changed = completed_fixture(); changed[field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(AssertionError): review.verify_parent_metadata(changed)

    def test_real_native_or_preflight_failure_never_admitted(self):
        for index in range(5):
            for field, bad in (('returncode', 1), ('returncode', -9), ('status', 'FAIL'), ('status', 'RUNNING')):
                changed = completed_fixture(); changed['commands'][index][field] = bad
                with self.subTest(index=index, field=field, bad=bad), self.assertRaises(AssertionError):
                    review.verify_parent_metadata(changed)

    def test_all_original_commands_and_budget_required(self):
        for labels in (review.LABELS[:-1], review.LABELS[::-1], review.LABELS + ['unknown']):
            changed = completed_fixture()
            changed['commands'] = [dict(changed['commands'][-1], label=label) for label in labels]
            with self.subTest(labels=labels), self.assertRaises(AssertionError): review.verify_parent_metadata(changed)
        changed = completed_fixture(); changed['commands'][-1]['timeout_seconds'] = 86400
        with self.assertRaises(AssertionError): review.verify_parent_metadata(changed)

    def test_full_target_part_clock_seed_not_reduced_or_changed(self):
        for field, bad in (('channels', 8), ('kernels', 1), ('parallel_products', 32),
                           ('intended_part', 'xc7a200tfbg484-1'), ('intended_clock_period_ns', 100), ('seed', 1)):
            changed = completed_fixture(); changed[field] = bad
            with self.subTest(field=field), self.assertRaises(AssertionError): review.verify_parent_metadata(changed)

    def test_no_old_result_or_physical_or_numerical_acceptance_in_parent(self):
        for field in ('native_routing_executed', 'old_placement_reused', 'input_group_assignment_used',
                      'numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff',
                      'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed',
                      'old_native_result_inherited'):
            changed = completed_fixture(); changed[field] = True
            with self.subTest(field=field), self.assertRaises(AssertionError): review.verify_parent_metadata(changed)

    def test_original_full_native_argv_no_shortcuts(self):
        for extra in ('--force', '--timing-allow-fail', '--no-place', '--pack-only'):
            changed = completed_fixture(); changed['commands'][-1]['argv'].append(extra)
            with self.subTest(extra=extra), self.assertRaises(AssertionError): review.verify_parent_metadata(changed)
        for flag, bad in (('--freq', '10'), ('--seed', '1'), ('--placer', 'static')):
            changed = completed_fixture(); argv = changed['commands'][-1]['argv']; argv[argv.index(flag) + 1] = bad
            with self.subTest(flag=flag), self.assertRaises(AssertionError): review.verify_parent_metadata(changed)

    def test_metadata_derivation_reversible_preserves_original_profile_gates(self):
        restored = review.METADATA_SOURCE
        for old, new in reversed(review.METADATA_REPLACEMENTS):
            self.assertEqual(restored.count(new), 1); restored = restored.replace(new, old)
        self.assertEqual(restored, inspect.getsource(review.scope_audit.previous.live_metadata))

    def test_complete_post_block_reversible_all_actual_full_guards_unchanged(self):
        restored = review.POST_BODY
        for old, new in reversed(review.POST_REPLACEMENTS):
            self.assertEqual(restored.count(new), 1); restored = restored.replace(new, old)
        self.assertEqual(restored, review.ORIGINAL_POST)
        for name in ('verify_clock_admission', 'compare_placement', 'routed_primitives', 'full_inventory',
                     'verify_corrected_packed', 'source_revision', 'digest'):
            self.assertIs(review.POST_NAMESPACE[name], review.placement.NAMESPACE[name])
        for gate in ('assert full_inventory(selected, placed) == pack[\'retained_kernel_dsps\']',
                     'verify_corrected_packed(cell, placed[name])', 'all(digest(p) == sha for p, sha in before.items())',
                     "report['production_source_after'] == report['production_source_before']"):
            self.assertIn(gate, review.POST_SOURCE)
        self.assertNotIn('subprocess', review.POST_SOURCE)

    def test_finite_full_counter_checksum_and_bound_active_observation_required(self):
        packed = json.loads((ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json').read_text())
        scope = json.loads((ROOT / 'build/openxc7/recursive-mux-analytic-scope-typed-1791501546954868842/report.json').read_text())
        # Artificial complete-log metadata control; mocking the native-log
        # phase checker here is NOT evidence that native completion happened.
        log = ('Info: Checksum: 0x77f1fde0\n'
               'Info: Creating initial analytic placement for 419259 cells, random placement wirelen = 238678682.\n'
               'Info: Running main analytical placer, max placement attempts per cell = 2147483646.\n')
        with patch.object(review.placement, 'check_heap_log') as normal:
            checks = review.fresh_log_checks(log, packed, scope)
            normal.assert_called_once_with(0, log)
        self.assertEqual(checks['actual_full_packed_cells'], 523522)
        self.assertEqual(checks['actual_logged_analytic_active_roots'], 419259)
        self.assertFalse(checks['analytic_marker_used_as_full_census'])
        self.assertTrue(checks['complete_output_membership_required'])
        self.assertFalse(checks['physical_fit_verified'])
        for changed in (log.replace('0x77f1fde0', '0x00000000'), log.replace('419259', '419260'),
                        log.replace('2147483646', '10000'), log + log,
                        log.replace('Running main analytical placer', 'Other placer')):
            with self.subTest(changed=changed[-60:]), patch.object(review.placement, 'check_heap_log'), self.assertRaises(AssertionError):
                review.fresh_log_checks(changed, packed, scope)

    def test_native_completion_failure_not_masked_by_log_scope(self):
        packed = json.loads((ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json').read_text())
        with patch.object(review.placement, 'check_heap_log', side_effect=AssertionError('Missing normal refinement')):
            with self.assertRaisesRegex(AssertionError, 'Missing normal refinement'):
                review.fresh_log_checks('incomplete', packed, {})

    def test_scope_diagnostic_not_misrepresented_as_placement_or_bit_pass(self):
        scope = json.loads((ROOT / 'build/openxc7/recursive-mux-analytic-scope-typed-1791501546954868842/report.json').read_text())
        path = ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json'
        native = completed_fixture()
        native.update(native_version=scope['native_version'], packed_report=scope['packed_report'],
                      production_source_before=scope['production_source'])
        native['commands'][-1]['pid'] = scope['current_native_pid']
        review.verify_scope_metadata(scope, native, path)
        for field, bad in (('status', 'RUNNING'), ('current_native_pid', 1), ('full_cell_membership_verified', True),
                           ('physical_fit_verified', True), ('bitstream_emitted', True), ('processes_signalled', True)):
            changed = deepcopy(scope); changed[field] = bad
            with self.subTest(field=field), self.assertRaises(AssertionError): review.verify_scope_metadata(changed, native, path)

    def test_main_running_parent_fails_before_output_or_tool_launch(self):
        # Real current producer path, explicit RUNNING fixture. It is never
        # written back and no native executable or P&R command is invoked.
        path = ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json'
        scope_path = ROOT / 'build/openxc7/recursive-mux-analytic-scope-typed-1791501546954868842/report.json'
        parent = completed_fixture(); parent['status'] = 'RUNNING'
        with patch.object(sys, 'argv', ['review', '--native-report', str(path), '--scope-report', str(scope_path)]), \
             patch.object(review.json, 'loads', return_value=parent), \
             patch.object(review.Path, 'mkdir') as output, patch.object(review.subprocess, 'run') as tool:
            with self.assertRaises(AssertionError): review.main()
            output.assert_not_called(); tool.assert_not_called()


if __name__ == '__main__':
    unittest.main()
