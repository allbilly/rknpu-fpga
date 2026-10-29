"""Diagnostic-only analytic-log scope controls, not numerical or native evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools')]
import audit_recursive_mux_analytic_scope as audit


class AnalyticScopeControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'build/openxc7/counter-safe-heap-engine-1791481639500508440/common/place/placer_heap.cc').read_text()
        cls.log = ('Info: Checksum: 0x77f1fde0\n'
                   'Info: Creating initial analytic placement for 419259 cells, random placement wirelen = 238678682.\n')

    def test_pinned_source_marker_is_active_roots_and_keeps_final_full_guards(self):
        result = audit.source_contract(self.source)
        self.assertEqual(result['marker_expression'], 'place_cells.size()')
        self.assertTrue(result['native_final_all_nonpseudo_cell_binding_guard_present'])
        self.assertFalse(result['exact_active_population_independently_reconstructed'])

    def test_changed_marker_population_or_selection_rejected(self):
        for old, new in (
            ('int(place_cells.size()), int(hpwl)', 'int(ctx->cells.size()), int(hpwl)'),
            ('if (ci->isPseudo()) {', 'if (false) {'),
            ('if (ci->bel != BelId()) {', 'if (false) {'),
            ('ctx->getClusterRootCell(ci->cluster) == ci', 'true'),
            ('!cfg.ioBufTypes.count(ci->type)', 'true'),
            ('!port.second.net->users.empty()', 'true'),
        ):
            with self.subTest(old=old), self.assertRaises(AssertionError):
                audit.source_contract(self.source.replace(old, new))

    def test_extra_population_append_rejected(self):
        with self.assertRaises(AssertionError):
            audit.source_contract(self.source + '\nplace_cells.push_back(ci);\n')

    def test_removed_native_full_binding_guards_rejected(self):
        for marker in ('Found unbound cell', 'Found mismatched binding', 'Stopping the program after %u errors found'):
            with self.subTest(marker=marker), self.assertRaises(AssertionError):
                audit.source_contract(self.source.replace(marker, 'removed final diagnostic'))

    def test_full_and_active_counts_remain_separate_not_acceptance(self):
        result = audit.log_observation(self.log, 523522, '0x77f1fde0')
        self.assertEqual(result['actual_logged_analytic_active_roots'], 419259)
        self.assertEqual(result['independently_characterized_full_packed_cells'], 523522)
        self.assertEqual(result['arithmetic_count_difference_not_an_omission_census'], 104263)
        self.assertFalse(result['analytic_marker_is_full_packed_cell_census'])
        self.assertFalse(result['exact_active_population_independently_reconstructed'])
        self.assertTrue(result['full_unique_BEL_and_cell_membership_still_required'])

    def test_missing_duplicate_or_unsupported_markers_rejected(self):
        for text in ('', self.log + self.log, self.log.replace('cells,', 'roots,')):
            with self.subTest(text=text), self.assertRaises(AssertionError):
                audit.log_observation(text, 523522, '0x77f1fde0')

    def test_wrong_or_duplicate_actual_packed_checksum_rejected(self):
        for text in (self.log.replace('0x77f1fde0', '0x00000000'),
                     'Info: Checksum: 0x77f1fde0\n' + self.log):
            with self.subTest(text=text), self.assertRaises(AssertionError):
                audit.log_observation(text, 523522, '0x77f1fde0')

    def test_invalid_subset_size_or_full_count_rejected(self):
        for count in (0, 523523):
            with self.subTest(count=count), self.assertRaises(AssertionError):
                audit.log_observation(self.log.replace('419259', str(count)), 523522, '0x77f1fde0')
        for full in (0, True, '523522'):
            with self.subTest(full=full), self.assertRaises(AssertionError):
                audit.log_observation(self.log, full, '0x77f1fde0')

    def test_native_warning_or_error_not_hidden_by_scope_audit(self):
        for marker in ('WARNING:', 'ERROR:', 'FATAL:', 'sorry:'):
            with self.subTest(marker=marker), self.assertRaises(AssertionError):
                audit.log_observation(self.log + marker + ' actual native failure\n', 523522, '0x77f1fde0')

    def test_current_live_metadata_is_diagnostic_only(self):
        # Static comparison-only fixture, NOT a live-job observation. The actual
        # audit separately requires /proc identity; these controls must remain
        # deterministic after the real producer changes stage or terminates.
        packed = json.loads((ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json').read_text())
        fixture = ROOT / 'build/openxc7/test-only-analytic-scope'
        argv = audit.placement.NAMESPACE['placement_argv'](packed['executable']['path'],
            packed['execution_input'], fixture / 'literal.xdc', fixture / 'placed.json')
        report = dict(status='RUNNING', stage='native_place', channels=32, kernels=16,
            parallel_products=512, intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20,
            seed=3588, executable=packed['executable'], native_packing_executed=True,
            native_placement_executed=True, original_prepared_input_repacked=True,
            commands=[dict(label='native_place', status='RUNNING', pid=12345,
                           returncode=None, timeout_seconds=43200, argv=argv)])
        for flag in ('native_routing_executed', 'old_placement_reused', 'input_group_assignment_used',
                     'numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff',
                     'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
            report[flag] = False
        command = audit.live_metadata(report)
        self.assertEqual(command['label'], 'native_place')
        for field, bad in (('status', 'PASS'), ('parallel_products', 32), ('native_routing_executed', True),
                           ('physical_fit_verified', True), ('bitstream_emitted', True)):
            changed = deepcopy(report); changed[field] = bad
            with self.subTest(field=field), self.assertRaises(AssertionError): audit.live_metadata(changed)

    def test_audited_heap_object_must_be_in_exact_successful_engine_link(self):
        obj = '/build/placer_heap.cc.o'
        exe = '/build/nextpnr-himbaechel'
        for status in ('PASS_TOOL_EXECUTION_ONLY', 'PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY'):
            label = 'link_recursive_mux_feedthrough'
            argv = ['/usr/bin/c++', obj, '-o', exe]
            step = dict(label=label, status=status, returncode=0, argv=argv)
            self.assertEqual(audit.verify_native_link_command([step], obj, exe), step)
            for changed in (
                dict(step, returncode=1),
                dict(step, status='RUNNING'),
                dict(step, argv=['/usr/bin/c++', '-o', exe]),
                dict(step, argv=['/usr/bin/c++', obj, obj, '-o', exe]),
                dict(step, argv=['/usr/bin/c++', obj, '-o', '/build/other-engine']),
                dict(step, label='unmodeled_link_command'),
            ):
                with self.subTest(label=label, changed=changed), self.assertRaises(AssertionError):
                    audit.verify_native_link_command([changed], obj, exe)
        with self.assertRaises(AssertionError):
            audit.verify_native_link_command([
                dict(label='relink_qualified_parent_identity', status='PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY',
                     returncode=0, argv=['/usr/bin/c++', obj, '-o', exe]),
            ], obj, exe)
        with self.assertRaises(AssertionError):
            audit.verify_native_link_command([
                dict(label='link_recursive_mux_feedthrough', status='PASS_TOOL_EXECUTION_ONLY',
                     returncode=0, argv=['/usr/bin/c++', obj, '-o', exe]),
                dict(label='link_recursive_mux_feedthrough', status='PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY',
                     returncode=0, argv=['/usr/bin/c++', obj, '-o', exe]),
            ], obj, exe)

    def test_old_running_verifier_not_modified_or_silently_admitted(self):
        packed = json.loads((ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json').read_text())
        with self.assertRaisesRegex(AssertionError, 'Changed complete full analytic cell census'):
            audit.placement.full_log_checks(self.log, packed)


if __name__ == '__main__':
    unittest.main()
