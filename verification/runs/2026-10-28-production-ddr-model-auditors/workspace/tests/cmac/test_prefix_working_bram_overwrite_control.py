"""Primitive-boundary overwrite qualifier controls, not a full-board proof."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import test_prefix_working_bram_overwrite as q


class WorkingBramOverwriteControl(unittest.TestCase):
    def fixture(self):
        selected=json.loads(q.SELECTED.read_text())
        wiring=json.loads((q.WIRING.parent/'actual-memory-wire-bindings.json').read_text())
        controls=json.loads((q.CONTROL_PARENT.parent/'actual-BRAM-control-cones.json').read_text())
        names=wiring['wiring_checks']['working_RAM_by_consumed_width'].values()
        return {name:selected[name] for name in names},wiring['logical_signal_physical_wires'],controls['logical_signal_physical_wires']

    def test_parameter_views_only_replace_unknown_INIT_SRVAL_symbols(self):
        brams,_,_=self.fixture()
        for cell in brams.values():
            mapped,delta=q.params_for_view(cell,'mapped');self.assertEqual(mapped,cell['parameters']);self.assertEqual(delta,{})
            for view,replacement in (('zero','0'),('one','1')):
                params,delta=q.params_for_view(cell,view)
                self.assertGreater(len(delta),100)
                for key,value in params.items():
                    expected=cell['parameters'][key]
                    if key in delta:expected=expected.replace('x',replacement)
                    self.assertEqual(value,expected)
                self.assertEqual(params['WRITE_MODE_A'],'READ_FIRST');self.assertEqual(params['WRITE_MODE_B'],'READ_FIRST')
                self.assertEqual(params['DOA_REG'],cell['parameters']['DOA_REG'])
        with self.assertRaises(AssertionError):q.params_for_view(next(iter(brams.values())),'bogus')

    def test_unknown_or_changed_actual_BRAM_modes_remain_rejected(self):
        brams,_,_=self.fixture();cell=next(iter(brams.values()))
        for mode in ('extra','write_mode','width','reg'):
            bad=deepcopy(cell)
            if mode=='extra':bad['parameters']['UNMODELED']='0'
            elif mode=='write_mode':bad['parameters']['WRITE_MODE_A']='WRITE_FIRST'
            elif mode=='width':bad['parameters']['READ_WIDTH_A']='0'*27+'10010'
            else:bad['parameters']['DOA_REG']='0'*31+'1'
            with self.assertRaises(AssertionError):q.params_for_view(bad,'zero')

    def test_actual_input_X_clock_addresses_write_lane_ties_and_consumed_outputs_preserved(self):
        brams,signals,controls=self.fixture()
        for view in ('mapped','zero','one'):
            text,_=q.wrapper(brams,signals,controls,view)
            self.assertEqual(text.count('RAMB36E1 #('),2)
            self.assertEqual(text.count("1'bx"),4)
            self.assertIn('.CLKARDCLK({clk})',text);self.assertIn('.CLKBWRCLK({clk})',text)
            self.assertIn('.REGCEAREGCE({1\'b0})',text);self.assertIn('.RSTRAMARSTRAM({1\'b0})',text)
            self.assertIn('.WEA({host_we,host_we,host_we,host_we})',text)
            self.assertIn(".WEBWE({1'b0,1'b0,1'b0,1'b0,core_we,core_we,core_we,core_we})",text)
            self.assertIn('.DOPADOP(',text);self.assertIn('host_rdata[8]',text)
            self.assertIn('host_rdata[15]',text);self.assertIn('core_rdata[15]',text)

    def test_no_missing_variable_or_changed_constant_is_silently_repaired(self):
        brams,signals,controls=self.fixture()
        for mode in ('missing','bad_constant','direction','alias'):
            bad=deepcopy(brams);name=next(iter(bad));cell=bad[name]
            if mode=='missing':cell['connections']['DIADI'][0]=9999999
            elif mode=='bad_constant':cell['connections']['DIADI'][8]='z'
            elif mode=='direction':cell['port_directions']['DIADI']='inout'
            else:cell['connections']['DOADO'][1]=cell['connections']['DOADO'][0]
            with self.assertRaises(AssertionError):q.wrapper(bad,signals,controls,'zero')

    def test_native_positive_requires_full_marker_exact_source_time_and_no_diagnostic(self):
        with tempfile.TemporaryDirectory(prefix='rknpu-bram-result-control-') as directory:
            bench=Path(directory)/q.BENCH.name;bench.write_text(q.render_bench(q.ROM))
            line=[i+1 for i,line in enumerate(bench.read_text().splitlines()) if line.strip()=='$finish;'][0]
            good=q.MARKER+'\n'+f'{bench}:{line}: $finish called at 655812000 (1ps)\n'
            q.validate_result(good,0,False,bench,0x3bb5)
            for bad,code in ((good,1),(q.MARKER+'\n',0),(good.replace('655812000','655812001'),0),
                             (good.replace('reads=20480','reads=20479'),0),('warning: bad\n'+good,0),(good+'extra\n',0)):
                with self.assertRaises(AssertionError):q.validate_result(bad,code,False,bench,0x3bb5)

    def test_real_negative_must_observe_exact_finite_three_view_result_not_X(self):
        marker='FATAL: bench:1: working BRAM mismatch phase=core_after_host_init index=0 got=3bb5/3bb5/3bb5 expected=3bb4\n'
        q.validate_result(marker,1,True,q.BENCH,0x3bb5)
        for bad,code in ((marker,0),(marker.replace('3bb5/3bb5/3bb5','xxxx/0000/ffff'),1),
                         (marker+q.MARKER,1),(marker+marker,1),(marker.replace('index=0','index=1'),1)):
            with self.assertRaises(AssertionError):q.validate_result(bad,code,True,q.BENCH,0x3bb5)

    def test_actual_six_instance_generated_corpus_compiles_with_unchanged_pinned_UNISIM(self):
        brams,signals,controls=self.fixture()
        with tempfile.TemporaryDirectory(prefix='rknpu-bram-compile-control-') as directory:
            wrapper=Path(directory)/'actual.v'
            wrapper.write_text('\n'.join(q.wrapper(brams,signals,controls,view)[0] for view in ('mapped','zero','one')))
            bench=Path(directory)/q.BENCH.name;bench.write_text(q.render_bench(q.ROM))
            files=[path for path in q.models.selected_models({'RAMB36E1'}) if path.suffix=='.v']
            for path,sha in q.models.selected_models({'RAMB36E1'}).items():self.assertEqual(q.digest(path),sha)
            result=subprocess.run(['iverilog','-g2012','-Ttyp','-s','tb_prefix_working_bram_overwrite','-s','glbl',
                '-o',str(Path(directory)/'control.vvp'),*map(str,files),str(wrapper),str(bench)],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout+result.stderr,'')


if __name__=='__main__':unittest.main()
