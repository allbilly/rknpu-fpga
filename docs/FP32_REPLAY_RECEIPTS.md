# FP32 replay receipts — 2026-11-08

Two fixture families had no execution path until the FP32 output work:
the four frozen `conv-gemm-vendor` GEMM cases and the FP32-output
`conv-simple` case. Both now run through real arithmetic and are recorded here.

Every row is simulation only: **no hardware accessed, no Vivado run, no
bitstream emitted**.

## conv-gemm-vendor GEMM (FP32 output)

Runner: `tools/cmac/run_gemm_fp32.py`, complete 4096-byte output BO compared.
Path: raw 50-QWORD stream → `rk_cmac_nvdla_dma(OUTPUT_FP16=0)` →
`rk_cmac_profile(OUTPUT_FP16=0)` → operand front / `rk_cmac_address(OUTPUT_FP32=1)`
→ `rk_nvdla_cmac_pipe(OUTPUT_FP16=0)` → `rk_cmac_output_fp32`.

| Case | Shape | k | Tolerance | Worst abs | Icarus | Verilator |
|---|---|---:|---:|---:|---|---|
| `gemm_m2_n2_k1` | m2 n2 | 1 | 0.0 | **0** (byte-exact) | PASS | PASS |
| `gemm_m1_n16_k32` | m1 n16 | 32 | 0.1 | 1.9e-6 | PASS | PASS |
| `gemm_m2_n16_k32` | m2 n16 | 32 | 0.1 | 1.9e-6 | PASS | PASS |
| `gemm_m4_n32_k64` | m4 n32 | 64 | 0.1 | 1.27e-4 | PASS | PASS |

Receipts: `build/cmac-gemm-fp32/iverilog-20261108T174335Z-<case>/report.json`
and `build/cmac-gemm-fp32/verilator-20261108T174335Z-<case>/report.json`.

The decoder differences are derived from `gemm.py`, not transplanted from a
capture: `out_precision = 2 if out_fp16 else 5`, `size_e = 1 if out_fp16 else 3`,
`OUT_CVT_SCALE = ((1 << 16) | 1) if out_fp16 else 0`.

Byte-exactness is claimed only for k=1. Deeper shapes have accumulation-order
freedom, so the family's declared bound applies and the measured deviation is
printed on every run.

## conv-simple FP32 output

Case: `conv_simple_fp16_1x1_c4_h8_w8_oc16`, profile 3, `OUTPUT_FP16=0`.
Runner: `tools/conv/run_conv_simple_fp32.py`, complete 4096-byte output BO.

| Simulator | Receipt | Values | Halfword writes | Differing words | Worst abs | Bound |
|---|---|---|---:|---:|---:|---:|
| Icarus | `build/conv-simple-fp32/iverilog-20261108T192540Z` | 1024 | 2048 | 63 | 4.77e-7 | 0.001 |
| Verilator | `build/conv-simple-fp32/verilator-20261108T192540Z` | 1024 | 2048 | 63 | 4.77e-7 | 0.001 |

The 63 differing words are last-bit differences from CACC vs device-DPU
accumulation order, not layout errors. The captured surface was measured
before the mapper was written: it is `[c1][pixel][c2=4]` with a plane stride of
`PIXELS*C2` words, and that mapping reproduces all 1024 words within 2.4e-7.
Plain NCHW and NHWC both disagree by whole values.

The same job also runs through the host-drivable endpoint
(`tools/conv/run_conv_simple_axi.py` profile 3), which re-checks the same
bytes after a real AXI-Lite submit:

| Simulator | Modes | Receipt |
|---|---|---|
| Icarus | 8/8 | `build/conv-axi/iverilog-20261108T194552Z-3` |
| Verilator | **not recorded** | the run was stopped before finishing; no partial tree is kept |

The eight modes are the same transport contract the FP16 profiles carry: full
job plus six rejections and one two-job mode. For the FP32 profile the compare
reports its measured deviation (`differing_words=63 worst_abs=4.77e-7
limit=0.001`) instead of demanding byte equality.

## Tool versions

Icarus Verilog 13.0, Verilator 5.048, Python 3.14.5. Source revision is the
worktree these receipts were produced from; each `report.json` records
`source_hashes_before` / `source_hashes_after` and fails if they differ.
