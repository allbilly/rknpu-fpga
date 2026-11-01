"""Candidate RKFI client over explicit, already-owned raw register callbacks.

No transport connection, programming, reset, retry, tensor operation or data
repair. Each successful command leaves its result held until explicit ACK.
The caller must retain the audited image/target lease for this entire epoch.
This source candidate does not admit RKFI on an earlier FPGA image.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time

from tools.host.transport import DeviceBusy, ProtocolError, _Deadline, _positive_seconds

CLAIM, CTRL_WRITE, LINE_WRITE, LINE_READ, ACK = range(1, 6)
READY, CLAIMED, GRANTED, BUSY, RESULT, MATCHED = (1 << n for n in range(6))
RECOVERY, PARENT_FAULT, CONTROL_FAULT, LOCAL_FAULT = (1 << n for n in range(6, 10))
INITIALIZED, DISARMED, BOOTSTRAPPED = 1 << 10, 1 << 12, 1 << 13
STATUS_MASK = 0x37FF


def uint(value, bits, label):
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ValueError(f'{label} must be uint{bits}')
    return value


@dataclass(frozen=True)
class FiResult:
    command: int
    ordinal: int
    status: int
    response_word: int
    words: tuple[int, ...]
    observations: tuple[tuple[int, int], ...]

    @property
    def raw_bytes(self):
        """Original little-endian words; no numerical or layout conversion."""
        return b''.join(word.to_bytes(4, 'little') for word in self.words)


class FiClient:
    def __init__(self, read_register, write_register, *, clock=time.monotonic,
                 sleep=time.sleep):
        if not all(callable(fn) for fn in (read_register, write_register, clock, sleep)):
            raise TypeError('Explicit raw register and clock callbacks required')
        self._read_register, self._write_register = read_register, write_register
        self._clock, self._sleep = clock, sleep
        self._mutex = threading.RLock()
        self._in_call = self.failed = self.claimed = False
        self._held = None
        self._window = None

    @contextmanager
    def _operation(self, timeout, *, admit=None):
        seconds = _positive_seconds(timeout)
        with self._mutex:
            if self.failed:
                raise ProtocolError('RKFI owner is poisoned; explicit joint recovery required')
            if self._in_call:
                raise DeviceBusy('Reentrant RKFI callback access is forbidden')
            # Software admission runs under the same lock as the transaction,
            # before the section that poisons uncertain hardware operations.
            # A waiting caller must not poison another call's held result.
            if admit is not None:
                admit()
            self._in_call = True
            try:
                yield _Deadline(seconds, self._clock)
            except BaseException as error:
                self.failed = True
                if hasattr(error, 'add_note'):
                    error.add_note('RKFI access may have taken effect. Do not retry, auto-ACK, release ownership or resume normal jobs; retain the trace and recover explicitly.')
                raise
            finally:
                self._in_call = False

    def _read(self, address, budget):
        budget.remaining()
        value = self._read_register(address, deadline=budget)
        budget.remaining()
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            raise ProtocolError('Malformed RKFI uint32 register response')
        return value

    def _write(self, address, value, budget):
        budget.remaining()
        answer = self._write_register(address, value, deadline=budget)
        budget.remaining()
        if answer is not None:
            raise ProtocolError('RKFI write callback must complete with None')

    def _status(self, budget):
        word = self._read(0x308, budget)
        if word & ~STATUS_MASK or word & CONTROL_FAULT or word & LOCAL_FAULT:
            raise ProtocolError(f'RKFI reserved/control/local fault status {word:#x}')
        if word & BUSY and word & RESULT or word & MATCHED and not word & RESULT:
            raise ProtocolError('Inconsistent RKFI command/result status')
        return word

    def _idle_owned(self, budget):
        word = self._status(budget)
        if word & (CLAIMED | GRANTED) != CLAIMED | GRANTED:
            raise ProtocolError('RKFI lost its claimed/granted ownership')
        if word & (READY | BUSY | RESULT | MATCHED):
            raise DeviceBusy('RKFI is not idle for a new command')
        return word

    def _metadata(self, budget):
        if (self._read(0x300, budget), self._read(0x304, budget),
                self._read(0x3E8, budget)) != (0x524B4649, 0x10000, 0x10040):
            raise ProtocolError('Image lacks the exact RKFI identity/ABI/line contract')
        base, size = self._read(0x3E0, budget), self._read(0x3E4, budget)
        if base % 64 or size < 64 or size % 64 or base + size > 1 << 31:
            raise ProtocolError('Unsupported RKFI address window')
        return base, size

    def _finish(self, command, ordinal, response, budget):
        while True:
            status = self._status(budget)
            if not status & CLAIMED:
                raise ProtocolError('RKFI command lost its claim')
            if status & RESULT:
                break
            if not status & BUSY:
                raise ProtocolError('RKFI command lacks active or held result state')
            self._sleep(min(0.001, budget.remaining()))
        if status & (CLAIMED | GRANTED | MATCHED) != CLAIMED | GRANTED | MATCHED:
            raise ProtocolError('RKFI result lacks actual grant/response-match witnesses')
        expected_record = command << 16 | 1 << 8 | response
        record = self._read(0x320, budget)
        if record != expected_record or self._read(0x358, budget) != ordinal:
            raise ProtocolError('RKFI command/response/ordinal mismatch')
        # Ordinary parent faults remain visible and may be expected after CE/UE;
        # they do not imply a valid event or authorize normal-job reuse.
        observations = tuple((address, self._read(address, budget))
                             for address in range(0x324, 0x358, 4))
        fields = dict(observations)
        if fields[0x324] or fields[0x328] & ~0x1FF or fields[0x334] & ~0xFF:
            raise ProtocolError('Invalid RKFI fault/mask observation')
        if fields[0x340] & ~0x1FFFFFFF or fields[0x344] & ~0x3FFFF:
            raise ProtocolError('Invalid RKFI MC address/metadata observation')
        words = tuple(self._read(0x3A0 + 4 * i, budget) for i in range(16)) if command == LINE_READ else ()
        held_status = self._status(budget)
        if (held_status & (CLAIMED | GRANTED | RESULT | MATCHED) !=
                CLAIMED | GRANTED | RESULT | MATCHED or held_status & BUSY or
                self._read(0x320, budget) != record or self._read(0x358, budget) != ordinal):
            raise ProtocolError('RKFI result changed during full readback')
        result = FiResult(command, ordinal, held_status, record, words, observations)
        self._held = result
        return result

    def claim(self, *, timeout=10):
        with self._operation(timeout, admit=self._require_claim) as budget:
            self._window = self._metadata(budget)
            status = self._status(budget)
            if status != READY | INITIALIZED | DISARMED | BOOTSTRAPPED:
                raise DeviceBusy('RKFI is not healthy, initialized and claim-ready')
            if (self._read(0x328, budget) != 0x1FF or
                    any(self._read(a, budget) for a in (0x324, 0x32C, 0x330, 0x334))):
                raise ProtocolError('RKFI claim lacks known-zero mask and fault witnesses')
            ordinal = self._read(0x358, budget)
            self.claimed = True  # A failed callback may already have submitted CLAIM.
            self._write(0x30C, CLAIM, budget)
            return self._finish(CLAIM, ordinal, 0, budget)

    def _require_claim(self):
        if self.claimed or self._held is not None:
            raise DeviceBusy('One explicit RKFI claim per joint-reset epoch')

    def _command(self, command, writes, response, budget):
        self._idle_owned(budget)
        ordinal = self._read(0x358, budget)
        if ordinal == 0xFFFFFFFF:
            raise ProtocolError('RKFI command ordinal exhausted; no wrap permitted')
        for address, value in writes:
            self._write(address, value, budget)
        self._write(0x30C, command, budget)
        return self._finish(command, ordinal + 1, response, budget)

    def _require_next(self):
        if not self.claimed or self._held is not None:
            raise DeviceBusy('Claim and explicitly ACK each result before a new command')

    def control_write(self, address, value, *, timeout=10):
        uint(address, 32, 'vendor control address'); uint(value, 32, 'vendor control data')
        if address not in (0x300, 0x304, 0x380) or address == 0x380 and value > 0xFF:
            raise ValueError('Unsupported vendor FI register/value')
        with self._operation(timeout, admit=self._require_next) as budget:
            result = self._command(CTRL_WRITE, ((0x310, address), (0x314, value)), 0, budget)
            fields = dict(result.observations)
            shift, width, known = {0x300: (0, 32, 0xF), 0x304: (32, 32, 0xF0),
                                   0x380: (64, 8, 0x100)}[address]
            observed = fields[0x32C] | fields[0x330] << 32 | fields[0x334] << 64
            if (fields[0x354] != address or fields[0x328] & known != known or
                    observed >> shift & ((1 << width) - 1) != value):
                raise ProtocolError('Control response lacks the actual mask-write witness')
            return result

    def _line_address(self, address):
        uint(address, 32, 'controller byte address')
        if self._window is None:
            raise DeviceBusy('RKFI metadata requires explicit claim first')
        base, size = self._window
        if address % 64 or address < base or address + 64 > base + size:
            raise ValueError('RKFI line must lie wholly inside the aligned source window')

    def write_line(self, address, words, *, timeout=10):
        self._line_address(address)
        words = tuple(words)
        if len(words) != 16:
            raise ValueError('Exactly sixteen original uint32 line words required')
        for word in words:
            uint(word, 32, 'line word')
        writes = [(0x318, address), (0x31C, 0)] + [(0x360 + 4 * i, w) for i, w in enumerate(words)]
        with self._operation(timeout, admit=self._require_next) as budget:
            result = self._command(LINE_WRITE, writes, 0, budget)
            if dict(result.observations)[0x350] != address:
                raise ProtocolError('RKFI write result has the wrong controller line address')
            return result

    def read_line(self, address, *, expected_response, timeout=10):
        self._line_address(address)
        if type(expected_response) is not int or expected_response not in (0, 2):
            raise ValueError('Explicit expected OKAY=0 or SLVERR=2 response required')
        with self._operation(timeout, admit=self._require_next) as budget:
            result = self._command(LINE_READ, ((0x318, address), (0x31C, expected_response)),
                                   expected_response, budget)
            if dict(result.observations)[0x350] != address:
                raise ProtocolError('RKFI read result has the wrong controller line address')
            return result

    def acknowledge(self, result, *, timeout=10):
        """Explicit consumption after caller checks raw data/event observations.

        A response match is not numerical or CE/UE qualification. This method
        does not release diagnostic ownership or make normal execution safe.
        """
        with self._operation(timeout, admit=lambda: self._require_receipt(result)) as budget:
            status = self._status(budget)
            if (status & (CLAIMED | GRANTED | RESULT | MATCHED) !=
                    CLAIMED | GRANTED | RESULT | MATCHED or status & BUSY or
                    self._read(0x320, budget) != result.response_word or
                    self._read(0x358, budget) != result.ordinal):
                raise ProtocolError('Held RKFI result changed before explicit ACK')
            self._write(0x30C, ACK, budget)
            self._idle_owned(budget)
            if self._read(0x35C, budget) != 0 or self._read(0x358, budget) != result.ordinal:
                raise ProtocolError('RKFI ACK lacks field-clear/ordinal witnesses')
            self._held = None

    def _require_receipt(self, result):
        if result is not self._held or result is None:
            raise ValueError('ACK requires this client\'s exact held result object')
