#!/usr/bin/env /usr/bin/python3
"""Emit Markdown fragments for the FDIV report from FDIV_TABLE.json."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DATA = HERE / "data"
t = json.loads((HERE / "FDIV_TABLE.json").read_text())

CLASSES = []
for _p in t["class_pair_table"]:
    if _p["a_class"] not in CLASSES:
        CLASSES.append(_p["a_class"])
NAMES = [f"`{c}`" for c in CLASSES]
LOOKUP = {(p["a_class"], p["b_class"]): p for p in t["class_pair_table"]}

SPECIAL_NOTES = {
    0: "IEEE divide-by-zero; special-path sign(a)",
    1: "IEEE divide-by-zero; special-path sign(a)",
    2: "**QUIRK**: IEEE requires qNaN; 0x7c01 is the sNaN encoding",
    3: "**QUIRK**: IEEE requires qNaN; zero/zero non-NaN -> sign(a)*inf",
    4: "**QUIRK**: IEEE requires qNaN; inf/inf -> sign(a)*inf",
    5: "**QUIRK**: IEEE requires qNaN; inf/inf -> sign(a)*inf",
    6: "IEEE inf numerator; special-path sign(a)",
    7: "IEEE finite / inf -> zero; special-path sign(a)",
    8: "IEEE finite / inf -> zero; special-path sign(a)",
    9: "IEEE inf / zero -> inf; special-path sign(a)",
    10: "IEEE zero / inf -> zero; special-path sign(a)",
    11: "**QUIRK**: canonical 0x7c01, payload dropped, quiet bit clear",
    12: "**QUIRK**: canonical 0x7c01, payload dropped, quiet bit clear",
    13: "finite; exact 1/3; 3G model = RNE",
    14: "finite; exact 2/3; 3G model = RNE",
    15: "finite; exact 1/10; 3G model = RNE",
    16: "finite; exact 65504/3; 3G model = RNE",
    17: "exact tie 0.5 ulp -> +0 (ties-to-even)",
    18: "exact subnormal result 0x0200",
    19: "exact quotient",
    20: "gross overflow -> +inf",
    21: "gross overflow (exact 2^24) -> +inf",
    22: "gross underflow -> +0",
    23: "exact negative tie 0.5 ulp -> -0",
}


def special_md():
    lines = [
        "| # | A bits | A class | B bits | B class | device | IEEE class | IEEE bits | donor bits | verdict | grid | note |",
        "|---:|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in t["special_rows"]:
        g = r.get("grid_confirmation")
        gs = "—" if not g else f"`{g['observed_bits']}` (pair {g['pair_index']})"
        if g and not g["matches"]:
            gs += " **MISMATCH**"
        lines.append(
            f"| {r['index']} | `{r['a_bits']}` | {r['a_class']} | `{r['b_bits']}` | {r['b_class']} "
            f"| `{r['observed_bits']}` ({r['observed_class']}) "
            f"| {r['ieee_required_class']} | `{r['ieee_unique_bits'] or 'qNaN (payload free)'}` "
            f"| `{r['donor_bits']}` | {r['ieee_verdict']} | {gs} | {SPECIAL_NOTES.get(r['index'], '')} |")
    return "\n".join(lines) + "\n"


def sweep_md():
    rows = [r for r in t["finite_rows"] if r["source"] == "real-rocket-fdiv8-finite-sweep"]
    lines = [
        "| # | A | B | device | exact quotient | RNE | contract | tags | delta |",
        "|---:|---|---|---|---|---|---|---|---:|",
    ]
    for r in rows:
        qs = f"{r['exact_decimal']} (`{r['exact_fraction']}`)" if "/" in r["exact_fraction"] else r["exact_decimal"]
        lines.append(
            f"| {r['index']} | `{r['a_bits']}` {r['a_value']} | `{r['b_bits']}` {r['b_value']} "
            f"| `{r['observed_bits']}` | {qs} | `{r['ieee_rne_bits']}` | `{r['contract_bits']}` "
            f"| {', '.join(r['tags'])} | {r['observed_minus_rne']} |")
    return "\n".join(lines) + "\n"


def fdiv8_md():
    rows = [r for r in t["finite_rows"] if r["source"] == "real-rocket-fdiv8"]
    lines = [
        "| # | A | B | device | exact quotient | RNE | contract | tags | delta |",
        "|---:|---|---|---|---|---|---|---|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['index']} | `{r['a_bits']}` {r['a_value']} | `{r['b_bits']}` {r['b_value']} "
            f"| `{r['observed_bits']}` | {r['exact_decimal']} | `{r['ieee_rne_bits']}` "
            f"| `{r['contract_bits']}` | {', '.join(r['tags'])} | {r['observed_minus_rne']} |")
    return "\n".join(lines) + "\n"


def anomalies_md():
    a = t["p1_1024"]["a_over_7_subsequence"]
    lines = [
        "| lane | A | B | device | exact RNE | delta | n | fraction in ulp | first 3 fraction bits |",
        "|---:|---:|---|---|---|---:|---:|---|---:|",
    ]
    for x in a["anomalies"]:
        lines.append(
            f"| {x['lane']} | {x['a_integer']} (`{x['a_bits']}`) | `{x['b_bits']}` "
            f"| `{x['observed_bits']}` | `{x['exact_rne_bits']}` | {x['delta_bits']} "
            f"| {x['n']} | {x['fraction_in_ulp']:.6f} | {x['first_3_fraction_bits']:03b} |")
    return "\n".join(lines) + "\n"


def class_grid():
    header = "| A \\ B | " + " | ".join(NAMES) + " |"
    sep = "|---|" + "---|" * len(CLASSES)
    lines = [header, sep]
    for an in CLASSES:
        cells = [f"`{LOOKUP[(an, bn)]['observed_bits']}`" for bn in CLASSES]
        lines.append(f"| `{an}` | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def pre_grid_bad_md():
    bad = [p for p in t["class_pair_table"] if not p["pre_grid_contract_correct"]]
    lines = [
        "| A class | B class | grid result | pre-grid prediction | error class |",
        "|---|---|---|---|---|",
    ]
    for p in bad:
        lines.append(
            f"| `{p['a_class']}` | `{p['b_class']}` | `{p['observed_bits']}` "
            f"| `{p['pre_grid_contract_bits']}` | {p['ieee_category']} |")
    return "\n".join(lines) + "\n"


def zero_inf_md():
    cells = t["systematic_grid"]["special_cells"]
    lines = [
        "| A \\ B | `+0` | `-0` | `+inf` | `-inf` |",
        "|---|---|---|---|---|",
        f"| `+0` | `{cells['zero_p/zero_p']}` | `{cells['zero_p/zero_n']}` "
        f"| `{LOOKUP[('zero_p','inf_p')]['observed_bits']}` | `{LOOKUP[('zero_p','inf_n')]['observed_bits']}` |",
        f"| `-0` | `{cells['zero_n/zero_p']}` | `{cells['zero_n/zero_n']}` "
        f"| `{LOOKUP[('zero_n','inf_p')]['observed_bits']}` | `{LOOKUP[('zero_n','inf_n')]['observed_bits']}` |",
        f"| `+inf` | `{LOOKUP[('inf_p','zero_p')]['observed_bits']}` | `{LOOKUP[('inf_p','zero_n')]['observed_bits']}` "
        f"| `{cells['inf_p/inf_p']}` | `{cells['inf_p/inf_n']}` |",
        f"| `-inf` | `{LOOKUP[('inf_n','zero_p')]['observed_bits']}` | `{LOOKUP[('inf_n','zero_n')]['observed_bits']}` "
        f"| `{cells['inf_n/inf_p']}` | `{cells['inf_n/inf_n']}` |",
    ]
    return "\n".join(lines) + "\n"


def sign_probe_md():
    probes = [
        ("finite-numerator / -0", "one_p", "zero_n"),
        ("negative finite / -0", "one_n", "zero_n"),
        ("finite-numerator / -inf", "one_p", "inf_n"),
        ("negative finite / -inf", "one_n", "inf_n"),
        ("-0 / finite-positive", "zero_n", "one_p"),
        ("-0 / finite-negative", "zero_n", "one_n"),
        ("+inf / finite-negative", "inf_p", "one_n"),
        ("-inf / finite-negative", "inf_n", "one_n"),
        ("finite overflow with - divisor", "fin_max", "half_n"),
        ("finite underflow with - divisor", "sub_min", "two_n"),
    ]
    lines = ["| Case | A class | B class | device | finite-path sign | special-path sign |",
             "|---|---|---|---|---|---|"]
    for label, ac, bc in probes:
        p = LOOKUP[(ac, bc)]
        lines.append(f"| {label} | `{ac}` | `{bc}` | `{p['observed_bits']}` "
                     f"| sign(a)^sign(b) | sign(a) |")
    return "\n".join(lines) + "\n"


DATA.mkdir(exist_ok=True)
(DATA / "md_special.md").write_text(special_md())
(DATA / "md_sweep.md").write_text(sweep_md())
(DATA / "md_fdiv8.md").write_text(fdiv8_md())
(DATA / "md_anomalies.md").write_text(anomalies_md())
(DATA / "md_classgrid.md").write_text(class_grid())
(DATA / "md_pre_grid_bad.md").write_text(pre_grid_bad_md())
(DATA / "md_zero_inf.md").write_text(zero_inf_md())
(DATA / "md_sign_probe.md").write_text(sign_probe_md())
print("wrote markdown fragments")
print(class_grid())
print("pre-grid bad rows:", len([p for p in t['class_pair_table'] if not p['pre_grid_contract_correct']]))
