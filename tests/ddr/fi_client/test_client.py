"""Device-free host ABI controls. This model does not verify the RTL or FPGA."""
import unittest
import threading
from tools.ddr.fi_client import (FiClient, ProtocolError, DeviceBusy, READY, INITIALIZED,
                       DISARMED, BOOTSTRAPPED, CLAIMED, GRANTED, RESULT, MATCHED,
                       PARENT_FAULT, LOCAL_FAULT)


class RegisterFixture:
    def __init__(self):
        self.reg = {0x300: 0x524B4649, 0x304: 0x10000, 0x3E0: 0,
                    0x3E4: 1 << 31, 0x3E8: 0x10040, 0x328: 0x1FF,
                    0x308: READY | INITIALIZED | DISARMED | BOOTSTRAPPED}
        self.events = []
        self.words = tuple((0x1020304 * i) & 0xFFFFFFFF for i in range(16))
        self.consumed = set()
        self.command = None
        self.timeout_submit = self.bad_match = self.bad_ordinal = False
        self.silent_mask = False

    def read(self, address, *, deadline):
        self.events.append(('read', address))
        if 0x3A0 <= address < 0x3E0:
            if self.command != 4 or not self.reg[0x308] & RESULT:
                raise ProtocolError('Result data not held')
            self.consumed.add(address)
            return self.words[(address - 0x3A0) // 4]
        return self.reg.get(address, 0)

    def write(self, address, value, *, deadline):
        self.events.append(('write', address, value))
        if address != 0x30C:
            self.reg[address] = value
            return
        if self.timeout_submit:
            raise TimeoutError('uncertain submitted command')
        if value == 5:
            if self.command == 4 and len(self.consumed) != 16:
                raise ProtocolError('Incomplete result readback')
            self.reg[0x308] &= ~(RESULT | MATCHED)
            self.reg[0x35C] = 0
            return
        self.command = value
        self.consumed.clear()
        status = self.reg[0x308] & (INITIALIZED | DISARMED | BOOTSTRAPPED | PARENT_FAULT)
        self.reg[0x308] = status | CLAIMED | GRANTED | RESULT | MATCHED
        response = self.reg.get(0x31C, 0) if value == 4 else 0
        self.reg[0x320] = value << 16 | (0 if self.bad_match else 1 << 8) | response
        if value != 1:
            self.reg[0x358] = self.reg.get(0x358, 0) + (2 if self.bad_ordinal else 1)
        if value == 2:
            a = self.reg[0x310]
            self.reg[0x354] = a
            if not self.silent_mask:
                self.reg[{0x300: 0x32C, 0x304: 0x330, 0x380: 0x334}[a]] = self.reg[0x314]
        if value in (3, 4):
            self.reg[0x350] = self.reg[0x318]


class Controls(unittest.TestCase):
    def setUp(self):
        self.fixture = RegisterFixture()
        self.client = FiClient(self.fixture.read, self.fixture.write)

    def own(self):
        result = self.client.claim()
        self.client.acknowledge(result)

    def test_construction_is_passive(self):
        self.assertEqual(self.fixture.events, [])

    def test_claim_is_held_and_cannot_repeat(self):
        result = self.client.claim()
        self.assertEqual(result.command, 1)
        self.assertEqual(result.ordinal, 0)
        self.assertEqual(result.raw_bytes, b'')
        self.assertFalse(any(e == ('write', 0x30C, 5) for e in self.fixture.events))
        with self.assertRaises(DeviceBusy):
            self.client.claim()

    def test_wrong_identity_never_claims(self):
        self.fixture.reg[0x300] = 0
        with self.assertRaises(ProtocolError):
            self.client.claim()
        self.assertFalse(any(e[0] == 'write' for e in self.fixture.events))

    def test_whole_raw_line_precedes_explicit_ack(self):
        self.own()
        before = len(self.fixture.events)
        result = self.client.read_line(64, expected_response=0)
        events = self.fixture.events[before:]
        self.assertEqual(result.words, self.fixture.words)
        self.assertEqual(result.raw_bytes, b''.join(w.to_bytes(4, 'little') for w in self.fixture.words))
        self.assertEqual([e[1] for e in events if e[0] == 'read' and 0x3A0 <= e[1] < 0x3E0],
                         list(range(0x3A0, 0x3E0, 4)))
        self.assertNotIn(('write', 0x30C, 5), events)
        self.client.acknowledge(result)
        self.assertEqual(len(self.fixture.consumed), 16)
        self.assertEqual(self.fixture.reg[0x308] & (CLAIMED | GRANTED), CLAIMED | GRANTED)

    def test_expected_ue_keeps_original_data_and_parent_fault(self):
        self.own()
        self.fixture.reg[0x308] |= PARENT_FAULT
        result = self.client.read_line(128, expected_response=2)
        self.assertEqual(result.words, self.fixture.words)
        self.assertEqual(result.response_word, 0x40102)
        self.assertTrue(result.status & PARENT_FAULT)
        self.client.acknowledge(result)

    def test_control_requires_actual_mask_witness(self):
        self.own()
        self.fixture.silent_mask = True
        with self.assertRaises(ProtocolError):
            self.client.control_write(0x300, 1)
        self.assertTrue(self.client.failed)
        self.assertEqual(self.fixture.reg[0x308] & RESULT, RESULT)

    def test_control_all_three_registers(self):
        self.own()
        for address, value in ((0x300, 0x80000001), (0x304, 0x12345678), (0x380, 0x80)):
            result = self.client.control_write(address, value)
            self.client.acknowledge(result)
        self.assertEqual(self.fixture.reg[0x358], 3)

    def test_line_write_preserves_all_words(self):
        self.own()
        result = self.client.write_line((1 << 31) - 64, self.fixture.words)
        self.assertEqual(result.command, 3)
        self.assertEqual(tuple(self.fixture.reg[0x360 + 4 * i] for i in range(16)), self.fixture.words)

    def test_invalid_requests_write_nothing(self):
        self.own()
        before = list(self.fixture.events)
        for callback in (
            lambda: self.client.read_line(1, expected_response=0),
            lambda: self.client.read_line(1 << 31, expected_response=0),
            lambda: self.client.read_line(0, expected_response=True),
            lambda: self.client.control_write(0x380, 256),
            lambda: self.client.control_write(0x308, 0),
            lambda: self.client.write_line(0, [0] * 15),
        ):
            with self.assertRaises(ValueError):
                callback()
        self.assertEqual(self.fixture.events, before)
        self.assertFalse(self.client.failed)

    def test_timeout_is_not_retried_or_acked(self):
        self.fixture.timeout_submit = True
        with self.assertRaises(TimeoutError):
            self.client.claim()
        self.assertTrue(self.client.failed)
        self.assertEqual([e for e in self.fixture.events if e[0] == 'write'], [('write', 0x30C, 1)])
        with self.assertRaises(ProtocolError):
            self.client.control_write(0x300, 0)

    def test_bad_result_and_ordinal_remain_held(self):
        for kind in ('bad_match', 'bad_ordinal'):
            fixture = RegisterFixture()
            client = FiClient(fixture.read, fixture.write)
            client.acknowledge(client.claim())
            setattr(fixture, kind, True)
            with self.assertRaises(ProtocolError):
                client.read_line(0, expected_response=0)
            self.assertTrue(client.failed)
            self.assertTrue(fixture.reg[0x308] & RESULT)

    def test_fault_while_held_prevents_ack(self):
        result = self.client.claim()
        self.fixture.reg[0x308] |= LOCAL_FAULT
        with self.assertRaises(ProtocolError):
            self.client.acknowledge(result)
        self.assertNotIn(('write', 0x30C, 5), self.fixture.events)

    def test_ack_rejects_other_receipt(self):
        result = self.client.claim()
        with self.assertRaises(ValueError):
            self.client.acknowledge(object())
        self.client.acknowledge(result)
        with self.assertRaises(ValueError):
            self.client.acknowledge(result)

    def test_waiting_call_preserves_first_held_result(self):
        self.own()
        entered, release, second_attempted = (threading.Event() for _ in range(3))
        original_read, original_operation = self.client._read_register, self.client._operation
        results, errors = {}, {}

        def read(address, *, deadline):
            if threading.current_thread().name == 'first' and address == 0x308 and not entered.is_set():
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('Test gate was not released')
            return original_read(address, deadline=deadline)

        def operation(*args, **kwargs):
            if threading.current_thread().name == 'second':
                second_attempted.set()
            return original_operation(*args, **kwargs)

        def call(label, address, value):
            try:
                results[label] = self.client.control_write(address, value)
            except BaseException as error:
                errors[label] = error

        self.client._read_register, self.client._operation = read, operation
        first = threading.Thread(target=call, args=('first', 0x300, 1), name='first')
        second = threading.Thread(target=call, args=('second', 0x304, 2), name='second')
        first.start()
        try:
            self.assertTrue(entered.wait(3))
            second.start()
            self.assertTrue(second_attempted.wait(3))
        finally:
            release.set()
            first.join(5)
            if second.ident is not None:
                second.join(5)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertNotIn('first', errors)
        self.assertIsInstance(errors['second'], DeviceBusy)
        self.assertFalse(self.client.failed)
        self.assertEqual(self.fixture.reg.get(0x358), 1)
        self.client.acknowledge(results['first'])


if __name__ == '__main__':
    unittest.main()
