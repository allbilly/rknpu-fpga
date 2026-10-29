"""Strict callback-only controls for RawFrameSession; no hardware or socket access."""
import threading
import unittest

from tools.host.transport import DeviceBusy, ProtocolError, _Deadline
from tools.host.raw_frame_session import (
    ABI_REG, ABI_VERSION, CAPABILITIES_REG, CAPABILITIES, CONTROL_REG,
    EPOCH_REG, FAILURE_REG, IDENTITY_REG, MAGIC, RKHO_ID, REQUESTER_REG,
    STATUS_REG, RawFrameSession,
)


class Clock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, value):
        self.value += value


def raw_request(sequence, opcode, address, data=0, strobes=0xF):
    return ((MAGIC << 572) | (sequence << 556) | (opcode << 548) |
            (strobes << 544) | (address << 512) | data)


def raw_response(sequence, status=0, data=0):
    return (MAGIC << 536) | (sequence << 520) | (status << 512) | data


class FakeRKHO:
    def __init__(self, source=1, clock=None):
        self.source = source
        self.clock = clock or Clock()
        self.regs = {IDENTITY_REG: RKHO_ID, ABI_REG: ABI_VERSION,
                     CAPABILITIES_REG: CAPABILITIES, STATUS_REG: 8,
                     EPOCH_REG: 5, REQUESTER_REG: source, FAILURE_REG: 0}
        self.writes = []
        self.frames = []
        self.closed = 0
        self.exchange_hook = None
        self.mutate = None
        self.session = None

    def close(self):
        self.closed += 1

    def exchange(self, frame, *, deadline):
        self.frames.append((frame, deadline))
        if self.exchange_hook is not None:
            result = self.exchange_hook(frame, deadline)
            if result is not None:
                return result
        sequence = (frame >> 556) & 0xFFFF
        opcode = (frame >> 548) & 0xFF
        address = (frame >> 512) & 0xFFFFFFFF
        data = frame & ((1 << 512) - 1)
        if opcode in (1, 2) and address >> 8 == 6:
            status = 0
            value = 0
            if opcode == 1:
                value = self.regs.get(address, 0)
            elif opcode == 2 and address == CONTROL_REG:
                self.writes.append(data)
                command = data & 0xFFFFFFFF
                if data >> 32 or self.regs[STATUS_REG] & 8 == 0:
                    status = 2
                elif command == 1 and self.regs[STATUS_REG] & 3 == 0:
                    self.regs[EPOCH_REG] += 1
                    self.regs[STATUS_REG] = 8 | self.source
                elif command == 2 and self.regs[STATUS_REG] & 3 == self.source:
                    self.regs[STATUS_REG] = 8
                else:
                    status = 2
            else:
                status = 3
            response = raw_response(sequence, status, value if status == 0 else 0)
            return self.mutate(frame, response) if self.mutate else response
        if self.exchange_hook is not None:
            return self.exchange_hook(frame, deadline)
        return raw_response((frame >> 556) & 0xFFFF, 0, 0xABC)


def new_session(fake, source=1, **kwargs):
    return RawFrameSession(fake.exchange, close=fake.close, source=source,
                           clock=fake.clock, **kwargs)


class RawFrameSessionTests(unittest.TestCase):
    def test_probe_order_one_budget_and_confirmed_acquire(self):
        fake = FakeRKHO(source=2)
        session = new_session(fake, source=2, timeout=10.0)
        observed = [((frame >> 548) & 0xFF, (frame >> 512) & 0xFFFFFFFF)
                    for frame, _ in fake.frames]
        self.assertEqual(observed, [(1, IDENTITY_REG), (1, ABI_REG), (1, CAPABILITIES_REG),
            (1, REQUESTER_REG), (1, FAILURE_REG), (1, STATUS_REG), (1, EPOCH_REG),
            (2, CONTROL_REG), (1, STATUS_REG), (1, EPOCH_REG), (1, FAILURE_REG)])
        self.assertEqual(fake.writes, [1])
        self.assertEqual(session.epoch, 6)
        self.assertTrue(all(deadline.clock is fake.clock for _, deadline in fake.frames))
        self.assertIs(fake.frames[0][1], fake.frames[-1][1])

    def test_acquire_confirmation_allows_release_witness_to_drop(self):
        fake = FakeRKHO()
        def witness_drops_after_acquire(frame, deadline):
            opcode = (frame >> 548) & 0xFF
            address = (frame >> 512) & 0xFFFFFFFF
            if opcode == 1 and address == STATUS_REG and fake.writes:
                fake.regs[STATUS_REG] = 1
                return raw_response((frame >> 556) & 0xFFFF, 0, 1)
            return None
        fake.exchange_hook = witness_drops_after_acquire
        session = new_session(fake)
        self.assertEqual(session.epoch, 6)
        self.assertEqual(fake.writes, [1])
        self.assertFalse(session.failed)

    def test_preflight_rejections_issue_no_writes_and_close(self):
        for address, value, source, error in (
            (IDENTITY_REG, 0, 1, ProtocolError), (ABI_REG, 7, 1, ProtocolError),
            (CAPABILITIES_REG, 1, 1, ProtocolError), (REQUESTER_REG, 2, 1, ProtocolError),
            (STATUS_REG, 9, 1, DeviceBusy), (STATUS_REG, 0, 1, DeviceBusy), (STATUS_REG, 0x18, 1, ProtocolError),
            (STATUS_REG, 0xC, 1, ProtocolError),
            (EPOCH_REG, 0xFFFFFFFF, 1, ProtocolError),
        ):
            with self.subTest(address=address, value=value):
                fake = FakeRKHO(source=source)
                fake.regs[address] = value
                with self.assertRaises(error):
                    new_session(fake, source=source)
                self.assertEqual(fake.writes, [])
                self.assertEqual(fake.closed, 1)

    def test_source_and_timeout_validation_close_without_io(self):
        fake = FakeRKHO()
        with self.assertRaises(ValueError):
            new_session(fake, source=True)
        self.assertEqual(fake.frames, [])
        self.assertEqual(fake.closed, 1)
        fake = FakeRKHO()
        with self.assertRaises(ValueError):
            new_session(fake, timeout=0)
        self.assertEqual(fake.frames, [])
        self.assertEqual(fake.closed, 1)

    def test_exact_backend_frame_forwarding_and_valid_error_return(self):
        fake = FakeRKHO()
        session = new_session(fake)
        request = raw_request(0xCAFE, 0x40, 0x12345678, 0x55)
        expected = raw_response(0xCAFE, 7, 0)
        fake.exchange_hook = lambda frame, deadline: expected
        self.assertEqual(session.exchange(request), expected)
        self.assertEqual(fake.frames[-1][0], request)
        self.assertFalse(session.failed)

    def test_management_page_rejected_only_for_register_opcodes(self):
        fake = FakeRKHO()
        session = new_session(fake)
        count = len(fake.frames)
        for opcode in (1, 2):
            with self.subTest(opcode=opcode):
                with self.assertRaises(ValueError):
                    session.exchange(raw_request(3 + opcode, opcode, 0x600))
        self.assertEqual(len(fake.frames), count)
        self.assertFalse(session.failed)

    def test_data_opcodes_at_management_page_forward_unchanged(self):
        fake = FakeRKHO()
        session = new_session(fake)
        for opcode, address in ((3, 0x600), (4, 0x640)):
            with self.subTest(opcode=opcode, address=address):
                request = raw_request(0x70 + opcode, opcode, address, 0xA55A)
                response = raw_response(0x70 + opcode, 0, 0xABC)
                fake.exchange_hook = lambda frame, deadline, response=response: response
                self.assertEqual(session.exchange(request), response)
                self.assertEqual(fake.frames[-1][0], request)
        self.assertFalse(session.failed)

    def test_invalid_backend_request_is_rejected_before_io(self):
        fake = FakeRKHO()
        session = new_session(fake)
        count = len(fake.frames)
        for frame in (True, 1 << 640, raw_request(1, 0x40, 0x100) | (1 << 604),
                      raw_request(1, 0x40, 0x100) ^ (1 << 572)):
            with self.subTest(frame=frame):
                with self.assertRaises((TypeError, ValueError)):
                    session.exchange(frame)
        self.assertEqual(len(fake.frames), count)
        self.assertFalse(session.failed)

    def test_management_error_payload_is_rejected(self):
        fake = FakeRKHO()
        fake.mutate = lambda frame, response: (
            raw_response((frame >> 556) & 0xFFFF, 2, 1)
            if ((frame >> 548) & 0xFF, (frame >> 512) & 0xFFFFFFFF) == (1, IDENTITY_REG)
            else response)
        with self.assertRaises(ProtocolError):
            new_session(fake)
        self.assertEqual(fake.writes, [])
        self.assertEqual(fake.closed, 1)

    def test_bad_backend_responses_poison(self):
        variants = (
            lambda seq: raw_response(seq, 0, 1) | (1 << 639),
            lambda seq: raw_response(seq, 0, 1) ^ (1 << 536),
            lambda seq: raw_response((seq + 1) & 0xFFFF, 0, 1),
            lambda seq: raw_response(seq, 2, 1),
            lambda seq: 1 << 640,
        )
        for malformed in variants:
            with self.subTest():
                fake = FakeRKHO()
                session = new_session(fake)
                request = raw_request(9, 0x40, 0x100)
                fake.exchange_hook = lambda frame, deadline, malformed=malformed: malformed((frame >> 556) & 0xFFFF)
                with self.assertRaises(ProtocolError):
                    session.exchange(request)
                self.assertTrue(session.failed)
                with self.assertRaises(ProtocolError):
                    session.exchange(request)

    def test_transport_exception_poison_and_partial_call_is_not_retried(self):
        fake = FakeRKHO()
        session = new_session(fake)
        before = len(fake.frames)
        def fail(frame, deadline):
            address = (frame >> 512) & 0xFFFFFFFF
            if not 0x600 <= address <= 0x6FF:
                raise EOFError('partial transport failure')
            return None
        fake.exchange_hook = fail
        with self.assertRaises(EOFError):
            session.exchange(raw_request(10, 0x40, 0x100))
        self.assertTrue(session.failed)
        self.assertEqual(len(fake.frames), before + 1)

    def test_held_release_refuses_without_poison_and_can_finish_then_release(self):
        fake = FakeRKHO()
        session = new_session(fake)
        fake.regs[STATUS_REG] = 1  # This source still owns the lease, but release_ready is low.
        writes_before = list(fake.writes)
        with self.assertRaises(DeviceBusy):
            session.release()
        self.assertEqual(fake.writes, writes_before)
        self.assertFalse(session.failed)
        fake.regs[STATUS_REG] = 9
        self.assertEqual(session.exchange(raw_request(12, 0x40, 0x200)),
                         raw_response(12, 0, 0xABC))
        session.release()
        self.assertEqual(fake.writes, [1, 2])
        self.assertTrue(session.released)
        with self.assertRaises(ProtocolError):
            session.exchange(raw_request(13, 0x40, 0x200))

    def test_successful_release_is_confirmed_and_close_never_releases(self):
        fake = FakeRKHO()
        session = new_session(fake)
        session.close()
        session.close()
        self.assertEqual(fake.writes, [1])
        self.assertEqual(fake.closed, 1)
        self.assertFalse(session.released)
        with self.assertRaises(ProtocolError):
            session.exchange(raw_request(1, 0x40, 0x100))

    def test_release_owner_epoch_or_fault_mismatch_poisons(self):
        for address, value in ((STATUS_REG, 10), (EPOCH_REG, 99), (FAILURE_REG, 1)):
            with self.subTest(address=address):
                fake = FakeRKHO()
                session = new_session(fake)
                fake.regs[address] = value
                with self.assertRaises(ProtocolError):
                    session.release()
                self.assertTrue(session.failed)
                self.assertEqual(fake.writes, [1])

    def test_release_confirmation_allows_ready_bit_to_drop(self):
        for status in (0, 8):
            with self.subTest(status=status):
                fake = FakeRKHO()
                session = new_session(fake)
                def release_status(frame, deadline):
                    opcode = (frame >> 548) & 0xFF
                    address = (frame >> 512) & 0xFFFFFFFF
                    if opcode == 1 and address == STATUS_REG and fake.writes == [1, 2]:
                        return raw_response((frame >> 556) & 0xFFFF, 0, status)
                    return None
                fake.exchange_hook = release_status
                session.release()
                self.assertTrue(session.released)
                self.assertFalse(session.failed)
                self.assertEqual(fake.writes, [1, 2])

    def test_release_confirmation_rejects_owner_fault_or_reserved_status(self):
        for status in (1, 2, 3, 4, 0x10):
            with self.subTest(status=status):
                fake = FakeRKHO()
                session = new_session(fake)
                def bad_release_status(frame, deadline):
                    opcode = (frame >> 548) & 0xFF
                    address = (frame >> 512) & 0xFFFFFFFF
                    if opcode == 1 and address == STATUS_REG and fake.writes == [1, 2]:
                        return raw_response((frame >> 556) & 0xFFFF, 0, status)
                    return None
                fake.exchange_hook = bad_release_status
                with self.assertRaises(ProtocolError):
                    session.release()
                self.assertTrue(session.failed)
                self.assertEqual(fake.writes, [1, 2])

    def test_rejected_release_snapshot_reads_poison_without_release_write(self):
        for address in (STATUS_REG, EPOCH_REG, REQUESTER_REG, FAILURE_REG):
            with self.subTest(address=address):
                fake = FakeRKHO()
                session = new_session(fake)
                def reject_read(frame, deadline):
                    opcode = (frame >> 548) & 0xFF
                    register = (frame >> 512) & 0xFFFFFFFF
                    if opcode == 1 and register == address:
                        return raw_response((frame >> 556) & 0xFFFF, 2, 0)
                    return None
                fake.exchange_hook = reject_read
                with self.assertRaises(ProtocolError):
                    session.release()
                self.assertTrue(session.failed)
                self.assertEqual(fake.writes, [1])
                with self.assertRaises(ProtocolError):
                    session.exchange(raw_request(0x56, 0x40, 0x100))
                self.assertEqual(fake.writes, [1])

    def test_management_busy_during_release_confirmation_poisons(self):
        fake = FakeRKHO()
        session = new_session(fake)
        def busy_confirmation(frame, deadline):
            opcode = (frame >> 548) & 0xFF
            address = (frame >> 512) & 0xFFFFFFFF
            if opcode == 1 and address == STATUS_REG and fake.writes == [1, 2]:
                return raw_response((frame >> 556) & 0xFFFF, 2, 0)
            return None
        fake.exchange_hook = busy_confirmation
        with self.assertRaises(ProtocolError):
            session.release()
        self.assertTrue(session.failed)
        self.assertEqual(fake.writes, [1, 2])
        with self.assertRaises(ProtocolError):
            session.exchange(raw_request(44, 0x40, 0x100))
        self.assertEqual(fake.writes, [1, 2])

    def test_release_write_without_confirmed_clear_poisons(self):
        fake = FakeRKHO()
        session = new_session(fake)
        def hold_owner(frame, deadline):
            if ((frame >> 548) & 0xFF, (frame >> 512) & 0xFFFFFFFF) == (2, CONTROL_REG):
                sequence = (frame >> 556) & 0xFFFF
                return raw_response(sequence)
            return None
        fake.exchange_hook = hold_owner
        with self.assertRaises(ProtocolError):
            session.release()
        self.assertTrue(session.failed)

    def test_post_acquire_mismatch_closes_without_compensating_release(self):
        fake = FakeRKHO()
        def bad_epoch(frame, response):
            if ((frame >> 548) & 0xFF, (frame >> 512) & 0xFFFFFFFF) == (1, EPOCH_REG) and fake.writes:
                response = raw_response((frame >> 556) & 0xFFFF, 0, 99)
            return response
        fake.mutate = bad_epoch
        with self.assertRaises(ProtocolError):
            new_session(fake)
        self.assertEqual(fake.writes, [1])
        self.assertEqual(fake.closed, 1)

    def test_deadline_expiry_and_clock_mismatch_before_io(self):
        fake = FakeRKHO()
        session = new_session(fake)
        count = len(fake.frames)
        foreign_clock = Clock()
        with self.assertRaises(ValueError):
            session.exchange(raw_request(1, 0x40, 0x100), deadline=_Deadline(1, foreign_clock))
        self.assertEqual(len(fake.frames), count)
        expired = _Deadline(0.1, fake.clock)
        fake.clock.advance(1)
        with self.assertRaises(TimeoutError):
            session.exchange(raw_request(1, 0x40, 0x100), deadline=expired)
        self.assertEqual(len(fake.frames), count)
        self.assertFalse(session.failed)

    def test_other_thread_operations_fail_fast_while_exchange_callback_is_held(self):
        fake = FakeRKHO()
        session = new_session(fake)
        entered = threading.Event()
        unblock = threading.Event()
        owner_result = []
        contender_result = []

        def blocking_callback(frame, deadline):
            if ((frame >> 512) & 0xFFFFFFFF) == 0x200:
                entered.set()
                if not unblock.wait(3):
                    raise TimeoutError('bounded test callback wait expired')
                return raw_response((frame >> 556) & 0xFFFF, 0, 0x77)
            return None

        def owner_call():
            try:
                owner_result.append(session.exchange(raw_request(0x61, 0x40, 0x200)))
            except BaseException as error:
                owner_result.append(error)

        def contended_calls():
            for operation in (
                lambda: session.exchange(raw_request(0x62, 0x40, 0x300)),
                session.release,
            ):
                try:
                    operation()
                    contender_result.append('unexpected success')
                except BaseException as error:
                    contender_result.append(error)

        fake.exchange_hook = blocking_callback
        owner = threading.Thread(target=owner_call, daemon=True)
        contender = threading.Thread(target=contended_calls, daemon=True)
        owner.start()
        try:
            self.assertTrue(entered.wait(1), 'owner callback did not enter')
            frame_count = len(fake.frames)
            contender.start()
            contender.join(0.5)
            self.assertFalse(contender.is_alive(), 'contending operations blocked on the session lock')
            self.assertEqual(len(fake.frames), frame_count, 'contending operations performed I/O')
        finally:
            unblock.set()
            owner.join(3)
            if contender.ident is not None:
                contender.join(3)
        self.assertFalse(owner.is_alive(), 'bounded owner callback did not finish')
        self.assertFalse(contender.is_alive(), 'contender thread did not finish')
        self.assertEqual(len(contender_result), 2)
        self.assertTrue(all(isinstance(error, DeviceBusy) for error in contender_result))
        self.assertEqual(owner_result, [raw_response(0x61, 0, 0x77)])
        self.assertFalse(session.failed)

    def test_callback_receives_same_deadline_and_reentrant_exchange_is_rejected(self):
        fake = FakeRKHO()
        session = new_session(fake)
        request = raw_request(31, 0x40, 0x100)
        nested = []
        def reentrant(frame, deadline):
            if ((frame >> 512) & 0xFFFFFFFF) == 0x100:
                with self.assertRaises(DeviceBusy):
                    session.exchange(raw_request(32, 0x40, 0x200), deadline=deadline)
                nested.append(frame)
                return raw_response((frame >> 556) & 0xFFFF, 0, 0x123)
            return None
        fake.exchange_hook = reentrant
        deadline = _Deadline(5, fake.clock)
        self.assertEqual(session.exchange(request, deadline=deadline), raw_response(31, 0, 0x123))
        self.assertEqual(nested, [request])
        self.assertIs(fake.frames[-1][1], deadline)

    def test_malformed_management_probe_poison_closes_without_write(self):
        fake = FakeRKHO()
        def malformed(frame, response):
            if ((frame >> 548) & 0xFF, (frame >> 512) & 0xFFFFFFFF) == (1, IDENTITY_REG):
                return response | (1 << 639)
            return response
        fake.mutate = malformed
        with self.assertRaises(ProtocolError):
            new_session(fake)
        self.assertEqual(fake.writes, [])
        self.assertEqual(fake.closed, 1)


if __name__ == '__main__':
    unittest.main()
