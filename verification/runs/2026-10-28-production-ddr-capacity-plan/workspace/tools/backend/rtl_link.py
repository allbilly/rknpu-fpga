"""Offline link to an actual Verilator EW frame endpoint; no socket or device IO.

The six-bit IR/IDCODE selection here is a software test shim, not BSCANE2/TAP
proof. Every nonzero USER2 frame executes through the compiled RTL's public
request port. The original mailbox CDC has its own independent native tests.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess
import time

from tools.host.transport import FRAME_BITS, IDCODE, MAGIC, ProtocolError, _Deadline


class RtlLink:
    host = 'offline-rtl'
    port = 3721
    actual_period_ns = 167  # Test metadata; this harness does not model TCK.

    def __init__(self, executable, trace, stderr, timeout=30.0):
        self.trace = Path(trace).open('w')
        self.stderr = Path(stderr).open('w')
        self.process = subprocess.Popen([str(Path(executable).resolve())], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.stderr, bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = bytearray()
        self.ir = 0
        self.response = MAGIC << 536
        self.closed = False
        self.frames = 0
        try:
            if self._line(_Deadline(timeout, time.monotonic)) != b'READY raw-frame-rtl1':
                raise ProtocolError('Native RTL endpoint did not initialize')
        except BaseException:
            self.close()
            raise

    def _line(self, deadline):
        while b'\n' not in self.buffer:
            if not self.selector.select(deadline.remaining()):
                raise TimeoutError('Offline RTL endpoint reply deadline')
            chunk = os.read(self.process.stdout.fileno(), 4096)
            if not chunk:
                raise EOFError('Offline RTL endpoint exited')
            self.buffer.extend(chunk)
            if len(self.buffer) > 4096:
                raise ProtocolError('Oversized offline RTL reply')
        line, _, tail = self.buffer.partition(b'\n')
        self.buffer = bytearray(tail)
        deadline.remaining()
        return bytes(line)

    def reset(self, *, deadline=None):
        if self.closed:
            raise ProtocolError('Offline RTL link closed')
        if deadline is not None:
            deadline.remaining()
        # TAP reset deliberately does not reset the fabric or its RAM.
        self.ir = 0

    def scan(self, value, bits=FRAME_BITS, *, ir=False, deadline=None):
        deadline = deadline or _Deadline(30.0, time.monotonic)
        deadline.remaining()
        if self.closed or type(value) is not int or type(bits) is not int or value < 0 or value >= 1 << bits:
            raise ProtocolError('Invalid/closed offline scan')
        if ir:
            if bits != 6 or value not in (0x09, 0x03):
                raise ProtocolError('Unsupported test-shim instruction')
            self.ir = value
            return 0
        if self.ir == 0x09:
            if bits != 32 or value:
                raise ProtocolError('Invalid test IDCODE scan')
            return IDCODE
        if self.ir != 0x03 or bits != FRAME_BITS:
            raise ProtocolError('USER2 test scan requires640 bits')
        previous = self.response
        frame = f'{value:0160x}'
        self.process.stdin.write(('frame ' + frame + '\n').encode())
        deadline.remaining()
        line = self._line(deadline)
        if not line.startswith(b'response ') or len(line) != 169:
            raise ProtocolError('Malformed offline RTL response')
        self.response = int(line[9:], 16)
        self.trace.write(json.dumps({'frame': frame, 'rtl_response': f'{self.response:0160x}'}) + '\n')
        self.trace.flush()
        self.frames += int(value != 0)
        # Capture returns the previous completion; Update submits this request.
        return self.response if value == 0 else previous

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.process.stdin.close()
        try:
            self.returncode = self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.returncode = self.process.wait(timeout=5)
        self.selector.close()
        self.process.stdout.close()
        self.stderr.close()
        self.trace.close()
