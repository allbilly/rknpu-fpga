"""One raw USER2 owner for the separate EW and terminal-CMAC CSR windows.

No device selection on import. Construction requires an already audited dual
image/link and checks both namespace identities before any write. Payload
BOs, descriptors and final QWORDs remain unchanged. This is not a tensor API.
"""
import time

from tools.host.transport import (ABI_VERSION, MAX_TCK_HZ, READ_REGISTERS, WRITE_REGISTERS,
                                 JtagTransport, ProtocolError, _Deadline, _positive_seconds, _uint)

PROFILES = {'ew': (0x000, 0x524b4557), 'cmac': (0x100, 0x524b434d)}


class DualRawTransport(JtagTransport):
    def __init__(self, host='localhost', port=3721, timeout=30.0, *, frequency_hz=MAX_TCK_HZ,
                 link=None, clock=time.monotonic, sleep=time.sleep):
        self._profile = 'ew'
        startup = _Deadline(_positive_seconds(timeout), clock)
        super().__init__(host, port, timeout, frequency_hz=frequency_hz, link=link, clock=clock, sleep=sleep)
        try:
            self._check_identity('cmac', startup)
        except BaseException:
            self._failed = True
            self.close()
            raise

    @property
    def profile(self):
        return self._profile

    def _check_identity(self, profile, deadline):
        base, identity = PROFILES[profile]
        if (self._command(1, base, deadline=deadline) != identity or
                self._command(1, base+4, deadline=deadline) != ABI_VERSION):
            raise ProtocolError('Unsupported raw-job namespace identity/ABI')

    def select_profile(self, profile):
        if not isinstance(profile, str) or profile not in PROFILES:
            raise ValueError('Unsupported raw command profile')
        with self._mutex:
            self._usable()
            if self._active_tag is not None or self._result is not None:
                raise ValueError('Consume and ACK the current job before changing its namespace')
            if profile == self._profile:
                return
            budget = _Deadline(self.timeout, self._clock)
            try:
                # Staged descriptors and peer-owned results are not discarded.
                if self._status(budget) != 0x10:
                    raise ProtocolError('Current namespace is not idle and memory-ready')
                self._check_identity(profile, budget)
                if self._command(1, PROFILES[profile][0]+8, deadline=budget) != 0x10:
                    raise ProtocolError('Requested namespace is not idle and memory-ready')
                self._profile = profile
            except BaseException:
                self._failed = True
                raise

    def reg_read(self, offset, *, _deadline=None):
        _uint(offset, 32, 'register offset')
        if offset not in READ_REGISTERS:
            raise ValueError('Unsupported raw-job read register')
        return self._command(1, PROFILES[self._profile][0]+offset, deadline=_deadline)

    def reg_write(self, offset, value):
        _uint(offset, 32, 'register offset')
        _uint(value, 32, 'register value')
        if offset not in WRITE_REGISTERS or (offset == 0x0c and value not in (1, 2)):
            raise ValueError('Unsupported raw-job write register/value')
        self._command(2, PROFILES[self._profile][0]+offset, value)
