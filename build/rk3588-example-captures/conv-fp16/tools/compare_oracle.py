#!/usr/bin/env python3
"""Host-side comparison helper for conv-fp16 capture bundles.

Reads the worker's raw output BO files and applies the donor's NC1HWC2 or
flat-1x1 unpack before comparing with the labelled NumPy oracle.  This tool is
host-side only; the board worker has no NumPy and only writes raw BO bytes.

It never invents a capture: a missing out*.bin is reported as missing, not
created.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

FAMILY_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = FAMILY_DIR / "manifest.json"
C2 = 8

def unpack_nc1hwc2(raw: np.ndarray, out_c: int, out_h: int, out_w: int, out_width_stride: int) -> np.ndarray:
    """Mirror conv_new_clean._unpack_nc1hwc2_output (lines 408-418)."""
    c1 = raw.size // (out_width_stride * C2)
    packed = raw.reshape(c1, out_width_stride, C2)
    packed = packed[:, : out_h * out_w, :]
    return packed.transpose(0, 2, 1).reshape(c1 * C2, out_h * out_w)[:out_c].reshape(out_c, out_h, out_w)


def unpack_flat_1x1(raw: np.ndarray, out_c: int, out_h: int, out_w: int, out_width_stride: int) -> np.ndarray:
    """Mirror conv_new_clean._unpack_flat_1x1_output (lines 403-406)."""
    c1 = raw.size // (out_width_stride * C2)
    packed = raw.reshape(1, c1, 1, out_width_stride, C2)
    return (
        packed[0, :, 0, : out_h * out_w, :]
        .transpose(0, 2, 1)
        .reshape(c1 * C2, out_h * out_w)[:out_c]
        .reshape(out_c, out_h, out_w)
    )


def load_manifest():
    return json.loads(MANIFEST_PATH.read_text())


def compare_case(case, atol: float) -> bool:
    name = case["case"]
    case_dir = FAMILY_DIR / "cases" / name
    job = json.loads((case_dir / "job.json").read_text())
    layouts = {layout["buffer"]: layout for layout in case.get("output_layouts", [])}
    buffers = {buffer["name"]: buffer for buffer in job["buffers"]}

    expected_by_buffer = {}
    all_ok = True
    for bname, layout in layouts.items():
        buffer = buffers[bname]
        out_path = case_dir / buffer["output"]
        expected_path = case_dir / layout["expected"]
        print(f"[{name}] {bname}: raw={out_path.name} expected={expected_path.name}")
        if not out_path.is_file():
            print(f"  MISSING: {out_path} (worker has not written this output)")
            all_ok = False
            continue
        if not expected_path.is_file():
            print(f"  MISSING ORACLE: {expected_path}")
            all_ok = False
            continue

        out_c = int(layout["out_c"])
        out_h = int(layout["out_h"])
        out_w = int(layout["out_w"])
        ws = int(layout["out_width_stride"])
        raw_bytes = out_path.stat().st_size
        if raw_bytes != int(layout["raw_bytes"]):
            print(f"  FAIL size: raw {raw_bytes} != declared {layout['raw_bytes']}")
            all_ok = False
            continue

        raw = np.frombuffer(out_path.read_bytes(), dtype=np.uint16).copy().view(np.float16)
        if layout["layout"] == "flat_1x1":
            got = unpack_flat_1x1(raw, out_c, out_h, out_w, ws)
        else:
            got = unpack_nc1hwc2(raw, out_c, out_h, out_w, ws)
        expected = np.frombuffer(expected_path.read_bytes(), dtype=np.uint16).copy().view(np.float16).reshape(out_c, out_h, out_w)
        diff = np.abs(got.astype(np.float64) - expected.astype(np.float64))
        bad = int(np.count_nonzero(diff > atol))
        max_diff = float(diff.max()) if diff.size else 0.0
        status = "PASS" if bad == 0 else "FAIL"
        print(f"  {status}: max_abs_diff={max_diff:.6g} over_tolerance={bad}/{diff.size} atol={atol}")
        if bad:
            all_ok = False
        expected_by_buffer[bname] = (got, expected)

    combined_path = case_dir / "expected_combined.bin"
    if len(layouts) > 1 and combined_path.is_file() and len(expected_by_buffer) == len(layouts):
        got_parts = []
        for layout in case["output_layouts"]:
            got_parts.append(expected_by_buffer[layout["buffer"]][0])
        got_combined = np.concatenate(got_parts, axis=0)
        shape = case["shape"]
        expected_combined = np.frombuffer(combined_path.read_bytes(), dtype=np.uint16).copy().view(np.float16).reshape(
            int(shape["out_c"]), int(shape["out_h"]), int(shape["out_w"])
        )
        diff = np.abs(got_combined.astype(np.float64) - expected_combined.astype(np.float64))
        bad = int(np.count_nonzero(diff > atol))
        max_diff = float(diff.max()) if diff.size else 0.0
        status = "PASS" if bad == 0 else "FAIL"
        print(f"[{name}] combined: {status}: max_abs_diff={max_diff:.6g} over_tolerance={bad}/{diff.size} atol={atol}")
        if bad:
            all_ok = False
    return all_ok


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", nargs="?", help="case name; omit with --all")
    parser.add_argument("--all", action="store_true", help="compare every READY case")
    parser.add_argument("--atol", type=float, default=0.2, help="absolute tolerance (donor uses 0.2)")
    args = parser.parse_args(argv)

    manifest = load_manifest()
    ready = {case["case"]: case for case in manifest["cases"] if case["status"] == "READY"}
    if args.all:
        selected = list(ready.values())
        if not selected:
            print("no READY cases")
            return 1
    elif args.case:
        if args.case not in ready:
            print(f"unknown READY case: {args.case}")
            print("available: " + ", ".join(sorted(ready)))
            return 1
        selected = [ready[args.case]]
    else:
        parser.error("provide a case name or --all")

    ok = True
    for case in selected:
        try:
            ok = compare_case(case, args.atol) and ok
        except Exception as exc:
            print(f"[{case['case']}] ERROR: {exc}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
