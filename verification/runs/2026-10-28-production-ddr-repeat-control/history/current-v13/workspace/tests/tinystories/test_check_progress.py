"""Synthetic receipt controls; these tests execute no model or hardware math."""
from pathlib import Path
import hashlib
import json
import struct
import tempfile
import unittest

from tools.tinystories.check_progress import check
from tools.tinystories.prepare import MODEL_SHA,TOKENIZER_SHA


def digest(data):return hashlib.sha256(data).hexdigest()


def write_json(path,value):path.write_text(json.dumps(value)+'\n')


class CheckProgressTests(unittest.TestCase):
    def fixture(self,positions=7,extra_projections=2,status='RUNNING'):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);worker=root/'worker';reference=root/'reference'
        worker.mkdir();reference.mkdir()
        prompt=[1,403,407,261,378];generated=list(range(100,128))
        gold=b''.join(struct.pack('<512f',*[i+j/1024 for j in range(512)]) for i in range(32))
        dense=[dict(name=f'projection-{i}',input_fp16_sha256=digest(f'input-{i}'.encode()),
                    output_fp16_sha256=digest(f'output-{i}'.encode())) for i in range(1152)]
        result=dict(forward_positions=32,dense_calls=1152,prompt_tokens=prompt,
                    generated_tokens=generated,input_tokens=prompt+generated[:-1],text='x'*32)
        write_json(reference/'donor-result.json',result)
        write_json(reference/'donor-dense-calls.json',dense)
        (reference/'donor-logits.bin').write_bytes(gold)
        write_json(reference/'report.json',dict(status='PASS_CPU_FULL_TINYSTORIES_DONOR_POLICY_REFERENCE_ONLY',
            hardware_accessed=False,artifacts={p.name:digest(p.read_bytes()) for p in reference.iterdir()}))
        count=positions*36+extra_projections
        rows=[]
        for i in range(positions):
            forced=i<4;token=prompt[i+1] if forced else generated[i-4]
            rows.append(dict(position=i,input_token=result['input_tokens'][i],next_token=token,
                forced_prompt=forced,stop=False,piece_hex=b'x'.hex(),logits_offset=i*2048,
                logits_bytes=2048,logits_sha256=digest(gold[i*2048:(i+1)*2048]),utc='fixture'))
        (worker/'positions.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        (worker/'projection-calls.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in dense[:count]))
        (worker/'logits.bin').write_bytes(gold[:positions*2048])
        record=dict(status=status,backend='jtag',model_sha256=MODEL_SHA,tokenizer_sha256=TOKENIZER_SHA,
            steps=32,prompt='Once upon a time',cpu_dense_fallback=False,completed_positions=positions,
            completed_projections=count,prefix=dict(completed_positions=positions,
                generated_tokens=generated[:max(0,positions-4)],text='x'*positions))
        write_json(worker/'report.json',record)
        return worker,reference,record

    def test_running_snapshot_ignores_only_unmarked_trailing_data(self):
        worker,reference,_=self.fixture()
        for name in ('positions.jsonl','projection-calls.jsonl','logits.bin'):
            with (worker/name).open('ab') as stream:stream.write(b'unmarked incomplete tail')
        result=check(worker,reference)
        self.assertEqual(result['completed_positions_checked'],7)
        self.assertEqual(result['completed_projection_pairs_checked'],254)
        self.assertEqual(result['producer_status'],'RUNNING')
        self.assertFalse(result['full_hardware_run_accepted'])
        self.assertFalse(result['raw_wire_audited'])

    def test_empty_startup_and_first_inflight_forward_have_no_completed_position(self):
        for projections in (0,2):
            with self.subTest(projections=projections):
                worker,reference,record=self.fixture(0,projections)
                record.pop('prefix');write_json(worker/'report.json',record)
                (worker/'positions.jsonl').unlink();(worker/'logits.bin').unlink()
                if projections==0:(worker/'projection-calls.jsonl').unlink()
                result=check(worker,reference)
                self.assertEqual(result['completed_positions_checked'],0)
                self.assertEqual(result['completed_projection_pairs_checked'],projections)
                self.assertFalse(result['full_hardware_run_accepted'])

    def test_failed_valid_prefix_preserves_failure_without_accepting_run(self):
        worker,reference,_=self.fixture(status='FAIL')
        result=check(worker,reference)
        self.assertEqual(result['producer_status'],'FAIL')
        self.assertEqual(result['status'],'MATCHED_RECORDED_COMPLETED_PREFIX_ONLY')
        self.assertFalse(result['full_hardware_run_accepted'])

    def test_counted_corruption_or_missing_data_is_rejected(self):
        for corruption in ('logits','short_logits','token','row_hash','dense_input','dense_output','short_row','prefix'):
            with self.subTest(corruption=corruption):
                worker,reference,record=self.fixture()
                if corruption=='logits':
                    path=worker/'logits.bin';data=bytearray(path.read_bytes());data[0]^=1;path.write_bytes(data)
                elif corruption=='short_logits':(worker/'logits.bin').write_bytes(b'')
                elif corruption=='prefix':
                    record['prefix']['text']='wrong';write_json(worker/'report.json',record)
                else:
                    path=worker/('projection-calls.jsonl' if corruption.startswith('dense_') else 'positions.jsonl')
                    lines=path.read_text().splitlines(keepends=True)
                    if corruption=='short_row':lines[0]=lines[0].rstrip('\n')
                    else:
                        row=json.loads(lines[0])
                        key={'token':'next_token','row_hash':'logits_sha256','dense_input':'input_fp16_sha256',
                             'dense_output':'output_fp16_sha256'}[corruption]
                        row[key]=511 if corruption=='token' else '0'*64
                        lines[0]=json.dumps(row)+'\n'
                    path.write_text(''.join(lines))
                with self.assertRaises((ValueError,json.JSONDecodeError)):check(worker,reference)

    def test_completion_requires_all_positions_and_exact_end_of_records(self):
        success='PASS_PHYSICAL_HYBRID_MODEL_EXECUTION_REQUIRES_INDEPENDENT_AUDIT'
        for tail in ('short','positions.jsonl','projection-calls.jsonl','logits.bin'):
            with self.subTest(tail=tail):
                worker,reference,_=self.fixture(7 if tail=='short' else 32,0,success)
                if tail!='short':
                    with (worker/tail).open('ab') as stream:stream.write(b'extra')
                with self.assertRaises(ValueError):check(worker,reference)
        worker,reference,record=self.fixture(32,0,success)
        result=check(worker,reference)
        self.assertEqual(result['completed_positions_checked'],32)
        self.assertFalse(result['full_hardware_run_accepted'])
        record['status']='PASS_CPU_MODEL_REFERENCE_ONLY';write_json(worker/'report.json',record)
        with self.assertRaisesRegex(ValueError,'backend'):check(worker,reference)

    def test_changed_reference_and_unknown_workload_are_rejected(self):
        for corruption in ('reference','steps','model','fallback','status','counts'):
            with self.subTest(corruption=corruption):
                worker,reference,record=self.fixture()
                if corruption=='reference':(reference/'donor-logits.bin').write_bytes(b'changed')
                else:
                    key,value={'steps':('steps',31),'model':('model_sha256','0'*64),
                        'fallback':('cpu_dense_fallback',True),'status':('status','SUCCESS'),
                        'counts':('completed_projections',0)}[corruption]
                    record[key]=value;write_json(worker/'report.json',record)
                with self.assertRaises(ValueError):check(worker,reference)


if __name__=='__main__':unittest.main()
