#!/usr/bin/env python3
"""Validate every READY bundle locally, without a device.

Checks the documented job.json/regcmd.bin/buffer/patch schema, file sizes,
manifest hashes, oracle/mask invariants, and that every DMA address write in
the QWORD stream has exactly one value32 patch.

Run::

    /usr/bin/python3 tools/validate.py

Exit status is non-zero on any failure.  Nothing here submits to the NPU.
"""

import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "manifest.json"
CASE_ROOT = ROOT / "cases"
VALIDATION_DIR = ROOT / "validation"
BUFFER_SIZE = 4096

JOB_KEYS = {
    "case", "source_example", "description", "timeout_ns",
    "tasks", "buffers", "patches",
}
TASK_KEYS = {"regcmd_offset_words", "regcmd_words"}
IN_BUFFER_KEYS = {"name", "size", "input", "direction"}
OUT_BUFFER_KEYS = {"name", "size", "direction", "output"}
PATCH_KEYS = {"regcmd_index", "buffer", "kind"}

TARGET_DPU = 0x1001
TARGET_RDMA = 0x2001
TARGET_PC = 0x0081
TARGET_PC_REG = 0x0101
TARGET_VERSION = 0x0041
KNOWN_TARGETS = {TARGET_DPU, TARGET_RDMA, TARGET_PC, TARGET_PC_REG, TARGET_VERSION}

DST_BASE_ADDR = 0x4020
RDMA_SRC_BASE_ADDR = 0x5018
RDMA_EW_BASE_ADDR = 0x5038
ADDRESS_ROLES = {
    "out": (TARGET_DPU, DST_BASE_ADDR),
    "a": (TARGET_RDMA, RDMA_SRC_BASE_ADDR),
    "b": (TARGET_RDMA, RDMA_EW_BASE_ADDR),
}
ADDRESS_REGS = set(ADDRESS_ROLES.values())

CASE_FILES = {
    "job.json", "regcmd.bin", "a.bin", "b.bin",
    "expected.bin", "expected.mask.bin",
}


class ValidationError(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_hash(hashes):
    return hashlib.sha256(
        "".join(f"{name}\0{hashes[name]}\n" for name in sorted(hashes)).encode()
    ).hexdigest()


def validate_ready(entry):
    case = entry["case"]
    case_dir = (ROOT / entry["bundle_dir"]).resolve()
    require(
        case_dir.parent == CASE_ROOT.resolve(),
        f"{case}: bundle_dir escapes cases/",
    )
    require(case_dir.is_dir(), f"{case}: case directory missing")
    present = {path.name for path in case_dir.iterdir() if path.is_file()}
    require(present == CASE_FILES, f"{case}: unexpected file set {sorted(present)}")

    for required in (
        "dtype", "operation", "layout", "shape", "source_example", "source_refs",
        "description", "regcmd_qwords", "oracle", "hashes", "bundle_hash",
        "output_item_size",
    ):
        require(required in entry, f"{case}: manifest entry missing {required}")
    require(entry["source_example"].startswith("/home/fedora/rk3588/examples/"),
            f"{case}: source_example is not the RK example tree")
    require(entry["source_refs"], f"{case}: empty source_refs")

    hashes = entry["hashes"]
    require(set(hashes) == CASE_FILES, f"{case}: hash key set mismatch")
    for name in sorted(CASE_FILES):
        actual = sha256_file(case_dir / name)
        require(actual == hashes[name], f"{case}: hash mismatch for {name}")
    require(bundle_hash(hashes) == entry["bundle_hash"],
            f"{case}: bundle_hash mismatch")

    job = json.loads((case_dir / "job.json").read_text(encoding="utf-8"))
    require(set(job) == JOB_KEYS, f"{case}: job.json key set {sorted(job)}")
    require(job["case"] == case, f"{case}: job case mismatch")
    require(job["source_example"] == entry["source_example"],
            f"{case}: job source_example mismatch")
    require(job["description"] == entry["description"],
            f"{case}: job description mismatch")
    require(isinstance(job["timeout_ns"], int) and job["timeout_ns"] > 0,
            f"{case}: bad timeout_ns")

    regcmd_path = case_dir / "regcmd.bin"
    regcmd = regcmd_path.read_bytes()
    require(len(regcmd) % 8 == 0, f"{case}: regcmd.bin length not a multiple of 8")
    total_qwords = len(regcmd) // 8
    require(total_qwords == entry["regcmd_qwords"],
            f"{case}: manifest regcmd_qwords mismatch")

    tasks = job["tasks"]
    require(isinstance(tasks, list) and len(tasks) == 1,
            f"{case}: exactly one task expected")
    task = tasks[0]
    require(set(task) == TASK_KEYS, f"{case}: task key set {sorted(task)}")
    require(task["regcmd_offset_words"] == 0, f"{case}: task offset must be 0")
    require(task["regcmd_words"] == total_qwords,
            f"{case}: task words != regcmd length")
    require(task["regcmd_offset_words"] + task["regcmd_words"] <= total_qwords,
            f"{case}: task exceeds regcmd.bin")

    buffers = job["buffers"]
    require(isinstance(buffers, list) and len(buffers) == 3,
            f"{case}: three buffers expected")
    by_name = {}
    for buffer in buffers:
        name = buffer.get("name")
        require(name in ("a", "b", "out"), f"{case}: unknown buffer {name!r}")
        require(name not in by_name, f"{case}: duplicate buffer {name}")
        by_name[name] = buffer
        require(buffer.get("size") == BUFFER_SIZE,
                f"{case}: buffer {name} size {buffer.get('size')} != {BUFFER_SIZE}")
    require(set(by_name) == {"a", "b", "out"}, f"{case}: buffer set mismatch")

    for name in ("a", "b"):
        buffer = by_name[name]
        require(set(buffer) == IN_BUFFER_KEYS, f"{case}: {name} key set")
        require(buffer["direction"] == "in", f"{case}: {name} direction")
        input_path = case_dir / buffer["input"]
        require(input_path.is_file(), f"{case}: {name} input missing")
        require(input_path.stat().st_size == buffer["size"],
                f"{case}: {name} input size != declared size")
    out_buffer = by_name["out"]
    require(set(out_buffer) == OUT_BUFFER_KEYS, f"{case}: out key set")
    require(out_buffer["direction"] == "out", f"{case}: out direction")
    require(out_buffer["output"] == "out.bin", f"{case}: out filename")

    patches = job["patches"]
    require(isinstance(patches, list) and len(patches) == 3,
            f"{case}: three patches expected")
    qwords = list(struct.unpack(f"<{total_qwords}Q", regcmd))
    patched_indices = []
    for patch in patches:
        require(set(patch) == PATCH_KEYS, f"{case}: patch key set")
        require(patch["kind"] == "value32", f"{case}: patch kind")
        require(patch["buffer"] in ADDRESS_ROLES, f"{case}: patch buffer")
        index = patch["regcmd_index"]
        require(isinstance(index, int) and 0 <= index < total_qwords,
                f"{case}: patch index {index} out of range")
        patched_indices.append(index)
        qword = qwords[index]
        target = (qword >> 48) & 0xFFFF
        offset = qword & 0xFFFF
        require((target, offset) == ADDRESS_ROLES[patch["buffer"]],
                f"{case}: patch {index} points at 0x{target:04x}/0x{offset:04x}, "
                f"not {patch['buffer']}")
        placeholder = (qword >> 16) & 0xFFFFFFFF
        require(placeholder != 0, f"{case}: patch {index} placeholder is zero")
    require(len(set(patched_indices)) == len(patched_indices),
            f"{case}: duplicate patch indices")

    address_indices = [
        index for index, qword in enumerate(qwords)
        if (((qword >> 48) & 0xFFFF), (qword & 0xFFFF)) in ADDRESS_REGS
    ]
    require(sorted(address_indices) == sorted(patched_indices),
            f"{case}: address writes {address_indices} != patched {sorted(patched_indices)}")
    placeholders = [(qwords[index] >> 16) & 0xFFFFFFFF for index in patched_indices]
    require(len(set(placeholders)) == len(placeholders),
            f"{case}: placeholder addresses are not distinct")

    for index, qword in enumerate(qwords):
        target = (qword >> 48) & 0xFFFF
        require(target in KNOWN_TARGETS,
                f"{case}: QWORD {index} unknown target 0x{target:04x}")
        offset = qword & 0xFFFF
        if target in (TARGET_PC, TARGET_PC_REG):
            require(offset in {0x0008, 0x0010, 0x0014},
                    f"{case}: QWORD {index} PC offset 0x{offset:04x}")
        if target == TARGET_VERSION:
            require(offset == 0, f"{case}: QWORD {index} version offset")

    expected = (case_dir / "expected.bin").read_bytes()
    mask = (case_dir / "expected.mask.bin").read_bytes()
    require(len(expected) == out_buffer["size"],
            f"{case}: expected.bin size != output buffer size")
    require(len(mask) == out_buffer["size"],
            f"{case}: expected.mask.bin size != output buffer size")
    require(set(mask) <= {0x00, 0xFF}, f"{case}: mask has values other than 0/0xFF")
    asserted = sum(1 for byte in mask if byte == 0xFF)
    expected_asserted = entry["shape"]["elements"] * entry["output_item_size"]
    require(asserted == expected_asserted,
            f"{case}: mask asserts {asserted} bytes, expected {expected_asserted}")
    for index, byte in enumerate(expected):
        if mask[index] == 0x00:
            require(byte == 0x00,
                    f"{case}: expected.bin byte {index} is outside the mask but nonzero")

    oracle = entry["oracle"]
    for key in ("kind", "formula", "expected", "mask", "compare", "confidence"):
        require(key in oracle, f"{case}: oracle missing {key}")
    require(oracle["expected"] == "expected.bin", f"{case}: oracle expected file")
    require(oracle["mask"] == "expected.mask.bin", f"{case}: oracle mask file")


def validate_blocked(entry):
    case = entry["case"]
    for required in (
        "dtype", "operation", "source_example", "source_refs", "description",
        "oracle", "blocked_reason",
    ):
        require(required in entry, f"{case}: blocked entry missing {required}")
    require(entry["oracle"] == "none", f"{case}: blocked oracle must be 'none'")
    require(entry["blocked_reason"].strip(), f"{case}: empty blocked_reason")
    require(not (CASE_ROOT / case).exists(), f"{case}: blocked case has a case dir")


def main():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    require(manifest.get("family") == "ew-int", "manifest family")
    cases = manifest["cases"]
    names = [entry["case"] for entry in cases]
    require(len(names) == len(set(names)), "duplicate case names")

    ready = [entry for entry in cases if entry["status"] == "READY"]
    blocked = [entry for entry in cases if entry["status"] == "BLOCKED"]
    require(len(ready) + len(blocked) == len(cases), "unknown status")
    require(manifest["counts"] == {"READY": len(ready), "BLOCKED": len(blocked)},
            "manifest counts mismatch")

    report = {"cases": [], "summary": {
        "ready": len(ready), "blocked": len(blocked), "failed": 0,
    }}
    failures = []
    for entry in ready:
        try:
            validate_ready(entry)
            report["cases"].append({"case": entry["case"], "status": "READY", "result": "PASS"})
        except Exception as exc:
            failures.append(entry["case"])
            report["cases"].append({
                "case": entry["case"], "status": "READY",
                "result": "FAIL", "error": f"{type(exc).__name__}: {exc}",
            })
            report["summary"]["failed"] += 1
    for entry in blocked:
        try:
            validate_blocked(entry)
            report["cases"].append({"case": entry["case"], "status": "BLOCKED", "result": "PASS"})
        except Exception as exc:
            failures.append(entry["case"])
            report["cases"].append({
                "case": entry["case"], "status": "BLOCKED",
                "result": "FAIL", "error": f"{type(exc).__name__}: {exc}",
            })
            report["summary"]["failed"] += 1

    declared = {entry["case"] for entry in ready}
    on_disk = {path.name for path in CASE_ROOT.iterdir() if path.is_dir()}
    if declared != on_disk:
        failures.append("case-directory-set")
        report["cases"].append({
            "case": "case-directory-set", "status": "-", "result": "FAIL",
            "error": f"declared {sorted(declared)} != on disk {sorted(on_disk)}",
        })
        report["summary"]["failed"] += 1

    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    (VALIDATION_DIR / "local_validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "RK3588 integer EW local bundle validation",
        f"READY {len(ready)}  BLOCKED {len(blocked)}  FAILED {report['summary']['failed']}",
    ]
    for case_report in report["cases"]:
        if case_report["result"] == "PASS":
            lines.append(f"  PASS {case_report['status']:7s} {case_report['case']}")
        else:
            lines.append(
                f"  FAIL {case_report['status']:7s} {case_report['case']}: "
                f"{case_report['error']}"
            )
    text = "\n".join(lines) + "\n"
    (VALIDATION_DIR / "local_validation.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    if failures:
        print(f"FAILURES: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
