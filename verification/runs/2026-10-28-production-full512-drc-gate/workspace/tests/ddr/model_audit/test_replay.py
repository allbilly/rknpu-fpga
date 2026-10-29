"""Synthetic read-only replay controls, with no hardware/numerical claim."""
import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests.tinystories.test_audit_model import fixture
from tools.tinystories import audit_model
from tools.tinystories.audit_model import audit,replay

def replay_ddr(*args):
    return replay(*args, memory_profile="ddr")

def ddr_fixture(corruption=None):
    data=list(fixture(corruption));wire=[]
    for original in data[0]:
        row=dict(original);op,address,value=(row[k] for k in ('op','address','data'))
        if op==1 and address in (0,256):row['response']=0x524b4144 if address==0 else 0x524b4344
        if op==1 and address in (28,284):
            wire.append(dict(op=1,address=address-20,data=0,response=2))
            wire.append(dict(op=1,address=address-20,data=0,response=4))
        wire.append(row)
        if op==1 and address in (4,260):wire.append(dict(op=1,address=address+4,data=0,response=16))
        if op==2 and address in (12,268) and value==2:
            wire.append(dict(op=1,address=address-4,data=0,response=16))
    data[0]=wire;return data

class DdrReplayTests(unittest.TestCase):
    def test_outer_ddr_audit_rejects_bram_image_and_preserves_profile_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);physical=root/'physical-tests';physical.mkdir()
            parent=dict(status='PASS_PHYSICAL_TINYSTORIES_FULL_MODEL_REQUIRES_INDEPENDENT_AUDIT',
                        owned_worker_exit=0,owned_bridge_exit=0,owned_hw_server_exit=0)
            (physical/'report.json').write_text(json.dumps(parent))
            (root/'image-review.json').write_text(json.dumps(dict(
                status='PASS_REVIEWED_TINYSTORIES_FULL512_DUAL_IMAGE')))
            with self.assertRaisesRegex(ValueError,'Wrong or changed image review'):
                audit(root,root,root,root,'greedy32',memory_profile='ddr')
        root=Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(dir=root/'build') as directory:
            for selected,extra in (('ddr',['--memory-profile','ddr']),('bram',[])):
                output=Path(directory)/(selected+'.json')
                argv=['audit_model.py','--run','unused-run','--package','unused-package',
                      '--catalog','unused-catalog','--reference','unused-reference',
                      '--phase','greedy32','--out',str(output),*extra]
                with self.subTest(failed_profile=selected),patch.object(sys,'argv',argv),\
                     patch.object(audit_model,'audit',side_effect=ValueError('synthetic rejected audit')):
                    with self.assertRaisesRegex(ValueError,'synthetic rejected audit'):
                        audit_model.main()
                receipt=json.loads(output.read_text())
                self.assertEqual(receipt['status'],'FAIL')
                self.assertEqual(receipt['memory_profile'],selected)
                self.assertEqual(receipt['phase'],'greedy32')
                self.assertFalse(receipt['full32_positions_accepted'])
                self.assertFalse(receipt['hardware_accessed'])
    def test_outer_ddr_audit_rejects_relabelled_parent_before_load_or_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);physical=root/'physical-tests';physical.mkdir()
            review=dict(status='PASS_REVIEWED_FULL512_CH1_DDR_DUAL_IMAGE',part='xc7k480tffg1156-2',
                        top='ypcb_ddr_dual_top',usr_access='12345678',source_sha256='12345678'+'0'*56,
                        programming_scope='volatile-sram',memory_profile='ddr',selected_physical_channel=1,
                        product_dsps=512,total_dsps=516,bram_blocks=0)
            path=root/'image-review.json';path.write_text(json.dumps(review))
            parent=dict(status='PASS_PHYSICAL_TINYSTORIES_FULL_MODEL_REQUIRES_INDEPENDENT_AUDIT',
                        owned_worker_exit=0,owned_bridge_exit=0,owned_hw_server_exit=0,
                        image_review_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        part=review['part'],memory_profile='bram',selected_physical_channel=1)
            (physical/'report.json').write_text(json.dumps(parent))
            with self.assertRaisesRegex(ValueError,'Wrong physical DDR source/profile census'):
                audit(root,root,root,root,'greedy32',memory_profile='ddr')
    def test_exact_raw_bytes_and_owned_pending_readiness_are_preserved(self):
        data=ddr_fixture();before=copy.deepcopy(data[0]);r=replay_ddr(*data)
        self.assertEqual(r['raw_jobs'],2);self.assertEqual(r['output_bo_bytes'],8192)
        self.assertEqual(data[0],before)
    def test_bram_identifiers_cannot_qualify_ddr(self):
        with self.assertRaisesRegex(ValueError,'namespace identity'):
            replay(*ddr_fixture())
        with self.assertRaisesRegex(ValueError,'Unsupported raw-model memory profile'):
            replay(*ddr_fixture(),memory_profile='auto')
        data=ddr_fixture()
        for row in data[0]:
            if row['op']==1 and row['address']==0:row['response']=0x524b4557;break
        with self.assertRaisesRegex(ValueError,'DDR namespace identity'):replay_ddr(*data)
    def test_empty_or_unknown_opcode_ddr_trace_cannot_qualify(self):
        for wire in ([],[dict(op=5,address=0,data=0,response=0)]):
            data=list(fixture());data[0]=wire;data[3]=[];data[4]=[];data[5]=[]
            with self.subTest(wire=wire),self.assertRaises(ValueError):replay_ddr(*data)
    def test_uninitialized_namespace_and_unknown_status_reject(self):
        for status in [0,0x800,0x18]:
            data=ddr_fixture()
            next(row for row in data[0] if row['op']==1 and row['address']==8)['response']=status
            with self.subTest(status=status),self.assertRaises(ValueError):replay_ddr(*data)
    def test_error_busy_or_unobserved_completion_cannot_authorize_bo_read(self):
        for status in [12,6,2,0x24]:
            data=ddr_fixture()
            next(row for row in data[0] if row['op']==1 and row['address']==264 and row['response']==4)['response']=status
            with self.subTest(status=status),self.assertRaises(ValueError):replay_ddr(*data)
    def test_owned_status_must_not_offer_another_submit(self):
        for status in (5,21):
            data=ddr_fixture()
            next(row for row in data[0] if row['op']==1 and row['address']==264 and row['response']==4)['response']=status
            with self.subTest(status=status),self.assertRaises(ValueError):replay_ddr(*data)
    def test_descriptor_write_before_both_namespace_probes_rejects(self):
        data=ddr_fixture();wire=data[0]
        index=next(i for i,row in enumerate(wire) if row['op']==2 and row['address']==16)
        descriptor=wire.pop(index);wire.insert(0,descriptor)
        with self.assertRaisesRegex(ValueError,'Descriptor write before both DDR namespaces are admitted'):
            replay_ddr(*data)
    def test_result_registers_must_precede_owned_readback(self):
        data=ddr_fixture();wire=data[0]
        index=next(i for i,row in enumerate(wire) if row['op']==1 and row['address']==284)
        delayed=wire.pop(index);read=next(i for i in range(index,len(wire)) if wire[i]['op']==3);wire.insert(read+1,delayed)
        with self.assertRaisesRegex(ValueError,'before validated DDR completion'):replay_ddr(*data)
    def test_ack_must_restore_healthy_memory_before_next_job_or_eof(self):
        for replacement in [None,0]:
            data=ddr_fixture();wire=data[0];ack=next(i for i,row in enumerate(wire) if row['op']==2 and row['address']==12 and row['data']==2)
            if replacement is None:wire.pop(ack+1)
            else:wire[ack+1]['response']=replacement
            with self.subTest(replacement=replacement),self.assertRaises(ValueError):replay_ddr(*data)
    def test_existing_raw_command_data_guard_and_ack_checks_still_reject(self):
        for corruption in ['command','tasks','input','weight','unity','guard','short_readback','unverified','wrong_ack']:
            with self.subTest(corruption=corruption),self.assertRaises(ValueError):replay_ddr(*ddr_fixture(corruption))

if __name__=='__main__':unittest.main()
