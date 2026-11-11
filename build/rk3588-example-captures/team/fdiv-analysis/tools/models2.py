#!/usr/bin/env /usr/bin/python3
"""Second-round model checks: subnormal quantum forms and donor comparison."""
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
    return q, e, ue


def model_final_ulp(q, e, ue):
    """Quantize 3 bits below the FINAL ulp, ties-to-even, ignore the tail."""
    u = Fraction(2) ** ue
    scaled = abs(q) / u
    n = scaled.numerator // scaled.denominator
    r = scaled - n
    m = (r * 8).numerator // (r * 8).denominator
    if m > 4 or (m == 4 and (n & 1)):
        n += 1
    v = Fraction(n) * u
    if v == 0:
        return M.signed_zero(1 if q < 0 else 0)
    return M.round_fraction_to_half(-v if q < 0 else v, "rne")


def model_norm14(q, e, ue):
    """3 extra bits below the NORMALIZED (e-10) ulp, then subnormal truncation."""
    u_norm = Fraction(2) ** (e - 10)
    scaled = abs(q) / u_norm
    n = scaled.numerator // scaled.denominator
    r = scaled - n
    m = (r * 8).numerator // (r * 8).denominator
    if m > 4 or (m == 4 and (n & 1)):
        n += 1
    v = Fraction(n) * u_norm
    if v == 0:
        return M.signed_zero(1 if q < 0 else 0)
    if v < Fraction(2) ** -14:
        # truncate to the subnormal grid (no rounding)
        k = (v / (Fraction(2) ** -24)).numerator // (v / (Fraction(2) ** -24)).denominator
        v = Fraction(k) * (Fraction(2) ** -24)
    if v == 0:
        return M.signed_zero(1 if q < 0 else 0)
    return M.round_fraction_to_half(-v if q < 0 else v, "rne")


def main():
    sets = load_all()
    lines = []
    for mname, fn in [("final_ulp_quantum", model_final_ulp), ("normalized_14bit", model_norm14)]:
        bad = []
        for name, lanes in sets.items():
            for i, (a, b, o) in enumerate(lanes):
                if M.is_nan(a) or M.is_inf(a) or M.is_nan(b) or M.is_inf(b):
                    continue
                if M.is_zero(a) or M.is_zero(b):
                    continue
                q, e, ue = ctx(a, b)
                if fn(q, e, ue) != o:
                    bad.append((name, i, o))
        lines.append(f"{mname}: mismatches={len(bad)} first={bad[:5]}")

    # Subnormal inexact lanes only, detail.
    lines.append("")
    lines.append("Subnormal-result inexact lanes:")
    for name, lanes in sets.items():
        for i, (a, b, o) in enumerate(lanes):
            if M.is_nan(a) or M.is_inf(a) or M.is_nan(b) or M.is_inf(b):
                continue
            if M.is_zero(a) or M.is_zero(b):
                continue
            q, e, ue = ctx(a, b)
            if ue != -24:
                continue
            u = Fraction(2) ** -24
            scaled = abs(q) / u
            n = scaled.numerator // scaled.denominator
            r = scaled - n
            if r == 0:
                continue
            lines.append(f"  {name}[{i}] A={M.bits_to_hex(a)} B={M.bits_to_hex(b)} obs={M.bits_to_hex(o)} "
                         f"n={n} r={float(r):.6f} final={M.bits_to_hex(model_final_ulp(q, e, ue))} "
                         f"norm14={M.bits_to_hex(model_norm14(q, e, ue))}")

    # Donor NumPy comparison for special rows and sweep rows.
    import numpy as np
    lines.append("")
    lines.append(f"numpy={np.__version__}")
    for name, d in [("special", KV / "real-rocket-fdiv8-special"),
                    ("finite_sweep", KV / "real-rocket-fdiv8-finite-sweep")]:
        a = read_halfwords(d / "input-a.fp16")
        b = read_halfwords(d / "input-b.fp16")
        o = read_halfwords(d / "output-raw.fp16")
        av = np.frombuffer((d / "input-a.fp16").read_bytes(), dtype="<f2").astype(np.float32)
        bv = np.frombuffer((d / "input-b.fp16").read_bytes(), dtype="<f2").astype(np.float32)
        with np.errstate(all="ignore"):
            donor = (av / bv).astype(np.float16)
        donor_bits = [int(x) for x in donor.view(np.uint16)]
        lines.append(f"{name} donor-vs-device mismatches: "
                     f"{sum(1 for x, y in zip(donor_bits, o) if x != y)}")
        for i, (x, y) in enumerate(zip(donor_bits, o)):
            if x != y:
                lines.append(f"  [{i}] donor=0x{x:04x} device=0x{y:04x} "
                             f"A=0x{a[i]:04x} B=0x{b[i]:04x}")
    (DATA / "models2.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
