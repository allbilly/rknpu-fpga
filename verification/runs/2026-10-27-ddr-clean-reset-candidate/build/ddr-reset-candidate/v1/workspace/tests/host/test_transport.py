"""Wire-level socket/TAP mocks only. Never opens a TCP or hardware connection."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

from tools.host.transport import (ABI_VERSION, FRAME_BITS, IDCODE, MAGIC, RKEW_ID,
                                  DeviceBusy, DeviceLock, JobError, JtagTransport,
                                  MailboxError, ProtocolError, Xvc)

ROOT = Path(__file__).resolve().parents[2]


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def sleep(self, amount): self.now += amount


class Tap:
    def __init__(self, retained_sequence=0):
        self.ir = 0
        self.idcode = IDCODE
        self.response = MAGIC << 536 | retained_sequence << 520
        self.pending = None
        self.delay_polls = 0
        self.stall = False
        self.response_status = 0
        self.corrupt = None
        self.registers = {0: RKEW_ID, 4: ABI_VERSION, 8: 0x10, 0x1C: 0, 0x20: 0, 0x24: 0}
        self.commands, self.scans = [], []
        self.memory = {}
        self.fields = 0
        self.job_pending = False
        self.job_delay = 1
        self.job_error = 0
        self.job_tasks = 2
        self.wrong_tag = False

    def shift(self, nbits, tms, tdi):
        self.scans.append((nbits, tms, tdi))
        if nbits == 6:
            assert tms == 0b011111 and tdi == 0
            self.ir = 0
            return 0
        ir = nbits == 12
        prefix, count = (0b0011, 4) if ir else (0b001, 3)
        bits = 6 if ir else (32 if self.ir == 9 else FRAME_BITS)
        assert nbits == count + bits + 2
        assert tms == prefix | (1 << (count + bits - 1)) | (1 << (count + bits))
        assert tdi & ((1 << count) - 1) == 0 and tdi >> (count + bits) == 0
        value = tdi >> count
        if ir:
            assert value in (9, 3)
            self.ir = value
            return 0
        if self.ir == 9:
            return self.idcode << count
        assert self.ir == 3
        if value:
            assert self.pending is None, 'More than one mailbox request outstanding'
            assert value >> 604 == 0 and value >> 572 == MAGIC
            self.pending = (value, self.delay_polls)
        elif self.pending and not self.stall:
            frame, delay = self.pending
            if delay:
                self.pending = (frame, delay - 1)
            else:
                self.pending = None
                self.execute(frame)
        return self.response << count

    def execute(self, frame):
        data = frame & ((1 << 512) - 1)
        address = frame >> 512 & 0xFFFFFFFF
        strobes = frame >> 544 & 15
        opcode = frame >> 548 & 255
        sequence = frame >> 556 & 65535
        assert strobes == 15 and sequence != 0
        self.commands.append((opcode, address, data, sequence))
        result = 0
        status = self.response_status
        if not status:
            if opcode == 1:
                assert data == 0
                if address == 8 and self.job_pending:
                    if self.job_delay:
                        self.job_delay -= 1
                    else:
                        self.job_pending = False
                        self.registers[8] = 0x714 | (0x28 if self.job_error else 0)
                        self.registers[0x1C] = self.registers[0x18] ^ int(self.wrong_tag)
                        self.registers[0x20] = self.job_tasks
                        self.registers[0x24] = self.job_error
                result = self.registers.get(address, 0)
            elif opcode == 2:
                assert data >> 32 == 0
                if address in (0x10, 0x14, 0x18):
                    self.registers[address] = data
                    self.fields |= 1 << ((address - 0x10) // 4)
                    self.registers[8] = self.fields << 8 | 16 | int(self.fields == 7)
                elif address == 0x0C and data == 1:
                    assert self.fields == 7 and not self.job_pending
                    self.job_pending = True
                    self.registers[8] = 0x752
                elif address == 0x0C and data == 2:
                    assert self.registers[8] & 4 and not self.job_error
                    self.fields = 0
                    self.registers[8] = 16
                    self.registers.update({0x10: 0, 0x14: 0, 0x18: 0})
                else:
                    raise AssertionError('Unexpected register write')
            elif opcode == 3:
                assert data == 0 and address % 64 == 0 and address < 1 << 31
                result = int.from_bytes(self.memory.get(address, bytes(range(64))), 'little')
            elif opcode == 4:
                assert address % 64 == 0 and address < 1 << 31
                self.memory[address] = data.to_bytes(64, 'little')
            else:
                raise AssertionError('Unexpected opcode')
        self.response = MAGIC << 536 | sequence << 520 | status << 512 | result
        if self.corrupt:
            self.response = self.corrupt(self.response)


class FakeSocket:
    def __init__(self, tap=None, *, period=167, info=b'xvcServer_v1.0:2048\n', fragment=3):
        self.tap = tap or Tap()
        self.period, self.info, self.fragment = period, info, fragment
        self.received = bytearray()
        self.sent = []
        self.closed = False
        self.failure = None
        self.padding = False
        self.timeout = None
        self.timeouts = []

    def settimeout(self, value):
        self.timeout = value
        self.timeouts.append(value)

    def elapse(self, clock, seconds):
        """Model a blocking socket call honoring its currently installed timeout."""
        if self.timeout is not None and seconds >= self.timeout:
            clock.sleep(self.timeout)
            raise socket.timeout('mock socket deadline')
        clock.sleep(seconds)

    def sendall(self, data):
        self.sent.append(data)
        if self.failure:
            raise self.failure
        if data == b'getinfo:':
            self.received.extend(self.info)
        elif data[:7] == b'settck:':
            assert len(data) == 11
            self.received.extend(struct.pack('<I', self.period))
        else:
            assert data[:6] == b'shift:'
            bits, = struct.unpack('<I', data[6:10])
            size = (bits + 7) // 8
            assert len(data) == 10 + 2 * size
            tms = int.from_bytes(data[10:10 + size], 'little')
            tdi = int.from_bytes(data[10 + size:], 'little')
            response = self.tap.shift(bits, tms, tdi)
            if self.padding:
                response |= 1 << bits
            self.received.extend(response.to_bytes(size, 'little'))

    def recv(self, size):
        amount = min(size, self.fragment, len(self.received))
        value = bytes(self.received[:amount])
        del self.received[:amount]
        return value

    def close(self): self.closed = True


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rknpu-host-test-')
        self.addCleanup(self.temporary.cleanup)
        self.env = patch.dict(os.environ, {'OTPU_RUN_DIR': self.temporary.name})
        self.env.start(); self.addCleanup(self.env.stop)
        network = patch.object(socket, 'create_connection', side_effect=AssertionError('Network connections forbidden in unit tests'))
        network.start(); self.addCleanup(network.stop)

    def transport(self, tap=None, **kwargs):
        sock = FakeSocket(tap)
        link = Xvc(sock=sock)
        self.addCleanup(link.close)
        clock = Clock()
        owner = JtagTransport(link=link, clock=clock, sleep=clock.sleep, **kwargs)
        self.addCleanup(owner.close)
        return owner, sock.tap, sock, clock

    def test_exact_xvc_clock_negotiation_and_frequency_cap(self):
        for requested, returned, expected in ((6_000_000, 167, 167), (12_000_000, 167, 167),
                                               (3_000_000, 334, 334), (6_000_000, 200, 167), (1, 1_000_000_000, 1_000_000_000)):
            with self.subTest(requested=requested, returned=returned):
                sock = FakeSocket(period=returned, fragment=1)
                link = Xvc(sock=sock, frequency_hz=requested)
                self.assertEqual(sock.sent, [b'getinfo:', b'settck:' + struct.pack('<I', expected)])
                self.assertEqual(link.actual_period_ns, returned)
                self.assertLessEqual(1_000_000_000 / returned, min(requested, 6_000_000))
                link.close()
        for period in (0, 1, 166):
            sock = FakeSocket(period=period)
            with self.subTest(period=period), self.assertRaises(ProtocolError): Xvc(sock=sock)
            self.assertTrue(sock.closed)
            self.assertFalse(any(message.startswith(b'shift:') for message in sock.sent))
        for hz in (0, -1, True, 6.0, float('nan')):
            with self.subTest(hz=hz), self.assertRaises(ValueError): Xvc(sock=FakeSocket(), frequency_hz=hz)

    def test_getinfo_and_scan_lengths_fail_closed(self):
        for info in (b'xvcServer_v1.0:644\n', b'xvcServer_v2.0:2048\n', b'bad\n', b'x' * 257, b'xvcServer_v1.0:4294967296\n'):
            sock = FakeSocket(info=info)
            with self.subTest(info=info), self.assertRaises((ProtocolError, EOFError)): Xvc(sock=sock)
            self.assertTrue(sock.closed)
        link = Xvc(sock=FakeSocket())
        self.addCleanup(link.close)
        before = len(link.sock.sent)
        for args in ((0, 0, 0), (2049, 0, 0), (6, 64, 0), (6, 0, -1)):
            with self.assertRaises(ValueError): link.shift(*args)
        self.assertEqual(len(link.sock.sent), before)

    def test_exact_idcode_user2_frames_and_identity_before_writes(self):
        owner, tap, _, _ = self.transport(Tap(retained_sequence=65534))
        self.assertEqual(tap.scans[:4], [(6, 31, 0), (12, 0b0011 | (1 << 9) | (1 << 10), 9 << 4),
                                        (37, 1 | (1 << 34) | (1 << 35), 0),
                                        (12, 0b0011 | (1 << 9) | (1 << 10), 3 << 4)])
        self.assertEqual([(op, addr, sequence) for op, addr, _, sequence in tap.commands], [(1, 0, 65535), (1, 4, 1)])
        owner.reg_write(0x18, 0x89ABCDEF)
        op, addr, data, seq = tap.commands[-1]
        self.assertEqual((op, addr, data, seq), (2, 0x18, 0x89ABCDEF, 2))
        sent = [tdi >> 3 for bits, _, tdi in tap.scans if bits == 645 and tdi]
        self.assertEqual(sent[-1], 0x89ABCDEF | 0x18 << 512 | 15 << 544 | 2 << 548 | 2 << 556 | MAGIC << 572)

    def test_wrong_tap_or_endpoint_identity_never_writes(self):
        for kind in ('idcode', 'id', 'abi', 'magic'):
            tap = Tap()
            if kind == 'idcode': tap.idcode = 0xFFFFFFFF
            if kind == 'id': tap.registers[0] = 0x4F545055
            if kind == 'abi': tap.registers[4] = 0x00010001
            if kind == 'magic': tap.response = 0
            sock = FakeSocket(tap); link = Xvc(sock=sock)
            with self.subTest(kind=kind), self.assertRaises(ProtocolError): JtagTransport(link=link)
            self.assertTrue(sock.closed)
            self.assertTrue(all(command[0] == 1 for command in tap.commands))
            lock = DeviceLock('localhost', 3721); lock.release()

    def test_bulk_roundtrip_and_edge_only_read_modify_write(self):
        owner, tap, _, _ = self.transport()
        base = 0x10000000
        data = bytes((i * 7) % 256 for i in range(140))
        tap.commands.clear()
        owner.mem_write(base + 3, data)
        traffic = [(op, address) for op, address, _, _ in tap.commands if op in (3, 4)]
        self.assertEqual(traffic, [(3, base), (4, base), (4, base + 64), (3, base + 128), (4, base + 128)])
        self.assertEqual(tap.memory[base][:3], bytes(range(3)))
        self.assertEqual(tap.memory[base + 128][15:], bytes(range(15, 64)))
        self.assertEqual(owner.mem_read(base + 3, len(data)), data)
        owner.mem_write((1 << 31) - 64, b'\xD5' * 64)
        self.assertEqual(owner.mem_read((1 << 31) - 64, 64), b'\xD5' * 64)

    def test_invalid_ranges_values_and_buffers_do_not_send_commands(self):
        owner, tap, _, _ = self.transport()
        before = len(tap.commands)
        for address, size in ((-1, 1), (0, -1), (1 << 31, 1), ((1 << 31) - 1, 2), (True, 1)):
            with self.assertRaises(ValueError): owner.mem_read(address, size)
        for offset, value in ((0, 1), (0x11, 1), (0x18, -1), (0x18, 1 << 32), (0x0C, 3)):
            with self.assertRaises(ValueError): owner.reg_write(offset, value)
        with self.assertRaises(TypeError): owner.mem_write(0, [1, 2])
        with self.assertRaises(TypeError): owner.upload_commands(0, ['ADD'])
        with self.assertRaises(ValueError): owner.mem_write(0, memoryview(bytes(32))[::2])
        with self.assertRaises(ValueError): owner.upload_commands(0, memoryview(bytes(32))[::2])
        for address, raw in ((1, bytes(8)), (0, b'x'), (0, b'')):
            with self.assertRaises(ValueError): owner.upload_commands(address, raw)
        self.assertEqual(owner.mem_read(1 << 31, 0), b'')
        owner.mem_write(1 << 31, b'')
        self.assertEqual(len(tap.commands), before)

    def test_mailbox_errors_poison_and_never_retry(self):
        for status in (2, 3, 4, 5, 6, 7, 0x80):
            with self.subTest(status=status):
                owner, tap, _, _ = self.transport()
                tap.response_status = status
                count = len(tap.commands)
                with self.assertRaises(MailboxError) as error: owner.reg_read(8)
                self.assertEqual(error.exception.status, status)
                self.assertEqual(len(tap.commands), count + 1)
                with self.assertRaises(ProtocolError): owner.reg_read(8)
                self.assertEqual(len(tap.commands), count + 1)
                with self.assertRaises(DeviceBusy): DeviceLock('localhost', 3721)
                owner.close()

    def test_corrupt_response_timeout_and_disconnect_poison(self):
        for corruption in (lambda response: response ^ (1 << 536),
                           lambda response: response | (1 << 568),
                           lambda response: response | (1 << 100)):
            owner, tap, _, _ = self.transport()
            tap.corrupt = corruption
            with self.assertRaises(ProtocolError): owner.reg_read(8)
            with self.assertRaises(ProtocolError): owner.reg_write(0x18, 1)
            owner.close()
        owner, tap, _, clock = self.transport(timeout=0.003)
        tap.stall = True
        before = len(tap.commands)
        with self.assertRaises(TimeoutError): owner.reg_read(8)
        self.assertGreaterEqual(clock.now, 0.003)
        with self.assertRaises(ProtocolError): owner.reg_read(8)
        self.assertEqual(len(tap.commands), before)
        owner.close()
        for failure in (EOFError('disconnected'), socket.timeout('timeout'), OSError('wire error')):
            owner, _, sock, _ = self.transport()
            sock.failure = failure
            with self.assertRaises(type(failure)): owner.reg_read(8)
            self.assertTrue(sock.closed)
            with self.assertRaises(ProtocolError): owner.reg_read(8)
            owner.close()

    def test_xvc_eof_is_fatal_and_padding_is_outside_scan(self):
        sock = FakeSocket(info=b'xvcServer_v1.0:2048')
        with self.assertRaises(EOFError): Xvc(sock=sock)
        self.assertTrue(sock.closed)
        sock = FakeSocket(); link = Xvc(sock=sock); sock.padding = True
        link.reset()
        self.assertFalse(sock.closed)
        link.close()

    def test_injected_link_must_honor_requested_slower_clock(self):
        sock = FakeSocket(); link = Xvc(sock=sock)
        with self.assertRaises(ProtocolError): JtagTransport(link=link, frequency_hz=3_000_000)
        self.assertTrue(sock.closed)

    def test_late_matching_completion_is_not_accepted(self):
        owner, tap, _, clock = self.transport(timeout=0.01)
        execute = tap.execute
        def late(frame):
            execute(frame)
            clock.now += 0.02
        tap.execute = late
        with self.assertRaises(TimeoutError): owner.reg_read(8)
        with self.assertRaises(ProtocolError): owner.reg_read(8)

    def test_fragmented_reply_uses_one_deadline_and_poisons_owner(self):
        owner, tap, sock, clock = self.transport(timeout=0.010)
        sock.fragment = 1
        receive = sock.recv
        def dribble(size):
            sock.elapse(clock, 0.009)
            return receive(size)
        sock.recv = dribble
        before = len(tap.commands); scans_before = len(tap.scans); start = clock.now
        sock.timeouts.clear()
        with self.assertRaises(TimeoutError): owner.reg_read(8)
        self.assertAlmostEqual(clock.now-start, 0.010)
        self.assertAlmostEqual(sock.timeouts[-1], 0.001)
        self.assertTrue(sock.closed)
        # The request was shifted, but its response was not consumed. The mock
        # completes pending requests on a later poll; no such poll may be sent.
        self.assertIsNotNone(tap.pending)
        self.assertEqual(len(tap.commands), before)
        self.assertEqual(len(tap.scans), scans_before+1)
        with self.assertRaises(ProtocolError): owner.reg_read(8)
        with self.assertRaises(DeviceBusy): DeviceLock('localhost', 3721)
        self.assertEqual(len(tap.commands), before)
        self.assertEqual(len(tap.scans), scans_before+1)

    def test_sendall_and_each_receive_share_remaining_budget(self):
        owner, _, sock, clock = self.transport(timeout=0.010)
        send, receive = sock.sendall, sock.recv
        def delayed_send(data):
            sock.elapse(clock, 0.006)
            send(data)
        def delayed_receive(size):
            sock.elapse(clock, 0.003)
            return receive(size)
        sock.sendall, sock.recv = delayed_send, delayed_receive
        start = clock.now
        with self.assertRaises(TimeoutError): owner.reg_read(8)
        self.assertAlmostEqual(clock.now-start, 0.010)
        self.assertTrue(sock.closed)
        with self.assertRaises(ProtocolError): owner.reg_write(0x18, 1)

    def test_negotiation_and_entire_identity_probe_have_global_deadlines(self):
        clock = Clock(); sock = FakeSocket(fragment=1); receive = sock.recv
        def slow_info(size):
            sock.elapse(clock, 0.009)
            return receive(size)
        sock.recv = slow_info
        with self.assertRaises(TimeoutError): Xvc(sock=sock, timeout=0.010, clock=clock)
        self.assertAlmostEqual(clock.now, 0.010)
        self.assertEqual(sock.sent, [b'getinfo:']); self.assertTrue(sock.closed)

        clock = Clock(); sock = FakeSocket(); link = Xvc(sock=sock)
        send = sock.sendall
        def slow_probe(data):
            sock.elapse(clock, 0.009)
            send(data)
        sock.sendall = slow_probe
        with self.assertRaises(TimeoutError):
            JtagTransport(link=link, timeout=0.050, clock=clock, sleep=clock.sleep)
        self.assertAlmostEqual(clock.now, 0.050)
        self.assertTrue(sock.closed)
        self.assertTrue(all(op==1 for op,_,_,_ in sock.tap.commands))
        lock = DeviceLock('localhost', 3721); lock.release()

    def test_slow_tck_scan_can_exceed_five_seconds_within_user_budget(self):
        clock = Clock(); sock = FakeSocket(period=10_000_000)
        send = sock.sendall
        def slow_wire(data):
            if data.startswith(b'shift:'):
                bits, = struct.unpack('<I', data[6:10])
                sock.elapse(clock, bits*sock.period/1_000_000_000)
            send(data)
        sock.sendall = slow_wire
        # Patch only the connection factory: no TCP endpoint is contacted.
        with patch.object(socket, 'create_connection', return_value=sock) as connect:
            owner = JtagTransport(timeout=60.0, frequency_hz=100, clock=clock, sleep=clock.sleep)
        self.addCleanup(owner.close); connect.assert_called_once()
        self.assertGreater(clock.now, 5)
        start = clock.now
        self.assertEqual(owner.reg_read(8), 0x10)
        self.assertAlmostEqual(clock.now-start, 12.9)
        self.assertFalse(sock.closed)
        self.assertGreater(max(sock.timeouts), 5)

    def test_poll_result_deadline_caps_blocking_scans(self):
        owner, tap, sock, clock = self.transport(timeout=30.0)
        owner.submit(0x100E0000, 35, 9); tap.job_delay = 100
        send = sock.sendall
        def slow_scan(data):
            sock.elapse(clock, 0.009)
            send(data)
        sock.sendall = slow_scan
        start = clock.now
        with self.assertRaises(TimeoutError): owner.poll_result(0.010)
        self.assertAlmostEqual(clock.now-start, 0.010)
        self.assertTrue(sock.closed)
        with self.assertRaises(ProtocolError): owner.poll_result()

    def test_descriptor_completion_output_read_and_explicit_ack(self):
        owner, tap, _, _ = self.transport()
        owner.submit(0x100E0000, 35, 0xBEEF)
        with self.assertRaises(ValueError): owner.submit(0x100E0000, 35, 1)
        with self.assertRaises(ValueError): owner.ack_success()
        result = owner.poll_result()
        self.assertEqual((result.tag, result.completed_tasks, result.error_code), (0xBEEF, 2, 0))
        self.assertEqual(owner.poll_result(), result)
        self.assertEqual(owner.mem_read(0x10040000, 4), bytes(range(4)))
        writes = [(address, value) for opcode, address, value, _ in tap.commands if opcode == 2]
        self.assertEqual(writes, [(0x10, 0x100E0000), (0x14, 35), (0x18, 0xBEEF), (0x0C, 1)])
        owner.ack_success()
        self.assertEqual([(a, d) for op, a, d, _ in tap.commands if op == 2][-1], (0x0C, 2))
        owner.submit(0x100E0100, 22, 0)
        self.assertEqual(owner.poll_result().tag, 0)
        owner.ack_success()

    def test_job_errors_stale_results_timeouts_and_busy_memory(self):
        owner, tap, _, _ = self.transport()
        tap.job_error = 5; tap.job_tasks = 1
        owner.submit(0x100E0000, 35, 9)
        with self.assertRaises(JobError) as error: owner.poll_result()
        self.assertEqual((error.exception.result.error_code, error.exception.result.completed_tasks), (5, 1))
        with self.assertRaises(ProtocolError): owner.ack_success()
        self.assertNotIn((0x0C, 2), [(a, d) for op, a, d, _ in tap.commands if op == 2])
        owner.close()
        owner, tap, _, _ = self.transport(); tap.wrong_tag = True
        owner.submit(0x100E0000, 35, 9)
        with self.assertRaises(ProtocolError): owner.poll_result()
        owner.close()
        owner, tap, _, _ = self.transport(); tap.job_delay = 100
        owner.submit(0x100E0000, 35, 9)
        with self.assertRaises(TimeoutError): owner.poll_result(0.003)
        with self.assertRaises(ProtocolError): owner.reg_read(8)
        owner.close()
        owner, tap, _, _ = self.transport(); owner.submit(0x100E0000, 35, 9)
        before = len([c for c in tap.commands if c[0] in (3, 4)])
        with self.assertRaises(ProtocolError): owner.mem_write(0x10000000, b'x')
        self.assertEqual(len([c for c in tap.commands if c[0] in (3, 4)]), before)

    def test_partial_upload_error_does_not_rollback_retry_or_continue(self):
        owner, tap, _, _ = self.transport()
        execute = tap.execute
        base = 0x10000000
        def fail_second_write(frame):
            if frame >> 548 & 255 == 4 and frame >> 512 & 0xFFFFFFFF == base + 64:
                tap.response_status = 0x80
            execute(frame)
        tap.execute = fail_second_write
        with self.assertRaises(MailboxError): owner.mem_write(base, b'\xA5' * 192)
        self.assertEqual(tap.memory[base], b'\xA5' * 64)
        self.assertNotIn(base + 64, tap.memory)
        self.assertNotIn(base + 128, tap.memory)
        writes = [address for opcode, address, _, _ in tap.commands if opcode == 4]
        self.assertEqual(writes, [base, base + 64])
        with self.assertRaises(ProtocolError): owner.submit(base, 22, 1)

    def test_donor_lock_path_flock_and_release(self):
        path = Path(self.temporary.name) / 'jtag-localhost-3721.lock'
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.dict(os.environ, {'OTPU_LOCK_HELD': 'jtag-localhost-3721'}):
                with self.assertRaises(DeviceBusy): DeviceLock('localhost', 3721)
        finally:
            os.close(fd)
        owner, _, _, _ = self.transport()
        self.assertEqual(path.read_text(), f'{os.getpid()}\n')
        with self.assertRaises(DeviceBusy): DeviceLock('localhost', 3721)
        owner.close(); owner.close()
        lock = DeviceLock('localhost', 3721); lock.release()

    def test_flock_excludes_a_second_process(self):
        owner, _, _, _ = self.transport()
        path = Path(self.temporary.name) / 'jtag-localhost-3721.lock'
        probe = ('import fcntl,os,sys\n'
                 'fd=os.open(sys.argv[1],os.O_RDWR)\n'
                 'try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\n'
                 'except BlockingIOError: sys.exit(23)\n'
                 'else: sys.exit(0)\n')
        result = subprocess.run([sys.executable, '-c', probe, str(path)], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 23, result.stderr)
        owner.close()
        result = subprocess.run([sys.executable, '-c', probe, str(path)], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_concurrent_calls_remain_single_outstanding(self):
        owner, tap, _, _ = self.transport()
        tap.delay_polls = 2
        errors = []
        def reader():
            try:
                for _ in range(10): self.assertEqual(owner.reg_read(0), RKEW_ID)
            except BaseException as error: errors.append(error)
        workers = [threading.Thread(target=reader) for _ in range(4)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(timeout=2)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        sequences = [command[3] for command in tap.commands]
        self.assertEqual(len(sequences), len(set(sequences)))

    def test_production_raw_command_bo_is_uploaded_without_rewriting(self):
        capture = json.loads((ROOT / 'tests/backend_ew_captures.json').read_text())['cases'][0]
        descriptor = capture['tasks'][0]['descriptor']
        address, count = descriptor['regcmd_addr'], descriptor['regcfg_amount']
        region = next(r for r in capture['regions'] if r['address'] <= address and
                      address + count * 8 <= r['address'] + r['size'])
        data = zlib.decompress(base64.b64decode(region['zlib_base64'], validate=True))
        raw = data[address - region['address']:address - region['address'] + count * 8]
        self.assertEqual(hashlib.sha256(raw).hexdigest(), capture['tasks'][0]['sha256'])
        owner, _, _, _ = self.transport()
        self.assertEqual(owner.upload_commands(address, raw), count)
        self.assertEqual(owner.mem_read(address, len(raw)), raw)
        # The mock completes metadata only; this is not an arithmetic execution test.
        owner.submit(address, count, 123)
        self.assertEqual(owner.poll_result().tag, 123)
        owner.ack_success()


if __name__ == '__main__':
    unittest.main()
