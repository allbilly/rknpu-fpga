"""Explicit whole-reset lifecycle over already-owned SYS register callbacks.

No connection, TAP selection, programming, BO access or automatic recovery.
The caller owns the audited image/target/transport and serializes SYS access.
Any failure after START is attempted must poison the containing runtime owner:
a timeout does not cancel an issued hardware reset or authorize another START.
"""
from dataclasses import dataclass
import time

from tools.host.transport import DeviceBusy, ProtocolError, _Deadline, _positive_seconds

START = 0x53545254
ACK = 0x41434B21
ACTIVE, RESULT, ERROR, QUIESCE = 2, 4, 8, 16
SENT, ASSERTED, COMPLETE, FAULT, READY = 32, 64, 512, 1024, 2048


@dataclass(frozen=True)
class WholeResetReceipt:
    attempts_before: int
    attempts_after: int
    epoch_before: int
    epoch_after: int
    configured_deadline_edges: int
    held_status: int
    status_reads: tuple[int, ...]
    action_writes: tuple[tuple[int, int], ...]


def perform_whole_reset(read_register, write_register, *, timeout,
                        clock=time.monotonic, sleep=time.sleep, deadline=None):
    """Perform one explicit START/success/ACK transaction, without retries.

    Callbacks accept SYS byte addresses and keyword ``deadline``. Reads return
    uint32; writes complete with None or raise. They must preserve raw mailbox
    framing/status semantics. No callback arithmetic or BO repair is allowed.
    This host contract does not establish physical clock-stop or reset proof.
    """
    if not all(callable(fn) for fn in (read_register, write_register, clock, sleep)):
        raise TypeError('Explicit already-owned register and clock callbacks required')
    seconds = _positive_seconds(timeout)
    if deadline is not None and (type(deadline) is not _Deadline or deadline.clock is not clock):
        raise ValueError('Whole reset must share the owner clock and absolute deadline')
    budget = _Deadline(seconds, clock) if deadline is None else deadline.capped(seconds)
    statuses, writes = [], []
    start_attempted = False

    def read(address):
        budget.remaining()
        value = read_register(address, deadline=budget)
        budget.remaining()
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            raise ProtocolError('Malformed SYS register response')
        return value

    def write(value):
        budget.remaining()
        result = write_register(0x0C, value, deadline=budget)
        budget.remaining()
        if result is not None:
            raise ProtocolError('SYS write callback must complete with None')
        writes.append((0x0C, value))

    def status():
        word = read(0x08)
        statuses.append(word)
        if (word & ~0xFFF or word & ERROR and not word & RESULT or
                word & ACTIVE and word & RESULT or
                word & 1 and word & (ACTIVE | RESULT | ERROR | QUIESCE) or
                word & ASSERTED and not word & SENT):
            raise ProtocolError('Reserved or inconsistent SYS status')
        return word

    def require_success(word):
        required = RESULT | QUIESCE | SENT | ASSERTED | COMPLETE | READY
        if word & required != required or word & (1 | ACTIVE | ERROR | FAULT):
            raise ProtocolError('SYS result lacks successful reset/freshness witnesses')

    try:
        if (read(0x00), read(0x04), read(0x1C)) != (0x524B5052, 0x10000, 0x10001):
            raise ProtocolError('Unsupported SYS identity/ABI/capability')
        attempts_before, epoch_before = read(0x10), read(0x14)
        if attempts_before == 0xFFFFFFFF or epoch_before == 0xFFFFFFFF:
            raise ProtocolError('SYS attempt/epoch overflow requires explicit recovery')
        configured = read(0x28) | (read(0x2C) << 32)
        if configured == 0:
            raise ProtocolError('SYS hardware deadline must be positive')
        word = status()
        if word & (ACTIVE | RESULT) or not word & 1:
            raise DeviceBusy('SYS controller is not idle and START eligible')
        if read(0x10) != attempts_before or read(0x14) != epoch_before:
            raise ProtocolError('SYS counters changed before this START')
        start_attempted = True  # A failed callback may have delivered START.
        write(START)
        while True:
            word = status()
            if word & RESULT:
                break
            if not word & ACTIVE or not word & QUIESCE or word & 1:
                raise ProtocolError('SYS START did not retain its active transaction')
            sleep(min(0.001, budget.remaining()))

        # A held failure is never ACKed, retried, cancelled or upgraded here.
        if word & ERROR:
            local_error, phase, coordinator_error = read(0x18), read(0x20), read(0x24)
            raise ProtocolError(f'SYS reset failed: error={local_error} phase={phase} coordinator={coordinator_error}')
        require_success(word)
        attempts_after, epoch_after = read(0x10), read(0x14)
        if attempts_after != attempts_before + 1 or epoch_after != epoch_before + 1:
            raise ProtocolError('SYS result counters do not match this reset attempt')
        if (read(0x18), read(0x20), read(0x24)) != (0, 4, 0):
            raise ProtocolError('SYS success has an invalid error/phase record')
        held_status = status()
        require_success(held_status)
        write(ACK)
        while True:
            word = status()
            if word & (ACTIVE | RESULT | ERROR | QUIESCE | FAULT):
                raise ProtocolError('SYS ACK did not consume and release its result')
            if word & 1 and word & (COMPLETE | READY) == COMPLETE | READY:
                break
            # Barrier return/fresh-edge synchronization may delay eligibility.
            sleep(min(0.001, budget.remaining()))
        if read(0x10) != attempts_after or read(0x14) != epoch_after:
            raise ProtocolError('SYS counters changed after ACK')
        return WholeResetReceipt(attempts_before, attempts_after, epoch_before,
                                 epoch_after, configured, held_status,
                                 tuple(statuses), tuple(writes))
    except BaseException as error:
        if start_attempted and hasattr(error, 'add_note'):
            error.add_note('SYS START may have been accepted. Do not retry or auto-ACK; poison the runtime owner and use explicit audited recovery.')
        raise
