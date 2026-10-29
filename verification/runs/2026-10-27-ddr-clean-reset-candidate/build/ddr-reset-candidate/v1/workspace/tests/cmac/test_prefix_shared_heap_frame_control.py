"""Counter-safe full-frame admission controls, not native route/frame results."""
from copy import deepcopy
import inspect
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(Path(__file__).parent)]
import convert_counter_safe_shared_frames as frames
import test_full_heap_frame_control as existing

ExistingFullFrameGuards = existing.Controls
SmallClockControls = existing.SmallClockControls
CorrectedFrameDatabaseControl = existing.CorrectedFrameDatabaseControl


def metadata():
    value = existing.metadata()
    value['status'] = frames.admission.route.ROUTED
    value['full_bound_cells'] = 523410
    value['physical_resource_checks']['unchanged_physical_bel_assignments'] = 523410
    value['original_logical_circuit_identity']['logical_board']['cells'] = 523410
    value.update(counter_safe_placement_only_HeAP_limit_expression_changed=True,
                 corrected_DSP_route_base_parent_chain_revalidated=True,
                 counter_safe_placement_engine_build_report=str(
                     ROOT / 'build/openxc7/counter-safe-heap-engine-1791481639500508440/report.json'))
    return value


class CounterSafeSharedFrameControls(unittest.TestCase):
    def test_exact_full_route_metadata_and_own_engine_profile_not_old_scope(self):
        report = metadata()
        saved = deepcopy(report)
        frames.admission.verify_metadata(report)
        self.assertEqual(report, saved)
        for key, value in (('status', 'RUNNING'), ('status', existing.new.admission.route.ROUTED),
                           ('stage', 'native_scan_and_route'), ('parallel_products', 256),
                           ('full_bound_cells', 538118), ('intended_clock_period_ns', 40),
                           ('counter_safe_placement_only_HeAP_limit_expression_changed', False),
                           ('corrected_DSP_route_base_parent_chain_revalidated', False)):
            wrong = deepcopy(report)
            wrong[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                frames.admission.verify_metadata(wrong)
        for key in frames.admission.route.original.FLAGS:
            wrong = deepcopy(report)
            wrong[key] = True
            with self.subTest(flag=key), self.assertRaises(AssertionError):
                frames.admission.verify_metadata(wrong)

    def test_shared_identity_census_and_all_actual_native_feature_gates_remain(self):
        for action in ('old_bels', 'old_logical', 'missing_kernel', 'missing_DSP', 'tile_ties', 'clock', 'command'):
            report = metadata()
            if action == 'old_bels':
                report['physical_resource_checks']['unchanged_physical_bel_assignments'] = 538118
            elif action == 'old_logical':
                report['original_logical_circuit_identity']['logical_board']['cells'] = 538118
            elif action == 'missing_kernel':
                report['physical_resource_checks']['retained_kernel_dsps'].pop('kernel0')
            elif action == 'missing_DSP':
                report['full_DSP_BRAM_FASM_feature_comparison']['selected_primitives_compared'] = 520
            elif action == 'tile_ties':
                report['full_DSP_BRAM_FASM_feature_comparison']['corrected_DSP_tile_pins_compared'] = 4112
            elif action == 'clock':
                report['full_native_clock_fanout_contracts'] = {}
            else:
                report['commands'][-1]['status'] = 'RUNNING'
            with self.subTest(action=action), self.assertRaises(AssertionError):
                frames.admission.verify_metadata(report)

    def test_source_reversal_retains_entire_original_actual_route_revalidation(self):
        text = frames.admission.VERIFY_SOURCE
        for old, new in reversed(frames.admission.REPLACEMENTS):
            self.assertEqual(text.count(new), 1)
            text = text.replace(new, old)
        self.assertEqual(text, inspect.getsource(frames.admission.previous.verify_route))
        self.assertEqual(frames.admission.METADATA_SOURCE.replace('523410', '538118'),
                         inspect.getsource(frames.admission.previous.verify_metadata))
        self.assertIs(frames.admission.NAMESPACE['bind_report'], frames.admission.route.bind_report)
        for marker in ('verify_qualification(', 'verify_placed_native_evidence(', 'verify_bindings(',
                       "assert c['argv']==argv", 'verify_routed_footprint(', 'assert_circuit_identity(',
                       "route.NAMESPACE['verify_full_features']", "route.NAMESPACE['check_full_scan']",
                       "route.NAMESPACE['clock_contracts']", "route.NAMESPACE['selected_inputs']"):
            self.assertIn(marker, frames.admission.VERIFY_SOURCE)

    def test_source_reversal_preserves_every_conversion_geometry_and_readback_guard(self):
        text = frames.MAIN_SOURCE
        for old, new in reversed(frames.REPLACEMENTS):
            self.assertEqual(text.count(new), 1)
            text = text.replace(new, old)
        self.assertEqual(text, inspect.getsource(frames.previous.main))
        for key in ('required_features', 'converter_requests', 'dsp_readback', 'verify_small_metadata', 'bind_report'):
            self.assertIs(frames.NAMESPACE[key], getattr(frames.previous, key))
        self.assertEqual(frames.FRAME_TIMEOUT, 43200)
        self.assertEqual(frames.FLAGS, frames.previous.FLAGS)
        self.assertLess(frames.MAIN_SOURCE.index('admission.verify_metadata('), frames.MAIN_SOURCE.index('out.mkdir'))
        self.assertLess(frames.MAIN_SOURCE.index('admission.verify_route('),
                        frames.MAIN_SOURCE.index("run('strict_full_native_FASM_conversion'"))
        self.assertIn("[frame.PYTHON,'-B',frame.__file__,'--worker',fasm,destination]", frames.MAIN_SOURCE)
        self.assertNotIn("'--worker',expected", frames.MAIN_SOURCE)

    def test_actual_incomplete_new_qualification_refused_before_output_and_conversion(self):
        prefix = 'full-counter-safe-shared-native-heap-frames-*'
        before = set((ROOT / 'build/openxc7').glob(prefix))
        path = ROOT / 'build/openxc7/counter-safe-heap-qualification-1791482371308735092/report.json'
        result = subprocess.run([sys.executable, '-B', frames.__file__, '--routed', str(path)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertIn('AssertionError', result.stderr)
        self.assertEqual(set((ROOT / 'build/openxc7').glob(prefix)), before)

    def test_small_data_or_unbound_comparison_input_cannot_become_full_frame_source(self):
        with self.assertRaises(AssertionError):
            frames.admission.verify_metadata(existing.json.loads(frames.previous.SMALL.read_text()))
        selected = frames.admission.route.NAMESPACE['selected_inputs']
        fixture = dict(placement_checks=dict(retained_kernel_dsps={}))
        with self.assertRaises(AssertionError):
            selected(fixture, {})
        self.assertNotIn('XRAY_ALLOW_MISSING_FEATURES=1', frames.MAIN_SOURCE)


if __name__ == '__main__':
    unittest.main()
