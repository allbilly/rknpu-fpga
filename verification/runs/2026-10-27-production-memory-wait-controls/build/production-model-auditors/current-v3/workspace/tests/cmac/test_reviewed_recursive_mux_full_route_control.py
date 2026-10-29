"""Host-only prepared reviewed-route controls; fixtures are not native passes."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import route_reviewed_recursive_mux_full_board as route
import test_recursive_mux_full_route_control as old

# Re-execute the qualified original route guards, including old negatives.
ExistingSharedGuards = old.ExistingSharedGuards
ExistingHeapGuards = old.ExistingHeapGuards
FullImportedExport = old.FullImportedExport
EmptyOutputFullRoute = old.EmptyOutputFullRoute
OldCounterSafeControls = old.OldCounterSafeControls
RecursiveMuxFullRouteControls = old.RecursiveMuxFullRouteControls

PACK = ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json'
NATIVE = ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json'


def fixture():
    """Synthetic future review metadata; never saved over a real producer."""
    pack = json.loads(PACK.read_text())
    report = old.old.existing.fixture()
    report.update(status=route.PLACED, finished_utc='host-only-future-terminal-fixture',
        packed_report=str(PACK), executable=pack['executable'], commands=[],
        original_native_commands=deepcopy(report['commands']), original_full_output_guards_retained=True,
        full_placed_cell_membership_verified=True, source_proven_analytic_subset_contract_used=True,
        fresh_native_placement_executed=False, original_failed_report_relabelled=False,
        original_native_output_modified=False, hardware_execution_input_changed=False)
    report['placement_checks']['primitive_counts'] = deepcopy(pack['native_census']['primitive_counts'])
    report['placement_checks']['bound_cells'] = report['placement_checks']['unique_bel_slots'] = pack['native_census']['cells']
    paths = [Path(sys.executable).resolve(), Path(route.prepared_review.__file__).resolve(),
             route.prepared_review.CONTROL, Path(route.review.__file__).resolve()]
    report['source'] = {str(p): route.original.digest(p) for p in paths}
    report['commands'] = [dict(label='software_controls', status='PASS_SOFTWARE_CONTROL_ONLY', returncode=0,
        timeout_seconds=120, cwd=str(ROOT), argv=[sys.executable, '-B', '-W', 'error', '-m', 'unittest',
            'discover', '-s', 'tests/cmac', '-p', route.prepared_review.CONTROL.name, '-v']),
        dict(label='generated_check', status='PASS_SOFTWARE_CONTROL_ONLY', returncode=0,
            timeout_seconds=120, cwd=str(ROOT), argv=['make', 'generated-check'])]
    native = deepcopy(report)
    native['commands'] = deepcopy(report['original_native_commands'])
    return report, native, pack


class ReviewedFullRouteControls(unittest.TestCase):
    def test_every_full_native_route_guard_reversibly_retained(self):
        for source, replacements, expected in ((route.MAIN_SOURCE, route.REPLACEMENTS, route.previous.MAIN_SOURCE),
            (route.METADATA_SOURCE, route.METADATA_REPLACEMENTS, route.previous.METADATA_SOURCE)):
            for before, after in reversed(replacements):
                self.assertEqual(source.count(after), 1); source = source.replace(after, before)
            self.assertEqual(source, expected)
        for name in ('check_full_scan', 'verify_small_evidence', 'verify_placed_module', 'assert_circuit_identity',
                     'verify_routed_footprint', 'verify_full_features', 'clock_contracts', 'audit_pairs',
                     'local_carry_roles', 'check_import_count', 'placement_build', 'verify_placement_engine'):
            self.assertIs(route.NAMESPACE[name], route.previous.NAMESPACE[name])
        self.assertIn("run('native_scan_and_route', argv, 43200)", route.MAIN_SOURCE)
        self.assertIn('12 * 1024**3', route.MAIN_SOURCE)
        self.assertIn("set(module['cells']) == shared.packed_names(shared_packed_path(placed, before))", route.MAIN_SOURCE)
        self.assertIn("design_path == original_execution(placed)[0].parent / 'placed.json'", route.MAIN_SOURCE)
        self.assertNotIn('timing-allow-fail', route.MAIN_SOURCE)

    def test_review_commands_are_distinct_from_native_history(self):
        report, _, _ = fixture(); saved = deepcopy(report)
        route.verify_review_metadata(report)
        self.assertEqual(report, saved)
        for index in range(2):
            for field, bad in (('status', 'PASS_TOOL_EXECUTION_ONLY'), ('returncode', 1), ('timeout_seconds', 43200),
                               ('cwd', '/tmp'), ('argv', ['true'])):
                changed = deepcopy(report); changed['commands'][index][field] = bad
                with self.subTest(index=index, field=field), self.assertRaises(AssertionError):
                    route.verify_review_metadata(changed)
        for commands in ([], report['original_native_commands'], report['commands'][::-1]):
            with self.assertRaises(AssertionError): route.verify_review_metadata(dict(report, commands=commands))

    def test_no_incomplete_or_physical_acceptance_claims_admitted(self):
        report, _, _ = fixture()
        for field, bad in (('status', 'RUNNING'), ('status', route.previous.PLACED), ('stage', 'full_unique_BEL_and_DSP_checks'),
                           ('finished_utc', ''), ('full_placed_cell_membership_verified', False),
                           ('source_proven_analytic_subset_contract_used', False), ('original_full_output_guards_retained', False)):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                route.verify_review_metadata(dict(report, **{field: bad}))
        for field in ('fresh_native_placement_executed', 'original_failed_report_relabelled', 'original_native_output_modified',
                      'hardware_execution_input_changed', 'native_routing_executed', 'numerical_netlist_acceptance',
                      'physical_fit_verified', 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                route.verify_review_metadata(dict(report, **{field: True}))

    def test_new_full_census_and_all_original_target_guards(self):
        report, native, pack = fixture()
        with patch.dict(route.METADATA_NAMESPACE, original_execution=lambda r: (NATIVE, native),
                        own_pack=lambda r: pack, verify_native_lineage=lambda r: None):
            route.verify_placed_metadata(report)
            for field, bad in (('channels', 8), ('kernels', 1), ('parallel_products', 32), ('retained_cmac_dsps', 32),
                               ('retained_shell_dsps', 0), ('intended_part', 'xc7a200tfbg484-1'),
                               ('intended_clock_period_ns', 100), ('seed', 1), ('DSP_configurations_compared', 514),
                               ('extra_tile_only_ties_compared', 4119)):
                with self.subTest(field=field), self.assertRaises(AssertionError):
                    route.verify_placed_metadata(dict(report, **{field: bad}))
            for field, bad in (('bound_cells', 523410), ('unique_bel_slots', 523521), ('primitive_counts', {}),
                               ('retained_kernel_dsps', {}), ('full_placed_numerical_acceptance', True), ('native_legality_scope', 'PASS')):
                changed = deepcopy(report); changed['placement_checks'][field] = bad
                with self.subTest(field=field), self.assertRaises(AssertionError): route.verify_placed_metadata(changed)
            for flag in ('packed_context_reloaded', 'old_placement_reused', 'input_group_assignment_used'):
                with patch.dict(native, **{flag: True}), self.subTest(flag=flag), self.assertRaises(AssertionError):
                    route.verify_placed_metadata(report)

    def test_actual_running_parent_rejected_without_any_output_or_launch(self):
        pattern = 'full-reviewed-recursive-mux-literal-empty-v2-scan-route-*'
        before = set((ROOT / 'build/openxc7').glob(pattern))
        # This is an actual running producer, NOT a completed placement review.
        result = subprocess.run([sys.executable, '-B', route.__file__, '--placed', str(NATIVE)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertIn('AssertionError', result.stderr)
        self.assertEqual(set((ROOT / 'build/openxc7').glob(pattern)), before)
        self.assertLess(route.MAIN_SOURCE.index('verify_placed_metadata(json.loads('), route.MAIN_SOURCE.index('out.mkdir('))

    def test_original_producer_cause_history_identity_and_live_pid_guards(self):
        with tempfile.TemporaryDirectory(prefix='full-prefix-shared-recursive-mux-heap-place-control-', dir=ROOT / 'build/openxc7') as directory:
            path = Path(directory) / 'report.json'
            native = json.loads(NATIVE.read_text())
            native.update(status=route.review.PARENT_FAILED, stage='native_place', error=route.review.PARENT_ERROR,
                          finished_utc='host-only-terminal-fixture', supervisor_pid=999999998, source={}, artifacts={})
            for command in native['commands']:
                command.update(status='PASS_TOOL_EXECUTION_ONLY', returncode=0, pid=999999999)
            path.write_text(json.dumps(native))
            report = {k: native[k] for k in ('executable', 'native_version', 'packed_report', 'prepared_report',
                'execution_input', 'constraint_translation', 'production_source_before')}
            report.update(native_execution_report=str(path), original_native_commands=deepcopy(native['commands']),
                          source={str(path): route.original.digest(path)})
            self.assertEqual(route.original_execution(report), (path, native))
            for field, bad in (('original_native_commands', []), ('executable', {}), ('execution_input', '/tmp/wrong.json')):
                with self.subTest(field=field), self.assertRaises(AssertionError):
                    route.original_execution(dict(report, **{field: bad}))
            with patch.object(route.Path, 'exists', return_value=True), self.assertRaises(AssertionError):
                route.original_execution(report)
            for field, bad in (('error', 'other cause'), ('status', 'RUNNING'), ('stage', 'complete')):
                path.write_text(json.dumps(dict(native, **{field: bad})))
                report['source'][str(path)] = route.original.digest(path)
                with self.subTest(field=field), self.assertRaises(AssertionError): route.original_execution(report)

    def test_source_artifact_chain_requires_complete_own_provenance(self):
        with tempfile.TemporaryDirectory(prefix='reviewed-route-binding-control-', dir=ROOT / 'build/openxc7') as directory:
            root = Path(directory); item = root / 'fixture.bin'; item.write_bytes(b'host-only fixture')
            path = root / 'report.json'; sha = route.original.digest(item)
            parent = dict(source={str(route.CONTROL): route.original.digest(route.CONTROL)}, artifacts={str(item): sha})
            report = dict(source={**parent['source'], str(item): sha})
            route.require_contained_bindings(report, parent, path)
            with self.assertRaises(KeyError): route.require_contained_bindings(dict(source={}), parent, path)
            with self.assertRaises(AssertionError):
                route.require_contained_bindings(report, dict(parent, artifacts={str(route.CONTROL): route.original.digest(route.CONTROL)}), path)
            with self.assertRaises(AssertionError):
                route.require_contained_bindings(report, dict(parent, artifacts={str(item): sha, str(item.relative_to(ROOT)): sha}), path)
            bound = dict(status=route.PLACED, source=parent['source'], artifacts=parent['artifacts'])
            path.write_text(json.dumps(bound)); before = {}; route.bind_report(path, bound, before)
            route.original.verify_bindings(before)
            saved = path.read_bytes()
            self.assertEqual(path.read_bytes(), saved)
            with self.assertRaises(AssertionError):
                route.bind_report(path, dict(bound, artifacts={str(route.CONTROL): route.original.digest(route.CONTROL)}), {})

    def test_review_snapshots_and_logs_confined_and_exact(self):
        with tempfile.TemporaryDirectory(prefix='full-recursive-mux-valid-pack-completed-placement-review-control-', dir=ROOT / 'build/openxc7') as directory:
            root = Path(directory); path = root / 'report.json'
            texts = {'executed_source.py': Path(route.prepared_review.__file__).read_text(),
                'executed_prepared_main.py': route.prepared_review.MAIN_SOURCE, 'executed_post_native_checks.py': route.review.POST_SOURCE,
                'software_controls.log': 'host-only fixture', 'generated_check.log': 'host-only fixture'}
            for name, text in texts.items(): (root / name).write_text(text)
            report = dict(artifacts={str(root / name): route.original.digest(root / name) for name in texts},
                          commands=[dict(log=str(root / name)) for name in ('software_controls.log', 'generated_check.log')])
            route.verify_review_snapshots(report, path)
            item = root / 'executed_post_native_checks.py'; item.write_text('not the actual complete-output guards')
            report['artifacts'][str(item)] = route.original.digest(item)
            with self.assertRaises(AssertionError): route.verify_review_snapshots(report, path)

    def test_native_checkpoint_owner_raw_input_log_and_clock_remain_required(self):
        # Small inert files exercise admission only, never full placement.
        with tempfile.TemporaryDirectory(prefix='full-prefix-shared-recursive-mux-heap-place-evidence-control-', dir=ROOT / 'build/openxc7') as directory:
            owner = Path(directory) / 'report.json'; output = owner.parent / 'placed.json'
            log = owner.parent / 'native_place.log'; output.write_text('{}'); log.write_text('host-only fixture')
            pack = json.loads(PACK.read_text()); native = json.loads(NATIVE.read_text())
            command = native['commands'][-1]; command['argv'][command['argv'].index('--write') + 1] = str(output)
            command['log'] = str(log); command['returncode'] = 0
            report = dict(placed_design=str(output), executable=native['executable'],
                constraint_translation=native['constraint_translation'], reviewed_native_log_characterization={'host-only': True},
                source={str(output): route.original.digest(output), str(log): route.original.digest(log), str(PACK): route.original.digest(PACK)})
            with patch.object(route, 'verify_review_snapshots'), patch.object(route, 'original_execution', return_value=(owner, native)), \
                 patch.object(route, 'own_pack', return_value=pack), patch.object(route, 'scope_report', return_value={}), \
                 patch.dict(route.previous.placement.NAMESPACE, verify_clock_admission=lambda text, constraints: None), \
                 patch.object(route.review, 'fresh_log_checks', return_value=report['reviewed_native_log_characterization']) as native_log:
                route.verify_placed_native_evidence(report, owner)
                native_log.assert_called_once_with(log.read_text(), pack, {})
                for field, bad in (('placed_design', str(log)), ('reviewed_native_log_characterization', {}),
                                   ('source', dict(report['source'], **{str(output): '0' * 64})),
                                   ('source', dict(report['source'], **{str(log): '0' * 64}))):
                    with self.subTest(field=field), self.assertRaises(AssertionError):
                        route.verify_placed_native_evidence(dict(report, **{field: bad}), owner)
                original_input = command['argv'][command['argv'].index('--json') + 1]
                command['argv'][command['argv'].index('--json') + 1] = str(output)
                with self.assertRaises(AssertionError): route.verify_placed_native_evidence(report, owner)
                command['argv'][command['argv'].index('--json') + 1] = original_input
                with patch.object(route.review, 'fresh_log_checks', side_effect=AssertionError('Missing normal refinement')):
                    with self.assertRaisesRegex(AssertionError, 'Missing normal refinement'):
                        route.verify_placed_native_evidence(report, owner)
                with patch.dict(route.previous.placement.NAMESPACE,
                                verify_clock_admission=lambda text, constraints: (_ for _ in ()).throw(AssertionError('Changed clock'))):
                    with self.assertRaisesRegex(AssertionError, 'Changed clock'): route.verify_placed_native_evidence(report, owner)


if __name__ == '__main__':
    unittest.main()
