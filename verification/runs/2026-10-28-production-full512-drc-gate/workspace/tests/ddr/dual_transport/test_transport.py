"""Wire-only tests for the RKAD/RKCD USER2 namespace owner; no TCP/hardware."""
import os
import socket
import tempfile
import unittest
from unittest.mock import patch

from tools.ddr.dual_transport import DualDdrRawTransport
from tools.host.transport import (ABI_VERSION, DeviceBusy, DeviceLock, IDCODE,
                                  MAGIC, ProtocolError)

RKAD_ID=0x524B4144
RKCD_ID=0x524B4344


class WireLink:
    """Small 640-bit USER2 endpoint fake with two independent CSR spaces."""
    host,port,actual_period_ns='mock-dual-ddr',3741,167
    def __init__(self, *, idcode=IDCODE):
        self.idcode=idcode;self.ir=0;self.closed=False;self.commands=[]
        self.response=MAGIC<<536
        self.registers={0:RKAD_ID,4:ABI_VERSION,8:0x10,
                        0x100:RKCD_ID,0x104:ABI_VERSION,0x108:0x10}
        self.fields={0:0,0x100:0};self.memory={};self.result_tag={0:0,0x100:0}
        self.result_tasks={0:1,0x100:1};self.result_error={0:0,0x100:0}
        self.ack_ready={0:True,0x100:True}
    def reset(self,**kwargs): self.ir=0
    def scan(self,value,bits=640,*,ir=False,**kwargs):
        if ir:
            self.ir=value
            return 0
        if self.ir==9: return self.idcode
        previous=self.response
        if not value:return previous
        op=value>>548&255;address=value>>512&0xffffffff
        data=value&((1<<512)-1);seq=value>>556&0xffff
        self.commands.append((op,address,data,seq))
        base=address&0x100;offset=address&0xff
        result=0
        if op==1:
            result=self.registers.get(address,0)
        elif op==2:
            self.registers[address]=data
            if offset in (0x10,0x14,0x18):
                bit={0x10:1,0x14:2,0x18:4}[offset]
                self.fields[base]|=bit
                self.registers[base+8]=(self.fields[base]<<8)|0x10|int(self.fields[base]==7)
            elif offset==0x0c and data==1:
                self.result_tag[base]=self.registers[base+0x18]
                self.registers[base+0x1c]=self.result_tag[base]
                self.registers[base+0x20]=self.result_tasks[base]
                self.registers[base+0x24]=self.result_error[base]
                # Completed result retained; general memory-ready is clear.
                self.registers[base+8]=0x704
            elif offset==0x0c and data==2:
                self.fields[base]=0
                self.registers[base+8]=0x10 if self.ack_ready[base] else 0
        elif op==3:
            result=int.from_bytes(self.memory.get(address,bytes(64)),'little')
        elif op==4:
            self.memory[address]=data.to_bytes(64,'little')
        self.response=MAGIC<<536|seq<<520|result
        return previous
    def close(self): self.closed=True


class DualDdrTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='rknpu-dual-ddr-transport-')
        self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,{'OTPU_RUN_DIR':self.temp.name});env.start();self.addCleanup(env.stop)
        tcp=patch.object(socket,'create_connection',side_effect=AssertionError('TCP must not be opened'))
        tcp.start();self.addCleanup(tcp.stop)
    def owner(self,link=None):
        link=link or WireLink()
        owner=DualDdrRawTransport(link.host,link.port,timeout=1,link=link)
        self.addCleanup(owner.close)
        return owner,link
    @staticmethod
    def ops(link,opcode=None):
        return [c for c in link.commands if opcode is None or c[0]==opcode]

    def test_four_identity_abi_reads_precede_any_write(self):
        owner,link=self.owner()
        self.assertEqual([(op,a) for op,a,_,_ in link.commands],
                         [(1,0),(1,4),(1,0x100),(1,0x104)])
        self.assertEqual(owner.profile,'ew')
        self.assertFalse(any(op in (2,3,4) for op,_,_,_ in link.commands))

    def test_reject_wrong_tap_or_either_namespace_identity_and_release_lock(self):
        cases=(('tap',lambda x:setattr(x,'idcode',0xFFFFFFFF)),
               ('rkad-id',lambda x:x.registers.__setitem__(0,0x524B4557)),
               ('rkad-abi',lambda x:x.registers.__setitem__(4,ABI_VERSION+1)),
               ('old-rkcm-id',lambda x:x.registers.__setitem__(0x100,0x524B434D)),
               ('cmac-abi',lambda x:x.registers.__setitem__(0x104,ABI_VERSION+1)))
        for name,mutate in cases:
            with self.subTest(name=name):
                link=WireLink();mutate(link)
                with self.assertRaises(ProtocolError):DualDdrRawTransport(link.host,link.port,timeout=1,link=link)
                self.assertTrue(link.closed)
                self.assertTrue(all(op==1 for op,_,_,_ in link.commands))
                self.assertFalse(any(op in (2,3,4) for op,_,_,_ in link.commands))
                lock=DeviceLock(link.host,link.port);lock.release()

    def test_ew_cmac_ew_switch_uses_real_csrs_and_preserves_raw_bo_and_amounts(self):
        owner,link=self.owner();owner.select_profile('cmac')
        raw=bytes((i*13+7)&255 for i in range(72));addr=0x100E0000
        self.assertEqual(owner.upload_commands(addr,raw),9)
        self.assertEqual(owner.mem_read(addr,len(raw)),raw)
        owner.submit(addr,45,0xC0C0)
        result=owner.poll_result(timeout=1)
        self.assertEqual((result.tag,result.completed_tasks,result.error_code),(0xC0C0,1,0))
        owner.ack_success();self.assertEqual(owner.reg_read(8),0x10)
        owner.select_profile('ew');self.assertEqual(owner.reg_read(8),0x10)
        owner.submit(0x100D0000,35,0xE0E0)
        result=owner.poll_result(timeout=1)
        self.assertEqual((result.tag,result.completed_tasks,result.error_code),(0xE0E0,1,0))
        owner.ack_success()
        writes=[(a,d) for op,a,d,_ in link.commands if op==2]
        for pair in ((0x110,addr),(0x114,45),(0x118,0xC0C0),(0x10c,1),(0x10c,2),
                     (0x010,0x100D0000),(0x014,35),(0x018,0xE0E0),(0x00c,1),(0x00c,2)):
            self.assertIn(pair,writes)
        self.assertEqual(link.memory[addr],raw[:64])
        self.assertEqual(link.memory[addr+64][:8],raw[64:])
        self.assertIn((1,0x100,0),[(op,a,d) for op,a,d,_ in link.commands])
        self.assertIn((1,0,0),[(op,a,d) for op,a,d,_ in link.commands])
        self.assertEqual(link.registers[8],0x10);self.assertEqual(link.registers[0x108],0x10)

    def test_owned_success_read_is_allowed_but_memory_write_and_profile_switch_wait_for_ack(self):
        owner,link=self.owner();owner.submit(0x10000000,35,0xA55A)
        result=owner.poll_result(timeout=1)
        self.assertEqual(owner.reg_read(8),0x704)
        before_ram=[c for c in link.commands if c[0] in (3,4)]
        self.assertEqual(owner.mem_read(0x10000000,8),bytes(8))
        after_read=[c for c in link.commands if c[0] in (3,4)]
        self.assertGreater(len(after_read),len(before_ram))
        before=len(link.commands)
        with self.assertRaises(DeviceBusy):owner.mem_write(0x10000000,b'blocked')
        after_blocked_memwrite=len(link.commands)
        with self.assertRaises(DeviceBusy):owner.reg_write(0x10,0x10000100)
        with self.assertRaises(ValueError):owner.select_profile('cmac')
        self.assertEqual(len(link.commands),after_blocked_memwrite)
        self.assertEqual(sum(op==2 for op,_,_,_ in link.commands),sum(op==2 for op,_,_,_ in link.commands[:before]))
        # A peer-busy view must not permit a namespace change while this result is owned.
        link.registers[0x108]=0x40
        with self.assertRaises(ValueError):owner.select_profile('cmac')
        # The rejected memory write queried fresh health once before refusing;
        # later descriptor/profile attempts must add no further wire commands.
        self.assertEqual([(op,a,d) for op,a,d,_ in link.commands[before:]],[(1,8,0)])
        self.assertEqual(len(link.commands),after_blocked_memwrite)
        link.registers[0x108]=0x10
        owner.ack_success()
        self.assertEqual(owner.reg_read(8),0x10)

    def test_staged_current_descriptor_blocks_switch_and_poisons_without_writes(self):
        owner,link=self.owner()
        link.registers[8]=0x110
        before=len(link.commands)
        with self.assertRaises(ProtocolError):owner.select_profile('cmac')
        self.assertTrue(owner._failed);self.assertEqual(len(link.commands),before+1)
        with self.assertRaises(ProtocolError):owner.reg_read(8)
        self.assertFalse(any(op==2 for op,_,_,_ in link.commands))

    def test_peer_staged_result_or_fault_blocks_switch_and_poisons(self):
        for status in (0x110,0x704,0x20,0x40):
            with self.subTest(peer_status=hex(status)):
                owner,link=self.owner();link.registers[0x108]=status
                with self.assertRaises(ProtocolError):owner.select_profile('cmac')
                self.assertEqual(owner.profile,'ew');self.assertTrue(owner._failed)
                self.assertFalse(any(op==2 for op,_,_,_ in link.commands))
                owner.close()

    def test_identity_change_detected_on_profile_switch_poisons_before_write(self):
        owner,link=self.owner();link.registers[0x100]=0x524B434D
        before=len(link.commands)
        with self.assertRaises(ProtocolError):owner.select_profile('cmac')
        self.assertTrue(owner._failed)
        self.assertEqual([a for op,a,_,_ in link.commands[before:] if op==1],[8,0x100])
        self.assertFalse(any(op==2 for op,_,_,_ in link.commands))

    def test_invalid_profile_register_offset_and_control_value_fail_before_wire(self):
        owner,link=self.owner();before=len(link.commands)
        for profile in ('matmul','fp32',None,1):
            with self.assertRaises(ValueError):owner.select_profile(profile)
        for offset in (0x0c,0x108,0x28):
            with self.assertRaises(ValueError):owner.reg_read(offset)
        for offset,value in ((0x20,1),(0x0c,0),(0x0c,3),(0x1c,0)):
            with self.assertRaises(ValueError):owner.reg_write(offset,value)
        self.assertEqual(len(link.commands),before)

    def test_cached_cmac_success_late_zero_code_fault_blocks_read_and_ack(self):
        owner,link=self.owner();owner.select_profile('cmac')
        owner.submit(0x10000000,45,0xCACE);result=owner.poll_result(timeout=1)
        self.assertEqual(result.error_code,0);self.assertIs(owner._result,result)
        before_read64=sum(op==3 for op,_,_,_ in link.commands)
        link.registers[0x108]=0x704|0x20;link.registers[0x124]=0
        with self.assertRaises(ProtocolError):owner.mem_read(0x10000000,8)
        self.assertTrue(owner._failed)
        self.assertEqual(sum(op==3 for op,_,_,_ in link.commands),before_read64)
        ack_count=sum(op==2 and a==0x10c and d==2 for op,a,d,_ in link.commands)
        with self.assertRaises(ProtocolError):owner.ack_success()
        self.assertEqual(sum(op==2 and a==0x10c and d==2 for op,a,d,_ in link.commands),ack_count)

    def test_ack_without_memory_ready_poisons_every_later_step(self):
        owner,link=self.owner();owner.select_profile('cmac')
        link.ack_ready[0x100]=False
        owner.submit(0x10000000,45,0xBAD0);owner.poll_result(timeout=1)
        with self.assertRaises(ProtocolError):owner.ack_success()
        self.assertTrue(owner._failed)
        count=len(link.commands)
        for op in (lambda:owner.reg_read(8),lambda:owner.mem_read(0x10000000,8),
                   lambda:owner.mem_write(0x10000000,b'x'),lambda:owner.select_profile('ew')):
            with self.assertRaises(ProtocolError):op()
        self.assertEqual(len(link.commands),count)
        self.assertEqual(link.registers[0x108],0)


if __name__=='__main__':unittest.main()
