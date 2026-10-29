"""Synthetic three-line decoded USER2 replay controls; no hardware or artifacts."""
import unittest

from tools.ddr import audit_trained_tile

RKAD=0x524B4144
RKCD=0x524B4344
ABI=0x00010000
BASE=0x10000000
ADDRESSES=(BASE,BASE+64,BASE+128)


def command(op,address,data=0,response=0):
    return dict(op=op,address=address,data=data,response=response)


class TrainedTileReplayTests(unittest.TestCase):
    """Tests the generic wire replay library, not real-vector CLI admission."""
    def setUp(self):
        self.initial={address:((index+1)*0x0102030405060708090a0b0c0d0e0f)&((1<<512)-1)
                      for index,address in enumerate(ADDRESSES)}
        cmac=dict(self.initial)
        cmac[ADDRESSES[2]]^=0xA5A5
        ew=dict(cmac)
        ew[ADDRESSES[0]]^=0x5A5A
        self.expected={'cmac':cmac,'ew':ew,'repeat':ew}
        # Deltas are the exact changed lines that the worker sends between
        # phases. An empty repeat delta is legal and keeps this fixture small.
        self.deltas={'ew':{ADDRESSES[0]:ew[ADDRESSES[0]]},'repeat':{}}
        self.wire,self.spans=self.valid_stream()

    def valid_stream(self):
        w=[];spans=[]
        # Both IDs, both ABI reads and each healthy idle status precede any
        # BO upload. The command records are the auditor's decoded-wire input.
        w.extend((command(1,0,response=RKAD),command(1,4,response=ABI),
                  command(1,256,response=RKCD),command(1,260,response=ABI),
                  command(1,8,response=0x10),command(1,264,response=0x10)))
        for address,value in sorted(self.initial.items()):w.append(command(4,address,value))
        for address,value in sorted(self.initial.items()):w.append(command(3,address,response=value))
        phases=(('cmac','cmac',256,45,1),('ew','ew',0,22,2),
                ('cmac','repeat',256,45,1),('ew','ew',0,22,2))
        current=dict(self.initial)
        for phase,(profile,golden,base,amount,tasks) in enumerate(phases):
            delta=self.deltas['ew'] if profile=='ew' else self.deltas['repeat']
            delta_start=len(w)
            for address,value in sorted(delta.items()):
                current[address]=value
                w.extend((command(4,address,value),command(3,address,response=value)))
            tag=0x26000001+phase
            w.extend((command(2,base+16,BASE+0xE0000),command(2,base+20,amount),
                      command(2,base+24,tag),command(2,base+12,1)))
            active_status=len(w)
            w.extend((command(1,base+8,response=0x04),command(1,base+28,response=tag),
                      command(1,base+32,response=tasks),command(1,base+36,response=0)))
            outputs=[]
            for address,value in sorted(self.expected[golden].items()):
                outputs.append(len(w));w.append(command(3,address,response=value))
            ack=len(w);w.append(command(2,base+12,2))
            ready=len(w);w.append(command(1,base+8,response=0x10))
            spans.append(dict(profile=profile,golden=golden,amount=amount,tasks=tasks,tag=tag,
                              delta_start=delta_start,active_status=active_status,
                              outputs=outputs,ack=ack,ready=ready))
            current=dict(self.expected[golden])
        return w,spans

    def replay(self,wire=None):
        return audit_trained_tile.replay(self.wire if wire is None else wire,
                                         self.initial,self.expected,self.deltas)

    def test_four_phase_positive_checks_both_namespaces_full_readback_and_ack(self):
        self.assertEqual([(p['profile'],p['amount'],p['tasks'],p['tag']) for p in self.spans],
                         [('cmac',45,1,0x26000001),('ew',22,2,0x26000002),
                          ('cmac',45,1,0x26000003),('ew',22,2,0x26000004)])
        result=self.replay()
        self.assertEqual(result['raw_jobs'],4)
        self.assertEqual(result['tasks'],6)
        self.assertEqual(result['complete_bo_bytes'],4*64*3)
        self.assertTrue(result['complete_readback_before_each_ack'])
        self.assertEqual(result['upload_line_commands'],3+2)

    def test_both_ddr_ids_and_abis_are_required_before_any_upload(self):
        for address,wrong in ((0,RKAD^1),(4,ABI+1),(256,RKCD^1),(260,ABI+1)):
            with self.subTest(address=address):
                wire=list(self.wire);index=next(i for i,c in enumerate(wire) if c['op']==1 and c['address']==address)
                wire[index]=dict(wire[index],response=wrong)
                with self.assertRaises(ValueError):self.replay(wire)
                self.assertTrue(all(c['op']==1 for c in wire[:6]))

    def test_unknown_csr_and_opcode_are_rejected(self):
        for bad in (command(1,0x40),command(5,0)):
            with self.subTest(bad=bad):
                wire=list(self.wire);wire.insert(6,bad)
                with self.assertRaises(ValueError):self.replay(wire)

    def test_wrong_descriptor_namespace_amount_tag_and_task_count_are_rejected(self):
        cases=(('namespace',lambda c:dict(c,address=0x10)),
               ('amount',lambda c:dict(c,data=46)),
               ('tag',lambda c:dict(c,data=c['data']+1)),
               ('tasks',lambda c:dict(c,response=c['response']+1)))
        for name,mutate in cases:
            with self.subTest(name=name):
                wire=list(self.wire);span=self.spans[0]
                if name=='namespace':index=next(i for i,c in enumerate(wire) if i>span['delta_start'] and c['op']==2 and c['address']==272)
                elif name=='amount':index=next(i for i,c in enumerate(wire) if c['op']==2 and c['address']==276)
                elif name=='tag':index=next(i for i,c in enumerate(wire) if c['op']==2 and c['address']==280)
                else:index=next(i for i,c in enumerate(wire) if c['op']==1 and c['address']==288)
                wire[index]=mutate(wire[index])
                with self.assertRaises(ValueError):self.replay(wire)

    def test_early_ack_missing_tail_and_duplicate_output_read_are_rejected(self):
        span=self.spans[0]
        early=list(self.wire)
        ack=early.pop(span['ack']);early.insert(span['outputs'][0],ack)
        with self.assertRaises(ValueError):self.replay(early)
        missing=list(self.wire);missing.pop(span['outputs'][-1])
        with self.assertRaises(ValueError):self.replay(missing)
        duplicate=list(self.wire);duplicate.insert(span['outputs'][1],dict(duplicate[span['outputs'][0]]))
        with self.assertRaises(ValueError):self.replay(duplicate)

    def test_changed_output_and_altered_delta_upload_are_rejected(self):
        span=self.spans[0]
        changed=list(self.wire);index=span['outputs'][0]
        changed[index]=dict(changed[index],response=changed[index]['response']^1)
        with self.assertRaises(ValueError):self.replay(changed)
        delta=list(self.wire);index=next(i for i in range(self.spans[1]['delta_start'],self.spans[1]['ack'])
                                          if delta[i]['op']==4)
        delta[index]=dict(delta[index],data=delta[index]['data']^1)
        with self.assertRaises(ValueError):self.replay(delta)

    def test_error_status_with_zero_code_and_wrong_peer_ack_are_rejected(self):
        error_status=list(self.wire);span=self.spans[0]
        index=span['active_status']
        error_status[index]=dict(error_status[index],response=0x24)
        with self.assertRaises(ValueError):self.replay(error_status)
        peer_ack=list(self.wire);peer_ack[span['ack']]=dict(peer_ack[span['ack']],address=12)
        with self.assertRaises(ValueError):self.replay(peer_ack)

    def test_memory_health_must_be_restored_after_each_ack(self):
        missing=list(self.wire);missing.pop(self.spans[0]['ready'])
        with self.assertRaises(ValueError):self.replay(missing)
        # The final ACK also requires its own idle/memory-ready observation.
        missing=list(self.wire);missing.pop(self.spans[-1]['ready'])
        with self.assertRaises(ValueError):self.replay(missing)


if __name__=='__main__':unittest.main()
