"""Explicit write-capable SYS adapter over a borrowed USER3 NativeLink."""
from __future__ import annotations

from tools.host.native_link import NativeLink
from tools.host.sys_mailbox import (
    SysMailboxProbe, DR_BITS, FULL_STROBES, MAGIC, ProtocolError, _uint,
)
from tools.ddr.whole_reset import perform_whole_reset

COMMAND_ADDRESS = 0x0C
WRITE_OPCODE = 2
START = 0x53545254
CANCEL = 0x43414E43
ACK = 0x41434B21
ACTIONS = frozenset((START, CANCEL, ACK))


def build_write_frame(value: int, sequence: int) -> int:
    """Encode one documented 0x0c command with all strobes and no upper payload."""
    if type(value) is not int or value not in ACTIONS:
        raise ValueError("SYS command must be START, CANCEL or ACK")
    if type(sequence) is not int or not 1 <= sequence <= 0xFFFF:
        raise ValueError("SYS sequence must be nonzero uint16")
    frame = (value | (COMMAND_ADDRESS << 512) | (FULL_STROBES << 544) |
             (WRITE_OPCODE << 548) | (sequence << 556) | (MAGIC << 572))
    _uint(frame, DR_BITS, "SYS command frame")
    if frame >> 604 or ((frame >> 572) & 0xFFFFFFFF) != MAGIC or \
       ((frame >> 548) & 0xFF) != WRITE_OPCODE or ((frame >> 544) & 0xF) != FULL_STROBES or \
       ((frame >> 32) & ((1 << 480) - 1)) != 0:
        raise ValueError("SYS command frame violates documented raw-frame contract")
    return frame


class SysMailboxAccess(SysMailboxProbe):
    """Borrowed USER3 SYS link plus a narrowly whitelisted command callback."""
    def __init__(self, borrowed_link: NativeLink, *, timeout=5.0, clock=None, sleep=None):
        kwargs = {"timeout": timeout}
        if clock is not None:
            kwargs["clock"] = clock
        if sleep is not None:
            kwargs["sleep"] = sleep
        super().__init__(borrowed_link, **kwargs)
        self._write_identity_verified = False

    def _verify_write_identity(self, deadline):
        identity = self.read_register(0x00, deadline=deadline)
        abi = self.read_register(0x04, deadline=deadline)
        capability = self.read_register(0x1C, deadline=deadline)
        if (identity, abi, capability) != (0x524B5052, 0x00010000, 0x00010001):
            raise ProtocolError("SYS RKPR/ABI/CAP must pass before the first command write")
        self._write_identity_verified = True

    def write_register(self, address, value, *, deadline=None):
        """Issue exactly one root-documented SYS command; response ambiguity poisons the adapter."""
        if type(address) is not int or address != COMMAND_ADDRESS:
            raise ValueError("SYS adapter writes only the command register at 0x0c")
        if type(value) is not int or value not in ACTIONS:
            raise ValueError("SYS adapter writes only START/CANCEL/ACK command keys")
        budget = self._deadline(deadline)
        with self._mutex, self._link_mutex:
            self._ensure_open()
            try:
                self._prepare(budget)
                if not self._write_identity_verified:
                    # Even when perform_whole_reset() already read these values,
                    # this explicit pre-first-write verification uses this budget.
                    self._verify_write_identity(budget)
                sequence = self._next_sequence
                request = build_write_frame(value, sequence)
                previous = self._link.scan(request, bits=DR_BITS, deadline=budget)
                self._parse_response(previous)
                if previous != self._last_response:
                    raise ProtocolError("Stale/concurrent SYS response changed before command capture")
                while True:
                    budget.remaining()
                    response = self._link.scan(0, bits=DR_BITS, deadline=budget)
                    got_sequence, status, payload = self._parse_response(response)
                    if got_sequence == sequence:
                        if status != 0:
                            if payload != 0:
                                raise ProtocolError("SYS command error response has nonzero payload")
                            raise ProtocolError(f"SYS command rejected with status {status:#x}")
                        if payload != 0:
                            raise ProtocolError("SYS command completion payload must be zero")
                        self._last_response = response
                        self._last_sequence = sequence
                        self._next_sequence = (sequence % 0xFFFF) + 1
                        return None
                    if got_sequence != self._last_sequence or response != self._last_response:
                        raise ProtocolError("Stale/out-of-order SYS command response")
                    self._sleep(min(0.001, budget.remaining()))
            except BaseException:
                self._failed = True
                raise

    def perform_reset(self, *, timeout=None, deadline=None):
        """Explicit caller action; executes only the root-owned START/success/ACK callback FSM."""
        seconds = self.timeout if timeout is None else timeout
        with self._mutex, self._link_mutex:
            self._ensure_open()
            try:
                return perform_whole_reset(self.read_register, self.write_register,
                    timeout=seconds, clock=self._clock, sleep=self._sleep, deadline=deadline)
            except BaseException:
                self._failed = True
                raise
