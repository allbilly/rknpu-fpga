"""Selected-controller fixture controls, not native startup acceptance."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import qualify_prefix_actual_reset_startup as new


class Controls(unittest.TestCase):
    def test_completed_physical_pin_binary_parent_is_required_and_revalidated(self):
        before={};cone=new.admit(before)
        self.assertIn(str(new.PARENT),before)
        self.assertEqual(len(cone['controller_registers']),50)
        self.assertEqual(len(cone['cells']),1328)

    def test_buffered_reset_boundary_rejects_other_pin_or_primitive(self):
        cell=dict(type='IBUF',connections={'I':[3],'O':[9]},port_directions={'I':'input','O':'output'},parameters={'IOSTANDARD':'LVCMOS18'})
        self.assertIn('NOT_IO_OR_ELECTRICAL',new.reset_boundary(cell,'O',0,9,3))
        for changed in ({**cell,'type':'LUT1'},{**cell,'parameters':{'IOSTANDARD':'LVCMOS33'}},{**cell,'connections':{'I':[3],'O':[10]}}):
            with self.assertRaises(AssertionError):new.reset_boundary(changed,'O',0,9,3)

    def test_bench_retains_unknown_producers_default_GSR_full_prefix_and_async_phases(self):
        text=new.render_bench(968)
        self.assertIn("producer_input='x",text)
        self.assertIn("controller_state!==50'bx",text)
        self.assertIn('total_writes!=10241||complete_prefixes!=2||reset_pulses!=3',text)
        self.assertIn('wait(prefix_writes==2048)',text)
        self.assertNotIn('force ',text)
        self.assertNotIn('@OTHER_',text)
        self.assertEqual(sum(new.REGISTERS.values()),53)
        self.assertIn('len(nodes) <= 503128',new.TRACE_SOURCE)

    def test_real_negative_is_finite_and_frontend_errors_are_refused(self):
        text='FATAL: /bench.sv:1: actual reset startup mismatch phase=after_gsr got=000 expected=100\n       Time: 102000 Scope: tb_prefix_actual_reset_startup\n'
        new.validate_native(text,1,True,Path('/bench.sv'),968)
        for bad in (text.replace('got=000','got=xxx'),text.replace('phase=after_gsr','phase=cold'),text+'Warning: waived\n','ERROR: unknown cell\n'):
            with self.assertRaises(AssertionError):new.validate_native(bad,1,True,Path('/bench.sv'),968)


if __name__=='__main__':unittest.main()
