#!/usr/bin/env python3
"""Derive single-task bundles from the two-task conv-fp16 cases.

Reads the original bundles under ../conv-fp16/cases/ and writes one-task
copies under this diagnostic directory.  The original bundles are opened
read-only and never modified.  This is a host-side preparation tool; it does
not contact the board and does not open the Rocket device.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAMILY = ROOT.parent / "conv-fp16"
CASES = FAMILY / "cases"
TASK_WORDS = 54

# case -> (task index, [(buffer name, input file, size)], output buffer,
#          output file, output size)
DERIVATIONS = [
    (
        "conv_grouped_3x3_c4_h5_w5_oc8_g2",
        0,
        [("a0", "a0.bin", 800), ("w0", "w0.bin", 1152)],
        ("out0", "out0.bin", 768),
    ),
    (
        "conv_grouped_3x3_c4_h5_w5_oc8_g2",
        1,
        [("a1", "a1.bin", 800), ("w1", "w1.bin", 1152)],
        ("out1", "out1.bin", 768),
    ),
    (
        "conv_splitoc_3x3_c16_h9_w9_oc16",
        0,
        [("a0", "a0.bin", 2592), ("w0", "w0.bin", 2304)],
        ("out0", "out0.bin", 3328),
    ),
    (
        "conv_splitoc_3x3_c16_h9_w9_oc16",
        1,
        [("a0", "a0.bin", 2592), ("w1", "w1.bin", 2304)],
        ("out1", "out1.bin", 3328),
    ),
]

SHORT = {
    "conv_grouped_3x3_c4_h5_w5_oc8_g2": "grouped",
    "conv_splitoc_3x3_c16_h9_w9_oc16": "splitoc",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    out_root = ROOT / "bundles"
    out_root.mkdir(parents=True, exist_ok=True)

    for source_name, task_index, inputs, output in DERIVATIONS:
        source_dir = CASES / source_name
        source_job = json.loads((source_dir / "job.json").read_text())
        tag = f"{SHORT[source_name]}_task{task_index}"
        case_name = f"diag_{tag}"
        case_dir = out_root / case_name
        if case_dir.exists():
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True)

        source_regcmd = (source_dir / "regcmd.bin").read_bytes()
        assert len(source_regcmd) == 2 * TASK_WORDS * 8
        start = task_index * TASK_WORDS * 8
        end = start + TASK_WORDS * 8
        task_stream = source_regcmd[start:end]
        assert len(task_stream) == TASK_WORDS * 8
        (case_dir / "regcmd.bin").write_bytes(task_stream)

        source_buffers = {b["name"]: b for b in source_job["buffers"]}
        buffers = []
        for name, filename, size in inputs:
            original = source_buffers[name]
            assert original["size"] == size, (name, original["size"], size)
            shutil.copyfile(source_dir / filename, case_dir / filename)
            assert (case_dir / filename).stat().st_size == size
            buffers.append(
                {
                    "name": name,
                    "size": size,
                    "input": filename,
                    "direction": "in",
                }
            )
        out_name, out_file, out_size = output
        original = source_buffers[out_name]
        assert original["size"] == out_size, (out_name, original["size"], out_size)
        buffers.append(
            {
                "name": out_name,
                "size": out_size,
                "direction": "out",
                "output": out_file,
            }
        )

        patches = []
        for patch in source_job["patches"]:
            index = patch["regcmd_index"]
            if not start // 8 <= index < end // 8:
                continue
            local = index - start // 8
            assert 0 <= local < TASK_WORDS
            assert patch["buffer"] in {b["name"] for b in buffers}, patch
            patches.append(
                {
                    "regcmd_index": local,
                    "buffer": patch["buffer"],
                    "kind": patch["kind"],
                }
            )
        assert len(patches) == 3, patches
        assert [(p["regcmd_index"], p["buffer"]) for p in patches] == [
            (21, inputs[0][0]),
            (27, inputs[1][0]),
            (35, out_name),
        ], patches

        # Source QWORDs at the patch indices must be zero placeholders; the
        # terminal PC tail (last four QWORDs) must remain source-exact.
        words = struct.unpack(f"<{TASK_WORDS}Q", task_stream)
        for patch in patches:
            assert words[patch["regcmd_index"]] & 0x0000FFFFFFFF0000 == 0
        assert words[-4:] == (
            0x0101000000000010,  # PC_BASE_ADDRESS = 0 (terminal)
            0x0101000000000014,  # PC_REGISTER_AMOUNTS = 0
            0x0041000000000000,  # VERSION = 0
            0x00810000000d0008,  # PC OPERATION_ENABLE = 0xd
        ), [hex(word) for word in words[-4:]]

        job = {
            "case": case_name,
            "source_example": source_job["source_example"],
            "description": (
                f"Diagnostic single-task derivation: {source_name} task "
                f"{task_index} of 2, same 54-QWORD stream at offset 0."
            ),
            "timeout_ns": source_job["timeout_ns"],
            "tasks": [{"regcmd_offset_words": 0, "regcmd_words": TASK_WORDS}],
            "buffers": buffers,
            "patches": patches,
        }
        job_path = case_dir / "job.json"
        job_path.write_text(json.dumps(job, indent=2) + "\n")

        # Copy the matching oracle for host-side comparison only.  It is not
        # declared in job.json and is never written by the runner.
        expected = "expected_out0.bin" if task_index == 0 else "expected_out1.bin"
        shutil.copyfile(source_dir / expected, case_dir / expected)

        derivation = {
            "source_case": source_name,
            "source_case_dir": str(source_dir),
            "source_task_index": task_index,
            "source_regcmd_sha256": sha256(source_regcmd),
            "source_regcmd_bytes": [start, end],
            "source_job_sha256": sha256((source_dir / "job.json").read_bytes()),
            "derived_job_sha256": sha256(job_path.read_bytes()),
            "derived_regcmd_sha256": sha256(task_stream),
            "oracle_copy": expected,
            "notes": [
                "regcmd.bin is the 54-QWORD task slice copied to offset 0",
                "task1 patch indices 75/81/89 are rebound to 21/27/35",
                "terminal PC tail and declared regcmd_words=54 are preserved",
            ],
        }
        (case_dir / "derivation.json").write_text(json.dumps(derivation, indent=2) + "\n")
        print(f"WROTE {case_dir}  case={case_name}")


if __name__ == "__main__":
    main()
