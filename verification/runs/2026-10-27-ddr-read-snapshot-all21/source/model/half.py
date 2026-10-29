"""Independent binary16 ADD/SUB/MUL oracle (not an RK silicon specification).

Binary64 represents the exact sum/product of two finite binary16 operands.
struct.pack('<e') supplies the final round-to-nearest, ties-to-even conversion.
NaNs are deliberately canonicalized to 0x7e00. Confirm silicon special-value
behavior before advertising bit-exact RK compatibility.
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
        return 0x7e00
    try:
        return struct.unpack('<H', struct.pack('<e', value))[0]
    except OverflowError:
        return 0xfc00 if math.copysign(1., value) < 0 else 0x7c00


def alu(a: int, b: int, op: str) -> int:
    x, y = from_bits(a), from_bits(b)
    if op == 'ADD':
        z = x + y
    elif op == 'SUB':
        z = x - y
    elif op == 'MUL':
        z = x * y
    else:
        raise ValueError(f"unsupported arithmetic operation {op}")
    return to_bits(z)
