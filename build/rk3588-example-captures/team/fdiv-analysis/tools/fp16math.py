"""Exact binary16 helpers for the FDIV capture analysis.

Pure Python (no NumPy).  Every routine here is analysis-side only: it models
candidate divider behaviour so the real captures can be classified.  It is not
a hardware fallback and it never replaces a device result.
"""
from __future__ import annotations

from fractions import Fraction

# IEEE binary16 field boundaries.
SIGN = 0x8000
EXP_MASK = 0x7C00
FRAC_MASK = 0x03FF
QUIET_BIT = 0x0200
POS_INF = 0x7C00
POS_ZERO = 0x0000

# Candidate RK NaN canonical value observed for ADD/SUB/MUL/MAX.
RK_NAN = 0x7C01


def is_nan(bits: int) -> bool:
    return (bits & EXP_MASK) == EXP_MASK and (bits & FRAC_MASK) != 0


def is_inf(bits: int) -> bool:
    return (bits & 0x7FFF) == POS_INF


def is_zero(bits: int) -> bool:
    return (bits & 0x7FFF) == 0


def is_subnormal(bits: int) -> bool:
    return (bits & EXP_MASK) == 0 and (bits & FRAC_MASK) != 0


def sign(bits: int) -> int:
    return (bits >> 15) & 1


def finite_value(bits: int) -> Fraction:
    """Exact value of a finite binary16 pattern."""
    if is_nan(bits) or is_inf(bits):
        raise ValueError("not finite")
    s = -1 if sign(bits) else 1
    e = (bits >> 10) & 0x1F
    f = bits & FRAC_MASK
    if e == 0:
        return s * Fraction(f, 1 << 24)
    return s * Fraction((1 << 10) | f, 1 << 10) * (Fraction(2) ** (e - 15))


def bits_from_fields(s: int, e: int, f: int) -> int:
    return (s << 15) | (e << 10) | f


def half_value(bits: int) -> Fraction:
    return finite_value(bits)


def classify(bits: int) -> str:
    if is_nan(bits):
        return "qnan" if (bits & QUIET_BIT) else "snan"
    if is_inf(bits):
        return "inf_n" if sign(bits) else "inf_p"
    if is_zero(bits):
        return "zero_n" if sign(bits) else "zero_p"
    if is_subnormal(bits):
        return "sub_n" if sign(bits) else "sub_p"
    return "norm_n" if sign(bits) else "norm_p"


def round_fraction_to_half(x: Fraction, mode: str = "rne") -> int:
    """Round an exact finite rational to binary16.

    mode:
      rne       round to nearest, ties to even (IEEE default)
      rna       round to nearest, ties away from zero
      rz        truncate toward zero
      rup/rdn   round toward +inf / -inf
      odd       round to nearest with the sticky bit forced (never used as a
                divider model; present only for completeness)
    Overflow: mode-dependent:
      rne/rna   -> signed infinity
      rz/rdn    -> largest finite of the sign
      rup       -> +inf for positive, largest finite for negative
    Result zero: sign of x is preserved for every mode (an exact zero result is
    only produced for x == 0).
    """
    if x == 0:
        raise ValueError("use signed_zero for zero")
    s = 1 if x < 0 else 0
    ax = -x if x < 0 else x
    # Find e such that 2^e <= ax < 2^(e+1), e >= -24 for half subnormals.
    e = 0
    if ax >= 1:
        while ax >= (Fraction(2) ** (e + 1)):
            e += 1
    else:
        while ax < (Fraction(2) ** e):
            e -= 1
    # Value of one ulp at this exponent for the normals, clipped for subnormals.
    ulp_exp = max(e - 10, -24)
    ulp = Fraction(2) ** ulp_exp
    scaled = ax / ulp
    n = scaled.numerator // scaled.denominator
    rem = scaled - n

    def up() -> bool:
        if rem == 0:
            return False
        if mode == "rne":
            if rem > Fraction(1, 2):
                return True
            if rem < Fraction(1, 2):
                return False
            return (n & 1) == 1
        if mode == "rna":
            return rem >= Fraction(1, 2)
        if mode == "rz":
            return False
        if mode == "rup":
            return s == 0
        if mode == "rdn":
            return s == 1
        raise ValueError(mode)

    if up():
        n += 1
    # Re-encode n * ulp.
    if ulp_exp == -24 and n < (1 << 10):
        # subnormal (or zero) encoding
        if n == 0:
            return bits_from_fields(s, 0, 0)
        return bits_from_fields(s, 0, n)
    # normal: n in [1024, 2047] normally, may be 2048 after rounding up
    while n >= 2048:
        n >>= 1
        e += 1
    exp_field = e + 15
    if exp_field >= 0x1F:
        # overflow
        if mode in ("rne", "rna"):
            return bits_from_fields(s, 0x1F, 0)
        if mode == "rup" and s == 0:
            return bits_from_fields(s, 0x1F, 0)
        if mode == "rdn" and s == 1:
            return bits_from_fields(s, 0x1F, 0)
        return bits_from_fields(s, 0x1E, 0x3FF)
    return bits_from_fields(s, exp_field, n - 1024)


def signed_zero(s: int) -> int:
    return bits_from_fields(s, 0, 0)


def exact_quotient(a_bits: int, b_bits: int) -> Fraction:
    return finite_value(a_bits) / finite_value(b_bits)


def ieee_div(a_bits: int, b_bits: int) -> int:
    """IEEE 754 binary16 division, round-to-nearest-even, without exceptions."""
    sa, sb = sign(a_bits), sign(b_bits)
    sr = sa ^ sb
    if is_nan(a_bits) or is_nan(b_bits):
        return RK_NAN
    if is_inf(a_bits) and is_inf(b_bits):
        return RK_NAN
    if is_zero(a_bits) and is_zero(b_bits):
        return RK_NAN
    if is_inf(a_bits):
        return bits_from_fields(sr, 0x1F, 0)
    if is_inf(b_bits):
        return signed_zero(sr)
    if is_zero(b_bits):
        return bits_from_fields(sr, 0x1F, 0)
    if is_zero(a_bits):
        return signed_zero(sr)
    return round_fraction_to_half(exact_quotient(a_bits, b_bits), "rne")


def bits_to_hex(bits: int) -> str:
    return f"0x{bits:04x}"


def fmt_half(bits: int) -> str:
    if is_nan(bits):
        return "nan"
    if is_inf(bits):
        return "-inf" if sign(bits) else "+inf"
    if is_zero(bits):
        return "-0" if sign(bits) else "+0"
    v = finite_value(bits)
    return f"{float(v):.9g}"
