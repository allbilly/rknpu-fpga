"""Terminal/full-profile archive admission controls, not HDL or FPGA evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/cmac'), str(Path(__file__).resolve().parent)]
import archive_dsp_prefix_observed_mapped_board as archive
from test_dsp_prefix_observed_mapped_board_control import result


def fixture(status=archive.PASS):
    labels = ['yosys_version', 'iverilog_version', 'vvp_version', 'model_commit', 'model_clean',
              'export', 'compile', 'negative', *('mode' + str(mode) for mode in range(9))]
    return dict(status=status, stage='complete', finished_utc='software-fixture-only',
                source={'files': {'fixture': 'not-a-real-manifest'}}, artifacts={'files': {'fixture': 'not-a-real-manifest'}},
                channels=32, kernels=16, parallel_products=512, intended_part='xc7k480tffg1156-2',
                intended_clock_period_ns=20,
                configurations=dict(kernel_dsp_configurations=32, shell_dsp_configurations=3,
                                    physical_cmac_dsps=512, total_physical_dsps=515),
                modes=list(range(9)), upstream_model_commit=archive.replay.models.COMMIT,
                model_four_state_yosys_equivalence=False, physical_fit_verified=False,
                bitstream_emitted=False, hardware_programmed=False,
                numerical_netlist_acceptance=status == archive.PASS,
                export_circuit_identity='PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE',
                commands=[dict(log=label + '.log', status='PASS', returncode=int(label == 'negative')) for label in labels],
                tests=[dict(mode=mode, status='PASS', result=result(mode).strip()) for mode in range(9)],
                error='actual failed gate' if status == 'FAIL' else None)


class PrefixObservedMappedBoardArchiveControls(unittest.TestCase):
    def test_only_terminal_exact_profiles_admitted(self):
        archive.verify_terminal_metadata(fixture())
        archive.verify_terminal_metadata(fixture('FAIL'))
        for key, value in (('status', 'RUNNING'), ('status', 'OTHER_PROFILE_PASS'), ('finished_utc', None),
                           ('channels', 16), ('kernels', 8), ('parallel_products', 256),
                           ('intended_part', 'xc7a100t'), ('intended_clock_period_ns', 100),
                           ('source', {'files': {}}), ('artifacts', {'files': {}}), ('configurations', {}),
                           ('modes', [0]), ('upstream_model_commit', 'different'),
                           ('model_four_state_yosys_equivalence', True), ('physical_fit_verified', True),
                           ('bitstream_emitted', True), ('hardware_programmed', True)):
            report = fixture()
            report[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                archive.verify_terminal_metadata(report)

    def test_pass_requires_real_negative_all_modes_and_export(self):
        for key, value in (('stage', 'compile'), ('numerical_netlist_acceptance', False),
                           ('export_circuit_identity', 'COUNTS_ONLY'), ('commands', []), ('tests', [])):
            report = fixture()
            report[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                archive.verify_terminal_metadata(report)
        for index, key, value in ((7, 'returncode', 0), (16, 'status', 'RUNNING'), (6, 'returncode', 1)):
            report = fixture()
            report['commands'][index][key] = value
            with self.subTest(index=index), self.assertRaises(AssertionError):
                archive.verify_terminal_metadata(report)
        report = fixture()
        report['tests'] = report['tests'][:-1]
        with self.assertRaises(AssertionError):
            archive.verify_terminal_metadata(report)
        report = fixture()
        report['tests'][7]['status'] = 'SKIPPED'
        with self.assertRaises(AssertionError):
            archive.verify_terminal_metadata(report)

    def test_failure_is_never_promoted_to_numeric_acceptance(self):
        report = fixture('FAIL')
        for key, value in (('error', ''), ('numerical_netlist_acceptance', True)):
            changed = deepcopy(report)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                archive.verify_terminal_metadata(changed)


if __name__ == '__main__':
    unittest.main()
