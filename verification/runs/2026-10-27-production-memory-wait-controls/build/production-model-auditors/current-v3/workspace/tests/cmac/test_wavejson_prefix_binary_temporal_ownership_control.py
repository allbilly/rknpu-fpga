"""Native initial/sparse vector frames without changing actual SAT or goldens."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import resume_wavejson_prefix_binary_temporal_ownership as new


def witness():
    root=new.FAILED.parent
    return (root/'negative.log').read_text(),json.loads((root/'negative-counterexample.json').read_text())


class WaveJSONTemporalControl(unittest.TestCase):
    def test_preserved_actual_failure_and_original_inputs_native_script(self):
        bindings={};cone,model,library,certificate=new.admit(bindings)
        self.assertIn(str(new.FAILED),bindings);self.assertEqual(len(cone['controller_registers']),50)
        self.assertEqual(model,(new.FAILED.parent/'actual-binary-temporal-controller.v').read_text())
        self.assertTrue(certificate['one_post_edge_clear_application_is_fixed_point'])
        self.assertIn(b'module LUT1',library)

    def test_actual_sparse_three_frame_wavejson_matches_every_native_table_value(self):
        text,wave=witness();r=new.negative_trace(text,wave)
        self.assertTrue(r['native_wavejson_table_crosschecked']);self.assertEqual(r['actual_frames'][2]['safe'],1)
        self.assertEqual(r['actual_frames'][2]['ok'],0);self.assertEqual(r['actual_initial_values']['seen_reset'],0)
        self.assertNotEqual(r['actual_initial_values']['storage_state'],0)
        self.assertEqual(new.decode_signal(dict(name='probe',wave='=.=',data=['000000000000','000000000001'])),[0,0,1])

    def test_unknown_width_unused_data_extra_signal_and_changed_trace_rejected(self):
        text,wave=witness()
        for change in ('unknown','width','unused','extra','changed'):
            bad=copy.deepcopy(wave)
            probe=next(s for s in bad['signal'] if s['name']=='probe')
            if change=='unknown':probe['data'][1]='x'+probe['data'][1][1:]
            elif change=='width':probe['data'][1]=probe['data'][1][1:]
            elif change=='unused':probe['data'].append('000000000000')
            elif change=='extra':bad['signal'].append(dict(name='opaque',wave='401'))
            else:probe['data'][1]='000000000001'
            with self.assertRaises(AssertionError):new.negative_trace(text,bad)

    def test_old_numeric_negative_and_warning_timeout_gates_are_unchanged(self):
        self.assertIn("first['seen_reset']==0 and first['reset_n']==0 and first['ok']==1",new.TRACE_SOURCE)
        self.assertIn("last['seen_reset']==1 and last['reset_n']==1 and last['safe']==1 and last['ok']==0",new.TRACE_SOURCE)
        self.assertNotIn('ignore-unknown-cells',new.MAIN_SOURCE)
        text,_=witness()
        for bad in (text+'Warning: waived\n',text+'timeout reached\n'):
            with self.assertRaises(AssertionError):new.previous.validate(bad,1,True)


if __name__=='__main__':unittest.main()
