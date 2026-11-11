#!/usr/bin/env /usr/bin/python3
"""Generate device-free FP16 elementwise capture bundles for RK3588.

This script only writes under build/rk3588-example-captures/ew-fp16/.  It does
not open a device, touch the network, or submit anything to hardware.  The
expected.bin files are donor CPU results (oracles), never device captures.

Derivation source: /home/fedora/rk3588/examples/elementwise.py, with the
EW_CFG values also cross-checked against examples/simple_add.py and the donor
implementation in experimental/kernel_6_18/elementwise.py.  The 22-QWORD
terminal command layout is the one emitted by elementwise.py for one task:
18 DPU/RDMA writes, then PC next-address, next-amount, VERSION marker and the
final PC OPERATION_ENABLE write.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "cases"
BUFFER_SIZE = 4096
TASK_WORDS = 22

MAIN = "/home/fedora/rk3588/examples/elementwise.py"
ADD = "/home/fedora/rk3588/examples/simple_add.py"
DONOR = "/home/fedora/rk3588/experimental/kernel_6_18/elementwise.py"
PROFILE = "/home/fedora/rknpu-fpga/model/profile.py"
FORMAT_DOC = "/home/fedora/rknpu-fpga/build/rk3588-example-captures/CAPTURE_FORMAT.md"

TARGET_DPU = 0x1001
TARGET_RDMA = 0x2001
TARGET_PC = 0x0081
TARGET_PC_REG = 0x0101
TARGET_VERSION = 0x0041

# op -> (EW_CFG, OUT_CVT_SCALE, RDMA_FEATURE_MODE_CFG)
OPS = {
    "ADD": (0x108202C0, 0x00010001, 0x00017849),
    "SUB": (0x108402C0, 0x00010001, 0x00017849),
    "MUL": (0x108003C4, 0x00010001, 0x00017849),
    "MAX": (0x108002C0, 0x00010001, 0x00017849),
    "NEG": (0x108003C4, 0x00010001, 0x00017849),
    # FDIV is the donor finite path: unity output scale, MRDMA fp16->fp32 off.
    "FDIV": (0x108303C0, 0x00000001, 0x00017841),
}
OP_ORDER = ["ADD", "SUB", "MUL", "MAX", "NEG", "FDIV"]
CORE_NS = [8, 9, 33]
EXTRA_NS = [1, 7, 1024]
CORE_PATTERNS = ["p1", "p2"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_revision(path: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", path, "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unavailable"


def enc(target: int, offset: int, value: int) -> int:
    if not (0 <= target <= 0xFFFF and 0 <= offset <= 0xFFFF and 0 <= value <= 0xFFFFFFFF):
        raise ValueError("command field out of range")
    return (target << 48) | (value << 16) | offset


def pattern_values(op: str, pattern: str, n: int) -> tuple[np.ndarray, np.ndarray]:
    idx = np.arange(n, dtype=np.int64)
    if pattern == "p1":
        a = (idx + 1).astype(np.float16)
        b = (8 - (idx % 8)).astype(np.float16)
    elif pattern == "p2":
        a = (((idx % 11) - 5) * 0.5).astype(np.float16)
        b = (((idx % 7) + 1) * 0.5).astype(np.float16)
    else:
        raise ValueError(pattern)
    if op == "NEG":
        # examples/elementwise.py:273 replaces the B operand with -1.0 for NEG.
        b = np.full(n, -1.0, dtype=np.float16)
    return a, b


def oracle(op: str, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Donor CPU result, exactly the examples/elementwise.py:475-478 path."""
    af = a.astype(np.float32)
    bf = b.astype(np.float32)
    with np.errstate(all="ignore"):
        if op == "ADD":
            r = af + bf
        elif op == "SUB":
            r = af - bf
        elif op == "MUL":
            r = af * bf
        elif op == "MAX":
            r = np.maximum(af, bf)
        elif op == "NEG":
            r = -af
        elif op == "FDIV":
            r = af / bf
        else:
            raise ValueError(op)
    return r.astype(np.float16)


def pattern_description(op: str, pattern: str) -> str:
    if op == "NEG":
        a_desc = "A=1..N" if pattern == "p1" else "A=-2.5,-2.0,...,2.5 cyclic (period 11)"
        return f"{a_desc}; B buffer is the MUL weight fixed to -1.0 (pattern B unused)"
    if pattern == "p1":
        return "A=1..N; B=8,7,...,1 cyclic (period 8)"
    return "A=-2.5,-2.0,...,2.5 cyclic (period 11); B=0.5,1.0,...,3.5 cyclic (period 7)"


def make_regcmd(op: str, n: int) -> tuple[bytes, int, int]:
    ew_cfg, out_cvt, rdma_mode = OPS[op]
    width = (n + 7) // 8 - 1
    padded = 8 * (width + 1)
    words = [
        enc(TARGET_DPU, 0x4004, 0x0000000E),      # S_POINTER
        enc(TARGET_DPU, 0x400C, 0x000001E5),      # FEATURE_MODE_CFG
        enc(TARGET_DPU, 0x4010, 0x48000002),      # DATA_FORMAT fp16/fp16/fp16
        enc(TARGET_DPU, 0x4030, width),           # DATA_CUBE_WIDTH (count/8 - 1)
        enc(TARGET_DPU, 0x4034, 0),               # DATA_CUBE_HEIGHT
        enc(TARGET_DPU, 0x4038, 0),               # DATA_CUBE_NOTCH
        enc(TARGET_DPU, 0x403C, 0x00070007),      # DATA_CUBE_CHANNEL
        enc(TARGET_DPU, 0x4070, ew_cfg),          # EW_CFG
        enc(TARGET_DPU, 0x4084, out_cvt),         # OUT_CVT_SCALE
        enc(TARGET_RDMA, 0x5004, 0x0000000E),     # RDMA S_POINTER
        enc(TARGET_RDMA, 0x500C, width),          # RDMA_DATA_CUBE_WIDTH
        enc(TARGET_RDMA, 0x5010, 0),              # RDMA_DATA_CUBE_HEIGHT
        enc(TARGET_RDMA, 0x5014, 7),              # RDMA_DATA_CUBE_CHANNEL
        enc(TARGET_RDMA, 0x5034, 0x40000008),     # RDMA_ERDMA_CFG
        enc(TARGET_DPU, 0x4020, 0),               # DST_BASE_ADDR placeholder
        enc(TARGET_RDMA, 0x5018, 0),              # RDMA_SRC_BASE_ADDR placeholder
        enc(TARGET_RDMA, 0x5038, 0),              # RDMA_EW_BASE_ADDR placeholder
        enc(TARGET_RDMA, 0x5044, rdma_mode),      # RDMA_FEATURE_MODE_CFG
        enc(TARGET_PC_REG, 0x0010, 0),            # PC next address (terminal 0)
        enc(TARGET_PC_REG, 0x0014, 0),            # PC next amount (terminal 0)
        enc(TARGET_VERSION, 0x0000, 0),           # VERSION marker
        enc(TARGET_PC, 0x0008, 0x18),             # OPERATION_ENABLE DPU|RDMA
    ]
    if len(words) != TASK_WORDS:
        raise AssertionError(len(words))
    return b"".join(struct.pack("<Q", w) for w in words), width, padded


def buffer_bytes(values: np.ndarray, padded: int, fill: float) -> bytes:
    pad = np.full(padded, fill, dtype=np.float16)
    pad[: len(values)] = values
    out = bytearray(BUFFER_SIZE)
    out[: 2 * padded] = pad.astype("<f2").tobytes()
    return bytes(out)


def case_entry(op: str, pattern: str, n: int) -> dict:
    case = f"{op.lower()}_{pattern}_n{n}"
    ew_cfg, out_cvt, rdma_mode = OPS[op]
    regcmd, width, padded = make_regcmd(op, n)
    a, b = pattern_values(op, pattern, n)

    # Logical operands must be finite.  FDIV never gets a zero divisor.
    assert np.isfinite(a).all() and np.isfinite(b).all()
    if op == "FDIV":
        assert (b != 0).all()
        b_fill = 1.0  # keep padded physical lanes finite: 0/1 = +0
    else:
        b_fill = 0.0

    expected = oracle(op, a, b)
    assert np.isfinite(expected).all()

    a_bytes = buffer_bytes(a, padded, 0.0)
    b_bytes = buffer_bytes(b, padded, b_fill)
    exp_bytes = expected.astype("<f2").tobytes()

    job_label = {
        "NEG": "elementwise NEG via MUL by -1.0",
        "FDIV": "finite elementwise FDIV",
    }.get(op, f"elementwise {op}")
    job = {
        "case": case,
        "source_example": MAIN,
        "description": (
            f"FP16 {job_label}, logical N={n}, {padded} physical lanes "
            f"(8-lane padding), pattern {pattern}"
        ),
        "timeout_ns": 6000000000,
        "tasks": [{"regcmd_offset_words": 0, "regcmd_words": TASK_WORDS}],
        "buffers": [
            {"name": "a", "size": BUFFER_SIZE, "input": "a.bin", "direction": "in"},
            {"name": "b", "size": BUFFER_SIZE, "input": "b.bin", "direction": "in"},
            {"name": "out", "size": BUFFER_SIZE, "direction": "out", "output": "out.bin"},
        ],
        "patches": [
            {"regcmd_index": 14, "buffer": "out", "kind": "value32"},
            {"regcmd_index": 15, "buffer": "a", "kind": "value32"},
            {"regcmd_index": 16, "buffer": "b", "kind": "value32"},
        ],
    }
    job_bytes = (json.dumps(job, indent=2) + "\n").encode()

    files = {
        "a.bin": a_bytes,
        "b.bin": b_bytes,
        "expected.bin": exp_bytes,
        "job.json": job_bytes,
        "regcmd.bin": regcmd,
    }
    bundle = {
        name: {"bytes": len(data), "sha256": sha256_bytes(data)}
        for name, data in sorted(files.items())
    }
    h = hashlib.sha256()
    for name in sorted(files):
        data = files[name]
        h.update(name.encode())
        h.update(b"\0")
        h.update(str(len(data)).encode())
        h.update(b"\0")
        h.update(sha256_bytes(data).encode())
        h.update(b"\n")
    bundle_digest = h.hexdigest()

    case_dir = CASES_DIR / case
    case_dir.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (case_dir / name).write_bytes(data)

    manifest_label = {
        "NEG": "NEG via MUL by -1.0",
        "FDIV": "finite FDIV",
    }.get(op, op)
    return {
        "case": case,
        "status": "READY",
        "op": op,
        "pattern": pattern,
        "logical_count": n,
        "padded_count": padded,
        "width": width,
        "ew_cfg": f"0x{ew_cfg:08x}",
        "out_convert": f"0x{out_cvt:08x}",
        "rdma_mode": f"0x{rdma_mode:08x}",
        "description": (
            f"FP16 {manifest_label} at N={n} ({padded} padded lanes); pattern {pattern}: "
            f"{pattern_description(op, pattern)}"
        ),
        "source_example": MAIN,
        "source_lines": [
            f"{MAIN}:246-352 (8-lane width, DPU/RDMA body, per-op EW_CFG)",
            f"{MAIN}:199-244 (terminal PC tail and task writer)",
            f"{MAIN}:475-478 (donor float32 compute then fp16 cast)",
            f"{DONOR}:224-231,302-309 (EW_CFG and CPU op oracle)",
            f"{ADD}:196-203,215-236 (EW_CFG and 8-lane width cross-check)",
            f"{PROFILE}:11-37,156-170 (reviewed register/EW_CFG whitelist)",
        ],
        "oracle": {
            "kind": "donor-cpu-numpy",
            "device_output": False,
            "warning": "CPU oracle only; never a device capture or fallback result",
            "file": "expected.bin",
            "dtype": "float16-le",
            "count": n,
            "covers": f"first {n} halfwords of out.bin; 8-lane padded tail excluded",
            "formula": oracle_formula(op),
            "source": f"{DONOR}:302-309",
            "cast_source": f"{MAIN}:475-478",
        },
        "bundle": bundle,
        "bundle_sha256": bundle_digest,
        "caveats": [
            "Address fields at regcmd QWORDs 14/15/16 are zero placeholders; the worker must apply all three value32 patches.",
            "Only the first N halfwords are covered by the oracle; the padded lanes are device padding.",
        ]
        + (
            [
                "NEG uses EW_CFG 0x108003c4, the same value as MUL, with weight -1.0. The local profile has no distinct NEG op and would classify it as MUL; this bundle targets RK silicon.",
            ]
            if op == "NEG"
            else []
        )
        + (
            [
                "Finite FDIV only: B is strictly positive. Uses EW_CFG 0x108303c0, out_convert=0x00000001 and rdma_mode=0x00017841, which are outside the current local RTL whitelist.",
                "FDIV padded B lanes are +1.0 so every physical lane computes a finite 0/1=+0; padded lanes are still outside the oracle.",
            ]
            if op == "FDIV"
            else []
        ),
    }


def oracle_formula(op: str) -> str:
    return {
        "ADD": "float16(float32(a) + float32(b))",
        "SUB": "float16(float32(a) - float32(b))",
        "MUL": "float16(float32(a) * float32(b))",
        "MAX": "float16(max(float32(a), float32(b)))",
        "NEG": "float16(-float32(a)) with B weight fixed -1.0",
        "FDIV": "float16(float32(a) / float32(b))",
    }[op]


def main() -> int:
    if CASES_DIR.exists():
        shutil.rmtree(CASES_DIR)
    CASES_DIR.mkdir(parents=True)

    cases = []
    for op in OP_ORDER:
        for n in CORE_NS:
            for pattern in CORE_PATTERNS:
                cases.append(case_entry(op, pattern, n))
        for n in EXTRA_NS:
            cases.append(case_entry(op, "p1", n))

    summary = {
        "total": len(cases),
        "ready": sum(c["status"] == "READY" for c in cases),
        "blocked": sum(c["status"] == "BLOCKED" for c in cases),
        "ops": OP_ORDER,
        "core_lengths": CORE_NS,
        "optional_lengths": EXTRA_NS,
        "patterns": CORE_PATTERNS,
    }
    source_hashes = {
        path: sha256_file(Path(path))
        for path in (MAIN, ADD, DONOR, PROFILE, FORMAT_DOC)
    }
    manifest = {
        "family": "ew-fp16",
        "schema": "rk3588-example-captures/v1",
        "format_doc": FORMAT_DOC,
        "generated_utc": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "prepared_device_free": True,
        "device_access": "none (no ssh/scp/board, no submit, no program/flash)",
        "board_execution": "PENDING: preparation only; no RK3588 or FPGA execution was performed",
        "out_of_scope": [
            "FDIV Inf/NaN/zero-divisor special-value cases: intentionally not duplicated; separate capture work exists.",
            "Linked PC chains and multiple tasks per case: not part of this terminal single-task family.",
            "FP32 output conversion and non-finite operands: not part of this finite FP16 family.",
        ],
        "source_revision": {
            "rknpu-fpga": git_revision("/home/fedora/rknpu-fpga"),
            "rk3588": git_revision("/home/fedora/rk3588"),
        },
        "source_hashes": source_hashes,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "input_generation": "closed-form deterministic patterns; no RNG and no seed",
        "summary": summary,
        "cases": cases,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"wrote {summary['total']} cases "
        f"({summary['ready']} READY, {summary['blocked']} BLOCKED) to {ROOT}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
