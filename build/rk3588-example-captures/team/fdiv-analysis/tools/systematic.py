#!/usr/bin/env /usr/bin/python3
"""Analyse the real 256-pair FDIV class grid and re-derive special rules.

Writes only under team/fdiv-analysis/.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fp16math as M  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
DATA = HERE / "data"
REPO = Path("/home/fedora/rknpu-fpga")
RES = REPO / "build/rk3588-example-captures/results/fdiv-systematic-20261105T204746Z"
SYSTEMATIC = REPO / "build/rk3588-example-captures/fdiv-systematic"

CLASSES = [
    ("zero_p", 0x0000), ("zero_n", 0x8000), ("inf_p", 0x7C00), ("inf_n", 0xFC00),
    ("qnan", 0x7E00), ("snan", 0x7C01), ("sub_min", 0x0001), ("sub_max", 0x03FF),
    ("norm_min", 0x0400), ("fin_max", 0x7BFF), ("one_p", 0x3C00), ("one_n", 0xBC00),
    ("half_p", 0x3800), ("half_n", 0xB800), ("two_p", 0x4000), ("two_n", 0xC000),
]
FINITE = {"sub_min", "sub_max", "norm_min", "fin_max", "one_p", "one_n",
          "half_p", "half_n", "two_p", "two_n"}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_halfwords(p: Path) -> list[int]:
    raw = p.read_bytes()
    return list(struct.unpack("<%dH" % (len(raw) // 2), raw))


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
    mm = (r * 8).numerator // (r * 8).denominator
    return q, e, ue, n, r, mm


def model_3g(q, ue):
    u = Fraction(2) ** ue
    scaled = abs(q) / u
    n = scaled.numerator // scaled.denominator
    r = scaled - n
    mm = (r * 8).numerator // (r * 8).denominator
    if mm > 4 or (mm == 4 and (n & 1)):
        n += 1
    v = Fraction(n) * u
    if v == 0:
        return M.signed_zero(1 if q < 0 else 0)
    return M.round_fraction_to_half(-v if q < 0 else v, "rne")


def classify_rule(a, b):
    """Return (predicted_bits, rule_name) under the corrected RK contract."""
    sa, sb = M.sign(a), M.sign(b)
    if M.is_nan(a) or M.is_nan(b):
        return 0x7C01, "nan"
    if M.is_zero(a) and M.is_zero(b):
        if a == 0x0000 and b == 0x0000:
            return 0x7C01, "zero-zero-plus"
        return (sa << 15) | 0x7C00, "zero-zero-inf-sign-a"
    if M.is_zero(b):
        return (sa << 15) | 0x7C00, "div-zero-sign-a"
    if M.is_inf(a):
        return (sa << 15) | 0x7C00, "inf-num-sign-a"
    if M.is_inf(b):
        return sa << 15, "inf-den-sign-a"
    if M.is_zero(a):
        return sa << 15, "zero-num-sign-a"
    q, e, ue, n, r, mm = ctx(a, b)
    return model_3g(q, ue), "finite-3g-rne-sign-xor"


def main():
    import numpy as np

    ev = json.loads((RES / "run_evidence.json").read_text())
    js = json.loads((RES / "class_results.json").read_text())
    tsv_lines = (RES / "class_results.tsv").read_text().splitlines()
    tsv_header = tsv_lines[0].split("\t")
    tsv = [dict(zip(tsv_header, line.split("\t"))) for line in tsv_lines[1:]]
    assert len(tsv) == 256

    # Verify per-case output.bin against the host-copied result and the TSV.
    case_files = {
        "fdiv_class_rows_00_01": RES / "fdiv-systematic/fdiv_class_rows_00_01/output.bin",
        "fdiv_class_rows_02_03": RES / "fdiv-systematic/fdiv_class_rows_02_03/output.bin",
        "fdiv_class_rows_04_05": RES / "fdiv-systematic/fdiv_class_rows_04_05/output.bin",
        "fdiv_class_rows_06_07": RES / "fdiv-systematic/fdiv_class_rows_06_07/output.bin",
        "fdiv_class_rows_08_09": RES / "fdiv-systematic/fdiv_class_rows_08_09/output.bin",
        "fdiv_class_rows_10_11": RES / "fdiv-systematic/fdiv_class_rows_10_11/output.bin",
        "fdiv_class_rows_12_13": RES / "fdiv-systematic/fdiv_class_rows_12_13/output.bin",
        "fdiv_class_rows_14_15": RES / "fdiv-systematic/fdiv_class_rows_14_15/output.bin",
    }
    audit = {"output_bins": {}, "checks": {}}
    for case, path in case_files.items():
        raw = path.read_bytes()
        hw = list(struct.unpack("<%dH" % (len(raw) // 2), raw))
        exp = [int(x["out_bits"], 16) for x in js["cases"][case]]
        tsv_case = [int(x["out_bits"], 16) for x in tsv if x["case"] == case]
        audit["output_bins"][case] = {
            "bytes": len(raw), "sha256": sha256(path),
            "halfwords": len(hw), "sha256_match_evidence":
                sha256(path) == next(c["output_sha256"] for c in ev["cases"] if c["case"] == case),
            "json_match": hw == exp, "tsv_match": hw == tsv_case,
        }
    audit["checks"]["total_output_bytes"] = sum(v["bytes"] for v in audit["output_bins"].values())
    audit["checks"]["all_64_bytes"] = all(v["bytes"] == 64 for v in audit["output_bins"].values())
    audit["checks"]["all_json_match"] = all(v["json_match"] for v in audit["output_bins"].values())
    audit["checks"]["all_tsv_match"] = all(v["tsv_match"] for v in audit["output_bins"].values())
    audit["checks"]["all_hashes_match_evidence"] = all(v["sha256_match_evidence"] for v in audit["output_bins"].values())
    audit["cases"] = [
        {"case": c["case"], "status": c["status"], "submit_ret": c["submit_ret"],
         "output_bytes": c["output_bytes"], "output_sha256": c["output_sha256"]}
        for c in ev["cases"]
    ]
    audit["run"] = {
        "run_id": ev["run_id"], "hostname": ev["board"]["hostname"],
        "kernel": ev["board"]["kernel"], "device": ev["board"]["device"],
        "python": ev["board"]["python"], "runner_sha256": ev["runner"]["sha256"],
        "source_revision": ev["source_revision"],
    }

    # Reconstruct the 256 row-major pairs and compare rules.
    row = []
    for entry in tsv:
        a = int(entry["A_bits"], 16)
        b = int(entry["B_bits"], 16)
        o = int(entry["out_bits"], 16)
        pair = int(entry["lane"]) + 32 * int(entry["case"].split("_")[-1].split("_")[0]) // 2  # unused
        pred, rule = classify_rule(a, b)
        ieee_cls, ieee_bits = None, None
        sa, sb = M.sign(a), M.sign(b)
        if M.is_nan(a) or M.is_nan(b) or (M.is_zero(a) and M.is_zero(b)) or (M.is_inf(a) and M.is_inf(b)):
            ieee_cls, ieee_bits = "nan", None
        elif M.is_inf(a):
            ieee_cls, ieee_bits = "inf", (sa ^ sb) << 15 | 0x7C00
        elif M.is_inf(b):
            ieee_cls, ieee_bits = "zero", (sa ^ sb) << 15
        elif M.is_zero(b):
            ieee_cls, ieee_bits = "inf", (sa ^ sb) << 15 | 0x7C00
        elif M.is_zero(a):
            ieee_cls, ieee_bits = "zero", (sa ^ sb) << 15
        else:
            bits = M.round_fraction_to_half(M.exact_quotient(a, b), "rne")
            ieee_cls = "inf" if M.is_inf(bits) else ("zero" if M.is_zero(bits) else "finite")
            ieee_bits = bits
        row.append({
            "case": entry["case"], "lane": int(entry["lane"]),
            "a_class": entry["A_class"], "b_class": entry["B_class"],
            "a_bits": entry["A_bits"], "b_bits": entry["B_bits"],
            "observed_bits": entry["out_bits"],
            "contract_bits": f"0x{pred:04x}",
            "contract_match": pred == o,
            "rule": rule,
            "ieee_class": ieee_cls,
            "ieee_bits": f"0x{ieee_bits:04x}" if ieee_bits is not None else None,
            "ieee_match": (ieee_bits == o) if ieee_bits is not None else (M.is_nan(o) if ieee_cls == "nan" else False),
            "ieee_quiet_ok": not (ieee_cls == "nan" and M.is_nan(o) and not (o & M.QUIET_BIT)),
        })

    # Aggregate the four zero/zero cells and the special sign rules.
    def get(ac, bc):
        return next(r for r in row if r["a_class"] == ac and r["b_class"] == bc)

    special_cells = {
        "zero_p/zero_p": get("zero_p", "zero_p")["observed_bits"],
        "zero_p/zero_n": get("zero_p", "zero_n")["observed_bits"],
        "zero_n/zero_p": get("zero_n", "zero_p")["observed_bits"],
        "zero_n/zero_n": get("zero_n", "zero_n")["observed_bits"],
        "inf_p/inf_p": get("inf_p", "inf_p")["observed_bits"],
        "inf_p/inf_n": get("inf_p", "inf_n")["observed_bits"],
        "inf_n/inf_p": get("inf_n", "inf_p")["observed_bits"],
        "inf_n/inf_n": get("inf_n", "inf_n")["observed_bits"],
        "one_p/zero_n": get("one_p", "zero_n")["observed_bits"],
        "one_n/zero_n": get("one_n", "zero_n")["observed_bits"],
        "one_n/inf_n": get("one_n", "inf_n")["observed_bits"],
        "zero_n/inf_n": get("zero_n", "inf_n")["observed_bits"],
        "zero_p/one_n": get("zero_p", "one_n")["observed_bits"],
        "zero_n/one_n": get("zero_n", "one_n")["observed_bits"],
    }

    # Finite-finite 100 pairs: model check.
    finite_pairs = [r for r in row if r["a_class"] in FINITE and r["b_class"] in FINITE]
    finite_bad = [r for r in finite_pairs if not r["contract_match"]]
    # Special pairs: model check.
    special_pairs = [r for r in row if r not in finite_pairs]
    special_bad = [r for r in special_pairs if not r["contract_match"]]

    # Check whether the old (pre-grid) contract would have failed, to quantify.
    def old_contract(a, b):
        sa, sb = M.sign(a), M.sign(b)
        sr = sa ^ sb
        if M.is_nan(a) or M.is_nan(b):
            return 0x7C01
        if a == 0x0000 and b == 0x0000:
            return 0x7C01
        if M.is_zero(b):
            return (sr << 15) | 0x7C00
        if M.is_inf(a) and M.is_inf(b):
            return (sr << 15) | 0x7C00
        if M.is_inf(a):
            return (sr << 15) | 0x7C00
        if M.is_inf(b):
            return sr << 15
        if M.is_zero(a):
            return sr << 15
        q, e, ue, n, r, mm = ctx(a, b)
        return model_3g(q, ue)
    old_bad = [r for r in row if old_contract(int(r["a_bits"], 16), int(r["b_bits"], 16)) != int(r["observed_bits"], 16)]

    # IEEE mismatches by category.
    ieee_mismatch = [r for r in row if not r["ieee_match"]]
    ieee_quiet_bad = [r for r in row if r["ieee_class"] == "nan" and M.is_nan(int(r["observed_bits"], 16)) and not (int(r["observed_bits"], 16) & M.QUIET_BIT)]

    out = {
        "audit": audit,
        "pair_count": len(row),
        "contract_mismatches": len([r for r in row if not r["contract_match"]]),
        "finite_pair_count": len(finite_pairs),
        "finite_contract_mismatches": len(finite_bad),
        "special_pair_count": len(special_pairs),
        "special_contract_mismatches": len(special_bad),
        "old_contract_mismatches": len(old_bad),
        "ieee_mismatch_count": len(ieee_mismatch),
        "ieee_quiet_bit_violations": len(ieee_quiet_bad),
        "special_cells": special_cells,
        "rows": row,
    }
    (DATA / "systematic_analysis.json").write_text(json.dumps(out, indent=2) + "\n")

    lines = []
    lines.append(f"run {ev['run_id']} host={ev['board']['hostname']} device={ev['board']['device']}")
    lines.append(f"256 lanes; output bytes={audit['checks']['total_output_bytes']}; "
                 f"all_json={audit['checks']['all_json_match']} all_tsv={audit['checks']['all_tsv_match']} "
                 f"hashes={audit['checks']['all_hashes_match_evidence']}")
    lines.append(f"contract mismatches: {out['contract_mismatches']}/256")
    lines.append(f"  finite-finite: {out['finite_contract_mismatches']}/{out['finite_pair_count']}")
    lines.append(f"  special: {out['special_contract_mismatches']}/{out['special_pair_count']}")
    lines.append(f"old pre-grid contract mismatches: {out['old_contract_mismatches']}/256")
    lines.append(f"IEEE bit mismatches: {out['ieee_mismatch_count']}/256; "
                 f"NaN quiet-bit violations: {out['ieee_quiet_bit_violations']}")
    lines.append("special cells: " + json.dumps(special_cells, indent=2))
    lines.append("")
    lines.append("Old-contract failures:")
    for r in old_bad:
        a = int(r["a_bits"], 16)
        b = int(r["b_bits"], 16)
        old = old_contract(a, b)
        lines.append(f"  {r['a_class']}/{r['b_class']} obs={r['observed_bits']} "
                     f"old=0x{old:04x} new={r['contract_bits']} rule={r['rule']}")
    lines.append("")
    lines.append("IEEE mismatches:")
    for r in ieee_mismatch:
        lines.append(f"  {r['a_class']}/{r['b_class']} obs={r['observed_bits']} "
                     f"ieee_class={r['ieee_class']} ieee_bits={r['ieee_bits']}")
    (DATA / "systematic_summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
