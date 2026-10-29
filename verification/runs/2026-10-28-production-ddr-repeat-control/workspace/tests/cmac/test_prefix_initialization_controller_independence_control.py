"""Full actual controller cache, complete corpora and strict SAT-gate controls."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import prove_prefix_initialization_controller_independence as new


class ControllerIndependenceControl(unittest.TestCase):
    def test_actual_complete_parent_cone_and_47_fold_revalidation(self):
        bindings={};cone,text,library=new.admit(bindings)
        self.assertGreaterEqual(len(bindings),685)
        self.assertEqual(len(cone['cells']),1245);self.assertEqual(len(cone['producer_cuts']),954)
        self.assertEqual(len(cone['controller_registers']),47)
        self.assertIn('wire [55:0] compared_0=',text)
        self.assertIn('wire [55:0] compared_1=',text)
        self.assertIn("wire init_phase=(state <= 4'd2)",text)
        self.assertIn(b'module LUT1',library)
        self.assertNotIn('assume',text)

    def test_missing_cut_extra_unreachable_cell_and_altered_record_rejected(self):
        cone=json.loads((new.PREPARED.parent/'actual-initialization-controller-cone.json').read_text())
        selected=json.loads((new.ROOT/'build/openxc7/prefix-config-contract-1791401020849392343/actual-selected-primitives.json').read_text())
        bad=copy.deepcopy(cone);del bad['producer_cuts'][next(iter(bad['producer_cuts']))]
        with self.assertRaises(AssertionError):new.replay_cone(bad,selected)
        bad=copy.deepcopy(cone);c=copy.deepcopy(next(c for c in bad['cells'].values() if c['type']=='LUT2'))
        c['connections']['O']=[999999999];bad['cells']['unreachable']=c
        with self.assertRaises(AssertionError):new.replay_cone(bad,selected)
        bad=copy.deepcopy(cone);bad['controller_registers'][4]['offset']=99
        with self.assertRaises(AssertionError):new.replay_cone(bad,selected)

    def test_every_known_corpus_vector_and_executed_one_bit_negative_required(self):
        footer='fixture:1: $finish called at 1125000 (1ps)'
        vendor=''.join(f'VECTOR {i:04d} 0\n' for i in range(1024))+footer+'\n'
        wrong=vendor.replace('VECTOR 0000 0','VECTOR 0000 1')
        self.assertEqual(new.compare_corpora(vendor,vendor,1,footer)['per_instance_comparisons'],1274880)
        new.validate_wrong_corpus(vendor,wrong,1,footer)
        for bad in (vendor,wrong.replace('VECTOR 0001 0','VECTOR 0001 1'),wrong.replace('VECTOR 0000 1','VECTOR 0000 x'),wrong+'warning: waived\n'):
            with self.assertRaises(AssertionError):new.validate_wrong_corpus(vendor,bad,1,footer)

    def test_original_warning_free_positive_real_negative_and_timeout_gates(self):
        raw=new.controller.prior.state.raw
        raw.validate_result(raw.SUCCESS,0,False)
        raw.validate_result(raw.FAILURE+'\nERROR: Called with -verify and proof did fail!\n',1,True)
        for text,code,negative in ((raw.SUCCESS+'\nWarning: waived',0,False),(raw.SUCCESS,0,True),
            (raw.FAILURE,1,True),(raw.SUCCESS+'\ntimeout reached',0,False)):
            with self.assertRaises(AssertionError):raw.validate_result(text,code,negative)


if __name__=='__main__':unittest.main()
