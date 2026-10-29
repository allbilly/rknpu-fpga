"""Exact original-job read-only audit guards, not process cancellation proof."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/openxc7'))
import audit_capacity_conflicted_heap as audit


class OriginalCapacityAuditControls(unittest.TestCase):
    def test_completed_source_bound_conflict_and_no_inferred_physical_acceptance(self):
        report = json.loads(audit.BOUND.read_text())
        audit.check_bound(report)
        for key, value in (('status', 'RUNNING'), ('full_target_parallel_products', 256), ('seed', 1),
                           ('finished_utc', None), ('bitstream_emitted', True), ('physical_fit_verified', True)):
            wrong = deepcopy(report)
            wrong[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                audit.check_bound(wrong)
        for key, value in (('lut_cells', 488080), ('necessary_position_lower_bound', 295139),
                           ('physical_LUT_positions', 597200), ('minimum_cut_capacity', 18139)):
            wrong = deepcopy(report)
            wrong['matching_bound'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                audit.check_bound(wrong)

    def test_exact_unit_invocation_pid_input_and_full_arguments_mandatory(self):
        report = json.loads(audit.LIVE.read_text())
        report.update(status='RUNNING', stage='native_place', supervisor_pid=audit.SUPERVISOR)
        report['commands'][-1].update(status='RUNNING', pid=audit.NATIVE)
        unit = dict(ActiveState='active', SubState='running', MainPID=str(audit.SUPERVISOR), InvocationID=audit.INVOCATION)
        command = report['commands'][-1]['argv']
        audit.check_live(report, unit, command)
        for key, value in (('ActiveState', 'failed'), ('SubState', 'dead'), ('MainPID', '1'), ('InvocationID', 'other')):
            with self.subTest(key=key), self.assertRaises(AssertionError):
                audit.check_live(report, dict(unit, **{key: value}), command)
        for key, value in (('status', 'PASS'), ('stage', 'complete'), ('supervisor_pid', 1)):
            with self.subTest(key=key), self.assertRaises(AssertionError):
                audit.check_live(dict(report, **{key: value}), unit, command)
        wrong = deepcopy(report)
        wrong['commands'][-1]['pid'] = 1
        with self.assertRaises(AssertionError):
            audit.check_live(wrong, unit, command)
        with self.assertRaises(AssertionError):
            audit.check_live(report, unit, command + ['--force'])

    def test_no_signal_stop_delete_or_shared_input_action_in_auditor(self):
        import inspect
        source = inspect.getsource(audit.main)
        self.assertNotIn('kill', source)
        self.assertNotIn("'stop'", source)
        self.assertNotIn('unlink', source)
        self.assertIn("recomputed == bound['matching_bound']", source)
        self.assertIn("digest(input_path)", source)
        self.assertIn("actual == original == ['0x68a070d4']", source)


if __name__ == '__main__':
    unittest.main()
