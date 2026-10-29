"""Compiled getter/early native legality controls, not full placement."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import resume_native_heap_early_constraints as new
from test_native_heap_placement_control import BASE,POSITIVE


class Controls(unittest.TestCase):
    def test_actual_first_failure_is_still_refused_by_old_procedure(self):
        import json
        r=json.loads(new.FAILED.read_text());self.assertEqual(r['status'],'FAIL')
        text=Path(r['commands'][-1]['log']).read_text()
        new.check_heap_log(125,text,True)
        with self.assertRaises(AssertionError):new.first.check_heap_log(125,text,True)

    def test_exact_early_guard_diagnostic_wrong_cell_or_continuation_refused(self):
        text=new.EARLY+'\n0 warnings, 1 error\n';new.check_heap_log(125,text,True)
        for bad in (text.replace('captured_pair_lut1','other_cell'),text.replace('A6LUT','A5LUT'),text+'Info: Program finished normally.\n',
                    'ERROR: unknown device\n0 warnings, 1 error\n',text+'Assertion failure\n'):
            with self.assertRaises(AssertionError):new.check_heap_log(125,bad,True)

    def test_compiled_beta_store_must_match_complete_symbol_and_abi(self):
        name='nextpnr_himbaechel::XilinxImpl::configurePlacerHeap(nextpnr_himbaechel::PlacerHeapCfg&)'
        address,size=new.getter_symbol('00000000005437d0 0000000000000100 T '+name+'\n')
        text='native: file format elf64-x86-64\n00000000005437d0 <'+name+'>:\n543843: c7 46 04 00 00 00 3f movl $0x3f000000,0x4(%rsi)\n'
        head='float alpha, beta;'
        self.assertEqual(new.validate_getter(text,address,size,head)['observed_literal_beta_store_value'],0.5)
        for bad in (text.replace('0x3f000000','0x3f666666'),text.replace('0x4(%rsi)','0x8(%rsi)'),text+text,text.replace('elf64-x86-64','elf32-i386')):
            with self.assertRaises(AssertionError):new.validate_getter(bad,address,size,head)
        with self.assertRaises(AssertionError):new.getter_symbol('missing symbol')

    def test_unchanged_normal_positive_and_algorithm_only_arguments(self):
        new.check_heap_log(0,POSITIVE)
        new.check_heap_log(0,POSITIVE.replace('Info: Xilinx HeAP effective beta: 0.500000 (architecture default)\n',''))
        self.assertEqual(new.first.heap_argv(BASE)[BASE.index('--placer')+1],'heap')
        self.assertIn('timeout=3600',new.MAIN_SOURCE)
        self.assertIn('expected=125',new.MAIN_SOURCE)
        self.assertIn('validate_placed',new.MAIN_SOURCE)
        self.assertIn('compare_features',new.MAIN_SOURCE)


if __name__=='__main__':unittest.main()
