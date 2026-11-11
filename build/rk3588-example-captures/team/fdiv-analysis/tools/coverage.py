#!/usr/bin/env /usr/bin/python3
"""Coverage statistics and class-pair observation scan."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fp16math as M  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
DATA = HERE / "data"
KV = Path("/home/fedora/rknpu-fpga/build/rk3588-kernel-comparison-v1")
EW = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures/ew-fp16")
EWRES = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/ew-fp16-20261105T201400Z")

CLASSES = [
    ("zero_p", 0x0000), ("zero_n", 0x8000), ("inf_p", 0x7C00), ("inf_n", 0xFC00),
    ("qnan", 0x7E00), ("snan", 0x7C01), ("sub_min", 0x0001), ("sub_max", 0x03FF),
    ("norm_min", 0x0400), ("fin_max", 0x7BFF), ("one_p", 0x3C00), ("one_n", 0xBC00),
    ("half_p", 0x3800), ("half_n", 0xB800), ("two_p", 0x4000), ("two_n", 0xC000),
]


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
    # Real 256-pair class grid.
    grid = json.loads((DATA / "systematic_analysis.json").read_text())["rows"]
    sets["fdiv-systematic-grid"] = [
        (int(r["a_bits"], 16), int(r["b_bits"], 16), int(r["observed_bits"], 16))
        for r in grid
    ]
    return sets


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
    tail = r * 8 - m
    return q, e, ue, n, r, m, tail


def main():
    sets = load_all()
    lines = []
    counts = Counter()
    ties = []
    subnormal_results = []
    overflow_results = []
    underflow_zero = []
    false_tie = []
    inexact = []
    for name, lanes in sets.items():
        for i, (a, b, o) in enumerate(lanes):
            if M.is_nan(a) or M.is_inf(a) or M.is_nan(b) or M.is_inf(b):
                continue
            if M.is_zero(a) or M.is_zero(b):
                continue
            q, e, ue, n, r, m, tail = metrics(a, b)
            counts["finite_nonzero"] += 1
            if r != 0:
                counts["inexact"] += 1
                inexact.append((name, i))
            if r == Fraction(1, 2):
                ties.append((name, i, a, b, o, n))
            if ue == -24 and n > 0:
                subnormal_results.append((name, i, a, b, o))
            if e > 15:
                overflow_results.append((name, i, a, b, o))
            if ue == -24 and n == 0 and r < Fraction(1, 2):
                underflow_zero.append((name, i, a, b, o))
            if m == 4 and (r * 8 - m) != 0:
                false_tie.append((name, i, a, b, o, n, n & 1))
            if n & 1:
                counts["n_odd"] += 1
    lines.append(f"counts={dict(counts)}")
    lines.append(f"exact destination-ulp ties: {len(ties)}")
    for t in ties:
        lines.append(f"  {t[0]}[{t[1]}] A={M.bits_to_hex(t[2])} B={M.bits_to_hex(t[3])} "
                     f"obs={M.bits_to_hex(t[4])} n={t[5]}")
    lines.append(f"destination ties detail (bits): " +
                 str([(t[0], t[1], f"{t[4]:04x}", t[5]) for t in ties]))
    lines.append("")
    lines.append(f"false-tie-signature lanes (m==4 with nonzero tail): {len(false_tie)}")
    for f in false_tie:
        lines.append(f"  {f[0]}[{f[1]}] A={M.bits_to_hex(f[2])} B={M.bits_to_hex(f[3])} "
                     f"obs={M.bits_to_hex(f[4])} n={f[5]} n_even={(f[6] == 0)}")
    lines.append("")
    lines.append(f"subnormal nonzero results: {len(subnormal_results)}")
    for s in subnormal_results:
        lines.append(f"  {s[0]}[{s[1]}] A={M.bits_to_hex(s[2])} B={M.bits_to_hex(s[3])} obs={M.bits_to_hex(s[4])}")
    lines.append("")
    lines.append(f"overflow results: {len(overflow_results)}")
    for s in overflow_results:
        lines.append(f"  {s[0]}[{s[1]}] A={M.bits_to_hex(s[2])} B={M.bits_to_hex(s[3])} obs={M.bits_to_hex(s[4])}")
    lines.append("")
    lines.append(f"underflow-to-zero (r<1/2): {len(underflow_zero)}")
    for s in underflow_zero:
        lines.append(f"  {s[0]}[{s[1]}] A={M.bits_to_hex(s[2])} B={M.bits_to_hex(s[3])} obs={M.bits_to_hex(s[4])}")

    # Zero-numerator finite-divisor lanes (p2)
    lines.append("")
    lines.append("zero-numerator lanes with finite nonzero divisor:")
    for name, lanes in sets.items():
        for i, (a, b, o) in enumerate(lanes):
            if M.is_zero(a) and not (M.is_zero(b) or M.is_nan(b) or M.is_inf(b)):
                lines.append(f"  {name}[{i}] A={M.bits_to_hex(a)} B={M.bits_to_hex(b)} "
                             f"({M.fmt_half(b)}) obs={M.bits_to_hex(o)}")

    # Class pair observation scan.
    observed = defaultdict(list)
    for name, lanes in sets.items():
        for i, (a, b, o) in enumerate(lanes):
            for cn, cb in CLASSES:
                if a == cb:
                    for dn, db in CLASSES:
                        if b == db:
                            observed[(cn, dn)].append((name, i, o))
    pairs = []
    for an, ab in CLASSES:
        for bn, bb in CLASSES:
            key = (an, bn)
            obs = observed.get(key, [])
            pairs.append({"a": an, "b": bn, "a_bits": ab, "b_bits": bb,
                          "observed": bool(obs), "evidence": obs[:3]})
    lines.append("")
    lines.append(f"class pairs directly observed with exact class bit patterns: "
                 f"{sum(1 for p in pairs if p['observed'])}/256")
    for p in pairs:
        if p["observed"]:
            lines.append(f"  ({p['a']},{p['b']}) -> " +
                         ", ".join(f"{e[0]}[{e[1]}]=0x{e[2]:04x}" for e in p["evidence"]))

    (DATA / "coverage.txt").write_text("\n".join(lines) + "\n")
    (DATA / "class_pairs_observed.json").write_text(json.dumps(pairs, indent=2) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
