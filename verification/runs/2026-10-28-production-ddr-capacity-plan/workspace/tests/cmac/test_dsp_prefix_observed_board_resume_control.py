"""Fail-closed cached-board replay controls; software fixtures, not HDL proof."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/cmac'), str(Path(__file__).resolve().parent)]
import resume_dsp_prefix_observed_mapped_board as resume
from test_dsp_prefix_observed_mapped_board_archive_control import fixture
from test_dsp_prefix_observed_mapped_board_control import result

DIRECTORY = ROOT / 'build/software-resume-fixture-only'


def timeout_parent():
    report = fixture('FAIL')
    report['source']['sha256'] = '1' * 64
    report.update(stage='mode0', tests=[])
    report['commands'] = report['commands'][:9]
    argv = ['vvp', str(DIRECTORY / 'board.vvp'), '+MODE=0']
    report['commands'][-1] = dict(log='mode0.log', status='FAIL', argv=argv, cwd='.', seconds=14405.105)
    report['error'] = repr(subprocess.TimeoutExpired(argv, 14400))
    report['execution_inputs'] = {'negative': {}, 'mode0': {}}
    return report


def archive_index():
    members = {'software-fixture-only': '0' * 64}
    encoded = ''.join(f'{value}  {name}\n' for name, value in members.items())
    return dict(status='ARCHIVED_TERMINAL_FULL_C32K16_PREFIX_OBSERVED_MAPPED_BOARD_RUN_ONLY',
                finished_utc='software-fixture-only', original_run_status='FAIL',
                original_run_report=str((DIRECTORY / 'report.json').relative_to(ROOT)),
                source_sha256='1' * 64, verified_members=1,
                members=dict(files=members, sha256=hashlib.sha256(encoded.encode()).hexdigest()),
                archive_sha256='2' * 64, archive_bytes=1, numerical_netlist_acceptance=False,
                model_four_state_yosys_equivalence=False, physical_fit_verified=False,
                bitstream_emitted=False, hardware_programmed=False)


def completed():
    report = timeout_parent()
    labels = ['runtime_version', 'negative', *('mode' + str(mode) for mode in range(9))]
    binding = {'files': {'software-fixture-only': '0' * 64}, 'sha256': '0' * 64}
    report.update(status='RUNNING', stage='mode8', error=None,
                  parent_status='FAIL', original_failure_preserved=True, reused_compiled_executable=True,
                  negative_reexecuted=True, wall_timeout_seconds=86400,
                  commands=[dict(log=label + '.log', status='PASS', returncode=int(label == 'negative'))
                            for label in labels],
                  tests=[dict(mode=mode, status='PASS', result=result(mode).strip()) for mode in range(9)],
                  execution_inputs={label: deepcopy(binding) for label in labels[1:]},
                  reused_execution_inputs=binding)
    report['commands'][1]['result'] = 'REJECTED_EXACT_FIRST_OUTPUT_GOLDEN_BIT'
    for mode, step in enumerate(report['commands'][2:]):
        step['result'] = result(mode).strip()
    return report


class ObservedBoardResumeControls(unittest.TestCase):
    def bundle_fixture(self, directory, corruption=None):
        source, artifact, path = (directory / name for name in ('source.txt', 'artifact.txt', 'report.json'))
        source.write_text('software source fixture only\n')
        artifact.write_text('software artifact fixture only\n')
        parent = dict(source=resume.fingerprint([source]), artifacts=resume.fingerprint([artifact]))
        path.write_text(json.dumps(parent))
        members = {**parent['source']['files'], **parent['artifacts']['files'],
                   **resume.fingerprint([path, Path(resume.archive.__file__).resolve()])['files']}
        if corruption == 'content':
            source.write_text('changed software fixture bytes\n')
        bundle = directory / 'evidence.tar.gz'
        with tarfile.open(bundle, 'w:gz') as packed:
            for name in members:
                if corruption == 'missing' and name == str(source.relative_to(ROOT)):
                    continue
                packed.add(ROOT / name, arcname=name, recursive=False)
            if corruption == 'duplicate':
                name = str(source.relative_to(ROOT))
                packed.add(source, arcname=name, recursive=False)
            if corruption == 'traversal':
                packed.add(source, arcname='../source.txt', recursive=False)
        encoded = ''.join(f'{members[name]}  {name}\n' for name in sorted(members, key=Path))
        index = archive_index()
        index.update(original_run_report=str(path.relative_to(ROOT)), source_sha256=parent['source']['sha256'],
                     verified_members=len(members), members=dict(files=members, sha256=hashlib.sha256(encoded.encode()).hexdigest()),
                     archive_sha256=resume.digest(bundle), archive_bytes=bundle.stat().st_size)
        index_path = directory / 'index.json'
        index_path.write_text(json.dumps(index))
        (directory / 'archive_SHA256SUMS').write_text(index['archive_sha256'] + '  evidence.tar.gz\n')
        return index_path, parent, path

    def test_actual_streamed_software_bundle_members_and_checksum(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='resume-controls-') as temporary:
            index_path, parent, path = self.bundle_fixture(Path(temporary))
            index, bundle = resume.verify_bundle(index_path, parent, path)
            self.assertEqual(index['archive_sha256'], resume.digest(bundle))
            changed = json.loads(index_path.read_text())
            changed['archive_sha256'] = '0' * 64
            index_path.write_text(json.dumps(changed))
            with self.assertRaises(AssertionError):
                resume.verify_bundle(index_path, parent, path)

    def test_changed_missing_duplicate_and_traversal_bundle_members_rejected(self):
        for corruption in ('content', 'missing', 'duplicate', 'traversal'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory(
                    dir=ROOT / 'build', prefix='resume-controls-') as temporary:
                index_path, parent, path = self.bundle_fixture(Path(temporary), corruption)
                with self.assertRaises(AssertionError):
                    resume.verify_bundle(index_path, parent, path)

    def test_only_bounded_longer_integer_wall_budget(self):
        self.assertEqual(resume.validate_budget(86400), 86400)
        self.assertEqual(resume.validate_budget(172800), 172800)
        for value in (True, False, None, 0, 14400, -1, 172801, 86400.0, '86400'):
            with self.subTest(value=value), self.assertRaises(AssertionError):
                resume.validate_budget(value)

    def test_only_exact_terminal_full_profile_mode_zero_timeout(self):
        report = timeout_parent()
        resume.timeout_metadata(report, DIRECTORY)
        for key, value in (('status', 'RUNNING'), ('stage', 'negative'), ('finished_utc', None),
                           ('channels', 16), ('kernels', 8), ('parallel_products', 256),
                           ('intended_part', 'xc7a100t'), ('intended_clock_period_ns', 100),
                           ('tests', [{'mode': 0, 'status': 'PASS'}]), ('commands', []),
                           ('export_circuit_identity', 'COUNTS_ONLY'), ('error', 'numerical mismatch'),
                           ('execution_inputs', {'mode0': {}}), ('numerical_netlist_acceptance', True),
                           ('physical_fit_verified', True), ('bitstream_emitted', True)):
            changed = deepcopy(report)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises((AssertionError, IndexError)):
                resume.timeout_metadata(changed, DIRECTORY)

    def test_failed_negative_or_different_terminal_command_rejected(self):
        for index, key, value in ((7, 'status', 'FAIL'), (7, 'returncode', 0),
                                  (8, 'status', 'PASS'), (8, 'returncode', 0),
                                  (8, 'cwd', 'different'), (8, 'seconds', 1),
                                  (8, 'argv', ['vvp', 'different', '+MODE=0'])):
            changed = timeout_parent()
            changed['commands'][index][key] = value
            with self.subTest(index=index, key=key), self.assertRaises(AssertionError):
                resume.timeout_metadata(changed, DIRECTORY)

    def test_archive_requires_exact_parent_members_and_failure_scope(self):
        parent, index = timeout_parent(), archive_index()
        members = index['members']['files']
        path = DIRECTORY / 'report.json'
        resume.archive_metadata(index, parent, path, members)
        for key, value in (('status', 'RUNNING'), ('finished_utc', None), ('original_run_status', 'PASS'),
                           ('original_run_report', 'different'), ('source_sha256', 'different'),
                           ('verified_members', 0), ('members', {'files': {}, 'sha256': '0' * 64}),
                           ('archive_sha256', 'wrong'), ('archive_bytes', 0),
                           ('numerical_netlist_acceptance', True), ('model_four_state_yosys_equivalence', True),
                           ('physical_fit_verified', True), ('bitstream_emitted', True), ('hardware_programmed', True)):
            changed = deepcopy(index)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                resume.archive_metadata(changed, parent, path, members)
        changed = deepcopy(index)
        changed['members']['sha256'] = '0' * 64
        with self.assertRaises(AssertionError):
            resume.archive_metadata(changed, parent, path, members)

    def test_completion_requires_fresh_negative_and_every_mode(self):
        report = completed()
        resume.validate_completed(report)
        for key, value in (('status', 'FAIL'), ('stage', 'negative'), ('error', 'actual failure'),
                           ('numerical_netlist_acceptance', True),
                           ('channels', 16), ('kernels', 8), ('parallel_products', 256), ('modes', [0]),
                           ('intended_part', 'xc7a100t'), ('intended_clock_period_ns', 100),
                           ('parent_status', 'PASS'), ('original_failure_preserved', False),
                           ('reused_compiled_executable', False), ('negative_reexecuted', False),
                           ('wall_timeout_seconds', 14400), ('commands', []), ('tests', report['tests'][:-1]),
                           ('execution_inputs', {}), ('model_four_state_yosys_equivalence', True),
                           ('physical_fit_verified', True), ('bitstream_emitted', True)):
            changed = deepcopy(report)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                resume.validate_completed(changed)
        changed = deepcopy(report)
        changed['execution_inputs']['mode8']['sha256'] = '1' * 64
        with self.assertRaises(AssertionError):
            resume.validate_completed(changed)
        for step in (1, 2, 10):
            changed = deepcopy(report)
            changed['commands'][step]['result'] = 'PASS other result'
            with self.subTest(step=step), self.assertRaises(AssertionError):
                resume.validate_completed(changed)

    def test_existing_numerical_and_fault_contracts_are_not_weakened(self):
        for mode in range(9):
            text = result(mode)
            self.assertEqual(resume.replay.simulation_result(text, 0, mode), text.strip())
            for bad, code in ((text.replace('init=4096', 'init=1'), 0), (text, 1),
                              (text + 'warning: ignored\n', 0), (text + 'FATAL: extra\n', 0)):
                with self.subTest(mode=mode), self.assertRaises(AssertionError):
                    resume.replay.simulation_result(bad, code, mode)


if __name__ == '__main__':
    unittest.main()
