#!/usr/bin/env python3
"""Prepare device-free Rocket jobs from the RK3588 vendor-ABI conv/GEMM examples.

The source examples build raw 64-bit PC command QWORDs with the vendor RKNPU
DRM ABI.  Mainline Rocket accepts a task as (regcmd address, regcmd count) and
does not expose the vendor task descriptor fields.  This script extracts the
pure register builders from the source examples, builds one task per selected
single-core case, leaves the DMA address fields symbolic, and emits the bundle
format documented in ../CAPTURE_FORMAT.md.

It never opens /dev/dri, never imports a vendor ioctl path and never talks to a
board.  Run it with /usr/bin/python3 because that interpreter has NumPy on this
host.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve()
FAMILY_DIR = HERE.parents[1]
CASES_DIR = FAMILY_DIR / "cases"
EXAMPLES = Path("/home/fedora/rk3588/examples")
REPO = Path("/home/fedora/rk3588")
FPGA_REPO = Path("/home/fedora/rknpu-fpga")

# Symbolic, 16-byte aligned DMA addresses.  Every occurrence in a command
# stream must be replaced by a value32 patch.  Buffers are then allocated by
# the board worker and patched with their real 32-bit DMA addresses.
SYM_INPUT = 0x10000000
SYM_WEIGHT = 0x20000000
SYM_OUTPUT = 0x30000000
SYMBOLIC = {"input": SYM_INPUT, "weight": SYM_WEIGHT, "output": SYM_OUTPUT}

PC = 0x0081
PC_REG = 0x0101
VERSION = 0x0041
ROCKET_MAX_REGCMDS = (0xFFFF + 1) * 2

# The vendor task descriptor stores regcfg_amount, and the vendor driver asks
# the PC unit for regcfg_amount + RKNPU_PC_DATA_EXTRA_AMOUNT (4) QWORDs.  The
# 4 QWORDs are the PC chain tail written immediately after the body.  Rocket
# computes the PC amount directly from regcmd_count, so the equivalent Rocket
# count is body_qwords + 4.  This covers exactly the bytes the vendor driver
# executes, including the terminal PC_BASE_ADDRESS=0 / PC_AMOUNTS=0 / VERSION /
# OPERATION_ENABLE tail.
PC_CHAIN_TAIL_QWORDS = 4


def E(target: int, reg_addr: int, value: int) -> int:
    return (target << 48) | ((value & 0xFFFFFFFF) << 16) | (reg_addr & 0xFFFF)


# conv.py, conv_gemm.py and conv_legacy.py write PC_BASE_ADDRESS=0 first.
TERMINAL_TAIL_PC_BASE_ZERO = (
    E(PC_REG, 0x0010, 0),
    E(PC_REG, 0x0014, 0),
    E(VERSION, 0x0000, 0),
    E(PC, 0x0008, (6 << 1) | 1),
)
# gemm.py uses an explicit target-0x0001 NOP separator instead.
TERMINAL_TAIL_NOP = (
    E(0x0001, 0x0000, 0),
    E(PC_REG, 0x0014, 0),
    E(VERSION, 0x0000, 0),
    E(PC, 0x0008, (6 << 1) | 1),
)
TERMINAL_TAILS = {
    "pc_base_zero": TERMINAL_TAIL_PC_BASE_ZERO,
    "nop_separator": TERMINAL_TAIL_NOP,
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def align_up(value: int, align: int) -> int:
    return (value + align - 1) // align * align


def load_defs(path: Path) -> dict[str, Any]:
    """Execute imports/classes/functions/constant assignments, not device calls.

    gemm.py and conv_legacy.py open /dev/dri at module import time.  The pure
    register builders do not need those allocations, so keep only definitions
    and assignments whose value contains no call.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body.append(node)
        elif isinstance(node, ast.Assign):
            if not any(isinstance(child, ast.Call) for child in ast.walk(node.value)):
                body.append(node)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None and not any(
                    isinstance(child, ast.Call) for child in ast.walk(node.value)):
                body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    namespace: dict[str, Any] = {
        "__file__": str(path),
        "__name__": "loaded_" + path.stem,
        "__builtins__": __builtins__,
    }
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def import_conv_py() -> dict[str, Any]:
    """conv.py only imports its planner at module load; it does not open DRM."""
    if str(EXAMPLES) not in sys.path:
        sys.path.insert(0, str(EXAMPLES))
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import conv  # type: ignore
    return vars(conv)


def source_info(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256(path),
        "lines": len(path.read_text().splitlines()),
    }


def append_tail(body: list[int], tail_style: str) -> list[int]:
    return list(body) + list(TERMINAL_TAILS[tail_style])


def find_patches(words: list[int]) -> list[dict[str, Any]]:
    """Replace only real DMA-address fields, and reject stray symbols.

    Address-bearing registers used by these sources:
      CNA_FEATURE_DATA_ADDR  (0x0201, 0x1070)
      CNA_DCOMP_ADDR0        (0x0201, 0x1110)
      DPU_DST_BASE_ADDR      (0x1001, 0x4020)
      RDMA_SRC_BASE_ADDR     (0x2001, 0x5018)
      RDMA_EW_BASE_ADDR      (0x2001, 0x5038)
    """
    address_fields = {
        (0x0201, 0x1070): "input",
        (0x0201, 0x1110): "weight",
        (0x1001, 0x4020): "output",
        (0x2001, 0x5018): "input",
        (0x2001, 0x5038): "weight",
    }
    patches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, word in enumerate(words):
        target = (word >> 48) & 0xFFFF
        offset = word & 0xFFFF
        value = (word >> 16) & 0xFFFFFFFF
        key = (target, offset)
        if key in address_fields:
            name = address_fields[key]
            if value != SYMBOLIC[name]:
                raise ValueError(
                    f"regcmd[{idx}] address field {key} has 0x{value:08x}, "
                    f"expected symbolic {name}=0x{SYMBOLIC[name]:08x}")
            patches.append({"regcmd_index": idx, "buffer": name, "kind": "value32"})
            seen.add(name)
            continue
        for name, symbol in SYMBOLIC.items():
            if value == symbol:
                raise ValueError(
                    f"regcmd[{idx}] non-address field {key} contains symbolic "
                    f"{name}=0x{symbol:08x}")
    missing = set(SYMBOLIC) - seen
    if missing:
        raise ValueError(f"no address field found for buffers: {sorted(missing)}")
    return patches


def pack_words(words: list[int]) -> bytes:
    return b"".join(int(word).to_bytes(8, "little") for word in words)


def write_case(
    case: str,
    source_example: Path,
    source_lines: list[str],
    shape: str,
    description: str,
    body_regs: list[int],
    input_bytes: bytes,
    weight_bytes: bytes,
    expected_logical: bytes,
    expected_dtype: str,
    expected_shape: list[int],
    output_bytes: int,
    oracle: dict[str, Any],
    task_repeats: int = 1,
    extra_manifest: dict[str, Any] | None = None,
    vendor_task_fields: dict[str, Any] | None = None,
    tail_style: str = "pc_base_zero",
) -> dict[str, Any]:
    case_dir = CASES_DIR / case
    case_dir.mkdir(parents=True, exist_ok=True)

    if tail_style not in TERMINAL_TAILS:
        raise ValueError(f"unknown tail style {tail_style}")
    body_words = len(body_regs)
    words = append_tail(body_regs, tail_style)
    vendor_fetch_words = 2 * ((body_words + 4 + 2 - 1) // 2)
    parity_pad_words = vendor_fetch_words - len(words)
    if parity_pad_words not in (0, 1):
        raise ValueError(f"unexpected parity pad {parity_pad_words}")
    if parity_pad_words:
        # The vendor regcmd BO is zero-filled.  The RK3588 PC unit fetches
        # two QWORDs per PC_DATA_AMOUNT unit, so an odd body+tail length
        # fetches one extra zero QWORD.  Keep that zero pad inside the bundle
        # so Rocket never reads past regcmd.bin.
        words.append(0)
    regcmd_words = len(words)
    if regcmd_words != vendor_fetch_words or regcmd_words % 2:
        raise ValueError("regcmd fetch length is not the even vendor length")
    regcmd_bytes = pack_words(words)
    patches = find_patches(words)
    if any(p["regcmd_index"] >= regcmd_words for p in patches):
        raise ValueError("patch outside task range")

    input_size = max(4096, len(input_bytes))
    weight_size = max(4096, len(weight_bytes))
    output_size = max(4096, output_bytes)
    input_blob = input_bytes.ljust(input_size, b"\x00")
    weight_blob = weight_bytes.ljust(weight_size, b"\x00")

    (case_dir / "regcmd.bin").write_bytes(regcmd_bytes)
    (case_dir / "input.bin").write_bytes(input_blob)
    (case_dir / "weight.bin").write_bytes(weight_blob)
    (case_dir / "expected.bin").write_bytes(expected_logical)

    tasks = [
        {"regcmd_offset_words": 0, "regcmd_words": regcmd_words}
        for _ in range(task_repeats)
    ]
    job = {
        "case": case,
        "source_example": str(source_example),
        "description": description,
        "timeout_ns": 6_000_000_000,
        "tasks": tasks,
        "buffers": [
            {"name": "input", "size": input_size, "input": "input.bin", "direction": "in"},
            {"name": "weight", "size": weight_size, "input": "weight.bin", "direction": "in"},
            {"name": "output", "size": output_size, "direction": "out", "output": "output.bin"},
        ],
        "patches": patches,
    }
    (case_dir / "job.json").write_text(json.dumps(job, indent=2, sort_keys=True) + "\n")

    record: dict[str, Any] = {
        "case": case,
        "status": "READY",
        "case_dir": str(case_dir.relative_to(FAMILY_DIR)),
        "source_example": str(source_example),
        "source_example_sha256": sha256(source_example),
        "source_lines": source_lines,
        "shape": shape,
        "description": description,
        "oracle": oracle,
        "rocket_tasks": tasks,
        "vendor_task_descriptor": {
            "regcfg_amount_qwords": body_words,
            "vendor_pc_data_extra_qwords": PC_CHAIN_TAIL_QWORDS,
            "terminal_tail_style": tail_style,
            "vendor_fetch_qwords": vendor_fetch_words,
            "parity_pad_qwords": parity_pad_words,
            "rocket_regcmd_count_qwords": regcmd_words,
            **(vendor_task_fields or {}),
            "rocket_drops": [
                "op_idx", "enable_mask", "int_mask", "int_clear",
                "flags", "regcfg_offset",
            ],
        },
        "patches": patches,
        "hashes": {
            "job.json": sha256(case_dir / "job.json"),
            "regcmd.bin": sha256(case_dir / "regcmd.bin"),
            "input.bin": sha256(case_dir / "input.bin"),
            "weight.bin": sha256(case_dir / "weight.bin"),
            "expected.bin": sha256(case_dir / "expected.bin"),
        },
        "sizes": {
            "regcmd_bytes": len(regcmd_bytes),
            "input_buffer_bytes": input_size,
            "weight_buffer_bytes": weight_size,
            "output_buffer_bytes": output_size,
            "expected_logical_bytes": len(expected_logical),
        },
        "expected_oracle": {
            "dtype": expected_dtype,
            "shape": expected_shape,
        },
    }
    if extra_manifest:
        record.update(extra_manifest)
    return record


def expected_conv_logical(
    input_nchw: np.ndarray,
    weight_local: np.ndarray,
    batch: int,
    in_c: int,
    in_h: int,
    in_w: int,
    out_c: int,
    kh: int,
    kw: int,
    groups: int,
    dtype: Any,
) -> np.ndarray:
    """FP64 convolution oracle with the source's per-group local weight layout.

    `weight_local` is (out_c, in_c // groups, kh, kw), exactly the shape the
    source passes to compute_expected_nchw.  Group g uses local channel
    ic - g*in_c/groups, not the absolute input channel.
    """
    out_h, out_w = in_h - kh + 1, in_w - kw + 1
    expected = np.zeros((batch, out_c, out_h, out_w), dtype=np.float64)
    i64 = input_nchw.astype(np.float64)
    w64 = weight_local.astype(np.float64)
    for n in range(batch):
        for g in range(groups):
            ic0 = g * in_c // groups
            ic1 = (g + 1) * in_c // groups
            oc0 = g * out_c // groups
            oc1 = (g + 1) * out_c // groups
            window = np.lib.stride_tricks.sliding_window_view(
                i64[n, ic0:ic1], (kh, kw), axis=(1, 2))
            # window: (ic_group, out_h, out_w, kh, kw)
            block = np.einsum(
                "cyxij,ocij->oyx", window, w64[oc0:oc1], optimize=True)
            expected[n, oc0:oc1] = block
    return expected.astype(dtype)


def conv_gemm_case(
    ns: dict[str, Any],
    case: str,
    shape: dict[str, Any],
    source_lines: list[str],
    description: str,
) -> dict[str, Any]:
    batch = shape["batch"]
    in_c = shape["in_c"]
    in_h = shape["in_h"]
    in_w = shape["in_w"]
    out_c = shape["out_c"]
    weight_in_c = shape["weight_in_c"]
    kh = shape["kh"]
    kw = shape["kw"]
    groups = shape["groups"]
    p = ns["_conv_params"](1, in_c, in_h, in_w, out_c, kh, kw, groups)
    is_spatial = kh != 1 or kw != 1
    grouped_spatial = ns["_is_grouped_spatial"](in_c, out_c, kh, kw, groups)

    np.random.seed(42)
    in_size = batch * in_c * in_h * in_w
    wt_size = out_c * weight_in_c * kh * kw
    input_nchw = np.arange(1, in_size + 1, dtype=np.float32).reshape(
        batch, in_c, in_h, in_w).astype(np.float16)
    weight_nchw = np.arange(wt_size, 0, -1, dtype=np.float32).reshape(
        out_c, weight_in_c, kh, kw).astype(np.float16)
    if ns["_is_depthwise"](in_c, out_c, groups):
        weight_full = np.zeros((out_c, in_c, kh, kw), dtype=np.float16)
        for oc in range(out_c):
            weight_full[oc, oc] = weight_nchw[oc, 0]
    else:
        weight_full = ns["_expand_grouped_weights"](
            weight_nchw, in_c, out_c, kh, kw, groups)
    if grouped_spatial:
        weight_full = ns["_reorder_grouped_spatial_weights_block16"](
            weight_full, out_c, in_c, kh, kw)

    weight_flat = ns["pack_conv_weights_for_shape"](
        weight_full, out_c, in_c, kh, kw, p["align_c"], groups)
    input_flat = ns["_pack_conv_input_fp16"](input_nchw[0], p)
    regs = ns["make_conv2d_regs"](
        1, in_c, in_h, in_w, out_c, kh, kw,
        SYM_INPUT, SYM_WEIGHT, SYM_OUTPUT, groups=groups)

    hw_fp16 = True  # conv_gemm.py make_conv2d_regs always selects FP16 output
    dtype = np.float16
    c2 = 8
    out_count = ((p["align_out_c"] + c2 - 1) // c2) * p["out_width_stride"] * c2
    out_bytes = out_count * 2
    expected = expected_conv_logical(
        input_nchw, weight_nchw, batch, in_c, in_h, in_w, out_c, kh, kw,
        groups, dtype)
    unpack = ("_unpack_grouped_spatial_output" if grouped_spatial
              else "_unpack_flat_1x1_output")
    oracle = {
        "kind": "host-numpy",
        "labelled": "host-side NumPy FP64 accumulation rounded to FP16; not a device capture",
        "file": "expected.bin",
        "dtype": "float16",
        "shape": [batch, out_c, p["out_h"], p["out_w"]],
        "layout": "NCHW logical output; unpack output.bin with conv_gemm.py " + unpack,
        "tolerance_abs": 0.2,
        "source_function": "host-side FP64 sliding-window einsum equivalent to conv_gemm.py:compute_expected_nchw",
    }
    extra = {
        "source_shape_parameters": shape,
        "conv_layout": {
            "align_c": p["align_c"], "align_out_c": p["align_out_c"],
            "width_stride": p["width_stride"],
            "out_width_stride": p["out_width_stride"],
            "use_nhwc": p["use_nhwc"], "grouped_spatial": grouped_spatial,
            "hardware_output_dtype": "fp16",
            "hardware_output_elements": out_count,
            "hardware_output_bytes": out_bytes,
            "unpack_c2": c2,
            "unpack_function": unpack,
        },
        "repeat_submissions": 2 if ns["_direct_submit_repeat"](
            p, batch, is_spatial, 1) == 2 else 1,
    }
    return write_case(
        case, EXAMPLES / "conv_gemm.py", source_lines,
        f"b{batch}_c{in_c}_h{in_h}_w{in_w}_oc{out_c}_wic{weight_in_c}"
        f"_k{kh}x{kw}_g{groups}",
        description, regs, input_flat.tobytes(), weight_flat.tobytes(),
        expected.tobytes(), "float16",
        [batch, out_c, p["out_h"], p["out_w"]], out_bytes, oracle,
        task_repeats=extra["repeat_submissions"], extra_manifest=extra,
        vendor_task_fields={
            "op_idx": 1, "enable_mask": 0xD,
            "int_mask": 0x300, "int_clear": 0x1FFFF,
        })


def conv_legacy_case(
    ns: dict[str, Any],
    case: str,
    shape: dict[str, Any],
    source_lines: list[str],
    description: str,
) -> dict[str, Any]:
    batch = shape["batch"]
    in_c = shape["in_c"]
    in_h = shape["in_h"]
    in_w = shape["in_w"]
    out_c = shape["out_c"]
    weight_in_c = shape["weight_in_c"]
    kh = shape["kh"]
    kw = shape["kw"]
    groups = shape["groups"]
    p = ns["_conv_params"](1, in_c, in_h, in_w, out_c, kh, kw, groups)
    is_spatial = kh != 1 or kw != 1
    grouped_spatial = ns["_is_grouped_spatial"](in_c, out_c, kh, kw, groups)

    np.random.seed(42)
    input_nchw = np.random.uniform(
        -2, 2, (batch, in_c, in_h, in_w)).astype(np.float16)
    weight_nchw = np.random.uniform(
        -2, 2, (out_c, weight_in_c, kh, kw)).astype(np.float16)
    if ns["_is_depthwise"](in_c, out_c, groups):
        weight_full = np.zeros((out_c, in_c, kh, kw), dtype=np.float16)
        for oc in range(out_c):
            weight_full[oc, oc] = weight_nchw[oc, 0]
    else:
        weight_full = ns["_expand_grouped_weights"](
            weight_nchw, in_c, out_c, kh, kw, groups)
    if grouped_spatial:
        weight_full = ns["_reorder_grouped_spatial_weights_block16"](
            weight_full, out_c, in_c, kh, kw)

    hw_fp16 = (is_spatial or p["is_depthwise"] or out_c >= 128
               or p["out_width_stride"] > 992)
    dtype = np.float16 if hw_fp16 else np.float32
    c2 = 8 if hw_fp16 else 4
    out_count = ((p["align_out_c"] + c2 - 1) // c2) * p["out_width_stride"] * c2
    out_bytes = out_count * (2 if hw_fp16 else 4)
    weight_flat = ns["pack_conv_weights_for_shape"](
        weight_full, out_c, in_c, kh, kw, p["align_c"], groups)
    input_flat = ns["_pack_conv_input_fp16"](input_nchw[0], p)
    regs = ns["make_conv2d_regs"](
        1, in_c, in_h, in_w, out_c, kh, kw,
        SYM_INPUT, SYM_WEIGHT, SYM_OUTPUT, groups=groups, out_fp16=hw_fp16)
    expected = expected_conv_logical(
        input_nchw, weight_nchw, batch, in_c, in_h, in_w, out_c, kh, kw,
        groups, dtype)
    unpack = ("_unpack_grouped_spatial_output" if grouped_spatial
              else "_unpack_flat_1x1_output")
    oracle = {
        "kind": "host-numpy",
        "labelled": "host-side NumPy FP64 accumulation rounded to the hardware output dtype; not a device capture",
        "file": "expected.bin",
        "dtype": "float16" if hw_fp16 else "float32",
        "shape": [batch, out_c, p["out_h"], p["out_w"]],
        "layout": "NCHW logical output; unpack output.bin with conv_legacy.py " + unpack,
        "tolerance_abs": 0.2,
        "source_function": "host-side FP64 sliding-window einsum equivalent to conv_legacy.py:compute_expected_nchw",
    }
    extra = {
        "source_shape_parameters": shape,
        "conv_layout": {
            "align_c": p["align_c"], "align_out_c": p["align_out_c"],
            "width_stride": p["width_stride"],
            "out_width_stride": p["out_width_stride"],
            "use_nhwc": p["use_nhwc"], "grouped_spatial": grouped_spatial,
            "hardware_output_dtype": "fp16" if hw_fp16 else "fp32",
            "hardware_output_elements": out_count,
            "hardware_output_bytes": out_bytes,
            "unpack_c2": c2,
            "unpack_function": unpack,
        },
        "repeat_submissions": 2 if ns["_direct_submit_repeat"](
            p, batch, is_spatial, 1) == 2 else 1,
    }
    return write_case(
        case, EXAMPLES / "conv_legacy.py", source_lines,
        f"b{batch}_c{in_c}_h{in_h}_w{in_w}_oc{out_c}_wic{weight_in_c}"
        f"_k{kh}x{kw}_g{groups}",
        description, regs, input_flat.tobytes(), weight_flat.tobytes(),
        expected.tobytes(), "float16" if hw_fp16 else "float32",
        [batch, out_c, p["out_h"], p["out_w"]], out_bytes, oracle,
        task_repeats=extra["repeat_submissions"], extra_manifest=extra,
        vendor_task_fields={
            "op_idx": 1, "enable_mask": 0xD,
            "int_mask": 0x300, "int_clear": 0x1FFFF,
        })


def conv_py_case(
    conv: dict[str, Any],
    case: str,
    shape_name: str,
    source_lines: list[str],
    description: str,
) -> dict[str, Any]:
    s = conv["shape_from_name"](shape_name)
    conv["validate_phase_a_shape"](s)
    p = conv["_conv_params"](s)
    np.random.seed(42)
    inp = np.random.uniform(
        -2, 2, (s["batch"], s["in_c"], s["in_h"], s["in_w"])).astype(np.float16)
    wt = np.random.uniform(
        -2, 2, (s["out_c"], s["weight_in_c"], s["kh"], s["kw"])).astype(np.float16)
    weight_full = np.zeros((s["out_c"], s["in_c"], s["kh"], s["kw"]), dtype=np.float16)
    for oc in range(s["out_c"]):
        weight_full[oc] = wt[oc]
    hw_fp16 = (p["is_spatial"] or s["out_c"] >= 128
               or p["out_width_stride"] > 992 or conv["_is_pointwise_wide"](s))
    dtype = np.float16 if hw_fp16 else np.float32
    c2 = 8 if hw_fp16 else 4
    out_count = ((p["align_out_c"] + c2 - 1) // c2) * p["out_width_stride"] * c2
    out_bytes = out_count * (2 if hw_fp16 else 4)
    input_flat = conv["pack_input"](inp[0], p)
    weight_flat = conv["pack_weights"](weight_full, s, p)
    regs = conv["make_regs"](s, p, SYM_INPUT, SYM_WEIGHT, SYM_OUTPUT, hw_fp16)
    expected = expected_conv_logical(
        inp, wt, s["batch"], s["in_c"], s["in_h"], s["in_w"],
        s["out_c"], s["kh"], s["kw"], s["groups"], dtype)
    oracle = {
        "kind": "host-numpy",
        "labelled": "host-side NumPy FP64 accumulation rounded to the hardware output dtype; not a device capture",
        "file": "expected.bin",
        "dtype": "float16" if hw_fp16 else "float32",
        "shape": [s["batch"], s["out_c"], p["out_h"], p["out_w"]],
        "layout": "NCHW logical output; unpack output.bin with conv.py unpack_output",
        "tolerance_abs": 0.12 if hw_fp16 else 0.1,
        "source_function": "host-side FP64 sliding-window einsum equivalent to conv.py:compute_expected_nchw",
    }
    extra = {
        "source_shape_parameters": s,
        "conv_layout": {
            "align_c": p["align_c"], "align_out_c": p["align_out_c"],
            "width_stride": p["width_stride"],
            "out_width_stride": p["out_width_stride"],
            "use_nhwc": p["use_nhwc"], "grouped_spatial": False,
            "hardware_output_dtype": "fp16" if hw_fp16 else "fp32",
            "hardware_output_elements": out_count,
            "hardware_output_bytes": out_bytes,
            "unpack_c2": c2,
            "unpack_function": "unpack_output",
        },
        "planner": {
            "rows": len(conv["planner"].descriptor_rows_for_shape(s)),
            "family": conv["planner"].descriptor_rows_for_shape(s)[0]["family"],
            "split_method": conv["planner"].descriptor_rows_for_shape(s)[0]["split_method"],
            "phase_a_validated": True,
        },
    }
    return write_case(
        case, EXAMPLES / "conv.py", source_lines,
        f"b{s['batch']}_c{s['in_c']}_h{s['in_h']}_w{s['in_w']}_oc{s['out_c']}"
        f"_wic{s['weight_in_c']}_k{s['kh']}x{s['kw']}_g{s['groups']}",
        description, regs, input_flat.tobytes(), weight_flat.tobytes(),
        expected.tobytes(), "float16" if hw_fp16 else "float32",
        [s["batch"], s["out_c"], p["out_h"], p["out_w"]], out_bytes, oracle,
        extra_manifest=extra,
        vendor_task_fields={
            "op_idx": 1, "enable_mask": 0xD,
            "int_mask": 0x300, "int_clear": 0x1FFFF,
        })


def gemm_case(
    ns: dict[str, Any],
    case: str,
    m: int,
    n: int,
    k: int,
    a: np.ndarray,
    b: np.ndarray,
    source_lines: list[str],
    description: str,
    main_table: bool,
) -> dict[str, Any]:
    align_in, align_out, _ = ns["_gemm_layout"](m, n, k)

    input_packed = np.zeros(align_in * m, dtype=np.float16)
    input_packed.reshape(m, align_in)[:, :k] = a[:, :k]
    weight = np.zeros((align_out, align_in), dtype=np.float16)
    weight_packed = np.zeros(align_out * align_in, dtype=np.float16)
    weight[:n, :k] = b.T[:n, :k]
    weight_packed[:] = weight.reshape(
        align_out // 16, 16, align_in // 32, 32).transpose(0, 2, 1, 3).ravel()

    regs = ns["make_gemm_regs"](
        m, n, k, SYM_INPUT, SYM_WEIGHT, SYM_OUTPUT)
    expected = (a.astype(np.float64) @ b.astype(np.float64)).astype(np.float32)
    surface = np.zeros((m, align_out), dtype=np.float32)
    surface[:, :n] = expected
    out_bytes = max(4096, m * align_out * 4)
    oracle = {
        "kind": "host-numpy",
        "labelled": "host-side NumPy FP64 matmul rounded to FP32; not a device capture",
        "file": "expected.bin",
        "dtype": "float32",
        "shape": [m, n],
        "layout": f"logical MxN; raw output surface is Mx{align_out} FP32 with row stride {align_out}",
        "expected_surface_file": "expected_surface.bin",
        "expected_surface_shape": [m, align_out],
        "tolerance_abs": 0.1,
        "source_function": "gemm.py:run_gemm",
    }
    extra = {
        "gemm_layout": {
            "m": m, "n": n, "k": k,
            "align_in": align_in, "align_out": align_out,
            "input_row_bytes": align_in * 2,
            "output_row_bytes": align_out * 4,
            "output_elements": m * align_out,
            "output_bytes": m * align_out * 4,
            "main_table_case": main_table,
        },
    }
    # write_case owns the normal files; add the raw-surface oracle afterwards.
    record = write_case(
        case, EXAMPLES / "gemm.py", source_lines,
        f"m{m}_n{n}_k{k}", description, regs,
        input_packed.tobytes(), weight_packed.tobytes(),
        expected.tobytes(), "float32", [m, n], out_bytes, oracle,
        extra_manifest=extra,
        vendor_task_fields={
            "op_idx": 0, "enable_mask": 0xD,
            "int_mask": 0x300, "int_clear": 0x1FFFF,
        },
        tail_style="nop_separator")
    case_dir = CASES_DIR / case
    surface_blob = surface.tobytes().ljust(out_bytes, b"\x00")
    (case_dir / "expected_surface.bin").write_bytes(surface_blob)
    record["hashes"]["expected_surface.bin"] = sha256(case_dir / "expected_surface.bin")
    record["sizes"]["expected_surface_bytes"] = len(surface_blob)
    return record


def blocked_case(
    case: str,
    source_example: Path,
    source_lines: list[str],
    shape: str,
    description: str,
    reason: str,
    evidence: list[str],
) -> dict[str, Any]:
    case_dir = CASES_DIR / case
    case_dir.mkdir(parents=True, exist_ok=True)
    text = (
        f"# BLOCKED: {case}\n\n"
        f"Source: `{source_example}`\n\n"
        f"Shape: `{shape}`\n\n"
        f"## Reason\n\n{reason}\n\n"
        "## Exact evidence\n\n" + "\n".join(f"- {item}" for item in evidence) + "\n"
    )
    (case_dir / "BLOCKED.md").write_text(text)
    return {
        "case": case,
        "status": "BLOCKED",
        "case_dir": str(case_dir.relative_to(FAMILY_DIR)),
        "source_example": str(source_example),
        "source_example_sha256": sha256(source_example),
        "source_lines": source_lines,
        "shape": shape,
        "description": description,
        "oracle": {
            "kind": "none",
            "reason": "blocked path is not submitted; no device-free oracle is bound",
        },
        "blocked_reason": reason,
        "evidence": evidence,
        "hashes": {
            "source_example": sha256(source_example),
            "BLOCKED.md": sha256(case_dir / "BLOCKED.md"),
        },
    }


def source_lines_text(path: Path, start: int, end: int) -> str:
    lines = path.read_text().splitlines()
    return "\n".join(f"{i + 1}: {lines[i]}" for i in range(start - 1, end))


def main() -> int:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    gemm = load_defs(EXAMPLES / "gemm.py")
    conv_gemm = load_defs(EXAMPLES / "conv_gemm.py")
    conv_legacy = load_defs(EXAMPLES / "conv_legacy.py")
    conv = import_conv_py()

    records: list[dict[str, Any]] = []

    # --- GEMM: gemm.py -------------------------------------------------
    np.random.seed(42)
    a_m2k1 = np.array([[1], [2]], dtype=np.float16)
    b_k1n2 = np.array([[4, 5]], dtype=np.float16)
    records.append(gemm_case(
        gemm, "gemm_m2_n2_k1", 2, 2, 1, a_m2k1, b_k1n2,
        ["gemm.py:249-407 make_gemm_regs", "gemm.py:465-524 run_gemm",
         "gemm.py:546-596 main test_cases"],
        "FP16 GEMM 2x2x1, exact smallest shape in gemm.py main table; FP32 output",
        main_table=True))

    for case, m, n, k in (
        ("gemm_m1_n16_k32", 1, 16, 32),
        ("gemm_m2_n16_k32", 2, 16, 32),
        ("gemm_m4_n32_k64", 4, 32, 64),
    ):
        np.random.seed(42)
        a = np.random.randn(m, k).astype(np.float16)
        b = np.random.randn(k, n).astype(np.float16)
        records.append(gemm_case(
            gemm, case, m, n, k, a, b,
            ["gemm.py:249-407 make_gemm_regs", "gemm.py:465-524 run_gemm",
             "gemm.py:577-582 host seed-42 generator (commented sweep pattern)"],
            f"FP16 GEMM {m}x{n}x{k}, single task; FP32 output; "
            "shape exercised through the public run_gemm/make_gemm_regs path "
            "(not present in the tiny main test_cases table)",
            main_table=False))

    # --- Conv: conv_gemm.py -------------------------------------------
    conv_gemm_shapes = [
        ("conv_1x1_c1_oc6_h4w4",
         dict(name="conv2d_1x6_1x1_4x4", batch=1, in_c=1, in_h=4, in_w=4,
              out_c=6, weight_in_c=1, kh=1, kw=1, groups=1),
         ["conv_gemm.py:1243 shape table", "conv_gemm.py:457-591 make_conv2d_regs",
          "conv_gemm.py:924-1095 _run_conv2d_inner"],
         "FP16 1x1 conv, C1/H4/W4 -> OC6, NHWC pack, single task"),
        ("conv_grouped_3x3_c4_oc4_g2_h5w5",
         dict(name="conv2d_b1_c4_h5_w5_oc4_wic2_k3x3_g2", batch=1, in_c=4,
              in_h=5, in_w=5, out_c=4, weight_in_c=2, kh=3, kw=3, groups=2),
         ["conv_gemm.py:1288 shape table", "conv_gemm.py:457-591 make_conv2d_regs",
          "conv_gemm.py:924-1095 _run_conv2d_inner"],
         "FP16 grouped 3x3 conv, C4/OC4/G2, H5/W5 -> H3/W3, single task"),
    ]
    for case, shape, lines, desc in conv_gemm_shapes:
        records.append(conv_gemm_case(conv_gemm, case, shape, lines, desc))

    # --- Conv: conv_legacy.py -----------------------------------------
    records.append(conv_legacy_case(
        conv_legacy, "conv_legacy_3x3_c4_oc4_h9w9",
        dict(name="conv2d_b1_c4_h9_w9_oc4_wic4_k3x3_g1", batch=1, in_c=4,
             in_h=9, in_w=9, out_c=4, weight_in_c=4, kh=3, kw=3, groups=1),
        ["conv_legacy.py:855 shape table", "conv_legacy.py:456-593 make_conv2d_regs",
         "conv_legacy.py:648-828 run_conv2d"],
        "FP16 3x3 valid conv from conv_legacy.py, C4/H9/W9 -> OC4; "
        "seed-42 random inputs/weights keep the FP16 oracle finite"))
    records.append(conv_legacy_case(
        conv_legacy, "conv_depthwise_3x3_c3_oc3_h11w28",
        dict(name="conv2d_b1_c3_h11_w28_oc3_wic1_k3x3_g3", batch=1, in_c=3,
             in_h=11, in_w=28, out_c=3, weight_in_c=1, kh=3, kw=3, groups=3),
        ["conv_legacy.py:861 shape table", "conv_legacy.py:456-593 make_conv2d_regs",
         "conv_legacy.py:648-828 run_conv2d",
         "conv_legacy.py:436-443 _direct_submit_repeat (=2 for depthwise spatial)"],
        "FP16 depthwise 3x3 conv from conv_legacy.py, C3/OC3/G3, "
        "H11/W28 -> H9/W26; source intentionally submits the same task twice; "
        "seed-42 random inputs/weights keep the FP16 oracle finite"))

    # --- Conv: conv.py planner ----------------------------------------
    records.append(conv_py_case(
        conv, "conv_py_3x3_c32_oc128_h14w14_fullsetup",
        "b1_c32_h14_w14_oc128_wic32_k3x3_g1_s1_pvalid",
        ["conv.py:536 supported LIST_SHAPES entry",
         "conv.py:713-772 make_regs full setup row",
         "conv.py:1446-1471 validate_phase_a_shape",
         "conv.py:2763-2846 run_shape single setup/NONE path"],
        "FP16 3x3 valid conv from conv.py planner (full 108-QWORD setup row), "
        "C32/H14/W14 -> OC128/H12/W12, single setup/NONE task"))

    # --- BLOCKED: vendor-only multi-core / PC-chain paths --------------
    byk_block = blocked_case(
        "conv_byk_c160_h14w14_oc320_k3x3",
        EXAMPLES / "conv.py",
        ["conv.py:31 EXACT11_BYK_SHAPE",
         "conv.py:1766-1797 run_exact11_byk_shape submit",
         "conv.py:1501-1530 exact_byk_layout PC chain",
         "conv.py:1251-1270 write_exact11_byk_tasks"],
        "b1_c160_h14_w14_oc320_wic160_k3x3_g1_s1_pvalid",
        "Vendor EXACT11 BY_K 3x3 conv path: 11-row PC chain, three tasks "
        "distributed one each to cores 0/1/2.",
        "Vendor BY_K conv path uses explicit multi-core task distribution "
        "and a multi-task PC chain. Rocket has no core_mask/subcore_task "
        "fields and no bundle patch kind for the runtime regcmd address in "
        "PC_BASE_ADDRESS.",
        [
            "Source calls npu_submit(..., task_count=3, core_mask=0, "
            "subcores=((0,1),(0,1),(0,1),(0,0),(0,0))). `core_mask=0` is "
            "RKNPU_CORE_AUTO_MASK and the three subcore entries assign one task "
            "each to three physical cores.",
            "Rocket presents one drm_sched_entity per file and picks one core; "
            "there is no UAPI way to express the 1/1/1 split.",
            "The 11-row layout also writes PC_BASE_ADDRESS to the regcmd BO DMA "
            "address and PC_REGISTER_AMOUNTS to non-zero chain lengths; the "
            "bundle schema can patch only named buffer addresses, not a "
            "self-referential regcmd address.",
        ],
    )
    records.append(byk_block)

    h40_block = blocked_case(
        "conv_h40_c160_h40w40_oc320_k3x3",
        EXAMPLES / "conv.py",
        ["conv.py:36 H40_SPATIAL_BY_Y_SHAPE",
         "conv.py:2331-2358 run_h40_exact17_shape submit",
         "conv.py:1298-1325 write_h40_exact17_tasks PC chain",
         "conv.py:46-49 H40_EXACT17_* tables"],
        "b1_c160_h40_w40_oc320_wic160_k3x3_g1_s1_pvalid",
        "Vendor H40 spatial BY_Y 3x3 conv path: 17 PC-chain rows, six tasks "
        "distributed two each to cores 0/1/2.",
        "Vendor H40 spatial BY_Y conv path distributes six tasks over three "
        "cores and uses 17 PC-chain rows. Rocket cannot express the vendor "
        "core_mask/subcore_task split, and the PC_BASE_ADDRESS rows require "
        "runtime regcmd-address patching that the bundle schema does not have.",
        [
            "Source calls npu_submit(..., task_count=6, core_mask=0, "
            "subcores=((0,2),(0,2),(0,2),(0,0),(0,0))). Two tasks are assigned "
            "to each of cores 0, 1 and 2.",
            "The 17-row layout writes per-row PC_BASE_ADDRESS/"
            "PC_REGISTER_AMOUNTS links and masks 0x0d/0x60.",
            "Rocket's drm_rocket_task has only regcmd and regcmd_count; the "
            "vendor task fields op_idx/enable_mask/int_mask/int_clear and "
            "submit core_mask/subcore_task are absent.",
        ],
    )
    records.append(h40_block)

    # --- Manifest ------------------------------------------------------
    ready = sum(1 for r in records if r["status"] == "READY")
    blocked = sum(1 for r in records if r["status"] == "BLOCKED")
    manifest = {
        "schema": "rk3588-example-capture-manifest-v1",
        "family": "conv-gemm-vendor",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scope": (
            "Device-free Rocket job bundles derived from vendor RKNPU ABI "
            "conv/GEMM examples. No board, vendor ioctl, FPGA or flash action "
            "is performed. READY means the command QWORD stream and task "
            "descriptor are expressible with Rocket's regcmd+count UAPI; it "
            "does not establish numerical correctness on RK3588 or FPGA."
        ),
        "source_revision": {
            "rk3588_git": subprocess.check_output(
                ["git", "-C", str(REPO), "rev-parse", "HEAD"],
                text=True).strip(),
            "rknpu_fpga_git": subprocess.check_output(
                ["git", "-C", str(FPGA_REPO), "rev-parse", "HEAD"],
                text=True).strip(),
            "examples": {
                name: source_info(EXAMPLES / name)
                for name in ("conv.py", "conv_gemm.py", "conv_legacy.py", "gemm.py")
            },
        },
        "tool_versions": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "generator": str(HERE),
            "generator_sha256": sha256(HERE),
            "validator_sha256": sha256(HERE.parent / "validate_bundles.py"),
            "oracle_checker_sha256": sha256(HERE.parent / "check_oracles.py"),
        },
        "rocket_contract": {
            "task_struct": "struct drm_rocket_task { __u32 regcmd; __u32 regcmd_count; }",
            "max_regcmds": ROCKET_MAX_REGCMDS,
            "regcmd_alignment_bytes": 16,
            "vendor_pc_data_extra_qwords": PC_CHAIN_TAIL_QWORDS,
            "count_crosswalk": (
                "vendor fetches 2*ceil((regcfg_amount + 4)/2) QWORDs, "
                "including one zero NOP when body+4 is odd; Rocket computes "
                "(regcmd_count + 1)/2 - 1 PC data units, so regcmd_count is "
                "that even vendor fetch length and regcmd.bin includes the "
                "parity NOP. Regcmd.bin never ends on an odd count."
            ),
            "cores": "Rocket drm_sched_entity selects one core; no vendor core_mask/subcore_task",
        },
        "checked_vendor_only_fields": {
            "memory_sync": (
                "No READY source path calls DRM_IOCTL_RKNPU_MEM_SYNC. The four "
                "listed examples use non-cacheable vendor BOs; Rocket uses "
                "ROCKET_PREP_BO/ROCKET_FINI_BO. The bundle worker owns that "
                "crosswalk, so no command-stream field is affected."
            ),
            "compression": (
                "No READY stream enables weight decompression. CNA_DCOMP_CTRL "
                "(0x1100) is absent from the conv_gemm/conv_legacy/gemm streams "
                "and is zero in the conv.py full-setup row; CNA_DCOMP_ADDR0 "
                "(0x1110) just carries the raw-weight buffer address. No "
                "unsupported compressed-weight field is exercised."
            ),
            "multi_core": (
                "The two BLOCKED conv.py paths use core_mask=0 plus non-empty "
                "subcore_task entries on more than one core; Rocket has no "
                "corresponding task or submit field."
            ),
        },
        "readiness": {"READY": ready, "BLOCKED": blocked, "total": len(records)},
        "cases": records,
    }
    manifest_path = FAMILY_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"manifest": str(manifest_path), "READY": ready,
                      "BLOCKED": blocked}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
