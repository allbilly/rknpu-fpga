"""Expanded actual-source extraction and reset-guarded temporal-model controls."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import audit_prefix_temporal_controller_cone as new


def fixture():
    signals={};qwire=10000;regs=[];cuts={};cells={}
    for name,width in new.REGISTERS.items():
        signals[name]=list(range(qwire,qwire+width));qwire+=width
        for offset,q in enumerate(signals[name]):
            c=dict(C=[8],CE=['1'],CLR=[40000],D=['0'],Q=[q])
            cell=dict(type='FDCE',parameters={'INIT':'x'},connections=c,port_directions={p:'output' if p=='Q' else 'input' for p in c})
            r=dict(cell='q'+str(q),original_primitive=cell)
            regs.append(dict(signal=name,offset=offset,**r));cuts[str(q)]=dict(**r,pin='Q',bit=0)
    signals['demo.memory.clk']=[8];signals['demo.rst_n']=[50000]
    c=dict(C=[8],CE=['1'],CLR=['0'],D=['0'],Q=[50000])
    cuts['50000']=dict(cell='outer_reset',pin='Q',bit=0,original_primitive=dict(type='FDCE',parameters={'INIT':'x'},connections=c,port_directions={p:'output' if p=='Q' else 'input' for p in c}))
    cells['reset_inv']=dict(type='INV',parameters={},connections={'I':[50000],'O':[40000]},port_directions={'I':'input','O':'output'})
    for i,name in enumerate(new.OUTPUTS):
        w=30000+i;signals[name]=[w]
        cells['control'+str(i)]=dict(type='INV',parameters={},connections={'I':[signals['demo.state'][0]],'O':[w]},port_directions={'I':'input','O':'output'})
    signals['demo.memory.host_rdata']=list(range(20000,20016))
    for w in signals['demo.memory.host_rdata']:
        cuts[str(w)]=dict(cell='host'+str(w),pin='DOADO',bit=0,original_primitive={})
    return dict(signals=signals,cells=cells,producer_cuts=cuts,controller_registers=regs)


class TemporalControllerConeControl(unittest.TestCase):
    def test_full_50_bits_and_60_comparisons_preserve_register_folds(self):
        cone=fixture();text=new.miter(cone)
        self.assertEqual(sum(new.REGISTERS.values()),50);self.assertEqual(len(new.OUTPUTS),10)
        self.assertEqual(text.count(" ? 1'b0 : 1'b1 ?"),100)
        self.assertIn('wire [59:0] compared_0=',text)
        self.assertIn('prefix_temporal_controller_miter',text)
        self.assertIn('demo.engine.state',new.WIDTHS);self.assertIn('demo.rst_n',new.WIDTHS)

    def test_real_state_uninitialized_reset_observation_and_arbitrary_probe(self):
        text=new.clock_model(fixture())
        self.assertIn('reg [49:0] storage_state;',text)
        self.assertNotIn('storage_state=',text)
        self.assertIn("reg seen_reset=1'b0",text)
        self.assertIn('if(!reset_n) begin seen_reset',text)
        self.assertIn('probe<=arbitrary_probe',text)
        self.assertIn('host_fire&&host_write',text)
        self.assertIn('index==probe',text)
        self.assertIn('after_async_clear',text)
        self.assertIn('!seen_reset||!reset_n',text)
        self.assertIn("!request_valid||writes_seen==13'd4096",text)
        self.assertIn('!(host_fire&&core_fire)',text)
        self.assertNotIn('assume',text);self.assertNotIn('force',text);self.assertNotIn('anyconst',text)

    def test_fixed_dma_state_enum_original_primitive_guards_and_full_budget(self):
        self.assertIn(new.DMA_ENUM,new.DMA_SOURCE.read_text())
        self.assertIn('len(nodes) <= 503128',new.TRACE_SOURCE)
        self.assertIn('len(cuts) <= 17519+432',new.TRACE_SOURCE)
        self.assertNotIn('DSP48E1',new.TRACE_SOURCE)
        self.assertIn('validate_fold_register',new.TRACE_SOURCE)

    def test_actual_completed_47_bit_parent_and_both_real_negatives_revalidated(self):
        bindings={};counts=new.admit(bindings)
        self.assertGreaterEqual(len(bindings),724)
        self.assertEqual(sum(counts.values()),503128)
        self.assertEqual(counts['DSP48E1'],515);self.assertEqual(counts['RAMB36E1'],6)


if __name__=='__main__':unittest.main()
