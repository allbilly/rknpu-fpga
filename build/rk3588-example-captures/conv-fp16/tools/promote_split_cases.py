#!/usr/bin/env python3
"""Promote the validated one-task conv-fp16 diagnostic bundles.

The RK3588 Rocket v6.18 board path executed only task 0 of a two-task job.
This script promotes the four already-validated single-task slices from
``conv-fp16-task-diagnostic/bundles`` into the main ``conv-fp16`` family and
marks the two original two-task cases BLOCKED while preserving their evidence.

It only reads the diagnostic/original bundles and writes under
``build/rk3588-example-captures/conv-fp16/``.  No device or board access.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAMILY_DIR = HERE.parent
CASES_DIR = FAMILY_DIR / "cases"
CAPTURES_ROOT = FAMILY_DIR.parent
DIAG_DIR = CAPTURES_ROOT / "conv-fp16-task-diagnostic" / "bundles"
DIAG_RESULTS = CAPTURES_ROOT / "results" / "conv-fp16-task-diagnostic-20261105T211500Z"
ORIG_RESULTS = CAPTURES_ROOT / "results" / "conv-fp16-20261105T205900Z"

BLOCKER = "MULTITASK_ROCKET_JOB_UNSUPPORTED"

PROMOTIONS = [
    dict(
        src="diag_grouped_task0",
        dst="conv_grouped_3x3_c4_h5_w5_oc8_g2_task0",
        parent="conv_grouped_3x3_c4_h5_w5_oc8_g2",
        task_index=0,
        expected="expected_out0.bin",
        out_sha256="2b9b1524c7cff40fffa54127df398f69a91297b9049a97f54fd06c880c38a9a5",
        description=(
            "One-task promotion of conv_grouped_3x3_c4_h5_w5_oc8_g2 task 0/2 "
            "(group 0): C2 5x5 -> OC4 3x3, stride 1, groups=1. The original "
            "two-task case is BLOCKED because Rocket executed only task 0."
        ),
    ),
    dict(
        src="diag_grouped_task1",
        dst="conv_grouped_3x3_c4_h5_w5_oc8_g2_task1",
        parent="conv_grouped_3x3_c4_h5_w5_oc8_g2",
        task_index=1,
        expected="expected_out1.bin",
        out_sha256="1bb2e0e5a2ec708d27d4bac96123d5c447a2a79214cbe2fe09bcac1b31b4024a",
        description=(
            "One-task promotion of conv_grouped_3x3_c4_h5_w5_oc8_g2 task 1/2 "
            "(group 1): C2 5x5 -> OC4 3x3, stride 1, groups=1. The original "
            "two-task case is BLOCKED because Rocket executed only task 0."
        ),
    ),
    dict(
        src="diag_splitoc_task0",
        dst="conv_splitoc_3x3_c16_h9_w9_oc16_task0",
        parent="conv_splitoc_3x3_c16_h9_w9_oc16",
        task_index=0,
        expected="expected_out0.bin",
        out_sha256="48ad9ce497eb9d44359343b570a836e5faea05430fc217f668a8c50a78cec108",
        description=(
            "One-task promotion of conv_splitoc_3x3_c16_h9_w9_oc16 task 0/2 "
            "(output channels 0..7): C16 9x9 -> OC8 7x7, stride 1, groups=1, "
            "full_data_bank=True preserved. The original two-task case is "
            "BLOCKED because Rocket executed only task 0."
        ),
    ),
    dict(
        src="diag_splitoc_task1",
        dst="conv_splitoc_3x3_c16_h9_w9_oc16_task1",
        parent="conv_splitoc_3x3_c16_h9_w9_oc16",
        task_index=1,
        expected="expected_out1.bin",
        out_sha256="f83443a0c459a8926272001d29c2018cb4d06d1869496be663f0b6a746c853be",
        description=(
            "One-task promotion of conv_splitoc_3x3_c16_h9_w9_oc16 task 1/2 "
            "(output channels 8..15): C16 9x9 -> OC8 7x7, stride 1, groups=1, "
            "full_data_bank=True preserved. The original two-task case is "
            "BLOCKED because Rocket executed only task 0."
        ),
    ),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def file_meta(path: Path):
    return dict(size=path.stat().st_size, sha256=sha256_file(path))


def collect_hashes(case_dir: Path):
    return {
        path.relative_to(case_dir).as_posix(): file_meta(path)
        for path in sorted(case_dir.rglob("*"))
        if path.is_file()
    }


def diagnostic_summary():
    path = DIAG_RESULTS / "host-analysis" / "comparison_summary.json"
    cases = read_json(path)
    return {entry["case"]: entry for entry in cases}


def task_shape(parent_case: str, parent_shape: dict, task_index: int, parent_layout: dict):
    groups = int(parent_shape["groups"])
    if groups > 1:
        in_c = int(parent_shape["in_c"]) // groups
        out_c = int(parent_shape["out_c"]) // groups
        task_groups = 1
    else:
        in_c = int(parent_shape["in_c"])
        out_c = int(parent_layout["out_c"])
        task_groups = 1
    return {
        "batch": 1,
        "in_c": in_c,
        "in_h": int(parent_shape["in_h"]),
        "in_w": int(parent_shape["in_w"]),
        "out_c": out_c,
        "kh": int(parent_shape["kh"]),
        "kw": int(parent_shape["kw"]),
        "stride": int(parent_shape.get("stride", 1)),
        "groups": task_groups,
        "padded_zero_frame": bool(parent_shape.get("padded_zero_frame", False)),
        "effective_input_h": int(parent_shape.get("effective_input_h", parent_shape["in_h"])),
        "effective_input_w": int(parent_shape.get("effective_input_w", parent_shape["in_w"])),
        "out_h": int(parent_shape["out_h"]),
        "out_w": int(parent_shape["out_w"]),
        "parent_case": parent_case,
        "parent_task_index": task_index,
        "parent_in_c": int(parent_shape["in_c"]),
        "parent_out_c": int(parent_shape["out_c"]),
        "parent_groups": groups,
    }


def build_provenance(promo, parent_entry, parent_prov, diag_job, diag_derivation,
                     layout, shape, task_meta, expected_sha):
    task = dict(task_meta)
    task["index"] = 0
    task["regcmd_offset_words"] = 0
    task["regcmd_words"] = 54
    task["body_qwords"] = 50
    task["tail_qwords"] = 4
    task["patches"] = [
        dict(regcmd_index=21, buffer=diag_job["buffers"][0]["name"], kind="value32"),
        dict(regcmd_index=27, buffer=diag_job["buffers"][1]["name"], kind="value32"),
        dict(regcmd_index=35, buffer=diag_job["buffers"][2]["name"], kind="value32"),
    ]
    oracle = dict(parent_prov["oracle"])
    oracle["expected_files"] = [promo["expected"]]
    oracle.pop("combined_expected", None)
    return {
        "case": promo["dst"],
        "generated_by": "tools/promote_split_cases.py",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_example": parent_prov["source_example"],
        "source_sha256": parent_prov["source_sha256"],
        "source_git_revision": parent_prov["source_git_revision"],
        "host": parent_prov["host"],
        "seed": parent_prov["seed"],
        "shape": shape,
        "branch": parent_prov["branch"].rstrip(".") + ". Promoted to one terminal task at offset 0.",
        "builder": parent_prov["builder"],
        "parent_case": promo["parent"],
        "parent_task_index": promo["task_index"],
        "promotion": {
            "reason": BLOCKER,
            "diagnostic_bundle": str(DIAG_DIR / promo["src"]),
            "diagnostic_results": str(DIAG_RESULTS),
            "original_results": str(ORIG_RESULTS),
            "diagnostic_out_sha256": promo["out_sha256"],
            "expected_out_sha256": expected_sha,
            "task_derivation": diag_derivation,
        },
        "tasks": [task],
        "placeholders": parent_prov["placeholders"],
        "oracle": oracle,
    }


def main() -> int:
    manifest_path = FAMILY_DIR / "manifest.json"
    manifest = read_json(manifest_path)
    entries = manifest["cases"]
    by_name = {entry["case"]: entry for entry in entries}
    summaries = diagnostic_summary()

    for promo in PROMOTIONS:
        parent_entry = by_name[promo["parent"]]
        parent_dir = CASES_DIR / promo["parent"]
        parent_prov = read_json(parent_dir / "provenance.json")
        parent_job = read_json(parent_dir / "job.json")
        parent_shape = parent_entry["shape"]
        parent_task = parent_prov["tasks"][promo["task_index"]]
        parent_layout = next(
            layout for layout in parent_entry["output_layouts"]
            if int(layout["task_index"]) == promo["task_index"]
        )

        diag_dir = DIAG_DIR / promo["src"]
        diag_job = read_json(diag_dir / "job.json")
        diag_derivation = read_json(diag_dir / "derivation.json")

        # The diagnostic bundle must be exactly one task at offset 0.
        if len(diag_job["tasks"]) != 1:
            raise SystemExit(f"{promo['src']}: expected exactly one task")
        if diag_job["tasks"][0] != {"regcmd_offset_words": 0, "regcmd_words": 54}:
            raise SystemExit(f"{promo['src']}: unexpected task record {diag_job['tasks'][0]!r}")

        # The expected oracle must be byte-identical to the original task oracle.
        diag_expected = diag_dir / promo["expected"]
        parent_expected = parent_dir / promo["expected"]
        expected_sha = sha256_file(diag_expected)
        if expected_sha != sha256_file(parent_expected):
            raise SystemExit(f"{promo['src']}: {promo['expected']} differs from parent")
        if diag_derivation.get("oracle_copy") not in (None, promo["expected"]):
            raise SystemExit(
                f"{promo['src']}: derivation oracle_copy is "
                f"{diag_derivation['oracle_copy']!r}, expected {promo['expected']!r}"
            )

        # The 54-QWORD diagnostic stream must equal the parent task slice.
        parent_regcmd = (parent_dir / "regcmd.bin").read_bytes()
        start = promo["task_index"] * 54 * 8
        parent_slice = parent_regcmd[start:start + 54 * 8]
        diag_regcmd = (diag_dir / "regcmd.bin").read_bytes()
        if diag_regcmd != parent_slice:
            raise SystemExit(f"{promo['src']}: regcmd slice differs from parent task")
        if len(diag_regcmd) != 54 * 8:
            raise SystemExit(f"{promo['src']}: regcmd is not 54 QWORDs")

        # Input and weight bytes must be byte-identical to the parent task.
        for buffer in diag_job["buffers"]:
            if buffer["direction"] != "in":
                continue
            name = buffer["input"]
            if (diag_dir / name).read_bytes() != (parent_dir / name).read_bytes():
                raise SystemExit(f"{promo['src']}: {name} differs from parent")

        # Patches must be the parent task patches remapped to local indices.
        parent_patches = {
            int(patch["regcmd_index"]) - promo["task_index"] * 54: patch
            for patch in parent_job["patches"]
            if promo["task_index"] * 54 <= int(patch["regcmd_index"]) < (promo["task_index"] + 1) * 54
        }
        diag_patches = {int(patch["regcmd_index"]): patch for patch in diag_job["patches"]}
        if set(parent_patches) != {21, 27, 35} or set(diag_patches) != {21, 27, 35}:
            raise SystemExit(f"{promo['src']}: unexpected patch indices")
        for idx in (21, 27, 35):
            if parent_patches[idx]["buffer"] != diag_patches[idx]["buffer"]:
                raise SystemExit(f"{promo['src']}: patch {idx} buffer changed")
            if parent_patches[idx]["kind"] != diag_patches[idx]["kind"]:
                raise SystemExit(f"{promo['src']}: patch {idx} kind changed")

        # The diagnostic board output is the byte evidence for the promoted
        # case's diagnostic_out_sha256.  Keep it at the case root: audit 1.3.0
        # rejects nested directories inside READY bundles.
        out_bin_name = "out0.bin" if promo["expected"].endswith("out0.bin") else "out1.bin"
        diag_out_path = DIAG_RESULTS / "board-out" / promo["src"] / out_bin_name
        if not diag_out_path.is_file():
            raise SystemExit(f"{promo['src']}: missing diagnostic output {diag_out_path}")
        diag_out_sha = sha256_file(diag_out_path)
        if diag_out_sha != promo["out_sha256"]:
            raise SystemExit(
                f"{promo['src']}: diagnostic output hash {diag_out_sha} "
                f"!= recorded {promo['out_sha256']}"
            )
        evidence_name = f"evidence_diagnostic_{out_bin_name}"

        # Promote the files.
        dst_dir = CASES_DIR / promo["dst"]
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        dst_dir.mkdir(parents=True)
        shutil.copy2(diag_dir / "regcmd.bin", dst_dir / "regcmd.bin")
        shutil.copy2(diag_dir / promo["expected"], dst_dir / promo["expected"])
        for buffer in diag_job["buffers"]:
            if buffer["direction"] == "in":
                shutil.copy2(diag_dir / buffer["input"], dst_dir / buffer["input"])
        shutil.copy2(diag_dir / "derivation.json", dst_dir / "derivation.json")
        shutil.copy2(diag_out_path, dst_dir / evidence_name)

        new_job = dict(diag_job)
        new_job["case"] = promo["dst"]
        new_job["description"] = promo["description"]
        write_json(dst_dir / "job.json", new_job)

        shape = task_shape(promo["parent"], parent_shape, promo["task_index"], parent_layout)
        provenance = build_provenance(
            promo, parent_entry, parent_prov, diag_job, diag_derivation,
            parent_layout, shape, parent_task, expected_sha,
        )
        provenance["promotion"]["diagnostic_derivation_unmodified"] = True
        provenance["promotion"]["diagnostic_derivation_note"] = (
            "derivation.json is the original diagnostic derivation; its "
            "derived_job_sha256 covers the diag_* job name, not this promoted "
            "case name. promoted_job_sha256 covers the promoted job.json."
        )
        provenance["promotion"]["promoted_job_sha256"] = sha256_file(dst_dir / "job.json")
        provenance["promotion"]["evidence_file"] = evidence_name
        provenance["promotion"]["evidence_sha256"] = diag_out_sha
        provenance["promotion"]["evidence_note"] = (
            "The diagnostic board output is retained at the case root because "
            "audit 1.3.0 rejects nested directories inside READY bundles; it is "
            "hash-bound in the manifest files map."
        )
        write_json(dst_dir / "provenance.json", provenance)

        summary = summaries[promo["src"]]
        if summary["exact_mismatch"] != 0 or summary["over_atol"] != 0:
            raise SystemExit(f"{promo['src']}: diagnostic summary is not exact")
        if summary["out_sha256"] != promo["out_sha256"]:
            raise SystemExit(f"{promo['src']}: diagnostic output hash changed")

        layout = dict(parent_layout)
        layout["task_index"] = 0
        entry = {
            "case": promo["dst"],
            "status": "READY",
            "source_example": parent_entry["source_example"],
            "source_lines": parent_entry["source_lines"],
            "shape": shape,
            "description": promo["description"],
            "branch": parent_entry["branch"] + " Promoted to one terminal task at offset 0.",
            "task_count": 1,
            "buffer_count": 3,
            "patch_count": 3,
            "tasks": new_job["tasks"],
            "buffers": new_job["buffers"],
            "expected_files": [promo["expected"]],
            "oracle": provenance["oracle"],
            "output_layouts": [layout],
            "caveats": [
                f"One-task promotion of {promo['parent']} task {promo['task_index']}/2; job.json has exactly one task at regcmd_offset_words=0, regcmd_words=54.",
                f"{promo['expected']} is a byte-identical copy of the parent task oracle (sha256 {expected_sha}).",
                "The parent two-task case is BLOCKED with reason MULTITASK_ROCKET_JOB_UNSUPPORTED; do not merge the tasks back into one job.",
                "Board diagnostic evidence: this one-task bundle matched its oracle exactly (0 mismatches, submit_ret=0); the original two-task control left task 1's output BO all zero.",
            ],
            "promotion_evidence": {
                "diagnostic_bundle": str(DIAG_DIR / promo["src"]),
                "diagnostic_results": str(DIAG_RESULTS),
                "original_results": str(ORIG_RESULTS),
                "evidence_file": evidence_name,
                "diagnostic_out_sha256": promo["out_sha256"],
                "exact_mismatch_elements": 0,
                "over_atol_elements": 0,
                "max_abs_diff": 0.0,
            },
            "files": collect_hashes(dst_dir),
        }
        by_name[promo["dst"]] = entry
        print(f"promoted {promo['src']} -> {promo['dst']}")

    # Mark the two original two-task cases BLOCKED, preserving their evidence.
    for parent in (
        "conv_grouped_3x3_c4_h5_w5_oc8_g2",
        "conv_splitoc_3x3_c16_h9_w9_oc16",
    ):
        entry = by_name[parent]
        parent_dir = CASES_DIR / parent
        zero_path = ORIG_RESULTS / "conv-fp16" / parent / "out1.bin"
        if not zero_path.is_file():
            raise SystemExit(f"{parent}: missing original zero task-1 output {zero_path}")
        zero_sha = sha256_file(zero_path)
        expected_zero_sha = (
            "ef115a0e0c15cdc41958ca46b5b14b456115f4baec5e3ca68599d2a8f435e3b8"
            if parent == "conv_grouped_3x3_c4_h5_w5_oc8_g2"
            else "6bb4877dfebc6d4f819999f0f8b65d06aa540746bc63b7c1261282636efcaa15"
        )
        if zero_sha != expected_zero_sha:
            raise SystemExit(f"{parent}: zero task-1 output hash {zero_sha} != {expected_zero_sha}")
        evidence_name = "evidence_task1_zero_output.bin"
        shutil.copy2(zero_path, parent_dir / evidence_name)
        entry.setdefault("files", {})[evidence_name] = file_meta(parent_dir / evidence_name)

        entry["status"] = "BLOCKED"
        entry["blocker"] = BLOCKER
        entry["reason_code"] = BLOCKER
        entry["evidence_preserved"] = True
        entry["promoted_to"] = [p["dst"] for p in PROMOTIONS if p["parent"] == parent]
        board_evidence = {
            "diagnostic_results": str(DIAG_RESULTS),
            "original_results": str(ORIG_RESULTS),
            "evidence_file": evidence_name,
            "task1_zero_sha256": zero_sha,
            "observed": (
                "Task 0 matched exactly; task 1's output BO was all zero. "
                "The identical task-1 command stream submitted alone (promoted "
                "one-task case) matched its oracle exactly."
            ),
        }
        if parent == "conv_grouped_3x3_c4_h5_w5_oc8_g2":
            board_evidence["grouped_control_task1_zero_sha256"] = zero_sha
        entry["board_evidence"] = board_evidence
        entry["reason"] = (
            "MULTITASK_ROCKET_JOB_UNSUPPORTED: the RK3588 Rocket v6.18 board path "
            "executed only task 0 of a two-task job. The original run's task 0 "
            "output matched exactly while task 1's output BO remained all zero. "
            "The four derived one-task bundles (including both task-1 streams) "
            "matched their expected_out0/expected_out1 oracles exactly as "
            "single-task jobs. This two-task job is retained as BLOCKED evidence "
            "and must not be submitted; use the promoted one-task cases."
        )

    # Rebuild the family case order: existing single-task READY cases, promoted
    # READY cases, the two preserved multi-task BLOCKED cases, then the other
    # pre-existing BLOCKED entries.
    promoted_names = [p["dst"] for p in PROMOTIONS]
    parent_names = [
        "conv_grouped_3x3_c4_h5_w5_oc8_g2",
        "conv_splitoc_3x3_c16_h9_w9_oc16",
    ]
    existing_blocked = [
        name for name, entry in by_name.items()
        if entry["status"] == "BLOCKED"
        and name not in parent_names
    ]
    ordered = []
    for entry in entries:
        if entry["status"] == "READY" and entry["case"] not in promoted_names:
            ordered.append(by_name[entry["case"]])
    for name in promoted_names:
        ordered.append(by_name[name])
    for name in parent_names:
        ordered.append(by_name[name])
    for name in existing_blocked:
        ordered.append(by_name[name])

    ready = sum(1 for entry in ordered if entry["status"] == "READY")
    blocked = sum(1 for entry in ordered if entry["status"] == "BLOCKED")
    manifest["generated_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["counts"] = dict(ready=ready, blocked=blocked, total=len(ordered))
    manifest["cases"] = ordered
    manifest["split_promotion"] = {
        "applied_utc": manifest["generated_utc"],
        "blocker": BLOCKER,
        "diagnostic_bundles": str(DIAG_DIR),
        "diagnostic_results": str(DIAG_RESULTS),
        "original_results": str(ORIG_RESULTS),
        "promoted_cases": promoted_names,
        "blocked_parents": parent_names,
        "method": (
            "The four one-task diagnostic bundles were copied into cases/ with "
            "one task at offset 0, byte-identical task slices, remapped patches "
            "21/27/35, and byte-identical expected_out0/expected_out1 oracles. "
            "The two original two-task case directories are retained unchanged "
            "as BLOCKED evidence."
        ),
        "board_evidence": {
            "all_four_one_task_exact": True,
            "control_two_task_task1_zero": True,
            "grouped_control_task1_zero_evidence": str(
                DIAG_RESULTS
                / "board-out"
                / "conv_grouped_3x3_c4_h5_w5_oc8_g2"
                / "out1.bin"
            ),
            "note": (
                "The zero-output hash is bound per case in each BLOCKED parent's "
                "board_evidence.task1_zero_sha256 and evidence_task1_zero_output.bin."
            ),
        },
    }
    manifest["preparation_tools"] = {
        name: file_meta(HERE / name)
        for name in (
            "gen_bundles.py",
            "validate_bundles.py",
            "compare_oracle.py",
            "promote_split_cases.py",
        )
        if (HERE / name).is_file()
    }
    write_json(manifest_path, manifest)
    print(f"manifest: {manifest_path}")
    print(f"counts: {ready} READY / {blocked} BLOCKED / {len(ordered)} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
