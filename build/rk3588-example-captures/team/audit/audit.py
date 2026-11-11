#!/usr/bin/env python3
"""Independent audit of build/rk3588-example-captures bundles.

This parser deliberately does not import or execute any family validator,
tools/gen_*, prepare_bundle, or runner code.  It reads the manifests and case
files as bytes, re-implements the documented CAPTURE_FORMAT checks, and
recomputes every declared hash from actual bytes.

Usage:
  python3 audit.py --root /home/fedora/rknpu-fpga/build/rk3588-example-captures \
                   --out-json .../AUDIT.json --out-md .../AUDIT.md

Exit status: 0 if no INVALID cases and no audit errors, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

AUDIT_VERSION = "independent-bundle-audit/1.3.0"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_PATCH_KINDS = {"value32", "all32", "low32", "high32"}
JOB_KEYS = {"case", "source_example", "description", "timeout_ns", "tasks", "buffers", "patches"}
TASK_KEYS = {"regcmd_offset_words", "regcmd_words"}
BUFFER_KEYS = {"name", "size", "input", "direction", "output"}
PATCH_KEYS = {"regcmd_index", "buffer", "kind"}
EXPECTED_NAME_MARKERS = ("expected", "oracle")
OUTPUT_LIKE_NAMES = {"out.bin", "output.bin", "out0.bin", "out1.bin", "out2.bin", "out3.bin"}


# ---------------------------------------------------------------------------
# Basic helpers


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_int(value) -> bool:
    return type(value) is int


def is_nonempty_str(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def safe_rel_name(value) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if os.path.isabs(value):
        return False
    if value in {".", ".."}:
        return False
    if "/" in value or "\\" in value:
        return False
    return True


def json_path_join(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else key


class DuplicateJsonKey(ValueError):
    pass


def _no_dup_pairs(pairs):
    out = OrderedDict()
    for key, value in pairs:
        if key in out:
            raise DuplicateJsonKey(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def strict_json_load(path: Path):
    data = path.read_bytes()
    obj = json.loads(data.decode("utf-8"), object_pairs_hook=_no_dup_pairs)
    return obj, data


def collect_hash_strings(obj, prefix=""):
    """Yield (json_path, value) for every 64-hex string in a JSON object."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from collect_hash_strings(value, json_path_join(prefix, str(key)))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from collect_hash_strings(value, f"{prefix}[{index}]")
    elif isinstance(obj, str) and HASH_RE.match(obj):
        yield prefix, obj


def collect_keyed_strings(obj, key_name, prefix=""):
    """Yield (json_path, key, value) for matching keys."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = json_path_join(prefix, str(key))
            if key == key_name:
                yield path, key, value
            yield from collect_keyed_strings(value, key_name, path)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from collect_keyed_strings(value, key_name, f"{prefix}[{index}]")


# ---------------------------------------------------------------------------
# Findings


class Findings:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, code, message):
        self.errors.append({"code": code, "message": message})
        return False

    def warning(self, code, message):
        self.warnings.append({"code": code, "message": message})
        return False

    def as_json(self):
        return {"errors": self.errors, "warnings": self.warnings}


class CaseAudit:
    CATEGORIES = (
        "schema",
        "manifest",
        "source",
        "buffers",
        "regcmd",
        "tasks",
        "patches",
        "hashes",
        "oracle",
        "outputs",
        "files",
        "semantics",
    )

    def __init__(self, name, manifest_status, materialized):
        self.case = name
        self.manifest_status = manifest_status
        self.materialized = materialized
        self.errors = []
        self.warnings = []
        self.checks = {category: True for category in self.CATEGORIES}
        self.verified_hashes = set()
        self.declared_hash_count = 0
        self.verified_hash_count = 0
        self.documented_deviations = []
        self.documented_codes = set()
        self.accepted_padding = []
        self.regcmd_qwords = None
        self.task_count = None
        self.buffer_count = None
        self.patch_count = None

    def error(self, category, code, message):
        self.checks[category] = False
        self.errors.append({"category": category, "code": code, "message": message})
        return False

    def documented(self, code, message, category="tasks"):
        self.documented_deviations.append(
            {"category": category, "code": code, "message": message}
        )
        self.documented_codes.add(code)
        return False

    @property
    def exception_status(self):
        if self.audit_status == "INVALID" and self.errors and all(
            error["code"] in self.documented_codes for error in self.errors
        ):
            if self.manifest_status in {"READY", "BLOCKED"}:
                return self.manifest_status
        return self.audit_status

    def warning(self, category, code, message):
        self.warnings.append({"category": category, "code": code, "message": message})
        return False

    def hash_verified(self, declared, actual):
        if isinstance(declared, str):
            self.declared_hash_count += 1
            if declared == actual:
                self.verified_hash_count += 1
                self.verified_hashes.add(actual)
                return True
        return False

    @property
    def audit_status(self):
        if self.errors:
            return "INVALID"
        if self.manifest_status == "READY":
            return "READY"
        if self.manifest_status == "BLOCKED":
            return "BLOCKED"
        return "INVALID"

    def as_json(self):
        return {
            "case": self.case,
            "manifest_status": self.manifest_status,
            "audit_status": self.audit_status,
            "exception_status": self.exception_status,
            "materialized": self.materialized,
            "regcmd_qwords": self.regcmd_qwords,
            "task_count": self.task_count,
            "buffer_count": self.buffer_count,
            "patch_count": self.patch_count,
            "declared_hashes": self.declared_hash_count,
            "verified_hashes": self.verified_hash_count,
            "checks": self.checks,
            "accepted_padding": self.accepted_padding,
            "documented_deviations": self.documented_deviations,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Snapshot


def family_dirs(root: Path):
    families = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if child.name in {"team", "runner", "board-worker", "results"}:
            continue
        if (child / "manifest.json").is_file():
            families.append(child.name)
    return families


def build_snapshot(root: Path, families):
    start = utc_now()
    files = {}
    data_by_key = {}
    for family in families:
        base = root / family
        for path in sorted(base.rglob("*"), key=lambda p: str(p)):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts:
                continue
            rel = str(path.relative_to(root))
            data = path.read_bytes()
            stat = path.stat()
            files[rel] = {
                "path": rel,
                "size": len(data),
                "sha256": sha256_bytes(data),
                "mtime_ns": stat.st_mtime_ns,
                "is_symlink": path.is_symlink(),
            }
            data_by_key[rel] = data
    end = utc_now()
    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(str(files[rel]["size"]).encode())
        digest.update(b"\0")
        digest.update(files[rel]["sha256"].encode())
        digest.update(b"\n")
    return {
        "start_utc": start,
        "end_utc": end,
        "tree_sha256": digest.hexdigest(),
        "files": files,
        "_data": data_by_key,
        "root": str(root),
    }


def compare_live(root: Path, snapshot):
    expected = snapshot["files"]
    live = {}
    for rel in sorted(expected):
        path = root / rel
        if not path.is_file():
            live[rel] = {"path": rel, "missing": True}
            continue
        data = path.read_bytes()
        live[rel] = {
            "path": rel,
            "size": len(data),
            "sha256": sha256_bytes(data),
        }
    changes = []
    for rel, old in sorted(expected.items()):
        new = live.get(rel)
        if new is None or new.get("missing"):
            changes.append({"path": rel, "change": "missing"})
            continue
        if new["size"] != old["size"] or new["sha256"] != old["sha256"]:
            changes.append(
                {
                    "path": rel,
                    "change": "changed",
                    "snapshot_sha256": old["sha256"],
                    "live_sha256": new["sha256"],
                }
            )
    # Also detect files added under the audited families.
    for family in snapshot.get("families", []):
        base = root / family
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            rel = str(path.relative_to(root))
            if rel not in expected:
                changes.append({"path": rel, "change": "added"})
    return changes


# ---------------------------------------------------------------------------
# Source-reference helpers


def resolve_ref(root: Path, family_dir: Path, case_dir, ref):
    if not isinstance(ref, str) or not ref:
        return None
    path = Path(ref)
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    else:
        if case_dir is not None:
            candidates.append(case_dir / path)
        candidates.append(family_dir / path)
        candidates.append(root / path)
        candidates.append(root.parent.parent / path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def check_source_ref(case: CaseAudit, root, family_dir, case_dir, ref, context):
    resolved = resolve_ref(root, family_dir, case_dir, ref)
    if resolved is None:
        case.error("source", "source.path_missing", f"{context}: source path does not exist: {ref!r}")
        return None
    return resolved


def verify_source_hash(case: CaseAudit, path: Path, declared_sha, context):
    if not isinstance(declared_sha, str):
        case.error("hashes", "hashes.unverifiable_source", f"{context}: source hash is not a string")
        return False
    actual = sha256_bytes(path.read_bytes())
    if case.hash_verified(declared_sha, actual):
        return True
    case.error(
        "hashes",
        "hashes.source_mismatch",
        f"{context}: declared source sha256 {declared_sha} != actual {actual} ({path})",
    )
    return False


def recursive_source_refs(obj, prefix=""):
    """Yield (json_path, path_string) for keys named path/source_example/root."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = json_path_join(prefix, str(key))
            if key in {"path", "source_example", "root", "selected_source"} and isinstance(value, str):
                yield path, value
            yield from recursive_source_refs(value, path)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from recursive_source_refs(value, f"{prefix}[{index}]")


# ---------------------------------------------------------------------------
# Manifest / case audit


def audit_case(
    root: Path,
    family: str,
    family_dir: Path,
    entry,
    name: str,
    manifest_status,
    materialized: bool,
    snapshot,
    family_findings: Findings,
):
    case_dir = family_dir / "cases" / name if materialized else None
    case = CaseAudit(name, manifest_status, materialized)
    case.checks["schema"] = True

    if not isinstance(entry, dict):
        case.error("manifest", "manifest.case_not_object", "manifest case entry is not a JSON object")
        return case

    # --- Manifest status and required descriptive fields
    if manifest_status not in {"READY", "BLOCKED"}:
        case.error(
            "manifest",
            "manifest.bad_status",
            f"manifest status must be READY or BLOCKED, got {manifest_status!r}",
        )
    if entry.get("case") != name:
        case.error(
            "manifest",
            "manifest.case_name_mismatch",
            f"manifest entry case {entry.get('case')!r} does not match key/dir {name!r}",
        )
    if not is_nonempty_str(entry.get("description")):
        case.error("manifest", "manifest.description_missing", "manifest case description is missing or not a string")
    source_example = entry.get("source_example")
    source_path = None
    if not is_nonempty_str(source_example):
        case.error("source", "source.source_example_missing", "manifest source_example is missing or not a string")
    else:
        source_path = check_source_ref(
            case, root, family_dir, case_dir, source_example, "manifest.source_example"
        )

    if manifest_status == "BLOCKED":
        reasons = [entry.get(k) for k in ("blocked_reason", "reason", "blocker")]
        if not any(is_nonempty_str(v) for v in reasons):
            case.error(
                "manifest",
                "manifest.blocked_reason_missing",
                "BLOCKED case has no non-empty blocked_reason/reason/blocker",
            )
    if manifest_status == "READY":
        if "oracle" not in entry:
            case.error("oracle", "oracle.missing", "READY case does not declare an oracle")
        oracle = entry.get("oracle")
        if isinstance(oracle, dict) and oracle.get("device_output") is True:
            case.error("oracle", "oracle.device_output", "oracle declares device_output=true; oracle must not be a device output")
        if isinstance(oracle, str) and oracle.strip().lower() not in {"none", "null", ""}:
            # A free-text oracle description that is not a file.
            pass

    # --- Directory and declared location
    for key in ("case_dir", "bundle_dir"):
        if key in entry:
            expected = f"cases/{name}"
            if entry.get(key) != expected:
                case.error(
                    "manifest",
                    "manifest.bundle_dir_mismatch",
                    f"{key}={entry.get(key)!r} != expected {expected!r}",
                )

    if not materialized:
        if manifest_status == "READY":
            case.error(
                "manifest",
                "manifest.ready_missing_bundle",
                f"READY case has no case directory under {family}/cases/",
            )
        # BLOCKED manifest-only entries are allowed.  Still verify any
        # manifest-declared case hashes point at files if an entry exists.
        audit_case_source_lines(case, root, family_dir, None, entry)
        audit_declared_source_hashes(case, source_path, entry)
        audit_declared_hashes_without_dir(case, entry)
        return case

    if not case_dir.is_dir():
        case.error("manifest", "manifest.case_dir_missing", f"case directory is not a directory: {case_dir}")
        return case

    actual_files = {}
    for path in sorted(case_dir.rglob("*"), key=lambda p: str(p)):
        if path.is_file():
            rel = str(path.relative_to(case_dir))
            actual_files[rel] = path
            if path.is_symlink():
                case.error("files", "files.symlink", f"case file is a symlink: {rel}")
        elif path.is_dir() and path != case_dir:
            if manifest_status == "READY":
                case.error("files", "files.nested_dir", f"nested directory inside READY case bundle: {path}")
            else:
                case.warning(
                    "files",
                    "files.blocked_evidence_dir",
                    f"BLOCKED case carries a nested evidence directory: {path.relative_to(case_dir)}",
                )

    # --- Job schema / bundle checks
    job_path = case_dir / "job.json"
    job = None
    job_bytes = None
    if job_path.is_file():
        try:
            job, job_bytes = strict_json_load(job_path)
        except DuplicateJsonKey as exc:
            case.error("schema", "job.duplicate_json_key", f"job.json: {exc}")
        except Exception as exc:
            case.error("schema", "job.invalid_json", f"job.json cannot be parsed: {exc}")
    else:
        if manifest_status == "READY":
            case.error("schema", "job.missing", "READY case has no job.json")
        # A BLOCKED probe may legitimately have no job.json.

    if job is not None:
        audit_job(case, root, family_dir, case_dir, name, entry, job, job_bytes, actual_files)
    elif manifest_status == "BLOCKED":
        # No job: the only files we allow are the declared blocker notes.
        allowed = set(actual_files)
        declared = set()
        for map_key in ("hashes", "files", "bundle"):
            value = entry.get(map_key)
            if isinstance(value, dict):
                declared |= set(value)
        undeclared = sorted(allowed - declared)
        if undeclared:
            case.error(
                "files",
                "files.blocked_undeclared",
                f"BLOCKED case without job.json has undeclared files: {undeclared}",
            )

    # --- Hash declarations (case-level and source-level)
    audit_case_hashes(case, entry, case_dir, actual_files, source_path, source_example)
    audit_declared_source_hashes(case, source_path, entry)
    audit_case_source_lines(case, root, family_dir, case_dir, entry)
    audit_provenance(case, actual_files, job, source_path, source_example)

    # --- Oracle separation / expected files / outputs
    audit_oracle_and_outputs(case, entry, job, actual_files)

    # --- Manifest/job consistency and size metadata
    if job is not None:
        audit_manifest_job_consistency(case, family, entry, job, actual_files, case_dir)
        audit_manifest_semantics(case, family, entry, job, actual_files, case_dir, source_path)

    # --- Scan case entry for 64-hex values not proven against bytes.
    for path, value in collect_hash_strings(entry, f"{family}.cases[{name}]"):
        if value not in case.verified_hashes:
            case.error(
                "hashes",
                "hashes.unverifiable",
                f"{path}: hash {value} was not verified against actual bytes",
            )

    # --- Output-like files that are not declared input/oracle files
    if job is not None:
        declared_device = set()
        for buffer in job.get("buffers", []):
            if isinstance(buffer, dict):
                for key in ("input", "output"):
                    value = buffer.get(key)
                    if isinstance(value, str):
                        declared_device.add(value)
        for fname in sorted(actual_files):
            if os.path.basename(fname) in OUTPUT_LIKE_NAMES and fname not in declared_device:
                case.error("outputs", "outputs.stale_output", f"stale output-like file present: {fname}")

    return case


def audit_case_source_lines(case: CaseAudit, root, family_dir, case_dir, entry):
    refs = entry.get("source_refs")
    if isinstance(refs, list):
        for index, ref in enumerate(refs):
            if isinstance(ref, dict) and "path" in ref:
                check_source_ref(
                    case,
                    root,
                    family_dir,
                    case_dir,
                    ref.get("path"),
                    f"source_refs[{index}].path",
                )
    lines = entry.get("source_lines")
    if isinstance(lines, list):
        for index, line in enumerate(lines):
            if isinstance(line, str) and line.startswith("/"):
                # Absolute path followed by :line-range or other suffix.
                ref = line.split(":", 1)[0]
                if ref:
                    check_source_ref(
                        case,
                        root,
                        family_dir,
                        case_dir,
                        ref,
                        f"source_lines[{index}]",
                    )


def audit_declared_source_hashes(case: CaseAudit, source_path, entry):
    if not isinstance(entry, dict):
        return
    declared = entry.get("source_example_sha256")
    if declared is not None:
        if source_path is None:
            case.error("source", "source.source_example_missing", "source_example_sha256 is declared without a valid source_example")
        else:
            verify_source_hash(case, source_path, declared, "source_example_sha256")


def audit_declared_hashes_without_dir(case: CaseAudit, entry):
    """For manifest-only BLOCKED entries, reject file hash declarations that
    point at nonexistent case files.  There is no case directory to hash."""
    if not isinstance(entry, dict):
        return
    for map_key in ("hashes", "files", "bundle"):
        value = entry.get(map_key)
        if isinstance(value, dict):
            for key in value:
                if key == "source_example":
                    continue
                case.error(
                    "hashes",
                    "hashes.file_but_no_bundle",
                    f"{map_key}[{key!r}] is declared but the case has no bundle directory",
                )


def audit_case_hashes(case: CaseAudit, entry, case_dir, actual_files, source_path, source_example):
    if not isinstance(entry, dict):
        return
    actual_names = set(actual_files)
    declared_names = set()
    maps = []
    for map_key in ("hashes", "files", "bundle"):
        value = entry.get(map_key)
        if isinstance(value, dict):
            maps.append((map_key, value))

    if not maps and actual_names:
        case.error("hashes", "hashes.none_declared", "materialized case has no per-case hash declarations")

    for map_key, mapping in maps:
        for fname, declaration in mapping.items():
            if fname == "source_example":
                if source_path is None:
                    case.error("hashes", "hashes.source_target_missing", "hashes['source_example'] has no source path")
                elif isinstance(declaration, str):
                    verify_source_hash(case, source_path, declaration, f"{map_key}['source_example']")
                else:
                    case.error(
                        "hashes",
                        "hashes.unverifiable",
                        f"{map_key}['source_example'] is not a string sha256",
                    )
                continue
            declared_names.add(fname)
            path = actual_files.get(fname)
            if path is None:
                case.error(
                    "hashes",
                    "hashes.file_missing",
                    f"{map_key}[{fname!r}] is declared but not present in the case directory",
                )
                continue
            data = path.read_bytes()
            actual_sha = sha256_bytes(data)
            if isinstance(declaration, str):
                if not case.hash_verified(declaration, actual_sha):
                    case.error(
                        "hashes",
                        "hashes.mismatch",
                        f"{map_key}[{fname!r}]: declared {declaration} != actual {actual_sha}",
                    )
            elif isinstance(declaration, dict):
                sha = declaration.get("sha256")
                size = declaration.get("size", declaration.get("bytes"))
                if not isinstance(sha, str):
                    case.error(
                        "hashes",
                        "hashes.unverifiable",
                        f"{map_key}[{fname!r}] has no string sha256",
                    )
                else:
                    if not case.hash_verified(sha, actual_sha):
                        case.error(
                            "hashes",
                            "hashes.mismatch",
                            f"{map_key}[{fname!r}]: declared {sha} != actual {actual_sha}",
                        )
                if size is None:
                    case.error(
                        "hashes",
                        "hashes.unverifiable_size",
                        f"{map_key}[{fname!r}] has no declared size/bytes",
                    )
                elif not is_int(size) or size != len(data):
                    case.error(
                        "hashes",
                        "hashes.size_mismatch",
                        f"{map_key}[{fname!r}]: declared size {size!r} != actual {len(data)}",
                    )
            else:
                case.error(
                    "hashes",
                    "hashes.unverifiable",
                    f"{map_key}[{fname!r}] is neither a sha256 string nor an object",
                )

    # Aggregate hashes (recomputed from actual bytes, not from declarations).
    if "bundle_hash" in entry:
        declared = entry.get("bundle_hash")
        hashes = entry.get("hashes")
        if not isinstance(hashes, dict) or not all(isinstance(v, str) for v in hashes.values()):
            case.error(
                "hashes",
                "hashes.unverifiable_aggregate",
                "bundle_hash is present but there is no flat hashes map to recompute it",
            )
        else:
            digest = hashlib.sha256()
            ok = True
            for fname in sorted(hashes):
                path = actual_files.get(fname)
                if path is None:
                    case.error(
                        "hashes",
                        "hashes.aggregate_missing_file",
                        f"bundle_hash includes missing file {fname!r}",
                    )
                    ok = False
                    continue
                digest.update(f"{fname}\0{sha256_bytes(path.read_bytes())}\n".encode())
            if ok:
                actual = digest.hexdigest()
                if isinstance(declared, str) and case.hash_verified(declared, actual):
                    pass
                else:
                    case.error(
                        "hashes",
                        "hashes.aggregate_mismatch",
                        f"bundle_hash: declared {declared!r} != recomputed {actual}",
                    )

    if "bundle_sha256" in entry:
        declared = entry.get("bundle_sha256")
        bundle = entry.get("bundle")
        if not isinstance(bundle, dict):
            case.error(
                "hashes",
                "hashes.unverifiable_aggregate",
                "bundle_sha256 is present but there is no bundle map to recompute it",
            )
        else:
            digest = hashlib.sha256()
            ok = True
            for fname in sorted(bundle):
                path = actual_files.get(fname)
                if path is None:
                    case.error(
                        "hashes",
                        "hashes.aggregate_missing_file",
                        f"bundle_sha256 includes missing file {fname!r}",
                    )
                    ok = False
                    continue
                data = path.read_bytes()
                digest.update(fname.encode())
                digest.update(b"\0")
                digest.update(str(len(data)).encode())
                digest.update(b"\0")
                digest.update(sha256_bytes(data).encode())
                digest.update(b"\n")
            if ok:
                actual = digest.hexdigest()
                if isinstance(declared, str) and case.hash_verified(declared, actual):
                    pass
                else:
                    case.error(
                        "hashes",
                        "hashes.aggregate_mismatch",
                        f"bundle_sha256: declared {declared!r} != recomputed {actual}",
                    )

    # Every file in a materialized case must be hash-bound.
    undeclared = sorted(actual_names - declared_names)
    if undeclared:
        case.error(
            "hashes",
            "hashes.uncovered_files",
            f"actual case files not declared in any hashes/files/bundle map: {undeclared}",
        )


def audit_provenance(case: CaseAudit, actual_files, job, source_path, source_example):
    """Cross-check conv-fp16-style provenance.json against the job/source."""
    if "provenance.json" not in actual_files:
        return
    try:
        prov, _ = strict_json_load(actual_files["provenance.json"])
    except Exception as exc:
        case.error("files", "files.provenance_invalid", f"provenance.json cannot be parsed: {exc}")
        return
    if not isinstance(prov, dict):
        case.error("files", "files.provenance_invalid", "provenance.json is not an object")
        return
    if job is not None:
        if prov.get("case") not in (None, job.get("case")):
            case.error(
                "semantics",
                "semantics.provenance_case_mismatch",
                f"provenance case {prov.get('case')!r} != job case {job.get('case')!r}",
            )
        if prov.get("source_example") not in (None, job.get("source_example")):
            case.error(
                "semantics",
                "semantics.provenance_source_mismatch",
                "provenance source_example differs from job.json",
            )
        ptasks = prov.get("tasks")
        if isinstance(ptasks, list):
            compact = []
            for task in ptasks:
                if isinstance(task, dict):
                    compact.append(
                        {
                            "regcmd_offset_words": task.get("regcmd_offset_words"),
                            "regcmd_words": task.get("regcmd_words"),
                        }
                    )
            if compact != job.get("tasks"):
                case.error(
                    "semantics",
                    "semantics.provenance_tasks_mismatch",
                    f"provenance tasks {compact} != job tasks {job.get('tasks')}",
                )
    prov_source = prov.get("source_example")
    if is_nonempty_str(prov_source):
        if source_path is None:
            case.error("source", "source.provenance_source_missing", f"provenance source does not exist: {prov_source}")
        elif prov_source != source_example:
            # Different source path: verify it exists independently.
            p = Path(prov_source)
            if not p.is_file():
                case.error("source", "source.provenance_source_missing", f"provenance source does not exist: {prov_source}")
        declared = prov.get("source_sha256")
        if declared is not None and source_path is not None:
            verify_source_hash(case, source_path, declared, "provenance.source_sha256")


# ---------------------------------------------------------------------------
# Job audit


def audit_job(case: CaseAudit, root, family_dir, case_dir, name, entry, job, job_bytes, actual_files):
    if not isinstance(job, dict):
        case.error("schema", "job.not_object", "job.json is not a JSON object")
        return
    keys = set(job)
    missing = JOB_KEYS - keys
    unknown = keys - JOB_KEYS
    if missing:
        case.error("schema", "job.missing_keys", f"job.json is missing keys: {sorted(missing)}")
    if unknown:
        case.error("schema", "job.unknown_keys", f"job.json has unknown keys: {sorted(unknown)}")

    if not is_nonempty_str(job.get("case")):
        case.error("schema", "job.case_type", "job.case must be a non-empty string")
    elif job.get("case") != name:
        case.error(
            "schema",
            "job.case_mismatch",
            f"job.case {job.get('case')!r} != case directory/manifest name {name!r}",
        )
    if not is_nonempty_str(job.get("source_example")):
        case.error("schema", "job.source_type", "job.source_example must be a non-empty string")
    else:
        check_source_ref(case, root, family_dir, case_dir, job.get("source_example"), "job.source_example")
        if entry.get("source_example") and job.get("source_example") != entry.get("source_example"):
            case.error(
                "manifest",
                "manifest.source_example_mismatch",
                f"job.source_example {job.get('source_example')!r} != manifest {entry.get('source_example')!r}",
            )
    if not is_nonempty_str(job.get("description")):
        case.error("schema", "job.description_type", "job.description must be a non-empty string")
    if not is_int(job.get("timeout_ns")) or job.get("timeout_ns") <= 0:
        case.error("schema", "job.timeout_type", "job.timeout_ns must be a positive integer")

    # --- tasks
    tasks = job.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        case.error("schema", "job.tasks_type", "job.tasks must be a non-empty list")
        tasks = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            case.error("tasks", "tasks.not_object", f"tasks[{index}] is not an object")
            continue
        tkeys = set(task)
        if tkeys != TASK_KEYS:
            case.error(
                "tasks",
                "tasks.keys",
                f"tasks[{index}] keys {sorted(tkeys)} != {sorted(TASK_KEYS)}",
            )
        off = task.get("regcmd_offset_words")
        words = task.get("regcmd_words")
        if not is_int(off) or off < 0:
            case.error("tasks", "tasks.offset_type", f"tasks[{index}].regcmd_offset_words must be a non-negative integer")
        if not is_int(words) or words <= 0:
            case.error("tasks", "tasks.words_type", f"tasks[{index}].regcmd_words must be a positive integer")
    case.task_count = len(tasks)

    # --- buffers
    buffers = job.get("buffers")
    if not isinstance(buffers, list) or not buffers:
        case.error("schema", "job.buffers_type", "job.buffers must be a non-empty list")
        buffers = []
    names = set()
    output_names = set()
    input_names = set()
    for index, buffer in enumerate(buffers):
        if not isinstance(buffer, dict):
            case.error("buffers", "buffers.not_object", f"buffers[{index}] is not an object")
            continue
        bkeys = set(buffer)
        unknown_bkeys = bkeys - BUFFER_KEYS
        if unknown_bkeys:
            case.error(
                "buffers",
                "buffers.unknown_keys",
                f"buffers[{index}] has unknown keys: {sorted(unknown_bkeys)}",
            )
        bname = buffer.get("name")
        if not is_nonempty_str(bname):
            case.error("buffers", "buffers.name_type", f"buffers[{index}].name must be a non-empty string")
        elif bname in names:
            case.error("buffers", "buffers.duplicate_name", f"duplicate buffer name {bname!r}")
        else:
            names.add(bname)
        size = buffer.get("size")
        if not is_int(size) or size <= 0:
            case.error("buffers", "buffers.size_type", f"buffers[{index}].size must be a positive integer")
        direction = buffer.get("direction")
        if direction not in {"in", "out", "inout"}:
            case.error(
                "buffers",
                "buffers.direction",
                f"buffers[{index}].direction must be in/out/inout, got {direction!r}",
            )
            continue
        inp = buffer.get("input")
        out = buffer.get("output")
        if direction in {"in", "inout"}:
            if not safe_rel_name(inp):
                case.error(
                    "buffers",
                    "buffers.input_name",
                    f"buffers[{index}] direction={direction} needs a plain relative input filename, got {inp!r}",
                )
            else:
                if inp in input_names:
                    case.error("buffers", "buffers.duplicate_input", f"input file {inp!r} is used by more than one buffer")
                input_names.add(inp)
                path = case_dir / inp
                if not path.is_file():
                    case.error("buffers", "buffers.input_missing", f"buffers[{index}].input file does not exist: {inp}")
                else:
                    actual_size = path.stat().st_size
                    if is_int(size) and actual_size != size:
                        case.error(
                            "buffers",
                            "buffers.input_size_mismatch",
                            f"buffers[{index}] {bname!r}: declared size {size} != input file length {actual_size}",
                        )
        else:
            if inp is not None:
                case.error(
                    "buffers",
                    "buffers.input_for_out",
                    f"buffers[{index}] direction=out must not declare an input file",
                )
        if direction in {"out", "inout"}:
            if not safe_rel_name(out):
                case.error(
                    "buffers",
                    "buffers.output_name",
                    f"buffers[{index}] direction={direction} needs a plain relative output filename, got {out!r}",
                )
            else:
                if out in output_names:
                    case.error("buffers", "buffers.duplicate_output", f"output file {out!r} is used by more than one buffer")
                output_names.add(out)
                if (case_dir / out).exists():
                    case.error(
                        "outputs",
                        "outputs.already_present",
                        f"declared output file is already present: {out}",
                    )
                low = out.lower()
                if any(marker in low for marker in EXPECTED_NAME_MARKERS):
                    case.error(
                        "outputs",
                        "outputs.oracle_as_output",
                        f"declared output filename looks like an oracle/expected file: {out}",
                    )
        else:
            if out is not None:
                case.error(
                    "buffers",
                    "buffers.output_for_in",
                    f"buffers[{index}] direction=in must not declare an output file",
                )
    case.buffer_count = len(buffers)

    # --- patches
    patches = job.get("patches")
    if not isinstance(patches, list):
        case.error("schema", "job.patches_type", "job.patches must be a list")
        patches = []
    patch_indices = set()
    case.patch_count = len(patches)
    for index, patch in enumerate(patches):
        if not isinstance(patch, dict):
            case.error("patches", "patches.not_object", f"patches[{index}] is not an object")
            continue
        pkeys = set(patch)
        if pkeys != PATCH_KEYS:
            case.error(
                "patches",
                "patches.keys",
                f"patches[{index}] keys {sorted(pkeys)} != {sorted(PATCH_KEYS)}",
            )
        ridx = patch.get("regcmd_index")
        pbuf = patch.get("buffer")
        kind = patch.get("kind")
        if not is_int(ridx) or ridx < 0:
            case.error("patches", "patches.index_type", f"patches[{index}].regcmd_index must be a non-negative integer")
        elif ridx in patch_indices:
            case.error("patches", "patches.duplicate_index", f"duplicate patch regcmd_index {ridx}")
        else:
            patch_indices.add(ridx)
        if not is_nonempty_str(pbuf):
            case.error("patches", "patches.buffer_type", f"patches[{index}].buffer must be a non-empty string")
        elif pbuf not in names:
            case.error("patches", "patches.buffer_missing", f"patches[{index}] references unknown buffer {pbuf!r}")
        if kind not in SUPPORTED_PATCH_KINDS:
            case.error(
                "patches",
                "patches.kind",
                f"patches[{index}].kind={kind!r} is not one of {sorted(SUPPORTED_PATCH_KINDS)}",
            )

    # --- regcmd and task ranges
    regcmd_path = case_dir / "regcmd.bin"
    if not regcmd_path.is_file():
        case.error("regcmd", "regcmd.missing", "regcmd.bin is missing")
        return
    regcmd = regcmd_path.read_bytes()
    if len(regcmd) == 0:
        case.error("regcmd", "regcmd.empty", "regcmd.bin is empty")
    if len(regcmd) % 8 != 0:
        case.error("regcmd", "regcmd.length", f"regcmd.bin length {len(regcmd)} is not a multiple of 8")
    nwords = len(regcmd) // 8
    case.regcmd_qwords = nwords

    ranges = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        off = task.get("regcmd_offset_words")
        words = task.get("regcmd_words")
        if not is_int(off) or not is_int(words) or off < 0 or words <= 0:
            continue
        start = off
        end = off + words
        if end > nwords:
            case.error(
                "tasks",
                "tasks.out_of_bounds",
                f"tasks[{index}] range [{start},{end}) exceeds regcmd length {nwords} QWORDs",
            )
        ranges.append((index, start, end))

    # non-overlap in declared order: each next start must be >= previous end
    for pos in range(1, len(ranges)):
        prev_index, prev_start, prev_end = ranges[pos - 1]
        cur_index, cur_start, cur_end = ranges[pos]
        if cur_start < prev_end:
            note = ""
            repeat = entry.get("repeat_submissions") if isinstance(entry, dict) else None
            identical = (
                cur_start == prev_start
                and cur_end == prev_end
                and is_int(repeat)
                and repeat == len(tasks)
            )
            if identical:
                note = (
                    f" (manifest declares repeat_submissions={repeat}; the family README calls this an "
                    "intentional duplicate submission, but the audit's non-overlap rule is still violated)"
                )
                case.documented(
                    "tasks.overlap",
                    f"two identical task descriptors point at regcmd range [{cur_start},{cur_end})"
                    f" because the source submits the same task {repeat} times",
                    category="tasks",
                )
            case.error(
                "tasks",
                "tasks.overlap",
                f"tasks[{cur_index}] range [{cur_start},{cur_end}) overlaps tasks[{prev_index}] "
                f"range [{prev_start},{prev_end}) in declared order{note}",
            )

    # exact coverage: union of task ranges must cover every QWORD once.
    if ranges and nwords >= 0:
        covered = set()
        for _, start, end in ranges:
            covered.update(range(start, min(end, nwords)))
        missing = sorted(set(range(nwords)) - covered)
        max_end = max(end for _, _, end in ranges)
        if missing:
            # CAPTURE_FORMAT permits exactly one zero QWORD of fetch padding
            # when the declared task extent is odd.  The task descriptors keep
            # the original count; the case must record
            # regcmd_padding_words=1 and regcmd_file_words=declared+1.
            declared_padding = entry.get("regcmd_padding_words") if isinstance(entry, dict) else None
            declared_file_words = entry.get("regcmd_file_words") if isinstance(entry, dict) else None
            declared_fetch_words = entry.get("regcmd_fetch_words") if isinstance(entry, dict) else None
            declared_task_words = entry.get("regcmd_words") if isinstance(entry, dict) else None
            declared_size_bytes = entry.get("regcmd_size_bytes") if isinstance(entry, dict) else None
            task_words = 0
            for task in tasks:
                if isinstance(task, dict) and is_int(task.get("regcmd_words")):
                    task_words += task["regcmd_words"]
            trailing = all(index >= max_end for index in missing)
            all_zero = all(
                struct.unpack_from("<Q", regcmd, index * 8)[0] == 0 for index in missing
            )
            documented_pad = (
                is_int(declared_padding)
                and declared_padding == 1
                and is_int(declared_file_words)
                and declared_file_words == nwords
                and is_int(declared_task_words)
                and declared_task_words == task_words
                and task_words % 2 == 1
                and nwords == task_words + 1
                and max_end == task_words
                and missing == [task_words]
                and trailing
                and all_zero
                and (
                    declared_fetch_words is None
                    or (is_int(declared_fetch_words) and declared_fetch_words == nwords)
                )
                and (
                    declared_size_bytes is None
                    or (is_int(declared_size_bytes) and declared_size_bytes == len(regcmd))
                )
            )
            if documented_pad:
                case.accepted_padding.append(
                    {
                        "kind": "rocket_qword_pair_fetch_padding",
                        "task_words": task_words,
                        "file_words": nwords,
                        "padding_words": 1,
                        "padding_value": 0,
                        "task_extent_odd": True,
                        "note": (
                            "accepted documented one-QWORD zero fetch padding; "
                            "task descriptors keep the declared count and the pad is never executed"
                        ),
                    }
                )
            else:
                detail = (
                    f"trailing QWORD(s) at {missing[:8]} are not the single documented zero fetch pad: "
                    f"padding_words={declared_padding!r}, file_words={declared_file_words!r}, "
                    f"task_words={task_words}, nwords={nwords}, max_task_end={max_end}, "
                    f"zero={all_zero}"
                )
                case.error("regcmd", "regcmd.padding_invalid", detail)
        # A declared padding count that is not actually present is a mismatch.
        declared_padding = entry.get("regcmd_padding_words") if isinstance(entry, dict) else None
        if is_int(declared_padding) and declared_padding != len(missing):
            case.error(
                "regcmd",
                "regcmd.padding_mismatch",
                f"manifest declares regcmd_padding_words={declared_padding}, "
                f"but actual trailing padding is {len(missing)} QWORD(s)",
            )

    # patch indices and address-field convention
    task_covered_indices = set()
    for _, start, end in ranges:
        task_covered_indices.update(range(start, end))
    for index, patch in enumerate(patches):
        if not isinstance(patch, dict):
            continue
        ridx = patch.get("regcmd_index")
        if not is_int(ridx) or ridx < 0 or ridx >= nwords:
            case.error(
                "patches",
                "patches.index_out_of_range",
                f"patches[{index}].regcmd_index={ridx!r} is outside regcmd.bin ({nwords} QWORDs)",
            )
            continue
        if ridx not in task_covered_indices:
            case.error(
                "patches",
                "patches.index_outside_tasks",
                f"patches[{index}].regcmd_index={ridx} is not covered by any declared task range",
            )
        qword = struct.unpack_from("<Q", regcmd, ridx * 8)[0]
        kind = patch.get("kind")
        # The documented value32 kind replaces bits [47:16] and preserves the
        # command target/offset nibbles.  A nonzero original value field is
        # legal (it is overwritten); only the supported target/offset framing
        # is checked here.
        if kind == "value32":
            target = (qword >> 48) & 0xFFFF
            offset = qword & 0xFFFF
            if target == 0 and offset == 0:
                case.error(
                    "patches",
                    "patches.empty_command",
                    f"patches[{index}] points at QWORD {ridx} with target/offset both zero",
                )
        elif kind in {"all32", "low32", "high32"}:
            # Supported by CAPTURE_FORMAT but not exercised by this corpus.
            pass


# ---------------------------------------------------------------------------
# Oracle / expected / output separation


def _oracle_refs(entry, actual_files):
    refs = set()

    def add(value):
        if isinstance(value, str) and value and value.lower() not in {"none", "null"}:
            refs.add(value)

    oracle = entry.get("oracle")
    if isinstance(oracle, dict):
        for key in (
            "file",
            "expected",
            "mask",
            "expected_surface_file",
            "combined_expected",
        ):
            add(oracle.get(key))
        expected_files = oracle.get("expected_files")
        if isinstance(expected_files, list):
            for value in expected_files:
                add(value)
    for layout in entry.get("output_layouts", []):
        if isinstance(layout, dict):
            add(layout.get("expected"))
            add(layout.get("combined_expected"))
    for fname in actual_files:
        base = os.path.basename(fname)
        low = base.lower()
        if base.startswith("expected") or "oracle" in low:
            refs.add(fname)
    return refs


def audit_oracle_and_outputs(case: CaseAudit, entry, job, actual_files):
    refs = _oracle_refs(entry, actual_files)
    if not isinstance(entry, dict):
        return
    oracle = entry.get("oracle")
    oracle_none = isinstance(oracle, str) and oracle.strip().lower() in {"none", "null", ""}
    if isinstance(oracle, dict):
        oracle_none = str(oracle.get("kind", "")).lower() == "none"
    if case.manifest_status == "READY" and not oracle_none and not refs:
        case.error("oracle", "oracle.no_expected_file", "READY case declares an oracle but no expected file")
    for ref in sorted(refs):
        path = actual_files.get(ref)
        resolved_ref = ref
        if path is None and case.manifest_status == "BLOCKED":
            evidence_ref = f"evidence/{ref}"
            if evidence_ref in actual_files:
                path = actual_files[evidence_ref]
                resolved_ref = evidence_ref
                case.warning(
                    "oracle",
                    "oracle.blocked_evidence_path",
                    f"oracle/expected file {ref!r} resolved under blocked-case evidence/: {resolved_ref!r}",
                )
        if path is None:
            case.error("oracle", "oracle.expected_missing", f"oracle/expected file is missing: {ref}")
            continue
        # Ensure the oracle is not also a device buffer.
        if job is not None:
            for buffer in job.get("buffers", []):
                if not isinstance(buffer, dict):
                    continue
                for key in ("input", "output"):
                    if buffer.get(key) in {ref, resolved_ref}:
                        case.error(
                            "oracle",
                            "oracle.device_buffer",
                            f"oracle/expected file {resolved_ref!r} is declared as a device {key} buffer",
                        )
        # Ensure the oracle file is not one of the declared device outputs.
        if job is not None:
            for buffer in job.get("buffers", []):
                if isinstance(buffer, dict) and buffer.get("direction") in {"out", "inout"}:
                    if buffer.get("output") in {ref, resolved_ref}:
                        case.error(
                            "outputs",
                            "outputs.oracle_as_output",
                            f"oracle/expected file {resolved_ref!r} is declared as a device output",
                        )


# ---------------------------------------------------------------------------
# Manifest / job consistency and family-specific metadata


def audit_manifest_job_consistency(case: CaseAudit, family, entry, job, actual_files, case_dir):
    if not isinstance(entry, dict) or not isinstance(job, dict):
        return
    # task_count / buffer_count / patch_count
    for key, value in (
        ("task_count", job.get("tasks")),
        ("buffer_count", job.get("buffers")),
        ("patch_count", job.get("patches")),
    ):
        if key in entry and isinstance(value, list):
            if entry.get(key) != len(value):
                case.error(
                    "manifest",
                    "manifest.count_mismatch",
                    f"{key}={entry.get(key)!r} != job {len(value)}",
                )
    # tasks/rocket_tasks
    for key in ("tasks", "rocket_tasks"):
        if key in entry and isinstance(entry.get(key), list):
            if entry.get(key) != job.get("tasks"):
                case.error(
                    "manifest",
                    "manifest.tasks_mismatch",
                    f"manifest {key} {entry.get(key)!r} != job tasks {job.get('tasks')!r}",
                )
    # buffers
    if isinstance(entry.get("buffers"), list):
        expected = []
        for buffer in job.get("buffers", []):
            if isinstance(buffer, dict):
                expected.append(
                    {
                        "name": buffer.get("name"),
                        "size": buffer.get("size"),
                        "direction": buffer.get("direction"),
                        "input": buffer.get("input"),
                        "output": buffer.get("output"),
                    }
                )
        declared = []
        for buffer in entry.get("buffers", []):
            if isinstance(buffer, dict):
                declared.append(
                    {
                        "name": buffer.get("name"),
                        "size": buffer.get("size"),
                        "direction": buffer.get("direction"),
                        "input": buffer.get("input"),
                        "output": buffer.get("output"),
                    }
                )
        if declared != expected:
            case.error(
                "manifest",
                "manifest.buffers_mismatch",
                f"manifest buffers {declared!r} != job buffers {expected!r}",
            )
    # patches (allow manifest extra annotation keys)
    if isinstance(entry.get("patches"), list):
        expected = []
        for patch in job.get("patches", []):
            if isinstance(patch, dict):
                expected.append(
                    {
                        "regcmd_index": patch.get("regcmd_index"),
                        "buffer": patch.get("buffer"),
                        "kind": patch.get("kind"),
                    }
                )
        declared = []
        for patch in entry.get("patches", []):
            if isinstance(patch, dict):
                declared.append(
                    {
                        "regcmd_index": patch.get("regcmd_index"),
                        "buffer": patch.get("buffer"),
                        "kind": patch.get("kind"),
                    }
                )
        if declared != expected:
            case.error(
                "manifest",
                "manifest.patches_mismatch",
                f"manifest patches {declared!r} != job patches {expected!r}",
            )
    # regcmd word counts.  regcmd_words is the declared task extent;
    # regcmd_file_words / regcmd_fetch_words / regcmd_padding_words describe
    # the file separately (used by conv-simple for QWORD-pair fetch padding).
    actual_qwords = case.regcmd_qwords
    task_words = 0
    for task in job.get("tasks", []):
        if isinstance(task, dict) and is_int(task.get("regcmd_words")):
            task_words += task["regcmd_words"]
    if is_int(entry.get("regcmd_words")) and entry["regcmd_words"] != task_words:
        case.error(
            "manifest",
            "manifest.regcmd_words_mismatch",
            f"regcmd_words={entry['regcmd_words']} != sum of job task words {task_words}",
        )
    if is_int(entry.get("regcmd_qwords")) and actual_qwords is not None:
        if entry["regcmd_qwords"] != actual_qwords:
            case.error(
                "manifest",
                "manifest.regcmd_qwords_mismatch",
                f"regcmd_qwords={entry['regcmd_qwords']} != actual regcmd file QWORDs {actual_qwords}",
            )
    has_file_fields = any(
        is_int(entry.get(key))
        for key in ("regcmd_file_words", "regcmd_fetch_words", "regcmd_padding_words", "regcmd_size_bytes")
    )
    if is_int(entry.get("regcmd_file_words")) and actual_qwords is not None:
        if entry["regcmd_file_words"] != actual_qwords:
            case.error(
                "manifest",
                "manifest.regcmd_file_words_mismatch",
                f"regcmd_file_words={entry['regcmd_file_words']} != actual regcmd file QWORDs {actual_qwords}",
            )
    if is_int(entry.get("regcmd_fetch_words")) and actual_qwords is not None:
        if entry["regcmd_fetch_words"] != actual_qwords:
            case.error(
                "manifest",
                "manifest.regcmd_fetch_words_mismatch",
                f"regcmd_fetch_words={entry['regcmd_fetch_words']} != actual regcmd file QWORDs {actual_qwords}",
            )
    if is_int(entry.get("regcmd_size_bytes")):
        actual_bytes = (case_dir / "regcmd.bin").stat().st_size
        if entry["regcmd_size_bytes"] != actual_bytes:
            case.error(
                "manifest",
                "manifest.regcmd_size_bytes_mismatch",
                f"regcmd_size_bytes={entry['regcmd_size_bytes']} != actual regcmd.bin bytes {actual_bytes}",
            )
    if is_int(entry.get("regcmd_padding_words")) and actual_qwords is not None:
        actual_padding = actual_qwords - task_words
        if entry["regcmd_padding_words"] != actual_padding:
            case.error(
                "manifest",
                "manifest.regcmd_padding_words_mismatch",
                f"regcmd_padding_words={entry['regcmd_padding_words']} != actual file-minus-task QWORDs {actual_padding}",
            )
    if not has_file_fields and actual_qwords is not None and actual_qwords != task_words:
        case.error(
            "manifest",
            "manifest.regcmd_length_mismatch",
            f"regcmd.bin has {actual_qwords} QWORDs but declared task ranges cover {task_words}",
        )

    # generic sizes map
    sizes = entry.get("sizes")
    if isinstance(sizes, dict):
        for key, value in sizes.items():
            if not key.endswith("_bytes") or not is_int(value):
                continue
            actual = None
            if key == "regcmd_bytes":
                actual = (case_dir / "regcmd.bin").stat().st_size
            elif key == "expected_logical_bytes":
                path = actual_files.get("expected.bin")
                actual = path.stat().st_size if path else None
            elif key == "expected_surface_bytes":
                path = actual_files.get("expected_surface.bin")
                actual = path.stat().st_size if path else None
            elif key in {"input_buffer_bytes", "weight_buffer_bytes", "output_buffer_bytes"}:
                role = key.split("_", 1)[0]
                for buffer in job.get("buffers", []):
                    if isinstance(buffer, dict) and (
                        buffer.get("name") == role
                        or (role == "output" and buffer.get("name") in {"out", "output"})
                        or (role == "input" and buffer.get("name") in {"in", "input", "a"})
                    ):
                        actual = buffer.get("size")
                        break
            if actual is not None and actual != value:
                case.error(
                    "manifest",
                    "manifest.size_mismatch",
                    f"sizes.{key}={value} != actual/declared {actual}",
                )

    # output_layouts
    for index, layout in enumerate(entry.get("output_layouts", [])):
        if not isinstance(layout, dict):
            continue
        bname = layout.get("buffer")
        out_name = layout.get("output")
        expected_name = layout.get("expected")
        job_buffer = None
        for buffer in job.get("buffers", []):
            if isinstance(buffer, dict) and buffer.get("name") == bname:
                job_buffer = buffer
                break
        if job_buffer is None:
            case.error(
                "manifest",
                "manifest.output_layout_buffer_missing",
                f"output_layouts[{index}] references unknown job buffer {bname!r}",
            )
        else:
            if job_buffer.get("output") != out_name:
                case.error(
                    "manifest",
                    "manifest.output_layout_name_mismatch",
                    f"output_layouts[{index}] output {out_name!r} != job {job_buffer.get('output')!r}",
                )
            if is_int(layout.get("raw_bytes")) and job_buffer.get("size") != layout.get("raw_bytes"):
                case.error(
                    "manifest",
                    "manifest.output_layout_size_mismatch",
                    f"output_layouts[{index}] raw_bytes {layout.get('raw_bytes')} != job buffer size {job_buffer.get('size')}",
                )
        if expected_name is not None and expected_name not in actual_files:
            case.error(
                "oracle",
                "oracle.expected_missing",
                f"output_layouts[{index}] expected file missing: {expected_name}",
            )

    # generic layout input/output buffer bytes (pooling)
    layout = entry.get("layout")
    if isinstance(layout, dict):
        for side, names in (("input", {"in", "input", "a", "a0"}), ("output", {"out", "output"})):
            section = layout.get(side)
            if not isinstance(section, dict):
                continue
            declared = section.get("buffer_bytes")
            if not is_int(declared):
                continue
            job_buffer = None
            for buffer in job.get("buffers", []):
                if isinstance(buffer, dict) and buffer.get("name") in names:
                    job_buffer = buffer
                    break
            if job_buffer is None:
                case.error(
                    "manifest",
                    "manifest.layout_buffer_missing",
                    f"layout.{side} has no matching job buffer",
                )
            elif job_buffer.get("size") != declared:
                case.error(
                    "manifest",
                    "manifest.layout_size_mismatch",
                    f"layout.{side}.buffer_bytes {declared} != job buffer size {job_buffer.get('size')}",
                )


def _qword_at(regcmd: bytes, target: int, offset: int):
    for index in range(0, len(regcmd) // 8):
        qword = struct.unpack_from("<Q", regcmd, index * 8)[0]
        if (qword >> 48) & 0xFFFF == target and qword & 0xFFFF == offset:
            return index, (qword >> 16) & 0xFFFFFFFF
    return None, None


def _patch_qword_map(job, regcmd):
    out = {}
    for patch in job.get("patches", []):
        if not isinstance(patch, dict):
            continue
        ridx = patch.get("regcmd_index")
        if not is_int(ridx) or ridx < 0 or ridx * 8 + 8 > len(regcmd):
            continue
        qword = struct.unpack_from("<Q", regcmd, ridx * 8)[0]
        out[patch.get("buffer")] = {
            "index": ridx,
            "target": (qword >> 48) & 0xFFFF,
            "offset": qword & 0xFFFF,
            "kind": patch.get("kind"),
        }
    return out


def audit_manifest_semantics(case: CaseAudit, family, entry, job, actual_files, case_dir, source_path):
    if not isinstance(entry, dict) or not isinstance(job, dict):
        return
    regcmd_path = case_dir / "regcmd.bin"
    regcmd = regcmd_path.read_bytes() if regcmd_path.is_file() else b""
    qword_count = len(regcmd) // 8
    patch_map = _patch_qword_map(job, regcmd)

    # --- EW integer family
    if family == "ew-int":
        shape = entry.get("shape")
        if isinstance(shape, dict):
            width = shape.get("width")
            channels = shape.get("channels")
            elements = shape.get("elements")
            if all(is_int(v) for v in (width, channels, elements)) and elements != width * channels:
                case.error(
                    "semantics",
                    "semantics.ew_int_shape",
                    f"shape.elements={elements} != width*channels={width * channels}",
                )
        item = entry.get("output_item_size")
        if is_int(item) and item <= 0:
            case.error("semantics", "semantics.output_item_size", f"output_item_size must be positive, got {item}")
        # EW address-field positions and target IDs are checked cross-family.
        for role, expected in {
            "out": (0x1001, 0x4020),
            "a": (0x2001, 0x5018),
            "b": (0x2001, 0x5038),
        }.items():
            got = patch_map.get(role)
            if got is None:
                case.error("patches", "patches.ew_role_missing", f"EW case has no {role!r} patch")
            elif (got["target"], got["offset"]) != expected or got["kind"] != "value32":
                case.error(
                    "patches",
                    "patches.ew_role_encoding",
                    f"EW {role} patch decoded as {got!r}, expected target/offset/kind {expected + ('value32',)}",
                )

    # --- EW FP16 family
    elif family == "ew-fp16":
        logical = entry.get("logical_count")
        padded = entry.get("padded_count")
        width = entry.get("width")
        if not is_int(logical) or logical <= 0:
            case.error("semantics", "semantics.logical_count", f"logical_count must be positive, got {logical!r}")
        if not is_int(padded) or padded <= 0 or padded % 8 != 0:
            case.error("semantics", "semantics.padded_count", f"padded_count must be a positive multiple of 8, got {padded!r}")
        if is_int(padded) and is_int(width) and width != padded // 8 - 1:
            case.error(
                "semantics",
                "semantics.width",
                f"width={width} != padded_count/8-1={padded // 8 - 1}",
            )
        if is_int(logical) and is_int(padded) and logical > padded:
            case.error("semantics", "semantics.logical_gt_padded", f"logical_count {logical} > padded_count {padded}")
        oracle = entry.get("oracle")
        if isinstance(oracle, dict) and is_int(oracle.get("count")):
            actual = actual_files.get("expected.bin")
            if actual is not None and actual.stat().st_size != oracle["count"] * 2:
                case.error(
                    "oracle",
                    "oracle.expected_size",
                    f"oracle.count={oracle['count']} needs {oracle['count'] * 2} bytes, expected.bin is {actual.stat().st_size}",
                )
            if is_int(logical) and oracle["count"] != logical:
                case.error(
                    "oracle",
                    "oracle.count_mismatch",
                    f"oracle.count={oracle['count']} != logical_count={logical}",
                )
        for role, expected in {
            "out": (0x1001, 0x4020),
            "a": (0x2001, 0x5018),
            "b": (0x2001, 0x5038),
        }.items():
            got = patch_map.get(role)
            if got is None:
                case.error("patches", "patches.ew_role_missing", f"EW case has no {role!r} patch")
            elif (got["target"], got["offset"]) != expected or got["kind"] != "value32":
                case.error(
                    "patches",
                    "patches.ew_role_encoding",
                    f"EW {role} patch decoded as {got!r}, expected target/offset/kind {expected + ('value32',)}",
                )
        # EW_CFG/out_convert/RDMA values must match the manifest.
        idx_cfg, val_cfg = _qword_at(regcmd, 0x1001, 0x4070)
        idx_conv, val_conv = _qword_at(regcmd, 0x1001, 0x4084)
        idx_rdma, val_rdma = _qword_at(regcmd, 0x2001, 0x5044)
        for label, index, value, declared in (
            ("ew_cfg", idx_cfg, val_cfg, entry.get("ew_cfg")),
            ("out_convert", idx_conv, val_conv, entry.get("out_convert")),
            ("rdma_mode", idx_rdma, val_rdma, entry.get("rdma_mode")),
        ):
            if index is None:
                case.error("semantics", "semantics.ew_register_missing", f"EW register {label} not found")
            elif is_nonempty_str(declared):
                try:
                    expected_value = int(declared, 16)
                except ValueError:
                    case.error("semantics", "semantics.ew_value_unparseable", f"{label}={declared!r} is not hex")
                    expected_value = None
                if expected_value is not None and value != expected_value:
                    case.error(
                        "semantics",
                        "semantics.ew_value_mismatch",
                        f"{label}: manifest {declared} != regcmd QWORD {index} value 0x{value:08x}",
                    )
        # The manifest "width" is the RDMA count-minus-one register at
        # 0x2001/0x500c.  The DPU 0x1001/0x4004 value is a different fixed
        # datapath width and is not this field.
        _, width_value = _qword_at(regcmd, 0x2001, 0x500c)
        if is_int(width) and width_value is not None and width_value != width:
            case.error(
                "semantics",
                "semantics.width_register",
                f"width={width} != regcmd RDMA width register {width_value}",
            )

    # --- FDIV systematic family
    elif family == "fdiv-systematic":
        lanes = entry.get("lanes")
        pair_count = entry.get("pair_count")
        pairs = entry.get("pairs")
        width = entry.get("width")
        if is_int(lanes) and is_int(pair_count) and lanes != pair_count:
            case.error("semantics", "semantics.fdiv_lanes", f"lanes={lanes} != pair_count={pair_count}")
        if isinstance(pairs, list):
            if is_int(pair_count) and len(pairs) != pair_count:
                case.error("semantics", "semantics.fdiv_pairs", f"len(pairs)={len(pairs)} != pair_count={pair_count}")
            if is_int(lanes) and len(pairs) != lanes:
                case.error("semantics", "semantics.fdiv_pairs", f"len(pairs)={len(pairs)} != lanes={lanes}")
            for index, pair in enumerate(pairs):
                if not isinstance(pair, dict):
                    case.error("semantics", "semantics.fdiv_pair", f"pairs[{index}] is not an object")
                    continue
                if pair.get("lane") != index:
                    case.error(
                        "semantics",
                        "semantics.fdiv_lane_order",
                        f"pairs[{index}].lane={pair.get('lane')!r} != {index}",
                    )
        input_a = actual_files.get("input-a.bin")
        input_b = actual_files.get("input-b.bin")
        if input_a is not None and input_b is not None and isinstance(pairs, list):
            a_bytes = input_a.read_bytes()
            b_bytes = input_b.read_bytes()
            if len(a_bytes) != (lanes * 2 if is_int(lanes) else len(a_bytes)):
                case.error(
                    "semantics",
                    "semantics.fdiv_a_size",
                    f"input-a.bin is {len(a_bytes)} bytes, expected {lanes * 2 if is_int(lanes) else '?'}",
                )
            if len(b_bytes) != (lanes * 2 if is_int(lanes) else len(b_bytes)):
                case.error(
                    "semantics",
                    "semantics.fdiv_b_size",
                    f"input-b.bin is {len(b_bytes)} bytes, expected {lanes * 2 if is_int(lanes) else '?'}",
                )
            if len(a_bytes) == len(b_bytes) == (lanes * 2 if is_int(lanes) else -1):
                a_words = struct.unpack("<" + "H" * lanes, a_bytes)
                b_words = struct.unpack("<" + "H" * lanes, b_bytes)
                for index, pair in enumerate(pairs):
                    if not isinstance(pair, dict):
                        continue
                    try:
                        a_expected = int(pair["a"]["bits"], 16)
                        b_expected = int(pair["b"]["bits"], 16)
                    except Exception:
                        case.error("semantics", "semantics.fdiv_bits", f"pairs[{index}] lacks parseable a/b bits")
                        continue
                    if a_words[index] != a_expected:
                        case.error(
                            "semantics",
                            "semantics.fdiv_a_bits",
                            f"input-a.bin lane {index}=0x{a_words[index]:04x} != pairs A 0x{a_expected:04x}",
                        )
                    if b_words[index] != b_expected:
                        case.error(
                            "semantics",
                            "semantics.fdiv_b_bits",
                            f"input-b.bin lane {index}=0x{b_words[index]:04x} != pairs B 0x{b_expected:04x}",
                        )
        # FDIV register values and address fields.
        _, width_value = _qword_at(regcmd, 0x2001, 0x500c)
        if is_int(width) and width_value is not None and width_value != width:
            case.error(
                "semantics",
                "semantics.fdiv_width_register",
                f"width={width} != regcmd RDMA width register {width_value}",
            )
        for role, expected in {
            "out": (0x1001, 0x4020),
            "a": (0x2001, 0x5018),
            "b": (0x2001, 0x5038),
        }.items():
            got = patch_map.get(role)
            if got is None:
                case.error("patches", "patches.fdiv_role_missing", f"FDIV case has no {role!r} patch")
            elif (got["target"], got["offset"]) != expected or got["kind"] != "value32":
                case.error(
                    "patches",
                    "patches.fdiv_role_encoding",
                    f"FDIV {role} patch decoded as {got!r}, expected target/offset/kind {expected + ('value32',)}",
                )
        idx_cfg, val_cfg = _qword_at(regcmd, 0x1001, 0x4070)
        idx_conv, val_conv = _qword_at(regcmd, 0x1001, 0x4084)
        idx_rdma, val_rdma = _qword_at(regcmd, 0x2001, 0x5044)
        for label, index, value, declared in (
            ("ew_cfg", idx_cfg, val_cfg, entry.get("ew_cfg")),
            ("out_convert", idx_conv, val_conv, entry.get("out_convert")),
            ("rdma_mode", idx_rdma, val_rdma, entry.get("rdma_mode")),
        ):
            if index is None:
                case.error("semantics", "semantics.fdiv_register_missing", f"FDIV register {label} not found")
            elif is_nonempty_str(declared):
                try:
                    expected_value = int(declared, 16)
                except ValueError:
                    expected_value = None
                if expected_value is None:
                    case.error("semantics", "semantics.fdiv_value_unparseable", f"{label}={declared!r} is not hex")
                elif value != expected_value:
                    case.error(
                        "semantics",
                        "semantics.fdiv_value_mismatch",
                        f"{label}: manifest {declared} != regcmd value 0x{value:08x}",
                    )
        out = entry.get("output")
        if isinstance(out, dict):
            for buffer in job.get("buffers", []):
                if isinstance(buffer, dict) and buffer.get("name") == out.get("name"):
                    for field in ("size", "direction", "output"):
                        if out.get(field) != buffer.get(field):
                            case.error(
                                "manifest",
                                "manifest.fdiv_output_mismatch",
                                f"manifest output.{field}={out.get(field)!r} != job {buffer.get(field)!r}",
                            )
                    break
            else:
                case.error("manifest", "manifest.fdiv_output_missing", f"manifest output {out.get('name')!r} has no job buffer")

    # --- conv-fp16 family
    elif family == "conv-fp16":
        if isinstance(entry.get("task_count"), int) and entry["task_count"] != len(job.get("tasks", [])):
            case.error("manifest", "manifest.task_count", f"task_count {entry['task_count']} != job tasks {len(job.get('tasks', []))}")
        if isinstance(entry.get("buffer_count"), int) and entry["buffer_count"] != len(job.get("buffers", [])):
            case.error("manifest", "manifest.buffer_count", f"buffer_count {entry['buffer_count']} != job buffers {len(job.get('buffers', []))}")
        oracle = entry.get("oracle")
        if isinstance(oracle, dict):
            expected_files = oracle.get("expected_files")
            if isinstance(expected_files, list):
                for fname in expected_files:
                    if fname not in actual_files:
                        case.error("oracle", "oracle.expected_missing", f"oracle.expected_files references missing {fname!r}")
            combined = oracle.get("combined_expected")
            if is_nonempty_str(combined):
                if combined not in actual_files:
                    case.error("oracle", "oracle.expected_missing", f"combined expected file missing: {combined}")
                elif isinstance(expected_files, list) and expected_files:
                    total = sum(
                        actual_files[name].stat().st_size for name in expected_files if name in actual_files
                    )
                    if actual_files[combined].stat().st_size != total:
                        case.error(
                            "oracle",
                            "oracle.combined_size",
                            f"combined expected {combined} is {actual_files[combined].stat().st_size} bytes, sum of parts {total}",
                        )

    # --- conv-simple family
    elif family == "conv-simple":
        if is_int(entry.get("tasks")) and entry["tasks"] != len(job.get("tasks", [])):
            case.error("manifest", "manifest.task_count", f"tasks {entry['tasks']} != job tasks {len(job.get('tasks', []))}")
        oracle = entry.get("oracle")
        if isinstance(oracle, dict):
            fname = oracle.get("file")
            if is_nonempty_str(fname) and fname in actual_files:
                expected_bytes = oracle.get("expected_bytes")
                if is_int(expected_bytes) and actual_files[fname].stat().st_size != expected_bytes:
                    case.error(
                        "oracle",
                        "oracle.expected_size",
                        f"oracle.expected_bytes={expected_bytes} != {fname} size {actual_files[fname].stat().st_size}",
                    )

    # --- conv-gemm-vendor family
    elif family == "conv-gemm-vendor":
        sizes = entry.get("sizes")
        if isinstance(sizes, dict):
            for key, fname in (("expected_logical_bytes", "expected.bin"), ("expected_surface_bytes", "expected_surface.bin")):
                if is_int(sizes.get(key)) and fname in actual_files:
                    actual = actual_files[fname].stat().st_size
                    if sizes[key] != actual:
                        case.error(
                            "oracle",
                            "oracle.expected_size",
                            f"sizes.{key}={sizes[key]} != {fname} size {actual}",
                        )
        expected_oracle = entry.get("expected_oracle")
        if isinstance(expected_oracle, dict):
            shape = expected_oracle.get("shape")
            dtype = expected_oracle.get("dtype")
            if isinstance(shape, list) and is_nonempty_str(dtype) and "expected.bin" in actual_files:
                count = 1
                for dim in shape:
                    if is_int(dim):
                        count *= dim
                width = {"float16": 2, "float32": 4, "uint8": 1, "int8": 1}.get(dtype)
                if width is not None and count * width != actual_files["expected.bin"].stat().st_size:
                    case.error(
                        "oracle",
                        "oracle.expected_shape_size",
                        f"expected shape {shape} x {dtype} = {count * width} bytes != expected.bin "
                        f"{actual_files['expected.bin'].stat().st_size}",
                    )
        vendor = entry.get("vendor_task_descriptor")
        if isinstance(vendor, dict) and isinstance(job.get("tasks"), list) and job["tasks"]:
            declared = vendor.get("rocket_regcmd_count_qwords")
            actual = job["tasks"][0].get("regcmd_words") if isinstance(job["tasks"][0], dict) else None
            if is_int(declared) and is_int(actual) and declared != actual:
                case.error(
                    "manifest",
                    "manifest.vendor_regcmd_count",
                    f"vendor_task_descriptor.rocket_regcmd_count_qwords={declared} != job task words {actual}",
                )
        repeat = entry.get("repeat_submissions")
        if is_int(repeat) and isinstance(job.get("tasks"), list) and repeat != len(job["tasks"]):
            case.error(
                "manifest",
                "manifest.repeat_mismatch",
                f"repeat_submissions={repeat} != job tasks {len(job['tasks'])}",
            )

    # --- pooling family
    elif family == "pooling":
        layout = entry.get("layout")
        if isinstance(layout, dict):
            for side, names in (("input", {"in"}), ("output", {"out"})):
                section = layout.get(side)
                if not isinstance(section, dict):
                    continue
                job_buffer = None
                for buffer in job.get("buffers", []):
                    if isinstance(buffer, dict) and buffer.get("name") in names:
                        job_buffer = buffer
                        break
                if job_buffer is None:
                    case.error("manifest", "manifest.layout_buffer_missing", f"layout.{side} has no job buffer")
                elif is_int(section.get("buffer_bytes")) and section["buffer_bytes"] != job_buffer.get("size"):
                    case.error(
                        "manifest",
                        "manifest.layout_size_mismatch",
                        f"layout.{side}.buffer_bytes={section['buffer_bytes']} != job buffer size {job_buffer.get('size')}",
                    )
                logical = section.get("logical_bytes")
                if is_int(logical) and is_int(job_buffer.get("size")) and logical > job_buffer["size"]:
                    case.error(
                        "semantics",
                        "semantics.layout_logical_gt_buffer",
                        f"layout.{side}.logical_bytes={logical} > buffer size {job_buffer['size']}",
                    )
            out_section = layout.get("output")
            if isinstance(out_section, dict):
                index_bytes = out_section.get("index_bytes", 0)
                index_offset = out_section.get("index_offset")
                if out_section.get("index_en") and is_int(index_bytes) and is_int(index_offset):
                    if index_offset + index_bytes > out_section.get("buffer_bytes", 0):
                        case.error(
                            "semantics",
                            "semantics.index_out_of_range",
                            f"index region [{index_offset},{index_offset + index_bytes}) exceeds output buffer",
                        )
        oracle = entry.get("oracle")
        if isinstance(oracle, dict):
            fname = oracle.get("expected_file")
            if is_nonempty_str(fname):
                if fname not in actual_files:
                    case.error("oracle", "oracle.expected_missing", f"oracle expected file missing: {fname}")
                elif is_int(oracle.get("buffer_bytes")) and actual_files[fname].stat().st_size != oracle["buffer_bytes"]:
                    case.error(
                        "oracle",
                        "oracle.expected_size",
                        f"oracle.buffer_bytes={oracle['buffer_bytes']} != {fname} size {actual_files[fname].stat().st_size}",
                    )
                if is_int(oracle.get("logical_output_bytes")) and oracle["logical_output_bytes"] > actual_files[fname].stat().st_size:
                    case.error(
                        "oracle",
                        "oracle.logical_size",
                        f"oracle.logical_output_bytes={oracle['logical_output_bytes']} > expected file size",
                    )
        # regcmd.txt is an auxiliary decode; recompute it independently.
        txt = actual_files.get("regcmd.txt")
        if txt is not None:
            decoded = []
            try:
                for line in txt.read_text(encoding="utf-8").splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 5 and parts[0].isdigit():
                        target = int(parts[1], 16)
                        offset = int(parts[2], 16)
                        value = int(parts[3], 16)
                        decoded.append((target << 48) | ((value & 0xFFFFFFFF) << 16) | (offset & 0xFFFF))
            except Exception as exc:
                case.error("files", "files.regcmd_txt_invalid", f"regcmd.txt cannot be decoded: {exc}")
                decoded = []
            actual_qwords = [
                struct.unpack_from("<Q", regcmd, index * 8)[0] for index in range(len(regcmd) // 8)
            ]
            if decoded != actual_qwords:
                case.error(
                    "files",
                    "files.regcmd_txt_mismatch",
                    f"regcmd.txt decodes to {len(decoded)} QWORDs that differ from regcmd.bin ({len(actual_qwords)})",
                )


# ---------------------------------------------------------------------------
# Top-level manifest audit


def audit_manifest_top(root, family, family_dir, manifest, manifest_bytes, family_findings):
    verified = set()
    failed = set()
    if not isinstance(manifest, dict):
        family_findings.error("manifest.not_object", "manifest.json is not a JSON object")
        return {}, verified
    if manifest.get("family") not in (None, family):
        family_findings.error(
            "manifest.family_mismatch",
            f"manifest family {manifest.get('family')!r} != directory {family!r}",
        )

    # Schema / format document references
    for key in ("schema", "format", "format_doc"):
        value = manifest.get(key)
        if is_nonempty_str(value) and (
            value.startswith("/")
            or value.startswith("build/")
            or value.startswith("./")
            or value.startswith("../")
            or value.endswith(".md")
        ):
            path = resolve_ref(root, family_dir, None, value)
            if path is None:
                family_findings.warning(
                    "manifest.schema_path_missing",
                    f"{key}={value!r} does not resolve to an existing document",
                )

    # source_hashes map
    source_hashes = manifest.get("source_hashes")
    if isinstance(source_hashes, dict):
        for ref, declared in source_hashes.items():
            path = resolve_ref(root, family_dir, None, ref)
            if path is None:
                family_findings.error("source.path_missing", f"source_hashes path does not exist: {ref!r}")
                continue
            actual = sha256_bytes(path.read_bytes())
            if not isinstance(declared, str) or declared != actual:
                if isinstance(declared, str):
                    failed.add(declared)
                family_findings.error(
                    "hashes.source_mismatch",
                    f"source_hashes[{ref!r}]: declared {declared!r} != actual {actual}",
                )
            else:
                verified.add(actual)

    # source_examples list or dict
    source_examples = manifest.get("source_examples")
    entries = []
    if isinstance(source_examples, list):
        entries = [entry for entry in source_examples if isinstance(entry, dict)]
    elif isinstance(source_examples, dict):
        for ref, value in source_examples.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("path", ref)
                entries.append(item)
    for index, entry in enumerate(entries):
        ref = entry.get("path")
        path = resolve_ref(root, family_dir, None, ref)
        if path is None:
            family_findings.error("source.path_missing", f"source_examples[{index}] path does not exist: {ref!r}")
            continue
        actual_sha = sha256_bytes(path.read_bytes())
        declared_sha = entry.get("sha256")
        if is_nonempty_str(declared_sha):
            if declared_sha != actual_sha:
                failed.add(declared_sha)
                family_findings.error(
                    "hashes.source_mismatch",
                    f"source_examples[{index}] {ref!r}: declared {declared_sha} != actual {actual_sha}",
                )
            else:
                verified.add(actual_sha)
        declared_bytes = entry.get("bytes")
        if is_int(declared_bytes) and declared_bytes != path.stat().st_size:
            family_findings.error(
                "hashes.size_mismatch",
                f"source_examples[{index}] {ref!r}: declared bytes {declared_bytes} != actual {path.stat().st_size}",
            )

    # source_revision: selected source and examples
    revision = manifest.get("source_revision")
    selected = None
    if isinstance(revision, dict):
        selected = revision.get("selected_source")
        if is_nonempty_str(selected):
            path = resolve_ref(root, family_dir, None, selected)
            declared_sha = revision.get("selected_source_sha256")
            if path is None:
                family_findings.error("source.path_missing", f"source_revision.selected_source does not exist: {selected!r}")
            elif is_nonempty_str(declared_sha):
                actual = sha256_bytes(path.read_bytes())
                if declared_sha != actual:
                    failed.add(declared_sha)
                    family_findings.error(
                        "hashes.source_mismatch",
                        f"source_revision.selected_source_sha256: declared {declared_sha} != actual {actual}",
                    )
                else:
                    verified.add(actual)
        examples = revision.get("examples")
        if isinstance(examples, dict):
            for name, item in examples.items():
                if not isinstance(item, dict):
                    continue
                ref = item.get("path")
                path = resolve_ref(root, family_dir, None, ref)
                if path is None:
                    family_findings.error("source.path_missing", f"source_revision.examples[{name!r}] path does not exist: {ref!r}")
                    continue
                declared_sha = item.get("sha256")
                if is_nonempty_str(declared_sha):
                    actual = sha256_bytes(path.read_bytes())
                    if declared_sha != actual:
                        failed.add(declared_sha)
                        family_findings.error(
                            "hashes.source_mismatch",
                            f"source_revision.examples[{name!r}]: declared {declared_sha} != actual {actual}",
                        )
                    else:
                        verified.add(actual)
                declared_lines = item.get("lines")
                if is_int(declared_lines) and declared_lines <= 0:
                    family_findings.error("hashes.size_mismatch", f"source_revision.examples[{name!r}].lines must be positive")

    # artifacts map (family-root files)
    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, dict):
        for name, declaration in artifacts.items():
            path = resolve_ref(root, family_dir, None, name)
            if path is None:
                family_findings.error("hashes.file_missing", f"artifact file does not exist: {name!r}")
                continue
            if not isinstance(declaration, dict):
                family_findings.error("hashes.unverifiable", f"artifacts[{name!r}] is not an object")
                continue
            actual = sha256_bytes(path.read_bytes())
            declared_sha = declaration.get("sha256")
            if not is_nonempty_str(declared_sha) or declared_sha != actual:
                if is_nonempty_str(declared_sha):
                    failed.add(declared_sha)
                family_findings.error(
                    "hashes.mismatch",
                    f"artifacts[{name!r}]: declared {declared_sha!r} != actual {actual}",
                )
            else:
                verified.add(actual)
            declared_bytes = declaration.get("bytes")
            if is_int(declared_bytes) and declared_bytes != path.stat().st_size:
                family_findings.error(
                    "hashes.size_mismatch",
                    f"artifacts[{name!r}]: declared bytes {declared_bytes} != actual {path.stat().st_size}",
                )

    # preparation_tools / tool_versions (generator and validator hashes)
    preparation_tools = manifest.get("preparation_tools")
    if isinstance(preparation_tools, dict):
        for name, declaration in preparation_tools.items():
            path = family_dir / "tools" / name
            if not path.is_file():
                family_findings.error("hashes.file_missing", f"preparation_tools file does not exist: {path}")
                continue
            if not isinstance(declaration, dict):
                family_findings.error("hashes.unverifiable", f"preparation_tools[{name!r}] is not an object")
                continue
            actual = sha256_bytes(path.read_bytes())
            declared_sha = declaration.get("sha256")
            if not is_nonempty_str(declared_sha) or declared_sha != actual:
                if is_nonempty_str(declared_sha):
                    failed.add(declared_sha)
                family_findings.error(
                    "hashes.mismatch",
                    f"preparation_tools[{name!r}]: declared {declared_sha!r} != actual {actual}",
                )
            else:
                verified.add(actual)
            declared_bytes = declaration.get("size", declaration.get("bytes"))
            if is_int(declared_bytes) and declared_bytes != path.stat().st_size:
                family_findings.error(
                    "hashes.size_mismatch",
                    f"preparation_tools[{name!r}]: declared size {declared_bytes} != actual {path.stat().st_size}",
                )

    tool_versions = manifest.get("tool_versions")
    if isinstance(tool_versions, dict):
        generator = tool_versions.get("generator")
        generator_sha = tool_versions.get("generator_sha256")
        if is_nonempty_str(generator) and is_nonempty_str(generator_sha):
            path = resolve_ref(root, family_dir, None, generator)
            if path is None:
                family_findings.error("source.path_missing", f"tool_versions.generator does not exist: {generator!r}")
            else:
                actual = sha256_bytes(path.read_bytes())
                if generator_sha != actual:
                    failed.add(generator_sha)
                    family_findings.error(
                        "hashes.mismatch",
                        f"tool_versions.generator_sha256: declared {generator_sha} != actual {actual}",
                    )
                else:
                    verified.add(actual)
        tools_dir = family_dir / "tools"
        for key, value in tool_versions.items():
            if not key.endswith("_sha256") or key == "generator_sha256":
                continue
            if not is_nonempty_str(value):
                family_findings.error("hashes.unverifiable", f"tool_versions.{key} is not a string sha256")
                continue
            matched = []
            if tools_dir.is_dir():
                for candidate in sorted(tools_dir.iterdir()):
                    if candidate.is_file() and sha256_bytes(candidate.read_bytes()) == value:
                        matched.append(candidate.name)
            if not matched:
                family_findings.error(
                    "hashes.unverifiable",
                    f"tool_versions.{key}={value} does not match any file under {tools_dir}",
                )
            else:
                verified.add(value)

    # Summary/count consistency
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        family_findings.error("manifest.cases_type", "manifest.cases is missing or not a list")
        cases = []
    statuses = Counter()
    names = []
    for entry in cases:
        if not isinstance(entry, dict):
            family_findings.error("manifest.case_not_object", "manifest.cases contains a non-object entry")
            continue
        name = entry.get("case")
        names.append(name)
        statuses[entry.get("status")] += 1
    for name, count in Counter(names).items():
        if count > 1:
            family_findings.error("manifest.duplicate_case", f"manifest case {name!r} appears {count} times")
    actual_ready = statuses.get("READY", 0)
    actual_blocked = statuses.get("BLOCKED", 0)
    actual_total = len(cases)
    for key in ("counts", "summary", "readiness"):
        value = manifest.get(key)
        if not isinstance(value, dict):
            continue
        pairs = {
            "READY": value.get("READY", value.get("ready")),
            "BLOCKED": value.get("BLOCKED", value.get("blocked")),
            "total": value.get("total"),
        }
        for label, declared in pairs.items():
            if declared is None:
                continue
            actual = {"READY": actual_ready, "BLOCKED": actual_blocked, "total": actual_total}[label]
            if declared != actual:
                family_findings.error(
                    "manifest.counts_mismatch",
                    f"{key}.{label}={declared} != actual {actual}",
                )

    return {
        "cases": cases,
        "statuses": statuses,
        "verified_hash_values": verified,
        "failed_hash_values": failed,
    }, verified, failed


# ---------------------------------------------------------------------------
# Cross-family checks


def audit_cross_family(root, families, family_results):
    findings = Findings()
    job_schemas = Counter()
    buffer_schemas = Counter()
    buffer_schema_by_direction = {}
    patch_kinds = Counter()
    ew_patch_signatures = {}
    ew_op_signatures = {}
    fd_overlap = []
    task_exceptions = []
    multi_task_cases = []
    case_names = Counter()
    buffer_name_sizes = Counter()
    schema_labels = {}
    source_revisions = {}

    for family in families:
        manifest_path = root / family / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        schema_labels[family] = {
            "schema": manifest.get("schema"),
            "format": manifest.get("format"),
            "format_doc": manifest.get("format_doc"),
        }
        revision = manifest.get("source_revision")
        if isinstance(revision, dict):
            source_revisions[family] = {
                "rknpu_fpga": revision.get("rknpu-fpga", revision.get("rknpu_fpga_git")),
                "rk3588": revision.get("rk3588", revision.get("rk3588_git", revision.get("git_revision"))),
            }
        elif isinstance(revision, str):
            source_revisions[family] = {"rk3588": revision}

    for family, data in family_results.items():
        for case in data["cases"]:
            case_names[case["case"]] += 1
            job = data.get("_jobs", {}).get(case["case"])
            if not isinstance(job, dict):
                continue
            job_schemas[tuple(sorted(job))] += 1
            for buffer in job.get("buffers", []):
                if isinstance(buffer, dict):
                    buffer_schemas[(buffer.get("direction"), tuple(sorted(buffer)))] += 1
                    buffer_schema_by_direction.setdefault(buffer.get("direction"), set()).add(tuple(sorted(buffer)))
                    buffer_name_sizes[(family, buffer.get("name"), buffer.get("size"))] += 1
            for patch in job.get("patches", []):
                if isinstance(patch, dict):
                    patch_kinds[patch.get("kind")] += 1

            # EW role/field signature
            regcmd_path = root / family / "cases" / case["case"] / "regcmd.bin"
            if not regcmd_path.is_file():
                continue
            regcmd = regcmd_path.read_bytes()
            patch_map = _patch_qword_map(job, regcmd)
            for role in ("out", "a", "b"):
                got = patch_map.get(role)
                if got is not None:
                    ew_patch_signatures.setdefault(family, Counter())[
                        (role, got.get("target"), got.get("offset"), got.get("kind"))
                    ] += 1

            if family in {"ew-fp16", "fdiv-systematic"}:
                _, cfg = _qword_at(regcmd, 0x1001, 0x4070)
                _, conv = _qword_at(regcmd, 0x1001, 0x4084)
                _, rdma = _qword_at(regcmd, 0x2001, 0x5044)
                entry = data.get("_entries", {}).get(case["case"], {})
                op = "FDIV" if family == "fdiv-systematic" else entry.get("op")
                signature = (cfg, conv, rdma)
                ew_op_signatures.setdefault(op, Counter())[signature] += 1
                if family == "ew-fp16" and op == "FDIV":
                    fd_overlap.append(
                        {
                            "family": family,
                            "case": case["case"],
                            "cfg": cfg,
                            "out_convert": conv,
                            "rdma": rdma,
                            "patches": {
                                role: (
                                    patch_map.get(role, {}).get("target"),
                                    patch_map.get(role, {}).get("offset"),
                                    patch_map.get(role, {}).get("kind"),
                                )
                                for role in ("out", "a", "b")
                            },
                        }
                    )
                elif family == "fdiv-systematic":
                    fd_overlap.append(
                        {
                            "family": family,
                            "case": case["case"],
                            "cfg": cfg,
                            "out_convert": conv,
                            "rdma": rdma,
                            "patches": {
                                role: (
                                    patch_map.get(role, {}).get("target"),
                                    patch_map.get(role, {}).get("offset"),
                                    patch_map.get(role, {}).get("kind"),
                                )
                                for role in ("out", "a", "b")
                            },
                        }
                    )

            # duplicate task ranges are already a per-case error; record the
            # cross-family exception explicitly.
            tasks = job.get("tasks")
            if isinstance(tasks, list) and len(tasks) > 1:
                multi_task_cases.append(
                    {
                        "family": family,
                        "case": case["case"],
                        "task_count": len(tasks),
                        "tasks": tasks,
                    }
                )
                ranges = []
                for task in tasks:
                    if isinstance(task, dict):
                        ranges.append((task.get("regcmd_offset_words"), task.get("regcmd_words")))
                for index in range(1, len(ranges)):
                    prev_start, prev_words = ranges[index - 1]
                    cur_start, cur_words = ranges[index]
                    if is_int(prev_start) and is_int(prev_words) and is_int(cur_start):
                        if cur_start < prev_start + prev_words:
                            task_exceptions.append(
                                {
                                    "family": family,
                                    "case": case["case"],
                                    "tasks": ranges,
                                    "note": "declared task ranges overlap in declared order; see case error tasks.overlap",
                                }
                            )

    # 1. Job/buffer schema consistency
    if len(job_schemas) > 1:
        findings.error(
            "cross.job_schema",
            f"job.json top-level key sets differ across families: {dict(job_schemas)}",
        )
    for direction, key_sets in buffer_schema_by_direction.items():
        if len(key_sets) > 1:
            findings.warning(
                "cross.buffer_schema",
                f"{direction} buffer key sets differ across families: {sorted(key_sets)}",
            )

    # Metadata labels and source revisions are family-specific but should not
    # silently disagree on the same reference.
    schema_shapes = Counter(
        (value.get("schema") is not None, value.get("format") is not None, value.get("format_doc") is not None)
        for value in schema_labels.values()
    )
    schema_names = {
        value.get("schema") for value in schema_labels.values() if isinstance(value.get("schema"), str)
    }
    format_names = {
        value.get("format") for value in schema_labels.values() if isinstance(value.get("format"), str)
    }
    if len(schema_shapes) > 1:
        findings.warning(
            "cross.schema_fields",
            "families use different schema/format field names: "
            + ", ".join(f"{family}={value}" for family, value in schema_labels.items()),
        )
    if len(schema_names) > 1 or len(format_names) > 1:
        findings.warning(
            "cross.schema_label",
            f"schema labels differ across families: schema={sorted(schema_names)}, format={sorted(format_names)}",
        )
    rk3588_revisions = {
        family: value.get("rk3588")
        for family, value in source_revisions.items()
        if value.get("rk3588")
    }
    if len(set(rk3588_revisions.values())) > 1:
        findings.warning(
            "cross.rk3588_revision",
            f"manifests bind different rk3588 revisions: {rk3588_revisions}",
        )
    rknpu_revisions = {
        family: value.get("rknpu_fpga")
        for family, value in source_revisions.items()
        if value.get("rknpu_fpga")
    }
    if len(set(rknpu_revisions.values())) > 1:
        findings.warning(
            "cross.rknpu_fpga_revision",
            f"manifests bind different rknpu-fpga revisions: {rknpu_revisions}",
        )

    # 2. Patch convention
    if set(patch_kinds) - SUPPORTED_PATCH_KINDS:
        findings.error("cross.patch_kind", f"unsupported patch kinds present: {sorted(set(patch_kinds) - SUPPORTED_PATCH_KINDS)}")
    if set(patch_kinds) != {"value32"}:
        findings.warning("cross.patch_kind", f"patch kinds used: {dict(patch_kinds)}; corpus is expected to use value32 only")

    # 3. EW register encoding for overlapping op families
    expected_ew = {
        "out": (0x1001, 0x4020, "value32"),
        "a": (0x2001, 0x5018, "value32"),
        "b": (0x2001, 0x5038, "value32"),
    }
    for family in ("ew-int", "ew-fp16", "fdiv-systematic"):
        if family not in ew_patch_signatures:
            continue
        for signature, count in ew_patch_signatures[family].items():
            role, target, offset, kind = signature
            if signature != (role,) + expected_ew.get(role, (None, None, None)):
                findings.error(
                    "cross.ew_patch_encoding",
                    f"{family}: {role} patch signature {signature} != expected {expected_ew.get(role)}",
                )
    # FDIV overlap: the op encoding and patch layout must agree across the two
    # independently prepared FDIV families.
    if fd_overlap:
        signatures = Counter(
            (item["cfg"], item["out_convert"], item["rdma"], tuple(item["patches"].items()))
            for item in fd_overlap
        )
        if len(signatures) != 1:
            findings.error(
                "cross.fdiv_overlap",
                f"FDIV register/patch signatures differ across ew-fp16 and fdiv-systematic: {dict(signatures)}",
            )
        else:
            fdiv_signature_note = (
                "FDIV signature is identical across ew-fp16 and fdiv-systematic; "
                "case-variable width/output-scale QWORDs are excluded from this comparison"
            )
    else:
        fdiv_signature_note = "no FDIV cases found"
    # Same-op consistency inside ew-fp16/fdiv.
    for op, signatures in ew_op_signatures.items():
        if len(signatures) > 1:
            findings.error(
                "cross.ew_op_signature",
                f"{op}: multiple EW_CFG/out_convert/rdma signatures across cases: {dict(signatures)}",
            )

    # 4. FDIV outside local RTL whitelist (documented, not a bundle error).
    interface = root.parent.parent / "docs" / "INTERFACE.md"
    if interface.is_file():
        text = interface.read_text(encoding="utf-8", errors="replace")
        supported = {}
        for match in re.finditer(r"(ADD|SUB|MUL|MAX)=0x([0-9a-fA-F]+)", text):
            supported[match.group(1)] = int(match.group(2), 16)
        if supported:
            for family in ("ew-fp16",):
                data = family_results.get(family, {})
                for case in data.get("cases", []):
                    job = data.get("_jobs", {}).get(case["case"])
                    if not isinstance(job, dict):
                        continue
                    entry = data.get("_entries", {}).get(case["case"], {})
                    op = entry.get("op")
                    declared = entry.get("ew_cfg")
                    if op in supported and is_nonempty_str(declared):
                        if int(declared, 16) != supported[op]:
                            findings.error(
                                "cross.ew_cfg_doc",
                                f"{family}/{case['case']}: {op} EW_CFG {declared} != docs/INTERFACE.md 0x{supported[op]:08x}",
                            )
            fdiv_cfg = "0x108303c0"
            if "FDIV" not in supported:
                fdiv_local_rtl_note = (
                    f"FDIV uses EW_CFG {fdiv_cfg}; docs/INTERFACE.md does not admit FDIV in the local RTL whitelist. "
                    "This is a device-capture configuration, not an RTL-supported operation."
                )
            else:
                fdiv_local_rtl_note = "FDIV is admitted by docs/INTERFACE.md."
        else:
            fdiv_local_rtl_note = "docs/INTERFACE.md has no parseable EW_CFG table; EW_CFG/doc cross-check skipped."
    else:
        fdiv_local_rtl_note = "docs/INTERFACE.md not available; EW_CFG/doc cross-check skipped."

    # 5. Duplicate case names across families are not expected.
    for name, count in case_names.items():
        if count > 1:
            findings.warning("cross.duplicate_case", f"case name {name!r} appears in {count} families")

    # 6. Task range overlap exceptions
    if task_exceptions:
        findings.error(
            "cross.task_overlap",
            f"{len(task_exceptions)} multi-task case(s) declare overlapping ranges: "
            + ", ".join(f"{item['family']}/{item['case']}" for item in task_exceptions),
        )

    # 7. No silently conflicting buffer sizes: every manifest/job/actual
    # declaration was checked per case.  Report same-name/same-size counts so a
    # reviewer can see the corpus consistency without treating legitimate
    # case-shape differences as conflicts.
    per_case_conflicts = []
    for family, data in family_results.items():
        for case in data["cases"]:
            for error in case["errors"]:
                if error["code"] in {
                    "buffers.input_size_mismatch",
                    "manifest.buffers_mismatch",
                    "manifest.size_mismatch",
                    "manifest.layout_size_mismatch",
                    "manifest.output_layout_size_mismatch",
                }:
                    per_case_conflicts.append(
                        {"family": family, "case": case["case"], "code": error["code"], "message": error["message"]}
                    )
    if per_case_conflicts:
        findings.error(
            "cross.buffer_size_conflict",
            f"{len(per_case_conflicts)} case-level buffer-size conflict(s); see per-case errors",
        )

    return {
        **findings.as_json(),
        "job_schema": {
            "top_level_key_sets": [{"keys": list(keys), "count": count} for keys, count in job_schemas.items()],
            "buffer_key_sets": [
                {"direction": direction, "keys": list(keys), "count": count}
                for (direction, keys), count in buffer_schemas.items()
            ],
            "consistent": len(job_schemas) == 1,
        },
        "patch_convention": {
            "kinds": dict(patch_kinds),
            "value32_definition": "replace command bits [47:16] with the 32-bit DMA address; preserve target[63:48] and offset[15:0]",
            "all_value32": set(patch_kinds) == {"value32"},
        },
        "ew_encoding": {
            "encoding": "(target << 48) | ((value & 0xffffffff) << 16) | offset",
            "patch_signatures": {
                family: [
                    {"role": role, "target": target, "offset": offset, "kind": kind, "count": count}
                    for (role, target, offset, kind), count in signatures.items()
                ]
                for family, signatures in ew_patch_signatures.items()
            },
            "op_signatures": {
                op: [
                    {"ew_cfg": cfg, "out_convert": conv, "rdma_mode": rdma, "count": count}
                    for (cfg, conv, rdma), count in signatures.items()
                ]
                for op, signatures in ew_op_signatures.items()
            },
            "fdiv_overlap_cases": len(fd_overlap),
            "fdiv_overlap_note": fdiv_signature_note,
            "fdiv_local_rtl_note": fdiv_local_rtl_note,
        },
        "task_range_exceptions": task_exceptions,
        "multi_task_cases": multi_task_cases,
        "schema_labels": schema_labels,
        "source_revisions": source_revisions,
        "case_names_across_families": {
            "unique": len(case_names) == sum(case_names.values()),
            "duplicates": {name: count for name, count in case_names.items() if count > 1},
        },
    }


# ---------------------------------------------------------------------------
# Result assembly


def render_markdown(result):
    lines = []
    lines.append("# Independent RK3588 capture bundle audit")
    lines.append("")
    lines.append(f"**Audit status: {result['summary']['status']}**")
    lines.append("")
    lines.append(f"- Parser: `{result['parser']['name']}` version `{result['parser']['version']}`")
    lines.append(f"- Parser source SHA-256: `{result['parser']['sha256']}`")
    lines.append(f"- Generated (UTC): {result['generated_utc']}")
    lines.append(f"- Snapshot window (UTC): {result['snapshot']['start_utc']} .. {result['snapshot']['end_utc']}")
    lines.append(f"- Snapshot tree SHA-256: `{result['snapshot']['tree_sha256']}`")
    lines.append(f"- Python: {result['environment']['python']}")
    lines.append(f"- Platform: {result['environment']['platform']}")
    lines.append(f"- rknpu-fpga revision at audit: `{result['environment']['rknpu_fpga_revision']}`")
    lines.append(f"- rk3588 revision at audit: `{result['environment']['rk3588_revision']}`")
    lines.append(f"- CAPTURE_FORMAT.md: `{result['capture_format']['sha256']}` ({result['capture_format']['bytes']} bytes)")
    lines.append("")
    lines.append("## Commands used")
    lines.append("")
    lines.append("```")
    for command in result["commands"]:
        lines.append(command)
    lines.append("```")
    lines.append("")
    lines.append("No `ssh`, `scp`, board access, device submit, FPGA programming or flash operation was performed.")
    lines.append("This audit did not modify any family bundle, tracked source, test or documentation file.")
    lines.append("")
    if result.get("determinism"):
        lines.append("## Declared determinism / seeds")
        lines.append("")
        for family, value in result["determinism"].items():
            lines.append(f"- {family}: `{value}`")
        lines.append("")
        lines.append("The audit itself uses no RNG and no seed.")
        lines.append("")
    lines.append("## Per-family results")
    lines.append("")
    lines.append("| Family | Manifest entries | Bundle dirs | READY | BLOCKED | INVALID | Verdict |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for family in result["family_order"]:
        data = result["families"][family]
        counts = data["counts"]
        lines.append(
            f"| {family} | {counts['manifest_entries']} | {counts['bundle_dirs']} | "
            f"{counts['READY']} | {counts['BLOCKED']} | {counts['INVALID']} | {data['verdict']} |"
        )
    summary = result["summary"]
    lines.append(
        f"| **TOTAL** | **{summary['manifest_entries']}** | **{summary['bundle_dirs']}** | "
        f"**{summary['READY']}** | **{summary['BLOCKED']}** | **{summary['INVALID']}** | **{summary['status']}** |"
    )
    lines.append("")
    lines.append(
        "Counts are over the union of manifest entries and bundles present under `cases/`. "
        "A manifest `BLOCKED` case is counted BLOCKED only when its probe/bundle structure is valid; "
        "structural errors make the case INVALID."
    )
    lines.append("")
    lines.append(
        f"**Case status: {summary.get('case_status')}** "
        f"({summary['READY']} READY / {summary['BLOCKED']} BLOCKED / {summary['INVALID']} INVALID). "
        f"**Provenance/cross-family status: {summary.get('provenance_status')}** "
        f"({summary.get('family_errors', 0)} family-level errors, "
        f"{summary.get('cross_family_errors', 0)} cross-family errors, "
        f"{summary.get('live_changes', 0)} live-tree changes)."
    )
    lines.append("")
    if summary.get("documented_deviations", 0):
        lines.append("### Documented-exception view")
        lines.append("")
        lines.append(
            "The strict counts above apply the stated audit contract literally. "
            "The table below reclassifies a case as its manifest status only when every one of its "
            "errors is an explicitly documented deviation. It is shown for transparency and is not "
            "the primary verdict."
        )
        lines.append("")
        lines.append("| Family | READY | BLOCKED | INVALID |")
        lines.append("|---|---:|---:|---:|")
        for family in result["family_order"]:
            counts = result["families"][family]["counts"]
            lines.append(
                f"| {family} | {counts.get('exception_READY', 0)} | "
                f"{counts.get('exception_BLOCKED', 0)} | {counts.get('exception_INVALID', 0)} |"
            )
        lines.append(
            f"| **TOTAL** | **{summary.get('exception_READY', 0)}** | "
            f"**{summary.get('exception_BLOCKED', 0)}** | **{summary.get('exception_INVALID', 0)}** |"
        )
        lines.append("")
        lines.append(
            f"Documented deviations found: {summary.get('documented_deviations', 0)}. "
            f"Status if all documented deviations were accepted: "
            f"{summary.get('status_if_documented_deviations_accepted')}."
        )
        lines.append("")
    lines.append(
        f"Checked {summary.get('jobs_checked', 0)} jobs, {summary.get('buffers_checked', 0)} buffers, "
        f"{summary.get('tasks_checked', 0)} task descriptors, {summary.get('patches_checked', 0)} patches, "
        f"and {summary.get('hashes_declared', 0)} per-case hashes "
        f"({summary.get('hashes_verified', 0)} verified)."
    )
    lines.append(
        f"Manifest-level 64-hex hash strings: {summary.get('manifest_hash_strings', 0)}; "
        f"unverified by audit: {summary.get('manifest_hashes_unverified', 0)}."
    )
    lines.append("")
    lines.append("## Errors")
    lines.append("")
    any_error = False
    for family in result["family_order"]:
        data = result["families"][family]
        family_errors = data["errors"]
        case_errors = [
            (case["case"], error)
            for case in data["cases"]
            for error in case["errors"]
        ]
        if not family_errors and not case_errors:
            continue
        any_error = True
        lines.append(f"### {family}")
        lines.append("")
        for error in family_errors:
            lines.append(f"- FAMILY `{error['code']}`: {error['message']}")
        for case_name, error in case_errors:
            lines.append(f"- `{case_name}` `{error['code']}`: {error['message']}")
        lines.append("")
    if not any_error:
        lines.append("No errors.")
        lines.append("")

    case_warnings = []
    for family in result["family_order"]:
        for case in result["families"][family]["cases"]:
            for warning in case.get("warnings", []):
                case_warnings.append((family, case["case"], warning))
    if case_warnings:
        lines.append("## Case warnings")
        lines.append("")
        for family, case_name, warning in case_warnings:
            lines.append(f"- `{family}/{case_name}` `{warning['code']}`: {warning['message']}")
        lines.append("")

    cross = result["cross_family"]
    lines.append("## Cross-family findings")
    lines.append("")
    if cross["errors"]:
        for error in cross["errors"]:
            lines.append(f"- ERROR `{error['code']}`: {error['message']}")
    else:
        lines.append("- No cross-family errors.")
    if cross["warnings"]:
        for warning in cross["warnings"]:
            lines.append(f"- WARNING `{warning['code']}`: {warning['message']}")
    lines.append("")
    lines.append(
        f"- Job schema top-level keys consistent: {cross['job_schema']['consistent']} "
        f"({cross['job_schema']['top_level_key_sets']})"
    )
    lines.append(
        f"- Patch kinds: {cross['patch_convention']['kinds']}; all value32: "
        f"{cross['patch_convention']['all_value32']}"
    )
    lines.append(
        f"- EW encoding: `{cross['ew_encoding']['encoding']}`; "
        f"FDIV overlap cases compared: {cross['ew_encoding']['fdiv_overlap_cases']}"
    )
    lines.append(f"  - {cross['ew_encoding'].get('fdiv_overlap_note', '')}")
    lines.append(f"  - {cross['ew_encoding'].get('fdiv_local_rtl_note', '')}")
    for family, signatures in cross["ew_encoding"]["patch_signatures"].items():
        formatted = [
            {
                "role": item["role"],
                "target": f"0x{item['target']:04x}",
                "offset": f"0x{item['offset']:04x}",
                "kind": item["kind"],
                "count": item["count"],
            }
            for item in signatures
        ]
        lines.append(f"  - {family}: {formatted}")
    for op, signatures in cross["ew_encoding"]["op_signatures"].items():
        formatted = [
            {
                "ew_cfg": f"0x{item['ew_cfg']:08x}" if item.get("ew_cfg") is not None else None,
                "out_convert": f"0x{item['out_convert']:08x}" if item.get("out_convert") is not None else None,
                "rdma_mode": f"0x{item['rdma_mode']:08x}" if item.get("rdma_mode") is not None else None,
                "count": item["count"],
            }
            for item in signatures
        ]
        lines.append(f"  - op {op}: {formatted}")
    if cross["task_range_exceptions"]:
        lines.append("- Task-range exceptions:")
        for item in cross["task_range_exceptions"]:
            lines.append(
                f"  - {item['family']}/{item['case']} tasks={item['tasks']}: {item['note']}"
            )
    lines.append("")
    if cross.get("schema_labels"):
        lines.append("Schema/format labels:")
        for family, value in cross["schema_labels"].items():
            lines.append(f"  - {family}: {value}")
    if cross.get("source_revisions"):
        lines.append("Declared source revisions:")
        for family, value in cross["source_revisions"].items():
            lines.append(f"  - {family}: {value}")
    lines.append("")

    documented = []
    for family in result["family_order"]:
        for case in result["families"][family]["cases"]:
            for deviation in case.get("documented_deviations", []):
                documented.append((family, case["case"], deviation))
    if documented:
        lines.append("## Documented deviations")
        lines.append("")
        lines.append(
            "These are explicitly documented in the family manifest/README and verified against the "
            "actual bytes, but they still fail the literal audit contract; the strict counts above treat "
            "them as INVALID. The documented-exception view above reclassifies the affected cases."
        )
        lines.append("")
        for family, case_name, deviation in documented:
            lines.append(f"- `{family}/{case_name}` `{deviation['code']}`: {deviation['message']}")
        lines.append("")

    accepted_padding = []
    for family in result["family_order"]:
        for case in result["families"][family]["cases"]:
            for item in case.get("accepted_padding", []):
                accepted_padding.append((family, case["case"], item))
    if result.get("format_observations"):
        lines.append("## Format observations not applied to case status")
        lines.append("")
        for observation in result["format_observations"]:
            lines.append(f"- `{observation['code']}`: {observation['message']}")
            for item in observation.get("cases", []):
                lines.append(
                    f"  - `{item['family']}/{item['case']}`: {item['task_count']} tasks"
                )
        lines.append("")
    if accepted_padding:
        lines.append("## Accepted Rocket fetch parity padding")
        lines.append("")
        lines.append(
            "CAPTURE_FORMAT permits exactly one zero QWORD of fetch-only padding when the declared "
            "task extent is odd. The task descriptor keeps the declared count; the case must record "
            "`regcmd_padding_words=1` and `regcmd_file_words=declared+1`. These cases were accepted "
            "after verifying the odd task extent, the exact one-QWORD trailing zero, and both fields."
        )
        lines.append("")
        for family, case_name, item in accepted_padding:
            lines.append(
                f"- `{family}/{case_name}`: task words {item['task_words']}, file words "
                f"{item['file_words']}, padding {item['padding_words']} x 0x{item['padding_value']:x}"
            )
        lines.append("")

    lines.append("## Blocked cases")
    lines.append("")
    for family in result["family_order"]:
        data = result["families"][family]
        blocked = [case for case in data["cases"] if case["audit_status"] == "BLOCKED"]
        if not blocked:
            continue
        lines.append(f"### {family} ({len(blocked)})")
        lines.append("")
        for case in blocked:
            entry = case.get("blocked_reason") or ""
            lines.append(f"- `{case['case']}`: {entry}")
        lines.append("")

    lines.append("## What was checked")
    lines.append("")
    lines.append("- `job.json` keys/types against CAPTURE_FORMAT.md; duplicate JSON keys rejected.")
    lines.append("- Unique case names, buffer names, input names and output names.")
    lines.append("- Buffer sizes exactly equal input file lengths; output files absent.")
    lines.append("- `regcmd.bin` length multiple of 8; task ranges in bounds, in declared order, non-overlapping, and covering the command extent. Exactly one documented zero QWORD of Rocket QWORD-pair fetch padding is accepted only when the task extent is odd and both `regcmd_padding_words=1` and `regcmd_file_words=declared+1` are recorded; any other trailing data is rejected.")
    lines.append("- Every patch index in range, inside a declared task range, kind supported, referenced buffer present; no duplicate patch index.")
    lines.append("- Expected/oracle files never used as device inputs or outputs.")
    lines.append("- Manifest and per-case hashes, declared sizes, aggregate hashes, source hashes and artifact hashes recomputed from actual bytes.")
    lines.append("- `source_example`/`source_refs`/`source_lines` paths exist.")
    lines.append("- Cross-family: job/buffer schema, patch convention, EW patch fields and EW_CFG/out_convert/RDMA encoding, FDIV overlap, task-range consistency, buffer-size declarations.")
    lines.append("- No device was accessed; no output was fabricated; no bundle was repaired.")
    lines.append("")
    lines.append("## Evidence limits")
    lines.append("")
    lines.append(
        "This audit verifies bundle structure and byte-level provenance only. It does not validate "
        "RK3588 silicon numerics, Rocket execution, FPGA RTL, or the correctness of any oracle formula. "
        "It also does not re-run the family generators or validators."
    )
    lines.append("")
    lines.append(
        f"Snapshot hashes cover {result['snapshot']['file_count']} files / "
        f"{result['snapshot']['total_bytes']} bytes. If the live tree changed after the snapshot, "
        f"the audit remains a statement about the snapshot; see `snapshot.live_changes`."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/fedora/rknpu-fpga/build/rk3588-example-captures")
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--out-md", default=None)
    parser.add_argument("--audit-dir", default=None)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    audit_dir = Path(args.audit_dir) if args.audit_dir else root / "team" / "audit"
    out_json = Path(args.out_json) if args.out_json else audit_dir / "AUDIT.json"
    out_md = Path(args.out_md) if args.out_md else audit_dir / "AUDIT.md"
    audit_dir.mkdir(parents=True, exist_ok=True)

    start_wall = utc_now()
    families = family_dirs(root)
    snapshot = build_snapshot(root, families)
    snapshot["families"] = families
    data = snapshot["_data"]

    # Environment / revisions
    def git_head(path):
        try:
            return subprocess.check_output(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except Exception:
            return "unavailable"

    repo_root = root.parent.parent
    env = {
        "python": sys.version.replace("\n", " "),
        "platform": sys.platform,
        "rknpu_fpga_revision": git_head(repo_root),
        "rk3588_revision": git_head(Path("/home/fedora/rk3588")),
        "cwd": str(Path.cwd()),
    }

    capture_format_path = root / "CAPTURE_FORMAT.md"
    if capture_format_path.is_file():
        capture_bytes = capture_format_path.read_bytes()
        capture_format = {
            "path": str(capture_format_path),
            "bytes": len(capture_bytes),
            "sha256": sha256_bytes(capture_bytes),
        }
        data[str(capture_format_path.relative_to(root))] = capture_bytes
    else:
        capture_format = {"path": str(capture_format_path), "bytes": 0, "sha256": None}

    # Declared determinism/seed metadata (recorded, not used to regenerate
    # bytes).  Provenance seeds for conv-fp16 are read from the hashed
    # provenance.json files.
    determinism = {}
    for family in families:
        manifest_path = root / family / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        entry = {}
        if "seeds" in manifest:
            entry["seeds"] = manifest.get("seeds")
        if "input_generation" in manifest:
            entry["input_generation"] = manifest.get("input_generation")
        generator = manifest.get("generator")
        if isinstance(generator, dict) and "input_generation" in generator:
            entry["input_generation"] = generator.get("input_generation")
        if "parity_padding" in manifest:
            entry["parity_padding"] = manifest.get("parity_padding")
        if family == "conv-fp16":
            seeds = set()
            for rel, item in snapshot["files"].items():
                if rel.endswith("/provenance.json"):
                    try:
                        prov = json.loads(data[rel].decode("utf-8"))
                    except Exception:
                        continue
                    if "seed" in prov:
                        seeds.add(prov["seed"])
            if seeds:
                entry["provenance_seeds"] = sorted(seeds)
        if entry:
            determinism[family] = entry

    # Audit each family.
    family_results = OrderedDict()
    family_order = []
    for family in families:
        family_order.append(family)
        family_dir = root / family
        family_findings = Findings()
        manifest_rel = f"{family}/manifest.json"
        manifest = None
        manifest_bytes = None
        if manifest_rel not in data:
            family_findings.error("manifest.missing", f"{manifest_rel} is missing")
            family_results[family] = {
                "family": family,
                "counts": {
                    "manifest_entries": 0,
                    "bundle_dirs": 0,
                    "READY": 0,
                    "BLOCKED": 0,
                    "INVALID": 0,
                    "exception_READY": 0,
                    "exception_BLOCKED": 0,
                    "exception_INVALID": 0,
                },
                "verdict": "FAIL",
                "errors": family_findings.errors,
                "warnings": family_findings.warnings,
                "cases": [],
                "_jobs": {},
                "_entries": {},
                "_blocked_reasons": {},
            }
            continue
        try:
            manifest, manifest_bytes = strict_json_load(family_dir / "manifest.json")
        except DuplicateJsonKey as exc:
            family_findings.error("manifest.duplicate_json_key", f"{manifest_rel}: {exc}")
        except Exception as exc:
            family_findings.error("manifest.invalid_json", f"{manifest_rel}: {exc}")

        top, top_verified, top_failed = audit_manifest_top(
            root, family, family_dir, manifest, manifest_bytes, family_findings
        )
        cases = top.get("cases", []) if isinstance(top, dict) else []
        entries_by_name = {}
        duplicate_names = set()
        for entry in cases:
            if isinstance(entry, dict):
                name = entry.get("case")
                if name in entries_by_name:
                    duplicate_names.add(name)
                else:
                    entries_by_name[name] = entry

        case_dir_names = set()
        cases_root = family_dir / "cases"
        if cases_root.is_dir():
            for child in cases_root.iterdir():
                if child.is_dir():
                    case_dir_names.add(child.name)
                elif child.is_file():
                    family_findings.warning(
                        "manifest.stray_file",
                        f"stray file directly under {family}/cases/: {child.name}",
                    )

        case_results = []
        jobs = {}
        entry_map = {}
        blocked_reasons = {}
        for entry in cases:
            if not isinstance(entry, dict):
                continue
            name = entry.get("case")
            materialized = name in case_dir_names
            case = audit_case(
                root,
                family,
                family_dir,
                entry,
                name,
                entry.get("status"),
                materialized,
                snapshot,
                family_findings,
            )
            case_results.append(case)
            entry_map[name] = entry
            blocked_reasons[name] = next(
                (
                    entry.get(key)
                    for key in ("blocked_reason", "reason", "blocker")
                    if is_nonempty_str(entry.get(key))
                ),
                "",
            )
            job_path = family_dir / "cases" / name / "job.json"
            if job_path.is_file():
                try:
                    jobs[name] = json.loads(job_path.read_text(encoding="utf-8"), object_pairs_hook=_no_dup_pairs)
                except Exception:
                    jobs[name] = None

        # Orphan directories are bundles too and must be INVALID.
        for name in sorted(case_dir_names - set(entries_by_name)):
            case = CaseAudit(name, None, True)
            case.error("manifest", "manifest.orphan_bundle", f"bundle directory {family}/cases/{name} is not listed in manifest.json")
            case_results.append(case)
            job_path = family_dir / "cases" / name / "job.json"
            if job_path.is_file():
                try:
                    jobs[name] = json.loads(job_path.read_text(encoding="utf-8"), object_pairs_hook=_no_dup_pairs)
                except Exception:
                    jobs[name] = None

        # Manifest duplicate names: mark each occurrence invalid.
        for name in sorted(duplicate_names):
            for case in case_results:
                if case.case == name:
                    case.error("manifest", "manifest.duplicate_case", f"case name {name!r} appears more than once in manifest.json")

        # Manifest-only BLOCKED entries are not materialized; they are still
        # counted as BLOCKED.  Cases with no entry are INVALID already.

        # Unverified top-level hashes.  Case-level hashes were verified above;
        # include their proven values so the manifest-wide scan only reports
        # genuinely unverified 64-hex fields.
        for case in case_results:
            top_verified |= case.verified_hashes
        for path, value in collect_hash_strings(manifest, f"{family}.manifest"):
            if value not in top_verified and value not in top_failed:
                family_findings.error(
                    "hashes.unverifiable",
                    f"{path}: hash {value} was not verified against actual bytes",
                )

        # Counts
        status_counts = Counter(case.audit_status for case in case_results)
        exception_counts = Counter(case.exception_status for case in case_results)
        bundle_dirs = len(case_dir_names)
        counts = {
            "manifest_entries": len(cases),
            "bundle_dirs": bundle_dirs,
            "READY": status_counts.get("READY", 0),
            "BLOCKED": status_counts.get("BLOCKED", 0),
            "INVALID": status_counts.get("INVALID", 0),
            "exception_READY": exception_counts.get("READY", 0),
            "exception_BLOCKED": exception_counts.get("BLOCKED", 0),
            "exception_INVALID": exception_counts.get("INVALID", 0),
        }
        verdict = "FAIL" if any(case.errors for case in case_results) or family_findings.errors else "PASS"
        if verdict == "PASS" and family_findings.warnings:
            verdict = "PASS_WITH_WARNINGS"
        case_json = []
        for case in case_results:
            item = case.as_json()
            item["blocked_reason"] = blocked_reasons.get(case.case, "")
            case_json.append(item)
        family_results[family] = {
            "family": family,
            "counts": counts,
            "verdict": verdict,
            "errors": family_findings.errors,
            "warnings": family_findings.warnings,
            "cases": case_json,
            "_jobs": jobs,
            "_entries": entry_map,
            "_blocked_reasons": blocked_reasons,
        }

    # Cross-family.
    cross = audit_cross_family(root, families, family_results)

    format_observations = []
    if (
        'capture_bytes' in locals()
        and b"Do not encode multiple sequential RK submissions" in capture_bytes
        and cross.get("multi_task_cases")
    ):
        format_observations.append(
            {
                "code": "format.rocket_job_boundary",
                "message": (
                    "The current CAPTURE_FORMAT.md contains a 'Rocket job boundary' paragraph "
                    "stating that multiple sequential RK submissions must not share one tasks array. "
                    "This audit rerun was scoped to the fetch-parity padding rule; the multi-task cases "
                    "below were not reclassified under that newer paragraph and need separate review."
                ),
                "cases": [
                    {
                        "family": item["family"],
                        "case": item["case"],
                        "task_count": item["task_count"],
                    }
                    for item in cross.get("multi_task_cases", [])
                ],
            }
        )

    # Live-change detection after the audit.
    live_changes = compare_live(root, snapshot)
    snapshot["live_changes"] = live_changes

    # Summary
    summary_counts = Counter()
    for family in family_order:
        data_fam = family_results[family]
        for key in ("READY", "BLOCKED", "INVALID", "exception_READY", "exception_BLOCKED", "exception_INVALID"):
            summary_counts[key] += data_fam["counts"][key]
        summary_counts["manifest_entries"] += data_fam["counts"]["manifest_entries"]
        summary_counts["bundle_dirs"] += data_fam["counts"]["bundle_dirs"]
    family_error_count = sum(len(family_results[f]["errors"]) for f in family_order)
    cross_error_count = len(cross["errors"])
    manifest_hash_strings = 0
    for family in family_order:
        try:
            manifest_obj = json.loads((root / family / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        manifest_hash_strings += sum(1 for _ in collect_hash_strings(manifest_obj))
    unverified_manifest_hashes = sum(
        1
        for family in family_order
        for error in family_results[family]["errors"]
        if error["code"].startswith("hashes.")
    )
    jobs_checked = sum(len(family_results[f].get("_jobs", {})) for f in family_order)
    buffers_checked = 0
    tasks_checked = 0
    patches_checked = 0
    hashes_declared = 0
    hashes_verified = 0
    for family in family_order:
        for job in family_results[family].get("_jobs", {}).values():
            if isinstance(job, dict):
                buffers_checked += len(job.get("buffers", []))
                tasks_checked += len(job.get("tasks", []))
                patches_checked += len(job.get("patches", []))
        for case in family_results[family]["cases"]:
            hashes_declared += case.get("declared_hashes", 0)
            hashes_verified += case.get("verified_hashes", 0)
    overall_ok = (
        summary_counts.get("INVALID", 0) == 0
        and family_error_count == 0
        and cross_error_count == 0
        and not live_changes
    )
    case_status = "PASS" if summary_counts.get("INVALID", 0) == 0 else "FAIL"
    provenance_status = (
        "PASS"
        if family_error_count == 0 and cross_error_count == 0 and not live_changes
        else "FAIL"
    )
    exception_ok = (
        summary_counts.get("exception_INVALID", 0) == 0
        and family_error_count == 0
        and cross_error_count == 0
        and not live_changes
    )
    summary = {
        **{
            k: summary_counts.get(k, 0)
            for k in (
                "manifest_entries",
                "bundle_dirs",
                "READY",
                "BLOCKED",
                "INVALID",
                "exception_READY",
                "exception_BLOCKED",
                "exception_INVALID",
            )
        },
        "case_status": case_status,
        "provenance_status": provenance_status,
        "family_errors": family_error_count,
        "cross_family_errors": cross_error_count,
        "live_changes": len(live_changes),
        "jobs_checked": jobs_checked,
        "buffers_checked": buffers_checked,
        "tasks_checked": tasks_checked,
        "patches_checked": patches_checked,
        "hashes_declared": hashes_declared,
        "hashes_verified": hashes_verified,
        "manifest_hash_strings": manifest_hash_strings,
        "manifest_hashes_unverified": unverified_manifest_hashes,
        "documented_deviations": sum(
            len(case.get("documented_deviations", []))
            for family in family_order
            for case in family_results[family]["cases"]
        ),
        "accepted_padding_cases": sum(
            1
            for family in family_order
            for case in family_results[family]["cases"]
            if case.get("accepted_padding")
        ),
        "status": "PASS" if overall_ok else "FAIL",
        "status_if_documented_deviations_accepted": "PASS" if exception_ok else "FAIL",
    }

    parser_path = Path(__file__)
    parser_sha = sha256_bytes(parser_path.read_bytes()) if parser_path.is_file() else "unavailable"

    result = {
        "audit_version": AUDIT_VERSION,
        "parser": {
            "name": "team/audit/audit.py",
            "version": AUDIT_VERSION,
            "sha256": parser_sha,
        },
        "generated_utc": utc_now(),
        "started_utc": start_wall,
        "environment": env,
        "capture_format": capture_format,
        "determinism": determinism,
        "scope": {
            "root": str(root),
            "families": families,
            "family_order": family_order,
            "manifest_count": len(families),
        },
        "snapshot": {
            "start_utc": snapshot["start_utc"],
            "end_utc": snapshot["end_utc"],
            "tree_sha256": snapshot["tree_sha256"],
            "file_count": len(snapshot["files"]),
            "total_bytes": sum(item["size"] for item in snapshot["files"].values()),
            "files": snapshot["files"],
            "live_changes": live_changes,
        },
        "family_order": family_order,
        "families": family_results,
        "cross_family": cross,
        "format_observations": format_observations,
        "summary": summary,
        "commands": [
            f"cd {repo_root}",
            f"python3 -m py_compile {parser_path}",
            f"python3 {parser_path} --root {root} --out-json {out_json} --out-md {out_md}",
            f"python3 --version  # {env['python']}",
            f"git -C {repo_root} rev-parse HEAD  # {env['rknpu_fpga_revision']}",
            f"git -C /home/fedora/rk3588 rev-parse HEAD  # {env['rk3588_revision']}",
        ],
    }

    # Remove internal keys from families before writing JSON.
    public_families = OrderedDict()
    for family in family_order:
        data_fam = dict(family_results[family])
        data_fam.pop("_jobs", None)
        data_fam.pop("_entries", None)
        data_fam.pop("_blocked_reasons", None)
        public_families[family] = data_fam
    result["families"] = public_families

    out_json.write_text(json.dumps(result, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(result), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
