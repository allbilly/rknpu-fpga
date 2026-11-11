#!/usr/bin/env python3
"""Local structural validator for the FDIV operand-class bundles.

This parser checks the CAPTURE_FORMAT.md JSON shape, the exact 22-QWORD
register template, buffer sizes (all exactly 64 bytes), patch indices and
placeholder bits, plan bounds, bundle hashes, and the 16x16 row-major pair
ordering recorded in manifest.json.  It never opens /dev/accel*, never uses
ssh/scp, and never submits anything.

It does not validate SystemVerilog, an FPGA image, RK3588 silicon or any
numerical result.  No output.bin or expected.bin is created or required.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "cases"
MANIFEST_PATH = ROOT / "manifest.json"
VALIDATION_DIR = ROOT / "validation"
BUFFER_BYTES = 64
LANES = 32
REGS = 22

TARGET_DPU = 0x1001
TARGET_RDMA = 0x2001
TARGET_PC_REG = 0x0101
TARGET_VERSION = 0x0041
TARGET_PC = 0x0081

CLASSES = [
    ("zero_p", 0x0000),
    ("zero_n", 0x8000),
    ("inf_p", 0x7C00),
    ("inf_n", 0xFC00),
    ("qnan", 0x7E00),
    ("snan", 0x7C01),
    ("sub_min", 0x0001),
    ("sub_max", 0x03FF),
    ("norm_min", 0x0400),
    ("fin_max", 0x7BFF),
    ("one_p", 0x3C00),
    ("one_n", 0xBC00),
    ("half_p", 0x3800),
    ("half_n", 0xB800),
    ("two_p", 0x4000),
    ("two_n", 0xC000),
]

# (index, target, offset, value, field, role); value 0 with index 14/15/16 is
# still an address placeholder, not a fixed zero write.
TEMPLATE = [
    (0, TARGET_DPU, 0x4004, 0x0000000E, "dpu_s_pointer", "command"),
    (1, TARGET_DPU, 0x400C, 0x000001E5, "dpu_feature_mode_cfg", "command"),
    (2, TARGET_DPU, 0x4010, 0x48000002, "dpu_data_format", "command"),
    (3, TARGET_DPU, 0x4030, 0x00000003, "dpu_data_cube_width", "command"),
    (4, TARGET_DPU, 0x4034, 0x00000000, "dpu_data_cube_height", "padding"),
    (5, TARGET_DPU, 0x4038, 0x00000000, "dpu_data_cube_notch", "padding"),
    (6, TARGET_DPU, 0x403C, 0x00070007, "dpu_data_cube_channel", "command"),
    (7, TARGET_DPU, 0x4070, 0x108303C0, "dpu_ew_cfg", "command"),
    (8, TARGET_DPU, 0x4084, 0x00000001, "dpu_out_cvt_scale", "command"),
    (9, TARGET_RDMA, 0x5004, 0x0000000E, "rdma_s_pointer", "command"),
    (10, TARGET_RDMA, 0x500C, 0x00000003, "rdma_data_cube_width", "command"),
    (11, TARGET_RDMA, 0x5010, 0x00000000, "rdma_data_cube_height", "command"),
    (12, TARGET_RDMA, 0x5014, 0x00000007, "rdma_data_cube_channel", "command"),
    (13, TARGET_RDMA, 0x5034, 0x40000008, "rdma_erdma_cfg", "command"),
    (14, TARGET_DPU, 0x4020, 0x00000000, "dst_base_addr", "command"),
    (15, TARGET_RDMA, 0x5018, 0x00000000, "src_a_base_addr", "command"),
    (16, TARGET_RDMA, 0x5038, 0x00000000, "src_b_base_addr", "command"),
    (17, TARGET_RDMA, 0x5044, 0x00017841, "rdma_feature_mode_cfg", "command"),
    (18, TARGET_PC_REG, 0x0010, 0x00000000, "pc_base_address", "padding"),
    (19, TARGET_PC_REG, 0x0014, 0x00000000, "pc_register_amounts", "padding"),
    (20, TARGET_VERSION, 0x0000, 0x00000000, "version_marker", "padding"),
    (21, TARGET_PC, 0x0008, 0x00000018, "pc_operation_enable", "command"),
]
PLACEHOLDERS = (14, 15, 16)
PATCHES = [
    {"regcmd_index": 14, "buffer": "out", "kind": "value32"},
    {"regcmd_index": 15, "buffer": "a", "kind": "value32"},
    {"regcmd_index": 16, "buffer": "b", "kind": "value32"},
]
JOB_KEYS = {"case", "source_example", "description", "timeout_ns", "tasks", "buffers", "patches"}
CASE_KEYS = {
    "case", "status", "op", "kind", "rows", "a_classes", "pair_range", "pair_count",
    "lanes", "width", "ew_cfg", "out_convert", "rdma_mode", "description",
    "source_example", "source_lines", "oracle", "output", "patches", "bundle", "pairs",
}
BUNDLE_KEYS = {"job.json", "regcmd.bin", "input-a.bin", "input-b.bin"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def emit(target: int, offset: int, value: int) -> int:
    return (target << 48) | ((int(value) & 0xFFFFFFFF) << 16) | offset


EXPECTED_WORDS = [emit(t, o, v) for _i, t, o, v, _f, _r in TEMPLATE]


def case_names() -> list[str]:
    return [f"fdiv_class_rows_{2 * c:02d}_{2 * c + 1:02d}" for c in range(8)]


def expected_pairs(case_index: int) -> list[dict]:
    pairs = []
    for lane in range(LANES):
        a_index = 2 * case_index + lane // 16
        b_index = lane % 16
        pairs.append(
            {
                "lane": lane,
                "pair_index": 16 * a_index + b_index,
                "a": {
                    "class_index": a_index,
                    "name": CLASSES[a_index][0],
                    "bits": f"0x{CLASSES[a_index][1]:04x}",
                },
                "b": {
                    "class_index": b_index,
                    "name": CLASSES[b_index][0],
                    "bits": f"0x{CLASSES[b_index][1]:04x}",
                },
            }
        )
    return pairs


def main() -> int:
    errors: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> bool:
        nonlocal checks
        checks += 1
        if not condition:
            errors.append(message)
        return bool(condition)

    def bad(case: str, message: str) -> None:
        errors.append(f"{case}: {message}")

    if not MANIFEST_PATH.is_file():
        print(f"FAIL: missing {MANIFEST_PATH}", file=sys.stderr)
        return 1
    manifest_bytes = MANIFEST_PATH.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except Exception as exc:
        print(f"FAIL: manifest.json is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(manifest, dict):
        print("FAIL: manifest.json is not an object", file=sys.stderr)
        return 1

    # ---- family-level shape and grid ------------------------------------
    check(manifest.get("family") == "fdiv-systematic", "family is not fdiv-systematic")
    check(
        manifest.get("schema") == "rk3588-example-captures/v1",
        "schema is not rk3588-example-captures/v1",
    )
    check(manifest.get("prepared_device_free") is True, "prepared_device_free is not true")
    check("no ssh/scp" in str(manifest.get("device_access", "")), "device_access does not disclaim ssh/scp")
    check(
        str(manifest.get("board_execution", "")).startswith("PENDING"),
        "board_execution does not say PENDING",
    )

    classes = manifest.get("operand_classes")
    check(isinstance(classes, list) and len(classes) == 16, "operand_classes must have 16 entries")
    if isinstance(classes, list) and len(classes) == 16:
        for index, (name, bits) in enumerate(CLASSES):
            entry = classes[index]
            check(isinstance(entry, dict), f"class {index} is not an object")
            if isinstance(entry, dict):
                check(entry.get("index") == index, f"class {index} index mismatch")
                check(entry.get("name") == name, f"class {index} name {entry.get('name')!r} != {name}")
                check(entry.get("bits") == f"0x{bits:04x}", f"class {index} bits {entry.get('bits')!r} != 0x{bits:04x}")

    grid = manifest.get("grid")
    check(isinstance(grid, dict), "grid is missing or not an object")
    if isinstance(grid, dict):
        check(grid.get("a_classes") == 16, "grid.a_classes != 16")
        check(grid.get("b_classes") == 16, "grid.b_classes != 16")
        check(grid.get("total_pairs") == 256, "grid.total_pairs != 256")
        check(grid.get("cases") == 8, "grid.cases != 8")
        check(grid.get("lanes_per_case") == 32, "grid.lanes_per_case != 32")
        check("row-major" in str(grid.get("order", "")).lower(), "grid.order is not row-major")

    template = manifest.get("regcmd_template")
    check(isinstance(template, list) and len(template) == REGS, "regcmd_template must have 22 entries")
    if isinstance(template, list) and len(template) == REGS:
        for index, (target, offset, value, field, role) in enumerate(
            [(t, o, v, f, r) for _i, t, o, v, f, r in TEMPLATE]
        ):
            entry = template[index]
            check(isinstance(entry, dict), f"regcmd_template[{index}] is not an object")
            if not isinstance(entry, dict):
                continue
            check(entry.get("index") == index, f"regcmd_template[{index}].index mismatch")
            check(entry.get("target") == f"0x{target:04x}", f"regcmd_template[{index}].target mismatch")
            check(entry.get("offset") == f"0x{offset:04x}", f"regcmd_template[{index}].offset mismatch")
            check(entry.get("value") == f"0x{value:08x}", f"regcmd_template[{index}].value mismatch")
            check(entry.get("field") == field, f"regcmd_template[{index}].field mismatch")
            check(entry.get("role") == role, f"regcmd_template[{index}].role mismatch")
            check(entry.get("placeholder") == (index in PLACEHOLDERS),
                  f"regcmd_template[{index}].placeholder mismatch")
        check(sum(1 for e in template if e.get("role") == "command") == 17,
              "regcmd_template does not have 17 command entries")
        check(sum(1 for e in template if e.get("role") == "padding") == 5,
              "regcmd_template does not have 5 padding entries")

    cases = manifest.get("cases")
    names = case_names()
    check(isinstance(cases, list) and len(cases) == 8, "manifest must list exactly 8 cases")
    if not isinstance(cases, list) or len(cases) != 8:
        errors.append("cannot continue case checks without 8 manifest cases")
        cases = []

    pair_indices: list[int] = []

    # ---- per-case bundle -------------------------------------------------
    for case_index, name in enumerate(names):
        if case_index >= len(cases):
            break
        entry = cases[case_index]
        if not isinstance(entry, dict):
            bad(name, "manifest case is not an object")
            continue
        missing = CASE_KEYS - set(entry)
        extra = set(entry) - CASE_KEYS
        if missing:
            bad(name, f"manifest case missing keys {sorted(missing)}")
        if extra:
            bad(name, f"manifest case unknown keys {sorted(extra)}")
        check(entry.get("case") == name, f"{name}: manifest case name mismatch")
        check(entry.get("status") == "READY", f"{name}: status is not READY")
        check(entry.get("op") == "FDIV", f"{name}: op is not FDIV")
        check(entry.get("kind") == "operand-class-truth-table", f"{name}: kind mismatch")
        check(entry.get("rows") == [2 * case_index, 2 * case_index + 1], f"{name}: rows mismatch")
        check(entry.get("a_classes") == [CLASSES[2 * case_index][0], CLASSES[2 * case_index + 1][0]],
              f"{name}: a_classes mismatch")
        check(entry.get("pair_range") == [32 * case_index, 32 * case_index + 31],
              f"{name}: pair_range mismatch")
        check(entry.get("pair_count") == 32, f"{name}: pair_count != 32")
        check(entry.get("lanes") == 32, f"{name}: lanes != 32")
        check(entry.get("width") == 3, f"{name}: width != 3")
        check(entry.get("ew_cfg") == "0x108303c0", f"{name}: ew_cfg mismatch")
        check(entry.get("out_convert") == "0x00000001", f"{name}: out_convert mismatch")
        check(entry.get("rdma_mode") == "0x00017841", f"{name}: rdma_mode mismatch")
        check(entry.get("oracle") == "none", f"{name}: oracle is not none")
        check(isinstance(entry.get("description"), str) and entry["description"], f"{name}: description missing")
        check(isinstance(entry.get("source_lines"), list) and entry["source_lines"], f"{name}: source_lines missing")

        expected_output = {
            "name": "out",
            "size": 64,
            "direction": "out",
            "output": "output.bin",
        }
        check(entry.get("output") == expected_output, f"{name}: output declaration mismatch")
        check(entry.get("patches") == [
            {**patch, "target": f"0x{target:04x}", "offset": f"0x{offset:04x}", "field": field}
            for patch, (target, offset, field) in zip(
                PATCHES,
                [(TARGET_DPU, 0x4020, "dst_base_addr"),
                 (TARGET_RDMA, 0x5018, "src_a_base_addr"),
                 (TARGET_RDMA, 0x5038, "src_b_base_addr")],
            )
        ], f"{name}: manifest patches mismatch")

        expected_pair_list = expected_pairs(case_index)
        check(entry.get("pairs") == expected_pair_list, f"{name}: pairs list/order mismatch")
        if isinstance(entry.get("pairs"), list):
            for pair in entry["pairs"]:
                if isinstance(pair, dict) and isinstance(pair.get("pair_index"), int):
                    pair_indices.append(pair["pair_index"])

        case_dir = CASES_DIR / name
        if not check(case_dir.is_dir(), f"{name}: case directory missing"):
            continue
        actual_files = {p.name for p in case_dir.iterdir() if p.is_file()}
        check(actual_files == BUNDLE_KEYS, f"{name}: files {sorted(actual_files)} != {sorted(BUNDLE_KEYS)}")
        if actual_files != BUNDLE_KEYS:
            continue

        files = {file_name: (case_dir / file_name).read_bytes() for file_name in BUNDLE_KEYS}
        for file_name in BUNDLE_KEYS:
            recorded = entry.get("bundle", {}).get(file_name)
            check(isinstance(recorded, dict), f"{name}: bundle entry {file_name} missing")
            if isinstance(recorded, dict):
                check(recorded.get("bytes") == len(files[file_name]),
                      f"{name}: {file_name} recorded size mismatch")
                check(recorded.get("sha256") == sha256_bytes(files[file_name]),
                      f"{name}: {file_name} sha256 mismatch")

        # regcmd.bin
        regcmd = files["regcmd.bin"]
        check(len(regcmd) == REGS * 8, f"{name}: regcmd.bin is {len(regcmd)} bytes, expected 176")
        if len(regcmd) != REGS * 8:
            continue
        words = list(struct.unpack("<" + "Q" * REGS, regcmd))
        for index, (target, offset, value, field, role) in enumerate(
            [(t, o, v, f, r) for _i, t, o, v, f, r in TEMPLATE]
        ):
            check(words[index] == EXPECTED_WORDS[index],
                  f"{name}: QWORD {index} ({field}/{role}) value mismatch")
            decoded_target = words[index] >> 48
            decoded_offset = words[index] & 0xFFFF
            decoded_value = (words[index] >> 16) & 0xFFFFFFFF
            check(decoded_target == target, f"{name}: QWORD {index} target mismatch")
            check(decoded_offset == offset, f"{name}: QWORD {index} offset mismatch")
            check(decoded_value == value, f"{name}: QWORD {index} value mismatch")
        for index in PLACEHOLDERS:
            check((words[index] >> 16) & 0xFFFFFFFF == 0,
                  f"{name}: placeholder QWORD {index} value bits are not zero")

        # job.json
        try:
            job = json.loads(files["job.json"])
        except Exception as exc:
            bad(name, f"job.json is not valid JSON: {exc}")
            continue
        if not isinstance(job, dict):
            bad(name, "job.json is not an object")
            continue
        check(set(job) == JOB_KEYS, f"{name}: job.json keys {sorted(set(job))} != {sorted(JOB_KEYS)}")
        check(job.get("case") == name, f"{name}: job.json case mismatch")
        check(job.get("source_example") == entry.get("source_example"), f"{name}: job source_example mismatch")
        check(isinstance(job.get("description"), str) and job["description"], f"{name}: job description missing")
        check(isinstance(job.get("timeout_ns"), int) and job["timeout_ns"] > 0,
              f"{name}: job timeout_ns must be a positive integer")

        tasks = job.get("tasks")
        check(isinstance(tasks, list) and len(tasks) == 1, f"{name}: tasks must be a one-element list")
        if isinstance(tasks, list) and len(tasks) == 1 and isinstance(tasks[0], dict):
            task = tasks[0]
            check(set(task) == {"regcmd_offset_words", "regcmd_words"},
                  f"{name}: task keys mismatch")
            check(task.get("regcmd_offset_words") == 0, f"{name}: task offset != 0")
            check(task.get("regcmd_words") == REGS, f"{name}: task words != 22")
            if isinstance(task.get("regcmd_offset_words"), int) and isinstance(task.get("regcmd_words"), int):
                start = task["regcmd_offset_words"]
                count = task["regcmd_words"]
                check(start >= 0 and count > 0 and start + count <= len(words),
                      f"{name}: task range {start}+{count} exceeds {len(words)} QWORDs")
                check(start * 8 + count * 8 <= len(regcmd),
                      f"{name}: task byte range exceeds regcmd.bin")

        buffers = job.get("buffers")
        buffers_by_name: dict[str, dict] = {}
        check(isinstance(buffers, list) and len(buffers) == 3,
              f"{name}: buffers must be a three-element list")
        if isinstance(buffers, list):
            for buffer in buffers:
                if not isinstance(buffer, dict) or not isinstance(buffer.get("name"), str):
                    bad(name, "malformed buffer entry")
                    continue
                buffers_by_name[buffer["name"]] = buffer
                check(buffer.get("size") == BUFFER_BYTES,
                      f"{name}: buffer {buffer.get('name')} size is not 64")
        check(set(buffers_by_name) == {"a", "b", "out"},
              f"{name}: buffer names are not exactly a/b/out")
        if "a" in buffers_by_name:
            check(buffers_by_name["a"].get("direction") == "in", f"{name}: a direction != in")
            check(buffers_by_name["a"].get("input") == "input-a.bin", f"{name}: a input filename mismatch")
        if "b" in buffers_by_name:
            check(buffers_by_name["b"].get("direction") == "in", f"{name}: b direction != in")
            check(buffers_by_name["b"].get("input") == "input-b.bin", f"{name}: b input filename mismatch")
        if "out" in buffers_by_name:
            check(buffers_by_name["out"].get("direction") == "out", f"{name}: out direction != out")
            check(buffers_by_name["out"].get("output") == "output.bin", f"{name}: out filename mismatch")
            check("input" not in buffers_by_name["out"], f"{name}: out must not declare an input")

        patches = job.get("patches")
        check(patches == PATCHES, f"{name}: job patches are not exactly the three value32 patches")
        if isinstance(patches, list):
            for patch in patches:
                if not isinstance(patch, dict):
                    bad(name, "malformed patch entry")
                    continue
                index = patch.get("regcmd_index")
                check(isinstance(index, int) and 0 <= index < REGS,
                      f"{name}: patch index {index!r} out of range")
                if isinstance(index, int) and 0 <= index < REGS:
                    _index, target, offset, _value, field, _role = TEMPLATE[index]
                    check(patch.get("kind") == "value32", f"{name}: patch {index} kind != value32")
                    check(patch.get("buffer") in buffers_by_name, f"{name}: patch {index} buffer missing")
                    check(index in PLACEHOLDERS, f"{name}: patch {index} is not an address field")
                    check((words[index] >> 48) == target,
                          f"{name}: patch {index} target does not match template")
                    check((words[index] & 0xFFFF) == offset,
                          f"{name}: patch {index} offset does not match template")
                    check(((words[index] >> 16) & 0xFFFFFFFF) == 0,
                          f"{name}: patch {index} placeholder is not zero")

        # Inputs: exact raw FP16 bits, exact 32-lane order.
        a_raw = files["input-a.bin"]
        b_raw = files["input-b.bin"]
        check(len(a_raw) == BUFFER_BYTES, f"{name}: input-a.bin is not 64 bytes")
        check(len(b_raw) == BUFFER_BYTES, f"{name}: input-b.bin is not 64 bytes")
        if len(a_raw) == BUFFER_BYTES and len(b_raw) == BUFFER_BYTES:
            a_bits = struct.unpack("<" + "H" * LANES, a_raw)
            b_bits = struct.unpack("<" + "H" * LANES, b_raw)
            for lane in range(LANES):
                a_index = 2 * case_index + lane // 16
                b_index = lane % 16
                check(a_bits[lane] == CLASSES[a_index][1],
                      f"{name}: input-a lane {lane} is 0x{a_bits[lane]:04x}, "
                      f"expected 0x{CLASSES[a_index][1]:04x}")
                check(b_bits[lane] == CLASSES[b_index][1],
                      f"{name}: input-b lane {lane} is 0x{b_bits[lane]:04x}, "
                      f"expected 0x{CLASSES[b_index][1]:04x}")

    # ---- whole-matrix coverage ------------------------------------------
    check(pair_indices == list(range(256)),
          "manifest pair indices are not the complete 0..255 row-major sequence")
    a_counts = [0] * 16
    b_counts = [0] * 16
    for case_index in range(8):
        for lane in range(LANES):
            a_counts[2 * case_index + lane // 16] += 1
            b_counts[lane % 16] += 1
    check(all(count == 16 for count in a_counts), "not every A class appears 16 times")
    check(all(count == 16 for count in b_counts), "not every B class appears 16 times")
    check(not any((CASES_DIR / name / "output.bin").exists() for name in names),
          "a fabricated output.bin exists in a case directory")
    check(not any((CASES_DIR / name / "expected.bin").exists() for name in names),
          "an unexpected expected.bin exists in a case directory")

    status = "PASS" if not errors else "FAIL"
    checked_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {
        "status": status,
        "checked_utc": checked_utc,
        "scope": (
            "device-free local parser: JSON shape, 64-byte buffers, 22-QWORD regcmd, "
            "patch indices/placeholders, task bounds, hashes and 16x16 row-major pair order; "
            "not hardware, not SystemVerilog, not a numerical oracle"
        ),
        "family": "fdiv-systematic",
        "cases": len(names),
        "ready": len(cases) if status == "PASS" else None,
        "blocked": 0,
        "counts": {
            "checks": checks,
            "cases": len(names),
            "input_files": 2 * len(names),
            "input_bytes_each": BUFFER_BYTES,
            "regcmd_words": REGS,
            "regcmd_bytes_each": REGS * 8,
            "patches": 3 * len(names),
            "pairs": 256,
        },
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "errors": errors,
    }
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    (VALIDATION_DIR / "local_validation.json").write_text(json.dumps(result, indent=2) + "\n")

    lines = [
        "FDIV systematic operand-class bundle local validation",
        f"status: {status}",
        f"checked_utc: {checked_utc}",
        "scope: device-free local parser only; not hardware, SystemVerilog or a numerical oracle",
        f"checks: {checks}",
        f"cases: {len(names)} declared, {len(cases)} manifest entries, status READY required",
        f"buffers: {2 * len(names)} input files x {BUFFER_BYTES} bytes, output declared {BUFFER_BYTES} bytes",
        f"regcmd: {len(names)} files x {REGS} QWORDs ({REGS * 8} bytes), exact template matched",
        f"patches: {3 * len(names)} value32 patches, indices 14/15/16, placeholders zero",
        "task bounds: offset 0 + 22 QWORDs within each 22-QWORD stream",
        "pair order: 256/256 unique row-major pairs, A outer, B inner; 32 lanes per case",
        f"manifest_sha256: {result['manifest_sha256']}",
        "",
    ]
    if errors:
        lines.append(f"errors ({len(errors)}):")
        lines.extend(f"  - {error}" for error in errors)
    else:
        lines.append("All local structural checks passed. No output.bin or expected.bin was created.")
    text = "\n".join(lines) + "\n"
    (VALIDATION_DIR / "local_validation.txt").write_text(text)
    print(text, end="")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
