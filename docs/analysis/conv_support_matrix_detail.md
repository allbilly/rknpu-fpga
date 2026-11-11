# Convolution capture support matrix — subagent supplement

Scope: only facts NOT derivable from `build/rk3588-example-captures/*/manifest.json`
(blocked causes, case-level packed layouts, fixture presence, captured-output
presence/divergence, RTL parameterization). Partial: see "Gaps" at the end.

Families / cases:
- `conv-fp16`: 9 READY / 5 BLOCKED (14)
- `conv-gemm-vendor`: 10 READY / 3 BLOCKED (13)
- `conv-simple`: 7 READY / 5 BLOCKED (12)
Total 26 READY / 13 BLOCKED / 39.

## READY status and captured output

| Family | READY | Captured output present | Exact | Tolerance | Known divergence |
|---|---:|---|---:|---:|---:|
| conv-fp16 | 9 | 9/9 | 9 | 0 | 0 |
| conv-gemm-vendor | 10 | 10/10 | 8 | 2 | 0 |
| conv-simple | 7 | 7/7 | 4 | 0 | 3 |

No READY case is oracle-only: every READY case has a real RK3588 Rocket output
BO somewhere under `build/rk3588-example-captures/results/`. Case directories
ship packed inputs/weights/regcmd/oracles only; device outputs live in the
result trees, not in `cases/`.

Result trees:
- conv-fp16: `results/conv-fp16-20261105T222300Z/board-run/conv-fp16/` (9 cases,
  35,392 output bytes, one 54-QWORD task each, all exact).
- conv-gemm-vendor: `results/conv-gemm-vendor-20261105T214000Z/` (8 cases) plus
  `results/conv-gemm-depthwise-rerun-20261105T221115Z/` (both split depthwise
  tasks, corrected 15,104-byte BO). The first vendor run's depthwise BO was
  half the size the stream requires (declared 7,552 B vs DPU two-surface
  15,104 B) and produced zero-filled tails; the rerun is the valid capture.
- conv-simple: `results/conv-simple-20261105T215921Z/` (7 cases, 21,888 bytes).
  Divergences: `conv_simple_fp16_1x1_c32_h8_w8_oc32` FP32-output structural
  placement/zero-fill mismatch (5,941/8,192 bytes, max abs 32.6407);
  `simple_conv_int8_5x5_c8_h8_w8_oc32` 7/512 prefix bytes +1 LSB;
  `simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64` 13/2,304 prefix bytes
  +1 LSB. Tolerance-only in vendor: `gemm_m4_n32_k64` (max 9.5367e-07) and
  `conv_py_3x3_c32_oc128_h14w14_fullsetup` (10/18,432 elements, max 0.015625).

Earlier conv-fp16 two-task tree `results/conv-fp16-20261105T205900Z/` preserves
the BLOCKED parent captures and the task-1-all-zero evidence; it is not current
PASS evidence.

## BLOCKED reasons (not just "BLOCKED")

conv-fp16:
1. `conv_grouped_3x3_c4_h5_w5_oc8_g2` — `MULTITASK_ROCKET_JOB_UNSUPPORTED`.
   Board ran only task 0; task 1 output BO all zero
   (sha256 ef115a0e...). Promoted one-task cases are the runnable form.
2. `conv_splitoc_3x3_c16_h9_w9_oc16` — same multi-task defect; promoted
   one-task cases are runnable.
3. `conv_tiles_vendor_abi_blocked` — vendor-only ABI: `/dev/dri/card1`,
   `DRM_IOCTL_RKNPU_*`, `struct rknpu_submit`/`RKNPU_JOB_PC`; no Rocket path.
4. `conv_3x3_pad_register_fp16_blocked` — no Rocket-capable FP16 builder emits
   `CNA_PAD_CON0`: conv_new_clean comments it out (547-550) and computes
   valid-only geometry; conv_mesa_fp16 emits it but with uint8 zero-point
   semantics. READY padded case is an explicit zero frame, not pad register.
5. `conv_split_k_reduction_blocked` — no accumulation contract: conv_0522
   clears output before each tile and tile offsets are zero; split-OC only.

conv-gemm-vendor:
1. `conv_depthwise_3x3_c3_oc3_h11w28` — multi-task parent; source intentionally
   double-submits depthwise; 104-QWORD stream with two byte-identical 52-word
   halves preserved under `evidence/`.
2. `conv_byk_c160_h14w14_oc320_k3x3` — vendor BY_K 11-row PC chain,
   `npu_submit(task_count=3, core_mask=0, subcores=...)` distributing 1/1/1
   across cores 0/1/2; Rocket has no core_mask/subcore_task, and
   `PC_BASE_ADDRESS` needs a self-referential regcmd address the patch schema
   cannot bind.
3. `conv_h40_c160_h40w40_oc320_k3x3` — vendor H40 17-row PC chain,
   `task_count=6`, 2 tasks on each of 3 cores; same UAPI/patch-schema limits.

conv-simple:
1. `..._stride2` — no source path encodes stride: parser accepts `sN` but
   `_conv_params` ignores it and `make_regs` always writes
   `CNA_CONV_CON3 = 0x9` (stride 1); `simple_conv.py` hardcodes the same value.
2. `..._samepad` — no SAME-pad path: FP16 `make_regs` never writes
   `CNA_PAD_CON0/1`; INT8 writes PAD_CON0=0 and only a zero-point pad fill,
   plus valid-only geometry.
3. `..._unpadded_pack` — C8 pack/align mismatch: `_conv_align_c` returns 16
   but input pack C2 is 8, so `pack_input` writes 8 ch/pixel while
   `CNA_DATA_SIZE1=0x00070010` declares 16 aligned channels; no source contract
   fills channels 5..8.
4. `..._grouped` — FP16 builder has no group register/table entry; only INT8
   `run_conv2d_grouped` slices and resubmits, overwriting shared BOs; would
   need per-group BOs and a PC self-address chain the schema cannot patch.
5. `simple_conv_int8_addition_...` — `addition_input/add_tensor` only change
   `CNA_PAD_CON1` and a CVT scale; `add_tensor` never becomes an address
   register and no addition BO is allocated/submitted.

## Case-level packed layouts (details not in the family manifests)

### conv-fp16 (donor `conv_new_clean.py`; all READY 54-QWORD, patches 21/27/35,
one task at offset 0)

- `conv_1x1_valid_c8_h5_w5_oc8`: input NC1HWC2 C2=8 in 2 C1 planes,
  800 B (2×8×5×5×2). C1 plane 0 = C0..C7, plane 1 = all zero (align_c=16).
  weight = "default" CRS order `[OC][ky][kx][IC]` padded to 16 IC,
  256 B; real OC0..7, IC0..7. output `flat_1x1`: 1,600 B = 4 C1 planes ×
  25 atoms × 8 lanes × 2 B, width stride 25 atoms, align_out_c=32; only
  OC0..7/25 atoms defined.
- `conv_3x3_valid_c4_h9_w9_oc4`: input 2,592 B = 2 planes × 81 pixels × 16 B;
  real C0..C3 in plane 0, plane 1 zero. weight kh-major
  `[tap][OC][align_C=16]`, 1,152 B; real OC0..3, IC0..3. output NC1HWC2
  3,328 B = 4 C1 planes × 52 atoms × 8 lanes × 2 B; 7×7=49 atoms × OC0..3.
- `conv_3x3_stride2_c4_h11_w11_oc4`: input 3,872 B = 2 planes ×121 pixels ×16 B;
  same kh-major 1,152 B; output 1,792 B = 4 planes × 28 atoms ×8 lanes ×2 B,
  5×5=25 atoms × OC0..3.
- `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4`: packed input 3,872 B = 2 planes of
  11×11 pixels ×16 B, one-pixel border explicitly zero, interior 4×9×9;
  same kh-major 1,152 B; output 5,376 B = 4 planes × 84 atoms ×8 lanes ×2 B,
  9×9=81 atoms × OC0..3. This is valid 3x3 on a zero frame, not pad registers.
- `conv_depthwise_3x3_c3_h11_w28_oc3`: input 4,928 B = 1 plane
  (align_c=8, C2=8) × 11×28 pixels ×16 B; real C0..2. weight
  depthwise_spatial_major = 3×3×8 lanes ×2 B = 144 B, only lanes 0..2.
  output 15,104 B = 4 planes × 236 atoms ×8 lanes ×2 B; defined 3 channels ×
  9×26 = 702 FP16. `full_data_bank=False` (data_bank=1, weight_bank=11).
- `conv_grouped_..._g2_task0/task1`: each is a 2-channel group slice.
  input 800 B = 2 C1 planes ×25 pixels ×16 B, real C0..C1, rest zero.
  weight 1,152 B kh-major `[tap][OC4][align_C=16]`, real OC0..3, IC0..1.
  output 768 B = 4 C1 planes ×12 atoms ×8 lanes ×2 B; 3×3=9 atoms × OC0..3.
  Both tasks use the same 54-QWORD template (`29b60f0b...`); only BOs differ.
- `conv_splitoc_...task0/task1`: C16 input shared. input 2,592 B = 2 C1 planes
  ×81 pixels ×16 B, all C0..C15 real. weight 2,304 B kh-major
  `[tap][OC8][align_C=16]` = 9×8×16×2, real IC0..C15. output 3,328 B =
  4 planes ×52 atoms ×8 lanes ×2 B, 49 atoms × OC8 (task0 = OC0..7,
  task1 = OC8..15 of the parent). `full_data_bank=True` (data_bank=11,
  weight_bank=1). Both tasks share one 54-QWORD template (`a60a4448...`).

### conv-gemm-vendor (vendor sources; conv cases 52 QWORD patches 18/24/32;
GEMM 50 QWORD patches 18/24/31; conv.py setup 112 QWORD patches 25/34/61)

- `gemm_m2_n2_k1`, `gemm_m1_n16_k32`, `gemm_m2_n16_k32`, `gemm_m4_n32_k64`:
  input packed A: rows M padded to `align_in` FP16 (row bytes 64 or 128);
  weight packed `[align_out/16][align_in/32][16 OC][32 IC]` block transpose
  (K padded to align_in); output FP32 surface M×align_out row stride
  align_out, expected_surface 4,096 B; logical M×N in `expected.bin`.
  All FP32 output. `gemm_m2_n2_k1` and `gemm_m2_n16_k32` share the identical
  regcmd hash `be934aee...`.
- `conv_1x1_c1_oc6_h4w4`: NHWC input `[H=4][width_stride=4][C=1]` (32 B
  meaningful); weight kh-major OC block × aligned-IC8; output FP16
  `_unpack_flat_1x1_output` align_out_c=16, c2=8, width stride 16 atoms,
  hardware region 512 B; 4×4 atoms × OC0..5 defined.
- `conv_grouped_3x3_c4_oc4_g2_h5w5`: ONE task with groups=2 (not the two-task
  conv-fp16 style). input NC1HWC2 c2=8, c1=1 plane ×5×5×16 = 400 B meaningful;
  grouped-spatial weight path: block-16 `_reorder_grouped_spatial_weights_block16`
  then `_pack_default` (oc-major `[OC][ky][kx][IC]`, padded to 16 IC),
  1,152 B. output grouped-spatial unpack with plane_stride 12 atoms,
  hardware 384 B.
- `conv_legacy_3x3_c4_oc4_h9w9`: NHWC input `[9][width_stride=10][C4]`
  (720 B meaningful; width padded 9→10); weight kh-major with c2_out =
  align_c = 8 (`[OC4][IC8][3][3]`, 576 B meaningful); output
  `_unpack_flat_1x1_output` with align_out_c=16, c2=8, width stride 52 atoms,
  hardware 1,664 B (196 defined).
- `conv_depthwise_..._task0/task1`: depthwise spatial weights
  `[blocks=1][kh3][kw3][C2=8]` = 144 B meaningful; input 4,928 B
  (c1=1 plane ×11×28×16); output align_out_c=16, c2=8, width stride 236 atoms,
  DPU SURFACE_ADD=7552 and DATA_CUBE_CHANNEL=31 -> requires 15,104 B (two
  7,552-byte surface groups); 702 defined values.
- `conv_py_3x3_c32_oc128_h14w14_fullsetup`: input 12,544 B = 4 C1 planes
  (C32, c2=8) ×196 pixels ×16 B; weight kh-major 73,728 B = 8 OC blocks ×
  9 taps ×16 OC lanes ×32 IC ×2 B; output 36,864 B = 16 C1 planes
  (align_out_c=128, c2=8) ×144 atoms ×8 lanes ×2 B; all 144 atoms ×128 OC
  defined. Full 108-QWORD setup row (no planner tiles).

### conv-simple (expt/conv_simple.py FP16; kernel_6_18/simple_conv.py INT8;
FP16 READY 51 declared words / 52 file words, patches 18/24/32; INT8 69/70,
patches 20/26/36/61)

- FP16 C4 (`1x1_c4`, `3x3_c4`, `5x5_c4`): input NHWC
  `[H][width_stride=8][C=4]` = 512 B. weights kh-major chunks of 16 OC
  `[oc_chunk][kh][kw][oc_lane][align_c=8]`: 256 B (1x1), 2,304 B (3x3),
  6,400 B (5x5). outputs `unpack_output` order `[c1][out_width_stride][c2]`:
  1x1 = FP32 c2=4, c1=4, width stride 64, 4,096 B (no padding);
  3x3 = FP16 c2=8, c1=2, 1,152 B; 5x5 = FP16 c2=8, c1=2, 512 B.
  These C4 cases use `align_c == pack C2 == 8` and NHWC (the source RGB
  packing class).
- `conv_simple_fp16_1x1_c32_h8_w8_oc32`: input 4,096 B =
  `[c1=4][H=8][width_stride=8][c2=8]`; weight 2,048 B = 2 OC blocks ×
  32 aligned IC; output FP32 c2=4, c1=8, width stride 64, 8,192 B.
  This is the case with the structural FP32-output mismatch on device.
- `conv_simple_fp16_3x3_c16_h8_w8_oc32`: input 2,048 B = 2 C1 planes ×
  64 pixels ×16 B; weight 9,216 B = 2 OC blocks × 3×3 ×16 OC ×16 IC ×2;
  output FP16 c2=8, c1=4, width stride 36, 2,304 B.
- `simple_conv_int8_5x5_c8_h8_w8_oc32`: input 2,048 B
  `[channel_group][x][y][16]`, values `(u-0x80)&0xff`; weight 51,200 B
  `[oc_group][ic_group][x][y][oc_lane][ic_lane]` uint8; bias 128 B int32;
  output 1,024 B BO, oracle prefix 512 B, order `[channel_group][x][y][16]`,
  logical NHWC `[1,4,4,32]`.
- `simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64`: input 8,192 B;
  weight 1,152 B depthwise layout; bias 256 B; output 4,608 B BO, prefix
  2,304 B, logical `[1,6,6,64]`.

## Pinned fixtures (`tests/conv/fixtures`, `tests/ppu_pooling/fixtures`)

Present (`tests/conv/fixtures/`, 8 dirs):
- `conv_1x1_valid_c8_h5_w5_oc8` — a.bin, w.bin, expected.bin, out.bin,
  regcmd.bin, README only (no manifest/job/provenance/device_capture).
- `conv_3x3_valid_c4_h9_w9_oc4`
- `conv_3x3_stride2_c4_h11_w11_oc4`
- `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4`
- `conv_grouped_3x3_c4_h5_w5_oc8_g2_task0`
- `conv_grouped_3x3_c4_h5_w5_oc8_g2_task1`
- `conv_splitoc_3x3_c16_h9_w9_oc16_task0`
- `conv_splitoc_3x3_c16_h9_w9_oc16_task1`
All spatial fixtures carry manifest/job/provenance/device_capture/device_out,
packed a/w, expected, regcmd, source_input_nchw, source_weight_nchw.

Absent:
- conv-fp16: no fixture for `conv_depthwise_3x3_c3_h11_w28_oc3`.
- conv-gemm-vendor: none of the 10 READY cases.
- conv-simple: none of the 7 READY cases.
- `tests/ppu_pooling/fixtures` contains only pooling fixtures, no conv.

## What the strict 3x3 front needs (exact profiles)

RTL: `rtl/cmac/rk_conv_3x3_valid_c4_front.sv` parameters `INPUT_H/W`,
`OUTPUT_H/W`, `STRIDE`, `INPUT_CHANNELS` (1..16), `KERNELS` (1..16),
`ALIGN_C` (>=C, <=32), `PACK_C2` fixed 8, `TAPS=9` fixed, valid-only geometry
(`IN = (OUT-1)*STRIDE + 3`). Core profile decoders in
`rk_conv_3x3_valid_c4_profile.sv` select one exact 54-QWORD template via
`STRIDE2`/`PAD1_ZERO_FRAME`/`GROUPED_C2`/`SPLIT_OC_C16`.

Distinct exact-profile sets exercised by captured cases:
1. REAL_C=4, REAL_K=4, ALIGN_C=16, PACK_C2=8, 9×9→7×7, stride 1, 9 taps
   (valid C4; `conv_3x3_valid_c4_h9_w9_oc4`).
2. REAL_C=4, REAL_K=4, ALIGN_C=16, PACK_C2=8, 11×11→5×5, stride 2, 9 taps
   (`conv_3x3_stride2_c4_h11_w11_oc4`).
3. REAL_C=4, REAL_K=4, ALIGN_C=16, PACK_C2=8, effective 11×11→9×9, stride 1,
   9 taps, explicit zero frame (`conv_3x3_pad1_zero_frame_c4_h9_w9_oc4`).
4. REAL_C=2, REAL_K=4, ALIGN_C=16, PACK_C2=8, 5×5→3×3, stride 1, 9 taps
   (`conv_grouped_..._g2_task0/task1`).
5. REAL_C=16, REAL_K=8, ALIGN_C=16, PACK_C2=8, 9×9→7×7, stride 1, 9 taps
   (`conv_splitoc_..._task0/task1`; requires two C1 planes, which the current
   front revision loads via `PLANES`/`plane_index`).

So the geometry-independent parameter tuples are
(4,4,16,8), (2,4,16,8), (16,8,16,8); with geometry/stride distinguished, 5
exact profiles. If 1x1/5x5/GEMM/depthwise are excluded as operation classes,
these 5 cover every captured FP16 dense 3x3 kh-major case.

Blocked by format (input/weight/output packing, op class or dtype), NOT by
geometry alone:
- conv-simple `conv_simple_fp16_3x3_c4_h8_w8_oc16`: geometry 8×8→6×6 is
  compatible, but input is NHWC C4 (8 B/pixel), align_c=8 and K=16 with
  source-kh-major OC-block weights; current front consumes 16 B/pixel
  NC1HWC2 C2=8 with ALIGN_C=16.
- conv-simple `conv_simple_fp16_3x3_c16_h8_w8_oc32`: input NC1HWC2-compatible
  C16 but K=32 exceeds the front/frame K<=16; REAL_K cannot be represented.
- conv-gemm-vendor `conv_py_3x3_c32_oc128_h14w14_fullsetup`: REAL_C=32 > 16
  and REAL_K=128 >> 16; full 108-QWORD setup profile; format/profile blocked.
- conv-gemm-vendor `conv_grouped_3x3_c4_oc4_g2_h5w5`: same 5×5→3×3 geometry
  as profile 4, but weight is grouped-spatial block-16/default-oc-major, not
  kh-major tap-major; single task with group register; format blocked.
- conv-gemm-vendor `conv_legacy_3x3_c4_oc4_h9w9`: exact same 9×9→7×7 geometry
  as profile 1, but NHWC width_stride=10, ALIGN_C=8, flat_1x1 output with
  align_out_c=16; format blocked.
- Both depthwise cases (conv-fp16 C3/OC3/G3 and vendor C3/OC3/G3): 3×3 but
  CONV_MODE=3, depthwise_spatial weight stream (one kernel, 8/16 lanes) and
  flat_1x1 output with width stride 236; no dense kh-major K=4 semantics.
- conv-fp16 `conv_1x1_valid_c8_h5_w5_oc8` and vendor
  `conv_1x1_c1_oc6_h4w4`: operation class 1x1; 1x1 C8 additionally uses
  flat_1x1 output, 1x1 C1 uses NHWC/align_c=8.
- conv-simple `conv_simple_fp16_5x5_c4_h8_w8_oc16` and
  `simple_conv_int8_5x5_c8_h8_w8_oc32`: 5×5 (25 taps), outside 3×3 front.
- conv-simple `conv_simple_fp16_1x1_c32_h8_w8_oc32`: 1x1 plus FP32 output
  (c2=4).
- conv-simple INT8 depthwise C64/G64: dtype and depthwise layout.
- All four GEMM cases: GEMM (M×N×K) class, not convolution geometry.
- Every manifest-BLOCKED case: excluded by the reason in the section above
  (multi-task, vendor ABI/PC chain, pad register, split-K, stride encoding,
  C8 pack/align, grouped resubmit chain, addition-input ABI).

## Gaps / not re-verified

- No per-case read of conv-gemm-vendor `job.json` was repeated for the 10 READY
  bundles; their packing details above come from the manifest + source packer
  reads (`conv_gemm.py`, `conv_legacy.py`, `conv.py`, `gemm.py`).
- Fixture internals were only listed/partially read; the eight conv fixtures'
  manifests were not re-hashed in this pass.
- No FPGA/Vivado execution is involved or claimed by this report.
