#!/usr/bin/env python3
"""Run the captured C8/H5/W5/OC8 raw-command convolution in both simulators."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/conv/fixtures/conv_1x1_valid_c8_h5_w5_oc8"
CASE = "conv_1x1_valid_c8_h5_w5_oc8"
SEED = 0xC08C8A25
EXPECTED = {
    "a.bin": (800, "fa1cfc610a9d473bbef852dac62bef6d63f67727b0d8a20587962b0418739c71"),
    "w.bin": (256, "52a1b39b6ef32d87bed51b67d32b67073f2aefae3fc96d265a0a82b6ba838418"),
    "expected.bin": (400, "7a364a2c20910f0b00f4f522856009ed69d5a477ea4b9fdee5ac146193d2058c"),
    "regcmd.bin": (432, "d2436a39835aac6c926b6ab0ed608a30b46f71616dbc0c8b56390b0cbbe51328"),
    "out.bin": (1600, "82f8bdb91b780e54f6d90b1ea4281d01913f7561d688f0e5a75df89b5f604f0e"),
}
DONOR = ROOT / "rtl/vendor/nvdla"

RTL = [
    "compat/nv_assert_never.v",
    "compat/nv_assert_no_x.v",
    "NV_DW_lsd.v",
    "NV_DW02_tree.v",
    "NV_NVDLA_CMAC_CORE_MAC_mul.v",
    "NV_NVDLA_CACC_CALC_fp_48b.v",
    "HLS_fp32_to_fp16.v",
]
RTL += [
    "rtl/cmac/rk_cmac_fp16_cell.sv",
    "rtl/cmac/rk_cmac_fp16_array.sv",
    "rtl/cmac/rk_nvdla_cacc.sv",
    "rtl/cmac/rk_cacc_fp16_array.sv",
    "rtl/cmac/rk_cmac_cacc_fp16_array.sv",
    "rtl/cmac/rk_nvdla_fp32_to_fp16.sv",
    "rtl/cmac/rk_cmac_writer.sv",
    "rtl/cmac/rk_cmac_output_nvdla.sv",
    "rtl/cmac/rk_cmac_frame_output.sv",
    "rtl/cmac/rk_cmac_rw_arbiter.sv",
    "rtl/cmac/rk_conv_profile.sv",
    "rtl/cmac/rk_conv_array_front.sv",
    "rtl/cmac/rk_conv_output_atom.sv",
    "rtl/cmac/rk_conv_array_core.sv",
    "tests/conv/tb_conv_array_core.sv",
]
RUNNER = "tools/conv/test_first_case.py"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(command: list[str], cwd: Path, log: Path, timeout: int = 180) -> str:
    started = time.monotonic()
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    log.write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n"
                           f"see {log}\n{result.stdout[-5000:]}")
    return result.stdout


def fixture_hex(directory: Path) -> None:
    for name, width, count in (("a.bin", 4, 400), ("w.bin", 4, 128),
                               ("out.bin", 4, 800), ("expected.bin", 4, 200)):
        words = struct.unpack(f"<{count}H", (FIXTURE / name).read_bytes())
        (directory / {"a.bin": "input.hex", "w.bin": "weight.hex",
                      "out.bin": "output.hex", "expected.bin": "expected.hex"}[name]
         ).write_text("".join(f"{word:0{width}x}\n" for word in words))
    commands = struct.unpack("<54Q", (FIXTURE / "regcmd.bin").read_bytes())
    (directory / "commands.hex").write_text("".join(f"{word:016x}\n" for word in commands))


def source_manifest() -> list[dict[str, str]]:
    result = []
    for relative in RTL:
        path = DONOR / relative if relative.startswith("compat/") or relative.startswith("NV_") or relative.startswith("HLS_") else ROOT / relative
        payload = path.read_bytes()
        result.append({"path": str(path.relative_to(ROOT)), "sha256": sha256(payload)})
    for name, (size, digest) in EXPECTED.items():
        payload = (FIXTURE / name).read_bytes()
        if len(payload) != size or sha256(payload) != digest:
            raise RuntimeError(f"fixture mismatch: {name}")
        result.append({"path": str((FIXTURE / name).relative_to(ROOT)), "sha256": digest})
    runner = ROOT / RUNNER
    result.append({"path": RUNNER, "sha256": sha256(runner.read_bytes())})
    return result


def expected_result(mode: int) -> str:
    if mode == 0:
        return ("PASS CONV_C8_H5_W5_OC8 mode=0 seed=c08c8a25 "
                "commands=54 reads=264 writes=200")
    reads, writes = (1, 0) if mode in (9, 10) else (0, 0)
    commands = {1: 8, 2: 6, 3: 53, 5: 22, 7: 9}.get(mode, 54)
    return (f"PASS CONV_C8_H5_W5_OC8 mode={mode} seed=c08c8a25 "
            f"commands={commands} reads={reads} writes={writes}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulator", choices=("all", "iverilog", "verilator"), default="all")
    args = parser.parse_args()
    out = ROOT / "build/convolution-first-case"
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "RUNNING",
        "case": CASE,
        "scope": "one captured FP16 valid 1x1 C8/H5/W5/OC8 task; raw 54 QWORD stream plus source task-boundary sideband; no board, full-top or bitstream",
        "base_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "seed": f"0x{SEED:08x}",
        "fixture_sha256": {name: digest for name, (_, digest) in EXPECTED.items()},
        "source": source_manifest(),
        "runs": [],
    }
    selected = ("iverilog", "verilator") if args.simulator == "all" else (args.simulator,)
    modes = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
    try:
        for simulator in selected:
            run_dir = out / f"{simulator}-{time.time_ns()}"
            run_dir.mkdir(parents=True, exist_ok=False)
            data_dir = run_dir / "fixture-hex"
            data_dir.mkdir()
            fixture_hex(data_dir)
            version_flag = "-V" if simulator == "iverilog" else "--version"
            version_output = run([simulator, version_flag], ROOT, run_dir / "version.log", 30)
            report_run = {"simulator": simulator, "version": version_output.splitlines()[0], "cases": []}
            sources = [str(DONOR / relative) if relative.startswith("compat/") or
                       relative.startswith("NV_") or relative.startswith("HLS_") else str(ROOT / relative)
                       for relative in RTL]
            if simulator == "iverilog":
                binary = run_dir / "sim_conv"
                command = ["iverilog", "-g2012", "-DDESIGNWARE_NOEXIST", "-DASSERT_ON",
                           f"-I{DONOR}", "-s", "tb_conv_array_core", "-o", str(binary), *sources]
                compile_text = run(command, ROOT, run_dir / "compile.log", 300)
                if re.search(r"warning:|sorry:", compile_text, re.I):
                    raise RuntimeError(f"unexpected Icarus warning; see {run_dir / 'compile.log'}")
                execute = ["vvp", str(binary)]
                runtime_version = run(["vvp", "-V"], ROOT, run_dir / "runtime-version.log", 30)
                report_run["runtime_version"] = runtime_version.splitlines()[0]
            else:
                binary_dir = run_dir / "obj_dir"
                command = ["verilator", "--binary", "--timing", "--assert", "-Wall", "-Wno-fatal",
                           "--timescale-override", "1ns/1ps", "-DDESIGNWARE_NOEXIST", "-DASSERT_ON",
                           f"-I{DONOR}", "--top-module", "tb_conv_array_core", "--Mdir", str(binary_dir),
                           "-o", "sim_conv", *sources]
                compile_text = run(command, ROOT, run_dir / "compile.log", 600)
                warning_headers = [line for line in compile_text.splitlines()
                                   if line.startswith("%Warning-")]
                report_run["compile_warning_headers"] = len(warning_headers)
                report_run["compile_warning_kinds"] = dict(sorted(Counter(
                    line.split("%Warning-", 1)[1].split(":", 1)[0]
                    for line in warning_headers).items()))
                report_run["warnings"] = [line.replace(str(ROOT) + "/", "")
                                           for line in warning_headers]
                execute = [str(binary_dir / "sim_conv")]
                report_run["cxx_version"] = subprocess.check_output(["c++", "--version"], text=True).splitlines()[0]
            for mode in modes:
                text = run(execute + [f"+FIXTURE={data_dir}", f"+MODE={mode}"], ROOT,
                           run_dir / f"mode-{mode}.log", 60)
                lines = [line for line in text.splitlines() if line.startswith("PASS CONV_")]
                wanted = expected_result(mode)
                if lines != [wanted]:
                    raise RuntimeError(f"unexpected {simulator} mode {mode} result: {lines}, expected {wanted}\n{text[-3000:]}")
                report_run["cases"].append({"mode": mode, "status": "PASS", "result": lines[0]})
            report["runs"].append(report_run)
        report["status"] = "PASS_CAPTURED_CONV_C8_H5_W5_OC8_RAW_STREAM_AND_WHOLE_BO"
    except Exception as exc:
        report["status"] = "FAIL"
        report["failure"] = str(exc)
        raise
    finally:
        report["finished_unix"] = time.time()
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(out / "report.json")
        print(report["status"])


if __name__ == "__main__":
    main()
