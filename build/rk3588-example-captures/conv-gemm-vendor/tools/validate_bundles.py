#!/usr/bin/env python3
"""Validate every READY bundle locally without a device.

Checks the CAPTURE_FORMAT job shape, buffer files and sizes, regcmd QWORD
length, task ranges/alignment, patch indices and address fields, expected
oracle size/hash, and the manifest hashes/status counts.  It does not run any
NPU command and does not access the board.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

FAMILY = Path(__file__).resolve().parents[1]
MANIFEST = FAMILY / "manifest.json"
ROCKET_MAX_REGCMDS = (0xFFFF + 1) * 2
DTYPE_BYTES = {"float16": 2, "float32": 4, "uint16": 2, "uint32": 4}
ADDRESS_FIELDS = {
    (0x0201, 0x1070): "input",   # CNA_FEATURE_DATA_ADDR
    (0x0201, 0x1110): "weight",  # CNA_DCOMP_ADDR0
    (0x1001, 0x4020): "output",  # DPU_DST_BASE_ADDR
    (0x2001, 0x5018): "input",   # RDMA_SRC_BASE_ADDR
    (0x2001, 0x5038): "weight",  # RDMA_EW_BASE_ADDR
}
ALLOWED_KINDS = {"value32", "all32", "low32", "high32"}
SYMBOLIC = {"input": 0x10000000, "weight": 0x20000000, "output": 0x30000000}
ERRORS: list[str] = []


def E(target: int, reg_addr: int, value: int) -> int:
    return (target << 48) | ((value & 0xFFFFFFFF) << 16) | (reg_addr & 0xFFFF)


def fail(msg: str) -> None:
    ERRORS.append(msg)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def main() -> int:
    require(MANIFEST.is_file(), f"missing {MANIFEST}")
    if not MANIFEST.is_file():
        print("\n".join(ERRORS))
        return 1
    manifest = json.loads(MANIFEST.read_text())
    require(manifest.get("schema") == "rk3588-example-capture-manifest-v1",
            "unexpected manifest schema")
    cases = manifest.get("cases", [])
    require(isinstance(cases, list) and bool(cases), "manifest has no cases")

    ready = blocked = 0
    max_words = 0
    seen_cases: set[str] = set()
    for case in cases:
        name = case.get("case", "")
        require(bool(name), "case without name")
        require(name not in seen_cases, f"{name}: duplicate case")
        seen_cases.add(name)
        status = case.get("status")
        require(status in {"READY", "BLOCKED"}, f"{name}: bad status {status!r}")
        source = Path(case.get("source_example", ""))
        require(source.is_file(), f"{name}: missing source {source}")
        if source.is_file():
            require(sha256(source) == case.get("source_example_sha256"),
                    f"{name}: source hash mismatch")
        require(bool(case.get("shape")), f"{name}: missing shape")
        require(bool(case.get("description")), f"{name}: missing description")
        require(isinstance(case.get("source_lines"), list)
                and bool(case["source_lines"]), f"{name}: missing source lines")

        if status == "BLOCKED":
            blocked += 1
            require(bool(case.get("blocked_reason")), f"{name}: missing reason")
            require(isinstance(case.get("evidence"), list)
                    and bool(case["evidence"]), f"{name}: missing evidence")
            case_dir = FAMILY / case.get("case_dir", "")
            blocked_md = case_dir / "BLOCKED.md"
            require(blocked_md.is_file(), f"{name}: missing BLOCKED.md")
            if blocked_md.is_file():
                require(sha256(blocked_md) == case["hashes"].get("BLOCKED.md"),
                        f"{name}: BLOCKED.md hash mismatch")
            require(not (case_dir / "job.json").exists(),
                    f"{name}: blocked case should not have job.json")
            continue

        ready += 1
        case_dir = FAMILY / case.get("case_dir", "")
        job_path = case_dir / "job.json"
        regcmd_path = case_dir / "regcmd.bin"
        expected_path = case_dir / "expected.bin"
        require(job_path.is_file(), f"{name}: missing job.json")
        require(regcmd_path.is_file(), f"{name}: missing regcmd.bin")
        require(expected_path.is_file(), f"{name}: missing expected.bin")
        if not (job_path.is_file() and regcmd_path.is_file() and expected_path.is_file()):
            continue

        hashes = case.get("hashes", {})
        require(hashes.get("job.json") == sha256(job_path),
                f"{name}: job hash mismatch")
        require(hashes.get("regcmd.bin") == sha256(regcmd_path),
                f"{name}: regcmd hash mismatch")
        require(hashes.get("expected.bin") == sha256(expected_path),
                f"{name}: expected hash mismatch")

        job = json.loads(job_path.read_text())
        for key in ("case", "source_example", "description", "timeout_ns",
                    "tasks", "buffers", "patches"):
            require(key in job, f"{name}: job missing {key}")
        require(job.get("case") == name, f"{name}: job case mismatch")
        require(isinstance(job.get("timeout_ns"), int) and job["timeout_ns"] > 0,
                f"{name}: bad timeout_ns")

        regcmd = regcmd_path.read_bytes()
        require(len(regcmd) % 8 == 0, f"{name}: regcmd not a QWORD multiple")
        words = list(struct.unpack("<" + "Q" * (len(regcmd) // 8), regcmd))
        regcmd_words = len(words)
        require(regcmd_words % 2 == 0,
                f"{name}: Rocket regcmd_count {regcmd_words} is odd and would fetch one extra QWORD")
        buffers = job.get("buffers", [])
        require(isinstance(buffers, list) and bool(buffers),
                f"{name}: no buffers")
        names: dict[str, dict] = {}
        for buf in buffers:
            bname = buf.get("name")
            require(bool(bname), f"{name}: buffer without name")
            require(bname not in names, f"{name}: duplicate buffer {bname}")
            names[bname] = buf
            size = buf.get("size")
            require(isinstance(size, int) and size > 0,
                    f"{name}/{bname}: bad size")
            direction = buf.get("direction")
            require(direction in {"in", "out", "inout"},
                    f"{name}/{bname}: bad direction {direction!r}")
            if direction in {"in", "inout"}:
                rel = buf.get("input")
                require(bool(rel), f"{name}/{bname}: missing input file")
                if rel:
                    path = case_dir / rel
                    require(path.is_file(), f"{name}/{bname}: missing {rel}")
                    if path.is_file():
                        require(path.stat().st_size == size,
                                f"{name}/{bname}: size {path.stat().st_size} != {size}")
            if direction in {"out", "inout"}:
                require(bool(buf.get("output")),
                        f"{name}/{bname}: missing output name")

        tasks = job.get("tasks", [])
        require(isinstance(tasks, list) and bool(tasks), f"{name}: no tasks")
        ranges: list[tuple[int, int]] = []
        for task in tasks:
            offset = task.get("regcmd_offset_words")
            count = task.get("regcmd_words")
            require(isinstance(offset, int) and isinstance(count, int),
                    f"{name}: task offset/count not ints")
            require(offset >= 0, f"{name}: negative task offset")
            require(count > 0, f"{name}: zero task count")
            require(count <= ROCKET_MAX_REGCMDS,
                    f"{name}: task count {count} > {ROCKET_MAX_REGCMDS}")
            require(offset % 2 == 0,
                    f"{name}: task offset {offset} not 16-byte aligned")
            require(offset + count <= regcmd_words,
                    f"{name}: task range {offset}+{count} > {regcmd_words}")
            max_words = max(max_words, count)
            ranges.append((offset, count))
        for i, (o1, c1) in enumerate(ranges):
            for o2, c2 in ranges[i + 1:]:
                if (o1, c1) != (o2, c2):
                    require(o1 + c1 <= o2 or o2 + c2 <= o1,
                            f"{name}: distinct task ranges overlap")

        vendor = case.get("vendor_task_descriptor", {})
        body = vendor.get("regcfg_amount_qwords")
        tail_style = vendor.get("terminal_tail_style")
        require(isinstance(body, int) and body > 0,
                f"{name}: missing vendor regcfg_amount")
        if isinstance(body, int) and body > 0:
            for offset, count in ranges:
                require(count >= body + 4,
                        f"{name}: task at {offset} shorter than body + tail")
                if tail_style == "pc_base_zero":
                    require(words[offset + body] == E(0x0101, 0x0010, 0),
                            f"{name}: task at {offset} PC_BASE_ADDRESS is not zero")
                    require(words[offset + body + 1] == E(0x0101, 0x0014, 0),
                            f"{name}: task at {offset} PC_REGISTER_AMOUNTS is not zero")
                elif tail_style == "nop_separator":
                    require(words[offset + body] == E(0x0001, 0x0000, 0),
                            f"{name}: task at {offset} NOP separator missing")
                    require(words[offset + body + 1] == E(0x0101, 0x0014, 0),
                            f"{name}: task at {offset} PC_REGISTER_AMOUNTS is not zero")
                else:
                    fail(f"{name}: unknown terminal tail style {tail_style!r}")
                require(words[offset + body + 2] == E(0x0041, 0x0000, 0),
                        f"{name}: task at {offset} VERSION marker missing")
                require(words[offset + body + 3] == E(0x0081, 0x0008, 0x000D),
                        f"{name}: task at {offset} PC_OPERATION_ENABLE is not 0xd")
                for idx in range(offset + body + 4, offset + count):
                    require(words[idx] == 0,
                            f"{name}: nonzero parity NOP pad at {idx}")

        vendor = case.get("vendor_task_descriptor", {})
        body = vendor.get("regcfg_amount_qwords")
        extra = vendor.get("vendor_pc_data_extra_qwords")
        fetch = vendor.get("vendor_fetch_qwords")
        pad = vendor.get("parity_pad_qwords")
        rocket_count = vendor.get("rocket_regcmd_count_qwords")
        require(isinstance(body, int) and body > 0,
                f"{name}: missing vendor regcfg_amount")
        require(extra == 4, f"{name}: unexpected vendor PC extra amount")
        require(isinstance(fetch, int) and fetch % 2 == 0,
                f"{name}: vendor fetch length is not even")
        require(fetch == 2 * ((body + 4 + 2 - 1) // 2),
                f"{name}: vendor fetch length does not match regcfg_amount")
        require(pad in (0, 1) and fetch == body + 4 + pad,
                f"{name}: parity pad crosswalk mismatch")
        require(rocket_count == fetch,
                f"{name}: vendor/rocket count crosswalk mismatch")
        require(all(count == rocket_count for _offset, count in ranges),
                f"{name}: job task count differs from manifest crosswalk")
        require(regcmd_words == max(offset + count for offset, count in ranges),
                f"{name}: regcmd.bin length differs from the last task end")

        patches = job.get("patches", [])
        require(isinstance(patches, list), f"{name}: patches not a list")
        patch_by_index: dict[int, dict] = {}
        for patch in patches:
            idx = patch.get("regcmd_index")
            bname = patch.get("buffer")
            kind = patch.get("kind")
            require(isinstance(idx, int) and 0 <= idx < regcmd_words,
                    f"{name}: patch index {idx} out of range")
            require(bname in names, f"{name}: patch buffer {bname!r} missing")
            require(kind in ALLOWED_KINDS, f"{name}: patch kind {kind!r}")
            require(idx not in patch_by_index,
                    f"{name}: duplicate patch index {idx}")
            patch_by_index[idx] = patch

        # Every real DMA-address field must be patched, and no patch may point
        # at a non-address field.  Simulate the value32 relocation with a
        # fresh set of dummy addresses to check bit placement.
        dummy_bases = {b: 0x40000000 + i * 0x10000 for i, b in enumerate(sorted(names))}
        relocated = list(words)
        for idx, word in enumerate(words):
            target = (word >> 48) & 0xFFFF
            offset = word & 0xFFFF
            value = (word >> 16) & 0xFFFFFFFF
            key = (target, offset)
            if key in ADDRESS_FIELDS:
                require(idx in patch_by_index,
                        f"{name}: unpatched address field {key} at {idx}")
                if idx in patch_by_index:
                    patch = patch_by_index[idx]
                    require(patch["buffer"] == ADDRESS_FIELDS[key],
                            f"{name}: patch {idx} buffer {patch['buffer']} != {ADDRESS_FIELDS[key]}")
                    require(value == SYMBOLIC[ADDRESS_FIELDS[key]],
                            f"{name}: address field {idx} value 0x{value:08x} "
                            f"!= symbolic 0x{SYMBOLIC[ADDRESS_FIELDS[key]]:08x}")
                    dummy = dummy_bases[patch["buffer"]]
                    relocated[idx] = (word & ~(0xFFFFFFFF << 16)) | (dummy << 16)
            else:
                require(idx not in patch_by_index,
                        f"{name}: patch {idx} on non-address field {key}")
        for idx, patch in patch_by_index.items():
            target = (relocated[idx] >> 48) & 0xFFFF
            offset = relocated[idx] & 0xFFFF
            value = (relocated[idx] >> 16) & 0xFFFFFFFF
            require((target, offset) in ADDRESS_FIELDS,
                    f"{name}: relocated patch {idx} lost target/offset")
            require(value == dummy_bases[patch["buffer"]],
                    f"{name}: relocated patch {idx} value mismatch")

        oracle = case.get("oracle", {})
        dtype = oracle.get("dtype") or case.get("expected_oracle", {}).get("dtype")
        shape = oracle.get("shape") or case.get("expected_oracle", {}).get("shape")
        require(dtype in DTYPE_BYTES, f"{name}: bad oracle dtype {dtype!r}")
        require(isinstance(shape, list) and all(isinstance(v, int) and v > 0 for v in shape),
                f"{name}: bad oracle shape")
        if dtype in DTYPE_BYTES and isinstance(shape, list):
            expected_bytes = DTYPE_BYTES[dtype]
            for dim in shape:
                expected_bytes *= dim
            require(expected_path.stat().st_size == expected_bytes,
                    f"{name}: expected.bin size {expected_path.stat().st_size} != {expected_bytes}")
        require(oracle.get("kind") in {"host-numpy", "none"},
                f"{name}: oracle must be labelled host-numpy or none")

        surface = oracle.get("expected_surface_file")
        if surface:
            surface_path = case_dir / surface
            require(surface_path.is_file(), f"{name}: missing {surface}")
            if surface_path.is_file():
                require(sha256(surface_path) == hashes.get(surface),
                        f"{name}: {surface} hash mismatch")
                output_buf = next((b for b in buffers if b.get("direction") == "out"), None)
                require(output_buf is not None, f"{name}: no output buffer")
                if output_buf:
                    require(surface_path.stat().st_size == output_buf["size"],
                            f"{name}: {surface} size != output buffer size")

    require(manifest.get("readiness", {}).get("READY") == ready,
            f"manifest READY count {manifest.get('readiness', {}).get('READY')} != {ready}")
    require(manifest.get("readiness", {}).get("BLOCKED") == blocked,
            f"manifest BLOCKED count {manifest.get('readiness', {}).get('BLOCKED')} != {blocked}")
    require(manifest.get("readiness", {}).get("total") == len(cases),
            "manifest total count mismatch")

    if ERRORS:
        print(f"FAIL: {len(ERRORS)} error(s)")
        for error in ERRORS:
            print(f"  - {error}")
        return 1
    print(f"PASS: READY={ready} BLOCKED={blocked} cases={len(cases)} "
          f"max_regcmd_words={max_words} rocket_max={ROCKET_MAX_REGCMDS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
