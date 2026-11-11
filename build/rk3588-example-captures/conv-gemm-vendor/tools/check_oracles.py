#!/usr/bin/env python3
"""Independently re-derive READY oracles with NumPy and compare expected.bin.

This is still a host-side oracle check, not device validation.  Conv uses an
FP64 sliding-window einsum with the source's local per-group weights; GEMM uses
an FP64 matmul.  Inputs/weights are regenerated from the same deterministic
source rules recorded in the manifest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

FAMILY = Path(__file__).resolve().parents[1]
MANIFEST = FAMILY / "manifest.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    failures: list[str] = []
    checked = 0
    for case in manifest["cases"]:
        if case["status"] != "READY":
            continue
        checked += 1
        name = case["case"]
        case_dir = FAMILY / case["case_dir"]
        oracle = case["oracle"]
        dtype = np.float16 if oracle["dtype"] == "float16" else np.float32
        expected = np.frombuffer(
            (case_dir / "expected.bin").read_bytes(), dtype=dtype
        ).reshape(oracle["shape"])
        if name.startswith("gemm"):
            layout = case["gemm_layout"]
            m, n, k = layout["m"], layout["n"], layout["k"]
            if layout["main_table_case"]:
                a = np.array([[1], [2]], dtype=np.float16)
                b = np.array([[4, 5]], dtype=np.float16)
            else:
                np.random.seed(42)
                a = np.random.randn(m, k).astype(np.float16)
                b = np.random.randn(k, n).astype(np.float16)
            ref = (a.astype(np.float64) @ b.astype(np.float64)).astype(np.float32)
        else:
            s = case["source_shape_parameters"]
            batch = s["batch"]
            in_c, out_c = s["in_c"], s["out_c"]
            in_h, in_w = s["in_h"], s["in_w"]
            kh, kw, groups = s["kh"], s["kw"], s["groups"]
            wic = s["weight_in_c"]
            if case["source_example"].endswith(("conv_legacy.py", "conv.py")):
                np.random.seed(42)
                inp = np.random.uniform(
                    -2, 2, (batch, in_c, in_h, in_w)).astype(np.float16)
                wt = np.random.uniform(
                    -2, 2, (out_c, wic, kh, kw)).astype(np.float16)
            else:
                inp = np.arange(
                    1, batch * in_c * in_h * in_w + 1, dtype=np.float32
                ).reshape(batch, in_c, in_h, in_w).astype(np.float16)
                wt = np.arange(
                    out_c * wic * kh * kw, 0, -1, dtype=np.float32
                ).reshape(out_c, wic, kh, kw).astype(np.float16)
            ref = np.zeros(
                (batch, out_c, in_h - kh + 1, in_w - kw + 1), dtype=np.float64)
            for n in range(batch):
                for g in range(groups):
                    ic0 = g * in_c // groups
                    ic1 = (g + 1) * in_c // groups
                    oc0 = g * out_c // groups
                    oc1 = (g + 1) * out_c // groups
                    window = np.lib.stride_tricks.sliding_window_view(
                        inp[n, ic0:ic1].astype(np.float64),
                        (kh, kw), axis=(1, 2))
                    ref[n, oc0:oc1] = np.einsum(
                        "cyxij,ocij->oyx", window,
                        wt[oc0:oc1].astype(np.float64), optimize=True)
            ref = ref.astype(dtype)
        diff = float(np.max(np.abs(
            expected.astype(np.float64) - ref.astype(np.float64))))
        if diff != 0.0:
            failures.append(f"{name}: max_abs_diff={diff}")
        print(f"{name}: max_abs_diff={diff}")

    if failures:
        print(f"FAIL: {len(failures)} oracle mismatch(es)")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"PASS: {checked} READY oracles match independent NumPy derivation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
