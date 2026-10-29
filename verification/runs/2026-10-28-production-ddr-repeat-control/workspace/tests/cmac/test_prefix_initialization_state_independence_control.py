"""Complete actual cache retrace, corpus negatives and original strict SAT gates."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import prove_prefix_initialization_state_independence as new


class InitStateIndependenceControl(unittest.TestCase):
    def test_actual_complete_admission_retrace_fold_binding_and_no_new_claim(self):
        bindings={};cone,text=new.admit(bindings)
        self.assertGreater(len(bindings),580)
        self.assertEqual(len(cone['cells']),497);self.assertEqual(len(cone['producer_cuts']),695)
        self.assertIn("wire init_phase=(state <= 4'd2)",text)
        self.assertNotIn('assume',text)

    def test_cached_missing_driver_or_extra_unreachable_cell_rejected(self):
        cone=json.loads((new.PREPARED.parent/'actual-initialization-state-cone.json').read_text())
        selected=json.loads(new.state.raw.ROOT.joinpath('build/openxc7/prefix-config-contract-1791401020849392343/actual-selected-primitives.json').read_text())
        bad=copy.deepcopy(cone);del bad['producer_cuts'][next(iter(bad['producer_cuts']))]
        with self.assertRaises(AssertionError):new.replay_cone(bad,selected)
        bad=copy.deepcopy(cone);record=copy.deepcopy(next(iter(bad['cells'].values())))
        record['connections']['O']=[999999999];bad['cells']['unreachable_fake']=record
        with self.assertRaises(AssertionError):new.replay_cone(bad,selected)

    def test_corpus_requires_every_known_vector_and_real_mutation(self):
        footer='fixture:1: $finish called at 1125000 (1ps)'
        vendor=''.join(f'VECTOR {i:04d} 0\n' for i in range(1024))+footer+'\n'
        good=vendor.replace('VECTOR 0000 0','VECTOR 0000 1')
        self.assertEqual(new.compare_corpora(vendor,vendor,1,footer)['per_instance_comparisons'],508928)
        new.validate_wrong_corpus(vendor,good,1,footer)
        for bad in (vendor,good.replace('VECTOR 0001 0','VECTOR 0001 1'),good.replace('VECTOR 0000 1','VECTOR 0000 x'),good+'warning: ignored\n'):
            with self.assertRaises(AssertionError):new.validate_wrong_corpus(vendor,bad,1,footer)

    def test_same_strict_sat_model_positive_negative_and_diagnostic_gates(self):
        raw=new.state.raw
        raw.validate_result(raw.SUCCESS,0,False)
        raw.validate_result(raw.FAILURE+'\nERROR: Called with -verify and proof did fail!\n',1,True)
        for text,code,negative in ((raw.SUCCESS+'\nWarning: waived',0,False),(raw.SUCCESS,0,True),(raw.FAILURE,1,True),(raw.SUCCESS+'\ntimeout reached',0,False)):
            with self.assertRaises(AssertionError):raw.validate_result(text,code,negative)


if __name__=='__main__':unittest.main()
