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

    def test_matching_generation_specific_hashes_are_supported(self):
        for value in ('0','3807618499','4294967295'):
            wrapper=self.wrapper.replace("32'd2969735049", "32'd"+value)
            bridge=self.bridge.replace('2969735049U',value+'U')
            with self.subTest(value=value):
                result=contract.validate(wrapper,bridge,self.top)
                self.assertEqual(result['wrapper_library_protection_hash'],int(value))

    def test_missing_duplicate_or_out_of_range_hash_fails(self):
        for wrapper,bridge in [
            (self.wrapper.replace(contract.BLOCK+'_protectlib_check_hash(protectlib_hash__V);',''),self.bridge),
            (self.wrapper.replace("32'd2969735049", "32'd4294967296"),
             self.bridge.replace('2969735049U','4294967296U')),
            (self.wrapper+"\nlocalparam int protectlib_hash__V = 32'd2969735049;\n",self.bridge),
            (self.wrapper.replace("32'd2969735049", "32'd02969735049"),
             self.bridge.replace('2969735049U','02969735049U'))]:
            with self.assertRaises(AssertionError):contract.validate(wrapper,bridge,self.top)

    def test_hash_check_must_be_unconditional_active_initializer_code(self):
        call=contract.BLOCK+'_protectlib_check_hash(protectlib_hash__V);'
        create='handle__V = '+contract.BLOCK+'_protectlib_create($sformatf("%m"));'
        variants=[
            self.wrapper.replace(call,'// '+call),
            self.wrapper.replace(call,'/* '+call+' */'),
            self.wrapper.replace(call,'if (0) '+call),
            self.wrapper.replace(call,'if (1) '+call),
            self.wrapper.replace(call,call+'\n        '+call),
            self.wrapper.replace(call,'$display("'+call+'");'),
            self.wrapper.replace(call,'').replace(create,create+'\n        '+call),
            self.wrapper.replace('initial begin','if (0) initial begin'),
            self.wrapper.replace('initial begin','generate if (0) begin initial begin')
                        .replace('// Combinatorially evaluate changes to inputs',
                                 'end endgenerate\n// Combinatorially evaluate changes to inputs'),
            self.wrapper.replace('initial begin','`ifdef DISABLED_LIBRARY_CHECK\ninitial begin')
                        .replace('// Combinatorially evaluate changes to inputs',
                                 '`endif\n// Combinatorially evaluate changes to inputs'),
            '`ifdef DISABLED_LIBRARY_CHECK\n'+self.wrapper+'\n`endif\n',
        ]
        for index,wrapper in enumerate(variants):
            with self.subTest(variant=index),self.assertRaises(AssertionError):
                contract.validate(wrapper,self.bridge,self.top)

    def test_missing_callback_or_edge_sensitive_weight_fails(self):
        with self.assertRaises(AssertionError):contract.validate(self.wrapper,self.bridge,[])
        with self.assertRaises(AssertionError):
            contract.validate(self.wrapper.replace('always @(weight)','always @(posedge weight)'),self.bridge,self.top)


if __name__=='__main__':unittest.main()
