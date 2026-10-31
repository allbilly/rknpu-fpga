"""Callback-only integration controls for RKHO and the full-DDR raw frame client."""
import threading
import unittest
from unittest import mock

from tools.ddr.frame_transport import FullDdrFrameTransport
from tools.ddr.framework_transport import PROFILES
from tools.host import transport as wire
from tools.host.raw_frame_session import RawFrameSession
from tools.host.transport import DeviceBusy, MailboxError, ProtocolError, _Deadline

RKHO = {0x600: 0x524B484F, 0x604: 0x10000, 0x61C: 3}
RESET = {0x500: 0x524B5253, 0x504: 0x10000, 0x518: 0x10004, 0x510: 7, 0x514: 0}


def response(sequence, status=0, data=0):
    return (wire.MAGIC << 536) | (sequence << 520) | (status << 512) | data


def decode(frame):
    return ((frame >> 556) & 0xFFFF, (frame >> 548) & 0xFF,
            (frame >> 544) & 0xF, (frame >> 512) & 0xFFFFFFFF,
            frame & ((1 << 512) - 1))


class FakeRawEndpoint:
    """Minimal protocol endpoint with separate RKHO, register, reset and BO state."""
    def __init__(self, source=1):
        self.source = source
        self.owner = 0
        self.lease_epoch = 0
        self.failure = 0
        self.release_ready = True
        self.closed = 0
        self.close_error = None
        self.clock = self._clock
        self.now = 0.0
        self.frames = []
        self.backend_frames = []
        self.backend_writes = []
        self.management_writes = []
        self.hook = None
        self.backend_error = None
        self.bad_read_payload = None
        self.fail_next_backend = None
        self.registers = dict(RESET)
        self.memory = bytearray(0x4000)
        self.profile_status = {base: 0x10 for base, _ in PROFILES.values()}
        self.descriptors = {base: {0x10: 0, 0x14: 0, 0x18: 0} for base, _ in PROFILES.values()}
        self.job_state = 'idle'
        self.poll_count = 0
        self.result_tag = 0
        self.result_tasks = 0
        self.reset_statuses = []
        self.reset_action_writes = []

    def _clock(self):
        self.now += 0.001
        return self.now

    def close(self):
        self.closed += 1
        if self.close_error is not None:
            raise self.close_error

    def session(self):
        return RawFrameSession(self.exchange, close=self.close, source=self.source,
                               timeout=5.0, clock=self.clock)

    def _rkho_value(self, address):
        if address == 0x600:
            return RKHO[0x600]
        if address == 0x604:
            return RKHO[0x604]
        if address == 0x608:
            return (self.release_ready << 3) | (self.failure << 2) | self.owner
        if address == 0x610:
            return self.lease_epoch
        if address == 0x614:
            return self.source
        if address == 0x618:
            return self.failure
        if address == 0x61C:
            return RKHO[0x61C]
        return None

    def _register_read(self, address):
        if address == 0x508:
            if self.reset_statuses:
                return self.reset_statuses.pop(0)
            return 0x31
        if address in self.registers:
            return self.registers[address]
        for base, ident in PROFILES.values():
            if address == base:
                return ident
            if address == base + 4:
                return 0x10000
            if address == base + 8:
                if base == 0 and self.job_state == 'active':
                    result = (0x12, 0x14, 0x4)[min(self.poll_count, 2)]
                    self.poll_count += 1
                    return result
                if base == 0 and self.job_state == 'staged':
                    return 0x11
                return self.profile_status[base]
            if base == 0:
                if address == 0x1C:
                    return self.result_tag
                if address == 0x20:
                    return self.result_tasks
                if address == 0x24:
                    return 0
                if address in self.descriptors[base]:
                    return self.descriptors[base][address]
            if base == 0x100 and address in self.descriptors[base]:
                return self.descriptors[base][address]
            if base == 0x400 and address in self.descriptors[base]:
                return self.descriptors[base][address]
        return 0

    def _register_write(self, address, value):
        for base in self.descriptors:
            if address in (base + 0x10, base + 0x14, base + 0x18):
                offset = address - base
                self.descriptors[base][offset] = value
                self.release_ready = False
                if base == 0:
                    self.job_state = 'staged'
                return 0
        if address == 0x0C:
            if value == 1:
                self.job_state = 'active'
                self.poll_count = 0
                self.result_tag = self.descriptors[0][0x18]
                self.result_tasks = 4
                self.release_ready = False
                return 0
            if value == 2:
                self.job_state = 'idle'
                self.profile_status[0] = 0x10
                self.descriptors[0] = {0x10: 0, 0x14: 0, 0x18: 0}
                self.release_ready = True
                return 0
        if address == 0x50C:
            self.reset_action_writes.append(value)
            if value == 1:
                self.registers[0x510] += 1
                self.reset_statuses = [0x32, 0x36, 0x36]
                self.release_ready = False
            elif value == 2:
                self.reset_statuses = [0x32, 0x31]
                self.release_ready = True
            return 0
        return 0

    def _backend(self, sequence, opcode, address, data):
        self.backend_frames.append((sequence, opcode, address, data))
        if self.fail_next_backend is not None:
            error, self.fail_next_backend = self.fail_next_backend, None
            raise error
        if self.hook is not None:
            override = self.hook(sequence, opcode, address, data)
            if isinstance(override, BaseException):
                raise override
            if override is not None:
                return override
        if self.backend_error is not None:
            status, self.backend_error = self.backend_error, None
            return response(sequence, status, 0)
        if opcode == 1:
            if self.bad_read_payload is not None and address == self.bad_read_payload[0]:
                return response(sequence, 0, self.bad_read_payload[1])
            return response(sequence, 0, self._register_read(address))
        if opcode == 2:
            self.backend_writes.append((opcode, address, data))
            if address == 0x50C:
                self._register_write(address, data & 0xFFFFFFFF)
            else:
                self._register_write(address, data & 0xFFFFFFFF)
            return response(sequence)
        if opcode == 3:
            if address + 64 > len(self.memory):
                return response(sequence, 3)
            block = self.memory[address:address + 64]
            return response(sequence, 0, int.from_bytes(block, 'little'))
        if opcode == 4:
            if address + 64 > len(self.memory):
                return response(sequence, 3)
            self.backend_writes.append((opcode, address, data))
            self.memory[address:address + 64] = data.to_bytes(64, 'little')
            return response(sequence)
        return response(sequence, 3)

    def exchange(self, frame, *, deadline):
        self.frames.append((frame, deadline))
        sequence, opcode, strobes, address, data = decode(frame)
        if opcode in (1, 2) and address >> 8 == 6:
            if opcode == 1:
                value = self._rkho_value(address)
                return response(sequence, 0 if value is not None else 3, value or 0)
            self.management_writes.append((address, data))
            command = data & 0xFFFFFFFF
            if address != 0x60C or data >> 32 or strobes != 0xF:
                return response(sequence, 2)
            if command == 1 and self.owner == 0 and self.release_ready and self.lease_epoch < 0xFFFFFFFF:
                self.owner = self.source
                self.lease_epoch += 1
                return response(sequence)
            if command == 2 and self.owner == self.source and self.release_ready:
                self.owner = 0
                return response(sequence)
            return response(sequence, 2)
        return self._backend(sequence, opcode, address, data)


class FullDdrFrameTransportTests(unittest.TestCase):
    def test_backend_then_release_never_reuses_retained_completion_sequence(self):
        endpoint = FakeRawEndpoint()
        original = endpoint.exchange
        completed = []

        def retained_mailbox_exchange(frame, *, deadline):
            sequence = decode(frame)[0]
            # A physical mailbox can still return its preceding completion
            # during the first polls of a new request. Reusing that sequence
            # makes the old response indistinguishable from the new one.
            if completed and sequence == completed[-1]:
                raise ProtocolError('New request aliases retained completion')
            reply = original(frame, deadline=deadline)
            completed.append(sequence)
            return reply

        session = RawFrameSession(retained_mailbox_exchange, close=endpoint.close,
                                  source=1, timeout=5, clock=endpoint.clock)
        transport = FullDdrFrameTransport(session)
        transport.release()
        self.assertTrue(session.released)
        self.assertEqual(endpoint.owner, 0)
        self.assertEqual(len(completed), len(endpoint.frames))
        self.assertTrue(all(a != b for a, b in zip(completed, completed[1:])))

    def test_captured_completion_seed_wraps_and_raw_forwarding_advances_allocator(self):
        endpoint = FakeRawEndpoint()
        session = RawFrameSession(endpoint.exchange, close=endpoint.close, source=1,
                                  timeout=5, clock=endpoint.clock, initial_sequence=0xFFFF)
        self.assertEqual(decode(endpoint.frames[0][0])[0], 0)
        raw = ((wire.MAGIC << 572) | (0xFFFF << 556) | (1 << 548) |
               (15 << 544) | (8 << 512))
        session.exchange(raw)
        self.assertEqual(endpoint.frames[-1][0], raw)
        session.release()
        raw_index = next(i for i, (frame, _) in enumerate(endpoint.frames) if frame == raw)
        self.assertEqual(decode(endpoint.frames[raw_index + 1][0])[0], 0)
        self.assertTrue(session.released)

    def test_bad_completion_seed_fails_before_any_exchange(self):
        for seed in (True, -1, 0x10000, '0'):
            endpoint = FakeRawEndpoint()
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                RawFrameSession(endpoint.exchange, close=endpoint.close, source=1,
                                clock=endpoint.clock, initial_sequence=seed)
            self.assertEqual(endpoint.frames, [])

    def make_transport(self, endpoint=None, *, timeout=5.0, source=1):
        endpoint = endpoint or FakeRawEndpoint(source)
        session = endpoint.session()
        with mock.patch.object(wire, 'DeviceLock', side_effect=AssertionError('DeviceLock called')) as lock, \
             mock.patch.object(wire, 'Xvc', side_effect=AssertionError('Xvc called')) as xvc, \
             mock.patch.object(wire.JtagTransport, '__init__', side_effect=AssertionError('JTAG initializer called')) as init:
            transport = FullDdrFrameTransport(session, timeout=timeout, sleep=lambda unused: None)
        lock.assert_not_called(); xvc.assert_not_called(); init.assert_not_called()
        return endpoint, session, transport

    def test_all_profile_and_reset_identities_precede_every_backend_write(self):
        endpoint, session, transport = self.make_transport()
        transport.reg_write(0x10, 0x100)
        expected = [entry for base, unused in PROFILES.values()
                    for entry in ((1, base), (1, base + 4))]
        expected += [(1, 0x500), (1, 0x504), (1, 0x518)]
        backend_reads = [(op, address) for _, op, address, _ in endpoint.backend_frames[:12]]
        self.assertEqual(backend_reads, expected + [(1, base + 8) for base, _ in PROFILES.values()])
        writes = [i for i, (_, op, _, _) in enumerate(endpoint.backend_frames) if op in (2, 4)]
        identities = [i for i, (_, op, address, _) in enumerate(endpoint.backend_frames)
                      if op == 1 and address in set(sum(([base, base + 4] for base, _ in PROFILES.values()), [])) | {0x500, 0x504, 0x518}]
        self.assertTrue(writes)
        self.assertLess(max(identities), min(writes))
        self.assertTrue(transport._verified)
        self.assertEqual((session.source, session.epoch, endpoint.owner), (1, 1, 1))

    def test_wrong_identity_closes_session_preserves_protocol_error_even_if_close_raises(self):
        endpoint = FakeRawEndpoint()
        session = endpoint.session()
        endpoint.registers[0x400] = 0
        endpoint.close_error = OSError('close callback failed')
        with self.assertRaises(ProtocolError):
            FullDdrFrameTransport(session, sleep=lambda unused: None)
        self.assertTrue(session.closed)
        self.assertFalse(session.released)
        self.assertEqual(endpoint.management_writes, [(0x60C, 1)])
        self.assertEqual(endpoint.closed, 1)

    def test_closed_released_or_poisoned_session_is_refused_and_closed(self):
        for state in ('closed', 'released', 'poisoned'):
            with self.subTest(state=state):
                endpoint = FakeRawEndpoint()
                session = endpoint.session()
                if state == 'closed':
                    session.close()
                elif state == 'released':
                    session.release()
                else:
                    session.failed = True
                before = len(endpoint.backend_frames)
                with self.assertRaises(ProtocolError):
                    FullDdrFrameTransport(session, sleep=lambda unused: None)
                self.assertEqual(len(endpoint.backend_frames), before)
                self.assertTrue(session.closed)
                self.assertEqual(endpoint.closed, 1)

    def test_exact_opcode_sequence_upload_and_partial_line_rmw(self):
        endpoint, session, transport = self.make_transport()
        raw = bytes(range(24))  # whole QWORDs, aligned command BO
        count = transport.upload_commands(0x100, raw)
        self.assertEqual(count, 3)
        self.assertEqual(endpoint.memory[0x100:0x118], raw)
        original = bytes((i * 7 + 3) & 0xFF for i in range(128))
        endpoint.memory[0x600:0x680] = original
        payload = b'partial-crosses-line'
        transport.mem_write(0x63B, payload)
        expected = bytearray(original)
        expected[0x3B:0x3B + len(payload)] = payload
        self.assertEqual(endpoint.memory[0x600:0x680], bytes(expected))
        requests = endpoint.backend_frames
        self.assertTrue(all(1 <= seq <= 0xFFFF for seq, _, _, _ in requests))
        # Ownership and backend requests share one physical completion stream.
        self.assertEqual([decode(frame)[0] for frame, _ in endpoint.frames],
                         list(range(1, len(endpoint.frames) + 1)))
        self.assertTrue(all(opcode in (1, 2, 3, 4) for _, opcode, _, _ in requests))
        self.assertTrue(any(op == 3 and address == 0x600 for _, op, address, _ in requests))
        self.assertTrue(any(op == 4 and address == 0x600 for _, op, address, _ in requests))
        for frame, deadline in endpoint.frames:
            seq, opcode, strobes, address, data = decode(frame)
            self.assertEqual((frame >> 572) & 0xFFFFFFFF, wire.MAGIC)
            self.assertEqual(frame >> 604, 0)
            self.assertEqual(strobes, 0xF)
            self.assertEqual(deadline.clock, endpoint.clock)
        self.assertFalse(session.failed)

    def test_bad_profiles_registers_and_input_fail_before_io(self):
        endpoint, session, transport = self.make_transport()
        count = len(endpoint.backend_frames)
        for profile in (None, True, 'EW', 'int8', 1):
            with self.subTest(profile=repr(profile)), self.assertRaises(ValueError):
                transport.select_profile(profile)
        with self.assertRaises(ValueError):
            transport.reg_read(0x0C)
        with self.assertRaises(ValueError):
            transport.reg_write(0x10, 1 << 32)
        with self.assertRaises(ValueError):
            transport.upload_commands(0x101, b'12345678')
        foreign = _Deadline(1.0, lambda: 0.0)
        with self.assertRaises(ValueError):
            transport._command(1, 8, deadline=foreign)
        self.assertEqual(len(endpoint.backend_frames), count)
        self.assertFalse(transport._failed)
        self.assertFalse(session.failed)

    def test_peer_bank_status_prevents_profile_change(self):
        endpoint, session, transport = self.make_transport()
        endpoint.profile_status[0x100] = 0x11
        count = len(endpoint.backend_frames)
        with self.assertRaises(DeviceBusy):
            transport.select_profile('layout')
        self.assertEqual(transport.profile, 'ew')
        self.assertTrue(transport._failed)
        self.assertEqual(len(endpoint.backend_frames), count + 2)  # EW and peer idle witnesses only
        self.assertEqual(endpoint.backend_writes, [])
        self.assertFalse(session.failed)

    def test_submit_result_full_bo_readback_ack_then_explicit_release(self):
        endpoint, session, transport = self.make_transport()
        bo = bytes((i * 13 + 5) & 0xFF for i in range(64))
        endpoint.memory[0x800:0x840] = bo
        commands = bytes(range(32))
        self.assertEqual(transport.upload_commands(0x100, commands), 4)
        transport.submit(0x100, len(commands) // 8, 0xBEEF)
        result = transport.poll_result(timeout=1.0)
        self.assertEqual((result.tag, result.completed_tasks, result.error_code), (0xBEEF, 4, 0))
        frame_count = len(endpoint.backend_frames)
        with self.assertRaises(DeviceBusy):
            transport.release()
        self.assertEqual(len(endpoint.backend_frames), frame_count)
        with self.assertRaises(DeviceBusy):
            transport.mem_write(0x800, b'x')
        readback = transport.mem_read(0x800, 64)
        self.assertEqual(readback, bo)
        ack_index_before = len(endpoint.backend_frames)
        self.assertTrue(any(opcode == 3 and address == 0x800
                            for _, opcode, address, _ in endpoint.backend_frames[:ack_index_before]))
        transport.ack_success()
        self.assertEqual(endpoint.backend_frames[ack_index_before][1:3], (2, 0x0C))
        self.assertIsNone(transport._active_tag)
        self.assertTrue(endpoint.release_ready)
        transport.release()
        self.assertTrue(session.released)
        self.assertEqual(endpoint.owner, 0)
        self.assertEqual(endpoint.memory[0x800:0x840], bo)

    def test_staged_descriptor_blocks_explicit_release_without_poison(self):
        endpoint, session, transport = self.make_transport()
        transport.reg_write(0x10, 0x200)
        before = list(endpoint.management_writes)
        with self.assertRaises(DeviceBusy):
            transport.release()
        self.assertEqual(endpoint.management_writes, before)
        self.assertEqual(before, [(0x60C, 1)])
        self.assertFalse(session.failed)
        self.assertFalse(transport._failed)

    def test_compute_reset_real_rkrs_sequence_and_memory_retention(self):
        endpoint, session, transport = self.make_transport()
        initial = bytes((i * 11 + 9) & 0xFF for i in range(512))
        endpoint.memory[:len(initial)] = initial
        receipt = transport.compute_reset(timeout=2.0)
        self.assertEqual(receipt.epoch_before, 7)
        self.assertEqual(receipt.epoch_after, 8)
        self.assertEqual(receipt.action_writes, ((0x50C, 1), (0x50C, 2)))
        self.assertEqual(receipt.status_reads, (0x31, 0x32, 0x36, 0x36, 0x32, 0x31))
        self.assertEqual(endpoint.reset_action_writes, [1, 2])
        self.assertIn(0x36, receipt.status_reads)  # result held until explicit ACK
        self.assertEqual(endpoint.memory[:len(initial)], initial)
        self.assertTrue(endpoint.release_ready)
        transport.release()
        self.assertEqual(endpoint.owner, 0)
        self.assertEqual(endpoint.memory[:len(initial)], initial)

    def test_close_never_releases_or_resets(self):
        endpoint, session, transport = self.make_transport()
        transport.close()
        transport.close()
        self.assertEqual(endpoint.closed, 1)
        self.assertEqual(endpoint.management_writes, [(0x60C, 1)])
        self.assertEqual(endpoint.reset_action_writes, [])
        self.assertEqual(endpoint.owner, 1)
        self.assertFalse(session.released)

    def test_backend_errors_malformed_payload_and_partial_io_poison(self):
        endpoint, session, transport = self.make_transport()
        endpoint.backend_error = 3
        with self.assertRaises(MailboxError):
            transport.reg_read(0x10)
        self.assertTrue(transport._failed)
        self.assertFalse(session.failed)  # correlated backend error frame remains transport-valid

        endpoint, session, transport = self.make_transport()
        endpoint.bad_read_payload = (0x10, 1 << 40)
        with self.assertRaises(ProtocolError):
            transport.reg_read(0x10)
        self.assertTrue(transport._failed)
        self.assertFalse(session.failed)

        endpoint, session, transport = self.make_transport()
        endpoint.fail_next_backend = EOFError('partial raw response')
        with self.assertRaises(EOFError):
            transport.reg_read(0x10)
        self.assertTrue(transport._failed)
        self.assertTrue(session.failed)

    def test_concurrent_command_and_release_return_devicebusy_before_io(self):
        endpoint, session, transport = self.make_transport()
        entered = threading.Event()
        unblock = threading.Event()
        operation_result = []
        def block(sequence, opcode, address, data):
            if address == 0x20:
                entered.set()
                if not unblock.wait(3):
                    return TimeoutError('bounded fake callback timed out')
                return response(sequence, 0, 0)
            return None
        endpoint.hook = block
        worker = threading.Thread(target=lambda: self._capture(operation_result,
            lambda: transport.reg_read(0x20)), daemon=True)
        contender = threading.Thread(target=lambda: operation_result.extend(self._contend(transport)), daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            before = len(endpoint.backend_frames)
            contender.start(); contender.join(0.5)
            self.assertFalse(contender.is_alive(), 'concurrent transport operations waited on the lock')
            self.assertEqual(len(endpoint.backend_frames), before)
        finally:
            unblock.set(); worker.join(3)
            if contender.ident is not None:
                contender.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(contender.is_alive())
        self.assertEqual(sum(isinstance(item, DeviceBusy) for item in operation_result), 2)
        self.assertFalse(transport._failed)
        self.assertFalse(session.failed)

    @staticmethod
    def _capture(output, operation):
        try:
            output.append(operation())
        except BaseException as error:
            output.append(error)

    @staticmethod
    def _contend(transport):
        output = []
        for operation in (lambda: transport.reg_read(0x24), transport.release):
            try:
                operation()
                output.append('unexpected success')
            except BaseException as error:
                output.append(error)
        return output


if __name__ == '__main__':
    unittest.main()
