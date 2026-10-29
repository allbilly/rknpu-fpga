"""Strict actual-input admission, no skipped proofs, genuine trace controls."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import prove_prefix_binary_temporal_ownership as new


def trace():
    first={name:0 for name in new.SHOW};first['ok']=1
    last={name:0 for name in new.SHOW};last.update(seen_reset=1,reset_n=1,safe=1)
    text=''.join(f' {t:3d} \\{name:20s} {v:3d} {v:x} {v:b}\n' for t,frame in ((1,first),(2,last)) for name,v in frame.items())
    wave={'signal':[dict(name=name,wave='4014') for name in new.SHOW]}
    return text,wave


class BinaryTemporalOwnershipControl(unittest.TestCase):
    def test_actual_50_bit_model_qualified_cells_clears_and_both_negatives_admitted(self):
        bindings={};cone,model,library,cert=new.admit(bindings)
        self.assertIn(str(new.QUALIFIED),bindings);self.assertIn(str(new.qualified.PREPARED),bindings)
        self.assertEqual(len(cone['controller_registers']),50);self.assertEqual(len(cone['cells']),1325)
        self.assertTrue(cert['one_post_edge_clear_application_is_fixed_point'])
        self.assertIn('reg [49:0] storage_state;',model);self.assertNotIn('storage_state=',model)
        self.assertIn("reg seen_reset=1'b0",model);self.assertIn('probe<=arbitrary_probe',model)
        self.assertIn(b'module LUT1',library)

    def test_literal_native_induction_base_cases_and_binary_only_scope(self):
        text=new.script(Path('/qualified/library.v'),Path('/qualified/model.v'),False,Path('/qualified/witness.json'))
        self.assertIn('-seq 1 -tempinduct-def -maxsteps 4',text)
        self.assertIn('-set-def-inputs -set-init-def',text);self.assertIn('-verify -prove ok 1 -timeout 120',text)
        self.assertIn('dffunmap\nopt_clean\ncheck -assert',text)
        for flag in ('-set-init-zero','-set-assumes','-prove-x','-tempinduct-skip','-prove-skip','-ignore-unknown-cells'):
            self.assertNotIn(flag,text)

    def test_strict_actual_induction_success_and_actual_base_case_failure(self):
        positive='Base case for induction length 1 proven.\n'+new.SUCCESS+'\n'
        negative=new.FAILURE+'\nERROR: Called with -verify and proof did fail!\n'
        self.assertEqual(new.validate(positive,0,False),1);new.validate(negative,1,True)
        for text,code,neg in ((positive+'Warning: waived\n',0,False),(new.SUCCESS,0,False),(positive.replace('length 1','length 2'),0,False),
            (positive+'Reached maximum number of time steps\n',0,False),(negative.replace('FAIL!','SUCCESS!'),1,True),
            (negative.replace('ERROR: Called with -verify and proof did fail!',''),1,True),(negative+'timeout reached\n',1,True),(positive,0,True)):
            with self.assertRaises(AssertionError):new.validate(text,code,neg)

    def test_genuine_two_step_finite_negative_requires_reset_safe_and_only_wrong_golden(self):
        text,wave=trace();record=new.negative_trace(text,wave)
        self.assertTrue(record['reset_observed_before_wrong_golden_failure'])
        rows=((f' {1:3d} \\{"reset_n":20s} {0:3d} 0 0',f' {3:3d} \\{"reset_n":20s} {0:3d} 0 0'),
            (f' {2:3d} \\{"safe":20s} {1:3d} 1 1',f' {2:3d} \\{"safe":20s} {0:3d} 0 0'))
        for old,changed in rows:
            self.assertIn(old,text)
            with self.assertRaises(AssertionError):new.negative_trace(text.replace(old,changed,1),wave)
        bad=copy.deepcopy(wave);bad['signal'][0]['name']='fake'
        with self.assertRaises(AssertionError):new.negative_trace(text,bad)
        with self.assertRaises(AssertionError):new.negative_trace('',wave)


if __name__=='__main__':unittest.main()
