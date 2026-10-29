"""Native numeric RPC/socket controls only; never accesses a JTAG device."""
import socket
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tests/host'))
from test_transport import Tap, Clock
from tools.host.native_link import NativeLink
from tools.host.transport import _Deadline, DeviceBusy, JtagTransport, ProtocolError


class RpcSocket:
    def __init__(self, greeting=b'READY 3000000\n', clock=None):
        self.pending = bytearray(greeting)
        self.tap, self.commands = Tap(), []
        self.closed, self.timeout = False, None
        self.error = None
        self.clock, self.delay = clock, 0

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, raw):
        self.commands.append(raw)
        if self.error is not None:
            self.pending.extend(self.error)
            return
        fields = raw.decode().strip().split()
        result = 0
        if fields == ['RESET']:
            self.tap.ir = 0
        elif fields == ['QUIT']:
            pass
        else:
            assert fields[0] == 'SCAN' and len(fields) == 4
            kind, bits, value = fields[1], int(fields[2]), int(fields[3], 16)
            if kind == 'IR':
                assert bits == 6 and value in (3, 9, 63)
                self.tap.ir = value
            elif self.tap.ir == 9:
                assert bits == 32
                result = self.tap.idcode
            else:
                assert self.tap.ir == 3 and bits == 640
                if value:
                    assert self.tap.pending is None
                    self.tap.pending = value
                elif self.tap.pending is not None:
                    self.tap.execute(self.tap.pending)
                    self.tap.pending = None
                result = self.tap.response
        self.pending.extend(f'OK {result:x}\n'.encode())

    def recv(self, size):
        if self.clock is not None and self.delay:
            if self.delay >= self.timeout:
                self.clock.sleep(self.timeout)
                raise socket.timeout('synthetic absolute deadline')
            self.clock.sleep(self.delay)
        if not self.pending:
            return b''
        data = bytes(self.pending[:size])
        del self.pending[:size]
        return data

    def close(self):
        self.closed = True


class NativeLinkTests(unittest.TestCase):
    def test_native_clock_is_exact_and_slower_owner_cap_is_enforced(self):
        from fractions import Fraction
        rpc = RpcSocket()
        link = NativeLink(sock=rpc)
        self.assertEqual(link.actual_frequency_hz, 3_000_000)
        self.assertEqual(link.actual_period_ns, Fraction(1000, 3))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, OTPU_RUN_DIR=directory):
            with self.assertRaises(ProtocolError):
                JtagTransport('127.0.0.1', 3741, frequency_hz=2_000_000, link=link)
        self.assertTrue(rpc.closed)
        self.assertEqual(rpc.commands, [])

    def test_full_640bit_response_and_original_transport_byte_path(self):
        sock = RpcSocket()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OTPU_RUN_DIR': tmp}):
            link = NativeLink(sock=sock)
            with JtagTransport('127.0.0.1', 3741, frequency_hz=6000000, link=link) as owner:
                data = bytes(range(64))+bytes(reversed(range(64)))
                owner.mem_write(0x10010000, data)
                self.assertEqual(owner.mem_read(0x10010000, len(data)), data)
                owner.submit(0x100e0000, 24, 0x1234)
                result = owner.poll_result()
                self.assertEqual((result.tag, result.completed_tasks, result.error_code), (0x1234, 2, 0))
                owner.ack_success()
            self.assertTrue(sock.closed)
            self.assertTrue(any(command.startswith(b'SCAN DR 640 ') and len(command)>150 for command in sock.commands))

    def test_readiness_clock_busy_or_eof_rejects_and_closes(self):
        for greeting in [b'BUSY\n', b'READY 2000000\n', b'READY 0\n', b'', b'x'*1025]:
            sock = RpcSocket(greeting)
            with self.subTest(greeting=greeting[:40]), self.assertRaises((ProtocolError, DeviceBusy, EOFError)):
                NativeLink(sock=sock)
            self.assertTrue(sock.closed)

    def test_unsafe_ir_and_widths_fail_before_any_rpc(self):
        sock = RpcSocket()
        link = NativeLink(sock=sock)
        for value, bits, ir in [(0x26, 6, True), (0x0b, 6, True), (0, 640, False),
                                (0, True, False), (0, -1, False), (False, 6, True), (3, 32, True)]:
            with self.subTest(value=value, bits=bits, ir=ir), self.assertRaises(ValueError):
                link.scan(value, bits, ir=ir)
        self.assertEqual(sock.commands, [])
        link.scan(9, 6, ir=True)
        with self.assertRaises(ValueError):
            link.scan(0, 640)
        self.assertEqual(len(sock.commands), 1)
        link.close()

    def test_error_poison_has_no_retry_or_reset(self):
        for error in [b'ERR\n', b'OK nope\n', b'OK '+b'f'*161+b'\n', b'OK 100\n', b'']:
            sock = RpcSocket()
            link = NativeLink(sock=sock)
            sock.error = error
            with self.subTest(error=error[:20]), self.assertRaises((ProtocolError, EOFError)):
                link.scan(9, 6, ir=True)
            self.assertTrue(sock.closed)
            before = list(sock.commands)
            with self.assertRaises(ProtocolError):
                link.reset()
            self.assertEqual(sock.commands, before)

    def test_fragmented_response_consumes_one_absolute_deadline(self):
        clock = Clock()
        sock = RpcSocket(clock=clock)
        link = NativeLink(sock=sock, clock=clock)
        sock.delay = .11
        budget = _Deadline(.3, clock)
        with self.assertRaises((TimeoutError, socket.timeout)):
            link.scan(9, 6, ir=True, deadline=budget)
        self.assertLessEqual(clock.now, .300001)
        self.assertTrue(sock.closed)
        self.assertEqual(len(sock.commands), 1)

    def test_close_does_not_reset_fabric_or_send_commands(self):
        sock = RpcSocket()
        link = NativeLink(sock=sock)
        link.close()
        link.close()
        self.assertEqual(sock.commands, [])
        self.assertTrue(sock.closed)

    def test_explicit_orderly_bridge_shutdown(self):
        sock = RpcSocket()
        link = NativeLink(sock=sock)
        link.shutdown_bridge()
        self.assertEqual(sock.commands, [b'QUIT\n'])
        self.assertTrue(sock.closed)


if __name__ == '__main__':
    unittest.main()
