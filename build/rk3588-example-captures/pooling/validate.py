#!/usr/bin/env python3
"""Validate the device-free RK3588 PPU pooling capture bundles.

Checks the manifest/job schema, file census and hashes, buffer sizes, regcmd
length and exact PPU/PPU_RDMA/PC QWORD order, both DMA patch indices, and
recomputes every READY expected buffer from in.bin with the source host oracle.
No device is opened.

Run with /usr/bin/python3 (NumPy is required):
    /usr/bin/python3 validate.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

try:
    import numpy as np
except ModuleNotFoundError as exc:  # default python3 may be a NumPy-less brew build
    raise SystemExit("NumPy is required; run with /usr/bin/python3") from exc

sys.dont_write_bytecode = True

BASE = Path(__file__).resolve().parent
SOURCE = Path("/home/fedora/rk3588/examples/expt/pooling.py")
BUFFER_BYTES = 4096
JOB_KEYS = {
    "case",
    "source_example",
    "description",
    "timeout_ns",
    "tasks",
    "buffers",
    "patches",
}

PPU = 0x4001
PPU_RDMA = 0x8001
PC = 0x0081

PPU_S_POINTER = 0x6004
PPU_DATA_CUBE_IN_WIDTH = 0x600C
PPU_DATA_CUBE_IN_HEIGHT = 0x6010
PPU_DATA_CUBE_IN_CHANNEL = 0x6014
PPU_DATA_CUBE_OUT_WIDTH = 0x6018
PPU_DATA_CUBE_OUT_HEIGHT = 0x601C
PPU_DATA_CUBE_OUT_CHANNEL = 0x6020
PPU_OPERATION_MODE_CFG = 0x6024
PPU_POOLING_KERNEL_CFG = 0x6034
PPU_RECIP_KERNEL_WIDTH = 0x6038
PPU_RECIP_KERNEL_HEIGHT = 0x603C
PPU_POOLING_PADDING_CFG = 0x6040
PPU_PADDING_VALUE_1_CFG = 0x6044
PPU_PADDING_VALUE_2_CFG = 0x6048
PPU_DST_BASE_ADDR = 0x6070
PPU_DST_SURF_STRIDE = 0x607C
PPU_DATA_FORMAT = 0x6084
PPU_MISC_CTRL = 0x60DC

PPU_RDMA_S_POINTER = 0x7004
PPU_RDMA_OPERATION_ENABLE = 0x7008
PPU_RDMA_CUBE_IN_WIDTH = 0x700C
PPU_RDMA_CUBE_IN_HEIGHT = 0x7010
PPU_RDMA_CUBE_IN_CHANNEL = 0x7014
PPU_RDMA_SRC_BASE_ADDR = 0x701C
PPU_RDMA_SRC_LINE_STRIDE = 0x7024
PPU_RDMA_SRC_SURF_STRIDE = 0x7028
PPU_RDMA_DATA_FORMAT = 0x7030
PC_OPERATION_ENABLE = 0x0008

REG_FIELDS = {
    (PPU, PPU_S_POINTER): "PPU_S_POINTER",
    (PPU, PPU_DATA_CUBE_IN_WIDTH): "PPU_DATA_CUBE_IN_WIDTH",
    (PPU, PPU_DATA_CUBE_IN_HEIGHT): "PPU_DATA_CUBE_IN_HEIGHT",
    (PPU, PPU_DATA_CUBE_IN_CHANNEL): "PPU_DATA_CUBE_IN_CHANNEL",
    (PPU, PPU_DATA_CUBE_OUT_WIDTH): "PPU_DATA_CUBE_OUT_WIDTH",
    (PPU, PPU_DATA_CUBE_OUT_HEIGHT): "PPU_DATA_CUBE_OUT_HEIGHT",
    (PPU, PPU_DATA_CUBE_OUT_CHANNEL): "PPU_DATA_CUBE_OUT_CHANNEL",
    (PPU, PPU_OPERATION_MODE_CFG): "PPU_OPERATION_MODE_CFG",
    (PPU, PPU_POOLING_KERNEL_CFG): "PPU_POOLING_KERNEL_CFG",
    (PPU, PPU_RECIP_KERNEL_WIDTH): "PPU_RECIP_KERNEL_WIDTH",
    (PPU, PPU_RECIP_KERNEL_HEIGHT): "PPU_RECIP_KERNEL_HEIGHT",
    (PPU, PPU_POOLING_PADDING_CFG): "PPU_POOLING_PADDING_CFG",
    (PPU, PPU_PADDING_VALUE_1_CFG): "PPU_PADDING_VALUE_1_CFG",
    (PPU, PPU_PADDING_VALUE_2_CFG): "PPU_PADDING_VALUE_2_CFG",
    (PPU, PPU_DST_BASE_ADDR): "PPU_DST_BASE_ADDR",
    (PPU, PPU_DST_SURF_STRIDE): "PPU_DST_SURF_STRIDE",
    (PPU, PPU_DATA_FORMAT): "PPU_DATA_FORMAT",
    (PPU, PPU_MISC_CTRL): "PPU_MISC_CTRL",
    (PPU_RDMA, PPU_RDMA_S_POINTER): "PPU_RDMA_S_POINTER",
    (PPU_RDMA, PPU_RDMA_OPERATION_ENABLE): "PPU_RDMA_OPERATION_ENABLE",
    (PPU_RDMA, PPU_RDMA_CUBE_IN_WIDTH): "PPU_RDMA_CUBE_IN_WIDTH",
    (PPU_RDMA, PPU_RDMA_CUBE_IN_HEIGHT): "PPU_RDMA_CUBE_IN_HEIGHT",
    (PPU_RDMA, PPU_RDMA_CUBE_IN_CHANNEL): "PPU_RDMA_CUBE_IN_CHANNEL",
    (PPU_RDMA, PPU_RDMA_SRC_BASE_ADDR): "PPU_RDMA_SRC_BASE_ADDR",
    (PPU_RDMA, PPU_RDMA_SRC_LINE_STRIDE): "PPU_RDMA_SRC_LINE_STRIDE",
    (PPU_RDMA, PPU_RDMA_SRC_SURF_STRIDE): "PPU_RDMA_SRC_SURF_STRIDE",
    (PPU_RDMA, PPU_RDMA_DATA_FORMAT): "PPU_RDMA_DATA_FORMAT",
    (PC, PC_OPERATION_ENABLE): "PC_OPERATION_ENABLE",
}

BASE_SEQUENCE = [
    (PPU, PPU_S_POINTER),
    (PPU_RDMA, PPU_RDMA_S_POINTER),
    (PPU, PPU_DATA_CUBE_IN_WIDTH),
    (PPU, PPU_DATA_CUBE_IN_HEIGHT),
    (PPU, PPU_DATA_CUBE_IN_CHANNEL),
    (PPU, PPU_DATA_CUBE_OUT_WIDTH),
    (PPU, PPU_DATA_CUBE_OUT_HEIGHT),
    (PPU, PPU_DATA_CUBE_OUT_CHANNEL),
    (PPU, PPU_OPERATION_MODE_CFG),
    (PPU, PPU_POOLING_KERNEL_CFG),
]
RECIP_SEQUENCE = [
    (PPU, PPU_RECIP_KERNEL_WIDTH),
    (PPU, PPU_RECIP_KERNEL_HEIGHT),
]
TAIL_SEQUENCE = [
    (PPU, PPU_POOLING_PADDING_CFG),
    (PPU, PPU_PADDING_VALUE_1_CFG),
    (PPU, PPU_PADDING_VALUE_2_CFG),
    (PPU, PPU_DST_BASE_ADDR),
    (PPU, PPU_DST_SURF_STRIDE),
    (PPU, PPU_DATA_FORMAT),
    (PPU, PPU_MISC_CTRL),
    (PPU_RDMA, PPU_RDMA_CUBE_IN_WIDTH),
    (PPU_RDMA, PPU_RDMA_CUBE_IN_HEIGHT),
    (PPU_RDMA, PPU_RDMA_CUBE_IN_CHANNEL),
    (PPU_RDMA, PPU_RDMA_SRC_BASE_ADDR),
    (PPU_RDMA, PPU_RDMA_SRC_LINE_STRIDE),
    (PPU_RDMA, PPU_RDMA_SRC_SURF_STRIDE),
    (PPU_RDMA, PPU_RDMA_DATA_FORMAT),
    (PPU_RDMA, PPU_RDMA_OPERATION_ENABLE),
    (PC, PC_OPERATION_ENABLE),
]

METHOD_SELECTORS = {"average": 0, "maximum": 1, "minimum": 2}
PRECISION_SELECTORS = {"INT8": 0, "INT16": 1, "FP16": 2, "INT32": 4, "FP32": 5}


def fail(message):
    raise SystemExit(f"VALIDATE_FAIL: {message}")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read JSON {path}: {exc!r}")


def load_source():
    if not SOURCE.is_file():
        fail(f"source example is missing: {SOURCE}")
    spec = importlib.util.spec_from_file_location("rk3588_pool_validate_source", SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def check_file_meta(path, meta, label):
    if not path.is_file():
        fail(f"{label}: missing file {path}")
    data = path.read_bytes()
    if meta.get("bytes") != len(data):
        fail(f"{label}: size mismatch for {path.name}")
    if meta.get("sha256") != sha256(data):
        fail(f"{label}: sha256 mismatch for {path.name}")
    return data


def validate_top(manifest):
    required = {
        "schema",
        "family",
        "prepared_date",
        "device_access",
        "source_examples",
        "generator",
        "summary",
        "worker_requirements",
        "coverage",
        "ready_cases",
        "blocked_cases",
        "cases",
        "not_bundled",
        "artifacts",
    }
    missing = required - set(manifest)
    if missing:
        fail(f"manifest missing keys: {sorted(missing)}")
    if manifest["schema"] != "rk3588-example-capture-manifest-v1":
        fail("unexpected manifest schema")
    if manifest["family"] != "pooling":
        fail("unexpected manifest family")
    if "none" not in manifest["device_access"]:
        fail("manifest does not declare device-free preparation")
    if manifest["generator"].get("path") != "prepare.py":
        fail("generator path is not prepare.py")

    source_examples = manifest["source_examples"]
    if len(source_examples) != 2:
        fail("expected two source example entries")
    for entry in source_examples:
        path = Path(entry["path"])
        if not path.is_file():
            fail(f"source example is missing: {path}")
        data = path.read_bytes()
        if entry["bytes"] != len(data) or entry["sha256"] != sha256(data):
            fail(f"source example hash mismatch: {path}")

    artifacts = manifest["artifacts"]
    for filename in ("README.md", "prepare.py", "validate.py"):
        if filename not in artifacts:
            fail(f"artifacts missing {filename}")
        check_file_meta(BASE / filename, artifacts[filename], "artifact")

    cases = manifest["cases"]
    names = [entry["case"] for entry in cases]
    if len(names) != len(set(names)):
        fail("duplicate case names in manifest")
    actual_dirs = {path.name for path in (BASE / "cases").iterdir() if path.is_dir()}
    if set(names) != actual_dirs:
        fail("manifest cases and case directories differ")

    statuses = [entry["status"] for entry in cases]
    if any(status not in ("READY", "BLOCKED") for status in statuses):
        fail("invalid case status")
    summary = manifest["summary"]
    if summary != {
        "ready": statuses.count("READY"),
        "blocked": statuses.count("BLOCKED"),
        "total": len(statuses),
    }:
        fail("summary counts do not match cases")

    coverage = manifest["coverage"]
    ready_names = {entry["case"] for entry in cases if entry["status"] == "READY"}
    blocked_names = {entry["case"] for entry in cases if entry["status"] == "BLOCKED"}
    if set(manifest["ready_cases"]) != ready_names:
        fail("manifest ready_cases does not match READY cases")
    if set(manifest["blocked_cases"]) != blocked_names:
        fail("manifest blocked_cases does not match BLOCKED cases")
    for group in ("by_precision", "by_method", "by_kernel", "by_stride"):
        seen = []
        for values in coverage[group].values():
            seen.extend(values)
        if set(seen) != ready_names or len(seen) != len(ready_names):
            fail(f"coverage.{group} does not exactly partition READY cases")
    if set(coverage["padded"]).intersection(coverage["valid"]):
        fail("coverage padded/valid overlap")
    if set(coverage["padded"]) | set(coverage["valid"]) != ready_names:
        fail("coverage padded/valid does not cover READY cases")
    if set(coverage["index_en"]) != {
        entry["case"] for entry in cases if entry["status"] == "READY" and entry["ppu"]["index_en"]
    }:
        fail("coverage.index_en mismatch")
    if set(coverage["blocked_zero_write"]) != blocked_names:
        fail("coverage.blocked_zero_write mismatch")

    return cases


def require_keys(mapping, keys, label):
    missing = set(keys) - set(mapping)
    if missing:
        fail(f"{label}: missing keys {sorted(missing)}")


def validate_case(entry, source):
    name = entry["case"]
    label = f"case {name}"
    case_dir = BASE / "cases" / name
    status = entry["status"]
    if status not in ("READY", "BLOCKED"):
        fail(f"{label}: invalid status")

    require_keys(
        entry,
        {
            "case",
            "status",
            "source_example",
            "source_case",
            "source_lines",
            "description",
            "probe_only",
            "derived",
            "ppu",
            "shapes",
            "layout",
            "oracle",
            "files",
        },
        label,
    )
    if entry["source_example"] != str(SOURCE):
        fail(f"{label}: unexpected source_example")
    if not isinstance(entry["source_lines"], list) or len(entry["source_lines"]) != 2:
        fail(f"{label}: source_lines must be a two-element list")
    if not all(isinstance(value, int) and value > 0 for value in entry["source_lines"]):
        fail(f"{label}: invalid source_lines")
    if not isinstance(entry["description"], str) or not entry["description"]:
        fail(f"{label}: empty description")
    if not isinstance(entry["probe_only"], bool) or not isinstance(entry["derived"], bool):
        fail(f"{label}: probe_only/derived must be booleans")

    ppu = entry["ppu"]
    require_keys(
        ppu,
        {
            "method",
            "method_selector",
            "precision_name",
            "output_precision",
            "rdma_width",
            "dtype",
            "channels",
            "in_shape",
            "out_shape",
            "kernel",
            "stride",
            "padding",
            "padding_value",
            "index_en",
            "use_cnt",
            "recip_override",
            "notch_addr",
        },
        f"{label} ppu",
    )
    if ppu["method"] not in METHOD_SELECTORS:
        fail(f"{label}: invalid method")
    if ppu["method_selector"] != METHOD_SELECTORS[ppu["method"]]:
        fail(f"{label}: method selector mismatch")
    if ppu["precision_name"] not in PRECISION_SELECTORS:
        fail(f"{label}: invalid precision name")
    if ppu["output_precision"] != PRECISION_SELECTORS[ppu["precision_name"]]:
        fail(f"{label}: precision selector mismatch")
    if ppu["dtype"] not in ("int8", "int16", "float16", "int32", "float32"):
        fail(f"{label}: invalid dtype")
    if ppu["notch_addr"] != 0:
        fail(f"{label}: notch_addr must be zero for this family")
    if ppu["use_cnt"] not in range(8):
        fail(f"{label}: invalid use_cnt")
    if not isinstance(ppu["index_en"], bool):
        fail(f"{label}: index_en must be boolean")
    if len(ppu["in_shape"]) != 2 or len(ppu["out_shape"]) != 2:
        fail(f"{label}: invalid shapes")
    if len(ppu["kernel"]) != 2 or len(ppu["stride"]) != 2:
        fail(f"{label}: invalid kernel/stride")
    if len(ppu["padding"]) != 4 or len(ppu["padding_value"]) != 2:
        fail(f"{label}: invalid padding/padding_value")

    dtype = np.dtype(ppu["dtype"])
    channels = int(ppu["channels"])
    in_h, in_w = map(int, ppu["in_shape"])
    out_h, out_w = map(int, ppu["out_shape"])
    kernel = tuple(map(int, ppu["kernel"]))
    stride = tuple(map(int, ppu["stride"]))
    padding = tuple(map(int, ppu["padding"]))
    padding_value = tuple(map(int, ppu["padding_value"]))
    index_en = bool(ppu["index_en"])
    if channels <= 0 or min(in_h, in_w, out_h, out_w) <= 0:
        fail(f"{label}: non-positive shape")
    if min(kernel) <= 0 or min(stride) <= 0:
        fail(f"{label}: non-positive kernel/stride")
    if any(value < 0 for value in padding):
        fail(f"{label}: negative padding")

    item_bytes = dtype.itemsize
    atom_channels = 16 // item_bytes
    if atom_channels <= 0:
        fail(f"{label}: invalid atom width")
    surfaces = (channels + atom_channels - 1) // atom_channels
    out_area = out_h * out_w
    in_logical_bytes = surfaces * in_h * in_w * 16
    value_bytes = surfaces * out_area * 16
    index_surfaces = (channels + 7) // 8 if index_en else 0
    index_offset = out_area * 2 * 16 if index_en else None
    index_bytes = index_surfaces * out_area * 16 if index_en else 0
    out_logical_bytes = (
        max(value_bytes, index_offset) + index_bytes if index_en else value_bytes
    )
    if in_logical_bytes > BUFFER_BYTES or out_logical_bytes > BUFFER_BYTES:
        fail(f"{label}: logical data exceeds {BUFFER_BYTES} bytes")

    shapes = entry["shapes"]
    require_keys(
        shapes,
        {
            "in_h",
            "in_w",
            "channels",
            "out_h",
            "out_w",
            "atom_bytes",
            "atom_channels",
            "surfaces",
            "out_area",
            "in_logical_bytes",
            "value_bytes",
            "index_offset",
            "index_bytes",
            "out_logical_bytes",
            "buffer_bytes",
        },
        f"{label} shapes",
    )
    expected_shapes = {
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
    }
    if shapes != expected_shapes:
        fail(f"{label}: shapes do not match PPU parameters")

    layout = entry["layout"]
    require_keys(layout, {"input", "output"}, f"{label} layout")
    input_layout = layout["input"]
    output_layout = layout["output"]
    require_keys(
        input_layout,
        {
            "packing",
            "dtype",
            "atom_bytes",
            "atom_channels",
            "surfaces",
            "line_stride_bytes",
            "surface_stride_bytes",
            "logical_bytes",
            "buffer_bytes",
            "tail_value",
        },
        f"{label} input layout",
    )
    require_keys(
        output_layout,
        {
            "packing",
            "value_bytes",
            "index_en",
            "index_offset",
            "index_surfaces",
            "index_bytes",
            "logical_bytes",
            "buffer_bytes",
        },
        f"{label} output layout",
    )
    if input_layout["dtype"] != ppu["dtype"]:
        fail(f"{label}: input layout dtype mismatch")
    if input_layout["atom_bytes"] != 16 or input_layout["atom_channels"] != atom_channels:
        fail(f"{label}: input atom mismatch")
    if input_layout["surfaces"] != surfaces:
        fail(f"{label}: input surface count mismatch")
    if input_layout["line_stride_bytes"] != in_w * 16:
        fail(f"{label}: input line stride mismatch")
    if input_layout["surface_stride_bytes"] != in_h * in_w * 16:
        fail(f"{label}: input surface stride mismatch")
    if input_layout["logical_bytes"] != in_logical_bytes:
        fail(f"{label}: input logical bytes mismatch")
    if input_layout["buffer_bytes"] != BUFFER_BYTES:
        fail(f"{label}: input buffer bytes mismatch")
    if output_layout["value_bytes"] != value_bytes:
        fail(f"{label}: output value bytes mismatch")
    if output_layout["index_en"] != index_en:
        fail(f"{label}: output index_en mismatch")
    if output_layout["index_offset"] != index_offset:
        fail(f"{label}: output index offset mismatch")
    if output_layout["index_surfaces"] != index_surfaces:
        fail(f"{label}: output index surfaces mismatch")
    if output_layout["index_bytes"] != index_bytes:
        fail(f"{label}: output index bytes mismatch")
    if output_layout["logical_bytes"] != out_logical_bytes:
        fail(f"{label}: output logical bytes mismatch")
    if output_layout["buffer_bytes"] != BUFFER_BYTES:
        fail(f"{label}: output buffer bytes mismatch")

    job = load_json(case_dir / "job.json")
    if set(job) != JOB_KEYS:
        fail(f"{label}: job.json keys differ from schema: {sorted(set(job) ^ JOB_KEYS)}")
    if job["case"] != name:
        fail(f"{label}: job.json case mismatch")
    if job["source_example"] != str(SOURCE):
        fail(f"{label}: job.json source_example mismatch")
    if job["description"] != entry["description"]:
        fail(f"{label}: job.json description mismatch")
    if not isinstance(job["timeout_ns"], int) or job["timeout_ns"] <= 0:
        fail(f"{label}: invalid timeout_ns")
    if len(job["tasks"]) != 1:
        fail(f"{label}: expected exactly one task")
    task = job["tasks"][0]
    if set(task) != {"regcmd_offset_words", "regcmd_words"}:
        fail(f"{label}: task keys differ from schema")
    if task["regcmd_offset_words"] != 0:
        fail(f"{label}: task offset must be zero")
    if not isinstance(task["regcmd_words"], int) or task["regcmd_words"] <= 0:
        fail(f"{label}: invalid regcmd_words")

    buffers = job["buffers"]
    if len(buffers) != 2:
        fail(f"{label}: expected exactly two buffers")
    buffer_by_name = {}
    for buffer in buffers:
        required_buffer_keys = {"name", "size", "direction"}
        if not required_buffer_keys.issubset(buffer):
            fail(f"{label}: buffer missing name/size/direction")
        if buffer["name"] in buffer_by_name:
            fail(f"{label}: duplicate buffer name")
        buffer_by_name[buffer["name"]] = buffer
    if set(buffer_by_name) != {"in", "out"}:
        fail(f"{label}: buffers must be named in/out")
    in_buffer = buffer_by_name["in"]
    out_buffer = buffer_by_name["out"]
    if in_buffer["size"] != BUFFER_BYTES or out_buffer["size"] != BUFFER_BYTES:
        fail(f"{label}: buffer size must be {BUFFER_BYTES}")
    if in_buffer["direction"] != "in" or "input" not in in_buffer:
        fail(f"{label}: input buffer must be direction=in with input")
    if out_buffer["direction"] != "inout":
        fail(f"{label}: output buffer must be direction=inout")
    if out_buffer.get("input") != "out_init.bin" or out_buffer.get("output") != "out.bin":
        fail(f"{label}: output buffer filenames mismatch")

    expected_files = {"job.json", "regcmd.bin", "regcmd.txt", "in.bin", "out_init.bin"}
    if status == "READY":
        expected_files.add("expected.bin")
    actual_files = {path.name for path in case_dir.iterdir() if path.is_file()}
    if actual_files != expected_files:
        fail(f"{label}: file census mismatch: {sorted(actual_files ^ expected_files)}")
    if set(entry["files"]) != expected_files:
        fail(f"{label}: manifest file list mismatch")
    file_data = {}
    for filename in expected_files:
        file_data[filename] = check_file_meta(
            case_dir / filename, entry["files"][filename], label
        )

    in_bytes = file_data["in.bin"]
    out_init = file_data["out_init.bin"]
    if len(in_bytes) != BUFFER_BYTES or len(out_init) != BUFFER_BYTES:
        fail(f"{label}: buffer payload length mismatch")
    if any(in_bytes[in_logical_bytes:]):
        fail(f"{label}: in.bin has nonzero bytes beyond the logical input")
    if any(out_init):
        fail(f"{label}: out_init.bin is not zero")

    regcmd = file_data["regcmd.bin"]
    words = task["regcmd_words"]
    if len(regcmd) != 8 * words:
        fail(f"{label}: regcmd.bin size does not match regcmd_words")
    commands = list(struct.unpack(f"<{words}Q", regcmd))
    actual_sequence = [((command >> 48) & 0xFFFF, command & 0xFFFF) for command in commands]
    sequence = list(BASE_SEQUENCE)
    if ppu["method"] == "average":
        sequence += RECIP_SEQUENCE
    sequence += TAIL_SEQUENCE
    if actual_sequence != sequence:
        fail(f"{label}: PPU/PPU_RDMA/PC QWORD order mismatch")
    if any(key not in REG_FIELDS for key in actual_sequence):
        fail(f"{label}: unknown register offset in regcmd.bin")
    values = {
        ((command >> 48) & 0xFFFF, command & 0xFFFF): (command >> 16) & 0xFFFFFFFF
        for command in commands
    }

    def expect(key, value, field):
        if values.get(key) != value:
            fail(
                f"{label}: {field} expected 0x{value:08x}, "
                f"got {values.get(key)!r}"
            )

    expect((PPU, PPU_S_POINTER), (1 << 3) | (1 << 2) | (1 << 1), "PPU_S_POINTER")
    expect(
        (PPU_RDMA, PPU_RDMA_S_POINTER),
        (1 << 3) | (1 << 2) | (1 << 1),
        "PPU_RDMA_S_POINTER",
    )
    expect((PPU, PPU_DATA_CUBE_IN_WIDTH), in_w - 1, "PPU_DATA_CUBE_IN_WIDTH")
    expect((PPU, PPU_DATA_CUBE_IN_HEIGHT), in_h - 1, "PPU_DATA_CUBE_IN_HEIGHT")
    expect((PPU, PPU_DATA_CUBE_IN_CHANNEL), channels - 1, "PPU_DATA_CUBE_IN_CHANNEL")
    expect((PPU, PPU_DATA_CUBE_OUT_WIDTH), out_w - 1, "PPU_DATA_CUBE_OUT_WIDTH")
    expect((PPU, PPU_DATA_CUBE_OUT_HEIGHT), out_h - 1, "PPU_DATA_CUBE_OUT_HEIGHT")
    expect((PPU, PPU_DATA_CUBE_OUT_CHANNEL), channels - 1, "PPU_DATA_CUBE_OUT_CHANNEL")
    operation_mode = (
        (int(index_en) << 30)
        | (int(ppu["use_cnt"]) << 5)
        | (1 << 4)
        | int(ppu["method_selector"])
    )
    expect((PPU, PPU_OPERATION_MODE_CFG), operation_mode, "PPU_OPERATION_MODE_CFG")
    kernel_cfg = (
        ((stride[0] - 1) << 20)
        | ((stride[1] - 1) << 16)
        | ((kernel[0] - 1) << 8)
        | (kernel[1] - 1)
    )
    expect((PPU, PPU_POOLING_KERNEL_CFG), kernel_cfg, "PPU_POOLING_KERNEL_CFG")
    if ppu["method"] == "average":
        recip_override = ppu["recip_override"]
        if recip_override is not None:
            recip_w, recip_h = map(int, recip_override)
        else:
            recip_w = source.fp17(1.0 / kernel[1])
            recip_h = source.fp17(1.0 / kernel[0])
        expect((PPU, PPU_RECIP_KERNEL_WIDTH), recip_w, "PPU_RECIP_KERNEL_WIDTH")
        expect((PPU, PPU_RECIP_KERNEL_HEIGHT), recip_h, "PPU_RECIP_KERNEL_HEIGHT")
    padding_cfg = (
        (padding[2] << 12)
        | (padding[1] << 8)
        | (padding[0] << 4)
        | padding[3]
    )
    expect((PPU, PPU_POOLING_PADDING_CFG), padding_cfg, "PPU_POOLING_PADDING_CFG")
    expect((PPU, PPU_PADDING_VALUE_1_CFG), padding_value[0], "PPU_PADDING_VALUE_1_CFG")
    expect((PPU, PPU_PADDING_VALUE_2_CFG), padding_value[1], "PPU_PADDING_VALUE_2_CFG")
    expect((PPU, PPU_DST_SURF_STRIDE), out_area << 4, "PPU_DST_SURF_STRIDE")
    index_add = out_area * 2 if index_en else out_area
    expect(
        (PPU, PPU_DATA_FORMAT),
        (index_add << 4) | int(ppu["output_precision"]),
        "PPU_DATA_FORMAT",
    )
    expect((PPU, PPU_MISC_CTRL), 3, "PPU_MISC_CTRL")
    expect((PPU_RDMA, PPU_RDMA_CUBE_IN_WIDTH), in_w - 1, "PPU_RDMA_CUBE_IN_WIDTH")
    expect((PPU_RDMA, PPU_RDMA_CUBE_IN_HEIGHT), in_h - 1, "PPU_RDMA_CUBE_IN_HEIGHT")
    expect((PPU_RDMA, PPU_RDMA_CUBE_IN_CHANNEL), channels - 1, "PPU_RDMA_CUBE_IN_CHANNEL")
    expect((PPU_RDMA, PPU_RDMA_SRC_LINE_STRIDE), in_w << 4, "PPU_RDMA_SRC_LINE_STRIDE")
    expect(
        (PPU_RDMA, PPU_RDMA_SRC_SURF_STRIDE),
        in_h * in_w << 4,
        "PPU_RDMA_SRC_SURF_STRIDE",
    )
    expect((PPU_RDMA, PPU_RDMA_DATA_FORMAT), int(ppu["rdma_width"]), "PPU_RDMA_DATA_FORMAT")
    expect((PPU_RDMA, PPU_RDMA_OPERATION_ENABLE), 1, "PPU_RDMA_OPERATION_ENABLE")
    expect((PC, PC_OPERATION_ENABLE), 0x60, "PC_OPERATION_ENABLE")

    address_keys = {
        (PPU, PPU_DST_BASE_ADDR): "out",
        (PPU_RDMA, PPU_RDMA_SRC_BASE_ADDR): "in",
    }
    address_indices = [
        index
        for index, key in enumerate(actual_sequence)
        if key in address_keys
    ]
    if len(address_indices) != 2:
        fail(f"{label}: expected two address QWORDs")
    for index in address_indices:
        if values[actual_sequence[index]] != 0:
            fail(f"{label}: address QWORD {index} is not a zero placeholder")
    patches = job["patches"]
    if len(patches) != 2:
        fail(f"{label}: expected exactly two patches")
    patch_by_index = {}
    for patch in patches:
        if set(patch) != {"regcmd_index", "buffer", "kind"}:
            fail(f"{label}: patch keys differ from schema")
        index = patch["regcmd_index"]
        if not isinstance(index, int) or index < 0 or index >= words:
            fail(f"{label}: patch index out of range")
        if index in patch_by_index:
            fail(f"{label}: duplicate patch index")
        if patch["buffer"] not in buffer_by_name:
            fail(f"{label}: patch buffer does not exist")
        if patch["kind"] != "value32":
            fail(f"{label}: patch kind must be value32")
        patch_by_index[index] = patch
    if set(patch_by_index) != set(address_indices):
        fail(f"{label}: patches do not exactly cover the two address QWORDs")
    for index in address_indices:
        expected_buffer = address_keys[actual_sequence[index]]
        if patch_by_index[index]["buffer"] != expected_buffer:
            fail(f"{label}: patch {index} has wrong buffer")

    regcmd_text = file_data["regcmd.txt"].decode("ascii")
    if f"# regcmd_qwords: {words}" not in regcmd_text:
        fail(f"{label}: regcmd.txt word count header mismatch")
    if regcmd_text.count("\n") < words + 1:
        fail(f"{label}: regcmd.txt does not list every QWORD")

    oracle = entry["oracle"]
    if status == "READY":
        require_keys(
            oracle,
            {
                "kind",
                "source_example",
                "source_lines",
                "expected_file",
                "buffer_bytes",
                "logical_output_bytes",
                "tolerance",
                "compare",
                "note",
            },
            f"{label} oracle",
        )
        if oracle["expected_file"] != "expected.bin":
            fail(f"{label}: READY oracle expected_file mismatch")
        if oracle["buffer_bytes"] != BUFFER_BYTES:
            fail(f"{label}: READY oracle buffer_bytes mismatch")
        if oracle["logical_output_bytes"] != out_logical_bytes:
            fail(f"{label}: READY oracle logical bytes mismatch")
        if not isinstance(oracle["tolerance"], (int, float)) or oracle["tolerance"] < 0:
            fail(f"{label}: invalid oracle tolerance")
        expected_bytes = file_data["expected.bin"]
        if len(expected_bytes) != BUFFER_BYTES:
            fail(f"{label}: expected.bin length mismatch")
        if any(expected_bytes[out_logical_bytes:]):
            fail(f"{label}: expected.bin has nonzero bytes beyond the logical output")
        if not any(expected_bytes[:out_logical_bytes]):
            fail(f"{label}: expected.bin is all zero in the logical region")
        if index_en:
            if any(expected_bytes[value_bytes:index_offset]):
                fail(f"{label}: expected index gap is not zero")
        else:
            if index_offset is not None:
                fail(f"{label}: non-index case has index offset")

        full_in = np.frombuffer(
            in_bytes,
            dtype=dtype,
            count=surfaces * in_h * in_w * atom_channels,
        ).reshape(surfaces, in_h, in_w, atom_channels)
        source_array = np.empty((in_h, in_w, channels), dtype=dtype)
        for channel in range(channels):
            source_array[:, :, channel] = full_in[
                channel // atom_channels, :, :, channel % atom_channels
            ]

        padding_scalar = np.float16(-np.inf) if padding_value[0] == 0xFC00 else 0
        if padding_value[0] == 0xFC00 and dtype != np.dtype("float16"):
            fail(f"{label}: non-FP16 case uses the 0xFC00 padding value")

        full_out = np.frombuffer(
            expected_bytes,
            dtype=dtype,
            count=surfaces * out_h * out_w * atom_channels,
        ).reshape(surfaces, out_h, out_w, atom_channels)
        got_values = np.empty((out_h, out_w, channels), dtype=dtype)
        for channel in range(channels):
            got_values[:, :, channel] = full_out[
                channel // atom_channels, :, :, channel % atom_channels
            ]

        if index_en:
            reference_values, reference_positions = source.maximum_with_index_reference(
                source_array, kernel, stride, padding, padding_scalar
            )
            if not np.array_equal(got_values, reference_values):
                fail(f"{label}: INDEX_EN value oracle mismatch")
            if channels % atom_channels:
                tail = full_out[-1, :, :, channels % atom_channels :]
                if not np.all(tail == input_layout["tail_value"]):
                    fail(f"{label}: output atom tail mismatch")
            index_full = np.frombuffer(
                expected_bytes,
                dtype=np.uint16,
                count=index_surfaces * out_h * out_w * 8,
                offset=index_offset,
            ).reshape(index_surfaces, out_h, out_w, 8)
            got_positions = np.empty((out_h, out_w, channels), dtype=np.uint16)
            for channel in range(channels):
                got_positions[:, :, channel] = index_full[
                    channel // 8, :, :, channel % 8
                ]
            if not np.array_equal(got_positions, reference_positions):
                fail(f"{label}: INDEX_EN position oracle mismatch")
        else:
            reference = source.pool_reference(
                source_array, kernel, stride, ppu["method_selector"], padding, padding_scalar
            )
            tolerance = float(oracle["tolerance"])
            if tolerance > 0:
                if not np.allclose(
                    got_values.astype(np.float32),
                    reference.astype(np.float32),
                    atol=tolerance,
                    rtol=0,
                ):
                    fail(f"{label}: value oracle mismatch beyond atol")
            elif not np.array_equal(got_values, reference):
                fail(f"{label}: value oracle mismatch")
            if channels % atom_channels:
                tail = full_out[-1, :, :, channels % atom_channels :]
                if not np.all(tail == input_layout["tail_value"]):
                    fail(f"{label}: output atom tail mismatch")
    else:
        if "blocked_reason" not in entry or not entry["blocked_reason"]:
            fail(f"{label}: BLOCKED case needs blocked_reason")
        if (
            "source_reported_behavior" not in entry
            or not entry["source_reported_behavior"]
        ):
            fail(f"{label}: BLOCKED case needs source_reported_behavior")
        if oracle.get("kind") != "none":
            fail(f"{label}: BLOCKED oracle must be none")
        if "expected.bin" in actual_files:
            fail(f"{label}: BLOCKED case must not have expected.bin")
        source_expected = entry.get("source_expected_nonzero")
        if not isinstance(source_expected, list) or not source_expected:
            fail(f"{label}: BLOCKED case needs source_expected_nonzero")
        source_expected_array = np.asarray(source_expected, dtype=dtype)
        if not np.any(source_expected_array):
            fail(f"{label}: source_expected_nonzero is all zero")
        full_in = np.frombuffer(
            in_bytes,
            dtype=dtype,
            count=surfaces * in_h * in_w * atom_channels,
        ).reshape(surfaces, in_h, in_w, atom_channels)
        source_array = np.empty((in_h, in_w, channels), dtype=dtype)
        for channel in range(channels):
            source_array[:, :, channel] = full_in[
                channel // atom_channels, :, :, channel % atom_channels
            ]
        reference = source.pool_reference(
            source_array, kernel, stride, ppu["method_selector"], padding, 0
        )
        if not np.array_equal(
            source_expected_array.reshape(out_h, out_w, channels), reference
        ):
            fail(f"{label}: source_expected_nonzero does not match the source oracle")


def main():
    manifest = load_json(BASE / "manifest.json")
    cases = validate_top(manifest)
    source = load_source()
    for entry in cases:
        validate_case(entry, source)
    print(
        "VALIDATE_PASS: "
        f"{manifest['summary']['ready']} READY, "
        f"{manifest['summary']['blocked']} BLOCKED, "
        f"{manifest['summary']['total']} total; schema, hashes, regcmd decode, "
        "patch indices and READY oracles checked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
