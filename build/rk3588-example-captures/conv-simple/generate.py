#!/usr/bin/env python3
"""Device-free generator for the conv-simple RK3588 capture bundles.

This script only *prepares* bundles.  It never opens a DRM device, never
contacts the board, and never programs an FPGA.  It imports the command
builders from the three named source examples, freezes their packed inputs,
weights and biases into raw byte files, emits a terminal PC record, and
computes a host-side NumPy oracle.

Run with the interpreter that has NumPy on this host:

    /usr/bin/python3 generate.py

The default ``python3`` on this machine (Homebrew 3.14) has no NumPy, so the
script refuses to run without it rather than silently substituting a different
oracle.

Source evidence (sha256 and line ranges are recorded in manifest.json):

  * /home/fedora/rk3588/examples/expt/conv_simple.py
      _conv_params, pack_input, pack_weights, make_regs, compute_expected,
      run_shape (output precision policy), run_shape_rocket (Rocket tail).
  * /home/fedora/rk3588/examples/conv_simple.py
      same generic FP16 builder; used here only as a cross-reference.
  * /home/fedora/rk3588/examples/kernel_6_18/simple_conv.py
      use_shape, pack_input, pack_weights, pack_biases, build_conv_regs,
      split_tasks, expected_output, calc_raw_output_size.
  * /home/fedora/rk3588/examples/kernel_6_18/conv_legacy.py
      shape table entries used to select valid small depthwise/5x5 shapes.

The INT8 module has module-level device setup (``fd = open_rocket_device()``
and several ``mem_allocate`` calls).  We remove exactly that setup block before
executing the module in memory so the pure command builders can be reused
verbatim.  No source file is modified.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import numpy as np
except ModuleNotFoundError as exc:  # pragma: no cover - recorded honestly
    raise SystemExit(
        "NumPy is required for the host-side oracle.  On this host use "
        "/usr/bin/python3 generate.py (the Homebrew python3 has no NumPy)."
    ) from exc

sys.path.insert(0, "/home/fedora/rk3588")
from conv_expt import conv_tile_planner as planner  # noqa: E402


ROOT = Path(__file__).resolve().parent
CASES_DIR = ROOT / "cases"

FP16_SRC = Path("/home/fedora/rk3588/examples/expt/conv_simple.py")
FP16_SRC_ALT = Path("/home/fedora/rk3588/examples/conv_simple.py")
INT8_SRC = Path("/home/fedora/rk3588/examples/kernel_6_18/simple_conv.py")
INT8_SHAPES_SRC = Path("/home/fedora/rk3588/examples/kernel_6_18/conv_legacy.py")

TIMEOUT_NS = 6_000_000_000
FP16_SEED = 42          # matches expt/conv_simple.py::run_shape
INT8_SEED = 1234        # preparation choice; recorded per case

# Address registers that must be patched.  Any occurrence of one of these
# register offsets in a command stream is an address and must be bound to a
# named buffer by job.json.
FP16_ADDRESS_REGS = {
    (0x0201, 0x1070): "input",   # CNA_FEATURE_DATA_ADDR
    (0x0201, 0x1110): "weight",  # CNA_DCOMP_ADDR0
    (0x1001, 0x4020): "out",     # DPU DST_BASE_ADDR
}
INT8_ADDRESS_REGS = {
    (0x0201, 0x1070): "input",   # CNA_FEATURE_DATA_ADDR
    (0x0201, 0x1110): "weight",  # CNA_DCOMP_ADDR0
    (0x1001, 0x4020): "out",     # DPU DST_BASE_ADDR
    (0x2001, 0x5020): "bias",    # RDMA_BS_BASE_ADDR
}

# Terminal PC tails copied from the sources:
#   expt/conv_simple.py::run_shape_rocket lines 780-785 / write_tasks 415-418
#   kernel_6_18/simple_conv.py::write_regs_to_npu_task lines 628-644
FP16_OP_ENABLE = (6 << 1) | 1     # 0x0d
INT8_OP_ENABLE = (14 << 1) | 1    # 0x1d


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_fp16_module():
    spec = importlib.util.spec_from_file_location("conv_simple_expt", FP16_SRC)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {FP16_SRC}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_int8_module():
    """Execute simple_conv.py with only its module-level device setup removed.

    The removed region starts at the literal ``fd = open_rocket_device()``
    assignment and ends immediately before ``def _ceil_div``.  All pure
    functions (pack_input, pack_weights, pack_biases, build_conv_regs,
    expected_output, ...) are reused unchanged.  ``npu_submit`` and
    ``write_buffers`` are never called.
    """
    src = INT8_SRC.read_text(encoding="utf-8")
    start_marker = "\nfd = open_rocket_device()\n"
    end_marker = "\ndef _ceil_div(x, y):"
    if src.count(start_marker) != 1 or src.count(end_marker) != 1:
        raise RuntimeError("simple_conv.py device setup markers changed; refusing to guess")
    start = src.index(start_marker)
    end = src.index(end_marker)
    if end <= start:
        raise RuntimeError("simple_conv.py device setup block is not ordered as expected")
    clean = src[:start] + src[end:]
    mod = {"__name__": "simple_conv_extracted", "__file__": str(INT8_SRC)}
    exec(compile(clean, str(INT8_SRC), "exec"), mod)
    for name in (
        "use_shape", "pack_input", "pack_weights", "pack_biases",
        "build_conv_regs", "split_tasks", "expected_output",
        "calc_raw_output_size", "write_regs_to_npu_task",
    ):
        if name not in mod:
            raise RuntimeError(f"extracted INT8 module is missing {name}")
    return mod


def qword(target: int, reg_addr: int, value: int) -> int:
    """E() from both sources: target[63:48], value[47:16], offset[15:0]."""
    return (target << 48) | ((value & 0xFFFFFFFF) << 16) | (reg_addr & 0xFFFF)


def terminal_tail(op_enable: int) -> list[int]:
    """Four-word terminal PC tail used by both source Rocket paths."""
    return [
        qword(0x0101, 0x0010, 0),  # PC_BASE_ADDRESS = 0
        qword(0x0101, 0x0014, 0),  # PC_REGISTER_AMOUNTS = 0
        qword(0x0041, 0x0000, 0),  # VERSION sentinel
        qword(0x0081, 0x0008, op_enable),
    ]


def split_address_patches(body: list[int], address_regs: dict[tuple[int, int], str]):
    """Return patches and assert every address register is present once."""
    patches = []
    seen = {}
    for index, command in enumerate(body):
        key = ((command >> 48) & 0xFFFF, command & 0xFFFF)
        if key not in address_regs:
            continue
        if (command >> 16) & 0xFFFFFFFF:
            raise AssertionError(
                f"address placeholder at qword {index} is not zero: 0x{command:016x}"
            )
        patches.append(
            {
                "regcmd_index": index,
                "buffer": address_regs[key],
                "kind": "value32",
            }
        )
        seen[key] = seen.get(key, 0) + 1
    missing = sorted(set(address_regs) - set(seen))
    duplicated = {k: v for k, v in seen.items() if v != 1}
    if missing or duplicated:
        raise AssertionError(
            f"address register coverage mismatch missing={missing} duplicated={duplicated}"
        )
    return patches


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_le(path: Path, array: np.ndarray, dtype: str) -> None:
    contiguous = np.ascontiguousarray(array)
    write_bytes(path, contiguous.astype(dtype, copy=False).tobytes(order="C"))


def pack_fp16_expected_raw(logical: np.ndarray, p: dict, out_fp16: bool, out_c: int) -> np.ndarray:
    """Inverse of expt/conv_simple.py::unpack_output.

    logical is (out_c, out_h, out_w).  The raw BO is
    [c1][out_width_stride][c2] in C order, where
    c2 = 8 for FP16 output, 4 for FP32 output, and c1 = align_out_c / c2.
    Our selected shapes have align_out_c == out_c and
    out_width_stride == out_h * out_w, so every raw element is meaningful.
    """
    c2 = 8 if out_fp16 else 4
    c1 = (p["align_out_c"] + c2 - 1) // c2
    if c1 * c2 != out_c:
        raise AssertionError(f"expected raw channel padding: c1={c1} c2={c2} out_c={out_c}")
    if p["out_width_stride"] != p["out_h"] * p["out_w"]:
        raise AssertionError("expected raw spatial padding in selected FP16 shape")
    dtype = np.float16 if out_fp16 else np.float32
    raw = np.zeros(c1 * p["out_width_stride"] * c2, dtype=dtype)
    for group in range(c1):
        for atom in range(p["out_h"] * p["out_w"]):
            for lane in range(c2):
                oc = group * c2 + lane
                raw[(group * p["out_width_stride"] + atom) * c2 + lane] = logical[
                    oc, atom // p["out_w"], atom % p["out_w"]
                ]
    return raw


def pack_int8_expected_raw(logical: np.ndarray, out_w: int, out_h: int, out_c: int) -> np.ndarray:
    """Inverse of kernel_6_18/simple_conv.py::read_output.

    logical is (1, out_h, out_w, out_c) uint8; the raw BO is laid out as
    [channel_group][x][y][16] (note the source's x-before-y reshape), and the
    stored byte is (logical_uint8 - 0x80) & 0xff.
    """
    if out_c % 16:
        raise AssertionError("selected INT8 shape must have out_c multiple of 16")
    raw = np.zeros((out_c // 16) * out_w * out_h * 16, dtype=np.uint8)
    for oc in range(out_c):
        group = oc // 16
        lane = oc % 16
        for y in range(out_h):
            for x in range(out_w):
                raw[((group * out_w + x) * out_h + y) * 16 + lane] = (
                    int(logical[0, y, x, oc]) - 0x80
                ) & 0xFF
    return raw


def base_case_record(case: str, source_example: Path, shape: dict, description: str):
    return {
        "case": case,
        "status": "READY",
        "source_example": str(source_example),
        "source_lines": {},
        "description": description,
        "shape": shape,
        "dtype": {},
        "layout": {},
        "tasks": 1,
        "regcmd_words": 0,
        "buffers": [],
        "patches": [],
        "oracle": None,
        "hashes": {},
        "blocker": None,
    }


def derive_fp16_case(case: str, in_c: int, in_h: int, in_w: int, out_c: int, k: int, description: str):
    mod = load_fp16_module()
    shape = {
        "name": case,
        "batch": 1,
        "in_c": in_c,
        "in_h": in_h,
        "in_w": in_w,
        "out_c": out_c,
        "weight_in_c": in_c,
        "kh": k,
        "kw": k,
        "groups": 1,
        "stride": 1,
    }
    rows = planner.descriptor_rows_for_shape(shape)
    if len(rows) != 1 or rows[0]["split_method"] != "NONE" or rows[0]["family"] != "setup":
        raise AssertionError(f"{case}: planner is not a single NONE/setup row: {rows}")
    if mod._is_pointwise_wide(shape):
        raise AssertionError(f"{case}: pointwise-wide path is disabled by the source")
    p = mod._conv_params(shape)
    out_fp16 = (
        p["is_spatial"]
        or out_c >= 128
        or p["out_width_stride"] > mod.RK_MAX_CONV_FLAT_STRIDE
    )

    np.random.seed(FP16_SEED)
    inp = np.random.uniform(-2, 2, (1, in_c, in_h, in_w)).astype(np.float16)
    wt = np.random.uniform(-2, 2, (out_c, in_c, k, k)).astype(np.float16)
    packed_input = mod.pack_input(inp[0], p).astype(np.float16, copy=False)
    packed_weight = mod.pack_weights(wt, shape, p).astype(np.float16, copy=False)
    if packed_input.ndim != 1 or packed_weight.ndim != 1:
        raise AssertionError(f"{case}: unexpected packed tensor rank")

    body = list(mod.make_regs(shape, p, 0, 0, 0, out_fp16))
    patches = split_address_patches(body, FP16_ADDRESS_REGS)
    regcmd = body + terminal_tail(FP16_OP_ENABLE)

    expected_logical = mod.compute_expected(inp, wt, shape)[0]
    dtype = np.float16 if out_fp16 else np.float32
    expected_raw = pack_fp16_expected_raw(
        expected_logical.astype(dtype), p, out_fp16, out_c
    )
    if not np.isfinite(expected_raw).all():
        raise AssertionError(f"{case}: oracle contains non-finite values")

    case_dir = CASES_DIR / case
    write_le(case_dir / "input.bin", packed_input, "<f2")
    write_le(case_dir / "weight.bin", packed_weight, "<f2")
    write_le(case_dir / "expected.bin", expected_raw, "<f2" if out_fp16 else "<f4")

    rec = base_case_record(case, FP16_SRC, shape, description)
    rec["depthwise"] = False
    rec["seed"] = FP16_SEED
    rec["source_lines"] = {
        "shape_and_params": "expt/conv_simple.py:228-238,297-311",
        "pack_input": "expt/conv_simple.py:364-374",
        "pack_weights": "expt/conv_simple.py:351-361",
        "make_regs": "expt/conv_simple.py:383-440",
        "output_precision": "expt/conv_simple.py:695,726-729,734",
        "rocket_tail": "expt/conv_simple.py:742-843 (terminal tail 780-785)",
        "oracle": "expt/conv_simple.py:588-598",
        "unpack": "expt/conv_simple.py:377-380",
        "source_shape_table": "expt/conv_simple.py:207-217",
        "planner_gate": "conv_expt/conv_tile_planner.py:526-527 (NONE/setup)",
    }
    rec["dtype"] = {
        "input": "float16",
        "weight": "float16",
        "output": "float16" if out_fp16 else "float32",
        "accumulator": "float64 (oracle only)",
    }
    if p["use_nhwc"]:
        input_layout = (
            "pack_input() NHWC: [H][width_stride][in_c] float16; "
            f"width_stride={p['width_stride']}, in_c={in_c}"
        )
    else:
        input_layout = (
            "pack_input(): [c1][H][width_stride][c2] float16, "
            f"c2={p['input_pack_c2']}, width_stride={p['width_stride']}"
        )
    rec["layout"] = {
        "input_raw": input_layout,
        "weight_raw": "kh-major chunks of 16 output channels: [oc_chunk][kh][kw][oc_in_chunk][align_c]",
        "output_raw": (
            "unpack_output() order: [c1][out_width_stride][c2], "
            f"c2={8 if out_fp16 else 4}, c1={p['align_out_c'] // (8 if out_fp16 else 4)}"
        ),
        "logical_output": f"[1, {out_c}, {p['out_h']}, {p['out_w']}] NCHW",
        "no_output_padding": True,
    }
    rec["tasks"] = 1
    rec["regcmd_words"] = len(regcmd)
    rec["buffers"] = [
        {"name": "input", "size": int(packed_input.nbytes), "input": "input.bin", "direction": "in"},
        {"name": "weight", "size": int(packed_weight.nbytes), "input": "weight.bin", "direction": "in"},
        {"name": "out", "size": int(expected_raw.nbytes), "direction": "out", "output": "out.bin"},
    ]
    rec["patches"] = patches
    rec["oracle"] = {
        "kind": "numpy_naive_valid_conv",
        "source": "expt/conv_simple.py::compute_expected (verbatim)",
        "file": "expected.bin",
        "dtype": "float16" if out_fp16 else "float32",
        "logical_shape": [1, out_c, p["out_h"], p["out_w"]],
        "logical_layout": "NCHW",
        "raw_bo_layout": rec["layout"]["output_raw"],
        "formula": (
            "out[oc,y,x] = sum_{ic,ky,kx} input[ic,y+ky,x+kx] * weight[oc,ic,ky,kx]; "
            "float64 accumulate, then cast to the device output dtype"
        ),
        "tolerance": {"atol": 0.12 if out_fp16 else 0.1, "rtol": 1e-5},
        "warning": "Host-side oracle only.  Not a device capture and not evidence of silicon numerics.",
    }
    write_json(case_dir / "job.json", job_record(case, FP16_SRC, description, rec))
    return rec, regcmd


def derive_int8_case(
    case: str,
    in_c: int,
    in_h: int,
    in_w: int,
    out_c: int,
    k: int,
    groups: int,
    weight_in_c: int,
    data_high: int,
    description: str,
):
    mod = load_int8_module()
    shape = {
        "name": case,
        "batch": 1,
        "in_c": in_c,
        "in_h": in_h,
        "in_w": in_w,
        "out_c": out_c,
        "weight_in_c": weight_in_c,
        "kh": k,
        "kw": k,
        "groups": groups,
        "stride": 1,
    }
    mod["use_shape"](shape)
    depthwise = bool(mod["DEPTHWISE"])
    if groups != 1 and not depthwise:
        raise AssertionError(f"{case}: grouped path is deliberately excluded")

    np.random.seed(INT8_SEED)
    inp = np.random.randint(0, data_high, (1, in_h, in_w, in_c), dtype=np.uint8)
    if depthwise:
        weight_shape = (1, k, k, in_c)
    else:
        weight_shape = (out_c, k, k, weight_in_c)
    wt = np.random.randint(0, data_high, weight_shape, dtype=np.uint8)
    biases = np.random.randint(-16, 17, (out_c,), dtype=np.int32)

    packed_input = mod["pack_input"](inp)
    packed_weight = mod["pack_weights"](wt)
    packed_bias = mod["pack_biases"](biases, wt)
    tasks = mod["split_tasks"]()
    if len(tasks) != 1:
        raise AssertionError(f"{case}: INT8 split_tasks returned {len(tasks)} tasks")
    task = tasks[0]
    if task["input_offset"] or task["output_offset"]:
        raise AssertionError(f"{case}: non-zero single-task offset")
    if task["input_height"] != in_h or task["output_height"] != mod["output_height"]:
        raise AssertionError(f"{case}: split_tasks changed the task shape")

    body = list(mod["build_conv_regs"](0, 0, 0, 0, task))
    patches = split_address_patches(body, INT8_ADDRESS_REGS)
    regcmd = body + terminal_tail(INT8_OP_ENABLE)

    # Verify the device writes exactly the real output channel count.  This
    # keeps expected.bin a full-buffer oracle with no uninspectable padding.
    out_c_aligned = mod["_align"](max(out_c, 32), 32)
    if depthwise and out_c <= 32:
        out_c_aligned *= 2
    if depthwise:
        out_c_aligned = mod["_align"](out_c_aligned, 64)
    if out_c_aligned != out_c:
        raise AssertionError(
            f"{case}: aligned output channels {out_c_aligned} != real {out_c}"
        )

    expected_logical = mod["expected_output"](inp, wt, biases)
    expected_raw = pack_int8_expected_raw(
        expected_logical, mod["output_width"], mod["output_height"], out_c
    )
    # simple_conv.py::calc_raw_output_size over-allocates by a factor of two:
    # oc1 = ceil(oc/16)*2.  read_output() uses only the first ceil(oc/16)
    # groups, so the oracle is the contiguous used prefix.  The output BO is
    # sized to the source's full calculation so a conservative WDMA footprint
    # cannot overflow it; the unused suffix is not part of the oracle.
    buffer_size = int(mod["calc_raw_output_size"](mod["output_width"], mod["output_height"], out_c))
    used_size = (out_c // 16) * int(mod["output_width"]) * int(mod["output_height"]) * 16
    if expected_raw.nbytes != used_size:
        raise AssertionError(f"{case}: oracle {expected_raw.nbytes} != used prefix {used_size}")
    if used_size > buffer_size:
        raise AssertionError(f"{case}: used prefix {used_size} > calc buffer {buffer_size}")
    if expected_logical.min() <= 0 or expected_logical.max() >= 255:
        raise AssertionError(
            f"{case}: oracle clips at 0/255 (range {expected_logical.min()}..{expected_logical.max()})"
        )

    case_dir = CASES_DIR / case
    write_le(case_dir / "input.bin", packed_input, "<u1")
    write_le(case_dir / "weight.bin", packed_weight, "<u1")
    write_le(case_dir / "bias.bin", packed_bias, "<i4")
    write_le(case_dir / "expected.bin", expected_raw, "<u1")

    rec = base_case_record(case, INT8_SRC, shape, description)
    rec["depthwise"] = depthwise
    rec["seed"] = INT8_SEED
    rec["source_lines"] = {
        "shape": (
            "kernel_6_18/simple_conv.py:66-84; "
            "kernel_6_18/conv_legacy.py:1190,1237,1248 (shape-table analogues)"
        ),
        "pack_input": "kernel_6_18/simple_conv.py:414-435",
        "pack_weights": "kernel_6_18/simple_conv.py:437-461",
        "pack_biases": "kernel_6_18/simple_conv.py:463-475",
        "build_conv_regs": "kernel_6_18/simple_conv.py:477-622",
        "split_tasks": "kernel_6_18/simple_conv.py:366-412",
        "terminal_tail": "kernel_6_18/simple_conv.py:624-673 (628-644)",
        "oracle": "kernel_6_18/simple_conv.py:705-727",
        "unpack": "kernel_6_18/simple_conv.py:693-703",
        "output_size": "kernel_6_18/simple_conv.py:342-344",
    }
    rec["dtype"] = {
        "input": "uint8 (zero point 0x80)",
        "weight": "uint8 (zero point 0x80)",
        "bias": "int32",
        "output": "uint8 (zero point 0x80; raw bytes are value-0x80)",
        "accumulator": "int64 (oracle only)",
    }
    rec["layout"] = {
        "input_raw": "pack_input(): [channel_group][x][y][16] bytes, values (u-0x80)&0xff",
        "weight_raw": "pack_weights(): [oc_group][ic_group][x][y][oc_lane][ic_lane], (w-0x80)&0xff",
        "bias_raw": "pack_biases(): int32 little-endian, length out_c",
        "output_raw": "read_output() order: [channel_group][x][y][16], byte = (logical-0x80)&0xff",
        "logical_output": f"[1, {mod['output_height']}, {mod['output_width']}, {out_c}] NHWC (y,x,c)",
        "oracle_prefix_bytes": int(expected_raw.nbytes),
        "output_buffer_bytes": int(buffer_size),
        "no_output_padding": False,
    }
    rec["tasks"] = 1
    rec["regcmd_words"] = len(regcmd)
    rec["buffers"] = [
        {"name": "input", "size": int(packed_input.nbytes), "input": "input.bin", "direction": "in"},
        {"name": "weight", "size": int(packed_weight.nbytes), "input": "weight.bin", "direction": "in"},
        {"name": "bias", "size": int(packed_bias.nbytes), "input": "bias.bin", "direction": "in"},
        {"name": "out", "size": int(buffer_size), "direction": "out", "output": "out.bin"},
    ]
    rec["patches"] = patches
    rec["oracle"] = {
        "kind": "numpy_naive_quantized_conv",
        "source": "kernel_6_18/simple_conv.py::expected_output (verbatim)",
        "file": "expected.bin",
        "dtype": "uint8",
        "logical_shape": [1, mod["output_height"], mod["output_width"], out_c],
        "logical_layout": "NHWC (y,x,c)",
        "raw_bo_layout": rec["layout"]["output_raw"],
        "formula": (
            "acc = bias[oc] + sum_{ky,kx,ic} input_u8[y+ky,x+kx,ic] * weight_u8[oc,kx,ky,ic]; "
            "logical = clip(round(acc * (1/255)), 0, 255); raw = (logical - 0x80) & 0xff"
        ),
        "tolerance": {"max_abs_diff_uint8": 1},
        "expected_bytes": int(expected_raw.nbytes),
        "output_buffer_bytes": int(buffer_size),
        "compare_region": (
            f"first {expected_raw.nbytes} bytes of out.bin (used channel groups); "
            f"the remaining {buffer_size - expected_raw.nbytes} bytes are the "
            "source's calc_raw_output_size over-allocation and are not part of the oracle"
        ),
        "warning": (
            "Host-side donor CPU oracle only.  Data bytes were chosen in a lower "
            "range than the example's randint(0,256) so the oracle does not clip; "
            "the source formula and register stream are unchanged."
        ),
    }
    write_json(case_dir / "job.json", job_record(case, INT8_SRC, description, rec))
    return rec, regcmd


def job_record(case: str, source: Path, description: str, rec: dict) -> dict:
    return {
        "case": case,
        "source_example": str(source),
        "description": description,
        "timeout_ns": TIMEOUT_NS,
        "tasks": [
            {"regcmd_offset_words": 0, "regcmd_words": int(rec["regcmd_words"])}
        ],
        "buffers": rec["buffers"],
        "patches": rec["patches"],
    }


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def write_regcmd(case: str, regcmd: list[int]) -> int:
    """Write the command stream plus Rocket's QWORD-pair fetch padding.

    Rocket's PC fetch amount is expressed in QWORD pairs, so an odd declared
    count fetches one extra QWORD.  The task descriptor keeps the declared
    count; the extra QWORD is a trailing zero that is fetched but never
    executed as a command.  Returns the declared (unpadded) word count.
    """
    declared_words = len(regcmd)
    emitted = list(regcmd)
    if declared_words & 1:
        emitted.append(0)
    data = b"".join(struct.pack("<Q", word & 0xFFFFFFFFFFFFFFFF) for word in emitted)
    write_bytes(CASES_DIR / case / "regcmd.bin", data)
    return declared_words


def blocked_record(
    case: str,
    source_example: Path,
    shape: dict,
    description: str,
    blocker: str,
    source_lines: dict,
):
    return {
        "case": case,
        "status": "BLOCKED",
        "source_example": str(source_example),
        "source_lines": source_lines,
        "description": description,
        "shape": shape,
        "dtype": {},
        "layout": {},
        "tasks": 0,
        "regcmd_words": 0,
        "buffers": [],
        "patches": [],
        "oracle": None,
        "hashes": {},
        "blocker": blocker,
    }


def write_blocked_marker(case: str, blocker: str) -> None:
    path = CASES_DIR / case / "BLOCKED.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(blocker.rstrip() + "\n", encoding="utf-8")


def main() -> int:
    ready_specs = [
        dict(
            kind="fp16",
            case="conv_simple_fp16_1x1_c4_h8_w8_oc16",
            in_c=4, in_h=8, in_w=8, out_c=16, k=1,
            description=(
                "FP16 1x1 valid conv, C4/H8/W8 -> OC16; <=4-channel NHWC path "
                "(the same packing class as the source's validated RGB probe); "
                "pointwise non-spatial policy selects FP32 output."
            ),
        ),
        dict(
            kind="fp16",
            case="conv_simple_fp16_3x3_c4_h8_w8_oc16",
            in_c=4, in_h=8, in_w=8, out_c=16, k=3,
            description=(
                "FP16 3x3 valid conv, C4/H8/W8 -> OC16; <=4-channel NHWC path, "
                "spatial policy selects FP16 output."
            ),
        ),
        dict(
            kind="fp16",
            case="conv_simple_fp16_5x5_c4_h8_w8_oc16",
            in_c=4, in_h=8, in_w=8, out_c=16, k=5,
            description=(
                "FP16 5x5 valid conv, C4/H8/W8 -> OC16; <=4-channel NHWC path, "
                "generic kh/kw builder, planner NONE/setup.  Not in the "
                "example's LIST_SHAPES."
            ),
        ),
        dict(
            kind="fp16",
            case="conv_simple_fp16_1x1_c32_h8_w8_oc32",
            in_c=32, in_h=8, in_w=8, out_c=32, k=1,
            description=(
                "FP16 1x1 valid conv with larger channels, C32/H8/W8 -> OC32; "
                "exercises c1=4 channel slicing and FP32 output."
            ),
        ),
        dict(
            kind="fp16",
            case="conv_simple_fp16_3x3_c16_h8_w8_oc32",
            in_c=16, in_h=8, in_w=8, out_c=32, k=3,
            description=(
                "FP16 3x3 valid conv, C16/H8/W8 -> OC32; larger channel count "
                "with spatial FP16 output."
            ),
        ),
        dict(
            kind="int8",
            case="simple_conv_int8_5x5_c8_h8_w8_oc32",
            in_c=8, in_h=8, in_w=8, out_c=32, k=5, groups=1, weight_in_c=8,
            data_high=32,
            description=(
                "INT8 quantized 5x5 valid conv, C8/H8/W8 -> OC32; source "
                "kernel_6_18/simple_conv.py direct path (not im2col)."
            ),
        ),
        dict(
            kind="int8",
            case="simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64",
            in_c=64, in_h=8, in_w=8, out_c=64, k=3, groups=64, weight_in_c=1,
            data_high=96,
            description=(
                "INT8 quantized depthwise 3x3 valid conv, C64/H8/W8 -> OC64, "
                "groups=64; exercises CORE DW_EN and the depthwise weight layout."
            ),
        ),
    ]

    records = []
    for spec in ready_specs:
        spec = dict(spec)
        kind = spec.pop("kind")
        if kind == "fp16":
            rec, regcmd = derive_fp16_case(**spec)
        else:
            rec, regcmd = derive_int8_case(**spec)
        declared_words = write_regcmd(rec["case"], regcmd)
        case_dir = CASES_DIR / rec["case"]
        file_words = declared_words + (declared_words & 1)
        rec["regcmd_words"] = declared_words
        rec["regcmd_file_words"] = file_words
        rec["regcmd_fetch_words"] = file_words
        rec["regcmd_padding_words"] = file_words - declared_words
        rec["regcmd_size_bytes"] = file_words * 8
        # Refresh job.json now that the final declared regcmd length is known.
        write_json(case_dir / "job.json", job_record(rec["case"], Path(rec["source_example"]), rec["description"], rec))
        rec["hashes"] = {
            "job.json": sha256(case_dir / "job.json"),
            "regcmd.bin": sha256(case_dir / "regcmd.bin"),
            "input.bin": sha256(case_dir / "input.bin"),
            "weight.bin": sha256(case_dir / "weight.bin"),
            "expected.bin": sha256(case_dir / "expected.bin"),
        }
        if (case_dir / "bias.bin").exists():
            rec["hashes"]["bias.bin"] = sha256(case_dir / "bias.bin")
        records.append(rec)

    blocked_specs = [
        dict(
            case="conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2",
            shape={
                "name": "conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2",
                "batch": 1, "in_c": 8, "in_h": 8, "in_w": 8, "out_c": 16,
                "weight_in_c": 8, "kh": 3, "kw": 3, "groups": 1, "stride": 2,
            },
            description="Intended FP16 3x3 stride-2 case (valid geometry 3x3 output).",
            blocker=(
                "No source path encodes a convolution stride.  The FP16 shape "
                "parser accepts an sN field (expt/conv_simple.py:228-238), but "
                "_conv_params ignores it (lines 297-311) and make_regs always "
                "writes CNA_CONV_CON3 = (1<<3)|1 = 0x9, i.e. stride 1 "
                "(expt/conv_simple.py:408).  kernel_6_18/simple_conv.py hardcodes "
                "the same value at line 557.  Emitting a stride-2 case would "
                "require a new CNA_CONV_CON3 encoding that these sources do not "
                "provide."
            ),
            source_lines={
                "stride_param": "expt/conv_simple.py:228-238,297-311",
                "stride_register": "expt/conv_simple.py:408; kernel_6_18/simple_conv.py:557",
            },
        ),
        dict(
            case="conv_simple_fp16_3x3_c8_h8_w8_oc16_samepad",
            shape={
                "name": "conv_simple_fp16_3x3_c8_h8_w8_oc16_samepad",
                "batch": 1, "in_c": 8, "in_h": 8, "in_w": 8, "out_c": 16,
                "weight_in_c": 8, "kh": 3, "kw": 3, "groups": 1, "stride": 1,
                "padding": "same",
            },
            description="Intended FP16 3x3 SAME-padding case.",
            blocker=(
                "No SAME-padding path exists in the named sources.  The FP16 "
                "make_regs() never writes CNA_PAD_CON0 or CNA_PAD_CON1 "
                "(expt/conv_simple.py:383-440) and _conv_params computes "
                "out_h/out_w = in_h/in_w - k + 1, i.e. valid-only "
                "(expt/conv_simple.py:301).  The INT8 builder writes "
                "CNA_PAD_CON0 = 0 (kernel_6_18/simple_conv.py:575), sets "
                "CNA_PAD_CON1 only to a zero-point fill value (line 584), and "
                "also computes valid-only output geometry (lines 81-82).  A "
                "SAME case would require new pad-register evidence and an "
                "output-with-halo contract that the sources do not provide."
            ),
            source_lines={
                "valid_geometry": "expt/conv_simple.py:301; kernel_6_18/simple_conv.py:81-82",
                "fp16_no_pad_regs": "expt/conv_simple.py:383-440",
                "int8_pad_regs": "kernel_6_18/simple_conv.py:575,584",
            },
        ),
        dict(
            case="conv_simple_fp16_3x3_c8_h8_w8_oc16_unpadded_pack",
            shape={
                "name": "conv_simple_fp16_3x3_c8_h8_w8_oc16_unpadded_pack",
                "batch": 1, "in_c": 8, "in_h": 8, "in_w": 8, "out_c": 16,
                "weight_in_c": 8, "kh": 3, "kw": 3, "groups": 1, "stride": 1,
            },
            description=(
                "Intended small FP16 3x3 C8 case in the example style "
                "(C8/H8/W8/OC8-like); blocked by the source's input-pack/align "
                "mismatch for 5 <= in_c <= 8."
            ),
            blocker=(
                "This C8 shape cannot be packed safely with the FP16 builder.  "
                "For in_c=8, _conv_align_c returns 16 "
                "(expt/conv_simple.py:283-286), but _conv_input_pack_c2 returns "
                "8 (lines 289-294).  pack_input() then writes c1*c2 = 8 "
                "channels per pixel (lines 364-374), while make_regs sets "
                "CNA_DATA_SIZE1 = ((in_c-1)<<16) | data_in_channel_aligned = "
                "0x00070010, i.e. a 16-channel aligned field (lines 393,410).  "
                "The source's own known-supported table has no C8 entry "
                "(lines 207-217), and its validated small-channel path is the "
                "<=4-channel NHWC case (C3/C4, where use_nhwc is true and the "
                "CVT fields carry the real channel count).  There is no "
                "source-supported padding contract that fills the missing 8 "
                "channels for C8 (the same gap affects 5 <= in_c <= 8).  The "
                "READY small cases therefore use C4, and the larger cases use "
                "C16/C32 where the packed channel count equals the aligned "
                "count."
            ),
            source_lines={
                "align_c": "expt/conv_simple.py:283-286",
                "input_pack_c2": "expt/conv_simple.py:289-294",
                "pack_input": "expt/conv_simple.py:364-374",
                "data_size1": "expt/conv_simple.py:393,410",
                "known_shapes": "expt/conv_simple.py:207-217",
            },
        ),
        dict(
            case="conv_simple_fp16_grouped_3x3_c8_h8_w8_oc8_g2",
            shape={
                "name": "conv_simple_fp16_grouped_3x3_c8_h8_w8_oc8_g2",
                "batch": 1, "in_c": 8, "in_h": 8, "in_w": 8, "out_c": 8,
                "weight_in_c": 4, "kh": 3, "kw": 3, "groups": 2, "stride": 1,
            },
            description="Intended FP16 grouped 3x3 conv, C8 -> OC8, groups=2.",
            blocker=(
                "The grouped path cannot be expressed safely from these sources.  "
                "The FP16 make_regs() has no group-count register and its "
                "known-supported table has no grouped entry "
                "(expt/conv_simple.py:207-217,383-440).  The only grouped "
                "implementation is kernel_6_18/simple_conv.py::run_conv2d_grouped "
                "(lines 729-759), which slices input/weight/bias and calls "
                "run_conv2d_shape once per group; each call overwrites the shared "
                "BOs in write_buffers (lines 675-691) and does its own npu_submit "
                "(lines 871-872).  A single bundle would therefore need per-group "
                "BOs plus a multi-task PC chain, and the chain's PC_BASE_ADDRESS "
                "would have to be regcmd_addr + task_offset.  The bundle patch "
                "schema can only bind named buffer addresses, not the regcmd "
                "self-address, so the chain cannot be encoded without leaving an "
                "unpatched address."
            ),
            source_lines={
                "fp16_no_group_field": "expt/conv_simple.py:207-217,383-440",
                "int8_group_split": "kernel_6_18/simple_conv.py:729-759",
                "shared_bo_overwrite": "kernel_6_18/simple_conv.py:675-691",
                "per_group_submit": "kernel_6_18/simple_conv.py:847-872",
            },
        ),
        dict(
            case="simple_conv_int8_addition_c8_h8_w8_oc32",
            shape={
                "name": "simple_conv_int8_addition_c8_h8_w8_oc32",
                "batch": 1, "in_c": 8, "in_h": 8, "in_w": 8, "out_c": 32,
                "weight_in_c": 8, "kh": 3, "kw": 3, "groups": 1, "stride": 1,
                "addition_input": True,
            },

            description="Intended INT8 residual/addition-input 3x3 case.",
            blocker=(
                "The source's addition-input knobs are not a usable ABI.  "
                "use_shape() reads addition_input/add_tensor "
                "(kernel_6_18/simple_conv.py:83-84), but build_conv_regs() uses "
                "them only to change CNA_PAD_CON1 and the single-channel CVT "
                "scale (lines 523-531); add_tensor is never written to an address "
                "register.  write_buffers() allocates and packs only "
                "input/weight/bias/output (lines 675-691), and npu_submit() "
                "submits no addition tensor BO (lines 298-305).  A residual case "
                "would require a vendor-only addition-input stream and a second "
                "feature buffer, which these sources do not construct."
            ),
            source_lines={
                "shape_knobs": "kernel_6_18/simple_conv.py:83-84",
                "reg_usage_only": "kernel_6_18/simple_conv.py:523-531",
                "no_addition_bo": "kernel_6_18/simple_conv.py:675-691,298-305",
            },
        ),
    ]

    for spec in blocked_specs:
        rec = blocked_record(
            spec["case"],
            INT8_SRC if spec["case"].startswith("simple_conv_") else FP16_SRC,
            spec["shape"],
            spec["description"],
            spec["blocker"],
            spec["source_lines"],
        )
        write_blocked_marker(rec["case"], rec["blocker"])
        rec["hashes"] = {"BLOCKED.md": sha256(CASES_DIR / rec["case"] / "BLOCKED.md")}
        records.append(rec)

    ready = sum(1 for r in records if r["status"] == "READY")
    blocked = sum(1 for r in records if r["status"] == "BLOCKED")
    manifest = {
        "family": "conv-simple",
        "format": "build/rk3588-example-captures/CAPTURE_FORMAT.md",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "generate.py",
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "platform": platform.platform(),
            "executable": sys.executable,
        },
        "seeds": {
            "fp16": FP16_SEED,
            "int8": INT8_SEED,
            "note": (
                "FP16 seed matches expt/conv_simple.py::run_shape.  INT8 seed is "
                "a preparation choice; each case also records its seed."
            ),
        },
        "source_examples": [
            {
                "path": str(FP16_SRC),
                "sha256": sha256(FP16_SRC),
                "role": "FP16 generic command builder, Rocket tail, FP16 oracle",
            },
            {
                "path": str(FP16_SRC_ALT),
                "sha256": sha256(FP16_SRC_ALT),
                "role": "cross-reference only; same generic make_regs",
            },
            {
                "path": str(INT8_SRC),
                "sha256": sha256(INT8_SRC),
                "role": "INT8 quantized builder, depthwise/5x5 path, donor oracle",
            },
            {
                "path": str(INT8_SHAPES_SRC),
                "sha256": sha256(INT8_SHAPES_SRC),
                "role": "shape-table analogues for 5x5 and depthwise",
            },
        ],
        "preparation_notes": [
            "Device-free preparation only: no ssh/scp, no board access, no FPGA programming.",
            "Every READY case is a single terminal PC record: PC_BASE_ADDRESS=0 and PC_REGISTER_AMOUNTS=0 in the tail.",
            "All address operands are value32 patches bound to named input/weight/bias/out buffers.",
            "No out.bin is shipped; the worker writes it.  expected.bin is a host NumPy oracle.",
            "The FP16 module is imported directly.  The INT8 module is executed with only its module-level DRM setup block removed.",
            "Per-case data seeds and source hashes are recorded here; the case files are deterministic for the recorded NumPy version.",
            "Rocket's PC fetch amount is in QWORD pairs.  Every READY regcmd.bin has one trailing zero QWORD of fetch padding when the declared task count is odd; the declared task regcmd_words (51/69) is unchanged and the padding is not executed as a command.",
            "The FP16 1x1 cases follow the source run_shape output-precision policy (FP32 output).  The separate Rocket probe helper run_shape_rocket hardcodes out_fp16=True; mainline-Rocket execution of this FP32-output stream is not separately evidenced by the source.",
            "The INT8 cases supply the depthwise path and the explicit 5x5 table analogue that the FP16 builder does not provide.  They are quantized-conv captures, not FP16 EW-slice validation.",
        ],
        "validation_files": ["validation.json", "numeric_check.json"],
        "parity_padding": {
            "reason": "Rocket PC fetch amount is expressed in QWORD pairs; an odd declared count fetches one extra QWORD.",
            "applied_to": "all READY cases",
            "qwords": 1,
            "value": 0,
            "executed": False,
            "declared_words_field": "job.json tasks[].regcmd_words",
            "file_words_fields": [
                "manifest.cases[].regcmd_file_words",
                "manifest.cases[].regcmd_fetch_words",
                "manifest.cases[].regcmd_size_bytes",
            ],
        },
        "summary": {"ready": ready, "blocked": blocked, "total": len(records)},
        "coverage": {
            "1x1": ["conv_simple_fp16_1x1_c4_h8_w8_oc16", "conv_simple_fp16_1x1_c32_h8_w8_oc32"],
            "3x3": ["conv_simple_fp16_3x3_c4_h8_w8_oc16", "conv_simple_fp16_3x3_c16_h8_w8_oc32"],
            "5x5": ["conv_simple_fp16_5x5_c4_h8_w8_oc16", "simple_conv_int8_5x5_c8_h8_w8_oc32"],
            "depthwise": ["simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64"],
            "grouped": [],
            "grouped_blocked": ["conv_simple_fp16_grouped_3x3_c8_h8_w8_oc8_g2"],
            "c8_fp16_blocked": ["conv_simple_fp16_3x3_c8_h8_w8_oc16_unpadded_pack"],
            "stride_1": [
                "conv_simple_fp16_1x1_c4_h8_w8_oc16",
                "conv_simple_fp16_3x3_c4_h8_w8_oc16",
                "conv_simple_fp16_5x5_c4_h8_w8_oc16",
                "conv_simple_fp16_1x1_c32_h8_w8_oc32",
                "conv_simple_fp16_3x3_c16_h8_w8_oc32",
                "simple_conv_int8_5x5_c8_h8_w8_oc32",
                "simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64",
            ],
            "stride_2_blocked": ["conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2"],
            "padding_valid": [
                "conv_simple_fp16_1x1_c4_h8_w8_oc16",
                "conv_simple_fp16_3x3_c4_h8_w8_oc16",
                "conv_simple_fp16_5x5_c4_h8_w8_oc16",
                "conv_simple_fp16_1x1_c32_h8_w8_oc32",
                "conv_simple_fp16_3x3_c16_h8_w8_oc32",
                "simple_conv_int8_5x5_c8_h8_w8_oc32",
                "simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64",
            ],
            "padding_same_blocked": ["conv_simple_fp16_3x3_c8_h8_w8_oc16_samepad"],
            "addition_input_blocked": ["simple_conv_int8_addition_c8_h8_w8_oc32"],
            "output_dtypes": {
                "float32": ["conv_simple_fp16_1x1_c4_h8_w8_oc16", "conv_simple_fp16_1x1_c32_h8_w8_oc32"],
                "float16": [
                    "conv_simple_fp16_3x3_c4_h8_w8_oc16",
                    "conv_simple_fp16_5x5_c4_h8_w8_oc16",
                    "conv_simple_fp16_3x3_c16_h8_w8_oc32",
                ],
                "uint8": [
                    "simple_conv_int8_5x5_c8_h8_w8_oc32",
                    "simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64",
                ],
            },
        },
        "cases": records,
    }
    write_json(ROOT / "manifest.json", manifest)
    print(
        f"generated {ready} READY and {blocked} BLOCKED cases under {ROOT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
