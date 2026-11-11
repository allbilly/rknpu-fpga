#!/usr/bin/env python3
"""Cross-check generated capture bundles against the real source examples.

This is a host-side proof that the transcription in gen_bundles.py matches the
actual functions in:

  /home/fedora/rk3588/examples/kernel_6_18/elementwise_int.py
  /home/fedora/rk3588/examples/expt/elementwise_int.py

It imports both modules (which is device-free: device access lives under the
``if __name__ == "__main__"`` guard), builds the same register streams, decodes
the generated input/oracle files with the source packers, and compares bytes.

Run with an interpreter that has NumPy, for example::

    /usr/bin/python3 tools/crosscheck_source.py

The script does not open /dev/accel*, does not submit, and does not touch the
board.  It writes validation/source_crosscheck.{json,txt} under this family.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "manifest.json"
VALIDATION_DIR = ROOT / "validation"

KERNEL_SRC = "/home/fedora/rk3588/examples/kernel_6_18/elementwise_int.py"
EXPT_SRC = "/home/fedora/rk3588/examples/expt/elementwise_int.py"

OUT_PH = 0x20000000
A_PH = 0x10000000
B_PH = 0x10010000

NP_DTYPES = {"INT8": np.int8, "INT16": np.int16, "INT32": np.int32}


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def qwords_from_file(path):
    raw = Path(path).read_bytes()
    if len(raw) % 8:
        raise AssertionError(f"{path}: length {len(raw)} is not a multiple of 8")
    return list(np.frombuffer(raw, dtype="<u8"))


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: mismatch\n  actual  ={actual}\n  expected={expected}")


def check_constants(gen, kernel, expt):
    checks = 0
    for name in ("INT8", "INT16", "INT32"):
        assert_equal(
            gen.DTYPES[name]["precision"],
            getattr(kernel, f"PRECISION_{name}"),
            f"precision {name}",
        )
        assert_equal(
            gen.DTYPES[name]["element_size"],
            getattr(kernel, f"ERDMA_SIZE_{name}"),
            f"element size {name}",
        )
        checks += 2

    for operation, spec in kernel.OPERATIONS.items():
        gen_spec = gen.OPERATIONS[operation]
        assert_equal(
            gen_spec.get("op_type", 0), spec.get("op_type", 0), f"op_type {operation}"
        )
        assert_equal(
            gen_spec.get("alu_algorithm", -1),
            spec.get("alu_algorithm", -1),
            f"alu {operation}",
        )
        checks += 2

    probes = [
        (gen.TARGET_DPU, gen.FEATURE_MODE_CFG, 0x1E5),
        (gen.TARGET_RDMA, gen.RDMA_SRC_BASE_ADDR, A_PH),
        (gen.TARGET_PC, gen.OPERATION_ENABLE, 0x18),
    ]
    for target, offset, value in probes:
        assert_equal(gen.emit(target, offset, value), kernel.emit(target, offset, value),
                     f"emit 0x{target:04x}/0x{offset:04x}")
        assert_equal(gen.emit(target, offset, value), expt.emit(target, offset, value),
                     f"expt emit 0x{target:04x}/0x{offset:04x}")
        checks += 2

    # Every dtype/operation/width/channel combination used anywhere in the
    # source's offline validators.
    for dtype_name in ("INT8", "INT16", "INT32"):
        config = kernel.DTYPES[dtype_name]
        for operation in kernel.OPERATIONS:
            for precision_bypass in (False, True):
                assert_equal(
                    gen.dpu_ew_cfg(config["element_size"], operation, precision_bypass),
                    kernel.dpu_ew_cfg(config["element_size"], operation, precision_bypass),
                    f"dpu_ew_cfg {dtype_name}/{operation}/{precision_bypass}",
                )
                assert_equal(
                    gen.dpu_ew_cfg(config["element_size"], operation, precision_bypass),
                    expt.dpu_ew_cfg(config["element_size"], operation, precision_bypass),
                    f"expt dpu_ew_cfg {dtype_name}/{operation}/{precision_bypass}",
                )
                checks += 2
        for width in (1, 2, 3):
            for channels in (3, 4, 5, 7, 8, 9, 15, 16, 17, 31, 32, 33):
                for operation in kernel.OPERATIONS:
                    theirs = kernel.make_regcmds(
                        OUT_PH, A_PH, B_PH,
                        config["precision"], config["element_size"],
                        width, channels, operation,
                    )
                    ours = gen.make_regcmds(
                        OUT_PH, A_PH, B_PH,
                        config["precision"], config["element_size"],
                        width, channels, operation,
                    )
                    assert_equal(ours, theirs, f"make_regcmds {dtype_name}/{operation}/{width}x{channels}")
                    theirs = expt.make_layout_regcmds(
                        OUT_PH, A_PH, B_PH,
                        config["precision"], config["element_size"],
                        width, channels, operation,
                    )
                    ours = gen.make_layout_regcmds(
                        OUT_PH, A_PH, B_PH,
                        config["precision"], config["element_size"],
                        width, channels, operation,
                    )
                    assert_equal(ours, theirs, f"make_layout_regcmds {dtype_name}/{operation}/{width}x{channels}")
                    checks += 2
    return checks


def check_case(entry, gen, kernel, expt):
    case = entry["case"]
    case_dir = ROOT / entry["bundle_dir"]
    job = json.loads((case_dir / "job.json").read_text(encoding="utf-8"))
    source = kernel if entry["source_example"] == KERNEL_SRC else expt
    dtype_name = entry["dtype"]
    operation = entry["operation"]
    width = entry["shape"]["width"]
    channels = entry["shape"]["channels"]
    items = width * channels
    dtype = NP_DTYPES[dtype_name]
    item_size = np.dtype(dtype).itemsize

    result = {"case": case, "checks": []}

    qwords = qwords_from_file(case_dir / "regcmd.bin")
    assert_equal(len(qwords), job["tasks"][0]["regcmd_words"],
                 f"{case}: regcmd word count")
    assert_equal(len(qwords), entry["regcmd_qwords"], f"{case}: manifest word count")

    if entry["layout"].startswith("C1WC2"):
        prefix = [gen.emit(gen.TARGET_DPU, gen.S_POINTER, 0xE),
                  gen.emit(gen.TARGET_RDMA, gen.RDMA_S_POINTER, 0xE),
                  gen.emit(gen.TARGET_RDMA, gen.RDMA_BRDMA_CFG, 1),
                  gen.emit(gen.TARGET_RDMA, gen.RDMA_NRDMA_CFG, 1)]
        assert_equal(qwords[:4], prefix, f"{case}: expt prepare_and_run prefix")
        expected_qwords = prefix + expt.make_layout_regcmds(
            OUT_PH, A_PH, B_PH,
            expt.DTYPES[dtype_name]["precision"],
            expt.DTYPES[dtype_name]["element_size"],
            width, channels, operation,
        )
        atom = 16 // item_size
        surfaces = (channels + atom - 1) // atom
        packed_elems = surfaces * width * atom
        packed_a = np.frombuffer((case_dir / "a.bin").read_bytes()[: packed_elems * item_size],
                                 dtype=dtype)
        packed_b = np.frombuffer((case_dir / "b.bin").read_bytes()[: packed_elems * item_size],
                                 dtype=dtype)
        logical_a = expt.unpack_c1wc2(packed_a, width, channels, dtype).reshape(-1)
        logical_b = expt.unpack_c1wc2(packed_b, width, channels, dtype).reshape(-1)
        expected_values = expt.integer_expected(operation, logical_a, logical_b, dtype)
        packed_expected = expt.pack_c1wc2(expected_values, width, channels, dtype).tobytes()
        # Valid-lane byte mask: 0xFF over every byte of a valid logical lane.
        valid = np.ones(width * channels, dtype=dtype)
        packed_valid = expt.pack_c1wc2(valid, width, channels, dtype)
        packed_mask = (
            np.repeat((packed_valid != 0).astype(np.uint8), item_size) * 0xFF
        ).tobytes()
        result["checks"].append("expt.unpack_c1wc2 inputs")
        result["checks"].append("expt.integer_expected oracle")
        result["checks"].append("expt.pack_c1wc2 expected+mask")
    else:
        config = source.DTYPES[dtype_name]
        expected_qwords = source.make_regcmds(
            OUT_PH, A_PH, B_PH,
            config["precision"], config["element_size"],
            width, channels, operation,
        )
        a = np.frombuffer((case_dir / "a.bin").read_bytes()[: items * item_size], dtype=dtype)
        b = np.frombuffer((case_dir / "b.bin").read_bytes()[: items * item_size], dtype=dtype)
        if dtype_name == "INT32" and operation == "MUL":
            b16 = (b.astype(np.int64) & 0xFFFF).astype(np.uint16).view(np.int16)
            expected_values = np.clip(
                a.astype(np.int64) * b16,
                np.iinfo(dtype).min, np.iinfo(dtype).max,
            ).astype(dtype)
            result["checks"].append("source-captured signed-INT16 MUL operand model")
        else:
            expected_values = source.integer_expected(operation, a, b, dtype)
            result["checks"].append("source.integer_expected")
        packed_expected = expected_values.tobytes()
        packed_mask = b"\xff" * len(packed_expected)
        result["checks"].insert(0, "source.make_regcmds")

    assert_equal(qwords, expected_qwords, f"{case}: regcmd QWORDs")

    expected_bytes = (case_dir / "expected.bin").read_bytes()
    mask_bytes = (case_dir / "expected.mask.bin").read_bytes()
    assert_equal(expected_bytes[: len(packed_expected)], packed_expected,
                 f"{case}: expected.bin payload")
    assert_equal(mask_bytes[: len(packed_mask)], packed_mask,
                 f"{case}: expected.mask.bin asserted lanes")
    assert_equal(set(mask_bytes[len(packed_mask):]) - {0}, set(),
                 f"{case}: mask has asserted bytes outside the payload")
    result["checks"].append("expected.bin + expected.mask.bin")
    return result


def check_int16_to_int32(entry, kernel):
    case_dir = ROOT / entry["bundle_dir"]
    captured = {}

    class FakeBO:
        def __init__(self, address):
            self.dma_addr = address

    def fake_prepare_and_run(fd, commands, payloads, output_dtype, output_count):
        captured["commands"] = commands(
            FakeBO(OUT_PH), [FakeBO(A_PH), FakeBO(B_PH)]
        )
        captured["payloads"] = [np.asarray(payload).copy() for payload in payloads]
        return 0, np.zeros(output_count, dtype=output_dtype)

    original = kernel.prepare_and_run
    kernel.prepare_and_run = fake_prepare_and_run
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            kernel.run_int16_add_to_int32(None)
    finally:
        kernel.prepare_and_run = original

    qwords = qwords_from_file(case_dir / "regcmd.bin")
    assert_equal(qwords, captured["commands"], "int16_add_to_int32: regcmd QWORDs")
    assert_equal(
        (case_dir / "a.bin").read_bytes()[:16],
        captured["payloads"][0].tobytes(),
        "int16_add_to_int32: a payload",
    )
    assert_equal(
        (case_dir / "b.bin").read_bytes()[:16],
        captured["payloads"][1].tobytes(),
        "int16_add_to_int32: b payload",
    )
    expected = captured["payloads"][0].astype(np.int32) + captured["payloads"][1].astype(np.int32)
    assert_equal(
        (case_dir / "expected.bin").read_bytes()[:32],
        expected.tobytes(),
        "int16_add_to_int32: expected.bin",
    )
    assert_equal(
        (case_dir / "expected.mask.bin").read_bytes()[:32],
        b"\xff" * 32,
        "int16_add_to_int32: mask",
    )
    return {"case": entry["case"], "checks": [
        "source.run_int16_add_to_int32 captured commands",
        "source payloads",
        "expected.bin + expected.mask.bin",
    ]}


def main():
    gen = load_module(str(ROOT / "tools" / "gen_bundles.py"), "ew_int_gen")
    kernel = load_module(KERNEL_SRC, "ew_kernel")
    expt = load_module(EXPT_SRC, "ew_expt")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    ready = [entry for entry in manifest["cases"] if entry["status"] == "READY"]

    report = {
        "tool": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "script": "tools/crosscheck_source.py",
        },
        "sources": {
            KERNEL_SRC: sha256_file(KERNEL_SRC),
            EXPT_SRC: sha256_file(EXPT_SRC),
        },
        "constant_and_builder_checks": check_constants(gen, kernel, expt),
        "cases": [],
        "summary": {"checked": 0, "failed": 0},
    }

    failures = []
    for entry in ready:
        try:
            if entry["case"] == "int16_add_to_int32_c8_w1":
                case_report = check_int16_to_int32(entry, kernel)
            else:
                case_report = check_case(entry, gen, kernel, expt)
            report["cases"].append(case_report)
            report["summary"]["checked"] += 1
        except Exception as exc:
            failures.append(entry["case"])
            report["cases"].append({
                "case": entry["case"],
                "error": f"{type(exc).__name__}: {exc}",
            })
            report["summary"]["failed"] += 1

    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    (VALIDATION_DIR / "source_crosscheck.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "RK3588 integer EW source cross-check",
        f"python {report['tool']['python']}  numpy {report['tool']['numpy']}",
        f"kernel source sha256 {report['sources'][KERNEL_SRC]}",
        f"expt   source sha256 {report['sources'][EXPT_SRC]}",
        f"function/constant comparisons: {report['constant_and_builder_checks']}",
        f"cases checked: {report['summary']['checked']}  failed: {report['summary']['failed']}",
    ]
    for case_report in report["cases"]:
        if "error" in case_report:
            lines.append(f"  FAIL {case_report['case']}: {case_report['error']}")
        else:
            lines.append(f"  PASS {case_report['case']}: {', '.join(case_report['checks'])}")
    text = "\n".join(lines) + "\n"
    (VALIDATION_DIR / "source_crosscheck.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    if failures:
        print(f"FAILURES: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
