#!/usr/bin/env python3
"""Small stdlib-only validator for the conv-simple capture bundles.

It checks the schema and bounds required by CAPTURE_FORMAT.md:

  * manifest and job.json required fields;
  * one task range per job, in-bounds and non-overlapping;
  * regcmd.bin length covers Rocket's QWORD-pair fetch extent (odd declared
    counts fetch one extra zero QWORD that is not executed);
  * every input file exists and its size equals the declared BO size;
  * the out buffer declares an output filename and that file is absent;
  * every address operand in the command stream is covered by exactly one
    value32 patch bound to the expected named buffer;
  * task tails are terminal (PC base/amount zero) with the source-specific
    operation-enable value;
  * expected.bin size matches the documented logical shape/dtype;
  * manifest hashes match the case files.

It does not run a device, does not import NumPy, and does not compare numerical
values.  Numeric consistency is checked separately by check_numeric.py.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JOB_KEYS = {
    "case", "source_example", "description", "timeout_ns",
    "tasks", "buffers", "patches",
}
TASK_KEYS = {"regcmd_offset_words", "regcmd_words"}
PATCH_KEYS = {"regcmd_index", "buffer", "kind"}
PATCH_KINDS = {"value32", "all32", "low32", "high32"}
FP16_ADDR = {(0x0201, 0x1070): "input", (0x0201, 0x1110): "weight", (0x1001, 0x4020): "out"}
INT8_ADDR = {
    (0x0201, 0x1070): "input",
    (0x0201, 0x1110): "weight",
    (0x1001, 0x4020): "out",
    (0x2001, 0x5020): "bias",
}
FP16_ENABLE = (6 << 1) | 1
INT8_ENABLE = (14 << 1) | 1


class ValidationError(Exception):
    pass


def require(cond, message):
    if not cond:
        raise ValidationError(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_rel(case_dir: Path, name, field: str) -> Path:
    require(isinstance(name, str) and name, f"{field} must be a non-empty string")
    candidate = (case_dir / name).resolve()
    try:
        candidate.relative_to(case_dir.resolve())
    except ValueError as exc:
        raise ValidationError(f"{field} escapes the case directory: {name}") from exc
    return candidate


def decode_qword(word: int):
    return (word >> 48) & 0xFFFF, word & 0xFFFF, (word >> 16) & 0xFFFFFFFF


def validate_ready(case_dir: Path, rec: dict) -> dict:
    case = rec["case"]
    require(case == case_dir.name, f"case name/directory mismatch: {case} vs {case_dir.name}")
    require(case_dir.is_dir(), f"missing case directory {case_dir}")
    require(not (case_dir / "out.bin").exists(), f"{case}: out.bin must not be shipped")
    require(isinstance(rec.get("source_lines"), dict) and rec["source_lines"],
            f"{case}: source_lines must be a non-empty object")
    require(isinstance(rec.get("seed"), int), f"{case}: seed must be recorded")
    require(Path(rec["source_example"]).is_file(), f"{case}: source_example does not exist")
    require(rec.get("blocker") is None, f"{case}: READY case has a blocker")

    job_path = case_dir / "job.json"
    require(job_path.is_file(), f"{case}: missing job.json")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    require(set(job) == JOB_KEYS, f"{case}: job.json keys {sorted(job)} != {sorted(JOB_KEYS)}")
    require(job["case"] == case, f"{case}: job.case mismatch")
    require(job["source_example"] == rec["source_example"], f"{case}: job.source_example mismatch")
    require(isinstance(job["description"], str) and job["description"], f"{case}: empty description")
    require(isinstance(job["timeout_ns"], int) and job["timeout_ns"] > 0,
            f"{case}: timeout_ns must be positive")

    regcmd_path = case_dir / "regcmd.bin"
    require(regcmd_path.is_file(), f"{case}: missing regcmd.bin")
    regcmd_bytes = regcmd_path.read_bytes()
    require(len(regcmd_bytes) % 8 == 0, f"{case}: regcmd.bin is not a QWORD multiple")
    words = list(struct.unpack("<" + "Q" * (len(regcmd_bytes) // 8), regcmd_bytes))
    require(words, f"{case}: empty regcmd.bin")

    tasks = job["tasks"]
    require(isinstance(tasks, list) and tasks, f"{case}: tasks must be a non-empty list")
    declared_ranges = []
    fetch_ranges = []
    for index, task in enumerate(tasks):
        require(set(task) == TASK_KEYS, f"{case}: task {index} keys mismatch")
        start = task["regcmd_offset_words"]
        count = task["regcmd_words"]
        require(isinstance(start, int) and start >= 0, f"{case}: bad task start")
        require(isinstance(count, int) and count > 0, f"{case}: bad task word count")
        require(start % 2 == 0, f"{case}: task {index} offset is not an even QWORD")
        declared_end = start + count
        # Rocket's PC fetch field is expressed in QWORD pairs; an odd declared
        # count fetches one extra QWORD.  The extra word must exist in the file
        # but is not executed as a command.
        fetch_words = count + (count & 1)
        fetch_end = start + fetch_words
        require(declared_end <= len(words),
                f"{case}: task {index} declared range {start}:{declared_end} exceeds {len(words)}")
        require(fetch_end <= len(words),
                f"{case}: task {index} fetch range {start}:{fetch_end} exceeds {len(words)}")
        declared_ranges.append((start, declared_end))
        fetch_ranges.append((start, fetch_end))
    fetch_ranges_sorted = sorted(fetch_ranges)
    for (s1, e1), (s2, e2) in zip(fetch_ranges_sorted, fetch_ranges_sorted[1:]):
        require(e1 <= s2,
                f"{case}: overlapping fetch ranges {s1}:{e1} and {s2}:{e2}")
    require(fetch_ranges_sorted[0][0] == 0, f"{case}: first task does not start at word 0")
    declared_words = max(end for _, end in declared_ranges)
    fetched_words = max(end for _, end in fetch_ranges)
    padding_words = len(words) - declared_words
    require(rec.get("tasks") == len(tasks), f"{case}: manifest tasks mismatch")
    require(rec.get("regcmd_words") == declared_words,
            f"{case}: manifest regcmd_words {rec.get('regcmd_words')} != declared {declared_words}")
    require(rec.get("regcmd_file_words") == len(words),
            f"{case}: manifest regcmd_file_words {rec.get('regcmd_file_words')} != {len(words)}")
    require(rec.get("regcmd_fetch_words") == fetched_words,
            f"{case}: manifest regcmd_fetch_words {rec.get('regcmd_fetch_words')} != {fetched_words}")
    require(rec.get("regcmd_size_bytes") == len(regcmd_bytes),
            f"{case}: manifest regcmd_size_bytes {rec.get('regcmd_size_bytes')} != {len(regcmd_bytes)}")
    require(rec.get("regcmd_padding_words") == padding_words,
            f"{case}: manifest regcmd_padding_words {rec.get('regcmd_padding_words')} != {padding_words}")
    require(padding_words == (declared_words & 1),
            f"{case}: expected exactly one parity QWORD for odd declared count, got {padding_words}")
    require(all(word == 0 for word in words[declared_words:]),
            f"{case}: trailing fetch padding is not zero")

    buffers = job["buffers"]
    require(isinstance(buffers, list) and buffers, f"{case}: buffers must be non-empty")
    by_name = {}
    input_paths = []
    out_buffers = []
    for buf in buffers:
        require(isinstance(buf, dict), f"{case}: buffer entry is not an object")
        require({"name", "size", "direction"} <= set(buf), f"{case}: buffer missing base keys")
        name = buf["name"]
        require(isinstance(name, str) and name, f"{case}: buffer name")
        require(name not in by_name, f"{case}: duplicate buffer {name}")
        by_name[name] = buf
        size = buf["size"]
        require(isinstance(size, int) and size > 0, f"{case}: buffer {name} bad size")
        direction = buf["direction"]
        require(direction in {"in", "out", "inout"}, f"{case}: buffer {name} bad direction")
        if direction in {"in", "inout"}:
            require("input" in buf, f"{case}: buffer {name} lacks input file")
            path = safe_rel(case_dir, buf["input"], f"{case}:{name}.input")
            require(path.is_file(), f"{case}: missing input file {buf['input']}")
            require(path.stat().st_size == size,
                    f"{case}: {buf['input']} size {path.stat().st_size} != declared {size}")
            input_paths.append((name, path))
        if direction in {"out", "inout"}:
            require("output" in buf, f"{case}: buffer {name} lacks output file")
            out_path = safe_rel(case_dir, buf["output"], f"{case}:{name}.output")
            require(not out_path.exists(), f"{case}: worker output {buf['output']} already exists")
            out_buffers.append((name, buf["size"], out_path))
    require(out_buffers, f"{case}: no out/inout buffer")
    if len(out_buffers) == 1:
        out_size = out_buffers[0][1]
        expected_path = case_dir / "expected.bin"
        require(expected_path.is_file(), f"{case}: missing expected.bin")
        expected_size = expected_path.stat().st_size
        require(expected_size <= out_size,
                f"{case}: expected.bin {expected_size} > out buffer {out_size}")
        require(expected_size > 0, f"{case}: empty expected.bin")
        expected_bytes = expected_path.read_bytes()
        require(len(set(expected_bytes)) > 1, f"{case}: expected.bin is constant")
    else:
        expected_size = None
        out_size = None

    # Shape consistency and expected-size cross-check.
    shape = rec["shape"]
    for key in ("batch", "in_c", "in_h", "in_w", "out_c", "weight_in_c", "kh", "kw", "groups"):
        require(isinstance(shape.get(key), int), f"{case}: shape.{key} must be an int")
    require(shape["batch"] == 1, f"{case}: only batch=1 bundles are prepared")
    require(shape["stride"] == 1, f"{case}: READY case must be stride 1")
    out_h = shape["in_h"] - shape["kh"] + 1
    out_w = shape["in_w"] - shape["kw"] + 1
    require(out_h > 0 and out_w > 0, f"{case}: non-positive output geometry")
    require(rec["shape"].get("name") == case, f"{case}: shape.name mismatch")
    groups = shape["groups"]
    if groups == shape["in_c"] == shape["out_c"] and shape["weight_in_c"] == 1:
        depthwise = True
    else:
        depthwise = False
        require(shape["in_c"] % groups == 0 and shape["out_c"] % groups == 0,
                f"{case}: channels not divisible by groups")
        require(shape["weight_in_c"] == shape["in_c"] // groups,
                f"{case}: weight_in_c != in_c/groups")
    if "depthwise" in rec:
        require(rec["depthwise"] == depthwise, f"{case}: depthwise flag mismatch")
    if expected_size is not None:
        oracle = rec.get("oracle")
        require(isinstance(oracle, dict), f"{case}: READY case lacks oracle object")
        require(oracle.get("file") == "expected.bin", f"{case}: oracle.file")
        require(isinstance(oracle.get("source"), str) and oracle["source"],
                f"{case}: oracle.source")
        require(isinstance(oracle.get("warning"), str) and "Host-side" in oracle["warning"],
                f"{case}: oracle must be labelled host-side")
        dtype = oracle.get("dtype")
        if dtype == "float16":
            unit = 2
        elif dtype == "float32":
            unit = 4
        elif dtype == "uint8":
            unit = 1
        else:
            raise ValidationError(f"{case}: unsupported oracle dtype {dtype}")
        logical = oracle.get("logical_shape")
        require(isinstance(logical, list) and len(logical) == 4, f"{case}: logical_shape")
        expected_elems = shape["out_c"] * out_h * out_w
        require(expected_size == expected_elems * unit,
                f"{case}: expected.bin {expected_size} != logical {expected_elems}*{unit}")
        if dtype == "uint8":
            require(out_size == 2 * expected_size,
                    f"{case}: INT8 out buffer {out_size} != 2x oracle prefix {expected_size}")
            require(oracle.get("expected_bytes") == expected_size,
                    f"{case}: oracle.expected_bytes mismatch")
            require(oracle.get("tolerance", {}).get("max_abs_diff_uint8") == 1,
                    f"{case}: INT8 tolerance")
        else:
            require(out_size == expected_size,
                    f"{case}: FP16 out buffer {out_size} != oracle size {expected_size}")
            require(isinstance(oracle.get("tolerance", {}).get("atol"), (int, float)),
                    f"{case}: FP16 atol")
        if dtype == "uint8":
            require(logical == [1, out_h, out_w, shape["out_c"]],
                    f"{case}: INT8 logical_shape mismatch")
        else:
            require(logical == [1, shape["out_c"], out_h, out_w],
                    f"{case}: FP16 logical_shape mismatch")

    # Patches and address coverage.
    is_int8 = Path(rec["source_example"]).name == "simple_conv.py"
    address_map = INT8_ADDR if is_int8 else FP16_ADDR
    patches = job["patches"]
    require(isinstance(patches, list), f"{case}: patches must be a list")
    patch_indices = set()
    for patch in patches:
        require(isinstance(patch, dict) and set(patch) == PATCH_KEYS,
                f"{case}: patch entry keys mismatch")
        index = patch["regcmd_index"]
        require(isinstance(index, int) and 0 <= index < len(words),
                f"{case}: patch index {index} out of range")
        require(index not in patch_indices, f"{case}: duplicate patch index {index}")
        patch_indices.add(index)
        require(patch["kind"] in PATCH_KINDS, f"{case}: patch kind {patch['kind']}")
        require(patch["buffer"] in by_name, f"{case}: patch buffer {patch['buffer']} missing")
        target, reg_addr, value = decode_qword(words[index])
        require(patch["kind"] == "value32", f"{case}: this bundle only uses value32 patches")
        require(value == 0, f"{case}: patch index {index} placeholder is not zero")
        key = (target, reg_addr)
        require(key in address_map, f"{case}: patch index {index} is not a known address register")
        require(address_map[key] == patch["buffer"],
                f"{case}: patch index {index} buffer {patch['buffer']} != {address_map[key]}")

    actual_address_indices = set()
    for index, word in enumerate(words):
        target, reg_addr, _ = decode_qword(word)
        if (target, reg_addr) in address_map:
            actual_address_indices.add(index)
    require(actual_address_indices == patch_indices,
            f"{case}: address indices {sorted(actual_address_indices)} != patches {sorted(patch_indices)}")

    # Terminal tail checks for every task range.
    expected_enable = INT8_ENABLE if is_int8 else FP16_ENABLE
    for start, end in declared_ranges:
        require(end - start >= 4, f"{case}: task shorter than terminal tail")
        tail = words[end - 4:end]
        t0, r0, v0 = decode_qword(tail[0])
        t1, r1, v1 = decode_qword(tail[1])
        t2, r2, v2 = decode_qword(tail[2])
        t3, r3, v3 = decode_qword(tail[3])
        require((t0, r0, v0) == (0x0101, 0x0010, 0), f"{case}: PC base is not terminal zero")
        require((t1, r1, v1) == (0x0101, 0x0014, 0), f"{case}: PC amount is not terminal zero")
        require((t2, r2, v2) == (0x0041, 0x0000, 0), f"{case}: VERSION sentinel mismatch")
        require((t3, r3, v3) == (0x0081, 0x0008, expected_enable),
                f"{case}: PC operation enable {v3:#x} != {expected_enable:#x}")
        for word in words[start:end - 4]:
            target, reg_addr, value = decode_qword(word)
            if (target, reg_addr) in {(0x0101, 0x0010), (0x0101, 0x0014)}:
                require(value == 0, f"{case}: nonzero PC chain field inside body")

    # Manifest/job duplication consistency and hashes.
    require(rec["buffers"] == buffers, f"{case}: manifest buffers != job buffers")
    require(rec["patches"] == patches, f"{case}: manifest patches != job patches")
    hashes = rec.get("hashes")
    require(isinstance(hashes, dict) and hashes, f"{case}: manifest hashes")
    expected_hash_keys = {"job.json", "regcmd.bin", "expected.bin"} | {
        b["input"] for b in buffers if "input" in b
    }
    require(set(hashes) == expected_hash_keys,
            f"{case}: hash keys {sorted(hashes)} != {sorted(expected_hash_keys)}")
    for name, expected_hash in hashes.items():
        path = safe_rel(case_dir, name, f"{case}:hash")
        require(path.is_file(), f"{case}: hashed file {name} missing")
        require(sha256(path) == expected_hash, f"{case}: hash mismatch for {name}")

    return {
        "case": case,
        "status": "READY",
        "tasks": len(tasks),
        "regcmd_words": declared_words,
        "regcmd_file_words": len(words),
        "regcmd_fetch_words": fetched_words,
        "regcmd_size_bytes": len(regcmd_bytes),
        "regcmd_padding_words": padding_words,
        "buffers": len(buffers),
        "patches": len(patches),
        "address_indices": sorted(patch_indices),
        "expected_bytes": expected_size,
        "out_bytes": out_size,
        "hash": sha256(case_dir / "job.json"),
    }


def validate_blocked(case_dir: Path, rec: dict) -> dict:
    case = rec["case"]
    require(case == case_dir.name, f"{case}: directory mismatch")
    require(case_dir.is_dir(), f"{case}: missing blocked case directory")
    require(not (case_dir / "job.json").exists(), f"{case}: BLOCKED case has job.json")
    require(not (case_dir / "regcmd.bin").exists(), f"{case}: BLOCKED case has regcmd.bin")
    blocker = rec.get("blocker")
    require(isinstance(blocker, str) and len(blocker) >= 80,
            f"{case}: blocker must be a concrete non-trivial string")
    require(rec.get("oracle") is None, f"{case}: BLOCKED case must not claim an oracle")
    require(rec.get("tasks") == 0, f"{case}: BLOCKED task count")
    require(rec.get("buffers") == [], f"{case}: BLOCKED buffers must be empty")
    require(rec.get("patches") == [], f"{case}: BLOCKED patches must be empty")
    marker = case_dir / "BLOCKED.md"
    require(marker.is_file() and marker.stat().st_size > 0, f"{case}: missing BLOCKED.md")
    require(marker.read_text(encoding="utf-8").strip() == blocker.strip(),
            f"{case}: BLOCKED.md does not match manifest blocker")
    require(rec.get("hashes", {}).get("BLOCKED.md") == sha256(marker),
            f"{case}: BLOCKED.md hash mismatch")
    require(Path(rec["source_example"]).is_file(), f"{case}: source_example missing")
    return {"case": case, "status": "BLOCKED", "blocker_chars": len(blocker)}


def validate_coverage(manifest: dict) -> None:
    by_name = {rec["case"]: rec for rec in manifest["cases"]}
    coverage = manifest.get("coverage")
    require(isinstance(coverage, dict), "manifest.coverage missing")
    required_keys = {
        "1x1", "3x3", "5x5", "depthwise", "grouped", "grouped_blocked",
        "c8_fp16_blocked", "stride_1", "stride_2_blocked", "padding_valid",
        "padding_same_blocked", "addition_input_blocked", "output_dtypes",
    }
    require(required_keys <= set(coverage), f"coverage keys missing {sorted(required_keys - set(coverage))}")
    for key, names in coverage.items():
        if key == "output_dtypes":
            require(isinstance(names, dict), "coverage.output_dtypes must be an object")
            for dtype, dtype_names in names.items():
                require(isinstance(dtype_names, list), f"coverage.output_dtypes.{dtype}")
                for name in dtype_names:
                    require(name in by_name, f"coverage.{key}.{dtype} unknown case {name}")
                    require(by_name[name]["status"] == "READY", f"coverage.{key} non-READY {name}")
            continue
        require(isinstance(names, list), f"coverage.{key} must be a list")
        for name in names:
            require(name in by_name, f"coverage.{key} unknown case {name}")
            expected_status = "BLOCKED" if key.endswith("_blocked") else "READY"
            require(by_name[name]["status"] == expected_status,
                    f"coverage.{key} case {name} is {by_name[name]['status']}")
    require(any(by_name[n]["shape"].get("kh") == 1 for n in coverage["1x1"]), "no 1x1 case")
    require(any(by_name[n]["shape"].get("kh") == 3 for n in coverage["3x3"]), "no 3x3 case")
    require(any(by_name[n]["shape"].get("kh") == 5 for n in coverage["5x5"]), "no 5x5 case")
    require(coverage["grouped"] == [], "grouped coverage must be empty (blocked)")


def main() -> int:
    errors = []
    checks = []
    manifest_path = ROOT / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(manifest.get("family") == "conv-simple", "manifest.family")
        require(isinstance(manifest.get("seeds"), dict), "manifest.seeds missing")
        require(isinstance(manifest["seeds"].get("fp16"), int), "manifest.seeds.fp16")
        require(isinstance(manifest["seeds"].get("int8"), int), "manifest.seeds.int8")
        require(isinstance(manifest.get("validation_files"), list) and manifest["validation_files"],
                "manifest.validation_files missing")
        require(isinstance(manifest.get("cases"), list) and manifest["cases"], "manifest.cases")
        by_case = {}
        for rec in manifest["cases"]:
            require(rec["case"] not in by_case, f"duplicate case {rec['case']}")
            by_case[rec["case"]] = rec
        ready_count = sum(1 for r in manifest["cases"] if r["status"] == "READY")
        blocked_count = sum(1 for r in manifest["cases"] if r["status"] == "BLOCKED")
        require(ready_count + blocked_count == len(manifest["cases"]), "unknown status")
        require(manifest.get("summary") == {
            "ready": ready_count, "blocked": blocked_count, "total": len(manifest["cases"])
        }, "manifest summary mismatch")
        validate_coverage(manifest)
        for rec in manifest["cases"]:
            case_dir = ROOT / "cases" / rec["case"]
            if rec["status"] == "READY":
                checks.append(validate_ready(case_dir, rec))
            elif rec["status"] == "BLOCKED":
                checks.append(validate_blocked(case_dir, rec))
            else:
                raise ValidationError(f"unknown status {rec['status']}")
        # Every case directory must be represented in the manifest.
        case_dirs = sorted(p.name for p in (ROOT / "cases").iterdir() if p.is_dir())
        require(set(case_dirs) == set(by_case), f"unlisted case dirs {set(case_dirs) - set(by_case)}")
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        errors.append(str(exc))

    result = {
        "validator": "validate.py",
        "validated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "PASS" if not errors else "FAIL",
        "ready_cases": sum(1 for c in checks if c["status"] == "READY"),
        "blocked_cases": sum(1 for c in checks if c["status"] == "BLOCKED"),
        "checks": checks,
        "errors": errors,
    }
    (ROOT / "validation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    if errors:
        print("validation FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"validation PASS: {result['ready_cases']} READY, {result['blocked_cases']} BLOCKED")
    for check in checks:
        if check["status"] == "READY":
            print(
                f"  READY   {check['case']}: {check['tasks']} task(s), "
                f"{check['regcmd_words']} declared / {check['regcmd_file_words']} file "
                f"({check['regcmd_fetch_words']} fetched) words, "
                f"{check['buffers']} buffers, {check['patches']} patches, "
                f"expected {check['expected_bytes']} B, out {check['out_bytes']} B"
            )
        else:
            print(f"  BLOCKED {check['case']}: {check['blocker_chars']} char reason")
    return 0


if __name__ == "__main__":
    sys.exit(main())
