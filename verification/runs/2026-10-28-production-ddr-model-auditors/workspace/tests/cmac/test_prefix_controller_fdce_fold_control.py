"""Actual-parameter preserving 47-fold harness/source/strict result controls."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import qualify_prefix_controller_fdce_fold as new


class ControllerFDCEFoldControl(unittest.TestCase):
    def test_47_actual_parameters_and_bits_never_coerced(self):
        old=new.original.records()[0];regs=[]
        for i in range(47):
            record=copy.deepcopy(old);record['cell']='fixture_'+str(i)
            record['original_primitive']['connections']['Q']=[10000+i]
            regs.append(record)
        text=new.wrapper(regs)
        self.assertEqual(text.count('FDCE #'),47)
        self.assertEqual(text.count(".INIT(1'bx)"),47)
        self.assertIn('output [46:0] observed',text)
        self.assertNotIn('force',text)
        with self.assertRaises(AssertionError):new.wrapper(regs[:-1])
        bad=copy.deepcopy(regs);bad[1]['cell']=bad[0]['cell']
        with self.assertRaises(AssertionError):new.wrapper(bad)
        bad=copy.deepcopy(regs);bad[0]['original_primitive']['parameters']['IS_D_INVERTED']='1'
        with self.assertRaises(AssertionError):new.wrapper(bad)

    def test_original_complete_stimulus_negative_and_completion_counts_preserved(self):
        text=new.bench_text()
        self.assertEqual(text.count('cell_index<47;'),3)
        self.assertIn('seeds!=752||async_checks!=752||next_checks!=752',text)
        self.assertIn('for(vector=0;vector<16;',text)
        self.assertIn('wait(glbl.GSR===1\'b0)',text)
        self.assertIn('negative&&vector==0&&cell_index==0',text)
        self.assertEqual(text.count('$finish;'),1)
        self.assertNotIn('force ',text)

    def test_exact_positive_footer_real_finite_negative_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as d:
            bench=Path(d)/'tb.sv';bench.write_text(new.bench_text())
            finish=bench.read_text().splitlines().index('        $finish;')+1
            positive=new.MARKER+'\n'+f'{bench}:{finish}: $finish called at 752000 (1ps)\n'
            negative=f'FATAL: {bench}:37: FDCE next fold mismatch cell=0 vector=0 got=0 expected=1\n       Time: 152000 Scope: tb_prefix_controller_fdce_fold\n'
            new.validate(positive,0,False,bench);new.validate(negative,1,True,bench)
            for text,code,is_negative in ((positive+'warning: waived\n',0,False),(positive.replace('752000','753000'),0,False),
                (positive.replace('752','751'),0,False),(negative.replace('got=0','got=x'),1,True),(negative,0,True),(positive,0,True)):
                with self.assertRaises(AssertionError):new.validate(text,code,is_negative,bench)


if __name__=='__main__':unittest.main()
