"""Shared-board admission/weighting controls, not transformed FPGA proof."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import analyze_shared_union_lut_pairs as runner
from test_board_lut_pair import lut


def metadata():
    return dict(status='PREPARED_SHARED_CONE_BOARD_NETLIST_ONLY',
        channels=32, kernels=16, parallel_products=512, circuit_lift_verified=True,
        export_circuit_identity='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE',
        numerical_netlist_acceptance=False, physical_fit_verified=False,
        bitstream_emitted=False, hardware_programmed=False,
        commands=[dict(log=label + '.log', status='PASS', returncode=0)
            for label in ('version', 'export', 'elaborate_check')])


def hierarchy():
    cells = {f'kernel{i}': dict(type=runner.PRIVATE) for i in range(16)}
    cells['shared'] = dict(type=runner.SHARED)
    modules = {runner.TOP: dict(cells=cells),
        runner.PRIVATE: dict(cells={'paired': dict(type='LUT6_2'), 'small': dict(type='LUT3')}),
        runner.SHARED: dict(cells={'small': dict(type='LUT3')}),
        'LUT6_2': dict(attributes={'blackbox': '1'}),
        'LUT3': dict(attributes={'blackbox': '1'})}
    return modules, dict(cells_after={'LUT6_2': 16, 'LUT3': 17}, lut_count=33, physical_lut_pairs=16)


class SharedUnionControls(unittest.TestCase):
    def test_completed_shared_metadata_is_not_mutated(self):
        value = metadata(); before = deepcopy(value)
        runner.validate_shared_metadata(value)
        self.assertEqual(value, before)

    def test_running_private_incomplete_or_misrepresented_parent_rejected(self):
        for case in ('running', 'failed', 'private', 'channels', 'kernels', 'products',
                'lift', 'export', 'missing_step', 'duplicated_step', 'reordered_steps', 'step_failure',
                'exit_failure', 'numerical_netlist_acceptance', 'physical_fit_verified',
                'bitstream_emitted', 'hardware_programmed'):
            value = metadata()
            if case in ('running', 'failed', 'private'):
                value['status'] = {'running': 'RUNNING', 'failed': 'FAIL',
                    'private': 'PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY'}[case]
            elif case in ('channels', 'kernels'): value[case] -= 1
            elif case == 'products': value['parallel_products'] = 511
            elif case == 'lift': value['circuit_lift_verified'] = False
            elif case == 'export': value['export_circuit_identity'] = 'count_only'
            elif case == 'missing_step': value['commands'].pop()
            elif case == 'duplicated_step': value['commands'].append(deepcopy(value['commands'][-1]))
            elif case == 'reordered_steps': value['commands'].reverse()
            elif case == 'step_failure': value['commands'][1]['status'] = 'FAIL'
            elif case == 'exit_failure': value['commands'][1]['returncode'] = 1
            else: value[case] = True
            with self.subTest(case=case), self.assertRaises(AssertionError): runner.validate_shared_metadata(value)

    def test_actual_three_module_multiplicity_and_resource_weighting(self):
        modules, report = hierarchy(); before = deepcopy(modules)
        self.assertEqual(runner.validate_counts(modules, report),
            Counter({runner.TOP: 1, runner.PRIVATE: 16, runner.SHARED: 1}))
        self.assertEqual(modules, before)

    def test_changed_copy_counts_cells_or_unknown_primitives_rejected(self):
        for case in ('lost_private', 'extra_private', 'lost_shared', 'extra_shared',
                'resource_counts', 'lut_total', 'pair_total', 'unknown_hardware', 'nonblackbox'):
            modules, report = hierarchy()
            if case == 'lost_private': del modules[runner.TOP]['cells']['kernel0']
            elif case == 'extra_private': modules[runner.TOP]['cells']['extra'] = dict(type=runner.PRIVATE)
            elif case == 'lost_shared': del modules[runner.TOP]['cells']['shared']
            elif case == 'extra_shared': modules[runner.TOP]['cells']['extra'] = dict(type=runner.SHARED)
            elif case == 'resource_counts': report['cells_after']['LUT3'] -= 1
            elif case == 'lut_total': report['lut_count'] += 1
            elif case == 'pair_total': report['physical_lut_pairs'] -= 1
            elif case == 'unknown_hardware': modules[runner.PRIVATE]['cells']['bad'] = dict(type='unmodeled')
            else: modules['LUT3']['attributes']['blackbox'] = '0'
            with self.subTest(case=case), self.assertRaises(AssertionError): runner.validate_counts(modules, report)

    def test_shared_and_private_proposals_preserve_raw_module_data(self):
        for name in (runner.PRIVATE, runner.SHARED, runner.TOP):
            module = dict(ports={'input': dict(direction='input', bits=[2, 3, 4, 5, 6])}, cells={
                'a': lut('LUT3', [2, 3, 4], 20, '01101001'),
                'b': lut('LUT2', [5, 6], 21, '1000')})
            before = deepcopy(module)
            records, classes, _ = runner.proposals(module)
            self.assertEqual(len(records), 1, name)
            runner.verify_proposals(module, records, classes)
            self.assertEqual(module, before)


if __name__ == '__main__': unittest.main()
