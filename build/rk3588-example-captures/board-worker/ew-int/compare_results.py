#!/usr/bin/env python3
"""Host-side masked oracle comparison for ew-int board captures.

Never writes or replaces a device output.  Reads out.bin exactly as returned
from the board and compares it against expected.bin under expected.mask.bin.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_lane(raw: bytes, item_size: int) -> int:
    return int.from_bytes(raw[:item_size], "little", signed=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)

    results = Path(args.results)
    cases = Path(args.cases)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    ready = [entry for entry in manifest["cases"] if entry["status"] == "READY"]

    report = {
        "kind": "host-side masked oracle comparison",
        "note": "device out.bin is never modified; expected.bin is only read",
        "results_root": str(results),
        "cases_root": str(cases),
        "compare": "(out[i] & mask[i]) == (expected[i] & mask[i]) over full BO",
        "summary": {
            "cases": len(ready),
            "pass": 0,
            "fail": 0,
            "missing": 0,
            "bytes_compared": 0,
        },
        "cases": [],
    }
    for entry in ready:
        name = entry["case"]
        item_size = entry["output_item_size"]
        case_out = results / name / "out.bin"
        capture_path = results / name / "capture.json"
        expected_path = cases / name / "expected.bin"
        mask_path = cases / name / "expected.mask.bin"
        row = {
            "case": name,
            "dtype": entry["dtype"],
            "output_item_size": item_size,
            "expected_file": str(expected_path),
            "mask_file": str(mask_path),
            "capture_file": str(capture_path),
            "out_file": str(case_out),
        }
        if not case_out.is_file():
            row.update(status="FAIL", reason="out.bin missing")
            report["summary"]["missing"] += 1
            report["summary"]["fail"] += 1
            report["cases"].append(row)
            continue
        out = case_out.read_bytes()
        expected = expected_path.read_bytes()
        mask = mask_path.read_bytes()
        if not (len(out) == len(expected) == len(mask) == 4096):
            row.update(
                status="FAIL",
                reason="size mismatch",
                sizes={"out": len(out), "expected": len(expected), "mask": len(mask)},
            )
            report["summary"]["fail"] += 1
            report["cases"].append(row)
            continue

        masked_mismatches = []
        first_any = None
        padding_differences = 0
        first_padding = None
        for index, (actual, expect, mask_byte) in enumerate(zip(out, expected, mask)):
            if actual != expect:
                lane = index // item_size
                detail = {
                    "byte_offset": index,
                    "lane": lane,
                    "byte_in_lane": index % item_size,
                    "mask": mask_byte,
                    "expected": expect,
                    "actual": actual,
                }
                if mask_byte:
                    masked_mismatches.append(detail)
                else:
                    padding_differences += 1
                    if first_padding is None:
                        first_padding = detail
                if first_any is None:
                    first_any = detail

        first = masked_mismatches[0] if masked_mismatches else None
        if first is not None:
            lane_start = first["lane"] * item_size
            lane_end = lane_start + item_size
            first["lane_expected_int"] = decode_lane(expected[lane_start:lane_end], item_size)
            first["lane_actual_int"] = decode_lane(out[lane_start:lane_end], item_size)
        row.update(
            status="PASS" if not masked_mismatches else "FAIL",
            out_sha256=sha256_file(case_out),
            expected_sha256=sha256_file(expected_path),
            mask_sha256=sha256_file(mask_path),
            asserted_bytes=sum(1 for value in mask if value == 0xFF),
            masked_mismatch_count=len(masked_mismatches),
            padding_difference_count=padding_differences,
            first_mismatch=first,
            first_padding_difference=first_padding,
            first_any_difference=first_any,
            masked_mismatches=masked_mismatches[:20],
        )
        report["summary"]["bytes_compared"] += len(out)
        if masked_mismatches:
            report["summary"]["fail"] += 1
        else:
            report["summary"]["pass"] += 1
        report["cases"].append(row)

    compare_path = results / "compare.json"
    with open(compare_path, "x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(
        f"COMPARE cases={report['summary']['cases']} "
        f"pass={report['summary']['pass']} fail={report['summary']['fail']} "
        f"bytes={report['summary']['bytes_compared']}"
    )
    for row in report["cases"]:
        if row["status"] == "PASS":
            print(f"  PASS {row['case']} mismatched_padding={row['padding_difference_count']}")
        else:
            first = row.get("first_mismatch")
            if first:
                print(
                    f"  FAIL {row['case']} first byte={first['byte_offset']} "
                    f"lane={first['lane']} mask={first['mask']:#04x} "
                    f"expected={first['expected']:#04x} actual={first['actual']:#04x} "
                    f"mismatches={row['masked_mismatch_count']}"
                )
            else:
                print(f"  FAIL {row['case']} {row.get('reason')}")
    return 0 if report["summary"]["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
