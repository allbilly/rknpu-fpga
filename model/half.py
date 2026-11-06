"""Independent binary16 ADD/SUB/MUL/MAX/FDIV oracle (not an RK silicon spec).

Binary64 represents the exact sum/product of two finite binary16 operands.
struct.pack('<e') supplies the final round-to-nearest, ties-to-even conversion.
NaN results use the captured RK value 0x7c01. MAX is compared on encoded
magnitudes so negative values and signed zero follow IEEE maximum ordering.
This oracle also reproduces captured RK ADD/SUB zero and SUB infinity quirks.

FDIV follows the captured RK_FDIV_3G_RNE candidate: an exact quotient truncated
at three bits below the destination quantum, then rounded to nearest with
ties-to-even. It is deliberately not infinite-precision RNE; the A/7 capture
subset is one ULP low in the 0.5 < fraction < 0.625, even-significand window.
Special results use sign(a), while the finite path uses sign(a)^sign(b).
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


def _unpack_finite(bits: int) -> tuple[int, int, int]:
    """Return (sign, normalized 11-bit significand, leading-bit exponent)."""
    sign = bits >> 15
    exponent = (bits >> 10) & 0x1f
    fraction = bits & 0x3ff
    if exponent:
        return sign, 0x400 | fraction, exponent - 15
    # Callers handle magnitude zero before reaching here.
    p = fraction.bit_length() - 1
    k = 10 - p
    return sign, fraction << k, -14 - k


def fdiv_bits(a: int, b: int) -> int:
    """Captured RK3588 FP16 division contract (candidate, not an IEEE FPU)."""
    sa, sb = a >> 15, b >> 15
    a_nan = (a & 0x7c00) == 0x7c00 and (a & 0x03ff) != 0
    b_nan = (b & 0x7c00) == 0x7c00 and (b & 0x03ff) != 0
    a_inf = (a & 0x7fff) == 0x7c00
    b_inf = (b & 0x7fff) == 0x7c00
    a_zero = (a & 0x7fff) == 0
    b_zero = (b & 0x7fff) == 0
    # Special-value precedence and the captured sign(a) rule. Only the exact
    # +0/+0 pattern is the zero/zero NaN; +0/-0, -0/+0 and -0/-0 are infinity.
    if a_nan or b_nan:
        return 0x7c01
    if a == 0x0000 and b == 0x0000:
        return 0x7c01
    if b_zero:
        return (sa << 15) | 0x7c00
    if a_zero:
        return sa << 15
    if a_inf:
        return (sa << 15) | 0x7c00
    if b_inf:
        return sa << 15
    _, ma, ea = _unpack_finite(a)
    _, mb, eb = _unpack_finite(b)
    if ma >= mb:
        e = ea - eb
        qn = ma
    else:
        e = ea - eb - 1
        qn = ma << 1
    qd = mb
    ue = e - 10 if e >= -14 else -24
    shift = e - ue + 3
    if shift >= 0:
        d = (qn << shift) // qd
    else:
        d = qn // (qd << -shift)
    n, m = d >> 3, d & 7
    if m > 4 or (m == 4 and (n & 1)):
        n += 1
    if n == 2048:
        n = 1024
        e += 1
    if n == 1024 and e < -14:
        e = -14
    sign = (sa ^ sb) << 15
    if e < -14:
        return sign | (n & 0x3ff)
    if e > 15:
        return sign | 0x7c00
    return sign | ((e + 15) << 10) | (n & 0x3ff)


def alu(a: int, b: int, op: str) -> int:
    if op == 'FDIV':
        return fdiv_bits(a, b)
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
