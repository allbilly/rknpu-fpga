#!/usr/bin/env python3
"""Generate device-free Rocket FP16 convolution capture bundles.

This script does not open /dev/accel*, /dev/dri* or the network.  It loads the
donor example with a host-only rocket_runtime stub, calls the donor's own
register builder and packing helpers, and writes the capture bundle below
build/rk3588-example-captures/conv-fp16/cases/.

The only hand-written command QWORDs are the four terminal PC/VERSION words,
which are produced by the donor's write_regs_to_npu_task() itself (single-task
branch).  No register values are invented here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SOURCE_ROOT = Path("/home/fedora/rk3588")
SOURCE_EXAMPLE = SOURCE_ROOT / "examples/kernel_6_18/conv_new_clean.py"
SOURCE_VENDOR_TILES = SOURCE_ROOT / "examples/conv_tiles.py"
SOURCE_MESA = SOURCE_ROOT / "examples/kernel_6_18/conv_mesa_fp16.py"

HERE = Path(__file__).resolve().parent
FAMILY_DIR = HERE.parent
CASES_DIR = FAMILY_DIR / "cases"

FP16 = np.float16


# ---------------------------------------------------------------------------
# Host-only rocket_runtime stub.  The donor module allocates BOs at import.
# ---------------------------------------------------------------------------


class _FakeBO:
    __slots__ = ("size", "dma_address", "offset", "handle")

    def __init__(self, size: int, dma_address: int, handle: int):
        self.size = int(size)
        self.dma_address = int(dma_address)
        self.offset = 0
        self.handle = int(handle)

    @property
    def dma_addr(self) -> int:
        return self.dma_address


class _HostBuffer(bytearray):
    """Writable host buffer with the donor's mmap-style size() method."""

    def size(self) -> int:
        return len(self)


def _load_donor():
    stub = types.ModuleType("rocket_runtime")
    next_dma = [0x10000000]
    next_handle = [1]

    def mem_allocate(fd, size, flags=0):
        next_dma[0] += 0x01000000
        next_handle[0] += 1
        return _HostBuffer(int(size)), _FakeBO(size, next_dma[0], next_handle[0])

    stub.mem_allocate = mem_allocate
    stub.open_rocket_device = lambda: 0
    stub.reset_npu = lambda fd: 0
    stub.fini_bo = lambda fd, bo: None
    stub.prep_bo = lambda fd, bo, timeout_ns=0: None
    stub.submit = lambda *a, **k: 0
    sys.modules["rocket_runtime"] = stub

    spec = importlib.util.spec_from_file_location("conv_new_clean", SOURCE_EXAMPLE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SOURCE_EXAMPLE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def align_up(value: int, align: int) -> int:
    return ((int(value) + int(align) - 1) // int(align)) * int(align)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def fp16_bytes(array) -> bytes:
    arr = np.ascontiguousarray(array, dtype=FP16)
    if sys.byteorder != "little":
        raise RuntimeError("bundle files are little-endian; host is big-endian")
    return arr.view(np.uint16).tobytes()


def pack_bo_bytes(data: bytes, align: int = 16) -> bytes:
    padded = align_up(len(data), align)
    return data + b"\x00" * (padded - len(data))


def words_bytes(words) -> bytes:
    out = bytearray()
    for word in words:
        out += int(word).to_bytes(8, "little", signed=False)
    return bytes(out)


def command_parts(word: int):
    return (int(word) >> 48) & 0xFFFF, (int(word) >> 16) & 0xFFFFFFFF, int(word) & 0xFFFF


def git_revision(path: Path):
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Case definitions
# ---------------------------------------------------------------------------

DIRECT = "direct"
GROUPED = "grouped"
SPLIT_OC = "split_oc"

CASES = [
    dict(
        case="conv_1x1_valid_c8_h5_w5_oc8",
        mode=DIRECT,
        in_c=8,
        in_h=5,
        in_w=5,
        out_c=8,
        weight_in_c=8,
        kh=1,
        kw=1,
        stride=1,
        groups=1,
        out_layout="flat_1x1",
        source_shape_line=1187,
        source_shape_text='dict(name="conv2d_8x8_1x1_5x5", batch=1, in_c=8, in_h=5, in_w=5, out_c=8, weight_in_c=8, kh=1, kw=1, groups=1)',
        branch="conv_new_clean.run_conv2d direct pointwise path (lines 941-1007; _unpack_flat_1x1_output at 403-406)",
        description="FP16 1x1 valid convolution, C8 H5 W5 -> OC8, stride 1, groups 1.",
        caveats=[
            "The 1x1 direct path uses the flat_1x1 output layout and the source's 52-entry minimum feature_grains rule.",
            "The output BO carries four aligned channel planes (32 channels); only the first eight are defined by the oracle.",
        ],
    ),
    dict(
        case="conv_3x3_valid_c4_h9_w9_oc4",
        mode=DIRECT,
        in_c=4,
        in_h=9,
        in_w=9,
        out_c=4,
        weight_in_c=4,
        kh=3,
        kw=3,
        stride=1,
        groups=1,
        out_layout="nc1hwc2",
        source_shape_line=1139,
        source_shape_text='dict(name="conv2d_b1_c4_h9_w9_oc4_wic4_k3x3_g1", batch=1, in_c=4, in_h=9, in_w=9, out_c=4, weight_in_c=4, kh=3, kw=3, groups=1)',
        branch="conv_new_clean.run_conv2d direct spatial path (lines 941-1007; _unpack_nc1hwc2_output at 408-418)",
        description="FP16 3x3 valid convolution, C4 H9 W9 -> OC4, stride 1, groups 1.",
        caveats=[
            "Spatial direct path uses kh-major weight packing (lines 346-354) and NC1HWC2 output unpacking.",
            "The output BO carries 32 aligned channels; only the first four are defined by the oracle.",
        ],
    ),
    dict(
        case="conv_3x3_stride2_c4_h11_w11_oc4",
        mode=DIRECT,
        in_c=4,
        in_h=11,
        in_w=11,
        out_c=4,
        weight_in_c=4,
        kh=3,
        kw=3,
        stride=2,
        groups=1,
        out_layout="nc1hwc2",
        source_shape_line=1139,
        source_shape_text='stride=2 variant of dict(name="conv2d_b1_c4_h9_w9_oc4_wic4_k3x3_g1", ...); stride is a run_conv2d parameter',
        branch="conv_new_clean.run_conv2d direct spatial path with stride=2 (CNA_CONV_CON3 at builder line 505-507)",
        description="FP16 3x3 valid convolution with stride 2, C4 H11 W11 -> OC4 5x5, groups 1.",
        caveats=[
            "stride=2 is implemented in _conv_params (lines 308-313) and make_conv2d_regs (lines 505-507), but the donor shape table only exercises stride 1. This case is a source-supported but table-uncovered variant.",
            "No padding is applied; the output is 5x5.",
        ],
    ),
    dict(
        case="conv_3x3_pad1_zero_frame_c4_h9_w9_oc4",
        mode=DIRECT,
        in_c=4,
        in_h=9,
        in_w=9,
        out_c=4,
        weight_in_c=4,
        kh=3,
        kw=3,
        stride=1,
        groups=1,
        out_layout="nc1hwc2",
        source_shape_line=1139,
        source_shape_text='3x3 same-padding variant, derived from dict(name="conv2d_b1_c4_h9_w9_oc4_wic4_k3x3_g1", ...)',
        branch="conv_new_clean.run_conv2d direct spatial path on an explicit 1-pixel zero frame (packed input is 11x11, valid 3x3 -> 9x9)",
        description="FP16 3x3 same-padded convolution (pad=1) realized as an explicit zero frame plus a valid 3x3 conv, C4 H9 W9 -> OC4 9x9.",
        padded_zero_frame=True,
        caveats=[
            "The clean FP16 builder does not emit CNA_PAD_CON0: the pad register is commented out at conv_new_clean.py lines 547-550 and geometry is valid-only. Padding is represented by zero-valued input bytes, not by a pad register.",
            "The packed input BO is 4x11x11 (aligned to 16 channels); the source NCHW tensor is 4x9x9. The oracle is the same-padded conv on the zero frame.",
            "A true CNA_PAD_CON0 FP16 case is BLOCKED; see manifest entry conv_3x3_pad_register_fp16_blocked.",
        ],
    ),
    dict(
        case="conv_depthwise_3x3_c3_h11_w28_oc3",
        mode=DIRECT,
        in_c=3,
        in_h=11,
        in_w=28,
        out_c=3,
        weight_in_c=1,
        kh=3,
        kw=3,
        stride=1,
        groups=3,
        out_layout="nc1hwc2",
        source_shape_line=1145,
        source_shape_text='dict(name="conv2d_b1_c3_h11_w28_oc3_wic1_k3x3_g3", batch=1, in_c=3, in_h=11, in_w=28, out_c=3, weight_in_c=1, kh=3, kw=3, groups=3)',
        branch="conv_new_clean.run_conv2d direct depthwise path; depthwise_spatial_major weights (lines 366-369) and CNA_CONV_CON1 depthwise mode",
        description="FP16 depthwise 3x3 valid convolution, C3 H11 W28 -> OC3 9x26, groups=3.",
        caveats=[
            "Depthwise uses CONV_MODE=3 and a spatial-major 3x3x8 weight stream; only 3 of 8 aligned channel lanes carry weights.",
            "The output BO carries 32 aligned channels; only the first three are defined by the oracle.",
        ],
    ),
    dict(
        case="conv_grouped_3x3_c4_h5_w5_oc8_g2",
        mode=GROUPED,
        in_c=4,
        in_h=5,
        in_w=5,
        out_c=8,
        weight_in_c=2,
        kh=3,
        kw=3,
        stride=1,
        groups=2,
        out_layout="nc1hwc2",
        source_shape_line=1177,
        source_shape_text='dict(name="conv2d_b1_c4_h5_w5_oc8_wic2_k3x3_g2", batch=1, in_c=4, in_h=5, in_w=5, out_c=8, weight_in_c=2, kh=3, kw=3, groups=2)',
        branch="conv_new_clean.run_conv2d grouped_serial path (lines 826-850): two per-group tasks with 2-channel input and 4-channel output",
        description="FP16 grouped 3x3 valid convolution, C4 H5 W5 -> OC8 3x3, groups=2; encoded as two per-group tasks.",
        multi_task=True,
        caveats=[
            "The donor submits each group as a separate npu_submit call on the same scratch BOs. The bundle uses two independent task descriptors in one job, each with its own input, weight and output BO because the bundle patch schema has no buffer+offset form.",
            "The two tasks use terminal PC tails (PC_BASE_ADDRESS=0) exactly as the donor's last-task branch; they are not PC-linked.",
            "Each output BO is 4x3x3 NC1HWC2 with 32 aligned channels; only four channels per group are defined.",
        ],
    ),
    dict(
        case="conv_splitoc_3x3_c16_h9_w9_oc16",
        mode=SPLIT_OC,
        in_c=16,
        in_h=9,
        in_w=9,
        out_c=16,
        weight_in_c=16,
        kh=3,
        kw=3,
        stride=1,
        groups=1,
        out_layout="nc1hwc2",
        source_shape_line=1189,
        source_shape_text='dict(name="conv2d_16x16_3x3_9x9", batch=1, in_c=16, in_h=9, in_w=9, out_c=16, weight_in_c=16, kh=3, kw=3, groups=1)',
        branch="conv_new_clean.run_conv2d spatial_oc_serial path (lines 852-877): two 8-output-channel tasks sharing one input BO; full_data_bank=True at lines 868-873",
        description="FP16 split-OC 3x3 valid convolution, C16 H9 W9 -> OC16 7x7; encoded as two 8-channel tasks.",
        multi_task=True,
        caveats=[
            "The donor loops over output-channel tiles in one process and reuses one output BO, unpacking after each submit. The bundle uses two output BOs so both tile results survive to the worker readback; the input BO is shared because both tasks read identical bytes.",
            "The donor sets full_data_bank=True for this branch (lines 868-873), so CNA_CBUF_CON0 uses data_bank=11/weight_bank=1; the bundle preserves that.",
            "The two tasks use terminal PC tails (PC_BASE_ADDRESS=0); they are not PC-linked.",
            "This is split-OC, not split-K: there is no reduction accumulation between tasks.",
        ],
    ),
]

BLOCKED_CASES = [
    dict(
        case="conv_tiles_vendor_abi_blocked",
        status="BLOCKED",
        source_example=str(SOURCE_VENDOR_TILES),
        source_lines=[
            "26-43: tiling family constants and captured direct-spatial template",
            "195-271: struct_rknpu_task / rknpu_mem_create / rknpu_submit and DRM_IOCTL_RKNPU_*",
            "320-338: npu_submit() through DRM_IOCTL_RKNPU_SUBMIT",
            "343: fd = os.open(\"/dev/dri/card1\", os.O_RDWR)",
        ],
        shape={
            "description": "vendor tiled direct-spatial / grouped / OC-serial corpus",
            "example_family": "DIRECT_SPATIAL_SIXDESC_C32_H14",
        },
        description="Tiled direct-spatial/split-family convolution corpus; vendor rknpu DRM submission path.",
        reason=(
            "Vendor-only ABI: conv_tiles.py opens /dev/dri/card1 and submits through "
            "DRM_IOCTL_RKNPU_MEM_CREATE/MEM_MAP/MEM_SYNC/ACTION/SUBMIT with "
            "struct rknpu_submit and RKNPU_JOB_PC. It has no rocket_runtime or "
            "drm_rocket_task path. Re-hosting its register builder would require a "
            "new BO/submission adapter and fresh verification; producing a "
            "READY bundle would imply an unverified Rocket ABI. No registers were invented."
        ),
    ),
    dict(
        case="conv_3x3_pad_register_fp16_blocked",
        status="BLOCKED",
        source_example=str(SOURCE_EXAMPLE),
        source_lines=[
            "308-318: _conv_params computes valid-only output geometry",
            "547-550: CNA_PAD_CON0 emission is commented out in the clean FP16 builder",
            "1139: 3x3 shape row used as the intended base shape",
            str(SOURCE_MESA) + ":1448-1450: the only inspected Rocket-capable builder that emits CNA_PAD_CON0",
            str(SOURCE_MESA) + ":1345-1363,1495: that path uses uint8 zero-point/quantized register semantics",
        ],
        shape={"in_c": 4, "in_h": 9, "in_w": 9, "out_c": 4, "kh": 3, "kw": 3, "stride": 1, "groups": 1, "padding": 1},
        description="True CNA_PAD_CON0 FP16 3x3 same-padding case.",
        reason=(
            "No Rocket-capable FP16 builder emits and validates CNA_PAD_CON0. "
            "conv_new_clean.py comments the pad register out (lines 547-550) and "
            "computes valid-only geometry. conv_mesa_fp16.py does emit "
            "CNA_PAD_CON0, but its register path is the Mesa uint8 zero-point "
            "semantics (for example BS_OW_OP uses 0x80 - weights_zero_point and "
            "OUT_CVT/EW scales are quantized), so using it would change the "
            "numerical contract. A true pad-register FP16 case is therefore "
            "blocked pending source evidence and tests. The READY padded case "
            "uses an explicit zero frame instead."
        ),
    ),
    dict(
        case="conv_split_k_reduction_blocked",
        status="BLOCKED",
        source_example=str(SOURCE_ROOT / "examples/kernel_6_18/conv_0522.py"),
        source_lines=[
            "362-386: split_method enum and _compute_k_step",
            "460-489: _plan_conv_tiles returns SPLIT_BY_K/SPLIT_BY_YK tiles",
            "491-514: _execute_conv_tiles clears the output before every tile; _tile_to_desc sets feature_off=weight_off=output_off=0",
            "670-957: run_conv executes tiles but has no cross-tile accumulation for a reduction split",
        ],
        shape={"in_c": 16, "in_h": 9, "in_w": 9, "out_c": 16, "kh": 3, "kw": 3, "stride": 1, "groups": 1, "split": "K"},
        description="Split-K reduction convolution, where partial K tiles would be summed.",
        reason=(
            "Split-K reduction requires accumulation of partial products across "
            "tiles. Neither inspected Rocket path provides an accumulator or a "
            "second reduction pass: conv_0522._execute_conv_tiles clears the "
            "output BO before every tile and _tile_to_desc leaves all tile "
            "offsets at zero; conv_new_clean has no K-split for spatial conv. "
            "Only split-OC is encoded as READY. Adding split-K would require a "
            "new accumulation contract, not just more tasks."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def draw_case_inputs(spec):
    np.random.seed(42)
    orig_h = int(spec["in_h"])
    orig_w = int(spec["in_w"])
    input_orig = np.random.uniform(-2, 2, (1, spec["in_c"], orig_h, orig_w)).astype(FP16)
    weight_orig = np.random.uniform(
        -2, 2, (spec["out_c"], spec["weight_in_c"], spec["kh"], spec["kw"])
    ).astype(FP16)
    if spec.get("padded_zero_frame"):
        input_eff = np.zeros((1, spec["in_c"], orig_h + 2, orig_w + 2), dtype=FP16)
        input_eff[:, :, 1:-1, 1:-1] = input_orig
    else:
        input_eff = input_orig
    return input_orig, input_eff, weight_orig


def _task_expected(m, input_nchw, weight_oracle, p, oracle_groups):
    expected = m.compute_expected_nchw(
        input_nchw[np.newaxis, ...],
        weight_oracle,
        1,
        p["in_c"],
        p["in_h"],
        p["in_w"],
        p["out_c"],
        p["kh"],
        p["kw"],
        groups=oracle_groups,
        stride=p["stride"],
    )[0]
    return expected.astype(FP16)


def build_direct_tasks(m, spec, input_eff, weight_orig):
    p = m._conv_params(
        1,
        spec["in_c"],
        input_eff.shape[2],
        input_eff.shape[3],
        spec["out_c"],
        spec["kh"],
        spec["kw"],
        spec["groups"],
        stride=spec["stride"],
    )
    is_depthwise = bool(p["is_depthwise"])
    if is_depthwise:
        weight_pack = np.zeros((spec["out_c"], spec["in_c"], spec["kh"], spec["kw"]), dtype=FP16)
        for channel in range(min(spec["out_c"], spec["in_c"])):
            weight_pack[channel, channel] = weight_orig[channel, 0]
        weight_oracle = weight_orig
        oracle_groups = spec["groups"]
    elif spec["groups"] == 1:
        weight_pack = weight_orig.reshape(spec["out_c"], spec["in_c"], spec["kh"], spec["kw"])
        weight_oracle = weight_pack
        oracle_groups = 1
    else:
        weight_pack = m._expand_grouped_weights(
            weight_orig, spec["in_c"], spec["out_c"], spec["kh"], spec["kw"], spec["groups"]
        )
        weight_oracle = weight_pack
        oracle_groups = spec["groups"]

    expected = _task_expected(m, input_eff[0], weight_oracle, p, oracle_groups)
    return [
        dict(
            p=p,
            input_nchw=input_eff[0],
            weight_pack=weight_pack,
            weight_oracle=weight_oracle,
            oracle_groups=oracle_groups,
            pack_out_c=spec["out_c"],
            pack_in_c=spec["in_c"],
            pack_groups=spec["groups"] if is_depthwise else 1,
            out_c=spec["out_c"],
            out_layout=spec["out_layout"],
            expected=expected,
            out_index=0,
        )
    ]


def build_grouped_tasks(m, spec, input_eff, weight_orig):
    groups = spec["groups"]
    in_per_group = spec["in_c"] // groups
    out_per_group = spec["out_c"] // groups
    gp = m._conv_params(
        1, in_per_group, input_eff.shape[2], input_eff.shape[3], out_per_group,
        spec["kh"], spec["kw"], 1, stride=spec["stride"],
    )
    tasks = []
    for g in range(groups):
        input_g = input_eff[0, g * in_per_group : (g + 1) * in_per_group]
        weight_g = weight_orig[g * out_per_group : (g + 1) * out_per_group].reshape(
            out_per_group, in_per_group, spec["kh"], spec["kw"]
        )
        expected = _task_expected(m, input_g, weight_g, gp, 1)
        tasks.append(
            dict(
                p=gp,
                input_nchw=input_g,
                weight_pack=weight_g,
                weight_oracle=weight_g,
                oracle_groups=1,
                pack_out_c=out_per_group,
                pack_in_c=in_per_group,
                pack_groups=1,
                out_c=out_per_group,
                out_layout=spec["out_layout"],
                expected=expected,
                out_index=g,
            )
        )
    return tasks


def build_split_oc_tasks(m, spec, input_eff, weight_orig):
    tile = int(m.UNPACK_C2)
    tasks = []
    for oc_start in range(0, spec["out_c"], tile):
        oc_end = min(oc_start + tile, spec["out_c"])
        tile_out_c = oc_end - oc_start
        tp = m._conv_params(
            1, spec["in_c"], input_eff.shape[2], input_eff.shape[3], tile_out_c,
            spec["kh"], spec["kw"], 1, stride=spec["stride"],
        )
        tile_weight = weight_orig[oc_start:oc_end].reshape(
            tile_out_c, spec["in_c"], spec["kh"], spec["kw"]
        )
        expected = _task_expected(m, input_eff[0], tile_weight, tp, 1)
        tasks.append(
            dict(
                p=tp,
                input_nchw=input_eff[0],
                weight_pack=tile_weight,
                weight_oracle=tile_weight,
                oracle_groups=1,
                pack_out_c=tile_out_c,
                pack_in_c=spec["in_c"],
                pack_groups=1,
                out_c=tile_out_c,
                out_layout=spec["out_layout"],
                expected=expected,
                out_index=oc_start // tile,
                full_data_bank=True,
            )
        )
    return tasks


def build_full_expected(m, spec, input_eff, weight_orig):
    return m.compute_expected_nchw(
        input_eff[0][np.newaxis, ...],
        weight_orig,
        1,
        spec["in_c"],
        input_eff.shape[2],
        input_eff.shape[3],
        spec["out_c"],
        spec["kh"],
        spec["kw"],
        groups=spec["groups"],
        stride=spec["stride"],
    )[0].astype(FP16)


def independent_naive_conv(input_nchw, weight_nchw, out_c, kh, kw, groups, stride):
    """Independent float64 loop oracle (same mathematical order as the donor)."""
    in_c, in_h, in_w = input_nchw.shape
    out_h = (in_h - kh) // stride + 1
    out_w = (in_w - kw) // stride + 1
    src = input_nchw.astype(np.float64)
    wgt = weight_nchw.astype(np.float64)
    out = np.zeros((out_c, out_h, out_w), dtype=np.float64)
    in_per_group = in_c // groups
    out_per_group = out_c // groups
    for g in range(groups):
        for oc in range(g * out_per_group, (g + 1) * out_per_group):
            for ic in range(g * in_per_group, (g + 1) * in_per_group):
                for ky in range(kh):
                    for kx in range(kw):
                        out[oc] += (
                            src[ic, ky : ky + stride * out_h : stride, kx : kx + stride * out_w : stride]
                            * wgt[oc, ic - g * in_per_group, ky, kx]
                        )
    return out


def raw_from_nchw(expected, out_width_stride, c2):
    """Inverse of the donor NC1HWC2 / flat-1x1 unpack (same atom order)."""
    out_c, out_h, out_w = expected.shape
    align_out_c = max(32, align_up(out_c, 16))
    c1 = align_out_c // c2
    raw = np.zeros(c1 * out_width_stride * c2, dtype=FP16)
    atoms = out_h * out_w
    if atoms > out_width_stride:
        raise ValueError("output does not fit in the declared atom stride")
    for plane in range(c1):
        channels = expected[plane * c2 : min((plane + 1) * c2, out_c)]
        if channels.shape[0] == 0:
            continue
        for atom in range(atoms):
            off = plane * out_width_stride * c2 + atom * c2
            raw[off : off + channels.shape[0]] = channels[:, atom // out_w, atom % out_w]
    return raw


def validate_layout_roundtrip(m, task):
    p = task["p"]
    expected = task["expected"]
    ws = int(p["out_width_stride"])
    c2 = int(m.UNPACK_C2)
    raw = raw_from_nchw(expected, ws, c2)
    if task["out_layout"] == "flat_1x1":
        unpacked = m._unpack_flat_1x1_output(
            raw, expected.shape[0], expected.shape[1], expected.shape[2], ws, c2
        )
    else:
        unpacked = m._unpack_nc1hwc2_output(
            raw, expected.shape[0], expected.shape[1], expected.shape[2], c2, ws
        )
    if not np.array_equal(unpacked, expected):
        raise AssertionError(
            f"layout round-trip failed for task {task['out_index']}: "
            f"max diff {np.max(np.abs(unpacked.astype(np.float64) - expected.astype(np.float64)))}"
        )
    return raw


def build_task_command(m, task):
    p = task["p"]
    packed_input = m._pack_cdma_dc_feature_input_fp16(task["input_nchw"], p)
    packed_weight = m.pack_weights(
        task["weight_pack"],
        task["pack_out_c"],
        task["pack_in_c"],
        p["kh"],
        p["kw"],
        p["align_c"],
        task["pack_groups"],
    )
    body = [
        int(q)
        for q in m.make_conv2d_regs_from_params(
            p, 0, 0, 0, full_data_bank=bool(task.get("full_data_bank", False))
        )
    ]

    # Use the donor's own single-task tail writer so the terminal PC/VERSION
    # words are source-exact rather than re-derived here.
    m.write_regs_to_npu_task([body])
    cmd_words = [int(m.npu_regcmd[i]) for i in range(len(body) + m.PC_CHAIN_TAIL_QWORDS)]
    if len(cmd_words) != len(body) + 4:
        raise AssertionError("unexpected donor tail length")
    if cmd_words[-4:] != [
        int(m.E(m.reg.PC_REG, m.reg.PC_BASE_ADDRESS, 0)),
        int(m.E(m.reg.PC_REG, m.reg.PC_REGISTER_AMOUNTS, 0)),
        int(m.E(m.reg.VERSION, 0, 0)),
        int(m.E(m.reg.PC, m.reg.OPERATION_ENABLE, (6 << 1) | 1)),
    ]:
        raise AssertionError("donor terminal tail mismatch")

    task = dict(task)
    task["packed_input"] = packed_input
    task["packed_weight"] = packed_weight
    task["body"] = body
    task["cmd_words"] = cmd_words
    return task


ADDRESS_REGS = None


def address_register_map(m):
    global ADDRESS_REGS
    if ADDRESS_REGS is None:
        ADDRESS_REGS = {
            int(m.reg.CNA_FEATURE_DATA_ADDR): ("input", int(m.reg.CNA)),
            int(m.reg.CNA_DCOMP_ADDR0): ("weight", int(m.reg.CNA)),
            int(m.reg.DST_BASE_ADDR): ("output", int(m.reg.DPU)),
        }
    return ADDRESS_REGS


def scan_address_patches(m, task, global_offset):
    """Replace zero placeholders by patch declarations; returns (words, patches)."""
    addr_map = address_register_map(m)
    counts = {reg: 0 for reg in addr_map}
    patches = []
    words = list(task["cmd_words"])
    for local_index, word in enumerate(words):
        target, value, reg = command_parts(word)
        if reg not in addr_map:
            continue
        if local_index >= len(task["body"]):
            raise AssertionError("address register found in terminal tail")
        expected_target = addr_map[reg][1]
        if target != expected_target:
            raise AssertionError(
                f"address register 0x{reg:04x} has target 0x{target:04x}, expected 0x{expected_target:04x}"
            )
        if value != 0:
            raise AssertionError(f"address register 0x{reg:04x} is not a zero placeholder: 0x{value:08x}")
        counts[reg] += 1
        patches.append(
            dict(
                regcmd_index=int(global_offset + local_index),
                buffer=None,  # filled by the caller
                kind="value32",
                _role=addr_map[reg][0],
                _reg=reg,
            )
        )
    if any(count != 1 for count in counts.values()):
        raise AssertionError(f"address register counts are {counts}; expected one each")
    return words, patches


def reg_value(body, reg_offset):
    hits = [value for target, value, reg in (command_parts(w) for w in body) if reg == int(reg_offset)]
    if len(hits) != 1:
        raise AssertionError(f"register 0x{int(reg_offset):04x} appears {len(hits)} times")
    return hits[0]


def audit_task_geometry(m, task):
    """Cross-check packed byte counts against the command-stream geometry fields."""
    p = task["p"]
    body = task["body"]
    data_size0 = reg_value(body, m.reg.CNA_DATA_SIZE0)
    data_size1 = reg_value(body, m.reg.CNA_DATA_SIZE1)
    weight_size0 = reg_value(body, m.reg.CNA_WEIGHT_SIZE0)
    weight_size1 = reg_value(body, m.reg.CNA_WEIGHT_SIZE1)
    weight_size2 = reg_value(body, m.reg.CNA_WEIGHT_SIZE2)
    cbuf_con0 = reg_value(body, m.reg.CNA_CBUF_CON0)
    data_bank = cbuf_con0 & 0xF
    weight_bank = (cbuf_con0 >> 4) & 0xF
    if task.get("full_data_bank"):
        if data_bank != int(m.RK_CBUF_BANKS) - 1:
            raise AssertionError(f"full_data_bank requested but CNA_CBUF_CON0 data_bank={data_bank}")
        if weight_bank != 1:
            raise AssertionError(f"full_data_bank CNA_CBUF_CON0 weight_bank={weight_bank} != 1")
    width_stride = (data_size0 >> 16) & 0xFFFF
    in_h = data_size0 & 0xFFFF
    aligned_c = data_size1 & 0xFFFF
    real_c_minus_1 = (data_size1 >> 16) & 0xFFFF
    if width_stride != int(p["width_stride"]) or in_h != int(p["in_h"]):
        raise AssertionError("CNA_DATA_SIZE0 does not match task geometry")
    if real_c_minus_1 != int(p["in_c"]) - 1 or aligned_c != int(m._align_up(p["in_c"], p["align_c"])):
        raise AssertionError("CNA_DATA_SIZE1 does not match task geometry")
    expected_input_bytes = aligned_c * in_h * width_stride * 2
    if task["packed_input"].nbytes != expected_input_bytes:
        raise AssertionError(
            f"packed input {task['packed_input'].nbytes} != geometry {expected_input_bytes}"
        )
    if weight_size0 != task["packed_weight"].nbytes:
        raise AssertionError(
            f"packed weight {task['packed_weight'].nbytes} != CNA_WEIGHT_SIZE0 {weight_size0}"
        )
    per_kernel = int(p["kh"]) * int(p["kw"]) * aligned_c * 2
    if weight_size1 != per_kernel:
        raise AssertionError(f"CNA_WEIGHT_SIZE1 {weight_size1} != per-kernel {per_kernel}")
    kernels = weight_size2 & 0xFFFF
    expected_kernels = 1 if p["is_depthwise"] else int(p["out_c"])
    if kernels != expected_kernels:
        raise AssertionError(f"CNA_WEIGHT_SIZE2 kernels {kernels} != {expected_kernels}")
    if task["out_layout"] == "flat_1x1" and (int(p["kh"]) != 1 or int(p["kw"]) != 1):
        raise AssertionError("flat_1x1 used for a spatial task")
    if task["out_layout"] == "nc1hwc2" and int(p["kh"]) == 1 and int(p["kw"]) == 1:
        raise AssertionError("nc1hwc2 used for a 1x1 task")
    return dict(
        width_stride=width_stride,
        in_h=in_h,
        aligned_c=aligned_c,
        real_c=real_c_minus_1 + 1,
        weight_total_bytes=weight_size0,
        weight_per_kernel_bytes=weight_size1,
        weight_kernels=kernels,
        cbuf_data_bank=data_bank,
        cbuf_weight_bank=weight_bank,
        full_data_bank=bool(task.get("full_data_bank", False)),
        packed_input_bytes=int(task["packed_input"].nbytes),
        packed_weight_bytes=int(task["packed_weight"].nbytes),
    )


# ---------------------------------------------------------------------------
# Bundle writer
# ---------------------------------------------------------------------------


def write_case(m, spec):
    input_orig, input_eff, weight_orig = draw_case_inputs(spec)
    if spec["mode"] == DIRECT:
        tasks = build_direct_tasks(m, spec, input_eff, weight_orig)
    elif spec["mode"] == GROUPED:
        tasks = build_grouped_tasks(m, spec, input_eff, weight_orig)
    elif spec["mode"] == SPLIT_OC:
        tasks = build_split_oc_tasks(m, spec, input_eff, weight_orig)
    else:
        raise ValueError(spec["mode"])

    full_expected = build_full_expected(m, spec, input_eff, weight_orig)

    # Independent oracle cross-check (float64, explicit loops).
    independent = independent_naive_conv(
        input_eff[0], weight_orig, spec["out_c"], spec["kh"], spec["kw"],
        spec["groups"], spec["stride"],
    )
    if not np.array_equal(independent, m.compute_expected_nchw(
        input_eff[0][np.newaxis, ...], weight_orig, 1, spec["in_c"],
        input_eff.shape[2], input_eff.shape[3], spec["out_c"], spec["kh"], spec["kw"],
        groups=spec["groups"], stride=spec["stride"],
    )[0]):
        raise AssertionError("independent naive oracle disagrees with donor oracle")

    if len(tasks) > 1:
        combined = np.concatenate([t["expected"] for t in tasks], axis=0)
        if not np.array_equal(combined, full_expected):
            raise AssertionError(
                "per-task oracle concatenation disagrees with full oracle: "
                f"max diff {np.max(np.abs(combined.astype(np.float64) - full_expected.astype(np.float64)))}"
            )
    else:
        if not np.array_equal(tasks[0]["expected"], full_expected):
            raise AssertionError("single-task oracle disagrees with full oracle")

    # Build command streams and assign global offsets.
    built = []
    global_words = []
    offset = 0
    for index, task in enumerate(tasks):
        task = build_task_command(m, task)
        task["index"] = index
        task["regcmd_offset_words"] = offset
        task["regcmd_words"] = len(task["cmd_words"])
        task["body_qwords"] = len(task["body"])
        task["tail_qwords"] = 4
        task["geometry_audit"] = audit_task_geometry(m, task)
        words, patches = scan_address_patches(m, task, offset)
        task["patches"] = patches
        built.append(task)
        global_words.extend(words)
        advance = align_up(len(words), 2)
        if advance > len(words):
            global_words.extend([0] * (advance - len(words)))
        offset += advance

    # Allocate unique input/weight buffers, reusing byte-identical images.
    in_buffers = []
    in_by_hash = {}
    for task in built:
        for role, data in (("input", task["packed_input"]), ("weight", task["packed_weight"])):
            data_bytes = fp16_bytes(data)
            key = sha256_bytes(data_bytes)
            if key not in in_by_hash:
                name_hint = "a" if role == "input" else "w"
                name = name_hint if len(built) == 1 else f"{name_hint}{task['index']}"
                base = name
                suffix = 0
                existing = {b["name"] for b in in_buffers}
                while name in existing:
                    suffix += 1
                    name = f"{base}_{suffix}"
                record = dict(
                    name=name,
                    role=role,
                    data=data_bytes,
                    size=align_up(len(data_bytes), 16),
                    input=f"{name}.bin",
                    direction="in",
                )
                in_buffers.append(record)
                in_by_hash[key] = record
            else:
                record = in_by_hash[key]
            task[f"{role}_buffer"] = record["name"]

    # Output buffers are always separate (the schema has no buffer+offset patch).
    out_buffers = []
    expected_files = {}
    for task in built:
        p = task["p"]
        align_out_c = max(32, align_up(task["out_c"], 16))
        c2 = int(m.UNPACK_C2)
        c1 = align_up(align_out_c, c2) // c2
        raw_bytes = c1 * int(p["out_width_stride"]) * c2 * 2
        donor_output_bytes = int(m._output_count(p)) * 2
        if raw_bytes != donor_output_bytes:
            raise AssertionError(
                f"{spec['case']} task {task['index']} raw output {raw_bytes} != donor _output_count {donor_output_bytes}"
            )
        name = "out" if len(built) == 1 else f"out{task['index']}"
        expected_name = "expected.bin" if len(built) == 1 else f"expected_{name}.bin"
        record = dict(
            name=name,
            size=raw_bytes,
            output=f"{name}.bin",
            direction="out",
            expected=expected_name,
            out_c=task["out_c"],
            out_h=int(p["out_h"]),
            out_w=int(p["out_w"]),
            out_width_stride=int(p["out_width_stride"]),
            align_out_c=align_out_c,
            c1=c1,
            c2=c2,
            layout=task["out_layout"],
            task_index=task["index"],
        )
        out_buffers.append(record)
        task["output_buffer"] = name
        expected_files[name] = task["expected"]
        task["raw_expected"] = validate_layout_roundtrip(m, task)

    # Fill patch buffer names and sanity-check the role mapping.
    for task in built:
        for patch in task["patches"]:
            if patch["_role"] == "input":
                patch["buffer"] = task["input_buffer"]
            elif patch["_role"] == "weight":
                patch["buffer"] = task["weight_buffer"]
            elif patch["_role"] == "output":
                patch["buffer"] = task["output_buffer"]
            else:
                raise AssertionError(patch["_role"])
            patch.pop("_role")
            patch.pop("_reg")

    # Write the bundle directory.
    case_dir = CASES_DIR / spec["case"]
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True)

    regcmd_bytes = words_bytes(global_words)
    write_bytes(case_dir / "regcmd.bin", regcmd_bytes)

    for buffer in in_buffers:
        write_bytes(case_dir / buffer["input"], pack_bo_bytes(buffer["data"]))

    for buffer in out_buffers:
        write_bytes(case_dir / buffer["expected"], fp16_bytes(expected_files[buffer["name"]]))

    write_bytes(case_dir / "source_input_nchw.bin", fp16_bytes(input_orig))
    write_bytes(case_dir / "source_weight_nchw.bin", fp16_bytes(weight_orig))
    if spec.get("padded_zero_frame"):
        write_bytes(case_dir / "source_input_padded_nchw.bin", fp16_bytes(input_eff))

    if len(built) > 1:
        write_bytes(case_dir / "expected_combined.bin", fp16_bytes(full_expected))

    job_buffers = []
    for buffer in in_buffers:
        job_buffers.append(
            dict(
                name=buffer["name"],
                size=int(buffer["size"]),
                input=buffer["input"],
                direction="in",
            )
        )
    for buffer in out_buffers:
        job_buffers.append(
            dict(
                name=buffer["name"],
                size=int(buffer["size"]),
                direction="out",
                output=buffer["output"],
            )
        )

    job = dict(
        case=spec["case"],
        source_example=str(SOURCE_EXAMPLE),
        description=spec["description"],
        timeout_ns=6_000_000_000,
        tasks=[
            dict(
                regcmd_offset_words=int(t["regcmd_offset_words"]),
                regcmd_words=int(t["regcmd_words"]),
            )
            for t in built
        ],
        buffers=job_buffers,
        patches=[
            dict(regcmd_index=int(p["regcmd_index"]), buffer=p["buffer"], kind=p["kind"])
            for t in built
            for p in t["patches"]
        ],
    )
    write_bytes(case_dir / "job.json", (json.dumps(job, indent=2) + "\n").encode("utf-8"))

    source_sha = sha256_file(SOURCE_EXAMPLE)
    provenance = dict(
        case=spec["case"],
        generated_by="tools/gen_bundles.py",
        generated_utc=datetime.now(timezone.utc).isoformat(),
        source_example=str(SOURCE_EXAMPLE),
        source_sha256=source_sha,
        source_git_revision=git_revision(SOURCE_ROOT),
        host=dict(python=platform.python_version(), numpy=np.__version__),
        seed=42,
        shape=dict(
            batch=1,
            in_c=spec["in_c"],
            in_h=spec["in_h"],
            in_w=spec["in_w"],
            out_c=spec["out_c"],
            kh=spec["kh"],
            kw=spec["kw"],
            stride=spec["stride"],
            groups=spec["groups"],
            padded_zero_frame=bool(spec.get("padded_zero_frame", False)),
            effective_input_h=int(input_eff.shape[2]),
            effective_input_w=int(input_eff.shape[3]),
            out_h=int(full_expected.shape[1]),
            out_w=int(full_expected.shape[2]),
        ),
        branch=spec["branch"],
        builder=dict(
            function="make_conv2d_regs_from_params / make_conv2d_regs",
            lines="445-629, 711-717",
            tail_function="write_regs_to_npu_task (single-task terminal branch)",
            tail_lines="631-676",
            packing="pack_weights (380-386), _pack_cdma_dc_feature_input_fp16 (388-401)",
        ),
        tasks=[
            dict(
                index=int(t["index"]),
                regcmd_offset_words=int(t["regcmd_offset_words"]),
                regcmd_words=int(t["regcmd_words"]),
                body_qwords=int(t["body_qwords"]),
                tail_qwords=int(t["tail_qwords"]),
                input_buffer=t["input_buffer"],
                weight_buffer=t["weight_buffer"],
                output_buffer=t["output_buffer"],
                input_packed_bytes=int(t["packed_input"].nbytes),
                weight_packed_bytes=int(t["packed_weight"].nbytes),
                output_bytes=int(next(b["size"] for b in out_buffers if b["name"] == t["output_buffer"])),
                geometry_audit=t["geometry_audit"],
                patches=t["patches"],
            )
            for t in built
        ],
        placeholders=dict(
            value32_zero=True,
            note="DMA address registers are zero in regcmd.bin; job.json patches replace command bits [47:16] with each buffer's 32-bit DMA address.",
            address_registers=["CNA_FEATURE_DATA_ADDR=0x1070", "CNA_DCOMP_ADDR0=0x1110", "DPU DST_BASE_ADDR=0x4020"],
        ),
        oracle=dict(
            kind="host_numpy_naive_conv",
            source="conv_new_clean.compute_expected_nchw (lines 1010-1021)",
            independent_check="tools/gen_bundles.py independent_naive_conv (float64 loop)",
            dtype="float16",
            byte_order="little",
            layout="NCHW",
            accumulation="float64 accumulation of float16 operands, rounded once to float16",
            tolerance_atol=0.2,
            expected_files=[b["expected"] for b in out_buffers],
            combined_expected="expected_combined.bin" if len(built) > 1 else None,
        ),
    )
    write_bytes(case_dir / "provenance.json", (json.dumps(provenance, indent=2) + "\n").encode("utf-8"))

    return {
        "case": spec["case"],
        "status": "READY",
        "source_example": str(SOURCE_EXAMPLE),
        "source_lines": [
            f"{spec['source_shape_line']}: shape table row",
            "308-332: _conv_params (shape, alignment, stride, output geometry)",
            "380-401: weight/input packing",
            "445-629: make_conv2d_regs (register body)",
            "631-676: write_regs_to_npu_task (terminal PC tail)",
            "1010-1021: compute_expected_nchw oracle",
            spec["branch"],
        ],
        "shape": provenance["shape"],
        "description": spec["description"],
        "branch": spec["branch"],
        "task_count": len(built),
        "buffer_count": len(job_buffers),
        "patch_count": len(job["patches"]),
        "oracle": provenance["oracle"],
        "output_layouts": [
            dict(
                buffer=b["name"],
                output=b["output"],
                expected=b["expected"],
                raw_bytes=b["size"],
                out_c=b["out_c"],
                out_h=b["out_h"],
                out_w=b["out_w"],
                out_width_stride=b["out_width_stride"],
                align_out_c=b["align_out_c"],
                c1=b["c1"],
                c2=b["c2"],
                layout=b["layout"],
                task_index=b["task_index"],
            )
            for b in out_buffers
        ],
        "caveats": spec["caveats"],
        "files": {},
    }


def collect_hashes(case_dir: Path):
    files = {}
    for path in sorted(case_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(case_dir).as_posix()
            files[rel] = dict(size=path.stat().st_size, sha256=sha256_file(path))
    return files


def write_readme(manifest):
    ready = [c for c in manifest["cases"] if c["status"] == "READY"]
    blocked = [c for c in manifest["cases"] if c["status"] == "BLOCKED"]
    lines = []
    lines.append("# FP16 convolution capture bundles (device-free preparation)")
    lines.append("")
    lines.append("This family prepares small FP16 convolution capture bundles for the")
    lines.append("mainline Rocket NPU on the RK3588. It was generated without any board,")
    lines.append("`/dev/accel`, `/dev/dri`, `ssh`, `scp` or FPGA access. A later single")
    lines.append("worker owns the board and runs the queue under the shared lease.")
    lines.append("")
    lines.append(f"- READY cases: **{len(ready)}**")
    lines.append(f"- BLOCKED cases: **{len(blocked)}**")
    lines.append(f"- Bundle directory: `{FAMILY_DIR}`")
    lines.append("- Schema: `../CAPTURE_FORMAT.md`")
    lines.append(f"- Generated with `/usr/bin/python3` {manifest['host']['python']} and NumPy {manifest['host']['numpy']}; the validator is stdlib-only.")
    lines.append("")
    lines.append("## Source inspection")
    lines.append("")
    lines.append("| Source | Submission path | FP16 conv status | Used here |")
    lines.append("|---|---|---|---|")
    lines.append("| `examples/kernel_6_18/conv_new_clean.py` | Rocket via `rocket_runtime` (`drm_rocket_*`) | Cleanest current FP16 direct/grouped/depthwise/split-OC builder; valid-only geometry; pad register commented out | Yes, all READY cases |")
    lines.append("| `examples/kernel_6_18/simple_conv_fp16.py` | Rocket via its own `DRM_IOCTL_ROCKET_*` | FP16 conv; stride fixed at 1; no pad register; older duplicate builder | No |")
    lines.append("| `examples/kernel_6_18/conv_mesa_fp16.py` | Rocket via its own `DRM_IOCTL_ROCKET_*` | Mesa port; pad registers emitted, but register path uses uint8 zero-point/quantized semantics | No; cited for the pad blocker |")
    lines.append("| `examples/kernel_6_18/conv_new.py` | Rocket via `rocket_runtime` | Older `conv_new` variant; superseded by `conv_new_clean.py` | No |")
    lines.append("| `examples/kernel_6_18/conv_new_trscrs.py` | Rocket via `rocket_runtime` | Same builder with CRS translation helper; no pad register | No |")
    lines.append("| `examples/kernel_6_18/conv_0522.py` | Rocket via `rocket_runtime` | Explicit Y/K tile planner and split enum, but tile offsets/accumulation are placeholders in the executor | No; cited for the split-K blocker |")
    lines.append("| `examples/kernel_6_18/conv_draft.py` | Rocket via `rocket_runtime` | Draft; `PAD_MODE_SAME` flag does not emit `CNA_PAD_CON0` | No |")
    lines.append("| `examples/conv_tiles.py` | Vendor rknpu (`/dev/dri/card1`, `DRM_IOCTL_RKNPU_*`) | Tiled family corpus with PC/subcore task policy | No; BLOCKED (vendor ABI) |")
    lines.append("")
    lines.append("## Cases")
    lines.append("")
    lines.append("| Case | Status | Shape | Path |")
    lines.append("|---|---|---|---|")
    for case in manifest["cases"]:
        if case["status"] == "READY":
            s = case["shape"]
            shape = f"C{s['in_c']} {s['in_h']}x{s['in_w']} -> OC{s['out_c']} {s['out_h']}x{s['out_w']}, k{s['kh']}x{s['kw']}, s{s['stride']}, g{s['groups']}"
            path = case.get("branch", "")
        else:
            s = case.get("shape", {})
            if "in_c" in s:
                shape = f"C{s['in_c']} {s['in_h']}x{s['in_w']} -> OC{s['out_c']}, k{s.get('kh', '?')}x{s.get('kw', '?')}, s{s.get('stride', '?')}, g{s.get('groups', '?')}"
                if s.get("padding"):
                    shape += f", pad{s['padding']}"
                if s.get("split"):
                    shape += f", split-{s['split']}"
            else:
                shape = s.get("description", "")
            path = "blocked"
        lines.append(f"| `{case['case']}` | {case['status']} | {shape} | {path} |")
    lines.append("")
    lines.append("## Derivation")
    lines.append("")
    lines.append("1. The donor module is loaded with a host-only `rocket_runtime` stub. The stub")
    lines.append("   returns host byte buffers and fixed fake DMA addresses; it performs no ioctl")
    lines.append("   and opens no device. The donor's own `_conv_params`,")
    lines.append("   `_pack_cdma_dc_feature_input_fp16`, `pack_weights` and")
    lines.append("   `make_conv2d_regs_from_params` produce the shape choices, packed bytes and")
    lines.append("   register body. No register values are hand-written.")
    lines.append("2. Each task body is passed through the donor's")
    lines.append("   `write_regs_to_npu_task([body])`; its single-task terminal tail")
    lines.append("   (`PC_BASE_ADDRESS=0`, `PC_REGISTER_AMOUNTS=0`, `VERSION=0`,")
    lines.append("   `OPERATION_ENABLE=0xd`) is copied from the donor, not re-derived.")
    lines.append("3. The three DMA address registers in each body")
    lines.append("   (`CNA_FEATURE_DATA_ADDR=0x1070`, `CNA_DCOMP_ADDR0=0x1110`,")
    lines.append("   `DPU DST_BASE_ADDR=0x4020`) are written as zero placeholders and declared")
    lines.append("   as `value32` patches. `regcmd.bin` is the concatenated little-endian QWORD")
    lines.append("   stream; each task range is aligned to an even number of QWORDs exactly as")
    lines.append("   the donor offsets do.")
    lines.append("4. Input and weight bytes are exactly the donor packer output, padded with")
    lines.append("   zero bytes to a 16-byte BO size. Output BO sizes are")
    lines.append("   `ceil(align_out_c/8) * out_width_stride * 8 * 2` bytes, matching the donor")
    lines.append("   readback count. Outputs are not written by preparation.")
    lines.append("5. `expected*.bin` is a host-side NumPy oracle, not a device capture. The")
    lines.append("   primary oracle is the donor's `compute_expected_nchw` (float64 accumulation")
    lines.append("   of FP16 operands, rounded once to FP16); an independent explicit loop")
    lines.append("   oracle is cross-checked at generation time. Per-task oracle slices are")
    lines.append("   concatenated and compared against the full oracle for the multi-task cases.")
    lines.append("   The donor's own acceptance tolerance is `atol=0.2`.")
    lines.append("6. A local layout round-trip packs the oracle into the donor NC1HWC2/flat-1x1")
    lines.append("   raw order, runs the donor unpack function, and requires exact FP16 equality.")
    lines.append("")
    lines.append("## Bundle ABI choices and caveats")
    lines.append("")
    lines.append("- **Multi-task cases are not PC-linked.** The donor's multi-tile/group paths")
    lines.append("  call `npu_submit` once per tile and reuse scratch BOs. The bundle uses one job")
    lines.append("  with several task descriptors, each with a terminal PC tail. The patch schema")
    lines.append("  has no `regcmd` pseudo-buffer, so a real `PC_BASE_ADDRESS` link cannot be")
    lines.append("  expressed. `/usr/include/drm/rocket_accel.h` lines 111-116 state that all")
    lines.append("  tasks in the same job execute sequentially on the same core, so independent")
    lines.append("  terminal tasks are the schema-native encoding. The donor's `npu_reset` calls")
    lines.append("  `rocket_runtime.reset_npu`, which is a no-op in the mainline runtime")
    lines.append("  (`experimental/kernel_6_18/rocket_runtime.py` lines 159-160), so the donor's")
    lines.append("  per-tile submits do not reset the NPU between tiles either. If the later")
    lines.append("  worker needs explicit PC links, these two cases need a worker/schema extension.")
    lines.append("- **No buffer+offset patches.** The schema patches a whole buffer base address.")
    lines.append("  Grouped and split-OC cases therefore declare one output BO per task instead of")
    lines.append("  reusing one output BO at different offsets. The input BO is shared when the")
    lines.append("  bytes are identical. Output BOs should be freshly allocated/zeroed: the donor")
    lines.append("  clears its reused scratch output before each multi-tile submit, while each")
    lines.append("  bundle output BO is used by exactly one task. Only the first")
    lines.append("  `out_c * out_h * out_w` elements are defined by the oracle; aligned channel")
    lines.append("  lanes and stride-tail atoms are outside it.")
    lines.append("- **Task descriptor fields are worker defaults.** The donor also sets")
    lines.append("  `op_idx=1`, `enable_mask=0xd`, `int_mask=(1<<8)|(1<<9)` and")
    lines.append("  `int_clear=0x1ffff` on each `struct_rknpu_task`. The bundle `tasks` array only")
    lines.append("  carries `regcmd_offset_words` and `regcmd_words`, so the worker must apply its")
    lines.append("  standard Rocket descriptor defaults. If the worker exposes these fields, set")
    lines.append("  them to the donor values above. The donor's `npu_reset` call is a no-op on")
    lines.append("  the mainline runtime, so no extra reset action is implied by this schema.")
    lines.append("- **Padded case is a zero frame, not `CNA_PAD_CON0`.** The clean FP16 builder")
    lines.append("  comments out the pad register and computes valid-only geometry. The READY")
    lines.append("  padded case feeds an explicit zero border through the valid 3x3 path. A true")
    lines.append("  pad-register FP16 case is BLOCKED in the manifest.")
    lines.append("- **Stride 2 is source-implemented but table-uncovered.** `_conv_params` and the")
    lines.append("  `CNA_CONV_CON3` builder accept stride 2; the donor shape table only exercises")
    lines.append("  stride 1. The stride-2 case is a deliberate source-supported variant.")
    lines.append("- **Oracle is not hardware evidence.** FP16 accumulation order, aligned-channel")
    lines.append("  padding and the stride-tail atoms are not modeled byte-for-byte. Compare the")
    lines.append("  worker's raw `out*.bin` after applying the donor unpack; do not compare raw BO")
    lines.append("  bytes against a fabricated raw oracle.")
    lines.append("- **No special-value guarantee.** The oracle uses ordinary random finite inputs")
    lines.append("  in [-2, 2); NaN/inf/subnormal behavior is outside this family.")
    lines.append("")
    lines.append("## Blocked cases")
    lines.append("")
    for case in blocked:
        lines.append(f"### `{case['case']}`")
        lines.append("")
        lines.append(case["description"])
        lines.append("")
        lines.append(case["reason"])
        lines.append("")
    lines.append("## Local validation")
    lines.append("")
    lines.append("```")
    lines.append(f"/usr/bin/python3 {FAMILY_DIR / 'tools/gen_bundles.py'}   # regenerate (NumPy required)")
    lines.append(f"/usr/bin/python3 {FAMILY_DIR / 'tools/validate_bundles.py'}  # stdlib-only parser")
    lines.append(f"/usr/bin/python3 {FAMILY_DIR / 'tools/compare_oracle.py'} --all  # after a capture")
    lines.append("```")
    lines.append("")
    lines.append("The validator checks JSON shape, buffer declarations and file sizes, regcmd")
    lines.append("length, task ranges, terminal tails, every address-register placeholder and its")
    lines.append("patch, patch index ranges, output layout sizes and manifest hashes. It does not")
    lines.append("run a device and does not accept a CPU result as a capture.")
    lines.append("")
    lines.append("## Board execution")
    lines.append("")
    lines.append("The later worker runs one case at a time under the shared board lease, copies")
    lines.append("each `buffers[].input` into a fresh BO, submits the declared task ranges, reads")
    lines.append("back each `out`/`inout` BO and writes `buffers[].output`. Preparation does not")
    lines.append("submit, program or flash anything.")
    lines.append("")
    (FAMILY_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    m = _load_donor()
    CASES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"source: {SOURCE_EXAMPLE}")
    print(f"source sha256: {sha256_file(SOURCE_EXAMPLE)}")
    print(f"donor terminal tail qwords: {m.PC_CHAIN_TAIL_QWORDS}")

    manifest_cases = []
    for spec in CASES:
        print(f"building {spec['case']} ...", flush=True)
        entry = write_case(m, spec)
        case_dir = CASES_DIR / spec["case"]
        entry["files"] = collect_hashes(case_dir)
        manifest_cases.append(entry)
        print(
            f"  tasks={entry['task_count']} buffers={entry['buffer_count']} "
            f"files={len(entry['files'])}"
        )

    for blocked in BLOCKED_CASES:
        manifest_cases.append(dict(blocked))

    manifest = dict(
        family="conv-fp16",
        format="rk3588-example-captures/1",
        generated_utc=datetime.now(timezone.utc).isoformat(),
        description="Device-free FP16 convolution capture bundles for mainline Rocket on RK3588.",
        source_revision=dict(
            root=str(SOURCE_ROOT),
            git_revision=git_revision(SOURCE_ROOT),
            selected_source=str(SOURCE_EXAMPLE),
            selected_source_sha256=sha256_file(SOURCE_EXAMPLE),
            inspected_sources=[
                str(SOURCE_EXAMPLE),
                str(SOURCE_ROOT / "examples/kernel_6_18/simple_conv_fp16.py"),
                str(SOURCE_MESA),
                str(SOURCE_ROOT / "examples/kernel_6_18/conv_new.py"),
                str(SOURCE_ROOT / "examples/kernel_6_18/conv_new_trscrs.py"),
                str(SOURCE_ROOT / "examples/kernel_6_18/conv_0522.py"),
                str(SOURCE_ROOT / "examples/kernel_6_18/conv_draft.py"),
                str(SOURCE_VENDOR_TILES),
            ],
        ),
        host=dict(python=platform.python_version(), numpy=np.__version__),
        preparation_tools={
            name: dict(size=(HERE / name).stat().st_size, sha256=sha256_file(HERE / name))
            for name in ("gen_bundles.py", "validate_bundles.py", "compare_oracle.py")
            if (HERE / name).is_file()
        },
        counts=dict(
            ready=sum(1 for c in manifest_cases if c["status"] == "READY"),
            blocked=sum(1 for c in manifest_cases if c["status"] == "BLOCKED"),
            total=len(manifest_cases),
        ),
        cases=manifest_cases,
    )
    write_bytes(FAMILY_DIR / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    write_readme(manifest)
    print(
        f"wrote {manifest['counts']['ready']} READY / {manifest['counts']['blocked']} BLOCKED"
    )
    print(f"manifest: {FAMILY_DIR / 'manifest.json'}")
    print(f"README:   {FAMILY_DIR / 'README.md'}")


if __name__ == "__main__":
    main()
