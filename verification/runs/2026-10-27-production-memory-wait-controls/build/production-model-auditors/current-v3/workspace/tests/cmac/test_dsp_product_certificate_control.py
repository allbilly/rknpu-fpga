"""Certificate admission controls; not new HDL, whole-lane or FPGA tests."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/cmac'))
sys.path.insert(0,str(ROOT/'tests/cmac'))
import audit_lane_dsp_product as runner
from test_dsp_donor_range_control import graph


class ProductCertificateControls(unittest.TestCase):
    def test_saved_json_range_statement_matches_every_value_without_domain_changes(self):
        statement=runner.range_statement(graph())
        self.assertEqual(statement['tree_shapes'],[[5,24],[5,24],[4,32]])
        self.assertEqual(statement['free_binary_input_bits'],37)
        self.assertEqual(statement['final_unsigned_row_sum_upper_bound'],2863267840)
        changed=deepcopy(statement);changed['tree_shapes'][2][1]=31
        self.assertNotEqual(changed,runner.range_statement(graph()))
        changed=deepcopy(statement);changed['final_unsigned_row_sum_upper_bound']-=1
        self.assertNotEqual(changed,runner.range_statement(graph()))

    def test_all_fifteen_exact_coefficients_and_integer_lifting_bounds(self):
        weights,codes,bits=runner.source_terms(graph())
        certificate=runner.polynomial_certificate(weights,codes,bits)
        self.assertEqual(weights,[1,4,16,64,256,1024,4096,16384])
        self.assertEqual(certificate['coefficient_residuals'],[0]*15)
        self.assertEqual(certificate['operand_bit_product_coefficients'],[1<<i for i in range(15)])
        self.assertEqual(certificate['booth_bias'],0x55550000)
        self.assertEqual(certificate['recoder_integer_output_interval'],[2,131070])
        self.assertEqual(certificate['biased_unsigned_product_interval'],[357957631,2505310209])

    def test_all_three_corrupted_certificates_are_rejected(self):
        weights,codes,bits=runner.source_terms(graph())
        checks=runner.negative_certificates(weights,codes,bits)
        self.assertEqual([c['name'] for c in checks],['wrong_bias','wrong_digit','wrong_weight'])
        self.assertTrue(all(c['status']=='PASS_EXPECTED_CERTIFICATE_REJECTION' for c in checks))

    def test_changed_actual_input_or_inversion_wiring_is_not_a_certificate(self):
        for mutation in ('padding','inversion','code','source','output_alias'):
            changed=graph();cells=changed['modules'][runner.ranges.TOP]['cells']
            if mutation=='padding':cells['high_tree']['connections']['INPUT'][17]=98765
            elif mutation=='inversion':cells['low_tree']['connections']['INPUT'][24]=98765
            elif mutation=='code':cells['booth[0].recode']['connections']['code'][0]='1'
            elif mutation=='source':cells['booth[0].recode']['connections']['src_data'][0]=98765
            else:cells['booth[1].recode']['connections']['out_data'][0]=cells['booth[0].recode']['connections']['out_data'][0]
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):runner.source_terms(changed)

    def test_changed_digit_connections_or_reduced_polynomial_domain_fail(self):
        weights,codes,bits=runner.source_terms(graph())
        for mutation in ('padding','unknown','rewired','coupled'):
            changed=deepcopy(codes);domain=list(bits)
            if mutation=='padding':changed[0][0]='1'
            elif mutation=='unknown':changed[0][1]=123456
            elif mutation=='rewired':changed[1][1]=bits[0]
            else:domain[1]=domain[0]
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):runner.polynomial_certificate(weights,changed,domain)

    def test_exact_completed_recoder_statement_is_bound_not_just_its_name(self):
        original=runner.components.MITERS.read_text();runner.validate_reference(original)
        for changed in (original.replace("32'h00010000","32'h00010001"),
                original.replace('sign ? -digit_product:digit_product','sign ? digit_product:-digit_product'),
                original.replace('actual ^ expected ^ `RK_COMPONENT_FLIP','32\'d0 ^ `RK_COMPONENT_FLIP'),
                original.replace('`define RK_COMPONENT_FLIP 1','`define RK_COMPONENT_FLIP 0')):
            with self.subTest(),self.assertRaises(AssertionError):runner.validate_reference(changed)


if __name__=='__main__':unittest.main()
