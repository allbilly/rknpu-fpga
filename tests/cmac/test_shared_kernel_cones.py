"""Synthetic dependency-closure controls, not mapping/numerical evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools/cmac'))
from analyze_shared_kernel_cones import shared_cones


class SharedConeControls(unittest.TestCase):
    def fixture(self):
        def lut(source, dest):
            return dict(type='LUT1', parameters={'INIT':'10'},
                        port_directions={'I0':'input','O':'output'}, connections={'I0':[source],'O':[dest]})
        def instance(data, weight):
            return dict(type='kernel', parameters={}, port_directions={'data':'input','weight':'input','result':'output'},
                        connections={'data':[data], 'weight':[weight], 'result':[weight+100]})
        return {'top': {'cells': {'k0':instance(100,200),'k1':instance(100,201)}},
                'kernel': {'ports': {'data':{'direction':'input','bits':[2]},
                                    'weight':{'direction':'input','bits':[3]},
                                    'result':{'direction':'output','bits':[6]}},
                           'cells': {'shared':lut(2,4),'shared_next':lut(4,5),
                                     'private':lut(3,6),'constant':lut('0',7)}},
                'LUT1': {'attributes':{'blackbox':'1'}, 'ports':{
                    'I0':{'direction':'input','bits':[1]},'O':{'direction':'output','bits':[2]}}}}

    def run_fixture(self, modules):
        return shared_cones(modules,'top','kernel',2)

    def test_exact_shared_transitive_and_constant_cones_only(self):
        modules=self.fixture(); before=deepcopy(modules)
        report=self.run_fixture(modules)
        self.assertEqual(modules,before)
        self.assertEqual(report['eligible_cell_names'],['constant','shared','shared_next'])
        self.assertEqual(report['potentially_removable_cells'],{'LUT1':3})
        self.assertEqual(report['shared_input_positions'],{'data':[0],'weight':[]})

    def test_changed_parent_wire_is_not_shared(self):
        modules=self.fixture(); modules['top']['cells']['k1']['connections']['data']=[101]
        self.assertEqual(self.run_fixture(modules)['eligible_cell_names'],['constant'])

    def test_unknown_input_rejected(self):
        modules=self.fixture(); modules['top']['cells']['k0']['connections']['data']=['x']
        with self.assertRaises(AssertionError): self.run_fixture(modules)

    def test_state_is_not_shared_even_with_shared_clock(self):
        modules=self.fixture()
        modules['FDRE']={'attributes':{'blackbox':'1'},'ports':{
            'D':{'direction':'input','bits':[1]},'Q':{'direction':'output','bits':[2]}}}
        modules['kernel']['cells']['state']={'type':'FDRE','parameters':{'INIT':'0'},
            'port_directions':{'D':'input','Q':'output'},'connections':{'D':[2],'Q':[8]}}
        modules['kernel']['cells']['shared_next']['connections']['I0']=[8]
        self.assertEqual(self.run_fixture(modules)['eligible_cell_names'],['constant','shared'])

    def test_cycle_rejected(self):
        modules=self.fixture(); modules['kernel']['cells']['shared']['connections']['I0']=[5]
        with self.assertRaises(AssertionError): self.run_fixture(modules)

    def test_undriven_pin_rejected(self):
        modules=self.fixture(); modules['kernel']['cells']['private']['connections']['I0']=[99]
        with self.assertRaises(AssertionError): self.run_fixture(modules)

    def test_unknown_hardware_rejected(self):
        modules=self.fixture(); modules['kernel']['cells']['private']['type']='invented_arithmetic'
        with self.assertRaises(AssertionError): self.run_fixture(modules)

    def test_wrong_multiplicity_and_parameter_override_rejected(self):
        modules=self.fixture(); del modules['top']['cells']['k1']
        with self.assertRaises(AssertionError): self.run_fixture(modules)
        modules=self.fixture(); modules['top']['cells']['k1']['parameters']={'ATOMIC_C':'1'}
        with self.assertRaises(AssertionError): self.run_fixture(modules)

    def test_multiple_driver_rejected(self):
        modules=self.fixture(); modules['kernel']['cells']['private']['connections']['O']=[4]
        with self.assertRaises(AssertionError): self.run_fixture(modules)

    def test_pin_width_and_model_logic_rejected(self):
        modules=self.fixture(); modules['kernel']['cells']['private']['connections']['I0']=[3,2]
        with self.assertRaises(AssertionError): self.run_fixture(modules)
        modules=self.fixture(); modules['LUT1']['cells']={'logic':{'type':'$and'}}
        with self.assertRaises(AssertionError): self.run_fixture(modules)

    def test_missing_primitive_pin_rejected(self):
        modules=self.fixture(); cell=modules['kernel']['cells']['private']
        del cell['connections']['I0']; del cell['port_directions']['I0']
        with self.assertRaises(AssertionError): self.run_fixture(modules)

    def test_conflicting_primary_port_alias_rejected(self):
        modules=self.fixture(); modules['kernel']['ports']['weight']['bits']=[2]
        with self.assertRaises(AssertionError): self.run_fixture(modules)


if __name__=='__main__':
    unittest.main()
