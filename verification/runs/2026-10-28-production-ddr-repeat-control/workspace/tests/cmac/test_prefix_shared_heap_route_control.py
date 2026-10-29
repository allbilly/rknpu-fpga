"""Counter-safe route preparation guards, not new routed/FPGA acceptance."""
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(Path(__file__).parent)]
import route_counter_safe_prefix_shared_board as route
import test_prefix_shared_route_control as existing

ExistingSharedGuards = existing.SharedRouteAdmission
ExistingHeapGuards = existing.ExistingHeapGuards
FullImportedExport = existing.FullImportedExport
EmptyOutputFullRoute = existing.EmptyOutputFullRoute


class CounterSafeFullRouteControls(unittest.TestCase):
    def test_reversible_procedure_retains_every_route_and_feature_gate(self):
        text = route.MAIN_SOURCE
        for old, new in reversed(route.REPLACEMENTS):
            self.assertEqual(text.count(new), 1)
            text = text.replace(new, old)
        self.assertEqual(text, route.previous.MAIN_SOURCE)
        self.assertEqual(route.METADATA_SOURCE.replace(route.NEW_QUALIFICATION, route.OLD_QUALIFICATION),
                         inspect.getsource(route.previous.verify_placed_metadata))
        self.assertEqual(route.EVIDENCE_SOURCE.replace(route.NEW_LOG, route.OLD_LOG),
                         inspect.getsource(route.previous.verify_placed_native_evidence))
        for key in ('verify_full_features', 'check_full_scan', 'verify_small_evidence',
                    'verify_placed_module', 'assert_circuit_identity', 'verify_routed_footprint',
                    'clock_contracts', 'audit_pairs', 'local_carry_roles', 'selected_inputs'):
            self.assertIs(route.NAMESPACE[key], route.previous.NAMESPACE[key])
        self.assertEqual(route.CELLS, 523410)
        self.assertIn("run('native_scan_and_route', argv, 43200)", route.MAIN_SOURCE)

    def test_original_or_incomplete_placement_cannot_admit_new_engine(self):
        report = existing.fixture()
        with self.assertRaises(AssertionError):
            route.verify_placed_metadata(report)
        report['status'] = route.PLACED
        report.update(native_source_or_executable_changed=True,
                      only_HeAP_limit_expression_changed=True, old_native_result_inherited=False)
        with self.assertRaises(AssertionError):
            route.verify_placed_metadata(report)  # Old qualification is not new native evidence.
        for value in ({'status': 'RUNNING'}, {'status': 'FAIL'}, {}):
            with self.assertRaises((AssertionError, KeyError)):
                route.verify_placed_metadata(value)

    def test_new_placement_artifacts_confined_and_report_bytes_not_projected(self):
        with tempfile.TemporaryDirectory(prefix='counter-safe-route-binding-', dir=ROOT / 'build/openxc7') as directory:
            out = Path(directory)
            artifact = out / 'fixture.bin'
            artifact.write_bytes(b'host binding test, never an execution netlist')
            report = dict(status=route.PLACED, source={}, artifacts={str(artifact): route.original.digest(artifact)})
            path = out / 'report.json'
            path.write_text(json.dumps(report))
            saved = path.read_bytes()
            before = {}
            route.bind_report(path, report, before)
            route.original.verify_bindings(before)
            self.assertEqual(saved, path.read_bytes())
            self.assertEqual(before[str(artifact)], report['artifacts'][str(artifact)])
            with self.assertRaises(AssertionError):
                route.bind_report(path, dict(report, artifacts={str(route.CONTROL): route.original.digest(route.CONTROL)}), {})
            duplicate = dict(report, artifacts={str(artifact): route.original.digest(artifact),
                             str(artifact.relative_to(ROOT)): route.original.digest(artifact)})
            with self.assertRaises(AssertionError):
                route.bind_report(path, duplicate, {})

    def test_bound_completed_one_object_parent_chain_not_guessed_route_base(self):
        path = ROOT / 'build/openxc7/counter-safe-heap-engine-1791481639500508440/report.json'
        built = json.loads(path.read_text())
        before = {**built['source'], **built['artifacts'], str(path): route.original.digest(path)}
        candidate = dict(build_report=str(path), executable=built['executable'],
                         qualified_parent_executable=built['parent_executable'],
                         production_source_after=built['production_source_after'])
        parent = route.placement_build(candidate, before)
        self.assertEqual(parent['executable'], built['parent_executable'])
        for changed in ({}, dict(before, **{str(path): '0' * 64})):
            with self.assertRaises(AssertionError):
                route.placement_build(candidate, changed)
        wrong = dict(candidate, executable=built['parent_executable'])
        with self.assertRaises(AssertionError):
            route.placement_build(wrong, before)


if __name__ == '__main__':
    unittest.main()
