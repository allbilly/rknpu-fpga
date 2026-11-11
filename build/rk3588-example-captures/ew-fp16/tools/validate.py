#!/usr/bin/env /usr/bin/python3
"""Local structural validator for the ew-fp16 capture bundles.

This is not hardware validation.  It checks the CAPTURE_FORMAT.md JSON shape,
buffer sizes, the 22-QWORD regcmd template, patch indices/placeholders, the
deterministic input patterns and the recorded bundle hashes.  When NumPy is
available it also recomputes the donor CPU oracle and compares expected.bin
byte-for-byte.  No device, network or board access is performed.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "cases"
BUFFER_SIZE = 4096
TASK_WORDS = 22

TARGET_DPU = 0x1001
TARGET_RDMA = 0x2001
TARGET_PC = 0x0081
TARGET_PC_REG = 0x0101
TARGET_VERSION = 0x0041

OPS = {
    "ADD": (0x108202C0, 0x00010001, 0x00017849),
    "SUB": (0x108402C0, 0x00010001, 0x00017849),
    "MUL": (0x108003C4, 0x00010001, 0x00017849),
    "MAX": (0x108002C0, 0x00010001, 0x00017849),
    "NEG": (0x108003C4, 0x00010001, 0x00017849),
    "FDIV": (0x108303C0, 0x00000001, 0x00017841),
}

# (target, offset, fixed value or None for the width field)
TEMPLATE = [
    (TARGET_DPU, 0x4004, 0x0000000E),
    (TARGET_DPU, 0x400C, 0x000001E5),
    (TARGET_DPU, 0x4010, 0x48000002),
    (TARGET_DPU, 0x4030, None),
    (TARGET_DPU, 0x4034, 0),
    (TARGET_DPU, 0x4038, 0),
    (TARGET_DPU, 0x403C, 0x00070007),
    (TARGET_DPU, 0x4070, None),
    (TARGET_DPU, 0x4084, None),
    (TARGET_RDMA, 0x5004, 0x0000000E),
    (TARGET_RDMA, 0x500C, None),
    (TARGET_RDMA, 0x5010, 0),
    (TARGET_RDMA, 0x5014, 7),
    (TARGET_RDMA, 0x5034, 0x40000008),
    (TARGET_DPU, 0x4020, 0),       # DST placeholder
    (TARGET_RDMA, 0x5018, 0),      # SRC placeholder
    (TARGET_RDMA, 0x5038, 0),      # EW placeholder
    (TARGET_RDMA, 0x5044, None),
    (TARGET_PC_REG, 0x0010, 0),
    (TARGET_PC_REG, 0x0014, 0),
    (TARGET_VERSION, 0x0000, 0),
    (TARGET_PC, 0x0008, 0x18),
]
ADDR_PATCHES = {
    14: ("out", TARGET_DPU, 0x4020),
    15: ("a", TARGET_RDMA, 0x5018),
    16: ("b", TARGET_RDMA, 0x5038),
}
CASE_KEYS = {
    "case",
    "status",
    "op",
    "pattern",
    "logical_count",
    "padded_count",
    "width",
    "ew_cfg",
    "out_convert",
    "rdma_mode",
    "description",
    "source_example",
    "source_lines",
    "oracle",
    "bundle",
    "bundle_sha256",
    "caveats",
}
JOB_KEYS = {
    "case",
    "source_example",
    "description",
    "timeout_ns",
    "tasks",
    "buffers",
    "patches",
}
BUNDLE_FILES = {"a.bin", "b.bin", "expected.bin", "job.json", "regcmd.bin"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bundle_digest(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        data = files[name]
        h.update(name.encode())
        h.update(b"\0")
        h.update(str(len(data)).encode())
        h.update(b"\0")
        h.update(sha256_bytes(data).encode())
        h.update(b"\n")
    return h.hexdigest()


def decode(word: int) -> tuple[int, int, int]:
    return word >> 48, word & 0xFFFF, (word >> 16) & 0xFFFFFFFF


def ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


def expected_pattern(op: str, pattern: str, n: int) -> tuple[list[float], list[float]]:
    a: list[float] = []
    b: list[float] = []
    for i in range(n):
        if pattern == "p1":
            av = float(i + 1)
            bv = float(8 - (i % 8))
        elif pattern == "p2":
            av = ((i % 11) - 5) * 0.5
            bv = ((i % 7) + 1) * 0.5
        else:
            raise ValueError(pattern)
        a.append(av)
        b.append(-1.0 if op == "NEG" else bv)
    return a, b


def pack_f16(value: float) -> bytes:
    return struct.pack("<e", value)


def check_case(entry: dict, errors: list[str]) -> None:
    case = entry.get("case", "<missing>")

    def bad(msg: str) -> None:
        errors.append(f"{case}: {msg}")

    missing = CASE_KEYS - set(entry)
    extra = set(entry) - CASE_KEYS
    if missing:
        bad(f"manifest case missing keys {sorted(missing)}")
    if extra:
        bad(f"manifest case unknown keys {sorted(extra)}")
    if entry.get("status") not in ("READY", "BLOCKED"):
        bad("status is not READY/BLOCKED")
    if entry.get("status") == "BLOCKED":
        if not entry.get("blocked_reason"):
            bad("BLOCKED without blocked_reason")
        return

    op = entry.get("op")
    if op not in OPS:
        bad(f"unknown op {op!r}")
        return
    ew_cfg, out_cvt, rdma_mode = OPS[op]
    if entry.get("ew_cfg") != f"0x{ew_cfg:08x}":
        bad(f"ew_cfg {entry.get('ew_cfg')!r} != 0x{ew_cfg:08x}")
    if entry.get("out_convert") != f"0x{out_cvt:08x}":
        bad(f"out_convert {entry.get('out_convert')!r} != 0x{out_cvt:08x}")
    if entry.get("rdma_mode") != f"0x{rdma_mode:08x}":
        bad(f"rdma_mode {entry.get('rdma_mode')!r} != 0x{rdma_mode:08x}")

    n = entry.get("logical_count")
    if not isinstance(n, int) or n < 1:
        bad("logical_count must be a positive integer")
        return
    width = ceil_div(n, 8) - 1
    padded = 8 * (width + 1)
    if entry.get("width") != width:
        bad(f"width {entry.get('width')!r} != {width}")
    if entry.get("padded_count") != padded:
        bad(f"padded_count {entry.get('padded_count')!r} != {padded}")

    pattern = entry.get("pattern")
    if pattern not in ("p1", "p2"):
        bad(f"pattern {pattern!r} is not p1/p2")

    case_dir = CASES_DIR / case
    if not case_dir.is_dir():
        bad("case directory missing")
        return
    actual_files = {p.name for p in case_dir.iterdir() if p.is_file()}
    if actual_files != BUNDLE_FILES:
        bad(f"case files {sorted(actual_files)} != {sorted(BUNDLE_FILES)}")
        return
    files = {name: (case_dir / name).read_bytes() for name in BUNDLE_FILES}

    # ---- job.json shape -------------------------------------------------
    try:
        job = json.loads(files["job.json"])
    except Exception as exc:
        bad(f"job.json is not valid JSON: {exc}")
        return
    if not isinstance(job, dict):
        bad("job.json is not an object")
        return
    if set(job) != JOB_KEYS:
        bad(f"job.json keys {sorted(set(job))} != {sorted(JOB_KEYS)}")
    if job.get("case") != case:
        bad("job.json case mismatch")
    if job.get("source_example") != entry.get("source_example"):
        bad("job.json source_example mismatch")
    if not isinstance(job.get("description"), str) or not job["description"]:
        bad("job.json description missing")
    if not isinstance(job.get("timeout_ns"), int) or job["timeout_ns"] <= 0:
        bad("job.json timeout_ns must be a positive integer")

    tasks = job.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1:
        bad("tasks must be a one-element list")
    else:
        task = tasks[0]
        if set(task) != {"regcmd_offset_words", "regcmd_words"}:
            bad("task keys are not exactly regcmd_offset_words/regcmd_words")
        else:
            if task["regcmd_offset_words"] != 0 or task["regcmd_words"] != TASK_WORDS:
                bad("task must be offset 0 and 22 regcmd words")

    buffers = job.get("buffers")
    buffers_by_name: dict[str, dict] = {}
    if not isinstance(buffers, list) or len(buffers) != 3:
        bad("buffers must be a three-element list")
    else:
        for buf in buffers:
            if not isinstance(buf, dict) or "name" not in buf:
                bad("malformed buffer entry")
                continue
            name = buf["name"]
            if name in buffers_by_name:
                bad(f"duplicate buffer {name}")
            buffers_by_name[name] = buf
        if set(buffers_by_name) != {"a", "b", "out"}:
            bad(f"buffer names {sorted(buffers_by_name)} != ['a','b','out']")
        for name, filename in (("a", "a.bin"), ("b", "b.bin")):
            buf = buffers_by_name.get(name, {})
            if set(buf) != {"name", "size", "input", "direction"}:
                bad(f"buffer {name} keys must be name/size/input/direction")
            if buf.get("size") != BUFFER_SIZE:
                bad(f"buffer {name} size {buf.get('size')!r} != {BUFFER_SIZE}")
            if buf.get("input") != filename:
                bad(f"buffer {name} input {buf.get('input')!r} != {filename!r}")
            if buf.get("direction") != "in":
                bad(f"buffer {name} direction must be 'in'")
        out = buffers_by_name.get("out", {})
        if set(out) != {"name", "size", "direction", "output"}:
            bad("out buffer keys must be name/size/direction/output")
        if out.get("size") != BUFFER_SIZE:
            bad(f"out buffer size {out.get('size')!r} != {BUFFER_SIZE}")
        if out.get("direction") != "out":
            bad("out buffer direction must be 'out'")
        if out.get("output") != "out.bin":
            bad("out buffer output must be 'out.bin'")

    patches = job.get("patches")
    if not isinstance(patches, list) or len(patches) != 3:
        bad("patches must be a three-element list")
    else:
        seen = set()
        for patch in patches:
            if set(patch) != {"regcmd_index", "buffer", "kind"}:
                bad("patch keys must be regcmd_index/buffer/kind")
                continue
            idx = patch["regcmd_index"]
            if not isinstance(idx, int):
                bad("patch regcmd_index is not an integer")
                continue
            if idx < 0 or idx >= TASK_WORDS:
                bad(f"patch index {idx} out of range 0..{TASK_WORDS - 1}")
            if idx in seen:
                bad(f"duplicate patch index {idx}")
            seen.add(idx)
            if idx in ADDR_PATCHES:
                name, _, _ = ADDR_PATCHES[idx]
                if patch["buffer"] != name:
                    bad(f"patch {idx} buffer {patch['buffer']!r} != {name!r}")
                if patch["kind"] != "value32":
                    bad(f"patch {idx} kind must be value32")
            else:
                bad(f"patch index {idx} is not one of the three address fields")
        if seen != set(ADDR_PATCHES):
            bad(f"patch indices {sorted(seen)} != {sorted(ADDR_PATCHES)}")

    # ---- regcmd template ------------------------------------------------
    regcmd = files["regcmd.bin"]
    if len(regcmd) != TASK_WORDS * 8:
        bad(f"regcmd.bin is {len(regcmd)} bytes, expected {TASK_WORDS * 8}")
        return
    words = list(struct.unpack("<" + "Q" * TASK_WORDS, regcmd))
    for idx, (target, offset, fixed) in enumerate(TEMPLATE):
        got_target, got_offset, got_value = decode(words[idx])
        if (got_target, got_offset) != (target, offset):
            bad(
                f"regcmd[{idx}] target/offset {got_target:#06x}/{got_offset:#06x} "
                f"!= {target:#06x}/{offset:#06x}"
            )
        expected_value = width if fixed is None and idx in (3, 10) else fixed
        if fixed is None and idx == 7:
            expected_value = ew_cfg
        if fixed is None and idx == 8:
            expected_value = out_cvt
        if fixed is None and idx == 17:
            expected_value = rdma_mode
        if got_value != expected_value:
            bad(f"regcmd[{idx}] value {got_value:#010x} != {expected_value:#010x}")
    if words[21] != 0x0081000000180008:
        bad("final PC OPERATION_ENABLE word is not 0x0081000000180008")
    for idx, (name, target, offset) in ADDR_PATCHES.items():
        t, o, v = decode(words[idx])
        if v != 0:
            bad(f"address placeholder regcmd[{idx}] is not zero: {v:#x}")

    # ---- raw input files ------------------------------------------------
    a_bytes = files["a.bin"]
    b_bytes = files["b.bin"]
    if len(a_bytes) != BUFFER_SIZE or len(b_bytes) != BUFFER_SIZE:
        bad("a.bin/b.bin size is not 4096")
        return
    a_vals, b_vals = expected_pattern(op, pattern, n)
    for i, (av, bv) in enumerate(zip(a_vals, b_vals)):
        if a_bytes[2 * i : 2 * i + 2] != pack_f16(av):
            bad(f"a.bin[{i}] does not match pattern {pattern}")
            break
    for i, (av, bv) in enumerate(zip(a_vals, b_vals)):
        if b_bytes[2 * i : 2 * i + 2] != pack_f16(bv):
            bad(f"b.bin[{i}] does not match pattern {pattern} (NEG weights are -1)")
            break
    b_fill = 1.0 if op == "FDIV" else 0.0
    for i in range(n, padded):
        if a_bytes[2 * i : 2 * i + 2] != pack_f16(0.0):
            bad(f"a.bin padded lane {i} is not +0.0")
            break
    for i in range(n, padded):
        if b_bytes[2 * i : 2 * i + 2] != pack_f16(b_fill):
            bad(f"b.bin padded lane {i} is not {b_fill}")
            break
    if any(a_bytes[2 * padded :]) or any(b_bytes[2 * padded :]):
        bad("bytes after the 8-lane padded region are not zero")

    # ---- expected.bin (oracle, not device output) -----------------------
    exp_bytes = files["expected.bin"]
    if len(exp_bytes) != 2 * n:
        bad(f"expected.bin is {len(exp_bytes)} bytes, expected {2 * n}")
    oracle = entry.get("oracle", {})
    if oracle.get("device_output") is not False:
        bad("oracle.device_output must be false")
    if oracle.get("file") != "expected.bin":
        bad("oracle.file must be expected.bin")
    if oracle.get("dtype") != "float16-le":
        bad("oracle.dtype must be float16-le")
    if oracle.get("count") != n:
        bad("oracle.count must equal logical_count")
    if not isinstance(oracle.get("warning"), str) or not oracle["warning"]:
        bad("oracle.warning missing")

    # ---- manifest hashes ------------------------------------------------
    bundle = entry.get("bundle", {})
    if set(bundle) != BUNDLE_FILES:
        bad(f"manifest bundle keys {sorted(bundle)} != {sorted(BUNDLE_FILES)}")
    else:
        for name, data in files.items():
            rec = bundle[name]
            if rec.get("bytes") != len(data):
                bad(f"manifest size mismatch for {name}")
            if rec.get("sha256") != sha256_bytes(data):
                bad(f"manifest sha256 mismatch for {name}")
    if entry.get("bundle_sha256") != bundle_digest(files):
        bad("bundle_sha256 mismatch")

    # ---- optional independent donor-oracle recompute --------------------
    global ORACLE_CHECKED, ORACLE_ERRORS, np
    if np is not None:
        a16 = np.frombuffer(a_bytes[: 2 * n], dtype="<f2")
        b16 = np.frombuffer(b_bytes[: 2 * n], dtype="<f2")
        af = a16.astype(np.float32)
        bf = b16.astype(np.float32)
        if not np.isfinite(a16).all() or not np.isfinite(b16).all():
            bad("non-finite logical input")
        if op == "FDIV" and not (b16 != 0).all():
            bad("FDIV logical divisor contains zero")
        with np.errstate(all="ignore"):
            if op == "ADD":
                raw = af + bf
            elif op == "SUB":
                raw = af - bf
            elif op == "MUL":
                raw = af * bf
            elif op == "MAX":
                raw = np.maximum(af, bf)
            elif op == "NEG":
                raw = -af
            else:
                raw = af / bf
        recomputed = raw.astype("<f2").tobytes()
        ORACLE_CHECKED += 1
        if recomputed != exp_bytes:
            ORACLE_ERRORS += 1
            bad("expected.bin does not match the recomputed donor oracle")
        if not np.isfinite(raw.astype(np.float16)).all():
            bad("oracle contains a non-finite logical result")
        # The physical lanes (including padding) must also stay finite.
        a_pad = np.frombuffer(a_bytes[: 2 * padded], dtype="<f2").astype(np.float32)
        b_pad = np.frombuffer(b_bytes[: 2 * padded], dtype="<f2").astype(np.float32)
        with np.errstate(all="ignore"):
            if op == "ADD":
                raw_pad = a_pad + b_pad
            elif op == "SUB":
                raw_pad = a_pad - b_pad
            elif op == "MUL":
                raw_pad = a_pad * b_pad
            elif op == "MAX":
                raw_pad = np.maximum(a_pad, b_pad)
            elif op == "NEG":
                raw_pad = a_pad * b_pad
            else:
                raw_pad = a_pad / b_pad
        if not np.isfinite(raw_pad.astype(np.float16)).all():
            bad("a padded physical lane produces a non-finite result")


def main() -> int:
    global np, ORACLE_CHECKED, ORACLE_ERRORS
    try:
        import numpy as np  # noqa: F811
    except Exception:
        np = None
    ORACLE_CHECKED = 0
    ORACLE_ERRORS = 0
    errors: list[str] = []

    manifest_path = ROOT / "manifest.json"
    if not manifest_path.is_file():
        print(f"FAIL: {manifest_path} missing")
        return 1
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as exc:
        print(f"FAIL: manifest.json is not valid JSON: {exc}")
        return 1

    required_top = {
        "family",
        "schema",
        "format_doc",
        "generated_utc",
        "prepared_device_free",
        "device_access",
        "board_execution",
        "out_of_scope",
        "source_revision",
        "source_hashes",
        "environment",
        "input_generation",
        "summary",
        "cases",
    }
    missing = required_top - set(manifest)
    if missing:
        errors.append(f"manifest: missing keys {sorted(missing)}")
    if manifest.get("family") != "ew-fp16":
        errors.append("manifest: family is not ew-fp16")
    if manifest.get("schema") != "rk3588-example-captures/v1":
        errors.append("manifest: unexpected schema")

    cases = manifest.get("cases")
    if not isinstance(cases, list):
        print("FAIL: manifest.cases is not a list")
        return 1
    names = [c.get("case") for c in cases]
    if len(names) != len(set(names)):
        errors.append("manifest: duplicate case names")

    summary = manifest.get("summary", {})
    ready = sum(c.get("status") == "READY" for c in cases)
    blocked = sum(c.get("status") == "BLOCKED" for c in cases)
    if summary.get("total") != len(cases):
        errors.append("manifest: summary.total mismatch")
    if summary.get("ready") != ready:
        errors.append("manifest: summary.ready mismatch")
    if summary.get("blocked") != blocked:
        errors.append("manifest: summary.blocked mismatch")

    if CASES_DIR.is_dir():
        dirs = {p.name for p in CASES_DIR.iterdir() if p.is_dir()}
        if dirs != set(names):
            errors.append(
                f"cases directory set differs from manifest: "
                f"extra={sorted(dirs - set(names))} missing={sorted(set(names) - dirs)}"
            )
    else:
        errors.append("cases directory missing")

    for entry in cases:
        before = len(errors)
        check_case(entry, errors)
        status = entry.get("status")
        if len(errors) == before:
            print(
                f"{entry.get('case')}: OK  status={status} "
                f"n={entry.get('logical_count')} padded={entry.get('padded_count')} "
                f"op={entry.get('op')} pattern={entry.get('pattern')}"
            )
        else:
            print(f"{entry.get('case')}: FAIL see errors below")

    print()
    print(f"cases: {len(cases)} total, {ready} READY, {blocked} BLOCKED")
    if np is not None:
        print(
            f"oracle recompute: numpy {np.__version__}, "
            f"{ORACLE_CHECKED} checked, {ORACLE_ERRORS} mismatches"
        )
    else:
        print("oracle recompute: SKIP (numpy unavailable)")
    print(f"structural errors: {len(errors)}")
    if errors:
        for err in errors:
            print(f"  ERROR {err}")
        print("result: FAIL")
        return 1
    print("result: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
