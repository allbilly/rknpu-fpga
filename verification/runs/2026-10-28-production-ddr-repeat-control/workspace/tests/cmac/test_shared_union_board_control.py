"""Literal whole-board transform controls, not full-board HDL/physical proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import prepare_shared_union_board as runner
from analyze_union_lut_pairs import proposals
from pair_board_luts import paired_cell
from test_board_lut_pair import lut


def fixture():
    module = dict(ports={'in': dict(direction='input', bits=[2, 3, 4, 5, 6]),
        'out': dict(direction='output', bits=list(range(20, 26)))}, cells={
        'small_a': lut('LUT3', [2, 3, 4], 20, '01101001'),
        'small_b': lut('LUT2', [5, 6], 21, '1000'),
        'both': paired_cell(lut('LUT3', [2, 3, 4], 22, '01101001'),
            lut('LUT3', [4, 3, 2], 23, '10010110'), [2, 3, 4]),
        'swap': paired_cell(lut('LUT3', [2, 3, 4], 24, '00010111'),
            lut('LUT3', [3, 4, 2], 25, '10001011'), [2, 3, 4]),
        'carry': dict(type='CARRY4', parameters={}, attributes={},
            connections={'S': [22, 23, '0', '0']}, port_directions={'S': 'input'}),
        'mux': dict(type='MUXF7', parameters={}, attributes={},
            connections={'I0': [24], 'I1': ['0']}, port_directions={'I0': 'input', 'I1': 'input'})})
    design = dict(modules={'test': module}, creator='literal fixture metadata')
    records, classes, _ = proposals(module)
    return design, {'test': records}, classes, {'test'}


class SharedUnionBoardControls(unittest.TestCase):
    def test_union_and_both_role_repairs_restore_every_original_field(self):
        original, records, classes, implementations = fixture(); before = deepcopy(original)
        candidate, certificate, functions = runner.transform(original, records, classes, implementations)
        self.assertEqual(original, before)
        self.assertEqual(len(certificate['test']['unions']), 1)
        self.assertEqual([r['mode'] for r in certificate['test']['roles']], ['split', 'swap'])
        self.assertEqual(len(candidate['modules']['test']['cells']), len(original['modules']['test']['cells']))
        self.assertTrue(all(not r['o5_has_dedicated_o6_sink'] for r in runner.audit_module(candidate['modules']['test'])))
        runner.verify_transform(original, candidate, certificate, functions, implementations)

    def test_changed_replacements_unrelated_hardware_ports_or_metadata_rejected(self):
        for mutation in ('init', 'wire', 'extra', 'deleted', 'port', 'metadata', 'role_init', 'role_output'):
            original, records, classes, implementations = fixture()
            candidate, certificate, functions = runner.transform(original, records, classes, implementations)
            cells = candidate['modules']['test']['cells']; union = certificate['test']['unions'][0]['name']
            if mutation == 'init': cells[union]['parameters']['INIT'] = '0' * 64
            elif mutation == 'wire': cells[union]['connections']['I1'] = [6]
            elif mutation == 'extra': cells['extra'] = deepcopy(cells[union])
            elif mutation == 'deleted': del cells['carry']
            elif mutation == 'port': candidate['modules']['test']['ports']['out']['bits'].pop()
            elif mutation == 'metadata': candidate['creator'] = 'changed'
            else:
                name = certificate['test']['roles'][0]['names'][0]
                if mutation == 'role_init': cells[name]['parameters']['INIT'] = '1' * 32
                else: cells[name]['connections']['O'] = [25]
            with self.subTest(mutation=mutation), self.assertRaises((AssertionError, KeyError)):
                runner.verify_transform(original, candidate, certificate, functions, implementations)

    def test_missing_duplicate_role_union_and_function_records_rejected(self):
        for mutation in ('missing_role', 'duplicate_role', 'missing_union', 'duplicate_union', 'extra_function', 'lost_function'):
            original, records, classes, implementations = fixture()
            candidate, certificate, functions = runner.transform(original, records, classes, implementations)
            if mutation == 'missing_role': certificate['test']['roles'].pop()
            elif mutation == 'duplicate_role': certificate['test']['roles'].append(deepcopy(certificate['test']['roles'][0]))
            elif mutation == 'missing_union': certificate['test']['unions'].pop()
            elif mutation == 'duplicate_union': certificate['test']['unions'].append(deepcopy(certificate['test']['unions'][0]))
            elif mutation == 'extra_function': functions['unlisted'] = deepcopy(next(iter(functions.values())))
            else: functions.pop(next(iter(functions)))
            with self.subTest(mutation=mutation), self.assertRaises((AssertionError, KeyError)):
                runner.verify_transform(original, candidate, certificate, functions, implementations)

    def test_unlisted_analysis_function_or_alias_collision_rejected(self):
        original, records, classes, implementations = fixture()
        classes['unlisted'] = deepcopy(next(iter(classes.values())))
        with self.assertRaises(AssertionError): runner.transform(original, records, classes, implementations)
        original, records, classes, implementations = fixture()
        original['modules']['test']['cells']['rk_union_pair_0'] = dict(type='unexpected')
        with self.assertRaises(AssertionError): runner.transform(original, records, classes, implementations)

    def test_exact_analysis_scope_rejects_running_failed_wrong_boundary_or_acceptance(self):
        report = dict(status='ANALYZED_SHARED_BOARD_UNION_FANIN_LUT_OPPORTUNITIES_ONLY', stage='complete',
            channels=32, kernels=16, parallel_products=512,
            implementation_copies={runner.TOP: 1, 'rk_cmac_fp16_cell_fixed_shared_xc7': 16,
                'rk_cmac_fp16_data_shared_xc7': 1},
            module_statistics={n: {'proposed_pairs': 1} for n in runner.IMPLEMENTATIONS},
            weighted_opportunities={'additional_disjoint_pairs': 18},
            projected_lut_primitives=32, candidate_lut_primitives=50,
            **{n: False for n in ('netlist_changed', 'function_classes_hdl_acceptance',
                'numerical_netlist_acceptance', 'packed_resource_acceptance', 'physical_fit_verified',
                'bitstream_emitted', 'hardware_programmed')})
        before = deepcopy(report); runner.validate_analysis(report); self.assertEqual(report, before)
        for mutation in ('status', 'stage', 'channels', 'kernels', 'products', 'copies', 'projection',
                'netlist_changed', 'function_classes_hdl_acceptance', 'numerical_netlist_acceptance',
                'packed_resource_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
            changed = deepcopy(report)
            if mutation == 'status': changed['status'] = 'RUNNING'
            elif mutation == 'stage': changed['stage'] = 'selection'
            elif mutation in ('channels', 'kernels'): changed[mutation] -= 1
            elif mutation == 'products': changed['parallel_products'] = 511
            elif mutation == 'copies': changed['implementation_copies'][runner.TOP] = 2
            elif mutation == 'projection': changed['projected_lut_primitives'] += 1
            else: changed[mutation] = True
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError): runner.validate_analysis(changed)


if __name__ == '__main__': unittest.main()
