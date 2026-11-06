#!/usr/bin/env python3
"""Read-only K8 bitfile/container/source/DRC audit; never accesses hardware."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import re

PKG = Path(__file__).resolve().parent
RUN = PKG / "emission-run-k8-v1"
OUT = RUN / "emission"
BIT = OUT / "k8-full-top.bit"
AUDIT_LIB = Path("/home/fedora/rknpu-fpga/build/full512-ddr-preparation/full512-bitfile-audit-v1/audit_image.py")
AUDIT_LIB_SHA256 = "4c5f33e9cfc94f16e058928d7f4cdaeddef84f440e09f126191a61fe46801472"
CHECKER_SHA256 = "480f6a4bd7ee7e5e7f6c9eee5750a3f1e223f52a4f87cb694afade7d0558f756"
EXPECTED_DRC = {"DPIP-1": 526, "DPOP-1": 263, "DPOP-2": 263, "REQP-1709": 2}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def need(ok, message):
    if not ok:
        raise SystemExit("FAIL: " + message)


def verify_map(expected):
    for name, digest in expected.items():
        path = Path(name)
        need(path.is_file() and not path.is_symlink(), "missing or linked bound input: " + name)
        need(sha(path) == digest, "changed bound input: " + name)


def drc_inventory(path):
    text = Path(path).read_text()
    totals = re.findall(r"Checks found:\s*(\d+)", text)
    need(len(totals) == 1 and int(totals[0]) == sum(EXPECTED_DRC.values()),
         "missing or changed K8 DRC total")
    actual = {}
    for line in text.splitlines():
        columns = [field.strip() for field in line.strip().strip("|").split("|")]
        if len(columns) != 4 or not re.fullmatch(r"[A-Z][A-Z0-9_-]*-[0-9]+", columns[0]):
            continue
        rule, severity, _description, count = columns
        need(rule not in actual and severity == "Warning" and count.isdigit(),
             "duplicate rule or unreviewed DRC severity/count")
        actual[rule] = int(count)
    need(actual == EXPECTED_DRC, "default/bitstream-check DRC inventory changed")
    return actual


def main():
    prep_path = RUN / "preparation.json"
    emission_path = RUN / "emission-report.json"
    audit_path = RUN / "bitfile-audit.json"
    need(not audit_path.exists(), "fresh bitfile-audit.json required")
    need(prep_path.is_file() and emission_path.is_file(), "missing emission preparation/report")
    prep_sha, emission_sha = sha(prep_path), sha(emission_path)
    prep, emission = json.loads(prep_path.read_text()), json.loads(emission_path.read_text())
    need(emission.get("status") == "PASS_K8_FULL_TOP_BITSTREAM_EMISSION_ONLY"
         and emission.get("returncode") == 0 and emission.get("bitstream_emitted") is True,
         "emitter did not complete successfully")
    need(emission.get("preparation_sha256") == prep_sha, "preparation report hash differs")
    need(all(emission.get(key) is False for key in
             ("hardware_accessed", "hardware_programmed", "flash_written")),
         "emitter crossed the offline boundary")
    need(emission.get("crc") == "NOT_CHECKED"
         and emission.get("programming") == "NOT_RUN"
         and emission.get("physical_hardware") == "NOT_RUN",
         "emission report scope changed")

    expected = prep["input_hashes"]
    need(emission["input_hashes_expected"] == expected
         and emission["input_hashes_before"] == expected
         and emission["input_hashes_after"] == expected,
         "emitter input hash maps differ")
    verify_map(expected)
    verify_map(prep["staged_copy_hashes"])

    manifest_path = PKG / "source-manifest.json"
    profile_path = PKG / "source-profile.json"
    manifest_sha = sha(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    profile = json.loads(profile_path.read_text())
    tag = manifest_sha[:8]
    need(tag == "5e0e41b3" and profile["source_tag"] == tag
         and profile["source_manifest_sha256"] == manifest_sha,
         "K8 source/profile tag mismatch")
    need(emission["source_tag"] == tag and emission["source_manifest_sha256"] == manifest_sha,
         "emitted image source tag mismatch")
    need(emission["route_checkpoint_sha256"] == prep["route_checkpoint_sha256"],
         "route checkpoint binding differs")
    need(sha(RUN / "post_route_final.dcp") == prep["route_checkpoint_sha256"],
         "staged routed checkpoint changed")

    bit_sha = sha(BIT)
    need(BIT.is_file() and bit_sha == emission["bitstream_sha256"]
         and BIT.stat().st_size == emission["bitstream_bytes"], "bitstream identity differs")
    image_dcp = OUT / "image.dcp"
    need(image_dcp.is_file() and sha(image_dcp) == emission["image_dcp_sha256"],
         "emitted image checkpoint identity differs")
    need((OUT / "emit.log").is_file(), "missing emission log")
    marker_lines = [line for line in (OUT / "emit.log").read_text().splitlines()
                    if line.strip() == "PASS_K8_FULL_TOP_BITSTREAM_EMISSION_ONLY"]
    need(len(marker_lines) == 1, "missing exact emission marker line")

    for path in (OUT / "default_drc.rpt", OUT / "bitstream_drc.rpt"):
        drc_inventory(path)

    need(sha(AUDIT_LIB) == AUDIT_LIB_SHA256, "reviewed bitfile audit library changed")
    spec = importlib.util.spec_from_file_location("k8_bitfile_audit_reference", AUDIT_LIB)
    need(spec is not None and spec.loader is not None, "cannot load reviewed audit library")
    lib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lib)
    need(lib.CHECKER_SHA == CHECKER_SHA256, "reviewed checker pin differs")
    checker = lib.load_checker()
    checked = checker.check(BIT, bit_sha)
    need(checked.get("status") == "PASS", "independent container checker failed")
    need(checked.get("crc") == "NOT_CHECKED", "CRC was incorrectly claimed checked")
    need(checked.get("programming") == "NOT_RUN"
         and checked.get("physical_hardware") == "NOT_RUN", "audit exceeded read-only scope")
    packets = lib.packet_inventory(BIT.read_bytes(), checked["structure"], tag)
    need(packets.get("crc_software_validation") == "NOT_CHECKED", "packet audit claimed CRC validation")

    report = {
        "schema": "k8-full-top-bitfile-audit-v1",
        "status": "PASS_K8_FULL_TOP_BITFILE_CONTAINER_SOURCE_DRC_AUDIT",
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_commit_at_emission": prep["source"]["git_revision"],
        "source_manifest_sha256": manifest_sha,
        "source_tag": tag,
        "implementation_report_sha256": prep["implementation_report_sha256"],
        "route_checkpoint_path": prep["route_checkpoint_path"],
        "route_checkpoint_sha256": prep["route_checkpoint_sha256"],
        "route_report_hashes": prep["route_report_hashes"],
        "bitstream_path": str(BIT.resolve()),
        "bitstream_sha256": bit_sha,
        "bitstream_bytes": BIT.stat().st_size,
        "image_dcp_path": str(image_dcp.resolve()),
        "image_dcp_sha256": sha(image_dcp),
        "checker_library_sha256": AUDIT_LIB_SHA256,
        "checker_source_sha256": CHECKER_SHA256,
        "auditor_source_sha256": sha(__file__),
        "checker": checked,
        "packets": packets,
        "default_drc": drc_inventory(OUT / "default_drc.rpt"),
        "bitstream_check_drc": drc_inventory(OUT / "bitstream_drc.rpt"),
        "crc": "NOT_CHECKED",
        "programming": "NOT_RUN",
        "physical_hardware": "NOT_RUN",
        "hardware_accessed": False,
        "hardware_programmed": False,
        "flash_written": False,
        "scope": "Read-only K8 source/profile, route/checkpoint, bitfile container/IDCODE/USR_ACCESS packet and exact DRC audit; software CRC validation, programming and physical execution are not qualified.",
    }
    with audit_path.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in
                      ("status", "source_tag", "bitstream_sha256", "bitstream_bytes", "image_dcp_sha256")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
