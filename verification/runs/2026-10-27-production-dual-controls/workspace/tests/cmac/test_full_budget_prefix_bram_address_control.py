"""Full proof capacity only; all earlier interface/rejection controls retained."""
from copy import deepcopy
import inspect
from pathlib import Path
import sys
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'tools/openxc7'),str(Path(__file__).resolve().parent)]
from test_prefix_bram_address_control import PrefixBramAddressControl
from test_sparse_prefix_bram_address_control import SparseCarryOutputControl
from test_coherent_prefix_bram_address_control import CoherentAddressControl
import prove_full_budget_prefix_bram_address as new


class FullBudgetAddressControl(unittest.TestCase):
    def test_capacity_is_exact_full_physical_census_not_a_reduced_candidate(self):
        self.assertEqual(new.LIMITS,dict(maximum_actual_cells=503128,maximum_known_binary_producer_bits=42239,
            actual_register_Q_bits=17519,actual_DSP_P_bits=24720))
        counts=deepcopy(__import__('json').loads(new.base.INVENTORY.read_text())['actual_primitive_counts'])
        for name in ('DSP48E1','RAMB36E1','FDCE','LUT2'):
            changed=dict(counts);changed[name]-=1
            with self.assertRaises(AssertionError):new.census_limits(changed)

    def test_only_software_capacity_and_new_directory_change_all_native_gates_remain(self):
        self.assertEqual(new.TRACE_SOURCE.replace(new.NEW_LIMIT,new.OLD_LIMIT),inspect.getsource(new.previous.trace_coherent))
        self.assertEqual(new.MAIN_SOURCE.replace('prefix-bram-address-full-budget-proof-','prefix-bram-address-coherent-proof-'),new.previous.MAIN_SOURCE)
        self.assertIn('-timeout 120',new.MAIN_SOURCE)
        self.assertIn('temporal_port_ownership_proved=False',new.MAIN_SOURCE)
        self.assertIn('input_assumptions=[]',new.MAIN_SOURCE)
        self.assertEqual(new.previous.CONTROL.name,'test_coherent_prefix_bram_address_control.py')


if __name__=='__main__':unittest.main()
