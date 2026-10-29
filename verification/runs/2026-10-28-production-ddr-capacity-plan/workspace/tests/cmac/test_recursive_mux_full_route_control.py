"""Prepared full new-graph route controls, never new native or FPGA results."""
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
import route_recursive_mux_prefix_shared_board as route
import test_prefix_shared_heap_route_control as old

# Execute every unchanged original error expectation/encoder comparison too.
ExistingSharedGuards = old.ExistingSharedGuards
ExistingHeapGuards = old.ExistingHeapGuards
FullImportedExport = old.FullImportedExport
EmptyOutputFullRoute = old.EmptyOutputFullRoute
OldCounterSafeControls = old.CounterSafeFullRouteControls


class RecursiveMuxFullRouteControls(unittest.TestCase):
    def test_every_old_native_route_gate_reversibly_retained(self):
        text = route.MAIN_SOURCE
        for before, after in reversed(route.REPLACEMENTS):
            self.assertEqual(text.count(after), 1)
            text = text.replace(after, before)
        self.assertEqual(text, route.previous.MAIN_SOURCE)
        for source, replacements, expected in (
            (route.METADATA_SOURCE, route.METADATA_REPLACEMENTS, inspect.getsource(route.shared.verify_placed_metadata)),
            (route.EVIDENCE_SOURCE, route.EVIDENCE_REPLACEMENTS, inspect.getsource(route.shared.verify_placed_native_evidence)),
            (route.SELECTED_SOURCE, (('PACKED_REPORT.parent', 'own_pack_path(placed).parent'),), inspect.getsource(route.shared.selected_inputs))):
            for before, after in reversed(replacements): source = source.replace(after, before)
            self.assertEqual(source, expected)
        for name in ('check_full_scan', 'verify_small_evidence', 'verify_placed_module',
                     'assert_circuit_identity', 'verify_routed_footprint', 'verify_full_features',
                     'clock_contracts', 'audit_pairs', 'local_carry_roles', 'check_import_count'):
            self.assertIs(route.NAMESPACE[name], route.previous.NAMESPACE[name])
        self.assertIn("run('native_scan_and_route', argv, 43200)", route.MAIN_SOURCE)
        self.assertIn('12 * 1024**3', route.MAIN_SOURCE)
        self.assertLess(route.MAIN_SOURCE.index('verify_placed_metadata(json.loads('), route.MAIN_SOURCE.index('out.mkdir('))

    def make_metadata_fixture(self, directory, extra=0):
        # Host-only fabricated report/counts: not native packing or placement.
        pack = deepcopy(json.loads(route.shared.PACKED_REPORT.read_text()))
        pack.update(status=route.placement.packer.PACKED,
            encoder_qualification='test-only-new-qualification',
            only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent=True,
            legacy_full_encoder_result_inherited_as_new_pack=False,
            legacy_DSP_encoder_qualification='test-only-baseline')
        pack['native_census']['cells'] += extra
        pack['native_census']['primitive_counts']['SLICE_LUTX'] += extra
        pack['LUT_sharing_bound']['lut_cells'] += extra
        log = directory / 'native-pack.log'; log.write_text('Info: Checksum: 0x12345678\n')
        pack['commands'][-1]['log'] = str(log)
        path = directory / 'report.json'; path.write_text(json.dumps(pack))
        placed = old.existing.fixture()
        placed.update(status=route.PLACED, packed_report=str(path), executable=pack['executable'],
                      qualification=pack['encoder_qualification'])
        placed['placement_checks']['primitive_counts'] = deepcopy(pack['native_census']['primitive_counts'])
        placed['placement_checks']['bound_cells'] = placed['placement_checks']['unique_bel_slots'] = pack['native_census']['cells']
        return placed, pack, path

    def test_new_actual_profile_not_retired_fixed_count(self):
        for extra in (0, 112):
            with tempfile.TemporaryDirectory(prefix='full-prefix-shared-recursive-mux-native-pack-control-', dir=ROOT / 'build/openxc7') as directory:
                placed, pack, path = self.make_metadata_fixture(Path(directory), extra)
                saved = path.read_bytes()
                self.assertEqual(route.own_pack(placed), pack)
                with patch.object(route, 'verify_recursive_binding') as binding:
                    # The compiled function owns its namespace; replace only
                    # this metadata-test hook, never a live producer module.
                    with patch.dict(route.METADATA_NAMESPACE, verify_recursive_binding=binding):
                        route.verify_placed_metadata(placed)
                        binding.assert_called_once_with(placed)
                        wrong = deepcopy(placed); wrong['placement_checks']['bound_cells'] -= 1
                        with self.assertRaises(AssertionError): route.verify_placed_metadata(wrong)
                self.assertEqual(saved, path.read_bytes())
                for field, value in (('executable', {'wrong': True}), ('qualification', 'retired-qualification')):
                    with self.assertRaises(AssertionError): route.own_pack(dict(placed, **{field: value}))
                checks = route.packed_checks(pack)
                self.assertEqual(checks['actual_full_packed_cells'], pack['native_census']['cells'])
                self.assertEqual(checks['actual_packed_checksum'], '0x12345678')
                self.assertFalse(checks['old_fixed_packed_census_or_checksum_inherited'])
                (Path(directory) / 'native-pack.log').write_text('Info: Checksum: 0x12345678\n' * 2)
                with self.assertRaises(AssertionError): route.packed_checks(pack)

    def test_incomplete_and_old_profile_rejected_before_output_or_tools(self):
        for report in ({}, {'status': 'RUNNING'}, {'status': route.previous.PLACED},
                       {'status': 'PASS_SMALL_RECURSIVE_MUX_NATIVE_PLACEMENT_NOT_FULL_BACKEND_QUALIFICATION_OR_FIT'}):
            with self.assertRaises((AssertionError, KeyError)): route.verify_placed_metadata(report)
        prefix = 'full-prefix-shared-recursive-mux-heap-literal-empty-v2-scan-route-*'
        before = set((ROOT / 'build/openxc7').glob(prefix))
        with tempfile.TemporaryDirectory(prefix='recursive-mux-route-incomplete-control-', dir=ROOT / 'build/openxc7') as directory:
            path = Path(directory) / 'report.json'; path.write_text('{"status":"RUNNING"}')
            result = subprocess.run([sys.executable, '-B', route.__file__, '--placed', str(path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1)
            self.assertIn('AssertionError', result.stderr)
        self.assertEqual(set((ROOT / 'build/openxc7').glob(prefix)), before)

    def test_actual_two_object_chain_unchanged_DSP_router_base(self):
        path = ROOT / 'build/openxc7/recursive-mux-feedthrough-native-io-engine-1791495496575181522/report.json'
        built = json.loads(path.read_text())
        before = {**built['source'], **built['artifacts'], str(path): route.original.digest(path)}
        candidate = dict(build_report=str(path), executable=built['executable'],
            qualified_parent_executable=built['parent_executable'], production_source_after=built['production_source_after'])
        base = route.placement_build(candidate, before)
        self.assertNotEqual(base['executable'], candidate['executable'])
        for changed in ({}, dict(before, **{str(path): '0' * 64}),
                        dict(before, **{str(route.placement.qualification.candidate.PARENT): '0' * 64})):
            with self.assertRaises(AssertionError): route.placement_build(candidate, changed)
        with self.assertRaises(AssertionError): route.placement_build(dict(candidate, executable=built['parent_executable']), before)

    def test_new_artifact_binding_retains_confinement_and_raw_report(self):
        with tempfile.TemporaryDirectory(prefix='recursive-mux-route-binding-control-', dir=ROOT / 'build/openxc7') as directory:
            root = Path(directory); artifact = root / 'fixture.bin'
            artifact.write_bytes(b'host-only binding fixture, not circuit data')
            for status in (route.PLACED, route.placement.packer.PACKED):
                report = dict(status=status, source={}, artifacts={str(artifact): route.original.digest(artifact)})
                path = root / 'report.json'; path.write_text(json.dumps(report)); saved = path.read_bytes()
                before = {}; route.bind_report(path, report, before); route.original.verify_bindings(before)
                self.assertEqual(path.read_bytes(), saved)
                with self.assertRaises(AssertionError): route.bind_report(path, dict(report, artifacts={str(route.CONTROL): route.original.digest(route.CONTROL)}), {})

    def test_full_scan_counts_and_all_old_target_guards_preserved(self):
        for count in (523410, 523522):
            text = old.existing.existing.NATIVE_GOOD.replace('538118', str(count))
            route.NAMESPACE['check_full_scan'](text, count, 200000, 17)
            with self.assertRaises(AssertionError): route.NAMESPACE['check_full_scan'](text, count + 1, 200000, 17)
        self.assertIs(route.NAMESPACE['verify_placement_engine'], route.placement.qualification.verify_qualification)
        self.assertIs(route.NAMESPACE['verify_packed_metadata'], route.placement.packer.validate_pack)
        self.assertIn('placement.full_log_checks(log.read_text(), pack)', route.EVIDENCE_SOURCE)


if __name__ == '__main__':
    unittest.main()
