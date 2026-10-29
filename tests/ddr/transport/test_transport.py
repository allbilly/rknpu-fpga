"""Wire-only mock controls for explicit RKAD DDR USER2 admission.

Reuse the existing host Clock/Tap/FakeSocket. No TCP connection, board, or
hardware is contacted; result-memory behavior is only the existing Tap mock.
"""
import importlib.util
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('rknpu_host_transport_fakes',ROOT/'tests/host/test_transport.py')
host_fakes=importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_fakes)
Clock,Tap,FakeSocket=host_fakes.Clock,host_fakes.Tap,host_fakes.FakeSocket
from tools.ddr.transport import DdrJtagTransport, RKAD_ID
from tools.host.transport import ABI_VERSION, IDCODE, DeviceBusy, DeviceLock, JobError, ProtocolError


class RkadTap(Tap):
    """Existing host TAP with explicit RKAD status and delayed completion."""
    def __init__(self, retained_sequence=0, *, initial_status=0x10,
                 ready_after_status_reads=None, completion_flags=0,
                 ack_release_memory=True):
        super().__init__(retained_sequence=retained_sequence)
        self.registers[0]=RKAD_ID
        self.registers[4]=ABI_VERSION
        self.registers[8]=initial_status
        self.status_reads=0
        self.ready_after_status_reads=ready_after_status_reads
        self.completion_flags=completion_flags
        self.ack_release_memory=ack_release_memory
        self.job_tag_value=None
        self.job_error=0

    def execute(self, frame):
        opcode=frame >> 548 & 255
        address=frame >> 512 & 0xFFFFFFFF
        if opcode==1 and address==8:
            self.status_reads+=1
            if (not self.job_pending and self.ready_after_status_reads is not None and
                    not self.registers[8]&16 and self.status_reads>=self.ready_after_status_reads):
                self.registers[8]=16
            if self.job_pending and self.job_delay==0:
                # Successful/fault result remains owned after completion. Bit2
                # is result-valid, bit4 (general memory ready) is deliberately
                # clear, and staged descriptor fields remain visible in 8:10.
                self.job_pending=False
                self.registers[8]=0x700 | 0x4 | self.completion_flags
                self.registers[0x1C]=self.registers[0x18] ^ int(self.wrong_tag)
                self.registers[0x20]=self.job_tasks
                self.registers[0x24]=self.job_error
        ack = opcode==2 and address==0x0C and (frame & ((1<<512)-1))==2
        super().execute(frame)
        # Deliberate bad-endpoint control: ACK clears fields/result but fails
        # to restore general memory-ready bit4.
        if ack and not self.ack_release_memory:
            self.registers[8] &= ~16


class DdrTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='rknpu-ddr-transport-test-')
        self.addCleanup(self.temp.cleanup)
        env=patch.dict(os.environ,{'OTPU_RUN_DIR':self.temp.name});env.start();self.addCleanup(env.stop)
        network=patch.object(socket,'create_connection',side_effect=AssertionError('TCP must not be opened'))
        network.start();self.addCleanup(network.stop)

    def make_link(self,tap,*,period=167):
        sock=FakeSocket(tap,period=period)
        link=__import__('tools.host.transport',fromlist=['Xvc']).Xvc(sock=sock)
        return link,sock

    def owner(self,tap,*,timeout=1.0,clock=None,period=167):
        clock=clock or Clock();link,sock=self.make_link(tap,period=period)
        owner=DdrJtagTransport(timeout=timeout,link=link,clock=clock,sleep=clock.sleep)
        self.addCleanup(owner.close)
        return owner,tap,sock,clock

    @staticmethod
    def ram_ops(tap):return [x for x in tap.commands if x[0] in (3,4)]

    def test_rkad_abi_idcode_and_no_write_before_identity(self):
        for failure in ('tap','rkew_id','abi'):
            tap=RkadTap()
            if failure=='tap':tap.idcode=0xFFFFFFFF
            elif failure=='rkew_id':tap.registers[0]=0x524B4557
            else:tap.registers[4]=ABI_VERSION+1
            link,sock=self.make_link(tap)
            with self.subTest(failure=failure),self.assertRaises(ProtocolError):
                DdrJtagTransport(timeout=1,link=link,clock=Clock(),sleep=Clock().sleep)
            self.assertTrue(sock.closed)
            self.assertTrue(all(op==1 for op,_,_,_ in tap.commands))
            self.assertFalse(any(op in (2,3,4) for op,_,_,_ in tap.commands))
            # Constructor rejection releases the exclusive lifetime lock.
            lock=DeviceLock('localhost',3721);lock.release()

    def test_wait_memory_ready_uses_status_bit4_not_can_submit_and_poisons_timeout(self):
        tap=RkadTap(initial_status=0,ready_after_status_reads=4)
        clock=Clock();owner,tap,_,_=self.owner(tap,clock=clock)
        status=owner.wait_memory_ready(timeout=1)
        self.assertEqual(status,16)
        self.assertFalse(status&1)  # can_submit is not the memory readiness gate
        self.assertEqual(tap.fields,0)
        self.assertFalse(any(op==2 for op,_,_,_ in tap.commands))
        owner.close()

        tap=RkadTap(initial_status=1,ready_after_status_reads=None)  # can_submit only
        clock=Clock();owner,tap,_,_=self.owner(tap,clock=clock)
        before=len(tap.commands)
        with self.assertRaises(TimeoutError):owner.wait_memory_ready(timeout=0.025)
        self.assertGreater(clock.now,0)
        self.assertTrue(owner._failed)
        self.assertFalse(any(op in (2,3,4) for op,_,_,_ in tap.commands[before:]))
        with self.assertRaises(ProtocolError):owner.reg_read(8)
        owner.close()

        # A latched fault, even with pending cause code zero, is an immediate
        # failure and must not be confused with uninitialized memory timeout.
        tap=RkadTap(initial_status=0x20,ready_after_status_reads=None)
        tap.registers[0x24]=0
        clock=Clock();owner,tap,_,_=self.owner(tap,clock=clock)
        with self.assertRaises(ProtocolError):owner.wait_memory_ready(timeout=1)
        self.assertEqual(clock.now,0.0)
        self.assertTrue(owner._failed)
        self.assertFalse(any(op in (2,3,4) for op,_,_,_ in tap.commands))

    def test_memory_before_initialization_refuses_without_ram_and_wait_can_retry(self):
        tap=RkadTap(initial_status=0,ready_after_status_reads=4)
        owner,tap,_,_=self.owner(tap)
        before=list(self.ram_ops(tap))
        with self.assertRaises(DeviceBusy):owner.mem_read(0x10000000,8)
        with self.assertRaises(DeviceBusy):owner.mem_write(0x10000000,b'not-yet-ready')
        self.assertEqual(self.ram_ops(tap),before)
        self.assertFalse(owner._failed)
        self.assertEqual(owner.wait_memory_ready(timeout=1),16)
        self.assertFalse(owner._failed)

    def test_pending_success_allows_owned_read_blocks_write_until_ack_two_roundtrips(self):
        tap=RkadTap(initial_status=16,retained_sequence=65534)
        tap.memory[0x10000000]=bytes((i+17)&255 for i in range(64))
        owner,tap,_,_=self.owner(tap,clock=Clock())
        self.assertEqual([(op,addr,seq) for op,addr,_,seq in tap.commands[:2]],[(1,0,65535),(1,4,1)])
        for tag in (0xA111,0xA222):
            self.assertTrue(owner.wait_memory_ready(timeout=1)&16)
            tap.job_delay=1
            address=0x10000000+(tag&0xFF)*0x100
            # Seed the fake memory after the aligned descriptor address is chosen.
            tap.memory[address]=bytes((i*3+tag)&255 for i in range(64))
            owner.submit(address,35,tag)
            result=owner.poll_result(timeout=1)
            self.assertEqual((result.tag,result.completed_tasks,result.error_code),(tag,2,0))
            status=owner.reg_read(8)
            self.assertEqual(status,0x704)
            self.assertFalse(status&16)
            self.assertTrue(status&4)
            self.assertEqual(status&0x700,0x700)
            expected=tap.memory[address][:8]
            self.assertEqual(owner.mem_read(address,8),expected)
            before=list(self.ram_ops(tap))
            with self.assertRaises(DeviceBusy):owner.mem_write(address,b'\xCC')
            self.assertEqual(self.ram_ops(tap),before)
            self.assertEqual(owner.poll_result(timeout=1),result)
            owner.ack_success()
            self.assertTrue(owner.reg_read(8)&16)
            self.assertIsNone(owner._active_tag)
        writes=[(addr,data) for op,addr,data,_ in tap.commands if op==2]
        self.assertEqual([addr for addr,_ in writes].count(0x0C),4)  # two submit+ACK pairs
        self.assertEqual([data for addr,data in writes if addr==0x0C],[1,2,1,2])

    def test_foreign_pending_result_cannot_be_read_or_written(self):
        tap=RkadTap(initial_status=0x704)
        owner,tap,_,_=self.owner(tap)
        before=list(self.ram_ops(tap))
        with self.assertRaises(DeviceBusy):owner.mem_read(0x10000000,8)
        with self.assertRaises(DeviceBusy):owner.mem_write(0x10000000,b'foreign')
        self.assertEqual(self.ram_ops(tap),before)
        self.assertIsNone(owner._active_tag)
        self.assertIsNone(owner._result)
        self.assertFalse(owner._failed)

    def test_code_zero_pending_fault_is_failure_poison_and_never_acked(self):
        tap=RkadTap(initial_status=16,completion_flags=0x28)
        tap.job_error=0
        owner,tap,_,_=self.owner(tap)
        owner.wait_memory_ready(timeout=1)
        tap.job_delay=0
        owner.submit(0x10000000,35,0xC0DE)
        with self.assertRaises(JobError) as error:owner.poll_result(timeout=1)
        self.assertEqual((error.exception.result.error_code,error.exception.result.tag),(0,0xC0DE))
        self.assertTrue(owner._failed)
        self.assertFalse(any(op==2 and addr==0x0C and data==2 for op,addr,data,_ in tap.commands))
        with self.assertRaises(ProtocolError):owner.ack_success()

    def test_fresh_health_fault_revokes_cached_success_read_permission(self):
        tap=RkadTap(initial_status=16)
        owner,tap,_,_=self.owner(tap)
        owner.wait_memory_ready(timeout=1)
        owner.submit(0x10000000,35,0xF17E)
        result=owner.poll_result(timeout=1)
        self.assertEqual(result.error_code,0)
        self.assertIs(owner._result,result)
        self.assertEqual(owner.reg_read(8),0x704)
        before_ram=list(self.ram_ops(tap))

        # Keep a previously validated success cached while a later poll sees
        # a new health fault with code zero. That fresh fault must revoke the
        # owned-read exception before any new READ64 is sent.
        tap.registers[8]=0x704|0x28
        tap.registers[0x24]=0
        with self.assertRaises(ProtocolError):owner.mem_read(0x10000000,8)
        self.assertTrue(owner._failed)
        self.assertEqual(self.ram_ops(tap),before_ram)
        ack_count=sum(op==2 and addr==0x0C and data==2 for op,addr,data,_ in tap.commands)
        with self.assertRaises(ProtocolError):owner.ack_success()
        self.assertEqual(sum(op==2 and addr==0x0C and data==2 for op,addr,data,_ in tap.commands),ack_count)

    def test_ack_must_restore_general_memory_ready_before_owner_can_submit_again(self):
        tap=RkadTap(initial_status=16,ack_release_memory=False)
        owner,tap,_,_=self.owner(tap)
        owner.wait_memory_ready(timeout=1)
        owner.submit(0x10000000,35,0xACCE)
        result=owner.poll_result(timeout=1)
        self.assertEqual(result.error_code,0)
        self.assertTrue(tap.registers[8]&4)

        with self.assertRaises(ProtocolError):owner.ack_success()
        self.assertTrue(owner._failed)
        self.assertEqual(tap.registers[8]&0x710,0)  # fields/result cleared; bit4 still low
        acks=sum(op==2 and addr==0x0C and data==2 for op,addr,data,_ in tap.commands)
        commands_before_retry=len(tap.commands)
        with self.assertRaises(ProtocolError):owner.submit(0x10000100,35,0xACCF)
        self.assertEqual(sum(op==2 and addr==0x0C and data==2 for op,addr,data,_ in tap.commands),acks)
        self.assertEqual(len(tap.commands),commands_before_retry)

    def test_unsupported_register_status_and_noncontiguous_upload_fail_closed(self):
        tap=RkadTap(initial_status=16);owner,tap,_,_=self.owner(tap)
        before=len(tap.commands)
        with self.assertRaises(ValueError):owner.reg_read(0x28)
        with self.assertRaises(ValueError):owner.reg_write(0x1C,0x55)
        with self.assertRaises(ValueError):owner.reg_write(0x0C,3)
        self.assertEqual(len(tap.commands),before)
        odd=memoryview(bytearray(range(64)))[::2]
        with self.assertRaises(ValueError):owner.upload_commands(0x10000000,odd)
        self.assertEqual(len(tap.commands),before)
        self.assertFalse(self.ram_ops(tap))
        owner.close()

        tap=RkadTap(initial_status=0x800);owner,tap,_,_=self.owner(tap)
        with self.assertRaises(ProtocolError):owner.wait_memory_ready(timeout=1)
        self.assertTrue(owner._failed)
        self.assertFalse(any(op in (2,3,4) for op,_,_,_ in tap.commands))

    def test_raw_bo_bytes_rmw_neighbors_and_31bit_range_are_preserved(self):
        tap=RkadTap(initial_status=16);owner,tap,_,_=self.owner(tap)
        base=0x10000000
        left=bytes((i*3+1)&255 for i in range(64));right=bytes((i*5+7)&255 for i in range(64))
        tap.memory[base]=left;tap.memory[base+64]=right
        payload=bytes((i*11+9)&255 for i in range(90))
        owner.mem_write(base+3,payload)
        expected0=left[:3]+payload[:61]
        expected1=payload[61:]+right[29:]
        self.assertEqual(tap.memory[base],expected0)
        self.assertEqual(tap.memory[base+64],expected1)
        self.assertEqual(owner.mem_read(base+3,len(payload)),payload)
        raw_bo=bytes((255-i)&255 for i in range(128))
        self.assertEqual(owner.upload_commands(base+0x200,raw_bo),16)
        self.assertEqual(tap.memory[base+0x200],raw_bo[:64])
        self.assertEqual(tap.memory[base+0x240],raw_bo[64:])
        self.assertEqual(owner.mem_read(base+0x200,len(raw_bo)),raw_bo)
        edge=(1<<31)-64;last=bytes((i+23)&255 for i in range(64))
        owner.mem_write(edge,last);self.assertEqual(owner.mem_read(edge,64),last)
        command_count=len(tap.commands)
        with self.assertRaises(ValueError):owner.mem_read(1<<31,1)
        with self.assertRaises(ValueError):owner.mem_write((1<<31)-1,b'xx')
        with self.assertRaises(ValueError):owner.upload_commands((1<<31)-16,b'\0'*24)
        self.assertEqual(len(tap.commands),command_count)


if __name__=='__main__':
    unittest.main()
