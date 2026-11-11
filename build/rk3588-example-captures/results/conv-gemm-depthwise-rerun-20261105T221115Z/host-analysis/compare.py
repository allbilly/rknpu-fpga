#!/usr/bin/env python3
"""Compare the corrected depthwise rerun outputs with the host oracle.

Pure standard library.  Mirrors conv_legacy.py:_unpack_flat_1x1_output for
out_c=3, out_h=9, out_w=26, out_width_stride=236, unpack_c2=8, and reports
exact FP16 matches plus padding/tail contents.  This is host-side analysis of
bytes read back from the board; it is not an FPGA or RK numerical claim.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

CASES = (
    "conv_depthwise_3x3_c3_oc3_h11w28_task0",
    "conv_depthwise_3x3_c3_oc3_h11w28_task1",
)
OUT_C = 3
OUT_H = 9
OUT_W = 26
OUT_WIDTH_STRIDE = 236
UNPACK_C2 = 8
ALIGN_OUT_C = 16
HW_BYTES = 15104
SURFACE_BYTES = 7552
TOLERANCE = 0.2


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def half_bits(data: bytes) -> list[int]:
    return list(struct.unpack("<%dH" % (len(data) // 2), data))


def half_floats(bits: list[int]) -> list[float]:
    return list(struct.unpack("<%de" % len(bits), struct.pack("<%dH" % len(bits), *bits)))


def channel_plane(raw_bits: list[int], channel: int, out_width_stride: int,
                  c2: int) -> list[int]:
    group = channel // c2
    lane = channel % c2
    return [
        raw_bits[group * out_width_stride * c2 + pos * c2 + lane]
        for pos in range(out_width_stride)
    ]


def unpack_flat_1x1(raw_bits: list[int], out_c: int, out_h: int, out_w: int,
                    out_width_stride: int, c2: int) -> list[list[int]]:
    """Exact reimplementation of conv_legacy._unpack_flat_1x1_output indexing."""
    positions = out_h * out_w
    c1 = len(raw_bits) // (out_width_stride * c2)
    if len(raw_bits) != c1 * out_width_stride * c2:
        raise ValueError("raw length is not an integer number of packed groups")
    return [
        channel_plane(raw_bits, channel, out_width_stride, c2)[:positions]
        for channel in range(out_c)
    ]


def main() -> int:
    result_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    bundle_root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
        "/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-gemm-vendor/cases"
    )
    run_root = result_root / "board-run" / "conv-gemm-depthwise-rerun"

    summary = {
        "schema": "conv-gemm-depthwise-rerun-comparison-v1",
        "labelled": ("host-side analysis of bytes read back through mainline Rocket; "
                     "not an FPGA execution and not a new hardware numerical policy claim"),
        "result_root": str(result_root),
        "bundle_root": str(bundle_root),
        "cases": {},
        "totals": {},
    }
    failures: list[str] = []

    total_bytes = 0
    total_logical = 0
    total_exact = 0
    max_abs_all = 0.0
    total_padding_nonzero = 0

    for case in CASES:
        case_out = run_root / case
        case_bundle = bundle_root / case
        out_path = case_out / "output.bin"
        cap_path = case_out / "capture.json"
        expected_path = case_bundle / "expected.bin"
        job_path = case_bundle / "job.json"
        regcmd_path = case_bundle / "regcmd.bin"
        input_path = case_bundle / "input.bin"
        weight_path = case_bundle / "weight.bin"

        out_bytes = out_path.read_bytes()
        expected_bytes = expected_path.read_bytes()
        capture = json.loads(cap_path.read_text())
        job = json.loads(job_path.read_text())

        bits = half_bits(out_bytes)
        expected_bits = half_bits(expected_bytes)
        values = half_floats(bits)
        expected_values = half_floats(expected_bits)

        read_elems = (ALIGN_OUT_C // UNPACK_C2) * OUT_WIDTH_STRIDE * UNPACK_C2
        read_bits = bits[:read_elems]
        logical = unpack_flat_1x1(read_bits, OUT_C, OUT_H, OUT_W,
                                  OUT_WIDTH_STRIDE, UNPACK_C2)
        logical_bits = [b for plane in logical for b in plane]
        logical_values = half_floats(logical_bits)
        expected_logical_bits = expected_bits[:OUT_C * OUT_H * OUT_W]
        expected_logical_values = expected_values[:OUT_C * OUT_H * OUT_W]

        if len(out_bytes) != HW_BYTES:
            failures.append(f"{case}: output size {len(out_bytes)} != {HW_BYTES}")
        if len(expected_bytes) != OUT_C * OUT_H * OUT_W * 2:
            failures.append(f"{case}: expected size {len(expected_bytes)} != 1404")
        if len(logical_bits) != OUT_C * OUT_H * OUT_W:
            failures.append(f"{case}: logical count {len(logical_bits)} != 702")

        exact = sum(1 for a, b in zip(logical_bits, expected_logical_bits) if a == b)
        diffs = [abs(a - b) for a, b in zip(logical_values, expected_logical_values)]
        max_abs = max(diffs) if diffs else 0.0
        over_tol = sum(1 for d in diffs if d > TOLERANCE)

        used = OUT_C * OUT_H * OUT_W
        # Padding is interleaved by channel plane, not a linear tail.
        logical_channel_pad_bits = [
            b
            for channel in range(OUT_C)
            for b in channel_plane(bits, channel, OUT_WIDTH_STRIDE, UNPACK_C2)[OUT_H * OUT_W:]
        ]
        nonlogical_channel_bits = [
            b
            for channel in range(OUT_C, ALIGN_OUT_C)
            for b in channel_plane(bits, channel, OUT_WIDTH_STRIDE, UNPACK_C2)
        ]
        second_surface_bits = bits[read_elems:]
        full_nonzero = sum(1 for b in bits if b != 0)
        logical_channel_pad_nonzero = sum(1 for b in logical_channel_pad_bits if b != 0)
        nonlogical_channel_nonzero = sum(1 for b in nonlogical_channel_bits if b != 0)
        second_surface_nonzero = sum(1 for b in second_surface_bits if b != 0)
        padding_nonzero = (logical_channel_pad_nonzero
                           + nonlogical_channel_nonzero
                           + second_surface_nonzero)

        # Metadata checks: the capture must describe exactly the bytes we read.
        cap_outputs = {entry["file"]: entry for entry in capture.get("outputs", [])}
        cap_out = cap_outputs.get("output.bin", {})
        cap_buffer = next((b for b in capture.get("buffers", [])
                           if b.get("name") == "output"), {})
        checks = {
            "status_OK": capture.get("status") == "OK",
            "submit_ret_0": capture.get("submit_ret") == 0,
            "errors_empty": capture.get("errors") == [],
            "submit_error_null": capture.get("submit_error") is None,
            "output_size_matches_capture": cap_out.get("size") == len(out_bytes) == HW_BYTES,
            "output_hash_matches_capture": cap_out.get("sha256") == sha256_bytes(out_bytes),
            "buffer_size_matches_capture": cap_buffer.get("size") == len(out_bytes),
            "job_hash_matches_capture": capture.get("hashes", {}).get("job_json") == sha256_file(job_path),
            "regcmd_source_hash_matches_capture": capture.get("hashes", {}).get("regcmd_source") == sha256_file(regcmd_path),
            "input_hash_matches_capture": capture.get("hashes", {}).get("inputs", {}).get("input", {}).get("sha256") == sha256_file(input_path),
            "weight_hash_matches_capture": capture.get("hashes", {}).get("inputs", {}).get("weight", {}).get("sha256") == sha256_file(weight_path),
            "one_task_52_words": len(capture.get("tasks", [])) == 1
                                    and capture["tasks"][0].get("regcmd_words") == 52,
            "job_output_size_15104": next((b.get("size") for b in job.get("buffers", [])
                                           if b.get("name") == "output"), None) == HW_BYTES,
        }
        for name, ok in checks.items():
            if not ok:
                failures.append(f"{case}: capture check failed: {name}")

        case_summary = {
            "case": case,
            "status": capture.get("status"),
            "submit_ret": capture.get("submit_ret"),
            "submit_errno": capture.get("submit_errno"),
            "errors": capture.get("errors"),
            "timeout_ns": capture.get("timeout_ns"),
            "started_utc": capture.get("started_utc"),
            "finished_utc": capture.get("finished_utc"),
            "durations_ns": capture.get("durations"),
            "output_bytes": len(out_bytes),
            "output_elements_fp16": len(bits),
            "output_sha256": sha256_bytes(out_bytes),
            "expected_sha256": sha256_bytes(expected_bytes),
            "logical_shape_nchw": [1, OUT_C, OUT_H, OUT_W],
            "logical_elements": OUT_C * OUT_H * OUT_W,
            "logical_exact_fp16": exact,
            "logical_mismatches": len(logical_bits) - exact,
            "max_abs_diff": max_abs,
            "over_tolerance_0_2": over_tol,
            "first_mismatch": next(
                ({"index": i, "got": logical_values[i], "expected": expected_logical_values[i]}
                 for i, (a, b) in enumerate(zip(logical_bits, expected_logical_bits)) if a != b),
                None,
            ),
            "read_window_bytes": read_elems * 2,
            "used_logical_bytes": used * 2,
            "logical_channel_padding_elements": len(logical_channel_pad_bits),
            "logical_channel_padding_bytes": len(logical_channel_pad_bits) * 2,
            "logical_channel_padding_nonzero": logical_channel_pad_nonzero,
            "nonlogical_channel_elements": len(nonlogical_channel_bits),
            "nonlogical_channel_bytes": len(nonlogical_channel_bits) * 2,
            "nonlogical_channel_nonzero": nonlogical_channel_nonzero,
            "unused_in_read_window_elements": len(logical_channel_pad_bits) + len(nonlogical_channel_bits),
            "unused_in_read_window_bytes": (len(logical_channel_pad_bits)
                                             + len(nonlogical_channel_bits)) * 2,
            "unused_in_read_window_nonzero": (logical_channel_pad_nonzero
                                              + nonlogical_channel_nonzero),
            "second_surface_bytes": len(second_surface_bits) * 2,
            "second_surface_elements": len(second_surface_bits),
            "second_surface_nonzero": second_surface_nonzero,
            "padding_tail_nonzero_total": padding_nonzero,
            "beyond_declared_bo_tail_bytes": 0,
            "nonzero_elements_in_full_bo": full_nonzero,
            "capture_checks": checks,
            "addresses": capture.get("addresses"),
            "tool": capture.get("tool"),
            "device": capture.get("device"),
        }
        summary["cases"][case] = case_summary

        total_bytes += len(out_bytes)
        total_logical += len(logical_bits)
        total_exact += exact
        max_abs_all = max(max_abs_all, max_abs)
        total_padding_nonzero += padding_nonzero

    summary["totals"] = {
        "cases": len(CASES),
        "submit_ret_all_zero": all(c["submit_ret"] == 0 for c in summary["cases"].values()),
        "output_bytes_read_back": total_bytes,
        "logical_elements": total_logical,
        "logical_exact_fp16": total_exact,
        "logical_mismatches": total_logical - total_exact,
        "max_abs_diff": max_abs_all,
        "padding_tail_nonzero": total_padding_nonzero,
    }
    summary["failures"] = failures
    summary["result"] = "PASS" if not failures else "FAIL"

    (result_root / "host-analysis" / "comparison.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )

    lines = [
        f"result: {summary['result']}",
        f"cases: {len(CASES)}",
        f"total output bytes read back: {total_bytes}",
        f"logical FP16 exact: {total_exact}/{total_logical}",
        f"max abs diff: {max_abs_all}",
        f"padding/tail nonzero elements: {total_padding_nonzero}",
        "",
    ]
    for case, c in summary["cases"].items():
        lines.append(
            f"{case}: submit_ret={c['submit_ret']} status={c['status']} "
            f"output={c['output_bytes']}B sha256={c['output_sha256']} "
            f"exact={c['logical_exact_fp16']}/{c['logical_elements']} "
            f"max_abs={c['max_abs_diff']} over_tol={c['over_tolerance_0_2']} "
            f"logical_pad={c['logical_channel_padding_bytes']}B"
            f"(nonzero={c['logical_channel_padding_nonzero']}) "
            f"nonlogical_channels={c['nonlogical_channel_bytes']}B"
            f"(nonzero={c['nonlogical_channel_nonzero']}) "
            f"second_surface={c['second_surface_bytes']}B"
            f"(nonzero={c['second_surface_nonzero']})"
        )
    if failures:
        lines.append("")
        lines.extend(f"FAIL {failure}" for failure in failures)
    (result_root / "host-analysis" / "comparison.txt").write_text("\n".join(lines) + "\n")

    print("\n".join(lines))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
