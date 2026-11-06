#!/usr/bin/env python3
"""Rebuild the build-local C32/K8 full-top source profile. No Vivado/hardware.

The profile is derived from the accepted 185-file FDIV/MAX first-die source
snapshot, with only the K8/timing-repair files replaced and the build-local
top/platform parameter patch applied. Tracked RTL defaults remain C32/K16.
"""
from pathlib import Path
import hashlib, json, subprocess, sys

ROOT = Path(__file__).resolve().parents[2]
PKG = Path(__file__).resolve().parent
SRC = PKG / "source"
ACC = json.loads((PKG / "accepted-source-manifest.json").read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


REPO_ORIGINS = {
    "hdl/110/rk_mig_ecc_monitor.sv": "rtl/ddr/rk_mig_ecc_monitor.sv",
    "hdl/138/rk_cmac_frame_output.sv": "rtl/cmac/rk_cmac_frame_output.sv",
    "hdl/139/rk_cmac_array_datapath.sv": "rtl/cmac/rk_cmac_array_datapath.sv",
    "hdl/140/rk_cmac_array_front.sv": "rtl/cmac/rk_cmac_array_front.sv",
    "hdl/142/rk_cmac_array_core.sv": "rtl/cmac/rk_cmac_array_core.sv",
    "hdl/143/rk_cmac_array_dma.sv": "rtl/cmac/rk_cmac_array_dma.sv",
    "hdl/146/rk_cmac_success_rearm.sv": "rtl/tinystories/rk_cmac_success_rearm.sv",
    "hdl/147/rk_cmac_async_engine.sv": "rtl/ddr/framework_factored/rk_cmac_async_engine.sv",
    "hdl/148/rk_dual_async_dispatch.sv": "rtl/ddr/framework_factored/rk_dual_async_dispatch.sv",
    "hdl/152/rk_ddr_capacity_owner.sv": "rtl/ddr/capacity/rk_ddr_capacity_owner.sv",
    "hdl/framework/01_rk_layout_compute_dispatch.sv":
        "rtl/ddr/framework_factored/rk_layout_compute_dispatch.sv",
}

BUILD_LOCAL_EDITS = {
    "hdl/120/top.sv": {
        "accepted_sha256": ACC["files"]["hdl/120/top.sv"],
        "purpose": "K8 profile default; forward ATOMIC_C/ATOMIC_K to the platform",
        "required_tokens": [
            "parameter int unsigned ATOMIC_C=32",
            "parameter int unsigned ATOMIC_K=8",
            ".ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) platform(",
        ],
    },
    "hdl/117/platform.sv": {
        "accepted_sha256": ACC["files"]["hdl/117/platform.sv"],
        "purpose": "forward ATOMIC_C/ATOMIC_K to the endpoint",
        "required_tokens": [
            "parameter int unsigned ATOMIC_C = 32",
            "parameter int unsigned ATOMIC_K = 16",
            ".ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) endpoint (",
        ],
    },
    "hdl/150/rk_jtag_dual_ddr_async.sv": {
        "accepted_sha256": ACC["files"]["hdl/150/rk_jtag_dual_ddr_async.sv"],
        "purpose": "forward ATOMIC_C/ATOMIC_K to the layout/compute dispatcher",
        "required_tokens": [
            "parameter int unsigned ATOMIC_C = 32",
            "parameter int unsigned ATOMIC_K = 16",
            ".SYNC_STAGES(SYNC_STAGES),.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) engine (",
        ],
    },
}


def main():
    files = {}
    for rel in ACC["files"]:
        path = SRC / rel
        if not path.is_file() or path.is_symlink():
            raise SystemExit("missing or linked source: " + rel)
        files[rel] = sha(path)
    changed = [rel for rel in ACC["files"] if files[rel] != ACC["files"][rel]]
    expected = sorted(set(REPO_ORIGINS) | set(BUILD_LOCAL_EDITS))
    if sorted(changed) != expected:
        raise SystemExit("unexpected changed set: " + repr(sorted(set(changed) ^ set(expected))))
    for rel, origin in REPO_ORIGINS.items():
        if files[rel] != sha(ROOT / origin):
            raise SystemExit(f"source tree {rel} does not match {origin}")

    commit = git("rev-parse", "HEAD")
    # Only RTL bytes feed this profile. Untracked build evidence and the
    # accompanying note do not make the selected source snapshot dirty.
    dirty = git("status", "--porcelain", "--", "rtl")
    manifest = {
        "schema": "k8-full-top-source-manifest-v1",
        "status": "PASS_K8_FULL_TOP_SOURCE_PROFILE",
        "scope": "Static source binding and parameter selection only. "
                 "Fresh synthesis is a separate gate; no place/route, bitstream, board or hardware claim.",
        "source_commit": commit,
        "source_commit_subject": git("log", "-1", "--format=%s"),
        "source_commit_base": "a9b5d028e9212776223df4b24cfabfde688f29db",
        "timing_repair_commit": "3707873549b9bc97900f8ba559ee202e575e0021",
        "worktree_dirty_at_generation": bool(dirty),
        "worktree_dirty_paths": dirty.splitlines(),
        "derived_from": {
            "profile": "build/fdv-max-image-v1/source-profile.json",
            "profile_sha256": sha(PKG / "accepted-source-profile.json"),
            "source_manifest": "build/fdv-max-image-v1/source-manifest.json",
            "source_manifest_sha256": sha(PKG / "accepted-source-manifest.json"),
            "file_count": 185,
            "source_commit": "58c0e7f50bdcb54dc7c7db733507c4d1575a019f",
        },
        "top": "ypcb_ddr_dual_top",
        "part": "xc7k480tffg1156-2",
        "port_count": 242,
        "precision": "FP16",
        "parameters": {
            "ATOMIC_C": 32,
            "ATOMIC_K": 8,
            "tracked_default_ATOMIC_C": 32,
            "tracked_default_ATOMIC_K": 16,
        },
        "file_count": 185,
        "changed_from_accepted": changed,
        "repo_origins": REPO_ORIGINS,
        "build_local_edits": BUILD_LOCAL_EDITS,
        "timing_repair_files": [
            "hdl/110/rk_mig_ecc_monitor.sv",
            "hdl/152/rk_ddr_capacity_owner.sv",
        ],
        "k8_parameter_files": [
            "hdl/117/platform.sv",
            "hdl/120/top.sv",
            "hdl/138/rk_cmac_frame_output.sv",
            "hdl/139/rk_cmac_array_datapath.sv",
            "hdl/140/rk_cmac_array_front.sv",
            "hdl/142/rk_cmac_array_core.sv",
            "hdl/143/rk_cmac_array_dma.sv",
            "hdl/146/rk_cmac_success_rearm.sv",
            "hdl/147/rk_cmac_async_engine.sv",
            "hdl/148/rk_dual_async_dispatch.sv",
            "hdl/150/rk_jtag_dual_ddr_async.sv",
            "hdl/framework/01_rk_layout_compute_dispatch.sv",
        ],
        "files": files,
    }
    manifest_path = PKG / "source-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    profile = {
        "schema": "k8-full-top-source-profile-v1",
        "status": "PASS_K8_FULL_TOP_SOURCE_PROFILE",
        "source_manifest_path": str(manifest_path),
        "source_manifest_sha256": sha(manifest_path),
        "source_tag": sha(manifest_path)[:8],
        "file_count": len(files),
        "changed_from_accepted": len(changed),
        "top": manifest["top"],
        "part": manifest["part"],
        "port_count": manifest["port_count"],
        "parameters": manifest["parameters"],
        "source_commit": commit,
        "source_commit_base": manifest["source_commit_base"],
        "timing_repair_commit": manifest["timing_repair_commit"],
        "derived_from": manifest["derived_from"],
        "hardware_accessed": False,
        "scope": manifest["scope"],
    }
    (PKG / "source-profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    print("PASS_K8_FULL_TOP_SOURCE_PROFILE files=%d changed=%d top=%s SOURCE_TAG %s" %
          (len(files), len(changed), manifest["top"], profile["source_tag"]))


if __name__ == "__main__":
    main()
