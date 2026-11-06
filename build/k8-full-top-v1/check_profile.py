#!/usr/bin/env python3
"""Static check for the build-local C32/K8 full-top source profile.

Checks every one of the 185 bound source hashes, the accepted-profile delta,
tracked-repository origins, the ATOMIC_C/ATOMIC_K pass-through chain and the
unchanged tracked K16 defaults. No Vivado, place/route, bitstream or hardware.
"""
from pathlib import Path
import hashlib, json, re, sys

ROOT = Path(__file__).resolve().parents[2]
PKG = Path(__file__).resolve().parent
SRC = PKG / "source"
ACC = json.loads((PKG / "accepted-source-manifest.json").read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def need(condition, message):
    if not condition:
        raise SystemExit("FAIL: " + message)


def text(rel):
    return (SRC / rel).read_text()


def repo(rel):
    return (ROOT / rel).read_text()


def require_atomic_default(source, name, value):
    need(re.search(r"ATOMIC_%s\s*=\s*%d\b" % (name, value), source),
         "missing ATOMIC_%s=%d default" % (name, value))


def main():
    m = json.loads((PKG / "source-manifest.json").read_text())
    need(m["schema"] == "k8-full-top-source-manifest-v1", "manifest schema")
    need(m["status"] == "PASS_K8_FULL_TOP_SOURCE_PROFILE", "manifest status")
    need(m["file_count"] == len(m["files"]) == 185, "file count")
    need(set(m["files"]) == set(ACC["files"]), "selection path set changed")
    need(m["top"] == "ypcb_ddr_dual_top", "top")
    need(m["part"] == "xc7k480tffg1156-2", "part")
    need(m["port_count"] == 242, "port count")
    need(m["parameters"] == {
        "ATOMIC_C": 32, "ATOMIC_K": 8,
        "tracked_default_ATOMIC_C": 32, "tracked_default_ATOMIC_K": 16,
    }, "profile parameters")
    for rel, digest in m["files"].items():
        path = SRC / rel
        need(path.is_file() and not path.is_symlink(), "missing or linked " + rel)
        need(sha(path) == digest, "file hash " + rel)

    computed_changed = [rel for rel in ACC["files"] if m["files"][rel] != ACC["files"][rel]]
    need(m["changed_from_accepted"] == computed_changed, "changed set vs accepted 185")
    need(len(computed_changed) == 14, "expected 14 changed files")
    need(set(m["timing_repair_files"]) == {
        "hdl/110/rk_mig_ecc_monitor.sv", "hdl/152/rk_ddr_capacity_owner.sv",
    }, "timing-repair files")

    for rel, origin in m["repo_origins"].items():
        need(sha(SRC / rel) == sha(ROOT / origin), "repo origin mismatch " + rel)
    for rel, edit in m["build_local_edits"].items():
        need(m["files"][rel] != edit["accepted_sha256"], "build-local edit not rebased " + rel)
        body = text(rel)
        for token in edit["required_tokens"]:
            need(token in body, "missing build-local token %r in %s" % (token, rel))

    # Build-local K8 selector and pass-through, starting at the accepted top.
    top = text("hdl/120/top.sv")
    need(re.search(r"parameter\s+int\s+unsigned\s+ATOMIC_C\s*=\s*32", top), "top ATOMIC_C")
    need(re.search(r"parameter\s+int\s+unsigned\s+ATOMIC_K\s*=\s*8", top), "top ATOMIC_K=8")
    need(".ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) platform(" in top, "top -> platform")
    platform = text("hdl/117/platform.sv")
    need(".ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) endpoint (" in platform, "platform -> endpoint")
    endpoint = text("hdl/150/rk_jtag_dual_ddr_async.sv")
    need(".SYNC_STAGES(SYNC_STAGES),.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) engine (" in endpoint,
         "endpoint -> layout dispatch")
    layout = text("hdl/framework/01_rk_layout_compute_dispatch.sv")
    need(".ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)," in layout, "layout -> dual dispatch")
    dual = text("hdl/148/rk_dual_async_dispatch.sv")
    need(".ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)," in dual, "dual -> cmac async")
    async_engine = text("hdl/147/rk_cmac_async_engine.sv")
    need(".ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)," in async_engine, "async -> success rearm")
    rearm = text("hdl/146/rk_cmac_success_rearm.sv")
    need(".ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)," in rearm, "rearm -> DMA")
    for rel in ("hdl/143/rk_cmac_array_dma.sv", "hdl/142/rk_cmac_array_core.sv",
                "hdl/139/rk_cmac_array_datapath.sv", "hdl/140/rk_cmac_array_front.sv"):
        require_atomic_default(text(rel), "C", 32)
        require_atomic_default(text(rel), "K", 16)
    require_atomic_default(text("hdl/138/rk_cmac_frame_output.sv"), "K", 16)

    # Every tracked K16 default in the modified hierarchy remains 16.
    tracked = [
        "rtl/ddr/framework/rk_cmac_async_engine.sv",
        "rtl/ddr/framework/rk_dual_async_dispatch.sv",
        "rtl/ddr/framework/rk_layout_compute_dispatch.sv",
        "rtl/ddr/framework/rk_jtag_dual_ddr_async.sv",
        "rtl/ddr/framework_factored/rk_cmac_async_engine.sv",
        "rtl/ddr/framework_factored/rk_dual_async_dispatch.sv",
        "rtl/ddr/framework_factored/rk_layout_compute_dispatch.sv",
        "rtl/ddr/framework_factored/rk_jtag_dual_ddr_async.sv",
        "rtl/tinystories/rk_cmac_success_rearm.sv",
        "rtl/cmac/rk_cmac_array_dma.sv",
        "rtl/cmac/rk_cmac_array_core.sv",
        "rtl/cmac/rk_cmac_array_datapath.sv",
        "rtl/cmac/rk_cmac_array_front.sv",
        "rtl/cmac/rk_cmac_frame_output.sv",
    ]
    for rel in tracked:
        body = repo(rel)
        need(re.search(r"ATOMIC_K\s*=\s*16\b", body), "tracked K16 default lost: " + rel)
        need(not re.search(r"ATOMIC_K\s*=\s*8\b", body), "tracked K8 override: " + rel)
        if "ATOMIC_C" in body:
            require_atomic_default(body, "C", 32)
        require_atomic_default(body, "K", 16)

    # The source-tree arithmetic array and writer remain K16-default modules;
    # only the build-local top selects 8.
    for rel in ("hdl/134/rk_cmac_cacc_fp16_array.sv", "hdl/145/rk_cmac_fp16_array_dsp_prefix_pipe.sv"):
        need(re.search(r"ATOMIC_K\s*=\s*16\b", text(rel)), "source-tree K16 default lost: " + rel)
    need(re.search(r"ATOMIC_C\s*=\s*32\b", text("hdl/144/rk_cmac_fp16_cell_dsp_prefix_pipe.sv")),
         "source-tree C32 cell default lost")

    # The synthesis recipe must read exactly this source selection, select the
    # K8 structural census and retain the accepted 298,600-LUT gate.
    synth = (PKG / "synth.tcl").read_text()
    listed = set(re.findall(r"\{" + re.escape(str(SRC)) + r"/([^\}]+)\}", synth))
    hdl = {rel for rel in m["files"] if rel.endswith((".sv", ".v"))}
    need(hdl.issubset(listed), "synth.tcl source list omits profile HDL")
    need(len(listed) == len(hdl) + 10, "synth.tcl has unexpected extra profile files")
    need(str(SRC / "mig-original.xdc") in synth and str(SRC / "board.xdc") in synth,
         "synth.tcl missing profile XDC")
    need("set expected_kernels 8" in synth and "set expected_product_dsps 256" in synth,
         "synth.tcl K8 structural census")
    need("set expected_fixed_aux_dsps 4" in synth and "set expected_front_aux_dsps_max 3" in synth,
         "synth.tcl K8 auxiliary DSP model")
    need("cap_check_total_luts [file join $out post_opt_utilization.rpt] 298600" in synth,
         "synth.tcl capacity gate changed")

    print("PASS_K8_FULL_TOP_SOURCE_PROFILE files=185 changed=14 top=ypcb_ddr_dual_top "
          "atomic_c=32 atomic_k=8 tracked_default_k=16")
    print("SOURCE_MANIFEST_SHA256 " + sha(PKG / "source-manifest.json"))
    print("SOURCE_TAG " + sha(PKG / "source-manifest.json")[:8])


if __name__ == "__main__":
    main()
