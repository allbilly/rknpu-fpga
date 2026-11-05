"""Independent binary16 ADD/SUB/MUL/MAX oracle (not an RK silicon spec).

Binary64 represents the exact sum/product of two finite binary16 operands.
struct.pack('<e') supplies the final round-to-nearest, ties-to-even conversion.
NaN results use the captured RK value 0x7c01. MAX is compared on encoded
magnitudes so negative values and signed zero follow IEEE maximum ordering.
This oracle also reproduces captured RK ADD/SUB zero and SUB infinity quirks.
"""
from __future__ import annotations
import math
import struct


def from_bits(bits: int) -> float:
    if not 0 <= bits <= 0xffff:
        raise ValueError("not a 16-bit value")
    return struct.unpack('<e', struct.pack('<H', bits))[0]


def to_bits(value: float) -> int:
    if math.isnan(value):
        return 0x7c01
    try:
        return struct.unpack('<H', struct.pack('<e', value))[0]
    except OverflowError:
        return 0xfc00 if math.copysign(1., value) < 0 else 0x7c00


def alu(a: int, b: int, op: str) -> int:
    x, y = from_bits(a), from_bits(b)
    if op == 'ADD':
        z = x + y
    elif op == 'SUB':
        # Captured RK SUB treats same-sign infinities as +inf and
        # opposite-sign infinities as NaN, unlike IEEE subtraction.
        if math.isinf(x) and math.isinf(y):
            return 0x7c00 if (a >> 15) == (b >> 15) else 0x7c01
        z = x - y
    elif op == 'MUL':
        z = x * y
    elif op == 'MAX':
        if math.isnan(x) or math.isnan(y):
            return 0x7c01
        sa, sb = a >> 15, b >> 15
        if sa != sb:
            return b if sa else a
        if not sa:
            return a if (a & 0x7fff) >= (b & 0x7fff) else b
        return a if (a & 0x7fff) <= (b & 0x7fff) else b
    else:
        raise ValueError(f"unsupported arithmetic operation {op}")
    if op in ('ADD', 'SUB') and z == 0:
        return 0x0000
    return to_bits(z)
