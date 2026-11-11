#!/usr/bin/env /usr/bin/python3
"""Characterise the one-ULP-low window and the A/7 subsequence of p1_n1024."""
from __future__ import annotations

import struct
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fp16math as M  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
DATA = HERE / "data"
KV = Path("/home/fedora/rknpu-fpga/build/rk3588-kernel-comparison-v1")
EW = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures/ew-fp16")
EWRES = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/ew-fp16-20261105T201400Z")


def read_halfwords(path: Path) -> list[int]:
    raw = path.read_bytes()
    return list(struct.unpack("<%dH" % (len(raw) // 2), raw))


def load_all():
    sets = {}
    for name, d, outname in [
        ("real-rocket-fdiv8", KV / "real-rocket-fdiv8", "output-raw.fp16"),
        ("real-rocket-fdiv8-special", KV / "real-rocket-fdiv8-special", "output-raw.fp16"),
        ("real-rocket-fdiv8-finite-sweep", KV / "real-rocket-fdiv8-finite-sweep", "output-raw.fp16"),
    ]:
        sets[name] = list(zip(read_halfwords(d / "input-a.fp16"),
                              read_halfwords(d / "input-b.fp16"),
                              read_halfwords(d / outname)))
    for case, n in [
        ("fdiv_p1_n1", 1), ("fdiv_p1_n7", 7), ("fdiv_p1_n8", 8),
        ("fdiv_p1_n9", 9), ("fdiv_p1_n33", 33), ("fdiv_p1_n1024", 1024),
        ("fdiv_p2_n8", 8), ("fdiv_p2_n9", 9), ("fdiv_p2_n33", 33),
    ]:
        a = read_halfwords(EW / "cases" / case / "a.bin")
        b = read_halfwords(EW / "cases" / case / "b.bin")
        o = read_halfwords(EWRES / case / "out.bin")
        sets[case] = list(zip(a[:n], b[:n], o[:n]))
    return sets


def ctx(a, b):
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
    return q, e, ue, n, r


def main():
    lines = []
    sets = load_all()
    window_all = []
    for name, lanes in sets.items():
        for i, (a, b, o) in enumerate(lanes):
            if M.is_nan(a) or M.is_inf(a) or M.is_nan(b) or M.is_inf(b):
                continue
            if M.is_zero(a) or M.is_zero(b):
                continue
            q, e, ue, n, r = ctx(a, b)
            if Fraction(1, 2) < r < Fraction(5, 8):
                window_all.append((name, i, a, b, o, n, r, n & 1))
    lines.append(f"lanes with 0.5 < frac < 0.625 (any n): {len(window_all)}")
    for w in window_all:
        lines.append(f"  {w[0]}[{w[1]}] A={M.bits_to_hex(w[2])} B={M.bits_to_hex(w[3])} "
                     f"obs={M.bits_to_hex(w[4])} n={w[5]} n_even={(w[7] == 0)} frac={float(w[6]):.6f}")
    lines.append("")
    lines.append(f"of those, n even (predicted 1 ULP low): "
                 f"{sum(1 for w in window_all if w[7] == 0)} across "
                 f"{len({(w[2], w[3]) for w in window_all if w[7] == 0})} unique operand pairs")
    lines.append("")

    # A/7 subsequence of p1_n1024.
    p1 = sets["fdiv_p1_n1024"]
    a7 = [(i, a, b, o) for i, (a, b, o) in enumerate(p1) if b == 0x4700]
    lines.append(f"p1_n1024 lanes with B=7.0: {len(a7)}")
    fails = []
    for i, a, b, o in a7:
        q, e, ue, n, r = ctx(a, b)
        rne = M.round_fraction_to_half(q, "rne")
        m = (r * 8).numerator // (r * 8).denominator
        ok = o == rne
        if not ok:
            fails.append((i, a, o, rne, n, r, m))
    lines.append(f"device != exact RNE: {len(fails)}")
    lines.append("failing A values: " + ", ".join(str(int(M.finite_value(a))) for _, a, _, _, _, _, _ in fails))
    from collections import Counter
    lines.append("rem histogram over B=7 lanes: " + str(Counter(
        str(r) for _, a, b, _o in a7 for _q, _e, _u, _n, r in [ctx(a, b)])))
    lines.append("")
    # For each B divisor, count model mismatches in p1.
    for bbits in (0x4100, 0x4700, 0x4600, 0x4500, 0x4400, 0x4300, 0x4200, 0x3C00):
        lanes = [(i, a, b, o) for i, (a, b, o) in enumerate(p1) if b == bbits]
        if not lanes:
            continue
        bad = 0
        inexact = 0
        for i, a, b, o in lanes:
            q, e, ue, n, r = ctx(a, b)
            if r != 0:
                inexact += 1
            rne = M.round_fraction_to_half(q, "rne")
            # final-ulp 3-bit model
            m = (r * 8).numerator // (r * 8).denominator
            nn = n
            if m > 4 or (m == 4 and (nn & 1)):
                nn += 1
            v = Fraction(nn) * (Fraction(2) ** ue)
            model = M.signed_zero(0) if v == 0 else M.round_fraction_to_half(v if q > 0 else -v, "rne")
            if model != o:
                bad += 1
        lines.append(f"  B={M.fmt_half(bbits):>4s} lanes={len(lanes):4d} inexact={inexact:4d} "
                     f"model_mismatch={bad}")
    (DATA / "window.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
