"""Synthetic reversible-lift controls; never HDL/FPGA evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/cmac'))
sys.path.insert(0,str(ROOT/'tests/cmac'))
from prepare_shared_board import INSTANCE, NODES, PRIVATE, SHARED, prepare, verify
import test_shared_kernel_cones as cone_controls


class SharedBoardPrepareControls(unittest.TestCase):
    def fixture(self):
        original=cone_controls.SharedConeControls().fixture()
        candidate,certificate=prepare({'modules':original},'top','kernel',2)
        return {'modules':original},candidate,certificate

    def reject(self,change):
        original,candidate,certificate=self.fixture()
        change(candidate,certificate)
        with self.assertRaises(AssertionError): verify(original,candidate,certificate)

    def test_literal_restore_and_original_unchanged(self):
        original={'modules':cone_controls.SharedConeControls().fixture()}; before=deepcopy(original)
        candidate,certificate=prepare(original,'top','kernel',2)
        self.assertEqual(original,before)
        verify(original,candidate,certificate)
        self.assertEqual(len(candidate['modules']['top']['cells']),3)
        self.assertEqual(set(candidate['modules'][SHARED]['cells']),{'shared','shared_next','constant'})
        self.assertEqual(set(candidate['modules'][PRIVATE]['cells']),{'private'})

    def test_truth_table_changed_rejected(self):
        self.reject(lambda d,c:d['modules'][SHARED]['cells']['shared']['parameters'].update(INIT='01'))

    def test_private_arithmetic_removed_rejected(self):
        self.reject(lambda d,c:d['modules'][PRIVATE]['cells'].pop('private'))

    def test_constant_or_wrong_shared_input_rejected(self):
        for value in ('0',201):
            self.reject(lambda d,c:d['modules']['top']['cells'][INSTANCE]['connections'].update(data=[value]))

    def test_kernel_output_pin_changed_rejected(self):
        self.reject(lambda d,c:d['modules']['top']['cells']['k1']['connections'].update(result=[999]))

    def test_kernel_count_or_parameter_changed_rejected(self):
        self.reject(lambda d,c:d['modules']['top']['cells'].pop('k1'))
        self.reject(lambda d,c:d['modules']['top']['cells']['k1']['parameters'].update(ATOMIC_C='1'))

    def test_shared_wire_collision_rejected(self):
        def change(d,c):
            wires=d['modules']['top']['cells'][INSTANCE]['connections'][NODES]
            wires[0]=100; c['parent_shared_wires']=wires
        self.reject(change)

    def test_each_kernel_must_use_same_shared_wire_vector(self):
        def change(d,c):
            d['modules']['top']['cells']['k1']['connections'][NODES][0]+=1000
        self.reject(change)

    def test_shared_primitive_or_pin_changed_rejected(self):
        self.reject(lambda d,c:d['modules'][SHARED]['cells']['shared'].update(type='LUT2'))
        self.reject(lambda d,c:d['modules'][SHARED]['cells']['shared']['connections'].update(I0=[3]))

    def test_added_hardware_and_extra_port_rejected(self):
        self.reject(lambda d,c:d['modules'][PRIVATE]['cells'].update(extra=deepcopy(d['modules'][PRIVATE]['cells']['private'])))
        self.reject(lambda d,c:d['modules'][SHARED]['ports'].update(extra={'direction':'input','bits':[3]}))

    def test_certificate_and_library_change_rejected(self):
        self.reject(lambda d,c:c.update(shared_cell_names=[]))
        self.reject(lambda d,c:d['modules']['LUT1']['attributes'].update(blackbox='0'))

    def test_original_shell_cell_changed_rejected(self):
        original={'modules':cone_controls.SharedConeControls().fixture()}
        original['modules']['top']['cells']['shell']=deepcopy(original['modules']['kernel']['cells']['private'])
        candidate,certificate=prepare(original,'top','kernel',2)
        candidate['modules']['top']['cells']['shell']['parameters']['INIT']='01'
        with self.assertRaises(AssertionError): verify(original,candidate,certificate)

    def test_shared_output_short_and_kernel_default_changed_rejected(self):
        def short(d,c):
            wires=d['modules']['top']['cells'][INSTANCE]['connections'][NODES]
            wires[1]=wires[0]; c['parent_shared_wires']=list(wires)
        self.reject(short)
        self.reject(lambda d,c:d['modules'][PRIVATE].update(parameter_default_values={'ATOMIC_C':'1'}))

    def test_original_kernel_port_width_changed_rejected(self):
        self.reject(lambda d,c:d['modules'][PRIVATE]['ports']['weight']['bits'].append(99))

    def test_module_and_instance_alias_collisions_rejected(self):
        original={'modules':cone_controls.SharedConeControls().fixture()}
        original['modules'][SHARED]={}
        with self.assertRaises(AssertionError): prepare(original,'top','kernel',2)
        original={'modules':cone_controls.SharedConeControls().fixture()}
        original['modules']['top']['cells'][INSTANCE]={}
        with self.assertRaises(AssertionError): prepare(original,'top','kernel',2)


if __name__=='__main__':
    unittest.main()
