"""Explicit raw-frame session ownership for the dual-host RKHO frontend.

The caller supplies an already-exclusive raw 640-bit exchange and a close
callback. This module does not open transports, map MMIO, emulate a TAP, or
rewrite backend frames. Closing a session never releases or resets hardware.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from tools.host.transport import DeviceBusy, ProtocolError, _Deadline, _positive_seconds, _uint

MAGIC = 0x4F54504A
RKHO_ID = 0x524B484F
ABI_VERSION = 0x00010000
CAPABILITIES = 0x00000003
IDENTITY_REG = 0x600
ABI_REG = 0x604
STATUS_REG = 0x608
CONTROL_REG = 0x60C
EPOCH_REG = 0x610
REQUESTER_REG = 0x614
FAILURE_REG = 0x618
CAPABILITIES_REG = 0x61C


class _PreIOTimeout(TimeoutError):
    """An exhausted budget detected before the callback was entered."""


def _request(sequence, opcode, address, data=0):
    return ((MAGIC << 572) | (sequence << 556) | (opcode << 548) |
            (0xF << 544) | (address << 512) | data)


class RawFrameSession:
    """Own one JTAG(1) or PCIe(2) RKHO lease around a raw exchange callback."""

    def __init__(self, exchange, *, close, source, timeout=30.0, clock=time.monotonic):
        if not callable(exchange) or not callable(close) or not callable(clock):
            raise TypeError('Explicit raw exchange, close, and clock callbacks are required')
        self._exchange = exchange
        self._close = close
        self._clock = clock
        self._mutex = threading.RLock()
        self.closed = False
        self.failed = False
        self.released = False
        self._active = False
        self._sequence = 0
        self._io_attempts = 0
        self.source = source
        self.timeout = None
        self.epoch = None
        try:
            if type(source) is not int or source not in (1, 2):
                raise ValueError('source must be integer 1 (JTAG) or 2 (PCIe)')
            self.timeout = _positive_seconds(timeout)
            deadline = _Deadline(self.timeout, self._clock)
            identity = self._read(IDENTITY_REG, deadline)
            abi = self._read(ABI_REG, deadline)
            capabilities = self._read(CAPABILITIES_REG, deadline)
            requester = self._read(REQUESTER_REG, deadline)
            failure = self._read(FAILURE_REG, deadline)
            status = self._read(STATUS_REG, deadline)
            epoch = self._read(EPOCH_REG, deadline)
            if identity != RKHO_ID:
                raise ProtocolError('Unsupported RKHO identity')
            if abi != ABI_VERSION:
                raise ProtocolError('Unsupported RKHO ABI')
            if capabilities != CAPABILITIES:
                raise ProtocolError('Unsupported RKHO capabilities')
            if requester != source:
                raise ProtocolError('RKHO physical requester does not match source')
            if failure != 0:
                raise ProtocolError('RKHO reports a retained ownership failure')
            self._check_idle_status(status)
            if epoch >= 0xFFFFFFFF:
                raise ProtocolError('RKHO lease epoch cannot be incremented')
            self._write(CONTROL_REG, 1, deadline)
            acquired_status = self._read(STATUS_REG, deadline)
            acquired_epoch = self._read(EPOCH_REG, deadline)
            acquired_failure = self._read(FAILURE_REG, deadline)
            if acquired_failure != 0:
                raise ProtocolError('RKHO faulted during acquisition')
            if acquired_epoch != epoch + 1:
                raise ProtocolError('RKHO acquisition did not advance exactly one epoch')
            self._check_owned_status(acquired_status)
            if (acquired_status & 3) != source:
                raise ProtocolError('RKHO acquisition returned the wrong owner')
            self.epoch = acquired_epoch
        except BaseException:
            self.failed = True
            try:
                self.close()
            except BaseException:
                pass
            raise

    def _next_sequence(self):
        self._sequence = (self._sequence + 1) & 0xFFFF
        return self._sequence

    def _external_deadline(self, deadline):
        if deadline is None:
            result = _Deadline(self.timeout, self._clock)
        else:
            if type(deadline) is not _Deadline or deadline.clock is not self._clock:
                raise ValueError('deadline must be an _Deadline using this session clock')
            result = deadline
        result.remaining()
        return result

    def _raw_call(self, frame, deadline):
        try:
            deadline.remaining()
        except TimeoutError as error:
            raise _PreIOTimeout(str(error)) from error
        try:
            self._io_attempts += 1
            response = self._exchange(frame, deadline=deadline)
        except BaseException:
            self.failed = True
            raise
        try:
            deadline.remaining()
        except BaseException:
            self.failed = True
            raise
        if type(response) is not int or not 0 <= response < 1 << 640:
            raise ProtocolError('Raw exchange returned a malformed frame value')
        return response

    def _management(self, opcode, address, data, deadline):
        sequence = self._next_sequence()
        response = self._raw_call(_request(sequence, opcode, address, data), deadline)
        if response >> 568:
            raise ProtocolError('Raw management response has nonzero reserved bits')
        if (response >> 536) & 0xFFFFFFFF != MAGIC:
            raise ProtocolError('Raw management response has bad magic')
        if (response >> 520) & 0xFFFF != sequence:
            raise ProtocolError('Raw management response sequence mismatch')
        status = (response >> 512) & 0xFF
        payload = response & ((1 << 512) - 1)
        if status and payload:
            raise ProtocolError('Raw management error response has nonzero payload')
        if status:
            if opcode == 2 and status == 2:
                raise DeviceBusy(f'RKHO management register {address:#x} rejected request')
            raise ProtocolError(f'RKHO management register {address:#x} status {status:#x}')
        if payload >> 32:
            raise ProtocolError('RKHO management read has nonzero reserved payload')
        return payload & 0xFFFFFFFF

    def _read(self, address, deadline):
        return self._management(1, address, 0, deadline)

    def _write(self, address, value, deadline):
        if self._management(2, address, value, deadline) != 0:
            raise ProtocolError('RKHO write response payload must be zero')

    @staticmethod
    def _check_idle_status(status):
        if status & ~0xF:
            raise ProtocolError('RKHO status has reserved bits set')
        owner, fault, ready = status & 3, (status >> 2) & 1, (status >> 3) & 1
        if fault:
            raise ProtocolError('RKHO ownership fault is set')
        if owner != 0 or not ready:
            raise DeviceBusy('RKHO is owned or backend session is not quiescent')

    @staticmethod
    def _check_owned_status(status):
        if status & ~0xF:
            raise ProtocolError('RKHO status has reserved bits set')
        if (status >> 2) & 1:
            raise ProtocolError('RKHO ownership fault is set')

    def _owned_snapshot(self, deadline):
        status = self._read(STATUS_REG, deadline)
        epoch = self._read(EPOCH_REG, deadline)
        requester = self._read(REQUESTER_REG, deadline)
        failure = self._read(FAILURE_REG, deadline)
        if failure != 0:
            raise ProtocolError('RKHO reports an ownership failure')
        if status & ~0xF:
            raise ProtocolError('RKHO status has reserved bits set')
        if (status >> 2) & 1:
            raise ProtocolError('RKHO ownership fault is set')
        if (status & 3) != self.source or requester != self.source or epoch != self.epoch:
            raise ProtocolError('RKHO owner, requester, or epoch changed during lease')
        if not ((status >> 3) & 1):
            raise DeviceBusy('RKHO backend session is not quiescent')
        return status

    def exchange(self, frame, *, deadline=None):
        """Forward exactly one backend frame; valid backend errors pass through unchanged."""
        _uint(frame, 640, 'raw request frame')
        if frame >> 604 or (frame >> 572) != MAGIC:
            raise ValueError('Unsupported raw request magic/reserved bits')
        opcode = (frame >> 548) & 0xFF
        address = (frame >> 512) & 0xFFFFFFFF
        if opcode in (1, 2) and address >> 8 == 0x6:
            raise ValueError('RKHO management register access is reserved to the session owner')
        budget = self._external_deadline(deadline)
        with self._try_operation_lock():
            self._ensure_open()
            if self._active:
                raise DeviceBusy('A raw session operation is already active')
            self._active = True
            try:
                response = self._raw_call(frame, budget)
                if response >> 568 or (response >> 536) & 0xFFFFFFFF != MAGIC:
                    raise ProtocolError('Malformed raw backend response header')
                if (response >> 520) & 0xFFFF != (frame >> 556) & 0xFFFF:
                    raise ProtocolError('Raw backend response sequence mismatch')
                status = (response >> 512) & 0xFF
                payload = response & ((1 << 512) - 1)
                if status and payload:
                    raise ProtocolError('Raw backend error response has nonzero payload')
                return response
            except BaseException as error:
                if not isinstance(error, (_PreIOTimeout, ValueError)):
                    self.failed = True
                raise
            finally:
                self._active = False

    def _ensure_open(self):
        if self.closed or self.released or self.failed:
            raise ProtocolError('Raw session is closed, released, or poisoned')

    @contextmanager
    def _try_operation_lock(self):
        if not self._mutex.acquire(blocking=False):
            raise DeviceBusy('A raw session operation is already active')
        try:
            yield
        finally:
            self._mutex.release()

    def release(self, *, deadline=None):
        """Release only after the hardware reports this source quiet and healthy."""
        budget = self._external_deadline(deadline)
        with self._try_operation_lock():
            self._ensure_open()
            if self._active:
                raise DeviceBusy('A raw session operation is already active')
            self._active = True
            release_write_confirmed = False
            release_write_calls_before = None
            try:
                self._owned_snapshot(budget)
                release_write_calls_before = self._io_attempts
                self._write(CONTROL_REG, 2, budget)
                release_write_confirmed = True
                status = self._read(STATUS_REG, budget)
                epoch = self._read(EPOCH_REG, budget)
                failure = self._read(FAILURE_REG, budget)
                if failure != 0 or epoch != self.epoch:
                    raise ProtocolError('RKHO release changed epoch or faulted')
                if status & ~0xF or status & 0x7:
                    raise ProtocolError('RKHO release did not confirm owner-free healthy status')
                self.released = True
            except DeviceBusy:
                # A live backend transaction may finish; caller can retry release later.
                if (release_write_confirmed or
                        (release_write_calls_before is not None and
                         self._io_attempts > release_write_calls_before)):
                    self.failed = True
                raise
            except _PreIOTimeout:
                if release_write_confirmed:
                    self.failed = True
                raise
            except BaseException:
                self.failed = True
                raise
            finally:
                self._active = False

    def close(self):
        """Close the supplied transport once; never send RKHO release or reset."""
        with self._mutex:
            if self.closed:
                return
            self.closed = True
            self._close()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()
