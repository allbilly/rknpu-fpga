#!/usr/bin/env /usr/bin/python3
"""Hypothesis tests for the 1024-lane FDIV p1 sequence.

Writes only under team/fdiv-analysis/data/.
"""
from __future__ import annotations

import json
import struct
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fp16math as M  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
DATA = HERE / "data"
EW = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures/ew-fp16")
EWRES = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/ew-fp16-20261105T201400Z")


def read_halfwords(path: Path) -> list[int]:
    raw = path.read_bytes()
    return list(struct.unpack("<%dH" % (len(raw) // 2), raw))


def all_lanes():
    lanes = json.loads((DATA / "lanes.json").read_text())["lanes"]
    return lanes


def p1_lanes():
    a = read_halfwords(EW / "cases/fdiv_p1_n1024/a.bin")[:1024]
    b = read_halfwords(EW / "cases/fdiv_p1_n1024/b.bin")[:1024]
    o = read_halfwords(EWRES / "fdiv_p1_n1024/out.bin")[:1024]
    return list(zip(a, b, o))


def metrics(a, b):
    q = M.exact_quotient(a, b)
    s = 1 if q < 0 else 0
    ax = -q if q < 0 else q
    e = 0
    if ax >= 1:
        while ax >= Fraction(2) ** (e + 1):
            e += 1
    else:
        while ax < Fraction(2) ** e:
            e -= 1
    ulp_exp = max(e - 10, -24)
    ulp = Fraction(2) ** ulp_exp
    scaled = ax / ulp
    n = scaled.numerator // scaled.denominator
    rem = scaled - n
    return q, e, ulp_exp, n, rem, s


def main():
    lines = []
    seq = p1_lanes()
    rows = []
    for i, (a, b, o) in enumerate(seq):
        if M.is_zero(b) or M.is_nan(a) or M.is_nan(b) or M.is_inf(a) or M.is_inf(b) or M.is_zero(a):
            continue
        q, e, ue, n, rem, s = metrics(a, b)
        rne = M.round_fraction_to_half(q, "rne")
        rows.append(dict(i=i, a=a, b=b, o=o, q=q, e=e, ue=ue, n=n, rem=rem,
                         rne=rne, ok=(o == rne)))

    fails = [r for r in rows if not r["ok"]]
    lines.append(f"finite nonzero lanes: {len(rows)}  rne mismatches: {len(fails)}")
    lines.append("")
    lines.append("ALL MISMATCHES (all B=7?):")
    for r in fails:
        A = M.finite_value(r["a"])
        B = M.finite_value(r["b"])
        lines.append(
            f" i={r['i']:4d} A={M.bits_to_hex(r['a'])}={float(A):7.1f} B={M.bits_to_hex(r['b'])}={float(B):4.1f}"
            f" obs={M.bits_to_hex(r['o'])} rne={M.bits_to_hex(r['rne'])}"
            f" n={r['n']} rem={float(r['rem']):.6f} e={r['e']} ue={r['ue']}"
            f" n&3={r['n'] & 3}")

    lines.append("")
    lines.append("B=7 lanes, all (A = 2,10,18,...):")
    b7 = [r for r in rows if r["b"] == 0x4700]
    lines.append(f"count={len(b7)} mismatches={sum(1 for r in b7 if not r['ok'])}")
    for r in b7:
        A = M.finite_value(r["a"])
        lines.append(
            f" A={int(A):4d} n={r['n']:5d} n&15={r['n'] & 15:2d} rem={float(r['rem']):.7f}"
            f" obs={M.bits_to_hex(r['o'])} rne={M.bits_to_hex(r['rne'])}"
            f" {'FAIL' if not r['ok'] else ''}")

    # Which divisors have mismatches?
    from collections import Counter
    lines.append("")
    lines.append("mismatch divisor histogram: " + str(Counter(M.finite_value(r["b"]) for r in fails)))
    # For B=7: what distinguishes failing A?
    # A/7 = (A*9)/63 etc. Look at A mod 7, A mod 8, n mod 2, n mod 8.
    lines.append("")
    lines.append("B=7 discriminator scan:")
    for mod in (2, 3, 4, 7, 8, 16, 32, 64, 128, 256):
        fail_set = sorted({int(M.finite_value(r["a"])) % mod for r in b7 if not r["ok"]})
        ok_set = sorted({int(M.finite_value(r["a"])) % mod for r in b7 if r["ok"]})
        lines.append(f"  A mod {mod:3d}: fail={fail_set} ok={ok_set}")
    for mod in (2, 4, 8, 16, 32, 64, 128):
        fail_set = sorted({r["n"] % mod for r in b7 if not r["ok"]})
        ok_set = sorted({r["n"] % mod for r in b7 if r["ok"]})
        lines.append(f"  n mod {mod:3d}: fail={fail_set} ok={ok_set}")

    # Hypothesis: device implements RNE but with a 10-bit + sticky truncation?
    # General family: round the exact quotient after truncating it to P
    # fractional quotient bits (P bits below the 11-bit significand), then RNE.
    lines.append("")
    lines.append("Truncate-then-RNE hypothesis scan (all 1024 lanes):")
    for P in range(0, 25):
        bad = 0
        for r in rows:
            # truncate |q| to P bits below the 11-bit significand, then RNE
            ulp = Fraction(2) ** r["ue"]
            quant = Fraction(2) ** (r["ue"] - P)
            t = (abs(r["q"]) / quant).numerator // (abs(r["q"]) / quant).denominator
            trunc = Fraction(t) * quant
            if r["q"] < 0:
                trunc = -trunc
            model = M.round_fraction_to_half(trunc, "rne") if trunc != 0 else M.signed_zero(M.sign(r["a"]) ^ M.sign(r["b"]))
            if model != r["o"]:
                bad += 1
        lines.append(f"  P={P:2d} mismatches={bad}")

    # Hypothesis: quotient computed as a/b via reciprocal rounded to half then
    # multiply (round each step).
    lines.append("")
    lines.append("reciprocal-then-multiply hypothesis (half-rounded 1/b, half-rounded product):")
    bad = 0
    bad_idx = []
    for r in rows:
        recip = M.round_fraction_to_half(1 / M.finite_value(r["b"]), "rne")
        model = M.round_fraction_to_half(M.finite_value(r["a"]) * M.finite_value(recip), "rne")
        if model != r["o"]:
            bad += 1
            bad_idx.append(r["i"])
    lines.append(f"  mismatches={bad} first={bad_idx[:20]}")

    # Hypothesis: reciprocal in float32 then multiply then half (i.e. donor) =
    # RNE, already covered.

    # Look at the 19 failures: exact quotient binary expansion.
    lines.append("")
    lines.append("Failure quotient binary expansions (first 24 significant bits):")
    for r in fails:
        q = abs(r["q"])
        e = r["e"]
        scaled = q / (Fraction(2) ** e)  # in [1,2)
        bits = ""
        x = scaled
        for _ in range(24):
            x *= 2
            if x >= 1:
                bits += "1"
                x -= 1
            else:
                bits += "0"
        lines.append(f" i={r['i']:4d} e={e:3d} 1.{bits}")

    (DATA / "hypotheses.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
