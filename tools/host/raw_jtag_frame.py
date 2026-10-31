"""Single-outstanding raw USER2 callback over an externally owned NativeLink."""
from __future__ import annotations

import threading
import time

from tools.host.transport import MAGIC, DeviceBusy, ProtocolError, _Deadline, _positive_seconds, _uint

DR_BITS = 640
IR_BITS = 6
USER2_IR = 0x03
RESPONSE_MAGIC = MAGIC


class RawJtagFrameExchange:
    """Borrowed-link USER2 raw-frame exchange; construction and close do no link I/O."""
    def __init__(self, borrowed_link, *, timeout=5.0, clock=time.monotonic, sleep=time.sleep):
        if borrowed_link is None or not callable(getattr(borrowed_link, "scan", None)):
            raise TypeError("An already-owned native link with scan() is required")
        mutex = getattr(borrowed_link, "_mutex", None)
        if mutex is None or not callable(getattr(mutex, "acquire", None)) or not callable(getattr(mutex, "release", None)):
            raise TypeError("Borrowed native link must expose an acquire/release transaction mutex")
        if not callable(clock) or not callable(sleep):
            raise TypeError("clock and sleep callbacks must be callable")
        self._link = borrowed_link
        self.timeout = _positive_seconds(timeout)
        self._clock, self._sleep = clock, sleep
        self._mutex = threading.RLock()
        self._link_mutex = mutex
        self._prepared = False
        self._active = False
        self._closed = False
        self._failed = False
        self._last_response = None
        self._last_sequence = None

    @staticmethod
    def _parse_response(frame):
        _uint(frame, DR_BITS, "USER2 response frame")
        if frame >> 568:
            raise ProtocolError("USER2 response has nonzero upper reserved bits")
        if ((frame >> 536) & 0xFFFFFFFF) != RESPONSE_MAGIC:
            raise ProtocolError("USER2 response magic mismatch")
        sequence = (frame >> 520) & 0xFFFF
        status = (frame >> 512) & 0xFF
        payload = frame & ((1 << 512) - 1)
        if status and payload:
            raise ProtocolError("USER2 error response has nonzero 512-bit payload")
        return sequence, status, payload

    @staticmethod
    def _validate_request(frame):
        _uint(frame, DR_BITS, "USER2 request frame")
        if frame >> 604:
            raise ProtocolError("USER2 request has nonzero upper reserved bits")
        if ((frame >> 572) & 0xFFFFFFFF) != MAGIC:
            raise ProtocolError("USER2 request magic mismatch")
        opcode = (frame >> 548) & 0xFF
        if opcode == 0:
            raise ProtocolError("USER2 request opcode zero is reserved for polling")
        return (frame >> 556) & 0xFFFF

    def _budget(self, deadline):
        if deadline is None:
            return _Deadline(self.timeout, self._clock)
        if type(deadline) is not _Deadline or deadline.clock is not self._clock:
            raise ValueError("Use one absolute deadline from this carrier's clock")
        return deadline.capped(self.timeout)

    def _ensure_open(self):
        if self._closed or self._failed:
            raise ProtocolError("USER2 frame carrier is closed or poisoned")

    def _begin_operation(self, budget):
        """Acquire both ownership locks without waiting beyond the deadline."""
        budget.remaining()
        if not self._mutex.acquire(blocking=False):
            raise DeviceBusy("Another USER2 carrier operation is active")
        link_locked = False
        try:
            if not self._link_mutex.acquire(blocking=False):
                raise DeviceBusy("Borrowed native link is busy with another transaction")
            link_locked = True
            budget.remaining()
            # RLock reentry by the current callback thread succeeds at acquire();
            # this flag still rejects a second packet during an active exchange.
            if self._active:
                raise DeviceBusy("A USER2 transaction is already outstanding")
            self._active = True
        except BaseException:
            if link_locked:
                self._link_mutex.release()
            self._mutex.release()
            raise

    def _end_operation(self):
        self._active = False
        self._link_mutex.release()
        self._mutex.release()

    def prepare(self, *, deadline=None):
        """Select USER2 and capture its retained completion sequence without reset."""
        budget = self._budget(deadline)
        self._begin_operation(budget)
        try:
            self._ensure_open()
            # A cached result is still subject to the caller's absolute budget.
            budget.remaining()
            if self._prepared:
                return self._last_sequence
            self._link.scan(USER2_IR, bits=IR_BITS, ir=True, deadline=budget)
            budget.remaining()
            baseline = self._link.scan(0, bits=DR_BITS, deadline=budget)
            budget.remaining()
            sequence, _status, _payload = self._parse_response(baseline)
            self._last_response = baseline
            self._last_sequence = sequence
            self._prepared = True
            return sequence
        except BaseException:
            self._failed = True
            raise
        finally:
            self._end_operation()

    @property
    def initial_sequence(self):
        if not self._prepared:
            raise ProtocolError("Call prepare() before seeding RawFrameSession")
        return self._last_sequence

    def exchange(self, frame, *, deadline=None):
        """Forward exactly one caller frame and return its correlated raw response."""
        budget = self._budget(deadline)
        # Lock contention/reentry fails here, before any packet is forwarded.
        self._begin_operation(budget)
        try:
            self._ensure_open()
            if not self._prepared:
                raise ProtocolError("USER2 carrier must be prepared before exchange")
            sequence = self._validate_request(frame)
            if sequence == self._last_sequence:
                raise ProtocolError("Request sequence aliases the retained completion")
            budget.remaining()
            self._link.scan(USER2_IR, bits=IR_BITS, ir=True, deadline=budget)
            budget.remaining()
            previous = self._link.scan(frame, bits=DR_BITS, ir=False, deadline=budget)
            budget.remaining()
            self._parse_response(previous)
            if previous != self._last_response:
                raise ProtocolError("USER2 completion changed before new request capture")
            while True:
                budget.remaining()
                response = self._link.scan(0, bits=DR_BITS, ir=False, deadline=budget)
                budget.remaining()
                got_sequence, _status, _payload = self._parse_response(response)
                if got_sequence == sequence:
                    self._last_response = response
                    self._last_sequence = sequence
                    return response
                if got_sequence != self._last_sequence or response != self._last_response:
                    raise ProtocolError("USER2 returned a stale, concurrent or out-of-order completion")
                budget.remaining()
                self._sleep(min(0.001, budget.remaining()))
        except BaseException:
            self._failed = True
            raise
        finally:
            self._end_operation()

    def close(self):
        """Close this callback object only; the borrowed link remains caller-owned."""
        with self._mutex:
            self._closed = True
