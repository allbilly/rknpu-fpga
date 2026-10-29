"""Full-scope admission and placement-checker controls, not a native result."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'tools/openxc7')]
import place_prefix_shared_board as new


def fixture():
    counts = dict(DSP48E1_DSP48E1=515, RAMB36E1_RAMB36E1=6, SLICE_FFX=17519, SLICE_LUTX=1)
    labels = ['software_controls', 'DSP_feature_controls', 'LUT_census_controls', 'LUT_matching_controls',
              'generated_check', 'version', 'native_pack']
    argv = ['fixture-executable', '--chipdb', str(new.DATABASE), '--device', 'xc7k480tffg1156-2',
            '--top', new.TOP, '--json', 'fixture-input', '-o', 'xdc=fixture.xdc', '--pack-only',
            '--freq', '50', '--seed', '3588', '--Werror', '--debug', '--write', 'fixture-packed']
    return dict(status=new.PACKED, stage='complete', finished_utc='fixture-only', channels=32, kernels=16,
        parallel_products=512, retained_cmac_dsps=512, retained_shell_dsps=3, intended_part='xc7k480tffg1156-2',
        intended_clock_period_ns=20, seed=3588, native_census=dict(primitive_counts=counts, cells=sum(counts.values())),
        retained_kernel_dsps={'kernel_' + str(i): 32 for i in range(16)}, DSP_configurations_compared=515,
        extra_tile_only_ties_compared=4120, native_packing_executed=True, clock_constraint_admitted=True,
        production_source_before={'fixture': 1}, production_source_after={'fixture': 1},
        LUT_sharing_bound=dict(lut_cells=1, physical_LUT_positions=298600, lower_bound_exceeds_device=False,
            necessary_position_lower_bound=1, maximum_five_to_smaller_matching=0, minimum_cut_capacity=0,
            physical_fit_verified=False, native_placement_executed=False, placement_assignment_generated=False,
            hardware_execution_input_changed=False),
        commands=[dict(label=n, status='PASS_TOOL_EXECUTION_ONLY', returncode=0, argv=argv if n == 'native_pack' else []) for n in labels],
        executable={'path': 'fixture-executable'}, execution_input='fixture-input', packed_design='fixture-packed',
        **dict.fromkeys(('native_placement_executed', 'native_routing_executed', 'full_circuit_equivalence_claimed',
                        'numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff', 'electrical_verified',
                        'drc_signoff', 'bitstream_emitted', 'hardware_programmed', 'complete_ordinary_wire_identity_proved'), False))


def design():
    return dict(creator='Next Generation Place and Route (Version c68c135)', modules={'top': dict(
        settings=dict(pack='0' * 31 + '1', place='0' * 31 + '1', placer='heap', target_freq='50000000'),
        attributes={}, ports=dict(SYS_CLK=dict(direction='input', bits=[2]), SYS_RSTN=dict(direction='input', bits=[3]),
                                 led_3bits_tri_o=dict(direction='output', bits=[4, 5, 6])),
        cells={'a': dict(type='SLICE_LUTX', attributes={'NEXTPNR_BEL': 'X0Y0/A6LUT'}),
               'b': dict(type='SLICE_FFX', attributes={'NEXTPNR_BEL': 'X0Y0/AFF'})})})


class SharedPlacementAdmission(unittest.TestCase):
    def reject(self, mutate):
        report = fixture()
        mutate(report)
        with self.assertRaises(AssertionError):
            new.validate_pack(report)

    def test_completed_full_pack_metadata_without_mutation(self):
        report = fixture()
        before = deepcopy(report)
        new.validate_pack(report)
        self.assertEqual(report, before)

    def test_running_failed_unfinished_or_wrong_stage_rejected(self):
        for key, value in (('status', 'RUNNING'), ('status', 'FAIL_PREFIX_SHARED_NATIVE_PACK'),
                           ('stage', 'complete_actual_native_census'), ('finished_utc', None)):
            self.reject(lambda r, k=key, v=value: r.update({k: v}))

    def test_shrunk_target_part_clock_or_seed_rejected(self):
        for key, value in (('channels', 16), ('kernels', 8), ('parallel_products', 256), ('retained_cmac_dsps', 256),
                           ('retained_shell_dsps', 0), ('intended_part', 'xc7k480tffg1156-1'),
                           ('intended_clock_period_ns', 40), ('seed', 0)):
            self.reject(lambda r, k=key, v=value: r.update({k: v}))

    def test_incomplete_actual_inventory_or_source_rejected(self):
        self.reject(lambda r: r['native_census']['primitive_counts'].update(DSP48E1_DSP48E1=514))
        self.reject(lambda r: r['native_census'].update(cells=1))
        self.reject(lambda r: r['retained_kernel_dsps'].pop('kernel_0'))
        self.reject(lambda r: r['retained_kernel_dsps'].update(kernel_0=31))
        self.reject(lambda r: r.update(production_source_after={'fixture': 2}))

    def test_capacity_conflict_or_incomplete_bound_rejected(self):
        self.reject(lambda r: r['LUT_sharing_bound'].update(lower_bound_exceeds_device=True))
        self.reject(lambda r: r['LUT_sharing_bound'].update(necessary_position_lower_bound=298601))
        self.reject(lambda r: r['LUT_sharing_bound'].update(physical_LUT_positions=597200))
        self.reject(lambda r: r['LUT_sharing_bound'].update(minimum_cut_capacity=1))
        self.reject(lambda r: r['LUT_sharing_bound'].update(lut_cells=2))

    def test_missing_dsp_comparison_clock_or_actual_pack_rejected(self):
        for key, value in (('DSP_configurations_compared', 514), ('extra_tile_only_ties_compared', 4112),
                           ('clock_constraint_admitted', False), ('native_packing_executed', False)):
            self.reject(lambda r, k=key, v=value: r.update({k: v}))

    def test_inferred_acceptance_or_assignment_rejected(self):
        for key in ('native_placement_executed', 'native_routing_executed', 'full_circuit_equivalence_claimed',
                    'numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff', 'electrical_verified',
                    'drc_signoff', 'bitstream_emitted', 'hardware_programmed', 'complete_ordinary_wire_identity_proved'):
            self.reject(lambda r, k=key: r.update({k: True}))
        self.reject(lambda r: r['LUT_sharing_bound'].update(placement_assignment_generated=True))
        self.reject(lambda r: r['LUT_sharing_bound'].update(hardware_execution_input_changed=True))

    def test_missing_failed_or_waived_native_command_rejected(self):
        self.reject(lambda r: r['commands'].pop())
        self.reject(lambda r: r['commands'][-1].update(returncode=1))
        self.reject(lambda r: r['commands'][-1].update(status='RUNNING'))
        for flag in ('--timing-allow-fail', '--unknown', '--no-pack'):
            self.reject(lambda r, f=flag: r['commands'][-1]['argv'].append(f))
        self.reject(lambda r: r['commands'][-1]['argv'].__setitem__(r['commands'][-1]['argv'].index('--freq') + 1, '25'))


class SharedPlacementChecks(unittest.TestCase):
    version = '"nextpnr-himbaechel" -- Next Generation Place and Route (Version c68c135)'
    counts = dict(SLICE_LUTX=1, SLICE_FFX=1)

    def test_generic_exact_membership_and_unique_bel_checks(self):
        checks, translation = new.compare_placement(design(), self.version, self.counts, None, {'a', 'b'})
        self.assertEqual(checks['unique_bel_slots'], 2)
        self.assertFalse(checks['full_placed_numerical_acceptance'])
        self.assertFalse(translation['graph_data_changed'])

    def test_changed_complete_membership_rejected_even_when_counts_match(self):
        value = design()
        module = value['modules']['top']
        module['cells']['renamed'] = module['cells'].pop('a')
        with self.assertRaises(AssertionError):
            new.compare_placement(value, self.version, self.counts, None, {'a', 'b'})

    def test_duplicate_bel_or_wrong_stage_rejected(self):
        for mutation in ('duplicate', 'routed', 'static', 'unplaced'):
            value = design()
            module = value['modules']['top']
            if mutation == 'duplicate':
                module['cells']['b']['attributes']['NEXTPNR_BEL'] = module['cells']['a']['attributes']['NEXTPNR_BEL']
            elif mutation == 'routed':
                module['settings']['route'] = '0' * 31 + '1'
            elif mutation == 'static':
                module['settings']['placer'] = 'static'
            else:
                module['settings']['place'] = '0' * 32
            with self.assertRaises(AssertionError):
                new.compare_placement(value, self.version, self.counts, None, {'a', 'b'})

    def test_native_arguments_preserve_full_target_and_no_shortcuts(self):
        argv = new.placement_argv('fixture', 'input', 'literal.xdc', 'output')
        new.verify_full_argv(argv)
        for flag in ('--force', '--timing-allow-fail', '--parallel-refine', '--no-pack', '--placer-heap-beta'):
            with self.assertRaises(AssertionError):
                new.verify_full_argv(argv + [flag])
        self.assertEqual(new.NATIVE_TIMEOUT, 43200)

    def test_actual_saved_packed_name_reader_is_complete(self):
        from pack_prefix_shared_board import QUALIFICATION
        path = QUALIFICATION.parent / 'clock-admitted-packed.json'
        expected = set(next(iter(json.loads(path.read_text())['modules'].values()))['cells'])
        self.assertEqual(new.packed_names(path), expected)
        with tempfile.TemporaryDirectory(prefix='rknpu-shared-placement-reader-') as directory:
            bad = Path(directory) / 'comparison-only.json'
            bad.write_bytes(path.read_bytes()[:-20])
            with self.assertRaises(AssertionError):
                new.packed_names(bad)


if __name__ == '__main__':
    unittest.main()
