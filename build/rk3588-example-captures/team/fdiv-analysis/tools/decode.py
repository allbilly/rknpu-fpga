#!/usr/bin/env /usr/bin/python3
"""Decode the real RK3588 FDIV captures and classify each lane.

Reads only files under build/.  Writes only under
build/rk3588-example-captures/team/fdiv-analysis/data/.
"""
from __future__ import annotations

import json
import struct
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fp16math as M  # noqa: E402

REPO = Path("/home/fedora/rknpu-fpga")
KV = REPO / "build/rk3588-kernel-comparison-v1"
EW = REPO / "build/rk3588-example-captures/ew-fp16"
EWRES = REPO / "build/rk3588-example-captures/results/ew-fp16-20261105T201400Z"
OUT = Path(__file__).resolve().parents[1] / "data"

CAPTURES = [
    ("fdiv8", KV / "real-rocket-fdiv8", "output-raw.fp16"),
    ("special", KV / "real-rocket-fdiv8-special", "output-raw.fp16"),
    ("finite_sweep", KV / "real-rocket-fdiv8-finite-sweep", "output-raw.fp16"),
]

EW_CASES = [
    "fdiv_p1_n1", "fdiv_p1_n7", "fdiv_p1_n8", "fdiv_p1_n9", "fdiv_p1_n33",
    "fdiv_p1_n1024", "fdiv_p2_n8", "fdiv_p2_n9", "fdiv_p2_n33",
]


def read_halfwords(path: Path) -> list[int]:
    raw = path.read_bytes()
    return list(struct.unpack("<%dH" % (len(raw) // 2), raw))


def ulp_metrics(a: int, b: int):
    """Return dict describing the exact quotient against binary16 neighbors."""
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
    down = M.round_fraction_to_half(q, "rz")
    up = M.round_fraction_to_half(q, "rne")
    away = M.round_fraction_to_half(q, "rna")
    # neighbor above toward +inf
    plus = M.round_fraction_to_half(q, "rup")
    return {
        "exact": q,
        "ulp_exp": ulp_exp,
        "n": n,
        "rem": rem,
        "frac": float(rem),
        "rne": up,
        "rz": down,
        "rna": away,
        "rup": plus,
        "guard1": bool(rem >= Fraction(1, 2)),
        "tie": rem == Fraction(1, 2),
        "sticky_lsb": (n & 1),
    }


def lane_record(i, a, b, observed, source):
    r = {
        "index": i,
        "a_bits": a,
        "b_bits": b,
        "a_class": M.classify(a),
        "b_class": M.classify(b),
        "a_hex": M.bits_to_hex(a),
        "b_hex": M.bits_to_hex(b),
        "observed_bits": observed,
        "observed_hex": M.bits_to_hex(observed),
        "observed_class": M.classify(observed),
        "source": source,
        "finite_operands": not (M.is_nan(a) or M.is_inf(a) or M.is_nan(b) or M.is_inf(b)),
        "zero_operands": M.is_zero(a) or M.is_zero(b),
    }
    if r["finite_operands"] and not r["zero_operands"]:
        m = ulp_metrics(a, b)
        q = m["exact"]
        sb = M.sign(a) ^ M.sign(b)
        r.update({
            "exact_fraction": f"{q.numerator}/{q.denominator}",
            "exact_decimal": f"{float(q):.12g}",
            "rne_bits": m["rne"],
            "rz_bits": m["rz"],
            "rna_bits": m["rna"],
            "rup_bits": m["rup"],
            "observed_minus_rne": observed - m["rne"],
            "observed_eq_rne": observed == m["rne"],
            "observed_eq_rz": observed == m["rz"],
            "observed_eq_rna": observed == m["rna"],
            "quotient_ulp_index": m["n"],
            "quotient_ulp_frac": m["frac"],
            "quotient_tie_12": m["tie"],
            "sign": sb,
        })
    return r


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"sources": {}, "lanes": []}

    for name, d, outname in CAPTURES:
        a = read_halfwords(d / "input-a.fp16")
        b = read_halfwords(d / "input-b.fp16")
        o = read_halfwords(d / outname)
        cap = json.loads((d / "capture.json").read_text())
        assert a == cap["a_bits"], (name, "a mismatch")
        assert b == cap["b_bits"], (name, "b mismatch")
        assert o == cap["out_bits"], (name, "out mismatch")
        report["sources"][name] = {
            "path": str(d),
            "lanes": len(a),
            "ew_cfg": cap.get("ew_cfg"),
            "out_convert": cap.get("out_convert"),
            "rdma_mode": cap.get("rdma_mode"),
            "capture_sha256": cap.get("output_full_sha256"),
            "scope": cap.get("scope"),
            "width_0x4030_0x500c": cap.get("width_0x4030_0x500c"),
            "device": cap.get("device", cap.get("device_node")),
        }
        for i, (aa, bb, oo) in enumerate(zip(a, b, o)):
            report["lanes"].append(lane_record(i, aa, bb, oo, name))

    for case in EW_CASES:
        cd = EW / "cases" / case
        rd = EWRES / case
        a = read_halfwords(cd / "a.bin")
        b = read_halfwords(cd / "b.bin")
        o = read_halfwords(rd / "out.bin")
        cap = json.loads((rd / "capture.json").read_text())
        # logical count from job description
        job = json.loads((cd / "job.json").read_text())
        import re
        match = re.search(r"N=(\d+)", job["description"])
        assert match is not None
        n = int(match.group(1))
        padded = 8 * ((n + 7) // 8)
        assert len(o) >= padded
        report["sources"][case] = {
            "path": str(rd),
            "lanes": n,
            "padded": padded,
            "ew_cfg": 0x108303C0,
            "out_convert": 1,
            "rdma_mode": 0x00017841,
            "capture_sha256": cap["hashes"]["out"],
            "scope": "ew-fp16 finite FDIV on /dev/accel/accel0",
            "device": cap["device_path"],
            "hostname": cap.get("hostname"),
            "kernel": cap.get("kernel"),
            "started_utc": cap.get("started_utc"),
            "b_pattern": "8..1 cyclic" if "p1" in case else "0.5..3.5 cyclic",
        }
        for i in range(n):
            report["lanes"].append(lane_record(i, a[i], b[i], o[i], case))

    (OUT / "lanes.json").write_text(json.dumps(report, indent=2) + "\n")

    # Human-readable per-source summary.
    lines = []
    for name, _, _ in CAPTURES:
        src = [x for x in report["lanes"] if x["source"] == name]
        bad = [x for x in src if x.get("observed_eq_rne") is False]
        lines.append(f"{name}: lanes={len(src)} "
                     f"finite_nonzero={sum(1 for x in src if x.get('rne_bits') is not None)} "
                     f"ne_rne={len(bad)}")
        for x in bad:
            lines.append(
                f"  {name}[{x['index']}] A={x['a_hex']} B={x['b_hex']} "
                f"obs={x['observed_hex']} rne={M.bits_to_hex(x['rne_bits'])} "
                f"rz={M.bits_to_hex(x['rz_bits'])} d={x['observed_minus_rne']} "
                f"q={x['exact_decimal']} frac={x['quotient_ulp_frac']:.6f}")
    for case in EW_CASES:
        src = [x for x in report["lanes"] if x["source"] == case]
        bad = [x for x in src if x.get("observed_eq_rne") is False]
        lines.append(f"{case}: lanes={len(src)} ne_rne={len(bad)} "
                     f"ne_rz={sum(1 for x in src if x.get('observed_eq_rz') is False)}")
    (OUT / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
