#!/usr/bin/env python3
"""Compare the 20261105T214000Z conv-gemm-vendor board captures to the manifest.

The board output BO bytes are read from the copied run tree exactly as returned.
No expected data is substituted into output.bin.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

RUN_ID = "20261105T214000Z"
HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent
FAMILY = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-gemm-vendor")
OUT_ROOT = RESULTS / "conv-gemm-vendor"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def f16_bits(a: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(a, dtype="<f2").view("<u2")


def f32_bits(a: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(a, dtype="<f4").view("<u4")


def unpack_flat(out_raw: np.ndarray, out_c: int, out_h: int, out_w: int,
                out_width_stride: int, c2: int) -> np.ndarray:
    c1 = out_raw.size // (out_width_stride * c2)
    packed = out_raw.reshape(1, c1, 1, out_width_stride, c2)
    return (packed[0, :, 0, :out_h * out_w, :]
            .transpose(0, 2, 1)
            .reshape(c1 * c2, out_h * out_w)[:out_c]
            .reshape(out_c, out_h, out_w))


def unpack_grouped(out_raw: np.ndarray, out_c: int, out_h: int, out_w: int,
                   c2: int, plane_stride: int) -> np.ndarray:
    c1 = (out_c + c2 - 1) // c2
    result = np.zeros((out_c, out_h, out_w), dtype=out_raw.dtype)
    for plane in range(c1):
        plane_raw = out_raw[plane * plane_stride:plane * plane_stride + out_h * out_w * c2]
        channels = min(c2, out_c - plane * c2)
        result[plane * c2:plane * c2 + channels] = (
            plane_raw.reshape(out_h, out_w, c2).transpose(2, 0, 1)[:channels])
    return result


def decode_f16(value: float) -> float:
    return float(np.float32(np.float16(value)))


def first_diff_details(got: np.ndarray, expected: np.ndarray, dtype: str,
                       element_bytes: int, max_items: int = 8) -> list[dict]:
    details = []
    if dtype == "float32":
        g, e = f32_bits(got.reshape(-1)), f32_bits(expected.reshape(-1))
        gv, ev = got.reshape(-1), expected.reshape(-1)
    else:
        g, e = f16_bits(got.reshape(-1)), f16_bits(expected.reshape(-1))
        gv, ev = got.reshape(-1), expected.reshape(-1)
    diff = np.nonzero(g != e)[0]
    for idx in diff[:max_items]:
        details.append({
            "element_index": int(idx),
            "byte_offset": int(idx * element_bytes),
            "got": float(gv[idx]),
            "expected": float(ev[idx]),
            "got_bits": f"0x{int(g[idx]):0{element_bytes * 2}x}",
            "expected_bits": f"0x{int(e[idx]):0{element_bytes * 2}x}",
        })
    return details


def tolerance_details(got: np.ndarray, expected: np.ndarray, dtype: str,
                      element_bytes: int, tolerance: float, max_items: int = 8) -> list[dict]:
    gv = got.reshape(-1).astype(np.float64)
    ev = expected.reshape(-1).astype(np.float64)
    diff = np.abs(gv - ev)
    bad = ~(diff <= tolerance)
    details = []
    for idx in np.nonzero(bad)[0][:max_items]:
        details.append({
            "element_index": int(idx),
            "byte_offset": int(idx * element_bytes),
            "got": float(gv[idx]),
            "expected": float(ev[idx]),
            "abs_diff": None if math.isnan(float(diff[idx])) else float(diff[idx]),
        })
    return details


def extract_surface_add(regcmd: bytes) -> tuple[int | None, int | None, int | None]:
    """Return (SURFACE_ADD word index/value, out-channel field, align_out_c)."""
    words = struct.unpack("<%dQ" % (len(regcmd) // 8), regcmd)
    surface = None
    channel_field = None
    for idx, word in enumerate(words):
        target = (word >> 48) & 0xFFFF
        offset = word & 0xFFFF
        value = (word >> 16) & 0xFFFFFFFF
        if (target, offset) == (0x1001, 0x40C0):
            surface = (idx, value)
        if (target, offset) == (0x1001, 0x403C):
            channel_field = value & 0xFFFF
    return surface, channel_field, None


def compare_gemm(case: dict, output: bytes, case_dir: Path) -> dict:
    oracle = case["oracle"]
    m, n = oracle["shape"]
    expected = (case_dir / oracle["file"]).read_bytes()
    expected_surface = (case_dir / oracle["expected_surface_file"]).read_bytes()
    out = np.frombuffer(output, dtype="<f4")
    exp = np.frombuffer(expected, dtype="<f4")
    exp_surface = np.frombuffer(expected_surface, dtype="<f4")

    raw_exact_bytes = sum(a == b for a, b in zip(output, expected_surface))
    raw_diff = next((i for i, (a, b) in enumerate(zip(output, expected_surface)) if a != b), None)

    logical = out.reshape(-1, 32)[:m, :n].reshape(-1)
    logical_exact_bytes = sum(a == b for a, b in zip(logical.astype("<f4").tobytes(), expected))
    logical_bits_equal = int(np.count_nonzero(f32_bits(logical) == f32_bits(exp)))
    absdiff = np.abs(logical.astype(np.float64) - exp.astype(np.float64))
    over = ~(absdiff <= oracle["tolerance_abs"])

    # Padding: columns N..31 of logical rows and all rows >= M.  expected_surface
    # is zero there (padded to the output BO size).
    logical_mask = np.zeros(out.size, dtype=bool)
    for row in range(m):
        logical_mask[row * 32:row * 32 + n] = True
    padding = out[~logical_mask]
    exp_padding = exp_surface[~logical_mask]

    return {
        "kind": "gemm",
        "shape": [m, n],
        "output_bytes": len(output),
        "expected_bytes": len(expected),
        "expected_surface_bytes": len(expected_surface),
        "raw_surface_exact_bytes": raw_exact_bytes,
        "raw_surface_first_diff_offset": raw_diff,
        "raw_surface_exact_elements": int(np.count_nonzero(f32_bits(out) == f32_bits(exp_surface))),
        "raw_surface_elements": int(out.size),
        "logical_exact_bytes": logical_exact_bytes,
        "logical_bytes": len(expected),
        "logical_exact_elements": logical_bits_equal,
        "logical_elements": int(exp.size),
        "max_abs_diff": float(np.nanmax(absdiff)) if absdiff.size else 0.0,
        "tolerance_abs": oracle["tolerance_abs"],
        "over_tolerance_elements": int(np.count_nonzero(over)),
        "exact_pass": logical_exact_bytes == len(expected),
        "tolerance_pass": int(np.count_nonzero(over)) == 0,
        "first_exact_diffs": first_diff_details(logical, exp, "float32", 4),
        "first_tolerance_failures": tolerance_details(
            logical, exp, "float32", 4, oracle["tolerance_abs"]),
        "padding": {
            "elements": int(padding.size),
            "bytes": int(padding.size * 4),
            "nonzero_elements": int(np.count_nonzero(f32_bits(padding))),
            "expected_nonzero_elements": int(np.count_nonzero(f32_bits(exp_padding))),
            "max_abs_value": float(np.max(np.abs(padding))) if padding.size else 0.0,
        },
    }


def compare_conv(case: dict, output: bytes, case_dir: Path) -> dict:
    oracle = case["oracle"]
    lay = case["conv_layout"]
    _, out_c, out_h, out_w = oracle["shape"]
    c2 = lay["unpack_c2"]
    ows = lay["out_width_stride"]
    expected = (case_dir / oracle["file"]).read_bytes()
    out = np.frombuffer(output, dtype="<f2")
    exp = np.frombuffer(expected, dtype="<f2")

    # Source read count: grouped spatial uses out_c; others use align_out_c.
    if lay["grouped_spatial"]:
        plane_stride = out_h * out_w * c2 + ows * 2
        read_count = ((out_c + c2 - 1) // c2) * plane_stride
        got = unpack_grouped(out[:read_count], out_c, out_h, out_w, c2, plane_stride)
    else:
        c1 = (lay["align_out_c"] + c2 - 1) // c2
        read_count = c1 * ows * c2
        got = unpack_flat(out[:read_count], out_c, out_h, out_w, ows, c2)

    logical_exact_bytes = sum(a == b for a, b in zip(got.astype("<f2").tobytes(), expected))
    logical_bits_equal = int(np.count_nonzero(f16_bits(got.reshape(-1)) == f16_bits(exp)))
    absdiff = np.abs(got.reshape(-1).astype(np.float64) - exp.astype(np.float64))
    over = ~(absdiff <= oracle["tolerance_abs"])
    nonfinite = int(np.count_nonzero(~np.isfinite(got)))

    # Used raw elements implied by the source layout, so padding/tails can be
    # reported separately from the logical FP16/NCHW values.
    used = np.zeros(read_count, dtype=bool)
    if lay["grouped_spatial"]:
        c1 = (out_c + c2 - 1) // c2
        for plane in range(c1):
            for pos in range(out_h * out_w):
                for ch in range(c2):
                    if plane * c2 + ch < out_c:
                        used[plane * plane_stride + pos * c2 + ch] = True
    else:
        c1 = (lay["align_out_c"] + c2 - 1) // c2
        for plane in range(c1):
            for pos in range(out_h * out_w):
                for ch in range(c2):
                    if plane * c2 + ch < out_c:
                        used[plane * ows * c2 + pos * c2 + ch] = True

    pad = out[:read_count][~used]
    tail = out[read_count:]

    regcmd = (case_dir / "regcmd.bin").read_bytes()
    surface, channel_field, _ = extract_surface_add(regcmd)
    surface_add = surface[1] if surface else None
    # The hardware output channel field is the low 16 bits of
    # DPU_DATA_CUBE_CHANNEL.  For depthwise it is rounded up to 32.
    hw_channels = (channel_field + 1) if channel_field is not None else None
    groups = ((hw_channels + 15) // 16) if hw_channels else None
    required = (groups * surface_add) if (groups and surface_add) else None

    return {
        "kind": "conv",
        "shape": list(oracle["shape"]),
        "layout": {
            "grouped_spatial": lay["grouped_spatial"],
            "align_out_c": lay["align_out_c"],
            "unpack_c2": c2,
            "out_width_stride": ows,
        },
        "output_bytes": len(output),
        "expected_bytes": len(expected),
        "source_read_elements": int(read_count),
        "source_read_bytes": int(read_count * 2),
        "logical_exact_bytes": logical_exact_bytes,
        "logical_bytes": len(expected),
        "logical_exact_elements": logical_bits_equal,
        "logical_elements": int(exp.size),
        "max_abs_diff": float(np.nanmax(absdiff)) if absdiff.size else 0.0,
        "tolerance_abs": oracle["tolerance_abs"],
        "over_tolerance_elements": int(np.count_nonzero(over)),
        "nonfinite_elements": nonfinite,
        "exact_pass": logical_exact_bytes == len(expected),
        "tolerance_pass": int(np.count_nonzero(over)) == 0,
        "first_exact_diffs": first_diff_details(got.reshape(-1), exp, "float16", 2),
        "first_tolerance_failures": tolerance_details(
            got.reshape(-1), exp, "float16", 2, oracle["tolerance_abs"]),
        "padding_and_tails": {
            "declared_output_bytes": len(output),
            "source_read_bytes": int(read_count * 2),
            "unused_within_read_elements": int(pad.size),
            "unused_within_read_bytes": int(pad.size * 2),
            "unused_within_read_nonzero_elements": int(np.count_nonzero(f16_bits(pad))),
            "tail_elements_after_source_read": int(tail.size),
            "tail_bytes_after_source_read": int(tail.size * 2),
            "tail_nonzero_elements": int(np.count_nonzero(f16_bits(tail))),
            "first_unused_nonzero_offsets": [
                int(i * 2) for i in np.nonzero(f16_bits(pad) != 0)[0][:8]
            ],
            "first_tail_nonzero_offsets": [
                int(read_count * 2 + i * 2) for i in np.nonzero(f16_bits(tail) != 0)[0][:8]
            ],
        },
        "dpu_surface": {
            "surface_add_word_index": surface[0] if surface else None,
            "surface_add_bytes": surface_add,
            "dpudatacube_channel_field": channel_field,
            "hardware_channels": hw_channels,
            "sixteen_channel_groups": groups,
            "required_output_bytes": required,
            "declared_output_bytes": len(output),
            "declared_output_sufficient": (required is not None and len(output) >= required),
        },
    }


def main() -> int:
    manifest = json.loads((FAMILY / "manifest.json").read_text())
    failures = []
    results = []
    total_output_bytes = 0
    for case in manifest["cases"]:
        if case["status"] != "READY":
            continue
        name = case["case"]
        case_dir = FAMILY / case["case_dir"]
        case_out = OUT_ROOT / name
        capture = json.loads((case_out / "capture.json").read_text())
        output_path = case_out / "output.bin"

        # Contract/capture checks.
        if capture.get("status") != "OK":
            failures.append(f"{name}: capture status {capture.get('status')!r}")
        if capture.get("submit_ret") != 0:
            failures.append(f"{name}: submit_ret {capture.get('submit_ret')!r}")
        if capture.get("errors"):
            failures.append(f"{name}: capture errors {capture['errors']}")
        if capture.get("tool", {}).get("sha256") != "a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd":
            failures.append(f"{name}: runner sha mismatch")
        if sha256_file(case_dir / "job.json") != capture["hashes"]["job_json"]:
            failures.append(f"{name}: capture job hash != local job.json")
        if sha256_file(case_dir / "regcmd.bin") != capture["hashes"]["regcmd_source"]:
            failures.append(f"{name}: capture regcmd_source != local regcmd.bin")
        for buf in capture["buffers"]:
            if buf["direction"] == "in":
                local = sha256_file(case_dir / buf["input"])
                if local != buf["input_sha256"]:
                    failures.append(f"{name}: input hash {buf['name']} mismatch")
            else:
                if sha256_file(output_path) != buf["output_sha256"]:
                    failures.append(f"{name}: output hash {buf['name']} mismatch")
                if output_path.stat().st_size != buf["output_size"]:
                    failures.append(f"{name}: output size {buf['name']} mismatch")

        output = output_path.read_bytes()
        total_output_bytes += len(output)
        if case["oracle"]["dtype"] == "float32":
            comparison = compare_gemm(case, output, case_dir)
        else:
            comparison = compare_conv(case, output, case_dir)
        comparison.update({
            "case": name,
            "capture_status": capture["status"],
            "submit_ret": capture["submit_ret"],
            "started_utc": capture["started_utc"],
            "finished_utc": capture["finished_utc"],
            "output_sha256": sha256_bytes(output),
            "capture_sha256": sha256_file(case_out / "capture.json"),
            "durations_ns": capture["durations"],
        })
        results.append(comparison)

    summary = {
        "run_id": RUN_ID,
        "family": manifest["family"],
        "ready_cases": len(results),
        "blocked_cases_not_staged": sum(1 for c in manifest["cases"] if c["status"] == "BLOCKED"),
        "capture_status_ok": sum(1 for r in results if r["capture_status"] == "OK"),
        "submit_ret_zero": sum(1 for r in results if r["submit_ret"] == 0),
        "exact_pass_cases": sum(1 for r in results if r["exact_pass"]),
        "tolerance_pass_cases": sum(1 for r in results if r["tolerance_pass"]),
        "total_output_bytes_read": total_output_bytes,
        "checksum_failures": failures,
    }
    payload = {"summary": summary, "results": results}
    (HERE / "comparison.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))
    for r in results:
        print(f"{r['case']}: exact={r['exact_pass']} tolerance={r['tolerance_pass']} "
              f"exact_bytes={r['logical_exact_bytes']}/{r['logical_bytes']} "
              f"over={r['over_tolerance_elements']} maxdiff={r['max_abs_diff']}")
    if failures:
        print("CHECKSUM/CONTRACT FAILURES:", file=sys.stderr)
        for f in failures:
            print(" -", f, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
