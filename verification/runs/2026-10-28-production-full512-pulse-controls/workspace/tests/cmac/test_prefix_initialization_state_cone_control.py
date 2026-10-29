"""State cone/paired-input source controls, not an executed actual SAT proof."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import audit_prefix_initialization_state_cone as new


def ff(q,d):
    c=dict(C=[8],CE=['1'],CLR=['0'],D=[d],Q=[q]);return dict(type='FDCE',parameters={'INIT':'x'},connections=c,port_directions={k:'output' if k=='Q' else 'input' for k in c})


class InitStateConeControl(unittest.TestCase):
    def test_state_miter_preserves_four_ce_clear_hold_folds_and_binary_data_pairing(self):
        host=list(range(100,116));qs=[10,11,12,13];regs=[dict(cell='q'+str(i),original_primitive=ff(q,20+i)) for i,q in enumerate(qs)]
        cuts={str(w):dict(cell='cut'+str(w),pin='Q',bit=0,original_primitive=ff(w,'0')) for w in qs+host}
        cells={}
        for i in range(4):
            c=dict(I0=[host[i]],I1=[qs[3]],O=[20+i])
            cells['gate'+str(i)]=dict(type='LUT2',parameters={'INIT':'1000'},connections=c,port_directions={k:'output' if k=='O' else 'input' for k in c})
        cone=dict(cells=cells,producer_cuts=cuts,state_registers=regs,signals={'demo.state':qs,'demo.memory.host_rdata':host,'demo.memory.clk':[8]})
        text=new.miter(cone)
        self.assertEqual(text.count(' actual_0_'),4);self.assertEqual(text.count(' actual_1_'),4)
        self.assertIn('input [3:0] producer_cut,input [15:0] host_0,host_1',text)
        self.assertIn("wire init_phase=(state <= 4'd2)",text)
        self.assertEqual(text.count("1'b0 ? 1'b0 : 1'b1 ?"),8)
        self.assertIn('next_0 == (next_1 ^ (NEGATIVE',text)
        self.assertNotIn('assume',text);self.assertNotIn('force',text)

    def test_wrong_register_interface_unknown_flags_and_clock_inversion_not_admitted(self):
        for change in ('flag','clock','unknown'):
            cell=ff(10,'0')
            if change=='flag':cell['parameters']['IS_C_INVERTED']='x'
            elif change=='clock':cell['connections']['C']=['x']
            else:cell['connections']['D']=['x']
            with self.assertRaises(AssertionError):new.coherent.validate_register(cell,'Q',0)

    def test_unsupported_combinational_producer_stays_explicit_failure(self):
        cell=dict(type='DSP48E1',parameters={},connections={'P':[100]},port_directions={'P':'output'})
        with self.assertRaises(AssertionError):new.coherent.validate_cell(cell)

    def test_original_four_bit_state_enum_coding_bound(self):
        self.assertIn(new.STATE_ENUM,new.STATE_SOURCE.read_text())
        self.assertEqual(new.STATE_Q,[29117,29119,44287,44288])


if __name__=='__main__':unittest.main()
