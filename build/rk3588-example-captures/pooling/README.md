# RK3588 PPU pooling capture bundles

Device-free preparation for the RK3588 PPU pooling examples. No board,
DRM/NPU device or FPGA was opened, and no `ssh`, `scp` or programming
command was run. The later single board worker owns execution under the
capture-queue lock.

## Sources

- `/home/fedora/rk3588/examples/pooling.py` - original PPU matrix.
- `/home/fedora/rk3588/examples/expt/pooling.py` - extended matrix used as
  the primary source for every bundle (source hashes are in `manifest.json`).
  Where the two files differ (for example the INT8/INT16 maximum input
  data), these bundles follow `expt/pooling.py`.

## Bundle layout

Each READY case has `job.json`, `regcmd.bin`, `regcmd.txt`, `in.bin`,
`out_init.bin` and `expected.bin`. BLOCKED cases keep the exact probe
streams but have no `expected.bin`.

`job.json` follows `../CAPTURE_FORMAT.md`: one task at regcmd word offset 0,
4096-byte input/output BOs, and `value32` patches for exactly the two DMA
address QWORDs (`PPU_DST_BASE_ADDR`, `PPU_RDMA_SRC_BASE_ADDR`). The output
buffer is `inout` with `out_init.bin` zeroes so the source's explicit
`output_map[:] = 0` initialization is reproduced.

## Derivation

1. `/usr/bin/python3` imports `expt/pooling.py`; `cases()` supplies the
   hardcoded source matrices and expected values.
2. `make_pool_regcmds()` is called with zero DMA addresses. The exact
   PPU, PPU_RDMA and PC QWORD order is written to `regcmd.bin`; the two
   address QWORD indices become the `job.json` patches.
3. `_pack_cube()` packs each input into the PPU's C1HWC2 surface order
   (16-byte atoms, `ceil(C / atom_channels)` surfaces). The full packed
   bytes, including atom tails, are written to `in.bin`; unused BO bytes
   are zero.
4. `expected.bin` comes from the source host-side `pool_reference()` or
   `maximum_with_index_reference()`, repacked into the output C1HWC2
   layout. Atom tails (for C3) are filled with the source tail value.
   For INDEX_EN the uint16 index area starts at `out_area * 2 * 16`.
5. All buffers are 4096 bytes so DMA bursts cannot run past the BO; only
   the first `layout.*.logical_bytes` bytes are meaningful. The rest of
   `out_init.bin`/`expected.bin` is zero.

The two FP32/INT32 zero-write probes are BLOCKED. The source docstring
states that PROC_PRECISION 4/5 submissions return success but write all
zero, so no valid expected output exists. They are retained only as exact
reproducible probes.

## Coverage

READY 19 / BLOCKED 2 / total 21.

| case | status | dtype | method | kernel | stride | padding | in HxWxC | out HxWxC | INDEX_EN |
|---|---|---|---|---|---|---|---|---|---|
| `fp16_avg_k2s1_valid_c8_h4w4` | READY | float16 | average | 2x2 | 1x1 | valid | 4x4x8 | 3x3x8 | no |
| `fp16_max_k2s1_valid_c8_h4w4` | READY | float16 | maximum | 2x2 | 1x1 | valid | 4x4x8 | 3x3x8 | no |
| `fp16_min_k2s1_valid_c8_h4w4` | READY | float16 | minimum | 2x2 | 1x1 | valid | 4x4x8 | 3x3x8 | no |
| `fp16_avg_global_k3x5_valid_c8_h3w5` | READY | float16 | average | 3x5 | 3x5 | valid | 3x5x8 | 1x1x8 | no |
| `fp16_max_k3s2_pad1_c8_h4w4` (derived) | READY | float16 | maximum | 3x3 | 2x2 | 1/1/1/1 | 4x4x8 | 2x2x8 | no |
| `fp16_max_k2s1_pad1_neg_c8_h2w2` | READY | float16 | maximum | 2x2 | 1x1 | 1/1/1/1 | 2x2x8 | 3x3x8 | no |
| `fp16_avg_k2s1_pad1_use_cnt0_c8_h1w1` (probe) | READY | float16 | average | 2x2 | 1x1 | 1/1/1/1 | 1x1x8 | 2x2x8 | no |
| `fp16_avg_k2s1_pad1_use_cnt7_c8_h1w1` (probe) | READY | float16 | average | 2x2 | 1x1 | 1/1/1/1 | 1x1x8 | 2x2x8 | no |
| `fp16_max_k2s2_index_c8_h2w2` | READY | float16 | maximum | 2x2 | 2x2 | valid | 2x2x8 | 1x1x8 | yes |
| `fp16_max_k2s2_c3_tail_h2w2` | READY | float16 | maximum | 2x2 | 2x2 | valid | 2x2x3 | 1x1x3 | no |
| `int8_max_k2s2_valid_c16_h2w2` | READY | int8 | maximum | 2x2 | 2x2 | valid | 2x2x16 | 1x1x16 | no |
| `int8_min_k2s2_valid_c16_h2w2` | READY | int8 | minimum | 2x2 | 2x2 | valid | 2x2x16 | 1x1x16 | no |
| `int8_avg_q16_k2s2_valid_c16_h2w2` (probe) | READY | int8 | average | 2x2 | 2x2 | valid | 2x2x16 | 1x1x16 | no |
| `int8_avg_q16_k3x3_valid_c16_h3w3` (probe) | READY | int8 | average | 3x3 | 3x3 | valid | 3x3x16 | 1x1x16 | no |
| `int8_max_k1s1_valid_c32_h1w1` | READY | int8 | maximum | 1x1 | 1x1 | valid | 1x1x32 | 1x1x32 | no |
| `int16_max_k2s2_valid_c8_h2w2` | READY | int16 | maximum | 2x2 | 2x2 | valid | 2x2x8 | 1x1x8 | no |
| `int16_min_k2s2_valid_c8_h2w2` | READY | int16 | minimum | 2x2 | 2x2 | valid | 2x2x8 | 1x1x8 | no |
| `int16_avg_q16_k2s2_valid_c8_h2w2` (probe) | READY | int16 | average | 2x2 | 2x2 | valid | 2x2x8 | 1x1x8 | no |
| `int16_avg_q16_k3x3_valid_c8_h3w3` (probe) | READY | int16 | average | 3x3 | 3x3 | valid | 3x3x8 | 1x1x8 | no |
| `int32_max_k2s2_zero_write_c4_h2w2` | BLOCKED | int32 | maximum | 2x2 | 2x2 | valid | 2x2x4 | 1x1x4 | no |
| `fp32_max_k2s2_zero_write_c4_h2w2` | BLOCKED | float32 | maximum | 2x2 | 2x2 | valid | 2x2x4 | 1x1x4 | no |

Coverage groups:

- precision: FP16: 10, INT8: 5, INT16: 4
- method: average: 8, maximum: 8, minimum: 3
- kernel: 2x2: 14, 3x5: 1, 3x3: 3, 1x1: 1
- stride: 1x1: 7, 3x5: 1, 2x2: 9, 3x3: 2
- padded cases: 4; valid cases: 15
- INDEX_EN cases: fp16_max_k2s2_index_c8_h2w2

## Register sequence

All cases use one PPU task. Maximum/minimum streams have 26 QWORDs;
average streams have 28 because `PPU_RECIP_KERNEL_WIDTH` and
`PPU_RECIP_KERNEL_HEIGHT` are inserted after `PPU_POOLING_KERNEL_CFG`.
Order: PPU S_POINTER, PPU_RDMA S_POINTER, input/output dimensions,
`OPERATION_MODE_CFG`, `POOLING_KERNEL_CFG`, optional reciprocals,
padding config/value, destination base/surface stride, `DATA_FORMAT`,
`MISC_CTRL`, PPU_RDMA dimensions/base/line stride/surface stride/format,
PPU_RDMA enable, then `PC_OPERATION_ENABLE=0x60`. `regcmd.txt` decodes
every QWORD for every case.

## Worker requirements

`job.json` carries only the schema's task offset/word count. The mainline
Rocket runner builds `drm_rocket_task` from `regcmd` (u32 DMA address)
and `regcmd_count` only. The source example's `struct_rknpu_task`
`op_idx`, `enable_mask` and interrupt fields are written into its vendor
task BO but are not consumed by `rocket_submit()` (expt/pooling.py
lines 212-234); PPU activation is the `PC_OPERATION_ENABLE=0x60` QWORD
in `regcmd.bin`. The `inout` output is copied from `out_init.bin` and,
per `runner/README.md`, is listed only in `out_bo_handles`.

## BLOCKED cases

`manifest.json` also carries top-level `ready_cases` and `blocked_cases`
lists so the board worker can select only READY jobs.

- `int32_max_k2s2_zero_write_c4_h2w2` - PROC_PRECISION=4, RDMA width 3.
- `fp32_max_k2s2_zero_write_c4_h2w2` - PROC_PRECISION=5, RDMA width 3.

The source reports that both probes submit successfully but write zero.
Their `in.bin`, `regcmd.bin`, `job.json` and `out_init.bin` are retained
for reproduction;
do not compare them to a numeric expected output. Do not submit them in
the board run queue: pointing the runner at this family directory expands
every case, so pass only the 19 READY case directories (or filter by
`manifest.json` status).

## Not bundled

- `int8_average` and `int16_average` (FP17-reciprocal integer average) are
  source-labelled inexact negative controls. Their expected values are
  recorded device observations, not host-derivable, so they are not READY
  host-oracle bundles. Exact integer average is covered by the Q16 cases.
- `maximum_indices_padding_stride` and `maximum_indices_kernel16` are
  probe-only INDEX_EN cases with non-window-local phase / modulo-8 index
  aliasing. The clean `maximum_indices` case is bundled; the padded
  3x3/stride-2 geometry is bundled without INDEX_EN as
  `fp16_max_k3s2_pad1_c8_h4w4`.
- `strided_input_notch_0/2` are probe-only explicit line/surface-stride
  and notch experiments outside the requested small-shape mode matrix.
- `padding_7` and `kernel_stride_16` are larger isolated probes; the
  requested small-shape matrix uses 1x1, 2x2, 3x3 and 3x5 cases.
- The source matrix has no padded INT8/INT16 pooling case. Padded
  windows are therefore covered by the FP16 padded cases only; no
  integer padded variant was invented without source evidence.
- The 2x3 average probes and the three multi-pass (linked submission)
  cases are not part of this single-task bundle.

## Caveats

- `expected.bin` is a host-side NumPy oracle, not a device capture. It
  establishes the intended contract only; it is not evidence of RK3588
  or FPGA behavior.
- FP16 average/global expected values use float32 accumulation followed
  by an FP16 cast. The source tolerance is 0.0625; compare those cases
  with that tolerance rather than demanding byte equality.
- Integer Q16 average cases are built so the means are exact; they do not
  characterize integer rounding on non-divisible windows.
- This is a source-grounded subset, not a full Cartesian product. Mode
  combinations absent from the source matrix (for example padded integer
  pooling or a padded 3x3 average) were not invented.
- `fp16_max_k3s2_pad1_c8_h4w4` is derived from the source padded INDEX_EN
  probe with INDEX_EN removed. Its values use the source host reference,
  but this exact non-index variant was not a separate source case.
- The clean INDEX_EN case uses `(row << 3) | column`. The source documents
  that padded/strided and >7 coordinates alias or lose window-local
  phase; those probe-only index cases are deliberately not scored here.
- No multi-pass/fenced sequence, unpool/upsample, DPU_RDMA or non-PPU
  selector is covered by this family.

## Local validation

Run `/usr/bin/python3 validate.py`. It checks the manifest shape, per-case
file census and hashes, buffer sizes, regcmd length and decode, the exact
PPU/PPU_RDMA/PC QWORD order, both patch indices and their address fields,
and independently recomputes every READY expected buffer from `in.bin`
with the source host oracle. It opens no device.

The queue's authoritative schema checker is also runnable without a board:

```sh
python3 ../runner/validate_bundle.py .
```

It accepts all 21 case directories in this family (it validates schema, not
READY/BLOCKED scoring), and it rejects unknown job.json fields.
