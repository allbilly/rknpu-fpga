#!/usr/bin/env python3
"""Offline joined USER3-link/SYS-register whole-reset tests using fake RPC frames."""
import socket
import unittest

from tools.host.native_link import NativeLink
from tools.host.sys_mailbox_access import SysMailboxAccess, build_write_frame, START, CANCEL, ACK
from tools.host.sys_mailbox import RKPR, ABI, CAP, MAGIC, ProtocolError

ACTIVE, RESULT, ERROR, QUIESCE = 2, 4, 8, 16
SENT, ASSERTED, COMPLETE, FAULT, READY = 32, 64, 512, 1024, 2048
SUCCESS = RESULT | QUIESCE | SENT | ASSERTED | COMPLETE | READY


def rsp(seq,status=0,data=0,*,magic=MAGIC,reserved=0):
    return (reserved<<568)|(magic<<536)|((seq&0xffff)<<520)|((status&0xff)<<512)|(data&((1<<512)-1))


class FakeSysRpc:
    def __init__(self,*,fail=False,write_status=0,write_payload=0,bad_magic=False,reserved=False,stale_write=False,timeout_write=False,registers=None):
        self.rx=bytearray(b'READY 3000000 USER3\n');self.sent=[];self.closed=False;self.selected=0
        self.response=rsp(0);self.registers=dict(registers or {});self.fail=fail;self.write_status=write_status;self.write_payload=write_payload
        self.bad_magic=bad_magic;self.reserved=reserved;self.stale_write=stale_write;self.timeout_write=timeout_write
        self.raw_requests=[];self.actions=[];self.started=False;self.acked=False;self.attempts=0;self.epoch=0;self.status_i=0;self.post_i=0
        self.error=3 if fail else 0;self.phase=5 if fail else 4;self.coord_error=7 if fail else 0
        self.default_registers={0x00:RKPR,0x04:ABI,0x1c:CAP,0x08:1,0x10:0,0x14:0,0x18:0,0x20:0,0x24:0,0x28:100000,0x2c:0}
        self.default_registers.update(self.registers)
    def settimeout(self,_):pass
    def recv(self,size):
        if not self.rx:return b''
        out=bytes(self.rx[:size]);del self.rx[:size];return out
    def close(self):self.closed=True
    def _status(self):
        if self.acked:
            values=[SENT|ASSERTED|COMPLETE|READY,1|SENT|ASSERTED|COMPLETE|READY]
            value=values[min(self.post_i,len(values)-1)];self.post_i+=1;return value
        if not self.started:return self.default_registers[0x08]
        if self.fail:return RESULT|ERROR|QUIESCE|SENT|ASSERTED
        values=[ACTIVE|QUIESCE|SENT|COMPLETE|READY|FAULT,ACTIVE|QUIESCE|SENT,SUCCESS]
        value=values[min(self.status_i,len(values)-1)];self.status_i+=1;return value
    def _read_reg(self,address):
        if address==0x08:return self._status()
        if address==0x10:return self.attempts
        if address==0x14:return self.epoch
        if address==0x18:return self.error
        if address==0x20:return self.phase
        if address==0x24:return self.coord_error
        return self.default_registers.get(address,0)
    def _handle(self,frame):
        if frame==0:return
        self.raw_requests.append(frame)
        if frame>>604 or ((frame>>572)&0xffffffff)!=MAGIC:raise AssertionError('Malformed raw frame sent')
        address=(frame>>512)&0xffffffff;strobes=(frame>>544)&0xf;opcode=(frame>>548)&0xff;seq=(frame>>556)&0xffff;data=frame&((1<<512)-1)
        if strobes!=0xf:raise AssertionError('SYS frame did not use all four strobes')
        if opcode==1:
            if data:raise AssertionError('READ carried data payload')
            payload=self._read_reg(address)
            self.response=rsp(seq,0,payload,magic=0 if self.bad_magic else MAGIC,reserved=1 if self.reserved else 0)
        elif opcode==2:
            self.actions.append((address,data&0xffffffff))
            if address!=0x0c or data>>32:raise AssertionError('Write escaped command register or upper payload not zero')
            command=data&0xffffffff
            status=self.write_status if command==ACK else 0;payload=self.write_payload if command==ACK else 0
            if command==START:
                self.started=True;self.attempts+=1
                if not self.fail:self.epoch+=1
            elif command==ACK:self.acked=True
            elif command!=CANCEL:raise AssertionError('Unsupported SYS command write')
            reply_seq=(seq-1)&0xffff if self.stale_write else seq
            self.response=rsp(reply_seq,status,payload,magic=0 if self.bad_magic else MAGIC,reserved=1 if self.reserved else 0)
        else:raise AssertionError('Adapter sent non-read/write opcode')
    def sendall(self,payload):
        line=payload.decode('ascii').strip();self.sent.append(line);fields=line.split()
        if fields[0]=='RESET':raise AssertionError('Unexpected TAP RESET')
        if fields[0]=='QUIT':raise AssertionError('Probe closed/quit borrowed bridge')
        if fields[0]!='SCAN':raise AssertionError('Unexpected native RPC command '+line)
        _,kind,bits,hexval=fields;bits=int(bits);value=int(hexval,16)
        if kind=='IR':
            if bits!=6 or value!=0x22:raise AssertionError('Unexpected IR command')
            self.selected=value;self.rx.extend(b'OK 0\n');return
        if kind!='DR' or bits!=640 or self.selected!=0x22:raise AssertionError('Unexpected DR selection/width')
        old=self.response
        if value and self.timeout_write and ((value>>548)&0xff)==2:raise socket.timeout('synthetic ambiguous write timeout')
        self._handle(value)
        reply=old
        self.rx.extend(f'OK {reply:x}\n'.encode('ascii'))


def make_access(**kwargs):
    rpc=FakeSysRpc(**kwargs);link=NativeLink(sock=rpc,allow_user3=True,timeout=0.1)
    return SysMailboxAccess(link,timeout=1.0),rpc,link


class SysMailboxAccessTests(unittest.TestCase):
    def test_constructor_is_io_free_and_access_borrows_link(self):
        rpc=FakeSysRpc();link=NativeLink(sock=rpc,allow_user3=True,timeout=0.1);sent=list(rpc.sent)
        access=SysMailboxAccess(link,timeout=1.0)
        self.assertEqual(rpc.sent,sent)
        access.close()
        self.assertFalse(rpc.closed)

    def test_wire_joined_success_has_actual_user3_raw_start_ack_once(self):
        access,rpc,link=make_access()
        receipt=access.perform_reset(timeout=1.0)
        self.assertEqual(receipt.action_writes,((0x0c,START),(0x0c,ACK)))
        self.assertEqual(rpc.actions,[(0x0c,START),(0x0c,ACK)])
        self.assertEqual(rpc.sent[0],'SCAN IR 6 22')
        self.assertFalse(any(cmd.startswith('RESET') or cmd.startswith('QUIT') for cmd in rpc.sent))
        self.assertTrue(all(((frame>>548)&0xff)==1 for frame in rpc.raw_requests if ((frame>>548)&0xff)==1))
        self.assertTrue(all(frame>>604==0 and ((frame>>544)&0xf)==0xf for frame in rpc.raw_requests))
        self.assertFalse(rpc.closed);self.assertIs(access._link,link)

    def test_user3_write_whitelist_rejects_before_any_frame(self):
        access,rpc,_=make_access()
        with self.assertRaises(ValueError):access.write_register(0x10,START)
        with self.assertRaises(ValueError):access.write_register(0x0c,0x12345678)
        self.assertEqual(rpc.raw_requests,[])

    def test_build_write_frame_exact_fields_and_upper_payload(self):
        frame=build_write_frame(START,7)
        self.assertEqual((frame>>512)&0xffffffff,0x0c)
        self.assertEqual((frame>>544)&0xf,0xf)
        self.assertEqual((frame>>548)&0xff,2)
        self.assertEqual((frame>>556)&0xffff,7)
        self.assertEqual((frame>>572)&0xffffffff,MAGIC)
        self.assertEqual((frame>>32)&((1<<480)-1),0)
        with self.assertRaises(ValueError):build_write_frame(0x1234,7)
        with self.assertRaises(ValueError):build_write_frame(START,0)

    def test_first_write_rechecks_identity_and_wrong_cap_never_sends_write(self):
        access,rpc,_=make_access(registers={0x1c:0x10000})
        with self.assertRaises(ProtocolError):access.write_register(0x0c,START)
        self.assertFalse(rpc.actions)
        self.assertTrue(all(((f>>548)&0xff)==1 for f in rpc.raw_requests))

    def test_full_lifecycle_has_no_extra_action_and_one_shared_link(self):
        access,rpc,link=make_access()
        receipt=access.perform_reset(timeout=1.0)
        self.assertEqual([v for _,v in receipt.action_writes],[START,ACK])
        self.assertIs(access._link,link);self.assertFalse(rpc.closed)
        self.assertTrue(all(addr==0x0c and value in (START,ACK) for addr,value in rpc.actions))

    def test_held_sys_failure_is_never_acknowledged(self):
        access,rpc,_=make_access(fail=True)
        with self.assertRaises(ProtocolError):access.perform_reset(timeout=1.0)
        self.assertEqual(rpc.actions,[(0x0c,START)])
        self.assertFalse(any(value==ACK for _,value in rpc.actions))
        self.assertTrue(access._failed)

    def test_ack_nonzero_success_payload_poison_no_retry(self):
        access,rpc,_=make_access(write_payload=1)
        with self.assertRaises(ProtocolError):access.perform_reset(timeout=1.0)
        self.assertEqual([v for _,v in rpc.actions],[START,ACK])
        self.assertTrue(access._failed)

    def test_ack_transport_error_poison_no_retry(self):
        access,rpc,_=make_access(write_status=2,write_payload=0)
        with self.assertRaises(ProtocolError):access.perform_reset(timeout=1.0)
        self.assertEqual([v for _,v in rpc.actions],[START,ACK])

    def test_stale_write_response_poison_without_retry(self):
        access,rpc,_=make_access(stale_write=True)
        with self.assertRaises(ProtocolError):access.write_register(0x0c,START,deadline=__import__('tools.host.transport',fromlist=['_Deadline'])._Deadline(0.02,access._clock))
        self.assertEqual([v for _,v in rpc.actions],[START])
        self.assertTrue(access._failed)

    def test_invalid_response_magic_or_reserved_bits_poison_without_retry(self):
        for kwargs in ({'bad_magic':True},{'reserved':True}):
            with self.subTest(kwargs=kwargs):
                access,rpc,_=make_access(**kwargs)
                with self.assertRaises(ProtocolError):access.write_register(0x0c,START)
                self.assertEqual(rpc.actions,[])
                self.assertTrue(access._failed)

    def test_ambiguous_write_timeout_does_not_retry(self):
        access,rpc,_=make_access(timeout_write=True)
        with self.assertRaises(Exception):access.write_register(0x0c,START)
        self.assertEqual([v for _,v in rpc.actions],[])
        self.assertTrue(access._failed)

    def test_preexisting_error_poison_does_not_emit_ack(self):
        access,rpc,_=make_access(fail=True)
        with self.assertRaises(ProtocolError):access.perform_reset(timeout=1.0)
        self.assertEqual(rpc.actions,[(0x0c,START)])
        self.assertNotIn(ACK,[value for _,value in rpc.actions])


if __name__=='__main__':unittest.main()
