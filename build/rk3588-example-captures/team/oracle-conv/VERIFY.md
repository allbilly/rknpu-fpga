# Independent conv / pooling oracle verification

Generated: `2026-11-05T20:57:40.815995+00:00`

This report was produced by an independent host-side verifier.  It does **not** contain a device capture and it does **not** establish RK3588 or FPGA numerics.  `expected*.bin` files are host-side oracles from the preparation bundles; they are compared against a separately implemented naive NumPy/pure-Python recomputation from the raw bundle inputs.

## Environment

- Python: `3.14.8` (`/usr/bin/python3`)
- NumPy: `2.4.6`
- Platform: `Linux-7.2.9-200.fc44.x86_64-x86_64-with-glibc2.43`
- Captures root: `/home/fedora/rknpu-fpga/build/rk3588-example-captures`

## Commands

```sh
/usr/bin/python3 /home/fedora/rknpu-fpga/build/rk3588-example-captures/team/oracle-conv/verify.py
```

No tracked source, test, generated file or family bundle was modified by this verifier.  `make generated-check` / `make test` were not run because this run only wrote under `team/oracle-conv/`.  No `ssh`, `scp`, board, NPU-device, flash or FPGA action was performed.

## Summary

| family | status | READY | BLOCKED | verified | PASS | FAIL | ERROR | WAITING |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `conv-simple` | READY | 7 | 5 | 7 | 7 | 0 | 0 | 0 |
| `conv-fp16` | READY | 7 | 3 | 7 | 7 | 0 | 0 | 0 |
| `conv-gemm-vendor` | READY | 9 | 2 | 9 | 9 | 0 | 0 | 0 |
| `pooling` | READY | 19 | 2 | 19 | 19 | 0 | 0 | 0 |

## Independence and comparison contract

- No family `tools/` helper or preparation-time oracle function is imported or called.
- Raw input/weight/bias bytes are decoded from the documented source layout; the convolution, pooling or GEMM is then recomputed with a small independent NumPy loops implementation.
- Only the declared logical output region is compared: whole raw BO for conv-simple FP16, meaningful prefix for conv-simple INT8, logical NCHW for conv-fp16, logical NCHW/MxN for conv-gemm-vendor, and the C1HWC2 value/index regions for pooling.
- `expected*.bin` is used only as the comparison target, never to construct the computed result.  No device output exists in these bundles; none is invented.
- Each family section records the manifest SHA-256 and generated timestamp; VERIFY.json also carries the manifest's source-example/revision/seed/tool metadata under `source_evidence`.
- Device-output scan: **0** declared worker output file(s) present.  The scan is listed separately so an oracle is never treated as a device capture.

## Layout contracts exercised

**`conv-simple`**

- FP16 input is C1HWC2-like [c1][H][width_stride][c2] with c2=8; the READY cases have width_stride == in_w and the padded lanes are zero.
- FP16 weights use the source's kh-major chunks [oc_chunk][kh][kw][oc_lane][aligned_in_c] (or the default [oc][kh][kw][aligned_in_c] for 1x1).
- FP16 output is unpack_output order [c1][out_width_stride][c2], with c2=8 for FP16 and c2=4 for FP32; READY cases have no output padding.
- INT8 input is [channel_group][x][y][16] bytes (value-0x80); INT8 weights are [oc_group][ic_group][x][y][oc_lane][ic_lane]; INT8 output is the meaningful prefix [channel_group][x][y][16] of the allocated BO.
- Valid-only geometry, stride 1, dilation 1; the INT8 depthwise case uses one input channel per output channel and groups=64.

**`conv-fp16`**

- Input is the donor CDMA_DC pack: [c1][H][width_stride][c2] with c2=8, c1=ceil(max(in_c, align_c)/c2); C1HWC2 atoms are FP16.
- Weights are one of default [oc][kh][kw][aligned_in_c], kh-major [kh][kw][oc_lane][aligned_in_c], pointwise-wide 32-channel atoms, or depthwise spatial [kh][kw][c2] with one weight per channel.
- Output BO is raw NC1HWC2 with c2=8 and out_width_stride rounded up to a multiple of 4 for spatial cases; expected.bin is the logical NCHW [1,out_c,out_h,out_w] slice, not the padded raw surface.
- Stride 1 and 2 are exercised; SAME padding is not: the padded case is an explicit 1-pixel zero frame around a valid 3x3. Groups 1 and 2 plus a 3-channel depthwise case are exercised. No dilation is encoded.
- FP16 oracle contract: float64 accumulation of FP16 operands, one cast to FP16; a device may accumulate in a different order.

**`conv-gemm-vendor`**

- GEMM uses logical MxNxK; A is M rows of align_in FP16 (only the first K columns meaningful). B is packed as W[align_out,align_in], with W[:N,:K] = B.T, laid out [oc_block16][ic_block32][oc_lane16][ic_lane32]. Output is MxN logical FP32 and an Mxalign_out FP32 raw surface with row stride align_out (32 in these cases).
- conv_gemm/conv_legacy input is NHWC when use_nhwc, otherwise [c1][H][width_stride][c2] with c2=8; weights are default, kh-major, grouped-spatial block-16 reorder, or depthwise spatial depending on shape. conv.py uses 16x32 weight blocks for spatial kh-major.
- All READY conv cases use valid-only geometry, stride 1, dilation 1. Groups 1/2 and depthwise groups=3 are exercised; the grouped-spatial weight reorder is inverted explicitly in the verifier.
- Expected.bin is logical NCHW [1,out_c,out_h,out_w] FP16; raw output BOs pad channels and spatial rows and are not byte-compared here.

**`pooling`**

- Input and output are C1HWC2: 16-byte atoms, so atom channels are 8 for FP16/INT16 and 16 for INT8. The value region is [surf][out_h][out_w][atom].
- Kernel and stride are independent width/height fields; padding is top/right/bottom/left. No dilation is encoded.
- Average uses the full kernel window, i.e. include-padding denominator; the two USE_CNT probes therefore share the same expected values. Maximum/minimum use the encoded padding value (0xFC00 == -inf for the negative FP16 case).
- INDEX_EN writes uint16 positions at out_area*2*16 bytes in [surf][out_h][out_w][8] order, with (row<<3)|column. Only the clean window-local case is scored.
- Atom tails are -99 for the source three-channel case and zero elsewhere; the declared value region includes those tail lanes.

## Mismatches

- None. All 42 READY cases with a declared expected oracle matched within their declared tolerance; no device output was compared and no oracle was substituted for one.

## Per-family results

### `conv-simple`

- Status: **READY**
- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-simple/manifest.json`
- Manifest SHA-256: `649ef4eb5f01e4ed46698e5005a2662e6e88cae6feb5a9e72e6b99ad2fc8ea39`
- Manifest generated: `2026-11-05T20:50:36Z`
- READY / BLOCKED: **7 / 5**
- Verified expected oracles: **7** (PASS 7, FAIL 0, ERROR 0, WAITING 0)
- Oracle coverage: **7/7** READY cases were checked against a declared expected file; **5** BLOCKED cases are not scored.

| case | status | expected | max diff | mismatches | notes |
|---|---|---|---:|---:|---|
| `conv_simple_fp16_1x1_c4_h8_w8_oc16` | PASS | expected.bin | 0 | 0 | layout=unpack_output() order: [c1][out_width_stride][c2], c2=4, c1=4; logical=NCHW [1, 16, 8, 8]; accumulate=float64 then cast float32. |
| `conv_simple_fp16_3x3_c4_h8_w8_oc16` | PASS | expected.bin | 0 | 0 | layout=unpack_output() order: [c1][out_width_stride][c2], c2=8, c1=2; logical=NCHW [1, 16, 6, 6]; accumulate=float64 then cast float16. |
| `conv_simple_fp16_5x5_c4_h8_w8_oc16` | PASS | expected.bin | 0 | 0 | layout=unpack_output() order: [c1][out_width_stride][c2], c2=8, c1=2; logical=NCHW [1, 16, 4, 4]; accumulate=float64 then cast float16. |
| `conv_simple_fp16_1x1_c32_h8_w8_oc32` | PASS | expected.bin | 0 | 0 | layout=unpack_output() order: [c1][out_width_stride][c2], c2=4, c1=8; logical=NCHW [1, 32, 8, 8]; accumulate=float64 then cast float32. |
| `conv_simple_fp16_3x3_c16_h8_w8_oc32` | PASS | expected.bin | 0 | 0 | layout=unpack_output() order: [c1][out_width_stride][c2], c2=8, c1=4; logical=NCHW [1, 32, 6, 6]; accumulate=float64 then cast float16. |
| `simple_conv_int8_5x5_c8_h8_w8_oc32` | PASS | expected.bin | 0 | 0 | INT8 decode: raw input/weight bytes are (logical-0x80)&0xff; packed bias is bias+128*sum(logical weights). compare prefix 512 bytes of 1024 B BO. |
| `simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64` | PASS | expected.bin | 0 | 0 | INT8 decode: raw input/weight bytes are (logical-0x80)&0xff; packed bias is bias+128*sum(logical weights). compare prefix 2304 bytes of 4608 B BO. |
| `conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2` | BLOCKED | - | - | - | No source path encodes a convolution stride.  The FP16 shape parser accepts an sN field (expt/conv_simple.py:228-238), but _conv_params ignores it (lines 297-311) and make_regs alw |
| `conv_simple_fp16_3x3_c8_h8_w8_oc16_samepad` | BLOCKED | - | - | - | No SAME-padding path exists in the named sources.  The FP16 make_regs() never writes CNA_PAD_CON0 or CNA_PAD_CON1 (expt/conv_simple.py:383-440) and _conv_params computes out_h/out_ |
| `conv_simple_fp16_3x3_c8_h8_w8_oc16_unpadded_pack` | BLOCKED | - | - | - | This C8 shape cannot be packed safely with the FP16 builder.  For in_c=8, _conv_align_c returns 16 (expt/conv_simple.py:283-286), but _conv_input_pack_c2 returns 8 (lines 289-294). |
| `conv_simple_fp16_grouped_3x3_c8_h8_w8_oc8_g2` | BLOCKED | - | - | - | The grouped path cannot be expressed safely from these sources.  The FP16 make_regs() has no group-count register and its known-supported table has no grouped entry (expt/conv_simp |
| `simple_conv_int8_addition_c8_h8_w8_oc32` | BLOCKED | - | - | - | The source's addition-input knobs are not a usable ABI.  use_shape() reads addition_input/add_tensor (kernel_6_18/simple_conv.py:83-84), but build_conv_regs() uses them only to cha |

### `conv-fp16`

- Status: **READY**
- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-fp16/manifest.json`
- Manifest SHA-256: `ae7acc1bcdd224defd38b7c082cf5edc168db4b0673afbafbe7754ba1f439282`
- Manifest generated: `2026-11-05T20:28:46.470666+00:00`
- READY / BLOCKED: **7 / 3**
- Verified expected oracles: **7** (PASS 7, FAIL 0, ERROR 0, WAITING 0)
- Oracle coverage: **7/7** READY cases were checked against a declared expected file; **3** BLOCKED cases are not scored.

| case | status | expected | max diff | mismatches | notes |
|---|---|---|---:|---:|---|
| `conv_1x1_valid_c8_h5_w5_oc8` | PASS | expected.bin | 0 | 0 | task 0: buffers a/w/out, weight layout default, input C1HWC2, align_c=16, out_width_stride=25, groups=1, stride=1. |
| `conv_3x3_valid_c4_h9_w9_oc4` | PASS | expected.bin | 0 | 0 | task 0: buffers a/w/out, weight layout kh_major, input C1HWC2, align_c=16, out_width_stride=52, groups=1, stride=1. |
| `conv_3x3_stride2_c4_h11_w11_oc4` | PASS | expected.bin | 0 | 0 | task 0: buffers a/w/out, weight layout kh_major, input C1HWC2, align_c=16, out_width_stride=28, groups=1, stride=2. |
| `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` | PASS | expected.bin | 0 | 0 | task 0: buffers a/w/out, weight layout kh_major, input C1HWC2, align_c=16, out_width_stride=84, groups=1, stride=1. |
| `conv_depthwise_3x3_c3_h11_w28_oc3` | PASS | expected.bin | 0 | 0 | task 0: buffers a/w/out, weight layout depthwise_spatial, input C1HWC2, align_c=8, out_width_stride=236, groups=3, stride=1. |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2` | PASS | expected_out0.bin,expected_out1.bin,expected_combined.bin | 0 | 0 | task 0: buffers a0/w0/out0, weight layout kh_major, input C1HWC2, align_c=16, out_width_stride=12, groups=1, stride=1. |
| `conv_splitoc_3x3_c16_h9_w9_oc16` | PASS | expected_out0.bin,expected_out1.bin,expected_combined.bin | 0 | 0 | task 0: buffers a0/w0/out0, weight layout kh_major, input C1HWC2, align_c=16, out_width_stride=52, groups=1, stride=1. |
| `conv_tiles_vendor_abi_blocked` | BLOCKED | - | - | - | Vendor-only ABI: conv_tiles.py opens /dev/dri/card1 and submits through DRM_IOCTL_RKNPU_MEM_CREATE/MEM_MAP/MEM_SYNC/ACTION/SUBMIT with struct rknpu_submit and RKNPU_JOB_PC. It has  |
| `conv_3x3_pad_register_fp16_blocked` | BLOCKED | - | - | - | No Rocket-capable FP16 builder emits and validates CNA_PAD_CON0. conv_new_clean.py comments the pad register out (lines 547-550) and computes valid-only geometry. conv_mesa_fp16.py |
| `conv_split_k_reduction_blocked` | BLOCKED | - | - | - | Split-K reduction requires accumulation of partial products across tiles. Neither inspected Rocket path provides an accumulator or a second reduction pass: conv_0522._execute_conv_ |

### `conv-gemm-vendor`

- Status: **READY**
- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-gemm-vendor/manifest.json`
- Manifest SHA-256: `6160c30fcd6c4f451e65cc0d02de7996f4c94f837142e0f13426f60d37b02a83`
- Manifest generated: `2026-11-05T20:33:06Z`
- READY / BLOCKED: **9 / 2**
- Verified expected oracles: **9** (PASS 9, FAIL 0, ERROR 0, WAITING 0)
- Oracle coverage: **9/9** READY cases were checked against a declared expected file; **2** BLOCKED cases are not scored.

| case | status | expected | max diff | mismatches | notes |
|---|---|---|---:|---:|---|
| `gemm_m2_n2_k1` | PASS | expected.bin,expected_surface.bin | 0 | 0 | GEMM M=2 N=2 K=1; align_in=32 (rows of A padded to K), align_out=32 (output row stride 32 FP32); weight raw is [oc_block16][ic_block32][oc_lane16][ic_lane32] of W[n,k]. |
| `gemm_m1_n16_k32` | PASS | expected.bin,expected_surface.bin | 0 | 0 | GEMM M=1 N=16 K=32; align_in=32 (rows of A padded to K), align_out=32 (output row stride 32 FP32); weight raw is [oc_block16][ic_block32][oc_lane16][ic_lane32] of W[n,k]. |
| `gemm_m2_n16_k32` | PASS | expected.bin,expected_surface.bin | 0 | 0 | GEMM M=2 N=16 K=32; align_in=32 (rows of A padded to K), align_out=32 (output row stride 32 FP32); weight raw is [oc_block16][ic_block32][oc_lane16][ic_lane32] of W[n,k]. |
| `gemm_m4_n32_k64` | PASS | expected.bin,expected_surface.bin | 0 | 0 | GEMM M=4 N=32 K=64; align_in=64 (rows of A padded to K), align_out=32 (output row stride 32 FP32); weight raw is [oc_block16][ic_block32][oc_lane16][ic_lane32] of W[n,k]. |
| `conv_1x1_c1_oc6_h4w4` | PASS | expected.bin | 0 | 0 | conv source=conv_gemm.py; input=NHWC; groups=1 depthwise=False grouped_spatial=False; out_width_stride=16; repeat_submissions=1. |
| `conv_grouped_3x3_c4_oc4_g2_h5w5` | PASS | expected.bin | 0 | 0 | conv source=conv_gemm.py; input=C1HWC2; groups=2 depthwise=False grouped_spatial=True; out_width_stride=12; repeat_submissions=1. |
| `conv_legacy_3x3_c4_oc4_h9w9` | PASS | expected.bin | 0 | 0 | conv source=conv_legacy.py; input=NHWC; groups=1 depthwise=False grouped_spatial=False; out_width_stride=52; repeat_submissions=1. |
| `conv_depthwise_3x3_c3_oc3_h11w28` | PASS | expected.bin | 0 | 0 | conv source=conv_legacy.py; input=C1HWC2; groups=3 depthwise=True grouped_spatial=False; out_width_stride=236; repeat_submissions=2. |
| `conv_py_3x3_c32_oc128_h14w14_fullsetup` | PASS | expected.bin | 0 | 0 | conv source=conv.py; input=C1HWC2; groups=1 depthwise=False grouped_spatial=False; out_width_stride=144; repeat_submissions=1. |
| `conv_byk_c160_h14w14_oc320_k3x3` | BLOCKED | - | - | - | Vendor BY_K conv path uses explicit multi-core task distribution and a multi-task PC chain. Rocket has no core_mask/subcore_task fields and no bundle patch kind for the runtime reg |
| `conv_h40_c160_h40w40_oc320_k3x3` | BLOCKED | - | - | - | Vendor H40 spatial BY_Y conv path distributes six tasks over three cores and uses 17 PC-chain rows. Rocket cannot express the vendor core_mask/subcore_task split, and the PC_BASE_A |

### `pooling`

- Status: **READY**
- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/pooling/manifest.json`
- Manifest SHA-256: `42b7ae1c9cbe80d48b9f59ed2f675bdc280d6daa7b22e720a7eee8794db0afd7`
- Manifest generated: `not declared`
- READY / BLOCKED: **19 / 2**
- Verified expected oracles: **19** (PASS 19, FAIL 0, ERROR 0, WAITING 0)
- Oracle coverage: **19/19** READY cases were checked against a declared expected file; **2** BLOCKED cases are not scored.

| case | status | expected | max diff | mismatches | notes |
|---|---|---|---:|---:|---|
| `fp16_avg_global_k3x5_valid_c8_h3w5` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 16 B, 8 channels, atom=8, tail=0. |
| `fp16_avg_k2s1_pad1_use_cnt0_c8_h1w1` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 64 B, 8 channels, atom=8, tail=0. |
| `fp16_avg_k2s1_pad1_use_cnt7_c8_h1w1` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 64 B, 8 channels, atom=8, tail=0. |
| `fp16_avg_k2s1_valid_c8_h4w4` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 144 B, 8 channels, atom=8, tail=0. |
| `fp16_max_k2s1_pad1_neg_c8_h2w2` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 144 B, 8 channels, atom=8, tail=0. |
| `fp16_max_k2s1_valid_c8_h4w4` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 144 B, 8 channels, atom=8, tail=0. |
| `fp16_max_k2s2_c3_tail_h2w2` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 16 B, 3 channels, atom=8, tail=-99. |
| `fp16_max_k2s2_index_c8_h2w2` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 16 B, 8 channels, atom=8, tail=0. |
| `fp16_max_k3s2_pad1_c8_h4w4` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 64 B, 8 channels, atom=8, tail=0. |
| `fp16_min_k2s1_valid_c8_h4w4` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 144 B, 8 channels, atom=8, tail=0. |
| `fp32_max_k2s2_zero_write_c4_h2w2` | BLOCKED | - | - | - | Source expt/pooling.py docstring lines 17-18 and the case flag expect_unsupported=True (lines 937-962) report that this PROC_PRECISION configuration submits successfully (submit_re |
| `int16_avg_q16_k2s2_valid_c8_h2w2` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 16 B, 8 channels, atom=8, tail=0. |
| `int16_avg_q16_k3x3_valid_c8_h3w3` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 16 B, 8 channels, atom=8, tail=0. |
| `int16_max_k2s2_valid_c8_h2w2` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 16 B, 8 channels, atom=8, tail=0. |
| `int16_min_k2s2_valid_c8_h2w2` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 16 B, 8 channels, atom=8, tail=0. |
| `int32_max_k2s2_zero_write_c4_h2w2` | BLOCKED | - | - | - | Source expt/pooling.py docstring lines 17-18 and the case flag expect_unsupported=True (lines 937-962) report that this PROC_PRECISION configuration submits successfully (submit_re |
| `int8_avg_q16_k2s2_valid_c16_h2w2` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 16 B, 16 channels, atom=16, tail=0. |
| `int8_avg_q16_k3x3_valid_c16_h3w3` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 16 B, 16 channels, atom=16, tail=0. |
| `int8_max_k1s1_valid_c32_h1w1` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 32 B, 32 channels, atom=16, tail=0. |
| `int8_max_k2s2_valid_c16_h2w2` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 16 B, 16 channels, atom=16, tail=0. |
| `int8_min_k2s2_valid_c16_h2w2` | PASS | expected.bin | 0 | 0 | C1HWC2 value region: 16 B, 16 channels, atom=16, tail=0. |

## Caveats

- Host-side oracle comparison only; it does not validate SystemVerilog, the FPGA bitstream, the RK3588 NPU or any device capture.
- The verifier does not import family preparation tools or copy their oracle code; expected*.bin is only the comparison target.
- Device output scan: no declared worker output file is present.  A later device result must be compared separately and must never be replaced by expected*.bin.
- conv-fp16 output BOs contain channel and row padding while expected.bin is logical NCHW.  This verifier compares the logical region; it does not claim byte equality of the raw device output surface.
- conv-gemm-vendor multi-task cases use one terminal task per group/tile.  This verifier checks the numerical decomposition, not PC-chain or core-mask semantics.
- Dilation is not encoded by any READY stream, so no dilation contract is claimed.  conv-simple stride-2/SAME/grouped and the vendor ABI, split-K, pooling INT32/FP32 zero-write probes remain BLOCKED and are not scored.
- Pooling index positions are scored only for the clean window-local `(row << 3) | column` case.  Padded/strided index aliasing is not scored.
- INT8 conv-simple values were chosen by preparation so the donor formula does not clip.  Agreement here does not characterise clipping or saturation.
- Integer Q16 pooling cases were built so the means are exact; they do not characterise integer rounding on non-divisible windows.
- No NaN/Inf/subnormal policy is established.  The comparator treats matching infinity signs as matching only to avoid a false failure on FP16 overflow artifacts; this is not evidence of a hardware special-value contract.
- FP16 oracle values use float64 accumulation and one cast to FP16 (or float32 mean for pooling averages).  A device may accumulate in a different order.
