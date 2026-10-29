"""All seventeen old guards plus unchanged-library continuation controls."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'tools/openxc7'),str(Path(__file__).resolve().parent)]
from test_prefix_bram_address_control import PrefixBramAddressControl
from test_sparse_prefix_bram_address_control import SparseCarryOutputControl
from test_coherent_prefix_bram_address_control import CoherentAddressControl
from test_full_budget_prefix_bram_address_control import FullBudgetAddressControl
from test_resumed_prefix_bram_address_control import ResumedAddressControl
import resume_binary_library_prefix_bram_address as new


class BinaryLibraryAddressControl(unittest.TestCase):
    def test_saved_cone_retrace_preserves_register_and_rejects_missing_driver(self):
        register=CoherentAddressControl().register()
        cell=dict(type='INV',parameters={},connections=dict(I=[5],O=[6]),port_directions=dict(I='input',O='output'))
        signals={name:[5]*width for name,width in new.base.WIDTHS.items()}
        signals['translated']=[6]*12;signals['core_fire']=[6];signals['req_ready']=[6]
        def driver(w): return ('registered_Q',register,'Q',0) if w==5 else ('inverter',cell,'O',0)
        nodes,cuts=new.previous.trace_coherent(signals,driver)
        self.assertEqual(new.replay_cone(signals,nodes,cuts),new.previous.NAMESPACE['miter'](signals,nodes,cuts))
        with self.assertRaisesRegex(AssertionError,'Incomplete'): new.replay_cone(signals,nodes,{})
        bad=deepcopy(cuts);bad[5]['original_primitive']['type']='FDPE'
        with self.assertRaisesRegex(AssertionError,'producer type'):new.replay_cone(signals,nodes,bad)

    def test_binary_bench_has_complete_carry_inputs_and_real_first_vector_negative(self):
        cell=dict(type='CARRY4',parameters={},connections=dict(CI=['0'],CYINIT=[2],DI=[3,4,5,6],S=[7,8,9,10],CO=[11,12,13,14]),
                  port_directions=dict(CI='input',CYINIT='input',DI='input',S='input',CO='output'))
        text,width=new.qualify_bench({'actual':cell})
        self.assertEqual(width,8)
        for literal in ('.CI(stimulus[0])','.CYINIT(stimulus[1])','.DI(stimulus[5:2])','.S(stimulus[9:6])',
                        '.CO(out_0[3:0])','.O(out_0[7:4])','vector<1024','negative && vector==0','glbl.GSR'):
            self.assertIn(literal,text)
        self.assertNotIn('assign CO',text)

    def test_binary_bench_preserves_actual_LUT_parameter(self):
        text,width=new.qualify_bench({'actual':PrefixBramAddressControl().cell()})
        self.assertEqual(width,1)
        self.assertIn("LUT2 #(.INIT(4'b1000))",text)
        self.assertIn('.I0(stimulus[0])',text);self.assertIn('.I1(stimulus[1])',text)

    def corpus(self): return ''.join(f'VECTOR {i:04d} 00\n' for i in range(1024))

    def test_complete_two_library_corpus_and_exact_mismatch(self):
        good=self.corpus()
        self.assertTrue(new.compare_vectors(good,good,8)['all_retained_primitive_input_combinations_exhausted'])
        with self.assertRaisesRegex(AssertionError,'Binary model mismatch vector=0'):
            new.compare_vectors(good,good.replace('VECTOR 0000 00','VECTOR 0000 01'),8)

    def test_unknown_truncated_reordered_warning_and_padding_are_not_binary_evidence(self):
        good=self.corpus()
        for bad,width in ((good.replace('0000 00','0000 0x'),8),(good.split('\n',1)[1],8),
                          (good.replace('0001 00','0000 00'),8),('warning: bad\n'+good,8),
                          (good.replace('0000 00','0000 ff'),7),(good.replace('0000 00','0000 0'),8)):
            with self.assertRaises(AssertionError):new.vectors(bad,width)

    def test_native_SAT_result_validator_and_old_failures_are_not_changed(self):
        self.assertIs(new.base.validate_result,new.previous.previous.base.validate_result)
        self.assertIn('resume_full_budget_prefix_bram_address',new.previous.__name__)
        self.assertEqual(new.previous.CONTROL.name,'test_resumed_prefix_bram_address_control.py')
        self.assertEqual(new.COUNTS['CARRY4'],28);self.assertEqual(sum(new.COUNTS.values()),557)


if __name__=='__main__':unittest.main()
