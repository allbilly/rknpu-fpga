#!/usr/bin/env python3
"""Infer the captured RK3588 finite-FDIV rounding rule from the real sweep.

Reads build/rk3588-kernel-comparison-v1/real-rocket-fdiv8-finite-sweep/
capture.json (32 lanes) and classifies each lane against candidate rules:
  * IEEE binary16 round-to-nearest, ties-to-even of the exact rational
  * truncate-toward-zero of the exact rational to binary16
  * Python float64 division then struct '<e' (double rounding proxy)
  * numpy float32 division then float16 cast
No device access; this only reads the already-captured file.
"""
from __future__ import annotations

import json
import struct
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAP = ROOT / "rk3588-kernel-comparison-v1/real-rocket-fdiv8-finite-sweep/capture.json"


def from_bits(bits: int) -> Fraction:
    sign = -1 if bits >> 15 else 1
    exp = (bits >> 10) & 0x1F
    frac = bits & 0x3FF
    if exp == 0x1F:
        raise ValueError("non-finite operand in finite sweep")
    if exp == 0:
        return sign * Fraction(frac, 1 << 24)
    return sign * Fraction(1024 + frac, 1024) * Fraction(2) ** (exp - 15)


def round_nearest_even_half(value: Fraction) -> int:
    """Correct IEEE binary16 round-to-nearest, ties-to-even for value != 0."""
    sign = 0x8000 if value < 0 else 0
    v = abs(value)
    if v == 0:
        return sign
    # Subnormal range: multiples of 2^-24.
    if v < Fraction(1, 1 << 14):
        scaled = v * (1 << 24)
        n = scaled.numerator // scaled.denominator
        rem = scaled - n
        if rem > Fraction(1, 2) or (rem == Fraction(1, 2) and n % 2):
            n += 1
        return sign | n
    # Normal range: find exponent e with 2^e <= v < 2^(e+1), e in [-14, 15].
    e = v.numerator.bit_length() - v.denominator.bit_length()
    if Fraction(2) ** e > v:
        e -= 1
    while Fraction(2) ** (e + 1) <= v:
        e += 1
    scaled = v / Fraction(2) ** e * 1024  # in [1024, 2048)
    n = scaled.numerator // scaled.denominator
    rem = scaled - n
    if rem > Fraction(1, 2) or (rem == Fraction(1, 2) and n % 2):
        n += 1
    if n == 2048:
        n = 1024
        e += 1
    if e > 15:
        return sign | 0x7C00
    return sign | ((e + 15) << 10) | (n - 1024)


def truncate_half(value: Fraction) -> int:
    """Round toward zero to binary16 (RK candidate)."""
    sign = 0x8000 if value < 0 else 0
    v = abs(value)
    if v == 0:
        return sign
    if v < Fraction(1, 1 << 14):
        n = (v * (1 << 24)).numerator // (v * (1 << 24)).denominator
        return sign | n
    e = v.numerator.bit_length() - v.denominator.bit_length()
    if Fraction(2) ** e > v:
        e -= 1
    while Fraction(2) ** (e + 1) <= v:
        e += 1
    n = (v / Fraction(2) ** e * 1024)
    n = n.numerator // n.denominator
    if n > 2047:
        return sign | 0x7C00
    return sign | ((e + 15) << 10) | (n - 1024)


def float64_rule(a: int, b: int) -> int:
    x = struct.unpack("<e", struct.pack("<H", a))[0]
    y = struct.unpack("<e", struct.pack("<H", b))[0]
    try:
        return struct.unpack("<H", struct.pack("<e", x / y))[0]
    except OverflowError:
        return 0xFC00 if (x / y) < 0 else 0x7C00


def is_tie(value: Fraction) -> bool:
    v = abs(value)
    if v == 0:
        return False
    if v < Fraction(1, 1 << 14):
        scaled = v * (1 << 24)
    else:
        e = v.numerator.bit_length() - v.denominator.bit_length()
        if Fraction(2) ** e > v:
            e -= 1
        while Fraction(2) ** (e + 1) <= v:
            e += 1
        scaled = v / Fraction(2) ** e * 1024
    return scaled - (scaled.numerator // scaled.denominator) == Fraction(1, 2)


def main() -> int:
    cap = json.loads(CAP.read_text())
    ab, bb, ob = cap["a_bits"], cap["b_bits"], cap["out_bits"]
    assert len(ab) == len(bb) == len(ob) == cap["lanes"]
    counts = {"nearest_even": 0, "truncate": 0, "float64": 0}
    rows = []
    for lane, (a, b, o) in enumerate(zip(ab, bb, ob)):
        q = from_bits(a) / from_bits(b)
        cand = {
            "nearest_even": round_nearest_even_half(q),
            "truncate": truncate_half(q),
            "float64": float64_rule(a, b),
        }
        for k, v in cand.items():
            if v == o:
                counts[k] += 1
        rows.append((lane, a, b, o, cand))
    print(f"lanes={len(rows)} rule matches: {counts}")
    mismatch = [r for r in rows if r[4]["truncate"] != r[3]]
    print(f"truncate mismatches: {len(mismatch)}")
    for lane, a, b, o, cand in mismatch:
        print(
            f"  lane {lane:2d} a=0x{a:04x} b=0x{b:04x} out=0x{o:04x} "
            f"nearest=0x{cand['nearest_even']:04x} trunc=0x{cand['truncate']:04x} "
            f"f64=0x{cand['float64']:04x}"
        )
    # show lanes where nearest and truncate disagree, to characterise policy
    diff = [r for r in rows if r[4]["nearest_even"] != r[4]["truncate"]]
    print(f"nearest/truncate differ on {len(diff)} lanes; out follows truncate "
          f"{sum(r[3] == r[4]['truncate'] for r in diff)}/{len(diff)}")
    for lane, a, b, o, cand in diff:
        print(
            f"  differ lane {lane:2d} a=0x{a:04x} b=0x{b:04x} out=0x{o:04x} "
            f"nearest=0x{cand['nearest_even']:04x} trunc=0x{cand['truncate']:04x}"
        )
    ties = []
    for lane, (a, b, o) in enumerate(zip(ab, bb, ob)):
        q = from_bits(a) / from_bits(b)
        if is_tie(q):
            ties.append((lane, a, b, o, round_nearest_even_half(q)))
    print(f"exact ties: {len(ties)}")
    for lane, a, b, o, nearest in ties:
        print(f"  tie lane {lane:2d} a=0x{a:04x} b=0x{b:04x} out=0x{o:04x} "
              f"nearest_even=0x{nearest:04x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
