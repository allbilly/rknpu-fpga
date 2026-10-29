"""Original fifteen controls plus a direct derived-namespace function check."""
from pathlib import Path
import sys
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'tools/openxc7'),str(Path(__file__).resolve().parent)]
from test_prefix_bram_address_control import PrefixBramAddressControl
from test_sparse_prefix_bram_address_control import SparseCarryOutputControl
from test_coherent_prefix_bram_address_control import CoherentAddressControl
from test_full_budget_prefix_bram_address_control import FullBudgetAddressControl
import resume_full_budget_prefix_bram_address as new


class ResumedAddressControl(unittest.TestCase):
    def test_actual_derived_namespace_function_handles_complete_small_producer_cone(self):
        register=CoherentAddressControl().register()
        inverter=dict(type='INV',parameters={},connections=dict(I=[5],O=[6]),port_directions=dict(I='input',O='output'))
        signals={name:[5]*width for name,width in new.previous.base.WIDTHS.items()}
        signals['translated']=[6]*12;signals['core_fire']=[6];signals['req_ready']=[6]
        def driver(w):
            return ('registered_Q',register,'Q',0) if w==5 else ('inverter',inverter,'O',0)
        with self.assertRaisesRegex(NameError,"name 'base' is not defined"):
            new.previous.trace_coherent(signals,driver)
        nodes,cuts=new.trace_coherent(signals,driver)
        self.assertEqual(nodes,{'inverter':inverter});self.assertEqual(set(cuts),{5})
        self.assertEqual(cuts[5]['original_primitive'],register)
        self.assertEqual(new.previous.previous.trace_coherent(signals,driver),(nodes,cuts))

    def test_only_namespace_binding_and_new_directory_no_source_or_proof_gate_change(self):
        self.assertIs(new.NAMESPACE['base'],new.previous.base)
        self.assertNotIn('base',new.previous.NAMESPACE)
        self.assertEqual(new.MAIN_SOURCE.replace('prefix-bram-address-full-budget-resume-','prefix-bram-address-full-budget-proof-'),new.previous.MAIN_SOURCE)
        self.assertEqual(new.previous.CONTROL.name,'test_full_budget_prefix_bram_address_control.py')


if __name__=='__main__':unittest.main()
