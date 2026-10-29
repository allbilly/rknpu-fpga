"""Clean replay admission controls. Mock metadata is not HDL/FPGA evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/cmac')]
import verify_dsp_prefix_clean_replay as clean
import vivado_dsp_prefix_array as checkpoint


def mock_report():
    return dict(status=clean.STATUS, stage='complete', finished_utc='MOCK_NOT_EXECUTED',
        channels=32, kernels=16, parallel_products=512, frames=208, expected_outputs=3328,
        seed='0x35883216', result=clean.original.EXPECTED,
        library_operations=['combo_update', 'create', 'seq_update'],
        **{name: True for name in ('complete_build_diagnostics_accepted', 'full_mapped_gate_accepted',
            'numerical_netlist_binary_fixture_acceptance', 'reused_compiled_kernel',
            'reused_actual_generated_top', 'original_failures_preserved')},
        **{name: False for name in ('four_state_x_acceptance', 'raw_board_numerical_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')},
        operational_library_path_contract=dict(changed_generated_variable='VM_HIER_LIBS',
            make_dependency_resolves_to_same_library=True, stock_archive_extraction_resolves_to_same_library=True,
            rtl_or_generated_cpp_changed=False),
        archive_member_contract=dict(kernel_object_count=10, top_object_count=9, merged_object_count=19,
            exact_member_multiset_verified=True),
        commands=[dict(log='MOCK/' + label + '.log', status='PASS',
            returncode=1 if label == 'negative_test' else 0) for label in clean.LABELS])


class CleanReplayAdmissionControl(unittest.TestCase):
    def test_mock_full_metadata_and_checkpoint_dispatch(self):
        report = mock_report()
        clean.validate_metadata(report)
        checkpoint.validate_mapped_metadata(report)
        with patch.object(checkpoint.json, 'loads', return_value=report), \
                patch.object(Path, 'read_text', return_value='MOCK'), \
                patch.object(clean, 'verify', return_value=report) as verify:
            paths = [ROOT / ('build/MOCK_' + name + '.json') for name in ('mapped', 'area', 'native')]
            self.assertEqual(checkpoint.verify_mapped(*paths, {'area': 'MOCK'}, {'native': 'MOCK'}), report)
            verify.assert_called_once_with(*paths, {'area': 'MOCK'}, {'native': 'MOCK'})

    def test_unclean_reused_top_and_incomplete_statuses_rejected(self):
        for status in ('RUNNING', 'FAIL',
                'PASS_FULL_C32K16_DSP_PREFIX_ARRAY_MAPPED_BINARY_REUSED_TOP_FIXTURES_ONLY'):
            report = mock_report(); report['status'] = status
            with self.assertRaises(AssertionError): clean.validate_metadata(report)

    def test_full_geometry_result_and_seed_required(self):
        for name, value in (('channels', 16), ('kernels', 8), ('parallel_products', 256),
                ('frames', 207), ('expected_outputs', 3312), ('seed', '0'), ('result', 'PASS smaller'),
                ('stage', 'simulation'), ('finished_utc', '')):
            report = mock_report(); report[name] = value
            with self.subTest(name=name), self.assertRaises(AssertionError): clean.validate_metadata(report)

    def test_actual_clean_build_and_numerical_flags_required(self):
        for name in ('complete_build_diagnostics_accepted', 'full_mapped_gate_accepted',
                'numerical_netlist_binary_fixture_acceptance', 'reused_compiled_kernel',
                'reused_actual_generated_top', 'original_failures_preserved'):
            report = mock_report(); report[name] = False
            with self.subTest(name=name), self.assertRaises(AssertionError): clean.validate_metadata(report)

    def test_no_physical_or_four_state_claim_inferred(self):
        for name in ('four_state_x_acceptance', 'raw_board_numerical_acceptance',
                'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
            report = mock_report(); report[name] = True
            with self.subTest(name=name), self.assertRaises(AssertionError): clean.validate_metadata(report)

    def test_all_operations_and_same_path_contract_required(self):
        report = mock_report(); report['library_operations'].remove('seq_update')
        with self.assertRaises(AssertionError): clean.validate_metadata(report)
        for name, value in (('changed_generated_variable', 'AR'),
                ('make_dependency_resolves_to_same_library', False),
                ('stock_archive_extraction_resolves_to_same_library', False),
                ('rtl_or_generated_cpp_changed', True)):
            report = mock_report(); report['operational_library_path_contract'][name] = value
            with self.subTest(name=name), self.assertRaises(AssertionError): clean.validate_metadata(report)

    def test_complete_commands_and_real_negative_required(self):
        for change in ('missing', 'duplicate', 'running', 'negative_zero', 'positive_nonzero', 'boolean_code'):
            report = mock_report()
            if change == 'missing': report['commands'].pop()
            elif change == 'duplicate': report['commands'].append(deepcopy(report['commands'][-1]))
            elif change == 'running': report['commands'][-1]['status'] = 'RUNNING'
            elif change == 'negative_zero': report['commands'][-2]['returncode'] = 0
            elif change == 'boolean_code': report['commands'][-1]['returncode'] = False
            else: report['commands'][-1]['returncode'] = 1
            with self.subTest(change=change), self.assertRaises(AssertionError): clean.validate_metadata(report)

    def test_exact_archive_contract_required(self):
        for name, value in (('exact_member_multiset_verified', False), ('kernel_object_count', 0),
                ('top_object_count', 0), ('merged_object_count', 18)):
            report = mock_report(); report['archive_member_contract'][name] = value
            with self.subTest(name=name), self.assertRaises(AssertionError): clean.validate_metadata(report)


if __name__ == '__main__':
    unittest.main()
