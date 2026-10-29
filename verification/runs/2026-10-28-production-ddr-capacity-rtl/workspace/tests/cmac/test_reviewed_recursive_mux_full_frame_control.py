"""Host-only reviewed full-frame handoff controls, not native conversion proof."""
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
import convert_reviewed_recursive_mux_full_frames as frames
import test_recursive_mux_full_frame_control as old

ExistingFullFrameGuards = old.ExistingFullFrameGuards
SmallClockControls = old.SmallClockControls
CorrectedFrameDatabaseControl = old.CorrectedFrameDatabaseControl
OldSharedFrameGuards = old.OldSharedFrameGuards
RecursiveMuxFullFrameControls = old.RecursiveMuxFullFrameControls

NATIVE = ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json'
PACK = ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json'


def metadata():
    report = deepcopy(old.old.metadata())
    report.update(status=frames.admission.route.ROUTED, full_bound_cells=523522,
        recursive_mux_and_counter_safe_placement_parent_chain_revalidated=True,
        recursive_mux_placement_engine_build_report=str(ROOT /
            'build/openxc7/recursive-mux-feedthrough-native-io-engine-1791495496575181522/report.json'),
        placed_report='host-only-future-reviewed-report', independent_full_placement_review_report='host-only-future-reviewed-report',
        original_failed_native_execution_report=str(NATIVE), original_failed_native_report_relabelled=False,
        original_native_output_modified=False, analytic_subset_marker_used_as_full_census=False)
    report['physical_resource_checks']['unchanged_physical_bel_assignments'] = 523522
    report['original_logical_circuit_identity']['logical_board']['cells'] = 523522
    return report


class ReviewedRecursiveMuxFullFrameControls(unittest.TestCase):
    def test_entire_full_route_revalidation_reversible_only_metadata_ownership_changes(self):
        admission = frames.admission
        source = admission.VERIFY_SOURCE
        for before, after in reversed(admission.REPLACEMENTS):
            self.assertEqual(source.count(after), 1); source = source.replace(after, before)
        self.assertEqual(source, admission.previous.VERIFY_SOURCE)
        self.assertEqual(admission.METADATA_SOURCE, admission.previous.METADATA_SOURCE)
        self.assertEqual(admission.WRAPPER_SOURCE, inspect.getsource(admission.previous.verify_metadata))
        for marker in ('verify_placed_native_evidence(', 'verify_bindings(', "assert c['argv']==argv",
                       'assert_circuit_identity(', 'verify_routed_footprint(', "route.NAMESPACE['check_full_scan']",
                       "route.NAMESPACE['verify_full_features']", "route.NAMESPACE['selected_inputs']",
                       "route.NAMESPACE['clock_contracts']", 'check_import_count'):
            self.assertEqual(admission.VERIFY_SOURCE.count(marker), admission.previous.VERIFY_SOURCE.count(marker))
            self.assertGreater(admission.VERIFY_SOURCE.count(marker), 0)
        self.assertIn("route.NAMESPACE['verify_placement_engine'](route.qualification_path(placed))", admission.VERIFY_SOURCE)
        self.assertIn("route.NAMESPACE['placement_build'](candidate,before)", admission.VERIFY_SOURCE)
        self.assertIs(admission.NAMESPACE['bind_report'], admission.route.bind_report)

    def test_new_reviewed_route_metadata_and_all_original_full_native_guards(self):
        value = metadata(); saved = deepcopy(value)
        with patch.dict(frames.admission.METADATA_NAMESPACE, route_cell_count=lambda r: 523522):
            frames.admission.verify_metadata(value); self.assertEqual(value, saved)
            for field, wrong in (('status', frames.admission.previous.route.ROUTED), ('status', 'RUNNING'),
                ('stage', 'native_scan_and_route'), ('full_bound_cells', 523410), ('parallel_products', 256),
                ('intended_clock_period_ns', 100), ('seed', 1), ('independent_full_placement_review_report', 'wrong-review'),
                ('original_failed_native_report_relabelled', True), ('original_native_output_modified', True),
                ('analytic_subset_marker_used_as_full_census', True),
                ('recursive_mux_and_counter_safe_placement_parent_chain_revalidated', False),
                ('corrected_DSP_route_base_parent_chain_revalidated', False)):
                with self.subTest(field=field), self.assertRaises(AssertionError):
                    frames.admission.verify_metadata(dict(value, **{field: wrong}))
            for field in frames.admission.route.original.FLAGS:
                with self.subTest(field=field), self.assertRaises(AssertionError):
                    frames.admission.verify_metadata(dict(value, **{field: True}))
            for action in ('bels', 'logical', 'kernel', 'DSP', 'ties', 'clock', 'command'):
                changed = deepcopy(value)
                if action == 'bels': changed['physical_resource_checks']['unchanged_physical_bel_assignments'] = 523410
                elif action == 'logical': changed['original_logical_circuit_identity']['logical_board']['cells'] = 523410
                elif action == 'kernel': changed['physical_resource_checks']['retained_kernel_dsps'].pop('kernel0')
                elif action == 'DSP': changed['full_DSP_BRAM_FASM_feature_comparison']['selected_primitives_compared'] = 520
                elif action == 'ties': changed['full_DSP_BRAM_FASM_feature_comparison']['corrected_DSP_tile_pins_compared'] = 4119
                elif action == 'clock': changed['full_native_clock_fanout_contracts'] = {}
                else: changed['commands'][-1]['returncode'] = 1
                with self.subTest(action=action), self.assertRaises(AssertionError): frames.admission.verify_metadata(changed)

    def test_census_requires_completed_review_not_old_native_or_diagnostic(self):
        with self.assertRaises(AssertionError): frames.admission.route_cell_count(dict(placed_report=str(NATIVE)))
        with tempfile.TemporaryDirectory(prefix='full-recursive-mux-valid-pack-completed-placement-review-census-control-', dir=ROOT / 'build/openxc7') as directory:
            path = Path(directory) / 'report.json'; path.write_text('{"status":"RUNNING"}'); saved = path.read_bytes()
            with self.assertRaises(AssertionError): frames.admission.route_cell_count(dict(placed_report=str(path)))
            # A metadata-only hook verifies exact census extraction, not fit.
            pack = json.loads(PACK.read_text())
            with patch.object(frames.admission.route, 'verify_placed_metadata') as reviewed, \
                 patch.object(frames.admission.route, 'own_pack', return_value=pack):
                self.assertEqual(frames.admission.route_cell_count(dict(placed_report=str(path))), 523522)
                reviewed.assert_called_once_with({'status': 'RUNNING'})
            self.assertEqual(path.read_bytes(), saved)

    def test_conversion_body_reversible_and_strict_raw_input_geometry_readbacks_unchanged(self):
        source = frames.MAIN_SOURCE
        for before, after in reversed(frames.REPLACEMENTS):
            self.assertEqual(source.count(after), 1); source = source.replace(after, before)
        self.assertEqual(source, frames.previous.MAIN_SOURCE)
        for name in ('required_features', 'converter_requests', 'dsp_readback', 'verify_small_metadata', 'bind_report', 'small'):
            self.assertIs(frames.NAMESPACE[name], frames.previous.NAMESPACE[name])
        self.assertEqual(frames.FRAME_TIMEOUT, 43200)
        self.assertEqual(frames.FLAGS, frames.previous.FLAGS)
        self.assertLess(frames.MAIN_SOURCE.index('admission.verify_metadata('), frames.MAIN_SOURCE.index('out.mkdir'))
        self.assertLess(frames.MAIN_SOURCE.index('admission.verify_route('), frames.MAIN_SOURCE.index("run('strict_full_native_FASM_conversion'"))
        for marker in ("[frame.PYTHON,'-B',frame.__file__,'--worker',fasm,destination]", 'verify_requests(',
                       'verify_clock_requests(', "run('exact_part_frame_geometry'", 'actual_frame_bit_corruption_rejected_in_comparison_only'):
            self.assertIn(marker, frames.MAIN_SOURCE)
        self.assertNotIn("'--worker',expected", frames.MAIN_SOURCE)
        self.assertNotIn('XRAY_ALLOW_MISSING_FEATURES=1', frames.MAIN_SOURCE)
        self.assertIn("assert 'XRAY_ALLOW_MISSING_FEATURES' not in os.environ", frames.MAIN_SOURCE)

    def test_actual_current_and_small_producers_rejected_before_conversion_output(self):
        pattern = 'full-reviewed-recursive-mux-native-heap-frames-*'
        before = set((ROOT / 'build/openxc7').glob(pattern))
        for path in (NATIVE, frames.previous.previous.previous.SMALL):
            result = subprocess.run([sys.executable, '-B', frames.__file__, '--routed', str(path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1); self.assertIn('AssertionError', result.stderr)
        self.assertEqual(set((ROOT / 'build/openxc7').glob(pattern)), before)

    def test_route_snapshots_history_and_original_checkpoint_owner_required(self):
        admission = frames.admission; route = admission.route
        with tempfile.TemporaryDirectory(prefix='full-reviewed-recursive-mux-literal-empty-v2-scan-route-snapshot-control-', dir=ROOT / 'build/openxc7') as directory:
            root = Path(directory); path = root / 'report.json'; placed_path = root / 'host-only-reviewed.json'
            texts = {'executed_source.py': Path(route.__file__).read_text(),
                'executed_control_source.py': route.CONTROL.read_text(), 'executed_prepared_main.py': route.MAIN_SOURCE}
            for name, text in texts.items(): (root / name).write_text(text)
            before = {str(root / name): route.original.digest(root / name) for name in texts}
            before.update({str(source): route.original.digest(source) for source in (Path(route.__file__).resolve(), route.CONTROL)})
            report = dict(independent_full_placement_review_report=str(placed_path), original_failed_native_execution_report=str(NATIVE),
                hardware_execution_input=str(NATIVE.parent / 'placed.json'), commands=[dict(pid=999999999)], supervisor_pid=999999998,
                prepared_main_source_sha256=before[str(root / 'executed_prepared_main.py')])
            with patch.object(route, 'original_execution', return_value=(NATIVE, {})):
                admission.verify_route_snapshots(path, report, before, placed_path, {})
                for field, wrong in (('independent_full_placement_review_report', 'wrong'),
                    ('original_failed_native_execution_report', 'wrong'), ('hardware_execution_input', str(root / 'comparison-only.json')),
                    ('prepared_main_source_sha256', '0' * 64)):
                    with self.subTest(field=field), self.assertRaises(AssertionError):
                        admission.verify_route_snapshots(path, dict(report, **{field: wrong}), before, placed_path, {})
                with patch.object(admission.Path, 'exists', return_value=True), self.assertRaises(AssertionError):
                    admission.verify_route_snapshots(path, report, before, placed_path, {})
                item = root / 'executed_prepared_main.py'; item.write_text('missing full native route guards')
                before[str(item)] = route.original.digest(item)
                report['prepared_main_source_sha256'] = before[str(item)]
                with self.assertRaises(AssertionError): admission.verify_route_snapshots(path, report, before, placed_path, {})

    def test_route_and_frame_admission_never_executes_or_mutates_execution_inputs(self):
        admission = frames.admission
        self.assertNotIn('subprocess', admission.VERIFY_SOURCE)
        self.assertNotIn('write_text', admission.VERIFY_SOURCE)
        self.assertNotIn('write_bytes', admission.VERIFY_SOURCE)
        self.assertIn("assert c['argv']==argv and c['timeout_seconds']==43200", admission.VERIFY_SOURCE)
        self.assertIn("own_file(path,r,'native_FASM',before)", admission.VERIFY_SOURCE)
        for path in (NATIVE, frames.previous.previous.previous.SMALL):
            with self.assertRaises(AssertionError): admission.verify_route(path)


if __name__ == '__main__':
    unittest.main()
