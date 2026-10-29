"""Stdlib USER2/XVC transport for the RKEW BRAM endpoint.

Wire compatibility follows the frozen OpenTPU c0182800 mailbox: 640-bit DR,
opcodes 1..4, LSB first, and retained 16-bit completion sequences. The target
must be the only TAP. No connection is opened merely by importing this module.
Constructing JtagTransport explicitly acquires OpenTPU's lifetime flock and
connects unless an already negotiated Xvc test link is supplied.

An error poisons the owner. close() releases resources, NOT the FPGA fault or
an outstanding transaction; recovery requires a separately audited joint reset
or reconfiguration. There is no automatic reconnect, retry or reset opcode.
Only byte transport and raw command-buffer descriptors are exposed. Partial
line writes preserve neighboring bytes by 64-byte read/modify/write; no tensor
arithmetic, command rewriting, layout conversion or hardware fallback exists.
"""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
import math
import os
from pathlib import Path
import re
import socket
import struct
import threading
import time

MAGIC = 0x4F54504A
IDCODE = 0x23751093
FRAME_BITS = 640
MAX_TCK_HZ = 6_000_000
RKEW_ID = 0x524B4557
ABI_VERSION = 0x00010000
ADDRESS_LIMIT = 1 << 31
READ_REGISTERS = frozenset((0, 4, 8, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24))
WRITE_REGISTERS = frozenset((0x0C, 0x10, 0x14, 0x18))


class ProtocolError(IOError):
    pass


class DeviceBusy(RuntimeError):
    pass


class MailboxError(IOError):
    def __init__(self, opcode, address, status):
        self.opcode, self.address, self.status = opcode, address, status
        super().__init__(f'USER2 opcode {opcode} at {address:#x}: status {status:#04x}; joint recovery required')


@dataclass(frozen=True)
class JobResult:
    tag: int
    completed_tasks: int
    error_code: int
    status: int


class JobError(IOError):
    def __init__(self, result):
        self.result = result
        super().__init__(f'RKEW job {result.tag:#x} failed E{result.error_code} after '
                         f'{result.completed_tasks} tasks; partial writes may remain')


def _uint(value, bits, name):
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ValueError(f'{name} must be uint{bits}')
    return value


def _positive_seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError('timeout must be finite and positive')
    return value


class _Deadline:
    """One absolute budget shared by all socket calls in an operation."""
    def __init__(self, timeout, clock):
        self.clock = clock
        self.stop = clock() + timeout

    def remaining(self):
        remaining = self.stop - self.clock()
        if not remaining > 0:
            raise TimeoutError('XVC/USER2 operation deadline expired')
        return remaining

    def capped(self, timeout):
        result = _Deadline(timeout, self.clock)
        result.stop = min(result.stop, self.stop)
        return result


def _period_ns(frequency_hz):
    if type(frequency_hz) is not int or frequency_hz < 1:
        raise ValueError('frequency_hz must be a positive integer')
    frequency = min(frequency_hz, MAX_TCK_HZ)
    return (1_000_000_000 + frequency - 1) // frequency


def _raw_bytes(data):
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError('Upload must contain raw bytes')
    view = memoryview(data)
    if not view.c_contiguous:
        raise ValueError('Noncontiguous uploads require a hardware layout operation; host gathers are unsupported')
    return view.cast('B').tobytes()


class DeviceLock:
    """Same run_dir and flock filename as OpenTPU host/runstate.py.

    Always take a real flock, including with injected links. An inherited
    OTPU_LOCK_HELD environment variable is not sufficient proof of ownership.
    The hostname spelling must match other OpenTPU clients of this endpoint.
    """
    def __init__(self, host, port):
        if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]+', host):
            raise ValueError('host must be a hostname or literal IP address')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('port must be in 1..65535')
        directory = Path(os.environ.get('OTPU_RUN_DIR', '/tmp/otpu'))
        directory.mkdir(parents=True, exist_ok=True, mode=0o1777)
        self.path = directory / f'jtag-{host}-{port}.lock'
        self.fd = None
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o666)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise DeviceBusy(f'JTAG endpoint is already owned: {self.path}') from None
        except BaseException:
            os.close(fd)
            raise
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f'{os.getpid()}\n'.encode())
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    def release(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            try:
                os.ftruncate(fd, 0)
            finally:
                os.close(fd)


class Xvc:
    """XVC v1.0; settck's returned period must honor the requested frequency cap."""
    def __init__(self, host='localhost', port=3721, timeout=5.0, *, frequency_hz=MAX_TCK_HZ,
                 sock=None, clock=time.monotonic, _deadline=None):
        self.timeout = _positive_seconds(timeout)
        self._clock = clock
        self.host, self.port = host, port
        self.requested_period_ns = _period_ns(frequency_hz)
        self.actual_period_ns = None
        self._failed = False
        self.sock = None
        deadline = _deadline if _deadline is not None else _Deadline(timeout, clock)
        try:
            self.sock = sock if sock is not None else socket.create_connection((host, port), deadline.remaining())
            self._send(b'getinfo:', deadline)
            info = bytearray()
            while not info.endswith(b'\n'):
                info.extend(self._recv(1, deadline))
                if len(info) > 256:
                    raise ProtocolError('Oversized XVC getinfo response')
            match = re.fullmatch(rb'xvcServer_v1\.0:([0-9]+)\n', bytes(info))
            if match is None or not FRAME_BITS + 5 <= int(match[1]) <= 0xFFFFFFFF:
                raise ProtocolError('XVC v1.0 server cannot scan the 645-bit mailbox transaction')
            self.max_bits = int(match[1])
            self._send(b'settck:' + struct.pack('<I', self.requested_period_ns), deadline)
            actual, = struct.unpack('<I', self._recv(4, deadline))
            if actual < self.requested_period_ns:
                raise ProtocolError(f'XVC returned {actual} ns TCK; at least {self.requested_period_ns} ns is required')
            self.actual_period_ns = actual
        except BaseException:
            self._failed = True
            self.close()
            raise

    def _send(self, data, deadline):
        self.sock.settimeout(deadline.remaining())
        self.sock.sendall(data)
        deadline.remaining()

    def _recv(self, size, deadline):
        data = bytearray()
        while len(data) < size:
            # A successful fragment must not restart the whole operation's
            # timeout. sendall and every recv consume this same deadline.
            self.sock.settimeout(deadline.remaining())
            chunk = self.sock.recv(size - len(data))
            deadline.remaining()
            if not chunk:
                raise EOFError('XVC disconnected')
            data.extend(chunk)
        return bytes(data)

    def shift(self, bits, tms, tdi, *, deadline=None):
        if type(bits) is not int or not 1 <= bits <= self.max_bits:
            raise ValueError('Scan length exceeds the negotiated XVC limit')
        _uint(tms, bits, 'TMS'); _uint(tdi, bits, 'TDI')
        if self._failed or self.sock is None:
            raise ProtocolError('XVC connection is closed or poisoned')
        size = (bits + 7) // 8
        deadline = deadline if deadline is not None else _Deadline(self.timeout, self._clock)
        try:
            self._send(b'shift:' + struct.pack('<I', bits) +
                       tms.to_bytes(size, 'little') + tdi.to_bytes(size, 'little'), deadline)
            value = int.from_bytes(self._recv(size, deadline), 'little')
            # XVC returns ceil(bits/8) bytes; padding outside the requested scan
            # is not a TAP bit or a mailbox field.
            return value & ((1 << bits) - 1)
        except BaseException:
            self._failed = True
            self.close()
            raise

    def reset(self, *, deadline=None):
        self.shift(6, 0b011111, 0, deadline=deadline)

    def scan(self, value, bits=FRAME_BITS, *, ir=False, deadline=None):
        if type(bits) is not int or bits < 1:
            raise ValueError('Scan width must be positive')
        _uint(value, bits, 'scan value')
        prefix, count = (0b0011, 4) if ir else (0b001, 3)
        tms = prefix | (1 << (count + bits - 1)) | (1 << (count + bits))
        response = self.shift(count + bits + 2, tms, value << count, deadline=deadline)
        return (response >> count) & ((1 << bits) - 1)

    def close(self):
        if self.sock is not None:
            sock, self.sock = self.sock, None
            sock.close()


class JtagTransport:
    """One process owner, one mailbox request, and one staged RKEW job at a time."""
    def __init__(self, host='localhost', port=3721, timeout=30.0, *, frequency_hz=MAX_TCK_HZ,
                 link=None, clock=time.monotonic, sleep=time.sleep):
        self.timeout = _positive_seconds(timeout)
        requested_period = _period_ns(frequency_hz)
        self._clock, self._sleep = clock, sleep
        self._mutex = threading.RLock()
        self._failed = False
        self._verified = False
        self._seq = 0
        self._active_tag = self._result = None
        self.link = self._lock = None
        initialization = _Deadline(self.timeout, self._clock)
        try:
            self._lock = DeviceLock(host, port)
            self.link = link if link is not None else Xvc(host, port, timeout, frequency_hz=frequency_hz,
                clock=clock, _deadline=initialization)
            if (self.link.host, self.link.port) != (host, port) or self.link.actual_period_ns is None or self.link.actual_period_ns < requested_period:
                raise ProtocolError('Link endpoint or negotiated TCK differs from this owner')
            self.link.reset(deadline=initialization)
            self.link.scan(0x09, 6, ir=True, deadline=initialization)
            ident = self.link.scan(0, 32, deadline=initialization)
            if ident != IDCODE:
                raise ProtocolError(f'Expected single XC7K480T TAP {IDCODE:#x}, got {ident:#x}')
            self.link.scan(0x03, 6, ir=True, deadline=initialization)
            response = self.link.scan(0, deadline=initialization)
            self._response(response)
            self._seq = (response >> 520) & 0xFFFF
            if (self.reg_read(0, _deadline=initialization) != RKEW_ID or
                    self.reg_read(4, _deadline=initialization) != ABI_VERSION):
                raise ProtocolError('Endpoint is not the supported RKEW ABI 1.0')
            self._verified = True
        except BaseException:
            self._failed = True
            self.close()
            raise

    @staticmethod
    def _response(response):
        if (response >> 536) & 0xFFFFFFFF != MAGIC or response >> 568:
            raise ProtocolError('Invalid USER2 response magic or reserved bits')

    def _usable(self):
        if self._failed or self.link is None:
            raise ProtocolError('Connection is closed or poisoned; joint recovery is required')

    def _command(self, opcode, address, data=0, *, deadline=None):
        with self._mutex:
            self._usable()
            if opcode in (2, 4) and not self._verified:
                raise ProtocolError('RKEW identity must be verified before writes')
            budget = deadline.capped(self.timeout) if deadline is not None else _Deadline(self.timeout, self._clock)
            try:
                budget.remaining()
                self._seq = self._seq % 65535 + 1
                sequence = self._seq
                frame = data | address << 512 | 15 << 544 | opcode << 548 | sequence << 556 | MAGIC << 572
                self.link.scan(frame, deadline=budget)
                while True:
                    budget.remaining()
                    response = self.link.scan(0, deadline=budget)
                    self._response(response)
                    budget.remaining()
                    if (response >> 520) & 0xFFFF == sequence:
                        status = (response >> 512) & 0xFF
                        value = response & ((1 << 512) - 1)
                        if status:
                            if value:
                                raise ProtocolError('Nonzero payload on mailbox error response')
                            raise MailboxError(opcode, address, status)
                        if (opcode == 1 and value >> 32) or (opcode in (2, 4) and value):
                            raise ProtocolError('Unexpected register/write response payload')
                        return value
                    self._sleep(min(0.001, budget.remaining()))
            except BaseException:
                self._failed = True
                raise

    def reg_read(self, offset, *, _deadline=None):
        _uint(offset, 32, 'register offset')
        if offset not in READ_REGISTERS:
            raise ValueError('Unsupported RKEW read register')
        return self._command(1, offset, deadline=_deadline)

    def reg_write(self, offset, value):
        _uint(offset, 32, 'register offset'); _uint(value, 32, 'register value')
        if offset not in WRITE_REGISTERS or (offset == 0x0C and value not in (1, 2)):
            raise ValueError('Unsupported RKEW write register/value')
        self._command(2, offset, value)

    def _status(self, deadline=None):
        value = self.reg_read(8, _deadline=deadline)
        if value & ~0x77F:
            self._failed = True
            raise ProtocolError('Unsupported RKEW status bits')
        return value

    def _memory_idle(self):
        if self._status() & (2 | 8 | 32 | 64):
            self._failed = True
            raise ProtocolError('Memory access requires an idle, nonfaulted RKEW endpoint')

    @staticmethod
    def _range(address, size):
        if type(address) is not int or type(size) is not int or address < 0 or size < 0 or address + size > ADDRESS_LIMIT:
            raise ValueError('Memory range must fit the 31-bit device address space')

    def mem_read(self, address, size):
        self._range(address, size)
        with self._mutex:
            self._usable()
            if not size:
                return b''
            self._memory_idle()
            result = bytearray()
            while len(result) < size:
                current = address + len(result); offset = current % 64
                amount = min(64 - offset, size - len(result))
                beat = self._command(3, current - offset).to_bytes(64, 'little')
                result.extend(beat[offset:offset + amount])
            return bytes(result)

    def mem_write(self, address, data):
        raw = _raw_bytes(data)
        self._range(address, len(raw))
        with self._mutex:
            self._usable()
            if not raw:
                return
            self._memory_idle()
            try:
                position = 0
                while position < len(raw):
                    current = address + position; offset = current % 64
                    amount = min(64 - offset, len(raw) - position)
                    beat = bytearray(64) if offset == 0 and amount == 64 else bytearray(
                        self._command(3, current - offset).to_bytes(64, 'little'))
                    beat[offset:offset + amount] = raw[position:position + amount]
                    self._command(4, current - offset, int.from_bytes(beat, 'little'))
                    position += amount
            except BaseException:
                self._failed = True
                raise

    def upload_commands(self, address, raw_commands):
        raw = _raw_bytes(raw_commands)
        self._range(address, len(raw))
        if address % 16 or not raw or len(raw) % 8:
            raise ValueError('Command BO must be 16-byte aligned and contain whole QWORDs')
        self.mem_write(address, raw)
        return len(raw) // 8

    def submit(self, command_address, initial_amount, tag):
        for value, name in ((command_address, 'command address'), (initial_amount, 'initial amount'), (tag, 'job tag')):
            _uint(value, 32, name)
        with self._mutex:
            self._usable()
            if self._active_tag is not None:
                raise ValueError('The current job must complete and be acknowledged first')
            try:
                status = self._status()
                if status & (2 | 4 | 8 | 32 | 64) or not status & 16:
                    raise ProtocolError('RKEW endpoint is not idle and memory-ready')
                for offset, value in ((0x10, command_address), (0x14, initial_amount), (0x18, tag)):
                    self.reg_write(offset, value)
                if not self._status() & 1:
                    raise ProtocolError('RKEW refused the staged descriptor')
                self._active_tag = tag
                self.reg_write(0x0C, 1)
            except BaseException:
                self._failed = True
                raise

    def poll_result(self, timeout=30.0):
        _positive_seconds(timeout)
        with self._mutex:
            self._usable()
            if self._active_tag is None:
                raise ValueError('No job was submitted by this owner')
            if self._result is not None:
                return self._result
            deadline = _Deadline(timeout, self._clock)
            try:
                while True:
                    status = self._status(deadline)
                    if status & 4:
                        result = JobResult(self.reg_read(0x1C, _deadline=deadline),
                                           self.reg_read(0x20, _deadline=deadline),
                                           self.reg_read(0x24, _deadline=deadline), status)
                        if result.tag != self._active_tag or result.error_code > 255 or status & (2 | 64):
                            raise ProtocolError('Invalid or stale RKEW completion snapshot')
                        if status & (8 | 32):
                            raise JobError(result)
                        if result.error_code or not result.completed_tasks:
                            raise ProtocolError('Invalid successful RKEW completion')
                        self._result = result
                        return result
                    self._sleep(min(0.001, deadline.remaining()))
            except BaseException:
                self._failed = True
                raise

    def ack_success(self):
        with self._mutex:
            self._usable()
            if self._result is None:
                raise ValueError('Only a successfully consumed result can be acknowledged')
            self.reg_write(0x0C, 2)
            if self._status() & 0x76F:
                self._failed = True
                raise ProtocolError('RKEW ACK did not clear the successful job')
            self._active_tag = self._result = None

    def close(self):
        with self._mutex:
            try:
                if self.link is not None:
                    link, self.link = self.link, None
                    link.close()
            finally:
                if self._lock is not None:
                    lock, self._lock = self._lock, None
                    lock.release()

    def __enter__(self):
        self._usable()
        return self

    def __exit__(self, *_):
        self.close()
