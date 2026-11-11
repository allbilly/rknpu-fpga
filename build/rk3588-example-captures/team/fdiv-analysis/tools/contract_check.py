#!/usr/bin/env /usr/bin/python3
"""Self-check the proposed RK FDIV contract against every real capture lane.

This is a behavioural model, not RTL and not a device oracle.  It implements
the pseudocode in FDIV_CONTRACT.md §5.2-5.5 literally (including the
special-case sign(a) rule) and compares the result bit-for-bit with the
captured device output.

Writes only under team/fdiv-analysis/.  Exits non-zero on any mismatch.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = Path("/home/fedora/rknpu-fpga")
KV = REPO / "build/rk3588-kernel-comparison-v1"
EW = REPO / "build/rk3588-example-captures/ew-fp16"
EWRES = REPO / "build/rk3588-example-captures/results/ew-fp16-20261105T201400Z"
SYS = REPO / "build/rk3588-example-captures/results/fdiv-systematic-20261105T204746Z"


def read_halfwords(path: Path) -> list[int]:
    raw = path.read_bytes()
    return list(struct.unpack("<%dH" % (len(raw) // 2), raw))


def msb(x: int) -> int:
    return x.bit_length() - 1


def fdiv(a: int, b: int) -> int:
    sa, sb = a >> 15, b >> 15
    sr = sa ^ sb
    ea, fa = (a >> 10) & 31, a & 1023
    eb, fb = (b >> 10) & 31, b & 1023
    a_nan = ea == 31 and fa != 0
    b_nan = eb == 31 and fb != 0
    a_inf = ea == 31 and fa == 0
    b_inf = eb == 31 and fb == 0
    a_zero = (a & 0x7FFF) == 0
    b_zero = (b & 0x7FFF) == 0

    # Special precedence (§5.2).  Special results use sign(a), not sign xor.
    if a_nan or b_nan:
        return 0x7C01
    if a == 0x0000 and b == 0x0000:
        return 0x7C01
    if b_zero:
        return (sa << 15) | 0x7C00
    if a_zero:
        return sa << 15
    if a_inf:
        return (sa << 15) | 0x7C00
    if b_inf:
        return sa << 15

    # Finite path (§5.3).  Normalize to integer significands.
    if ea != 0:
        ma, ea_u = 1024 | fa, ea - 15
    else:
        k = 10 - msb(fa)
        ma, ea_u = fa << k, -14 - k
    if eb != 0:
        mb, eb_u = 1024 | fb, eb - 15
    else:
        k = 10 - msb(fb)
        mb, eb_u = fb << k, -14 - k

    if ma >= mb:
        e, qn, qd = ea_u - eb_u, ma, mb
    else:
        e, qn, qd = ea_u - eb_u - 1, ma << 1, mb

    ue = e - 10 if e >= -14 else -24
    shift = e - ue + 3
    if shift >= 0:
        d = (qn << shift) // qd
    else:
        d = qn // (qd << -shift)
    n, m = d >> 3, d & 7

    # Round to nearest, ties-to-even on the truncated significand.
    if m > 4 or (m == 4 and (n & 1)):
        n += 1

    # Pack (§5.5).
    if n == 2048:
        n, e = 1024, e + 1
    if n == 1024 and e < -14:
        e = -14
    if e < -14:
        return (sr << 15) | (n & 1023)
    if e > 15:
        return (sr << 15) | 0x7C00
    return (sr << 15) | ((e + 15) << 10) | ((n - 1024) & 1023)


def load_all():
    sets = {}
    for name, d in [
        ("real-rocket-fdiv8", KV / "real-rocket-fdiv8"),
        ("real-rocket-fdiv8-special", KV / "real-rocket-fdiv8-special"),
        ("real-rocket-fdiv8-finite-sweep", KV / "real-rocket-fdiv8-finite-sweep"),
    ]:
        sets[name] = list(zip(read_halfwords(d / "input-a.fp16"),
                              read_halfwords(d / "input-b.fp16"),
                              read_halfwords(d / "output-raw.fp16")))
    for case, n in [
        ("fdiv_p1_n1", 1), ("fdiv_p1_n7", 7), ("fdiv_p1_n8", 8),
        ("fdiv_p1_n9", 9), ("fdiv_p1_n33", 33), ("fdiv_p1_n1024", 1024),
        ("fdiv_p2_n8", 8), ("fdiv_p2_n9", 9), ("fdiv_p2_n33", 33),
    ]:
        a = read_halfwords(EW / "cases" / case / "a.bin")
        b = read_halfwords(EW / "cases" / case / "b.bin")
        o = read_halfwords(EWRES / case / "out.bin")
        sets[case] = list(zip(a[:n], b[:n], o[:n]))
    lines = (SYS / "class_results.tsv").read_text().splitlines()
    header = lines[0].split("\t")
    rows = [dict(zip(header, line.split("\t"))) for line in lines[1:]]
    sets["fdiv-systematic"] = [
        (int(r["A_bits"], 16), int(r["B_bits"], 16), int(r["out_bits"], 16))
        for r in rows
    ]
    return sets


def main() -> int:
    sets = load_all()
    total = 0
    bad = []
    for name, lanes in sets.items():
        nbad = 0
        for i, (a, b, o) in enumerate(lanes):
            total += 1
            got = fdiv(a, b)
            if got != o:
                nbad += 1
                bad.append((name, i, a, b, o, got))
        print(f"{name:28s} lanes={len(lanes):5d} mismatches={nbad}")
    print(f"TOTAL lanes={total} mismatches={len(bad)}")
    if bad:
        for row in bad[:20]:
            print("  MISMATCH", row[0], row[1],
                  f"A=0x{row[2]:04x} B=0x{row[3]:04x} "
                  f"obs=0x{row[4]:04x} contract=0x{row[5]:04x}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
