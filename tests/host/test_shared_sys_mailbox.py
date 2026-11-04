"""Offline fake-wire checks for shared USER2/USER3 mailbox selection."""
import threading
import unittest

from tools.host.raw_jtag_frame import RawJtagFrameExchange, USER2_IR
from tools.host.sys_mailbox import ABI, CAP, MAGIC, ProtocolError, RKPR, USER3_IR
from tools.host.sys_mailbox_access import START
from tools.host.shared_sys_mailbox import SharedSysMailboxAccess, SharedSysMailboxProbe

IR_BITS = 6
DR_BITS = 640
FULL_STROBES = 0xF


def response(sequence, status=0, payload=0):
    return ((MAGIC << 536) | ((sequence & 0xFFFF) << 520) |
            ((status & 0xFF) << 512) | (payload & ((1 << 512) - 1)) )


def user2_read_frame(sequence, address=0x200):
    return ((MAGIC << 572) | ((sequence & 0xFFFF) << 556) | (1 << 548) |
            (FULL_STROBES << 544) | ((address & 0xFFFFFFFF) << 512))


class FakeSharedNativeLink:
    """Route each fake DR shift through the instruction currently selected."""
    def __init__(self, *, allow_user3=True, sys_sequence=41, user2_sequence=7):
        self.allow_user3 = allow_user3
        self._mutex = threading.RLock()
        self.selected_ir = None
        self.closed = False
        self.ir_selects = []
        self.events = []
        self.user3_dr_count = 0
        self.user2_dr_count = 0
        self.user3_baseline_count = 0
        self.user2_baseline_count = 0
        self.user3_pending = False
        self.user2_pending = False
        self.user3_requests = []
        self.user3_writes = []
        self.user2_requests = []
        self.user3_response = response(sys_sequence)
        self.user2_response = response(user2_sequence)
        self.user3_registers = {0x00: RKPR, 0x04: ABI, 0x08: 0x1357,
                                0x10: 0x2468, 0x14: 3, 0x18: 0,
                                0x1C: CAP, 0x20: 0, 0x24: 0,
                                0x28: 1000, 0x2C: 0}
        self.fail_next_ir = None
        self.failed_selector_count = 0

    def close(self):
        self.closed = True

    def scan(self, value, bits=640, *, ir=False, deadline=None):
        if not self._mutex._is_owned():
            raise AssertionError('borrowed link transaction lock is not held')
        if self.closed:
            raise ProtocolError('fake borrowed link is closed')
        self.events.append(('IR' if ir else 'DR', self.selected_ir, value, bits))
        if ir:
            if bits != IR_BITS or value not in (USER2_IR, USER3_IR):
                raise ProtocolError('unexpected fake IR select')
            self.ir_selects.append(value)
            if self.fail_next_ir == value:
                self.fail_next_ir = None
                self.failed_selector_count += 1
                raise ProtocolError('ambiguous USER3 selector result')
            self.selected_ir = value
            return 0
        if bits != DR_BITS:
            raise ProtocolError('unexpected fake DR width')
        if self.selected_ir == USER3_IR:
            self.user3_dr_count += 1
            return self._scan_user3(value)
        if self.selected_ir == USER2_IR:
            self.user2_dr_count += 1
            return self._scan_user2(value)
        raise ProtocolError('DR shift without an admitted USER2/USER3 instruction')

    def _scan_user3(self, frame):
        if frame == 0:
            if self.user3_pending:
                self.user3_pending = False
                return self.user3_response
            self.user3_baseline_count += 1
            return self.user3_response
        self.user3_requests.append(frame)
        old = self.user3_response
        address = (frame >> 512) & 0xFFFFFFFF
        opcode = (frame >> 548) & 0xFF
        sequence = (frame >> 556) & 0xFFFF
        strobes = (frame >> 544) & 0xF
        if strobes != FULL_STROBES or frame >> 604:
            raise AssertionError('malformed SYS frame')
        if opcode == 1:
            payload = self.user3_registers.get(address, 0)
            self.user3_response = response(sequence, 0, payload)
        elif opcode == 2:
            value = frame & 0xFFFFFFFF
            if address != 0x0C or value not in (START, 0x41434B21) or (frame >> 32) & ((1 << 480) - 1):
                raise AssertionError('SYS write escaped command whitelist')
            self.user3_writes.append((address, value))
            self.user3_response = response(sequence, 0, 0)
        else:
            raise AssertionError('unexpected SYS opcode')
        self.user3_pending = True
        return old

    def _scan_user2(self, frame):
        if frame == 0:
            if self.user2_pending:
                self.user2_pending = False
                return self.user2_response
            self.user2_baseline_count += 1
            return self.user2_response
        self.user2_requests.append(frame)
        old = self.user2_response
        if frame >> 604 or (frame >> 572) & 0xFFFFFFFF != MAGIC:
            raise AssertionError('malformed USER2 frame')
        sequence = (frame >> 556) & 0xFFFF
        self.user2_response = response(sequence, 0, 0x5A17)
        self.user2_pending = True
        return old


class SharedSysMailboxTests(unittest.TestCase):
    def _make_access(self, link):
        return SharedSysMailboxAccess(link, timeout=1.0, sleep=lambda _seconds: None)

    def _exchange_user2(self, link):
        carrier = RawJtagFrameExchange(link, timeout=1.0, sleep=lambda _seconds: None)
        initial = carrier.prepare()
        frame = user2_read_frame((initial % 0xFFFF) + 1)
        result = carrier.exchange(frame)
        return carrier, frame, result

    def test_same_sys_instance_reselects_after_real_user2_exchange_and_preserves_sequence(self):
        link = FakeSharedNativeLink(sys_sequence=41, user2_sequence=7)
        access = self._make_access(link)
        self.assertEqual(access.read_register(0x08), 0x1357)
        self.assertEqual(access._last_sequence, 42)
        carrier, user2_frame, user2_response = self._exchange_user2(link)
        self.assertEqual((user2_response >> 520) & 0xFFFF, 8)
        self.assertEqual(user2_response & 0xFFFFFFFF, 0x5A17)
        self.assertEqual(link.user2_requests, [user2_frame])
        self.assertEqual(((user2_frame >> 512) & 0xFFFFFFFF,
                          (user2_frame >> 548) & 0xFF), (0x200, 1))
        self.assertEqual(access.read_register(0x10), 0x2468)
        access.write_register(0x0C, START)
        self.assertEqual([((frame >> 556) & 0xFFFF) for frame in link.user3_requests],
                         [42, 43, 44, 45, 46, 47])
        self.assertEqual([((frame >> 512) & 0xFFFFFFFF, (frame >> 548) & 0xFF)
                          for frame in link.user3_requests],
                         [(0x08, 1), (0x10, 1), (0x00, 1), (0x04, 1), (0x1C, 1), (0x0C, 2)])
        self.assertEqual(access._last_sequence, 47)
        self.assertEqual(link.user3_baseline_count, 1, 'prepared SYS client must never rebaseline')
        self.assertEqual(link.user3_writes, [(0x0C, START)])
        self.assertEqual(link.ir_selects.count(USER3_IR), 6)
        self.assertEqual(link.ir_selects.count(USER2_IR), 2)
        self.assertGreater(link.user2_dr_count, 0)
        self.assertGreater(link.user3_dr_count, 0)
        access.close(); carrier.close()
        self.assertFalse(link.closed, 'both adapters borrow the link and must leave it open')

    def test_stale_sys_reply_after_user2_switch_poisons_without_rebaseline(self):
        link = FakeSharedNativeLink(sys_sequence=90)
        access = SharedSysMailboxProbe(link, timeout=1.0, sleep=lambda _seconds: None)
        self.assertEqual(access.read_register(0x08), 0x1357)
        carrier, _frame, _response = self._exchange_user2(link)
        link.user3_response = response(90, 0, 0)
        with self.assertRaisesRegex(ProtocolError, 'Stale or concurrent SYS response changed'):
            access.read_register(0x10)
        self.assertTrue(access._failed)
        self.assertEqual(link.user3_baseline_count, 1)
        self.assertEqual(len(link.user3_requests), 2)
        self.assertEqual(link.user3_writes, [])
        access.close(); carrier.close()
        self.assertFalse(link.closed)

    def test_ambiguous_user3_select_poisons_reset_without_start_retry(self):
        link = FakeSharedNativeLink(sys_sequence=120)
        access = self._make_access(link)
        access.read_register(0x08)
        carrier, _frame, _response = self._exchange_user2(link)
        link.fail_next_ir = USER3_IR
        with self.assertRaisesRegex(ProtocolError, 'ambiguous USER3 selector result'):
            access.perform_reset(timeout=1.0)
        self.assertTrue(access._failed)
        self.assertEqual(link.failed_selector_count, 1)
        self.assertEqual(link.user3_writes, [], 'ambiguous selection must fail before START')
        user3_selects = link.ir_selects.count(USER3_IR)
        with self.assertRaisesRegex(ProtocolError, 'closed or poisoned'):
            access.write_register(0x0C, START)
        self.assertEqual(link.failed_selector_count, 1)
        self.assertEqual(link.ir_selects.count(USER3_IR), user3_selects, 'poisoned SYS client must not retry select')
        self.assertEqual(link.user3_writes, [])
        access.close(); carrier.close()
        self.assertFalse(link.closed)

    def test_default_user3_opt_in_rejection_is_preserved(self):
        link = FakeSharedNativeLink(allow_user3=False)
        with self.assertRaisesRegex(ValueError, 'explicitly opt in to USER3'):
            SharedSysMailboxProbe(link)
        with self.assertRaisesRegex(ValueError, 'explicitly opt in to USER3'):
            SharedSysMailboxAccess(link)
        self.assertEqual(link.events, [])
        self.assertFalse(link.closed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
