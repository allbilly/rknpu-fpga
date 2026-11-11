#!/usr/bin/env python3
"""Host-side comparison of the returned pooling capture BOs with expected.bin.

This program only reads files under build/ and writes a separate analysis
directory.  It never contacts the board or the device.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path("/home/fedora/rknpu-fpga")
BASE = REPO / "build/rk3588-example-captures"
MANIFEST = BASE / "pooling" / "manifest.json"

DTYPES = {
    "float16": ("<f2", np.float16, 2),
    "int16": ("<i2", np.int16, 2),
    "int8": ("i1", np.int8, 1),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode(raw: bytes, dtype: str) -> float | int:
    arr = np.frombuffer(raw, dtype=np.dtype(dtype))
    value = arr[0].item()
    return value


def fmt_value(value, dtype: str) -> str:
    if dtype == "float16":
        v = float(value)
        if np.isnan(v):
            return "nan"
        if np.isposinf(v):
            return "+inf"
        if np.isneginf(v):
            return "-inf"
        return f"{v:.6g}"
    return str(int(value))


def mismatch_details(
    got: bytes, exp: bytes, dtype: str, item_bytes: int, offset: int, **where
) -> dict:
    e = decode(exp[offset : offset + item_bytes], dtype)
    g = decode(got[offset : offset + item_bytes], dtype)
    row = {
        "byte_offset": offset,
        "expected_hex": exp[offset : offset + item_bytes].hex(),
        "got_hex": got[offset : offset + item_bytes].hex(),
        "expected": fmt_value(e, dtype),
        "got": fmt_value(g, dtype),
        "raw_expected": int.from_bytes(exp[offset : offset + item_bytes], "little"),
        "raw_got": int.from_bytes(got[offset : offset + item_bytes], "little"),
    }
    row.update(where)
    return row


def compare_case(name: str, entry: dict, out_root: Path) -> dict:
    ppu = entry["ppu"]
    shapes = entry["shapes"]
    layout = entry["layout"]
    oracle = entry["oracle"]
    dtype = ppu["dtype"]
    dstr, _dtype, item_bytes = DTYPES[dtype]
    channels = ppu["channels"]
    atom_channels = shapes["atom_channels"]
    atom_bytes = shapes["atom_bytes"]
    out_h, out_w = ppu["out_shape"]
    value_bytes = layout["output"]["value_bytes"]
    index_en = bool(ppu["index_en"])
    index_bytes = layout["output"]["index_bytes"]
    index_offset = layout["output"]["index_offset"]
    logical = oracle["logical_output_bytes"]
    tolerance = float(oracle["tolerance"])
    padding = ppu["padding"]
    is_padded = any(padding)
    is_fp16_average = dtype == "float16" and ppu["method"] == "average"

    case_out = out_root / name
    capture_path = case_out / "capture.json"
    out_path = case_out / "out.bin"
    exp_path = BASE / "pooling" / "cases" / name / "expected.bin"
    init_path = BASE / "pooling" / "cases" / name / "out_init.bin"
    result: dict = {"case": name, "ok": False}
    problems: list[str] = []

    for path, label in (
        (capture_path, "capture.json"),
        (out_path, "out.bin"),
        (exp_path, "expected.bin"),
        (init_path, "out_init.bin"),
    ):
        if not path.is_file():
            problems.append(f"missing {label}: {path}")

    if not capture_path.is_file() or not out_path.is_file() or not exp_path.is_file():
        result["problems"] = problems
        return result

    capture = json.loads(capture_path.read_text())
    got = out_path.read_bytes()
    exp = exp_path.read_bytes()
    out_init = init_path.read_bytes() if init_path.is_file() else b""
    got_sha = sha256(got)
    exp_sha = sha256(exp)
    out_init_sha = sha256(out_init) if out_init else None

    result.update(
        {
            "status": capture.get("status"),
            "submit_ret": capture.get("submit_ret"),
            "submit_errno": capture.get("submit_errno"),
            "submit_error": capture.get("submit_error"),
            "errors": capture.get("errors", []),
            "cleanup_errors": capture.get("cleanup_errors", []),
            "started_utc": capture.get("started_utc"),
            "dtype": dtype,
            "method": ppu["method"],
            "index_en": index_en,
            "padded": is_padded,
            "padding": padding,
            "padding_value": ppu["padding_value"],
            "out_bytes": len(got),
            "expected_bytes": len(exp),
            "out_init_bytes": len(out_init),
            "out_sha256": got_sha,
            "expected_sha256": exp_sha,
            "out_init_sha256": out_init_sha,
            "value_bytes": value_bytes,
            "index_bytes": index_bytes,
            "index_offset": index_offset,
            "logical_output_bytes": logical,
            "tolerance": tolerance if is_fp16_average else None,
            "durations": capture.get("durations", {}),
            "addresses": capture.get("addresses", {}),
            "device": capture.get("device", {}),
            "tool": capture.get("tool", {}),
        }
    )

    if capture.get("status") != "OK":
        problems.append(f"capture status is {capture.get('status')!r}")
    if capture.get("submit_ret") != 0:
        problems.append(f"submit_ret is {capture.get('submit_ret')!r}")
    if capture.get("errors"):
        problems.append(f"runner errors: {capture.get('errors')}")
    if capture.get("cleanup_errors"):
        problems.append(f"runner cleanup errors: {capture.get('cleanup_errors')}")
    if len(got) != 4096:
        problems.append(f"out.bin is {len(got)} bytes, expected 4096")
    if len(exp) != 4096:
        problems.append(f"expected.bin is {len(exp)} bytes, expected 4096")
    if len(got) != len(exp):
        problems.append("out.bin and expected.bin sizes differ")

    # The runner's own capture must record exactly the bytes we received.
    recorded: list[str] = []
    for row in capture.get("outputs", []):
        if row.get("buffer") == "out":
            recorded.append(row.get("sha256"))
            if row.get("size") != len(got):
                problems.append(
                    f"capture output size {row.get('size')} != out.bin size {len(got)}"
                )
    if capture.get("hashes", {}).get("outputs", {}).get("out", {}).get("sha256"):
        recorded.append(capture["hashes"]["outputs"]["out"]["sha256"])
    for row in capture.get("buffers", []):
        if row.get("name") == "out" and row.get("output_sha256"):
            recorded.append(row["output_sha256"])
    result["capture_output_hashes"] = recorded
    if not recorded:
        problems.append("capture.json records no out buffer hash")
    elif any(h != got_sha for h in recorded):
        problems.append("capture.json output hash does not match returned out.bin")

    # Byte-exact comparisons at three scopes.
    full_diff = [i for i in range(min(len(got), len(exp))) if got[i] != exp[i]]
    declared_diff = [
        i for i in range(min(logical, len(got), len(exp))) if got[i] != exp[i]
    ]
    value_diff = [
        i for i in range(min(value_bytes, len(got), len(exp))) if got[i] != exp[i]
    ]
    index_diff = []
    if index_en:
        index_diff = [
            i
            for i in range(index_offset, min(index_offset + index_bytes, len(got), len(exp)))
            if got[i] != exp[i]
        ]
    gap_nonzero_got = []
    gap_nonzero_exp = []
    if index_en:
        gap_nonzero_got = [i for i in range(value_bytes, index_offset) if got[i] != 0]
        gap_nonzero_exp = [i for i in range(value_bytes, index_offset) if exp[i] != 0]
    tail_nonzero_got = [i for i in range(logical, min(4096, len(got))) if got[i] != 0]
    tail_nonzero_exp = [i for i in range(logical, min(4096, len(exp))) if exp[i] != 0]

    result.update(
        {
            "full_bo_exact": not full_diff,
            "full_bo_mismatch_bytes": len(full_diff),
            "full_bo_first_mismatch_offsets": full_diff[:32],
            "declared_region_exact": not declared_diff,
            "declared_region_mismatch_bytes": len(declared_diff),
            "declared_region_first_mismatch_offsets": declared_diff[:32],
            "value_region_exact": not value_diff,
            "value_region_mismatch_bytes": len(value_diff),
            "index_region_exact": (not index_diff) if index_en else None,
            "index_region_mismatch_bytes": len(index_diff) if index_en else None,
            "gap_nonzero_got_bytes": len(gap_nonzero_got),
            "gap_nonzero_expected_bytes": len(gap_nonzero_exp),
            "gap_first_nonzero_got_offsets": gap_nonzero_got[:32],
            "tail_nonzero_got_bytes": len(tail_nonzero_got),
            "tail_nonzero_expected_bytes": len(tail_nonzero_exp),
            "tail_first_nonzero_got_offsets": tail_nonzero_got[:32],
            "out_bin_equals_expected_full": got == exp,
            "out_bin_equals_out_init": got == out_init if out_init else None,
        }
    )

    # Decoded value region, including atom tail lanes (the C3 case declares
    # its tail lanes as -99 in the logical output).
    value_mismatches: list[dict] = []
    if value_bytes % atom_bytes != 0:
        problems.append("value region is not a whole number of 16-byte atoms")
    else:
        surfaces = value_bytes // (out_h * out_w * atom_bytes)
        for s in range(surfaces):
            for y in range(out_h):
                for x in range(out_w):
                    base = ((s * out_h + y) * out_w + x) * atom_bytes
                    for lane in range(atom_channels):
                        off = base + lane * item_bytes
                        if off + item_bytes > value_bytes:
                            continue
                        if got[off : off + item_bytes] == exp[off : off + item_bytes]:
                            continue
                        channel = s * atom_channels + lane
                        value_mismatches.append(
                            mismatch_details(
                                got,
                                exp,
                                dtype,
                                item_bytes,
                                off,
                                region="value",
                                surface=s,
                                y=y,
                                x=x,
                                lane=lane,
                                channel=channel if channel < channels else None,
                                logical_channel=channel < channels,
                                atom_tail=channel >= channels,
                            )
                        )
    result["value_mismatches"] = value_mismatches
    result["value_mismatch_elements"] = len(value_mismatches)

    index_mismatches: list[dict] = []
    if index_en and index_bytes:
        units = index_bytes // 16
        if units % (out_h * out_w) != 0:
            problems.append("index region does not map to whole output positions")
        else:
            index_surfaces = units // (out_h * out_w)
            for s in range(index_surfaces):
                for y in range(out_h):
                    for x in range(out_w):
                        base = index_offset + ((s * out_h + y) * out_w + x) * 16
                        for lane in range(8):
                            off = base + lane * 2
                            if off + 2 > index_offset + index_bytes:
                                continue
                            if got[off : off + 2] == exp[off : off + 2]:
                                continue
                            channel = s * 8 + lane
                            index_mismatches.append(
                                mismatch_details(
                                    got,
                                    exp,
                                    "uint16",
                                    2,
                                    off,
                                    region="index_position",
                                    surface=s,
                                    y=y,
                                    x=x,
                                    lane=lane,
                                    channel=channel,
                                )
                            )
    result["index_mismatches"] = index_mismatches
    result["index_mismatch_elements"] = len(index_mismatches) if index_en else None

    # FP16 average tolerance is reported separately and never replaces the
    # byte-exact result above.
    if is_fp16_average:
        diffs: list[dict] = []
        surfaces = value_bytes // (out_h * out_w * atom_bytes)
        for s in range(surfaces):
            for y in range(out_h):
                for x in range(out_w):
                    base = ((s * out_h + y) * out_w + x) * atom_bytes
                    for lane in range(atom_channels):
                        off = base + lane * item_bytes
                        if off + item_bytes > value_bytes:
                            continue
                        channel = s * atom_channels + lane
                        if channel >= channels:
                            continue
                        ev = float(decode(exp[off : off + item_bytes], dtype))
                        gv = float(decode(got[off : off + item_bytes], dtype))
                        diff = abs(gv - ev)
                        diffs.append(
                            {
                                "byte_offset": off,
                                "channel": channel,
                                "y": y,
                                "x": x,
                                "expected": fmt_value(ev, dtype),
                                "got": fmt_value(gv, dtype),
                                "abs_diff": diff,
                                "exceeds_atol": (not np.isfinite(diff)) or diff > tolerance,
                            }
                        )
        finite = [d["abs_diff"] for d in diffs if np.isfinite(d["abs_diff"])]
        result["tolerance_applicable"] = True
        result["tolerance_atol"] = tolerance
        result["tolerance_max_abs_diff"] = max(finite) if finite else None
        result["tolerance_nonfinite_count"] = sum(
            1 for d in diffs if not np.isfinite(d["abs_diff"])
        )
        result["tolerance_exceeds_count"] = sum(1 for d in diffs if d["exceeds_atol"])
        result["tolerance_pass"] = all(not d["exceeds_atol"] for d in diffs)
        result["tolerance_elements"] = len(diffs)
        result["tolerance_over_atol"] = [
            d for d in diffs if d["exceeds_atol"]
        ][:64]
    else:
        result["tolerance_applicable"] = False
        result["tolerance_atol"] = None
        result["tolerance_max_abs_diff"] = None
        result["tolerance_pass"] = None
        result["tolerance_exceeds_count"] = None

    # Padding note: for padded cases the arithmetic padding is already part of
    # the declared oracle values; only bytes outside the declared region are
    # excluded from the value verdict and are reported above as tail bytes.
    result["padding_note"] = (
        "padding config "
        f"{padding} with padding_value {ppu['padding_value']} is baked into the "
        "declared oracle values; undeclared bytes after logical_output_bytes are "
        "reported separately and are not part of the value verdict"
        if is_padded
        else "no padding"
    )

    result["problems"] = problems
    result["ok"] = not problems
    return result


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: compare_pooling.py RUN_ID", file=sys.stderr)
        return 2
    run_id = sys.argv[1]
    run_root = BASE / "results" / f"pooling-{run_id}"
    out_root = run_root / "pooling"
    analysis_root = BASE / "results" / f"pooling-{run_id}-host-analysis"
    if not out_root.is_dir():
        print(f"missing capture tree: {out_root}", file=sys.stderr)
        return 1
    analysis_root.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(MANIFEST.read_text())
    cases_by_name = {c["case"]: c for c in manifest["cases"]}
    ready = manifest["ready_cases"]
    blocked = set(manifest.get("blocked_cases", []))

    results = []
    for name in ready:
        if name in blocked:
            raise SystemExit(f"internal error: blocked case in ready list: {name}")
        results.append(compare_case(name, cases_by_name[name], out_root))

    expected_dirs = set(ready)
    actual_dirs = {p.name for p in out_root.iterdir() if p.is_dir()}
    extra_dirs = sorted(actual_dirs - expected_dirs)
    missing_dirs = sorted(expected_dirs - actual_dirs)
    blocked_dirs = sorted(actual_dirs & blocked)

    total_out_bytes = sum(r.get("out_bytes", 0) for r in results)
    summary = {
        "run_id": run_id,
        "board_run_tree": str(run_root),
        "capture_tree": str(out_root),
        "ready_cases": len(ready),
        "blocked_cases_not_run": sorted(blocked),
        "cases_compared": len(results),
        "case_dirs_observed": len(actual_dirs),
        "extra_case_dirs": extra_dirs,
        "missing_case_dirs": missing_dirs,
        "blocked_case_dirs_present": blocked_dirs,
        "all_submit_ret_zero": all(r.get("submit_ret") == 0 for r in results),
        "all_capture_status_ok": all(r.get("status") == "OK" for r in results),
        "all_full_bo_exact": all(r.get("full_bo_exact") for r in results),
        "all_declared_region_exact": all(r.get("declared_region_exact") for r in results),
        "all_value_region_exact": all(r.get("value_region_exact") for r in results),
        "all_index_region_exact": all(
            r.get("index_region_exact") for r in results if r.get("index_en")
        ),
        "all_tolerance_pass": all(
            r.get("tolerance_pass")
            for r in results
            if r.get("tolerance_applicable")
        ),
        "total_out_bytes_read": total_out_bytes,
        "total_expected_bytes_compared": sum(r.get("expected_bytes", 0) for r in results),
        "problems": {
            r["case"]: r["problems"] for r in results if r.get("problems")
        },
        "cases": results,
    }

    (analysis_root / "comparison.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )

    lines: list[str] = []
    lines.append(f"PASS/FAIL COMPARISON run_id={run_id}")
    lines.append(f"capture_tree={out_root}")
    lines.append(
        f"ready_cases={len(ready)} compared={len(results)} "
        f"total_out_bytes_read={total_out_bytes}"
    )
    lines.append(
        "blocked_cases_not_run=" + ",".join(sorted(blocked)) + " (absent_on_board)"
    )
    lines.append("")
    header = (
        f"{'case':52s} {'submit':>6s} {'st':>2s} {'fullBO':>6s} "
        f"{'decl':>4s} {'value':>5s} {'index':>5s} {'tail':>4s} "
        f"{'exact':>5s} {'atol':>6s} {'maxdiff':>9s}"
    )
    lines.append(header)
    for r in results:
        tail = r.get("tail_nonzero_got_bytes")
        index_mismatch = (
            r.get("index_region_mismatch_bytes") if r.get("index_en") else "-"
        )
        tolerance_pass = (
            r.get("tolerance_pass") if r.get("tolerance_applicable") else "-"
        )
        max_diff = r.get("tolerance_max_abs_diff")
        max_diff_text = (
            f"{max_diff:.6g}"
            if r.get("tolerance_applicable") and max_diff is not None
            else "-"
        )
        lines.append(
            f"{r['case']:52s} "
            f"{str(r.get('submit_ret')):>6s} "
            f"{str(r.get('status')):>2s} "
            f"{str(r.get('full_bo_mismatch_bytes')):>6s} "
            f"{str(r.get('declared_region_mismatch_bytes')):>4s} "
            f"{str(r.get('value_region_mismatch_bytes')):>5s} "
            f"{str(index_mismatch):>5s} "
            f"{str(tail):>4s} "
            f"{str(r.get('value_region_exact')):>5s} "
            f"{str(tolerance_pass):>6s} "
            f"{max_diff_text:>9s}"
        )
    lines.append("")
    for r in results:
        lines.append(f"CASE {r['case']}")
        lines.append(
            f"  status={r.get('status')} submit_ret={r.get('submit_ret')} "
            f"out_bytes={r.get('out_bytes')} out_sha256={r.get('out_sha256')}"
        )
        lines.append(
            f"  expected_sha256={r.get('expected_sha256')} "
            f"out_bin_equals_expected_full={r.get('out_bin_equals_expected_full')} "
            f"out_bin_equals_out_init={r.get('out_bin_equals_out_init')}"
        )
        lines.append(
            f"  full_bo_mismatch_bytes={r.get('full_bo_mismatch_bytes')} "
            f"declared_region_mismatch_bytes={r.get('declared_region_mismatch_bytes')} "
            f"value_region_mismatch_bytes={r.get('value_region_mismatch_bytes')} "
            f"index_region_mismatch_bytes={r.get('index_region_mismatch_bytes')}"
        )
        lines.append(
            f"  value_bytes={r.get('value_bytes')} "
            f"index_offset={r.get('index_offset')} index_bytes={r.get('index_bytes')} "
            f"logical_output_bytes={r.get('logical_output_bytes')} "
            f"gap_nonzero_got={r.get('gap_nonzero_got_bytes')} "
            f"tail_nonzero_got={r.get('tail_nonzero_got_bytes')} "
            f"tail_nonzero_expected={r.get('tail_nonzero_expected_bytes')}"
        )
        if r.get("tolerance_applicable"):
            lines.append(
                f"  FP16 average tolerance atol={r.get('tolerance_atol')} "
                f"elements={r.get('tolerance_elements')} "
                f"max_abs_diff={r.get('tolerance_max_abs_diff')} "
                f"exceeds={r.get('tolerance_exceeds_count')} "
                f"pass={r.get('tolerance_pass')} "
                f"(exact byte mismatches still reported above)"
            )
        else:
            lines.append("  tolerance: not applicable (exact result required)")
        lines.append(f"  padding: {r.get('padding_note')}")
        lines.append(
            f"  durations_ns: total={r.get('durations', {}).get('total_ns')} "
            f"output_prep={r.get('durations', {}).get('output_prep_ns')} "
            f"submit={r.get('durations', {}).get('submit_ns')}"
        )
        for m in r.get("value_mismatches", []):
            lines.append(
                "  MISMATCH value offset={byte_offset} channel={channel} "
                "y={y} x={x} lane={lane} atom_tail={atom_tail} "
                "expected={expected} got={got} expected_hex={expected_hex} "
                "got_hex={got_hex}".format(**m)
            )
        for m in r.get("index_mismatches", []):
            lines.append(
                "  MISMATCH index offset={byte_offset} channel={channel} "
                "y={y} x={x} lane={lane} expected={expected} got={got} "
                "expected_hex={expected_hex} got_hex={got_hex}".format(**m)
            )
        if r.get("problems"):
            lines.append(f"  PROBLEMS: {r['problems']}")
        lines.append("")

    lines.append(
        "SUMMARY "
        f"submit_ret_zero={summary['all_submit_ret_zero']} "
        f"status_ok={summary['all_capture_status_ok']} "
        f"full_bo_exact={summary['all_full_bo_exact']} "
        f"declared_exact={summary['all_declared_region_exact']} "
        f"value_exact={summary['all_value_region_exact']} "
        f"index_exact={summary['all_index_region_exact']} "
        f"all_tolerance_pass={summary['all_tolerance_pass']}"
    )
    lines.append(
        f"TOTAL out bytes read={total_out_bytes} "
        f"expected bytes compared={summary['total_expected_bytes_compared']}"
    )
    (analysis_root / "comparison.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
