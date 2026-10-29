"""Exact state-register/model configuration and native fold result controls."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import qualify_prefix_state_fdce_fold as new


class StateFoldControl(unittest.TestCase):
    def test_exact_four_actual_records_unknown_init_and_pins_preserved(self):
        regs=new.records();text=new.wrapper(regs)
        self.assertEqual([r['original_primitive']['connections']['Q'][0] for r in regs],new.state.STATE_Q)
        self.assertEqual(text.count("FDCE #(.INIT(1'bx))"),4)
        self.assertNotIn('force ',text);self.assertNotIn("INIT(1'b0)",text)

    def test_finite_real_negative_rejects_unknown_wrong_phase_or_extra_fatal(self):
        good='FATAL: /test.sv:35: FDCE next fold mismatch cell=0 vector=0 got=0 expected=1\n Time: 152000 Scope: test\n'
        new.validate(good,1,True,None)
        for text,code in ((good,0),(good.replace('got=0','got=x'),1),(good.replace('next fold','seed'),1),(good+'FATAL: extra\n',1),(good+'warning: ignored\n',1)):
            with self.assertRaises(AssertionError):new.validate(text,code,True,None)

    def test_exact_positive_corpus_and_finish_no_diagnostic_waivers(self):
        with tempfile.TemporaryDirectory() as directory:
            bench=Path(directory)/'test.sv';bench.write_text('$finish;\n')
            good=new.MARKER+f'\n{bench}:1: $finish called at 752000 (1ps)\n'
            new.validate(good,0,False,bench)
            for text,code in ((good,1),(good.replace('752000','751000'),0),(good+'extra\n',0),(good+'warning: ignored\n',0)):
                with self.assertRaises(AssertionError):new.validate(text,code,False,bench)


if __name__=='__main__':unittest.main()
