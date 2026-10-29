"""Strict actual-domain admission controls, not full-board or physical proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import test_union_lut_functions as runner
from analyze_union_lut_pairs import proposals
from test_union_lut_pairs import fixture


def domain():
    module = fixture(); records, classes, skipped = proposals(module)
    copies = {'ypcb_cmac_array_top': 1, 'kernel': 16}
    report = dict(status='ANALYZED_UNION_FANIN_LUT_OPPORTUNITIES_ONLY', stage='complete',
        channels=32, kernels=16, parallel_products=512, implementation_copies=copies,
        module_statistics={name: dict(proposed_pairs=1, **skipped) for name in copies},
        weighted_opportunities={'additional_disjoint_pairs': 17}, candidate_lut_primitives=100,
        projected_lut_primitives=83, unique_proposed_function_classes=1)
    report.update({name: False for name in ('netlist_changed', 'function_classes_hdl_acceptance',
        'numerical_netlist_acceptance', 'packed_resource_acceptance', 'physical_fit_verified',
        'bitstream_emitted', 'hardware_programmed')})
    return report, {name: deepcopy(module) for name in copies}, {name: deepcopy(records) for name in copies}, list(classes.values())


class UnionFunctionProofControls(unittest.TestCase):
    def test_exact_two_module_fixture_domain_and_original_inputs_retained(self):
        values = domain(); before = deepcopy(values)
        self.assertEqual(runner.validate_domain(*values), 2048)
        self.assertEqual(values, before)

    def test_running_failed_wrong_shape_projection_and_acceptance_claims_rejected(self):
        for case in ('running', 'failed', 'stage', 'shape', 'copies', 'count', 'projection',
                'netlist_changed', 'function_classes_hdl_acceptance', 'physical_fit_verified'):
            report, _, _, _ = domain()
            if case in ('running', 'failed'): report['status'] = case.upper()
            elif case == 'stage': report['stage'] = 'selection'
            elif case == 'shape': report['parallel_products'] = 16
            elif case == 'copies': report['implementation_copies']['kernel'] = 1
            elif case == 'count': report['weighted_opportunities']['additional_disjoint_pairs'] = 16
            elif case == 'projection': report['projected_lut_primitives'] = 82
            else: report[case] = True
            with self.subTest(case=case), self.assertRaises(AssertionError): runner.validate_analysis(report)

    def test_function_coverage_wire_truth_roles_and_proposal_count_mutations_rejected(self):
        for case in ('missing_module', 'duplicate_class', 'constant_class', 'missing_class',
                'proposal_count', 'wire', 'truth', 'role'):
            report, modules, records, classes = domain()
            if case == 'missing_module': del records['kernel']
            elif case == 'duplicate_class': classes.append(deepcopy(classes[0]))
            elif case == 'constant_class': classes[0]['fanins'] = 0
            elif case == 'missing_class': classes = []
            elif case == 'proposal_count': records['kernel'] = []
            elif case == 'wire': modules['kernel']['cells']['a']['connections']['I0'] = [9]
            elif case == 'truth': modules['kernel']['cells']['a']['parameters']['INIT'] = '0' * 8
            else: records['kernel'][0]['dedicated_o6_sinks']['O5'] = [dict(cell='wrong')]
            with self.subTest(case=case), self.assertRaises(AssertionError):
                runner.validate_domain(report, modules, records, classes)


if __name__ == '__main__': unittest.main()
