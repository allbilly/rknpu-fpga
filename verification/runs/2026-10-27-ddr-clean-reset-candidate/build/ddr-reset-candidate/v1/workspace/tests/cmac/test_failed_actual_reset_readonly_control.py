"""Read-only failure controls, not controller startup or FPGA acceptance."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import trace_failed_actual_reset_startup as trace

REPORT=trace.ROOT/'build/openxc7/failed-reset-readonly-trace-1791456691562076912/report.json'


class Controls(unittest.TestCase):
    def setUp(self):
        self.cone=json.loads((trace.PARENT.parent/'actual-53-register-reset-controller-cone.json').read_text())

    def test_observer_only_reads_original_hierarchy_without_repair(self):
        text=trace.observer(self.cone)
        self.assertIn('@(posedge tb_prefix_actual_reset_startup.clk); #1;',text)
        self.assertIn('actual.producer_input[778]',text)
        self.assertNotRegex(text,r'\b(?:assign|initial|force|release|deposit|fatal|finish|stop)\b')

    def test_changed_fault_init_is_not_admitted(self):
        changed=copy.deepcopy(self.cone)
        changed['producer_cuts']['50677']['original_primitive']['parameters']['INIT']='0'
        with self.assertRaises(AssertionError):trace.observer(changed)

    def test_original_failure_and_native_finite_negative_remain_fail_and_rejection(self):
        r=json.loads(trace.PARENT.read_text())
        self.assertEqual(r['status'],'FAIL')
        self.assertFalse(r['actual_vendor_controller_startup_fixture_passed'])
        c={s['label']:s for s in r['commands']}
        self.assertEqual(c['negative']['status'],'PASS_EXPECTED_REAL_FINITE_NEGATIVE')
        self.assertEqual(c['positive']['returncode'],1)
        self.assertIn('Time: 172000 ',Path(c['positive']['log']).read_text())

    def test_completed_observer_bundle_is_bound_without_startup_acceptance(self):
        r=json.loads(REPORT.read_text())
        self.assertEqual(r['stage'],'complete')
        self.assertTrue(r['read_only_failure_reproduced'])
        self.assertEqual(len(r['observed_trace']),9)
        for key in ('entire_upstream_chain_revalidated','startup_acceptance','hardware_input_modified','electrical_verified',
                    'timing_signoff','drc_signoff','bitstream_emitted','hardware_programmed'):
            self.assertFalse(r[key])
        trace.verify_bindings(r['source']);trace.verify_bindings(r['execution_inputs'])
        trace.verify_bindings({str(trace.ROOT/p):sha for p,sha in r['artifacts'].items()})
        self.assertEqual(trace.observer(self.cone),(REPORT.parent/'read_only_observer.sv').read_text())


if __name__=='__main__':unittest.main()
