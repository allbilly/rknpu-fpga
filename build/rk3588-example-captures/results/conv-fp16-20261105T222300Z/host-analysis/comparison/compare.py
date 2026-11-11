#!/usr/bin/env python3
"""Compare the 20261105T222300Z conv-fp16 board capture against its oracles.

Exact comparison is performed on the defined output elements after applying the
manifest output_layouts (the raw BO is wider than the compact oracle).  Padding
and per-channel tails are reported separately and are never compared to the
oracle.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

C2 = 8
ATOL = 0.2
RUN_ID = "20261105T222300Z"
BASE = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures")
FAMILY = BASE / "conv-fp16"
RUN = BASE / "results" / f"conv-fp16-{RUN_ID}" / "board-run" / "conv-fp16"
OUT = BASE / "results" / f"conv-fp16-{RUN_ID}" / "host-analysis" / "comparison"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unpack_nc1hwc2(raw: np.ndarray, out_c: int, out_h: int, out_w: int, ws: int) -> np.ndarray:
    c1 = raw.size // (ws * C2)
    packed = raw.reshape(c1, ws, C2)
    packed = packed[:, : out_h * out_w, :]
    return (
        packed.transpose(0, 2, 1)
        .reshape(c1 * C2, out_h * out_w)[:out_c]
        .reshape(out_c, out_h, out_w)
    )


def unpack_flat_1x1(raw: np.ndarray, out_c: int, out_h: int, out_w: int, ws: int) -> np.ndarray:
    c1 = raw.size // (ws * C2)
    packed = raw.reshape(1, c1, 1, ws, C2)
    return (
        packed[0, :, 0, : out_h * out_w, :]
        .transpose(0, 2, 1)
        .reshape(c1 * C2, out_h * out_w)[:out_c]
        .reshape(out_c, out_h, out_w)
    )


def region_masks(c1: int, ws: int, out_c: int, out_h: int, out_w: int):
    hw = out_h * out_w
    defined = np.zeros((c1, ws, C2), dtype=bool)
    channel_pad = np.zeros((c1, ws, C2), dtype=bool)
    tail = np.zeros((c1, ws, C2), dtype=bool)
    for ci in range(c1):
        for lane in range(C2):
            channel = ci * C2 + lane
            if channel < out_c:
                defined[ci, :hw, lane] = True
            else:
                channel_pad[ci, :hw, lane] = True
        tail[ci, hw:, :] = True
    return defined, channel_pad, tail


def pad_stats(raw_u16: np.ndarray, raw_f16: np.ndarray, mask: np.ndarray) -> dict:
    u16 = raw_u16.reshape(mask.shape)[mask]
    f16 = raw_f16.reshape(mask.shape)[mask]
    finite = f16[np.isfinite(f16)]
    return {
        "elements": int(u16.size),
        "nonzero_bits": int(np.count_nonzero(u16)),
        "nonzero_values": int(np.count_nonzero(f16 != 0)),
        "nan": int(np.count_nonzero(np.isnan(f16))),
        "inf": int(np.count_nonzero(np.isinf(f16))),
        "max_abs_finite": (
            float(np.max(np.abs(finite.astype(np.float64)))) if finite.size else 0.0
        ),
    }


def main() -> int:
    manifest = json.loads((FAMILY / "manifest.json").read_text())
    ready = [c for c in manifest["cases"] if c["status"] == "READY"]
    results = []
    all_ok = True

    for case in ready:
        name = case["case"]
        case_dir = FAMILY / "cases" / name
        job = json.loads((case_dir / "job.json").read_text())
        capture_path = RUN / name / "capture.json"
        capture = json.loads(capture_path.read_text())
        capture_out_hashes = {
            item.get("name"): item.get("output_sha256")
            for item in capture.get("buffers", [])
            if item.get("direction") in ("out", "inout")
        }
        capture_out_sizes = {
            item.get("name"): item.get("output_size")
            for item in capture.get("buffers", [])
            if item.get("direction") in ("out", "inout")
        }
        case_result = {
            "case": name,
            "capture_status": capture.get("status"),
            "submit_ret": capture.get("submit_ret"),
            "task_count": len(capture.get("tasks", [])),
            "device_path": capture.get("device_path"),
            "device": capture.get("device"),
            "tool": capture.get("tool"),
            "capture_json_sha256": sha256(capture_path.read_bytes()),
            "outputs": [],
            "exact_all": True,
            "tolerance_all": True,
        }
        job_files = {b.get("name"): b for b in job.get("buffers", [])}

        for layout in case.get("output_layouts", []):
            bname = layout["buffer"]
            out_path = RUN / name / layout["output"]
            exp_path = case_dir / layout["expected"]
            raw_bytes = out_path.read_bytes()
            exp_bytes = exp_path.read_bytes()
            out_c = int(layout["out_c"])
            out_h = int(layout["out_h"])
            out_w = int(layout["out_w"])
            ws = int(layout["out_width_stride"])
            c1 = int(layout["c1"])
            align_out_c = int(layout["align_out_c"])

            size_ok = len(raw_bytes) == int(layout["raw_bytes"])
            expected_size_ok = len(exp_bytes) == out_c * out_h * out_w * 2
            raw_u16 = np.frombuffer(raw_bytes, dtype="<u2").copy()
            raw_f16 = raw_u16.view(np.float16)
            if layout["layout"] == "flat_1x1":
                got = unpack_flat_1x1(raw_f16, out_c, out_h, out_w, ws)
            else:
                got = unpack_nc1hwc2(raw_f16, out_c, out_h, out_w, ws)
            exp_u16 = np.frombuffer(exp_bytes, dtype="<u2").copy()
            expected = exp_u16.view(np.float16).reshape(out_c, out_h, out_w)

            got_bytes = got.tobytes(order="C")
            got_u16 = np.frombuffer(got_bytes, dtype="<u2")
            exact_bytes = got_bytes == exp_bytes
            exact_byte_mismatches = sum(a != b for a, b in zip(got_bytes, exp_bytes))
            exact_element_mismatches = int(np.count_nonzero(got_u16 != exp_u16))

            got64 = got.astype(np.float64)
            exp64 = expected.astype(np.float64)
            diff = np.abs(got64 - exp64)
            nonfinite = ~np.isfinite(got64)
            over = np.count_nonzero((diff > ATOL) | nonfinite)
            max_diff = float(np.nanmax(diff)) if np.any(np.isfinite(diff)) else float("nan")
            nonzero_diff = int(np.count_nonzero(diff != 0))

            defined_mask, channel_mask, tail_mask = region_masks(
                c1, ws, out_c, out_h, out_w
            )
            # Sanity: the unpacked shape and raw layout agree with the manifest.
            layout_ok = (
                c1 * C2 == align_out_c
                and raw_u16.size == c1 * ws * C2
                and int(np.count_nonzero(defined_mask)) == out_c * out_h * out_w
            )
            padding_total = pad_stats(raw_u16, raw_f16, ~defined_mask)
            padding_channel = pad_stats(raw_u16, raw_f16, channel_mask)
            padding_tail = pad_stats(raw_u16, raw_f16, tail_mask)

            capture_hash = capture_out_hashes.get(bname)
            capture_size = capture_out_sizes.get(bname)
            job_buffer_size = int(job_files[bname]["size"])
            output_sha = sha256(raw_bytes)

            exact_ok = exact_bytes and size_ok and expected_size_ok and layout_ok
            tol_ok = over == 0 and size_ok and expected_size_ok and layout_ok
            all_ok = all_ok and exact_ok and tol_ok and capture.get("status") == "OK" and capture.get("submit_ret") == 0
            case_result["exact_all"] = case_result["exact_all"] and exact_ok
            case_result["tolerance_all"] = case_result["tolerance_all"] and tol_ok

            output_result = {
                "buffer": bname,
                "output": layout["output"],
                "expected": layout["expected"],
                "layout": layout["layout"],
                "out_c": out_c,
                "out_h": out_h,
                "out_w": out_w,
                "out_width_stride": ws,
                "align_out_c": align_out_c,
                "c1": c1,
                "c2": C2,
                "raw_bytes": len(raw_bytes),
                "declared_raw_bytes": int(layout["raw_bytes"]),
                "buffer_size": job_buffer_size,
                "expected_bytes": len(exp_bytes),
                "size_ok": size_ok,
                "expected_size_ok": expected_size_ok,
                "layout_ok": layout_ok,
                "output_sha256": output_sha,
                "capture_output_sha256": capture_hash,
                "capture_hash_matches": capture_hash == output_sha,
                "capture_output_size": capture_size,
                "capture_size_matches": capture_size == len(raw_bytes),
                "expected_sha256": sha256(exp_bytes),
                "defined_sha256": sha256(got_bytes),
                "exact_bytes_equal": exact_bytes,
                "exact_byte_mismatches": int(exact_byte_mismatches),
                "exact_element_mismatches": int(exact_element_mismatches),
                "tolerance_atol": ATOL,
                "nonzero_diff_elements": int(nonzero_diff),
                "over_tolerance_elements": int(over),
                "nonfinite_elements": int(np.count_nonzero(nonfinite)),
                "max_abs_diff": max_diff,
                "defined_elements": int(out_c * out_h * out_w),
                "padding_total": padding_total,
                "padding_channel": padding_channel,
                "padding_tail": padding_tail,
            }
            case_result["outputs"].append(output_result)

            print(
                f"{name:52s} {bname:5s} "
                f"exact_bytes={'YES' if exact_bytes else 'NO'} "
                f"byte_diff={exact_byte_mismatches} "
                f"elem_bits_diff={exact_element_mismatches} "
                f"max_abs={max_diff:.6g} over_atol={over}/{out_c*out_h*out_w} "
                f"pad_nonzero={padding_total['nonzero_bits']}/{padding_total['elements']} "
                f"tail_nonzero={padding_tail['nonzero_bits']}/{padding_tail['elements']}"
            )

        # Compare the raw promoted-case BO to the diagnostic evidence bytes, if
        # present.  This is a raw-byte check of padding as well as data.
        evidence = sorted(case_dir.glob("evidence_diagnostic_out*.bin"))
        case_result["diagnostic_evidence"] = []
        for ev in evidence:
            stem = ev.stem.replace("evidence_diagnostic_", "")
            target_name = "out" + stem[-1] + ".bin"
            target = RUN / name / target_name
            if not target.is_file():
                continue
            ev_bytes = ev.read_bytes()
            got_bytes = target.read_bytes()
            mismatch = sum(a != b for a, b in zip(ev_bytes, got_bytes))
            first = next((i for i, (a, b) in enumerate(zip(ev_bytes, got_bytes)) if a != b), None)
            # Check whether the diagnostic raw BO also matches the compact
            # oracle on its defined region; any remaining raw difference is
            # then confined to undefined padding/tail bytes.
            ev_u16 = np.frombuffer(ev_bytes, dtype="<u2").copy()
            ev_f16 = ev_u16.view(np.float16)
            if layout["layout"] == "flat_1x1":
                ev_got = unpack_flat_1x1(ev_f16, out_c, out_h, out_w, ws)
            else:
                ev_got = unpack_nc1hwc2(ev_f16, out_c, out_h, out_w, ws)
            ev_got_bytes = ev_got.tobytes(order="C")
            ev_defined_exact = ev_got_bytes == exp_bytes
            ev_defined_mismatches = int(
                np.count_nonzero(
                    np.frombuffer(ev_got_bytes, dtype="<u2") != exp_u16
                )
            )
            # Byte-level classification of evidence-vs-new differences.
            mask_flat = defined_mask.reshape(-1)
            evidence_defined_byte_diffs = 0
            evidence_padding_byte_diffs = 0
            for i, (a, b) in enumerate(zip(ev_bytes, got_bytes)):
                if a != b:
                    if mask_flat[i // 2]:
                        evidence_defined_byte_diffs += 1
                    else:
                        evidence_padding_byte_diffs += 1
            item = {
                "evidence_file": ev.name,
                "target_file": target_name,
                "evidence_sha256": sha256(ev_bytes),
                "target_sha256": sha256(got_bytes),
                "raw_bytes_equal": ev_bytes == got_bytes,
                "raw_byte_mismatches": mismatch,
                "first_mismatch_offset": first,
                "evidence_defined_exact": ev_defined_exact,
                "evidence_defined_element_mismatches": ev_defined_mismatches,
                "evidence_defined_byte_diffs": evidence_defined_byte_diffs,
                "evidence_padding_byte_diffs": evidence_padding_byte_diffs,
            }
            case_result["diagnostic_evidence"].append(item)
            print(
                f"{name:52s} evidence={ev.name} raw_equal={item['raw_bytes_equal']} "
                f"raw_diff_bytes={mismatch} first={first}"
            )

        results.append(case_result)

    summary = {
        "run_id": RUN_ID,
        "atol": ATOL,
        "case_count": len(results),
        "cases_exact_all": sum(1 for c in results if c["exact_all"]),
        "cases_tolerance_all": sum(1 for c in results if c["tolerance_all"]),
        "all_ok": all_ok,
        "cases": results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"SUMMARY cases={len(results)} exact_all={summary['cases_exact_all']} "
        f"tolerance_all={summary['cases_tolerance_all']} all_ok={all_ok}"
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
