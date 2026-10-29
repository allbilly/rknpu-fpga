"""Shared full-route admission controls, not a full native routing result."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import route_prefix_shared_board as new
import test_native_heap_route_control as existing

# Preserve every original error expectation and saved-small comparison test.
ExistingHeapGuards = existing.Controls
FullImportedExport = existing.FullImportedExport
EmptyOutputFullRoute = existing.EmptyOutputFullRoute


def fixture():
    pack = json.loads(new.PACKED_REPORT.read_text())
    return dict(status=new.PLACED, stage='complete', finished_utc='synthetic metadata only',
        channels=32, kernels=16, parallel_products=512, retained_cmac_dsps=512, retained_shell_dsps=3,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        packed_report=str(new.PACKED_REPORT), qualification=str(new.shared.HEAP_QUALIFICATION),
        prepared_report=pack['prepared_report'], execution_input=pack['execution_input'],
        host_native_timeout_seconds=43200, native_packing_executed=True,
        native_placement_executed=True, original_prepared_input_repacked=True,
        **dict.fromkeys(('native_routing_executed', 'packed_context_reloaded', 'old_placement_reused',
            'input_group_assignment_used', 'numerical_netlist_acceptance', 'physical_fit_verified',
            'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'), False),
        commands=[dict(label=n, status='PASS_TOOL_EXECUTION_ONLY', returncode=0)
                  for n in ('software_controls', 'native_heap_guard_controls', 'generated_check', 'version', 'native_place')],
        placement_checks=dict(primitive_counts=dict(new.COUNTS), bound_cells=new.CELLS, unique_bel_slots=new.CELLS,
            retained_kernel_dsps=pack['retained_kernel_dsps'], full_placed_numerical_acceptance=False,
            native_legality_scope='QUALIFIED_HEAP_NORMAL_REFINEMENT_FINAL_BEL_VALIDITY_CHECK_NOT_COMPLETE_ARCHITECTURE_SIGNOFF'),
        retained_kernel_dsps=pack['retained_kernel_dsps'], DSP_configurations_compared=515,
        extra_tile_only_ties_compared=4120, constraint_translation=pack['constraint_translation'],
        production_source_before=pack['production_source_after'], production_source_after=pack['production_source_after'])


class SharedRouteAdmission(unittest.TestCase):
    def reject(self, mutate):
        report = fixture()
        mutate(report)
        with self.assertRaises((AssertionError, KeyError)):
            new.verify_placed_metadata(report)

    def test_complete_shared_metadata_without_mutation_not_original_acceptance(self):
        report = fixture()
        original = deepcopy(report)
        new.verify_placed_metadata(report)
        self.assertEqual(report, original)
        with self.assertRaises(AssertionError):
            new.previous.verify_placed_metadata(report)
        with self.assertRaises(AssertionError):
            new.verify_placed_metadata(existing.heap_fixture())

    def test_running_failed_unfinished_or_wrong_stage_refused(self):
        for key, value in (('status', 'RUNNING'), ('status', 'FAIL_PREFIX_SHARED_NATIVE_HEAP_PLACE'),
                           ('finished_utc', None), ('stage', 'native_place')):
            self.reject(lambda r, k=key, v=value: r.update({k: v}))

    def test_target_clock_seed_or_actual_count_changes_refused(self):
        for key, value in (('parallel_products', 256), ('channels', 16), ('kernels', 8), ('retained_cmac_dsps', 256),
                           ('retained_shell_dsps', 0), ('intended_part', 'xc7k480tffg1156-1'),
                           ('intended_clock_period_ns', 40), ('seed', 1), ('host_native_timeout_seconds', 86400)):
            self.reject(lambda r, k=key, v=value: r.update({k: v}))
        self.reject(lambda r: r['placement_checks']['primitive_counts'].update(SLICE_LUTX=502795))
        self.reject(lambda r: r['placement_checks'].update(bound_cells=538118))
        self.reject(lambda r: r['placement_checks'].update(unique_bel_slots=new.CELLS - 1))
        self.reject(lambda r: r['placement_checks']['retained_kernel_dsps'].pop(next(iter(r['retained_kernel_dsps']))))

    def test_unperformed_native_commands_and_reused_assignment_refused(self):
        for key in ('native_packing_executed', 'native_placement_executed', 'original_prepared_input_repacked'):
            self.reject(lambda r, k=key: r.update({k: False}))
        for key in ('packed_context_reloaded', 'old_placement_reused', 'input_group_assignment_used'):
            self.reject(lambda r, k=key: r.update({k: True}))
        self.reject(lambda r: r['commands'].pop(1))
        self.reject(lambda r: r['commands'][-1].update(returncode=-9))
        self.reject(lambda r: r['commands'][-1].update(status='RUNNING'))

    def test_config_scope_source_parent_or_inferred_signoff_refused(self):
        for key in ('native_routing_executed', 'numerical_netlist_acceptance', 'physical_fit_verified',
                    'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
            self.reject(lambda r, k=key: r.update({k: True}))
        self.reject(lambda r: r.update(DSP_configurations_compared=514))
        self.reject(lambda r: r.update(extra_tile_only_ties_compared=4112))
        self.reject(lambda r: r['placement_checks'].update(native_legality_scope='unqualified'))
        self.reject(lambda r: r.update(production_source_after={'changed': True}))
        self.reject(lambda r: r.update(prepared_report='old or comparison-only input'))
        self.reject(lambda r: r.update(execution_input='old or comparison-only input'))

    def test_actual_running_fixture_rejected_before_output_or_tools(self):
        prefix = 'full-prefix-shared-heap-literal-empty-v2-scan-route-*'
        before = set((new.ROOT / 'build/openxc7').glob(prefix))
        with tempfile.TemporaryDirectory(prefix='shared-route-running-negative-', dir=new.ROOT / 'build/openxc7') as directory:
            path = Path(directory) / 'report.json'
            path.write_text(json.dumps(dict(status='RUNNING')))
            result = subprocess.run([sys.executable, '-B', str(Path(new.__file__)), '--placed', str(path)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1)
            self.assertIn('AssertionError', result.stderr)
            self.assertEqual(set((new.ROOT / 'build/openxc7').glob(prefix)), before)

    def test_absolute_own_artifact_binding_preserves_original_report_bytes(self):
        with tempfile.TemporaryDirectory(prefix='shared-route-binding-control-', dir=new.ROOT / 'build/openxc7') as directory:
            artifact = Path(directory) / 'fixture.bin'
            artifact.write_bytes(b'host binding fixture, not hardware input')
            report = dict(status=new.PLACED, source={}, artifacts={str(artifact): new.original.digest(artifact)})
            path = Path(directory) / 'report.json'
            path.write_text(json.dumps(report))
            before_bytes = path.read_bytes()
            bindings = {}
            new.bind_report(path, report, bindings)
            new.original.verify_bindings(bindings)
            self.assertEqual(bindings[str(path)], new.original.digest(path))
            self.assertEqual(path.read_bytes(), before_bytes)
            self.assertEqual(report['artifacts'], {str(artifact): new.original.digest(artifact)})
            with self.assertRaises(AssertionError):
                new.original.bind_report(path, report, {})
            outside = dict(report, artifacts={str(new.CONTROL): new.original.digest(new.CONTROL)})
            with self.assertRaisesRegex(AssertionError, 'outside actual shared attempt'):
                new.bind_report(path, outside, {})
            corrupt = dict(report, artifacts={str(artifact): 'not a digest'})
            with self.assertRaises(AssertionError):
                new.bind_report(path, corrupt, {})
            duplicate = dict(report, artifacts={str(artifact): new.original.digest(artifact),
                                                str(artifact.relative_to(new.ROOT)): new.original.digest(artifact)})
            with self.assertRaisesRegex(AssertionError, 'Duplicate normalized artifact path'):
                new.bind_report(path, duplicate, {})
            wrong = dict(report, artifacts={str(artifact): '0' * 64})
            wrong_bindings = {}
            new.bind_report(path, wrong, wrong_bindings)
            with self.assertRaisesRegex(AssertionError, 'Changed placement input'):
                new.original.verify_bindings(wrong_bindings)

    def test_actual_new_selected_input_census_and_source_binding(self):
        path = new.PACKED_REPORT.parent / 'actual-DSP-BRAM-input.json'
        before = {str(path): new.original.digest(path)}
        report = fixture()
        selected = new.selected_inputs(report, before)
        self.assertEqual(len(selected), 521)
        with self.assertRaises(AssertionError):
            new.selected_inputs(report, {})
        with self.assertRaises(AssertionError):
            new.selected_inputs(report, {str(path): '0' * 64})
        changed = deepcopy(report)
        changed['placement_checks']['retained_kernel_dsps'].pop(next(iter(changed['retained_kernel_dsps'])))
        with self.assertRaises(AssertionError):
            new.selected_inputs(changed, before)

    def test_other_packed_report_or_changed_inventory_is_not_this_profile(self):
        # A genuine existing report is still not this candidate's packed graph.
        self.reject(lambda r: r.update(packed_report=str(new.shared.HEAP_QUALIFICATION)))
        self.assertEqual(new.CELLS, 523410)
        self.assertEqual(new.own_pack(fixture())['native_census']['primitive_counts'], new.COUNTS)

    def test_source_transition_reversible_and_all_native_guards_preserved(self):
        restored = new.MAIN_SOURCE
        for old, replacement in reversed(new.REPLACEMENTS):
            self.assertEqual(restored.count(replacement), 1)
            restored = restored.replace(replacement, old)
        self.assertEqual(restored, new.previous.MAIN_SOURCE)
        for marker in ('verify_small_evidence(before)', 'verify_placed_module(', 'verify_placed_native_evidence(',
                       'check_import_count(', 'assert_circuit_identity(', 'verify_routed_footprint(',
                       'verify_full_features(', 'clock_contracts(module)', 'verify_bindings(before)',
                       "run('native_scan_and_route', argv, 43200)", 'fixed-lut-v2'):
            self.assertEqual(new.MAIN_SOURCE.count(marker), new.previous.MAIN_SOURCE.count(marker))
            self.assertGreater(new.MAIN_SOURCE.count(marker), 0)
        self.assertLess(new.MAIN_SOURCE.index('verify_placed_metadata(json.loads('), new.MAIN_SOURCE.index('out.mkdir('))
        self.assertIn('shared.packed_names(shared_packed_path(placed, before))', new.MAIN_SOURCE)
        self.assertIn('selected_inputs(placed, before)', new.MAIN_SOURCE)
        self.assertNotIn('checker.checkpoint.SELECTED.read_text()', new.MAIN_SOURCE)
        self.assertIs(new.NAMESPACE['verify_full_features'], new.previous.NAMESPACE['verify_full_features'])
        self.assertIs(new.NAMESPACE['check_full_scan'], new.previous.check_full_scan)
        self.assertIs(new.NAMESPACE['verify_small_evidence'], new.previous.NAMESPACE['verify_small_evidence'])

    def test_scan_counts_must_describe_new_graph_not_old_or_small(self):
        good = existing.NATIVE_GOOD.replace('538118', str(new.CELLS))
        new.previous.check_full_scan(good, new.CELLS, 200000, 17)
        for bad in (existing.NATIVE_GOOD, good.replace(str(new.CELLS), '286'), good + '\nInfo: HeAP Placer Time:'):
            with self.assertRaises(AssertionError):
                new.previous.check_full_scan(bad, new.CELLS, 200000, 17)


if __name__ == '__main__':
    unittest.main()
