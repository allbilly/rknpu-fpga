"""Byte/ownership control fixtures only; no numerical oracle or hardware."""
import base64
import hashlib
import unittest
from types import SimpleNamespace
import zlib

from tools.tinystories.device import RawDenseDevice


def blob(raw):
    return dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),zlib_base64=base64.b64encode(zlib.compress(raw)).decode())


class Transport:
    def __init__(self):
        self.memory={};self.writes=[];self.reads=[];self.acks=0;self.mutation=None;self.tasks=1;self.corrupt_read=False
    def select_profile(self,profile):self.profile=profile
    def mem_write(self,address,data):self.memory[address]=bytearray(data);self.writes.append((address,bytes(data)))
    def mem_read(self,address,size):
        self.reads.append((address,size));data=bytes(self.memory.get(address,bytes(size)))
        return bytes([data[0]^1])+data[1:] if self.corrupt_read else data
    def submit(self,address,amount,tag):
        self.tag=tag
        if self.mutation is not None:self.mutation(self.memory[0x10001000])
    def poll_result(self,timeout):return SimpleNamespace(tag=self.tag,completed_tasks=self.tasks,error_code=0,status=0x714)
    def ack_success(self):self.acks+=1


def fixture():
    # Construct only the isolated control layer. Production construction still
    # requires the complete pinned model/catalog and an audited transport.
    device=RawDenseDevice.__new__(RawDenseDevice)
    device.transport=Transport();device.tag=0;device.records=[];device.calls=[];device.observer=None
    device.poisoned=False;device.initialized=True
    device.buffers={'command':dict(address=0x100e0000),'tasks':dict(address=0x100f0000),
                    'native_output':dict(address=0x10001000)}
    device.shadow={'command':bytearray(65536),'tasks':bytearray(16384),
                   'native_output':bytearray(b'\x5a\xa5'*2048)}
    for name,data in device.shadow.items():device.transport.memory[device.buffers[name]['address']]=bytearray(data)
    job=dict(profile='cmac',address=0x100e0000,amount=45,task_count=1,
             command_bo=blob(bytes(65536)),task_bo=blob(bytes(4096)))
    return device,job


class RawDeviceControlTests(unittest.TestCase):
    def test_complete_output_readback_precedes_ack(self):
        device,job=fixture()
        def update(data):data[:32]=b'\x00\x3c'*16;data[64:96]=b'\x00\x3c'*16
        device.transport.mutation=update
        device._execute(job,'native_output',[(0,32),(64,96)])
        self.assertEqual(device.transport.acks,1)
        self.assertIn((0x10001000,4096),device.transport.reads)
        self.assertTrue(device.records[0]['ack_after_readback'])
        self.assertEqual(device.shadow['native_output'][32:64],b'\x5a\xa5'*16)

    def test_escaped_write_or_nonfinite_result_prevents_ack(self):
        for mode in ('guard','nonfinite'):
            device,job=fixture()
            def update(data):
                if mode=='guard':data[1000]^=1
                else:data[0:2]=b'\x00\x7c'
            device.transport.mutation=update
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                device._execute(job,'native_output',[(0,32),(64,96)])
            self.assertEqual(device.transport.acks,0)

    def test_wrong_task_count_prevents_output_acceptance(self):
        device,job=fixture();device.transport.tasks=2
        with self.assertRaises(ValueError):device._execute(job,'native_output',[(0,32),(64,96)])
        self.assertEqual(device.transport.acks,0)
        self.assertNotIn((0x10001000,4096),device.transport.reads)

    def test_delta_upload_preserves_complete_original_bytes(self):
        device,_=fixture();target=bytearray(65536);target[70]=0x5a
        device._replace('command',target)
        self.assertEqual(device.transport.writes,[(0x100e0040,bytes(target[64:128]))])
        self.assertEqual(device.shadow['command'],target)
        before=len(device.transport.writes);device._replace('command',target)
        self.assertEqual(len(device.transport.writes),before)

    def test_corrupt_transfer_is_never_silently_accepted(self):
        device,_=fixture();device.transport.corrupt_read=True;target=bytearray(65536);target[70]=0x5a
        with self.assertRaises(ValueError):device._replace('command',target)
        self.assertEqual(device.shadow['command'],bytes(65536))


if __name__=='__main__':unittest.main()
