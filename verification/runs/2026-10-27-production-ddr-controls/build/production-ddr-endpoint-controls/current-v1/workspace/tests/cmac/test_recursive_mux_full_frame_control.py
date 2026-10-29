"""New full-graph frame admission controls, not route/frames/FPGA results."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import convert_recursive_mux_shared_frames as frames
import test_prefix_shared_heap_frame_control as old

ExistingFullFrameGuards = old.ExistingFullFrameGuards
SmallClockControls = old.SmallClockControls
CorrectedFrameDatabaseControl = old.CorrectedFrameDatabaseControl
OldSharedFrameGuards = old.CounterSafeSharedFrameControls


class RecursiveMuxFullFrameControls(unittest.TestCase):
    def test_whole_native_route_verifier_reversible_new_actual_census_only(self):
        admission = frames.admission
        text = admission.VERIFY_SOURCE
        for before, after in reversed(admission.REPLACEMENTS): text = text.replace(after, before)
        self.assertEqual(text, admission.previous.VERIFY_SOURCE)
        text = admission.METADATA_SOURCE
        for before, after in reversed(admission.METADATA_REPLACEMENTS): text = text.replace(after, before)
        self.assertEqual(text, admission.previous.METADATA_SOURCE)
        for marker in ('verify_qualification(', 'verify_placed_native_evidence(', 'verify_bindings(',
            "assert c['argv']==argv", 'assert_circuit_identity(', 'verify_routed_footprint(',
            "route.NAMESPACE['check_full_scan']", "route.NAMESPACE['verify_full_features']",
            "route.NAMESPACE['selected_inputs']", "route.NAMESPACE['clock_contracts']"):
            self.assertEqual(admission.VERIFY_SOURCE.count(marker), admission.previous.VERIFY_SOURCE.count(marker))
            self.assertGreater(admission.VERIFY_SOURCE.count(marker), 0)
        self.assertIs(admission.NAMESPACE['bind_report'], admission.route.bind_report)

    def test_native_route_metadata_requires_actual_new_count_and_all_original_gates(self):
        # Metadata-only fixture; fake count admission never becomes native evidence.
        for count in (523410, 523522):
            value = deepcopy(old.metadata())
            value.update(status=frames.admission.route.ROUTED, full_bound_cells=count,
                recursive_mux_and_counter_safe_placement_parent_chain_revalidated=True,
                recursive_mux_placement_engine_build_report=str(ROOT /
                    'build/openxc7/recursive-mux-feedthrough-native-io-engine-1791495496575181522/report.json'))
            value['physical_resource_checks']['unchanged_physical_bel_assignments'] = count
            value['original_logical_circuit_identity']['logical_board']['cells'] = count
            with patch.dict(frames.admission.METADATA_NAMESPACE, route_cell_count=lambda r: count):
                frames.admission.verify_metadata(value)
                for field, wrong_value in (('full_bound_cells', count - 1), ('parallel_products', 256),
                    ('status', frames.admission.previous.route.ROUTED),
                    ('recursive_mux_and_counter_safe_placement_parent_chain_revalidated', False),
                    ('corrected_DSP_route_base_parent_chain_revalidated', False)):
                    wrong = deepcopy(value); wrong[field] = wrong_value
                    with self.subTest(field=field), self.assertRaises(AssertionError): frames.admission.verify_metadata(wrong)
                for field in frames.admission.route.original.FLAGS:
                    wrong = deepcopy(value); wrong[field] = True
                    with self.subTest(flag=field), self.assertRaises(AssertionError): frames.admission.verify_metadata(wrong)

    def test_conversion_body_identical_and_actual_raw_FASM_only(self):
        text = frames.MAIN_SOURCE
        for before, after in reversed(frames.REPLACEMENTS): text = text.replace(after, before)
        self.assertEqual(text, frames.previous.MAIN_SOURCE)
        for name in ('required_features', 'converter_requests', 'dsp_readback', 'verify_small_metadata', 'bind_report'):
            self.assertIs(frames.NAMESPACE[name], frames.previous.NAMESPACE[name])
        self.assertEqual(frames.FRAME_TIMEOUT, 43200)
        self.assertEqual(frames.FLAGS, frames.previous.FLAGS)
        self.assertLess(frames.MAIN_SOURCE.index('admission.verify_metadata('), frames.MAIN_SOURCE.index('out.mkdir'))
        self.assertLess(frames.MAIN_SOURCE.index('admission.verify_route('), frames.MAIN_SOURCE.index("run('strict_full_native_FASM_conversion'"))
        self.assertIn("[frame.PYTHON,'-B',frame.__file__,'--worker',fasm,destination]", frames.MAIN_SOURCE)
        self.assertIn("admission.route.NAMESPACE['selected_inputs']", frames.MAIN_SOURCE)
        self.assertNotIn('XRAY_ALLOW_MISSING_FEATURES=1', frames.MAIN_SOURCE)

    def test_small_build_and_old_qualification_rejected_before_conversion_output(self):
        prefix = 'full-recursive-mux-shared-native-heap-frames-*'
        before = set((ROOT / 'build/openxc7').glob(prefix))
        for path in (frames.previous.previous.SMALL,
            ROOT / 'build/openxc7/recursive-mux-native-placement-probe-1791496225072484294/report.json',
            ROOT / 'build/openxc7/counter-safe-heap-qualification-1791486974423403401/report.json'):
            result = subprocess.run([sys.executable, '-B', frames.__file__, '--routed', str(path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1)
            self.assertIn('AssertionError', result.stderr)
        self.assertEqual(set((ROOT / 'build/openxc7').glob(prefix)), before)
        with self.assertRaises((AssertionError, KeyError)):
            frames.admission.verify_metadata(json.loads(frames.previous.previous.SMALL.read_text()))


if __name__ == '__main__':
    unittest.main()
