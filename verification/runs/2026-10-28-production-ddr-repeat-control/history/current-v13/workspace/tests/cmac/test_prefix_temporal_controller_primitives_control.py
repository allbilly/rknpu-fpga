"""Exact actual-source primitive, clear-root, corpus and diagnostic controls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import qualify_prefix_temporal_controller_primitives as new


def actual_cone():
    return json.loads((new.PREPARED.parent/'actual-initialization-controller-cone.json').read_text())


class TemporalPrimitiveControl(unittest.TestCase):
    def test_all_50_actual_register_parameters_and_bits_preserved(self):
        regs=actual_cone()['controller_registers'];text=new.wrapper(regs)
        self.assertEqual(text.count('FDCE #'),50);self.assertEqual(text.count(".INIT(1'bx)"),50)
        self.assertIn('output [49:0] observed',text)
        with self.assertRaises(AssertionError):new.wrapper(regs[:-1])
        bad=copy.deepcopy(regs);bad[1]['cell']=bad[0]['cell']
        with self.assertRaises(AssertionError):new.wrapper(bad)
        bad=copy.deepcopy(regs);bad[0]['original_primitive']['parameters']['IS_D_INVERTED']='1'
        with self.assertRaises(AssertionError):new.wrapper(bad)

    def test_original_stimulus_gsr_golden_and_exact_completion_counts(self):
        text=new.bench_text()
        self.assertEqual(text.count('cell_index<50;'),3)
        self.assertIn('seeds!=800||async_checks!=800||next_checks!=800',text)
        self.assertIn('for(vector=0;vector<16;',text);self.assertIn("wait(glbl.GSR===1'b0)",text)
        self.assertIn('negative&&vector==0&&cell_index==0',text)
        self.assertEqual(text.count('$finish;'),1);self.assertNotIn('force ',text)

    def test_exact_fold_positive_negative_and_all_diagnostics_retained(self):
        with tempfile.TemporaryDirectory() as d:
            bench=Path(d)/'tb.sv';bench.write_text(new.bench_text())
            line=bench.read_text().splitlines().index('        $finish;')+1
            pos=new.MARKER+'\n'+f'{bench}:{line}: $finish called at 752000 (1ps)\n'
            neg=f'FATAL: {bench}:37: FDCE next fold mismatch cell=0 vector=0 got=0 expected=1\n       Time: 152000 Scope: tb_prefix_temporal_fdce_fold\n'
            new.validate_fold(pos,0,False,bench);new.validate_fold(neg,1,True,bench)
            for text,code,negative in ((pos+'warning: waived\n',0,False),(pos.replace('752000','753000'),0,False),
                (pos.replace('800','799'),0,False),(neg.replace('got=0','got=x'),1,True),(neg,0,True),(pos,0,True)):
                with self.assertRaises(AssertionError):new.validate_fold(text,code,negative,bench)

    def test_actual_all_clear_roots_fixed_point_and_wrong_function_rejected(self):
        cone=actual_cone();cert=new.clear_certificate(cone)
        self.assertEqual(cert['binary_root_comparisons'],1600);self.assertEqual(len(cert['binary_rows']),32)
        self.assertTrue(cert['one_post_edge_clear_application_is_fixed_point'])
        for row in cert['binary_rows']:
            self.assertEqual(row['clear_bits_lsb_first'][:44],[int(not row['reset_n'])]*44)
            self.assertEqual(row['clear_bits_lsb_first'][44:],[int(not row['reset_n'] or row['demo_state']==10)]*6)
        root=cone['controller_registers'][0]['original_primitive']['connections']['CLR'][0]
        bad=copy.deepcopy(cone)
        driver=[c for c in bad['cells'].values() if c['connections'].get('O')==[root]]
        self.assertEqual(len(driver),1);self.assertEqual(driver[0]['type'],'INV')
        driver[0]['connections']['I']=['1']
        with self.assertRaisesRegex(AssertionError,'Unexpected actual async clear producer'):new.clear_certificate(bad)
        bad=copy.deepcopy(cone);driver=[c for c in bad['cells'].values() if c['connections'].get('O')==[root]][0]
        driver['connections']['I']=[root]
        with self.assertRaisesRegex(AssertionError,'Unknown/cyclic'):new.clear_certificate(bad)

    def test_complete_binary_corpus_and_executed_one_bit_mutation_contract(self):
        footer='strict-footer'
        vendor=''.join('VECTOR %04d %x\n'%(i,i&1) for i in range(1024))+footer+'\n'
        new.compare_corpora(vendor,vendor,1,footer)
        wrong=vendor.replace('VECTOR 0000 0','VECTOR 0000 1',1)
        new.validate_wrong_corpus(vendor,wrong,1,footer)
        for bad in (vendor.replace('VECTOR 0001 1','VECTOR 0001 x'),vendor.replace('VECTOR 0001 1','VECTOR 0001 3'),vendor+'warning: waived\n'):
            with self.assertRaises(AssertionError):new.compare_corpora(vendor,bad,1,footer)

    def test_actual_parent_retraced_miter_clock_model_and_library_identical(self):
        bindings={};cone,library=new.admit(bindings)
        parent=json.loads(new.PREPARED.read_text())
        expected={*(str(Path(p).resolve(strict=True)) for p in parent['source']),str(new.PREPARED),
            *(str((new.ROOT/p).resolve(strict=True)) for p in parent['artifacts'])}
        self.assertEqual(set(bindings),expected);self.assertEqual(len(cone['cells']),1325)
        self.assertEqual(len(cone['producer_cuts']),1019)
        self.assertEqual(sum(cone['full_primitive_counts'].values()),503128)
        self.assertEqual(cone['full_primitive_counts']['DSP48E1'],515)
        self.assertEqual(cone['full_primitive_counts']['RAMB36E1'],6)
        self.assertIn(b'module LUT1',library)


if __name__=='__main__':unittest.main()
