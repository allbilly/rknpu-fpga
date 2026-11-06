#!/usr/bin/env bash
# K8 phase gate: fresh routed checkpoint only. Never programs or accesses hardware.
set -euo pipefail
PKG="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(git -C "$PKG/../.." rev-parse --show-toplevel)"
REPORT_SOURCE="${K8_IMPLEMENTATION_REPORT:-/home/fedora/rknpu-fpga/build/k8-full-top-v1/implementation-report.json}"
RUN="$PKG/emission-run-k8-v1"

python3 - "$ROOT" "$PKG" "$REPORT_SOURCE" "$RUN" <<'PY'
from pathlib import Path
import datetime, hashlib, json, re, shutil, subprocess, sys

root, pkg, report_source, run = (Path(arg).resolve() for arg in sys.argv[1:])
expected_drc = {"DPIP-1": 526, "DPOP-1": 263, "DPOP-2": 263, "REQP-1709": 2}

def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def need(condition, message):
    if not condition:
        raise SystemExit("FAIL_PREEMISSION: " + message)

def drc_inventory(path):
    text = Path(path).read_text()
    totals = re.findall(r"Checks found:\s*(\d+)", text)
    need(len(totals) == 1 and int(totals[0]) == sum(expected_drc.values()),
         "final default DRC total")
    actual = {}
    for line in text.splitlines():
        columns = [field.strip() for field in line.strip().strip("|").split("|")]
        if len(columns) != 4 or not re.fullmatch(r"[A-Z][A-Z0-9_-]*-[0-9]+", columns[0]):
            continue
        rule, severity, _description, count = columns
        need(rule not in actual and severity == "Warning" and count.isdigit(),
             "unreviewed DRC rule/severity/count")
        actual[rule] = int(count)
    need(actual == expected_drc, "final default DRC warning inventory")
    return actual

need(not run.exists(), "fresh emission output directory already exists; refusing stale output")
need(report_source.is_file(), "existing K8 implementation-report.json missing")
profile_check = subprocess.run([sys.executable, str(pkg / "check_profile.py")],
                               cwd=root, check=False, text=True, capture_output=True)
need(profile_check.returncode == 0,
     "K8 source profile check failed: " + profile_check.stdout + profile_check.stderr)

manifest_path = pkg / "source-manifest.json"
profile_path = pkg / "source-profile.json"
synthesis_path = pkg / "synthesis-report.json"
manifest = json.loads(manifest_path.read_text())
profile = json.loads(profile_path.read_text())
report = json.loads(report_source.read_text())
manifest_sha = sha(manifest_path)
profile_sha = sha(profile_path)
tag = manifest_sha[:8]
revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
need(manifest.get("status") == "PASS_K8_FULL_TOP_SOURCE_PROFILE"
     and profile.get("status") == "PASS_K8_FULL_TOP_SOURCE_PROFILE", "K8 source/profile status")
need(profile.get("source_manifest_sha256") == manifest_sha and profile.get("source_tag") == tag
     and tag == "5e0e41b3", "K8 profile/manifest tag binding")
need(report.get("schema") == "k8-full-top-routed-implementation-v1"
     and report.get("status") == "PASS_ROUTED_TIMING_ROUTE_STATUS_DEFAULT_DRC_WARNINGS_ONLY",
     "existing implementation report is not PASS: " + str(report.get("status")))
source = report["source"]
need(source.get("git_revision") == revision
     and revision == "a61b96f0a60a2ccb1c8d13e99e113eb75ec097ba",
     "implementation report source revision differs from current K8 worktree")
need(source.get("profile_tag") == tag and source.get("manifest_sha256") == manifest_sha
     and source.get("files") == 185 and source.get("changed_files") == 14
     and source.get("parameters") == {"ATOMIC_C": 32, "ATOMIC_K": 8}
     and source.get("tracked_default_atomic_k") == 16, "implementation report K8 source binding")
need(report.get("bitstream_emitted") is False and report.get("hardware_accessed") is False
     and report.get("programmed") is False, "implementation report crossed offline boundary")

route = pkg / "impl-place"
checkpoint = route / "post_route_aggr.dcp"
need(Path(report["final_checkpoint"]["path"]).resolve() == checkpoint.resolve()
     and sha(checkpoint) == report["final_checkpoint"]["sha256"], "exact final routed checkpoint hash")
need(report["final_checkpoint"].get("design_state") == "Fully Routed", "final checkpoint is not fully routed")
need(Path(report["input_checkpoint"]["path"]).resolve() == (pkg / "impl-synth/post_opt.dcp").resolve()
     and sha(pkg / "impl-synth/post_opt.dcp") == report["input_checkpoint"]["sha256"],
     "implementation input checkpoint binding")
need(report["implementation_recipe"].get("all_stages_exit_0") is True
     and report["implementation_recipe"].get("completion_marker") ==
     "READY_FRESH_PLACE_ROUTE_CORRECTIVE_AND_FINAL_AUDIT", "implementation recipe completion gate")
for stage, path in report["implementation_recipe"]["stage_exit_files"].items():
    need(Path(path).read_text().strip() == "0", "implementation stage did not exit 0: " + stage)

timing = report["timing"]["global"]
need(report["timing"].get("all_user_specified_constraints_met") is True
     and timing.get("wns_ns", -1) >= 0 and timing.get("tns_ns", 0) == 0
     and timing.get("tns_failing") == 0 and timing.get("whs_ns", -1) >= 0
     and timing.get("ths_ns", 0) == 0 and timing.get("ths_failing") == 0
     and timing.get("wpws_ns", -1) >= 0 and timing.get("tpws_ns", 0) == 0
     and timing.get("tpws_failing") == 0, "accepted setup/hold/pulse timing gate")
need(report["routing"].get("fully_routed") is True
     and report["routing"].get("fully_routed_nets") == report["routing"].get("routable_nets")
     and report["routing"].get("routing_error_nets") == 0
     and report["routing"].get("final_audit_route_errors") == 0, "route status gate")
need(report["top_audit"] == {
    "top": "ypcb_ddr_dual_top", "part": "xc7k480tffg1156-2", "ports": 242,
    "waivers": 0, "blackboxes": 0, "config_voltage": 1.8, "cfgbvs": "GND",
    "bscan2_cells": 2, "capacity_owner_cells": 1, "startup_cells": 2,
}, "implementation top/configuration/structural audit")
check_timing = report["check_timing"]
need(check_timing.get("no_clock") == 0 and check_timing.get("constant_clock") == 0
     and check_timing.get("unconstrained_internal_endpoints") == 0
     and check_timing.get("combinational_loops") == 0,
     "implementation check_timing structural findings")
drc = report["drc"]
actual_report_drc = {row["rule"]: row["checks"] for row in drc["warnings_by_rule"]}
need(drc.get("ruledeck") == "default" and drc.get("checks_found") == sum(expected_drc.values())
     and drc.get("errors") == 0 and drc.get("critical_warnings") == 0
     and all(row.get("severity") == "Warning" for row in drc["warnings_by_rule"])
     and actual_report_drc == expected_drc, "implementation report DRC inventory")

artifact_paths = {}
for name, item in report["artifacts"].items():
    path = Path(item["path"]).resolve()
    need(path == (route / name).resolve() and path.is_file() and sha(path) == item["sha256"],
         "exact final-route report hash: " + name)
    artifact_paths[name] = path
need("All user specified timing constraints are met." in
     (route / "final_timing.rpt").read_text(), "final timing report constraint status")
for name in ("final_timing.rpt", "final_pulse_width.rpt", "final_check_timing.rpt"):
    need((route / name).is_file(), "missing final timing evidence: " + name)
final_drc = drc_inventory(route / "final_default_drc.rpt")
need(final_drc == expected_drc, "exact K8 final default DRC report")

script_hash_file = pkg / "implementation-script-sha256.txt"
scripts = {}
for line in script_hash_file.read_text().splitlines():
    digest, rel = line.split(None, 1)
    path = (root / rel).resolve()
    need(path.is_file() and sha(path) == digest, "implementation script hash: " + rel)
    scripts[str(path)] = digest
need(len(scripts) == 5, "unexpected implementation script inventory")

tool = subprocess.run(["vivado", "-version"], check=False, text=True, capture_output=True)
version_text = tool.stdout + tool.stderr
need(tool.returncode == 0 and "v2026.1" in version_text and "SW Build 6511674" in version_text,
     "Vivado version/build differs from routed implementation")
need(report["tool"].get("version") == "2026.1" and report["tool"].get("build") == "6511674",
     "implementation report Vivado version/build")

synthesis = json.loads(synthesis_path.read_text())
need(synthesis.get("status") == "PASS_K8_FULL_TOP_SYNTHESIS_RESOURCE_GATE",
     "K8 synthesis gate missing")
need(synthesis.get("source_manifest_sha256") == manifest_sha, "K8 synthesis manifest differs")

# Bind every selected source plus profile, synthesis/route checkpoint, report and script input.
input_hashes = {}
def bind(path):
    path = Path(path).resolve()
    need(path.is_file() and not path.is_symlink(), "missing input: " + str(path))
    input_hashes[str(path)] = sha(path)

for rel in manifest["files"]:
    bind(pkg / "source" / rel)
for path in (
    manifest_path, profile_path, pkg / "accepted-source-manifest.json",
    pkg / "accepted-source-profile.json", synthesis_path, pkg / "synth.tcl",
    pkg / "implementation-script-sha256.txt", pkg / "make_profile.py", pkg / "check_profile.py",
    pkg / "impl-synth/post_opt.dcp", checkpoint, report_source,
    pkg / "impl-place/final_utilization.rpt", pkg / "impl-place/final_io.rpt",
    pkg / "impl-place/final_clocks.rpt", pkg / "impl-place/initial_post_route.dcp",
    pkg / "impl-place/post_phys.dcp", pkg / "impl-place/post_route_corrective.dcp",
    pkg / "impl-place/place.log", pkg / "impl-place/route.log",
    pkg / "impl-place/corrective.log", pkg / "impl-place/final-audit.log",
    pkg / "impl-place/place.exit", pkg / "impl-place/route.exit",
    pkg / "impl-place/corrective.exit", pkg / "impl-place/final-audit.exit",
    pkg / "emit_sys.tcl", pkg / "audit_sys_bitfile.py", pkg / "run_emission.sh",
    script_hash_file,
    Path("/home/fedora/rknpu-fpga/build/full512-ddr-preparation/full512-bitfile-audit-v1/audit_image.py"),
    Path("/home/fedora/ypcb/local-overrides/projects-bonetto-soc/files/scripts/fedora-check-vivado-bitstream.py"),
):
    bind(path)
for name in report["artifacts"]:
    bind(route / name)

need(not run.exists(), "fresh emission directory already exists")
run.mkdir()
(run / "emission").mkdir()
(run / "route-evidence").mkdir()
(run / "source-evidence").mkdir()
staged = {}
def stage(source_path, relative):
    dest = run / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, dest)
    digest = sha(source_path)
    need(sha(dest) == digest, "staged input copy mismatch: " + str(dest))
    staged[str(dest.resolve())] = digest

stage(report_source, "implementation-report.json")
stage(checkpoint, "post_route_final.dcp")
stage(manifest_path, "source-evidence/source-manifest.json")
stage(profile_path, "source-evidence/source-profile.json")
stage(synthesis_path, "source-evidence/synthesis-report.json")
for name in report["artifacts"]:
    stage(route / name, "route-evidence/" + name)
for name in ("final_utilization.rpt", "final_io.rpt", "final_clocks.rpt"):
    stage(route / name, "route-evidence/" + name)
(run / "vivado-version.txt").write_text(version_text)
staged[str((run / "vivado-version.txt").resolve())] = sha(run / "vivado-version.txt")

prep = {
    "schema": "k8-full-top-image-emission-preparation-v1",
    "status": "PASS_K8_IMAGE_EMISSION_INPUTS_BOUND",
    "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source": {"git_revision": revision, "profile_tag": tag,
               "manifest_sha256": manifest_sha, "profile_sha256": profile_sha,
               "source_manifest_commit": manifest["source_commit"],
               "parameters": manifest["parameters"], "files": len(manifest["files"])},
    "tool": {"name": "Vivado", "version": "2026.1", "build": "6511674",
             "version_output": version_text.strip()},
    "implementation_report_path": str((run / "implementation-report.json").resolve()),
    "implementation_report_sha256": sha(run / "implementation-report.json"),
    "implementation_report_status": report["status"],
    "route_checkpoint_path": str(checkpoint.resolve()),
    "route_checkpoint_sha256": sha(checkpoint),
    "route_checkpoint_staged_path": str((run / "post_route_final.dcp").resolve()),
    "route_report_hashes": {name: sha(route / name) for name in report["artifacts"]},
    "default_drc_inventory": expected_drc,
    "timing": timing,
    "implementation_scripts": scripts,
    "profile_check_output": profile_check.stdout.strip(),
    "input_hashes": dict(sorted(input_hashes.items())),
    "staged_copy_hashes": dict(sorted(staged.items())),
    "hardware_accessed": False,
    "bitstream_emitted": False,
    "programmed": False,
    "flash_written": False,
}
with (run / "preparation.json").open("x") as stream:
    json.dump(prep, stream, indent=2, sort_keys=True)
    stream.write("\n")
print("PASS_K8_IMAGE_EMISSION_PREFLIGHT source_tag=" + tag)
print("ROUTE_CHECKPOINT_SHA256 " + prep["route_checkpoint_sha256"])
print("IMPLEMENTATION_REPORT_SHA256 " + prep["implementation_report_sha256"])
PY

cd "$RUN"
set +e
RK_K8_IMAGE_APPROVED=APPROVED RK_K8_IMAGE_TAG="$(python3 -c 'import json; print(json.load(open("preparation.json"))["source"]["profile_tag"])')" \
  vivado -mode batch -source "$PKG/emit_sys.tcl" \
  -log emission/emit.log -journal emission/emit.jou > emission/vivado.out 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > emission/emit.exit
if [[ "$rc" -ne 0 ]]; then
  echo "K8_EMISSION_FAILED rc=$rc"
  exit "$rc"
fi
grep -q '^PASS_K8_FULL_TOP_BITSTREAM_EMISSION_ONLY$' emission/emit.log || {
  echo "K8_EMISSION_MARKER_MISSING"
  exit 3
}
[[ ! -e emission-report.json ]] || { echo "STALE_EMISSION_REPORT"; exit 3; }

python3 - <<'PY'
from pathlib import Path
import datetime, hashlib, json, re

run = Path.cwd()
prep_path = run / "preparation.json"
prep = json.loads(prep_path.read_text())
def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
def need(condition, message):
    if not condition:
        raise SystemExit("FAIL_POST_EMISSION: " + message)

expected = prep["input_hashes"]
actual = {name: sha(name) for name in expected}
need(actual == expected, "an emission input changed while Vivado ran")
log = (run / "emission/emit.log").read_text()
out = (run / "emission/vivado.out").read_text()
markers = [line for line in log.splitlines()
           if line.strip() == "PASS_K8_FULL_TOP_BITSTREAM_EMISSION_ONLY"]
need(len(markers) == 1, "exact PASS marker line")
need(not re.search(r"^\s*(?:ERROR|CRITICAL WARNING)\s*:", log + "\n" + out, re.M | re.I),
     "Vivado emitted an ERROR or CRITICAL WARNING")
outputs = {}
for rel in (
    "emission/k8-full-top.bit", "emission/image.dcp", "emission/route_status.rpt",
    "emission/utilization.rpt", "emission/io.rpt", "emission/clocks.rpt",
    "emission/timing.rpt", "emission/check_timing.rpt", "emission/pulse_width.rpt",
    "emission/default_drc.rpt", "emission/bitstream_drc.rpt",
):
    path = run / rel
    need(path.is_file(), "missing emitted artifact " + rel)
    outputs[rel] = sha(path)
need((run / "emission/k8-full-top.bit").stat().st_size > 0, "empty bitstream")
for rel in ("emission/default_drc.rpt", "emission/bitstream_drc.rpt"):
    need("Checks found: 1054" in (run / rel).read_text(), "unexpected emission DRC total: " + rel)

report = {
    "schema": "k8-full-top-bitstream-emission-v1",
    "status": "PASS_K8_FULL_TOP_BITSTREAM_EMISSION_ONLY",
    "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "returncode": 0,
    "preparation_sha256": sha(prep_path),
    "source": prep["source"],
    "source_tag": prep["source"]["profile_tag"],
    "source_manifest_sha256": prep["source"]["manifest_sha256"],
    "implementation_report_sha256": prep["implementation_report_sha256"],
    "implementation_report_status": prep["implementation_report_status"],
    "route_checkpoint_path": prep["route_checkpoint_path"],
    "route_checkpoint_sha256": prep["route_checkpoint_sha256"],
    "route_report_hashes": prep["route_report_hashes"],
    "tool": prep["tool"],
    "input_hashes_expected": expected,
    "input_hashes_before": expected,
    "input_hashes_after": actual,
    "output_hashes": outputs,
    "bitstream_path": str((run / "emission/k8-full-top.bit").resolve()),
    "bitstream_sha256": outputs["emission/k8-full-top.bit"],
    "bitstream_bytes": (run / "emission/k8-full-top.bit").stat().st_size,
    "image_dcp_path": str((run / "emission/image.dcp").resolve()),
    "image_dcp_sha256": outputs["emission/image.dcp"],
    "emit_log_sha256": sha(run / "emission/emit.log"),
    "vivado_stdout_sha256": sha(run / "emission/vivado.out"),
    "vivado_journal_sha256": sha(run / "emission/emit.jou"),
    "hardware_accessed": False,
    "hardware_programmed": False,
    "flash_written": False,
    "bitstream_emitted": True,
    "crc": "NOT_CHECKED",
    "programming": "NOT_RUN",
    "physical_hardware": "NOT_RUN",
    "scope": "Offline bitstream emission from the exact accepted K8 routed checkpoint; no CRC software validation, programming, board access or flash.",
}
with (run / "emission-report.json").open("x") as stream:
    json.dump(report, stream, indent=2, sort_keys=True)
    stream.write("\n")
print("PASS_K8_FULL_TOP_BITSTREAM_EMISSION_ONLY")
PY
