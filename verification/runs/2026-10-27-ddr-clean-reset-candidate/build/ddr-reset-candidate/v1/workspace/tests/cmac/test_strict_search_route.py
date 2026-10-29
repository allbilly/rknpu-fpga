"""Prepared full-route admission and saved-small comparison controls, not P&R."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import route_strict_search_board as route
from place_prefix_board import PACK_PARENT
from route_prefix_board import verify_placed_metadata as old_placement_gate
from test_full_imported_export import FullImportedExport


def placement():
    packed = json.loads(PACK_PARENT.read_text()); counts = packed['native_packed_cell_counts']
    return dict(status=route.PLACED, stage='complete', finished_utc='synthetic admission only',
        channels=32, kernels=16, parallel_products=512, retained_cmac_dsps=512, retained_shell_dsps=3,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        native_packing_executed=True, native_placement_executed=True, original_prepared_input_repacked=True,
        packed_context_reloaded=False, FPGA_clock_period_changed=False,
        corrected_DSP_encoder_preserved=True, native_legality_guards_preserved=True, changed_static_placer_object=1,
        **{k: False for k in route.PLACE_FLAGS},
        commands=[dict(label=n, status='PASS_TOOL_EXECUTION_ONLY', returncode=0)
                  for n in ('software_controls', 'generated_check', 'version', 'native_place')],
        placement_checks=dict(primitive_counts=counts, bound_cells=sum(counts.values()), unique_bel_slots=sum(counts.values()),
            retained_kernel_dsps=packed['retained_kernel_dsps'], full_placed_numerical_acceptance=False),
        constraint_translation=dict(target_period_ns=20.0, signoff_constraint_profile=False),
        production_source_before='same', production_source_after='same')


NATIVE_GOOD = '\n'.join([
    'Info: RKNPU imported placement scan: begin before clock/general routing.',
    'Info: RKNPU imported placement scan: verified 17 local carry DI roles.',
    'Info: RKNPU imported placement scan: passed 538118 bound cells and 200000 fixed logic pairs; original tags restored and caches invalidated.',
    'Info: Running router1 to check that route is legal...', 'Info: Routing complete.',
    'Info: Running post-routing legalisation...', 'Info: Program finished normally.'])


class StrictSearchRoute(unittest.TestCase):
    def test_metadata_requires_full_512_and_does_not_modify_old_gate(self):
        route.verify_placed_metadata(placement())
        with self.assertRaises(AssertionError): old_placement_gate(placement())

    def test_incomplete_wrong_size_target_native_or_physical_acceptance_fails(self):
        for key, value in [('status', 'RUNNING'), ('status', 'FAIL'), ('stage', 'native_place'),
                ('parallel_products', 32), ('retained_cmac_dsps', 32), ('intended_clock_period_ns', 40),
                ('corrected_DSP_encoder_preserved', False), ('native_legality_guards_preserved', False),
                ('native_placement_executed', False), ('changed_static_placer_object', 2)] + [(k, True) for k in route.PLACE_FLAGS]:
            r = placement(); r[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): route.verify_placed_metadata(r)
        for kind in ('duplicate_bels', 'small_cells', 'missing_kernel', 'wrong_rc'):
            r = placement()
            if kind == 'duplicate_bels': r['placement_checks']['unique_bel_slots'] -= 1
            elif kind == 'small_cells': r['placement_checks']['bound_cells'] = 286
            elif kind == 'missing_kernel': r['placement_checks']['retained_kernel_dsps'] = {'one': 32}
            else: r['commands'][-1]['returncode'] = -9
            with self.assertRaises(AssertionError): route.verify_placed_metadata(r)

    def test_completed_actual_small_checker_profile_not_full_acceptance(self):
        r = json.loads(route.SMALL.read_text()); route.verify_small_metadata(r)
        for key, value in [('status', 'RUNNING'), ('fresh_native_286_scan_and_route_executed', False),
                           ('imported_corruptions_revalidated', 6), ('original_preplacement_truth_comparisons', 0)] + [(k, True) for k in route.small.FLAGS]:
            bad = deepcopy(r); bad[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): route.verify_small_metadata(bad)

    def test_full_native_scan_requires_exact_counts_roles_normal_router_and_no_replacement(self):
        route.check_full_scan(NATIVE_GOOD, 538118, 200000, 17)
        for text in (NATIVE_GOOD.replace('verified 17', 'verified 16'), NATIVE_GOOD.replace('538118', '286'),
                     NATIVE_GOOD.replace('200000', '98'), NATIVE_GOOD.replace('Routing complete.', 'not complete'),
                     NATIVE_GOOD + '\nInfo: Running Static placer...', NATIVE_GOOD + '\nWARNING: ignored'):
            with self.assertRaises(AssertionError): route.check_full_scan(text, 538118, 200000, 17)

    def test_saved_49_and_286_projection_preserves_complete_actual_logical_proof(self):
        targets = [(route.checker.NATIVE.parent / 'valid-forced-placed.json', route.small.PARENT.parent / 'fixed_49-routed.json', 49),
                   (route.checker.TRANSFER.parent / 'corrected-transfer-input.json', route.SMALL.parent / 'routed-286.json', 286)]
        for before_path, after_path, expected in targets:
            before = next(iter(json.loads(before_path.read_text())['modules'].values()))
            after = next(iter(json.loads(after_path.read_text())['modules'].values()))
            original = deepcopy(before)
            projected = route.comparison_port_source(before)
            view, metadata = route.full_export_view(projected, after)
            result = route.assert_circuit_identity(route.proof_module(before), route.proof_module(view, before['ports']))
            self.assertEqual(result['logical_board']['cells'], expected)
            self.assertFalse(metadata['comparison_view_used_for_execution'])
            self.assertEqual(before, original)
            self.assertEqual(set(projected['cells']), set(before['cells']))

    def test_projection_cannot_hide_changed_LUT_INIT_or_connected_carry_pin(self):
        before = next(iter(json.loads((route.checker.NATIVE.parent / 'valid-forced-placed.json').read_text())['modules'].values()))
        after = next(iter(json.loads((route.small.PARENT.parent / 'fixed_49-routed.json').read_text())['modules'].values()))
        bad = deepcopy(after)
        cell = next(c for c in bad['cells'].values() if c['type'] == 'SLICE_LUTX')
        init = cell['parameters']['INIT']; cell['parameters']['INIT'] = ('1' if init[0] == '0' else '0') + init[1:]
        view, _ = route.full_export_view(route.comparison_port_source(before), bad)
        with self.assertRaises(AssertionError):
            route.assert_circuit_identity(route.proof_module(before), route.proof_module(view, before['ports']))
        bad = deepcopy(after)
        name, source = next((n, c) for n, c in before['cells'].items() if c['type'] == 'CARRY4' and c['connections'].get('CO3'))
        del bad['cells'][name]['connections']['CO3']; del bad['cells'][name]['port_directions']['CO3']
        with self.assertRaises(AssertionError): route.full_export_view(route.comparison_port_source(before), bad)

    def test_unmodeled_non_LUT_empty_output_remains_failure(self):
        before = next(iter(json.loads((route.checker.NATIVE.parent / 'valid-forced-placed.json').read_text())['modules'].values()))
        after = next(iter(json.loads((route.small.PARENT.parent / 'fixed_49-routed.json').read_text())['modules'].values()))
        name = next(n for n, c in before['cells'].items() if c['type'] == 'SLICE_FFX')
        before['cells'][name]['connections']['unsupported'] = []
        before['cells'][name]['port_directions']['unsupported'] = 'output'
        with self.assertRaises(AssertionError): route.full_export_view(route.comparison_port_source(before), after)


if __name__ == '__main__': unittest.main()
