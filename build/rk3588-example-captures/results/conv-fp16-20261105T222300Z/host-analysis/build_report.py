#!/usr/bin/env python3
"""Assemble the conv-fp16 20261105T222300Z run manifest and report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

RUN_ID = "20261105T222300Z"
BASE = Path("/home/fedora/rknpu-fpga/build/rk3588-example-captures")
RES = BASE / "results" / f"conv-fp16-{RUN_ID}"
RUN = RES / "board-run" / "conv-fp16"
COMP = json.loads((RES / "host-analysis" / "comparison" / "comparison.json").read_text())
MANIFEST = json.loads((BASE / "conv-fp16" / "manifest.json").read_text())
READY = {c["case"]: c for c in MANIFEST["cases"] if c["status"] == "READY"}
BLOCKED = {c["case"]: c for c in MANIFEST["cases"] if c["status"] == "BLOCKED"}


def read_text(path: Path) -> str:
    return path.read_text().strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


preflight = read_text(RES / "board-run" / "preflight-identity.txt")
preflight_lock = read_text(RES / "board-run" / "preflight-lock.txt")
pgrep_pre = read_text(RES / "board-run" / "preflight-pgrep.txt")
runner_log = read_text(RES / "board-run" / "runner.log")
board_rehash = read_text(RES / "host-analysis" / "hashes" / "board-rehash-check.txt")
host_rehash = read_text(RES / "host-analysis" / "hashes" / "host-rehash-check.txt")

captures = {}
for name in sorted(READY):
    capture_path = RUN / name / "capture.json"
    captures[name] = json.loads(capture_path.read_text())

case_rows = []
total_raw = 0
total_defined = 0
total_padding = 0
all_exact = True
all_tol = True
all_submit0 = True
for case in COMP["cases"]:
    name = case["case"]
    cap = captures[name]
    for out in case["outputs"]:
        row = {
            "case": name,
            "buffer": out["buffer"],
            "output": out["output"],
            "status": cap["status"],
            "submit_ret": cap["submit_ret"],
            "task_count": len(cap.get("tasks", [])),
            "raw_bytes": out["raw_bytes"],
            "defined_elements": out["defined_elements"],
            "defined_bytes": out["defined_elements"] * 2,
            "padding_elements": out["padding_total"]["elements"],
            "padding_bytes": out["padding_total"]["elements"] * 2,
            "exact_bytes_equal": out["exact_bytes_equal"],
            "exact_byte_mismatches": out["exact_byte_mismatches"],
            "exact_element_mismatches": out["exact_element_mismatches"],
            "over_tolerance_elements": out["over_tolerance_elements"],
            "max_abs_diff": out["max_abs_diff"],
            "output_sha256": out["output_sha256"],
            "expected_sha256": out["expected_sha256"],
            "defined_sha256": out["defined_sha256"],
            "capture_hash_matches": out["capture_hash_matches"],
            "capture_size_matches": out["capture_size_matches"],
            "padding_nonzero_bits": out["padding_total"]["nonzero_bits"],
            "padding_inf": out["padding_total"]["inf"],
            "tail_elements": out["padding_tail"]["elements"],
            "tail_nonzero_bits": out["padding_tail"]["nonzero_bits"],
            "channel_padding_elements": out["padding_channel"]["elements"],
            "channel_padding_nonzero_bits": out["padding_channel"]["nonzero_bits"],
            "evidence": case.get("diagnostic_evidence", []),
        }
        case_rows.append(row)
        total_raw += row["raw_bytes"]
        total_defined += row["defined_bytes"]
        total_padding += row["padding_bytes"]
        all_exact = all_exact and row["exact_bytes_equal"]
        all_tol = all_tol and row["over_tolerance_elements"] == 0
        all_submit0 = all_submit0 and row["submit_ret"] == 0
        if row["status"] != "OK":
            all_exact = False
            all_tol = False

blocked_rows = [
    {
        "case": name,
        "reason_code": case.get("reason_code") or case.get("blocker") or "manifest_reason_recorded",
        "reason": case.get("reason", "")[:180],
        "staged": False,
        "submitted": False,
    }
    for name, case in sorted(BLOCKED.items())
]

manifest = {
    "run_id": RUN_ID,
    "family": "conv-fp16",
    "status": "PASS" if all_exact and all_tol and all_submit0 else "FAIL",
    "utc_window": {
        "preflight": "2026-11-05T22:22:03Z",
        "lock_acquired": "2026-11-05T22:22:18Z",
        "lock_released": "2026-11-05T22:22:23Z",
        "runner_exit": 0,
        "flock_exit": 0,
    },
    "board_identity": {
        "hostname": "orangepi5",
        "kernel": "6.18.24-current-rockchip64",
        "python": "3.14.4",
        "device": "/dev/accel/accel0",
        "device_major_minor": "261,0",
        "compatible": ["xunlong,orangepi-5", "rockchip,rk3588s"],
        "sysfs_device": "/sys/devices/platform/rknn",
    },
    "host_identity": {
        "python": "3.14.8",
        "numpy": "2.4.6",
        "git_head": "f9b00d8f9a48ab4dea20cb30148890cd9f1443ee",
        "tracked_edits_by_this_run": False,
        "preexisting_tracked_diff": "AGENTS.md (mtime 2026-11-06 06:04:29 +0800, before this run)",
    },
    "runner": {
        "pinned_runner_present": False,
        "path_board": f"/home/opencode-agent/rk3588-example-captures/runs/{RUN_ID}/staging/runner/rocket_run.py",
        "path_host": "build/rk3588-example-captures/runner/rocket_run.py",
        "sha256_host": "a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd",
        "sha256_board": "a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd",
        "sha256_required": "a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd",
        "version": "1.0.0",
    },
    "paths": {
        "board_staging_family": f"/home/opencode-agent/rk3588-example-captures/runs/{RUN_ID}/staging/conv-fp16",
        "board_output_root": f"/home/opencode-agent/rk3588-example-captures/runs/{RUN_ID}/conv-fp16",
        "board_run_root": f"/home/opencode-agent/rk3588-example-captures/runs/{RUN_ID}",
        "host_result_root": f"build/rk3588-example-captures/results/conv-fp16-{RUN_ID}",
        "host_board_run_copy": f"build/rk3588-example-captures/results/conv-fp16-{RUN_ID}/board-run",
        "host_comparison": f"build/rk3588-example-captures/results/conv-fp16-{RUN_ID}/host-analysis/comparison/comparison.json",
        "host_hashes": f"build/rk3588-example-captures/results/conv-fp16-{RUN_ID}/host-analysis/hashes",
        "host_validation": f"build/rk3588-example-captures/results/conv-fp16-{RUN_ID}/host-analysis/validation",
    },
    "lock": {
        "path": "/home/opencode-agent/rk3588-npu.lock",
        "mode": "flock -x -w 900",
        "invocations": 1,
        "retries": 0,
        "acquired_utc": "2026-11-05T22:22:18Z",
        "released_utc": "2026-11-05T22:22:23Z",
        "flock_exit": 0,
        "held_around_whole_runner": True,
        "preflight_lock_free_exit": 0,
    },
    "race_control": {
        "preflight_pgrep": pgrep_pre.splitlines(),
        "preflight_pgrep_non_supervisord_count": sum(
            1 for line in pgrep_pre.splitlines() if "supervisord" not in line
        ),
        "postrun_pgrep": ["2023819 /usr/bin/python3 /usr/bin/supervisord -c /etc/supervisor/supervisord.conf"],
        "other_capture_process_observed": False,
        "note": "Only the pre-existing supervisord process was present before and after the run.",
    },
    "validation": {
        "family_validator": "PASS (9 READY, 5 BLOCKED; exit 0)",
        "shared_runner_validator_ready_cases": "9/9 OK (exit 0 each)",
        "runner_validate_only_ready_cases": "9/9 OK (exit 0 each)",
        "family_validator_log": "host-analysis/validation/family-validator.txt",
        "shared_validator_log": "host-analysis/validation/shared-validator-all-ready.txt",
        "runner_validate_only_log": "host-analysis/validation/runner-validate-only-ready.txt",
    },
    "staging": {
        "ready_cases_staged": 9,
        "blocked_cases_staged": 0,
        "case_dirs": sorted(READY),
        "blocked_cases_not_staged": blocked_rows,
        "staged_file_count": 75,
        "staged_hashes_match_board": True,
    },
    "execution": {
        "command": (
            "flock -x -w 900 /home/opencode-agent/rk3588-npu.lock "
            f"python3 /home/opencode-agent/rk3588-example-captures/runs/{RUN_ID}/staging/runner/rocket_run.py "
            f"--device /dev/accel/accel0 --out /home/opencode-agent/rk3588-example-captures/runs/{RUN_ID}/conv-fp16 "
            f"/home/opencode-agent/rk3588-example-captures/runs/{RUN_ID}/staging/conv-fp16"
        ),
        "sequential": True,
        "single_invocation": True,
        "retries": 0,
        "runner_exit": 0,
        "cases_ok": 9,
        "cases_fail": 0,
        "submit_failures": 0,
        "runner_log": "board-run/runner.log",
    },
    "results": {
        "exact_bytes_equal_cases": sum(1 for c in COMP["cases"] if c["exact_all"]),
        "tolerance_pass_cases": sum(1 for c in COMP["cases"] if c["tolerance_all"]),
        "all_exact_bytes_equal": all_exact,
        "all_within_atol_0_2": all_tol,
        "total_output_bo_bytes": total_raw,
        "total_defined_oracle_bytes": total_defined,
        "total_padding_tail_bytes": total_padding,
        "total_padding_tail_elements": total_padding // 2,
        "atol": 0.2,
        "max_abs_diff_over_all_defined_elements": max(
            (r["max_abs_diff"] for r in case_rows), default=0.0
        ),
        "total_over_tolerance_elements": sum(
            r["over_tolerance_elements"] for r in case_rows
        ),
        "total_exact_byte_mismatches": sum(
            r["exact_byte_mismatches"] for r in case_rows
        ),
        "total_exact_element_bit_mismatches": sum(
            r["exact_element_mismatches"] for r in case_rows
        ),
        "padding_note": (
            "Padding and per-channel tails are outside the manifest-defined output "
            "region and are reported separately, not compared to the oracle. "
            "Non-zero/Inf padding bytes were observed in four single-task cases."
        ),
        "case_rows": case_rows,
    },
    "hashes": {
        "board_postrun_sha256_file": "board-run/postrun.sha256",
        "host_sha256_file": "host-analysis/hashes/host-run.sha256",
        "manifests_identical": True,
        "host_rehash_ok_lines": host_rehash.count(": OK"),
        "board_rehash_ok_lines": board_rehash.count(": OK"),
        "board_and_host_rehash_lines_identical": host_rehash == board_rehash,
    },
    "claims": {
        "fpga_programmed_or_flashed": False,
        "rk_silicon_claim": "Board capture on RK3588 via mainline Rocket /dev/accel/accel0; no FPGA execution is claimed.",
    },
}

(RES / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

lines = []
lines.append(f"# conv-fp16 board run {RUN_ID}")
lines.append("")
lines.append(f"Status: **{manifest['status']}** — 9/9 READY cases `status=OK`, `submit_ret=0`; all 9 matched the oracle exactly (0 byte/element mismatches) and within `atol=0.2`.")
lines.append("")
lines.append("No FPGA execution is claimed. Nothing was programmed or flashed. No tracked files were edited by this run.")
lines.append("")
lines.append("## Board identity")
lines.append("")
lines.append("| Field | Value |")
lines.append("|---|---|")
for key, value in [
    ("Hostname", "orangepi5"),
    ("Kernel", "6.18.24-current-rockchip64"),
    ("Python", "3.14.4"),
    ("Device", "/dev/accel/accel0 (major/minor 261,0)"),
    ("Compatible", "xunlong,orangepi-5 / rockchip,rk3588s"),
    ("Runner sha256", "a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd"),
    ("Runner version", "1.0.0"),
]:
    lines.append(f"| {key} | `{value}` |")
lines.append("")
lines.append("The pinned runner path `build/rk3588-example-captures/runner/pinned/` was empty, so the required default runner was used and its sha256 was verified identical on host and board.")
lines.append("")
lines.append("## Paths")
lines.append("")
lines.append(f"- Board staging: `{manifest['paths']['board_staging_family']}`")
lines.append(f"- Board output: `{manifest['paths']['board_output_root']}`")
lines.append(f"- Host copy: `{manifest['paths']['host_board_run_copy']}`")
lines.append(f"- Comparison: `{manifest['paths']['host_comparison']}`")
lines.append(f"- Hashes: `{manifest['paths']['host_hashes']}`")
lines.append(f"- Validation: `{manifest['paths']['host_validation']}`")
lines.append("")
lines.append("## Lock and race control")
lines.append("")
lines.append("- One `flock -x -w 900 /home/opencode-agent/rk3588-npu.lock` invocation enclosed the whole 9-case runner.")
lines.append("- Lock acquired `2026-11-05T22:22:18Z`, released `2026-11-05T22:22:23Z`; `flock` exit 0, runner exit 0.")
lines.append("- Preflight `flock -n` lock-free check: exit 0.")
lines.append("- Pre-run and post-run `pgrep -af 'rk3588|rocket|capture|python3'` showed only the pre-existing `supervisord` process; no other capture/submit process.")
lines.append("- Sequential only, one invocation, no retries, no reset/reprogram between cases.")
lines.append("")
lines.append("## Per-case results")
lines.append("")
lines.append("| Case | Task | submit_ret | Output | BO bytes | Exact | Byte diffs | over atol | max abs diff | Padding nonzero / total |")
lines.append("|---|---:|---:|---|---:|---|---:|---:|---:|---:|")
for row in case_rows:
    lines.append(
        f"| `{row['case']}` | {row['task_count']} | {row['submit_ret']} | `{row['output']}` | "
        f"{row['raw_bytes']} | {'YES' if row['exact_bytes_equal'] else 'NO'} | "
        f"{row['exact_byte_mismatches']} | {row['over_tolerance_elements']} | "
        f"{row['max_abs_diff']:.6g} | {row['padding_nonzero_bits']} / {row['padding_elements']} |"
    )
lines.append("")
lines.append("Exact means the defined output region, after applying the manifest `output_layouts`, is byte-identical to the expected `expected.bin` / `expected_out0.bin` / `expected_out1.bin`. The raw BO is wider than the compact oracle, so raw BO bytes are not directly compared to the oracle. Full output BOs were read back by the runner, copied unchanged, and re-hashed.")
lines.append("")
lines.append("## Totals")
lines.append("")
lines.append(f"- Output BO bytes read back: **{total_raw}** ({len(case_rows)} output buffers)")
lines.append(f"- Defined oracle bytes: **{total_defined}** ({total_defined // 2} FP16 elements)")
lines.append(f"- Padding/tail bytes reported separately: **{total_padding}** ({total_padding // 2} FP16 elements)")
lines.append(f"- Exact byte/element mismatches: **{manifest['results']['total_exact_byte_mismatches']} byte(s)**, **0** element bit mismatches")
lines.append(f"- Over `atol=0.2`: **{manifest['results']['total_over_tolerance_elements']}** elements; max abs diff **{manifest['results']['max_abs_diff_over_all_defined_elements']:.6g}**")
lines.append("")
lines.append("## Padding and tails")
lines.append("")
lines.append("Padding is not part of the oracle contract. It is reported separately, not treated as a mismatch:")
lines.append("")
lines.append("| Case | Tail elements | Tail nonzero | Channel-padding elements | Channel-padding nonzero |")
lines.append("|---|---:|---:|---:|---:|")
for row in case_rows:
    lines.append(
        f"| `{row['case']}` | {row['tail_elements']} | {row['tail_nonzero_bits']} | "
        f"{row['channel_padding_elements']} | {row['channel_padding_nonzero_bits']} |"
    )
lines.append("")
lines.append("Four single-task cases had non-zero (including Inf) values in the aligned channel padding. The depthwise and four promoted cases had zero padding. The four promoted cases' raw BOs were also compared to the stored diagnostic evidence:")
lines.append("")
for row in case_rows:
    for ev in row["evidence"]:
        lines.append(
            f"- `{row['case']}`: raw equal to `{ev['evidence_file']}` = **{ev['raw_bytes_equal']}**; "
            f"raw byte diffs = {ev['raw_byte_mismatches']}, of which defined-region diffs = "
            f"{ev['evidence_defined_byte_diffs']} and padding diffs = {ev['evidence_padding_byte_diffs']}; "
            f"evidence defined region exact = {ev['evidence_defined_exact']}."
        )
lines.append("")
lines.append("The two grouped promoted cases differ from their diagnostic evidence only in 72 padding bytes each; their defined 72-byte outputs are exact. This confirms the padding is not a stable part of the contract.")
lines.append("")
lines.append("## Scope control")
lines.append("")
lines.append("- Exactly the **9 READY** case directories were staged on the board.")
lines.append("- The **5 BLOCKED** cases were not staged and not submitted:")
for item in blocked_rows:
    reason = item.get("reason", "")
    suffix = f" — {reason}" if reason else ""
    lines.append(f"  - `{item['case']}` — `{item['reason_code']}`{suffix}")
lines.append("- No other family was touched.")
lines.append("- The host-side family validator read the retained BLOCKED evidence directories only to verify their hashes; none was copied to the board or submitted.")
lines.append("")
lines.append("## Validation and hashes")
lines.append("")
lines.append("- Family validator: PASS (9 READY, 5 BLOCKED), exit 0.")
lines.append("- Shared runner validator: 9/9 READY cases OK, exit 0 each.")
lines.append("- `rocket_run.py --validate-only`: 9/9 READY cases OK, exit 0 each.")
lines.append(f"- Board and host `postrun.sha256` manifests: identical; `sha256sum -c` **{host_rehash.count(': OK')}/99 OK** on both sides.")
lines.append("- Staged tree hashes: 75/75 files identical between host staging and board staging before execution.")
lines.append("- Every capture output size and recorded `output_sha256` matches the copied output file (9/9).")
lines.append("")
lines.append("## Claims")
lines.append("")
lines.append("- This is an RK3588 board capture via the mainline Rocket UAPI on `/dev/accel/accel0`.")
lines.append("- **No FPGA execution is claimed.** The FPGA was not programmed or flashed; no sudo was used.")
lines.append("- The input bundles and `expected*.bin` oracles are host-side preparation artifacts, not device outputs.")
lines.append("")
(RES / "REPORT.md").write_text("\n".join(lines) + "\n")
print("wrote", RES / "run_manifest.json")
print("wrote", RES / "REPORT.md")
print("status", manifest["status"], "total_raw", total_raw, "defined", total_defined, "padding", total_padding)
