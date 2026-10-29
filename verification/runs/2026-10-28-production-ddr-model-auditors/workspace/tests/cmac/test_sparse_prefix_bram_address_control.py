"""All original address controls plus exact unused-output source guards."""
from copy import deepcopy
import inspect
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'tools/openxc7'), str(Path(__file__).resolve().parent)]
from test_prefix_bram_address_control import PrefixBramAddressControl
import prove_sparse_prefix_bram_address as new


class SparseCarryOutputControl(unittest.TestCase):
    def cell(self):
        return dict(type='CARRY4', parameters={}, connections=dict(CI=['0'], CYINIT=['1'], DI=['0']*4, S=[10,11,12,13], CO=[20,21,22,23]),
                    port_directions=dict(CI='input', CYINIT='input', DI='input', S='input', CO='output'))

    def test_only_unused_O_absence_is_added_without_cell_or_old_module_mutation(self):
        cell = self.cell(); before = deepcopy(cell)
        with self.assertRaisesRegex(AssertionError,'Unmodeled primitive pin'): new.old.validate_cell(cell)
        self.assertEqual(new.validate_cell(cell)[1], {'CO':4})
        self.assertEqual(cell,before)
        self.assertEqual(new.old.CONTROL.name,'test_prefix_bram_address_control.py')
        new.verify_primary_source()

    def test_inputs_required_and_present_output_direction_width_or_unknown_still_fail(self):
        for mode in ('input','direction','width','unknown','extra','CO'):
            cell=self.cell()
            if mode=='input': del cell['connections']['DI'];del cell['port_directions']['DI']
            elif mode=='direction':cell['port_directions']['O']='input';cell['connections']['O']=[30,31,32,33]
            elif mode=='width':cell['port_directions']['O']='output';cell['connections']['O']=[]
            elif mode=='unknown':cell['connections']['DI'][0]='x'
            elif mode=='extra':cell['connections']['unused']=['0'];cell['port_directions']['unused']='input'
            else:del cell['connections']['CO'];del cell['port_directions']['CO']
            with self.assertRaises(AssertionError):new.validate_cell(cell)

    def test_changes_are_reversible_and_other_cone_miter_gates_literal(self):
        self.assertEqual(new.CELL_SOURCE.replace(new.NEW_OUTPUT,new.OLD_OUTPUT),inspect.getsource(new.old.validate_cell))
        self.assertEqual(new.TRACE_SOURCE,inspect.getsource(new.old.trace_cone))
        self.assertEqual(new.MITER_SOURCE,inspect.getsource(new.old.miter))
        restored=new.MAIN_SOURCE.replace('prefix-bram-address-sparse-output-proof-','prefix-bram-address-proof-')
        restored=restored.replace(new.NEW_BIND,new.OLD_BIND).replace(new.NEW_SAVE,new.OLD_SAVE)
        self.assertEqual(restored,inspect.getsource(new.old.main))
        self.assertIn("run(kind, ['yosys', '-Q', '-T', '-s', script], bool(negative))",new.MAIN_SOURCE)


if __name__=='__main__':unittest.main()
