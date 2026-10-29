"""Routing admission/export identity controls, not a new native route or signoff."""
from collections import Counter
from copy import deepcopy
from itertools import permutations
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/openxc7'))
from route_prefix_board import (PLACED, ABSENT_ACCEPTANCE, DATABASE, CONSTIDS,
    SMALL_ROUTE, verify_placed_metadata, logical_lut, proof_module,
    physical_footprint, verify_routed_footprint, SiteBELMap, verify_precision_transition_metadata,
    verify_small_route_metadata)
from prepare_prefix_pack_input import assert_circuit_identity
from probe_prefix_route_resume import PARENT, resume_argv


def placement_metadata():
    counts = {'DSP48E1_DSP48E1': 515, 'RAMB36E1_RAMB36E1': 6, 'SLICE_LUTX': 1000}
    return dict(status=PLACED, stage='complete', finished_utc='controls-only',
        channels=32, kernels=16, parallel_products=512, retained_cmac_dsps=512,
        retained_shell_dsps=3, intended_part='xc7k480tffg1156-2',
        intended_clock_period_ns=20, seed=3588, native_packing_executed=True,
        native_placement_executed=True, original_prepared_input_repacked=True,
        packed_context_reloaded=False, **{key: False for key in ABSENT_ACCEPTANCE},
        placement_checks=dict(retained_kernel_dsps={f'k{i}': 32 for i in range(16)},
            primitive_counts=counts, bound_cells=sum(counts.values()),
            unique_bel_slots=sum(counts.values()), full_placed_numerical_acceptance=False),
        commands=[dict(log=label + '.log', returncode=0, status='PASS_TOOL_EXECUTION_ONLY')
                  for label in ('version', 'help', 'native_place')],
        constraint_translation=dict(target_period_ns=20, signoff_constraint_profile=False),
        native_tool_transition=transition_metadata())


def transition_metadata():
    return dict(original_qualification='/synthetic-controls/original', selected_qualification='/synthetic-controls/selected',
        original_executable=dict(path='/synthetic-controls/old', sha256='a' * 64),
        selected_executable=dict(path='/synthetic-controls/new', sha256='b' * 64),
        changed_exponential_calls=2, fresh_native_positive_placements=3, fresh_lut_output_comparisons=1024,
        only_static_placer_object_replaced=True, parent_relink_byte_identical=True,
        assertions_objective_clock_and_full_geometry_unchanged=True, packing_routing_timing_objects_unchanged=True,
        global_donor_pointer_changed=False)


def small_route_metadata():
    return dict(status='PASS_SMALL_NATIVE_PLACED_RELOAD_AND_ROUTE_CONTROL_NOT_FULL_BOARD_OR_SIGNOFF',
        stage='complete', finished_utc='synthetic controls only', native_tool_transition=transition_metadata(),
        **{k: True for k in ('small_native_reload_executed', 'small_native_routing_executed',
            'exact_all_cell_bel_reload_identity', 'duplicate_bel_native_rejection')},
        **{k: False for k in ('full_board_native_routing_executed', 'full_board_numerical_acceptance',
            'physical_fit_verified', 'timing_signoff', 'electrical_verified', 'bitstream_emitted', 'hardware_programmed')},
        router_connectivity_check=dict(actual_linked_call_present=True, executable_sha256='b' * 64),
        commands=[dict(label=name, status='PASS_EXPECTED_REJECTION_ONLY' if name == 'duplicate_bel_rejection' else 'PASS_TOOL_EXECUTION_ONLY',
            returncode=-6 if name == 'duplicate_bel_rejection' else 0, expected_returncode=-6 if name == 'duplicate_bel_rejection' else 0)
            for name in ('software_controls', 'generated_check', 'version', 'linked_router_check',
                         'reload', 'duplicate_bel_rejection', 'route')])


def lut(width=3, physical=None, init=None):
    physical = physical or tuple(range(1, width + 1))
    connections = {'O6': [20]}
    attributes = dict(X_ORIG_TYPE=f'LUT{width}', X_ORIG_PORT_O6='O',
                      NEXTPNR_BEL='generic', BEL_STRENGTH='1')
    for i, pin in enumerate(physical):
        connections[f'A{pin}'] = [i + 2]
        attributes[f'X_ORIG_PORT_A{pin}'] = f'I{i}'
    return dict(type='SLICE_LUTX', parameters=dict(INIT=init or '01' * (1 << (width - 1))),
        attributes=attributes, connections=connections,
        port_directions={p: 'output' if p == 'O6' else 'input' for p in connections})


def logical_design(cell):
    width = int(cell['attributes']['X_ORIG_TYPE'][-1])
    return proof_module(dict(cells={'lut': cell}, ports={
        'inputs': dict(direction='input', bits=list(range(2, width + 2))),
        'out': dict(direction='output', bits=[20])}))


def small_export_identity(route_report=SMALL_ROUTE):
    saved = json.loads(route_report.read_text())
    parent = (ROOT / saved['parent_report']).resolve(strict=True)
    assert parent.is_relative_to(ROOT / 'build/openxc7')
    placed = next(iter(json.loads((parent.parent / 'placed.json').read_text())['modules'].values()))
    routed = next(iter(json.loads((route_report.parent / 'routed.json').read_text())['modules'].values()))
    with SiteBELMap(DATABASE, CONSTIDS) as database:
        footprint = physical_footprint(placed, database)
    resource = verify_routed_footprint(routed, footprint, {})
    identity = assert_circuit_identity(proof_module(placed), proof_module(routed, placed['ports']))
    assert len(placed['cells']) == 18
    assert dict(Counter(c['type'] for c in placed['cells'].values())) == dict(Counter(c['type'] for c in routed['cells'].values()))
    return dict(resource_checks=resource, original_logical_circuit_identity=identity,
                small_saved_export_read_only=True, new_native_routing_executed=False)


class PrefixFullRouteControl(unittest.TestCase):
    def test_small_route_requires_actual_completion_expected_negative_and_same_executable(self):
        verify_small_route_metadata(small_route_metadata())
        for key, value in [('status', 'RUNNING'), ('status', 'FAIL'), ('stage', 'route'), ('finished_utc', '')] + [
                (k, not v) for k, v in small_route_metadata().items() if type(v) is bool]:
            report = small_route_metadata()
            report[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): verify_small_route_metadata(report)
        for change in ('command_status', 'command_rc', 'wrong_negative', 'missing_command', 'unchecked_router', 'wrong_executable'):
            report = small_route_metadata()
            if change == 'command_status': report['commands'][-1]['status'] = 'RUNNING'
            elif change == 'command_rc': report['commands'][-1]['returncode'] = 1
            elif change == 'wrong_negative':
                report['commands'][-2]['returncode'] = report['commands'][-2]['expected_returncode'] = 125
            elif change == 'missing_command': report['commands'].pop()
            elif change == 'unchecked_router': report['router_connectivity_check']['actual_linked_call_present'] = False
            else: report['router_connectivity_check']['executable_sha256'] = 'a' * 64
            with self.subTest(change=change), self.assertRaises(AssertionError): verify_small_route_metadata(report)

    def test_precision_engine_metadata_is_mandatory_not_a_stock_fallback(self):
        verify_precision_transition_metadata(transition_metadata())
        for key, value in [('changed_exponential_calls', 1), ('fresh_native_positive_placements', 2),
                          ('fresh_lut_output_comparisons', 512), ('global_donor_pointer_changed', True),
                          ('selected_qualification', 'relative-path')] + [(k, False) for k, v in transition_metadata().items() if v is True]:
            report = transition_metadata()
            report[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): verify_precision_transition_metadata(report)
        for field in ('qualification', 'executable'):
            report = transition_metadata()
            report['selected_' + field] = report['original_' + field]
            with self.assertRaises(AssertionError): verify_precision_transition_metadata(report)
        for key, value in [('path', 'relative'), ('sha256', 'invalid')]:
            report = transition_metadata()
            report['selected_executable'][key] = value
            with self.assertRaises(AssertionError): verify_precision_transition_metadata(report)
        report = placement_metadata()
        report.pop('native_tool_transition')
        with self.assertRaises(KeyError): verify_placed_metadata(report)

    def test_full_placement_only_admission(self):
        verify_placed_metadata(placement_metadata())
        mutations = dict(status='RUNNING', stage='native_place', finished_utc='',
            channels=16, kernels=8, parallel_products=256, retained_cmac_dsps=256,
            retained_shell_dsps=2, intended_part='xc7k480tffg1156-1',
            intended_clock_period_ns=40, seed=1, native_packing_executed=False,
            native_placement_executed=False, original_prepared_input_repacked=False,
            packed_context_reloaded=True, **{key: True for key in ABSENT_ACCEPTANCE})
        for key, value in mutations.items():
            report = placement_metadata()
            report[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): verify_placed_metadata(report)

    def test_placement_counts_membership_and_tool_success_are_mandatory(self):
        for change in ('missing_kernel', 'smaller_kernel', 'dsp', 'bram', 'unbound', 'duplicate',
                       'numeric_claim', 'command_rc', 'command_pending', 'command_label', 'clock', 'constraints'):
            report = placement_metadata()
            checks = report['placement_checks']
            if change == 'missing_kernel': checks['retained_kernel_dsps'].pop('k15')
            elif change == 'smaller_kernel': checks['retained_kernel_dsps']['k0'] = 16
            elif change == 'dsp': checks['primitive_counts']['DSP48E1_DSP48E1'] = 514
            elif change == 'bram': checks['primitive_counts']['RAMB36E1_RAMB36E1'] = 5
            elif change == 'unbound': checks['bound_cells'] -= 1
            elif change == 'duplicate': checks['unique_bel_slots'] -= 1
            elif change == 'numeric_claim': checks['full_placed_numerical_acceptance'] = True
            elif change == 'command_rc': report['commands'][-1]['returncode'] = 1
            elif change == 'command_pending': report['commands'][-1]['status'] = 'RUNNING'
            elif change == 'command_label': report['commands'][-1]['log'] = 'small_place.log'
            elif change == 'clock': report['constraint_translation']['target_period_ns'] = 40
            else: report['constraint_translation']['signoff_constraint_profile'] = True
            with self.subTest(change=change), self.assertRaises(AssertionError): verify_placed_metadata(report)

    def test_all_1956_LUT1_to_6_injective_physical_pin_permutations(self):
        count = 0
        for width in range(1, 7):
            original = logical_design(lut(width))
            for pins in permutations(range(1, 7), width):
                assert_circuit_identity(original, logical_design(lut(width, pins)))
                count += 1
        self.assertEqual(count, 1956)

    def test_source_defined_aliased_logical_inputs_and_unmapped_physical_inputs(self):
        original = lut(2)
        original['connections']['A2'] = original['connections']['A1']
        changed = deepcopy(original)
        changed['connections'].pop('A2')
        changed['port_directions'].pop('A2')
        changed['attributes'].pop('X_ORIG_PORT_A2')
        changed['attributes']['X_ORIG_PORT_A1'] = 'I0 I1'
        changed['connections']['A6'] = [99]  # No FASM logical mapping; INIT cannot depend on this pin.
        changed['port_directions']['A6'] = 'input'
        self.assertEqual(logical_lut(original), logical_lut(changed))

    def test_native_padded_and_short_INIT_representations_remain_literal(self):
        for width in range(1, 7):
            for length in (1, 2, 32, 64):
                cell = lut(width, init='0' * (length - 1) + '1')
                self.assertEqual(logical_lut(cell)['parameters'], cell['parameters'])
        left, right = lut(1, init='01'), lut(1, init='0' * 31 + '1')
        with self.assertRaises(AssertionError): assert_circuit_identity(logical_design(left), logical_design(right))

    def test_unknown_missing_duplicate_or_malformed_LUT_mapping_is_rejected(self):
        for change in ('kind', 'parameter', 'init_nonbinary', 'init_wide', 'pin', 'direction',
                       'missing', 'duplicate', 'unknown', 'disconnected', 'extra_map', 'empty_map',
                       'mapping_type', 'two_outputs', 'wrong_output', 'missing_output', 'wide_input'):
            cell = lut()
            if change == 'kind': cell['attributes']['X_ORIG_TYPE'] = 'SRLC32E'
            elif change == 'parameter': cell['parameters']['extra'] = '1'
            elif change == 'init_nonbinary': cell['parameters']['INIT'] = 'xx'
            elif change == 'init_wide': cell['parameters']['INIT'] = '1' * 65
            elif change == 'pin': cell['connections']['CLK'] = [30]; cell['port_directions']['CLK'] = 'input'
            elif change == 'direction': cell['port_directions']['A1'] = 'output'
            elif change == 'missing': cell['attributes'].pop('X_ORIG_PORT_A1')
            elif change == 'duplicate': cell['attributes']['X_ORIG_PORT_A2'] = 'I0'
            elif change == 'unknown': cell['attributes']['X_ORIG_PORT_A1'] = 'I5'
            elif change == 'disconnected': cell['connections']['A1'] = []
            elif change == 'extra_map': cell['attributes']['X_ORIG_PORT_A6'] = 'I0'
            elif change == 'empty_map': cell['attributes']['X_ORIG_PORT_A1'] = ''
            elif change == 'mapping_type': cell['attributes']['X_ORIG_PORT_A1'] = 0
            elif change == 'two_outputs':
                cell['connections']['O5'] = [40]; cell['port_directions']['O5'] = 'output'; cell['attributes']['X_ORIG_PORT_O5'] = 'O'
            elif change == 'wrong_output': cell['attributes']['X_ORIG_PORT_O6'] = 'Q'
            elif change == 'missing_output': cell['connections']['O6'] = []; cell['attributes'].pop('X_ORIG_PORT_O6')
            else: cell['connections']['A1'] = [2, 3]
            with self.subTest(change=change), self.assertRaises(AssertionError): logical_lut(cell)

    def test_changed_INIT_or_logical_wire_incidence_still_fails(self):
        original = lut()
        for change in ('init', 'merge', 'swap', 'output', 'width', 'output_disconnected'):
            cell = deepcopy(original)
            if change == 'init': cell['parameters']['INIT'] = '11' * 4
            elif change == 'merge': cell['connections']['A2'] = cell['connections']['A1']
            elif change == 'swap': cell['connections']['A1'], cell['connections']['A2'] = cell['connections']['A2'], cell['connections']['A1']
            elif change == 'output': cell['connections']['O6'] = cell['connections']['A1']
            elif change == 'width': cell['parameters']['INIT'] = '0' + cell['parameters']['INIT']
            else: cell['connections']['O6'] = []
            with self.subTest(change=change), self.assertRaises(AssertionError):
                assert_circuit_identity(logical_design(original), logical_design(cell))

    def test_exact_XORCY_intermediate_metadata_and_disconnected_output_retained(self):
        cell = lut(2, init=format(0x6, '032b'))
        cell['attributes'].update(X_ORIG_PORT_I0='CI', X_ORIG_PORT_I1='LI', X_ORIG_PORT_O='O')
        cell['connections']['O6'] = []
        result = logical_lut(cell)
        self.assertEqual(result['connections']['O'], [])
        self.assertEqual(result['parameters'], cell['parameters'])
        for key, value in (('X_ORIG_PORT_I0', 'DI'), ('X_ORIG_PORT_I2', 'S'), ('X_ORIG_TYPE', 'LUT3')):
            bad = deepcopy(cell)
            bad['attributes'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): logical_lut(bad)
        bad = deepcopy(cell)
        bad['attributes'].pop('X_ORIG_PORT_I1')
        with self.assertRaises(AssertionError): logical_lut(bad)
        bad = deepcopy(cell)
        bad['parameters']['INIT'] = format(0xCA, '032b')
        with self.assertRaises(AssertionError): logical_lut(bad)

    def test_saved_real_small_route_preserves_all_BELs_and_logical_circuit(self):
        result = small_export_identity()
        self.assertEqual(result['resource_checks']['unchanged_physical_bel_assignments'], 18)
        self.assertEqual(result['original_logical_circuit_identity']['logical_board']['cells'], 18)
        self.assertFalse(result['new_native_routing_executed'])

    def test_saved_real_small_export_physical_resource_corruption_is_rejected(self):
        original = next(iter(json.loads((PARENT.parent / 'placed.json').read_text())['modules'].values()))
        routed = next(iter(json.loads((SMALL_ROUTE.parent / 'routed.json').read_text())['modules'].values()))
        with SiteBELMap(DATABASE, CONSTIDS) as database: footprint = physical_footprint(original, database)
        for change in ('missing', 'extra', 'type', 'bel', 'lut_attr', 'pad_attr', 'route', 'place', 'pack', 'freq', 'group'):
            module = deepcopy(routed)
            groups = {}
            cell = module['cells']['toggle_inv']
            if change == 'missing': module['cells'].pop('toggle_inv')
            elif change == 'extra': module['cells']['extra'] = deepcopy(cell)
            elif change == 'type': cell['type'] = 'SLICE_FFX'
            elif change == 'bel': cell['attributes']['NEXTPNR_BEL'] = 'SLICE_X0Y0/A5LUT'
            elif change == 'lut_attr': cell['attributes']['BEL_STRENGTH'] = 'changed'
            elif change == 'pad_attr': module['cells']['SYS_CLK']['attributes']['IOSTANDARD'] = 'LVCMOS33'
            elif change in ('route', 'place', 'pack'): module['settings'][change] = '0' * 32
            elif change == 'freq': module['settings']['target_freq'] = '25000000'
            else: groups = {'kernel0': 32}
            with self.subTest(change=change), self.assertRaises(AssertionError): verify_routed_footprint(module, footprint, groups)

    def test_real_database_translation_and_invalid_labels_fail_closed(self):
        with SiteBELMap(DATABASE, CONSTIDS) as database:
            self.assertEqual(database.global_label('X160Y205/SLICE_X0Y0.A5LUT'), 'SLICE_X94Y202/A5LUT')
            self.assertEqual(database.global_label('X147Y195/SLICE_X0Y0.A5LUT'), 'SLICE_X86Y212/A5LUT')
            for label in ('SLICE_X94Y202/A5LUT', 'X99999Y205/SLICE_X0Y0.A5LUT',
                          'WRONGX160Y205/SLICE_X0Y0.A5LUT', 'X160Y205/unknown', 'X-1Y205/SLICE_X0Y0.A5LUT'):
                with self.subTest(label=label), self.assertRaises(AssertionError): database.global_label(label)
            with self.assertRaises(AssertionError): database.checked(len(database.data), 1)
            with self.assertRaises(AssertionError): database.name(len(database.names))
        with patch.object(Path, 'read_text', return_value='X(WRONG_CONSTID_ENUM)\n'):
            with self.assertRaises(AssertionError): SiteBELMap(DATABASE, CONSTIDS)

    def test_route_argv_retains_original_checkpoint_device_clock_seed_and_no_waivers(self):
        argv = resume_argv('qualified-tool', 'original-placed.json', 'top', 'literal.xdc', 'routed.json', True)
        for flag, value in (('--device', 'xc7k480tffg1156-2'), ('--freq', '50'), ('--seed', '3588'),
                            ('--json', 'original-placed.json'), ('--router', 'router2')):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        for flag in ('--no-pack', '--no-place', '--Werror'): self.assertIn(flag, argv)
        for flag in ('--force', '--timing-allow-fail', '--ignore-loops', '--fasm', '--no-route'): self.assertNotIn(flag, argv)


if __name__ == '__main__':
    unittest.main()
