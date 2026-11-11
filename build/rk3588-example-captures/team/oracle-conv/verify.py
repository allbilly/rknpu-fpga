#!/usr/bin/env python3
"""Independent host-side conv / pooling / GEMM oracle verifier.

This tool intentionally does **not** import any family preparation helper and
does **not** use a preparation-time oracle as the thing being verified.  It
reads the raw bundle bytes, reconstructs the logical tensors from the layouts
documented by the source examples, recomputes the operation with a small
independent NumPy implementation, and only then compares that result with the
bundle's ``expected*.bin`` (and with a device output if one ever exists).

The comparison targets are always the *declared* logical value region:
  * conv-simple: whole raw output BO for FP16, meaningful prefix for INT8;
  * conv-fp16: logical NCHW arrays (expected.bin / expected_out*.bin);
  * conv-gemm-vendor: logical NCHW conv arrays or logical MxN GEMM arrays;
  * pooling: the C1HWC2 value region plus, when INDEX_EN, the uint16 index
    region at the declared offset.

No device is opened and no hardware result is fabricated.
"""

from __future__ import annotations

import argparse
import json
import platform
import hashlib
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
CAPTURES = HERE.parents[1]  # build/rk3588-example-captures
FAMILIES = ("conv-simple", "conv-fp16", "conv-gemm-vendor", "pooling")

LAYOUT_CONTRACTS = {
    "conv-simple": [
        "FP16 input is C1HWC2-like [c1][H][width_stride][c2] with c2=8; "
        "the READY cases have width_stride == in_w and the padded lanes are zero.",
        "FP16 weights use the source's kh-major chunks [oc_chunk][kh][kw][oc_lane]"
        "[aligned_in_c] (or the default [oc][kh][kw][aligned_in_c] for 1x1).",
        "FP16 output is unpack_output order [c1][out_width_stride][c2], with "
        "c2=8 for FP16 and c2=4 for FP32; READY cases have no output padding.",
        "INT8 input is [channel_group][x][y][16] bytes (value-0x80); INT8 weights "
        "are [oc_group][ic_group][x][y][oc_lane][ic_lane]; INT8 output is the "
        "meaningful prefix [channel_group][x][y][16] of the allocated BO.",
        "Valid-only geometry, stride 1, dilation 1; the INT8 depthwise case uses "
        "one input channel per output channel and groups=64.",
    ],
    "conv-fp16": [
        "Input is the donor CDMA_DC pack: [c1][H][width_stride][c2] with c2=8, "
        "c1=ceil(max(in_c, align_c)/c2); C1HWC2 atoms are FP16.",
        "Weights are one of default [oc][kh][kw][aligned_in_c], kh-major "
        "[kh][kw][oc_lane][aligned_in_c], pointwise-wide 32-channel atoms, or "
        "depthwise spatial [kh][kw][c2] with one weight per channel.",
        "Output BO is raw NC1HWC2 with c2=8 and out_width_stride rounded up to a "
        "multiple of 4 for spatial cases; expected.bin is the logical NCHW "
        "[1,out_c,out_h,out_w] slice, not the padded raw surface.",
        "Stride 1 and 2 are exercised; SAME padding is not: the padded case is an "
        "explicit 1-pixel zero frame around a valid 3x3. Groups 1 and 2 plus a "
        "3-channel depthwise case are exercised. No dilation is encoded.",
        "FP16 oracle contract: float64 accumulation of FP16 operands, one cast to "
        "FP16; a device may accumulate in a different order.",
    ],
    "conv-gemm-vendor": [
        "GEMM uses logical MxNxK; A is M rows of align_in FP16 (only the first K "
        "columns meaningful). B is packed as W[align_out,align_in], with "
        "W[:N,:K] = B.T, laid out [oc_block16][ic_block32][oc_lane16][ic_lane32]. "
        "Output is MxN logical FP32 and an Mxalign_out FP32 raw surface with row "
        "stride align_out (32 in these cases).",
        "conv_gemm/conv_legacy input is NHWC when use_nhwc, otherwise "
        "[c1][H][width_stride][c2] with c2=8; weights are default, kh-major, "
        "grouped-spatial block-16 reorder, or depthwise spatial depending on "
        "shape. conv.py uses 16x32 weight blocks for spatial kh-major.",
        "All READY conv cases use valid-only geometry, stride 1, dilation 1. "
        "Groups 1/2 and depthwise groups=3 are exercised; the grouped-spatial "
        "weight reorder is inverted explicitly in the verifier.",
        "Expected.bin is logical NCHW [1,out_c,out_h,out_w] FP16; raw output BOs "
        "pad channels and spatial rows and are not byte-compared here.",
    ],
    "pooling": [
        "Input and output are C1HWC2: 16-byte atoms, so atom channels are 8 for "
        "FP16/INT16 and 16 for INT8. The value region is "
        "[surf][out_h][out_w][atom].",
        "Kernel and stride are independent width/height fields; padding is "
        "top/right/bottom/left. No dilation is encoded.",
        "Average uses the full kernel window, i.e. include-padding denominator; "
        "the two USE_CNT probes therefore share the same expected values. "
        "Maximum/minimum use the encoded padding value (0xFC00 == -inf for the "
        "negative FP16 case).",
        "INDEX_EN writes uint16 positions at out_area*2*16 bytes in "
        "[surf][out_h][out_w][8] order, with (row<<3)|column. Only the clean "
        "window-local case is scored.",
        "Atom tails are -99 for the source three-channel case and zero "
        "elsewhere; the declared value region includes those tail lanes.",
    ],
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _align_up(x: int, align: int) -> int:
    return ((int(x) + int(align) - 1) // int(align)) * int(align)


def _ceil_div(x: int, y: int) -> int:
    return (int(x) + int(y) - 1) // int(y)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _source_evidence(manifest: dict[str, Any]) -> dict[str, Any]:
    keys = ("generator", "generated_utc", "source_revision", "source_examples",
            "seeds", "environment", "tool_versions", "host")
    return {k: manifest[k] for k in keys if k in manifest}


def _file_meta(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "sha256": _sha256(path),
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _dtype(name: str) -> np.dtype:
    return {
        "float16": np.dtype("<f2"),
        "float32": np.dtype("<f4"),
        "int8": np.dtype("i1"),
        "uint8": np.dtype("u1"),
        "int16": np.dtype("<i2"),
        "uint16": np.dtype("<u2"),
        "int32": np.dtype("<i4"),
    }[name]


def _read_array(path: Path, dtype: str, count: int | None = None) -> np.ndarray:
    blob = _read_bytes(path)
    if count is None:
        arr = np.frombuffer(blob, dtype=_dtype(dtype))
    else:
        arr = np.frombuffer(blob, dtype=_dtype(dtype), count=int(count))
    return np.array(arr, copy=True)


def _fp16_from_u16(raw_value: int) -> np.float16:
    return np.array([int(raw_value) & 0xFFFF], dtype=np.uint16).view(np.float16)[0]


def _stack(*parts: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for part in parts:
        if isinstance(part, dict):
            out.update(part)
    return out


def _compare(
    name: str,
    got: np.ndarray,
    expected: np.ndarray,
    *,
    atol: float = 0.0,
    rtol: float = 0.0,
    label: str = "",
) -> dict[str, Any]:
    """Compare two arrays and return a serialisable check record."""
    got = np.asarray(got)
    expected = np.asarray(expected)
    record: dict[str, Any] = {
        "name": name,
        "label": label,
        "got_shape": list(got.shape),
        "expected_shape": list(expected.shape),
        "got_dtype": str(got.dtype),
        "expected_dtype": str(expected.dtype),
        "status": "PASS",
        "max_abs_diff": 0.0,
        "mismatch_count": 0,
        "tolerance": {"atol": float(atol), "rtol": float(rtol)},
    }
    if got.shape != expected.shape:
        record["status"] = "FAIL"
        record["detail"] = "shape mismatch"
        return record
    if got.size == 0:
        return record

    if got.dtype.kind in "fc" or expected.dtype.kind in "fc":
        g = got.astype(np.float64)
        e = expected.astype(np.float64)
        finite_g = np.isfinite(g)
        finite_e = np.isfinite(e)
        both_finite = finite_g & finite_e
        nan_any = np.isnan(g) | np.isnan(e)
        inf_same = np.isinf(g) & np.isinf(e) & (np.sign(g) == np.sign(e))
        nonfinite_bad = (~both_finite) & (~inf_same)
        with np.errstate(invalid="ignore", over="ignore"):
            diff = np.abs(g - e)
            tol = float(atol) + float(rtol) * np.abs(e)
            bad = (diff > tol) | nonfinite_bad
        finite_diff = diff[both_finite]
        record["max_abs_diff"] = float(np.max(finite_diff)) if finite_diff.size else 0.0
        record["mismatch_count"] = int(np.count_nonzero(bad))
        record["non_identical_count"] = int(np.count_nonzero(
            (both_finite & (diff != 0.0)) | nonfinite_bad))
        record["nonfinite_got"] = int(np.count_nonzero(~finite_g))
        record["nonfinite_expected"] = int(np.count_nonzero(~finite_e))
        record["nan_count"] = int(np.count_nonzero(nan_any))
        record["inf_same_sign_count"] = int(np.count_nonzero(inf_same))
        record["status"] = "PASS" if not bool(np.any(bad)) else "FAIL"
        if np.any(bad):
            idx = np.unravel_index(int(np.argmax(bad)), bad.shape)
            record["first_failure_index"] = [int(i) for i in idx]
            record["first_failure_got"] = float(g[idx])
            record["first_failure_expected"] = float(e[idx])
    else:
        g = got.astype(np.int64)
        e = expected.astype(np.int64)
        diff = np.abs(g - e)
        bad = diff > float(atol)
        record["max_abs_diff"] = float(np.max(diff))
        record["mismatch_count"] = int(np.count_nonzero(bad))
        record["non_identical_count"] = int(np.count_nonzero(diff != 0))
        record["status"] = "PASS" if not bool(np.any(bad)) else "FAIL"
        if np.any(bad):
            idx = np.unravel_index(int(np.argmax(bad)), bad.shape)
            record["first_failure_index"] = [int(i) for i in idx]
            record["first_failure_got"] = int(g[idx])
            record["first_failure_expected"] = int(e[idx])
    return record


def _case(
    family: str,
    name: str,
    status: str,
    *,
    source: str | None = None,
    oracle_file: str | None = None,
    checks: list[dict[str, Any]] | None = None,
    notes: list[str] | None = None,
    blocker: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    checks = checks or []
    failed = any(c.get("status") == "FAIL" for c in checks)
    if status == "PASS" and failed:
        status = "FAIL"
    return {
        "case": name,
        "family": family,
        "status": status,
        "source_example": source,
        "oracle_file": oracle_file,
        "blocker": blocker,
        "detail": detail,
        "checks": checks,
        "notes": notes or [],
    }


def _buffer_map(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for buf in job.get("buffers", []) or []:
        if isinstance(buf, dict) and isinstance(buf.get("name"), str):
            out[buf["name"]] = buf
    return out


def _input_file(case_dir: Path, job: dict[str, Any], name: str,
                fallback: str | None = None) -> Path:
    buf = _buffer_map(job).get(name)
    if buf and isinstance(buf.get("input"), str):
        return case_dir / buf["input"]
    if fallback is None:
        fallback = f"{name}.bin"
    return case_dir / fallback


def _job_structure_check(case_dir: Path, job: dict[str, Any],
                         expected_case: str) -> dict[str, Any]:
    """Validate the CAPTURE_FORMAT job.json surface we depend on."""
    errors: list[str] = []
    case_name = job.get("case")
    if case_name not in (None, expected_case):
        errors.append(f"job.case={case_name!r} does not match {expected_case!r}")
    regcmd_path = case_dir / "regcmd.bin"
    if not regcmd_path.is_file():
        errors.append("regcmd.bin missing")
        total_words = 0
    else:
        total_words = regcmd_path.stat().st_size // 8
        if regcmd_path.stat().st_size % 8:
            errors.append("regcmd.bin size is not a multiple of 8")
    tasks = job.get("tasks") or []
    if not tasks:
        errors.append("job.tasks is empty")
    for ti, task in enumerate(tasks):
        off = task.get("regcmd_offset_words")
        words = task.get("regcmd_words")
        if not isinstance(off, int) or not isinstance(words, int):
            errors.append(f"task {ti}: non-integer offset/words")
            continue
        if off < 0 or words <= 0 or off + words > total_words:
            errors.append(
                f"task {ti}: range [{off},{off + words}) outside regcmd "
                f"({total_words} QWORDs)"
            )
    bufs = _buffer_map(job)
    for ti, patch in enumerate(job.get("patches") or []):
        idx = patch.get("regcmd_index")
        if not isinstance(idx, int) or idx < 0 or idx >= total_words:
            errors.append(f"patch {ti}: regcmd_index {idx!r} outside regcmd")
        if patch.get("buffer") not in bufs:
            errors.append(f"patch {ti}: unknown buffer {patch.get('buffer')!r}")
        if patch.get("kind") not in {"value32", "all32", "low32", "high32"}:
            errors.append(f"patch {ti}: unsupported kind {patch.get('kind')!r}")
    for bname, buf in bufs.items():
        size = buf.get("size")
        if not isinstance(size, int) or size < 0:
            errors.append(f"buffer {bname}: invalid size {size!r}")
        if buf.get("direction") not in {"in", "out", "inout"}:
            errors.append(f"buffer {bname}: invalid direction {buf.get('direction')!r}")
        inp = buf.get("input")
        if inp:
            ipath = case_dir / inp
            if not ipath.is_file():
                errors.append(f"buffer {bname}: input file {inp} missing")
            elif isinstance(size, int) and ipath.stat().st_size > size:
                errors.append(
                    f"buffer {bname}: input file {inp} is larger than declared BO size"
                )
    return {
        "name": "job_structure",
        "status": "PASS" if not errors else "FAIL",
        "detail": errors,
        "regcmd_qwords": total_words,
        "task_count": len(tasks),
        "buffer_count": len(bufs),
        "patch_count": len(job.get("patches") or []),
    }


def _check_bundle_hashes(case_dir: Path, entry: dict[str, Any]) -> dict[str, Any] | None:
    hashes = entry.get("hashes")
    if not hashes:
        return None
    mismatches: list[dict[str, str]] = []
    checked = 0
    for rel, want in hashes.items():
        path = case_dir / rel
        if not path.is_file():
            mismatches.append({"file": rel, "problem": "missing"})
            continue
        got = _sha256(path)
        checked += 1
        if got != want:
            mismatches.append({"file": rel, "problem": "sha256", "expected": want, "got": got})
    return {"checked": checked, "mismatches": mismatches}


# ===========================================================================
# conv-simple
# ===========================================================================

def _cs_fp16_params(shape: dict[str, Any]) -> dict[str, Any]:
    """Reimplementation of expt/conv_simple.py::_conv_params (READY subset)."""
    in_c = int(shape["in_c"])
    in_h = int(shape["in_h"])
    in_w = int(shape["in_w"])
    out_c = int(shape["out_c"])
    kh = int(shape["kh"])
    kw = int(shape["kw"])
    groups = int(shape["groups"])
    is_depthwise = groups == in_c == out_c
    is_spatial = kh != 1 or kw != 1
    out_h = in_h - kh + 1
    out_w = in_w - kw + 1

    if not is_depthwise and (groups > 1 or in_c > 4):
        align_c = 16
    else:
        align_c = max(8, min(1 << (max(1, in_c) - 1).bit_length(),
                             32 if is_depthwise else 16))
    align_out_c = max(16, _align_up(out_c, 16))
    width_stride = _align_up(in_w, max(1, _ceil_div(16, align_c)))
    out_atoms = max(1, out_h * out_w)
    out_width_stride = out_atoms if (not is_spatial and out_atoms < 4) else _align_up(out_atoms, 4)

    if in_c == 1:
        input_pack_c2 = 2
    elif is_depthwise or groups > 1 or in_c > 4:
        input_pack_c2 = 8
    else:
        input_pack_c2 = align_c
    use_nhwc = (not is_depthwise and not (groups > 1 and is_spatial)
                and input_pack_c2 // in_c == 2)
    return {
        "in_c": in_c, "in_h": in_h, "in_w": in_w, "out_c": out_c,
        "kh": kh, "kw": kw, "groups": groups,
        "is_depthwise": is_depthwise, "is_spatial": is_spatial,
        "out_h": out_h, "out_w": out_w,
        "align_c": align_c, "align_out_c": align_out_c,
        "width_stride": width_stride, "out_width_stride": out_width_stride,
        "input_pack_c2": input_pack_c2, "use_nhwc": use_nhwc,
    }


def _cs_decode_input_fp16(blob: bytes, p: dict[str, Any]) -> np.ndarray:
    in_c = p["in_c"]
    in_h = p["in_h"]
    in_w = p["in_w"]
    ws = p["width_stride"]
    if p["use_nhwc"]:
        need = in_h * ws * in_c
        arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
        return arr.reshape(in_h, ws, in_c)[:, :in_w, :].transpose(2, 0, 1).copy()
    c2 = p["input_pack_c2"]
    c1 = _ceil_div(in_c, c2)
    need = c1 * in_h * ws * c2
    arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
    full = arr.reshape(c1, in_h, ws, c2).transpose(0, 3, 1, 2)
    full = full.reshape(c1 * c2, in_h, ws)
    return full[:in_c, :, :in_w].copy()


def _cs_decode_weight_fp16(blob: bytes, p: dict[str, Any]) -> np.ndarray:
    out_c = p["out_c"]
    in_c = p["in_c"]
    kh = p["kh"]
    kw = p["kw"]
    groups = p["groups"]
    align_c = p["align_c"]
    is_dw = p["is_depthwise"]
    pointwise_wide = (groups == 1 and kh == 1 and kw == 1 and in_c >= 64)

    if pointwise_wide:
        aligned_in = max(32, _align_up(in_c, 32))
        w = np.zeros((out_c, in_c, 1, 1), dtype=np.float16)
        off = 0
        for oc0 in range(0, out_c, 16):
            cnt = min(16, out_c - oc0)
            chunk_elems = (aligned_in // 32) * cnt * 32
            chunk = np.frombuffer(blob[off * 2:(off + chunk_elems) * 2],
                                  dtype="<f2", count=chunk_elems)
            off += chunk_elems
            arr = chunk.reshape(aligned_in // 32, cnt, 32).transpose(1, 0, 2)
            arr = arr.reshape(cnt, aligned_in)
            w[oc0:oc0 + cnt, :, 0, 0] = arr[:, :in_c]
        return w

    # _pack_kh_major: 16-oc-major chunks, [kh][kw][oc_lane][aligned_in_c]
    aligned_in = align_c * _ceil_div(in_c, align_c)
    w = np.zeros((out_c, in_c, kh, kw), dtype=np.float16)
    off = 0
    for oc0 in range(0, out_c, 16):
        cnt = min(16, out_c - oc0)
        chunk_elems = kh * kw * cnt * aligned_in
        chunk = np.frombuffer(blob[off * 2:(off + chunk_elems) * 2],
                              dtype="<f2", count=chunk_elems)
        off += chunk_elems
        arr = chunk.reshape(kh, kw, cnt, aligned_in).transpose(2, 3, 0, 1)
        w[oc0:oc0 + cnt, :in_c, :, :] = arr[:, :in_c, :, :]
    return w


def _cs_conv_fp16(inp: np.ndarray, w: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    out_c = p["out_c"]
    in_c = p["in_c"]
    kh = p["kh"]
    kw = p["kw"]
    out_h = p["out_h"]
    out_w = p["out_w"]
    out = np.zeros((out_c, out_h, out_w), dtype=np.float64)
    inp64 = inp.astype(np.float64)
    w64 = w.astype(np.float64)
    for oc in range(out_c):
        for ic in range(in_c):
            for ky in range(kh):
                for kx in range(kw):
                    out[oc] += inp64[ic, ky:ky + out_h, kx:kx + out_w] * w64[oc, ic, ky, kx]
    return out


def _cs_pack_fp16_raw(logical: np.ndarray, out_c: int, out_width_stride: int,
                      c2: int, align_out_c: int, dtype: np.dtype) -> np.ndarray:
    c1 = align_out_c // c2
    raw = np.zeros(c1 * out_width_stride * c2, dtype=dtype)
    out_h, out_w = logical.shape[1], logical.shape[2]
    for oc in range(out_c):
        plane = oc // c2
        lane = oc % c2
        for y in range(out_h):
            base = plane * out_width_stride * c2 + (y * out_w) * c2 + lane
            raw[base:base + out_w * c2:c2] = logical[oc, y, :]
    return raw


def _cs_int8_input(blob: bytes, in_c: int, in_h: int, in_w: int) -> np.ndarray:
    inp = np.zeros((in_h, in_w, in_c), dtype=np.uint8)
    idx = 0
    for u in range(_ceil_div(in_c, 16)):
        for x in range(in_w):
            for y in range(in_h):
                for c in range(16):
                    val = blob[idx]
                    idx += 1
                    ic = u * 16 + c
                    if ic < in_c:
                        inp[y, x, ic] = (int(val) + 0x80) & 0xFF
    return inp


def _cs_int8_weight(blob: bytes, out_c: int, in_c: int, kh: int, kw: int,
                    depthwise: bool) -> np.ndarray:
    if depthwise:
        ic_padded = max(in_c, 16)
        ic_groups = 64
        w = np.zeros((in_c, kw, kh), dtype=np.uint8)
        n = 0
        for ii in range(_ceil_div(ic_padded, ic_groups)):
            for x in range(kw):
                for y in range(kh):
                    for _oi in range(1):
                        for ij in range(min(ic_padded, ic_groups)):
                            val = blob[n]
                            n += 1
                            ic = ii * ic_groups + ij
                            if ic < in_c:
                                w[ic, x, y] = (int(val) + 0x80) & 0xFF
        return w

    oc_aligned = _align_up(out_c, 2)
    ic_padded = max(in_c, 16)
    ic_groups = 32
    w = np.zeros((out_c, kw, kh, in_c), dtype=np.uint8)
    n = 0
    for oo in range(_ceil_div(oc_aligned, 32)):
        for ii in range(_ceil_div(ic_padded, 32)):
            for x in range(kw):
                for y in range(kh):
                    for oi in range(min(oc_aligned - oo * 32, 32)):
                        for ij in range(min(ic_padded, ic_groups)):
                            val = blob[n]
                            n += 1
                            oc = oo * 32 + oi
                            ic = ii * ic_groups + ij
                            if oc < out_c and ic < in_c:
                                w[oc, x, y, ic] = (int(val) + 0x80) & 0xFF
    return w


def _cs_int8_conv(inp: np.ndarray, w: np.ndarray, bias_log: np.ndarray,
                  out_c: int, out_h: int, out_w: int, kh: int, kw: int,
                  depthwise: bool) -> np.ndarray:
    out = np.zeros((out_h, out_w, out_c), dtype=np.int64)
    for oc in range(out_c):
        acc = np.full((out_h, out_w), int(bias_log[oc]), dtype=np.int64)
        for kx in range(kw):
            for ky in range(kh):
                if depthwise:
                    acc += (inp[ky:ky + out_h, kx:kx + out_w, oc].astype(np.int64)
                            * int(w[oc, kx, ky]))
                else:
                    for ic in range(inp.shape[2]):
                        acc += (inp[ky:ky + out_h, kx:kx + out_w, ic].astype(np.int64)
                                * int(w[oc, kx, ky, ic]))
        out[:, :, oc] = np.clip(np.rint(acc.astype(np.float64) / 255.0), 0, 255).astype(np.int64)
    return out


def _cs_int8_pack_raw(logical: np.ndarray) -> np.ndarray:
    out_h, out_w, out_c = logical.shape
    raw = np.zeros(out_c * out_h * out_w, dtype=np.uint8)
    for oc in range(out_c):
        g = oc // 16
        c = oc % 16
        for x in range(out_w):
            for y in range(out_h):
                idx = g * out_w * out_h * 16 + x * out_h * 16 + y * 16 + c
                raw[idx] = (int(logical[y, x, oc]) - 0x80) & 0xFF
    return raw


def verify_conv_simple(root: Path) -> dict[str, Any]:
    family = "conv-simple"
    manifest_path = root / family / "manifest.json"
    family_result: dict[str, Any] = {
        "family": family,
        "manifest": str(manifest_path),
        "status": "WAITING",
        "counts": {"ready": 0, "blocked": 0, "verified": 0, "pass": 0, "fail": 0,
                   "error": 0, "waiting": 0},
        "cases": [],
        "notes": [],
    }
    if not manifest_path.is_file():
        family_result["notes"].append("manifest.json not present; verifier is waiting")
        return family_result
    manifest = _read_json(manifest_path)
    entries = manifest.get("cases", [])
    family_result["manifest_file"] = _file_meta(manifest_path)
    family_result["manifest_generated_utc"] = manifest.get("generated_utc")
    family_result["source_evidence"] = _source_evidence(manifest)
    family_result["counts"]["ready"] = sum(1 for e in entries if e.get("status") == "READY")
    family_result["counts"]["blocked"] = sum(1 for e in entries if e.get("status") == "BLOCKED")
    family_result["status"] = "READY"

    for entry in entries:
        name = entry.get("case", "")
        case_dir = root / family / "cases" / name
        if entry.get("status") != "READY":
            family_result["cases"].append(_case(
                family, name, "BLOCKED",
                source=entry.get("source_example"),
                blocker=entry.get("blocker"),
                notes=["BLOCKED bundle: no scalar oracle is scored."],
            ))
            continue

        try:
            job_path = case_dir / "job.json"
            if not job_path.is_file():
                family_result["cases"].append(_case(
                    family, name, "WAITING", source=entry.get("source_example"),
                    notes=[f"{job_path.name} is not present; waiting for this bundle."],
                ))
                family_result["counts"]["waiting"] += 1
                continue
            job = _read_json(job_path)
            oracle = entry.get("oracle")
            if not oracle:
                raise ValueError("READY case has no oracle metadata")
            expected_name = oracle.get("file")
            expected_path = case_dir / expected_name
            if not expected_path.is_file():
                family_result["cases"].append(_case(
                    family, name, "WAITING", source=entry.get("source_example"),
                    oracle_file=expected_name,
                    notes=["expected oracle file is not present; waiting."],
                ))
                family_result["counts"]["waiting"] += 1
                continue

            shape = entry["shape"]
            out_dtype = entry["dtype"]["output"]
            checks: list[dict[str, Any]] = []
            notes: list[str] = []
            checks.append(_job_structure_check(case_dir, job, name))
            bufs = _buffer_map(job)
            integrity = _check_bundle_hashes(case_dir, entry)
            if integrity is not None:
                if integrity["mismatches"]:
                    notes.append(f"bundle hash mismatches: {integrity['mismatches']}")
                    checks.append({
                        "name": "bundle_sha256", "status": "FAIL",
                        "mismatch_count": len(integrity["mismatches"]),
                        "detail": integrity["mismatches"],
                    })
                else:
                    checks.append({"name": "bundle_sha256", "status": "PASS",
                                   "checked": integrity["checked"]})

            if name.startswith("conv_simple_fp16"):
                p = _cs_fp16_params(shape)
                inp = _cs_decode_input_fp16(
                    _read_bytes(_input_file(case_dir, job, "input")), p)
                w = _cs_decode_weight_fp16(
                    _read_bytes(_input_file(case_dir, job, "weight")), p)
                logical64 = _cs_conv_fp16(inp, w, p)
                dtype = _dtype(out_dtype)
                logical = logical64.astype(dtype)
                c2 = 8 if out_dtype == "float16" else 4
                got_raw = _cs_pack_fp16_raw(logical, p["out_c"], p["out_width_stride"],
                                            c2, p["align_out_c"], dtype)
                exp_raw = _read_array(expected_path, out_dtype,
                                       count=int(expected_path.stat().st_size // np.dtype(dtype).itemsize))
                checks.append({
                    "name": "expected_size",
                    "status": "PASS" if exp_raw.size == got_raw.size else "FAIL",
                    "computed_values": int(got_raw.size),
                    "file_values": int(exp_raw.size),
                })
                declared_out = int((bufs.get("out") or {}).get("size", got_raw.nbytes))
                checks.append({
                    "name": "output_buffer_size",
                    "status": "PASS" if declared_out == got_raw.nbytes else "FAIL",
                    "declared_bytes": declared_out, "computed_bytes": int(got_raw.nbytes),
                })
                logical_shape = [1, int(p["out_c"]), int(p["out_h"]), int(p["out_w"])]
                declared_shape = [int(v) for v in (oracle.get("logical_shape") or logical_shape)]
                checks.append({
                    "name": "logical_shape",
                    "status": "PASS" if logical_shape == declared_shape else "FAIL",
                    "computed": logical_shape, "declared": declared_shape,
                })
                atol = 0.12 if out_dtype == "float16" else 0.1
                checks.append(_compare("expected_raw", got_raw, exp_raw, atol=atol,
                                       rtol=1e-5 if out_dtype == "float32" else 0.0,
                                       label=oracle.get("raw_bo_layout", "")))
                notes.append(
                    f"layout={oracle.get('raw_bo_layout')}; "
                    f"logical={oracle.get('logical_layout')} {oracle.get('logical_shape')}; "
                    f"accumulate=float64 then cast {out_dtype}."
                )
            else:
                in_c, in_h, in_w = int(shape["in_c"]), int(shape["in_h"]), int(shape["in_w"])
                out_c = int(shape["out_c"])
                kh, kw = int(shape["kh"]), int(shape["kw"])
                depthwise = bool(entry.get("depthwise"))
                out_h, out_w = in_h - kh + 1, in_w - kw + 1
                inp = _cs_int8_input(
                    _read_bytes(_input_file(case_dir, job, "input")), in_c, in_h, in_w)
                w = _cs_int8_weight(
                    _read_bytes(_input_file(case_dir, job, "weight")),
                    out_c, in_c, kh, kw, depthwise)
                packed_bias = np.frombuffer(
                    _read_bytes(_input_file(case_dir, job, "bias")),
                    dtype="<i4", count=out_c).astype(np.int64)
                if depthwise:
                    sum_w = np.sum(w.astype(np.int64), axis=(1, 2))
                else:
                    sum_w = np.sum(w.astype(np.int64), axis=(1, 2, 3))
                bias_log = packed_bias - 128 * sum_w
                logical = _cs_int8_conv(inp, w, bias_log, out_c, out_h, out_w,
                                        kh, kw, depthwise)
                got_raw = _cs_int8_pack_raw(logical)
                exp_raw = np.frombuffer(_read_bytes(expected_path), dtype=np.uint8)
                checks.append({
                    "name": "expected_size",
                    "status": "PASS" if exp_raw.size == got_raw.size else "FAIL",
                    "computed_values": int(got_raw.size),
                    "file_values": int(exp_raw.size),
                })
                declared_out = int((bufs.get("out") or {}).get("size", got_raw.nbytes))
                checks.append({
                    "name": "output_buffer_size",
                    "status": "PASS" if declared_out >= got_raw.nbytes else "FAIL",
                    "declared_bytes": declared_out, "computed_bytes": int(got_raw.nbytes),
                })
                logical_shape = [1, out_h, out_w, out_c]
                declared_shape = [int(v) for v in (oracle.get("logical_shape") or logical_shape)]
                checks.append({
                    "name": "logical_shape",
                    "status": "PASS" if logical_shape == declared_shape else "FAIL",
                    "computed": logical_shape, "declared": declared_shape,
                })
                checks.append(_compare("expected_prefix", got_raw, exp_raw, atol=1,
                                       label=oracle.get("compare_region", "")))
                checks.append(_compare("expected_exact_prefix", got_raw, exp_raw, atol=0,
                                       label="byte-exact reference check"))
                notes.append(
                    "INT8 decode: raw input/weight bytes are (logical-0x80)&0xff; "
                    "packed bias is bias+128*sum(logical weights). "
                    f"compare prefix {len(exp_raw)} bytes of {oracle.get('output_buffer_bytes')} B BO."
                )

            status = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
            family_result["cases"].append(_case(
                family, name, status,
                source=entry.get("source_example"),
                oracle_file=expected_name,
                checks=checks,
                notes=notes + ([f"bundle integrity ok ({integrity['checked']} files)"]
                               if integrity and not integrity["mismatches"] else []),
            ))
            family_result["counts"]["verified"] += 1
            family_result["counts"]["pass" if status == "PASS" else "fail"] += 1
        except Exception as exc:  # noqa: BLE001 - report, never hide
            family_result["cases"].append(_case(
                family, name, "ERROR", source=entry.get("source_example"),
                notes=[f"{type(exc).__name__}: {exc}"],
                detail=traceback.format_exc(),
            ))
            family_result["counts"]["error"] += 1
    return family_result


# ===========================================================================
# conv-fp16
# ===========================================================================

def _cf_is_depthwise(in_c: int, out_c: int, groups: int) -> bool:
    return groups == in_c == out_c


def _cf_conv_align_c(in_c: int, groups: int, out_c: int) -> int:
    if not _cf_is_depthwise(in_c, out_c, groups) and groups == 1 and in_c > 1:
        return 16
    if not _cf_is_depthwise(in_c, out_c, groups) and in_c > 4:
        return 16
    return int(np.clip(1 << (max(1, in_c) - 1).bit_length(), 8, 32))


def _cf_pointwise_atom_groups(in_c: int) -> int:
    return _ceil_div(max(in_c, 8), 32)


def _cf_uses_pointwise_atom_layout(in_c: int, kh: int, kw: int, groups: int) -> bool:
    return groups == 1 and kh == 1 and kw == 1 and _cf_pointwise_atom_groups(in_c) > 1


def _cf_input_pack_c2(in_c: int, groups: int, out_c: int, align_c: int) -> int:
    if in_c == 1:
        return 2
    if not _cf_is_depthwise(in_c, out_c, groups) and groups == 1 and 1 < in_c <= 4:
        return 8
    if _cf_is_depthwise(in_c, out_c, groups) or groups > 1 or in_c > 4:
        return 8
    return align_c


def _cf_params(shape: dict[str, Any]) -> dict[str, Any]:
    """Reimplementation of conv_new_clean.py::_conv_params for the READY set."""
    in_c = int(shape["in_c"])
    in_h = int(shape["in_h"])
    in_w = int(shape["in_w"])
    out_c = int(shape["out_c"])
    kh = int(shape["kh"])
    kw = int(shape["kw"])
    groups = int(shape["groups"])
    stride = int(shape.get("stride", 1))
    is_dw = _cf_is_depthwise(in_c, out_c, groups)
    is_spatial = kh != 1 or kw != 1
    out_h = (in_h - kh) // stride + 1
    out_w = (in_w - kw) // stride + 1
    align_c = 32 if _cf_uses_pointwise_atom_layout(in_c, kh, kw, groups) else _cf_conv_align_c(in_c, groups, out_c)
    align_out_c = max(32, _align_up(out_c, 16))
    width_stride = _align_up(in_w, max(1, _ceil_div(16, align_c)))
    out_atoms = max(1, out_h * out_w)
    out_width_stride = out_atoms if not is_spatial else _align_up(out_atoms, 4)
    input_pack_c2 = _cf_input_pack_c2(in_c, groups, out_c, align_c)
    mesa_aligned_small = (not is_dw) and groups == 1 and 1 < in_c <= 4
    use_nhwc = (not mesa_aligned_small) and (not is_dw) and (in_c > 0 and input_pack_c2 // in_c == 2)
    return {
        "in_c": in_c, "in_h": in_h, "in_w": in_w, "out_c": out_c,
        "kh": kh, "kw": kw, "groups": groups, "stride": stride,
        "is_depthwise": is_dw, "is_spatial": is_spatial,
        "out_h": out_h, "out_w": out_w,
        "align_c": align_c, "align_out_c": align_out_c,
        "width_stride": width_stride, "out_width_stride": out_width_stride,
        "input_pack_c2": input_pack_c2, "use_nhwc": use_nhwc,
    }


def _cf_decode_input(blob: bytes, p: dict[str, Any]) -> np.ndarray:
    in_c = p["in_c"]
    in_h = p["in_h"]
    in_w = p["in_w"]
    ws = p["width_stride"]
    if p["use_nhwc"]:
        need = in_h * ws * in_c
        arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
        return arr.reshape(in_h, ws, in_c)[:, :in_w, :].transpose(2, 0, 1).copy()
    c2 = p["input_pack_c2"]
    c1 = _ceil_div(max(in_c, p["align_c"]), c2)
    need = c1 * in_h * ws * c2
    arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
    full = arr.reshape(c1, in_h, ws, c2).transpose(0, 3, 1, 2)
    full = full.reshape(c1 * c2, in_h, ws)
    return full[:in_c, :, :in_w].copy()


def _cf_choose_weight_layout(out_c: int, in_c: int, kh: int, kw: int,
                             align_c: int, groups: int) -> str:
    is_dw = _cf_is_depthwise(in_c, out_c, groups)
    if is_dw and out_c <= align_c and kh == kw:
        return "depthwise_spatial"
    if _cf_uses_pointwise_atom_layout(in_c, kh, kw, groups):
        return "pointwise_wide"
    multi_input_group = groups > 1 and in_c != groups
    if (kh != 1 or kw != 1) and not is_dw and not multi_input_group:
        return "kh_major"
    return "default"


def _cf_decode_weight(blob: bytes, p: dict[str, Any]) -> np.ndarray:
    out_c = p["out_c"]
    in_c = p["in_c"]
    kh = p["kh"]
    kw = p["kw"]
    groups = p["groups"]
    align_c = p["align_c"]
    layout = _cf_choose_weight_layout(out_c, in_c, kh, kw, align_c, groups)
    p["weight_layout"] = layout

    if layout == "depthwise_spatial":
        need = kh * kw * align_c
        arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
        arr = arr.reshape(kh, kw, align_c)
        w = np.zeros((out_c, kh, kw), dtype=np.float16)
        for oc in range(out_c):
            w[oc, :, :] = arr[:, :, oc]
        return w

    if layout == "pointwise_wide":
        aligned_in = max(32, _align_up(in_c, 32))
        aligned_out = _align_up(out_c, 16) if out_c >= 48 else out_c
        w = np.zeros((out_c, in_c, 1, 1), dtype=np.float16)
        off = 0
        for oc0 in range(0, aligned_out, 16):
            cnt = min(16, aligned_out - oc0)
            chunk_elems = (aligned_in // 32) * cnt * 32
            chunk = np.frombuffer(blob[off * 2:(off + chunk_elems) * 2],
                                  dtype="<f2", count=chunk_elems)
            off += chunk_elems
            arr = chunk.reshape(aligned_in // 32, cnt, 32).transpose(1, 0, 2)
            arr = arr.reshape(cnt, aligned_in)
            if oc0 < out_c:
                take = min(cnt, out_c - oc0)
                w[oc0:oc0 + take, :, 0, 0] = arr[:take, :in_c]
        return w

    aligned_in = align_c * _ceil_div(in_c, align_c)
    if layout == "kh_major":
        w = np.zeros((out_c, in_c, kh, kw), dtype=np.float16)
        off = 0
        for oc0 in range(0, out_c, 16):
            cnt = min(16, out_c - oc0)
            chunk_elems = kh * kw * cnt * aligned_in
            chunk = np.frombuffer(blob[off * 2:(off + chunk_elems) * 2],
                                  dtype="<f2", count=chunk_elems)
            off += chunk_elems
            arr = chunk.reshape(kh, kw, cnt, aligned_in).transpose(2, 3, 0, 1)
            w[oc0:oc0 + cnt, :in_c, :, :] = arr[:, :in_c, :, :]
        return w

    # default: [oc][kh][kw][aligned_in_c]
    need = out_c * kh * kw * aligned_in
    arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
    arr = arr.reshape(out_c, kh, kw, aligned_in)
    w = np.zeros((out_c, in_c, kh, kw), dtype=np.float16)
    for oc in range(out_c):
        w[oc, :, :, :] = arr[oc, :, :, :in_c].transpose(2, 0, 1)
    return w


def _cf_conv(inp: np.ndarray, w: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    in_c = p["in_c"]
    out_c = p["out_c"]
    groups = p["groups"]
    kh = p["kh"]
    kw = p["kw"]
    stride = p["stride"]
    out_h = p["out_h"]
    out_w = p["out_w"]
    out = np.zeros((out_c, out_h, out_w), dtype=np.float64)
    inp64 = inp.astype(np.float64)
    w64 = w.astype(np.float64)
    if p["is_depthwise"]:
        for oc in range(out_c):
            for ky in range(kh):
                for kx in range(kw):
                    out[oc] += inp64[oc, ky:ky + out_h * stride:stride,
                                     kx:kx + out_w * stride:stride] * w64[oc, ky, kx]
        return out

    in_per_group = in_c // groups
    out_per_group = out_c // groups
    for oc in range(out_c):
        g = oc // out_per_group
        ic_start = g * in_per_group
        for local_ic in range(in_per_group):
            ic = ic_start + local_ic
            w_ic = local_ic if w.shape[1] == in_per_group else ic
            for ky in range(kh):
                for kx in range(kw):
                    ys = ky
                    xs = kx
                    out[oc] += (inp64[ic, ys:ys + out_h * stride:stride,
                                      xs:xs + out_w * stride:stride]
                                * w64[oc, w_ic, ky, kx])
    return out


def _cf_expected_task_shape(case_shape: dict[str, Any], n_tasks: int,
                            task_meta: dict[str, Any]) -> dict[str, Any]:
    """Return per-task in_c/out_c/groups for grouped / split-OC tasks.

    Multi-task output-channel counts come from the task's provenance geometry
    audit (``weight_kernels``), not from the expected-oracle file size.
    """
    in_c = int(case_shape["in_c"])
    out_c = int(case_shape["out_c"])
    groups = int(case_shape["groups"])
    kh = int(case_shape["kh"])
    kw = int(case_shape["kw"])
    stride = int(case_shape.get("stride", 1))
    in_h = int(case_shape.get("effective_input_h", case_shape["in_h"]))
    in_w = int(case_shape.get("effective_input_w", case_shape["in_w"]))
    out_h = int(case_shape.get("out_h", in_h - kh + 1))
    out_w = int(case_shape.get("out_w", in_w - kw + 1))
    if n_tasks == 1:
        return {"in_c": in_c, "out_c": out_c, "groups": groups,
                "in_h": in_h, "in_w": in_w, "out_h": out_h, "out_w": out_w,
                "kh": kh, "kw": kw, "stride": stride}
    if groups > 1:
        return {"in_c": in_c // groups, "out_c": out_c // groups, "groups": 1,
                "in_h": in_h, "in_w": in_w, "out_h": out_h, "out_w": out_w,
                "kh": kh, "kw": kw, "stride": stride}
    # split-OC: derive the per-task output-channel count from the task's
    # provenance geometry audit, not from the expected oracle bytes.
    geom = task_meta.get("geometry_audit") or {}
    if "weight_kernels" not in geom:
        raise ValueError("multi-task split-OC case lacks geometry_audit.weight_kernels")
    return {"in_c": in_c, "out_c": int(geom["weight_kernels"]), "groups": 1,
            "in_h": in_h, "in_w": in_w, "out_h": out_h, "out_w": out_w,
            "kh": kh, "kw": kw, "stride": stride}


def verify_conv_fp16(root: Path) -> dict[str, Any]:
    family = "conv-fp16"
    manifest_path = root / family / "manifest.json"
    family_result: dict[str, Any] = {
        "family": family,
        "manifest": str(manifest_path),
        "status": "WAITING",
        "counts": {"ready": 0, "blocked": 0, "verified": 0, "pass": 0, "fail": 0,
                   "error": 0, "waiting": 0},
        "cases": [],
        "notes": [],
    }
    if not manifest_path.is_file():
        family_result["notes"].append("manifest.json not present; verifier is waiting")
        return family_result
    manifest = _read_json(manifest_path)
    entries = manifest.get("cases", [])
    family_result["manifest_file"] = _file_meta(manifest_path)
    family_result["manifest_generated_utc"] = manifest.get("generated_utc")
    family_result["source_evidence"] = _source_evidence(manifest)
    family_result["counts"]["ready"] = sum(1 for e in entries if e.get("status") == "READY")
    family_result["counts"]["blocked"] = sum(1 for e in entries if e.get("status") == "BLOCKED")
    family_result["status"] = "READY"

    for entry in entries:
        name = entry.get("case", "")
        case_dir = root / family / "cases" / name
        if entry.get("status") != "READY":
            family_result["cases"].append(_case(
                family, name, "BLOCKED", source=entry.get("source_example"),
                blocker=entry.get("blocker") or entry.get("reason"),
                notes=["BLOCKED bundle: no scalar oracle is scored."],
            ))
            continue

        try:
            job_path = case_dir / "job.json"
            if not job_path.is_file():
                family_result["cases"].append(_case(
                    family, name, "WAITING", source=entry.get("source_example"),
                    notes=[f"{job_path.name} is not present; waiting for this bundle."],
                ))
                family_result["counts"]["waiting"] += 1
                continue
            job = _read_json(job_path)
            prov_path = case_dir / "provenance.json"
            prov = _read_json(prov_path) if prov_path.is_file() else {}
            oracle = entry.get("oracle") or {}
            expected_files = oracle.get("expected_files") or (
                [oracle.get("file")] if oracle.get("file") else [])
            if not expected_files:
                raise ValueError("READY case has no expected file list")
            missing = [f for f in expected_files if not (case_dir / f).is_file()]
            if missing:
                family_result["cases"].append(_case(
                    family, name, "WAITING", source=entry.get("source_example"),
                    oracle_file=",".join(expected_files),
                    notes=[f"expected oracle files missing: {missing}; waiting."],
                ))
                family_result["counts"]["waiting"] += 1
                continue

            shape = entry["shape"]
            tasks_meta = prov.get("tasks") or []
            n_tasks = len(tasks_meta) if tasks_meta else len(job.get("tasks", []))
            if n_tasks == 0:
                n_tasks = 1
            checks: list[dict[str, Any]] = []
            notes: list[str] = []
            task_outputs: list[np.ndarray] = []
            checks.append(_job_structure_check(case_dir, job, name))
            bufs = _buffer_map(job)
            job_task_count = len(job.get("tasks") or [])
            if job_task_count != n_tasks:
                checks.append({
                    "name": "job_task_count", "status": "FAIL",
                    "declared": job_task_count, "provenance": n_tasks,
                })
            else:
                checks.append({"name": "job_task_count", "status": "PASS",
                               "count": n_tasks})

            for ti in range(n_tasks):
                meta = tasks_meta[ti] if ti < len(tasks_meta) else {}
                in_name = meta.get("input_buffer", "a" if n_tasks == 1 else f"a{ti}")
                w_name = meta.get("weight_buffer", "w" if n_tasks == 1 else f"w{ti}")
                out_name = meta.get("output_buffer", "out" if n_tasks == 1 else f"out{ti}")
                for buf_name in (in_name, w_name, out_name):
                    if buf_name not in bufs:
                        checks.append({
                            "name": f"task{ti}_buffer_{buf_name}",
                            "status": "FAIL",
                            "detail": "provenance task names a buffer absent from job.json",
                        })
                expected_out_name = oracle.get("expected_files", [None] * n_tasks)[ti] \
                    if len(oracle.get("expected_files", [])) >= n_tasks else None
                task_shape = _cf_expected_task_shape(shape, n_tasks, meta)
                p = _cf_params(task_shape)
                out_buf = bufs.get(out_name) or {}
                raw_out_bytes = (_ceil_div(p["align_out_c"], 8)
                                 * p["out_width_stride"] * 8 * 2)
                checks.append({
                    "name": f"task{ti}_output_surface_bytes",
                    "status": "PASS" if int(out_buf.get("size", raw_out_bytes)) >= raw_out_bytes
                    else "FAIL",
                    "declared_bytes": int(out_buf.get("size", raw_out_bytes)),
                    "computed_bytes": int(raw_out_bytes),
                    "align_out_c": p["align_out_c"],
                    "out_width_stride": p["out_width_stride"],
                })
                declared_out_h = int(shape.get("out_h", p["out_h"]))
                declared_out_w = int(shape.get("out_w", p["out_w"]))
                checks.append({
                    "name": f"task{ti}_out_shape",
                    "status": "PASS" if (p["out_h"], p["out_w"]) ==
                    (declared_out_h, declared_out_w) else "FAIL",
                    "computed": [p["out_h"], p["out_w"]],
                    "declared": [declared_out_h, declared_out_w],
                })
                geom = meta.get("geometry_audit") or {}
                geom_expected = {
                    "width_stride": p["width_stride"],
                    "in_h": p["in_h"],
                    "aligned_c": p["align_c"],
                    "real_c": p["in_c"],
                }
                if p["is_depthwise"]:
                    geom_expected["weight_kernels"] = 1
                else:
                    geom_expected["weight_kernels"] = p["out_c"]
                for field, got in geom_expected.items():
                    if field not in geom:
                        continue
                    want = geom[field]
                    same = want == got
                    checks.append({
                        "name": f"task{ti}_geometry_{field}",
                        "status": "PASS" if same else "FAIL",
                        "declared": want, "computed": got,
                    })
                    if not same:
                        notes.append(
                            f"task {ti}: provenance geometry {field}={want}, "
                            f"source layout gives {got}"
                        )
                inp = _cf_decode_input(_read_bytes(_input_file(case_dir, job, in_name)), p)
                w = _cf_decode_weight(_read_bytes(_input_file(case_dir, job, w_name)), p)
                out64 = _cf_conv(inp, w, p)
                out_dtype_name = str(oracle.get("dtype", "float16"))
                with np.errstate(over="ignore", invalid="ignore"):
                    out = out64.astype(_dtype(out_dtype_name))
                task_outputs.append(out)
                if not np.all(np.isfinite(out)):
                    notes.append(
                        f"task {ti}: {int(np.count_nonzero(~np.isfinite(out)))} "
                        "non-finite FP16 values (float64->FP16 overflow); compared "
                        "sign-exactly, not as special-value policy evidence."
                    )

                if expected_out_name:
                    exp = _read_array(case_dir / expected_out_name, out_dtype_name)
                    want = p["out_c"] * p["out_h"] * p["out_w"]
                    checks.append({
                        "name": f"task{ti}_expected_size",
                        "status": "PASS" if exp.size == want else "FAIL",
                        "expected_values": want, "file_values": int(exp.size),
                    })
                    if exp.size != want:
                        notes.append(
                            f"task {ti}: expected file has {exp.size} values, "
                            f"declared logical region is {want}"
                        )
                    checks.append(_compare(
                        f"task{ti}_{expected_out_name}", out.reshape(-1), exp[:want],
                        atol=float(oracle.get("tolerance_atol", 0.2)),
                        label=oracle.get("layout", ""),
                    ))
                notes.append(
                    f"task {ti}: buffers {in_name}/{w_name}/{out_name}, "
                    f"weight layout {p.get('weight_layout')}, input "
                    f"{'NHWC' if p['use_nhwc'] else 'C1HWC2'}, "
                    f"align_c={p['align_c']}, out_width_stride={p['out_width_stride']}, "
                    f"groups={p['groups']}, stride={p['stride']}."
                )

            if oracle.get("combined_expected"):
                combined = np.concatenate(task_outputs, axis=0)
                exp_comb = _read_array(case_dir / oracle["combined_expected"],
                                       str(oracle.get("dtype", "float16")))
                checks.append(_compare("expected_combined", combined.reshape(-1),
                                       exp_comb, atol=float(oracle.get("tolerance_atol", 0.2)),
                                       label="full logical NCHW output"))
                notes.append(
                    "combined output = channel-order concatenation of per-task "
                    f"{[int(t.shape[0]) for t in task_outputs]} channel tiles."
                )

            status = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
            oracle_label = list(expected_files)
            if oracle.get("combined_expected"):
                oracle_label.append(str(oracle["combined_expected"]))
            family_result["cases"].append(_case(
                family, name, status, source=entry.get("source_example"),
                oracle_file=",".join(oracle_label), checks=checks, notes=notes,
            ))
            family_result["counts"]["verified"] += 1
            family_result["counts"]["pass" if status == "PASS" else "fail"] += 1
        except Exception as exc:  # noqa: BLE001
            family_result["cases"].append(_case(
                family, name, "ERROR", source=entry.get("source_example"),
                notes=[f"{type(exc).__name__}: {exc}"],
                detail=traceback.format_exc(),
            ))
            family_result["counts"]["error"] += 1
    return family_result


# ===========================================================================
# conv-gemm-vendor
# ===========================================================================

def _gm_gemm_layout(m: int, n: int, k: int) -> tuple[int, int, int]:
    aligned_k = max(32, _align_up(k, 32))
    align_out = max(32, _align_up(n, 32))
    align_in = max(aligned_k, align_out)
    eff_k = align_in if align_in != aligned_k else k
    return align_in, align_out, eff_k


def _gm_conv_params(shape: dict[str, Any], style: str) -> dict[str, Any]:
    in_c = int(shape["in_c"])
    in_h = int(shape["in_h"])
    in_w = int(shape["in_w"])
    out_c = int(shape["out_c"])
    kh = int(shape["kh"])
    kw = int(shape["kw"])
    groups = int(shape["groups"])
    is_dw = groups == in_c == out_c
    is_spatial = kh != 1 or kw != 1
    out_h = in_h - kh + 1
    out_w = in_w - kw + 1
    if not is_dw and (groups > 1 or in_c > 4):
        align_c = 16
    else:
        align_c = max(8, min(1 << (max(1, in_c) - 1).bit_length(),
                             32 if is_dw else 16))
    if style == "conv.py":
        align_out_c = max(32 if groups == 1 and kh == 1 and kw == 1 and in_c >= 64 else 16,
                          _align_up(out_c, 16))
    else:
        align_out_c = max(16, _align_up(out_c, 16))
    width_stride = _align_up(in_w, max(1, _ceil_div(16, align_c)))
    out_atoms = max(1, out_h * out_w)
    out_width_stride = out_atoms if (not is_spatial and out_atoms < 4) else _align_up(out_atoms, 4)
    if in_c == 1:
        input_pack_c2 = 2
    elif is_dw or groups > 1 or in_c > 4:
        input_pack_c2 = 8
    else:
        input_pack_c2 = align_c
    if style == "conv.py":
        use_nhwc = (not is_dw and not (groups > 1 and is_spatial)
                    and in_c < input_pack_c2)
    else:
        should_nhwc = (in_c > 0 and (input_pack_c2 // in_c == 2
                                     or (in_c == 2 and input_pack_c2 // in_c == 4)))
        use_nhwc = (not is_dw and not (groups > 1 and is_spatial) and should_nhwc)
    grouped_spatial = ((kh != 1 or kw != 1) and groups > 1
                       and in_c != groups and not is_dw)
    return {
        "in_c": in_c, "in_h": in_h, "in_w": in_w, "out_c": out_c,
        "kh": kh, "kw": kw, "groups": groups,
        "is_depthwise": is_dw, "is_spatial": is_spatial,
        "out_h": out_h, "out_w": out_w,
        "align_c": align_c, "align_out_c": align_out_c,
        "width_stride": width_stride, "out_width_stride": out_width_stride,
        "input_pack_c2": input_pack_c2, "use_nhwc": use_nhwc,
        "grouped_spatial": grouped_spatial,
    }


def _gm_decode_input(blob: bytes, p: dict[str, Any], style: str) -> np.ndarray:
    in_c, in_h, in_w, ws = p["in_c"], p["in_h"], p["in_w"], p["width_stride"]
    if p["use_nhwc"]:
        need = in_h * ws * in_c
        arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
        return arr.reshape(in_h, ws, in_c)[:, :in_w, :].transpose(2, 0, 1).copy()
    c2 = p["input_pack_c2"]
    c1 = _ceil_div(in_c, c2)
    need = c1 * in_h * ws * c2
    arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
    full = arr.reshape(c1, in_h, ws, c2).transpose(0, 3, 1, 2)
    full = full.reshape(c1 * c2, in_h, ws)
    return full[:in_c, :, :in_w].copy()


def _gm_reorder_grouped_spatial(weight_full: np.ndarray) -> np.ndarray:
    """Exact copy of conv_gemm/conv_legacy _reorder_grouped_spatial_weights_block16."""
    out_c, in_c, kh, kw = weight_full.shape
    block_size = 16
    kernel_hw = kh * kw
    reordered = np.empty_like(weight_full)
    for block_start in range(0, out_c, block_size):
        block_end = min(block_start + block_size, out_c)
        block_channels = block_end - block_start
        block = weight_full[block_start:block_end]
        pack_order = block.transpose(2, 3, 0, 1).reshape(block_channels, kernel_hw, in_c)
        reordered[block_start:block_end] = pack_order.transpose(0, 2, 1).reshape(
            block_channels, in_c, kh, kw)
    return reordered


def _gm_invert_grouped_reorder(reordered: np.ndarray) -> np.ndarray:
    out_c, in_c, kh, kw = reordered.shape
    index = np.arange(out_c * in_c * kh * kw, dtype=np.int64).reshape(out_c, in_c, kh, kw)
    perm = _gm_reorder_grouped_spatial(index)
    original_flat = np.empty(out_c * in_c * kh * kw, dtype=np.float16)
    original_flat[perm.ravel()] = reordered.ravel()
    return original_flat.reshape(out_c, in_c, kh, kw)


def _gm_decode_weight(blob: bytes, p: dict[str, Any], style: str) -> np.ndarray:
    out_c, in_c, kh, kw = p["out_c"], p["in_c"], p["kh"], p["kw"]
    align_c, groups = p["align_c"], p["groups"]
    is_dw = p["is_depthwise"]
    grouped_spatial = p["grouped_spatial"]

    if style == "conv.py":
        pointwise_wide = (groups == 1 and kh == 1 and kw == 1 and in_c >= 64)
        if pointwise_wide:
            aligned_out = max(32, _align_up(out_c, 16))
            w = np.zeros((out_c, in_c, 1, 1), dtype=np.float16)
            off = 0
            for oc0 in range(0, aligned_out, 16):
                oc_cnt = min(16, aligned_out - oc0)
                for ic0 in range(0, in_c, 32):
                    ic_cnt = min(32, in_c - ic0)
                    chunk_elems = oc_cnt * ic_cnt
                    chunk = np.frombuffer(blob[off * 2:(off + chunk_elems) * 2],
                                          dtype="<f2", count=chunk_elems)
                    off += chunk_elems
                    arr = chunk.reshape(oc_cnt, ic_cnt)
                    take_oc = min(oc_cnt, max(0, out_c - oc0))
                    if take_oc > 0:
                        w[oc0:oc0 + take_oc, ic0:ic0 + ic_cnt, 0, 0] = arr[:take_oc]
            return w
        # conv.py spatial kh_major: [oc_block16][ic_block32][y][x]
        # [oc_lane][ic_lane], with the final OC/IC block possibly partial.
        aligned_in = align_c * _ceil_div(in_c, align_c)
        if kh != 1 or kw != 1:
            w = np.zeros((out_c, in_c, kh, kw), dtype=np.float16)
            off = 0
            for oc0 in range(0, out_c, 16):
                oc_cnt = min(16, out_c - oc0)
                for ic0 in range(0, aligned_in, 32):
                    ic_cnt = min(32, aligned_in - ic0)
                    for y in range(kh):
                        for x in range(kw):
                            chunk_elems = oc_cnt * ic_cnt
                            chunk = np.frombuffer(
                                blob[off * 2:(off + chunk_elems) * 2],
                                dtype="<f2", count=chunk_elems)
                            off += chunk_elems
                            arr = chunk.reshape(oc_cnt, ic_cnt)
                            take_ic = max(0, min(ic_cnt, in_c - ic0))
                            if take_ic:
                                w[oc0:oc0 + oc_cnt, ic0:ic0 + take_ic, y, x] = \
                                    arr[:, :take_ic]
            return w
        # conv.py compact 1x1 kh_major branch
        aligned_in = align_c * _ceil_div(in_c, align_c)
        need = out_c * aligned_in
        arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
        arr = arr.reshape(out_c, 1, 1, aligned_in)
        return arr[:, :in_c, 0, 0].transpose(0, 1).reshape(out_c, in_c, 1, 1)

    # conv_gemm / conv_legacy
    if is_dw and (kh != 1 or kw != 1):
        blocks = _ceil_div(out_c, align_c)
        need = blocks * kh * kw * align_c
        arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
        arr = arr.reshape(blocks, kh, kw, align_c)
        w = np.zeros((out_c, kh, kw), dtype=np.float16)
        for oc in range(out_c):
            b = oc // align_c
            lane = oc % align_c
            w[oc, :, :] = arr[b, :, :, lane]
        return w

    aligned_in = align_c * _ceil_div(in_c, align_c)
    if grouped_spatial:
        need = out_c * kh * kw * aligned_in
        arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
        reordered = arr.reshape(out_c, kh, kw, aligned_in)[:, :, :, :in_c]
        reordered = reordered.transpose(0, 3, 1, 2).copy()
        return _gm_invert_grouped_reorder(reordered)

    multi_input_group = groups > 1 and in_c != groups
    kh_major = ((kh != 1 or kw != 1) and not is_dw and not multi_input_group)
    if kh_major:
        w = np.zeros((out_c, in_c, kh, kw), dtype=np.float16)
        off = 0
        for oc0 in range(0, out_c, 16):
            cnt = min(16, out_c - oc0)
            chunk_elems = kh * kw * cnt * aligned_in
            chunk = np.frombuffer(blob[off * 2:(off + chunk_elems) * 2],
                                  dtype="<f2", count=chunk_elems)
            off += chunk_elems
            arr = chunk.reshape(kh, kw, cnt, aligned_in).transpose(2, 3, 0, 1)
            w[oc0:oc0 + cnt, :in_c, :, :] = arr[:, :in_c, :, :]
        return w

    need = out_c * kh * kw * aligned_in
    arr = np.frombuffer(blob[: need * 2], dtype="<f2", count=need)
    arr = arr.reshape(out_c, kh, kw, aligned_in)
    w = np.zeros((out_c, in_c, kh, kw), dtype=np.float16)
    for oc in range(out_c):
        w[oc, :, :, :] = arr[oc, :, :, :in_c].transpose(2, 0, 1)
    return w


def _gm_conv(inp: np.ndarray, w: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    in_c, out_c = p["in_c"], p["out_c"]
    groups, kh, kw = p["groups"], p["kh"], p["kw"]
    out_h, out_w = p["out_h"], p["out_w"]
    out = np.zeros((out_c, out_h, out_w), dtype=np.float64)
    inp64 = inp.astype(np.float64)
    w64 = w.astype(np.float64)
    if p["is_depthwise"]:
        for oc in range(out_c):
            for ky in range(kh):
                for kx in range(kw):
                    out[oc] += inp64[oc, ky:ky + out_h, kx:kx + out_w] * w64[oc, ky, kx]
        return out
    in_per_group = in_c // groups
    out_per_group = out_c // groups
    for oc in range(out_c):
        g = oc // out_per_group
        for local_ic in range(in_per_group):
            ic = g * in_per_group + local_ic
            w_ic = local_ic if w.shape[1] == in_per_group else ic
            for ky in range(kh):
                for kx in range(kw):
                    out[oc] += (inp64[ic, ky:ky + out_h, kx:kx + out_w]
                                * w64[oc, w_ic, ky, kx])
    return out


def _gm_gemm_case(case_dir: Path, entry: dict[str, Any],
                  job: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    layout = entry["gemm_layout"]
    m, n, k = int(layout["m"]), int(layout["n"]), int(layout["k"])
    align_in, align_out, _eff_k = _gm_gemm_layout(m, n, k)
    for field, got in (("align_in", align_in), ("align_out", align_out)):
        want = int(layout[field])
        if got != want:
            notes.append(f"declared gemm_layout.{field}={want}, source formula gives {got}")
        checks.append({"name": f"layout_{field}", "status": "PASS" if got == want else "FAIL",
                       "declared": want, "computed": got})

    in_blob = _read_bytes(_input_file(case_dir, job, "input"))
    wt_blob = _read_bytes(_input_file(case_dir, job, "weight"))
    a = np.frombuffer(in_blob[: m * align_in * 2], dtype="<f2",
                      count=m * align_in).reshape(m, align_in)[:, :k].astype(np.float16)
    wt = np.frombuffer(wt_blob[: align_out * align_in * 2], dtype="<f2",
                       count=align_out * align_in)
    wmat = wt.reshape(align_out // 16, align_in // 32, 16, 32)
    wmat = wmat.transpose(0, 2, 1, 3).reshape(align_out, align_in)
    b = wmat[:n, :k].T.astype(np.float16)
    expected = (a.astype(np.float64) @ b.astype(np.float64)).astype(np.float32)
    exp = _read_array(case_dir / "expected.bin", "float32", count=m * n).reshape(m, n)
    exp_size = (case_dir / "expected.bin").stat().st_size
    checks.append({
        "name": "expected_size",
        "status": "PASS" if exp_size == m * n * 4 else "FAIL",
        "expected_bytes": m * n * 4, "file_bytes": int(exp_size),
    })
    checks.append(_compare("expected_logical", expected, exp,
                           atol=float(entry["oracle"].get("tolerance_abs", 0.1)),
                           label="logical MxN GEMM"))
    notes.append(
        f"GEMM M={m} N={n} K={k}; align_in={align_in} (rows of A padded to K), "
        f"align_out={align_out} (output row stride {align_out} FP32); "
        "weight raw is [oc_block16][ic_block32][oc_lane16][ic_lane32] of W[n,k]."
    )

    surface_path = case_dir / "expected_surface.bin"
    if surface_path.is_file():
        surface = np.zeros((m, align_out), dtype=np.float32)
        surface[:, :n] = expected
        surf_blob = _read_bytes(surface_path)
        surf_flat = np.frombuffer(surf_blob[: m * align_out * 4], dtype="<f4",
                                  count=m * align_out)
        checks.append(_compare("expected_surface", surface.reshape(-1), surf_flat,
                               atol=float(entry["oracle"].get("tolerance_abs", 0.1)),
                               label="raw Mx align_out FP32 surface"))
        tail = surf_blob[m * align_out * 4:]
        if any(tail):
            notes.append("expected_surface.bin has nonzero bytes after the declared surface")
    return checks, notes


def verify_conv_gemm_vendor(root: Path) -> dict[str, Any]:
    family = "conv-gemm-vendor"
    manifest_path = root / family / "manifest.json"
    family_result: dict[str, Any] = {
        "family": family,
        "manifest": str(manifest_path),
        "status": "WAITING",
        "counts": {"ready": 0, "blocked": 0, "verified": 0, "pass": 0, "fail": 0,
                   "error": 0, "waiting": 0},
        "cases": [],
        "notes": [],
    }
    if not manifest_path.is_file():
        family_result["notes"].append("manifest.json not present; verifier is waiting")
        return family_result
    manifest = _read_json(manifest_path)
    entries = manifest.get("cases", [])
    family_result["manifest_file"] = _file_meta(manifest_path)
    family_result["manifest_generated_utc"] = manifest.get("generated_utc")
    family_result["source_evidence"] = _source_evidence(manifest)
    family_result["counts"]["ready"] = sum(1 for e in entries if e.get("status") == "READY")
    family_result["counts"]["blocked"] = sum(1 for e in entries if e.get("status") == "BLOCKED")
    family_result["status"] = "READY"

    for entry in entries:
        name = entry.get("case", "")
        case_dir = root / family / "cases" / name
        if entry.get("status") != "READY":
            family_result["cases"].append(_case(
                family, name, "BLOCKED", source=entry.get("source_example"),
                blocker=entry.get("blocked_reason"),
                notes=["BLOCKED bundle: no scalar oracle is scored."],
            ))
            continue

        try:
            job_path = case_dir / "job.json"
            if not job_path.is_file():
                family_result["cases"].append(_case(
                    family, name, "WAITING", source=entry.get("source_example"),
                    notes=[f"{job_path.name} is not present; waiting for this bundle."],
                ))
                family_result["counts"]["waiting"] += 1
                continue
            job = _read_json(job_path)
            checks: list[dict[str, Any]] = []
            notes: list[str] = []
            checks.append(_job_structure_check(case_dir, job, name))
            declared_tasks = len(entry.get("rocket_tasks") or [])
            actual_tasks = len(job.get("tasks") or [])
            checks.append({
                "name": "job_task_count",
                "status": "PASS" if declared_tasks == actual_tasks else "FAIL",
                "declared": declared_tasks, "job": actual_tasks,
            })
            integrity = _check_bundle_hashes(case_dir, entry)
            if integrity is not None:
                if integrity["mismatches"]:
                    checks.append({"name": "bundle_sha256", "status": "FAIL",
                                   "mismatch_count": len(integrity["mismatches"]),
                                   "detail": integrity["mismatches"]})
                    notes.append(f"bundle hash mismatches: {integrity['mismatches']}")
                else:
                    checks.append({"name": "bundle_sha256", "status": "PASS",
                                   "checked": integrity["checked"]})

            if name.startswith("gemm_"):
                c, n = _gm_gemm_case(case_dir, entry, job)
                checks.extend(c)
                notes.extend(n)
                oracle_file = "expected.bin,expected_surface.bin"
            else:
                shape = entry["source_shape_parameters"]
                style = Path(entry["source_example"]).name
                p = _gm_conv_params(shape, style)
                declared = entry.get("conv_layout") or {}
                for field in ("align_c", "align_out_c", "width_stride",
                              "out_width_stride", "use_nhwc", "grouped_spatial"):
                    if field not in declared:
                        continue
                    got = p[field]
                    want = declared[field]
                    same = got == want
                    checks.append({"name": f"layout_{field}",
                                   "status": "PASS" if same else "FAIL",
                                   "declared": want, "computed": got})
                    if not same:
                        notes.append(f"declared conv_layout.{field}={want}, source gives {got}")

                inp = _gm_decode_input(
                    _read_bytes(_input_file(case_dir, job, "input")), p, style)
                w = _gm_decode_weight(
                    _read_bytes(_input_file(case_dir, job, "weight")), p, style)
                out64 = _gm_conv(inp, w, p)
                exp_dtype_name = str(entry.get("expected_oracle", {}).get("dtype", "float16"))
                with np.errstate(over="ignore", invalid="ignore"):
                    out = out64.astype(_dtype(exp_dtype_name))
                if not np.all(np.isfinite(out)):
                    notes.append(
                        f"{int(np.count_nonzero(~np.isfinite(out)))} non-finite "
                        "output values (float64 cast overflow); compared "
                        "sign-exactly, not as special-value policy evidence."
                    )
                exp = _read_array(case_dir / "expected.bin", exp_dtype_name)
                want = p["out_c"] * p["out_h"] * p["out_w"]
                checks.append({
                    "name": "expected_size",
                    "status": "PASS" if exp.size == want else "FAIL",
                    "expected_values": want, "file_values": int(exp.size),
                })
                logical_shape = [1, p["out_c"], p["out_h"], p["out_w"]]
                declared_shape = [int(v) for v in
                                  (entry.get("expected_oracle", {}).get("shape") or logical_shape)]
                checks.append({
                    "name": "logical_shape",
                    "status": "PASS" if logical_shape == declared_shape else "FAIL",
                    "computed": logical_shape, "declared": declared_shape,
                })
                checks.append(_compare("expected_logical", out.reshape(-1), exp[:want],
                                       atol=float(entry["oracle"].get("tolerance_abs", 0.2)),
                                       label=entry["oracle"].get("layout", "")))
                notes.append(
                    f"conv source={style}; input={'NHWC' if p['use_nhwc'] else 'C1HWC2'}; "
                    f"groups={p['groups']} depthwise={p['is_depthwise']} "
                    f"grouped_spatial={p['grouped_spatial']}; "
                    f"out_width_stride={p['out_width_stride']}; repeat_submissions="
                    f"{entry.get('repeat_submissions', 1)}."
                )
                oracle_file = "expected.bin"

            status = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
            family_result["cases"].append(_case(
                family, name, status, source=entry.get("source_example"),
                oracle_file=oracle_file, checks=checks, notes=notes,
            ))
            family_result["counts"]["verified"] += 1
            family_result["counts"]["pass" if status == "PASS" else "fail"] += 1
        except Exception as exc:  # noqa: BLE001
            family_result["cases"].append(_case(
                family, name, "ERROR", source=entry.get("source_example"),
                notes=[f"{type(exc).__name__}: {exc}"],
                detail=traceback.format_exc(),
            ))
            family_result["counts"]["error"] += 1
    return family_result


# ===========================================================================
# pooling
# ===========================================================================

def _pool_decode_input(blob: bytes, dtype_name: str, channels: int,
                       in_h: int, in_w: int) -> np.ndarray:
    dt = _dtype(dtype_name)
    itemsize = dt.itemsize
    atom = 16 // itemsize
    surfaces = _ceil_div(channels, atom)
    need = surfaces * in_h * in_w * atom
    arr = np.frombuffer(blob[: need * itemsize], dtype=dt, count=need)
    arr = arr.reshape(surfaces, in_h, in_w, atom)
    out = np.empty((in_h, in_w, channels), dtype=dt)
    for c in range(channels):
        out[:, :, c] = arr[c // atom, :, :, c % atom]
    return out


def _pool_padding_value(ppu: dict[str, Any], dtype_name: str) -> Any:
    raw0 = int(ppu.get("padding_value", [0, 0])[0])
    if dtype_name == "float16":
        return _fp16_from_u16(raw0)
    if dtype_name == "float32":
        return np.array([raw0], dtype=np.uint32).view(np.float32)[0]
    return raw0


def _pool_compute(src: np.ndarray, ppu: dict[str, Any]) -> tuple[np.ndarray, np.ndarray | None]:
    dtype_name = ppu["dtype"]
    dt = _dtype(dtype_name)
    kh, kw = (int(v) for v in ppu["kernel"])
    sy, sx = (int(v) for v in ppu["stride"])
    pt, pr, pb, pl = (int(v) for v in ppu.get("padding", [0, 0, 0, 0]))
    method = ppu["method"]
    index_en = bool(ppu.get("index_en", False))

    if method == "average":
        pad_value: Any = 0
    else:
        pad_value = _pool_padding_value(ppu, dtype_name)
    padded = np.pad(src, ((pt, pb), (pl, pr), (0, 0)), constant_values=pad_value)
    out_h = (padded.shape[0] - kh) // sy + 1
    out_w = (padded.shape[1] - kw) // sx + 1
    channels = src.shape[2]
    out = np.empty((out_h, out_w, channels), dtype=dt)
    positions = np.empty((out_h, out_w, channels), dtype=np.uint16) if index_en else None

    for y in range(out_h):
        for x in range(out_w):
            window = padded[y * sy:y * sy + kh, x * sx:x * sx + kw, :]
            if method == "maximum":
                out[y, x] = np.max(window, axis=(0, 1))
            elif method == "minimum":
                out[y, x] = np.min(window, axis=(0, 1))
            elif method == "average":
                out[y, x] = np.mean(window.astype(np.float64), axis=(0, 1)).astype(dt)
            else:
                raise ValueError(f"unsupported pooling method {method!r}")
            if index_en:
                for c in range(channels):
                    flat = int(np.argmax(window[:, :, c]))
                    row, col = divmod(flat, kw)
                    positions[y, x, c] = (row << 3) | col
    return out, positions


def _pool_pack(expected_shape: tuple[int, int, int], out: np.ndarray,
               positions: np.ndarray | None, dtype_name: str,
               channels: int, index_en: bool) -> tuple[np.ndarray, int, int, int]:
    dt = _dtype(dtype_name)
    itemsize = dt.itemsize
    atom = 16 // itemsize
    out_h, out_w, _ = expected_shape
    surfaces = _ceil_div(channels, atom)
    tail = np.array([-99], dtype=dt)[0] if channels == 3 else np.array([0], dtype=dt)[0]
    value = np.full((surfaces, out_h, out_w, atom), tail, dtype=dt)
    for c in range(channels):
        value[c // atom, :, :, c % atom] = out[:, :, c]
    value_bytes = value.size * itemsize

    if not index_en:
        return value.reshape(-1).view(np.uint8), value_bytes, 0, 0

    index_surfaces = _ceil_div(channels, 8)
    index = np.zeros((index_surfaces, out_h, out_w, 8), dtype=np.uint16)
    for c in range(channels):
        index[c // 8, :, :, c % 8] = positions[:, :, c]
    index_offset = out_h * out_w * 2 * 16
    index_bytes = index.size * 2
    return value.reshape(-1).view(np.uint8), value_bytes, index_offset, index_bytes


def verify_pooling(root: Path) -> dict[str, Any]:
    family = "pooling"
    manifest_path = root / family / "manifest.json"
    family_result: dict[str, Any] = {
        "family": family,
        "manifest": str(manifest_path),
        "status": "WAITING",
        "counts": {"ready": 0, "blocked": 0, "verified": 0, "pass": 0, "fail": 0,
                   "error": 0, "waiting": 0},
        "cases": [],
        "notes": [],
    }
    if not manifest_path.is_file():
        family_result["notes"].append("manifest.json not present; verifier is waiting")
        return family_result
    manifest = _read_json(manifest_path)
    entries = manifest.get("cases", [])
    family_result["manifest_file"] = _file_meta(manifest_path)
    family_result["manifest_generated_utc"] = manifest.get("generated_utc")
    family_result["source_evidence"] = _source_evidence(manifest)
    family_result["counts"]["ready"] = sum(1 for e in entries if e.get("status") == "READY")
    family_result["counts"]["blocked"] = sum(1 for e in entries if e.get("status") == "BLOCKED")
    family_result["status"] = "READY"

    for entry in entries:
        name = entry.get("case", "")
        case_dir = root / family / "cases" / name
        if entry.get("status") != "READY":
            family_result["cases"].append(_case(
                family, name, "BLOCKED", source=entry.get("source_example"),
                blocker=entry.get("blocked_reason"),
                notes=["BLOCKED probe: no valid numerical oracle exists."],
            ))
            continue

        try:
            job_path = case_dir / "job.json"
            if not job_path.is_file():
                family_result["cases"].append(_case(
                    family, name, "WAITING", source=entry.get("source_example"),
                    notes=[f"{job_path.name} is not present; waiting for this bundle."],
                ))
                family_result["counts"]["waiting"] += 1
                continue
            job = _read_json(job_path)
            ppu = entry["ppu"]
            layout = entry["layout"]
            oracle = entry["oracle"]
            expected_path = case_dir / oracle["expected_file"]
            if not expected_path.is_file():
                family_result["cases"].append(_case(
                    family, name, "WAITING", source=entry.get("source_example"),
                    oracle_file=oracle["expected_file"],
                    notes=["expected oracle file missing; waiting."],
                ))
                family_result["counts"]["waiting"] += 1
                continue

            checks: list[dict[str, Any]] = []
            notes: list[str] = []
            checks.append(_job_structure_check(case_dir, job, name))
            integrity = _check_bundle_hashes(case_dir, entry)
            if integrity is not None:
                if integrity["mismatches"]:
                    checks.append({"name": "bundle_sha256", "status": "FAIL",
                                   "mismatch_count": len(integrity["mismatches"]),
                                   "detail": integrity["mismatches"]})
                    notes.append(f"bundle hash mismatches: {integrity['mismatches']}")
                else:
                    checks.append({"name": "bundle_sha256", "status": "PASS",
                                   "checked": integrity["checked"]})

            dtype_name = ppu["dtype"]
            in_h, in_w = (int(v) for v in ppu["in_shape"])
            out_h, out_w = (int(v) for v in ppu["out_shape"])
            channels = int(ppu["channels"])
            src = _pool_decode_input(
                _read_bytes(_input_file(case_dir, job, "in", "in.bin")),
                dtype_name, channels, in_h, in_w)
            out, positions = _pool_compute(src, ppu)
            got_bytes, value_bytes, index_offset, index_bytes = _pool_pack(
                (out_h, out_w, channels), out, positions, dtype_name, channels,
                bool(ppu.get("index_en", False)))

            dt = _dtype(dtype_name)
            atom = 16 // dt.itemsize
            in_surfaces = _ceil_div(channels, atom)
            exp_in_bytes = in_surfaces * in_h * in_w * atom * dt.itemsize
            declared_in = layout.get("input", {})
            declared_out = layout.get("output", {})
            layout_checks = [
                ("layout_input_atom_channels", int(declared_in.get("atom_channels", atom)), atom),
                ("layout_input_logical_bytes", int(declared_in.get("logical_bytes", exp_in_bytes)), exp_in_bytes),
                ("layout_output_value_bytes", int(declared_out.get("value_bytes", value_bytes)), value_bytes),
                ("layout_output_index_offset", int(declared_out.get("index_offset") or 0), index_offset),
                ("layout_output_index_bytes", int(declared_out.get("index_bytes", 0)), index_bytes),
            ]
            for cname, want, got in layout_checks:
                checks.append({
                    "name": cname,
                    "status": "PASS" if want == got else "FAIL",
                    "declared": want, "computed": got,
                })
                if want != got:
                    notes.append(f"declared {cname}={want}, source layout gives {got}")

            exp_bytes = _read_bytes(expected_path)
            declared_buffer = int(declared_out.get("buffer_bytes", 4096))
            checks.append({
                "name": "expected_file_size",
                "status": "PASS" if len(exp_bytes) == declared_buffer else "FAIL",
                "expected": declared_buffer, "actual": len(exp_bytes),
            })
            exp_values = np.frombuffer(exp_bytes[:value_bytes], dtype=dt)
            got_values = np.frombuffer(got_bytes[:value_bytes], dtype=dt)
            tol = float(oracle.get("tolerance", 0.0))
            checks.append(_compare("value_region", got_values, exp_values, atol=tol,
                                   label="declared C1HWC2 value region"))
            notes.append(
                f"C1HWC2 value region: {value_bytes} B, {channels} channels, "
                f"atom={16 // dt.itemsize}, tail={-99 if channels == 3 else 0}."
            )

            if ppu.get("index_en", False):
                exp_idx = np.frombuffer(exp_bytes[index_offset:index_offset + index_bytes],
                                        dtype="<u2")
                index_surfaces = _ceil_div(channels, 8)
                index = np.zeros((index_surfaces, out_h, out_w, 8), dtype=np.uint16)
                for c in range(channels):
                    index[c // 8, :, :, c % 8] = positions[:, :, c]
                got_idx = index.reshape(-1)
                checks.append(_compare("index_region", got_idx, exp_idx, atol=0,
                                       label="uint16 (row<<3)|column indices"))
                notes.append(f"INDEX_EN: uint16 index region at +{index_offset} B, "
                             f"{index_bytes} B, layout [surf][y][x][8].")

            logical_bytes = int(oracle["logical_output_bytes"])
            if len(exp_bytes) != int(layout["output"]["buffer_bytes"]):
                notes.append(
                    f"expected.bin is {len(exp_bytes)} B, manifest buffer_bytes is "
                    f"{layout['output']['buffer_bytes']}"
                )
            outside = bytearray(exp_bytes)
            for a, b in ((0, value_bytes),
                         (index_offset, index_offset + index_bytes) if index_bytes else (0, 0)):
                for i in range(a, min(b, len(outside))):
                    outside[i] = 0
            nonzero_outside = [i for i, v in enumerate(outside) if v != 0]
            checks.append({
                "name": "expected_zero_outside_logical",
                "status": "PASS" if not nonzero_outside else "FAIL",
                "mismatch_count": len(nonzero_outside),
                "logical_output_bytes": logical_bytes,
                "detail": nonzero_outside[:16],
            })
            if nonzero_outside:
                notes.append("expected.bin has nonzero bytes outside declared value/index regions")

            status = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
            family_result["cases"].append(_case(
                family, name, status, source=entry.get("source_example"),
                oracle_file=oracle["expected_file"], checks=checks, notes=notes,
            ))
            family_result["counts"]["verified"] += 1
            family_result["counts"]["pass" if status == "PASS" else "fail"] += 1
        except Exception as exc:  # noqa: BLE001
            family_result["cases"].append(_case(
                family, name, "ERROR", source=entry.get("source_example"),
                notes=[f"{type(exc).__name__}: {exc}"],
                detail=traceback.format_exc(),
            ))
            family_result["counts"]["error"] += 1
    return family_result


# ===========================================================================
# Report generation
# ===========================================================================

def _family_markdown(fr: dict[str, Any]) -> list[str]:
    counts = fr["counts"]
    lines = [
        f"### `{fr['family']}`",
        "",
        f"- Status: **{fr['status']}**",
        f"- Manifest: `{fr['manifest']}`",
        f"- Manifest SHA-256: `{(fr.get('manifest_file') or {}).get('sha256', 'n/a')}`",
        f"- Manifest generated: `{fr.get('manifest_generated_utc') or 'not declared'}`",
        f"- READY / BLOCKED: **{counts['ready']} / {counts['blocked']}**",
        f"- Verified expected oracles: **{counts['verified']}** "
        f"(PASS {counts['pass']}, FAIL {counts['fail']}, ERROR {counts['error']}, "
        f"WAITING {counts['waiting']})",
        f"- Oracle coverage: **{counts['verified']}/{counts['ready']}** READY cases "
        f"were checked against a declared expected file; **{counts['blocked']}** "
        "BLOCKED cases are not scored.",
        "",
    ]
    for note in fr.get("notes", []):
        lines.append(f"- {note}")
    if fr.get("notes"):
        lines.append("")
    lines += [
        "| case | status | expected | max diff | mismatches | notes |",
        "|---|---|---|---:|---:|---|",
    ]
    for c in fr["cases"]:
        maxdiff = ""
        mism = ""
        for chk in c["checks"]:
            if "max_abs_diff" in chk:
                maxdiff = f"{float(chk['max_abs_diff']):.6g}"
                break
        for chk in c["checks"]:
            if "mismatch_count" in chk:
                mism = str(chk["mismatch_count"])
                break
        note = c.get("blocker") or (c.get("notes") or [""])[0]
        note = str(note).replace("|", "/")[:180]
        lines.append(
            f"| `{c['case']}` | {c['status']} | {c.get('oracle_file') or '-'} | "
            f"{maxdiff or '-'} | {mism or '-'} | {note} |"
        )
    lines.append("")
    failures = [c for c in fr["cases"] if c["status"] in ("FAIL", "ERROR")]
    if failures:
        lines.append("Failure details:")
        lines.append("")
        for c in failures:
            lines.append(f"- `{c['case']}` ({c['status']})")
            for chk in c["checks"]:
                if chk.get("status") != "PASS":
                    lines.append(f"  - {chk.get('name')}: {chk}")
            for note in c.get("notes", []):
                lines.append(f"  - {note}")
        lines.append("")
    return lines


def _build_markdown(report: dict[str, Any]) -> str:
    env = report["environment"]
    lines = [
        "# Independent conv / pooling oracle verification",
        "",
        f"Generated: `{report['generated_utc']}`",
        "",
        "This report was produced by an independent host-side verifier.  It does "
        "**not** contain a device capture and it does **not** establish RK3588 or "
        "FPGA numerics.  `expected*.bin` files are host-side oracles from the "
        "preparation bundles; they are compared against a separately implemented "
        "naive NumPy/pure-Python recomputation from the raw bundle inputs.",
        "",
        "## Environment",
        "",
        f"- Python: `{env['python']}` (`{env['executable']}`)",
        f"- NumPy: `{env['numpy']}`",
        f"- Platform: `{env['platform']}`",
        f"- Captures root: `{env['captures_root']}`",
        "",
        "## Commands",
        "",
        "```sh",
        f"/usr/bin/python3 {Path(__file__).resolve()}",
        "```",
        "",
        "No tracked source, test, generated file or family bundle was modified by "
        "this verifier.  `make generated-check` / `make test` were not run because "
        "this run only wrote under `team/oracle-conv/`.  No `ssh`, `scp`, board, "
        "NPU-device, flash or FPGA action was performed.",
        "",
        "## Summary",
        "",
        "| family | status | READY | BLOCKED | verified | PASS | FAIL | ERROR | WAITING |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for fam in FAMILIES:
        fr = report["families"][fam]
        c = fr["counts"]
        lines.append(
            f"| `{fam}` | {fr['status']} | {c['ready']} | {c['blocked']} | "
            f"{c['verified']} | {c['pass']} | {c['fail']} | {c['error']} | {c['waiting']} |"
        )
    lines += [
        "",
        "## Independence and comparison contract",
        "",
        "- No family `tools/` helper or preparation-time oracle function is imported or called.",
        "- Raw input/weight/bias bytes are decoded from the documented source layout; the "
        "convolution, pooling or GEMM is then recomputed with a small independent NumPy "
        "loops implementation.",
        "- Only the declared logical output region is compared: whole raw BO for conv-simple "
        "FP16, meaningful prefix for conv-simple INT8, logical NCHW for conv-fp16, logical "
        "NCHW/MxN for conv-gemm-vendor, and the C1HWC2 value/index regions for pooling.",
        "- `expected*.bin` is used only as the comparison target, never to construct the "
        "computed result.  No device output exists in these bundles; none is invented.",
        "- Each family section records the manifest SHA-256 and generated timestamp; "
        "VERIFY.json also carries the manifest's source-example/revision/seed/tool "
        "metadata under `source_evidence`.",
        f"- Device-output scan: **{report['device_output_scan']['present']}** declared "
        "worker output file(s) present.  The scan is listed separately so an oracle is "
        "never treated as a device capture.",
        "",
        "## Layout contracts exercised",
        "",
    ]
    for fam in FAMILIES:
        lines.append(f"**`{fam}`**")
        lines.append("")
        for item in LAYOUT_CONTRACTS[fam]:
            lines.append(f"- {item}")
        lines.append("")

    lines += [
        "## Mismatches",
        "",
    ]
    all_cases = [c for fam in FAMILIES for c in report["families"][fam]["cases"]]
    mismatched = [c for c in all_cases if c["status"] in ("FAIL", "ERROR")]
    if mismatched:
        for c in mismatched:
            lines.append(f"- `{c['family']}/{c['case']}`: **{c['status']}**")
            for chk in c["checks"]:
                if chk.get("status") != "PASS":
                    lines.append(f"  - `{chk.get('name')}`: {chk}")
            for note in c.get("notes", []):
                lines.append(f"  - {note}")
    else:
        lines.append(
            f"- None. All {report['summary']['verified']} READY cases with a declared "
            "expected oracle matched within their declared tolerance; no device output "
            "was compared and no oracle was substituted for one."
        )
    lines.append("")

    lines += [
        "## Per-family results",
        "",
    ]
    for fam in FAMILIES:
        lines.extend(_family_markdown(report["families"][fam]))

    lines += ["## Caveats", ""]
    for caveat in report.get("caveats", []):
        lines.append(f"- {caveat}")
    lines.append("")
    return "\n".join(lines)


def _attach_artifact_hashes(root: Path, families: dict[str, Any]) -> None:
    """Pin each scored case to the exact bytes used by this run."""
    for family, fr in families.items():
        for case in fr["cases"]:
            if case["status"] == "BLOCKED":
                continue
            case_dir = root / family / "cases" / case["case"]
            if not case_dir.is_dir():
                continue
            names: set[str] = set()
            job_path = case_dir / "job.json"
            if job_path.is_file():
                names.add("job.json")
                try:
                    job = _read_json(job_path)
                except Exception:  # noqa: BLE001
                    job = {}
                for buf in job.get("buffers", []) or []:
                    inp = buf.get("input")
                    if isinstance(inp, str):
                        names.add(inp)
            if (case_dir / "regcmd.bin").is_file():
                names.add("regcmd.bin")
            for fname in str(case.get("oracle_file") or "").split(","):
                if fname:
                    names.add(fname)
            artifacts: dict[str, Any] = {}
            for name in sorted(names):
                path = case_dir / name
                if path.is_file():
                    artifacts[name] = _file_meta(path)
            case["artifacts"] = artifacts


def _scan_device_outputs(root: Path) -> dict[str, Any]:
    """Find declared worker output files without substituting a host oracle."""
    found: list[dict[str, Any]] = []
    for family in FAMILIES:
        cases_dir = root / family / "cases"
        if not cases_dir.is_dir():
            continue
        for job_path in sorted(cases_dir.glob("*/job.json")):
            try:
                job = _read_json(job_path)
            except Exception:  # noqa: BLE001 - scan is best effort
                continue
            case_dir = job_path.parent
            for buf in job.get("buffers", []) or []:
                out_name = buf.get("output")
                if not out_name or not isinstance(out_name, str):
                    continue
                out_path = case_dir / out_name
                if out_path.is_file():
                    found.append({
                        "family": family,
                        "case": case_dir.name,
                        "buffer": buf.get("name"),
                        "file": str(out_path),
                        "bytes": int(out_path.stat().st_size),
                        "sha256": _sha256(out_path),
                    })
    return {
        "present": len(found),
        "files": found,
        "note": (
            "Device output files declared by job.json.  A present file is never "
            "replaced by expected*.bin; this verifier does not yet score device "
            "outputs and would require a separate device-differential step."
        ),
    }


def build_report(root: Path) -> dict[str, Any]:
    families = {
        "conv-simple": verify_conv_simple(root),
        "conv-fp16": verify_conv_fp16(root),
        "conv-gemm-vendor": verify_conv_gemm_vendor(root),
        "pooling": verify_pooling(root),
    }
    total = {"ready": 0, "blocked": 0, "verified": 0, "pass": 0, "fail": 0,
             "error": 0, "waiting": 0}
    for fr in families.values():
        c = fr["counts"]
        fr["oracle_coverage"] = {
            "ready_cases": c["ready"],
            "ready_expected_oracles_compared": c["verified"],
            "blocked_not_scored": c["blocked"],
            "ready_waiting_for_expected": c["waiting"],
            "expected_files": sorted({
                f for case in fr["cases"]
                if case.get("oracle_file")
                for f in str(case["oracle_file"]).split(",")
            }),
        }
        for k in total:
            total[k] += int(c.get(k, 0))
    _attach_artifact_hashes(root, families)
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "tool": str(Path(__file__).resolve()),
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "executable": sys.executable,
            "platform": platform.platform(),
            "captures_root": str(root),
        },
        "summary": total,
        "layout_contracts": LAYOUT_CONTRACTS,
        "device_output_scan": _scan_device_outputs(root),
        "families": families,
        "caveats": [
            "Host-side oracle comparison only; it does not validate SystemVerilog, the "
            "FPGA bitstream, the RK3588 NPU or any device capture.",
            "The verifier does not import family preparation tools or copy their oracle "
            "code; expected*.bin is only the comparison target.",
            "Device output scan: no declared worker output file is present.  A later "
            "device result must be compared separately and must never be replaced by "
            "expected*.bin.",
            "conv-fp16 output BOs contain channel and row padding while expected.bin is "
            "logical NCHW.  This verifier compares the logical region; it does not claim "
            "byte equality of the raw device output surface.",
            "conv-gemm-vendor multi-task cases use one terminal task per group/tile.  This "
            "verifier checks the numerical decomposition, not PC-chain or core-mask "
            "semantics.",
            "Dilation is not encoded by any READY stream, so no dilation contract is "
            "claimed.  conv-simple stride-2/SAME/grouped and the vendor ABI, split-K, "
            "pooling INT32/FP32 zero-write probes remain BLOCKED and are not scored.",
            "Pooling index positions are scored only for the clean window-local "
            "`(row << 3) | column` case.  Padded/strided index aliasing is not scored.",
            "INT8 conv-simple values were chosen by preparation so the donor formula does "
            "not clip.  Agreement here does not characterise clipping or saturation.",
            "Integer Q16 pooling cases were built so the means are exact; they do not "
            "characterise integer rounding on non-divisible windows.",
            "No NaN/Inf/subnormal policy is established.  The comparator treats matching "
            "infinity signs as matching only to avoid a false failure on FP16 overflow "
            "artifacts; this is not evidence of a hardware special-value contract.",
            "FP16 oracle values use float64 accumulation and one cast to FP16 (or float32 "
            "mean for pooling averages).  A device may accumulate in a different order.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, default=CAPTURES,
                        help="rk3588-example-captures root")
    parser.add_argument("--out", type=Path, default=HERE,
                        help="directory for VERIFY.json / VERIFY.md")
    parser.add_argument("--no-write", action="store_true",
                        help="print summary only; do not write report files")
    args = parser.parse_args(argv)

    report = build_report(args.captures)
    markdown = _build_markdown(report)
    if not args.no_write:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "VERIFY.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (args.out / "VERIFY.md").write_text(markdown, encoding="utf-8")

    s = report["summary"]
    print(f"independent conv/pooling oracle verification: "
          f"READY={s['ready']} BLOCKED={s['blocked']} verified={s['verified']} "
          f"PASS={s['pass']} FAIL={s['fail']} ERROR={s['error']} WAITING={s['waiting']}")
    for fam in FAMILIES:
        fr = report["families"][fam]
        c = fr["counts"]
        print(f"  {fam:20s} {fr['status']:7s} ready={c['ready']} blocked={c['blocked']} "
              f"pass={c['pass']} fail={c['fail']} error={c['error']} waiting={c['waiting']}")
    if s["fail"] or s["error"]:
        for fam in FAMILIES:
            for c in report["families"][fam]["cases"]:
                if c["status"] in ("FAIL", "ERROR"):
                    print(f"  {c['status']}: {fam}/{c['case']}")
                    for chk in c["checks"]:
                        if chk.get("status") != "PASS":
                            print(f"    {chk.get('name')}: {chk}")
                    for note in c.get("notes", []):
                        print(f"    {note}")
    return 0 if not (s["fail"] or s["error"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
