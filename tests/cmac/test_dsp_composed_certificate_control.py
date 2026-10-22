"""Source/certificate controls; not a fresh positive SAT or mapped/FPGA run."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/cmac'))
import prove_lane_dsp_composed as runner


def inputs():
    contract=json.loads(runner.CONTRACT.read_text())
    texts={m['source']:(ROOT/m['source']).read_text() for m in contract['modules']}
    product=dict(booth_bias=0x55550000,biased_unsigned_product_interval=[357957631,2505310209],
        signed_product_interval=[-1073676289,1073676289])
    return contract,texts,product


class ComposedCertificateControls(unittest.TestCase):
    def test_entire_exact_glue_and_all_thirty_two_control_states(self):
        contract,texts,product=inputs();runner.validate_contract(contract,texts)
        certificate=runner.alignment_certificate(contract,texts,product)
        self.assertEqual((certificate['full_miter_binary_input_bits'],certificate['compared_sum_tag_bits']),(37,40))
        states=certificate['all_control_states'];self.assertEqual(len(states),32)
        self.assertEqual({(s['exp_sft'],s['pair_nz']) for s in states},{(e,n) for e in range(16) for n in range(2)})
        self.assertEqual(sum(s['active'] for s in states),8)
        for state in states:
            if not state['active']:self.assertEqual((state['output_tag'],state['output_compensation']),(0,0))

    def test_changed_source_multiply_width_bias_carry_mask_tag_or_original_row_binding_fail(self):
        contract,texts,product=inputs();path='rtl/cmac/experimental/rk_cmac_fp16_lane_dsp.sv'
        for before,after in [("32'h55550000","32'h55550001"),
                ('wire signed [15:0] signed_a','wire signed [14:0] signed_a'),
                ('> (biased_sum & low_mask)','>= (biased_sum & low_mask)'),
                (".exp_sft(4'd0)",".exp_sft(exp_sft)"),
                (".pair_nz(1'b1)",".pair_nz(pair_nz)"),
                ("8'hf0 >> exp_sft[2:0]","8'hf0 >> exp_sft[3:1]")]:
            self.assertIn(before,texts[path]);changed=dict(texts);changed[path]=texts[path].replace(before,after)
            with self.subTest(before=before),self.assertRaises(AssertionError):runner.alignment_certificate(contract,changed,product)

    def test_no_extra_module_external_assignment_or_preprocessor_gate(self):
        contract,texts,product=inputs();path='rtl/cmac/experimental/rk_cmac_fp16_lane_dsp.sv'
        for suffix in ('\nmodule hidden; endmodule','\nassign hidden=1;', '\n`define HIDDEN 1'):
            changed=dict(texts);changed[path]+=suffix
            with self.subTest(suffix=suffix),self.assertRaises(AssertionError):runner.validate_contract(contract,changed)
        changed=dict(texts);changed[path]='`define HIDDEN 1\n'+changed[path]
        with self.assertRaises(AssertionError):runner.validate_contract(contract,changed)

    def test_compensation_table_and_product_bounds_are_independently_checked(self):
        contract,texts,product=inputs();path='tests/cmac/cmac_lane_dsp_miter.sv'
        changed=dict(texts);changed[path]=changed[path].replace("32'hffaaab00","32'hffaaab01")
        # Even co-mutating the admission fixture cannot alter the separately
        # audited compensation values or integer bounds.
        forged=deepcopy(contract)
        for module in forged['modules']:
            if module['source']==path:module['canonical_module']=runner.canonical_module(changed[path],module['module'],module['exclusive'])
        with self.assertRaises(AssertionError):runner.alignment_certificate(forged,changed,product)
        for field in ('booth_bias','signed_product_interval','biased_unsigned_product_interval'):
            changed=deepcopy(product)
            if field=='booth_bias':changed[field]+=1
            else:changed[field][0]+=1
            with self.subTest(field=field),self.assertRaises(AssertionError):runner.alignment_certificate(contract,texts,changed)

    def test_carry_theorem_and_reference_difference_are_bound_as_whole_modules(self):
        contract,texts,product=inputs()
        for path,before,after in [('tests/cmac/cmac_lane_dsp_component_miters.sv',
                '!sum_overflow && (|difference)','(|difference)'),
                ('tests/cmac/cmac_lane_dsp_miter.sv','reference_lane ^ actual_lane','reference_lane ^ 32\'d0')]:
            changed=dict(texts);self.assertIn(before,changed[path]);changed[path]=changed[path].replace(before,after)
            with self.subTest(path=path),self.assertRaises(AssertionError):runner.validate_contract(contract,changed)


if __name__=='__main__':unittest.main()
