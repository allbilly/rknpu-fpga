"""Original per-view goldens, complete stimulus corpus and strict result controls."""
import inspect
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import qualify_isolated_working_bram_overwrite as new


class IsolatedOverwriteControl(unittest.TestCase):
    def test_all_goldens_stimuli_counts_and_single_actual_view_no_fake_aliases(self):
        old=new.original.render_bench(Path('/bound/ROM.hex'))
        for view,golden in (('mapped','xxxx'),('zero','0000'),('one','ffff')):
            text=new.bench(view,Path('/bound/ROM.hex'))
            self.assertEqual(text.count('actual_working_bram_'),1)
            self.assertIn('actual_working_bram_'+view+' selected(',text)
            self.assertIn("if(a!==16'h"+golden+')',text)
            self.assertNotIn('assign ',text);self.assertNotIn('force ',text)
            self.assertIn('if(a!==expected)',text)
            for literal in ('probes!=4096||writes!=12288||reads!=20480||old_reads!=12288||retention!=34',
                'for(i=0;i<4096;i=i+1) host_write_word(i,rom[i][15:0],1);',
                "wanted=rom[i][15:0]^((negative&&i==0)?16'h1:16'h0);",'repeat(17) begin',
                'for(i=0;i<4096;i=i+1) core_write_word(i,changed(i));',
                'for(i=0;i<4096;i=i+1) host_write_word(i,rom[i][15:0],0);'):
                self.assertIn(literal,old);self.assertIn(literal,text)
            normalized=text[text.index('    task automatic host_write_word'):]
            baseline=old[old.index('    task automatic host_write_word'):].replace('h_m,h_z,h_o','host_rdata').replace('c_m,c_z,c_o','core_rdata').replace('configurations=2 variants=3','configurations=2 view='+view)
            self.assertEqual(normalized,baseline)

    def test_real_negative_requires_finite_actual_golden_rejects_cold_fail_unknowns_and_warnings(self):
        good='FATAL: /test.sv:25: working BRAM mismatch phase=core_after_host_init index=0 got=3bb5 expected=3bb4\n Time: 163972000 Scope: test\n'
        for view in ('mapped','zero','one'):
            new.validate_result(good,1,True,None,0x3bb5,view)
            for bad in (good.replace('got=3bb5','got=xxxx'),good.replace('got=3bb5','got=3bb4'),good+'WARNING: ignored\n',good+'FATAL: extra\n',new.marker(view),
                'FATAL: working BRAM cold-state mismatch index=0 got=xX00\n'):
                with self.assertRaises(AssertionError):new.validate_result(bad,1,True,None,0x3bb5,view)

    def test_positive_requires_exact_marker_finish_time_and_no_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'test.sv';source.write_text('$finish;\n')
            for view in ('mapped','zero','one'):
                good=new.marker(view)+f'\n{source}:1: $finish called at 655812000 (1ps)\n'
                new.validate_result(good,0,False,source,0x3bb5,view)
                for bad,code in ((good,1),(good.replace('655812000','655811000'),0),(good+'warning: waived\n',0),(good+'extra\n',0)):
                    with self.assertRaises(AssertionError):new.validate_result(bad,code,False,source,0x3bb5,view)

    def test_admitted_exact_isolation_contexts_observation_not_old_property_acceptance(self):
        before={};new.bind_isolated(before)
        self.assertGreater(len(before),500)
        self.assertIn(str(new.ISOLATED),before)

    def test_reversible_main_keep_warning_time_production_and_absent_board_acceptance_gates(self):
        text=new.MAIN_SOURCE
        for a,b in reversed((('prefix-working-bram-cold-diagnostic-','isolated-working-bram-overwrite-'),
            ('def run(label,argv):','def run(label,argv,negative=None):'),(new.OLD_NATIVE,new.NEW_NATIVE),
            (new.OLD_BIND,new.NEW_BIND),(new.OLD_GENERATED,new.NEW_GENERATED),
            (new.OLD_EXECUTION,new.NEW_EXECUTION),(new.OLD_STATUS,new.NEW_STATUS))):text=text.replace(b,a)
        self.assertEqual(text,inspect.getsource(new.base.main))
        for literal in ('timeout_seconds=180','full_board_startup_independence_proved=False','temporal_port_ownership_proved=False','write_before_read_proved=False','bitstream_emitted=False'):
            self.assertIn(literal,new.MAIN_SOURCE)


if __name__=='__main__':unittest.main()
