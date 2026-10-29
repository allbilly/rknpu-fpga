"""Private whole-regression compiler options; not RTL/numerical/FPGA evidence."""
import copy
import inspect
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/openxc7'))
import run_source_identical_production_opt0 as subject


def fixture():
    return dict(status='FAIL', finished_utc='fixture-only', actual_make_test_executed=True,
        production_source_before={'sha256': 'fixture-only'}, production_source_after={'sha256': 'fixture-only'},
        declared_source_files=101, commands=[dict(argv=['make', '-j2', '-o', 'vectors', '-o', 'cmac-vectors', 'test'],
            status='FAIL', returncode=2, timeout_seconds=7200, seconds=3030.576)],
        **dict.fromkeys(('full_board_numerical_acceptance', 'physical_fit_verified', 'timing_signoff',
            'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed', 'hardware_input_modified'), False))


class SourceIdenticalProductionOpt0Control(unittest.TestCase):
    def test_only_options_archival_and_completed_failure_admission_change(self):
        restored = subject.MAIN_SOURCE
        for old, new in reversed(subject.REPLACEMENTS):
            self.assertEqual(restored.count(new), 1); restored = restored.replace(new, old)
        self.assertEqual(restored, inspect.getsource(subject.previous.main))
        self.assertEqual(subject.OPTIONS, ['OPT_FAST=-O0', 'OPT_SLOW=-O0'])
        self.assertIs(subject.NAMESPACE['REPORTS'], subject.previous.REPORTS)
        self.assertEqual(len(subject.previous.REPORTS), 5)
        for name in ('source_revision', 'verify_bindings', 'FIXTURE_DIRECTORIES'):
            self.assertIs(subject.NAMESPACE[name], subject.previous.__dict__[name])

    def test_every_original_whole_report_numerical_source_warning_and_deadline_guard_preserved(self):
        old = inspect.getsource(subject.previous.main)
        for text in ('for name,status in REPORTS.items()', "assert r['status']==status and r['finished_utc']",
            "revision==report['production_source_before']", "r['cases']>1000000 and r['seed']=='0x3588'",
            "all(c['status']=='PASS' and c['returncode']==0 for c in r['commands'])",
            "all(t['status']=='PASS' for t in r['tests'])", 'verify_bindings(before);verify_bindings(copied)',
            "assert report['production_source_after']==report['production_source_before']",
            'timeout_seconds=7200', 'process.wait(timeout=7200)', 'os.killpg(process.pid,signal.SIGKILL)',
            'for directory in FIXTURE_DIRECTORIES:', 'assert digest(target)==sha'):
            self.assertGreater(subject.MAIN_SOURCE.count(text), 0)
            self.assertEqual(subject.MAIN_SOURCE.count(text), old.count(text))
        makefile = (ROOT / 'Makefile').read_text()
        self.assertIn('CXXFLAGS ?= -O2 -std=c++17 -Wall -Wextra -Werror', makefile)
        self.assertIn('test: model-test lint rtl-test four-state-test cmac-test cmac-four-state-test', makefile)
        self.assertNotIn('CXXFLAGS=', subject.MAIN_SOURCE)
        self.assertNotIn('timeout=601', subject.MAIN_SOURCE)

    def test_actual_make_command_variables_override_only_documented_generated_cpp_options(self):
        script = 'include ' + str(subject.VERILATED_MAKE) + "\nshow-options:\n\t@printf '%s\\n' '$(origin OPT_FAST)|$(OPT_FAST)' '$(origin OPT_SLOW)|$(OPT_SLOW)'\n"
        run = subprocess.run(['make', '--no-print-directory', '-s', '-f', '-', *subject.OPTIONS, 'show-options'],
            input=script, text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stderr, '')
        self.assertEqual(run.stdout.splitlines(), ['command line|-O0', 'command line|-O0'])

    def test_complete_failed_default_scope_not_running_success_or_changed_target(self):
        subject.metadata(fixture())
        for key, value in (('status', 'RUNNING'), ('status', 'PASS'), ('finished_utc', None),
            ('actual_make_test_executed', False), ('declared_source_files', 100),
            ('production_source_after', {'sha256': 'different'})):
            record = fixture(); record[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): subject.metadata(record)
        for key, value in (('status', 'PASS'), ('returncode', 0), ('timeout_seconds', 7201),
                           ('seconds', 7200), ('argv', ['make', 'test'])):
            record = fixture(); record['commands'][0][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): subject.metadata(record)

    def test_all_unsupported_acceptance_flags_stay_false(self):
        for key in ('full_board_numerical_acceptance', 'physical_fit_verified', 'timing_signoff',
            'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed', 'hardware_input_modified'):
            record = fixture(); record[key] = True
            with self.subTest(key=key), self.assertRaises(AssertionError): subject.metadata(record)

    def test_running_parent_cannot_create_new_private_whole_regression(self):
        before = set((ROOT / 'build/source-identical-production-opt0').glob('*'))
        with tempfile.TemporaryDirectory(prefix='production-opt0-parent-control-', dir=ROOT / 'build') as directory:
            path = Path(directory) / 'report.json'; path.write_text('{"status":"RUNNING"}')
            with patch.object(subject, 'PARENT', path), self.assertRaisesRegex(AssertionError, 'Require completed failed default producer'):
                subject.main()
        self.assertEqual(set((ROOT / 'build/source-identical-production-opt0').glob('*')), before)
        self.assertLess(subject.MAIN_SOURCE.index('admitted=admission()'), subject.MAIN_SOURCE.index('out.mkdir'))


if __name__ == '__main__':
    unittest.main()
