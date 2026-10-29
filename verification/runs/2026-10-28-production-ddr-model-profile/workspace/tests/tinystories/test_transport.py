"""Dual-namespace host controls with a numeric TAP fixture, no network/RTL."""
import os
import tempfile
import unittest
from unittest.mock import patch

from tools.host.transport import IDCODE, MAGIC, ProtocolError
from tools.tinystories.transport import DualRawTransport


class Link:
    host, port, actual_period_ns = 'mock-dual', 3741, 167
    def __init__(self):
        self.ir = 0
        self.response = MAGIC << 536
        self.closed = False
        self.commands = []
        self.registers = {0:0x524b4557,4:0x10000,8:16,0x100:0x524b434d,0x104:0x10000,0x108:16}
        self.memory = {}
        self.fields = {0:0,0x100:0}
    def reset(self, **kwargs):
        self.ir = 0
    def scan(self, value, bits=640, *, ir=False, **kwargs):
        if ir:
            self.ir = value
            return 0
        if self.ir == 9:
            return IDCODE
        previous = self.response
        if not value:
            return previous
        op, address, data, seq = value>>548&255, value>>512&0xffffffff, value&((1<<512)-1), value>>556&65535
        self.commands.append((op,address,data))
        result = 0
        if op == 1:
            result = self.registers.get(address,0)
        elif op == 2:
            base, offset = address&0x100, address&0xff
            self.registers[address] = data
            if offset in (0x10,0x14,0x18):
                self.fields[base] |= 1 << ((offset-0x10)//4)
                self.registers[base+8] = self.fields[base]<<8|16|int(self.fields[base]==7)
            elif offset == 0x0c and data == 1:
                self.registers[base+8] = 0x714
                self.registers[base+0x1c] = self.registers[base+0x18]
                self.registers[base+0x20] = 1 if base else 2
                self.registers[base+0x24] = 0
            elif offset == 0x0c and data == 2:
                self.fields[base] = 0
                self.registers[base+8] = 16
        elif op == 3:
            result = int.from_bytes(self.memory.get(address, bytes(64)), 'little')
        elif op == 4:
            self.memory[address] = data.to_bytes(64, 'little')
        self.response = MAGIC<<536|seq<<520|result
        return previous
    def close(self):
        self.closed = True


class DualTransportTests(unittest.TestCase):
    def owner(self, link, **kwargs):
        return DualRawTransport(link.host,link.port,link=link,**kwargs)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'OTPU_RUN_DIR':self.directory.name})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def test_both_identities_precede_every_write(self):
        link = Link()
        with self.owner(link) as owner:
            self.assertEqual(link.commands, [(1,0,0),(1,4,0),(1,0x100,0),(1,0x104,0)])
            self.assertEqual(owner.profile, 'ew')
            self.assertFalse(any(op in (2,4) for op,_,_ in link.commands))

    def test_wrong_cmac_identity_or_abi_closes_without_writing(self):
        for offset in (0x100,0x104):
            link = Link();link.registers[offset] = 0
            with self.subTest(offset=offset), self.assertRaises(ProtocolError):
                self.owner(link)
            self.assertTrue(link.closed)
            self.assertFalse(any(op in (2,4) for op,_,_ in link.commands))

    def test_raw_jobs_switch_namespace_only_after_ack(self):
        link = Link()
        with self.owner(link) as owner:
            owner.select_profile('cmac')
            owner.submit(0x100e0000,45,0x11112222)
            before = len(link.commands)
            with self.assertRaises(ValueError):
                owner.select_profile('ew')
            self.assertEqual(len(link.commands), before)
            result = owner.poll_result()
            self.assertEqual((result.tag,result.completed_tasks,result.error_code),(0x11112222,1,0))
            with self.assertRaises(ValueError):
                owner.select_profile('ew')
            owner.ack_success()
            owner.select_profile('ew')
            owner.submit(0x100e0000,22,0x33334444)
            self.assertEqual(owner.poll_result().completed_tasks, 2)
            owner.ack_success()
        writes = [(a,d) for op,a,d in link.commands if op==2]
        self.assertIn((0x114,45),writes)
        self.assertIn((0x10c,1),writes)
        self.assertIn((0x014,22),writes)
        self.assertIn((0x00c,1),writes)

    def test_byte_uploads_do_not_translate_or_rewrite_payloads(self):
        link = Link();raw = bytes(range(64))
        with self.owner(link) as owner:
            owner.select_profile('cmac')
            self.assertEqual(owner.upload_commands(0x100e0000,raw), 8)
            self.assertEqual(owner.mem_read(0x100e0000,64),raw)
        self.assertEqual(link.memory, {0x100e0000:raw})

    def test_peer_busy_or_staged_descriptor_poison_without_reset(self):
        for offset,value in ((8,0x110),(0x108,0)):
            link=Link()
            with self.owner(link) as owner:
                link.registers[offset]=value
                with self.assertRaises(ProtocolError):
                    owner.select_profile('cmac')
                self.assertEqual(owner.profile,'ew')
                with self.assertRaises(ProtocolError):
                    owner.mem_write(0x10000000,bytes(64))
            self.assertFalse(any(op==2 for op,_,_ in link.commands))

    def test_unknown_profiles_and_registers_fail_locally(self):
        link=Link()
        with self.owner(link) as owner:
            before=len(link.commands)
            for profile in ('matmul','fp32',None,1):
                with self.assertRaises(ValueError):owner.select_profile(profile)
            with self.assertRaises(ValueError):owner.reg_write(0x100,1)
            with self.assertRaises(ValueError):owner.reg_read(0x108)
            self.assertEqual(len(link.commands),before)

    def test_both_namespace_probes_share_the_initialization_deadline(self):
        class Clock:
            now=0.0
            def __call__(self):return self.now
            def sleep(self, amount):self.now+=amount
        clock=Clock()
        class SlowLink(Link):
            def scan(self,value,bits=640,*,ir=False,**kwargs):
                if bits==640 and value:
                    address=value>>512&0xffffffff
                    clock.now+=0.7 if address==0x100 else 0.2
                return super().scan(value,bits,ir=ir,**kwargs)
        link=SlowLink()
        with self.assertRaises(TimeoutError):
            self.owner(link,timeout=1.0,clock=clock,sleep=clock.sleep)
        self.assertTrue(link.closed)
        self.assertFalse(any(op in (2,4) for op,_,_ in link.commands))


if __name__=='__main__':
    unittest.main()
