"""Full-controller extraction/source gates, not actual independence or startup proof."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import audit_prefix_initialization_controller_cone as new


def ff(q,d='0'):
    c=dict(C=[8],CE=['1'],CLR=['0'],D=[d],Q=[q])
    return dict(type='FDCE',parameters={'INIT':'x'},connections=c,port_directions={k:'output' if k=='Q' else 'input' for k in c})


def fixture():
    signals={}; next_wire=10000
    for name,width in new.REGISTERS.items():
        signals[name]=list(range(next_wire,next_wire+width)); next_wire+=width
    signals['demo.memory.clk']=[8]; signals['demo.memory.host_rdata']=list(range(20000,20016))
    cells={}; cuts={}; registers=[]
    for name in new.REGISTERS:
        for offset,q in enumerate(signals[name]):
            cell=ff(q); record=dict(cell='q'+str(q),original_primitive=cell)
            registers.append(dict(signal=name,offset=offset,**record))
            cuts[str(q)]=dict(**record,pin='Q',bit=0)
    for w in signals['demo.memory.host_rdata']:
        cuts[str(w)]=dict(cell='host'+str(w),pin='Q',bit=0,original_primitive=ff(w))
    for i,name in enumerate(new.OUTPUTS):
        w=30000+i;signals[name]=[w];c=dict(I=[signals['demo.state'][0]],O=[w])
        cells['gate'+str(i)]=dict(type='INV',parameters={},connections=c,port_directions=dict(I='input',O='output'))
    return dict(signals=signals,cells=cells,producer_cuts=cuts,controller_registers=registers)


class InitializationControllerConeControl(unittest.TestCase):
    def test_all_47_register_folds_and_nine_controls_have_shared_boundary(self):
        cone=fixture();text=new.miter(cone)
        self.assertEqual(sum(new.REGISTERS.values()),47)
        self.assertEqual(text.count("1'b0 ? 1'b0 : 1'b1 ?"),94)
        self.assertEqual(text.count(' actual_0_'),9);self.assertEqual(text.count(' actual_1_'),9)
        self.assertIn('input [46:0] producer_cut,input [15:0] host_0,host_1',text)
        self.assertIn('wire [55:0] compared_0=',text);self.assertIn('wire [55:0] compared_1=',text)
        self.assertIn("wire init_phase=(state <= 4'd2)",text)
        self.assertNotIn('assume',text);self.assertNotIn('force',text)
        bad=copy.deepcopy(cone);del bad['producer_cuts'][str(cone['signals']['demo.index'][0])]
        with self.assertRaises(AssertionError):new.miter(bad)

    def test_unsupported_register_clock_flags_and_unknown_pin_stay_failures(self):
        new.validate_fold_register(ff(10),[8])
        for change in ('kind','clock','flag','unknown'):
            cell=ff(10)
            if change=='kind':cell['type']='FDRE';cell['connections']['R']=cell['connections'].pop('CLR');cell['port_directions']['R']=cell['port_directions'].pop('CLR')
            elif change=='clock':cell['connections']['C']=[9]
            elif change=='flag':cell['parameters']['IS_C_INVERTED']='1'
            else:cell['connections']['D']=['x']
            with self.assertRaises(AssertionError):new.validate_fold_register(cell,[8])

    def test_no_opaque_dsp_shortcut_or_silent_missing_driver(self):
        cone=fixture();signals=cone['signals'];q=signals['demo.state'][0]
        reg=ff(q,40000);dsp=dict(type='DSP48E1',parameters={},connections={'P':[40000]},port_directions={'P':'output'})
        def driver(w):
            if w==q:return 'q',reg,'Q',0
            if w==40000:return 'dsp',dsp,'P',0
            raise AssertionError('Missing actual driver')
        with self.assertRaises(AssertionError):new.trace_controller(signals,driver,{})

    def test_complete_byte_identical_library_selection_and_explicit_class_limit(self):
        data=new.LIBRARY.read_bytes();selected,records=new.selected_definitions(data,new.COMBINATIONAL)
        self.assertEqual(set(records),new.COMBINATIONAL)
        for record in records.values():
            self.assertIn(data[record['offset']:record['offset']+record['length']],selected)
        for bad in (set(),{'DSP48E1'},{'FDCE'}):
            with self.assertRaises(AssertionError):new.selected_definitions(data,bad)
        record=records['INV'];block=data[record['offset']:record['offset']+record['length']]
        with self.assertRaises(AssertionError):new.selected_definitions(data+block,{'INV'})
        with self.assertRaises(AssertionError):new.selected_definitions(data.replace(block,b''),{'INV'})

    def test_original_complete_storage_declarations_are_not_narrowed(self):
        text=new.prior.state.STATE_SOURCE.read_text()
        for declaration in ('logic [11:0] index;','logic [19:0] watchdog;','output logic [7:0] error_code'):
            self.assertIn(declaration,text)
        self.assertIn(new.prior.state.STATE_ENUM,text)
        self.assertEqual(len(new.OUTPUTS),9)
        self.assertIn('demo.memory.host_rsp_valid',new.REGISTERS)
        self.assertIn('demo.memory.rsp_error',new.REGISTERS)

    def test_actual_completed_parent_rebound_and_native_gates_revalidated(self):
        bindings={};counts=new.admit(bindings)
        self.assertGreaterEqual(len(bindings),653)
        self.assertEqual(sum(counts.values()),503128)
        self.assertEqual(counts['DSP48E1'],515);self.assertEqual(counts['RAMB36E1'],6)


if __name__=='__main__':
    unittest.main()
