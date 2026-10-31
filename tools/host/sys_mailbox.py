"""Read-only SYS mailbox probe over a borrowed, explicitly USER3-enabled link.

Construction performs no I/O and does not own/close the link. Calling probe()
selects USER3 without a TAP/fabric reset, captures/validates the previous DR
response to seed sequence allocation, then performs only raw 604-bit register
read requests. No reset/START/CANCEL/ACK write path exists in this probe.
"""
from __future__ import annotations

import threading
import time

from tools.host.transport import MAGIC, ProtocolError, _Deadline, _positive_seconds, _uint

RKPR = 0x524B5052
ABI = 0x00010000
CAP = 0x00010001
DR_BITS = 640
IR_BITS = 6
USER3_IR = 0x22
FULL_STROBES = 0xF
READ_OPCODE = 1
REGISTER_ADDRESSES = {
    "rkpr": 0x00,
    "abi": 0x04,
    "status": 0x08,
    "attempts": 0x10,
    "success_epoch": 0x14,
    "last_error": 0x18,
    "capability": 0x1C,
    "phase": 0x20,
    "coordinator_error": 0x24,
    "deadline_low": 0x28,
    "deadline_high": 0x2C,
}


def build_read_frame(address: int, sequence: int) -> int:
    """Build the unchanged native raw-frame READ request, with all strobes."""
    if type(address) is not int or address not in set(REGISTER_ADDRESSES.values()) or address & 3:
        raise ValueError("Unsupported or unaligned SYS mailbox register read")
    if type(sequence) is not int or not 1 <= sequence <= 0xFFFF:
        raise ValueError("SYS mailbox sequence must be in 1..65535")
    frame = ((address & 0xFFFFFFFF) << 512) | (FULL_STROBES << 544) | (READ_OPCODE << 548) | (sequence << 556) | (MAGIC << 572)
    _uint(frame, 640, "SYS raw request frame")
    if frame >> 604 or ((frame >> 572) & 0xFFFFFFFF) != MAGIC or ((frame >> 548) & 0xFF) != READ_OPCODE:
        raise ValueError("Constructed SYS request violates raw-frame contract")
    return frame


class SysMailboxProbe:
    """Read-only SYS register probe. Link lifetime and cable ownership stay external."""
    def __init__(self, borrowed_link, *, timeout=5.0, clock=time.monotonic, sleep=time.sleep):
        if borrowed_link is None or not callable(getattr(borrowed_link, "scan", None)):
            raise TypeError("An already-owned native link with scan() is required")
        if getattr(borrowed_link, "allow_user3", False) is not True:
            raise ValueError("The borrowed native link must explicitly opt in to USER3")
        if not callable(clock) or not callable(sleep):
            raise TypeError("clock and sleep callbacks must be callable")
        self._link = borrowed_link
        self.timeout = _positive_seconds(timeout)
        self._clock, self._sleep = clock, sleep
        self._mutex = threading.RLock()
        self._link_mutex = getattr(borrowed_link, "_mutex", self._mutex)
        self._prepared = False
        self._closed = False
        self._failed = False
        self._last_response = None
        self._last_sequence = None
        self._next_sequence = None

    def _deadline(self, deadline):
        if deadline is None:
            return _Deadline(self.timeout, self._clock)
        if type(deadline) is not _Deadline or deadline.clock is not self._clock:
            raise ValueError("Use one absolute deadline from this probe's clock")
        return deadline.capped(self.timeout)

    @staticmethod
    def _parse_response(frame):
        _uint(frame, DR_BITS, "SYS mailbox response frame")
        if frame >> 568:
            raise ProtocolError("SYS mailbox response has reserved upper bits")
        if ((frame >> 536) & 0xFFFFFFFF) != MAGIC:
            raise ProtocolError("SYS mailbox response magic mismatch")
        sequence = (frame >> 520) & 0xFFFF
        status = (frame >> 512) & 0xFF
        payload = frame & ((1 << 512) - 1)
        if status != 0 and payload != 0:
            raise ProtocolError("SYS mailbox error response has nonzero payload")
        if status == 0 and payload >> 32:
            raise ProtocolError("SYS mailbox successful register response has nonzero upper payload bits")
        return sequence, status, payload

    def _ensure_open(self):
        if self._closed or self._failed:
            raise ProtocolError("SYS mailbox probe is closed or poisoned")
        if getattr(self._link, "allow_user3", False) is not True:
            self._failed = True
            raise ProtocolError("Borrowed link lost explicit USER3 opt-in")

    def _prepare(self, deadline):
        if self._prepared:
            return
        self._ensure_open()
        # USER3 IR selection is not a TAP reset and does not reset fabric.
        self._link.scan(USER3_IR, bits=IR_BITS, ir=True, deadline=deadline)
        baseline = self._link.scan(0, bits=DR_BITS, deadline=deadline)
        sequence, _status, _payload = self._parse_response(baseline)
        # The captured response belongs to an earlier transaction. Seed the
        # next request from it so an old reply cannot match the first read.
        self._last_response = baseline
        self._last_sequence = sequence
        self._next_sequence = (sequence % 0xFFFF) + 1
        self._prepared = True

    def read_register(self, address: int, *, deadline=None) -> int:
        if type(address) is not int or address not in set(REGISTER_ADDRESSES.values()) or address & 3:
            raise ValueError("Unsupported or unaligned SYS mailbox register read")
        budget = self._deadline(deadline)
        with self._mutex, self._link_mutex:
            self._ensure_open()
            try:
                self._prepare(budget)
                sequence = self._next_sequence
                request = build_read_frame(address, sequence)
                # A USER3 DR shift also captures the previous response. It must
                # still equal the baseline/last response; otherwise another
                # transaction or stale completion intervened.
                previous = self._link.scan(request, bits=DR_BITS, deadline=budget)
                self._parse_response(previous)
                if previous != self._last_response:
                    raise ProtocolError("Stale or concurrent SYS response changed before request capture")
                while True:
                    budget.remaining()
                    response = self._link.scan(0, bits=DR_BITS, deadline=budget)
                    got_sequence, status, payload = self._parse_response(response)
                    if got_sequence == sequence:
                        if status != 0:
                            if payload != 0:
                                raise ProtocolError("SYS mailbox error response has nonzero payload")
                            raise ProtocolError(f"SYS mailbox READ failed with transport status {status:#x}")
                        if payload >> 32:
                            raise ProtocolError("SYS mailbox register read has nonzero upper payload bits")
                        value = payload & 0xFFFFFFFF
                        self._last_response = response
                        self._last_sequence = sequence
                        self._next_sequence = (sequence % 0xFFFF) + 1
                        return value
                    if got_sequence != self._last_sequence or response != self._last_response:
                        raise ProtocolError("Stale or out-of-order SYS mailbox response sequence")
                    self._sleep(min(0.001, budget.remaining()))
            except BaseException:
                self._failed = True
                raise

    def probe(self, *, deadline=None):
        """Read and validate identity, ABI, capability and current SYS counters/status."""
        budget = self._deadline(deadline)
        try:
            values = {}
            values["rkpr"] = self.read_register(REGISTER_ADDRESSES["rkpr"], deadline=budget)
            if values["rkpr"] != RKPR:
                raise ProtocolError("SYS mailbox RKPR identity mismatch")
            values["abi"] = self.read_register(REGISTER_ADDRESSES["abi"], deadline=budget)
            if values["abi"] != ABI:
                raise ProtocolError("SYS mailbox ABI mismatch")
            values["capability"] = self.read_register(REGISTER_ADDRESSES["capability"], deadline=budget)
            if values["capability"] != CAP:
                raise ProtocolError("SYS mailbox capability mismatch")
            for name, address in REGISTER_ADDRESSES.items():
                if name not in values:
                    values[name] = self.read_register(address, deadline=budget)
            if values["status"] & ~0xFFF:
                raise ProtocolError("SYS mailbox status has reserved bits set")
            if values["phase"] > 5:
                raise ProtocolError("SYS mailbox phase is outside the documented range")
            values["deadline_edges"] = values.pop("deadline_low") | (values.pop("deadline_high") << 32)
            values["read_only"] = True
            values["tap_or_fabric_reset_requested"] = False
            return values
        except BaseException:
            self._failed = True
            raise

    def close(self):
        """Release only this probe object; the borrowed link remains open and owned externally."""
        with self._mutex:
            self._closed = True
