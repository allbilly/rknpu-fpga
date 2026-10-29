"""Synthetic raw-memory audit controls; no numerical or FPGA execution claim."""
from pathlib import Path
import base64
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
import zlib

from tools.tinystories.audit_model import audit,replay,sha as file_sha


def digest(data):return hashlib.sha256(data).hexdigest()


def blob(data):
    return dict(size=len(data),sha256=digest(data),zlib_base64=base64.b64encode(zlib.compress(data)).decode())


def fixture(corruption=None):
    buffers={name:dict(address=address,bytes=size) for name,address,size in [
        ('input',0x10000000,4096),('native_output',0x10001000,4096),
        ('linear_output',0x10002000,4096),('unity',0x10003000,4096),
        ('weights',0x10010000,4096),('command',0x100e0000,65536),('tasks',0x100f0000,16384)]}
    input_data=b'\x00\x3c'*32+bytes(4096-64);weights=b'weight!!'*512
    output_data=b'\x00\x40'*32
    initial={name:bytes(item['bytes']) for name,item in buffers.items()}
    initial.update(input=input_data,weights=weights,unity=b'\x00\x3c'*16+bytes(4096-32),
        native_output=b'\x5a\xa5'*2048,linear_output=b'\x5a\xa5'*2048)
    tile=dict(projection='fixture',first_output=0,address=buffers['weights']['address'],bytes=4096,file='weights.bin')
    prepared=dict(candidate_buffers=buffers,projections=[dict(name='fixture',inputs=32,outputs=32)],tiles=[tile])
    jobs={}
    for kind,profile,amount,count in [('cmac','cmac',45,1),('compaction','ew',22,2)]:
        command=kind.encode()+bytes(65536-len(kind));task=kind.encode()+bytes(64-len(kind))
        jobs[kind]=dict(profile=profile,address=buffers['command']['address'],amount=amount,task_count=count,
                        command_bo=blob(command),task_bo=blob(task))
    catalog=dict(programs=[dict(projection='fixture',first_output=0,**jobs)])
    oracle=[dict(name='fixture',input_fp16_sha256=digest(input_data[:64]),output_fp16_sha256=digest(output_data))]
    calls=[dict(oracle[0],first_job=0,raw_jobs=2)]
    wire=[];events=[]
    def command(op,address,data=0,response=0):wire.append(dict(op=op,address=address,data=data,response=response))
    def upload(name,data,verify=True):
        address=buffers[name]['address']
        for offset in range(0,len(data),64):
            value=int.from_bytes(data[offset:offset+64],'little')
            command(4,address+offset,value)
            if verify:command(3,address+offset,response=value)
    for base,identity in [(0,0x524b4557),(256,0x524b434d)]:
        command(1,base,response=identity);command(1,base+4,response=0x10000)
    for name,data in initial.items():
        if (corruption=='input' and name=='input') or (corruption=='weight' and name=='weights') or (
                corruption=='unity' and name=='unity'):
            data=bytes([data[0]^1])+data[1:]
        upload(name,data,verify=not(corruption=='unverified' and name=='input'))
    for index,kind in enumerate(('cmac','compaction')):
        job=jobs[kind];base=256 if kind=='cmac' else 0
        for name,key in [('command','command_bo'),('tasks','task_bo')]:
            data=zlib.decompress(base64.b64decode(job[key]['zlib_base64']))
            data+=bytes(buffers[name]['bytes']-len(data))
            if corruption==name and index==0:data=bytes([data[0]^1])+data[1:]
            upload(name,data)
        for offset,value in [(16,job['address']),(20,job['amount']),(24,index+1)]:command(2,base+offset,value)
        command(2,base+12,1)
        for offset,value in [(28,index+1),(32,job['task_count']),(36,0)]:command(1,base+offset,response=value)
        name='native_output' if kind=='cmac' else 'linear_output'
        actual=bytearray(initial[name])
        if kind=='cmac':
            actual[:32]=output_data[:32];actual[64:96]=output_data[32:]
            allowed=[[0,32],[64,96]]
        else:
            actual[:64]=output_data;allowed=[[0,64]]
            if corruption=='guard':actual[-1]^=1
        for offset in range(0,4096,64):
            if corruption=='short_readback' and index==1 and offset==4032:continue
            command(3,buffers[name]['address']+offset,response=int.from_bytes(actual[offset:offset+64],'little'))
        event=dict(profile=job['profile'],tag=index+1,tasks=job['task_count'],output=name,
            whole_bo_bytes=4096,output_sha256=digest(actual),
            output_zlib_base64=base64.b64encode(zlib.compress(actual)).decode(),
            ack_after_readback=True,allowed_ranges=allowed)
        events.append(event)
        if corruption=='wrong_ack' and index==1:base=256
        command(2,base+12,2)
    return wire,prepared,catalog,calls,oracle,events,{'weights.bin':weights}


class ModelAuditTests(unittest.TestCase):
    def test_artifact_hashing_streams_without_reading_entire_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'large-trace.jsonl';data=b'trace fixture\n'*200000
            path.write_bytes(data)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('Whole trace loaded')):
                self.assertEqual(file_sha(path),digest(data))

    def test_wire_replay_checks_both_jobs_and_complete_output_buffers(self):
        result=replay(*fixture())
        self.assertEqual(result,dict(raw_jobs=2,actual_projection_pairs=1,weight_tiles_checked_before_use=1,
                                     output_bo_bytes=8192,tasks=3))

    def test_changed_original_program_task_weight_unity_or_input_is_rejected(self):
        for corruption in ('command','tasks','weight','unity','input'):
            with self.subTest(corruption=corruption):
                with self.assertRaises(ValueError):replay(*fixture(corruption))

    def test_guard_readback_upload_and_ack_ownership_are_independent_requirements(self):
        for corruption in ('guard','short_readback','unverified','wrong_ack'):
            with self.subTest(corruption=corruption):
                with self.assertRaises(ValueError):replay(*fixture(corruption))

    def test_running_or_failed_parent_cannot_claim_full32_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);physical=run/'physical-tests';physical.mkdir()
            (run/'image-review.json').write_text('{}')
            for status in ('RUNNING_AUTHORIZED_VOLATILE_USER2_TEST','FAIL_USER2_PHYSICAL_TEST'):
                (physical/'report.json').write_text(json.dumps(dict(status=status)))
                with self.assertRaisesRegex(ValueError,'has not completed'):
                    audit(run,run,run,run,'greedy32')


if __name__=='__main__':unittest.main()
