#!/usr/bin/env python3
"""Generate device-free RK3588 integer-elementwise capture bundles.

This script is a host-side preparation tool.  It does not open /dev/accel*,
does not submit anything, and does not talk to the Orange Pi.

The register streams below are transcribed from the two source examples:

  /home/fedora/rk3588/examples/kernel_6_18/elementwise_int.py
  /home/fedora/rk3588/examples/expt/elementwise_int.py

Every QWORD is built by the same ``emit(target, offset, value)`` encoding the
examples use::

    (target << 48) | ((value & 0xffffffff) << 16) | offset

so a ``value32`` patch over bits [47:16] is exactly an RK DMA address write.

The generator is pure Python (no NumPy) so the bundle bytes are reproducible on
the board-side worker host.  A separate cross-check script imports the real
examples under NumPy and compares every generated QWORD and byte.

Outputs are written only under this capture family directory.
"""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "cases"
MANIFEST_PATH = ROOT / "manifest.json"
BUFFER_SIZE = 4096

KERNEL_SRC = "/home/fedora/rk3588/examples/kernel_6_18/elementwise_int.py"
EXPT_SRC = "/home/fedora/rk3588/examples/expt/elementwise_int.py"

# Placeholders used inside regcmd.bin.  They are deliberately distinct so a
# missing patch is visible; the worker replaces them with real DMA addresses.
OUT_PH = 0x20000000
A_PH = 0x10000000
B_PH = 0x10010000

# ---------------------------------------------------------------------------
# Constants copied from the examples.
# ---------------------------------------------------------------------------

TARGET_DPU = 0x1001
TARGET_RDMA = 0x2001
TARGET_PC = 0x0081
TARGET_PC_REG = 0x0101
TARGET_VERSION = 0x0041

OPERATION_ENABLE = 0x0008
PC_BASE_ADDRESS = 0x0010
PC_REGISTER_AMOUNTS = 0x0014

S_POINTER = 0x4004
FEATURE_MODE_CFG = 0x400C
DATA_FORMAT = 0x4010
DST_BASE_ADDR = 0x4020
DST_SURF_STRIDE = 0x4024
DATA_CUBE_WIDTH = 0x4030
DATA_CUBE_HEIGHT = 0x4034
DATA_CUBE_NOTCH = 0x4038
DATA_CUBE_CHANNEL = 0x403C
BS_CFG = 0x4040
BS_ALU_CFG = 0x4044
BS_MUL_CFG = 0x4048
BS_OW_CFG = 0x4050
WDMA_SIZE_0 = 0x4058
WDMA_SIZE_1 = 0x405C
BN_CFG = 0x4060
BN_ALU_CFG = 0x4064
BN_MUL_CFG = 0x4068
BN_RELUX_CMP_VALUE = 0x406C
EW_CFG = 0x4070
EW_CVT_OFFSET_VALUE = 0x4074
EW_CVT_SCALE_VALUE = 0x4078
OUT_CVT_OFFSET = 0x4080
OUT_CVT_SCALE = 0x4084
OUT_CVT_SHIFT = 0x4088
SURFACE_ADD = 0x40C0

RDMA_S_POINTER = 0x5004
RDMA_DATA_CUBE_WIDTH = 0x500C
RDMA_DATA_CUBE_HEIGHT = 0x5010
RDMA_DATA_CUBE_CHANNEL = 0x5014
RDMA_SRC_BASE_ADDR = 0x5018
RDMA_BRDMA_CFG = 0x501C
RDMA_BS_BASE_ADDR = 0x5020
RDMA_NRDMA_CFG = 0x5028
RDMA_BN_BASE_ADDR = 0x502C
RDMA_ERDMA_CFG = 0x5034
RDMA_EW_BASE_ADDR = 0x5038
RDMA_EW_SURF_STRIDE = 0x5040
RDMA_FEATURE_MODE_CFG = 0x5044
RDMA_SRC_DMA_CFG = 0x5048
RDMA_SURF_NOTCH = 0x504C
RDMA_WEIGHT = 0x5068
RDMA_EW_SURF_NOTCH = 0x506C

PRECISION_INT8 = 0
PRECISION_INT16 = 1
PRECISION_FP16 = 2
PRECISION_INT32 = 4

ERDMA_SIZE_INT8 = 1
ERDMA_SIZE_INT16 = 2
ERDMA_SIZE_INT32 = 3

EW_DATA_MODE_PER_PIXEL = 1

EW_ALU_MAX = 0
EW_ALU_MIN = 1
EW_ALU_ADD = 2
EW_ALU_MINUS = 4

EW_OP_TYPE_ALU = 0
EW_OP_TYPE_MUL = 1

OPERATIONS = {
    "MAX": {"alu_algorithm": EW_ALU_MAX, "integer_supported": True},
    "MIN": {"alu_algorithm": EW_ALU_MIN, "integer_supported": True},
    "ADD": {"alu_algorithm": EW_ALU_ADD, "integer_supported": True},
    "DIV": {"alu_algorithm": 3, "integer_supported": False},
    "MINUS": {"alu_algorithm": EW_ALU_MINUS, "integer_supported": True},
    "ABS": {"alu_algorithm": 5, "integer_supported": True},
    "NEG": {"alu_algorithm": 6, "integer_supported": True},
    "FLOOR": {"alu_algorithm": 7, "integer_supported": False},
    "CEIL": {"alu_algorithm": 8, "integer_supported": False},
    "MUL": {"op_type": EW_OP_TYPE_MUL, "integer_supported": True},
}

DTYPES = {
    "INT8": {
        "precision": PRECISION_INT8,
        "element_size": ERDMA_SIZE_INT8,
        "item_size": 1,
        "limits": (-128, 127),
    },
    "INT16": {
        "precision": PRECISION_INT16,
        "element_size": ERDMA_SIZE_INT16,
        "item_size": 2,
        "limits": (-32768, 32767),
    },
    "INT32": {
        "precision": PRECISION_INT32,
        "element_size": ERDMA_SIZE_INT32,
        "item_size": 4,
        "limits": (-2147483648, 2147483647),
    },
}


def emit(target, offset, value):
    """Encode one decoded register write into a Rocket regcmd QWORD."""
    return (target << 48) | ((int(value) & 0xFFFFFFFF) << 16) | offset


def dpu_feature_mode():
    # burst_len=15, output_mode=2, flying_mode=1.
    return (15 << 5) | (2 << 1) | 1


def dpu_data_format(precision):
    # OUT_PRECISION[31:29], IN_PRECISION[28:26], PROC_PRECISION[2:0].
    return (precision << 29) | (precision << 26) | precision


def dpu_cube_channel(channels_minus_one):
    # ORIG_CHANNEL[28:16] and CHANNEL[12:0].
    return (channels_minus_one << 16) | channels_minus_one


def dpu_ew_cfg(element_size, operation, converter_bypass):
    # Per-pixel ERDMA, selected element width, RELU/LUT bypass, operand from ERDMA.
    op = OPERATIONS[operation]
    value = (
        (EW_DATA_MODE_PER_PIXEL << 28)
        | (element_size << 22)
        | (1 << 9)
        | (1 << 7)
        | (1 << 6)
    )
    if op.get("op_type", EW_OP_TYPE_ALU) == EW_OP_TYPE_MUL:
        value |= EW_OP_TYPE_MUL << 2
    else:
        value |= op["alu_algorithm"] << 16
    if operation in ("MAX", "MIN"):
        value |= 1 << 21  # EW_EQUAL_EN, matching RKNN min/max captures.
    if converter_bypass:
        value |= 1 << 8
    return value


def rdma_erdma_cfg(element_size):
    # Per-pixel ERDMA mode and ERDMA_DATA_SIZE[3:2].
    return (EW_DATA_MODE_PER_PIXEL << 30) | (element_size << 2)


def rdma_feature_mode(precision):
    # IN_PRECISION[17:15], burst_len=15, PROC_PRECISION[7:5], flying_mode=1.
    return (precision << 15) | (15 << 11) | (precision << 5) | 1


# ---------------------------------------------------------------------------
# Register streams, transcribed from the source examples.
# ---------------------------------------------------------------------------


def make_regcmds(output_dma, input_dma, ew_dma, precision, element_size,
                 width, channels, operation):
    """kernel_6_18/elementwise_int.py lines 314-352 (18 QWORDs)."""
    channels_minus_one = channels - 1
    converter_bypass = precision == PRECISION_INT32
    return [
        emit(TARGET_DPU, FEATURE_MODE_CFG, dpu_feature_mode()),
        emit(TARGET_DPU, DATA_FORMAT, dpu_data_format(precision)),
        emit(TARGET_DPU, DATA_CUBE_CHANNEL, dpu_cube_channel(channels_minus_one)),
        emit(TARGET_DPU, DATA_CUBE_WIDTH, width - 1),
        emit(TARGET_DPU, EW_CFG, dpu_ew_cfg(element_size, operation, converter_bypass)),
        # Integer EW conversion needs a scale of 1. INT32 bypasses the converter.
        emit(TARGET_DPU, EW_CVT_SCALE_VALUE, 1),
        emit(TARGET_RDMA, RDMA_DATA_CUBE_WIDTH, width - 1),
        emit(TARGET_RDMA, RDMA_DATA_CUBE_HEIGHT, 0),
        emit(TARGET_RDMA, RDMA_DATA_CUBE_CHANNEL, channels_minus_one),
        emit(TARGET_RDMA, RDMA_ERDMA_CFG, rdma_erdma_cfg(element_size)),
        emit(TARGET_DPU, DST_BASE_ADDR, output_dma),
        emit(TARGET_RDMA, RDMA_SRC_BASE_ADDR, input_dma),
        emit(TARGET_RDMA, RDMA_EW_BASE_ADDR, ew_dma),
        emit(TARGET_RDMA, RDMA_FEATURE_MODE_CFG, rdma_feature_mode(precision)),
        emit(TARGET_PC_REG, PC_BASE_ADDRESS, 0),
        emit(TARGET_PC_REG, PC_REGISTER_AMOUNTS, 0),
        emit(TARGET_VERSION, 0, 0),
        # Enable RDMA and DPU through PC; enable_mask remains the known-safe 0x18.
        emit(TARGET_PC, OPERATION_ENABLE, 0x18),
    ]


def make_layout_regcmds(output_dma, input_dma, ew_dma, precision, element_size,
                        width, channels, operation):
    """expt/elementwise_int.py lines 529-596 (40 QWORDs)."""
    channels_minus_one = channels - 1
    surface_stride = width << 4
    converter_bypass = precision == PRECISION_INT32
    return [
        emit(TARGET_DPU, S_POINTER, 0xE),
        emit(TARGET_RDMA, RDMA_S_POINTER, 0xE),
        emit(TARGET_RDMA, RDMA_BRDMA_CFG, 1),
        emit(TARGET_RDMA, RDMA_NRDMA_CFG, 1),
        emit(TARGET_DPU, FEATURE_MODE_CFG, dpu_feature_mode()),
        emit(TARGET_DPU, DATA_FORMAT, dpu_data_format(precision)),
        emit(TARGET_DPU, DST_SURF_STRIDE, surface_stride),
        emit(TARGET_DPU, DATA_CUBE_WIDTH, width - 1),
        emit(TARGET_DPU, DATA_CUBE_HEIGHT, 0),
        emit(TARGET_DPU, DATA_CUBE_NOTCH, 0),
        emit(TARGET_DPU, DATA_CUBE_CHANNEL, dpu_cube_channel(channels_minus_one)),
        emit(TARGET_DPU, BS_CFG, 0x53),
        emit(TARGET_DPU, BS_ALU_CFG, 0),
        emit(TARGET_DPU, BS_MUL_CFG, 0),
        emit(TARGET_DPU, BS_OW_CFG, 2),
        emit(TARGET_DPU, WDMA_SIZE_0, channels_minus_one),
        emit(TARGET_DPU, WDMA_SIZE_1, width - 1),
        emit(TARGET_DPU, BN_CFG, 0x53),
        emit(TARGET_DPU, BN_ALU_CFG, 0),
        emit(TARGET_DPU, BN_MUL_CFG, 0),
        emit(TARGET_DPU, EW_CFG, dpu_ew_cfg(element_size, operation, converter_bypass)),
        emit(TARGET_DPU, EW_CVT_SCALE_VALUE, 1),
        emit(TARGET_DPU, SURFACE_ADD, surface_stride),
        emit(TARGET_RDMA, RDMA_DATA_CUBE_WIDTH, width - 1),
        emit(TARGET_RDMA, RDMA_DATA_CUBE_HEIGHT, 0),
        emit(TARGET_RDMA, RDMA_DATA_CUBE_CHANNEL, channels_minus_one),
        emit(TARGET_RDMA, RDMA_ERDMA_CFG, rdma_erdma_cfg(element_size)),
        emit(TARGET_RDMA, RDMA_EW_SURF_STRIDE, surface_stride),
        emit(TARGET_RDMA, RDMA_SRC_DMA_CFG, 0),
        emit(TARGET_RDMA, RDMA_SURF_NOTCH, 0),
        emit(TARGET_RDMA, RDMA_EW_SURF_NOTCH, 0),
        emit(TARGET_DPU, DST_BASE_ADDR, output_dma),
        emit(TARGET_RDMA, RDMA_SRC_BASE_ADDR, input_dma),
        emit(TARGET_RDMA, RDMA_EW_BASE_ADDR, ew_dma),
        emit(TARGET_RDMA, RDMA_FEATURE_MODE_CFG, rdma_feature_mode(precision)),
        emit(TARGET_RDMA, RDMA_WEIGHT, (1 << 24) | (1 << 16) | (1 << 8) | 1),
        emit(TARGET_PC_REG, PC_BASE_ADDRESS, 0),
        emit(TARGET_PC_REG, PC_REGISTER_AMOUNTS, 0),
        emit(TARGET_VERSION, 0, 0),
        emit(TARGET_PC, OPERATION_ENABLE, 0x18),
    ]


def prepare_and_run_prefix():
    """expt/elementwise_int.py lines 752-760: re-arm both register groups."""
    return [
        emit(TARGET_DPU, S_POINTER, 0xE),
        emit(TARGET_RDMA, RDMA_S_POINTER, 0xE),
        # Bit 0 is *_DISABLE: one prevents unused auxiliary clients from
        # fetching stale BRDMA/NRDMA addresses left by an earlier task.
        emit(TARGET_RDMA, RDMA_BRDMA_CFG, 1),
        emit(TARGET_RDMA, RDMA_NRDMA_CFG, 1),
    ]


def int16_add_to_int32_regcmds(output_dma, input_dma, ew_dma):
    """kernel_6_18/elementwise_int.py lines 586-651 (31 QWORDs)."""
    return [
        emit(TARGET_DPU, FEATURE_MODE_CFG, dpu_feature_mode()),
        emit(
            TARGET_DPU,
            DATA_FORMAT,
            (PRECISION_INT32 << 29) | (PRECISION_INT16 << 26) | PRECISION_INT16,
        ),
        # The captured 16-to-32 layout emits two four-lane surfaces.
        emit(TARGET_DPU, DST_SURF_STRIDE, 1 << 4),
        emit(TARGET_DPU, DATA_CUBE_WIDTH, 0),
        emit(TARGET_DPU, DATA_CUBE_HEIGHT, 0),
        emit(TARGET_DPU, DATA_CUBE_NOTCH, 0),
        emit(TARGET_DPU, DATA_CUBE_CHANNEL, dpu_cube_channel(7)),
        emit(TARGET_DPU, BS_CFG, (1 << 6) | (1 << 4) | (1 << 1) | 1),
        # SIZE_E_0/1/2=1 is required to regroup all eight INT16 lanes.
        emit(TARGET_DPU, BS_OW_CFG, (1 << 8) | (1 << 5) | (1 << 2) | (1 << 1)),
        emit(TARGET_DPU, WDMA_SIZE_0, 7),
        emit(TARGET_DPU, WDMA_SIZE_1, 0),
        emit(TARGET_DPU, BN_CFG, (1 << 6) | (1 << 4) | (1 << 1) | 1),
        emit(TARGET_DPU, EW_CFG, dpu_ew_cfg(ERDMA_SIZE_INT16, "ADD", False)),
        emit(TARGET_DPU, EW_CVT_OFFSET_VALUE, 0),
        emit(TARGET_DPU, EW_CVT_SCALE_VALUE, 1),
        emit(TARGET_DPU, OUT_CVT_OFFSET, 0),
        emit(TARGET_DPU, OUT_CVT_SCALE, 1),
        emit(TARGET_DPU, OUT_CVT_SHIFT, 0),
        emit(TARGET_DPU, SURFACE_ADD, 2 << 4),
        emit(TARGET_RDMA, RDMA_DATA_CUBE_WIDTH, 0),
        emit(TARGET_RDMA, RDMA_DATA_CUBE_HEIGHT, 0),
        emit(TARGET_RDMA, RDMA_DATA_CUBE_CHANNEL, 7),
        emit(TARGET_RDMA, RDMA_ERDMA_CFG, rdma_erdma_cfg(ERDMA_SIZE_INT16)),
        emit(TARGET_DPU, DST_BASE_ADDR, output_dma),
        emit(TARGET_RDMA, RDMA_SRC_BASE_ADDR, input_dma),
        emit(TARGET_RDMA, RDMA_EW_BASE_ADDR, ew_dma),
        emit(TARGET_RDMA, RDMA_FEATURE_MODE_CFG, rdma_feature_mode(PRECISION_INT16)),
        emit(TARGET_PC_REG, PC_BASE_ADDRESS, 0),
        emit(TARGET_PC_REG, PC_REGISTER_AMOUNTS, 0),
        emit(TARGET_VERSION, 0, 0),
        emit(TARGET_PC, OPERATION_ENABLE, 0x18),
    ]


# ---------------------------------------------------------------------------
# Data layout and oracle helpers.
# ---------------------------------------------------------------------------


def clamp(value, dtype_name):
    lo, hi = DTYPES[dtype_name]["limits"]
    return max(lo, min(hi, int(value)))


def signed16(value):
    value &= 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


def oracle_value(operation, a, b, dtype_name):
    """Mirror integer_expected() plus the captured INT32-MUL limitation."""
    if operation == "MAX":
        return int(max(a, b))
    if operation == "MIN":
        return int(min(a, b))
    if operation == "ADD":
        return clamp(a + b, dtype_name)
    if operation == "MINUS":
        return clamp(a - b, dtype_name)
    if operation == "MUL":
        if dtype_name == "INT32":
            # Captured hardware limitation: the EW MUL operand decodes as
            # signed INT16 even though ERDMA is packed as INT32.
            return clamp(a * signed16(b), dtype_name)
        return clamp(a * b, dtype_name)
    raise ValueError(f"unsupported operation for oracle: {operation}")


def contiguous_encode(values, item_size):
    data = b"".join(int(v).to_bytes(item_size, "little", signed=True) for v in values)
    return data, b"\xff" * len(data)


def pack_c1wc2(values, width, channels, item_size):
    """Pack logical WC data into contiguous 16-byte DPU channel surfaces.

    Returns (data, mask) where mask has 0xFF exactly over the valid logical
    lanes and 0x00 over the surface padding.
    """
    atom_channels = 16 // item_size
    surfaces = (channels + atom_channels - 1) // atom_channels
    total = surfaces * width * atom_channels
    data = bytearray(total * item_size)
    mask = bytearray(total * item_size)
    for pixel in range(width):
        for channel in range(channels):
            value = values[pixel * channels + channel]
            offset = (
                ((channel // atom_channels) * width + pixel) * atom_channels
                + (channel % atom_channels)
            ) * item_size
            data[offset:offset + item_size] = int(value).to_bytes(
                item_size, "little", signed=True
            )
            mask[offset:offset + item_size] = b"\xff" * item_size
    return bytes(data), bytes(mask)


def pad(data, size=BUFFER_SIZE):
    if len(data) > size:
        raise ValueError(f"payload {len(data)} exceeds buffer size {size}")
    return data + b"\x00" * (size - len(data))


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_qword_index(qwords, target, offset):
    matches = [
        index
        for index, qword in enumerate(qwords)
        if ((qword >> 48) & 0xFFFF) == target and (qword & 0xFFFF) == offset
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one write to target 0x{target:04x} "
            f"offset 0x{offset:04x}, found {matches}"
        )
    return matches[0]


def packet_patches(qwords):
    """Build the three value32 patches shared by every integer EW stream."""
    return [
        {
            "regcmd_index": find_qword_index(qwords, TARGET_DPU, DST_BASE_ADDR),
            "buffer": "out",
            "kind": "value32",
        },
        {
            "regcmd_index": find_qword_index(qwords, TARGET_RDMA, RDMA_SRC_BASE_ADDR),
            "buffer": "a",
            "kind": "value32",
        },
        {
            "regcmd_index": find_qword_index(qwords, TARGET_RDMA, RDMA_EW_BASE_ADDR),
            "buffer": "b",
            "kind": "value32",
        },
    ]


def write_case(name, source_example, source_refs, description, qwords,
               a_payload, b_payload, expected, expected_mask, oracle,
               dtype_name, operation, layout, width, channels, notes,
               output_item_size, special_values=None):
    case_dir = CASES_DIR / name
    case_dir.mkdir(parents=True, exist_ok=True)

    regcmd = b"".join(int(qword).to_bytes(8, "little") for qword in qwords)
    (case_dir / "regcmd.bin").write_bytes(regcmd)
    (case_dir / "a.bin").write_bytes(pad(a_payload))
    (case_dir / "b.bin").write_bytes(pad(b_payload))
    (case_dir / "expected.bin").write_bytes(pad(expected))
    (case_dir / "expected.mask.bin").write_bytes(pad(expected_mask))

    job = {
        "case": name,
        "source_example": source_example,
        "description": description,
        "timeout_ns": 6000000000,
        "tasks": [{"regcmd_offset_words": 0, "regcmd_words": len(qwords)}],
        "buffers": [
            {"name": "a", "size": BUFFER_SIZE, "input": "a.bin", "direction": "in"},
            {"name": "b", "size": BUFFER_SIZE, "input": "b.bin", "direction": "in"},
            {"name": "out", "size": BUFFER_SIZE, "direction": "out", "output": "out.bin"},
        ],
        "patches": packet_patches(qwords),
    }
    (case_dir / "job.json").write_text(
        json.dumps(job, indent=2) + "\n", encoding="utf-8"
    )

    files = ["a.bin", "b.bin", "expected.bin", "expected.mask.bin", "job.json", "regcmd.bin"]
    hashes = {name_: sha256_file(case_dir / name_) for name_ in files}
    bundle_hash = hashlib.sha256(
        "".join(f"{name_}\0{hashes[name_]}\n" for name_ in sorted(hashes)).encode()
    ).hexdigest()

    entry = {
        "case": name,
        "status": "READY",
        "dtype": dtype_name,
        "operation": operation,
        "layout": layout,
        "shape": {"width": width, "channels": channels, "elements": width * channels},
        "output_item_size": output_item_size,
        "source_example": source_example,
        "source_refs": source_refs,
        "description": description,
        "regcmd_qwords": len(qwords),
        "oracle": oracle,
        "bundle_dir": f"cases/{name}",
        "hashes": hashes,
        "bundle_hash": bundle_hash,
        "notes": notes,
    }
    if special_values:
        entry["special_values"] = special_values
    return entry


# ---------------------------------------------------------------------------
# Case definitions.
# ---------------------------------------------------------------------------

KERNEL_REFS_SIMPLE = [
    {"path": KERNEL_SRC, "lines": "314-352", "symbol": "make_regcmds"},
    {"path": KERNEL_SRC, "lines": "355-454", "symbol": "run_operation"},
    {"path": KERNEL_SRC, "lines": "100-111", "symbol": "OPERATIONS"},
    {"path": KERNEL_SRC, "lines": "659-682", "symbol": "integer_expected"},
    {"path": KERNEL_SRC, "lines": "685-711", "symbol": "DTYPES"},
    {"path": KERNEL_SRC, "lines": "714-731", "symbol": "__main__ argument parsing"},
]

EXPT_REFS_LAYOUT = [
    {"path": EXPT_SRC, "lines": "529-596", "symbol": "make_layout_regcmds"},
    {"path": EXPT_SRC, "lines": "599-696", "symbol": "run_integer_layout"},
    {"path": EXPT_SRC, "lines": "733-799", "symbol": "prepare_and_run"},
    {"path": EXPT_SRC, "lines": "752-760", "symbol": "S_POINTER/BRDMA/NRDMA re-arm prefix"},
    {"path": EXPT_SRC, "lines": "505-526", "symbol": "pack_c1wc2/unpack_c1wc2"},
    {"path": EXPT_SRC, "lines": "699-730", "symbol": "validate_integer_layout_streams"},
    {"path": EXPT_SRC, "lines": "2185-2213", "symbol": "integer_expected"},
    {"path": EXPT_SRC, "lines": "2216-2242", "symbol": "DTYPES"},
    {"path": EXPT_SRC, "lines": "2245-2278", "symbol": "--probe-layout argument parsing"},
]

KERNEL_REFS_INT16_TO_INT32 = [
    {"path": KERNEL_SRC, "lines": "586-651", "symbol": "run_int16_add_to_int32"},
    {"path": KERNEL_SRC, "lines": "457-513", "symbol": "prepare_and_run"},
    {"path": KERNEL_SRC, "lines": "659-682", "symbol": "integer_expected"},
]

SIMPLE_A_INT8 = [-100, -24, -7, -1, 0, 1, 24, 100]
SIMPLE_B_INT8 = [20, -6, 2, -1, 1, 2, -3, 5]

SIMPLE_A_INT16 = [-30000, -1200, -7, -1, 0, 1, 1200, 30000]
SIMPLE_B_INT16 = [1000, -30, 2, -1, 1, 2, -30, 1000]

SIMPLE_A_INT32 = [-1000, -2000, -7, -1, 0, 1, 2000, 1000]
SIMPLE_B_INT32 = [50000, -50000, 2, -1, 1, 2, -50000, 50000]

# Small MUL values that stay inside the destination range, so the MUL capture
# tests multiply semantics rather than saturation policy.
MUL_A_8 = [-8, -6, -4, -2, -1, 0, 1, 3]
MUL_B_8 = [3, -2, 5, -1, 1, 7, 2, 4]


def simple_case(name, dtype_name, operation, a_values, b_values, channels,
                description, oracle_formula, confidence, notes,
                special_values=None):
    config = DTYPES[dtype_name]
    width = len(a_values) // channels
    if width * channels != len(a_values):
        raise ValueError(f"{name}: element count not divisible by {channels}")
    qwords = make_regcmds(
        OUT_PH, A_PH, B_PH,
        config["precision"], config["element_size"], width, channels, operation,
    )
    expected_values = [
        oracle_value(operation, a_values[index], b_values[index], dtype_name)
        for index in range(len(a_values))
    ]
    a_payload, _ = contiguous_encode(a_values, config["item_size"])
    b_payload, _ = contiguous_encode(b_values, config["item_size"])
    expected, expected_mask = contiguous_encode(expected_values, config["item_size"])
    oracle = {
        "kind": "host-python-formula",
        "formula": oracle_formula,
        "expected": "expected.bin",
        "mask": "expected.mask.bin",
        "compare": (
            "masked byte equality over the full 4096-byte output BO; "
            "0xFF mask bytes mark asserted lanes, 0x00 bytes are surface/BO padding"
        ),
        "confidence": confidence,
        "source_symbol": "integer_expected",
    }
    return write_case(
        name=name,
        source_example=KERNEL_SRC,
        source_refs=KERNEL_REFS_SIMPLE,
        description=description,
        qwords=qwords,
        a_payload=a_payload,
        b_payload=b_payload,
        expected=expected,
        expected_mask=expected_mask,
        oracle=oracle,
        dtype_name=dtype_name,
        operation=operation,
        layout="contiguous-WC (example run_operation, native dtype tobytes)",
        width=width,
        channels=channels,
        notes=notes,
        output_item_size=config["item_size"],
        special_values=special_values,
    )


LAYOUT_A_9 = [-47, -30, -13, 4, 21, 38, -46, -29, -12]
LAYOUT_B_9 = [-8, 3, 14, -6, 5, -15, -4, 7, -13]


def layout_case(name, dtype_name, operation, description, oracle_formula,
                confidence, notes, special_values=None):
    config = DTYPES[dtype_name]
    width, channels = 1, 9
    qwords = prepare_and_run_prefix() + make_layout_regcmds(
        OUT_PH, A_PH, B_PH,
        config["precision"], config["element_size"], width, channels, operation,
    )
    a_values, b_values = LAYOUT_A_9, LAYOUT_B_9
    expected_values = [
        oracle_value(operation, a_values[index], b_values[index], dtype_name)
        for index in range(len(a_values))
    ]
    a_payload, _ = pack_c1wc2(a_values, width, channels, config["item_size"])
    b_payload, _ = pack_c1wc2(b_values, width, channels, config["item_size"])
    expected, expected_mask = pack_c1wc2(
        expected_values, width, channels, config["item_size"]
    )
    oracle = {
        "kind": "host-python-formula + source C1WC2 packing",
        "formula": oracle_formula,
        "expected": "expected.bin",
        "mask": "expected.mask.bin",
        "compare": (
            "masked byte equality over the full 4096-byte output BO; the mask "
            "selects the nine valid logical lanes and excludes 16-byte surface padding"
        ),
        "confidence": confidence,
        "source_symbol": "integer_expected + pack_c1wc2",
    }
    return write_case(
        name=name,
        source_example=EXPT_SRC,
        source_refs=EXPT_REFS_LAYOUT,
        description=description,
        qwords=qwords,
        a_payload=a_payload,
        b_payload=b_payload,
        expected=expected,
        expected_mask=expected_mask,
        oracle=oracle,
        dtype_name=dtype_name,
        operation=operation,
        layout=(
            "C1WC2 packed 16-byte channel surfaces, width=1, channels=9 "
            f"(atom_channels={16 // config['item_size']}, "
            f"surfaces={(9 + 16 // config['item_size'] - 1) // (16 // config['item_size'])})"
        ),
        width=width,
        channels=channels,
        notes=notes,
        output_item_size=config["item_size"],
        special_values=special_values,
    )


def int16_to_int32_case():
    name = "int16_add_to_int32_c8_w1"
    a_values = SIMPLE_A_INT16
    b_values = SIMPLE_B_INT16
    qwords = int16_add_to_int32_regcmds(OUT_PH, A_PH, B_PH)
    expected_values = [int(a) + int(b) for a, b in zip(a_values, b_values)]
    a_payload, _ = contiguous_encode(a_values, 2)
    b_payload, _ = contiguous_encode(b_values, 2)
    expected, expected_mask = contiguous_encode(expected_values, 4)
    oracle = {
        "kind": "host-python-formula",
        "formula": "int32(a[i]) + int32(b[i])  (INT16 arithmetic widened to INT32 output)",
        "expected": "expected.bin",
        "mask": "expected.mask.bin",
        "compare": (
            "masked byte equality over the full 4096-byte output BO; first 32 bytes "
            "are the eight INT32 results, the rest is BO padding"
        ),
        "confidence": "source asserts exact hardware match in run_int16_add_to_int32",
        "source_symbol": "run_int16_add_to_int32",
    }
    return write_case(
        name=name,
        source_example=KERNEL_SRC,
        source_refs=KERNEL_REFS_INT16_TO_INT32,
        description=(
            "INT16 ADD on eight lanes with external INT32 writeback "
            "(16-to-32 regroup, DST_SURF_STRIDE=16, SURFACE_ADD=32)"
        ),
        qwords=qwords,
        a_payload=a_payload,
        b_payload=b_payload,
        expected=expected,
        expected_mask=expected_mask,
        oracle=oracle,
        dtype_name="INT16->INT32",
        operation="ADD",
        layout="contiguous INT16 input, two four-lane INT32 output surfaces",
        width=1,
        channels=8,
        notes=[
            "31 QWORDs; kernel_6_18 stream has no S_POINTER re-arm prefix.",
            "The expt variant (lines 872-938) adds EW_CFG bits (3 << 30); this "
            "bundle intentionally captures the kernel_6_18 stream.",
        ],
        output_item_size=4,
        special_values=["31000 exceeds INT16 range but must stay 31000 in INT32 output"],
    )


def blocked_case(name, dtype_name, operation, source_example, source_refs,
                 description, reason):
    return {
        "case": name,
        "status": "BLOCKED",
        "dtype": dtype_name,
        "operation": operation,
        "source_example": source_example,
        "source_refs": source_refs,
        "description": description,
        "oracle": "none",
        "blocked_reason": reason,
    }


def build_cases():
    cases = []

    cases.append(simple_case(
        "int8_add_c8_w1", "INT8", "ADD",
        SIMPLE_A_INT8, SIMPLE_B_INT8, 8,
        "INT8 ADD, 8 lanes, one 16-byte channel surface; lane 7 saturates 105 -> 127",
        "saturate_int8(a[i] + b[i])",
        "source DTYPES INT8 + run_operation; source asserts exact hardware match",
        ["18 QWORDs (kernel_6_18 make_regcmds, no S_POINTER re-arm)."],
        ["lane 7: 100 + 5 = 105 -> 127 (saturating overflow)"],
    ))
    cases.append(simple_case(
        "int8_max_c8_w1", "INT8", "MAX",
        SIMPLE_A_INT8, SIMPLE_B_INT8, 8,
        "INT8 MAX, 8 lanes; EW_EQUAL_EN set as in RKNN min/max captures",
        "max(a[i], b[i])",
        "source DTYPES INT8 + run_operation; source asserts exact hardware match",
        ["18 QWORDs; EW_CFG includes EW_EQUAL_EN (bit 21)."],
    ))
    cases.append(simple_case(
        "int8_min_c8_w1", "INT8", "MIN",
        SIMPLE_A_INT8, SIMPLE_B_INT8, 8,
        "INT8 MIN, 8 lanes; EW_EQUAL_EN set as in RKNN min/max captures",
        "min(a[i], b[i])",
        "source DTYPES INT8 + run_operation; source asserts exact hardware match",
        ["18 QWORDs; EW_CFG includes EW_EQUAL_EN (bit 21)."],
    ))
    cases.append(simple_case(
        "int8_mul_c8_w1", "INT8", "MUL",
        MUL_A_8, MUL_B_8, 8,
        "INT8 MUL, 8 lanes, values chosen to stay inside INT8 range",
        "saturate_int8(a[i] * b[i])",
        "source DTYPES INT8 + run_operation; source asserts exact hardware match",
        ["18 QWORDs; EW_OP_TYPE=MUL selects the separate multiplier lane."],
    ))
    cases.append(simple_case(
        "int16_add_c8_w1", "INT16", "ADD",
        SIMPLE_A_INT16, SIMPLE_B_INT16, 8,
        "INT16 ADD, 8 lanes; lane 7 saturates 31000 -> 32767",
        "saturate_int16(a[i] + b[i])",
        "source DTYPES INT16 + run_operation; source asserts exact hardware match",
        ["18 QWORDs; 16-byte input is exactly one INT16 channel surface."],
        ["lane 7: 30000 + 1000 = 31000 -> 32767 (saturating overflow)"],
    ))
    cases.append(simple_case(
        "int16_minus_c8_w1", "INT16", "MINUS",
        SIMPLE_A_INT16, SIMPLE_B_INT16, 8,
        "INT16 SUB (MINUS), 8 lanes; lane 0 saturates -31000 -> -32768",
        "saturate_int16(a[i] - b[i])",
        "source DTYPES INT16 + run_operation; source asserts exact hardware match",
        ["18 QWORDs; EW ALU algorithm 4 is MINUS in the source TRM mapping."],
        ["lane 0: -30000 - 1000 = -31000 -> -32768 (saturating overflow)"],
    ))
    cases.append(simple_case(
        "int16_mul_c8_w1", "INT16", "MUL",
        MUL_A_8, MUL_B_8, 8,
        "INT16 MUL, 8 lanes, values chosen to stay inside INT16 range",
        "saturate_int16(a[i] * b[i])",
        "source DTYPES INT16 + run_operation; source asserts exact hardware match",
        ["18 QWORDs; EW_OP_TYPE=MUL selects the separate multiplier lane."],
    ))
    cases.append(simple_case(
        "int32_add_c8_w2", "INT32", "ADD",
        SIMPLE_A_INT32, SIMPLE_B_INT32, 4,
        "INT32 ADD, eight lanes as width=2 x channels=4; INT32 converter bypassed",
        "saturate_int32(a[i] + b[i])",
        "source DTYPES INT32 + run_operation; source asserts exact hardware match",
        ["18 QWORDs; EW_CFG bit 8 (converter bypass) set for INT32."],
    ))
    cases.append(simple_case(
        "int32_max_c8_w2", "INT32", "MAX",
        SIMPLE_A_INT32, SIMPLE_B_INT32, 4,
        "INT32 MAX, eight lanes as width=2 x channels=4; signed INT32 operands",
        "max(a[i], b[i])",
        "source DTYPES INT32 + run_operation; source asserts exact hardware match",
        ["18 QWORDs; EW_CFG includes EW_EQUAL_EN (bit 21)."],
    ))
    cases.append(simple_case(
        "int32_mul_int16_operand_c8_w2", "INT32", "MUL",
        SIMPLE_A_INT32, SIMPLE_B_INT32, 4,
        "INT32 MUL, eight lanes; source-captured limitation: EW MUL operand is signed INT16",
        "saturate_int32(a[i] * s16(b[i] & 0xffff)), s16(x) = x-65536 if x>=32768 else x",
        "source-captured hardware limitation (kernel_6_18 lines 430-443); candidate behavior",
        [
            "The full INT32 main cube is used, but the separate MUL operand decodes "
            "as signed INT16: 50000 -> -15536, -50000 -> 15536.",
            "Do not treat this as full-width INT32 multiply.",
        ],
        ["b lane 0 = 50000 decodes as -15536", "b lane 1 = -50000 decodes as 15536"],
    ))

    cases.append(layout_case(
        "int8_add_c9_w1_layout", "INT8", "ADD",
        "INT8 ADD, width=1 x channels=9 across one full 16-byte surface plus tail",
        "saturate_int8(a[i] + b[i]) then C1WC2 pack",
        "source layout probe; source validates stream offline and asserts logical result",
        [
            "44 QWORDs: prepare_and_run prefix (4) + make_layout_regcmds (40); "
            "the four re-arm writes therefore appear twice.",
            "Nine valid bytes are asserted; seven surface-padding bytes are not.",
        ],
    ))
    cases.append(layout_case(
        "int16_add_c9_w1_layout", "INT16", "ADD",
        "INT16 ADD, width=1 x channels=9 across two 16-byte surfaces (8+1 lanes)",
        "saturate_int16(a[i] + b[i]) then C1WC2 pack",
        "source layout probe; source validates stream offline and asserts logical result",
        [
            "44 QWORDs; two surfaces, second surface has one valid lane.",
            "Valid bytes are 0..15 and 16..17; the rest of surface 1 is padding.",
        ],
    ))
    cases.append(layout_case(
        "int16_minus_c9_w1_layout", "INT16", "MINUS",
        "INT16 SUB (MINUS), width=1 x channels=9 across two 16-byte surfaces",
        "saturate_int16(a[i] - b[i]) then C1WC2 pack",
        "source layout probe; source validates stream offline and asserts logical result",
        [
            "44 QWORDs; exercises the tail channel (channel 8) in surface 1.",
            "Valid bytes are 0..15 and 16..17; the rest of surface 1 is padding.",
        ],
    ))
    cases.append(layout_case(
        "int32_add_c9_w1_layout", "INT32", "ADD",
        "INT32 ADD, width=1 x channels=9 across three four-lane surfaces (4+4+1)",
        "saturate_int32(a[i] + b[i]) then C1WC2 pack",
        "source layout probe; INT32 9ch stream is offline-validated only in the source",
        [
            "44 QWORDs; three surfaces, third surface has one valid lane.",
            "Valid bytes are 0..35 (three 16-byte surfaces, 4 valid bytes in the last).",
            "Device behavior for INT32 9ch is the open question this capture answers.",
        ],
        ["tail lane 8 lands in the third 16-byte surface"],
    ))

    cases.append(int16_to_int32_case())
    return cases


def blocked_cases():
    return [
        blocked_case(
            "int32_div_c8_w2", "INT32", "DIV", KERNEL_SRC,
            [
                {"path": KERNEL_SRC, "lines": "100-111", "symbol": "OPERATIONS"},
                {"path": KERNEL_SRC, "lines": "355-454", "symbol": "run_operation"},
                {"path": KERNEL_SRC, "lines": "445-450", "symbol": "not-an-integer-op check"},
            ],
            "INT32 DIV probe (source submits it) with the other non-integer ALU modes",
            "The source proves DIV/FLOOR/CEIL use floating-point semantics and are "
            "not integer operations (OPERATIONS[...]['integer_supported'] = False). "
            "There is no trustworthy integer oracle; bundling them as integer EW "
            "would mislabel the result. FLOOR and CEIL share this blocker.",
        ),
        blocked_case(
            "fp16_four_input_sum_c8_w1", "FP16", "ADD", EXPT_SRC,
            [
                {"path": EXPT_SRC, "lines": "1907-1998", "symbol": "run_fp16_four_input_pipeline"},
                {"path": EXPT_SRC, "lines": "1820-1904", "symbol": "run_fp16_bs_bn_activations"},
            ],
            "FP16 four-input sum: main + BRDMA(FP32) + NRDMA(FP32) + ERDMA(FP16)",
            "The only multi-input sum in either source is FP16, with FP32 BRDMA/NRDMA "
            "operands. This family is integer-only (ew-int); an FP16/FP32 mixed case "
            "needs its own oracle and belongs in an ew-fp16 family. It is not an "
            "INT8/INT16/INT32 case and was deliberately not materialized here.",
        ),
        blocked_case(
            "fp16_bs_bn_relu_prelu_c8_w1", "FP16", "RELUX/PRELU", EXPT_SRC,
            [
                {"path": EXPT_SRC, "lines": "1820-1904", "symbol": "run_fp16_bs_bn_activations"},
                {"path": EXPT_SRC, "lines": "1846-1885", "symbol": "activation command stream"},
            ],
            "FP16 BS/BN ReLU-X and PReLU probes",
            "ReLU-X and PReLU are emitted only in the FP16 BS/BN auxiliary stages. "
            "No integer ReLU path exists in either source, and ReLU6 and batchnorm "
            "are never emitted at all. Not an integer elementwise case.",
        ),
    ]


def source_identity():
    sources = {}
    for path in (KERNEL_SRC, EXPT_SRC):
        sources[path] = {
            "sha256": sha256_file(path),
            "bytes": Path(path).stat().st_size,
        }
    try:
        revision = subprocess.run(
            ["git", "-C", "/home/fedora/rk3588", "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except Exception as exc:  # pragma: no cover - evidence only
        revision = f"unavailable: {exc}"
    return sources, revision


def main():
    if CASES_DIR.exists():
        for old in sorted(CASES_DIR.iterdir()):
            if old.is_dir():
                for child in sorted(old.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink()
                    elif child.is_dir():
                        child.rmdir()
                old.rmdir()
    CASES_DIR.mkdir(parents=True, exist_ok=True)

    ready = build_cases()
    blocked = blocked_cases()
    sources, revision = source_identity()

    manifest = {
        "family": "ew-int",
        "description": (
            "Device-free RK3588 integer elementwise capture bundles derived from "
            "the kernel_6_18 and expt elementwise_int.py examples."
        ),
        "schema": "build/rk3588-example-captures/CAPTURE_FORMAT.md",
        "source_revision": revision,
        "source_examples": sources,
        "regcmd_encoding": (
            "little-endian uint64: (target << 48) | ((value & 0xffffffff) << 16) | offset"
        ),
        "task_descriptor_contract": {
            "note": (
                "job.json follows the documented schema and does not encode task "
                "fields. The worker must use the source examples' known-safe "
                "descriptor: flags=0, op_idx=4, enable_mask=0x18, int_mask=0x300, "
                "int_clear=0x1FFFF, int_status=0, regcfg_offset=0, "
                "regcfg_amount=regcmd_words, regcmd_addr=regcmd BO address."
            )
        },
        "oracle_policy": (
            "expected.bin is a host-side pure-Python formula, not device data. "
            "expected.mask.bin marks asserted bytes with 0xFF and unasserted "
            "surface/BO padding with 0x00. Compare (actual & mask) == (expected & mask) "
            "over the full output BO."
        ),
        "validation": {
            "local_bundle_validation": "validation/local_validation.json",
            "source_crosscheck": "validation/source_crosscheck.json",
            "note": "Host-side checks only; they do not validate RK3588 silicon.",
        },
        "counts": {"READY": len(ready), "BLOCKED": len(blocked)},
        "coverage": {
            "integer_dtypes_bundled": ["INT8", "INT16", "INT32"],
            "fp32": (
                "Neither example defines an FP32 EW dtype or submits FP32 input. "
                "The expt FP16 pipelines consume configured FP32 constants, but "
                "those are non-integer probes and are not bundled here."
            ),
            "operations_bundled": ["ADD", "MINUS(SUB)", "MUL", "MAX", "MIN"],
            "multi_input_sum": (
                "The only multi-input sum emitted by the sources is the FP16 "
                "run_fp16_four_input_pipeline; see the BLOCKED entry. No integer "
                "multi-input sum exists in either script."
            ),
            "relu_relu6_batchnorm": (
                "ReLU-X and PReLU are emitted only for FP16 BS/BN (BLOCKED entry). "
                "ReLU6 and batchnorm are not emitted by either example. No integer "
                "activation variant exists."
            ),
            "lane_shapes": [
                "8-lane simple path: INT8/INT16 width=1 x channels=8; INT32 width=2 x channels=4",
                "9-lane layout path: width=1 x channels=9 for INT8, INT16 and INT32",
            ],
            "not_bundled_streams": [
                "FP16 compare -> INT16 (expt 802-869)",
                "FP16 register-constant ALU/MUL pipelines (expt 941-1088, 1746-1817)",
                "FP16 BS/BN configured MINUS and external MUL (expt 1091-1632)",
                "FP16 regroup one-in-two (expt 1226-1327)",
                "FP16 per-channel broadcast and SiLU LUT (expt 2001-2182)",
                "INT32 ABS/NEG/FLOOR/CEIL and the INT32_MIN edge vectors",
            ],
        },
        "cases": ready + blocked,
    }

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    print(f"family: {ROOT}")
    print(f"READY: {len(ready)}  BLOCKED: {len(blocked)}")
    for entry in ready:
        print(
            f"  READY  {entry['case']}: {entry['regcmd_qwords']} QWORDs, "
            f"{entry['shape']['elements']} lanes, hash {entry['bundle_hash'][:16]}"
        )
    for entry in blocked:
        print(f"  BLOCKED {entry['case']}: {entry['blocked_reason'][:80]}...")


if __name__ == "__main__":
    main()
