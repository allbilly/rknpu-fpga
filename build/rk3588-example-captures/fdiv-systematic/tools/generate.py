#!/usr/bin/env python3
"""Generate the device-free FDIV operand-class capture bundles.

This is host-side preparation only.  It never opens /dev/accel*, never runs
ssh/scp, and never submits to the RK3588 or FPGA.

The family is a 16x16 Cartesian product of raw FP16 operand classes:
A is the outer (row) class, B is the inner (column) class, row-major.
256 pairs are packed as 8 cases of 32 lanes (two complete A rows per case).
Every case is one FDIV task with width=3 (32 physical lanes).

The 22-QWORD register stream is the terminal single-task donor layout.  The
17 non-padding commands are the requested FDIV facts; five zero-valued donor
fields (DPU height/notch and the three PC-tail words) are retained as padding
so the stream matches the same 22-QWORD layout used by the other capture
families.  Address fields at QWORDs 14/15/16 are zero placeholders for the
CAPTURE_FORMAT.md value32 patches.

Outputs are written only under this family directory.
"""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
CASES_DIR = ROOT / "cases"
MANIFEST_PATH = ROOT / "manifest.json"
FORMAT_DOC = ROOT.parent / "CAPTURE_FORMAT.md"
SOURCE_EXAMPLE = "/home/fedora/rk3588/examples/elementwise.py"
SOURCE_LINES = [
    "/home/fedora/rk3588/examples/elementwise.py:301-352 (FDIV task register body)",
    "/home/fedora/rk3588/examples/elementwise.py:206-222 (terminal PC tail and PC enable)",
    "/home/fedora/rk3588/examples/elementwise.py:254-260 (FDIV output scale / fp16 output)",
    "/home/fedora/rk3588/examples/elementwise.py:295-299 (width and DMA address derivation)",
    "/home/fedora/rk3588/examples/elementwise.py:320-331 (EW_CFG 0x108303c0 for FDIV)",
    "/home/fedora/rk3588/examples/elementwise.py:345-351 (RDMA mode 0x00017841 for FDIV)",
]

TARGET_DPU = 0x1001
TARGET_RDMA = 0x2001
TARGET_PC_REG = 0x0101
TARGET_VERSION = 0x0041
TARGET_PC = 0x0081

WIDTH = 3                    # 32 physical lanes
LANES_PER_CASE = 32
PAIR_COUNT = 16 * 16
CASE_COUNT = 8
REGS_PER_TASK = 22
BUFFER_BYTES = 64

# Exact class order requested for the characterization truth table.
CLASSES = [
    ("zero_p", 0x0000, "+0"),
    ("zero_n", 0x8000, "-0"),
    ("inf_p", 0x7C00, "+inf"),
    ("inf_n", 0xFC00, "-inf"),
    ("qnan", 0x7E00, "quiet NaN, payload 0x200"),
    ("snan", 0x7C01, "signaling NaN, payload 0x001"),
    ("sub_min", 0x0001, "minimum positive subnormal"),
    ("sub_max", 0x03FF, "maximum positive subnormal"),
    ("norm_min", 0x0400, "minimum positive normal"),
    ("fin_max", 0x7BFF, "maximum positive finite"),
    ("one_p", 0x3C00, "+1.0"),
    ("one_n", 0xBC00, "-1.0"),
    ("half_p", 0x3800, "+0.5"),
    ("half_n", 0xB800, "-0.5"),
    ("two_p", 0x4000, "+2.0"),
    ("two_n", 0xC000, "-2.0"),
]

# (index, target, offset, value, field, role)
# role "command" = one of the 17 requested donor commands.
# role "padding" = zero-valued donor field kept to reach 22 QWORDs.
TEMPLATE = [
    (0, TARGET_DPU, 0x4004, 0x0000000E, "dpu_s_pointer", "command"),
    (1, TARGET_DPU, 0x400C, 0x000001E5, "dpu_feature_mode_cfg", "command"),
    (2, TARGET_DPU, 0x4010, 0x48000002, "dpu_data_format", "command"),
    (3, TARGET_DPU, 0x4030, WIDTH, "dpu_data_cube_width", "command"),
    (4, TARGET_DPU, 0x4034, 0, "dpu_data_cube_height", "padding"),
    (5, TARGET_DPU, 0x4038, 0, "dpu_data_cube_notch", "padding"),
    (6, TARGET_DPU, 0x403C, 0x00070007, "dpu_data_cube_channel", "command"),
    (7, TARGET_DPU, 0x4070, 0x108303C0, "dpu_ew_cfg", "command"),
    (8, TARGET_DPU, 0x4084, 0x00000001, "dpu_out_cvt_scale", "command"),
    (9, TARGET_RDMA, 0x5004, 0x0000000E, "rdma_s_pointer", "command"),
    (10, TARGET_RDMA, 0x500C, WIDTH, "rdma_data_cube_width", "command"),
    (11, TARGET_RDMA, 0x5010, 0, "rdma_data_cube_height", "command"),
    (12, TARGET_RDMA, 0x5014, 7, "rdma_data_cube_channel", "command"),
    (13, TARGET_RDMA, 0x5034, 0x40000008, "rdma_erdma_cfg", "command"),
    (14, TARGET_DPU, 0x4020, 0, "dst_base_addr", "command"),
    (15, TARGET_RDMA, 0x5018, 0, "src_a_base_addr", "command"),
    (16, TARGET_RDMA, 0x5038, 0, "src_b_base_addr", "command"),
    (17, TARGET_RDMA, 0x5044, 0x00017841, "rdma_feature_mode_cfg", "command"),
    (18, TARGET_PC_REG, 0x0010, 0, "pc_base_address", "padding"),
    (19, TARGET_PC_REG, 0x0014, 0, "pc_register_amounts", "padding"),
    (20, TARGET_VERSION, 0x0000, 0, "version_marker", "padding"),
    (21, TARGET_PC, 0x0008, 0x00000018, "pc_operation_enable", "command"),
]
PLACEHOLDER_INDICES = (14, 15, 16)

PATCHES = [
    {
        "regcmd_index": 14,
        "buffer": "out",
        "kind": "value32",
        "target": "0x1001",
        "offset": "0x4020",
        "field": "dst_base_addr",
    },
    {
        "regcmd_index": 15,
        "buffer": "a",
        "kind": "value32",
        "target": "0x2001",
        "offset": "0x5018",
        "field": "src_a_base_addr",
    },
    {
        "regcmd_index": 16,
        "buffer": "b",
        "kind": "value32",
        "target": "0x2001",
        "offset": "0x5038",
        "field": "src_b_base_addr",
    },
]


def emit(target: int, offset: int, value: int) -> int:
    """Rocket register command encoding: target[63:48] | value[47:16] | offset[15:0]."""
    return (target << 48) | ((int(value) & 0xFFFFFFFF) << 16) | offset


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def source_revision() -> dict:
    try:
        rev = subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        rev = None
    return {"rknpu-fpga": rev, "rk3588": "273d015e08af40c81d2cd9ab84198486b03a17f1"}


def case_name(case_index: int) -> str:
    first = 2 * case_index
    return f"fdiv_class_rows_{first:02d}_{first + 1:02d}"


def case_pairs(case_index: int) -> list[dict]:
    pairs = []
    for local_lane in range(LANES_PER_CASE):
        a_index = 2 * case_index + local_lane // 16
        b_index = local_lane % 16
        global_pair = 16 * a_index + b_index
        a = CLASSES[a_index]
        b = CLASSES[b_index]
        pairs.append(
            {
                "lane": local_lane,
                "pair_index": global_pair,
                "a": {
                    "class_index": a_index,
                    "name": a[0],
                    "bits": f"0x{a[1]:04x}",
                },
                "b": {
                    "class_index": b_index,
                    "name": b[0],
                    "bits": f"0x{b[1]:04x}",
                },
            }
        )
    return pairs


def build_regcmd() -> bytes:
    words = []
    for _index, target, offset, value, _field, _role in TEMPLATE:
        words.append(emit(target, offset, value))
    assert len(words) == REGS_PER_TASK
    return struct.pack("<" + "Q" * len(words), *words)


def build_job(name: str, case_index: int) -> dict:
    rows = (2 * case_index, 2 * case_index + 1)
    a_desc = (
        f"lanes 0-15 A{rows[0]:02d}=0x{CLASSES[rows[0]][1]:04x} ({CLASSES[rows[0]][2]}); "
        f"lanes 16-31 A{rows[1]:02d}=0x{CLASSES[rows[1]][1]:04x} ({CLASSES[rows[1]][2]})"
    )
    return {
        "case": name,
        "source_example": SOURCE_EXAMPLE,
        "description": (
            "FP16 FDIV raw operand-class truth table, 32 lanes, width=3; "
            + a_desc
            + "; B classes 0-15 in order in each 16-lane half"
        ),
        "timeout_ns": 6000000000,
        "tasks": [{"regcmd_offset_words": 0, "regcmd_words": REGS_PER_TASK}],
        "buffers": [
            {
                "name": "a",
                "size": BUFFER_BYTES,
                "input": "input-a.bin",
                "direction": "in",
            },
            {
                "name": "b",
                "size": BUFFER_BYTES,
                "input": "input-b.bin",
                "direction": "in",
            },
            {
                "name": "out",
                "size": BUFFER_BYTES,
                "direction": "out",
                "output": "output.bin",
            },
        ],
        "patches": [
            {
                "regcmd_index": patch["regcmd_index"],
                "buffer": patch["buffer"],
                "kind": patch["kind"],
            }
            for patch in PATCHES
        ],
    }


def bundle_hashes(case_dir: Path) -> dict:
    names = ["job.json", "regcmd.bin", "input-a.bin", "input-b.bin"]
    return {
        name: {
            "bytes": (case_dir / name).stat().st_size,
            "sha256": sha256_file(case_dir / name),
        }
        for name in names
    }


def main() -> None:
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    regcmd = build_regcmd()

    cases = []
    for case_index in range(CASE_COUNT):
        name = case_name(case_index)
        case_dir = CASES_DIR / name
        case_dir.mkdir(parents=True, exist_ok=True)
        pairs = case_pairs(case_index)
        rows = [2 * case_index, 2 * case_index + 1]

        a_bytes = b"".join(
            struct.pack("<H", CLASSES[rows[pair["lane"] // 16]][1]) for pair in pairs
        )
        b_bytes = b"".join(
            struct.pack("<H", CLASSES[pair["lane"] % 16][1]) for pair in pairs
        )
        assert len(a_bytes) == BUFFER_BYTES
        assert len(b_bytes) == BUFFER_BYTES

        job = build_job(name, case_index)
        job_bytes = (json.dumps(job, indent=2) + "\n").encode()

        (case_dir / "job.json").write_bytes(job_bytes)
        (case_dir / "regcmd.bin").write_bytes(regcmd)
        (case_dir / "input-a.bin").write_bytes(a_bytes)
        (case_dir / "input-b.bin").write_bytes(b_bytes)

        cases.append(
            {
                "case": name,
                "status": "READY",
                "op": "FDIV",
                "kind": "operand-class-truth-table",
                "rows": rows,
                "a_classes": [CLASSES[rows[0]][0], CLASSES[rows[1]][0]],
                "pair_range": [32 * case_index, 32 * case_index + 31],
                "pair_count": LANES_PER_CASE,
                "lanes": LANES_PER_CASE,
                "width": WIDTH,
                "ew_cfg": "0x108303c0",
                "out_convert": "0x00000001",
                "rdma_mode": "0x00017841",
                "description": job["description"],
                "source_example": SOURCE_EXAMPLE,
                "source_lines": SOURCE_LINES,
                "oracle": "none",
                "output": {
                    "name": "out",
                    "size": BUFFER_BYTES,
                    "direction": "out",
                    "output": "output.bin",
                },
                "patches": PATCHES,
                "bundle": bundle_hashes(case_dir),
                "pairs": pairs,
            }
        )

    manifest = {
        "family": "fdiv-systematic",
        "schema": "rk3588-example-captures/v1",
        "format_doc": str(FORMAT_DOC),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prepared_device_free": True,
        "device_access": "none (no ssh/scp/board, no submit, no program/flash)",
        "board_execution": (
            "PENDING: preparation only; no RK3588, Rocket or FPGA execution was performed"
        ),
        "source_revision": source_revision(),
        "source_hashes": {
            str(FORMAT_DOC): sha256_file(FORMAT_DOC),
            SOURCE_EXAMPLE: sha256_file(Path(SOURCE_EXAMPLE)),
        },
        "source_example": SOURCE_EXAMPLE,
        "source_lines": SOURCE_LINES,
        "operand_classes": [
            {"index": index, "name": name, "bits": f"0x{bits:04x}", "meaning": meaning}
            for index, (name, bits, meaning) in enumerate(CLASSES)
        ],
        "grid": {
            "a_classes": 16,
            "b_classes": 16,
            "total_pairs": PAIR_COUNT,
            "cases": CASE_COUNT,
            "lanes_per_case": LANES_PER_CASE,
            "order": "row-major, A class outer (row), B class inner (column)",
            "lane_mapping": (
                "case c covers A rows 2c and 2c+1; lane 0..15 uses A row 2c with "
                "B class 0..15, lane 16..31 uses A row 2c+1 with B class 0..15; "
                "global pair index = 16*A index + B index"
            ),
        },
        "regcmd_template": [
            {
                "index": index,
                "target": f"0x{target:04x}",
                "offset": f"0x{offset:04x}",
                "value": f"0x{value:08x}",
                "field": field,
                "role": role,
                "placeholder": index in PLACEHOLDER_INDICES,
            }
            for index, target, offset, value, field, role in TEMPLATE
        ],
        "cases": cases,
        "validation": {
            "method": "tools/validate.py (local JSON/binary shape parser only)",
            "scope": (
                "device-free structural validation; not SystemVerilog, not FPGA, "
                "not RK3588 silicon and not a numerical oracle"
            ),
            "result_file": "validation/local_validation.json",
        },
        "notes": [
            "All cases are READY with oracle none: this is a device characterization truth table.",
            "No output.bin or expected.bin is included; the later worker writes output.bin from the real device.",
            "Raw pair order is preserved in each case's pairs list and in the lane order of input-a.bin/input-b.bin.",
            "The 22-QWORD stream is 17 non-padding commands plus five zero-valued donor padding fields.",
            "QWORDs 14/15/16 are zero placeholders and require all three value32 patches before submit.",
        ],
    }

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {MANIFEST_PATH}")
    print(f"wrote {len(cases)} case bundles under {CASES_DIR}")


if __name__ == "__main__":
    main()
