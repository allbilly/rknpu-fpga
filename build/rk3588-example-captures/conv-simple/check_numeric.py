#!/usr/bin/env python3
"""Independent NumPy reconstruction check for the conv-simple bundles.

This is deliberately separate from generate.py's source-function calls.  It
reconstructs the logical tensors from the *packed raw files* using the layout
documented in manifest.json, runs a straightforward naive convolution, packs
the result back into the source output layout, and compares it with
expected.bin.  It does not open a device.

Run with /usr/bin/python3 (needs NumPy).
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
READY = {"status": "READY"}


def ceil_div(x, y):
    return (x + y - 1) // y


def align_up(x, a):
    return ceil_div(x, a) * a


def load_manifest():
    with (ROOT / "manifest.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def fp16_case(case_rec):
    shape = case_rec["shape"]
    c, h, w, oc = shape["in_c"], shape["in_h"], shape["in_w"], shape["out_c"]
    kh, kw = shape["kh"], shape["kw"]
    case_dir = ROOT / "cases" / case_rec["case"]
    out_dtype = case_rec["oracle"]["dtype"]
    out_np = np.dtype("<f2") if out_dtype == "float16" else np.dtype("<f4")

    packed_in = np.fromfile(case_dir / "input.bin", dtype="<f2")
    packed_wt = np.fromfile(case_dir / "weight.bin", dtype="<f2")
    expected_raw = np.fromfile(case_dir / "expected.bin", dtype=out_np)

    # Recompute the source's packing choice for groups=1, non-depthwise.
    # _conv_align_c(): 8 for in_c <= 4, 16 otherwise.  _conv_input_pack_c2():
    # 8 for in_c > 4 and align_c for in_c <= 4.  use_nhwc is true when the
    # pack factor is exactly two (the validated C3/C4 small-channel path).
    align_c = 8 if c <= 4 else 16
    input_pack_c2 = 8 if c > 4 else align_c
    use_nhwc = input_pack_c2 // c == 2
    width_stride = align_up(w, max(1, ceil_div(16, align_c)))
    inp = np.zeros((c, h, w), dtype=np.float16)
    if use_nhwc:
        if packed_in.size != h * width_stride * c:
            raise AssertionError(f"{case_rec['case']}: NHWC input size {packed_in.size}")
        p_in = packed_in.reshape(h, width_stride, c)
        for ic in range(c):
            inp[ic] = p_in[:, :w, ic]
    else:
        c2 = input_pack_c2
        c1 = ceil_div(c, c2)
        if packed_in.size != c1 * h * width_stride * c2:
            raise AssertionError(f"{case_rec['case']}: channel-pair input size {packed_in.size}")
        p_in = packed_in.reshape(c1, h, width_stride, c2)
        for ic in range(c):
            inp[ic] = p_in[ic // c2, :, :w, ic % c2]

    # _pack_kh_major(): chunks of 16 output channels, [kh][kw][oc_lane][ic].
    aligned_in_c = align_c * ceil_div(c, align_c)
    chunk_elems = kh * kw * 16 * aligned_in_c
    n_chunks = ceil_div(oc, 16)
    if packed_wt.size != n_chunks * chunk_elems:
        raise AssertionError(f"{case_rec['case']}: weight size {packed_wt.size}")
    wt = np.zeros((oc, c, kh, kw), dtype=np.float16)
    for chunk in range(n_chunks):
        base = chunk * chunk_elems
        for ky in range(kh):
            for kx in range(kw):
                for lane in range(16):
                    oc_idx = chunk * 16 + lane
                    if oc_idx >= oc:
                        continue
                    off = base + ((ky * kw + kx) * 16 + lane) * aligned_in_c
                    wt[oc_idx, :c, ky, kx] = packed_wt[off:off + c]

    # Naive valid cross-correlation in float64, same reduction order as
    # expt/conv_simple.py::compute_expected.
    out_h, out_w = h - kh + 1, w - kw + 1
    acc = np.zeros((oc, out_h, out_w), dtype=np.float64)
    i64 = inp.astype(np.float64)
    w64 = wt.astype(np.float64)
    for o in range(oc):
        for ic in range(c):
            for ky in range(kh):
                for kx in range(kw):
                    acc[o] += i64[ic, ky:ky + out_h, kx:kx + out_w] * w64[o, ic, ky, kx]

    # unpack_output() inverse: [c1_out][out_width_stride][c2_out].
    c2_out = 8 if out_np == np.dtype("<f2") else 4
    c1_out = ceil_div(oc, c2_out)
    out_stride = out_h * out_w
    if expected_raw.size != c1_out * out_stride * c2_out:
        raise AssertionError(f"{case_rec['case']}: expected size {expected_raw.size}")
    decoded = np.zeros((oc, out_h, out_w), dtype=out_np)
    for o in range(oc):
        group, lane = divmod(o, c2_out)
        for y in range(out_h):
            for x in range(out_w):
                decoded[o, y, x] = expected_raw[
                    (group * out_stride + y * out_w + x) * c2_out + lane
                ]
    oracle = acc.astype(out_np)
    if not np.array_equal(decoded, oracle):
        diff = np.max(np.abs(decoded.astype(np.float64) - oracle.astype(np.float64)))
        raise AssertionError(f"{case_rec['case']}: independent oracle mismatch max={diff}")
    return f"FP16 {case_rec['case']}: independent naive conv == expected.bin ({out_np.name})"


def int8_case(case_rec):
    shape = case_rec["shape"]
    c, h, w, oc = shape["in_c"], shape["in_h"], shape["in_w"], shape["out_c"]
    kh, kw = shape["kh"], shape["kw"]
    groups = shape["groups"]
    depthwise = groups == c == oc and shape["weight_in_c"] == 1
    case_dir = ROOT / "cases" / case_rec["case"]
    packed_in = np.fromfile(case_dir / "input.bin", dtype=np.uint8)
    packed_wt = np.fromfile(case_dir / "weight.bin", dtype=np.uint8)
    packed_bias = np.fromfile(case_dir / "bias.bin", dtype="<i4")
    expected_raw = np.fromfile(case_dir / "expected.bin", dtype=np.uint8)

    # pack_input(): [channel_group][x][y][16], value = (u-0x80)&0xff.
    # calc_input_size() over-allocates by 2x; the written data is the first
    # in_groups*w*h*16 bytes and the suffix is zero fill.
    in_groups = ceil_div(c, 16)
    in_used = in_groups * w * h * 16
    in_alloc = in_groups * 2 * w * h * 16
    if packed_in.size != in_alloc:
        raise AssertionError(
            f"{case_rec['case']}: input size {packed_in.size} != calc {in_alloc}"
        )
    if np.any(packed_in[in_used:] != 0):
        raise AssertionError(f"{case_rec['case']}: input over-allocation suffix is not zero")
    inp = np.zeros((h, w, c), dtype=np.uint8)
    for group in range(in_groups):
        for x in range(w):
            for y in range(h):
                for lane in range(16):
                    ic = group * 16 + lane
                    if ic < c:
                        inp[y, x, ic] = (
                            int(packed_in[((group * w + x) * h + y) * 16 + lane]) + 0x80
                        ) & 0xFF

    # pack_weights(): replay the source loop exactly and read the sequential
    # packed bytes.  The packed array is over-allocated; only the written
    # prefix is meaningful.
    ic_loop = max(c, 16)
    oc_loop = 1 if depthwise else align_up(oc, 2)
    ic_groups = 64 if depthwise else 32
    wt = np.zeros((oc, kh, kw, c), dtype=np.uint8)  # [oc][x][y][ic]
    n = 0
    for oo in range(ceil_div(oc_loop, 32)):
        for ii in range(ceil_div(ic_loop, ic_groups)):
            for x in range(kw):
                for y in range(kh):
                    for oi in range(min(oc_loop - oo * 32, 32)):
                        for ij in range(min(ic_loop, ic_groups)):
                            oc_idx = oo * 32 + oi
                            ic_idx = ii * ic_groups + ij
                            if n >= packed_wt.size:
                                raise AssertionError(f"{case_rec['case']}: weight overrun at {n}")
                            value = (int(packed_wt[n]) + 0x80) & 0xFF
                            n += 1
                            if depthwise:
                                # A depthwise kernel is stored once per
                                # channel; the output channel is ic_idx.
                                if ic_idx < oc:
                                    wt[ic_idx, x, y, ic_idx] = value
                            elif oc_idx < oc and ic_idx < c:
                                wt[oc_idx, x, y, ic_idx] = value
    if n < 1:
        raise AssertionError(f"{case_rec['case']}: weight loop wrote nothing")

    # pack_biases(): stored = bias + 128 * sum(weight_u8), so invert it.
    bias = packed_bias.astype(np.int64).copy()
    for o in range(oc):
        correction = 0
        if depthwise:
            for x in range(kw):
                for y in range(kh):
                    correction += int(wt[o, x, y, o])
        else:
            for x in range(kw):
                for y in range(kh):
                    for ic in range(c):
                        correction += int(wt[o, x, y, ic])
        bias[o] -= 128 * correction

    out_h, out_w = h - kh + 1, w - kw + 1
    acc = np.zeros((1, out_h, out_w, oc), dtype=np.int64)
    for o in range(oc):
        acc[0, :, :, o] = bias[o]
        group = o if depthwise else o // (oc // groups)
        input_start = o if depthwise else group * (c // groups)
        input_end = input_start + 1 if depthwise else input_start + (c // groups)
        for y in range(kh):
            for x in range(kw):
                for ic in range(input_start, input_end):
                    if depthwise:
                        acc[0, :, :, o] += (
                            inp[y:y + out_h, x:x + out_w, o].astype(np.int64)
                            * int(wt[o, x, y, o])
                        )
                    else:
                        acc[0, :, :, o] += (
                            inp[y:y + out_h, x:x + out_w, ic].astype(np.int64)
                            * int(wt[o, x, y, ic - input_start])
                        )

    logical = np.clip(np.round(acc.astype(np.float64) * (1.0 / 255.0)), 0, 255).astype(np.uint8)

    # read_output() inverse: [channel_group][x][y][16], raw = logical-0x80.
    used_groups = ceil_div(oc, 16)
    used_size = used_groups * out_w * out_h * 16
    if expected_raw.size != used_size:
        raise AssertionError(
            f"{case_rec['case']}: expected prefix {expected_raw.size} != used {used_size}"
        )
    repacked = np.zeros(used_size, dtype=np.uint8)
    for o in range(oc):
        group, lane = divmod(o, 16)
        for y in range(out_h):
            for x in range(out_w):
                repacked[((group * out_w + x) * out_h + y) * 16 + lane] = (
                    int(logical[0, y, x, o]) - 0x80
                ) & 0xFF
    if not np.array_equal(repacked, expected_raw):
        diff = int(np.max(np.abs(repacked.astype(np.int16) - expected_raw.astype(np.int16))))
        raise AssertionError(f"{case_rec['case']}: independent INT8 oracle mismatch max={diff}")
    return f"INT8 {case_rec['case']}: independent int64 naive conv == expected.bin prefix"


def main() -> int:
    manifest = load_manifest()
    results = []
    cases = []
    for case_rec in manifest["cases"]:
        if case_rec["status"] != "READY":
            continue
        if "simple_conv" in Path(case_rec["source_example"]).name:
            message = int8_case(case_rec)
        else:
            message = fp16_case(case_rec)
        results.append(message)
        cases.append({"case": case_rec["case"], "status": "PASS", "check": message})
    print("\n".join(results))
    print(f"numeric check PASS: {len(results)} READY cases")
    report = {
        "checker": "check_numeric.py",
        "checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "PASS",
        "cases": cases,
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "note": (
            "Independent reconstruction from packed raw files, naive convolution, "
            "repacked raw output compared byte-for-byte with expected.bin.  "
            "Host-side only; not a device capture."
        ),
    }
    (ROOT / "numeric_check.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
