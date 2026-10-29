"""Timing metadata is not hardware, but unexpected hardware still fails."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/cmac'))
from xc7_primitive_counts import primitive_counts

class PrimitiveCounts(unittest.TestCase):
    def design(self):
        return {'top': {'cells': {'a': {'type': 'INV'}, 'k': {'type': 'kernel'}}},
                'INV': {'attributes': {'blackbox': '1'}, 'cells': {'delay': {'type': '$specify2'}}},
                'kernel': {'attributes': {'hdlname': 'rk_cmac_fp16_cell'}, 'cells': {'b': {'type': 'INV'}}}}
    def test_primitive_timing_is_not_hardware(self):
        self.assertEqual(primitive_counts(self.design(), 'top'), {'INV': 2})
    def test_nonblackbox_primitive_rejected(self):
        d=self.design();d['INV']['attributes']['blackbox']='0'
        with self.assertRaises(AssertionError): primitive_counts(d,'top')
    def test_hardware_inside_primitive_rejected(self):
        d=self.design();d['INV']['cells']['extra']={'type':'$add'}
        with self.assertRaises(AssertionError): primitive_counts(d,'top')
    def test_timing_cell_in_hardware_rejected(self):
        d=self.design();d['top']['cells']['extra']={'type':'$specify2'}
        with self.assertRaises(AssertionError): primitive_counts(d,'top')
    def test_unknown_hardware_rejected(self):
        d=self.design();d['top']['cells']['extra']={'type':'UNKNOWN'}
        with self.assertRaises(AssertionError): primitive_counts(d,'top')
    def test_unreviewed_module_rejected(self):
        d=self.design();d['kernel']['attributes']['hdlname']='another_design'
        with self.assertRaises(AssertionError): primitive_counts(d,'top')

if __name__ == '__main__': unittest.main()
