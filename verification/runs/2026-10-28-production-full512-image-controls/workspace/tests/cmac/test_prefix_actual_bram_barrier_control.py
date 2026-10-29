"""Actual BRAM pin roles, physical ghost events and unchanged native gates."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import prove_prefix_actual_bram_barrier as new


class ActualBRAMBarrierControl(unittest.TestCase):
    def test_actual_completed_temporal_and_six_BRAM_wiring_control_parents(self):
        bindings={};original,cert,selected,brams,classification,wire,control=new.admit(bindings)
        for p in (new.PARENT,new.WIRING,new.CONTROLS):self.assertIn(str(p),bindings)
        self.assertEqual(len(brams),6);self.assertEqual(len(original['controller_registers']),50)
        self.assertTrue(cert['one_post_edge_clear_application_is_fixed_point'])
        self.assertEqual(wire['logical_signal_physical_wires']['demo.index'],original['signals']['demo.index'])
        self.assertEqual({n for n in brams if not classification[n]['readonly']},{'rk_mapped_cell_86684','rk_mapped_cell_86685'})

    def test_model_counts_physical_pin_events_without_changing_real_register_folds(self):
        cone=json.loads((new.completed.previous.qualified.PREPARED.parent/'actual-initialization-controller-cone.json').read_text())
        # Fixture only: reuse existing driven outputs to check text generation,
        # not claim that this incomplete fixture has actual BRAM write drivers.
        for name in new.PIN_SIGNALS:cone['signals'][name]=cone['signals']['demo.memory.host_fire']
        text=new.clock_model(cone)
        self.assertIn('else if(bram_host_enable&&bram_host_we)',text)
        self.assertIn('physical_write_equivalence',text);self.assertIn('physical_ports_exclusive',text)
        self.assertIn('physical_read_barrier',text);self.assertIn('writes_seen==13\'d4096&&probe_written',text)
        self.assertIn('reg [49:0] storage_state;',text);self.assertNotIn('storage_state=',text)
        self.assertNotIn('assume',text);self.assertNotIn('force',text)
        self.assertEqual(text.count(' ? 1\'b0 : next_clock['),50)

    def test_all_original_actual_primitive_guards_and_full_target_budgets_remain(self):
        self.assertIn('len(nodes) <= 503128',new.temporal.TRACE_SOURCE)
        self.assertIn('len(cuts) <= 17519+432',new.temporal.TRACE_SOURCE)
        self.assertEqual(sum(new.REGISTERS.values()),50);self.assertEqual(len(new.OUTPUTS),14)
        self.assertEqual(set(new.PIN_SIGNALS.values()),{'ENARDEN','ENBWREN','WEA','WEBWE'})
        text=new.script(Path('/library.v'),Path('/model.v'),False,Path('/witness.json'))
        self.assertIn('-seq 1 -tempinduct-def -maxsteps 4',text);self.assertIn('-set-init-def',text)
        for flag in ('-set-init-zero','-set-assumes','-prove-x','-tempinduct-skip','-ignore-unknown-cells'):self.assertNotIn(flag,text)

    def test_strict_native_diagnostics_and_vector_padding_rejections(self):
        old=new.completed.previous
        positive='Base case for induction length 1 proven.\n'+old.SUCCESS+'\n'
        self.assertEqual(old.validate(positive,0,False),1)
        for bad in (positive+'Warning: waived\n',positive+'timeout reached\n',positive+'unknown cell\n'):
            with self.assertRaises(AssertionError):old.validate(bad,0,False)
        footer='strict-footer';vendor=''.join(f'VECTOR {i:04d} 0\n' for i in range(1024))+footer+'\n'
        self.assertEqual(new.compare_corpora(vendor,vendor,1,footer,3)['per_instance_comparisons'],3072)
        for bad in (vendor.replace('VECTOR 0000 0','VECTOR 0000 x'),vendor.replace('VECTOR 0000 0','VECTOR 0000 2'),vendor+'warning: waived\n'):
            with self.assertRaises(AssertionError):new.compare_corpora(vendor,bad,1,footer,3)


if __name__=='__main__':unittest.main()
