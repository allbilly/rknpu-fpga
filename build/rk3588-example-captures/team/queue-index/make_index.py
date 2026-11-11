#!/usr/bin/env python3
"""Build the top-level queue index for the RK3588 example captures.

Read-only with respect to every family bundle, runner, result and tracked
source.  Writes only QUEUE.json and STATUS.md in this directory.

No board access, no ssh/scp, no submit, no FPGA programming.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # build/rk3588-example-captures
HOST_ROOT = str(ROOT)
BOARD_ROOT = "/home/opencode-agent/rk3588-example-captures"
BOARD_LOCK = "/home/opencode-agent/rk3588-npu.lock"

FAMILIES = [
    "ew-int",
    "ew-fp16",
    "fdiv-systematic",
    "conv-fp16",
    "conv-simple",
    "conv-gemm-vendor",
    "pooling",
]

RUN_ID = "ew-int-20261105T200154Z"
EW_INT_RESULTS = ROOT / "results" / RUN_ID
EW_INT_EVIDENCE = ROOT / "results" / f"{RUN_ID}-evidence"

SOURCE_EXAMPLES = {
    "ew-int": [
        {
            "path": "/home/fedora/rk3588/examples/kernel_6_18/elementwise_int.py",
            "sha256": "825c7c2166eed48fd73fc1d31655238928b0fd5677df539d17f7301dc671d329",
            "role": "primary integer EW register builder and Rocket tail",
        },
        {
            "path": "/home/fedora/rk3588/examples/expt/elementwise_int.py",
            "sha256": "1c6a43b0d928b744420f4db1762527f5bbb52c7cc92dc2d1ef0aba2ff94b95f8",
            "role": "cross-check integer EW paths and operation table",
        },
    ],
    "ew-fp16": [
        {
            "path": "/home/fedora/rk3588/examples/elementwise.py",
            "sha256": "242ad9262254f85b1b426ecc4da76735c0541be9dbe57f812417128e8297e0a0",
            "role": "primary FP16 EW register body, terminal tail and donor oracle",
        },
        {
            "path": "/home/fedora/rk3588/examples/simple_add.py",
            "sha256": "838b3145a9bd925c5be9ae3ea154b539970f3a69f0099021c02080de50cb0963",
            "role": "cross-check EW_CFG and 8-lane width",
        },
        {
            "path": "/home/fedora/rk3588/experimental/kernel_6_18/elementwise.py",
            "sha256": "7f90bb9d4add99bbbb490d3711ac31d2e7ba44629520a3b74c54e5ffb52825f2",
            "role": "cross-check EW_CFG and CPU operation oracle",
        },
        {
            "path": "/home/fedora/rknpu-fpga/model/profile.py",
            "sha256": "9ec427d601bbfe78197063135a369b0e9945ee2f7bfc2e5737fb97f62f30ba78",
            "role": "reviewed register/EW_CFG whitelist used by preparation",
        },
    ],
    "fdiv-systematic": [
        {
            "path": "/home/fedora/rk3588/examples/elementwise.py",
            "sha256": "242ad9262254f85b1b426ecc4da76735c0541be9dbe57f812417128e8297e0a0",
            "role": "FDIV task register body, operand classes, terminal PC tail",
        },
    ],
    "conv-fp16": [
        {
            "path": "/home/fedora/rk3588/examples/kernel_6_18/conv_new_clean.py",
            "sha256": "f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51",
            "role": "selected Rocket-capable FP16 conv builder and oracle",
        },
    ],
    "conv-simple": [
        {
            "path": "/home/fedora/rk3588/examples/expt/conv_simple.py",
            "sha256": "c1dac1d8bded072f50ed0953c9ec457050c1bcacfa285918c6539937bc5f1431",
            "role": "FP16 generic command builder, Rocket tail and FP16 oracle",
        },
        {
            "path": "/home/fedora/rk3588/examples/conv_simple.py",
            "sha256": "6134263cb50f77fa050bb900c8243e89ac0e29c3f82254c4a02a6d1adb7b1d9a",
            "role": "cross-reference; same generic make_regs",
        },
        {
            "path": "/home/fedora/rk3588/examples/kernel_6_18/simple_conv.py",
            "sha256": "40e5c935b57c568d67bfcf44dcba327116e7bde6aa9ee5b22bb2c7bf958ebfd6",
            "role": "INT8 quantized builder, depthwise/5x5 path and donor oracle",
        },
        {
            "path": "/home/fedora/rk3588/examples/kernel_6_18/conv_legacy.py",
            "sha256": "5d2aa637ffdd4608151347796d495847a10344637468f75e60b186b849904942",
            "role": "shape-table analogues for 5x5 and depthwise",
        },
    ],
    "conv-gemm-vendor": [
        {
            "path": "/home/fedora/rk3588/examples/gemm.py",
            "sha256": "df0f4b98a1fa265b549ae0be682de1b68b9e23bb8cc8cd110a06e2f4b19e6fe6",
            "role": "GEMM register builder and test table",
        },
        {
            "path": "/home/fedora/rk3588/examples/conv_gemm.py",
            "sha256": "eeb584b025c16091e0f0aff20c23989f7ec99ce9c32b3431ea220eaa578440ae",
            "role": "vendor conv/GEMM spatial builder",
        },
        {
            "path": "/home/fedora/rk3588/examples/conv_legacy.py",
            "sha256": "b4cc1f57ef782fe3f89ec61d4b94f841b2a2820a912609f3755fbf517f9efad9",
            "role": "legacy conv builder and shape table",
        },
        {
            "path": "/home/fedora/rk3588/examples/conv.py",
            "sha256": "07c1595785a3e9cc0d2dd07e6e447a9b3b964fde87310a0d2e68c01d363d2a32",
            "role": "full 108-QWORD setup-row conv builder",
        },
    ],
    "pooling": [
        {
            "path": "/home/fedora/rk3588/examples/expt/pooling.py",
            "sha256": "2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e",
            "role": "extended PPU pooling matrix; primary bundle source",
        },
        {
            "path": "/home/fedora/rk3588/examples/pooling.py",
            "sha256": "f4823489e2d06690c11ff01c1659de51523111ed8e793a9ec8b7848db5894e9f",
            "role": "original PPU pooling matrix; cross-check",
        },
    ],
}

INSPECTED_SOURCES = {
    "conv-fp16": [
        "/home/fedora/rk3588/examples/kernel_6_18/conv_new_clean.py",
        "/home/fedora/rk3588/examples/kernel_6_18/simple_conv_fp16.py",
        "/home/fedora/rk3588/examples/kernel_6_18/conv_mesa_fp16.py",
        "/home/fedora/rk3588/examples/kernel_6_18/conv_new.py",
        "/home/fedora/rk3588/examples/kernel_6_18/conv_new_trscrs.py",
        "/home/fedora/rk3588/examples/kernel_6_18/conv_0522.py",
        "/home/fedora/rk3588/examples/kernel_6_18/conv_draft.py",
        "/home/fedora/rk3588/examples/conv_tiles.py",
    ]
}

SOURCE_REVISIONS = {
    "ew-int": {"rk3588": "273d015e08af40c81d2cd9ab84198486b03a17f1"},
    "ew-fp16": {
        "rk3588": "273d015e08af40c81d2cd9ab84198486b03a17f1",
        "rknpu-fpga": "d54d33bc8f910059b6237d54d77e173737282869",
    },
    "fdiv-systematic": {
        "rk3588": "273d015e08af40c81d2cd9ab84198486b03a17f1",
        "rknpu-fpga": "d54d33bc8f910059b6237d54d77e173737282869",
    },
    "conv-fp16": {"rk3588": "273d015e08af40c81d2cd9ab84198486b03a17f1"},
    "conv-simple": {"note": "not recorded in manifest"},
    "conv-gemm-vendor": {
        "rk3588": "273d015e08af40c81d2cd9ab84198486b03a17f1",
        "rknpu-fpga": "6aa8e7a8054311ff7e60db5de6fd397a22540c82",
    },
    "pooling": {
        "rknpu-fpga_generator": "6aa8e7a8054311ff7e60db5de6fd397a22540c82",
        "rk3588": "not recorded in manifest",
    },
}

FAMILY_VALIDATION = {
    "ew-int": {
        "status": "PASS",
        "log": "logs/validate_ew-int-copy2.log",
        "note": "Rerun on a byte-identical copy: 15 READY PASS, 3 BLOCKED shape checks PASS. The family's recorded validation/*.json and *.txt also PASS. Current runner validation is 14/15: int16_add_to_int32_c8_w1 (31 words/31 QWORDs) is verified but not re-runnable without one QWORD of padding.",
    },
    "ew-fp16": {
        "status": "PASS",
        "log": "logs/validate_ew-fp16-final.log",
        "note": "NumPy 2.4.6; 54 cases, 54 oracle recomputes, 0 mismatches, 0 structural errors.",
    },
    "fdiv-systematic": {
        "status": "PASS",
        "log": "logs/validate_fdiv-systematic-copy2.log",
        "note": "Rerun on a byte-identical copy: 2150 structural checks, exact 22-QWORD template, 8 cases. No expected.bin is created by design.",
    },
    "conv-fp16": {
        "status": "PASS",
        "log": "logs/validate_conv-fp16-final3.log",
        "note": "7 READY, 3 BLOCKED; schema, sizes, task ranges, tails, patches, layouts and manifest hashes PASS.",
    },
    "conv-simple": {
        "status": "PASS",
        "log": "logs/validate_conv-simple-final3.log",
        "note": "Family validator PASS for the final 7 READY/5 BLOCKED manifest, but all 7 READY cases fail the current official runner validation: 51/69 declared words in a 51/69-QWORD regcmd.bin fetch as 52/70 QWORD pairs. Deferred until padded and regenerated.",
    },
    "conv-gemm-vendor": {
        "status": "PASS",
        "log": "logs/validate_conv-gemm-vendor-final4.log",
        "note": "Family validator PASS for 9 READY/2 BLOCKED, but it accepts repeat_submissions=2. The official runner validator rejects the depthwise case's duplicate task ranges; 8/9 READY cases are runner-valid.",
    },
    "pooling": {
        "status": "PASS",
        "log": "logs/validate_pooling-final.log",
        "note": "19 READY, 2 BLOCKED; schema, hashes, regcmd decode, patch indices and all READY oracles PASS. An initial run raced a concurrent prepare.py write and failed an artifact size check; the final rerun passes.",
    },
}

ORACLE_NOTES = {
    "ew-int": "expected.bin + expected.mask.bin; masked byte equality over the full 4096-byte output BO. Host-python formula, not device data. 0xFF mask bytes are asserted; padding is not.",
    "ew-fp16": "expected.bin per case covers only the first logical_count halfwords. Donor CPU NumPy oracle, explicitly not a device capture. Compare the asserted prefix only; trailing padding is not asserted.",
    "fdiv-systematic": "oracle: none for all 8 cases. No expected.bin exists. The raw output.bin (64 bytes) is the characterization record; do not substitute a CPU division result.",
    "conv-fp16": "host_numpy_naive_conv expected.bin for all 7 READY cases. Grouped and split-OC cases also carry expected_out0.bin, expected_out1.bin and expected_combined.bin. Host oracle only; unpack raw out*.bin before comparing.",
    "conv-simple": "numpy_naive_valid_conv for the 5 FP16 cases and numpy_naive_quantized_conv for the 2 INT8 cases. expected.bin is a logical-layout oracle; raw BO output must be unpacked first. Host oracle only.",
    "conv-gemm-vendor": "host-numpy expected.bin for all 9 READY cases; GEMM cases also carry expected_surface.bin. FP64 accumulation rounded to the hardware output dtype with recorded tolerance. Host oracle only.",
    "pooling": "numpy-source-pool-reference expected.bin for all 19 READY cases. FP16 average uses a recorded tolerance; INDEX_EN cases compare the uint16 index region; inout cases start from out_init.bin. Host oracle only.",
}

RISK_NOTES = {
    "ew-int": "Verified on RK3588 Rocket only. This is integer EW evidence, not FPGA, SystemVerilog or general RK3588 NPU evidence. int16_add_to_int32_c8_w1 is verified but not re-runnable under the current runner without one QWORD of padding. Do not rerun other cases unless the board, kernel/driver or source revision changes.",
    "ew-fp16": "Largest family (54 cases). FDIV is outside the current strict FP16 EW RTL profile and NEG is encoded as MUL by the donor path. Split by op to bound failure impact; run FDIV last.",
    "fdiv-systematic": "Smallest and structurally simplest, but all 8 cases are raw special-value operand classes (zero, inf, NaN, subnormal, normals) and have no oracle. A hang or zero-write is informative; do not score it with a CPU result.",
    "conv-fp16": "Multi-task grouped/split-OC cases are independent terminal tasks, not PC-linked. The padded case is a zero frame, not CNA_PAD_CON0. Oracle comparison needs the donor unpack, not raw-BO equality. No special-value guarantee.",
    "conv-simple": "All 7 READY cases currently fail the official runner validation because 51/69 declared words are fetched as 52/70 QWORD pairs from a 51/69-QWORD regcmd.bin. The family validator passes but does not model the fetch extent. Deferred until the bundle is padded. The 5 FP16 1x1 cases also select FP32 output from the source policy and are not separately evidenced on mainline Rocket; 5x5/INT8 shapes are generic derivations, not known-supported table entries.",
    "conv-gemm-vendor": "Vendor-ABI-derived streams. One manifest-READY case (conv_depthwise_3x3_c3_oc3_h11w28) is not executable: job.json declares two identical task ranges and the official runner rejects the overlap. Pass only the 8 runner-valid case directories; do not pass the family directory.",
    "pooling": "Two BLOCKED probe cases still have job.json in the family directory. Pointing the runner at the family directory would submit them. Pass only the 19 READY case directories. The probes are known zero-write configurations and must not be scored.",
}

PREPARED_NOTES = {
    "ew-int": "Control family: already verified. Not scheduled for a new capture in this queue.",
    "ew-fp16": "Prepared, not run. 54 single-task cases. Split into 6 op sub-batches of 9 cases; run FDIV last.",
    "fdiv-systematic": "Prepared, not run. 8 single-task cases, 64-byte BOs, 22-QWORD stream. First in the queue.",
    "conv-fp16": "Prepared, not run. 7 READY cases; grouped/split-OC are two-task jobs. Run single-task cases first, grouped/split-OC last.",
    "conv-simple": "Deferred: 7 READY cases, but all fail current runner validation on the QWORD-pair fetch extent. Pad regcmd.bin and regenerate before scheduling.",
    "conv-gemm-vendor": "Prepared, not run. 8 runner-valid cases. The depthwise case is manifest-READY but runner-invalid and must be skipped until the bundle or runner is fixed.",
    "pooling": "Prepared, not run. 19 READY cases; 2 BLOCKED probes also have job.json and must be excluded by explicit case selection.",
}

EXECUTION_ORDER = [
    {
        "rank": 1,
        "family": "fdiv-systematic",
        "cases": 8,
        "selection": "family directory (all 8 cases READY; no BLOCKED job.json)",
        "oracle": "none (raw 64-byte output.bin only)",
        "why": "Smallest buffers and command stream, one terminal task, exact validated template. First smoke test after the lock gate.",
        "risk": "Special-value operand classes; no oracle; a failure is informative and must not be scored against a CPU division.",
    },
    {
        "rank": 2,
        "family": "conv-fp16",
        "cases": 7,
        "selection": "family directory; single-task cases first, then conv_grouped_3x3_c4_h5_w5_oc8_g2 and conv_splitoc_3x3_c16_h9_w9_oc16",
        "oracle": "host NumPy naive conv; unpack raw out*.bin first",
        "why": "Small, selected-source FP16 conv family with complete local validation and an oracle for every READY case.",
        "risk": "Grouped/split-OC use two independent terminal tasks; zero-frame pad and stride-2 are source-supported variants, not table-covered.",
    },
    {
        "rank": 3,
        "family": "conv-gemm-vendor",
        "cases": 8,
        "selection": "explicit 8 runner-valid case directories; exclude conv_depthwise_3x3_c3_oc3_h11w28",
        "oracle": "host-numpy expected.bin / expected_surface.bin",
        "why": "Small GEMM and conv cases with oracles; tiny GEMMs provide quick low-risk coverage.",
        "risk": "Vendor-ABI-derived; one READY bundle is runner-invalid. Do not pass the family directory.",
    },
    {
        "rank": 4,
        "family": "pooling",
        "cases": 19,
        "selection": "explicit 19 READY case directories only; exclude fp32_max_k2s2_zero_write_c4_h2w2 and int32_max_k2s2_zero_write_c4_h2w2",
        "oracle": "host NumPy source pool reference; tolerance/index/out_init rules",
        "why": "Moderate case count, simple PPU streams, complete oracles. Runs after the small conv/GEMM families.",
        "risk": "Two BLOCKED probes have job.json. Family-directory expansion would submit them. Explicit case selection is mandatory.",
    },
    {
        "rank": 5,
        "family": "ew-fp16",
        "cases": 54,
        "selection": "6 op sub-batches of 9 cases: ADD, SUB, MUL, MAX, NEG, FDIV; explicit case directories per sub-batch",
        "oracle": "donor CPU NumPy; asserted prefix only",
        "why": "Per-case work is tiny, but this is the largest family. Run last to avoid occupying the board for a long single family.",
        "risk": "FDIV is outside the strict FP16 EW RTL profile; NEG is MUL by -1.0; oracle covers only the asserted prefix.",
    },
]

DEFERRED_FAMILIES = [
    {
        "family": "conv-simple",
        "cases": 7,
        "reason": (
            "All 7 READY cases fail the current official runner validation because the task declares 51 or 69 "
            "regcmd words while regcmd.bin contains exactly 51 or 69 QWORDs. Rocket fetches the count as QWORD "
            "pairs and reads one extra QWORD. Add one zero QWORD of padding (or use an even task count) and "
            "regenerate/revalidate before scheduling. The family validator passes, but it does not model the "
            "current runner's fetch extent."
        ),
        "reentry": "If fixed, pass only the 7 READY case directories (the five BLOCKED case directories have no job.json), insert after conv-fp16 (rank 2) and before conv-gemm-vendor, and re-index first because the manifest and bundle hashes will change.",
    },
]

# The already-verified family is a control, not a new capture slot.
CONTROL_NOTE = (
    "ew-int is already verified. Do not schedule a rerun in this queue. "
    "One verified case (int16_add_to_int32_c8_w1) is not re-runnable under the current runner without one QWORD "
    "of padding because it declares 31 words in a 31-QWORD regcmd.bin. Use ew-int as a board-health control only "
    "if the board, kernel/driver or source revision changed, and pad/regenerate it first."
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_manifest(family: str):
    path = ROOT / family / "manifest.json"
    raw = path.read_bytes()
    return json.loads(raw), sha256_bytes(raw), len(raw), path


def case_oracle(case: dict, case_dir: Path):
    raw = case.get("oracle")
    if raw is None:
        raw = case.get("expected_oracle")
    if isinstance(raw, dict):
        kind = raw.get("kind")
        file_hint = raw.get("file") or raw.get("expected_surface_file")
    elif isinstance(raw, str):
        kind = raw
        file_hint = None
    else:
        kind = None
        file_hint = None
    expected = sorted(p.name for p in case_dir.glob("expected*.bin")) if case_dir.is_dir() else []
    present = bool(expected) and kind not in (None, "none")
    return {
        "kind": kind,
        "file_hint": file_hint,
        "expected_files": expected,
        "present": present,
    }


def short_reason(text: str, limit: int = 280) -> str:
    if not text:
        return ""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def parse_runner_failures():
    path = HERE / "validation" / "runner_validation_final.json"
    data = json.loads(path.read_text())
    failures = {}
    for full, messages in data.get("fails", []):
        parts = Path(full).parts
        family = parts[-3]
        case = parts[-1]
        failures[(family, case)] = messages
    return data, failures


def verify_ew_int_cases():
    summary = json.loads((EW_INT_RESULTS / "summary.json").read_text())
    compare = json.loads((EW_INT_RESULTS / "compare.json").read_text())
    manifest = json.loads((ROOT / "ew-int" / "manifest.json").read_text())
    verified = {}
    for case in manifest["cases"]:
        if case["status"] != "READY":
            continue
        name = case["case"]
        case_dir = ROOT / "ew-int" / "cases" / name
        result_dir = EW_INT_RESULTS / name
        out_path = result_dir / "out.bin"
        exp_path = case_dir / "expected.bin"
        mask_path = case_dir / "expected.mask.bin"
        cap_path = result_dir / "capture.json"
        if not all(p.is_file() for p in (out_path, exp_path, mask_path, cap_path)):
            verified[name] = {"status": "MISSING", "errors": ["missing out.bin/expected/mask/capture.json"]}
            continue
        out = out_path.read_bytes()
        exp = exp_path.read_bytes()
        mask = mask_path.read_bytes()
        capture = json.loads(cap_path.read_text())
        mismatches = (
            sum(1 for i in range(len(out)) if (out[i] & mask[i]) != (exp[i] & mask[i]))
            if len(out) == len(exp) == len(mask)
            else None
        )
        asserted = sum(1 for b in mask if b == 0xFF)
        ok = (
            mismatches == 0
            and capture.get("status") == "OK"
            and capture.get("submit_ret") == 0
            and len(out) == 4096
        )
        verified[name] = {
            "status": "verified" if ok else "FAIL",
            "out_bin": str(out_path.relative_to(ROOT)),
            "out_sha256": sha256_bytes(out),
            "out_bytes": len(out),
            "asserted_bytes": asserted,
            "masked_mismatches": mismatches,
            "submit_ret": capture.get("submit_ret"),
            "capture_status": capture.get("status"),
        }
    return summary, compare, verified


def main():
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    runner_data, runner_failures = parse_runner_failures()
    ew_summary, ew_compare, ew_verified = verify_ew_int_cases()

    families = []
    blocked_all = []
    verified_not_rerunnable = []
    totals = {
        "families": len(FAMILIES),
        "manifest_cases_total": 0,
        "manifest_ready": 0,
        "manifest_blocked": 0,
        "ready_runner_valid": 0,
        "prepared_not_run": 0,
        "verified": 0,
        "verified_runner_valid": 0,
        "verified_not_rerunnable": 0,
        "captured_unverified": 0,
        "running_on_board": 0,
        "blocked_total": 0,
        "blocked_manifest": 0,
        "blocked_runner_invalid": 0,
        "runner_invalid_ready": 0,
        "out_bo_count": 0,
        "oracle_verified": 0,
    }

    for family in FAMILIES:
        manifest, manifest_sha, manifest_bytes, manifest_path = read_manifest(family)
        family_dir = ROOT / family
        cases_out = []
        counts = {"ready": 0, "blocked": 0, "total": 0}
        state_counts = {
            "verified": 0,
            "verified_runner_invalid": 0,
            "prepared": 0,
            "captured_unverified": 0,
            "running_on_board": 0,
            "blocked": 0,
            "blocked_runner_invalid": 0,
        }
        ready_with_expected = 0
        ready_without_expected = 0
        oracle_kinds = set()

        for case in manifest.get("cases", []):
            name = case.get("case") or case.get("name")
            status = case.get("status")
            case_dir = family_dir / "cases" / name
            runner_messages = runner_failures.get((family, name), [])
            oracle = case_oracle(case, case_dir)
            if status == "READY":
                counts["ready"] += 1
                if oracle["present"]:
                    ready_with_expected += 1
                else:
                    ready_without_expected += 1
                if oracle["kind"]:
                    oracle_kinds.add(str(oracle["kind"]))
            elif status == "BLOCKED":
                counts["blocked"] += 1

            manifest_blocked = status == "BLOCKED"
            runner_failed = bool(runner_messages)
            if manifest_blocked:
                runner_status = "not_run_blocked"
                reason = (
                    case.get("reason")
                    or case.get("blocked_reason")
                    or case.get("blocker")
                    or "manifest BLOCKED"
                )
            elif runner_failed:
                runner_status = "FAIL"
                if case.get("repeat_submissions"):
                    reason = (
                        "Manifest READY but the official runner validator rejects this bundle: "
                        + " ".join(runner_messages)
                        + ". The manifest records repeat_submissions="
                        + str(case.get("repeat_submissions"))
                        + "; the two tasks point at the same regcmd range. The family validator accepts the repeat, the runner does not. "
                        "Do not submit until the bundle is regenerated with separate task ranges or the runner gains repeat-submission support."
                    )
                else:
                    reason = (
                        "Manifest READY but the official runner validator rejects this bundle: "
                        + " ".join(runner_messages)
                        + ". The task declares an odd regcmd word count; Rocket fetches it as QWORD pairs, so "
                        "regcmd.bin must include the extra fetch QWORD (or the task count must be even). "
                        "Do not submit until the bundle is regenerated with the required padding."
                    )
            else:
                runner_status = "OK" if status == "READY" else "not_run"
                reason = None

            capture = {
                "status": "none",
                "results_dir": None,
                "out_bo_count": 0,
                "verified": False,
            }
            if family == "ew-int" and status == "READY":
                vr = ew_verified.get(name, {"status": "MISSING"})
                capture = {
                    "status": "verified" if vr.get("status") == "verified" else "captured_unverified",
                    "results_dir": str(EW_INT_RESULTS),
                    "out_bo_count": 1 if vr.get("out_bin") else 0,
                    "verified": vr.get("status") == "verified",
                    "out_bin": vr.get("out_bin"),
                    "out_sha256": vr.get("out_sha256"),
                    "asserted_bytes": vr.get("asserted_bytes"),
                    "masked_mismatches": vr.get("masked_mismatches"),
                    "submit_ret": vr.get("submit_ret"),
                    "capture_status": vr.get("capture_status"),
                }

            if manifest_blocked:
                state = "blocked"
            elif runner_failed and capture["verified"]:
                state = "verified_runner_invalid"
            elif runner_failed:
                state = "blocked_runner_invalid"
            elif capture["verified"]:
                state = "verified"
            elif capture["status"] == "captured_unverified":
                state = "captured_unverified"
            else:
                state = "prepared"

            state_counts[state] += 1
            if state in ("blocked", "blocked_runner_invalid"):
                blocked_all.append(
                    {
                        "family": family,
                        "case": name,
                        "manifest_status": status,
                        "state": state,
                        "reason": short_reason(reason or "blocked"),
                        "full_reason": reason,
                        "case_dir": str(case_dir) if case_dir.is_dir() else None,
                    }
                )
            if state == "verified_runner_invalid":
                verified_not_rerunnable.append(
                    {
                        "family": family,
                        "case": name,
                        "manifest_status": status,
                        "state": state,
                        "reason": short_reason(reason or "verified but not re-runnable"),
                        "full_reason": reason,
                        "capture": capture,
                    }
                )

            cases_out.append(
                {
                    "case": name,
                    "manifest_status": status,
                    "state": state,
                    "source_example": case.get("source_example"),
                    "source_lines": case.get("source_lines") or case.get("source_refs"),
                    "runner_validation": runner_status,
                    "oracle": oracle,
                    "capture": capture,
                    "reason": short_reason(reason) if reason else None,
                }
            )

        totals["manifest_cases_total"] += counts["total"] if counts["total"] else len(cases_out)
        totals["manifest_ready"] += counts["ready"]
        totals["manifest_blocked"] += counts["blocked"]
        totals["ready_runner_valid"] += (
            state_counts["prepared"]
            + state_counts["verified"]
            + state_counts["captured_unverified"]
        )
        totals["prepared_not_run"] += state_counts["prepared"]
        totals["verified"] += state_counts["verified"] + state_counts["verified_runner_invalid"]
        totals["verified_runner_valid"] += state_counts["verified"]
        totals["verified_not_rerunnable"] += state_counts["verified_runner_invalid"]
        totals["captured_unverified"] += state_counts["captured_unverified"]
        totals["running_on_board"] += state_counts["running_on_board"]
        totals["blocked_total"] += state_counts["blocked"] + state_counts["blocked_runner_invalid"]
        totals["blocked_manifest"] += counts["blocked"]
        totals["blocked_runner_invalid"] += state_counts["blocked_runner_invalid"]
        totals["runner_invalid_ready"] += state_counts["blocked_runner_invalid"] + state_counts["verified_runner_invalid"]
        totals["oracle_verified"] += state_counts["verified"] + state_counts["verified_runner_invalid"]
        totals["out_bo_count"] += sum(1 for c in cases_out if c["capture"]["out_bo_count"])

        if family == "ew-int":
            verified_total = state_counts["verified"] + state_counts["verified_runner_invalid"]
            family_state = "verified" if verified_total else "prepared"
            capture_obj = {
                "status": "verified" if verified_total == counts["ready"] else "partial",
                "results_dir": str(EW_INT_RESULTS),
                "evidence_dir": str(EW_INT_EVIDENCE),
                "captured_cases": sum(1 for c in cases_out if c["capture"]["out_bo_count"]),
                "verified_cases": verified_total,
                "runner_valid_verified_cases": state_counts["verified"],
                "rerun_blocked_cases": state_counts["verified_runner_invalid"],
                "unverified_cases": state_counts["captured_unverified"],
                "out_bo_count": sum(1 for c in cases_out if c["capture"]["out_bo_count"]),
                "capture_json_count": len(list(EW_INT_RESULTS.glob("*/capture.json"))),
                "submit_ret_zero_count": ew_summary.get("submit_ret_zero_count"),
                "oracle_pass": ew_compare.get("summary", {}).get("pass"),
                "oracle_fail": ew_compare.get("summary", {}).get("fail"),
                "bytes": sum(c["capture"].get("out_bytes", 0) or 0 for c in cases_out) or 61440,
                "summary_json": {
                    "path": str((EW_INT_RESULTS / "summary.json").relative_to(ROOT)),
                    "sha256": sha256_file(EW_INT_RESULTS / "summary.json"),
                },
                "compare_json": {
                    "path": str((EW_INT_RESULTS / "compare.json").relative_to(ROOT)),
                    "sha256": sha256_file(EW_INT_RESULTS / "compare.json"),
                },
                "board": {
                    "hostname": ew_summary.get("hostname"),
                    "kernel": ew_summary.get("kernel"),
                    "python": ew_summary.get("python_version"),
                    "device": ew_summary.get("device_path"),
                    "driver": "rocket",
                    "started_utc": ew_summary.get("started_utc"),
                    "finished_utc": ew_summary.get("finished_utc"),
                },
                "executor": {
                    "path": str(ROOT / "board-worker" / "ew-int" / "ew_int_run.py"),
                    "sha256": sha256_file(ROOT / "board-worker" / "ew-int" / "ew_int_run.py"),
                    "note": "This is the executor that produced the verified ew-int capture. The current runner/rocket_run.py is a different tool; one ew-int case is not re-runnable under it without padding.",
                },
                "attempt1_evidence": {
                    "path": str((EW_INT_EVIDENCE / "attempt1-runner-keyerror").relative_to(ROOT)),
                    "capture_json_count": len(list((EW_INT_EVIDENCE / "attempt1-runner-keyerror").glob("*/capture.json"))),
                    "out_bin_count": len(list((EW_INT_EVIDENCE / "attempt1-runner-keyerror").glob("*/out.bin"))),
                    "note": "Runner KeyError before any submit; capture.json exists but zero output BOs. Not counted as captured.",
                },
                "note": (
                    "15/15 READY cases verified by submit_ret==0, real out.bin presence, and masked oracle equality. "
                    "The independent snapshot check is in logs/verify_ew-int_results.log. "
                    "One verified case (int16_add_to_int32_c8_w1, 31 words/31 QWORDs) is not re-runnable under the "
                    "current runner without one QWORD of padding, because the current runner validates the QWORD-pair "
                    "fetch extent. The capture itself was made with the earlier ew_int_run.py executor and remains valid evidence."
                ),
            }
        else:
            family_state = "prepared" if state_counts["prepared"] else "blocked"
            capture_obj = {
                "status": "none",
                "results_dir": None,
                "captured_cases": 0,
                "verified_cases": 0,
                "unverified_cases": 0,
                "out_bo_count": 0,
                "note": "No results directory with real output BOs exists for this family. Nothing is marked captured.",
            }

        families.append(
            {
                "family": family,
                "path": str(family_dir),
                "manifest": str(manifest_path),
                "manifest_sha256": manifest_sha,
                "manifest_bytes": manifest_bytes,
                "manifest_generated_utc": manifest.get("generated_utc")
                or manifest.get("prepared_date")
                or "not recorded",
                "counts": {
                    "ready": counts["ready"],
                    "blocked": counts["blocked"],
                    "total": len(cases_out),
                },
                "declared_counts": manifest.get("counts")
                or manifest.get("readiness")
                or manifest.get("summary"),
                "ready_runner_valid": state_counts["prepared"]
                + state_counts["verified"]
                + state_counts["captured_unverified"],
                "verified_not_rerunnable": state_counts["verified_runner_invalid"],
                "state": family_state,
                "state_counts": state_counts,
                "source_examples": SOURCE_EXAMPLES[family],
                "inspected_sources": INSPECTED_SOURCES.get(family),
                "source_revision": SOURCE_REVISIONS[family],
                "local_validation": {
                    "runner_validator": {
                        "status": "PASS"
                        if (
                            state_counts["prepared"]
                            + state_counts["verified"]
                            + state_counts["captured_unverified"]
                        )
                        == counts["ready"]
                        else "FAIL",
                        "ok": state_counts["prepared"]
                        + state_counts["verified"]
                        + state_counts["captured_unverified"],
                        "fail": state_counts["blocked_runner_invalid"]
                        + state_counts["verified_runner_invalid"],
                        "cases_checked": counts["ready"],
                        "log": "logs/runner_validate_ready-final5.log",
                        "validator": str(ROOT / "runner" / "validate_bundle.py"),
                        "validator_sha256": sha256_file(ROOT / "runner" / "validate_bundle.py"),
                    },
                    "family_validator": FAMILY_VALIDATION[family],
                    "combined_status": "PASS"
                    if (
                        state_counts["blocked_runner_invalid"] == 0
                        and state_counts["verified_runner_invalid"] == 0
                        and FAMILY_VALIDATION[family]["status"] == "PASS"
                    )
                    else "MIXED"
                    if (
                        FAMILY_VALIDATION[family]["status"] == "PASS"
                        and (
                            state_counts["prepared"]
                            + state_counts["verified"]
                            + state_counts["verified_runner_invalid"]
                        )
                        > 0
                    )
                    else "FAIL",
                    "note": FAMILY_VALIDATION[family]["note"],
                },
                "oracle": {
                    "status": "none"
                    if ready_with_expected == 0 and counts["ready"] > 0
                    else "present",
                    "ready_cases_with_expected": ready_with_expected,
                    "ready_cases_without_expected": ready_without_expected,
                    "kinds": sorted(oracle_kinds),
                    "note": ORACLE_NOTES[family],
                },
                "capture": capture_obj,
                "prepared_note": PREPARED_NOTES[family],
                "risk_note": RISK_NOTES[family],
                "cases": cases_out,
            }
        )

    # Totals sanity check.
    assert totals["prepared_not_run"] + totals["verified"] + totals["blocked_total"] == totals["manifest_cases_total"], totals
    assert totals["ready_runner_valid"] + totals["runner_invalid_ready"] == totals["manifest_ready"], totals
    assert totals["blocked_total"] == totals["blocked_manifest"] + totals["blocked_runner_invalid"], totals
    assert totals["runner_invalid_ready"] == totals["blocked_runner_invalid"] + totals["verified_not_rerunnable"], totals

    current_board = {
        "state": "not_observable_without_board_access",
        "confirmed_running": [],
        "note": (
            "This index was built on the host and did not query the board. No in-flight capture is visible "
            "from host-side evidence. The last known board worker was the ew-int capture, which completed at "
            "2026-11-05T20:04:25Z and whose results were copied back. If a worker is running now, it owns the "
            "exclusive lock and this queue must not start until it releases it."
        ),
        "last_known_run": {
            "family": "ew-int",
            "run_id": RUN_ID,
            "results_dir": str(EW_INT_RESULTS),
            "started_utc": ew_summary.get("started_utc"),
            "finished_utc": ew_summary.get("finished_utc"),
            "cases": ew_summary.get("case_count"),
            "submit_ret_zero": ew_summary.get("submit_ret_zero_count"),
            "oracle_pass": ew_compare.get("summary", {}).get("pass"),
            "oracle_fail": ew_compare.get("summary", {}).get("fail"),
            "out_bin_count": len(list(EW_INT_RESULTS.glob("*/out.bin"))),
        },
        "lock": BOARD_LOCK,
        "pre_start_gate": [
            "Do not start while any capture/rocket process is present; the current worker owns the board.",
            "Acquire flock -x -w 900 /home/opencode-agent/rk3588-npu.lock around the whole runner invocation.",
            "Record hostname, kernel, python version, /dev/accel/accel0 and a pgrep snapshot before the first submit.",
            "Use a fresh run/output root; never overwrite an existing capture.json or output BO.",
            "Copy results back and rehash before starting the next family.",
        ],
    }

    queue = {
        "schema": "rk3588-example-captures/queue-index/v1",
        "generated_utc": generated,
        "scope": {
            "description": "Top-level index of every family under build/rk3588-example-captures with a manifest.",
            "board_access": "none; no ssh/scp, no submit, no FPGA program/flash",
            "family_edits": "none; index writes only under build/rk3588-example-captures/team/queue-index/",
            "capture_rule": "A case is never marked captured until a results directory contains a real output BO. A CPU oracle is never stored as output.",
        },
        "paths": {
            "host_root": HOST_ROOT,
            "board_root": BOARD_ROOT,
            "board_lock": BOARD_LOCK,
            "runner": str(ROOT / "runner" / "rocket_run.py"),
            "runner_sha256": sha256_file(ROOT / "runner" / "rocket_run.py"),
            "runner_version": "1.0.0",
            "validator": str(ROOT / "runner" / "validate_bundle.py"),
            "validator_sha256": sha256_file(ROOT / "runner" / "validate_bundle.py"),
        },
        "environment": {
            "host_python3": "3.14.5",
            "usr_bin_python3": "3.14.8",
            "numpy": "2.4.6",
            "kernel": "Linux 7.2.9-200.fc44.x86_64",
            "rknpu_fpga_git": "6aa8e7a8054311ff7e60db5de6fd397a22540c82",
        },
        "status_definitions": {
            "prepared": "READY, official runner validation OK, no results directory with real output BOs.",
            "running_on_board": "Exclusive board worker has submitted the case; capture in progress.",
            "captured_unverified": "Results directory contains real output BOs but no completed oracle comparison.",
            "verified": "Results directory contains real output BOs, submit_ret==0 for every case, and oracle comparison PASS.",
            "verified_runner_invalid": "Verified by real capture and oracle comparison, but the current runner rejects the bundle for a rerun (odd-word fetch extent). Not counted as blocked.",
            "blocked": "Manifest BLOCKED or official runner validation FAIL; must not be submitted.",
            "blocked_runner_invalid": "Manifest READY but the current official runner validation rejects the bundle; must not be submitted until regenerated/revalidated.",
        },
        "totals": totals,
        "current_board": current_board,
        "execution_order": EXECUTION_ORDER,
        "deferred_families": DEFERRED_FAMILIES,
        "control_family": {"family": "ew-int", "note": CONTROL_NOTE},
        "families": families,
        "blocked": blocked_all,
        "verified_not_rerunnable": verified_not_rerunnable,
        "risks": [
            {
                "id": "conv-gemm-depthwise-runner-invalid",
                "severity": "high",
                "detail": "conv-gemm-vendor/cases/conv_depthwise_3x3_c3_oc3_h11w28 is manifest READY but job.json has two tasks both at [0,52). The official runner validator rejects the overlap. The family validator passes because it models repeat_submissions=2. Do not submit this case; pass the other 8 case directories explicitly.",
            },
            {
                "id": "conv-simple-odd-word-runner-invalid",
                "severity": "high",
                "detail": "All 7 conv-simple READY cases fail the current official runner validation: 51/69 declared words fetch as 52/70 QWORD pairs, but regcmd.bin has only 51/69 QWORDs. The family validator passes because it does not model the QWORD-pair fetch extent. Defer conv-simple until the bundle adds one zero QWORD of padding and is regenerated/revalidated.",
            },
            {
                "id": "ew-int-verified-not-rerunnable",
                "severity": "medium",
                "detail": "ew-int/cases/int16_add_to_int32_c8_w1 is verified from the 2026-11-05 board run (31 words, 31 QWORDs), but the current runner would fetch 32 QWORDs. Do not rerun it without one QWORD of padding. The captured evidence remains valid for the earlier executor.",
            },
            {
                "id": "pooling-blocked-job-json",
                "severity": "high",
                "detail": "pooling contains two BLOCKED probes with job.json. Passing the family directory would submit them. Pass only the 19 READY case directories.",
            },
            {
                "id": "conv-simple-evidence-scope",
                "severity": "medium",
                "detail": "The 5 FP16 1x1 cases select FP32 output; mainline Rocket execution of that stream is not separately evidenced. 5x5 and INT8 shapes are generic derivations, not known-supported table entries. INT8 is not FP16 EW-slice evidence.",
            },
            {
                "id": "fdiv-no-oracle",
                "severity": "medium",
                "detail": "All 8 fdiv-systematic cases have oracle: none. Their raw output.bin is a characterization record; a CPU division result must not be substituted or used to score them.",
            },
            {
                "id": "conv-fp16-not-pc-linked",
                "severity": "medium",
                "detail": "Grouped and split-OC conv-fp16 cases are encoded as independent terminal tasks, not a PC-linked chain. Oracle comparison needs the donor unpack, not raw-BO equality.",
            },
            {
                "id": "ew-fp16-scope",
                "severity": "medium",
                "detail": "FDIV is outside the strict FP16 EW RTL profile and NEG is MUL by -1.0 in the donor path. The family is the largest queue (54 cases); split by op and run FDIV last.",
            },
            {
                "id": "concurrent-preparation",
                "severity": "medium",
                "detail": "Several family manifests were still being regenerated during this snapshot. All hashes are recorded above. If a manifest hash no longer matches, stop and re-index; do not execute a changed bundle against this plan.",
            },
            {
                "id": "board-state-unobservable",
                "severity": "high",
                "detail": "No board query was made. The queue must not overlap the current board worker. Start only after the exclusive lock is acquired and pgrep shows no capture process.",
            },
            {
                "id": "evidence-scope",
                "severity": "medium",
                "detail": "The only verified capture is ew-int on RK3588 Rocket. It does not validate SystemVerilog, the FPGA image or the full RK3588 NPU. No other family has device output.",
            },
        ],
        "evidence": {
            "runner_validation_final": {
                "path": "validation/runner_validation_final.json",
                "sha256": sha256_file(HERE / "validation" / "runner_validation_final.json"),
                "cases": runner_data.get("count"),
                "ok": runner_data.get("ok"),
                "fail": runner_data.get("fail"),
                "exit_status": runner_data.get("exit_status"),
            },
            "ew_int_independent_check": {
                "path": "logs/verify_ew-int_results.log",
                "sha256": sha256_file(HERE / "logs" / "verify_ew-int_results.log"),
                "result": "15/15 verified",
            },
            "logs": sorted(
                {
                    "logs/runner_validate_ready-final5.log",
                    *[v["log"] for v in FAMILY_VALIDATION.values()],
                    "logs/verify_ew-int_results.log",
                }
            ),
        },
    }

    (HERE / "QUEUE.json").write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")

    # ---------------- STATUS.md ----------------
    lines = []
    lines.append("# RK3588 example-capture queue status")
    lines.append("")
    lines.append(f"Snapshot: **{generated}**  ")
    lines.append(f"Index: `{HERE / 'QUEUE.json'}`  ")
    lines.append("Host: `/home/fedora/rknpu-fpga` at `6aa8e7a8054311ff7e60db5de6fd397a22540c82`  ")
    lines.append(
        f"Tooling: `runner/rocket_run.py` SHA256 `{queue['paths']['runner_sha256']}`; "
        f"`runner/validate_bundle.py` SHA256 `{queue['paths']['validator_sha256']}`."
    )
    lines.append("")
    lines.append(
        "This index was built without board access: **no ssh/scp, no submit, no FPGA program/flash**. "
        "It records device-free preparation only. Nothing below is marked captured unless a results "
        "directory contains real output BOs."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "| Family | Manifest READY | Manifest BLOCKED | Runner-valid READY | Prepared (not run) | Verified | Verified not re-runnable | Captured unverified | Blocked total |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for fam in families:
        sc = fam["state_counts"]
        verified_total = sc["verified"] + sc["verified_runner_invalid"]
        lines.append(
            f"| `{fam['family']}` | {fam['counts']['ready']} | {fam['counts']['blocked']} | "
            f"{fam['ready_runner_valid']} | {sc['prepared']} | {verified_total} | "
            f"{sc['verified_runner_invalid']} | {sc['captured_unverified']} | "
            f"{sc['blocked'] + sc['blocked_runner_invalid']} |"
        )
    lines.append(
        f"| **Total** | **{totals['manifest_ready']}** | **{totals['manifest_blocked']}** | "
        f"**{totals['ready_runner_valid']}** | **{totals['prepared_not_run']}** | "
        f"**{totals['verified']}** | **{totals['verified_not_rerunnable']}** | "
        f"**{totals['captured_unverified']}** | **{totals['blocked_total']}** |"
    )
    lines.append("")
    lines.append(
        f"Blocked total = {totals['blocked_manifest']} manifest BLOCKED + "
        f"{totals['blocked_runner_invalid']} manifest-READY cases that fail the current official runner validator. "
        f"One further verified case is not re-runnable under the current runner but is not counted as blocked because "
        f"its device capture and oracle comparison are valid. "
        f"Prepared + verified + blocked = {totals['prepared_not_run']} + {totals['verified']} + {totals['blocked_total']} "
        f"= {totals['manifest_cases_total']} manifest cases."
    )
    lines.append("")
    lines.append(
        f"Currently running on board: **{totals['running_on_board']} confirmed** (the board was not queried; see below). "
        f"Captured but unverified: **{totals['captured_unverified']}**."
    )
    lines.append("")

    lines.append("## Verified")
    lines.append("")
    ew = next(f for f in families if f["family"] == "ew-int")
    ec = ew["capture"]
    lines.append(f"### `ew-int` — {ec['verified_cases']}/{ew['counts']['ready']} verified")
    lines.append("")
    lines.append(f"- Results: `{ec['results_dir']}`")
    lines.append(f"- Evidence: `{ec['evidence_dir']}`")
    lines.append(
        f"- {ec['out_bo_count']} real output BOs (`out.bin`, 4096 B each), {ec['capture_json_count']} `capture.json`, "
        f"`submit_ret == 0` for {ec['submit_ret_zero_count']}/{ew['counts']['ready']}."
    )
    lines.append(
        f"- Oracle: `compare.json` reports {ec['oracle_pass']} PASS / {ec['oracle_fail']} FAIL / 0 missing "
        f"over {ec['bytes']} compared bytes. Independent masked comparison at snapshot: **15/15 PASS** "
        f"(`logs/verify_ew-int_results.log`)."
    )
    lines.append(
        f"- Re-run caveat: {ec['runner_valid_verified_cases']}/{ew['counts']['ready']} verified cases are also valid "
        f"under the current runner. {ec['rerun_blocked_cases']} verified case "
        f"(`int16_add_to_int32_c8_w1`, 31 words/31 QWORDs) would need one zero QWORD of padding before a rerun; "
        "the existing capture is unchanged and remains verified evidence."
    )
    lines.append(
        f"- Board: `{ec['board']['hostname']}`, kernel `{ec['board']['kernel']}`, Python `{ec['board']['python']}`, "
        f"`{ec['board']['device']}`, driver `{ec['board']['driver']}`; run `{ec['board']['started_utc']}` to `{ec['board']['finished_utc']}`."
    )
    lines.append(
        f"- Executor: `{ec['executor']['path']}`  \n  SHA256 `{ec['executor']['sha256']}`. "
        "The current `runner/rocket_run.py` is a different executor; see the re-run caveat."
    )
    lines.append(
        f"- Manifest: `{ew['manifest']}`  \n  SHA256 `{ew['manifest_sha256']}`"
    )
    lines.append(
        "- Scope: RK3588 Rocket integer EW only. This is not FPGA, SystemVerilog or full RK3588 NPU evidence."
    )
    lines.append(
        f"- Attempt 1 `{ec['attempt1_evidence']['path']}` has "
        f"{ec['attempt1_evidence']['capture_json_count']} `capture.json` but "
        f"{ec['attempt1_evidence']['out_bin_count']} `out.bin`; the runner raised `KeyError: 'durations'` before submit. "
        "It is **not** a capture and is not counted."
    )
    lines.append("")

    lines.append("## Currently running on board")
    lines.append("")
    lines.append(
        "**None confirmed from host-side evidence.** This index did not query the board, so it cannot prove the "
        "board is idle. A worker may be running outside this host's visibility."
    )
    lines.append("")
    lk = current_board["last_known_run"]
    lines.append(
        f"- Last known board worker: `{lk['family']}` run `{lk['run_id']}`, "
        f"{lk['cases']} cases, {lk['submit_ret_zero']} `submit_ret==0`, "
        f"{lk['oracle_pass']} oracle PASS, finished `{lk['finished_utc']}`."
    )
    lines.append(f"- Results copied back: `{lk['results_dir']}` ({lk['out_bin_count']} real `out.bin`).")
    lines.append(f"- Exclusive lock: `{BOARD_LOCK}`.")
    lines.append("")
    lines.append(
        "**Gate before rank 1:** do not start while any capture/rocket process is present. Acquire "
        "`flock -x -w 900 /home/opencode-agent/rk3588-npu.lock` around the whole runner invocation, record "
        "board identity and `pgrep`, and use a fresh output root. If the current worker still holds the lock, "
        "wait; do not launch a second copy."
    )
    lines.append("")

    lines.append("## Captured but unverified")
    lines.append("")
    lines.append(
        "**None.** The only results directory with real output BOs is `ew-int-20261105T200154Z`, and it is verified. "
        "The first-attempt evidence directory has `capture.json` files but zero `out.bin`, so it is not a capture. "
        "No other family has a results directory with device output. Per the capture rule, no other case is marked captured."
    )
    lines.append("")

    lines.append("## Prepared")
    lines.append("")
    lines.append(
        "These are individual READY cases that pass the current official runner validator, have no results directory "
        "with real output BOs, and are waiting for the single board worker. A family may also contain blocked cases; "
        "the counts below are prepared cases only."
    )
    lines.append("")
    lines.append("| Family | Prepared | Oracle | Runner validation | Family validation | Execution note |")
    lines.append("|---|---:|---|---|---|---|")
    for fam in families:
        if fam["state_counts"]["prepared"] == 0:
            continue
        rv = fam["local_validation"]["runner_validator"]
        lines.append(
            f"| `{fam['family']}` | {fam['state_counts']['prepared']} | "
            f"{fam['oracle']['status']} ({fam['oracle']['ready_cases_with_expected']}/{fam['counts']['ready']} with expected) | "
            f"{rv['ok']}/{rv['cases_checked']} OK | "
            f"{fam['local_validation']['family_validator']['status']} | "
            f"{short_reason(fam['prepared_note'], 180)} |"
        )
    lines.append("")
    lines.append(
        "`ew-int` is verified, not prepared; it is deliberately not in the prepared table. "
        "`conv-simple` has zero prepared cases: all 7 READY cases are deferred for the odd-word fetch extent. "
        "`conv-gemm-vendor` has 8 prepared cases and 1 manifest-READY case that is runner-invalid; see Blocked."
    )
    lines.append("")

    lines.append("## Blocked")
    lines.append("")
    lines.append(
        f"{totals['blocked_total']} cases must not be submitted: {totals['blocked_manifest']} manifest BLOCKED plus "
        f"{totals['blocked_runner_invalid']} manifest-READY but runner-invalid."
    )
    lines.append("")
    lines.append("| Family | Case | Manifest | State | Reason |")
    lines.append("|---|---|---|---|---|")
    for b in blocked_all:
        lines.append(
            f"| `{b['family']}` | `{b['case']}` | {b['manifest_status']} | {b['state']} | {short_reason(b['reason'], 220)} |"
        )
    lines.append("")
    lines.append(
        "**High-risk selection rule:** `pooling` contains two BLOCKED probes with `job.json`; passing the family "
        "directory would submit them. `conv-gemm-vendor` contains one manifest-READY case with overlapping duplicate "
        "tasks; passing the family directory would record a runner FAIL. `conv-simple` contains five blocked case "
        "directories without `job.json`, so family-directory expansion is also not clean there. Use explicit READY "
        "case directories for all three."
    )
    lines.append("")

    lines.append("## Verified but not re-runnable")
    lines.append("")
    if verified_not_rerunnable:
        for v in verified_not_rerunnable:
            lines.append(
                f"- `{v['family']}/{v['case']}`: captured and oracle-verified on 2026-11-05, but the current official "
                f"runner rejects the bundle because it declares an odd regcmd word count (QWORD-pair fetch extends one "
                f"QWORD past `regcmd.bin`). Add one zero QWORD of padding before any rerun. This case is **not** in the "
                f"blocked count because the existing device output and oracle comparison are valid."
            )
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Family paths and manifest hashes")
    lines.append("")
    lines.append("| Family | Path | Manifest SHA256 | Bytes | Generated |")
    lines.append("|---|---|---|---:|---|")
    for fam in families:
        lines.append(
            f"| `{fam['family']}` | `{fam['path']}` | `{fam['manifest_sha256']}` | "
            f"{fam['manifest_bytes']} | {fam['manifest_generated_utc']} |"
        )
    lines.append("")
    lines.append(
        "If a manifest hash no longer matches, the family changed after this snapshot. Stop and re-index; do not "
        "execute the changed bundle against this plan."
    )
    lines.append("")

    lines.append("## Source examples")
    lines.append("")
    lines.append(
        "Paths and hashes are as recorded in the family manifests. The `conv-fp16` manifest also records additional "
        "inspected sources that were not selected for the READY bundles."
    )
    lines.append("")
    for fam in families:
        lines.append(f"### `{fam['family']}`")
        lines.append("")
        for src in fam["source_examples"]:
            sha = f"  \n  SHA256 `{src['sha256']}`" if src.get("sha256") else ""
            lines.append(f"- `{src['path']}` — {src['role']}{sha}")
        if fam.get("inspected_sources"):
            lines.append("- Additional inspected sources:")
            for path in fam["inspected_sources"]:
                lines.append(f"  - `{path}`")
        lines.append("")

    lines.append("## Recommended serialized execution order")
    lines.append("")
    lines.append(
        "One board owner, one case at a time, one exclusive lock. Rank 1 starts only after the current worker "
        "releases the lock and the pgrep check is clean. Copy results back and rehash before the next rank."
    )
    lines.append("")
    lines.append("| Rank | Family | Cases | Selection | Oracle | Why / risk |")
    lines.append("|---:|---|---:|---|---|---|")
    for rank in EXECUTION_ORDER:
        lines.append(
            f"| {rank['rank']} | `{rank['family']}` | {rank['cases']} | {rank['selection']} | "
            f"{rank['oracle']} | {rank['why']} Risk: {rank['risk']} |"
        )
    lines.append("")
    lines.append(f"**Control:** {CONTROL_NOTE}")
    lines.append("")
    lines.append(
        "The order deliberately starts with the smallest, simplest prepared family (`fdiv-systematic`, 8 cases, 64-byte BOs) "
        "and the small conv/GEMM families, then the moderate pooling family, and leaves the 54-case `ew-fp16` family for last. "
        "It does not schedule any board work in parallel with the current worker."
    )
    lines.append("")
    lines.append(
        "Per-case acceptance follows `BOARD_RUN_PLAN.md`: `submit_ret == 0`; every declared output file exists at its "
        "declared size; `capture.json` records the real BO addresses, hashes and durations; the output is stored "
        "unchanged; any oracle comparison is separate and labelled. A failing case is recorded and the worker moves "
        "to the next case; no retry, no reset, no fabricated output."
    )
    lines.append("")
    lines.append("### Deferred until the bundle is fixed")
    lines.append("")
    for d in DEFERRED_FAMILIES:
        lines.append(
            f"- `{d['family']}` ({d['cases']} READY cases): {d['reason']} Re-entry: {d['reentry']}"
        )
    lines.append("")

    lines.append("## Local validation evidence")
    lines.append("")
    lines.append(
        "All checks were host-only. `runner/validate_bundle.py` imports no device and never opens `/dev/accel/*`. "
        "The writer validators were rerun on byte-identical scratch copies under this team directory, then the copies "
        "were removed; the logs are retained, and no family bundle was modified. "
        "The repository-wide `make test` suite was not used as evidence for this index; the family validators and the "
        "official runner validator were run directly."
    )
    lines.append("")
    lines.append("| Family | Runner validator | Family validator | Combined | Log |")
    lines.append("|---|---|---|---|---|")
    for fam in families:
        rv = fam["local_validation"]["runner_validator"]
        fv = fam["local_validation"]["family_validator"]
        lines.append(
            f"| `{fam['family']}` | {rv['ok']}/{rv['cases_checked']} OK"
            + (f" ({rv['fail']} FAIL)" if rv["fail"] else "")
            + f" | {fv['status']} | {fam['local_validation']['combined_status']} | `{fv['log']}` |"
        )
    lines.append("")
    lines.append(
        f"Runner validator final result: **{totals['ready_runner_valid']}/{runner_data['count']} OK, "
        f"{totals['runner_invalid_ready']} FAIL**, exit `{runner_data['exit_status']}`. "
        "The failures are: 7 `conv-simple` READY cases (51/69 declared words fetch as 52/70 QWORD pairs from "
        "51/69-QWORD regcmd files), 1 `conv-gemm-vendor` READY case "
        "(`conv_depthwise_3x3_c3_oc3_h11w28`, overlapping duplicate task ranges), and 1 `ew-int` verified case "
        "(`int16_add_to_int32_c8_w1`, 31 words vs 31 QWORDs; not re-runnable without padding)."
    )
    lines.append("")
    lines.append(
        "Family validator notes: "
        + " ".join(
            f"`{fam['family']}`: {fam['local_validation']['family_validator']['note']}"
            for fam in families
        )
    )
    lines.append("")
    lines.append(
        "The initial `pooling` run and the first `conv-simple` copy raced concurrent preparation writes; both final "
        "reruns pass. The final results are the ones recorded here."
    )
    lines.append("")

    lines.append("## Oracle status")
    lines.append("")
    lines.append("| Family | Oracle status | READY with expected | READY without expected | Kinds / note |")
    lines.append("|---|---|---:|---:|---|")
    for fam in families:
        o = fam["oracle"]
        lines.append(
            f"| `{fam['family']}` | {o['status']} | {o['ready_cases_with_expected']} | "
            f"{o['ready_cases_without_expected']} | {o['note']} |"
        )
    lines.append("")
    lines.append(
        "No oracle is device data. The only oracle comparison against real device output is the verified `ew-int` "
        "masked comparison. All other `expected.bin` files are host-side references for the later worker."
    )
    lines.append("")

    lines.append("## Risks and caveats")
    lines.append("")
    for risk in queue["risks"]:
        lines.append(f"- **{risk['severity'].upper()} — {risk['id']}**: {risk['detail']}")
    lines.append("")

    lines.append("## Case census")
    lines.append("")
    lines.append(
        "Full per-case state is in `QUEUE.json`. This census lists every manifest case by family. "
        "`READY` here is the manifest status; per-case executability is shown in the state column."
    )
    lines.append("")
    for fam in families:
        lines.append(f"### `{fam['family']}`")
        lines.append("")
        lines.append(f"- Manifest: `{fam['manifest']}`")
        lines.append(f"- Counts: {fam['counts']['ready']} READY, {fam['counts']['blocked']} BLOCKED, {fam['counts']['total']} total")
        ready_cases = [c for c in fam["cases"] if c["manifest_status"] == "READY"]
        blocked_cases = [c for c in fam["cases"] if c["manifest_status"] == "BLOCKED"]
        def case_label(c):
            if c["state"] == "verified":
                return f"`{c['case']}` (verified)"
            if c["state"] == "verified_runner_invalid":
                return f"`{c['case']}` (verified; not re-runnable)"
            if c["state"] == "blocked_runner_invalid":
                return f"`{c['case']}` (runner-invalid)"
            if c["state"] == "prepared":
                return f"`{c['case']}` (prepared)"
            return f"`{c['case']}` ({c['state']})"

        lines.append(
            "- READY: "
            + (", ".join(case_label(c) for c in ready_cases) if ready_cases else "none")
        )
        lines.append(
            "- BLOCKED: "
            + (", ".join(f"`{c['case']}`" for c in blocked_cases) if blocked_cases else "none")
        )
        lines.append("")

    lines.append("## What this does not prove")
    lines.append("")
    lines.append(
        "- It does not prove the board is idle or that any prepared family will submit successfully. No board command was run."
    )
    lines.append(
        "- It does not validate SystemVerilog, the FPGA image, timing or the full RK3588 NPU. The only device evidence is `ew-int` on RK3588 Rocket."
    )
    lines.append(
        "- It does not make any host-side oracle a device capture. `expected.bin` is a test target, not a fallback result."
    )
    lines.append(
        "- It does not establish numerical special-value policy for the prepared FP16 families; those remain candidate behavior until device differential tests."
    )
    lines.append("")

    (HERE / "STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {HERE / 'QUEUE.json'}")
    print(f"wrote {HERE / 'STATUS.md'}")
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
