#!/usr/bin/env /usr/bin/python3
"""Dump the special and finite-sweep rows with exact-quotient context."""
from __future__ import annotations

import json
import struct
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fp16math as M  # noqa: E402

KV = Path("/home/fedora/rknpu-fpga/build/rk3588-kernel-comparison-v1")


def read_halfwords(path: Path) -> list[int]:
    raw = path.read_bytes()
    return list(struct.unpack("<%dH" % (len(raw) // 2), raw))


def metrics(a, b):
    q = M.exact_quotient(a, b)
    ax = abs(q)
    e = 0
    if ax >= 1:
        while ax >= Fraction(2) ** (e + 1):
            e += 1
    else:
        while ax < Fraction(2) ** e:
            e -= 1
    ue = max(e - 10, -24)
    scaled = ax / (Fraction(2) ** ue)
    n = scaled.numerator // scaled.denominator
    r = scaled - n
    m = (r * 8).numerator // (r * 8).denominator
    return q, e, ue, n, r, m


def trunc3_rule(q, ue):
    ax = abs(q)
    scaled = ax / (Fraction(2) ** ue)
    n = scaled.numerator // scaled.denominator
    r = scaled - n
    m = (r * 8).numerator // (r * 8).denominator
    if m < 4:
        up = False
    elif m > 4:
        up = True
    else:
        up = (n & 1) == 1
    if up:
        n += 1
    v = Fraction(n) * (Fraction(2) ** ue)
    return M.round_fraction_to_half(v if q >= 0 else -v, "rne") if v != 0 else M.signed_zero(1 if q < 0 else 0)


def main():
    out = []
    for name, d in [("special", KV / "real-rocket-fdiv8-special"),
                    ("finite_sweep", KV / "real-rocket-fdiv8-finite-sweep")]:
        a = read_halfwords(d / "input-a.fp16")
        b = read_halfwords(d / "input-b.fp16")
        o = read_halfwords(d / "output-raw.fp16")
        out.append(f"=== {name} ({len(a)} lanes) ===")
        for i, (aa, bb, oo) in enumerate(zip(a, b, o)):
            donor = None
            ieee = None
            meta = ""
            try:
                ieee = M.ieee_div(aa, bb)
            except Exception as exc:  # pragma: no cover
                ieee = f"err:{exc}"
            if not (M.is_nan(aa) or M.is_inf(aa) or M.is_nan(bb) or M.is_inf(bb) or M.is_zero(aa) or M.is_zero(bb)):
                q, e, ue, n, r, m = metrics(aa, bb)
                m3 = trunc3_rule(q, ue)
                rne = M.round_fraction_to_half(q, "rne")
                meta = (f" q={float(q):.9g} frac={q.numerator}/{q.denominator}"
                        f" e={e} ue={ue} n={n} r={float(r):.6f} m={m}"
                        f" rne={M.bits_to_hex(rne)} m3={M.bits_to_hex(m3)}")
            out.append(
                f"[{i:2d}] A={M.bits_to_hex(aa)}({M.classify(aa)},{M.fmt_half(aa)}) "
                f"B={M.bits_to_hex(bb)}({M.classify(bb)},{M.fmt_half(bb)}) -> "
                f"obs={M.bits_to_hex(oo)}({M.classify(oo)},{M.fmt_half(oo)}) "
                f"ieee={M.bits_to_hex(ieee) if isinstance(ieee, int) else ieee}{meta}")
        out.append("")
    (Path(__file__).resolve().parents[1] / "data" / "rows_dump.txt").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
