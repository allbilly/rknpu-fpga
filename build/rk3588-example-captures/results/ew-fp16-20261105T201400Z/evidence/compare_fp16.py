#!/usr/bin/env /usr/bin/python3
"""Host-side comparison for the ew-fp16 real-device capture.

Compares only the manifest-declared logical halfword region against the donor
CPU oracle and reports the physical-padding and BO-tail differences separately.
Uses raw bytes and exact FP16 bit patterns; no NumPy and no device access.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1]
REPO = Path("/home/fedora/rknpu-fpga")
FAMILY = REPO / "build/rk3588-example-captures/ew-fp16"
MANIFEST = FAMILY / "manifest.json"
CASES = FAMILY / "cases"
BO_BYTES = 4096
HALFWORDS = BO_BYTES // 2


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def f16(bits: int) -> float:
    return struct.unpack("<e", struct.pack("<H", bits))[0]


def bits_at(data: bytes, index: int) -> int:
    return struct.unpack_from("<H", data, 2 * index)[0]


def special(bits: int) -> bool:
    return (bits & 0x7C00) == 0x7C00


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = [entry for entry in manifest["cases"] if entry["status"] == "READY"]
    if len(entries) != 54:
        print(f"expected 54 READY cases, got {len(entries)}", file=sys.stderr)
        return 1

    reports = []
    for entry in entries:
        case = entry["case"]
        out_path = RESULTS / case / "out.bin"
        exp_path = CASES / case / "expected.bin"
        cap_path = RESULTS / case / "capture.json"
        out = out_path.read_bytes()
        exp = exp_path.read_bytes()
        cap = json.loads(cap_path.read_text(encoding="utf-8"))
        n = entry["logical_count"]
        padded = entry["padded_count"]
        if len(out) != BO_BYTES:
            raise SystemExit(f"{case}: out.bin is {len(out)} bytes, not {BO_BYTES}")
        if len(exp) != 2 * n:
            raise SystemExit(f"{case}: expected.bin is {len(exp)} bytes, not {2 * n}")

        mismatches = []
        for i in range(n):
            expected_bits = bits_at(exp, i)
            device_bits = bits_at(out, i)
            if expected_bits != device_bits:
                mismatches.append({
                    "halfword_index": i,
                    "byte_offset": 2 * i,
                    "expected_bits": f"0x{expected_bits:04x}",
                    "device_bits": f"0x{device_bits:04x}",
                    "expected_f16": f16(expected_bits),
                    "device_f16": f16(device_bits),
                    "expected_finite": not special(expected_bits),
                    "device_finite": not special(device_bits),
                })

        padding_nonzero = [i for i in range(n, padded) if bits_at(out, i) != 0]
        tail_nonzero = [i for i in range(padded, HALFWORDS) if bits_at(out, i) != 0]
        nonfinite = [i for i in range(n) if special(bits_at(out, i))]
        padding_special = [i for i in range(n, padded) if special(bits_at(out, i))]
        tail_special = [i for i in range(padded, HALFWORDS) if special(bits_at(out, i))]

        cap_out_sha = cap.get("hashes", {}).get("out")
        out_sha = sha256(out)
        hash_consistent = cap_out_sha == out_sha
        report = {
            "case": case,
            "op": entry["op"],
            "pattern": entry["pattern"],
            "logical_count": n,
            "padded_count": padded,
            "logical_bytes": 2 * n,
            "out_bytes": len(out),
            "out_sha256": out_sha,
            "expected_sha256": sha256(exp),
            "capture_out_sha256": cap_out_sha,
            "capture_out_hash_consistent": hash_consistent,
            "submit_ret": cap.get("submit_ret"),
            "capture_status": cap.get("status"),
            "bytes_read": cap.get("bytes_read"),
            "logical_region_match": not mismatches,
            "logical_mismatch_count": len(mismatches),
            "logical_mismatches": mismatches,
            "device_logical_nonfinite_count": len(nonfinite),
            "device_logical_nonfinite_indices": nonfinite,
            "padding_region_halfwords": [n, padded],
            "padding_nonzero_halfword_count": len(padding_nonzero),
            "padding_nonzero_halfword_indices": padding_nonzero,
            "padding_special_count": len(padding_special),
            "padding_special_indices": padding_special,
            "tail_region_halfwords": [padded, HALFWORDS],
            "tail_nonzero_halfword_count": len(tail_nonzero),
            "tail_nonzero_halfword_indices": tail_nonzero,
            "tail_special_count": len(tail_special),
            "full_bo_nonzero_outside_logical_count": len(padding_nonzero) + len(tail_nonzero),
        }
        reports.append(report)

    by_op: dict[str, dict] = {}
    for report in reports:
        stat = by_op.setdefault(report["op"], {
            "cases": 0,
            "logical_pass": 0,
            "logical_fail": 0,
            "mismatched_halfwords": 0,
            "cases_with_nonfinite": 0,
            "padding_nonzero_halfwords": 0,
            "tail_nonzero_halfwords": 0,
        })
        stat["cases"] += 1
        if report["logical_region_match"]:
            stat["logical_pass"] += 1
        else:
            stat["logical_fail"] += 1
        stat["mismatched_halfwords"] += report["logical_mismatch_count"]
        stat["cases_with_nonfinite"] += 1 if report["device_logical_nonfinite_count"] else 0
        stat["padding_nonzero_halfwords"] += report["padding_nonzero_halfword_count"]
        stat["tail_nonzero_halfwords"] += report["tail_nonzero_halfword_count"]

    fail = [r for r in reports if not r["logical_region_match"]]
    hash_bad = [r["case"] for r in reports if not r["capture_out_hash_consistent"]]
    summary = {
        "family": manifest["family"],
        "cases": len(reports),
        "logical_pass": len(reports) - len(fail),
        "logical_fail": len(fail),
        "failed_cases": [r["case"] for r in fail],
        "fd_iv_cases": [r["case"] for r in reports if r["op"] == "FDIV"],
        "fd_iv_failed_cases": [r["case"] for r in fail if r["op"] == "FDIV"],
        "cases_with_nonfinite_logical_output": [
            r["case"] for r in reports if r["device_logical_nonfinite_count"]
        ],
        "capture_hash_inconsistent_cases": hash_bad,
        "total_out_bytes": sum(r["out_bytes"] for r in reports),
        "total_logical_bytes": sum(r["logical_bytes"] for r in reports),
        "by_op": by_op,
        "cases_report": reports,
    }

    (RESULTS / "evidence" / "comparison.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = []
    for report in reports:
        lines.append(
            f"{report['case']:<18} {report['op']:<4} n={report['logical_count']:<4} "
            f"submit_ret={report['submit_ret']} "
            f"logical={'PASS' if report['logical_region_match'] else 'FAIL'} "
            f"mismatch_hw={report['logical_mismatch_count']} "
            f"padding_nonzero_hw={report['padding_nonzero_halfword_count']} "
            f"tail_nonzero_hw={report['tail_nonzero_halfword_count']} "
            f"out_sha256={report['out_sha256']}"
        )
        for item in report["logical_mismatches"]:
            lines.append(
                f"  MISMATCH {report['case']} halfword={item['halfword_index']} "
                f"offset={item['byte_offset']} "
                f"expected={item['expected_bits']}({item['expected_f16']!r}) "
                f"device={item['device_bits']}({item['device_f16']!r})"
            )
    (RESULTS / "evidence" / "comparison.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        f"cases={summary['cases']} logical_pass={summary['logical_pass']} "
        f"logical_fail={summary['logical_fail']} "
        f"out_bytes={summary['total_out_bytes']} "
        f"capture_hash_inconsistent={len(hash_bad)}"
    )
    for op, stat in sorted(by_op.items()):
        print(
            f"{op:<4} cases={stat['cases']} pass={stat['logical_pass']} "
            f"fail={stat['logical_fail']} mismatched_hw={stat['mismatched_halfwords']} "
            f"nonfinite_cases={stat['cases_with_nonfinite']} "
            f"padding_nonzero_hw={stat['padding_nonzero_halfwords']} "
            f"tail_nonzero_hw={stat['tail_nonzero_halfwords']}"
        )
    if fail:
        print("FAILED CASES: " + ", ".join(r["case"] for r in fail))
    return 0 if not fail and not hash_bad else 2


if __name__ == "__main__":
    sys.exit(main())
