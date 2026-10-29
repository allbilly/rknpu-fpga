"""Saved-native admission/comparison controls, not a new native/physical run."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import qualify_native_heap_clock_features as new


class Controls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=json.loads(new.FAILED.read_text());cls.compared=new.compare_saved_features()

    def test_actual_original_failure_has_completed_native_commands_not_qualification(self):
        new.check_saved_metadata(self.original)
        with self.assertRaises(AssertionError):new.native.verify_metadata(self.original)
        self.assertEqual(self.original['status'],'FAIL')

    def test_wrong_failure_target_missing_command_or_bad_native_return_refused(self):
        for key,value in (('status','RUNNING'),('status','PASS'),('error','other'),('full_parallel_products',32),
                          ('native_source_or_executable_changed',True),('lut_output_comparisons',0)):
            r=deepcopy(self.original);r[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):new.check_saved_metadata(r)
        for action in ('remove','returncode','commandfail'):
            r=deepcopy(self.original)
            if action=='remove':r['commands'].pop()
            elif action=='returncode':r['commands'][-1]['returncode']=125
            else:r['commands'][-1]['status']='FAIL'
            with self.assertRaises(AssertionError):new.check_saved_metadata(r)

    def test_all_original_dsp_bram_feature_contracts_and_clock_ownership(self):
        r=self.compared
        self.assertEqual(len(r['DSP_feature_comparison']),4);self.assertEqual(len(r['BRAM_feature_comparison']),6)
        self.assertEqual(r['native_control_cell_counts']['DSP48E1_DSP48E1'],4)
        self.assertEqual(r['native_control_cell_counts']['RAMB36E1_RAMB36E1'],6)
        self.assertEqual(sum(r['native_control_cell_counts'].values()),286)
        self.assertEqual(r['native_FASM_features'],7869)
        self.assertEqual(r['native_FASM_repeated_clock_enable_lines'],{'HCLK_R_X22Y234.ENABLE_BUFFER.HCLK_CK_BUFHCLK0':[9060,9061]})

    def test_metadata_cannot_claim_new_native_or_full_board_physical_acceptance(self):
        r=dict(self.compared,status=new.QUALIFIED,stage='complete',finished_utc='synthetic control only',
               part='xc7k480tffg1156-2',full_parallel_products=512,placer='heap',native_evidence_parent=str(new.FAILED),
               original_failure_relabelled=False,reused_completed_native_commands_without_execution=True,
               new_native_PNR_executed=False,native_source_or_executable_changed=False,native_positive_placements=3,
               lut_output_comparisons=1024,illegal_pair_rejected_before_postPlace=True,production_source_before='same',production_source_after='same',
               commands=[dict(label=n,status='PASS_TOOL_EXECUTION_ONLY',returncode=0,expected_returncode=0) for n in new.COMMANDS],
               **{k:False for k in new.FLAGS})
        new.verify_metadata(r)
        for key,value in (('status','RUNNING'),('new_native_PNR_executed',True),('original_failure_relabelled',True),
                          ('full_parallel_products',32),('production_source_after','changed'))+tuple((k,True) for k in new.FLAGS):
            bad=deepcopy(r);bad[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):new.verify_metadata(bad)


if __name__=='__main__':unittest.main()
