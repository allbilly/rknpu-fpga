# Frozen `conv-gemm-vendor` fixtures

Ten READY cases. Seven are frozen here. The three cases that were initially
rejected are now reconciled by the 2026-11-05 live reruns (see below and
`RESULTS.md`): two were a bundle BO-size defect, one is within the documented
FP32 tolerance. No device/datapath anomaly remains in this family.

## Frozen

| Case | Oracle kind | Comparison | Output BO |
|---|---|---|---|
| `gemm_m2_n2_k1` | recomputed from operands | exact | 4096 B |
| `gemm_m1_n16_k32` | recomputed from operands | exact | 4096 B |
| `gemm_m2_n16_k32` | recomputed from operands | exact | 4096 B |
| `gemm_m4_n32_k64` | recomputed from operands | tolerance ≤ 0.1 | 4096 B |
| `conv_1x1_c1_oc6_h4w4` | host oracle repack | exact on 256 B | 4096 B |
| `conv_grouped_3x3_c4_oc4_g2_h5w5` | host oracle repack | exact on 384 B | 4096 B |
| `conv_legacy_3x3_c4_oc4_h9w9` | host oracle repack | exact on 832 B | 4096 B |

The four GEMM cases are recomputed **from the packed operand BOs** in pure
Python: input `[m][align_in]`, weight
`[oc_chunk][k_chunk][oc_lane][k_lane]` with a 16×32 tile, output
`[m][align_out]` FP32. All four reproduce the device surface; the largest
deviation is `7.9e-7` against a 0.1 tolerance, which is expected FP32
accumulation order, not a packing error.

The three `conv` cases use the capture's own logical NCHW `expected.bin`,
repacked into the captured hardware surface
`[c1][out_width_stride][c2]`. That proves oracle/packing self-consistency, **not**
an independent recomputation from operands — the manifest records the weaker
provenance as `conv_host_oracle_repack`.

## Initially rejected cases — resolved 2026-11-05, live-reverified 2026-11-10

These three cases were rejected at first freeze time; the rejection reason was
a bundle/oracle defect, not a device fault. The corrected reruns are in
`build/rk3588-example-captures/results/conv-gemm-depthwise-rerun-20261105T221115Z/`
and `.../conv-gemm-vendor-20261105T214000Z/`, and the 2026-11-10 live P0 jobs
reproduced the same device outputs under the board lock.

| Case | Original rejection | Resolution |
|---|---|---|
| `conv_depthwise_3x3_c3_oc3_h11w28_task0` | declared a 7,552-byte output BO; expected oracle covered only 1,404 bytes | the command stream requires a **15,104-byte** output BO (two groups × 7,552, `DPU_DATA_CUBE_CHANNEL=0x1f`). After correcting the BO size: **702/702 exact**, max abs diff 0. |
| `conv_depthwise_3x3_c3_oc3_h11w28_task1` | same + two tasks shared one device BO hash | after the same BO-size fix both tasks are 702/702 exact with identical output bytes; the split single-task form is the capture contract (Rocket does not reliably execute a second task in one job). |
| `conv_py_3x3_c32_oc128_h14w14_fullsetup` | 18,398/18,432 elements differed from the packed host oracle | the packed-layout oracle was wrong for this case; the device surface is the contract. Measured deviation from the device surface is **within 0.015625 against the documented 0.12 tolerance**. |

The two depthwise tasks' device output BOs are **byte-identical** with SHA-256
prefix `23762b45` (7,552 B each; recomputed from the current capture tree and
re-confirmed by the live P0 rerun), which is exactly why the split
single-task form is the capture contract rather than a two-task job.

A fixture that binds a device BO to an oracle it contradicts would be worse
than no fixture, so these three stay out of the frozen seven until their
device-derived oracles are pinned. The remaining three BLOCKED cases in this
family are the vendor-ABI ones (two large `conv.py` BY_K paths and the
multi-task parent); they have no RTL and no Rocket capture route.

## GEMM FP32 leaf — done

The four frozen GEMM cases now run end to end through real arithmetic:

```
raw 50-QWORD stream -> rk_cmac_nvdla_dma(OUTPUT_FP16=0)
    -> rk_cmac_profile(OUTPUT_FP16=0)
    -> rk_cmac_operand_front / rk_cmac_address(OUTPUT_FP32=1)
    -> rk_nvdla_cmac_pipe(OUTPUT_FP16=0)
    -> rk_cmac_output_fp32          (no conversion, two halfwords per value)
```

The decoder differences are **derived from `gemm.py`'s own formulas**, never
transplanted from a capture:

| Register | FP16 value | FP32 value | Source expression |
|---|---|---|---|
| DPU `DATA_FORMAT` `0x4010` | `0x48000002` | `0xa8000002` | `out_precision = 2 if out_fp16 else 5`, shifted to bit 29 |
| DPU `BS_OW_CFG` `0x4050` | `0x126` | `0x36e` | `size_e = 1 if out_fp16 else 3`, three copies |
| DPU `OUT_CVT_SCALE` `0x4084` | `0x10001` | `0x0` | `((1 << 16) | 1) if out_fp16 else 0` |

`rk_cmac_profile #(.OUTPUT_FP16(...))` computes all three at elaboration; the
parameter is forwarded through `rk_cmac_operand_front`, `rk_cmac_nvdla_core`,
`rk_cmac_nvdla_dma` and `rk_cmac_nvdla_axi`. The numerical tail is selected in
`rk_nvdla_cmac_pipe`: the FP16 branch keeps the donor conversion, the FP32
branch is `rk_cmac_output_fp32`, which commits the CACC value unchanged.

The address walker needed one honest correction. FP16 writes one halfword per
element in padded 16-lane atoms (`+2`, with `+34` at each 16-channel crossing),
while the captured FP32 GEMM BO is the logical M×N tensor: each element
advances 4 bytes and the 16-channel crossing advances one element (`+4`), not a
padded atom. That difference is `rk_cmac_address #(.OUTPUT_FP32(...))`.

### Evidence

`tools/cmac/run_gemm_fp32.py --simulator both`, complete 4096-byte output BO:

| Case | Shape | k | Tolerance | Worst abs | Result |
|---|---|---:|---:|---:|---|
| `gemm_m2_n2_k1` | m2 n2 | 1 | 0.0 | **0 (byte-exact)** | PASS |
| `gemm_m1_n16_k32` | m1 n16 | 32 | 0.1 | 1.9e-6 | PASS |
| `gemm_m2_n16_k32` | m2 n16 | 32 | 0.1 | 1.9e-6 | PASS |
| `gemm_m4_n32_k64` | m4 n32 | 64 | 0.1 | 1.27e-4 | PASS |

Receipts: `build/cmac-gemm-fp32/iverilog-20261108T174335Z-*` and
`build/cmac-gemm-fp32/verilator-20261108T174335Z-*`.

Byte-exactness is claimed only for k=1: with a single product per output value
there is no accumulation-order freedom. The deeper shapes are limited by
different CACC rounding in RTL versus the device DPU, which is why the family's
own `0.1` bound applies there and the measured worst deviation is printed on
every run.

### Two bugs the replay found

* **Weight-panel stride.** The first version assumed an output-lane group
  advanced the weight pointer by `ai*2` bytes. It does not: within a 16-lane
  group the next output channel is one 16×32 panel, i.e. `+64` bytes,
  independent of `ai`. The K=64 case exposed it by walking the weight BO into
  the output window.
* **16-channel crossing.** The FP32 output address is contiguous, but the
  weight panel must still step at `oc % 16 == 15`. Skipping the crossing made
  the second 16 output channels read the wrong weights.

## What is still missing on this family

The three vendor-BY_K cases remain without RTL. They are a different datapath
(vendor `BY_K` partitioning) rather than GEMM shapes, and none of the four GEMM
replays above exercises that path. No claim is made for them here.
