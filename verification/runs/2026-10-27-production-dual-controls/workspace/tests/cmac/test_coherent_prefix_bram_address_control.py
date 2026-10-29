"""Original controls and coherent producer-boundary rejection controls."""
from copy import deepcopy
import inspect
from pathlib import Path
import sys
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'tools/openxc7'),str(Path(__file__).resolve().parent)]
from test_prefix_bram_address_control import PrefixBramAddressControl
from test_sparse_prefix_bram_address_control import SparseCarryOutputControl
import prove_coherent_prefix_bram_address as new


class CoherentAddressControl(unittest.TestCase):
    def register(self):
        return dict(type='FDCE',parameters=dict(INIT='x'),connections=dict(C=[2],CE=['1'],D=[3],CLR=[4],Q=[5]),
                    port_directions=dict(C='input',CE='input',D='input',CLR='input',Q='output'))

    def test_exact_Q_cut_preserves_unknown_INIT_without_initialization_assumptions(self):
        cell=self.register();before=deepcopy(cell)
        new.validate_register(cell,'Q',0)
        self.assertIn('NOT_INITIALIZATION',new.validate_producer(cell,'Q',0))
        self.assertEqual(cell,before)
        for mode in ('pin','bit','missing','direction','width','parameter'):
            bad=self.register();pin='Q';bit=0
            if mode=='pin':pin='D'
            elif mode=='bit':bit=1
            elif mode=='missing':del bad['connections']['CLR']
            elif mode=='direction':bad['port_directions']['Q']='input'
            elif mode=='width':bad['connections']['Q']=[5,6]
            else:bad['parameters']['unmodeled']='0'
            with self.assertRaises(AssertionError):new.validate_register(bad,pin,bit)

    def test_unknown_missing_or_bidirectional_driver_is_not_turned_into_free_input(self):
        with self.assertRaises(AssertionError):new.validate_producer(dict(type='unknown'),'Q',0)
        with self.assertRaises(AssertionError):new.trace_coherent({},lambda w:None)
        signals={name:list(range(100+index*40,100+index*40+width)) for index,(name,width) in enumerate(new.base.WIDTHS.items())}
        with self.assertRaises(AssertionError):new.trace_coherent(signals,lambda w:(_ for _ in ()).throw(AssertionError('missing')))

    def test_unused_carry_output_omission_does_not_add_any_port_or_admit_missing_input(self):
        cell=SparseCarryOutputControl().cell();cell['connections']['O']=[30,31,32,33];cell['port_directions']['O']='output'
        del cell['connections']['CO'];del cell['port_directions']['CO'];before=deepcopy(cell)
        self.assertEqual(new.validate_cell(cell)[1],{'O':4});self.assertEqual(cell,before)
        del cell['connections']['CI']
        with self.assertRaises(AssertionError):new.validate_cell(cell)

    def test_original_address_reference_and_native_result_gates_are_reversible(self):
        source=new.MITER_SOURCE
        for old,replacement in reversed(new.MITER_REPLACEMENTS):source=source.replace(replacement,old)
        self.assertEqual(source,inspect.getsource(new.base.miter))
        source=new.MAIN_SOURCE
        for old,replacement in reversed(new.MAIN_REPLACEMENTS):source=source.replace(replacement,old)
        self.assertEqual(source,new.previous.MAIN_SOURCE)
        self.assertIn('input_assumptions=[]',new.MAIN_SOURCE)
        self.assertIn("run(kind, ['yosys', '-Q', '-T', '-s', script], bool(negative))",new.MAIN_SOURCE)
        self.assertEqual(new.previous.CONTROL.name,'test_sparse_prefix_bram_address_control.py')


if __name__=='__main__':unittest.main()
