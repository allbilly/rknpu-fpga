#!/usr/bin/env python3
"""Local, device-free validator for the conv-fp16 capture bundles.

Checks the bundle schema, command stream bounds, terminal tails, address
placeholder patches, buffer sizes, output layout sizes, oracle file sizes and
manifest hashes.  It never opens a device and never treats an oracle as a
capture.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

FAMILY_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = FAMILY_DIR / "manifest.json"

ADDR_REGS = {
    0x1070: ("input", 0x0201),   # CNA_FEATURE_DATA_ADDR
    0x1110: ("weight", 0x0201),  # CNA_DCOMP_ADDR0
    0x4020: ("output", 0x1001),  # DPU DST_BASE_ADDR
}

TERMINAL_TAIL = [
    (0x0101, 0x00000000, 0x0010),  # PC_REG.PC_BASE_ADDRESS
    (0x0101, 0x00000000, 0x0014),  # PC_REG.PC_REGISTER_AMOUNTS
    (0x0041, 0x00000000, 0x0000),  # VERSION
    (0x0081, 0x0000000D, 0x0008),  # PC.OPERATION_ENABLE = (6 << 1) | 1
]

TARGETS = {0x0041, 0x0081, 0x0101, 0x0201, 0x0801, 0x1001, 0x2001}
C2 = 8


class Problems:
    def __init__(self):
        self.items = []

    def add(self, case, message):
        self.items.append((case, message))

    def fail(self, case, message):
        self.add(case, message)

    def check(self, condition, case, message):
        if not condition:
            self.add(case, message)
        return bool(condition)

    def __len__(self):
        return len(self.items)


def align_up(value, align):
    value = int(value)
    align = int(align)
    return ((value + align - 1) // align) * align


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def word_parts(word):
    return (word >> 48) & 0xFFFF, (word >> 16) & 0xFFFFFFFF, word & 0xFFFF


def load_words(path: Path):
    data = path.read_bytes()
    if len(data) % 8:
        raise ValueError(f"{path} is {len(data)} bytes, not a multiple of 8")
    return list(struct.unpack("<%dQ" % (len(data) // 8), data))


def validate_ready(case, problems):
    name = case["case"]
    case_dir = FAMILY_DIR / "cases" / name
    if not problems.check(case_dir.is_dir(), name, f"missing case directory {case_dir}"):
        return

    job_path = case_dir / "job.json"
    regcmd_path = case_dir / "regcmd.bin"
    if not problems.check(job_path.is_file(), name, "missing job.json"):
        return
    if not problems.check(regcmd_path.is_file(), name, "missing regcmd.bin"):
        return

    try:
        job = json.loads(job_path.read_text())
    except Exception as exc:
        problems.fail(name, f"job.json parse error: {exc}")
        return

    problems.check(job.get("case") == name, name, f"job case {job.get('case')!r} != {name!r}")
    source = job.get("source_example")
    problems.check(isinstance(source, str) and Path(source).is_file(), name, f"source_example missing: {source!r}")
    problems.check(isinstance(job.get("timeout_ns"), int) and job["timeout_ns"] > 0, name, "timeout_ns must be a positive integer")

    try:
        words = load_words(regcmd_path)
    except Exception as exc:
        problems.fail(name, f"regcmd parse error: {exc}")
        return
    total = len(words)

    tasks = job.get("tasks")
    if not problems.check(isinstance(tasks, list) and tasks, name, "tasks must be a non-empty list"):
        return

    ranges = []
    for index, task in enumerate(tasks):
        if not problems.check(isinstance(task, dict), name, f"task {index} is not an object"):
            continue
        off = task.get("regcmd_offset_words")
        count = task.get("regcmd_words")
        if not problems.check(isinstance(off, int) and off >= 0, name, f"task {index} offset invalid: {off!r}"):
            continue
        if not problems.check(isinstance(count, int) and count > 4, name, f"task {index} count invalid: {count!r}"):
            continue
        if not problems.check(off + count <= total, name, f"task {index} range [{off},{off+count}) exceeds {total} qwords"):
            continue
        ranges.append((off, count, index))
        body = words[off : off + count - 4]
        tail = words[off + count - 4 : off + count]
        tail_parts = [word_parts(w) for w in tail]
        problems.check(tail_parts == TERMINAL_TAIL, name, f"task {index} terminal tail mismatch: {[hex(w) for w in tail]}")
        problems.check(len(body) > 0, name, f"task {index} empty body")
        addr_hits = []
        for local, word in enumerate(body):
            target, value, reg = word_parts(word)
            if reg in ADDR_REGS:
                role, expected_target = ADDR_REGS[reg]
                addr_hits.append((local, reg, target, value, role))
                problems.check(target == expected_target, name, f"task {index} reg 0x{reg:04x} target 0x{target:04x} != 0x{expected_target:04x}")
                problems.check(value == 0, name, f"task {index} reg 0x{reg:04x} value 0x{value:08x} is not a zero placeholder")
        hits_by_reg = {hit[1] for hit in addr_hits}
        problems.check(hits_by_reg == set(ADDR_REGS), name, f"task {index} address registers {sorted(hex(r) for r in hits_by_reg)} != expected {sorted(hex(r) for r in ADDR_REGS)}")
        problems.check(len(addr_hits) == 3, name, f"task {index} has {len(addr_hits)} address registers, expected 3")
        for word in body + tail:
            target = (word >> 48) & 0xFFFF
            problems.check(target in TARGETS, name, f"task {index} unknown target 0x{target:04x}")

    ranges.sort()
    for i, (off, count, index) in enumerate(ranges):
        if i == 0:
            problems.check(off == 0, name, f"first task offset is {off}, expected 0")
        else:
            prev_off, prev_count, prev_index = ranges[i - 1]
            problems.check(off >= prev_off + prev_count, name, f"task {index} overlaps task {prev_index}")
    if ranges:
        last_off, last_count, _ = ranges[-1]
        problems.check(last_off + last_count <= total, name, "last task exceeds regcmd")

    # The RK3588 Rocket v6.18 board path executed only task 0 of a two-task
    # job. READY bundles must therefore be exactly one task at offset 0.
    problems.check(len(ranges) == 1, name, f"READY case has {len(ranges)} tasks; Rocket multi-task jobs are unsupported (require exactly one task)")
    if len(ranges) == 1:
        problems.check(ranges[0][0] == 0, name, "READY task must start at regcmd_offset_words=0")

    buffers = job.get("buffers")
    if not problems.check(isinstance(buffers, list) and buffers, name, "buffers must be a non-empty list"):
        return
    by_name = {}
    for index, buffer in enumerate(buffers):
        if not problems.check(isinstance(buffer, dict), name, f"buffer {index} is not an object"):
            continue
        bname = buffer.get("name")
        if not problems.check(isinstance(bname, str) and bname, name, f"buffer {index} name invalid"):
            continue
        problems.check(bname not in by_name, name, f"duplicate buffer name {bname!r}")
        by_name[bname] = buffer
        size = buffer.get("size")
        problems.check(isinstance(size, int) and size > 0, name, f"buffer {bname} size invalid: {size!r}")
        direction = buffer.get("direction")
        problems.check(direction in ("in", "out", "inout"), name, f"buffer {bname} direction invalid: {direction!r}")
        input_name = buffer.get("input")
        output_name = buffer.get("output")
        if direction in ("in", "inout"):
            if problems.check(isinstance(input_name, str) and input_name, name, f"buffer {bname} missing input filename"):
                input_path = case_dir / input_name
                if problems.check(input_path.is_file(), name, f"buffer {bname} input file missing: {input_name}"):
                    actual = input_path.stat().st_size
                    problems.check(actual == size, name, f"buffer {bname} input size {actual} != declared {size}")
                    problems.check(size % 16 == 0, name, f"buffer {bname} input size {size} is not 16-byte aligned")
        if direction in ("out", "inout"):
            problems.check(isinstance(output_name, str) and output_name, name, f"buffer {bname} missing output filename")
            if isinstance(output_name, str):
                problems.check(not output_name.startswith("expected"), name, f"buffer {bname} output name collides with oracle: {output_name}")
                problems.check(output_name not in ("job.json", "regcmd.bin", "provenance.json"), name, f"buffer {bname} output name collides with bundle metadata: {output_name}")

    patches = job.get("patches")
    if not problems.check(isinstance(patches, list), name, "patches must be a list"):
        return
    patched = {}
    for index, patch in enumerate(patches):
        if not problems.check(isinstance(patch, dict), name, f"patch {index} is not an object"):
            continue
        ridx = patch.get("regcmd_index")
        bname = patch.get("buffer")
        kind = patch.get("kind")
        if not problems.check(isinstance(ridx, int) and 0 <= ridx < total, name, f"patch {index} index invalid: {ridx!r}"):
            continue
        problems.check(ridx not in patched, name, f"duplicate patch index {ridx}")
        patched[ridx] = (bname, kind)
        problems.check(bname in by_name, name, f"patch {ridx} references unknown buffer {bname!r}")
        problems.check(kind == "value32", name, f"patch {ridx} kind {kind!r} != value32")
        target, value, reg = word_parts(words[ridx])
        problems.check(reg in ADDR_REGS, name, f"patch {ridx} targets non-address reg 0x{reg:04x}")
        problems.check(value == 0, name, f"patch {ridx} pre-patch value 0x{value:08x} is not zero")
        if reg in ADDR_REGS:
            role, expected_target = ADDR_REGS[reg]
            problems.check(target == expected_target, name, f"patch {ridx} target 0x{target:04x} != 0x{expected_target:04x}")

    # Every address placeholder inside every task body must be patched.
    for off, count, index in ranges:
        for local in range(count - 4):
            ridx = off + local
            reg = words[ridx] & 0xFFFF
            if reg in ADDR_REGS:
                problems.check(ridx in patched, name, f"task {index} address reg 0x{reg:04x} at qword {ridx} has no patch")

    expected_patch_count = 3 * len(ranges)
    problems.check(len(patches) == expected_patch_count, name, f"patch count {len(patches)} != {expected_patch_count}")
    if "patch_count" in case:
        problems.check(case["patch_count"] == len(patches), name, f"manifest patch_count {case['patch_count']} != {len(patches)}")

    # Output layout and oracle sizes.
    layouts = case.get("output_layouts")
    if not problems.check(isinstance(layouts, list) and layouts, name, "manifest output_layouts missing"):
        layouts = []
    layout_by_buffer = {layout.get("buffer"): layout for layout in layouts}
    for bname, buffer in by_name.items():
        if buffer.get("direction") not in ("out", "inout"):
            continue
        layout = layout_by_buffer.get(bname)
        if not problems.check(isinstance(layout, dict), name, f"buffer {bname} has no manifest output_layout"):
            continue
        out_c = layout.get("out_c")
        out_h = layout.get("out_h")
        out_w = layout.get("out_w")
        ws = layout.get("out_width_stride")
        align_out_c = layout.get("align_out_c")
        c1 = layout.get("c1")
        c2 = layout.get("c2")
        raw_bytes = layout.get("raw_bytes")
        if not problems.check(all(isinstance(v, int) and v > 0 for v in (out_c, out_h, out_w, ws, align_out_c, c1, c2, raw_bytes)), name, f"buffer {bname} output_layout has invalid integers"):
            continue
        problems.check(c2 == C2, name, f"buffer {bname} c2 {c2} != {C2}")
        problems.check(align_out_c == max(32, align_up(out_c, 16)), name, f"buffer {bname} align_out_c {align_out_c} mismatch")
        problems.check(c1 == align_up(align_out_c, c2) // c2, name, f"buffer {bname} c1 {c1} mismatch")
        problems.check(raw_bytes == c1 * ws * c2 * 2, name, f"buffer {bname} raw_bytes {raw_bytes} != {c1 * ws * c2 * 2}")
        problems.check(buffer.get("size") == raw_bytes, name, f"buffer {bname} size {buffer.get('size')} != raw_bytes {raw_bytes}")
        expected_name = layout.get("expected")
        if problems.check(isinstance(expected_name, str) and expected_name, name, f"buffer {bname} missing expected file name"):
            expected_path = case_dir / expected_name
            if problems.check(expected_path.is_file(), name, f"buffer {bname} expected file missing: {expected_name}"):
                expected_size = out_c * out_h * out_w * 2
                problems.check(expected_path.stat().st_size == expected_size, name, f"buffer {bname} expected size {expected_path.stat().st_size} != {expected_size}")

    if len(layouts) > 1:
        combined = case_dir / "expected_combined.bin"
        if problems.check(combined.is_file(), name, "multi-task case missing expected_combined.bin"):
            shape = case.get("shape", {})
            expected_size = int(shape.get("out_c", 0)) * int(shape.get("out_h", 0)) * int(shape.get("out_w", 0)) * 2
            problems.check(combined.stat().st_size == expected_size, name, f"combined oracle size {combined.stat().st_size} != {expected_size}")

    # Manifest hashes.
    files = case.get("files")
    if not problems.check(isinstance(files, dict) and files, name, "manifest files map missing"):
        return
    worker_outputs = {
        buffer.get("output")
        for buffer in by_name.values()
        if isinstance(buffer.get("output"), str)
    }
    for rel, meta in files.items():
        path = case_dir / rel
        if not problems.check(path.is_file(), name, f"manifest file missing: {rel}"):
            continue
        problems.check(isinstance(meta, dict), name, f"manifest file entry invalid: {rel}")
        if isinstance(meta, dict):
            problems.check(path.stat().st_size == meta.get("size"), name, f"size mismatch for {rel}")
            problems.check(sha256_file(path) == meta.get("sha256"), name, f"sha256 mismatch for {rel}")
    for path in case_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(case_dir).as_posix()
        if rel in files or rel in worker_outputs:
            continue
        problems.fail(name, f"unlisted file in case directory: {rel}")


def validate_blocked(case, problems):
    name = case["case"]
    source = case.get("source_example")
    problems.check(isinstance(source, str) and Path(source).is_file(), name, f"source_example missing: {source!r}")
    problems.check(isinstance(case.get("source_lines"), list) and case["source_lines"], name, "source_lines must be a non-empty list")
    problems.check(isinstance(case.get("reason"), str) and case["reason"].strip(), name, "blocked reason must be non-empty")

    case_dir = FAMILY_DIR / "cases" / name
    if not case_dir.exists():
        return
    # A blocked case may retain its generated bundle as evidence.  In that
    # case the manifest hashes must still describe the preserved bytes.
    problems.check(case.get("evidence_preserved") is True, name, "blocked case has a directory but evidence_preserved is not true")
    files = case.get("files")
    if not problems.check(isinstance(files, dict) and files, name, "blocked evidence case has no manifest files map"):
        return
    for rel, meta in files.items():
        path = case_dir / rel
        if not problems.check(path.is_file(), name, f"preserved evidence file missing: {rel}"):
            continue
        problems.check(isinstance(meta, dict), name, f"preserved evidence entry invalid: {rel}")
        if isinstance(meta, dict):
            problems.check(path.stat().st_size == meta.get("size"), name, f"preserved evidence size mismatch for {rel}")
            problems.check(sha256_file(path) == meta.get("sha256"), name, f"preserved evidence sha256 mismatch for {rel}")
    for path in case_dir.rglob("*"):
        if path.is_file() and path.relative_to(case_dir).as_posix() not in files:
            problems.fail(name, f"unlisted file in preserved evidence directory: {path.relative_to(case_dir).as_posix()}")


def main():
    if not MANIFEST_PATH.is_file():
        print(f"FAIL: missing {MANIFEST_PATH}")
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text())
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        print("FAIL: manifest.cases is not a list")
        return 1

    problems = Problems()
    ready = 0
    blocked = 0
    for case in cases:
        status = case.get("status")
        if status == "READY":
            ready += 1
            validate_ready(case, problems)
        elif status == "BLOCKED":
            blocked += 1
            validate_blocked(case, problems)
        else:
            problems.fail(case.get("case", "<unknown>"), f"invalid status {status!r}")

    counts = manifest.get("counts", {})
    problems.check(counts.get("ready") == ready, "manifest", f"counts.ready {counts.get('ready')} != {ready}")
    problems.check(counts.get("blocked") == blocked, "manifest", f"counts.blocked {counts.get('blocked')} != {blocked}")
    problems.check(counts.get("total") == len(cases), "manifest", f"counts.total {counts.get('total')} != {len(cases)}")

    for name, meta in manifest.get("preparation_tools", {}).items():
        path = FAMILY_DIR / "tools" / name
        if not problems.check(path.is_file(), "manifest", f"preparation tool missing: {name}"):
            continue
        problems.check(isinstance(meta, dict), "manifest", f"preparation tool entry invalid: {name}")
        if isinstance(meta, dict):
            problems.check(path.stat().st_size == meta.get("size"), "manifest", f"size mismatch for tool {name}")
            problems.check(sha256_file(path) == meta.get("sha256"), "manifest", f"sha256 mismatch for tool {name}")

    print(f"manifest: {MANIFEST_PATH}")
    print(f"cases: {ready} READY, {blocked} BLOCKED, {len(cases)} total")
    if problems:
        print(f"FAIL: {len(problems)} problem(s)")
        for case, message in problems.items:
            print(f"  [{case}] {message}")
        return 1
    print("PASS: schema, sizes, task ranges, tails, patches, layouts and hashes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
