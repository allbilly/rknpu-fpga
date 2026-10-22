"""Actual generated-source interface guard controls, not mapped numerical tests."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/cmac')]
import dsp_prefix_protected_library_contract as contract


class ProtectedLibraryControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=ROOT/'build/rknpu-dsp-prefix-array-mapped-binary/1791283708506179317/cell'
        cls.wrapper=(folder/(contract.BLOCK+'.sv')).read_text()
        cls.bridge=(folder/(contract.BLOCK+'.cpp')).read_text()
        cls.top=[path.read_text() for path in (ROOT/'build/rknpu-dsp-prefix-array-mapped-continuation/1791296795046895468/top').glob('Vtb_cmac_fp16_dsp_prefix_mapped*.cpp')]

    def test_actual_generated_roles_and_callbacks(self):
        result=contract.validate(self.wrapper,self.bridge,self.top)
        self.assertEqual(result['generated_input_roles']['seq_update'],{'weight':512})
        self.assertFalse(result['full_array_numerical_acceptance'])

    def test_missing_weight_or_changed_width_fails(self):
        for bridge in (self.bridge.replace('VL_SET_W_SVLV(512,  handlep__V->weight, weight + 0);',''),
                self.bridge.replace('VL_SET_W_SVLV(512,  handlep__V->weight,','VL_SET_W_SVLV(256,  handlep__V->weight,')):
            with self.subTest(bridge=bridge[:20]),self.assertRaises(AssertionError):
                contract.validate(self.wrapper,bridge,self.top)

    def test_missing_eval_or_changed_protection_hash_fails(self):
        for bridge in (self.bridge.replace('handlep__V->eval();','',1),
                self.bridge.replace('2969735049U','2969735048U')):
            with self.assertRaises(AssertionError):contract.validate(self.wrapper,bridge,self.top)

    def test_missing_callback_or_edge_sensitive_weight_fails(self):
        with self.assertRaises(AssertionError):contract.validate(self.wrapper,self.bridge,[])
        with self.assertRaises(AssertionError):
            contract.validate(self.wrapper.replace('always @(weight)','always @(posedge weight)'),self.bridge,self.top)


if __name__=='__main__':unittest.main()
