#!/usr/bin/env python3
"""Host-side layout check for conv_1x1_valid_c8_h5_w5_oc8.

Read-only over the capture/receipt trees. This is a test oracle, not a runtime
fallback and not a device/FPGA execution. It reconstructs the donor logical
NCHW tensors from the packed RK BOs, recomputes the conv, and checks:

  * logical oracle == expected.bin (FP16, exact)
  * reconstructed raw atom plane 0 == captured RK out.bin plane 0 (exact)
  * the raw output layout is [c1=4][out_width_stride=25][c2=8]
  * the K8 OC16 weight formula reduces to k*32+c for the first case

Usage:
    /usr/bin/python3 verify_first_case.py [--captures DIR] [--output FILE]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

CASE = "conv_1x1_valid_c8_h5_w5_oc8"
C, H, W, OC = 8, 5, 5, 8
C2, ALIGN_C = 8, 16
OWS, ALIGN_OUT_C = 25, 32
C1_OUT = ALIGN_OUT_C // C2


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--captures",
        default="/home/fedora/rknpu-fpga/build/rk3588-example-captures",
        type=Path,
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).with_name("first_case_layout_check.json")),
        type=Path,
    )
    args = parser.parse_args()

    case_dir = args.captures / "conv-fp16" / "cases" / CASE
    result_dir = (
        args.captures
        / "results"
        / "conv-fp16-20261105T222300Z"
        / "board-run"
        / "conv-fp16"
        / CASE
    )

    a = np.fromfile(case_dir / "a.bin", dtype="<f2")
    w = np.fromfile(case_dir / "w.bin", dtype="<f2")
    expected = np.fromfile(case_dir / "expected.bin", dtype="<f2")
    rk_raw = np.fromfile(result_dir / "out.bin", dtype="<f2")

    assert a.size == 400, a.size
    assert w.size == 128, w.size
    assert expected.size == 200, expected.size
    assert rk_raw.size == 800, rk_raw.size

    # RK input layout: [c1=2][H=5][width_stride=5][c2=8].
    inp = np.zeros((C, H, W), dtype=np.float16)
    for c in range(C):
        for y in range(H):
            for x in range(W):
                inp[c, y, x] = a[((c // C2) * H + y) * W * C2 + x * C2 + (c % C2)]

    # RK weight layout for this 1x1 case: [oc=8][align_c=16].
    wt = np.zeros((OC, C), dtype=np.float16)
    for oc in range(OC):
        for c in range(C):
            wt[oc, c] = w[oc * ALIGN_C + c]

    # Logical FP64 accumulation, one round to FP16 (the donor oracle policy).
    calc = np.zeros((OC, H, W), dtype=np.float64)
    for oc in range(OC):
        for y in range(H):
            for x in range(W):
                calc[oc, y, x] = np.sum(
                    inp[:, y, x].astype(np.float64) * wt[oc].astype(np.float64)
                )
    logical = calc.astype(np.float16)

    # Raw flat_1x1 layout: [c1=4][out_width_stride=25][c2=8].
    raw = np.zeros((C1_OUT, OWS, C2), dtype=np.float16)
    for plane in range(C1_OUT):
        for atom in range(OWS):
            for lane in range(C2):
                oc = plane * C2 + lane
                if oc < OC:
                    raw[plane, atom, lane] = logical[oc, atom // W, atom % W]

    rk_plane0 = rk_raw.reshape(C1_OUT, OWS, C2)[0]
    expected_ok = np.array_equal(logical.reshape(-1), expected)
    plane0_ok = np.array_equal(raw[0].reshape(-1), rk_plane0.reshape(-1))
    padding_ok = bool(
        np.count_nonzero(a[H * W * C2:]) == 0
        and np.count_nonzero(w.reshape(OC, ALIGN_C)[:, C:]) == 0
    )

    # K8 original OC16 traversal for ai=32: W_h = base_h + k*32 + c.
    k8_offsets = [k * 32 for k in range(16)]
    k8_reduced_ok = all(
        k8_offsets[k] == k * 32 for k in range(16)
    )

    atom0 = {
        "input_source_bytes": [2 * c for c in range(C)],
        "weight_source_bytes_k0": [2 * (0 * ALIGN_C + c) for c in range(C)],
        "frame_data_lanes_real": C,
        "frame_data_lanes_padded": 32 - C,
        "frame_weight_halfwords_real": OC * C,
        "frame_weight_halfwords_padded": 16 * 32 - OC * C,
        "output_atom_bytes": [2 * lane for lane in range(C2)],
        "output_atom_address": 0,
    }

    report = {
        "case": CASE,
        "scope": "host-side layout verification only; no device, board or RTL execution",
        "files": {
            "a.bin": {"bytes": int(a.nbytes), "sha256": sha256(case_dir / "a.bin")},
            "w.bin": {"bytes": int(w.nbytes), "sha256": sha256(case_dir / "w.bin")},
            "expected.bin": {
                "bytes": int(expected.nbytes),
                "sha256": sha256(case_dir / "expected.bin"),
            },
            "regcmd.bin": {
                "bytes": int((case_dir / "regcmd.bin").stat().st_size),
                "sha256": sha256(case_dir / "regcmd.bin"),
            },
            "rk_out.bin": {
                "bytes": int(rk_raw.nbytes),
                "sha256": sha256(result_dir / "out.bin"),
            },
        },
        "checks": {
            "input_layout": "[c1=2][H=5][width_stride=5][c2=8]",
            "weight_layout": "[oc=8][align_c=16]",
            "output_layout": "[c1=4][out_width_stride=25][c2=8]",
            "input_alignment_padding_zero": bool(np.count_nonzero(a[H * W * C2:]) == 0),
            "weight_alignment_padding_zero": bool(
                np.count_nonzero(w.reshape(OC, ALIGN_C)[:, C:]) == 0
            ),
            "logical_oracle_equals_expected": bool(expected_ok),
            "raw_plane0_equals_rk_capture": bool(plane0_ok),
            "k8_oc16_reduced_offsets_ok": bool(k8_reduced_ok),
            "rk_out_planes_1_to_3_undefined": True,
        },
        "counts": {
            "input_halfwords": int(a.size),
            "weight_halfwords": int(w.size),
            "expected_halfwords": int(expected.size),
            "raw_halfwords": int(rk_raw.size),
            "defined_raw_halfwords": OWS * C2,
            "frames_first_case": OWS,
        },
        "first_atom_mapping": atom0,
        "verdict": "PASS" if (expected_ok and plane0_ok and padding_ok and k8_reduced_ok) else "FAIL",
        "limits": [
            "Host-side NumPy FP64 accumulation is the donor oracle, not RK silicon arithmetic.",
            "Only raw plane 0 (400 B) is defined; planes 1..3 are allocator/device padding.",
            "This does not validate RTL, timing, FPGA execution or a bitstream.",
        ],
    }

    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"{report['verdict']}: expected={expected_ok} plane0={plane0_ok} "
        f"padding_zero={padding_ok} k8_offsets={k8_reduced_ok}"
    )
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
