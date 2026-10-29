"""Continuation archive software controls; generated fixtures are not HDL proof."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/cmac'), str(Path(__file__).resolve().parent)]
import archive_dsp_prefix_observed_board_continuation as archive
from test_dsp_prefix_observed_board_resume_control import completed


def fixture():
    report = completed()
    report.update(status=archive.resume.PASS, stage='complete', finished_utc='software-fixture-only',
                  numerical_netlist_acceptance=True, parent_source_sha256='1' * 64,
                  parent_archive_sha256='2' * 64,
                  reused_compile_inputs={'files': {'software-fixture-only': '0' * 64}},
                  reused_compiled_executable_manifest={'files': {'software-fixture-only': '0' * 64}},
                  runtime_program={'path': '/software-fixture-only/vvp', 'sha256': '3' * 64},
                  vvp_version='software-fixture-version-only')
    return report


def execution_fixture(directory, failed=False):
    report = fixture()
    binary = ROOT / 'build/software-fixture-only/board.vvp'
    negative = directory / 'software-negative-cwd'
    for label, step in zip(archive.LABELS, report['commands']):
        step.update(log=str((directory / (label + '.log')).relative_to(ROOT)),
                    wall_timeout_seconds=86400, seconds=1, pid=1)
        if label == 'runtime_version':
            step.update(argv=[report['runtime_program']['path'], '-V'], cwd='.')
            text = report['vvp_version'] + '\n'
        else:
            mode = 0 if label == 'negative' else int(label.removeprefix('mode'))
            step.update(argv=[report['runtime_program']['path'], str(binary), '+MODE=' + str(mode)],
                        cwd=str(negative.relative_to(ROOT)) if label == 'negative' else '.')
            text = ('FATAL: software-fixture: board demo numerical/address mismatch output=0\n'
                    if label == 'negative' else step['result'] + '\n')
        (ROOT / step['log']).write_text(text)
    if failed:
        report.update(status='FAIL', stage='mode0', error='actual software-fixture failed command',
                      numerical_netlist_acceptance=False, tests=[])
        report['commands'] = report['commands'][:3]
        report['commands'][-1].update(status='FAIL', returncode=-9)
        report['execution_inputs'] = {name: report['execution_inputs'][name] for name in ('negative', 'mode0')}
    return report, binary, negative, report['reused_execution_inputs']


class ContinuationArchiveControls(unittest.TestCase):
    def test_terminal_full_profile_and_completed_admission_only(self):
        report = fixture()
        archive.terminal_metadata(report)
        for key, value in (('status', 'RUNNING'), ('status', archive.resume.archive.PASS),
                           ('finished_utc', None), ('channels', 16), ('kernels', 8), ('parallel_products', 256),
                           ('modes', [0]), ('intended_part', 'xc7a100t'), ('intended_clock_period_ns', 100),
                           ('parent_status', 'PASS'), ('original_failure_preserved', False),
                           ('reused_compiled_executable', False), ('upstream_model_commit', 'different'),
                           ('wall_timeout_seconds', 14400), ('source', {'files': {}}), ('artifacts', {'files': {}}),
                           ('parent_source_sha256', 'wrong'), ('parent_archive_sha256', 'wrong'),
                           ('reused_compile_inputs', {'files': {}}), ('reused_execution_inputs', {'files': {}}),
                           ('model_four_state_yosys_equivalence', True), ('physical_fit_verified', True),
                           ('bitstream_emitted', True), ('hardware_programmed', True)):
            changed = deepcopy(report)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                archive.terminal_metadata(changed)

    def test_pass_requires_fresh_negative_complete_modes_and_results(self):
        for key, value in (('commands', []), ('tests', []), ('negative_reexecuted', False),
                           ('numerical_netlist_acceptance', False)):
            report = fixture()
            report[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                archive.terminal_metadata(report)
        report = fixture()
        report['commands'][1]['returncode'] = 0
        with self.assertRaises(AssertionError):
            archive.terminal_metadata(report)

    def test_valid_own_logs_with_full_existing_transaction_contracts(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='continuation-archive-controls-') as temporary:
            directory = Path(temporary)
            report, binary, negative, binding = execution_fixture(directory)
            archive.terminal_metadata(report)
            archive.execution_contract(report, directory, binary, negative, binding, report['vvp_version'])

    def test_parent_log_substitution_rejected_even_with_matching_marker(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='continuation-archive-controls-') as temporary:
            directory = Path(temporary)
            report, binary, negative, binding = execution_fixture(directory)
            other = directory / 'parent-log'
            other.mkdir()
            (other / 'negative.log').write_text((directory / 'negative.log').read_text())
            report['commands'][1]['log'] = str((other / 'negative.log').relative_to(ROOT))
            with self.assertRaises(AssertionError):
                archive.execution_contract(report, directory, binary, negative, binding, report['vvp_version'])

    def test_changed_argv_cwd_budget_returncode_binding_or_log_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='continuation-archive-controls-') as temporary:
            directory = Path(temporary)
            report, binary, negative, binding = execution_fixture(directory)
            for index, key, value in ((1, 'argv', ['vvp', 'wrong']), (2, 'cwd', 'different'),
                                      (3, 'wall_timeout_seconds', 14400), (4, 'returncode', 1),
                                      (0, 'pid', 0)):
                changed = deepcopy(report)
                changed['commands'][index][key] = value
                with self.subTest(key=key), self.assertRaises(AssertionError):
                    archive.execution_contract(changed, directory, binary, negative, binding, report['vvp_version'])
            changed = deepcopy(report)
            changed['execution_inputs']['mode8']['sha256'] = 'f' * 64
            with self.assertRaises(AssertionError):
                archive.execution_contract(changed, directory, binary, negative, binding, report['vvp_version'])
            path = directory / 'mode8.log'
            path.write_text(path.read_text() + 'warning: ignored\n')
            with self.assertRaises(AssertionError):
                archive.execution_contract(report, directory, binary, negative, binding, report['vvp_version'])

    def test_real_failure_scope_preserved_without_positive_acceptance(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='continuation-archive-controls-') as temporary:
            directory = Path(temporary)
            report, binary, negative, binding = execution_fixture(directory, failed=True)
            archive.terminal_metadata(report)
            archive.execution_contract(report, directory, binary, negative, binding, report['vvp_version'])
            self.assertFalse(report['numerical_netlist_acceptance'])
            report['numerical_netlist_acceptance'] = True
            with self.assertRaises(AssertionError):
                archive.terminal_metadata(report)

    def test_original_archiver_still_refuses_new_profile(self):
        with self.assertRaises(AssertionError):
            archive.resume.archive.verify_terminal_metadata(fixture())


if __name__ == '__main__':
    unittest.main()
