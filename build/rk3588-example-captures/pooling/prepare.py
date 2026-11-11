#!/usr/bin/env python3
"""Prepare device-free RK3588 PPU pooling capture bundles.

This script opens no device. It imports the source example's host-side helpers
and reproduces the exact register/QWORD stream with zero DMA placeholders.
The later board worker patches the two address fields from job.json.

Run with /usr/bin/python3 (NumPy is required):
    /usr/bin/python3 prepare.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path

try:
    import numpy as np
except ModuleNotFoundError as exc:  # default python3 may be a NumPy-less brew build
    raise SystemExit("NumPy is required; run with /usr/bin/python3") from exc

sys.dont_write_bytecode = True

BASE = Path(__file__).resolve().parent
CASES_DIR = BASE / "cases"
SOURCE = Path("/home/fedora/rk3588/examples/expt/pooling.py")
SOURCE_ORIGINAL = Path("/home/fedora/rk3588/examples/pooling.py")
REPO = Path("/home/fedora/rknpu-fpga")
BUFFER_BYTES = 4096
TIMEOUT_NS = 6_000_000_000
PREPARED_DATE = "2026-11-06"


def load_module(path: Path, name: str):
    if not path.is_file():
        raise SystemExit(f"missing source example: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


src = load_module(SOURCE, "rk3588_example_expt_pooling")
source_cases = src.cases()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def json_bytes(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("ascii")


REG_FIELDS = {
    (0x4001, 0x6004): "PPU_S_POINTER",
    (0x4001, 0x600C): "PPU_DATA_CUBE_IN_WIDTH",
    (0x4001, 0x6010): "PPU_DATA_CUBE_IN_HEIGHT",
    (0x4001, 0x6014): "PPU_DATA_CUBE_IN_CHANNEL",
    (0x4001, 0x6018): "PPU_DATA_CUBE_OUT_WIDTH",
    (0x4001, 0x601C): "PPU_DATA_CUBE_OUT_HEIGHT",
    (0x4001, 0x6020): "PPU_DATA_CUBE_OUT_CHANNEL",
    (0x4001, 0x6024): "PPU_OPERATION_MODE_CFG",
    (0x4001, 0x6034): "PPU_POOLING_KERNEL_CFG",
    (0x4001, 0x6038): "PPU_RECIP_KERNEL_WIDTH",
    (0x4001, 0x603C): "PPU_RECIP_KERNEL_HEIGHT",
    (0x4001, 0x6040): "PPU_POOLING_PADDING_CFG",
    (0x4001, 0x6044): "PPU_PADDING_VALUE_1_CFG",
    (0x4001, 0x6048): "PPU_PADDING_VALUE_2_CFG",
    (0x4001, 0x6070): "PPU_DST_BASE_ADDR",
    (0x4001, 0x607C): "PPU_DST_SURF_STRIDE",
    (0x4001, 0x6084): "PPU_DATA_FORMAT",
    (0x4001, 0x60DC): "PPU_MISC_CTRL",
    (0x8001, 0x7004): "PPU_RDMA_S_POINTER",
    (0x8001, 0x7008): "PPU_RDMA_OPERATION_ENABLE",
    (0x8001, 0x700C): "PPU_RDMA_CUBE_IN_WIDTH",
    (0x8001, 0x7010): "PPU_RDMA_CUBE_IN_HEIGHT",
    (0x8001, 0x7014): "PPU_RDMA_CUBE_IN_CHANNEL",
    (0x8001, 0x701C): "PPU_RDMA_SRC_BASE_ADDR",
    (0x8001, 0x7024): "PPU_RDMA_SRC_LINE_STRIDE",
    (0x8001, 0x7028): "PPU_RDMA_SRC_SURF_STRIDE",
    (0x8001, 0x7030): "PPU_RDMA_DATA_FORMAT",
    (0x0081, 0x0008): "PC_OPERATION_ENABLE",
}

METHOD_NAMES = {
    src.POOL_AVERAGE: "average",
    src.POOL_MAXIMUM: "maximum",
    src.POOL_MINIMUM: "minimum",
}
PRECISION_NAMES = {
    src.PRECISION_INT8: "INT8",
    src.PRECISION_INT16: "INT16",
    src.PRECISION_FP16: "FP16",
    src.PRECISION_INT32: "INT32",
    src.PRECISION_FP32: "FP32",
}
DTYPE_NAMES = {
    np.dtype("int8"): "int8",
    np.dtype("int16"): "int16",
    np.dtype("float16"): "float16",
    np.dtype("int32"): "int32",
    np.dtype("float32"): "float32",
}


def source_spec(
    name,
    source_case,
    source_lines,
    description,
    oracle_kind="numpy-source-pool-reference",
    oracle_lines=(731, 758),
    tolerance=0.0,
    oracle_note="",
    probe_only=None,
    overrides=None,
    derived=False,
):
    case = dict(source_cases[source_case])
    if overrides:
        case.update(overrides)
    return {
        "name": name,
        "source_case": source_case,
        "source_lines": list(source_lines),
        "description": description,
        "oracle_kind": oracle_kind,
        "oracle_lines": list(oracle_lines),
        "tolerance": tolerance,
        "oracle_note": oracle_note,
        "probe_only": bool(case.get("probe_only", False)) if probe_only is None else bool(probe_only),
        "derived": bool(derived),
        "case": case,
    }


def derived_padded_max_spec():
    # Same input, geometry, padding and 0xFC00 padding value as the source
    # maximum_indices_padding_stride probe, but with INDEX_EN removed so the
    # whole output has a clean host-side maximum oracle.
    case = dict(source_cases["maximum_indices_padding_stride"])
    case["index_en"] = False
    source_array = (np.arange(4 * 4 * 8, dtype=np.float16).reshape(4, 4, 8) + 1)
    expected = src.pool_reference(
        source_array,
        (3, 3),
        (2, 2),
        src.POOL_MAXIMUM,
        (1, 1, 1, 1),
        np.float16(-np.inf),
    )
    reference_values, _ = src.maximum_with_index_reference(
        source_array, (3, 3), (2, 2), (1, 1, 1, 1)
    )
    if not np.array_equal(reference_values, expected):
        raise SystemExit("derived padded-max value oracle disagrees with source reference")
    case["source"] = source_array
    case["expected"] = expected
    case["probe_only"] = False
    return {
        "name": "fp16_max_k3s2_pad1_c8_h4w4",
        "source_case": "maximum_indices_padding_stride (values-only variant)",
        "source_lines": [858, 891],
        "description": (
            "FP16 maximum pooling, 3x3 kernel, stride 2, padding 1 on all sides, "
            "C8 H4 W4 -> H2 W2; 0xFC00 (-inf) padding value. Same geometry/input "
            "as the source padded INDEX_EN probe with INDEX_EN removed so all "
            "expected values come from the source host-side maximum reference."
        ),
        "oracle_kind": "numpy-source-pool-reference",
        "oracle_lines": [731, 758, 858, 891],
        "tolerance": 0.0,
        "oracle_note": (
            "source pool_reference with padding_value=-inf; source probe states "
            "the values are ordinary local maxima. Index positions are not used."
        ),
        "probe_only": False,
        "derived": True,
        "case": case,
    }


SPECS = [
    source_spec(
        "fp16_avg_k2s1_valid_c8_h4w4",
        "fp16_average",
        [799, 818],
        "FP16 average pooling, 2x2 kernel, stride 1, no padding, C8 H4 W4 -> H3 W3; "
        "FP17 reciprocals 1/2; fractional means exercise FP16 output rounding.",
        tolerance=0.0625,
        oracle_note="source pool_reference; float32 accumulation then FP16 cast; source atol=0.0625.",
    ),
    source_spec(
        "fp16_max_k2s1_valid_c8_h4w4",
        "fp16_maximum",
        [799, 818],
        "FP16 maximum pooling, 2x2 kernel, stride 1, no padding, C8 H4 W4 -> H3 W3.",
    ),
    source_spec(
        "fp16_min_k2s1_valid_c8_h4w4",
        "fp16_minimum",
        [799, 818],
        "FP16 minimum pooling, 2x2 kernel, stride 1, no padding, C8 H4 W4 -> H3 W3.",
    ),
    source_spec(
        "fp16_avg_global_k3x5_valid_c8_h3w5",
        "global_average_3x5",
        [820, 835],
        "FP16 global average pooling, 3x5 kernel and stride, no padding, "
        "C8 H3 W5 -> H1 W1; dimension-specific FP17 reciprocals 1/5 and 1/3.",
        tolerance=0.0625,
        oracle_note="source pool_reference; float32 accumulation then FP16 cast; source atol=0.0625.",
    ),
    derived_padded_max_spec(),
    source_spec(
        "fp16_max_k2s1_pad1_neg_c8_h2w2",
        "negative_max_padding_neg_inf",
        [1112, 1135],
        "FP16 negative maximum pooling, 2x2 kernel, stride 1, padding 1, "
        "C8 H2 W2 -> H3 W3; 0xFC00 (-inf) padding value; all input values negative.",
        oracle_lines=[731, 758, 1124, 1134],
        oracle_note="source pool_reference with padding_value=-inf and the 0xFC00 register value.",
    ),
    source_spec(
        "fp16_avg_k2s1_pad1_use_cnt0_c8_h1w1",
        "average_padding_use_cnt_0",
        [1137, 1160],
        "FP16 average pooling, 2x2 kernel, stride 1, padding 1, C8 H1 W1 -> H2 W2, "
        "USE_CNT=0; include-padding mean 8/4=2. Source isolated probe.",
        tolerance=0.0625,
        oracle_lines=[731, 758, 1137, 1159],
        oracle_note="source include-padding expectation; alternate exclude-padding result 8 is a failure.",
    ),
    source_spec(
        "fp16_avg_k2s1_pad1_use_cnt7_c8_h1w1",
        "average_padding_use_cnt_7",
        [1137, 1160],
        "FP16 average pooling, 2x2 kernel, stride 1, padding 1, C8 H1 W1 -> H2 W2, "
        "USE_CNT=7; include-padding mean 8/4=2. Source isolated probe.",
        tolerance=0.0625,
        oracle_lines=[731, 758, 1137, 1159],
        oracle_note="source include-padding expectation; alternate exclude-padding result 8 is a failure.",
    ),
    source_spec(
        "fp16_max_k2s2_index_c8_h2w2",
        "maximum_indices",
        [837, 856],
        "FP16 maximum pooling with INDEX_EN, 2x2 kernel, stride 2, no padding, "
        "C8 H2 W2 -> H1 W1; index area at out_area*2*16 with (row<<3)|column positions.",
        oracle_kind="numpy-source-maximum-with-index-reference",
        oracle_lines=[761, 793],
        oracle_note="source maximum_with_index_reference; values and (row<<3)|column positions exact.",
    ),
    source_spec(
        "fp16_max_k2s2_c3_tail_h2w2",
        "three_channels",
        [1162, 1182],
        "FP16 maximum pooling, 2x2 kernel, stride 2, C3 H2 W2 -> H1 W1; "
        "16-byte atom tail lanes filled with -99 and checked in the output.",
        oracle_lines=[731, 758, 1179, 1181],
        oracle_note="source pool_reference over the full atom; tail lanes -99 per source expected_tail.",
    ),
    source_spec(
        "int8_max_k2s2_valid_c16_h2w2",
        "int8_maximum",
        [937, 962],
        "INT8 maximum pooling, 2x2 kernel, stride 2, no padding, C16 H2 W2 -> H1 W1; "
        "PPU_RDMA storage width 1 (8-bit).",
        oracle_lines=[937, 962],
        oracle_note="source int8 case and pool_reference/np.max expectation.",
    ),
    source_spec(
        "int8_min_k2s2_valid_c16_h2w2",
        "int8_minimum",
        [964, 998],
        "INT8 minimum pooling, 2x2 kernel, stride 2, no padding, C16 H2 W2 -> H1 W1.",
        oracle_lines=[731, 758, 964, 998],
        oracle_note="source int8 minimum case and pool_reference expectation.",
    ),
    source_spec(
        "int8_avg_q16_k2s2_valid_c16_h2w2",
        "int8_average_recip_q16",
        [1000, 1026],
        "INT8 average pooling, 2x2 kernel, stride 2, no padding, C16 H2 W2 -> H1 W1; "
        "Q16 reciprocals 0x8000/0x8000; exact integer means. Source isolated probe.",
        oracle_lines=[731, 758, 1022, 1023],
        oracle_note="source exact integer mean with Q16 reciprocals; values are exact.",
    ),
    source_spec(
        "int8_avg_q16_k3x3_valid_c16_h3w3",
        "int8_average_recip_q16_3x3",
        [1028, 1057],
        "INT8 average pooling, 3x3 kernel and stride, C16 H3 W3 -> H1 W1; "
        "Q16 reciprocals round(65536/3)=0x5555; exact integer means. Source isolated probe.",
        oracle_lines=[1028, 1057],
        oracle_note="source exact integer mean with Q16 reciprocals; values are exact.",
    ),
    source_spec(
        "int8_max_k1s1_valid_c32_h1w1",
        "vendor_int8_1x1_c32",
        [1059, 1075],
        "INT8 maximum pooling, 1x1 kernel and stride, C32 H1 W1 -> H1 W1; "
        "two 16-byte C1HWC2 surfaces; vendor 1x1 token probe.",
        oracle_lines=[1059, 1075],
        oracle_note="source vendor token case; identity max over a 1x1 window.",
    ),
    source_spec(
        "int16_max_k2s2_valid_c8_h2w2",
        "int16_maximum",
        [937, 962],
        "INT16 maximum pooling, 2x2 kernel, stride 2, no padding, C8 H2 W2 -> H1 W1; "
        "PPU_RDMA storage width 2 (16-bit).",
        oracle_lines=[937, 962],
        oracle_note="source int16 case and pool_reference/np.max expectation.",
    ),
    source_spec(
        "int16_min_k2s2_valid_c8_h2w2",
        "int16_minimum",
        [964, 998],
        "INT16 minimum pooling, 2x2 kernel, stride 2, no padding, C8 H2 W2 -> H1 W1.",
        oracle_lines=[731, 758, 964, 998],
        oracle_note="source int16 minimum case and pool_reference expectation.",
    ),
    source_spec(
        "int16_avg_q16_k2s2_valid_c8_h2w2",
        "int16_average_recip_q16",
        [1000, 1026],
        "INT16 average pooling, 2x2 kernel, stride 2, no padding, C8 H2 W2 -> H1 W1; "
        "Q16 reciprocals 0x8000/0x8000; exact integer means. Source isolated probe.",
        oracle_lines=[731, 758, 1022, 1023],
        oracle_note="source exact integer mean with Q16 reciprocals; values are exact.",
    ),
    source_spec(
        "int16_avg_q16_k3x3_valid_c8_h3w3",
        "int16_average_recip_q16_3x3",
        [1028, 1057],
        "INT16 average pooling, 3x3 kernel and stride, C8 H3 W3 -> H1 W1; "
        "Q16 reciprocals round(65536/3)=0x5555; exact integer means. Source isolated probe.",
        oracle_lines=[1028, 1057],
        oracle_note="source exact integer mean with Q16 reciprocals; values are exact.",
    ),
    source_spec(
        "int32_max_k2s2_zero_write_c4_h2w2",
        "int32_maximum",
        [937, 962],
        "BLOCKED probe: INT32 maximum pooling, 2x2 kernel, stride 2, C4 H2 W2 -> H1 W1; "
        "PROC_PRECISION=4, PPU_RDMA width 3. Source reports submit success with all-zero output.",
    ),
    source_spec(
        "fp32_max_k2s2_zero_write_c4_h2w2",
        "fp32_maximum",
        [937, 962],
        "BLOCKED probe: FP32 maximum pooling, 2x2 kernel, stride 2, C4 H2 W2 -> H1 W1; "
        "PROC_PRECISION=5, PPU_RDMA width 3. Source reports submit success with all-zero output.",
    ),
]

for spec in SPECS:
    case = spec["case"]
    if case.get("expect_unsupported", False):
        if not np.any(np.asarray(case["expected"])):
            raise SystemExit(f"blocked source case {spec['name']} has no nonzero expectation")
        spec["status"] = "BLOCKED"
    else:
        spec["status"] = "READY"


def build_one(spec):
    case = spec["case"]
    name = spec["name"]
    dtype = np.dtype(case["dtype"])
    dtype_name = DTYPE_NAMES[dtype]
    channels = int(case["channels"])
    in_h, in_w = map(int, case["in_shape"])
    out_h, out_w = map(int, case["out_shape"])
    kernel = tuple(map(int, case["kernel"]))
    stride = tuple(map(int, case["stride"]))
    padding = tuple(map(int, case.get("padding", (0, 0, 0, 0))))
    padding_value = tuple(map(int, case.get("padding_value", (0, 0))))
    index_en = bool(case.get("index_en", False))
    use_cnt = int(case.get("use_cnt", 0))
    recip_override = case.get("recip_override")
    tail_value = case.get("tail_value", 0)
    method = int(case["method"])
    precision = int(case["output_precision"])
    rdma_width = int(case["rdma_width"])
    item_bytes = dtype.itemsize
    atom_channels = 16 // item_bytes
    surfaces = (channels + atom_channels - 1) // atom_channels
    out_area = out_h * out_w
    in_logical_bytes = surfaces * in_h * in_w * 16
    value_bytes = surfaces * out_area * 16
    index_surfaces = (channels + 7) // 8 if index_en else 0
    index_offset = out_area * 2 * 16 if index_en else None
    index_bytes = index_surfaces * out_area * 16 if index_en else 0
    out_logical_bytes = (max(value_bytes, index_offset) + index_bytes) if index_en else value_bytes
    if out_logical_bytes > BUFFER_BYTES or in_logical_bytes > BUFFER_BYTES:
        raise SystemExit(f"{name}: logical data exceeds {BUFFER_BYTES}-byte buffer")

    source_array = np.asarray(case["source"], dtype=dtype).reshape(in_h, in_w, channels)
    input_buffer = bytearray(BUFFER_BYTES)
    src._pack_cube(input_buffer, source_array, dtype, tail_value)
    input_bytes = bytes(input_buffer)

    commands = src.make_pool_regcmds(
        0,
        0,
        (in_h, in_w),
        (out_h, out_w),
        channels,
        method,
        precision,
        rdma_width,
        kernel,
        stride,
        padding,
        index_en,
        use_cnt,
        padding_value,
        0,
        recip_override,
        None,
        None,
    )

    patches = []
    for index, command in enumerate(commands):
        target = (command >> 48) & 0xFFFF
        offset = command & 0xFFFF
        if (target, offset) == (src.reg.PPU, src.reg.PPU_DST_BASE_ADDR):
            patches.append({"regcmd_index": index, "buffer": "out", "kind": "value32"})
        elif (target, offset) == (src.reg.PPU_RDMA, src.reg.PPU_RDMA_SRC_BASE_ADDR):
            patches.append({"regcmd_index": index, "buffer": "in", "kind": "value32"})
    if len(patches) != 2:
        raise SystemExit(f"{name}: expected exactly two address patches, got {len(patches)}")

    padding_scalar = (
        np.float16(-np.inf) if padding_value[0] == 0xFC00 else 0
    )
    expected_logical = np.asarray(case["expected"], dtype=dtype).reshape(out_h, out_w, channels)

    expected_positions = None
    if index_en:
        expected_positions = np.asarray(case["expected_positions"], dtype=np.uint16).reshape(
            out_h, out_w, channels
        )
        reference_values, reference_positions = src.maximum_with_index_reference(
            source_array, kernel, stride, padding, padding_scalar
        )
        if not np.array_equal(reference_values, expected_logical):
            raise SystemExit(f"{name}: INDEX_EN value oracle mismatch")
        if not np.array_equal(reference_positions, expected_positions):
            raise SystemExit(f"{name}: INDEX_EN position oracle mismatch")
        oracle_kind = spec["oracle_kind"]
    else:
        reference = src.pool_reference(
            source_array, kernel, stride, method, padding, padding_scalar
        )
        if not np.array_equal(reference, expected_logical):
            raise SystemExit(f"{name}: host pool_reference mismatch")
        oracle_kind = spec["oracle_kind"]

    expected_full = np.zeros((surfaces, out_h, out_w, atom_channels), dtype=dtype)
    for channel in range(channels):
        expected_full[channel // atom_channels, :, :, channel % atom_channels] = (
            expected_logical[:, :, channel]
        )
    if channels % atom_channels:
        expected_full[-1, :, :, channels % atom_channels :] = tail_value

    out_buffer = bytearray(BUFFER_BYTES)
    value_view = np.ndarray(
        (surfaces, out_h, out_w, atom_channels), dtype=dtype, buffer=out_buffer
    )
    value_view[:] = expected_full

    if index_en:
        index_full = np.zeros((index_surfaces, out_h, out_w, 8), dtype=np.uint16)
        for channel in range(channels):
            index_full[channel // 8, :, :, channel % 8] = expected_positions[:, :, channel]
        index_view = np.ndarray(
            (index_surfaces, out_h, out_w, 8),
            dtype=np.uint16,
            buffer=out_buffer,
            offset=index_offset,
        )
        index_view[:] = index_full

    expected_bytes = bytes(out_buffer)
    if any(expected_bytes[out_logical_bytes:]):
        raise SystemExit(f"{name}: expected buffer has nonzero bytes beyond the logical output")

    status = spec["status"]
    job = {
        "case": name,
        "source_example": str(SOURCE),
        "description": spec["description"],
        "timeout_ns": TIMEOUT_NS,
        "tasks": [
            {"regcmd_offset_words": 0, "regcmd_words": len(commands)}
        ],
        "buffers": [
            {"name": "in", "size": BUFFER_BYTES, "input": "in.bin", "direction": "in"},
            {
                "name": "out",
                "size": BUFFER_BYTES,
                "input": "out_init.bin",
                "direction": "inout",
                "output": "out.bin",
            },
        ],
        "patches": patches,
    }

    case_dir = CASES_DIR / name
    case_dir.mkdir(parents=True, exist_ok=False)
    (case_dir / "job.json").write_bytes(json_bytes(job))
    (case_dir / "regcmd.bin").write_bytes(
        b"".join(struct.pack("<Q", int(command)) for command in commands)
    )
    (case_dir / "regcmd.txt").write_text(render_regcmd(name, spec, commands, patches), encoding="ascii")
    (case_dir / "in.bin").write_bytes(input_bytes)
    (case_dir / "out_init.bin").write_bytes(bytes(BUFFER_BYTES))
    if status == "READY":
        (case_dir / "expected.bin").write_bytes(expected_bytes)
    elif (case_dir / "expected.bin").exists():
        raise SystemExit(f"{name}: blocked case must not have expected.bin")

    files = {}
    for path in sorted(case_dir.iterdir()):
        if not path.is_file():
            continue
        data = path.read_bytes()
        files[path.name] = {"bytes": len(data), "sha256": sha256_bytes(data)}

    oracle = {
        "kind": oracle_kind,
        "source_example": str(SOURCE),
        "source_lines": spec["oracle_lines"],
        "expected_file": "expected.bin" if status == "READY" else None,
        "buffer_bytes": BUFFER_BYTES,
        "logical_output_bytes": out_logical_bytes,
        "tolerance": float(spec["tolerance"]),
        "compare": (
            "Decode expected.bin with ppu.dtype. Compare the value region and, for "
            "INDEX_EN, the uint16 index region at layout.output.index_offset. Use "
            "oracle.tolerance for FP16 average; integers, maxima/minima, and index "
            "positions are exact. Bytes after logical_output_bytes must remain zero."
        ),
        "note": spec["oracle_note"],
    }
    if status == "BLOCKED":
        oracle = {
            "kind": "none",
            "reason": (
                "Source reports submit_ret==0 but the PPU writes all zero for this "
                "PROC_PRECISION; no valid device output exists to compare."
            ),
        }

    entry = {
        "case": name,
        "status": status,
        "source_example": str(SOURCE),
        "source_case": spec["source_case"],
        "source_lines": spec["source_lines"],
        "description": spec["description"],
        "probe_only": spec["probe_only"],
        "derived": spec["derived"],
        "ppu": {
            "method": METHOD_NAMES[method],
            "method_selector": method,
            "precision_name": PRECISION_NAMES[precision],
            "output_precision": precision,
            "rdma_width": rdma_width,
            "dtype": dtype_name,
            "channels": channels,
            "in_shape": [in_h, in_w],
            "out_shape": [out_h, out_w],
            "kernel": [kernel[0], kernel[1]],
            "stride": [stride[0], stride[1]],
            "padding": [padding[0], padding[1], padding[2], padding[3]],
            "padding_value": [padding_value[0], padding_value[1]],
            "index_en": index_en,
            "use_cnt": use_cnt,
            "recip_override": list(map(int, recip_override)) if recip_override else None,
            "notch_addr": 0,
        },
        "shapes": {
            "in_h": in_h,
            "in_w": in_w,
            "channels": channels,
            "out_h": out_h,
            "out_w": out_w,
            "atom_bytes": 16,
            "atom_channels": atom_channels,
            "surfaces": surfaces,
            "out_area": out_area,
            "in_logical_bytes": in_logical_bytes,
            "value_bytes": value_bytes,
            "index_offset": index_offset,
            "index_bytes": index_bytes,
            "out_logical_bytes": out_logical_bytes,
            "buffer_bytes": BUFFER_BYTES,
        },
        "layout": {
            "input": {
                "packing": "C1HWC2 (surface, y, x, 16-byte atom), little-endian",
                "dtype": dtype_name,
                "atom_bytes": 16,
                "atom_channels": atom_channels,
                "surfaces": surfaces,
                "line_stride_bytes": in_w * 16,
                "surface_stride_bytes": in_h * in_w * 16,
                "logical_bytes": in_logical_bytes,
                "buffer_bytes": BUFFER_BYTES,
                "tail_value": int(tail_value),
            },
            "output": {
                "packing": "C1HWC2 (surface, y, x, 16-byte atom), little-endian",
                "value_bytes": value_bytes,
                "index_en": index_en,
                "index_offset": index_offset,
                "index_surfaces": index_surfaces,
                "index_bytes": index_bytes,
                "logical_bytes": out_logical_bytes,
                "buffer_bytes": BUFFER_BYTES,
            },
        },
        "oracle": oracle,
        "files": files,
    }
    if status == "BLOCKED":
        entry["blocked_reason"] = (
            "Source expt/pooling.py docstring lines 17-18 and the case flag "
            "expect_unsupported=True (lines 937-962) report that this "
            "PROC_PRECISION configuration submits successfully (submit_ret==0) "
            "but writes all zero, while the expected maximum is nonzero. That "
            "disproves the format on this PPU path; there is no valid output to "
            "compare. The exact probe stream is retained, but it must not be "
            "scored as a READY numerical case."
        )
        entry["source_reported_behavior"] = (
            "source reports submit_ret==0 and output BO all zero; source expected nonzero"
        )
        entry["source_expected_nonzero"] = [
            int(value) if dtype.kind in "iu" else float(value)
            for value in np.asarray(case["expected"]).reshape(-1).tolist()
        ]
        entry["source_docstring_lines"] = [17, 18]
    return entry


def render_regcmd(name, spec, commands, patches):
    patch_by_index = {row["regcmd_index"]: row["buffer"] for row in patches}
    lines = [
        f"# case: {name}",
        f"# source: {SOURCE}:{spec['source_lines'][0]}-{spec['source_lines'][1]}",
        f"# regcmd_qwords: {len(commands)}",
        "# address placeholders: PPU_DST_BASE_ADDR -> out, PPU_RDMA_SRC_BASE_ADDR -> in",
        "idx\ttarget\toffset\tvalue\tfield\tpatch",
    ]
    for index, command in enumerate(commands):
        target = (command >> 48) & 0xFFFF
        offset = command & 0xFFFF
        value = (command >> 16) & 0xFFFFFFFF
        field = REG_FIELDS.get((target, offset), "UNKNOWN")
        patch = patch_by_index.get(index, "")
        lines.append(
            f"{index}\t0x{target:04x}\t0x{offset:04x}\t0x{value:08x}\t{field}\t{patch}"
        )
    return "\n".join(lines) + "\n"


def source_hash_entry(path: Path, role: str):
    data = path.read_bytes()
    return {
        "path": str(path),
        "role": role,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
    }


def repo_head():
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def render_readme(summary, coverage, entries):
    ready = [entry for entry in entries if entry["status"] == "READY"]
    blocked = [entry for entry in entries if entry["status"] == "BLOCKED"]
    lines = [
        "# RK3588 PPU pooling capture bundles",
        "",
        "Device-free preparation for the RK3588 PPU pooling examples. No board,",
        "DRM/NPU device or FPGA was opened, and no `ssh`, `scp` or programming",
        "command was run. The later single board worker owns execution under the",
        "capture-queue lock.",
        "",
        "## Sources",
        "",
        f"- `/home/fedora/rk3588/examples/pooling.py` - original PPU matrix.",
        f"- `/home/fedora/rk3588/examples/expt/pooling.py` - extended matrix used as",
        "  the primary source for every bundle (source hashes are in `manifest.json`).",
        "  Where the two files differ (for example the INT8/INT16 maximum input",
        "  data), these bundles follow `expt/pooling.py`.",
        "",
        "## Bundle layout",
        "",
        "Each READY case has `job.json`, `regcmd.bin`, `regcmd.txt`, `in.bin`,",
        "`out_init.bin` and `expected.bin`. BLOCKED cases keep the exact probe",
        "streams but have no `expected.bin`.",
        "",
        "`job.json` follows `../CAPTURE_FORMAT.md`: one task at regcmd word offset 0,",
        "4096-byte input/output BOs, and `value32` patches for exactly the two DMA",
        "address QWORDs (`PPU_DST_BASE_ADDR`, `PPU_RDMA_SRC_BASE_ADDR`). The output",
        "buffer is `inout` with `out_init.bin` zeroes so the source's explicit",
        "`output_map[:] = 0` initialization is reproduced.",
        "",
        "## Derivation",
        "",
        "1. `/usr/bin/python3` imports `expt/pooling.py`; `cases()` supplies the",
        "   hardcoded source matrices and expected values.",
        "2. `make_pool_regcmds()` is called with zero DMA addresses. The exact",
        "   PPU, PPU_RDMA and PC QWORD order is written to `regcmd.bin`; the two",
        "   address QWORD indices become the `job.json` patches.",
        "3. `_pack_cube()` packs each input into the PPU's C1HWC2 surface order",
        "   (16-byte atoms, `ceil(C / atom_channels)` surfaces). The full packed",
        "   bytes, including atom tails, are written to `in.bin`; unused BO bytes",
        "   are zero.",
        "4. `expected.bin` comes from the source host-side `pool_reference()` or",
        "   `maximum_with_index_reference()`, repacked into the output C1HWC2",
        "   layout. Atom tails (for C3) are filled with the source tail value.",
        "   For INDEX_EN the uint16 index area starts at `out_area * 2 * 16`.",
        "5. All buffers are 4096 bytes so DMA bursts cannot run past the BO; only",
        "   the first `layout.*.logical_bytes` bytes are meaningful. The rest of",
        "   `out_init.bin`/`expected.bin` is zero.",
        "",
        "The two FP32/INT32 zero-write probes are BLOCKED. The source docstring",
        "states that PROC_PRECISION 4/5 submissions return success but write all",
        "zero, so no valid expected output exists. They are retained only as exact",
        "reproducible probes.",
        "",
        "## Coverage",
        "",
        f"READY {summary['ready']} / BLOCKED {summary['blocked']} / total {summary['total']}.",
        "",
        "| case | status | dtype | method | kernel | stride | padding | in HxWxC | out HxWxC | INDEX_EN |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in entries:
        ppu = entry["ppu"]
        shp = entry["shapes"]
        pad = ppu["padding"]
        pad_text = "valid" if not any(pad) else "/".join(str(value) for value in pad)
        marker = ""
        if entry["probe_only"]:
            marker += " (probe)"
        if entry["derived"]:
            marker += " (derived)"
        lines.append(
            "| `{}`{} | {} | {} | {} | {}x{} | {}x{} | {} | {}x{}x{} | {}x{}x{} | {} |".format(
                entry["case"],
                marker,
                entry["status"],
                ppu["dtype"],
                ppu["method"],
                ppu["kernel"][0],
                ppu["kernel"][1],
                ppu["stride"][0],
                ppu["stride"][1],
                pad_text,
                shp["in_h"],
                shp["in_w"],
                shp["channels"],
                shp["out_h"],
                shp["out_w"],
                shp["channels"],
                "yes" if ppu["index_en"] else "no",
            )
        )
    lines += [
        "",
        "Coverage groups:",
        "",
        f"- precision: {', '.join(f'{key}: {len(value)}' for key, value in coverage['by_precision'].items())}",
        f"- method: {', '.join(f'{key}: {len(value)}' for key, value in coverage['by_method'].items())}",
        f"- kernel: {', '.join(f'{key}: {len(value)}' for key, value in coverage['by_kernel'].items())}",
        f"- stride: {', '.join(f'{key}: {len(value)}' for key, value in coverage['by_stride'].items())}",
        f"- padded cases: {len(coverage['padded'])}; valid cases: {len(coverage['valid'])}",
        f"- INDEX_EN cases: {', '.join(coverage['index_en']) or 'none'}",
        "",
        "## Register sequence",
        "",
        "All cases use one PPU task. Maximum/minimum streams have 26 QWORDs;",
        "average streams have 28 because `PPU_RECIP_KERNEL_WIDTH` and",
        "`PPU_RECIP_KERNEL_HEIGHT` are inserted after `PPU_POOLING_KERNEL_CFG`.",
        "Order: PPU S_POINTER, PPU_RDMA S_POINTER, input/output dimensions,",
        "`OPERATION_MODE_CFG`, `POOLING_KERNEL_CFG`, optional reciprocals,",
        "padding config/value, destination base/surface stride, `DATA_FORMAT`,",
        "`MISC_CTRL`, PPU_RDMA dimensions/base/line stride/surface stride/format,",
        "PPU_RDMA enable, then `PC_OPERATION_ENABLE=0x60`. `regcmd.txt` decodes",
        "every QWORD for every case.",
        "",
        "## Worker requirements",
        "",
        "`job.json` carries only the schema's task offset/word count. The mainline",
        "Rocket runner builds `drm_rocket_task` from `regcmd` (u32 DMA address)",
        "and `regcmd_count` only. The source example's `struct_rknpu_task`",
        "`op_idx`, `enable_mask` and interrupt fields are written into its vendor",
        "task BO but are not consumed by `rocket_submit()` (expt/pooling.py",
        "lines 212-234); PPU activation is the `PC_OPERATION_ENABLE=0x60` QWORD",
        "in `regcmd.bin`. The `inout` output is copied from `out_init.bin` and,",
        "per `runner/README.md`, is listed only in `out_bo_handles`.",
        "",
        "## BLOCKED cases",
        "",
        "`manifest.json` also carries top-level `ready_cases` and `blocked_cases`",
        "lists so the board worker can select only READY jobs.",
        "",
        "- `int32_max_k2s2_zero_write_c4_h2w2` - PROC_PRECISION=4, RDMA width 3.",
        "- `fp32_max_k2s2_zero_write_c4_h2w2` - PROC_PRECISION=5, RDMA width 3.",
        "",
        "The source reports that both probes submit successfully but write zero.",
        "Their `in.bin`, `regcmd.bin`, `job.json` and `out_init.bin` are retained",
        "for reproduction;",
        "do not compare them to a numeric expected output. Do not submit them in",
        "the board run queue: pointing the runner at this family directory expands",
        "every case, so pass only the 19 READY case directories (or filter by",
        "`manifest.json` status).",
        "",
        "## Not bundled",
        "",
        "- `int8_average` and `int16_average` (FP17-reciprocal integer average) are",
        "  source-labelled inexact negative controls. Their expected values are",
        "  recorded device observations, not host-derivable, so they are not READY",
        "  host-oracle bundles. Exact integer average is covered by the Q16 cases.",
        "- `maximum_indices_padding_stride` and `maximum_indices_kernel16` are",
        "  probe-only INDEX_EN cases with non-window-local phase / modulo-8 index",
        "  aliasing. The clean `maximum_indices` case is bundled; the padded",
        "  3x3/stride-2 geometry is bundled without INDEX_EN as",
        "  `fp16_max_k3s2_pad1_c8_h4w4`.",
        "- `strided_input_notch_0/2` are probe-only explicit line/surface-stride",
        "  and notch experiments outside the requested small-shape mode matrix.",
        "- `padding_7` and `kernel_stride_16` are larger isolated probes; the",
        "  requested small-shape matrix uses 1x1, 2x2, 3x3 and 3x5 cases.",
        "- The source matrix has no padded INT8/INT16 pooling case. Padded",
        "  windows are therefore covered by the FP16 padded cases only; no",
        "  integer padded variant was invented without source evidence.",
        "- The 2x3 average probes and the three multi-pass (linked submission)",
        "  cases are not part of this single-task bundle.",
        "",
        "## Caveats",
        "",
        "- `expected.bin` is a host-side NumPy oracle, not a device capture. It",
        "  establishes the intended contract only; it is not evidence of RK3588",
        "  or FPGA behavior.",
        "- FP16 average/global expected values use float32 accumulation followed",
        "  by an FP16 cast. The source tolerance is 0.0625; compare those cases",
        "  with that tolerance rather than demanding byte equality.",
        "- Integer Q16 average cases are built so the means are exact; they do not",
        "  characterize integer rounding on non-divisible windows.",
        "- This is a source-grounded subset, not a full Cartesian product. Mode",
        "  combinations absent from the source matrix (for example padded integer",
        "  pooling or a padded 3x3 average) were not invented.",
        "- `fp16_max_k3s2_pad1_c8_h4w4` is derived from the source padded INDEX_EN",
        "  probe with INDEX_EN removed. Its values use the source host reference,",
        "  but this exact non-index variant was not a separate source case.",
        "- The clean INDEX_EN case uses `(row << 3) | column`. The source documents",
        "  that padded/strided and >7 coordinates alias or lose window-local",
        "  phase; those probe-only index cases are deliberately not scored here.",
        "- No multi-pass/fenced sequence, unpool/upsample, DPU_RDMA or non-PPU",
        "  selector is covered by this family.",
        "",
        "## Local validation",
        "",
        "Run `/usr/bin/python3 validate.py`. It checks the manifest shape, per-case",
        "file census and hashes, buffer sizes, regcmd length and decode, the exact",
        "PPU/PPU_RDMA/PC QWORD order, both patch indices and their address fields,",
        "and independently recomputes every READY expected buffer from `in.bin`",
        "with the source host oracle. It opens no device.",
        "",
        "The queue's authoritative schema checker is also runnable without a board:",
        "",
        "```sh",
        "python3 ../runner/validate_bundle.py .",
        "```",
        "",
        "It accepts all 21 case directories in this family (it validates schema, not",
        "READY/BLOCKED scoring), and it rejects unknown job.json fields.",
        "",
    ]
    return "\n".join(lines)


def main():
    if CASES_DIR.exists():
        shutil.rmtree(CASES_DIR)
    CASES_DIR.mkdir(parents=True)

    entries = []
    for spec in SPECS:
        entry = build_one(spec)
        entries.append(entry)

    ready_entries = [entry for entry in entries if entry["status"] == "READY"]
    blocked_entries = [entry for entry in entries if entry["status"] == "BLOCKED"]
    summary = {
        "ready": len(ready_entries),
        "blocked": len(blocked_entries),
        "total": len(entries),
    }

    coverage = {
        "by_precision": {},
        "by_method": {},
        "by_kernel": {},
        "by_stride": {},
        "padded": [],
        "valid": [],
        "index_en": [],
        "blocked_zero_write": [entry["case"] for entry in blocked_entries],
    }
    for entry in ready_entries:
        ppu = entry["ppu"]
        coverage["by_precision"].setdefault(ppu["precision_name"], []).append(entry["case"])
        coverage["by_method"].setdefault(ppu["method"], []).append(entry["case"])
        kernel = f"{ppu['kernel'][0]}x{ppu['kernel'][1]}"
        stride = f"{ppu['stride'][0]}x{ppu['stride'][1]}"
        coverage["by_kernel"].setdefault(kernel, []).append(entry["case"])
        coverage["by_stride"].setdefault(stride, []).append(entry["case"])
        if any(ppu["padding"]):
            coverage["padded"].append(entry["case"])
        else:
            coverage["valid"].append(entry["case"])
        if ppu["index_en"]:
            coverage["index_en"].append(entry["case"])

    readme_path = BASE / "README.md"
    readme_path.write_text(render_readme(summary, coverage, entries), encoding="ascii")

    prepare_path = Path(__file__).resolve()
    validate_path = BASE / "validate.py"
    artifacts = {
        "README.md": {"bytes": readme_path.stat().st_size, "sha256": sha256_file(readme_path)},
        "prepare.py": {"bytes": prepare_path.stat().st_size, "sha256": sha256_file(prepare_path)},
    }
    if validate_path.is_file():
        artifacts["validate.py"] = {
            "bytes": validate_path.stat().st_size,
            "sha256": sha256_file(validate_path),
        }
    else:
        raise SystemExit("validate.py must exist before prepare.py writes manifest.json")

    manifest = {
        "schema": "rk3588-example-capture-manifest-v1",
        "family": "pooling",
        "prepared_date": PREPARED_DATE,
        "device_access": (
            "none: no DRM/NPU/FPGA device opened, no ssh/scp, no programming"
        ),
        "source_examples": [
            source_hash_entry(SOURCE_ORIGINAL, "original PPU pooling matrix"),
            source_hash_entry(SOURCE, "extended PPU pooling matrix; primary bundle source"),
        ],
        "generator": {
            "path": "prepare.py",
            "python": platform.python_version(),
            "python_executable": sys.executable,
            "numpy": np.__version__,
            "repo_head": repo_head(),
            "input_generation": (
                "closed-form source arrays and constants; no RNG and no seed"
            ),
        },
        "summary": summary,
        "ready_cases": [entry["case"] for entry in ready_entries],
        "blocked_cases": [entry["case"] for entry in blocked_entries],
        "worker_requirements": {
            "runner": "build/rk3588-example-captures/runner/rocket_run.py",
            "run_only_status": "READY",
            "blocked_must_not_be_submitted": True,
            "job_schema": (
                "CAPTURE_FORMAT.md; runner/validate_bundle.py rejects unknown "
                "job.json fields"
            ),
            "task_descriptor": {
                "type": "drm_rocket_task",
                "fields": {
                    "regcmd": "u32 DMA address of regcmd.bin",
                    "regcmd_count": "regcmd_words",
                },
                "source_lines": [212, 234],
                "note": (
                    "rocket_submit() builds only drm_rocket_task{regcmd, "
                    "regcmd_count}. The vendor struct_rknpu_task op_idx/"
                    "enable_mask/int_* writes (lines 502-514) are not consumed "
                    "by the mainline submit path; do not add them to job.json."
                ),
            },
            "submit": {
                "in_bos": ["regcmd", "in"],
                "out_bos": ["out"],
                "timeout_ns": TIMEOUT_NS,
            },
            "inout_note": (
                "runner copies out_init.bin into the output BO and lists an "
                "inout buffer only in out_bo_handles."
            ),
        },
        "coverage": coverage,
        "cases": sorted(entries, key=lambda entry: entry["case"]),
        "not_bundled": [
            {
                "source_cases": ["int8_average", "int16_average"],
                "reason": (
                    "Source labels the FP17-reciprocal integer average as an inexact "
                    "negative control; expected_inexact values are recorded device "
                    "observations, not host-derivable. Exact integer average is covered "
                    "by the Q16 reciprocal cases."
                ),
            },
            {
                "source_cases": [
                    "maximum_indices_padding_stride",
                    "maximum_indices_kernel16",
                ],
                "reason": (
                    "probe_only INDEX_EN cases; source records non-window-local phase "
                    "and modulo-8 coordinate aliasing that are not host-derivable. The "
                    "clean maximum_indices case is bundled; the padded 3x3/stride-2 "
                    "geometry is bundled without INDEX_EN."
                ),
            },
            {
                "source_cases": ["strided_input_notch_0", "strided_input_notch_2"],
                "reason": (
                    "probe_only explicit RDMA line/surface stride and notch "
                    "experiments outside the requested small-shape mode matrix."
                ),
            },
            {
                "source_cases": ["padding_7", "kernel_stride_16"],
                "reason": (
                    "larger isolated probes (8x8 kernel/pad7, 16x16 kernel/stride); "
                    "the requested small-shape matrix uses 1x1/2x2/3x3/3x5 cases."
                ),
            },
            {
                "source_cases": [],
                "subject": "integer padded pooling",
                "reason": (
                    "the source hardcoded matrix has no padded INT8/INT16 case; "
                    "padded windows are covered by FP16 only. No integer padded "
                    "variant was invented without source evidence."
                ),
            },
            {
                "source_cases": [],
                "subject": "unlisted mode combinations",
                "reason": (
                    "this is a source-grounded subset, not a full Cartesian product; "
                    "combinations absent from the source matrix were not invented."
                ),
            },
            {
                "source_cases": [
                    "int8_average_recip_q16_2x3",
                    "int16_average_recip_q16_2x3",
                ],
                "reason": "2x3 geometry is not in the requested 2x2/3x3 matrix.",
            },
            {
                "source_cases": [
                    "multi_pass_average",
                    "multi_pass_maximum",
                    "multi_pass_minimum",
                ],
                "reason": (
                    "three fenced linked submissions per case; these single-task "
                    "job.json bundles do not express the linked ordering."
                ),
            },
        ],
        "artifacts": artifacts,
    }
    (BASE / "manifest.json").write_bytes(json_bytes(manifest))
    print(
        f"prepared {summary['total']} cases ({summary['ready']} READY, "
        f"{summary['blocked']} BLOCKED) under {BASE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
