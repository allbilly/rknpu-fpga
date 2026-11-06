#!/usr/bin/env python3
"""Summarize the build-local K8 full-top synthesis result. No place/route."""
from pathlib import Path
import datetime, hashlib, json, re, sys

PKG = Path(__file__).resolve().parent
LOG = PKG / "impl-synth" / "synth.log"
UTIL = PKG / "impl-synth" / "post_opt_utilization.rpt"
MANIFEST = PKG / "source-manifest.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    log = LOG.read_text()
    facts = (PKG / "impl-synth" / "constrained_synthesis_facts.tsv").read_text()
    match = re.search(r"^\| ypcb_ddr_dual_top\s+\|.*?\|\s+(\d+)\s+\|\s+(\d+)\s+\|\s+(\d+)\s+\|\s+(\d+)\s+\|\s+(\d+)\s+\|\s+(\d+)\s+\|\s+(\d+)\s+\|\s+(\d+)\s+\|\s*$",
                      UTIL.read_text(), re.M)
    if not match:
        raise SystemExit("missing top utilization row")
    total_luts, logic_luts, lutram, srl, ff, ramb36, ramb18, dsp = map(int, match.groups())
    gate = re.search(r"^CAPACITY_RESOURCE_GATE stage=post_opt total_luts=(\d+) limit=(\d+)$", log, re.M)
    if not gate:
        raise SystemExit("missing capacity gate line")
    gate_luts, limit = map(int, gate.groups())
    if gate_luts != total_luts:
        raise SystemExit("gate/utilization LUT mismatch")
    census = re.findall(r"^CENSUS\s+(\S+).*?KERNELS\s+(\d+)\s+PRODUCT_DSPS\s+(\d+)"
                        r"\s+TOTAL_DSPS\s+(\d+)\s+AUXILIARY_DSPS\s+(\d+)"
                        r"\s+FRONT_AUX_DSPS\s+(\d+)\s+SCALAR_PORTS\s+(\d+)", facts, re.M)
    report = {
        "schema": "k8-full-top-synthesis-v1",
        "status": "PASS_K8_FULL_TOP_SYNTHESIS_RESOURCE_GATE" if gate_luts <= limit else
                  "FAIL_K8_FULL_TOP_SYNTHESIS_RESOURCE_GATE",
        "scope": "Constrained post-opt synthesis only; no place/route, bitstream, board or hardware claim.",
        "top": "ypcb_ddr_dual_top",
        "part": "xc7k480tffg1156-2",
        "parameters": {"ATOMIC_C": 32, "ATOMIC_K": 8},
        "source_manifest_sha256": sha(MANIFEST),
        "source_tag": sha(MANIFEST)[:8],
        "synthesis_script_sha256": sha(PKG / "synth.tcl"),
        "synthesis_log_sha256": sha(LOG),
        "utilization_report_sha256": sha(UTIL),
        "resources": {
            "total_luts": total_luts, "logic_luts": logic_luts, "lutram": lutram,
            "srl": srl, "ff": ff, "ramb36": ramb36, "ramb18": ramb18, "dsp": dsp,
        },
        "resource_gate_total_luts": limit,
        "resource_gate_margin": limit - gate_luts,
        "census": [
            {key: (value if key == "stage" else int(value))
             for key, value in zip(("stage", "kernels", "product_dsps", "total_dsps",
                                    "auxiliary_dsps", "front_aux_dsps", "scalar_ports"), row)}
            for row in census
        ],
        "tool": re.search(r"^SHARED_DATA_CONSTRAINED_NATIVE_TOOL (\S+)$", log, re.M).group(1),
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "hardware_accessed": False,
        "place_route_executed": False,
        "bitstream_emitted": False,
    }
    (PKG / "synthesis-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
