#!/usr/bin/env /usr/bin/python3
"""Test candidate divider rounding models against every real capture lane.

Models are analysis-side only; no RTL or device access.  Writes only under
team/fdiv-analysis/data/.
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
KV = Path("/home/fedora/rknpu-fpga/build/rk3588-kernel-comparison-v1")
EW = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures/ew-fp16")
EWRES = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/ew-fp16-20261105T201400Z")


def read_halfwords(path: Path) -> list[int]:
    raw = path.read_bytes()
    return list(struct.unpack("<%dH" % (len(raw) // 2), raw))


def load_all():
    sets = {}
    for name, d, outname in [
        ("fdiv8", KV / "real-rocket-fdiv8", "output-raw.fp16"),
        ("special", KV / "real-rocket-fdiv8-special", "output-raw.fp16"),
        ("finite_sweep", KV / "real-rocket-fdiv8-finite-sweep", "output-raw.fp16"),
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


def ulp_context(a, b):
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
    return q, e, ue


def trunc_bits(q, ue, p):
    quant = Fraction(2) ** (ue - p)
    aq = abs(q)
    t = (aq / quant).numerator // (aq / quant).denominator
    v = Fraction(t) * quant
    return -v if q < 0 else v


def model_trunc_then(q, ue, p, mode):
    v = trunc_bits(q, ue, p)
    if v == 0:
        return M.signed_zero(1 if q < 0 else 0)
    return M.round_fraction_to_half(v, mode)


def model_double_round(q, ue, p):
    v = M.round_fraction_to_half(q, "rne") if False else None
    # round exact to (11+p) bits, then to 11 bits, both RNE
    quant = Fraction(2) ** (ue - p)
    aq = abs(q)
    scaled = aq / quant
    n = scaled.numerator // scaled.denominator
    rem = scaled - n
    if rem > Fraction(1, 2) or (rem == Fraction(1, 2) and (n & 1)):
        n += 1
    v = Fraction(n) * quant
    if q < 0:
        v = -v
    if v == 0:
        return M.signed_zero(1 if q < 0 else 0)
    return M.round_fraction_to_half(v, "rne")


def model_exact(q, ue):
    if q == 0:
        return M.signed_zero(1 if q < 0 else 0)
    return M.round_fraction_to_half(q, "rne")


def main():
    sets = load_all()
    lines = []
    total = 0
    for name, lanes in sets.items():
        finite = [(i, a, b, o) for i, (a, b, o) in enumerate(lanes)
                  if not (M.is_nan(a) or M.is_inf(a) or M.is_nan(b) or M.is_inf(b)
                          or M.is_zero(a) or M.is_zero(b))]
        total += len(finite)
        bad = 0
        for i, a, b, o in finite:
            q, e, ue = ulp_context(a, b)
            if model_exact(q, ue) != o:
                bad += 1
        lines.append(f"{name:14s} lanes={len(lanes):5d} finite_nonzero={len(finite):4d} "
                     f"exact_rne_mismatch={bad}")

    lines.append("")
    lines.append(f"TOTAL finite-nonzero device lanes: {total}")
    lines.append("")

    classes = {
        "exact_rne": lambda q, ue: model_exact(q, ue),
    }
    for p in range(0, 9):
        classes[f"truncP{p}_rne"] = (lambda p: (lambda q, ue: model_trunc_then(q, ue, p, "rne")))(p)
        classes[f"truncP{p}_rna"] = (lambda p: (lambda q, ue: model_trunc_then(q, ue, p, "rna")))(p)
        classes[f"roundP{p}_rnd"] = (lambda p: (lambda q, ue: model_double_round(q, ue, p)))(p)

    lines.append("Model mismatch counts over all finite-nonzero lanes:")
    for model_name, fn in classes.items():
        bad = []
        for name, lanes in sets.items():
            for i, (a, b, o) in enumerate(lanes):
                if M.is_nan(a) or M.is_inf(a) or M.is_nan(b) or M.is_inf(b):
                    continue
                if M.is_zero(a) or M.is_zero(b):
                    continue
                q, e, ue = ulp_context(a, b)
                got = fn(q, ue)
                if got != o:
                    bad.append((name, i, o, got))
        lines.append(f"  {model_name:14s} mismatches={len(bad):4d}"
                     + ("" if not bad else f"  first={bad[:3]}"))

    # Which lanes distinguish truncP3 from exact RNE?
    lines.append("")
    lines.append("Lanes where truncP3_rne != exact_rne (predicted anomaly set):")
    diff = []
    for name, lanes in sets.items():
        for i, (a, b, o) in enumerate(lanes):
            if M.is_nan(a) or M.is_inf(a) or M.is_nan(b) or M.is_inf(b):
                continue
            if M.is_zero(a) or M.is_zero(b):
                continue
            q, e, ue = ulp_context(a, b)
            rne = model_exact(q, ue)
            m3 = model_trunc_then(q, ue, 3, "rne")
            if rne != m3:
                diff.append((name, i, a, b, o, rne, m3))
    lines.append(f"count={len(diff)}")
    for name, i, a, b, o, rne, m3 in diff:
        lines.append(f"  {name}[{i}] A={M.bits_to_hex(a)} B={M.bits_to_hex(b)} "
                     f"obs={M.bits_to_hex(o)} rne={M.bits_to_hex(rne)} truncP3={M.bits_to_hex(m3)} "
                     f"{'OK' if o == m3 else 'BAD'}")

    # Also list lanes with the false-tie signature (first 3 extra bits == 100,
    # tail nonzero) so the reader sees the full trigger set, not just failures.
    lines.append("")
    lines.append("All lanes with 3-extra-bit pattern 100 + nonzero tail:")
    for name, lanes in sets.items():
        for i, (a, b, o) in enumerate(lanes):
            if M.is_nan(a) or M.is_inf(a) or M.is_nan(b) or M.is_inf(b):
                continue
            if M.is_zero(a) or M.is_zero(b):
                continue
            q, e, ue = ulp_context(a, b)
            quant = Fraction(2) ** (ue - 3)
            aq = abs(q)
            scaled = aq / quant
            n = scaled.numerator // scaled.denominator
            rem = scaled - n
            if n % 2 == 0 and rem == Fraction(0) and False:
                pass
            # direct check: bits at positions -1,-2,-3 after 11-bit ulp
            base = Fraction(2) ** ue
            frac = aq / base
            nb = frac.numerator // frac.denominator
            r = frac - nb
            r3 = (r * 8).numerator // (r * 8).denominator
            tail = r * 8 - r3
            if r3 == 4 and tail != 0:
                rne = model_exact(q, ue)
                m3 = model_trunc_then(q, ue, 3, "rne")
                lines.append(f"  {name}[{i}] A={M.bits_to_hex(a)} B={M.bits_to_hex(b)} "
                             f"obs={M.bits_to_hex(o)} rne={M.bits_to_hex(rne)} "
                             f"truncP3={M.bits_to_hex(m3)} n_even={(nb % 2) == 0}")

    (DATA / "models.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
