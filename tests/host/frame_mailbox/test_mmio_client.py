"""Strict callback controls for the raw MMIO frame client.

These tests model only the documented register callbacks. They do not map a
BAR, perform tensor work, or imply that an FPGA/device was exercised.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.host.axil_frame_mailbox import AxilFrameMailbox, FULL, MAGIC
from tools.host.transport import DeviceBusy, ProtocolError, _Deadline


def request_frame(seq=0x1234, payload=None):
    if payload is None:
        payload = bytes((i * 29 + 7) & 255 for i in range(64))
    # Raw frame fields: 512-bit payload, 8-bit request flags, 16-bit sequence,
    # 32-bit magic, and 32 reserved high bits.
    return int.from_bytes(payload, 'little') | (0x5a << 512) | (seq << 556) | (MAGIC << 572)


def response_frame(seq=0x1234, payload=None, error=0, reserved=0):
    if payload is None:
        payload = bytes((i * 17 + 3) & 255 for i in range(64))
    return (int.from_bytes(payload, 'little') | (error << 512) |
            (seq << 520) | (MAGIC << 536) | (reserved << 568))


class RegisterDevice:
    def __init__(self, *, initial=(1, 0, 0, 0), statuses=(0x12, 0x14),
                 response=None, mutations=None, read_result=None,
                 write_result=None, clock=None):
        self.initial = initial
        self.statuses = list(statuses)
        self.response = response_frame() if response is None else response
        self.mutations = mutations or {}
        self.read_result = read_result
        self.write_result = write_result
        self.reads, self.writes = [], []
        self.events = []
        self.closed = 0
        self.staged = [0] * 20
        self.req_mask = 0
        self.rsp_mask = FULL if self.response is not None else 0
        self.committed = False
        self.acked = False
        self.clock = clock
        self.on_read = None
        self.on_write = None

    def close(self):
        self.closed += 1

    def read32(self, address, *, deadline):
        self.reads.append((address, deadline))
        self.events.append(('read', address))
        if self.on_read:
            self.on_read(address, deadline)
        if self.read_result is not None:
            return self.read_result(address, deadline)
        if address == 0:
            value = 0x524b5046
        elif address == 4:
            value = 0x10000
        elif address == 8:
            if self.acked:
                value = 1
            elif self.committed:
                value = self.statuses.pop(0) if self.statuses else 0x14
            elif self.req_mask:
                value = 0x11 if self.req_mask == FULL else 1
            else:
                value = self.initial[0]
        elif address == 0x10:
            value = self.req_mask if self.req_mask else self.initial[1]
        elif address == 0x14:
            value = (0 if self.acked else (FULL if self.committed else self.rsp_mask)) if self.committed else self.initial[2]
        elif address == 0x18:
            value = self.initial[3]
        elif 0x100 <= address <= 0x14c and address % 4 == 0:
            index = (address - 0x100) // 4
            value = self.response >> (32 * index) & 0xffffffff
        else:
            raise AssertionError(f'unexpected read {address:#x}')
        return self.mutations.get(('read', len(self.reads) - 1), value)

    def write32(self, address, value, *, deadline):
        self.writes.append((address, value, deadline))
        self.events.append(('write', address, value))
        if self.on_write:
            self.on_write(address, value, deadline)
        if self.write_result is not None:
            return self.write_result
        if 0x40 <= address <= 0x8c and address % 4 == 0:
            index = (address - 0x40) // 4
            self.staged[index] = value
            self.req_mask |= 1 << index
        elif address == 0xc and value == 1:
            self.committed = True
        elif address == 0xc and value == 2:
            self.acked = True
            self.req_mask = 0
            self.rsp_mask = 0
        else:
            raise AssertionError(f'unexpected write {address:#x}={value:#x}')
        return None


class MMIOClientControls(unittest.TestCase):
    def make_client(self, device=None, **kwargs):
        device = device or RegisterDevice()
        client = AxilFrameMailbox(device.read32, device.write32, close=device.close, **kwargs)
        return client, device

    def test_constructor_probe_and_readonly_registers_before_any_write(self):
        client, d = self.make_client()
        self.assertEqual([a for a, _ in d.reads], [0, 4, 8, 0x10, 0x14, 0x18])
        self.assertEqual(d.writes, [])
        self.assertEqual(d.closed, 0)
        client.close()

    def test_exchange_stages_twenty_little_endian_dwords_then_commits_once(self):
        frame = request_frame()
        client, d = self.make_client()
        d.reads.clear()
        got = client.exchange(frame)
        expected = [(0x40 + 4*i, frame >> (32*i) & 0xffffffff) for i in range(20)]
        self.assertEqual([(a, v) for a, v, _ in d.writes], expected + [(0xc, 1), (0xc, 2)])
        self.assertEqual(d.staged, [v for _, v in expected])
        self.assertEqual(d.staged[-1], 0)  # all 32 request reserved bits are zero
        self.assertEqual(sum(1 << i for i in range(20) if d.staged[i] == (frame >> (32*i) & 0xffffffff)), FULL)
        self.assertEqual(got, d.response)
        self.assertEqual([a for a, _ in d.reads if 0x100 <= a <= 0x14c], [0x100 + i*4 for i in range(20)])
        client.close()

    def test_silent_rejected_write_is_detected_without_ack_or_retry(self):
        # A posted-write adapter may not expose a device-side write rejection.
        # Request-mask and state readback must still prevent false completion.
        for dropped_address in (0x48, 0x0c):
            with self.subTest(dropped_address=dropped_address):
                device = RegisterDevice()
                original_write = device.write32

                def reject_write(address, value, *, deadline):
                    if address == dropped_address:
                        device.writes.append((address, value, deadline))
                        device.events.append(('write_rejected', address, value))
                        return None
                    return original_write(address, value, deadline=deadline)

                device.write32 = reject_write
                client, device = self.make_client(device)
                with self.assertRaises(ProtocolError):
                    client.exchange(request_frame())
                self.assertTrue(client.failed)
                self.assertFalse(device.committed)
                self.assertFalse(device.acked)
                self.assertNotIn((0x0c, 2), [(a, v) for a, v, _ in device.writes])
                writes = list(device.writes)
                with self.assertRaises(ProtocolError):
                    client.exchange(request_frame())
                self.assertEqual(device.writes, writes)
                client.close()
                self.assertEqual(device.closed, 1)

    def test_polling_and_all_response_words_precede_ack(self):
        client, d = self.make_client()
        d.reads.clear()
        client.exchange(request_frame())
        statuses = [a for a, _ in d.reads if a == 8]
        self.assertGreaterEqual(statuses.count(8), 4)
        rsp_reads = [a for a, _ in d.reads if 0x100 <= a <= 0x14c]
        self.assertEqual(rsp_reads, [0x100 + i*4 for i in range(20)])
        ack_index = next(i for i, (a, v, _) in enumerate(d.writes) if a == 0xc and v == 2)
        self.assertEqual(ack_index, 21)
        ack_event = d.events.index(('write', 0xc, 2))
        final_word_event = d.events.index(('read', 0x14c))
        mask_event = max(i for i, e in enumerate(d.events[:ack_event]) if e == ('read', 0x14))
        held_status_event = max(i for i, e in enumerate(d.events[:ack_event]) if e == ('read', 8))
        self.assertLess(final_word_event, mask_event)
        self.assertLess(mask_event, held_status_event)
        self.assertLess(held_status_event, ack_event)
        # Response mask and held DONE state are observed after all words and before ACK.
        tail = [(a, v) for a, v, _ in d.writes[ack_index:]]
        self.assertEqual(tail[0], (0xc, 2))
        client.close()

    def test_one_deadline_object_is_shared_by_constructor_and_whole_exchange(self):
        now = [10.0]
        clock = lambda: now[0]
        d = RegisterDevice()
        client, d = self.make_client(d, timeout=7.0, clock=clock, sleep=lambda n: None)
        all_deadlines = [dl for _, dl in d.reads] + [dl for _, _, dl in d.writes]
        self.assertTrue(all(dl is all_deadlines[0] for dl in all_deadlines))
        self.assertEqual(all_deadlines[0].stop, 17.0)
        d.reads.clear(); d.writes.clear()
        client.exchange(request_frame())
        all_deadlines = [dl for _, dl in d.reads] + [dl for _, _, dl in d.writes]
        self.assertTrue(all(dl is all_deadlines[0] for dl in all_deadlines))
        self.assertEqual(all_deadlines[0].stop, 17.0)
        client.close()

    def test_caller_deadline_accepts_same_clock_and_rejects_wrong_owner_before_io(self):
        clock = lambda: 1.0
        client, d = self.make_client(clock=clock)
        d.reads.clear()
        external = _Deadline(2.0, clock)
        client.exchange(request_frame(), deadline=external)
        self.assertTrue(all(dl is external for _, dl in d.reads))
        before = len(d.reads) + len(d.writes)
        with self.assertRaises(ValueError):
            client.exchange(request_frame(), deadline=_Deadline(2.0, lambda: 1.0))
        self.assertEqual(before, len(d.reads) + len(d.writes))
        with self.assertRaises(ValueError):
            client.exchange(request_frame(), deadline=object())
        self.assertEqual(before, len(d.reads) + len(d.writes))
        client.close()

    def test_valid_backend_error_frame_is_returned_unchanged_without_fake_job_ack(self):
        error_frame = response_frame(error=7, payload=bytes(64))
        d = RegisterDevice(response=error_frame)
        client, d = self.make_client(d)
        self.assertEqual(client.exchange(request_frame()), error_frame)
        self.assertEqual([(a, v) for a, v, _ in d.writes if a == 0xc], [(0xc, 1), (0xc, 2)])
        client.close()

    def test_malformed_response_and_register_failures_poison_without_ack(self):
        bads = [response_frame(reserved=1), response_frame(seq=4),
                response_frame() ^ (1 << 536),
                response_frame(error=2, payload=b'\x01' + bytes(63))]
        for bad in bads:
            with self.subTest(response=bad):
                d = RegisterDevice(response=bad)
                client, d = self.make_client(d)
                with self.assertRaises(ProtocolError):
                    client.exchange(request_frame())
                self.assertTrue(client.failed)
                self.assertNotIn((0xc, 2), [(a, v) for a, v, _ in d.writes])
                client.close()
        for malformed in (1 << 40, True):
            d = RegisterDevice()
            original_read = d.read32
            def bad_read(address, *, deadline, malformed=malformed, original_read=original_read):
                if address == 0x120 and d.committed:
                    return malformed
                return original_read(address, deadline=deadline)
            d.read32 = bad_read
            client, d = self.make_client(d)
            with self.assertRaises(ProtocolError):
                client.exchange(request_frame())
            self.assertNotIn((0xc, 2), [(a, v) for a, v, _ in d.writes])
            client.close()

    def test_bad_identity_or_unsupported_status_never_writes(self):
        d = RegisterDevice(initial=(0x20, 0, 0, 0))
        d.read32 = lambda address, *, deadline: 0 if address == 0 else (0x10000 if address == 4 else 1)
        with self.assertRaises(ProtocolError):
            AxilFrameMailbox(d.read32, d.write32, close=d.close)
        self.assertEqual(d.writes, [])
        self.assertEqual(d.closed, 1)
        for state in (0, 2, 3, 8, 0x10, 0x13, 0x15, 0x20):
            d = RegisterDevice(initial=(state, 0, 0, 0))
            with self.assertRaises(ProtocolError):
                self.make_client(d)
            self.assertEqual(d.writes, [])

    def test_constructor_preserves_probe_error_when_close_also_fails(self):
        d = RegisterDevice()
        original = ProtocolError('scripted identity probe failure')
        close_error = OSError('scripted close failure')
        def fail_probe(address, *, deadline):
            raise original
        def fail_close():
            d.closed += 1
            raise close_error

        class CapturingMailbox(AxilFrameMailbox):
            instance = None
            def __new__(cls, *args, **kwargs):
                result = super().__new__(cls)
                cls.instance = result
                return result

        with self.assertRaises(ProtocolError) as caught:
            CapturingMailbox(fail_probe, d.write32, close=fail_close)
        self.assertIs(caught.exception, original)
        self.assertTrue(CapturingMailbox.instance.failed)
        self.assertTrue(CapturingMailbox.instance.closed)
        self.assertEqual(d.closed, 1)
        self.assertTrue(any('scripted close failure' in note
                            for note in getattr(original, '__notes__', [])))

    def test_preexisting_partial_staging_result_or_foreign_pending_rejected_readonly(self):
        for initial in ((1, 1, 0, 0), (1, 0, 1, 0), (0x12, 0, 0, 0), (0x14, 0, 0, 0)):
            d = RegisterDevice(initial=initial)
            with self.subTest(initial=initial), self.assertRaises((DeviceBusy, ProtocolError)):
                self.make_client(d)
            self.assertEqual(d.writes, [])
            self.assertEqual(d.closed, 1)

    def test_unsupported_committed_status_combinations_poison_without_ack(self):
        for status in (0, 1, 2, 3, 8, 0x10, 0x11, 0x13, 0x15, 0x20):
            d = RegisterDevice(statuses=(status,))
            client, d = self.make_client(d)
            with self.subTest(status=status), self.assertRaises(ProtocolError):
                client.exchange(request_frame())
            self.assertTrue(client.failed)
            self.assertNotIn(('write', 0xc, 2), d.events)
            client.close()

    def test_write_callback_must_return_none_and_any_transaction_failure_poisons(self):
        for result in (0, False, 'ok'):
            d = RegisterDevice(write_result=lambda result=result: result)
            client, d = self.make_client(d)
            with self.assertRaises(ProtocolError):
                client.exchange(request_frame())
            self.assertTrue(client.failed)
            self.assertEqual(len(d.writes), 1)
            with self.assertRaises(ProtocolError):
                client.exchange(request_frame())
            client.close()

    def test_callback_failure_after_partial_staging_poisons_without_retry_or_control_write(self):
        client, d = self.make_client()
        count = [0]
        def fail_on_fifth(address, value, deadline):
            count[0] += 1
            if count[0] == 5:
                raise OSError('scripted callback failure')
        d.on_write = fail_on_fifth
        with self.assertRaisesRegex(OSError, 'scripted callback failure'):
            client.exchange(request_frame())
        self.assertTrue(client.failed)
        self.assertEqual(len(d.writes), 5)
        self.assertFalse(any(a == 0xc for a, _, _ in d.writes))
        with self.assertRaises(ProtocolError):
            client.exchange(request_frame())
        self.assertEqual(len(d.writes), 5)
        client.close()

    def test_invalid_frames_fail_before_io_without_poisoning(self):
        client, d = self.make_client()
        d.reads.clear()
        before = len(d.reads) + len(d.writes)
        for value in (True, -1, 1 << 640, 1 << 604, (1 << 572)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                client.exchange(value)
        self.assertEqual(before, len(d.reads) + len(d.writes))
        self.assertFalse(client.failed)
        client.close()

    def test_deadline_expiry_mid_stage_never_commits_or_acks(self):
        now = [0.0]
        clock = lambda: now[0]
        d = RegisterDevice()
        client, d = self.make_client(d, timeout=1.0, clock=clock)
        d.reads.clear(); d.writes.clear()
        def advancing_write(address, value, deadline):
            now[0] += 0.2
        d.on_write = advancing_write
        with self.assertRaises(TimeoutError):
            client.exchange(request_frame())
        self.assertTrue(client.failed)
        self.assertFalse(any(a == 0xc for a, _, _ in d.writes))
        client.close()

    def test_reentrant_exchange_is_busy_without_extra_register_writes(self):
        client, d = self.make_client()
        nested = []
        invoked = [False]
        def callback(address, deadline):
            if not invoked[0]:
                invoked[0] = True
                before = len(d.writes)
                with self.assertRaises(DeviceBusy):
                    client.exchange(request_frame(0x4321))
                nested.append(len(d.writes) - before)
        d.on_read = callback
        client.exchange(request_frame())
        self.assertEqual(nested, [0])
        client.close()

    def test_close_idempotent_only_closes_provider(self):
        client, d = self.make_client()
        client.close(); client.close()
        self.assertEqual(d.closed, 1)
        self.assertEqual(d.writes, [])


if __name__ == '__main__':
    unittest.main()
