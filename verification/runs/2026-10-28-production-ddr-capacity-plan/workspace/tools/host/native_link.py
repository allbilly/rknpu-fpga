"""Native Vivado numeric-scan RPC link for the unchanged JtagTransport.

No hardware access on import. Root separately owns the audited image, cable
lease, hw_server and Tcl bridge. This adapter does not program/reset fabric,
reconnect, retry commands or perform tensor arithmetic/layout conversion.
RPC pattern reference: openTPU/tools/fedora_run_vivado_native_jtag.py; socket
deadlines and instruction/width checks here are deliberately explicit.
"""
from __future__ import annotations

from fractions import Fraction
import socket
import threading
import time
import re
from pathlib import Path

from tools.host.transport import _Deadline, _positive_seconds, _uint, DeviceBusy, ProtocolError
from tools.hardware.sample_ew import tcl_literal


TEMPLATE = Path(__file__).resolve().parents[2]/'fpga/host/native_rpc.tcl.in'


def render_bridge(target, server, source_tag, ready_path, port=3741):
    if not isinstance(target, str) or not target.startswith(server+'/') or any(c in target for c in '\r\n\0'):
        raise ValueError('Require exact audited native target URI')
    if not re.fullmatch('[0-9a-f]{8}', source_tag) or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid source tag or loopback RPC port')
    values = dict(TARGET=tcl_literal(target), SERVER=tcl_literal(server), USR_ACCESS=tcl_literal(source_tag),
                  READY=tcl_literal(ready_path), PORT=str(port))
    text = TEMPLATE.read_text()
    for name, value in values.items():
        marker = '@'+name+'@'
        if text.count(marker) != 1:
            raise ValueError('Changed native bridge marker '+name)
        text = text.replace(marker, value)
    return text


class NativeLink:
    """The reset/scan interface consumed by the existing raw-byte owner."""
    def __init__(self, host='127.0.0.1', port=3741, timeout=30.0, *, sock=None, clock=time.monotonic):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid native RPC port')
        self.host, self.port = host, port
        self.timeout = _positive_seconds(timeout)
        self._clock, self._mutex = clock, threading.RLock()
        self._failed, self.sock = False, None
        self.actual_period_ns = None
        self._ir = None
        deadline = _Deadline(self.timeout, clock)
        try:
            self.sock = sock if sock is not None else socket.create_connection((host, port), deadline.remaining())
            line = self._line(deadline)
            if line == b'BUSY\n':
                raise DeviceBusy('Native cable RPC already owned')
            # Use the3MHz DLC10 setting already verified by native receipts.
            # Preserve its exact rational period rather than rounding it up
            # to334ns. The owner uses the unchanged6MHz design ceiling.
            if line != b'READY 3000000\n':
                raise ProtocolError('Unexpected native readiness/clock receipt')
            self.actual_period_ns = Fraction(1_000_000_000, 3_000_000)
            self.actual_frequency_hz = 3_000_000
        except BaseException:
            self._failed = True
            self.close()
            raise

    def _line(self, deadline):
        data = bytearray()
        while not data.endswith(b'\n'):
            self.sock.settimeout(deadline.remaining())
            chunk = self.sock.recv(1)
            deadline.remaining()
            if not chunk:
                raise EOFError('Native JTAG RPC disconnected; completion uncertain')
            data.extend(chunk)
            if len(data) > 1024:
                raise ProtocolError('Oversized native JTAG RPC response')
        return bytes(data)

    def _command(self, text, deadline=None):
        with self._mutex:
            if self._failed or self.sock is None:
                raise ProtocolError('Native JTAG owner is closed or poisoned')
            budget = deadline if deadline is not None else _Deadline(self.timeout, self._clock)
            try:
                self.sock.settimeout(budget.remaining())
                self.sock.sendall(text.encode('ascii')+b'\n')
                budget.remaining()
                line = self._line(budget)
                match = re.fullmatch(rb'OK ([0-9a-fA-F]{1,160})\n', line)
                if match is None:
                    raise ProtocolError('Native JTAG RPC rejected or malformed response')
                return int(match[1], 16)
            except BaseException:
                self._failed = True
                self.close()
                raise

    def reset(self, *, deadline=None):
        result = self._command('RESET', deadline)
        self._ir = None
        if result != 0:
            self._failed = True
            self.close()
            raise ProtocolError('Nonzero TAP reset acknowledgment')

    def scan(self, value, bits=640, *, ir=False, deadline=None):
        if type(bits) is not int or bits not in (6, 32, 640) or type(ir) is not bool:
            raise ValueError('Unsupported native scan width/kind')
        _uint(value, bits, 'native scan value')
        if ir:
            if bits != 6 or value not in (0x09, 0x03, 0x3F):
                raise ValueError('Only IDCODE/USER2/BYPASS instructions are supported')
        elif (self._ir, bits) not in ((0x09, 32), (0x03, 640)):
            raise ValueError('DR width differs from selected audited instruction')
        result = self._command(f'SCAN {"IR" if ir else "DR"} {bits} {value:x}', deadline)
        if result >= 1 << bits:
            self._failed = True
            self.close()
            raise ProtocolError('Native scan response exceeds requested width')
        if ir:
            self._ir = value
        return result

    def shutdown_bridge(self):
        """Root-only orderly bridge exit; never resets the FPGA fabric."""
        result = self._command('QUIT')
        if result != 0:
            self._failed = True
            self.close()
            raise ProtocolError('Nonzero bridge exit acknowledgment')
        self.close()

    def close(self):
        # Closing the connection cannot recover an uncertain fabric transaction.
        if self.sock is not None:
            sock, self.sock = self.sock, None
            sock.close()
