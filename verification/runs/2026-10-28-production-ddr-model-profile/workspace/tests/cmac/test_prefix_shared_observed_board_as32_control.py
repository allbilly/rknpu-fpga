"""Wider host-AS runner controls, not a full numerical/FPGA result."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/cmac'), str(ROOT / 'tools/openxc7'), str(Path(__file__).parent)]
import test_prefix_shared_observed_board_as32 as runner
import test_prefix_shared_observed_board_control as old

ExistingReplayControls = old.ExistingReplayControls
ExistingSharedRunnerControls = old.SharedNumericalRunnerControls


class HostAddressSpaceControls(unittest.TestCase):
    def test_reversible_whole_runner_and_no_numerical_gate_changes(self):
        source = runner.MAIN_SOURCE
        for before, after in reversed(runner.REPLACEMENTS):
            self.assertEqual(source.count(after), 1)
            source = source.replace(after, before)
        self.assertEqual(source, inspect.getsource(runner.previous.main))
        self.assertEqual(runner.ADDRESS_BYTES, 34359738368)
        for key in ('verify_prepared', 'execution_files', 'full_result', 'source_revision'):
            self.assertIs(runner.NAMESPACE[key], getattr(runner.previous, key))
        for text in ('compile_timeout_seconds=21600', 'each_mode_timeout_seconds=86400',
                     'original.simulation_result(text, code, mode, negative)',
                     "('negative', 0, negative_cwd)", 'for m in original.MODES',
                     "run('compile', ['iverilog', '-g2012', '-Ttyp'",
                     "'tb_cmac_array_bram_demo', '-s', 'glbl'", 'full_result(report[',
                     'not re.search(', 'Changed actual simulation input'):
            self.assertEqual(runner.MAIN_SOURCE.count(text), inspect.getsource(runner.previous.main).count(text))
            self.assertGreater(runner.MAIN_SOURCE.count(text), 0)
        self.assertLess(runner.MAIN_SOURCE.index('verify_failed_parent()'), runner.MAIN_SOURCE.index('out.mkdir('))
        self.assertNotIn('MemoryMax', runner.MAIN_SOURCE)
        self.assertNotIn('MemorySwapMax', runner.MAIN_SOURCE)

    def test_actual_allocation_failure_not_relabelled_numerical_result(self):
        report = json.loads(runner.FAILED.read_text())
        log = Path(report['commands'][-1]['log']).read_text()
        before = deepcopy(report)
        runner.verify_failed_metadata(report, log)
        self.assertEqual(report, before)
        self.assertNotEqual(report['status'], runner.SUCCESS)
        for key, value in (('status', 'RUNNING'), ('stage', 'complete'), ('finished_utc', None),
            ('parallel_products', 256), ('modes', [0]), ('tests', [{'mode': 0}]),
            ('numerical_netlist_acceptance', True), ('old_executable_or_numerical_result_inherited', True),
            ('default_global_startup_preserved', False), ('runtime_CPU_arithmetic_or_layout_fixup', True),
            ('compile_timeout_seconds', 43200), ('each_mode_timeout_seconds', 1)):
            changed = deepcopy(report); changed[key] = value
            with self.subTest(field=key), self.assertRaises(AssertionError): runner.verify_failed_metadata(changed, log)
        for key in runner.previous.PHYSICAL_FLAGS:
            changed = deepcopy(report); changed[key] = True
            with self.subTest(flag=key), self.assertRaises(AssertionError): runner.verify_failed_metadata(changed, log)

    def test_timeout_wrong_failure_or_unaccepted_compile_cannot_admit(self):
        report = json.loads(runner.FAILED.read_text())
        log = Path(report['commands'][-1]['log']).read_text()
        for field, value in (('status', 'PASS'), ('returncode', -9), ('returncode', 0),
                             ('seconds', 21600), ('timeout_seconds', 43200)):
            changed = deepcopy(report); changed['commands'][-1][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(AssertionError): runner.verify_failed_metadata(changed, log)
        with self.assertRaises(AssertionError): runner.verify_failed_metadata(report, 'different failure')
        for key in ('compiled_executable', 'execution_inputs'):
            changed = deepcopy(report); changed[key] = {}
            with self.subTest(field=key), self.assertRaises(AssertionError): runner.verify_failed_metadata(changed, log)


if __name__ == '__main__':
    unittest.main()
