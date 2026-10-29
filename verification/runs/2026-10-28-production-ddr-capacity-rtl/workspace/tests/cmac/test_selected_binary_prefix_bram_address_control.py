"""Twenty-seven old guards plus exact selected-definition/frontend controls."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'tools/openxc7'),str(Path(__file__).resolve().parent)]
from test_prefix_bram_address_control import PrefixBramAddressControl
from test_sparse_prefix_bram_address_control import SparseCarryOutputControl
from test_coherent_prefix_bram_address_control import CoherentAddressControl
from test_full_budget_prefix_bram_address_control import FullBudgetAddressControl
from test_resumed_prefix_bram_address_control import ResumedAddressControl
from test_binary_library_prefix_bram_address_control import BinaryLibraryAddressControl
from test_declared_binary_prefix_bram_address_control import DeclaredBinaryAddressControl
from test_binary_result_prefix_bram_address_control import BinaryResultAddressControl
import resume_selected_binary_prefix_bram_address as new


class SelectedBinaryAddressControl(unittest.TestCase):
    def test_every_selected_definition_is_complete_and_byte_identical_including_attributes(self):
        original=new.raw.LIBRARY.read_bytes()
        selected,records=new.selected_definitions(original,set(new.raw.COUNTS))
        self.assertEqual(len(records),9)
        for record in records.values():
            block=original[record['offset']:record['offset']+record['length']]
            self.assertEqual(selected.count(block),1)
            self.assertTrue(block.endswith(b'\nendmodule\n'))
        self.assertIn(b'(* abc9_box, lib_whitebox *)\nmodule CARRY4',selected)
        self.assertIn(b'(* abc9_lut=5 *)\nmodule LUT6',selected)
        self.assertIn(b'  specify\n',selected)
        self.assertNotIn(b'module IOBUF',selected)
        self.assertNotIn(b"1'bz",selected)

    def test_missing_duplicate_or_unbound_definition_and_changed_inventory_fail(self):
        original=new.raw.LIBRARY.read_bytes();kinds=set(new.raw.COUNTS)
        for bad in (original.replace(b'module INV(',b'module NOT_INV('),
                    original+original[original.index(b'module INV('):original.index(b'(* abc9_lut=1 *)')],
                    original.replace(b'  assign O = !I;',b'  `ifdef UNKNOWN\n  assign O = !I;')):
            with self.assertRaises(AssertionError):new.selected_definitions(bad,kinds)
        with self.assertRaises(AssertionError):new.selected_definitions(original,kinds|{'IOBUF'})

    def test_actual_Yosys_reads_exact_selected_sources_without_any_diagnostic_waiver(self):
        data,_=new.selected_definitions(new.raw.LIBRARY.read_bytes(),set(new.raw.COUNTS))
        with tempfile.TemporaryDirectory(prefix='rknpu-selected-library-control-') as directory:
            source=Path(directory)/'selected.v';source.write_bytes(data)
            result=subprocess.run(['yosys','-Q','-T','-p',f'read_verilog {source}; hierarchy -check -top INV; check -assert'],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertFalse(re.search(r'(?im)warning:|error:|timed out|unknown cell',result.stdout+result.stderr))
        self.assertIs(new.NAMESPACE['base'].validate_result,new.raw.base.validate_result)


if __name__=='__main__':unittest.main()
