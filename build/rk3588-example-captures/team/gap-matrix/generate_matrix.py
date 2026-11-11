#!/usr/bin/env python3
"""Build the RK3588 example -> FPGA RTL gap matrix.

Reads only:
  /home/fedora/rk3588/examples/**
  build/rk3588-example-captures/*/manifest.json
  build/rk3588-example-captures/results/**
  rtl/**, docs/**

Writes only:
  build/rk3588-example-captures/team/gap-matrix/{EXAMPLE_MATRIX.json,GAP_MATRIX.md}

No device/board/FPGA access. This is a static census and documentation map.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/fedora/rknpu-fpga")
EXAMPLES = Path("/home/fedora/rk3588/examples")
CAP = ROOT / "build/rk3588-example-captures"
OUT = CAP / "team/gap-matrix"

# ---------------------------------------------------------------------------
# Capture queue parsing
# ---------------------------------------------------------------------------


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_capture_cases():
    manifests = {}
    cases = []
    for manifest_path in sorted(CAP.glob("*/manifest.json")):
        family = manifest_path.parent.name
        data = json.loads(manifest_path.read_text())
        manifests[family] = {
            "path": str(manifest_path),
            "sha256": sha256(manifest_path),
            "case_count": len(data.get("cases", [])),
            "summary": data.get("summary") or data.get("counts") or data.get("readiness"),
        }
        for case in data.get("cases", []):
            item = dict(case)
            item["family"] = family
            item["manifest_status"] = case.get("status")
            item["source_example"] = case.get("source_example")
            cases.append(item)
    return manifests, cases


def _case_outputs(case_dir: Path):
    """Return every real output BO in a case directory.

    Single-task cases use out.bin; multi-task and fdiv cases use out0.bin /
    out1.bin or output.bin. Expected/oracle files are never included.
    """
    outputs = set()
    for pattern in ("out*.bin", "output*.bin"):
        outputs.update(case_dir.glob(pattern))
    return sorted(outputs)


def _run_timestamp(run: str) -> str:
    match = re.search(r"(\d{8}T\d{6}Z)$", run)
    return match.group(1) if match else ""


def load_results(cases):
    """Attach captured/exact/tolerance/known status from host receipts.

    A case is captured only when its result tree contains capture.json plus a
    real output BO. Exact, tolerance-only, known-divergence and truth-table
    states are recorded separately; none is inferred from a manifest.
    When a case appears in more than one run, the newest run timestamp wins
    (this selects the depthwise split rerun over its failed predecessor).
    """
    case_family = {case.get("case"): case["family"] for case in cases}
    captured = {}
    captured_bytes = {}
    exact = {}
    tolerance = {}
    known = {}
    truth = {}
    candidates = {}

    # 1. Discover captures by actual output BOs. This excludes the failed
    # ew-int evidence directory (capture.json but no output BO) and diagnostic
    # task-level trees.
    for capture_path in sorted(CAP.glob("results/**/capture.json")):
        case_dir = capture_path.parent
        outputs = _case_outputs(case_dir)
        if not outputs:
            continue
        rel = capture_path.relative_to(CAP / "results")
        run = rel.parts[0]
        if "diagnostic" in run:
            continue
        name = case_dir.name
        size = sum(path.stat().st_size for path in outputs)
        submit_zero = 0
        try:
            capture = json.loads(capture_path.read_text())
            submit_zero = 1 if capture.get("submit_ret") == 0 else 0
        except Exception:
            pass
        rank = (_run_timestamp(run), run)
        previous = candidates.get(name)
        if previous is None or rank > previous["rank"]:
            candidates[name] = {
                "rank": rank, "run": run, "bytes": size,
                "submit_zero": submit_zero,
            }

    for name, candidate in candidates.items():
        captured[name] = candidate["run"]
        captured_bytes[name] = candidate["bytes"]

    # 2. ew-int style compare.json (masked exact oracle)
    for compare_path in sorted(CAP.glob("results/*/compare.json")):
        run = compare_path.parent.name
        compare = json.loads(compare_path.read_text())
        for case in compare.get("cases", []):
            name = case.get("case")
            if case.get("status") == "PASS":
                exact[name] = run
            elif case.get("status") == "FAIL":
                known[name] = run

    # 3. ew-fp16 style evidence/comparison.json (exact logical region)
    for evidence_compare in sorted(CAP.glob("results/*/evidence/comparison.json")):
        run = evidence_compare.parent.parent.name
        compare = json.loads(evidence_compare.read_text())
        for case in compare.get("cases_report", []):
            name = case.get("case")
            if case.get("logical_region_match"):
                exact[name] = run
            else:
                known[name] = run

    # 4. pooling style host-analysis comparison.json
    for host_compare in sorted(CAP.glob("results/*-host-analysis/comparison.json")):
        analysis_root = host_compare.parent.name
        run = analysis_root.removesuffix("-host-analysis")
        compare = json.loads(host_compare.read_text())
        for case in compare.get("cases", []):
            name = case.get("case")
            if case.get("ok") and case.get("full_bo_exact"):
                exact[name] = run
            elif case.get("ok") and case.get("tolerance_pass"):
                tolerance[name] = run
            elif case.get("ok") is False:
                known[name] = run

    # 5. conv-fp16 style host-analysis/comparison/comparison.json
    for compare_path in sorted(CAP.glob("results/*/host-analysis/comparison/comparison.json")):
        run = compare_path.parent.parent.parent.name
        compare = json.loads(compare_path.read_text())
        if not isinstance(compare, dict):
            continue
        for case in compare.get("cases", []):
            name = case.get("case")
            if case.get("exact_all"):
                exact[name] = run
                tolerance.pop(name, None)
                known.pop(name, None)
            elif case.get("tolerance_all"):
                tolerance[name] = run
                known.pop(name, None)
            elif case.get("capture_status") == "OK":
                known[name] = run

    # 6. conv-gemm-vendor style host-analysis/comparison.json
    for compare_path in sorted(CAP.glob("results/*/host-analysis/comparison.json")):
        run = compare_path.parent.parent.name
        if "conv-simple" in run:
            continue
        compare = json.loads(compare_path.read_text())
        records = compare.get("results") or compare.get("cases") or []
        if not isinstance(records, list):
            continue
        for case in records:
            name = case.get("case")
            if case.get("exact_pass"):
                exact[name] = run
                tolerance.pop(name, None)
                known.pop(name, None)
            elif case.get("tolerance_pass"):
                tolerance[name] = run
                known.pop(name, None)
            elif case.get("capture_status") == "OK":
                known[name] = run

    # 7. Depthwise 15,104-byte BO rerun supersedes the two failed split cases.
    for compare_path in sorted(CAP.glob("results/*depthwise-rerun*/host-analysis/comparison.json")):
        run = compare_path.parent.parent.name
        compare = json.loads(compare_path.read_text())
        records = compare.get("cases", {})
        if isinstance(records, dict):
            records = list(records.values())
        for case in records:
            name = case.get("case")
            if (case.get("logical_mismatches") == 0
                    and case.get("logical_exact_fp16") == case.get("logical_elements")):
                exact[name] = run
                tolerance.pop(name, None)
                known.pop(name, None)

    # 8. conv-simple host-analysis comparison.json
    for compare_path in sorted(CAP.glob("results/conv-simple-*/host-analysis/comparison.json")):
        run = compare_path.parent.parent.name
        compare = json.loads(compare_path.read_text())
        for case in compare.get("cases", []):
            name = case.get("case")
            if case.get("exact_full_match"):
                exact[name] = run
            else:
                known[name] = run

    # 9. fdiv-systematic is a truth table, not a pass/fail oracle.
    for name, run in captured.items():
        if case_family.get(name) == "fdiv-systematic":
            truth[name] = run

    # 10. Aggregate result-run metadata from the selected captures.
    result_runs = {}
    for name, run in captured.items():
        info = result_runs.setdefault(run, {
            "run": run,
            "path": str(CAP / "results" / run),
            "cases": set(),
            "bytes_read_total": 0,
            "submit_ret_zero_count": 0,
        })
        info["cases"].add(name)
        info["bytes_read_total"] += captured_bytes.get(name, 0)
        info["submit_ret_zero_count"] += 1

    for run, info in result_runs.items():
        root = CAP / "results" / run
        summary_path = root / "summary.json"
        evidence_path = root / "run_evidence.json"
        hostname = kernel = started = finished = None
        submit_zero = None
        if summary_path.is_file():
            summary = json.loads(summary_path.read_text())
            hostname = summary.get("hostname")
            kernel = summary.get("kernel")
            started = summary.get("started_utc")
            finished = summary.get("finished_utc")
            submit_zero = summary.get("submit_ret_zero_count")
        elif evidence_path.is_file():
            evidence = json.loads(evidence_path.read_text())
            board = evidence.get("board", {})
            hostname = board.get("hostname")
            kernel = board.get("kernel")
            cases_meta = evidence.get("cases", [])
            started = min((c.get("started_utc") for c in cases_meta if c.get("started_utc")), default=None)
            finished = max((c.get("finished_utc") for c in cases_meta if c.get("finished_utc")), default=None)
            submit_zero = sum(1 for c in cases_meta if c.get("submit_ret") == 0)
        else:
            first = sorted(info["cases"])[0]
            for capture_path in root.glob(f"**/{first}/capture.json"):
                capture = json.loads(capture_path.read_text())
                hostname = (capture.get("hostname")
                            or (capture.get("tool") or {}).get("hostname"))
                kernel = (capture.get("kernel")
                          or (capture.get("device") or {}).get("kernel"))
                started = capture.get("started_utc")
                finished = capture.get("finished_utc")
                break
        info["case_count"] = len(info["cases"])
        info["hostname"] = hostname
        info["kernel"] = kernel
        info["started_utc"] = started
        info["finished_utc"] = finished
        info["submit_ret_zero_count"] = (
            submit_zero if submit_zero is not None
            else info.get("submit_ret_zero_count")
        )
        info["exact_pass"] = sum(1 for c in info["cases"] if c in exact)
        info["tolerance_pass"] = sum(1 for c in info["cases"] if c in tolerance)
        info["known_divergence"] = sum(1 for c in info["cases"] if c in known)
        info["truth_table"] = sum(1 for c in info["cases"] if c in truth)
        info["unverified"] = len(info["cases"]) - (
            info["exact_pass"] + info["tolerance_pass"]
            + info["known_divergence"] + info["truth_table"]
        )
        del info["cases"]

    result_runs = sorted(result_runs.values(), key=lambda item: item["run"])
    return captured, exact, tolerance, known, truth, captured_bytes, result_runs

# No current runner-validator failure is asserted here. The original combined
# depthwise two-task bundle is now manifest-BLOCKED as
# MULTITASK_ROCKET_JOB_UNSUPPORTED and split into two one-task READY cases.
# The older queue-index snapshot that lists runner-invalid cases is stale.
RUNNER_INVALID = {}


def build_capture_index():
    manifests, cases = load_capture_cases()
    captured, exact, tolerance, known, truth, captured_bytes, runs = load_results(cases)
    by_source = defaultdict(lambda: {
        "cases": 0, "ready": 0, "blocked": 0, "captured": 0,
        "bytes": 0, "exact": 0, "tolerance": 0, "known": 0,
        "truth": 0, "unverified": 0, "prepared": 0,
        "runner_invalid": 0, "not_implemented": [],
        "families": set(), "case_list": [],
    })
    family_stats = defaultdict(lambda: {
        "total": 0, "ready": 0, "blocked": 0, "captured": 0,
        "bytes": 0, "exact": 0, "tolerance": 0, "known": 0,
        "truth": 0, "unverified": 0, "prepared": 0,
        "runner_invalid": 0, "not_implemented": 0,
    })
    for case in cases:
        name = case.get("case")
        source = case.get("source_example") or "<none>"
        fam = case["family"]
        status = case.get("manifest_status")
        entry = by_source[source]
        fentry = family_stats[fam]
        entry["cases"] += 1
        fentry["total"] += 1
        entry["families"].add(fam)
        if status == "READY":
            entry["ready"] += 1
            fentry["ready"] += 1
            if name in captured:
                entry["captured"] += 1
                fentry["captured"] += 1
                entry["bytes"] += captured_bytes.get(name, 0)
                fentry["bytes"] += captured_bytes.get(name, 0)
                if name in exact:
                    entry["exact"] += 1
                    fentry["exact"] += 1
                elif name in tolerance:
                    entry["tolerance"] += 1
                    fentry["tolerance"] += 1
                elif name in known:
                    entry["known"] += 1
                    fentry["known"] += 1
                elif name in truth or fam == "fdiv-systematic":
                    entry["truth"] += 1
                    fentry["truth"] += 1
                else:
                    entry["unverified"] += 1
                    fentry["unverified"] += 1
                if fam == "fdiv-systematic" or name.startswith("fdiv_"):
                    entry["not_implemented"].append(name)
                    fentry["not_implemented"] += 1
            elif name in RUNNER_INVALID:
                entry["runner_invalid"] += 1
                fentry["runner_invalid"] += 1
            else:
                entry["prepared"] += 1
                fentry["prepared"] += 1
        elif status == "BLOCKED":
            entry["blocked"] += 1
            fentry["blocked"] += 1
        blocker_text = (case.get("blocker") or case.get("reason")
                        or case.get("blocked_reason") or case.get("block_reason") or "")
        if status == "READY":
            blocker_class = None
        elif "MULTITASK_ROCKET_JOB_UNSUPPORTED" in blocker_text:
            blocker_class = "blocked_multitask_execution"
        elif ("Vendor-only ABI" in blocker_text or "core_mask" in blocker_text
              or "DRM_IOCTL_RKNPU" in blocker_text):
            blocker_class = "blocked_missing_abi"
        else:
            blocker_class = "blocked_unsupported_dtype_shape"
        entry["case_list"].append({
            "case": name,
            "family": fam,
            "manifest_status": status,
            "blocker": blocker_text or None,
            "blocker_class": blocker_class,
            "captured": name in captured,
            "exact_pass": name in exact,
            "tolerance_pass": name in tolerance,
            "known_divergence": name in known,
            "truth_table": name in truth,
            "captured_unverified": name in captured and name not in exact and name not in tolerance and name not in known and name not in truth,
            "result_run": captured.get(name),
            "runner_invalid": name in RUNNER_INVALID,
        })
    for entry in by_source.values():
        entry["families"] = sorted(entry["families"])
    return manifests, by_source, family_stats, runs


MANIFESTS, CAPTURE_BY_SOURCE, FAMILY_STATS, RESULT_RUNS = build_capture_index()
TOTAL_CASES = sum(v["cases"] for v in CAPTURE_BY_SOURCE.values())
TOTAL_READY = sum(v["ready"] for v in CAPTURE_BY_SOURCE.values())
TOTAL_BLOCKED = sum(v["blocked"] for v in CAPTURE_BY_SOURCE.values())
TOTAL_CAPTURED = sum(v["captured"] for v in CAPTURE_BY_SOURCE.values())
TOTAL_EXACT = sum(v["exact"] for v in CAPTURE_BY_SOURCE.values())
TOTAL_TOLERANCE = sum(v["tolerance"] for v in CAPTURE_BY_SOURCE.values())
TOTAL_KNOWN = sum(v["known"] for v in CAPTURE_BY_SOURCE.values())
TOTAL_TRUTH = sum(v["truth"] for v in CAPTURE_BY_SOURCE.values())
TOTAL_UNVERIFIED = sum(v["unverified"] for v in CAPTURE_BY_SOURCE.values())
TOTAL_PREPARED = sum(v["prepared"] for v in CAPTURE_BY_SOURCE.values())
TOTAL_RUNNER_INVALID = sum(v["runner_invalid"] for v in CAPTURE_BY_SOURCE.values())
CASE_BLOCKER_COUNTS = Counter()
for _entry in CAPTURE_BY_SOURCE.values():
    for _case in _entry["case_list"]:
        if _case["manifest_status"] == "BLOCKED" and _case["blocker_class"]:
            CASE_BLOCKER_COUNTS[_case["blocker_class"]] += 1
        if _case["runner_invalid"]:
            CASE_BLOCKER_COUNTS["blocked_bundle_integrity"] += 1

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

VENDOR_ABI = {
    "primary": "vendor-rknpu-drm",
    "device": "/dev/dri/card1",
    "ioctls": [
        "DRM_IOCTL_RKNPU_MEM_CREATE", "DRM_IOCTL_RKNPU_MEM_MAP",
        "DRM_IOCTL_RKNPU_SUBMIT", "DRM_IOCTL_RKNPU_ACTION",
    ],
    "rocket_compatible": False,
    "notes": "Downstream rknpu DRM ABI; not the mainline Rocket /dev/accel UAPI.",
}

ROCKET_ABI = {
    "primary": "rocket-mainline",
    "device": "/dev/accel/accel* (falls back to /dev/dri/renderD* and sometimes /dev/dri/card*)",
    "ioctls": [
        "DRM_IOCTL_ROCKET_CREATE_BO", "DRM_IOCTL_ROCKET_PREP_BO",
        "DRM_IOCTL_ROCKET_FINI_BO", "DRM_IOCTL_ROCKET_SUBMIT",
    ],
    "rocket_compatible": True,
    "notes": "Mainline Rocket task UAPI; command QWORD stream remains the RK register stream.",
}

ROCKET_RUNTIME_ABI = {
    "primary": "rocket-mainline-via-rocket_runtime",
    "device": "/dev/accel/accel*",
    "ioctls": ["rocket_runtime.open_rocket_device / mem_allocate / submit"],
    "rocket_compatible": True,
    "notes": "Imports /home/fedora/rk3588/experimental/kernel_6_18/rocket_runtime.py.",
}


def vendor_abi(**extra):
    d = dict(VENDOR_ABI)
    d.update(extra)
    return d


def rocket_abi(**extra):
    d = dict(ROCKET_ABI)
    d.update(extra)
    return d


def rocket_runtime_abi(**extra):
    d = dict(ROCKET_RUNTIME_ABI)
    d.update(extra)
    return d


def blocks(ew_fp16="-", ew_int="-", ppu="-", cna="-", cmac="-", bs_bn="-", rdma_pc="-"):
    return {
        "EW_FP16": ew_fp16,
        "EW_INT": ew_int,
        "PPU": ppu,
        "CNA_CONV": cna,
        "CMAC_GEMM": cmac,
        "DPU_BS_BN": bs_bn,
        "RDMA_PC": rdma_pc,
    }


def regs(*items):
    return list(items)


PC_REGS = regs(
    "PC 0x0081 (OPERATION_ENABLE, task dispatch)",
    "PC_REG 0x0101 (PC_BASE_ADDRESS / PC_REGISTER_AMOUNTS chain)",
    "VERSION 0x0041 (terminal marker)",
)
CONV_REGS = regs(
    "CNA 0x0201 (CONV_CON1..3, DATA_SIZE0..3, WEIGHT_SIZE0..2, CBUF_CON0/1, CVT_CON0..5, PAD_CON0/1, DMA_CON0..2, FEATURE_DATA_ADDR, DCOMP_ADDR0)",
    "CORE 0x0801 (MISC_CFG, DATAOUT_SIZE_0/1, CLIP_TRUNCATE)",
    "DPU 0x1001 (FEATURE_MODE_CFG, DATA_FORMAT, CUBE_WIDTH/HEIGHT/NOTCH/CHANNEL, BS_CFG/OW_CFG, WDMA_SIZE, BN_CFG, EW_CFG, OUT_CVT, SURFACE_ADD)",
)
DPU_EW_REGS = regs(
    "DPU 0x1001 (FEATURE_MODE_CFG, DATA_FORMAT, CUBE_WIDTH/HEIGHT/NOTCH/CHANNEL, EW_CFG, OUT_CVT_SCALE)",
    "RDMA 0x2001 (S_POINTER, CUBE_WIDTH/HEIGHT/CHANNEL, ERDMA_CFG, SRC_BASE_ADDR, EW_BASE_ADDR, FEATURE_MODE_CFG, RDMA_MODE)",
)
PPU_REGS = regs(
    "PPU 0x4001 (S_POINTER, cube in/out, OPERATION_MODE_CFG, POOLING_KERNEL_CFG, RECIP_KERNEL_WIDTH/HEIGHT, PADDING_CFG, PADDING_VALUE_1/2, DST_BASE_ADDR, DST_SURF_STRIDE, DATA_FORMAT, MISC_CTRL)",
    "PPU_RDMA 0x8001 (S_POINTER, cube in, SRC_BASE_ADDR, SRC_LINE_STRIDE, SRC_SURF_STRIDE, DATA_FORMAT)",
    "PC 0x0081 (OPERATION_ENABLE)",
)
INT_EW_REGS = regs(
    "DPU 0x1001 (FEATURE_MODE_CFG, DATA_FORMAT, CUBE_*, BS_CFG/ALU/MUL/OW, BN_CFG/ALU/MUL, EW_CFG, OUT_CVT, WDMA_SIZE, LUT_* for expt)",
    "RDMA 0x2001 (SRC/EW/BS/BN bases, ERDMA/BRDMA/NRDMA_CFG, cube and surface strides)",
    "PC 0x0081 / PC_REG 0x0101 / VERSION 0x0041",
)
CMAC_REGS = regs(
    "CNA 0x0201 (convolution/GEMM geometry and CBUF controls)",
    "CORE 0x0801 (MAC geometry and dataout sizes)",
    "DPU 0x1001 (output format/convert path)",
)


def ex(eid, path, classification, labels, entry_point, cli, device_abi,
       block_map, register_families, notes, unknowns=None, device_free=None,
       manual_status=None):
    capture = CAPTURE_BY_SOURCE.get(str(EXAMPLES / path), {
        "cases": 0, "ready": 0, "blocked": 0, "captured": 0,
        "bytes": 0, "exact": 0, "tolerance": 0, "known": 0,
        "truth": 0, "unverified": 0, "prepared": 0,
        "runner_invalid": 0, "not_implemented": [],
        "families": [], "case_list": [],
    })
    # Keep the register-family list honest for files that touch RDMA only for
    # state clearing or a packed data path. The detailed families above win.
    source_text = (EXAMPLES / path).read_text(errors="replace")
    if ("reg.RDMA" in source_text or "TARGET_RDMA" in source_text) and not any(
            "RDMA 0x2001" in entry for entry in register_families):
        register_families.append(
            "RDMA 0x2001 (source-referenced RDMA bases/config or state clear; see file)"
        )
    return {
        "id": eid,
        "path": str(EXAMPLES / path),
        "relative_path": path,
        "classification": classification,
        "labels": labels,
        "entry_point": entry_point,
        "cli": cli,
        "device_abi": device_abi,
        "device_free_modes": device_free or [],
        "hardware_blocks": block_map,
        "register_families": register_families,
        "capture": {
            "exists": capture["cases"] > 0,
            "families": capture["families"],
            "cases": capture["cases"],
            "ready": capture["ready"],
            "blocked": capture["blocked"],
            "captured": capture["captured"],
            "captured_bytes": capture["bytes"],
            "exact_pass": capture["exact"],
            "tolerance_pass": capture["tolerance"],
            "known_divergence": capture["known"],
            "truth_table": capture["truth"],
            "captured_unverified": capture["unverified"],
            "oracle_verified": capture["exact"],
            "oracle_diverged": capture["known"],
            "captured_no_oracle": capture["truth"],
            "captured_not_implemented": capture["not_implemented"],
            "prepared_not_run": capture["prepared"],
            "runner_invalid": capture["runner_invalid"],
            "device_executed_under_this_queue": capture["captured"],
            "case_list": capture["case_list"],
        },
        "evidence_status": [],  # filled below
        "manual_status": manual_status or [],
        "fpga_path": {},        # filled below
        "unknowns": unknowns or [],
        "notes": notes,
    }


EXAMPLES_JSON = [
    ex(
        "conv_gemm", "conv_gemm.py", "runnable",
        ["runnable", "vendor-abi", "combined conv+GEMM probe", "overlaps conv.py and gemm.py"],
        "module __main__; run_conv2d() and run_gemm()",
        "python3 conv_gemm.py [conv [shape_filter]] [gemm [shape_filter]]",
        vendor_abi(),
        blocks(cna="Y", cmac="Y", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "Large combined vendor-ABI conv/GEMM probe. Two conv cases are bundled; its own GEMM test table is not bundled (gemm.py supplies the four GEMM bundles).",
            "The depthwise bundle from this family is attributed to conv_legacy.py in the current manifest. Current conv-gemm-vendor state is 13 cases: 10 READY, 3 BLOCKED (2 vendor ABI + 1 combined multi-task depthwise). The old 9/9 note predates the split into _task0/_task1 READY one-task bundles. All 10 READY cases have real captures; the oracle comparison is pending.",
        ],
    ),
    ex(
        "conv_legacy", "conv_legacy.py", "runnable",
        ["runnable", "vendor-abi", "legacy reference"],
        "module __main__; run_conv2d() matrix",
        "python3 conv_legacy.py [--out fp16]",
        vendor_abi(),
        blocks(cna="Y", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "Reference implementation kept beside conv.py. Docstring states some FP32 outputs are actually FP16 NPU writeback plus host dtype cast.",
            "Four conv-gemm-vendor cases are attributed here: conv_legacy_3x3_c4_oc4_h9w9, the combined depthwise case (BLOCKED, MULTITASK_ROCKET_JOB_UNSUPPORTED) and its split _task0/_task1 one-task READY cases. Rocket completes only the first task of the combined job. All three READY cases have real captures, but oracle comparison is pending.",
        ],
    ),
    ex(
        "conv", "conv.py", "runnable",
        ["runnable", "vendor-abi", "planner-driven Phase A"],
        "module __main__; planner-driven run_shape()/guarded direct-spatial paths",
        "python3 conv.py <shape> | --list | --dry-run-* | --allow-*-submit",
        vendor_abi(),
        blocks(cna="Y", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "Imports conv_expt.conv_tile_planner from /home/fedora/rk3588. Many shapes are crash-fenced or gated behind explicit --allow flags.",
            "Two bundled cases are BLOCKED because the vendor BY_K/H40 paths need core_mask/subcore_task and a PC_BASE_ADDRESS self-address patch that the Rocket bundle schema cannot express.",
        ],
        unknowns=["Direct-spatial template tables are described as RKNN-observed templates, not a general tiling compiler."],
        device_free=["--list", "--dry-run-* (metadata only)"],
    ),
    ex(
        "conv_simple", "conv_simple.py", "runnable",
        ["runnable", "vendor-abi", "simplified Phase A"],
        "module __main__; run_shape()",
        "python3 conv_simple.py <shape> | --list",
        vendor_abi(),
        blocks(cna="Y", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "Simplified vendor-ABI sibling of conv.py; no capture bundle of its own. The experimental expt/conv_simple.py is the bundled variant.",
        ],
        device_free=["--list"],
    ),
    ex(
        "conv_tiles", "conv_tiles.py", "runnable",
        ["runnable", "vendor-abi", "legacy tiled probe"],
        "module __main__; run_shape_suite()",
        "python3 conv_tiles.py [shape ...] [--start-index N] [--count N] [--skip-index N]",
        vendor_abi(),
        blocks(cna="Y", bs_bn="B", rdma_pc="PC-only", ppu="D"),
        CONV_REGS + PC_REGS + regs("PPU 0x4001 / PPU_RDMA 0x8001 constants are defined but no call site uses them"),
        [
            "Port source for kernel_6_18/conv.py (diff similarity ~0.80).",
            "Opens /dev/dri/card1 at import unless RK3588_CONV_NO_DEVICE=1; the vendor path is why its only capture case is BLOCKED.",
        ],
        device_free=["RK3588_CONV_NO_DEVICE=1 (offline build/plan; no submit)"],
    ),
    ex(
        "elementwise", "elementwise.py", "runnable",
        ["runnable", "vendor-abi", "FP16 EW matrix", "capture source"],
        "module __main__; run_op() over OPS",
        "python3 elementwise.py [OP|ALL|CAST_BOOL_HALF] [--out fp16|fp32]",
        vendor_abi(),
        blocks(ew_fp16="Y", rdma_pc="Y"),
        DPU_EW_REGS + PC_REGS,
        [
            "Source of the ew-fp16 and fdiv-systematic bundles.",
            "ADD/SUB/MUL/MAX/NEG at N=8 are also covered by the separate real Rocket capture + RTL simulation in build/rk3588-kernel-comparison-v1.",
            "The 54-case ew-fp16 capture is complete: 45/45 ADD/SUB/MUL/MAX/NEG logical comparisons pass; 9 FDIV cases were captured, 7 pass the donor oracle, and 2 A/7 cases (fdiv_p1_n33, fdiv_p1_n1024; 20 halfwords) are one ULP low. The 8-case fdiv-systematic truth table adds 256 operand classes and 512 bytes with oracle none.",
            "The 32-lane finite sweep and the 256-class truth table are correctly rounded nearest-even; the A/7 cases are the specific exception. FDIV remains rejected by the RTL decoder; FP32 output and CAST_BOOL_HALF are outside the strict EW slice.",
        ],
        unknowns=["The FP32 output path is real on RK but not implemented by the FPGA EW slice; its timing-sensitive polling loop is not a hardware contract."],
        device_free=[],
    ),
    ex(
        "gemm", "gemm.py", "runnable",
        ["runnable", "vendor-abi", "standalone GEMM"],
        "module __main__; run_gemm()",
        "python3 gemm.py [--out fp16]",
        vendor_abi(),
        blocks(cmac="Y", bs_bn="B", rdma_pc="PC-only"),
        CMAC_REGS + PC_REGS,
        [
            "Four small GEMM cases are prepared (m2n2k1, m1n16k32, m2n16k32, m4n32k64). The default output is FP32; --out fp16 selects FP16.",
            "The CMAC RTL is a strict FP16 C32/K16 terminal profile with FP16 output. It does not implement the example's general FP32-output path or arbitrary small K/N shapes.",
        ],
        unknowns=["Whether every emitted task fits the CMAC profile's physical channel/row rules without padding is not established by the example."],
        manual_status=["blocked_unsupported_dtype_shape"],
    ),
    ex(
        "pooling", "pooling.py", "runnable",
        ["runnable", "rocket-abi", "PPU probe"],
        "module __main__; cases()/run_pool_case()",
        "python3 pooling.py [case|all|--list|--surface]",
        rocket_abi(),
        blocks(ppu="Y", rdma_pc="Y"),
        PPU_REGS,
        [
            "Earlier PPU probe; expt/pooling.py is the bundled, expanded version. No bundle is attributed to this file.",
            "Source docstring records RK silicon results for average/max/min, INDEX_EN, FP16/INT8/INT16, and disproves INT32/FP32 on the tested path.",
        ],
        device_free=["--list", "--surface"],
    ),
    ex(
        "simple_add", "simple_add.py", "duplicate",
        ["duplicate", "minimal EW probe", "vendor-abi"],
        "module __main__; run_op() ADD only",
        "python3 simple_add.py [ADD|ALL]",
        vendor_abi(),
        blocks(ew_fp16="Y", rdma_pc="Y"),
        DPU_EW_REGS + PC_REGS,
        [
            "Minimal duplicate of the elementwise.py ADD path. Its raw stream omits the strict OUT_CVT/terminal profile fields the RTL decoder requires, so it is not directly runnable on the FPGA EW slice.",
            "Functionally covered by the ew-fp16 ADD bundles, which include the complete 21-field profile.",
        ],
        unknowns=["No bundle and no direct RTL replay of this exact minimal stream."],
        manual_status=["blocked_unsupported_dtype_shape"],
    ),
    ex(
        "expt/conv_simple", "expt/conv_simple.py", "runnable",
        ["runnable", "experimental", "vendor-default + Rocket option", "capture source"],
        "module __main__; run_shape() (vendor) and run_shape_rocket()",
        "python3 expt/conv_simple.py <shape> | --list | --validate-rgb-regs | --validate-mesa-cna-regs | --rocket-rgb",
        vendor_abi(
            primary="vendor-default + rocket-option",
            rocket_option="--rocket-rgb uses /dev/accel via DRM_IOCTL_ROCKET_*",
        ),
        blocks(cna="Y", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "Capture source for conv-simple. The default run_shape() opens /dev/dri/card1 and uses the vendor RKNPU ioctls; --rocket-rgb selects the Rocket path.",
            "All 7 READY cases now carry one zero fetch-padding QWORD (regcmd_fetch_words one greater than regcmd_words) and are runner-valid.",
            "Four of nine bundled cases are BLOCKED for source-evidence reasons (stride, SAME pad, C8 packing, grouped path), not because a register value was invented.",
        ],
        unknowns=["The --rocket-rgb path is a separate re-hosting path from the default vendor submission."],
        device_free=["--list", "--validate-rgb-regs", "--validate-mesa-cna-regs"],
    ),
    ex(
        "expt/elementwise_int", "expt/elementwise_int.py", "runnable",
        ["runnable", "rocket-abi", "integer EW probe", "capture source", "superset"],
        "module __main__; run_operation()/probe dispatch",
        "python3 expt/elementwise_int.py [DTYPE] [OP] | --validate-* | --probe-*",
        rocket_abi(),
        blocks(ew_int="Y", ew_fp16="P", bs_bn="Y", rdma_pc="Y"),
        INT_EW_REGS,
        [
            "Superset integer EW campaign: INT8/INT16/INT32 ADD/MIN/SUB/MUL/MAX, BS/BN ALU/MUL/ReLU/PReLU, BRDMA/NRDMA, LUT SiLU, FP16 compare->INT16.",
            "Four of six bundled cases are captured and verified on RK3588 Rocket; the two BLOCKED cases are an FP16 four-input sum and FP16 BS/BN ReLU/PReLU, deliberately kept out of the integer family.",
        ],
        device_free=["--validate-probes", "--validate-layout-probes", "--validate-external-mul-layouts", "--validate-external-alu-mul"],
    ),
    ex(
        "expt/pooling", "expt/pooling.py", "runnable",
        ["runnable", "rocket-abi", "PPU probe", "capture source"],
        "module __main__; cases()/run_pool_case()",
        "python3 expt/pooling.py [case|all|--list|--validate|--validate-multi-pass|--surface]",
        rocket_abi(),
        blocks(ppu="Y", rdma_pc="Y"),
        PPU_REGS,
        [
            "Bundled PPU matrix: 19 READY captured and 19/19 full-BO exact (77,824 bytes); the 2 BLOCKED zero-write FP32/INT32 probes were not run.",
            "Source docstring records real RK silicon findings; the 19 capture pairs under results/pooling-20261105T203205Z are the device receipts.",
        ],
        unknowns=["PPU DPU-flying input (FLYING_MODE=0) is register-defined but not silicon-proven by this script."],
        device_free=["--list", "--validate", "--validate-multi-pass", "--surface"],
    ),
    ex(
        "kernel/conv_0522", "kernel_6_18/conv_0522.py", "draft",
        ["draft", "rocket-abi", "dated experiment"],
        "module __main__; run_conv() over a hardcoded shape list",
        "python3 kernel_6_18/conv_0522.py (no CLI filter)",
        rocket_runtime_abi(),
        blocks(cna="Y", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "Only its split-K case is bundled, and that case is BLOCKED: _execute_conv_tiles clears the output before every tile and _tile_to_desc leaves tile offsets at zero, so no partial-sum accumulation is encoded.",
            "The main matrix includes shapes the source itself labels as partial-output/known-limitation.",
        ],
        unknowns=["Tile-offset handling and split-K accumulation contract are unproven."],
    ),
    ex(
        "kernel/conv_draft", "kernel_6_18/conv_draft.py", "draft",
        ["draft", "rocket-abi", "SAME-pad experiment"],
        "module __main__; run_conv() for three shapes",
        "python3 kernel_6_18/conv_draft.py",
        rocket_runtime_abi(),
        blocks(cna="Y", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "Explicit draft. It computes SAME padding and a float32 output buffer while DATA_FORMAT selects FP16; the numerical/output contract is internally inconsistent and is treated as unknown.",
        ],
        unknowns=["Output dtype/unpack contract is inconsistent; no bundle and no trusted oracle."],
        manual_status=["blocked_unsupported_dtype_shape"],
    ),
    ex(
        "kernel/conv_legacy", "kernel_6_18/conv_legacy.py", "runnable",
        ["runnable", "rocket-abi", "reference", "carries EW helper"],
        "module __main__; run_conv2d() matrix",
        "python3 kernel_6_18/conv_legacy.py [--out fp16]",
        rocket_abi(),
        blocks(cna="Y", ew_fp16="P", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "Rocket port of the legacy conv reference (~0.68 similarity to top-level conv_legacy.py). Contains an unused-by-default submit_fp16_add() helper.",
        ],
    ),
    ex(
        "kernel/conv_mesa", "kernel_6_18/conv_mesa.py", "runnable",
        ["runnable", "rocket-abi", "Mesa INT8 target", "known-good reference"],
        "module __main__; shape_matrix_runner() / conv_py_shape_matrix_runner()",
        "python3 kernel_6_18/conv_mesa.py [--input-packer ...] [--compare-packed-input ...]",
        rocket_abi(),
        blocks(cna="Y", bs_bn="Y", rdma_pc="Y"),
        CONV_REGS + PC_REGS,
        [
            "README calls this the known-good Mesa-equivalent target. INT8/uint8 quantized semantics with zero-point subtraction and bias correction.",
            "No bundle of its own; conv-simple's two INT8 cases come from simple_conv.py, not this Mesa clone.",
        ],
        device_free=["--compare-packed-input"],
        manual_status=["blocked_unsupported_dtype_shape"],
    ),
    ex(
        "kernel/conv_mesa_fp16", "kernel_6_18/conv_mesa_fp16.py", "duplicate",
        ["duplicate", "variant of conv_mesa", "rocket-abi", "FP16 packing experiment"],
        "module __main__; same Mesa matrix plus FP16 packing options",
        "python3 kernel_6_18/conv_mesa_fp16.py [--compare-fp16-packed-input | --submit-fp16-packed-input ...]",
        rocket_abi(),
        blocks(cna="Y", bs_bn="Y", rdma_pc="Y"),
        CONV_REGS + PC_REGS,
        [
            "96.9% similar to conv_mesa.py; adds translate_crs_fp16_mesa and FP16 submit options. It emits CNA_PAD_CON0 but its register body remains the Mesa uint8 zero-point recipe, so its FP16 pad semantics are not accepted as evidence.",
        ],
        unknowns=["FP16 pad-register semantics are not validated by the bundled sources."],
        device_free=["--compare-packed-input", "--compare-fp16-packed-input"],
        manual_status=["blocked_unsupported_dtype_shape"],
    ),
    ex(
        "kernel/conv_new_clean", "kernel_6_18/conv_new_clean.py", "runnable",
        ["runnable", "canonical", "rocket-abi", "capture source"],
        "module __main__; run_conv2d() matrix",
        "python3 kernel_6_18/conv_new_clean.py",
        rocket_runtime_abi(),
        blocks(cna="Y", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "Cleaned Rocket FP16 conv builder and capture source for conv-fp16. The family is now split: 5 single-task cases captured/verified; 4 grouped/split-OC _task0/_task1 cases prepared; 2 combined multi-task cases BLOCKED because Rocket completes only task 1; 1 pad-register case BLOCKED.",
            "The original combined grouped/split-OC captures remain as evidence that task 1 wrote an all-zero output BO; the split one-task bundles are the follow-up.",
            "One blocked case is the pad-register FP16 case: conv_new_clean comments out CNA_PAD_CON0 and computes valid-only geometry.",
        ],
        device_free=[],
    ),
    ex(
        "kernel/conv_new", "kernel_6_18/conv_new.py", "duplicate",
        ["duplicate", "working copy", "rocket-abi"],
        "module __main__; run_conv2d() matrix",
        "python3 kernel_6_18/conv_new.py",
        rocket_runtime_abi(),
        blocks(cna="Y", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "README says this is the file under active change. It is ~86.3% similar to conv_new_clean.py; the clean copy is the canonical bundled builder.",
        ],
    ),
    ex(
        "kernel/conv_new_trscrs", "kernel_6_18/conv_new_trscrs.py", "duplicate",
        ["duplicate", "translateCRS variant", "rocket-abi"],
        "module __main__; run_conv2d() matrix",
        "python3 kernel_6_18/conv_new_trscrs.py",
        rocket_runtime_abi(),
        blocks(cna="Y", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "~98.1% similar to conv_new.py; adds translateCRSToFeatureData FP16 packing. Experimental duplicate, not the canonical builder.",
        ],
    ),
    ex(
        "kernel/conv", "kernel_6_18/conv.py", "duplicate",
        ["duplicate", "Rocket port of conv_tiles.py", "rocket-abi"],
        "module __main__; run_shape_suite()",
        "python3 kernel_6_18/conv.py [shape ...]",
        rocket_runtime_abi(),
        blocks(cna="Y", bs_bn="B", rdma_pc="PC-only", ppu="P"),
        CONV_REGS + PC_REGS + regs("PPU 0x4001 / PPU_RDMA 0x8001 (separator record in direct-spatial sparse stream)"),
        [
            "~79.6% similar to conv_tiles.py; this is the Rocket port with direct-spatial policies. No bundle is attributed to this file.",
            "Its direct-spatial sparse stream inserts a 26-QWORD PPU 'separator' record (operation mode (1<<4)|1) between conv tasks; no evidence establishes that this is a pooling operation or that the record is numerically inert.",
        ],
        unknowns=["PPU separator record semantics in the direct-spatial stream are unknown and not modeled by RTL."],
    ),
    ex(
        "kernel/elementwise_int", "kernel_6_18/elementwise_int.py", "runnable",
        ["runnable", "rocket-abi", "integer EW subset", "capture source"],
        "module __main__; run_operation() over DTYPES x OPERATIONS",
        "python3 kernel_6_18/elementwise_int.py [DTYPE] [OP]",
        rocket_abi(),
        blocks(ew_int="Y", ew_fp16="P", bs_bn="P", rdma_pc="Y"),
        INT_EW_REGS,
        [
            "Smaller integer EW matrix than expt/elementwise_int.py. Eleven of twelve bundled cases are captured and verified on RK3588 Rocket; int32_div is BLOCKED because DIV/FLOOR/CEIL are floating-point semantics, not integer ops.",
            "int16_add_to_int32_c8_w1 is a 31-QWORD bundle. It needs one zero fetch-padding QWORD only for generic-runner replay; the captured/verified result uses the existing 31-word stream.",
        ],
        device_free=[],
    ),
    ex(
        "kernel/simple_add", "kernel_6_18/simple_add.py", "duplicate",
        ["duplicate", "minimal EW probe", "rocket-abi"],
        "module __main__; run_op() ADD only",
        "python3 kernel_6_18/simple_add.py [ADD|ALL]",
        rocket_abi(),
        blocks(ew_fp16="Y", rdma_pc="Y"),
        DPU_EW_REGS + PC_REGS,
        [
            "Minimal Rocket ADD duplicate. It includes the PC chain tail but still omits the strict OUT_CVT write; no bundle and no direct RTL replay of this exact stream.",
            "Functionally covered by ew-fp16 ADD bundles.",
        ],
        manual_status=["blocked_unsupported_dtype_shape"],
    ),
    ex(
        "kernel/simple_conv", "kernel_6_18/simple_conv.py", "runnable",
        ["runnable", "rocket-abi", "INT8 quantized conv", "capture source"],
        "module __main__; run_conv2d_shape() matrix",
        "python3 kernel_6_18/simple_conv.py",
        rocket_abi(),
        blocks(cna="Y", bs_bn="Y", rdma_pc="Y"),
        CONV_REGS + PC_REGS,
        [
            "INT8/uint8 Mesa-style quantized conv with zero-point/bias correction and an im2col fallback. Two cases are prepared in conv-simple; the addition-input case is BLOCKED because the source never writes an addition-tensor address.",
        ],
        device_free=[],
    ),
    ex(
        "kernel/simple_conv_fp16", "kernel_6_18/simple_conv_fp16.py", "runnable",
        ["runnable", "variant of conv_legacy", "rocket-abi"],
        "module __main__; run_conv2d() matrix",
        "python3 kernel_6_18/simple_conv_fp16.py [--out fp16] [--keep-going]",
        rocket_abi(),
        blocks(cna="Y", ew_fp16="P", bs_bn="B", rdma_pc="PC-only"),
        CONV_REGS + PC_REGS,
        [
            "~81.4% similar to kernel_6_18/conv_legacy.py; FP16 conv variant with an unused-by-default submit_fp16_add() helper. No bundle.",
        ],
    ),
]

NOTE_JSON = [
    {
        "path": str(EXAMPLES / "expt/ppu_pooling_findings.md"),
        "classification": "note",
        "role": "RK3588 PPU capability findings (expanded)",
        "key_points": [
            "Average/max/min, FP16/INT8/INT16, INDEX_EN, kernel/stride 16, padding 7, FP16 -inf padding, multi-pass PPU.",
            "INT32/FP32 pooling submit but write zero on the tested external-RDMA path.",
            "No RTL in this repository implements any PPU operation.",
        ],
    },
    {
        "path": str(EXAMPLES / "ppu_pooling_findings.md"),
        "classification": "note",
        "role": "Earlier PPU findings note",
        "key_points": [
            "Shorter duplicate of expt/ppu_pooling_findings.md; same headline conclusions.",
        ],
    },
    {
        "path": str(EXAMPLES / "expt/trm_register_findings.md"),
        "classification": "note",
        "role": "RK3588 DPU register campaign",
        "key_points": [
            "Documents RK-silicon PASS results for INT8/INT16/INT32 EW, BS/BN ALU/MUL/ReLU/PReLU, BRDMA/NRDMA four-input sums, LUT SiLU/sigmoid/tanh, FP16 compare->INT16 and INT16->INT32.",
            "Those are RK silicon observations; the FPGA RTL contains only the FP16 EW ALU.",
        ],
    },
    {
        "path": str(EXAMPLES / "expt/trm_register_matrix.md"),
        "classification": "note",
        "role": "RK3588 semantic-register triage",
        "key_points": [
            "Separates PASS/NEGATIVE/CAPTURED/UNPROVED/QUARANTINED fields.",
            "States the selected tinygrad branch emits only DPU+DPU_RDMA; CNA/CORE and PPU are future work.",
        ],
    },
    {
        "path": str(EXAMPLES / "kernel_6_18/README.md"),
        "classification": "note",
        "role": "Vendor-to-Rocket porting guide",
        "key_points": [
            "Documents /dev/dri/card1 vendor ABI vs /dev/accel Rocket ABI and the regcfg_amount/PC-tail porting rules.",
            "Names conv_mesa.py as the known-good target and conv_new.py as the working file.",
        ],
    },
    {
        "path": str(EXAMPLES / "kernel_6_18/tile.md"),
        "classification": "note",
        "role": "CDMA input packing comparison",
        "key_points": [
            "Compares translateCRSToFeatureData, conv_new's FP16 packer, and Mesa's uint8 packer.",
            "Documents C1/H/W/C2 layout differences and Mesa's W-before-H packing.",
        ],
    },
]

# ---------------------------------------------------------------------------
# Block support table
# ---------------------------------------------------------------------------

BLOCK_SUPPORT = [
    {
        "id": "EW_FP16",
        "label": "DPU elementwise FP16 ALU",
        "status": "supported_strict",
        "rtl": [
            "rtl/rk_fp16_alu.sv",
            "rtl/rk_ew_engine.sv",
            "rtl/rk_ew_core.sv",
            "rtl/rk_ew_regs.sv",
            "rtl/rk_ew_dma.sv",
        ],
        "docs": ["docs/INTERFACE.md", "docs/PC_DMA.md", "docs/EW_INITIALIZATION.md"],
        "scope": [
            "Binary16 ADD, SUB, MUL, MAX; NEG is MUL by -1.",
            "Eight lanes per group; width is count-minus-one in groups of eight, up to 7999.",
            "Strict fixed profile: DPU pointer/mode/data-format, height=0, notch=0, channels=0x00070007, RDMA mode 0x00017849, OUT_CVT 0x00010001.",
            "Round-to-nearest-even, gradual underflow, RK-captured NaN 0x7c01, signed-zero and SUB-infinity policy.",
        ],
        "not_supported": [
            "FDIV (captured on RK, decoder rejects EW_CFG 0x108303c0).",
            "INT8/INT16/INT32 EW, BS/BN arithmetic, LUT/activation, FP32 output, CAST_BOOL_HALF.",
            "General surface strides, ERDMA broadcast, BRDMA/NRDMA, multi-input, runtime gather/layout repair.",
        ],
        "evidence": [
            "build/rk3588-kernel-comparison-v1: real Rocket capture + RTL simulation for ADD/SUB/MUL/NEG/MAX at N=8.",
            "build/rk3588-example-captures/results/ew-fp16-20261105T201400Z: 45/45 supported-op logical PASS; 9 FDIV captured, 7 exact, 2 A/7 cases (20 halfwords) explained by the three-guard-bit ties-to-even contract, matching 1452/1452 real lanes.",
            "build/rk3588-example-captures/results/fdiv-systematic-20261105T204746Z: 8 cases, 512 bytes, 256 operand classes; the 32-lane finite sweep and 256-class truth table are correctly rounded nearest-even, with no pass/fail oracle by design.",
        ],
    },
    {
        "id": "EW_INT",
        "label": "DPU elementwise integer ALU",
        "status": "missing_rtl",
        "rtl": [],
        "docs": ["docs/INTERFACE.md", "docs/REVIEW_AND_PLAN.md"],
        "scope": [
            "RK examples exercise INT8/INT16/INT32 ADD/MIN/SUB/MUL/MAX, saturation and INT16->INT32 regrouping.",
            "RK silicon evidence is strong: 15/15 ew-int bundled cases captured and oracle-verified on Rocket.",
        ],
        "not_supported": [
            "No integer ALU exists. rk_fp16_alu.sv is half-precision only and rk_ew_regs.sv fixes DATA_FORMAT to 0x48000002.",
            "No integer saturation, no EDATA_SIZE integer modes, no INT16->INT32 WDMA.",
        ],
        "evidence": [
            "build/rk3588-example-captures/results/ew-int-20261105T200154Z: 15/15 submit_ret=0 and masked oracle PASS.",
            "int16_add_to_int32_c8_w1 is a 31-QWORD bundle; one zero fetch-padding QWORD is needed only for generic-runner replay.",
            "docs/REVIEW_AND_PLAN.md lists quantized/integer paths as deferred.",
        ],
    },
    {
        "id": "PPU",
        "label": "PPU pooling",
        "status": "missing_rtl",
        "rtl": [],
        "docs": ["docs/REVIEW_AND_PLAN.md", "examples/expt/ppu_pooling_findings.md"],
        "scope": [
            "RK examples exercise average/max/min, FP16/INT8/INT16, INDEX_EN, padding, kernel/stride 16, multi-pass.",
            "19 READY pooling cases are captured and 19/19 full-BO exact (77,824 bytes); 2 FP32/INT32 zero-write probes are BLOCKED and were not run.",
        ],
        "not_supported": [
            "No rtl/ module named PPU or implementing pool arithmetic. PPU 0x4001/0x8001 targets are not decoded by rk_ew_regs.",
            "No DPU-flying PPU input, no PPU_RDMA, no INDEX_EN.",
        ],
        "evidence": [
            "build/rk3588-example-captures/results/pooling-20261105T203205Z-host-analysis/comparison.json: 19/19 full-BO exact, 77,824 bytes.",
            "grep of rtl/**/*.sv finds no PPU module.",
            "docs/REVIEW_AND_PLAN.md: 'PPU ... remain deferred'.",
        ],
    },
    {
        "id": "CNA_CONV",
        "label": "CNA / CBUF / CSC convolution",
        "status": "missing_rtl",
        "rtl": [],
        "docs": ["docs/CMAC_ENCODER_CONTRACT.md", "docs/REVIEW_AND_PLAN.md", "examples/kernel_6_18/tile.md"],
        "scope": [
            "RK examples exercise 1x1/3x3/5x5 valid conv, depthwise, grouped, split-OC, stride, explicit zero-frame pad, CBUF banks, input/weight packing.",
            "39 conv cases: 26 captured (9 conv-fp16 exact; 10 conv-gemm-vendor PASS, 8 exact + 2 tolerance; 7 conv-simple: 4 exact + 3 known divergence), 0 prepared and 13 BLOCKED (3 ABI, 3 multi-task, 7 other shape/source).",
        ],
        "not_supported": [
            "No CNA, CBUF, CSC, CDMA, pad/stride/dilation, im2col or convolution data-fetch RTL.",
            "rk_cmac_array_* consumes already-packed C32/K16 GEMM frames; it is not a convolution engine.",
            "No INT8 CNA, no grouped/depthwise hardware decomposition, no multi-core/subcore scheduling.",
        ],
        "evidence": [
            "build/rk3588-example-captures/results/conv-fp16-20261105T222300Z: 9/9 exact, 35,392 bytes. The older 205900 tree retains only 2 now-BLOCKED combined captures (8,192 bytes) as task-1-all-zero evidence.",
            "build/rk3588-example-captures/results/conv-gemm-vendor-20261105T214000Z plus results/conv-gemm-depthwise-rerun-20261105T221115Z: 10/10 PASS (8 exact, 2 tolerance), 95,744 bytes; depthwise 702/702 after the 15,104-byte BO fix.",
            "build/rk3588-example-captures/results/conv-simple-20261105T215921Z: 7 captured, 4 exact + 3 known divergence (1 FP32 structural, 2 INT8 +1 LSB).",
            "No rtl/ module implements CNA/CBUF/CSC/convolution.",
            "docs/REVIEW_AND_PLAN.md lists general convolution as deferred.",
        ],
    },
    {
        "id": "CMAC_GEMM",
        "label": "CMAC / CACC FP16 GEMM",
        "status": "partial_supported_strict",
        "rtl": [
            "rtl/rk_cmac_profile.sv",
            "rtl/cmac/rk_cmac_array_front.sv",
            "rtl/cmac/rk_cmac_array_datapath.sv",
            "rtl/cmac/rk_cmac_array_core.sv",
            "rtl/cmac/rk_cmac_array_dma.sv",
            "rtl/cmac/rk_cmac_cacc_fp16_array.sv",
            "rtl/cmac/rk_cmac_frame_output.sv",
            "rtl/cmac/rk_cmac_array_axi.sv",
            "rtl/ddr/framework/rk_cmac_async_engine.sv",
        ],
        "docs": ["docs/CMAC_PROFILE_CANDIDATE.md", "docs/CMAC_PRODUCT_PATH.md", "docs/FRAMEWORK_FULL_PROFILE.md", "docs/CMAC_ENCODER_CONTRACT.md"],
        "scope": [
            "FP16 C32/K16, 512 parallel products, FP48 accumulation and FP32 finalization followed by FP16 output writes.",
            "Strict terminal 49-QWORD profile: rows 1..2047, input/output channels multiples of 32, input channels >= output channels, no ReLU, no FP32 output, physical packed operands.",
            "Framework full profile adds layout DMA and six compiler shapes; default EW board top does not instantiate the CMAC product path.",
        ],
        "not_supported": [
            "No general GEMM ABI, no runtime gathers, no arbitrary K/N/M, no FP32 output, no activation, no INT8/INT4.",
            "Not the default EW endpoint; requires the explicit RKCD/RKLY/RKRS framework profile.",
        ],
        "evidence": [
            "docs/CMAC_PROFILE_CANDIDATE.md and docs/FRAMEWORK_FULL_PROFILE.md.",
            "docs/CMAC_PRODUCT_PATH.md: the product leaf is not instantiated by the EW DMA/host/board top.",
        ],
    },
    {
        "id": "DPU_BS_BN",
        "label": "DPU batch/scale/norm and LUT stages",
        "status": "missing_rtl",
        "rtl": [],
        "docs": ["docs/INTERFACE.md", "docs/EW_INITIALIZATION.md"],
        "scope": [
            "RK examples exercise BS/BN ALU/MUL/ReLU/PReLU, BRDMA/NRDMA inputs, four-input sums, 513-entry LUTs.",
            "rk_ew_regs.sv accepts BS_CFG/BN_CFG and related fields only at fixed no-op values as part of the all-or-none FP16 initialization group.",
        ],
        "not_supported": [
            "No BS/BN add/mul/relu/prelu arithmetic, no BRDMA/NRDMA, no LUT, no nonzero EW scale/offset/shift.",
            "Nonzero BS/BN values in conv_mesa/simple_conv/elementwise_int are rejected by the strict decoder.",
        ],
        "evidence": [
            "rtl/rk_ew_regs.sv: fixed 0x53/0x00/0x02 init values and no arithmetic.",
            "docs/REVIEW_AND_PLAN.md lists LUT/activation/conversion modes as deferred.",
        ],
    },
    {
        "id": "RDMA_PC",
        "label": "RDMA and PC command chain",
        "status": "partial_supported_strict",
        "rtl": [
            "rtl/rk_ew_dma.sv",
            "rtl/rk_ew_regs.sv",
            "rtl/rk_ew_engine.sv",
            "rtl/cmac/rk_cmac_array_dma.sv",
            "rtl/ddr/framework/rk_ew_async_engine.sv",
        ],
        "docs": ["docs/PC_DMA.md", "docs/INTERFACE.md"],
        "scope": [
            "EW DMA fetches raw QWORDs from command memory, supports linked terminal EW tasks, next-address/amount tails and a task limit.",
            "One outstanding halfword memory request; A/B/D scalar reads and writes; 16-byte aligned bases.",
        ],
        "not_supported": [
            "General DPU RDMA: surface line strides, ERDMA per-channel broadcast, BRDMA/NRDMA, multi-surface, FP32 operands, bursts.",
            "Vendor core_mask/subcore_task multi-core dispatch; CMAC linked PC chains (CMAC DMA is one terminal task).",
        ],
        "evidence": [
            "docs/PC_DMA.md and rtl/rk_ew_dma.sv.",
            "rtl/cmac/rk_cmac_array_dma.sv comments: one terminal task for the CMAC controller.",
        ],
    },
]

# ---------------------------------------------------------------------------
# Derive per-example status and fpga path
# ---------------------------------------------------------------------------

BLOCK_TO_SUPPORT = {b["id"]: b["status"] for b in BLOCK_SUPPORT}
CAPTURE_BLOCKED_FAMILIES = {"conv-fp16", "conv-simple", "conv-gemm-vendor", "pooling", "ew-int", "fdiv-systematic"}


def classify_example(item):
    cap = item["capture"]
    tags = list(item.get("manual_status", []))
    if cap["captured"]:
        if cap["exact_pass"]:
            tags.append("captured_exact")
        if cap["tolerance_pass"]:
            tags.append("captured_tolerance")
        if cap["known_divergence"]:
            tags.append("captured_known_divergence")
        if cap["truth_table"]:
            tags.append("captured_truth_table")
        if cap["captured_unverified"]:
            tags.append("captured_unverified")
    if cap["captured_not_implemented"]:
        tags.append("captured_not_implemented")
        tags.append("blocked_missing_rtl")
    if cap["prepared_not_run"]:
        tags.append("prepared_not_run")
    if cap["blocked"]:
        # classify by reading blocker text
        blocker_text = " ".join(
            (c.get("blocker") or "")
            for c in cap["case_list"] if c["manifest_status"] == "BLOCKED"
        )
        has_abi_case = False
        has_multitask_case = False
        if "MULTITASK_ROCKET_JOB_UNSUPPORTED" in blocker_text:
            tags.append("blocked_multitask_execution")
            has_multitask_case = True
        if ("Vendor-only ABI" in blocker_text or "core_mask" in blocker_text
                or "DRM_IOCTL_RKNPU" in blocker_text):
            tags.append("blocked_missing_abi")
            has_abi_case = True
        if not has_abi_case and not has_multitask_case and (
            "split-K" in blocker_text or "pad" in blocker_text or "stride" in blocker_text
            or "grouped" in blocker_text or "zero" in blocker_text or "ADDI" in blocker_text
        ):
            tags.append("blocked_unsupported_dtype_shape")
        if (not has_abi_case and not has_multitask_case
                and "blocked_unsupported_dtype_shape" not in tags):
            tags.append("blocked_unsupported_dtype_shape")
    if cap["runner_invalid"]:
        tags.append("blocked_bundle_integrity")
    abi = item["device_abi"]["primary"]
    if abi == "vendor-rknpu-drm" or abi == "vendor-default + rocket-option":
        tags.append("blocked_missing_abi")
    # RTL blockers are declared by the block map and support table.
    missing = []
    for block_id, level in item["hardware_blocks"].items():
        if level in ("-", "D", "B"):
            continue
        support = BLOCK_TO_SUPPORT.get(block_id, "unknown")
        if support == "missing_rtl":
            missing.append(block_id)
    if missing:
        tags.append("blocked_missing_rtl")
    if item["unknowns"]:
        tags.append("unknown")
    # Stable order + de-duplicate.
    order = [
        "captured_exact", "captured_tolerance", "captured_known_divergence",
        "captured_truth_table", "captured_unverified",
        "captured_not_implemented", "prepared_not_run",
        "blocked_missing_abi", "blocked_missing_rtl",
        "blocked_unsupported_dtype_shape", "blocked_multitask_execution",
        "blocked_bundle_integrity", "unknown",
    ]
    seen = []
    for name in order:
        if name in tags:
            seen.append(name)
    return seen


def compute_fpga_path(item):
    block_status = {}
    blockers = []
    for block_id, level in item["hardware_blocks"].items():
        if level in ("-", "D"):
            block_status[block_id] = "not_exercised"
        elif level == "B":
            block_status[block_id] = "configured_bypass_only"
        else:
            status = BLOCK_TO_SUPPORT.get(block_id, "unknown")
            block_status[block_id] = status
            if status == "missing_rtl":
                blockers.append(f"{block_id}: missing RTL")
            elif status == "partial_supported_strict":
                blockers.append(f"{block_id}: only the strict partial profile exists")
    if not blockers:
        if any(v == "supported_strict" for v in block_status.values()):
            blockers.append("RTL supports the exercised block(s), but no bundle for this exact example has been replayed on the FPGA; the prepared bundles are still device-free.")
        else:
            blockers.append("No FPGA mapping established.")
    return {
        "executable_now_as_written": False,
        "block_status": block_status,
        "blockers": blockers,
    }


for item in EXAMPLES_JSON:
    item["evidence_status"] = classify_example(item)
    item["fpga_path"] = compute_fpga_path(item)

# Notes get a simpler status
for note in NOTE_JSON:
    note["evidence_status"] = ["note"]

# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

EXAMPLE_COUNTS = Counter(item["classification"] for item in EXAMPLES_JSON)
ABI_COUNTS = Counter(item["device_abi"]["primary"] for item in EXAMPLES_JSON)
STATUS_COUNTS = Counter(tag for item in EXAMPLES_JSON for tag in item["evidence_status"])
EXAMPLES_WITH_BUNDLE = [item for item in EXAMPLES_JSON if item["capture"]["exists"]]
EXAMPLES_WITH_CAPTURE = [item for item in EXAMPLES_JSON if item["capture"]["captured"]]
EXAMPLES_WITH_PREPARED = [item for item in EXAMPLES_JSON if item["capture"]["prepared_not_run"]]
EXAMPLES_WITHOUT_BUNDLE = [item for item in EXAMPLES_JSON if not item["capture"]["exists"]]

BLOCK_EXAMPLE_COUNTS = {}
for block in BLOCK_SUPPORT:
    bid = block["id"]
    BLOCK_EXAMPLE_COUNTS[bid] = {
        "exercised": sum(1 for item in EXAMPLES_JSON if item["hardware_blocks"].get(bid) == "Y"),
        "partial_or_helper": sum(1 for item in EXAMPLES_JSON if item["hardware_blocks"].get(bid) == "P"),
        "bypass_or_config_only": sum(1 for item in EXAMPLES_JSON if item["hardware_blocks"].get(bid) == "B"),
        "definition_only": sum(1 for item in EXAMPLES_JSON if item["hardware_blocks"].get(bid) == "D"),
        "pc_only": sum(1 for item in EXAMPLES_JSON if item["hardware_blocks"].get(bid) == "PC-only"),
        "none": sum(1 for item in EXAMPLES_JSON if item["hardware_blocks"].get(bid) == "-"),
    }

# Capture family totals
FAMILY_TABLE = []
for fam in sorted(FAMILY_STATS):
    s = FAMILY_STATS[fam]
    FAMILY_TABLE.append({
        "family": fam,
        "total": s["total"],
        "ready": s["ready"],
        "blocked": s["blocked"],
        "captured": s["captured"],
        "captured_bytes": s["bytes"],
        "exact_pass": s["exact"],
        "tolerance_pass": s["tolerance"],
        "known_divergence": s["known"],
        "truth_table": s["truth"],
        "captured_unverified": s["unverified"],
        "prepared_not_run": s["prepared"],
        "runner_invalid": s["runner_invalid"],
    })

# ---------------------------------------------------------------------------
# Top gaps
# ---------------------------------------------------------------------------

TOP_GAPS = [
    {
        "rank": 1,
        "gap": "CNA/CBUF/CSC convolution datapath is absent",
        "blocks": ["CNA_CONV"],
        "examples": [item["relative_path"] for item in EXAMPLES_JSON if item["hardware_blocks"]["CNA_CONV"] in ("Y", "P")],
        "capture_cases": 39,
        "captured": 26,
        "prepared_not_run": 0,
        "blocked": 13,
        "runner_invalid": 0,
        "why": "The RTL has a CMAC array that consumes packed C32/K16 GEMM frames, but no CNA, CBUF, CSC, CDMA, im2col, pad, stride or convolution data-fetch engine. All 26 READY conv cases are captured: conv-fp16 9/9 exact, conv-gemm-vendor 10/10 PASS (8 exact, 2 tolerance), and conv-simple 4/7 exact plus 3 known divergences. The 13 BLOCKED cases are 3 vendor-ABI, 3 multi-task and 7 other shape/source. None can execute on the FPGA.",
        "evidence": ["rtl/ has no CNA/CBUF/CSC/convolution module", "docs/REVIEW_AND_PLAN.md lists general convolution as deferred", "results/conv-fp16-20261105T222300Z, results/conv-gemm-vendor-20261105T214000Z, results/conv-gemm-depthwise-rerun-20261105T221115Z and results/conv-simple-20261105T215921Z are the current receipts"],
    },
    {
        "rank": 2,
        "gap": "PPU pooling is absent",
        "blocks": ["PPU"],
        "examples": [item["relative_path"] for item in EXAMPLES_JSON if item["hardware_blocks"]["PPU"] in ("Y", "P")],
        "capture_cases": 21,
        "captured": 19,
        "prepared_not_run": 0,
        "blocked": 2,
        "why": "No PPU or PPU_RDMA RTL exists. The 19 READY pooling bundles are captured on RK3588 Rocket with 19/19 full-BO exact comparisons and 77,824 captured bytes, but none can execute on the FPGA. The two BLOCKED FP32/INT32 probes were not run. The kernel_6_18/conv.py PPU 'separator' record is not a pool operation and its semantics are unknown.",
        "evidence": ["grep of rtl/**/*.sv finds no PPU module", "docs/REVIEW_AND_PLAN.md lists PPU as deferred"],
    },
    {
        "rank": 3,
        "gap": "Integer EW and DPU BS/BN/LUT arithmetic are absent",
        "blocks": ["EW_INT", "DPU_BS_BN"],
        "examples": [item["relative_path"] for item in EXAMPLES_JSON if item["hardware_blocks"]["EW_INT"] == "Y" or item["hardware_blocks"]["DPU_BS_BN"] in ("Y", "P")],
        "capture_cases": 21,
        "captured": 17,
        "prepared_not_run": 0,
        "blocked": 4,
        "why": "15 ew-int cases are verified on RK3588 Rocket, but the FPGA ALU is FP16-only. The 3-case INT8 conv family is also captured: 2 INT8 cases show +1 LSB output-conversion divergences, 1 addition-input case is BLOCKED. rk_ew_regs accepts BS/BN fields only as fixed no-op initialization; there is no integer saturation, BS/BN ALU/MUL/ReLU/PReLU, BRDMA/NRDMA or LUT path.",
        "evidence": ["rtl/rk_fp16_alu.sv is half-precision only", "rtl/rk_ew_regs.sv fixes DATA_FORMAT to 0x48000002 and BS/BN init to fixed no-op values", "results/ew-int 15/15 verified on RK"],
    },
    {
        "rank": 4,
        "gap": "FDIV is captured on RK but has no RTL",
        "blocks": ["EW_FP16"],
        "examples": ["elementwise.py"],
        "capture_cases": 17,
        "captured": 17,
        "prepared_not_run": 0,
        "blocked": 0,
        "why": "FDIV is captured in 9 ew-fp16 cases and the 8-case, 256-class fdiv-systematic truth table. The 32-lane finite sweep and the 256-class truth table are correctly rounded nearest-even. The EW FP16 A/7 cases fdiv_p1_n33 and fdiv_p1_n1024 are the known divergence: 20 halfwords differ, explained by the three-guard-bit ties-to-even contract, which matches 1452/1452 real lanes. Do not model the divider as globally truncating toward zero. rk_ew_regs still rejects EW_CFG 0x108303c0 with error 2, and rk_fp16_alu has no divide operation.",
        "evidence": ["build/rk3588-kernel-comparison-v1 real-rocket-fdiv8* captures", "results/fdiv-systematic-20261105T204746Z (8 cases, 512 bytes, 256 classes, oracle none)", "rtl/rk_ew_regs.sv rejects FDIV EW_CFG", "rtl/rk_fp16_alu.sv implements only ADD/SUB/MUL/MAX"],
    },
    {
        "rank": 5,
        "gap": "Vendor RKNPU ABI and multi-core/PC-chain submission are not implemented",
        "blocks": ["RDMA_PC"],
        "examples": [item["relative_path"] for item in EXAMPLES_JSON if item["device_abi"]["primary"] in ("vendor-rknpu-drm", "vendor-default + rocket-option")],
        "capture_cases": 3,
        "prepared_not_run": 0,
        "blocked": 3,
        "why": "Eight examples use /dev/dri/card1 and DRM_IOCTL_RKNPU_*; expt/conv_simple.py defaults to that path. Rocket/FPGA has no core_mask/subcore_task fields, no RKNPU job ABI and no PC_BASE_ADDRESS self-address patch in the bundle schema. This blocks direct execution and three bundles: conv_tiles.py, plus conv.py's BY_K and H40 cases.",
        "evidence": ["examples/kernel_6_18/README.md documents the vendor-to-Rocket port", "conv-fp16/conv-gemm-vendor BLOCKED reasons", "docs/PC_DMA.md limits the FPGA PC chain to raw EW tasks"],
    },
]

ADDITIONAL_GAPS = [
    {
        "gap": "CMAC/GEMM is only a strict FP16 C32/K16 terminal profile",
        "detail": "gemm.py's four captured cases use small shapes and default FP32 output. The CMAC RTL requires physically packed operands, 32-multiple channels, rows 1..2047, FP16 output and no activation. General GEMM, runtime gathers and FP32 output remain missing.",
        "cases": 4,
    },
    {
        "gap": "General DPU RDMA/layout is missing",
        "detail": "No ERDMA per-channel broadcast, BRDMA/NRDMA, surface strides, multi-surface or FP32 operand path. EW scalar A/B/D works only for the strict contiguous profile. This is an underlying limitation for the integer/BS-BN/conv examples even after their arithmetic is added.",
        "cases": "many cases across ew-int, conv, BS/BN",
    },
    {
        "gap": "Blocked queue cases split across ABI, dtype/shape, multi-task and integrity",
        "detail": "12 cases are blocked by unsupported dtype/shape or missing source evidence (SAME pad, stride-2 FP16, C8 unpadded packing, grouped FP16, split-K, INT32 DIV, FP32/INT32 PPU, addition-input conv); 3 are blocked by the vendor/multi-core ABI; 3 are combined multi-task jobs (depthwise and conv-fp16 grouped/split-OC) where Rocket completes only task 0, each split into READY one-task cases; 0 current runner-invalid.",
        "cases": TOTAL_BLOCKED + TOTAL_RUNNER_INVALID,
    },
    {
        "gap": "Unknown semantics",
        "detail": "10 examples carry explicit unknown notes. Three contracts are especially important: conv_draft.py has an inconsistent FP16/FP32 output contract; conv_0522.py split-K/tile offsets are unproven; kernel_6_18/conv.py's PPU 'separator' record has unknown semantics. These are marked unknown, not supported.",
        "cases": 10,
    },
]

# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

GENERATED = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

DOC = {
    "schema": "rk3588-example-gap-matrix/1",
    "generated_utc": GENERATED,
    "scope": {
        "description": "Census of every Python example under /home/fedora/rk3588/examples and map of exercised RKNPU blocks to current FPGA RTL support.",
        "board_access": "none; no ssh/scp, no submit, no FPGA program/flash",
        "source_edits": "none; this directory is the only write target",
        "capture_rule": "A case is called captured only when its result tree contains capture.json plus a real output BO (out.bin or output.bin). A manifest READY flag alone is prepared, not captured. Oracle PASS/FAIL is recorded separately.",
        "fpga_rule": "RTL support is claimed only from actual rtl/ modules and docs, not from RK silicon behavior or prepared command streams.",
    },
    "source_revision": {
        "rknpu_fpga_git": "f9b00d8f9a48ab4dea20cb30148890cd9f1443ee",
        "rk3588_examples_git": "273d015e08af40c81d2cd9ab84198486b03a17f1",
        "python_host": "Python 3.14.5",
    },
    "summary": {
        "python_examples": len(EXAMPLES_JSON),
        "python_examples_by_directory": {
            "top_level": sum(1 for item in EXAMPLES_JSON if "/" not in item["relative_path"]),
            "expt": sum(1 for item in EXAMPLES_JSON if item["relative_path"].startswith("expt/")),
            "kernel_6_18": sum(1 for item in EXAMPLES_JSON if item["relative_path"].startswith("kernel_6_18/")),
        },
        "notes": len(NOTE_JSON),
        "classification_counts": dict(EXAMPLE_COUNTS),
        "abi_counts": dict(ABI_COUNTS),
        "examples_with_bundle": len(EXAMPLES_WITH_BUNDLE),
        "examples_without_bundle": len(EXAMPLES_WITHOUT_BUNDLE),
        "examples_with_capture": len(EXAMPLES_WITH_CAPTURE),
        "examples_with_prepared_not_run": len(EXAMPLES_WITH_PREPARED),
        "evidence_status_counts_non_exclusive": dict(STATUS_COUNTS),
        "capture_bundles": len(MANIFESTS),
        "capture_cases": TOTAL_CASES,
        "capture_ready": TOTAL_READY,
        "capture_blocked_manifest": TOTAL_BLOCKED,
        "capture_captured": TOTAL_CAPTURED,
        "capture_exact": TOTAL_EXACT,
        "capture_tolerance": TOTAL_TOLERANCE,
        "capture_known_divergence": TOTAL_KNOWN,
        "capture_truth_table": TOTAL_TRUTH,
        "capture_unverified": TOTAL_UNVERIFIED,
        "capture_prepared_not_run": TOTAL_PREPARED,
        "capture_runner_invalid": TOTAL_RUNNER_INVALID,
        "capture_blocked_total": TOTAL_BLOCKED + TOTAL_RUNNER_INVALID,
        "case_blocker_counts": dict(CASE_BLOCKER_COUNTS),
        "fpga_executions_of_these_bundles": 0,
        "all_capture_cases_accounted_for": TOTAL_CAPTURED + TOTAL_PREPARED + TOTAL_BLOCKED + TOTAL_RUNNER_INVALID == TOTAL_CASES,
    },
    "status_vocabulary": {
        "captured_exact": "At least one bundle case has a real device capture and an exact oracle comparison.",
        "captured_tolerance": "At least one bundle case has a real device capture and passes the declared tolerance, but is not byte-exact.",
        "captured_known_divergence": "At least one bundle case has a real device capture but differs from the declared oracle; the difference is known and scoped.",
        "captured_truth_table": "A real device capture exists as a truth table/characterization with no pass/fail oracle by design (currently fdiv-systematic).",
        "captured_unverified": "Real device output exists but no completed oracle comparison is available.",
        "captured_not_implemented": "A real device capture exists, but the corresponding arithmetic is not implemented in the FPGA RTL (currently FDIV).",
        "prepared_not_run": "Bundle is READY and runner-valid, but there is no results directory with real output BOs.",
        "blocked_missing_abi": "The example or bundle needs an ABI/transport the Rocket/FPGA path does not provide (vendor RKNPU, core_mask/subcore_task, PC self-address patch).",
        "blocked_missing_rtl": "A required arithmetic or data-movement block has no RTL implementation.",
        "blocked_unsupported_dtype_shape": "The dtype, shape, pad/stride/grouped contract, oracle or source evidence is unsupported or absent.",
        "blocked_multitask_execution": "The bundle needs a multi-task Rocket job, but this Rocket/FPGA path completes only the first task; the bundle is blocked or split into one-task cases.",
        "blocked_bundle_integrity": "Manifest says READY but the official runner validator rejects the bundle.",
        "unknown": "The example's semantics or output contract are not established.",
        "note": "Non-executable documentation file.",
    },
    "capture_runs": RESULT_RUNS,
    "capture_families": FAMILY_TABLE,
    "manifests": MANIFESTS,
    "block_support": BLOCK_SUPPORT,
    "block_example_counts": BLOCK_EXAMPLE_COUNTS,
    "examples": EXAMPLES_JSON,
    "notes": NOTE_JSON,
    "top_gaps": TOP_GAPS,
    "additional_gaps": ADDITIONAL_GAPS,
    "caveats": [
        "READY is a bundle-preparation state, not a device result. All 122 READY cases now have real RK3588 Rocket captures; 0 remain prepared and 18 are manifest BLOCKED.",
        "The 122 captures are RK3588 Rocket behavior, not FPGA execution. No FPGA run of any bundle in this queue is recorded here.",
        "Exact/tolerance split: 107 exact PASS, 2 tolerance-only PASS (conv-gemm GEMM m4n32k64 and conv.py full-setup), 5 known divergences, 8 fdiv-systematic truth-table cases, 0 unverified. The 18 BLOCKED cases are 3 ABI, 12 dtype/shape/oracle and 3 multi-task.",
        "ew-int is 15/15 verified. int16_add_to_int32_c8_w1 is a 31-QWORD bundle that needs one zero fetch-padding QWORD only for generic-runner replay.",
        "ew-fp16 has 54 captures: 52/54 match the donor oracle exactly. The two A/7 cases fdiv_p1_n33 and fdiv_p1_n1024 differ on 20 halfwords; the three-guard-bit ties-to-even contract explains them and matches 1452/1452 real lanes. This is a known divergence from the donor oracle, not global truncation.",
        "pooling is 19/19 full-BO exact over 77,824 bytes; the 2 blocked FP32/INT32 probes were not run. fdiv-systematic is 8/8 captured, 512 bytes and 256 operand classes, with oracle none by design.",
        "conv-fp16 is now split: 9/9 READY cases are captured and exact (35,392 bytes) after the multi-task cases were promoted to one-task _task0/_task1 bundles. The 5 BLOCKED cases (2 combined multi-task, pad-register, split-K, vendor ABI) were not run.",
        "conv-gemm-vendor is 10/10 PASS (80,640 bytes before the depthwise BO fix; 95,744 bytes counting the 15,104-byte depthwise rerun): 8 exact and 2 tolerance-only. The depthwise _task0/_task1 rerun is 702/702 exact after the 15,104-byte BO fix.",
        "conv-simple is 4/7 exact, 1 FP32-output C32 structural placement/zero-fill mismatch, and 2 INT8 +1 LSB output-conversion divergences. These are known divergences, not exact passes.",
        "The queue-index team snapshot is stale for this census: it still lists runner-invalid and prepared counts that the current job fixes and captures supersede.",
        "The conv-fp16-task-diagnostic result tree is task-level diagnostic evidence, not a separate case capture; it is excluded from the current conv-fp16 count to avoid double counting.",
        "The capture results are consumed as host-side receipts. This census did not re-audit the board run, oracle implementation or result hashes independently.",
        "C++/Python/RTL simulation and RK capture do not validate SystemVerilog timing, the physical FPGA or a new image. No bitstream or flash action is implied.",
    ],
}

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "EXAMPLE_MATRIX.json").write_text(json.dumps(DOC, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def md_escape(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def block_cell(value):
    return {
        "Y": "Y", "B": "B", "P": "P", "D": "D", "-": "-", "?": "?",
    }.get(value, md_escape(value))


def bundle_cell(item):
    c = item["capture"]
    if not c["exists"]:
        return "—"
    fams = ", ".join(c["families"])
    suffix = f" +{c['runner_invalid']}!" if c["runner_invalid"] else ""
    return f"`{fams}` {c['ready']}R/{c['blocked']}B/{c['captured']}C{suffix}"


def status_cell(item):
    return ", ".join(item["evidence_status"]) or "—"


def short_register_families(item):
    names = []
    for entry in item["register_families"]:
        for key in ("PPU_RDMA", "PPU", "CNA", "CORE", "DPU", "RDMA", "PC_REG", "PC", "VERSION"):
            if entry.startswith(key) and key not in names:
                names.append(key)
                break
    return ", ".join(names) if names else "—"


def abi_cell(item):
    p = item["device_abi"]["primary"]
    return {
        "vendor-rknpu-drm": "V",
        "rocket-mainline": "R",
        "rocket-mainline-via-rocket_runtime": "R*",
        "vendor-default + rocket-option": "V+R",
    }.get(p, md_escape(p))


lines = []
lines.append("# RK3588 example -> FPGA RTL gap matrix")
lines.append("")
lines.append(f"Snapshot: **{GENERATED}**  ")
lines.append("Host source: `rknpu-fpga@f9b00d8f9a48ab4dea20cb30148890cd9f1443ee`, "
             "`rk3588@273d015e08af40c81d2cd9ab84198486b03a17f1`.  ")
lines.append("Board access: **none** (no ssh/scp, no submit, no FPGA program/flash). "
             "All capture facts below are read from existing host-side receipts.")
lines.append("")
lines.append("This is a strict FP16 EW slice, not full RK3588 or a completed soDLA fork. "
             "The matrix separates **RK silicon capture**, **device-free prepared bundle**, "
             "**missing ABI**, **missing RTL**, **unsupported dtype/shape**, and **unknown**. "
             "FDIV is additionally marked **captured-not-implemented**: the real device output exists but the RTL has no divider. "
             "The fdiv-systematic truth table is **captured-characterization** because it has no pass/fail oracle by design. "
             "A `READY` manifest never means captured, and an RK result never means the FPGA RTL contains the block.")
lines.append("")

lines.append("## 1. Counts")
lines.append("")
lines.append("| Item | Count |")
lines.append("|---|---:|")
lines.append(f"| Python examples under `/home/fedora/rk3588/examples` | {len(EXAMPLES_JSON)} |")
lines.append("| Top-level / `expt/` / `kernel_6_18/` | 9 / 3 / 13 |")
lines.append(f"| Runnable / duplicate / draft | {EXAMPLE_COUNTS.get('runnable',0)} / {EXAMPLE_COUNTS.get('duplicate',0)} / {EXAMPLE_COUNTS.get('draft',0)} |")
lines.append(f"| Non-Python notes | {len(NOTE_JSON)} |")
lines.append(f"| Vendor RKNPU `/dev/dri/card1` ABI | {ABI_COUNTS.get('vendor-rknpu-drm',0)} |")
lines.append(f"| Vendor default + Rocket option | {ABI_COUNTS.get('vendor-default + rocket-option',0)} |")
lines.append(f"| Rocket `/dev/accel` ABI (direct or `rocket_runtime`) | {ABI_COUNTS.get('rocket-mainline',0) + ABI_COUNTS.get('rocket-mainline-via-rocket_runtime',0)} |")
lines.append(f"| Examples with a capture bundle | {len(EXAMPLES_WITH_BUNDLE)} |")
lines.append(f"| Examples with no bundle | {len(EXAMPLES_WITHOUT_BUNDLE)} |")
lines.append(f"| Capture bundles | {len(MANIFESTS)} |")
lines.append(f"| Manifest cases | {TOTAL_CASES} |")
lines.append(f"| READY / BLOCKED | {TOTAL_READY} / {TOTAL_BLOCKED} |")
lines.append(f"| Captured on RK3588 Rocket | **{TOTAL_CAPTURED}** |")
lines.append(f"| Exact PASS | **{TOTAL_EXACT}** |")
lines.append(f"| Tolerance-only PASS | **{TOTAL_TOLERANCE}** |")
lines.append(f"| Known divergence | **{TOTAL_KNOWN}** |")
lines.append(f"| Truth-table characterization | **{TOTAL_TRUTH}** |")
lines.append(f"| Captured, oracle comparison pending | **{TOTAL_UNVERIFIED}** |")
lines.append(f"| Prepared, runner-valid, not run | **{TOTAL_PREPARED}** |")
lines.append(f"| Manifest READY but runner-invalid | **{TOTAL_RUNNER_INVALID}** |")
lines.append(f"| Blocked total (manifest + runner-invalid) | **{TOTAL_BLOCKED + TOTAL_RUNNER_INVALID}** |")
lines.append("| Blocked cases by missing ABI / dtype-shape / multi-task / integrity | "
             f"{CASE_BLOCKER_COUNTS.get('blocked_missing_abi',0)} / "
             f"{CASE_BLOCKER_COUNTS.get('blocked_unsupported_dtype_shape',0)} / "
             f"{CASE_BLOCKER_COUNTS.get('blocked_multitask_execution',0)} / "
             f"{CASE_BLOCKER_COUNTS.get('blocked_bundle_integrity',0)} |")
lines.append(f"| FPGA executions of these bundles | **0** |")
lines.append("")
lines.append("Check: captured + prepared + blocked total = "
             f"{TOTAL_CAPTURED} + {TOTAL_PREPARED} + {TOTAL_BLOCKED + TOTAL_RUNNER_INVALID} = "
             f"{TOTAL_CAPTURED + TOTAL_PREPARED + TOTAL_BLOCKED + TOTAL_RUNNER_INVALID} = {TOTAL_CASES}.")
lines.append("")
lines.append(f"Captured breakdown: {TOTAL_EXACT} exact PASS + {TOTAL_TOLERANCE} tolerance PASS + "
             f"{TOTAL_KNOWN} known divergence + {TOTAL_TRUTH} truth table + {TOTAL_UNVERIFIED} pending = {TOTAL_CAPTURED}.")
lines.append("")
lines.append("Non-exclusive example labels: " + ", ".join(
    f"`{k}` {v}" for k, v in sorted(STATUS_COUNTS.items()))) 
lines.append("")

lines.append("## 2. Capture queue")
lines.append("")
lines.append("A case is **captured** only when its result directory contains `capture.json` plus a real output BO "
             "(`out.bin`, `out0.bin`, `out1.bin` or `output.bin`). Exact, tolerance-only, known-divergence and truth-table states are shown separately. "
             "All 122 READY cases are captured. `ew-int` is 15/15 exact; `pooling` is 19/19 full-BO exact; `fdiv-systematic` is an 8-case, 256-class truth table. "
             "`conv-fp16` is 9/9 exact after the multi-task split. `conv-gemm-vendor` is 10/10 PASS (8 exact, 2 tolerance), including the depthwise 702/702 rerun after the 15,104-byte BO fix. "
             "`conv-simple` is 4/7 exact, with 1 FP32-output C32 structural mismatch and 2 INT8 +1 LSB output-conversion divergences.")
lines.append("")
lines.append("| Family | Total | READY | BLOCKED | Captured | Bytes | Exact | Tolerance | Known | Truth | Pending | Prepared |")
lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
for row in FAMILY_TABLE:
    lines.append(f"| `{row['family']}` | {row['total']} | {row['ready']} | {row['blocked']} | "
                 f"{row['captured']} | {row['captured_bytes']} | {row['exact_pass']} | "
                 f"{row['tolerance_pass']} | {row['known_divergence']} | {row['truth_table']} | "
                 f"{row['captured_unverified']} | {row['prepared_not_run']} |")
lines.append(f"| **Total** | **{TOTAL_CASES}** | **{TOTAL_READY}** | **{TOTAL_BLOCKED}** | "
             f"**{TOTAL_CAPTURED}** | **{sum(r['captured_bytes'] for r in FAMILY_TABLE)}** | "
             f"**{TOTAL_EXACT}** | **{TOTAL_TOLERANCE}** | **{TOTAL_KNOWN}** | "
             f"**{TOTAL_TRUTH}** | **{TOTAL_UNVERIFIED}** | **{TOTAL_PREPARED}** |")
lines.append("")
lines.append("Result roots: " + "; ".join(
    f"`{run['path']}` ({run['case_count']} cases, {run['bytes_read_total']} bytes"
    + (f", {run['submit_ret_zero_count']} submit_ret=0" if run.get('submit_ret_zero_count') is not None else "")
    + (f", {run['hostname']} / {run['kernel']}" if run.get('hostname') else "")
    + ")" for run in RESULT_RUNS) + ".")
lines.append("")
lines.append("Result-root accounting: the old `conv-fp16-20261105T205900Z` tree contributes only the 2 now-BLOCKED combined captures (8,192 bytes); "
             "the current 9/9 exact count comes from `conv-fp16-20261105T222300Z` (35,392 bytes). "
             "`conv-gemm-vendor-20261105T214000Z` contributes 8 cases/65,536 bytes; the depthwise rerun `conv-gemm-depthwise-rerun-20261105T221115Z` contributes 2 cases/30,208 bytes (15,104 bytes each) and supersedes the failed depthwise outputs. "
             "`conv-simple-20261105T215921Z` contributes 7 cases/21,888 bytes (4 exact + 3 known divergence).")
lines.append("")

lines.append("## 3. Example census")
lines.append("")
lines.append("Block symbols: `Y` exercised, `B` configured/bypass only, `P` partial/helper or non-main path, "
             "`D` definition only, `PC-only` = PC command chain used without a data-path RDMA block, `-` not used. "
             "`V` = vendor `/dev/dri/card1` RKNPU; `R` = Rocket `/dev/accel`; "
             "`R*` = Rocket via `rocket_runtime`; `V+R` = vendor default with Rocket option. "
             "Bundle counts are `READY/BLOCKED/CAPTURED`.")
lines.append("")
lines.append("| Example | Kind | ABI | EW-F16 | EW-INT | PPU | CNA/conv | CMAC/GEMM | BS/BN | RDMA/PC | Bundle R/B/C | Evidence |")
lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|")
for item in EXAMPLES_JSON:
    b = item["hardware_blocks"]
    lines.append(
        f"| `{item['relative_path']}` | {item['classification']} | {abi_cell(item)} | "
        f"{block_cell(b['EW_FP16'])} | {block_cell(b['EW_INT'])} | {block_cell(b['PPU'])} | "
        f"{block_cell(b['CNA_CONV'])} | {block_cell(b['CMAC_GEMM'])} | {block_cell(b['DPU_BS_BN'])} | "
        f"{block_cell(b['RDMA_PC'])} | {bundle_cell(item)} | {status_cell(item)} |"
    )
lines.append("")
lines.append("Notes: " + ", ".join(f"`{n['path'].split('/examples/')[-1]}`" for n in NOTE_JSON) + ".")
lines.append("")
lines.append("Key entry points / CLI:")
lines.append("")
for item in EXAMPLES_JSON:
    lines.append(f"- `{item['relative_path']}` — {item['entry_point']}; `{item['cli']}`")
lines.append("")
lines.append("Register families (abridged; full lists in `EXAMPLE_MATRIX.json`):")
lines.append("")
lines.append("| Example | Target families |")
lines.append("|---|---|")
for item in EXAMPLES_JSON:
    lines.append(f"| `{item['relative_path']}` | {short_register_families(item)} |")
lines.append("")

lines.append("## 4. Block support in the actual RTL")
lines.append("")
lines.append("| Block | FPGA status | RTL present | Scope / gap |")
lines.append("|---|---|---|---|")
for block in BLOCK_SUPPORT:
    rtl = "<br>".join(f"`{p}`" for p in block["rtl"]) if block["rtl"] else "**none**"
    scope = " ".join(block["scope"])
    gap = " ".join(block["not_supported"])
    lines.append(f"| **{block['id']}** — {md_escape(block['label'])} | **{block['status']}** | {rtl} | "
                 f"Supported: {md_escape(scope)}<br>Not supported: {md_escape(gap)} |")
lines.append("")
lines.append("Evidence by block:")
lines.append("")
for block in BLOCK_SUPPORT:
    lines.append(f"- **{block['id']}**: " + "; ".join(md_escape(e) for e in block["evidence"]))
lines.append("")

lines.append("## 5. Top five blocking gaps")
lines.append("")
for gap in TOP_GAPS:
    lines.append(f"### {gap['rank']}. {gap['gap']}")
    lines.append("")
    lines.append(gap["why"])
    lines.append("")
    count_bits = [
        f"examples: {len(gap['examples'])}",
        f"queue cases: {gap['capture_cases']}",
        f"captured: {gap.get('captured', 0)}",
        f"prepared: {gap['prepared_not_run']}",
        f"blocked: {gap['blocked']}",
    ]
    if gap.get("runner_invalid"):
        count_bits.append(f"runner-invalid: {gap['runner_invalid']}")
    lines.append("; ".join(count_bits) + ".")
    lines.append("")
    lines.append("Affected: " + ", ".join(f"`{e}`" for e in gap["examples"]))
    lines.append("")
    lines.append("Evidence: " + "; ".join(md_escape(e) for e in gap["evidence"]))
    lines.append("")

lines.append("## 6. Additional gaps and unknowns")
lines.append("")
for gap in ADDITIONAL_GAPS:
    lines.append(f"- **{gap['gap']}** ({gap['cases']}): {gap['detail']}")
lines.append("")
lines.append("Explicit unknowns:")
lines.append("")
for item in EXAMPLES_JSON:
    if item["unknowns"]:
        lines.append(f"- `{item['relative_path']}`: " + " ".join(item["unknowns"]))
lines.append("")
lines.append("## 7. What is actually verified")
lines.append("")
lines.append("| Evidence level | What it covers | What it does not cover |")
lines.append("|---|---|---|")
lines.append("| Real RK3588 Rocket capture | 122 cases: 54 ew-fp16 (52 exact + 2 known), 15 ew-int exact, 19 pooling exact, 8 fdiv truth table, 9 conv-fp16 exact, 10 conv-gemm-vendor (8 exact + 2 tolerance), 7 conv-simple (4 exact + 3 known). | Not FPGA, not vendor RKNPU, not SystemVerilog |")
lines.append("| RTL simulation | EW FP16 ADD/SUB/MUL/MAX/NEG8 and special matrices in `build/rk3588-kernel-comparison-v1` | Not the full captured queues, not physical FPGA, not timing closure |")
lines.append("| Prepared bundles | 0 runner-valid READY cases remain; all 122 READY cases are captured | Not applicable |")
lines.append("| Blocked cases | 18 manifest BLOCKED; 0 current runner-invalid | No bundle may be submitted |")
lines.append("| RTL block support | EW FP16 strict, CMAC strict partial, RDMA/PC strict partial | No CNA/conv, PPU, EW INT, BS/BN/LUT, FDIV |")
lines.append("")
lines.append("## 8. Caveats")
lines.append("")
for caveat in DOC["caveats"]:
    lines.append(f"- {caveat}")
lines.append("")
lines.append("Method and file-level notes are in `README.md`; the machine-readable form is `EXAMPLE_MATRIX.json`.")
lines.append("")

(OUT / "GAP_MATRIX.md").write_text("\n".join(lines) + "\n")
print(f"wrote {OUT/'EXAMPLE_MATRIX.json'}")
print(f"wrote {OUT/'GAP_MATRIX.md'}")
print(f"counts: examples={len(EXAMPLES_JSON)} notes={len(NOTE_JSON)} cases={TOTAL_CASES} "
      f"captured={TOTAL_CAPTURED} exact={TOTAL_EXACT} tolerance={TOTAL_TOLERANCE} known={TOTAL_KNOWN} truth={TOTAL_TRUTH} prepared={TOTAL_PREPARED} "
      f"blocked={TOTAL_BLOCKED}+{TOTAL_RUNNER_INVALID}")
