#!/usr/bin/env python3
"""Host-side audit of the conv-simple board capture. Read-only over build/."""
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures")
RUN_ID = "20261105T215921Z"
RES = ROOT / "results" / f"conv-simple-{RUN_ID}" / "conv-simple"
CASES = ROOT / "conv-simple" / "cases"
MAN = json.loads((ROOT / "conv-simple" / "manifest.json").read_text())
BY = {c["case"]: c for c in MAN["cases"]}
ORDER = [
    "conv_simple_fp16_1x1_c4_h8_w8_oc16",
    "conv_simple_fp16_3x3_c4_h8_w8_oc16",
    "conv_simple_fp16_5x5_c4_h8_w8_oc16",
    "conv_simple_fp16_1x1_c32_h8_w8_oc32",
    "conv_simple_fp16_3x3_c16_h8_w8_oc32",
    "simple_conv_int8_5x5_c8_h8_w8_oc32",
    "simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64",
]
DT = {"float16": "<e", "float32": "<f", "uint8": "B"}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def decode(raw: bytes, dtype: str, idx: int):
    fmt = DT[dtype]
    size = struct.calcsize(fmt)
    if dtype == "uint8":
        return raw[idx]
    val = struct.unpack_from(fmt, raw, idx * size)[0]
    return val


total = 0
rows = []
for name in ORDER:
    rec = BY[name]
    cdir = RES / name
    cap = json.loads((cdir / "capture.json").read_text())
    out = (cdir / "out.bin").read_bytes()
    exp = (CASES / name / "expected.bin").read_bytes()
    total += len(out)
    dtype = rec["oracle"]["dtype"]
    is_prefix = len(exp) < len(out)
    lhs = out[:len(exp)] if is_prefix else out
    rhs = exp
    assert len(lhs) == len(rhs)
    mism = [i for i in range(len(rhs)) if lhs[i] != rhs[i]]
    out_hash = sha(cdir / "out.bin")
    cap_hash = cap["hashes"]["outputs"]["out"]["sha256"]
    exp_hash = sha(CASES / name / "expected.bin")
    man_exp_hash = rec["hashes"]["expected.bin"]
    decl_size = [b for b in rec["buffers"] if b["name"] == "out"][0]["size"]
    exact_full = (len(out) == len(exp) and not mism)
    prefix_ok = not mism
    row = {
        "case": name,
        "dtype": dtype,
        "out_bytes": len(out),
        "expected_bytes": len(exp),
        "declared_out_size": decl_size,
        "out_hash": out_hash,
        "capture_out_hash": cap_hash,
        "hash_chain_ok": out_hash == cap_hash,
        "expected_hash": exp_hash,
        "manifest_expected_hash_ok": exp_hash == man_exp_hash,
        "status": cap["status"],
        "submit_ret": cap["submit_ret"],
        "errors": cap["errors"],
        "exact_full_match": exact_full,
        "prefix_ok": prefix_ok,
        "compared_bytes": len(rhs),
        "mismatch_bytes": len(mism),
        "tail_bytes": len(out) - len(exp) if is_prefix else 0,
        "tail_nonzero": sum(1 for b in out[len(exp):] if b) if is_prefix else 0,
        "tail_sha256": hashlib.sha256(out[len(exp):]).hexdigest() if is_prefix else None,
    }
    # numeric delta over compared region
    if dtype != "uint8":
        fmt = DT[dtype]
        sz = struct.calcsize(fmt)
        n = len(rhs) // sz
        a = struct.unpack(f"<{n}{fmt[1:]}", rhs)
        b = struct.unpack(f"<{n}{fmt[1:]}", lhs)
        diffs = [abs(x - y) for x, y in zip(a, b)]
        finite = [d for d in diffs if d == d]
        row["max_abs_diff"] = max(finite) if finite else None
        row["nonzero_element_diffs"] = sum(1 for d in diffs if d != 0)
        row["num_elements"] = n
        row["first_mismatches"] = [
            {
                "elem": i // sz,
                "byte_offset": i,
                "expected": struct.unpack_from(fmt, rhs, i - (i % sz))[0],
                "actual": struct.unpack_from(fmt, lhs, i - (i % sz))[0],
                "expected_hex": rhs[i - (i % sz):i - (i % sz) + sz].hex(),
                "actual_hex": lhs[i - (i % sz):i - (i % sz) + sz].hex(),
            }
            for i in mism[:8]
        ]
    else:
        diffs = [abs(lhs[i] - rhs[i]) for i in range(len(rhs))]
        row["max_abs_diff"] = max(diffs) if diffs else 0
        row["nonzero_element_diffs"] = sum(1 for d in diffs if d)
        row["num_elements"] = len(rhs)
        row["first_mismatches"] = [
            {
                "byte_offset": i,
                "expected": rhs[i],
                "actual": lhs[i],
                "expected_hex": f"{rhs[i]:02x}",
                "actual_hex": f"{lhs[i]:02x}",
            }
            for i in mism[:8]
        ]
    row["first_16_compared_hex"] = lhs[:16].hex()
    row["first_16_expected_hex"] = rhs[:16].hex()
    if is_prefix:
        tail = out[len(exp):]
        row["tail_first_16_hex"] = tail[:16].hex()
        row["tail_all_zero"] = not any(tail)
    rows.append(row)

print(json.dumps({"run_id": RUN_ID, "total_out_bytes_read": total, "cases": rows}, indent=2))
