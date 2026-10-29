"""Explicit RKAD ABI1.0 admission over the existing raw USER2 byte protocol.

This does not connect at import, program a card, encode tensor operations or
repair layouts. Callers supply an audited transport/image and own the shared
board lease. The original RKEW transport and its qualified sources are unchanged.
"""
from __future__ import annotations

import threading
import time

from tools.host import transport as wire

RKAD_ID = 0x524B4144


class DdrJtagTransport(wire.JtagTransport):
    """One RKAD owner; initialization and result-readback have distinct gates."""

    def __init__(self, host='localhost', port=3721, timeout=30.0, *,
                 frequency_hz=wire.MAX_TCK_HZ, link=None, clock=time.monotonic,
                 sleep=time.sleep):
        # The RKEW initializer intentionally accepts only RKEW. Preserve that
        # admission rule and initialize the same byte protocol explicitly here.
        self.timeout = wire._positive_seconds(timeout)
        requested_period = wire._period_ns(frequency_hz)
        self._clock, self._sleep = clock, sleep
        self._mutex = threading.RLock()
        self._failed = self._verified = False
        self._seq = 0
        self._active_tag = self._result = None
        self.link = self._lock = None
        initialization = wire._Deadline(self.timeout, self._clock)
        try:
            self._lock = wire.DeviceLock(host, port)
            self.link = link if link is not None else wire.Xvc(host, port, timeout,
                frequency_hz=frequency_hz, clock=clock, _deadline=initialization)
            if ((self.link.host, self.link.port) != (host, port) or
                    self.link.actual_period_ns is None or self.link.actual_period_ns < requested_period):
                raise wire.ProtocolError('Link endpoint or negotiated TCK differs from this owner')
            self.link.reset(deadline=initialization)
            self.link.scan(0x09, 6, ir=True, deadline=initialization)
            ident = self.link.scan(0, 32, deadline=initialization)
            if ident != wire.IDCODE:
                raise wire.ProtocolError(f'Expected single XC7K480T TAP {wire.IDCODE:#x}, got {ident:#x}')
            self.link.scan(0x03, 6, ir=True, deadline=initialization)
            response = self.link.scan(0, deadline=initialization)
            self._response(response)
            self._seq = (response >> 520) & 0xFFFF
            if (self.reg_read(0, _deadline=initialization) != RKAD_ID or
                    self.reg_read(4, _deadline=initialization) != wire.ABI_VERSION):
                raise wire.ProtocolError('Endpoint is not the supported RKAD ABI 1.0')
            self._verified = True
        except BaseException:
            self._failed = True
            self.close()
            raise

    def reg_read(self, offset, *, _deadline=None):
        wire._uint(offset, 32, 'register offset')
        if offset not in wire.READ_REGISTERS:
            raise ValueError('Unsupported RKAD read register')
        return self._command(1, offset, deadline=_deadline)

    def reg_write(self, offset, value):
        wire._uint(offset, 32, 'register offset')
        wire._uint(value, 32, 'register value')
        if offset not in wire.WRITE_REGISTERS or (offset == 0x0C and value not in (1, 2)):
            raise ValueError('Unsupported RKAD write register/value')
        self._command(2, offset, value)

    def _status(self, deadline=None):
        value = self.reg_read(8, _deadline=deadline)
        if value & ~0x77F:
            self._failed = True
            raise wire.ProtocolError('Unsupported RKAD status bits')
        return value

    def wait_memory_ready(self, timeout=30.0):
        """Wait for status bit4, without staging a descriptor or resetting faults."""
        wire._positive_seconds(timeout)
        with self._mutex:
            self._usable()
            if self._active_tag is not None:
                raise ValueError('An owned job must complete and be acknowledged first')
            deadline = wire._Deadline(timeout, self._clock)
            try:
                while True:
                    status = self._status(deadline)
                    if status & (2 | 4 | 8 | 32 | 64):
                        raise wire.ProtocolError('RKAD is faulted or retains a previous transaction')
                    if status & 16:
                        return status
                    self._sleep(min(0.01, deadline.remaining()))
            except BaseException:
                self._failed = True
                raise

    def _memory_access(self, *, write):
        status = self._status()
        if status & (8 | 32):
            self._failed = True
            raise wire.ProtocolError('RKAD memory is faulted; coordinated recovery is required')
        if status & (2 | 64):
            raise wire.DeviceBusy('RKAD job still owns active memory traffic')
        if status & 4:
            # DDR keeps ownership through successful readback/ACK and clears
            # general memory-ready during this interval. Only this owner's
            # already-validated successful result permits reads; writes wait.
            if (not write and self._result is not None and
                    self._active_tag is not None and self._result.tag == self._active_tag):
                return
            raise wire.DeviceBusy('RKAD pending result retains memory ownership')
        if not status & 16:
            raise wire.DeviceBusy('RKAD memory initialization is not complete')

    def _memory_idle(self):
        self._memory_access(write=False)

    def mem_write(self, address, data):
        raw = wire._raw_bytes(data)
        self._range(address, len(raw))
        with self._mutex:
            self._usable()
            if not raw:
                return
            self._memory_access(write=True)
            return super().mem_write(address, raw)

    def ack_success(self):
        with self._mutex:
            super().ack_success()
            status = self._status()
            if not status & 16:
                self._failed = True
                raise wire.ProtocolError('RKAD ACK did not release healthy initialized memory')
