"""Full-DDR raw-job API over an explicitly acquired RKHO frame session.

The caller audits the image and physical endpoint, owns its per-transport
resources, and explicitly acquires RawFrameSession first. This class reuses
the existing byte/BO/job/reset methods; it never opens a TAP, a socket or a BAR.
The original JTAG-specific initializers are deliberately not called.
"""
import threading
import time

from tools.ddr.framework_transport import FullDdrRawTransport
from tools.host.raw_frame_session import RawFrameSession
from tools.host.transport import (
    DeviceBusy, MailboxError, ProtocolError, MAGIC, _Deadline,
    _positive_seconds, _uint,
)


class _OperationLock:
    """Reentrant for inherited helpers; concurrent operations fail before I/O."""
    def __init__(self):
        self._lock = threading.RLock()

    def __enter__(self):
        if not self._lock.acquire(blocking=False):
            raise DeviceBusy('Another raw transport operation is active')
        return self

    def __exit__(self, *unused):
        self._lock.release()


class FullDdrFrameTransport(FullDdrRawTransport):
    """Transport-independent full profile, using an already acquired raw lease."""
    def __init__(self, session, *, timeout=None, sleep=time.sleep):
        if not isinstance(session, RawFrameSession):
            raise TypeError('An explicitly acquired RawFrameSession is required')
        if not callable(sleep):
            raise TypeError('sleep must be callable')
        self.timeout = _positive_seconds(session.timeout if timeout is None else timeout)
        self._clock, self._sleep = session._clock, sleep
        self._mutex = _OperationLock()
        self._session = session
        self._failed = self._verified = False
        self._seq = 0
        self._active_tag = self._result = None
        self._profile = 'ew'
        self.reset_receipts = []
        try:
            self._usable()
            budget = _Deadline(self.timeout, self._clock)
            for profile in ('ew', 'cmac', 'layout'):
                self._check_identity(profile, budget)
            if tuple(self._command(1, address, deadline=budget)
                     for address in (0x500, 0x504, 0x518)) != (0x524B5253, 0x10000, 0x10004):
                raise ProtocolError('Unsupported compute-reset identity/ABI/capability')
            self._all_idle(budget)
            self._verified = True
        except BaseException:
            self._failed = True
            try:
                self.close()
            except BaseException:
                pass
            raise

    def _usable(self):
        session = self._session
        if (self._failed or session is None or session.closed or
                session.failed or session.released):
            raise ProtocolError('Raw frame owner is closed, released or poisoned')

    def _command(self, opcode, address, data=0, *, deadline=None):
        _uint(opcode, 8, 'opcode')
        _uint(address, 32, 'device address')
        _uint(data, 512, 'raw payload')
        if opcode not in (1, 2, 3, 4):
            raise ValueError('Unsupported raw byte command opcode')
        if opcode in (1, 3) and data or opcode == 2 and data >> 32:
            raise ValueError('Unsupported raw register/read command payload')
        if deadline is not None and (type(deadline) is not _Deadline or deadline.clock is not self._clock):
            raise ValueError('A deadline using the raw session clock is required')
        with self._mutex:
            self._usable()
            if opcode in (2, 4) and not self._verified:
                raise ProtocolError('Full-DDR identities must be verified before writes')
            budget = deadline.capped(self.timeout) if deadline is not None else _Deadline(self.timeout, self._clock)
            try:
                budget.remaining()
                self._seq = self._seq % 65535 + 1
                sequence = self._seq
                frame = (data | (address << 512) | (15 << 544) | (opcode << 548) |
                         (sequence << 556) | (MAGIC << 572))
                response = self._session.exchange(frame, deadline=budget)
                # RawFrameSession validates the entire correlated frame. Keep
                # command-specific payload validation at this transport layer.
                status = (response >> 512) & 0xFF
                value = response & ((1 << 512) - 1)
                if status:
                    raise MailboxError(opcode, address, status)
                if opcode == 1 and value >> 32 or opcode in (2, 4) and value:
                    raise ProtocolError('Unexpected raw register/write response payload')
                budget.remaining()
                return value
            except BaseException:
                self._failed = True
                raise

    def release(self, *, timeout=None):
        """Explicit handoff after full readback/job ACK and hardware quiescence."""
        seconds = self.timeout if timeout is None else _positive_seconds(timeout)
        with self._mutex:
            self._usable()
            if self._active_tag is not None or self._result is not None:
                raise DeviceBusy('Consume and ACK the owned job before releasing its transport')
            try:
                self._session.release(deadline=_Deadline(seconds, self._clock))
            except DeviceBusy:
                if self._session.failed:
                    self._failed = True
                raise
            except BaseException:
                self._failed = True
                raise

    def close(self):
        """Close transport resources; never release the lease or reset hardware."""
        with self._mutex:
            if self._session is not None:
                session, self._session = self._session, None
                session.close()
