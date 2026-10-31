import importlib.util
import json
import os
import pathlib
import socket
import sys
import threading
import time
import unittest
from contextlib import closing

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PKG = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PKG))

from tools.host.raw_jtag_frame import RawJtagFrameExchange, USER2_IR, IR_BITS, DR_BITS
from tools.host.native_link import NativeLink
from tools.host.sys_mailbox_access import SysMailboxAccess
from tools.host.raw_frame_session import RawFrameSession
from tools.host.transport import MAGIC, DeviceBusy, ProtocolError
from tools.ddr.frame_transport import FullDdrFrameTransport

# Reuse the published callback fixture unchanged; no copied or modified test oracle.
fixture_path = ROOT / 'tests/ddr/frame_transport/test_transport.py'
spec = importlib.util.spec_from_file_location('qualified_frame_fixture', fixture_path)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
FakeRawEndpoint = fixture.FakeRawEndpoint


def response(seq, status=0, payload=0):
    return (MAGIC << 536) | (seq << 520) | (status << 512) | payload


def request(seq, opcode=1, address=0x20, payload=0):
    return ((MAGIC << 572) | (seq << 556) | (opcode << 548) |
            (0xF << 544) | (address << 512) | payload)


class ScriptLink:
    def __init__(self, baseline=None, result=None, *, stale=False, step=None):
        self._mutex = threading.RLock()
        self.ir = None
        self.closed = False
        self.scans = []
        self.baseline = response(7) if baseline is None else baseline
        self.result = response(8, 0, 0x1234) if result is None else result
        self.stale = stale
        self.step = step
        self.pending = False
        self.unexpected_poll = None
        self.on_request = None
    def scan(self, value, bits=640, *, ir=False, deadline=None):
        self.scans.append((value, bits, ir, deadline))
        if self.step:
            self.step()
        if ir:
            self.ir = value
            return 0
        if bits != 640 or self.ir != USER2_IR:
            raise AssertionError('scan did not select USER2')
        if value:
            if self.on_request is not None:
                self.on_request()
            self.pending = True
            return self.baseline
        if self.pending and self.unexpected_poll is not None:
            self.pending = False
            return self.unexpected_poll
        if self.pending and not self.stale:
            self.pending = False
            self.baseline = self.result
            return self.result
        return self.baseline
    def close(self):
        self.closed = True


class CarrierUnitTests(unittest.TestCase):
    def test_nonzero_baseline_wraps_and_forwards_exact_640_bit_request(self):
        payload = (1 << 512) - 1
        link = ScriptLink(response(0xFFFF), response(0, 0, payload))
        carrier = RawJtagFrameExchange(link, sleep=lambda _s: None)
        self.assertEqual(carrier.prepare(), 0xFFFF)
        raw = request(0)
        self.assertEqual(carrier.exchange(raw), response(0, 0, payload))
        dr_requests = [row[0] for row in link.scans if not row[2] and row[0] != 0]
        self.assertEqual(dr_requests, [raw])
        self.assertEqual(carrier.initial_sequence, 0)
        self.assertEqual([row[0] for row in link.scans if row[2]], [USER2_IR, USER2_IR])

    def test_duplicate_baseline_sequence_and_malformed_request_reject_before_dr(self):
        cases = [
            (response(19), request(19)),
            (response(19), request(20) ^ (1 << 572)),
            (response(19), request(20) | (1 << 604)),
            (response(19), request(20, opcode=0)),
        ]
        for baseline, raw in cases:
            with self.subTest(raw=raw):
                link = ScriptLink(baseline)
                c = RawJtagFrameExchange(link, sleep=lambda _s: None)
                c.prepare()
                before = len([x for x in link.scans if not x[2]])
                with self.assertRaises(ProtocolError):
                    c.exchange(raw)
                after = len([x for x in link.scans if not x[2]])
                self.assertEqual(after, before)
                self.assertTrue(c._failed)
                self.assertFalse(link.closed)

    def test_response_header_and_error_payload_are_strict(self):
        for bad in (response(2) ^ (1 << 536), response(2) | (1 << 568), response(2, 3, 1)):
            with self.subTest(bad=bad):
                link = ScriptLink(baseline=bad)
                c = RawJtagFrameExchange(link)
                with self.assertRaises(ProtocolError):
                    c.prepare()
                self.assertTrue(c._failed)

    def test_out_of_order_completion_poisoned_and_not_accepted(self):
        link = ScriptLink(response(40), response(41))
        link.unexpected_poll = response(42)
        c = RawJtagFrameExchange(link, sleep=lambda _s: None)
        c.prepare()
        with self.assertRaises(ProtocolError):
            c.exchange(request(41))
        self.assertTrue(c._failed)

    def test_one_deadline_object_covers_reselection_and_all_scans(self):
        from tools.host.transport import _Deadline
        now = [0.0]
        link = ScriptLink(response(50), response(51))
        c = RawJtagFrameExchange(link, clock=lambda: now[0], sleep=lambda _s: None)
        deadline = _Deadline(1.0, c._clock)
        c.prepare(deadline=deadline)
        before = len(link.scans)
        c.exchange(request(51), deadline=deadline)
        rows = link.scans[before:]
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(all(row[3] is rows[0][3] for row in rows))

    def test_expired_deadline_rejects_cached_prepare_before_io(self):
        from tools.host.transport import _Deadline
        now = [0.0]
        link = ScriptLink(response(60), response(61))
        c = RawJtagFrameExchange(link, clock=lambda: now[0], sleep=lambda _s: None)
        self.assertEqual(c.prepare(), 60)
        before = len(link.scans)
        budget = _Deadline(1.0, c._clock)
        now[0] = 2.0
        with self.assertRaises(TimeoutError):
            c.prepare(deadline=budget)
        self.assertEqual(len(link.scans), before)
        self.assertFalse(c._failed)

    def test_busy_borrowed_link_mutex_rejects_before_any_scan(self):
        link = ScriptLink()
        carrier = RawJtagFrameExchange(link)
        locked = threading.Event()
        release = threading.Event()
        def holder():
            link._mutex.acquire()
            locked.set()
            release.wait(2.0)
            link._mutex.release()
        thread = threading.Thread(target=holder)
        thread.start()
        try:
            self.assertTrue(locked.wait(1.0))
            with self.assertRaises(DeviceBusy):
                carrier.prepare()
            self.assertEqual(link.scans, [])
            self.assertFalse(carrier._failed)
        finally:
            release.set()
            thread.join(1.0)
        self.assertFalse(thread.is_alive())

    def test_reentrant_second_packet_is_rejected_while_first_is_outstanding(self):
        link = ScriptLink(response(70), response(71))
        carrier = RawJtagFrameExchange(link, sleep=lambda _s: None)
        carrier.prepare()
        link.on_request = lambda: carrier.exchange(request(72))
        with self.assertRaises(DeviceBusy):
            carrier.exchange(request(71))
        self.assertTrue(carrier._failed)
        nonzero_dr = [row for row in link.scans if not row[2] and row[0] != 0]
        self.assertEqual([row[0] for row in nonzero_dr], [request(71)])

    def test_valid_backend_error_is_returned_unchanged(self):
        error = response(0x1235, 3, 0)
        link = ScriptLink(response(0x1234), error)
        c = RawJtagFrameExchange(link, sleep=lambda _s: None)
        c.prepare()
        self.assertEqual(c.exchange(request(0x1235)), error)

    def test_unexpected_stale_completion_times_out_and_poisoned(self):
        now = [0.0]
        def tick(): now[0] += 0.6
        link = ScriptLink(response(30), response(31), stale=True)
        c = RawJtagFrameExchange(link, timeout=1.0, clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0]+s))
        c.prepare()
        link.step = tick
        with self.assertRaises(TimeoutError):
            c.exchange(request(31))
        self.assertTrue(c._failed)

    def test_close_only_closes_carrier_not_borrowed_link(self):
        link = ScriptLink()
        c = RawJtagFrameExchange(link)
        c.close()
        self.assertFalse(link.closed)
        self.assertEqual(link.scans, [])


class FakeNativeXvc:
    """Socket-level fake numeric-scan bridge with distinct USER2/USER3 mailboxes."""
    def __init__(self, sock, endpoint):
        self.sock, self.endpoint = sock, endpoint
        self.user2 = response(0)
        self.user3 = response(0)
        self.pending2 = None
        self.pending3 = None
        self.sys = {0x00: 0x524B5052, 0x04: 0x10000, 0x08: 1 | 2048,
                    0x10: 0, 0x14: 0, 0x18: 0, 0x1C: 0x10001,
                    0x20: 0, 0x24: 0, 0x28: 100000, 0x2C: 0}
        self.ir = None
        self.lines = []
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _sys_response(self, raw):
        seq = (raw >> 556) & 0xFFFF
        op = (raw >> 548) & 0xFF
        addr = (raw >> 512) & 0xFFFFFFFF
        data = raw & ((1 << 512) - 1)
        value = 0
        status = 0
        if ((raw >> 572) & 0xFFFFFFFF) != MAGIC or raw >> 604:
            status = 2
        elif op == 1 and addr in self.sys:
            value = self.sys[addr]
            if addr == 0x08 and self.sys.pop('_active_once', False):
                self.sys[0x08] = 4 | 16 | 32 | 64 | 512 | 2048
                value = 2 | 16
        elif op == 2 and addr == 0x0C and data >> 32 == 0:
            key = data & 0xFFFFFFFF
            if key == 0x53545254 and (self.sys[0x08] & 1):
                self.sys[0x10] += 1
                self.sys[0x14] += 1
                self.sys[0x18], self.sys[0x20], self.sys[0x24] = 0, 4, 0
                self.sys[0x08] = 2 | 16
                self.sys['_active_once'] = True
                # Model-only reset of the ordinary backend epoch/memory.
                self.endpoint.owner = 0
                self.endpoint.release_ready = True
                self.endpoint.memory[:] = bytes(len(self.endpoint.memory))
                self.endpoint.job_state = 'idle'
                self.endpoint.profile_status = {base: 0x10 for base, _ in fixture.PROFILES.values()}
            elif key == 0x41434B21 and self.sys[0x08] & 4:
                self.sys[0x08] = 1 | 512 | 2048
            else:
                status = 2
        else:
            status = 2
        return response(seq, status, value)

    def _scan(self, kind, bits, value):
        if kind == 'IR':
            self.ir = value
            return 0
        if bits != 640:
            raise ValueError('unexpected DR width')
        if self.ir == 3:
            old = self.user2
            if value:
                self.pending2 = self.endpoint.exchange(value, deadline=fixture._Deadline(10, self.endpoint.clock))
                return old
            if self.pending2 is not None:
                self.user2, self.pending2 = self.pending2, None
            return self.user2
        if self.ir == 0x22:
            old = self.user3
            if value:
                self.pending3 = self._sys_response(value)
                return old
            if self.pending3 is not None:
                self.user3, self.pending3 = self.pending3, None
            return self.user3
        raise ValueError('DR scan without USER2/USER3')

    def _serve(self):
        try:
            self.sock.sendall(b'READY 3000000 USER3\n')
            f = self.sock.makefile('rwb', buffering=0)
            while not self._stop.is_set():
                line = f.readline()
                if not line:
                    break
                self.lines.append(line.decode().strip())
                if line == b'QUIT\n':
                    f.write(b'OK 0\n')
                    break
                parts = line.decode().strip().split()
                if len(parts) != 4 or parts[0] != 'SCAN':
                    f.write(b'ERR\n')
                    continue
                result = self._scan(parts[1], int(parts[2]), int(parts[3], 16))
                f.write(f'OK {result:x}\n'.encode())
        except (OSError, ValueError):
            pass

    def stop(self):
        self._stop.set()
        try: self.sock.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        try: self.sock.close()
        except OSError: pass
        self.thread.join(1)


def self_reset_count(receipt):
    return len([item for item in receipt.action_writes if item == (0x0C, 0x53545254)])


class JoinedLifecycleTests(unittest.TestCase):
    def test_user2_jobs_bo_reset_and_explicit_reload_share_one_link(self):
        client, server = socket.socketpair()
        endpoint = FakeRawEndpoint()
        fake = FakeNativeXvc(server, endpoint)
        link = NativeLink(sock=client, timeout=2.0, allow_user3=True)
        try:
            carrier = RawJtagFrameExchange(link, timeout=20.0, clock=time.monotonic, sleep=lambda _s: None)
            baseline = carrier.prepare()
            session = RawFrameSession(carrier.exchange, close=carrier.close, source=1,
                                      timeout=30.0, clock=time.monotonic, initial_sequence=baseline)
            transport = FullDdrFrameTransport(session, timeout=30.0, sleep=lambda _s: None)
            original = bytes((i * 13 + 5) & 0xFF for i in range(64))
            commands = bytes(range(32))
            transport.upload_commands(0x100, commands)
            transport.mem_write(0x800, original)
            transport.submit(0x100, len(commands) // 8, 0xBEEF)
            result = transport.poll_result(timeout=1.0)
            self.assertEqual((result.tag, result.completed_tasks, result.error_code), (0xBEEF, 4, 0))
            self.assertEqual(transport.mem_read(0x800, 64), original)
            transport.ack_success()
            transport.release()
            transport.close()  # closes session/carrier only, not the borrowed link
            self.assertIsNotNone(link.sock)

            sys_access = SysMailboxAccess(link, timeout=2.0, sleep=lambda _s: None)
            receipt = sys_access.perform_reset(timeout=2.0)
            self.assertEqual(receipt.action_writes, ((0x0C, 0x53545254), (0x0C, 0x41434B21)))
            sys_access.close()
            self.assertIsNotNone(link.sock)

            new_carrier = RawJtagFrameExchange(link, timeout=20.0, clock=time.monotonic, sleep=lambda _s: None)
            seed = new_carrier.prepare()
            new_session = RawFrameSession(new_carrier.exchange, close=new_carrier.close,
                                          source=1, timeout=30.0, clock=time.monotonic,
                                          initial_sequence=seed)
            new_transport = FullDdrFrameTransport(new_session, timeout=30.0, sleep=lambda _s: None)
            new_transport.upload_commands(0x100, commands)
            new_transport.mem_write(0x800, original)  # explicit reload after model reset
            self.assertEqual(new_transport.mem_read(0x800, 64), original)
            new_transport.release()
            new_transport.close()
            self.assertIsNotNone(link.sock)
            self.assertTrue(any(line == 'SCAN IR 6 3' for line in fake.lines))
            self.assertTrue(any(line == 'SCAN IR 6 22' for line in fake.lines))
            self.assertFalse(any(line == 'RESET' for line in fake.lines))
            self.assertEqual(endpoint.owner, 0)
            trace = {'rpc_lines': fake.lines, 'model_only': True, 'reset_count': self_reset_count(receipt)}
            default_trace = ROOT / 'build' / 'host-raw-jtag-frame' / str(time.time_ns()) / 'trace.json'
            trace_path = pathlib.Path(os.environ.get('CARRIER_TRACE_PATH', default_trace))
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text(json.dumps(trace, sort_keys=True, indent=2) + '\n')
        finally:
            link.close()
            fake.stop()


if __name__ == '__main__':
    unittest.main(verbosity=2)
