#!/usr/bin/env python3
"""Offline tests for private USER3 opt-in, SysMailboxProbe and Tcl dispatch."""
from pathlib import Path
import importlib.util
import re
import shutil
import subprocess
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
from tools.host.sys_mailbox import SysMailboxProbe, build_read_frame, RKPR, ABI, CAP, REGISTER_ADDRESSES
from tools.host import native_link

MAGIC = 0x4F54504A


def response(sequence, status=0, payload=0, *, magic=MAGIC, reserved=0):
    return (reserved << 568) | (magic << 536) | ((sequence & 0xFFFF) << 520) | ((status & 0xFF) << 512) | payload


class FakeSocket:
    def __init__(self, ready):
        self.rx = bytearray(ready)
        self.sent = []
        self.closed = False
    def settimeout(self, _): pass
    def recv(self, size):
        if not self.rx:return b''
        value=bytes(self.rx[:size]);del self.rx[:size];return value
    def sendall(self, payload):
        self.sent.append(payload.decode('ascii'))
        self.rx.extend(b'OK 0\n')
    def close(self):self.closed=True


class FakeBorrowedLink:
    def __init__(self, values=None, *, baseline=None, stale=False, bad_status=0, bad_payload=0, bad_magic=MAGIC, reserved=0, timeout=False):
        self.allow_user3=True
        self._mutex=threading.RLock()
        self.values=dict(values or {})
        self.baseline=response(0xFFFF) if baseline is None else baseline
        self.last_response=self.baseline
        self.pending=None
        self.first_dr=True
        self.stale=stale
        self.bad_status=bad_status
        self.bad_payload=bad_payload
        self.bad_magic=bad_magic
        self.reserved=reserved
        self.timeout=timeout
        self.calls=[]
        self.closed=False
    def scan(self, value, bits=640, *, ir=False, deadline=None):
        self.calls.append((value,bits,ir))
        if ir:
            return 0
        if bits!=640:raise ValueError('test link expects 640-bit DR')
        if self.first_dr:
            self.first_dr=False
            return self.baseline
        if value:
            frame=value
            if (frame>>548)&0xff != 1:raise AssertionError('probe issued non-READ opcode')
            if (frame>>544)&0xf != 0xf:raise AssertionError('probe omitted full strobes')
            if frame&((1<<512)-1):raise AssertionError('probe sent write/data payload')
            if frame>>604:raise AssertionError('probe request reserved bits not zero')
            sequence=(frame>>556)&0xffff;address=(frame>>512)&0xffffffff
            self.pending=(sequence,address)
            return self.last_response
        if self.timeout:
            raise TimeoutError('synthetic mailbox read timeout')
        if self.pending is not None:
            sequence,address=self.pending
            if self.stale:
                return self.last_response
            payload=self.values.get(address,0)
            if self.bad_status or self.bad_payload or self.bad_magic!=MAGIC or self.reserved:
                reply=response(sequence,self.bad_status,self.bad_payload,magic=self.bad_magic,reserved=self.reserved)
            else:
                reply=response(sequence,0,payload)
            self.last_response=reply
            self.pending=None
            return reply
        return self.last_response
    def close(self):self.closed=True


class User3OptInTests(unittest.TestCase):
    def test_default_native_link_still_rejects_user3(self):
        sock=FakeSocket(b'READY 3000000\n')
        link=native_link.NativeLink(sock=sock)
        self.assertFalse(link.allow_user3)
        link.scan(0x03,bits=6,ir=True)
        before=list(sock.sent)
        with self.assertRaises(ValueError):link.scan(0x22,bits=6,ir=True)
        self.assertEqual(sock.sent,before)
        self.assertEqual(sock.sent,['SCAN IR 6 3\n'])
        link.close()

    def test_native_link_optin_requires_matching_tcl_handshake(self):
        sock=FakeSocket(b'READY 3000000 USER3\n')
        link=native_link.NativeLink(sock=sock,allow_user3=True)
        self.assertTrue(link.allow_user3)
        self.assertEqual(link.scan(0x22,bits=6,ir=True),0)
        with self.assertRaises(ValueError):link.scan(0x22,bits=5,ir=True)
        with self.assertRaises(ValueError):link.scan(0,bits=32)
        self.assertEqual(link.scan(0,bits=640),0)
        self.assertEqual(sock.sent,['SCAN IR 6 22\n','SCAN DR 640 0\n'])
        link.close()
        wrong=FakeSocket(b'READY 3000000\n')
        with self.assertRaises(Exception):native_link.NativeLink(sock=wrong,allow_user3=True)
        self.assertTrue(wrong.closed)

    def test_allow_user3_is_explicit_bool_at_python_boundary(self):
        with self.assertRaises(ValueError):native_link.NativeLink(sock=FakeSocket(b'READY 3000000\n'),allow_user3=1)
        with self.assertRaises(ValueError):native_link.render_bridge('server/xc7k480t','server','0123abcd','/tmp/ready',allow_user3=1)

    def test_render_bridge_has_optin_and_default_user2(self):
        default=native_link.render_bridge('server/xc7k480t','server','0123abcd','/tmp/ready')
        enabled=native_link.render_bridge('server/xc7k480t','server','0123abcd','/tmp/ready',allow_user3=True)
        self.assertIn('set allow_user3 0',default)
        self.assertIn('set allow_user3 1',enabled)
        self.assertIn('READY 3000000 USER3',enabled)
        self.assertIn('READY 3000000',default)

    def test_probe_is_readonly_and_seeds_sequence_from_baseline(self):
        values={0x00:RKPR,0x04:ABI,0x08:0x801,0x10:8,0x14:6,0x18:0,0x1c:CAP,0x20:5,0x24:3,0x28:0x12345678,0x2c:0x9abcdef0}
        link=FakeBorrowedLink(values,baseline=response(0xFFFF))
        probe=SysMailboxProbe(link,timeout=1.0)
        result=probe.probe()
        self.assertEqual(result['rkpr'],RKPR);self.assertEqual(result['abi'],ABI);self.assertEqual(result['capability'],CAP)
        self.assertEqual(result['deadline_edges'],0x9ABCDEF012345678)
        self.assertTrue(result['read_only']);self.assertFalse(result['tap_or_fabric_reset_requested'])
        self.assertEqual(link.calls[0],(0x22,6,True))
        frames=[v for v,bits,ir in link.calls if not ir and v]
        self.assertEqual([(f>>556)&0xffff for f in frames],list(range(1,12)))
        self.assertTrue(all(((f>>548)&0xff)==1 for f in frames))
        self.assertFalse(link.closed)
        probe.close();self.assertFalse(link.closed)

    def test_probe_rejects_user2_borrowed_link_before_io(self):
        link=FakeBorrowedLink();link.allow_user3=False
        with self.assertRaises(ValueError):SysMailboxProbe(link)
        self.assertEqual(link.calls,[])

    def test_build_read_frame_rejects_unsupported_fields(self):
        self.assertEqual((build_read_frame(0,1)>>544)&0xf,0xf)
        with self.assertRaises(ValueError):build_read_frame(0x30,1)
        with self.assertRaises(ValueError):build_read_frame(1,1)
        with self.assertRaises(ValueError):build_read_frame(0,0)

    def test_bad_baseline_magic_reserved_or_error_payload_poison_before_any_request(self):
        for base in (response(1,magic=0),response(1,reserved=1),response(1,status=2,payload=1),response(1,status=0,payload=1<<40)):
            link=FakeBorrowedLink(baseline=base);probe=SysMailboxProbe(link,timeout=0.1)
            with self.assertRaises(Exception):probe.read_register(0)
            self.assertFalse([v for v,b,i in link.calls if not i and v])
            before=len(link.calls)
            with self.assertRaises(Exception):probe.read_register(0)
            self.assertEqual(len(link.calls),before)

    def test_valid_error_baseline_is_reseeded_for_readonly_diagnostic(self):
        link=FakeBorrowedLink({0x00:RKPR},baseline=response(0x5100,status=2,payload=0))
        probe=SysMailboxProbe(link,timeout=0.1)
        self.assertEqual(probe.read_register(0),RKPR)
        sent=[v for v,b,i in link.calls if not i and v]
        self.assertEqual(len(sent),1)
        self.assertEqual((sent[0]>>556)&0xffff,0x5101)
        self.assertTrue(all(((frame>>548)&0xff)==1 for frame in sent))
        self.assertFalse(link.closed)

    def test_identity_and_abi_failures_poison_without_retry(self):
        for values,expected_reads in (({0x00:0x1234},1),({0x00:RKPR,0x04:0x20000},2),({0x00:RKPR,0x04:ABI,0x1c:0x123},3)):
            link=FakeBorrowedLink(values);probe=SysMailboxProbe(link,timeout=0.1)
            with self.assertRaises(Exception):probe.probe()
            sent=[v for v,b,i in link.calls if not i and v]
            self.assertEqual(len(sent),expected_reads)
            before=len(link.calls)
            with self.assertRaises(Exception):probe.probe()
            self.assertEqual(len(link.calls),before)

    def test_error_or_malformed_payload_poison_without_retry(self):
        for status,payload,bad_magic,reserved in ((2,0,MAGIC,0),(0,1<<40,MAGIC,0),(0,0,0,0),(0,0,MAGIC,1)):
            link=FakeBorrowedLink({0x00:RKPR},bad_status=status,bad_payload=payload,bad_magic=bad_magic,reserved=reserved)
            probe=SysMailboxProbe(link,timeout=0.1)
            with self.assertRaises(Exception):probe.read_register(0)
            count=sum(1 for v,b,i in link.calls if not i and v)
            self.assertEqual(count,1)
            before=len(link.calls)
            with self.assertRaises(Exception):probe.read_register(0)
            self.assertEqual(len(link.calls),before)

    def test_stale_reply_timeout_sends_no_retry(self):
        link=FakeBorrowedLink(baseline=response(4),stale=True)
        probe=SysMailboxProbe(link,timeout=0.01,sleep=lambda _delay:None)
        with self.assertRaises(Exception):probe.read_register(0)
        sends=[v for v,b,i in link.calls if not i and v]
        self.assertEqual(len(sends),1)
        before=len(link.calls)
        with self.assertRaises(Exception):probe.read_register(0)
        self.assertEqual(len(link.calls),before)

    def test_transport_deadline_failure_poison_does_not_retry(self):
        link=FakeBorrowedLink(baseline=response(12),timeout=True)
        probe=SysMailboxProbe(link,timeout=0.1)
        with self.assertRaises(TimeoutError):probe.read_register(0)
        sent=[v for v,b,i in link.calls if not i and v]
        self.assertEqual(len(sent),1)
        before=len(link.calls)
        with self.assertRaises(Exception):probe.read_register(0)
        self.assertEqual(len(link.calls),before)

    def test_actual_tcl_clean_exit_marker_matches_optin_mode(self):
        text=(ROOT/'fpga/host/native_rpc.tcl.in').read_text()
        start=text.index('if {$owner ne ""} {native_drop $owner}')
        tail=text[start:]
        tclsh=shutil.which('tclsh')
        self.assertIsNotNone(tclsh)
        for allow_user3,expected in ((0,'PASS_NATIVE_USER2_BRIDGE_CLEAN_EXIT'),
                                     (1,'PASS_NATIVE_USER3_ENABLED_BRIDGE_CLEAN_EXIT')):
            setup=(f'set allow_user3 {allow_user3}\nset owner \"\"\nset listener \"\"\n'
                   'set raw 0\nset target_open 0\nset connected 0\nset manager 0\n'
                   'set failed 0\nset cleanup_failed 0\nset problem \"\"\n')
            result=subprocess.run([tclsh],input=setup+tail,text=True,capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stderr,'')
            self.assertEqual(result.stdout,expected+'\n')

    def test_tcl_dispatch_user3_whitelist_without_tap_reset_in_optin_branch(self):
        text=(ROOT/'fpga/host/native_rpc.tcl.in').read_text()
        self.assertIn('set allow_user3 @ALLOW_USER3@',text)
        self.assertIn('native_ir_allowed',text);self.assertIn('native_dr_allowed',text)
        branch=text.split('if {$allow_user3 eq "0"} {',1)[1]
        default,optin=branch.split('} else {',1)
        optin=optin.split('set listener [socket',1)[0]
        self.assertNotIn('run_state_hw_jtag RESET',optin)
        self.assertIn('run_state_hw_jtag RESET',default)
        self.assertIn('scan_ir_hw_jtag 6 -tdi 22',text)
        tclsh=shutil.which('tclsh')
        self.assertIsNotNone(tclsh)
        def extract(name):
            start=text.index('proc '+name+' ')
            sig_end=text.index('{',start)
            args_end=text.index('}',sig_end)
            body_open=text.index('{',args_end)
            depth=0;end=None
            for i in range(body_open,len(text)):
                if text[i]=='{':depth+=1
                elif text[i]=='}':
                    depth-=1
                    if depth==0:end=i+1;break
            return text[start:end]
        procs=extract('native_ir_allowed')+'\n'+extract('native_dr_allowed')+'\n'
        test='''
puts [native_ir_allowed 0 6 9]
puts [native_ir_allowed 0 6 3]
puts [native_ir_allowed 0 6 34]
puts [native_ir_allowed 1 6 34]
puts [native_ir_allowed 1 5 34]
puts [native_dr_allowed 0 3 640]
puts [native_dr_allowed 0 34 640]
puts [native_dr_allowed 1 34 640]
puts [native_dr_allowed 1 34 32]
'''
        result=subprocess.run([tclsh],input=procs+test,text=True,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stderr,'')
        self.assertEqual(result.stdout,'1\n1\n0\n1\n0\n1\n0\n1\n0\n')

if __name__=='__main__':unittest.main()
