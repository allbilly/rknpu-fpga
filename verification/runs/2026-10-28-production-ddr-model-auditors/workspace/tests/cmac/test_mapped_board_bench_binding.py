"""Wire-only binding controls, not full mapped-board numerical acceptance."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/cmac'))
import bind_mapped_board_bench as runner


def fixture():
    bits=2; nets={}; live=[]
    for name,width in sorted(runner.WIDTHS.items()):
        group=list(range(bits,bits+width)); bits+=width; live.extend(group)
        nets[name]=dict(bits=group)
    return dict(ports={'a':dict(direction='input',bits=live)},cells={},netnames=nets)


class MappedBoardBenchBindingTests(unittest.TestCase):
    def source(self): return runner.BENCH.read_text()

    def test_exact_wire_only_binding_preserves_every_other_source_byte(self):
        module=fixture(); before=deepcopy(module); source=self.source()
        result,edits=runner.bind(module,source)
        self.assertEqual(module,before)
        restored=[]; end=0; offset=0
        for edit in edits:
            start=edit['start']+offset
            restored.extend((result[end:start],edit['original']))
            end=start+len(edit['replacement']); offset+=len(edit['replacement'])-len(edit['original'])
        restored.append(result[end:]); self.assertEqual(''.join(restored),source)
        self.assertEqual(source.count('$fatal('),result.count('$fatal('))
        self.assertEqual(source.count('!=='),result.count('!=='))

    def test_missing_exact_name_not_guessed_from_other_alias(self):
        module=fixture(); module['netnames']['other.core_busy']=module['netnames'].pop('demo.core_busy')
        bindings,issues=runner.analyze(module,self.source())
        self.assertNotIn('demo.core_busy',bindings)
        self.assertEqual(issues,[dict(signal='demo.core_busy',reason='Missing exact original signal name')])
        with self.assertRaises(AssertionError): runner.bind(module,self.source())

    def test_real_recoded_state_width_is_not_silently_reinterpreted(self):
        module=fixture(); module['netnames']['demo.state']['bits']=list(range(900,911))
        module['ports']['a']['bits'].extend(range(900,911))
        _,issues=runner.analyze(module,self.source())
        self.assertEqual(issues,[dict(signal='demo.state',reason='Width changed; recoding is not a wire alias',expected=4,actual=11)])
        with self.assertRaises(AssertionError): runner.bind(module,self.source())

    def test_dead_debug_wires_and_bit_order_or_signedness_rejected(self):
        for label in ('dead','offset','upto','signed','encoding'):
            module=fixture(); net=module['netnames']['demo.index']
            if label=='dead': net['bits'][0]=999999
            elif label=='encoding': net['bits'][0]=None
            else: net[label]=1
            with self.assertRaises(AssertionError): runner.bind(module,self.source())

    def test_constant_or_repeated_fault_targets_rejected_not_overridden(self):
        for name in runner.FORCED:
            module=fixture(); module['netnames'][name]['bits'][0]='0'
            with self.assertRaises(AssertionError): runner.bind(module,self.source())
        module=fixture(); bits=module['netnames']['demo.host_rdata']['bits']; bits[1]=bits[0]
        with self.assertRaises(AssertionError): runner.bind(module,self.source())

    def test_new_observation_or_changed_force_contract_rejected(self):
        with self.assertRaises(AssertionError): runner.bind(fixture(),self.source()+'\ninitial $display(dut.unknown);\n')
        source=self.source().replace("force dut.demo.mem_rsp_error=1'b1;","dut.demo.mem_rsp_error=1'b1;")
        with self.assertRaises(AssertionError): runner.bind(fixture(),source)

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Real Icarus unavailable; no force/release pass claimed')
    def test_real_icarus_scalar_and_vector_wire_force_release_semantics(self):
        source="""`timescale 1ns/1ps
module hardware; reg source=0; wire n_2=source, n_3=source, n_4=source; endmodule
module bench; hardware dut(); initial begin
 #1; if(dut.demo.mem_rsp_error!==0 || dut.demo.host_rdata!==0) $fatal(1,"initial");
 force dut.demo.mem_rsp_error=1; force dut.demo.host_rdata=2'b10;
 #1; if(dut.demo.mem_rsp_error!==1 || dut.demo.host_rdata!==2'b10) $fatal(1,"forced");
 release dut.demo.mem_rsp_error; release dut.demo.host_rdata;
 #1; if(dut.demo.mem_rsp_error!==0 || dut.demo.host_rdata!==0) $fatal(1,"release");
 $display("PASS exact scalar and concatenated mapped wire force/release"); $finish;
end endmodule
"""
        source=source.replace('dut.demo.mem_rsp_error','dut.n_2').replace('dut.demo.host_rdata','{dut.n_4,dut.n_3}')
        with tempfile.TemporaryDirectory(prefix='rk_board_binding_',dir=ROOT/'build') as name:
            directory=Path(name); sv=directory/'bench.sv'; sv.write_text(source)
            binary=directory/'bench.vvp'
            compile=subprocess.run(['iverilog','-g2012','-s','bench','-o',str(binary),str(sv)],text=True,capture_output=True,timeout=60)
            self.assertEqual(compile.returncode,0,compile.stdout+compile.stderr)
            result=subprocess.run(['vvp',str(binary)],text=True,capture_output=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS exact scalar and concatenated mapped wire force/release',result.stdout)


if __name__=='__main__': unittest.main()
