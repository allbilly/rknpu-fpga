import pathlib
import sys
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
from tools.ddr import compute_reset as reset, framework_transport as transport

from tools.host.transport import DeviceBusy, ProtocolError, _Deadline


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        self.value += 0.001
        return self.value


class ScriptIO:
    """Only scripted raw register operations are available to a test."""
    def __init__(self):
        self.values = {}
        self.events = []
        self.deadlines = []
        self.closed = False
        self.fail_at = None

    def add(self, address, *values):
        self.values.setdefault(address, []).extend(values)

    def command(self, opcode, address, value=None, *, deadline=None):
        if deadline is not None:
            self.deadlines.append(deadline)
        event = ("r", address) if opcode == 1 else ("w", address, value)
        self.events.append(event)
        if self.fail_at == len(self.events):
            raise OSError("scripted raw protocol failure")
        if opcode == 1:
            queue = self.values.get(address, [])
            if not queue:
                raise AssertionError("unexpected/exhausted register read %#x" % address)
            result = queue.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        if opcode != 2:
            raise AssertionError("unexpected opcode")
        return None

    def no_nonregister_io(self, name):
        if any(part in name.lower() for part in ("bo", "buffer", "memory", "connect", "recover", "device", "socket")):
            raise AssertionError("non-register operation requested: " + name)
        raise AttributeError(name)


def profile_identity(io, profile):
    base, ident = transport.PROFILES[profile]
    io.add(base, ident)
    io.add(base + 4, transport.ABI_VERSION)


def reset_identity(io):
    io.add(0x500, 0x524B5253)
    io.add(0x504, 0x10000)
    io.add(0x518, 0x10004)


def reset_success(io, epoch=7):
    # All three job profiles are idle before and after reset.
    for profile in ("ew", "cmac", "layout"):
        io.add(transport.PROFILES[profile][0] + 8, 0x10, 0x10)
    reset_identity(io)
    reset_identity(io)
    io.add(0x510, epoch, epoch, epoch + 1, epoch + 1)
    io.add(0x508, 0x31, 0x32, 0x36, 0x36, 0x32, 0x31)
    io.add(0x514, 0)


class FullDdrRawTransportTests(unittest.TestCase):
    def make_owner(self, io, *, clock=None, timeout=5.0):
        old_init = transport.DualDdrRawTransport.__init__

        def fake_init(owner, host="localhost", port=3721, timeout=30.0, *,
                      frequency_hz=None, link=None, clock=None, sleep=None):
            owner._profile = "ew"
            owner._mutex = threading.RLock()
            owner._active_tag = None
            owner._result = None
            owner._failed = False
            owner.link = object()
            owner.timeout = timeout
            owner._clock = clock
            owner._script = io
            owner._command = lambda op, address, value=None, *, deadline=None: io.command(
                op, address, value, deadline=deadline)
            owner.close = lambda: setattr(io, "closed", True)

        transport.DualDdrRawTransport.__init__ = fake_init
        try:
            return transport.FullDdrRawTransport(timeout=timeout, link=object(),
                                                 clock=clock or Clock())
        finally:
            transport.DualDdrRawTransport.__init__ = old_init

    def test_missing_link_fails_before_parent_constructor(self):
        called = []
        old = transport.DualDdrRawTransport.__init__
        transport.DualDdrRawTransport.__init__ = lambda *a, **k: called.append(True)
        try:
            with self.assertRaises(ValueError):
                transport.FullDdrRawTransport()
        finally:
            transport.DualDdrRawTransport.__init__ = old
        self.assertEqual(called, [])

    def test_constructor_reads_exact_three_profile_and_reset_identities_only(self):
        io = ScriptIO()
        profile_identity(io, "layout")
        reset_identity(io)
        owner = self.make_owner(io)
        self.assertEqual(io.events, [("r", a) for a in
            (0x400, 0x404, 0x500, 0x504, 0x518)])
        self.assertFalse(any(e[0] == "w" for e in io.events))
        self.assertEqual(owner.profile, "ew")

    def test_bad_layout_identity_or_reset_identity_closes_without_writes(self):
        for address, bad in ((0x400, 0), (0x404, 7), (0x500, 0), (0x504, 2), (0x518, 0)):
            with self.subTest(address=hex(address)):
                io = ScriptIO()
                for p in ("ew", "cmac", "layout"):
                    profile_identity(io, p)
                reset_identity(io)
                io.values[address] = [bad]
                with self.assertRaises(ProtocolError):
                    self.make_owner(io)
                self.assertTrue(io.closed)
                self.assertFalse(any(e[0] == "w" for e in io.events))

    def test_select_checks_all_three_idle_and_preserves_staged_peer(self):
        io = ScriptIO()
        for p in ("ew", "cmac", "layout"):
            profile_identity(io, p)
        reset_identity(io)
        owner = self.make_owner(io)
        io.events.clear()
        # idle reads in fixed order, then selected identity; no descriptor writes.
        for p in ("ew", "cmac", "layout"):
            io.add(transport.PROFILES[p][0] + 8, 0x10)
        profile_identity(io, "layout")
        owner.select_profile("layout")
        self.assertEqual(owner.profile, "layout")
        self.assertEqual(io.events, [("r", 8), ("r", 0x108), ("r", 0x408),
                                     ("r", 0x400), ("r", 0x404)])
        self.assertFalse(any(e[0] == "w" for e in io.events))

    def test_select_busy_peer_fails_poisoned_and_retains_profile(self):
        for bad in (0x11, 0x12, 0x30, 0x32, 0x36):
            with self.subTest(status=hex(bad)):
                io = ScriptIO()
                for p in ("ew", "cmac", "layout"):
                    profile_identity(io, p)
                reset_identity(io)
                owner = self.make_owner(io)
                io.add(8, 0x10); io.add(0x108, bad)
                with self.assertRaises(DeviceBusy):
                    owner.select_profile("layout")
                self.assertTrue(owner._failed)
                self.assertEqual(owner.profile, "ew")
                self.assertFalse(any(e[0] == "w" for e in io.events))

    def test_relative_register_access_uses_selected_base(self):
        io = ScriptIO()
        for p in ("ew", "cmac", "layout"):
            profile_identity(io, p)
        reset_identity(io)
        owner = self.make_owner(io)
        for p in ("ew", "cmac", "layout"):
            io.add(transport.PROFILES[p][0] + 8, 0x10)
        owner.select_profile("cmac")
        io.add(0x110, 0xA5)
        self.assertEqual(owner.reg_read(0x10), 0xA5)
        owner.reg_write(0x14, 0x1234)
        self.assertEqual(io.events[-2:], [("r", 0x110), ("w", 0x114, 0x1234)])

    def test_invalid_profiles_registers_values_and_booleans_rejected(self):
        io = ScriptIO()
        for p in ("ew", "cmac", "layout"):
            profile_identity(io, p)
        reset_identity(io)
        owner = self.make_owner(io)
        for profile in (None, True, "EW", "int8", 1):
            with self.subTest(profile=repr(profile)), self.assertRaises(ValueError):
                owner.select_profile(profile)
        for offset in (True, -1, 1, 0x0C, 0x100000000):
            with self.subTest(offset=repr(offset)), self.assertRaises(ValueError):
                owner.reg_read(offset)
        for offset, value in ((True, 1), (1, 1), (0x0C, 0), (0x0C, True), (0x10, -1), (0x10, 1 << 32)):
            with self.subTest(offset=repr(offset), value=repr(value)), self.assertRaises(ValueError):
                owner.reg_write(offset, value)

    def test_active_tag_or_result_prevents_namespace_and_reset_change(self):
        for field, value in (("_active_tag", 8), ("_result", object())):
            for operation in ("select", "reset"):
                with self.subTest(field=field, operation=operation):
                    io = ScriptIO()
                    for p in ("ew", "cmac", "layout"):
                        profile_identity(io, p)
                    reset_identity(io)
                    owner = self.make_owner(io)
                    setattr(owner, field, value)
                    before = list(io.events)
                    with self.assertRaises(DeviceBusy):
                        owner.select_profile("layout") if operation == "select" else owner.compute_reset()
                    self.assertEqual(io.events, before)

    def test_reset_success_is_raw_only_shared_deadline_and_records_frozen_receipt(self):
        io = ScriptIO()
        for p in ("ew", "cmac", "layout"):
            profile_identity(io, p)
        reset_success(io)
        clock = Clock()
        owner = self.make_owner(io, clock=clock, timeout=8.0)
        io.events.clear(); io.deadlines.clear()
        receipt = owner.compute_reset(timeout=2.5)
        expected_writes = [("w", 0x50C, 1), ("w", 0x50C, 2)]
        self.assertEqual([e for e in io.events if e[0] == "w"], expected_writes)
        self.assertEqual(receipt.epoch_before, 7)
        self.assertEqual(receipt.epoch_after, 8)
        self.assertEqual(receipt.status_reads, (0x31, 0x32, 0x36, 0x36, 0x32, 0x31))
        self.assertEqual(receipt.action_writes, ((0x50C, 1), (0x50C, 2)))
        self.assertTrue(type(receipt).__dataclass_params__.frozen)
        self.assertEqual(owner.reset_receipts, [receipt])
        self.assertTrue(io.deadlines)
        self.assertTrue(all(d is io.deadlines[0] for d in io.deadlines))
        self.assertIs(io.deadlines[0].clock, clock)
        self.assertEqual(io.deadlines[0].stop, 2.502)
        idle_reads = [e for e in io.events if e[0] == "r" and e[1] in (8, 0x108, 0x408)]
        self.assertEqual(len(idle_reads), 6)

    def test_reset_bad_identity_or_nonidle_preflight_no_write_and_poison(self):
        for bad_addr, bad in ((0x500, 0), (0x504, 0), (0x518, 1), (0x108, 0x11)):
            with self.subTest(address=hex(bad_addr)):
                io = ScriptIO()
                for p in ("ew", "cmac", "layout"):
                    profile_identity(io, p)
                reset_identity(io)
                reset_identity(io)
                for p in ("ew", "cmac", "layout"):
                    io.add(transport.PROFILES[p][0] + 8, 0x10)
                if bad_addr == 0x108:
                    io.values[bad_addr] = [bad]
                else:
                    io.values[bad_addr][1] = bad
                owner = self.make_owner(io)
                io.events.clear()
                with self.assertRaises((ProtocolError, DeviceBusy)):
                    owner.compute_reset()
                self.assertTrue(owner._failed)
                self.assertFalse(any(e[0] == "w" for e in io.events))
                self.assertEqual(owner.reset_receipts, [])

    def test_reset_failures_poison_and_never_implicit_recovery_or_ack_after_fault(self):
        # Fail each operation point in a valid reset transcript. The error must
        # poison ownership; no subsequent retry/ACK is allowed by this call.
        for failing_event in (9, 10, 11, 16):
            with self.subTest(event=failing_event):
                io = ScriptIO()
                for p in ("ew", "cmac", "layout"):
                    profile_identity(io, p)
                reset_success(io)
                owner = self.make_owner(io)
                io.events.clear()
                io.fail_at = failing_event
                with self.assertRaises(OSError):
                    owner.compute_reset()
                self.assertTrue(owner._failed)
                self.assertEqual(owner.reset_receipts, [])
                if failing_event < 16:
                    self.assertNotIn(("w", 0x50C, 2), io.events)

    def test_reset_timeout_values_rejected_before_io(self):
        for value in (True, False, 0, -1, float("nan"), float("inf"), -float("inf"), "1"):
            with self.subTest(value=repr(value)):
                io = ScriptIO()
                for p in ("ew", "cmac", "layout"):
                    profile_identity(io, p)
                reset_identity(io)
                owner = self.make_owner(io)
                before = list(io.events)
                with self.assertRaises(ValueError):
                    owner.compute_reset(timeout=value)
                self.assertEqual(io.events, before)
                self.assertFalse(owner._failed)


class ResetClientCompatibilityTests(unittest.TestCase):
    def raw_reset(self, *, status=None, epochs=None, result=None, fail_at=None):
        io = ScriptIO()
        reset_identity(io)
        io.add(0x510, *(epochs if epochs is not None else (7, 7, 8, 8)))
        io.add(0x508, *(status if status is not None else (0x31, 0x32, 0x36, 0x36, 0x32, 0x31)))
        io.add(0x514, *(result if result is not None else (0,)))
        io.fail_at = fail_at
        def read(address, *, deadline):
            return io.command(1, address, deadline=deadline)
        def write(address, value, *, deadline):
            return io.command(2, address, value, deadline=deadline)
        return io, read, write

    def test_identity_mismatch_epoch_overflow_and_epoch_drift_fail_precommand(self):
        for address, value in ((0x500, 0), (0x504, 0x10001), (0x518, 0x10005)):
            with self.subTest(address=hex(address)):
                io, read, write = self.raw_reset()
                io.values[address][0] = value
                with self.assertRaises(ProtocolError):
                    reset.perform_reset(read, write, timeout=2)
                self.assertFalse(any(e[0] == "w" for e in io.events))
        for epochs in ((0xFFFFFFFF,), (7, 8)):
            with self.subTest(epochs=epochs):
                io, read, write = self.raw_reset(epochs=epochs)
                with self.assertRaises(ProtocolError):
                    reset.perform_reset(read, write, timeout=2)
                self.assertFalse(any(e[0] == "w" for e in io.events))

    def test_initial_pending_result_bad_status_and_malformed_values_fail_before_command(self):
        for word in (0x35, 0x3D, 0x11, 0x16, 0x71, 0x19, 0x33, 0x37, True, -1, 1 << 32, "49"):
            with self.subTest(word=repr(word)):
                io, read, write = self.raw_reset(status=(word,))
                with self.assertRaises(ProtocolError):
                    reset.perform_reset(read, write, timeout=2)
                self.assertFalse(any(e[0] == "w" for e in io.events))

    def test_exact_initial_wait_states_and_epoch_checks(self):
        for initial in (0x10, 0x12, 0x30, 0x32):
            with self.subTest(initial=hex(initial)):
                io, read, write = self.raw_reset(
                    status=(initial, 0x31, 0x32, 0x36, 0x36, 0x32, 0x31),
                    epochs=(7, 7, 7, 8, 8))
                receipt = reset.perform_reset(read, write, timeout=2)
                self.assertEqual((receipt.epoch_before, receipt.epoch_after), (7, 8))
                self.assertEqual(io.events.count(("w", 0x50C, 1)), 1)
                self.assertEqual(io.events.count(("w", 0x50C, 2)), 1)

    def test_ownership_loss_result_mismatch_and_ack_release_errors_never_report_success(self):
        scenarios = (
            ((0x31, 0x30), (7, 7), (0,), False),
            ((0x31, 0x32, 0x36, 0x32), (7, 7, 8), (0,), False),
            ((0x31, 0x32, 0x36, 0x36), (7, 7, 9), (0,), False),
            ((0x31, 0x32, 0x36, 0x36), (7, 7, 8), (2,), False),
            ((0x31, 0x32, 0x36, 0x36, 0x36), (7, 7, 8, 8), (0,), True),
        )
        for statuses, epochs, result, ack_sent in scenarios:
            with self.subTest(statuses=statuses, epochs=epochs, result=result):
                io, read, write = self.raw_reset(status=statuses, epochs=epochs, result=result)
                with self.assertRaises(ProtocolError):
                    reset.perform_reset(read, write, timeout=2)
                self.assertEqual(("w", 0x50C, 2) in io.events, ack_sent)

    def test_callback_failures_and_deadline_expiry_propagate_without_extra_ack(self):
        io, read, write = self.raw_reset(fail_at=10)
        with self.assertRaises(OSError):
            reset.perform_reset(read, write, timeout=2)
        self.assertNotIn(("w", 0x50C, 2), io.events)
        class Expiring:
            def __init__(self, timeout, clock, expiry): self.expiry, self.calls = expiry, 0
            def remaining(self):
                self.calls += 1
                if self.calls >= self.expiry: raise TimeoutError("scripted deadline")
                return 1.0
        original = reset._Deadline
        try:
            for expiry, max_writes in ((7, 0), (12, 1), (14, 1)):
                io, read, write = self.raw_reset()
                reset._Deadline = lambda timeout, clock, n=expiry: Expiring(timeout, clock, n)
                with self.assertRaises(TimeoutError):
                    reset.perform_reset(read, write, timeout=2)
                self.assertLessEqual(sum(e[0] == "w" for e in io.events), max_writes)
                self.assertNotIn(("w", 0x50C, 2), io.events)
        finally:
            reset._Deadline = original

    def test_positive_seconds_and_optional_deadline_contract(self):
        for value in (True, 0, -1, float("nan"), float("inf"), -float("inf")):
            io = ScriptIO()
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                reset.perform_reset(lambda *a, **k: io.events.append(("r", a[0])),
                                    lambda *a, **k: None, timeout=value)
            self.assertEqual(io.events, [])
        for timeout in (1, 1.0, 0.25):
            with self.subTest(timeout=timeout):
                clock = Clock()
                d = _Deadline(timeout, clock)
                with self.assertRaises(ProtocolError):
                    reset.perform_reset(lambda a, *, deadline: 0,
                                        lambda a, v, *, deadline: None,
                                        timeout=timeout, clock=clock, _deadline=d)
                self.assertIs(d.clock, clock)
        with self.assertRaises(ValueError):
            reset.perform_reset(lambda *a, **k: 0, lambda *a, **k: None,
                                timeout=1, clock=Clock(), _deadline=_Deadline(1, Clock()))

    def test_reset_receipt_and_all_callback_deadlines_share_identity(self):
        io = ScriptIO(); reset_success(io)
        profile_identity(io, "layout")
        deadlines = []
        def read(address, *, deadline):
            deadlines.append(deadline)
            return io.command(1, address, deadline=deadline)
        def write(address, value, *, deadline):
            deadlines.append(deadline)
            return io.command(2, address, value, deadline=deadline)
        clock = Clock()
        receipt = reset.perform_reset(read, write, timeout=3.0, clock=clock)
        self.assertTrue(deadlines)
        self.assertTrue(all(item is deadlines[0] for item in deadlines))
        self.assertIs(deadlines[0].clock, clock)
        self.assertEqual((receipt.epoch_before, receipt.epoch_after), (7, 8))

    def test_quiet_failure_after_command_cannot_ack_or_record_success(self):
        io = ScriptIO(); reset_success(io)
        # Fail at the next status read after command acceptance.
        profile_identity(io, "layout")
        io.fail_at = 11
        owner = FullDdrRawTransportTests().make_owner(io)
        io.events.clear()
        with self.assertRaises(OSError):
            owner.compute_reset()
        self.assertTrue(owner._failed)
        self.assertNotIn(("w", 0x50C, 2), io.events)
        self.assertEqual(owner.reset_receipts, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
