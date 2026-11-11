# FP16 convolution capture bundles (device-free preparation)

This family prepares small FP16 convolution capture bundles for the
mainline Rocket NPU on the RK3588. It was prepared without any board,
`/dev/accel`, `/dev/dri`, `ssh`, `scp` or FPGA access. A later single worker
owns the board and runs the queue under the shared lease.

- READY cases: **9**
- BLOCKED cases: **5**
- Bundle directory: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-fp16`
- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-fp16/manifest.json`
- Schema: `../CAPTURE_FORMAT.md`
- Prepared with `/usr/bin/python3` 3.14.8 and NumPy 2.4.6; the family validator is stdlib-only.

## One-task split after the two-task diagnostic

The RK3588 Rocket v6.18 board path executed only task 0 of a two-task job.
In the original conv-fp16 run, task 0 matched exactly while task 1's output BO
was all zero for both multi-task cases. The diagnostic run then submitted four
derived one-task bundles:

- `diag_grouped_task0` → `conv_grouped_3x3_c4_h5_w5_oc8_g2_task0`
- `diag_grouped_task1` → `conv_grouped_3x3_c4_h5_w5_oc8_g2_task1`
- `diag_splitoc_task0` → `conv_splitoc_3x3_c16_h9_w9_oc16_task0`
- `diag_splitoc_task1` → `conv_splitoc_3x3_c16_h9_w9_oc16_task1`

All four one-task jobs matched their `expected_out0.bin` / `expected_out1.bin`
oracles exactly (`submit_ret=0`, 0 mismatches, max abs diff 0.0). The original
grouped two-task control left task 1's 768-byte output BO all zero
(sha256 `ef115a0e0c15cdc41958ca46b5b14b456115f4baec5e3ca68599d2a8f435e3b8`).

The four one-task bundles are promoted here as READY cases with exactly one
task at `regcmd_offset_words=0`, 54 QWORDs. Their expected files are
byte-identical copies of the original per-task oracle files. The two original
two-task cases are retained as BLOCKED evidence with
`MULTITASK_ROCKET_JOB_UNSUPPORTED`; they must not be submitted.

Evidence bytes are hash-bound in each case's `files` map:

- promoted READY cases: `evidence_diagnostic_out0.bin` or
  `evidence_diagnostic_out1.bin`, matching `promotion_evidence.diagnostic_out_sha256`;
- parent BLOCKED cases: `evidence_task1_zero_output.bin`, matching
  `board_evidence.task1_zero_sha256` (and the grouped control field on the
  grouped parent);
- the top-level `split_promotion.board_evidence` uses only the path
  `grouped_control_task1_zero_evidence`, not an unbound hash string.

The evidence files are at the case root rather than under a nested
`evidence/` directory because audit v1.3.0 rejects nested directories inside
READY bundles (`files.nested_dir`). This keeps the evidence hash-bound and the
audit at PASS with no warnings.

Evidence:

- `../conv-fp16-task-diagnostic/bundles/`
- `../results/conv-fp16-task-diagnostic-20261105T211500Z/`
- `../results/conv-fp16-20261105T205900Z/`

## Source inspection

| Source | Submission path | FP16 conv status | Used here |
|---|---|---|---|
| `examples/kernel_6_18/conv_new_clean.py` | Rocket via `rocket_runtime` (`drm_rocket_*`) | Cleanest current FP16 direct/grouped/depthwise/split-OC builder; valid-only geometry; pad register commented out | Yes, all READY cases |
| `examples/kernel_6_18/simple_conv_fp16.py` | Rocket via its own `DRM_IOCTL_ROCKET_*` | FP16 conv; stride fixed at 1; no pad register; older duplicate builder | No |
| `examples/kernel_6_18/conv_mesa_fp16.py` | Rocket via its own `DRM_IOCTL_ROCKET_*` | Mesa port; pad registers emitted, but register path uses uint8 zero-point/quantized semantics | No; cited for the pad blocker |
| `examples/kernel_6_18/conv_new.py` | Rocket via `rocket_runtime` | Older `conv_new` variant; superseded by `conv_new_clean.py` | No |
| `examples/kernel_6_18/conv_new_trscrs.py` | Rocket via `rocket_runtime` | Same builder with CRS translation helper; no pad register | No |
| `examples/kernel_6_18/conv_0522.py` | Rocket via `rocket_runtime` | Explicit Y/K tile planner and split enum, but tile offsets/accumulation are placeholders in the executor | No; cited for the split-K blocker |
| `examples/kernel_6_18/conv_draft.py` | Rocket via `rocket_runtime` | Draft; `PAD_MODE_SAME` flag does not emit `CNA_PAD_CON0` | No |
| `examples/conv_tiles.py` | Vendor rknpu (`/dev/dri/card1`, `DRM_IOCTL_RKNPU_*`) | Tiled family corpus with PC/subcore task policy | No; BLOCKED (vendor ABI) |

## Cases

| Case | Status | Tasks | Shape | Path |
|---|---|---:|---|---|
| `conv_1x1_valid_c8_h5_w5_oc8` | READY | 1 | C8 5x5 -> OC8 5x5, k1x1, s1, g1 | direct pointwise |
| `conv_3x3_valid_c4_h9_w9_oc4` | READY | 1 | C4 9x9 -> OC4 7x7, k3x3, s1, g1 | direct spatial |
| `conv_3x3_stride2_c4_h11_w11_oc4` | READY | 1 | C4 11x11 -> OC4 5x5, k3x3, s2, g1 | direct spatial, stride 2 |
| `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` | READY | 1 | C4 9x9 -> OC4 9x9, k3x3, s1, g1 | zero-frame padded |
| `conv_depthwise_3x3_c3_h11_w28_oc3` | READY | 1 | C3 11x28 -> OC3 9x26, k3x3, s1, g3 | depthwise direct |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2_task0` | READY | 1 | C2 5x5 -> OC4 3x3, k3x3, s1, g1 | grouped task 0/2 |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2_task1` | READY | 1 | C2 5x5 -> OC4 3x3, k3x3, s1, g1 | grouped task 1/2 |
| `conv_splitoc_3x3_c16_h9_w9_oc16_task0` | READY | 1 | C16 9x9 -> OC8 7x7, k3x3, s1, g1 | split-OC task 0/2 |
| `conv_splitoc_3x3_c16_h9_w9_oc16_task1` | READY | 1 | C16 9x9 -> OC8 7x7, k3x3, s1, g1 | split-OC task 1/2 |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2` | BLOCKED | 2 | C4 5x5 -> OC8 3x3, k3x3, g2 | parent evidence; Rocket multi-task failure |
| `conv_splitoc_3x3_c16_h9_w9_oc16` | BLOCKED | 2 | C16 9x9 -> OC16 7x7, k3x3, s1 | parent evidence; Rocket multi-task failure |
| `conv_tiles_vendor_abi_blocked` | BLOCKED | - | vendor tiled corpus | vendor rknpu ABI |
| `conv_3x3_pad_register_fp16_blocked` | BLOCKED | - | C4 9x9 -> OC4, k3x3, pad1 | no Rocket FP16 pad register |
| `conv_split_k_reduction_blocked` | BLOCKED | - | C16 9x9 -> OC16, split-K | no accumulation path |

## Derivation

1. The donor module is loaded with a host-only `rocket_runtime` stub. The stub
   returns host byte buffers and fixed fake DMA addresses; it performs no ioctl
   and opens no device. The donor's own `_conv_params`,
   `_pack_cdma_dc_feature_input_fp16`, `pack_weights` and
   `make_conv2d_regs_from_params` produce the shape choices, packed bytes and
   register body. No register values are hand-written.
2. Each task body is passed through the donor's
   `write_regs_to_npu_task([body])`; its single-task terminal tail
   (`PC_BASE_ADDRESS=0`, `PC_REGISTER_AMOUNTS=0`, `VERSION=0`,
   `OPERATION_ENABLE=0xd`) is copied from the donor, not re-derived.
3. The three DMA address registers in each body
   (`CNA_FEATURE_DATA_ADDR=0x1070`, `CNA_DCOMP_ADDR0=0x1110`,
   `DPU DST_BASE_ADDR=0x4020`) are written as zero placeholders and declared
   as `value32` patches. `regcmd.bin` is the concatenated little-endian QWORD
   stream; each task range is aligned to an even number of QWORDs exactly as
   the donor offsets do.
4. Input and weight bytes are exactly the donor packer output. Output BO sizes
   are `ceil(align_out_c/8) * out_width_stride * 8 * 2` bytes, matching the
   donor readback count. Outputs are not written by preparation.
5. `expected*.bin` is a host-side NumPy oracle, not a device capture. The
   primary oracle is the donor's `compute_expected_nchw` (float64 accumulation
   of FP16 operands, rounded once to FP16); an independent explicit loop oracle
   is cross-checked at generation time. The donor's own acceptance tolerance is
   `atol=0.2`.
6. A local layout round-trip packs the oracle into the donor NC1HWC2/flat-1x1
   raw order, runs the donor unpack function, and requires exact FP16 equality.
7. The four promoted one-task cases are copied from the validated diagnostic
   bundles. `regcmd.bin` is the byte-identical 54-QWORD slice of the parent
   task, with patches rebound from 75/81/89 to 21/27/35 as appropriate.
   `expected_out0.bin` / `expected_out1.bin` are byte-identical copies of the
   original parent task oracles. The original two-task directories are left
   untouched and remain BLOCKED evidence.

## Bundle ABI choices and caveats

- **Exactly one task per READY job.** The RK3588 Rocket v6.18 board path
  executed only task 0 of a two-task job; the second output BO stayed all zero.
  The four one-task promotions preserve the validated per-task command streams.
  Do not merge them back into one `tasks` array.
- **Parent evidence is frozen.** The two original two-task case directories
  remain in `cases/` and their manifest hashes are checked. They are marked
  `BLOCKED / MULTITASK_ROCKET_JOB_UNSUPPORTED` and must not be staged or
  submitted.
- **Task descriptor fields are worker defaults.** The donor also sets
  `op_idx=1`, `enable_mask=0xd`, `int_mask=(1<<8)|(1<<9)` and
  `int_clear=0x1ffff` on each `struct_rknpu_task`. The bundle `tasks` array only
  carries `regcmd_offset_words` and `regcmd_words`, so the worker must apply its
  standard Rocket descriptor defaults. The donor's `npu_reset` call is a no-op
  on the mainline runtime.
- **Padded case is a zero frame, not `CNA_PAD_CON0`.** The clean FP16 builder
  comments out the pad register and computes valid-only geometry. The READY
  padded case feeds an explicit zero border through the valid 3x3 path. A true
  pad-register FP16 case is BLOCKED in the manifest.
- **Stride 2 is source-implemented but table-uncovered.** `_conv_params` and the
  `CNA_CONV_CON3` builder accept stride 2; the donor shape table only exercises
  stride 1. The stride-2 case is a deliberate source-supported variant.
- **Oracle is not hardware evidence.** FP16 accumulation order, aligned-channel
  padding and the stride-tail atoms are not modeled byte-for-byte. Compare the
  worker's raw `out*.bin` after applying the donor unpack; do not compare raw BO
  bytes against a fabricated raw oracle. The promoted cases use the original
  per-task oracles, not diagnosed board outputs.
- **No special-value guarantee.** The oracle uses ordinary random finite inputs
  in [-2, 2); NaN/inf/subnormal behavior is outside this family.

## Blocked cases

### `conv_grouped_3x3_c4_h5_w5_oc8_g2`

Two-task grouped convolution, `MULTITASK_ROCKET_JOB_UNSUPPORTED`. Board task 0
matched exactly; task 1's output BO was all zero. Retained as evidence. Use the
two promoted one-task cases instead.

### `conv_splitoc_3x3_c16_h9_w9_oc16`

Two-task split-OC convolution, `MULTITASK_ROCKET_JOB_UNSUPPORTED`. Board task 0
matched exactly; task 1's output BO was all zero. Retained as evidence. Use the
two promoted one-task cases instead.

### `conv_tiles_vendor_abi_blocked`

Tiled direct-spatial/split-family convolution corpus; vendor rknpu DRM submission path.

Vendor-only ABI: conv_tiles.py opens /dev/dri/card1 and submits through DRM_IOCTL_RKNPU_MEM_CREATE/MEM_MAP/MEM_SYNC/ACTION/SUBMIT with struct rknpu_submit and RKNPU_JOB_PC. It has no rocket_runtime or drm_rocket_task path. Re-hosting its register builder would require a new BO/submission adapter and fresh verification; producing a READY bundle would imply an unverified Rocket ABI. No registers were invented.

### `conv_3x3_pad_register_fp16_blocked`

True CNA_PAD_CON0 FP16 3x3 same-padding case.

No Rocket-capable FP16 builder emits and validates CNA_PAD_CON0. conv_new_clean.py comments the pad register out (lines 547-550) and computes valid-only geometry. conv_mesa_fp16.py does emit CNA_PAD_CON0, but its register path is the Mesa uint8 zero-point semantics (for example BS_OW_OP uses 0x80 - weights_zero_point and OUT_CVT/EW scales are quantized), so using it would change the numerical contract. A true pad-register FP16 case is therefore blocked pending source evidence and tests. The READY padded case uses an explicit zero frame instead.

### `conv_split_k_reduction_blocked`

Split-K reduction convolution, where partial K tiles would be summed.

Split-K reduction requires accumulation of partial products across tiles. Neither inspected Rocket path provides an accumulator or a second reduction pass: conv_0522._execute_conv_tiles clears the output BO before every tile and _tile_to_desc leaves all tile offsets at zero; conv_new_clean has no K-split for spatial conv. Only split-OC is encoded as READY. Adding split-K would require a new accumulation contract, not just more tasks.

## Local validation

```sh
/usr/bin/python3 /home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-fp16/tools/validate_bundles.py
/usr/bin/python3 /home/fedora/rknpu-fpga/build/rk3588-example-captures/runner/validate_bundle.py \
  /home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-fp16/cases/<case>
/usr/bin/python3 /home/fedora/rknpu-fpga/build/rk3588-example-captures/team/oracle-conv/verify.py --no-write
/usr/bin/python3 /home/fedora/rknpu-fpga/build/rk3588-example-captures/team/audit/audit.py \
  --root /home/fedora/rknpu-fpga/build/rk3588-example-captures
```

The family validator checks JSON shape, one-task READY jobs at offset 0, buffer
declarations and file sizes, regcmd length, task ranges, terminal tails, every
address-register placeholder and its patch, patch index ranges, output layout
sizes, preserved BLOCKED evidence hashes and manifest hashes. It does not run a
device and does not accept a CPU result as a capture.

Current promotion status (host-side only): family validator PASS; shared runner
validator 9/9 READY cases `OK`; independent oracle verifier 9/9 READY cases
PASS; independent bundle audit v1.3.0 PASS with **0 unverified manifest
hashes**. No device output was used or fabricated.

## Board execution

The later worker stages only READY cases and runs one case at a time under the
shared board lease. Each READY `job.json` has exactly one task at offset 0. The
worker copies each `buffers[].input` into a fresh BO, submits the task, reads
back each `out`/`inout` BO and writes `buffers[].output`. Preparation does not
submit, program or flash anything.

`tools/gen_bundles.py` generates the original seven-case set and does not apply
the one-task split. The current promoted manifest is authoritative. If the
original set must be regenerated, run
`tools/promote_split_cases.py` afterwards to re-apply the four one-task cases
and restore the BLOCKED parent entries.
