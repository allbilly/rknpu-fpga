# RK3588 example-capture queue status

Snapshot: **2026-11-05T20:44:53Z**  
Index: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/team/queue-index/QUEUE.json`  
Host: `/home/fedora/rknpu-fpga` at `6aa8e7a8054311ff7e60db5de6fd397a22540c82`  
Tooling: `runner/rocket_run.py` SHA256 `a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd`; `runner/validate_bundle.py` SHA256 `2aa8503e338a47bef064fbd47cf24a6d695eacf6171ab966f8c70b6b3cb2b064`.

This index was built without board access: **no ssh/scp, no submit, no FPGA program/flash**. It records device-free preparation only. Nothing below is marked captured unless a results directory contains real output BOs.

## Summary

| Family | Manifest READY | Manifest BLOCKED | Runner-valid READY | Prepared (not run) | Verified | Verified not re-runnable | Captured unverified | Blocked total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ew-int` | 15 | 3 | 14 | 0 | 15 | 1 | 0 | 3 |
| `ew-fp16` | 54 | 0 | 54 | 54 | 0 | 0 | 0 | 0 |
| `fdiv-systematic` | 8 | 0 | 8 | 8 | 0 | 0 | 0 | 0 |
| `conv-fp16` | 7 | 3 | 7 | 7 | 0 | 0 | 0 | 3 |
| `conv-simple` | 7 | 5 | 0 | 0 | 0 | 0 | 0 | 12 |
| `conv-gemm-vendor` | 9 | 2 | 8 | 8 | 0 | 0 | 0 | 3 |
| `pooling` | 19 | 2 | 19 | 19 | 0 | 0 | 0 | 2 |
| **Total** | **119** | **15** | **110** | **96** | **15** | **1** | **0** | **23** |

Blocked total = 15 manifest BLOCKED + 8 manifest-READY cases that fail the current official runner validator. One further verified case is not re-runnable under the current runner but is not counted as blocked because its device capture and oracle comparison are valid. Prepared + verified + blocked = 96 + 15 + 23 = 134 manifest cases.

Currently running on board: **0 confirmed** (the board was not queried; see below). Captured but unverified: **0**.

## Verified

### `ew-int` — 15/15 verified

- Results: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/ew-int-20261105T200154Z`
- Evidence: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/ew-int-20261105T200154Z-evidence`
- 15 real output BOs (`out.bin`, 4096 B each), 15 `capture.json`, `submit_ret == 0` for 15/15.
- Oracle: `compare.json` reports 15 PASS / 0 FAIL / 0 missing over 61440 compared bytes. Independent masked comparison at snapshot: **15/15 PASS** (`logs/verify_ew-int_results.log`).
- Re-run caveat: 14/15 verified cases are also valid under the current runner. 1 verified case (`int16_add_to_int32_c8_w1`, 31 words/31 QWORDs) would need one zero QWORD of padding before a rerun; the existing capture is unchanged and remains verified evidence.
- Board: `orangepi5`, kernel `6.18.24-current-rockchip64`, Python `3.14.4`, `/dev/accel/accel0`, driver `rocket`; run `2026-11-05T20:04:25Z` to `2026-11-05T20:04:25Z`.
- Executor: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/board-worker/ew-int/ew_int_run.py`  
  SHA256 `1ed990e7b1617ad606ae688980987e89e241789304d9b0e57a92cfa368b88e9a`. The current `runner/rocket_run.py` is a different executor; see the re-run caveat.
- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/ew-int/manifest.json`  
  SHA256 `a67136d463c7f15c97afec929b9d55b8986a33c4cbe5377c64cd7dd502d46340`
- Scope: RK3588 Rocket integer EW only. This is not FPGA, SystemVerilog or full RK3588 NPU evidence.
- Attempt 1 `results/ew-int-20261105T200154Z-evidence/attempt1-runner-keyerror` has 15 `capture.json` but 0 `out.bin`; the runner raised `KeyError: 'durations'` before submit. It is **not** a capture and is not counted.

## Currently running on board

**None confirmed from host-side evidence.** This index did not query the board, so it cannot prove the board is idle. A worker may be running outside this host's visibility.

- Last known board worker: `ew-int` run `ew-int-20261105T200154Z`, 15 cases, 15 `submit_ret==0`, 15 oracle PASS, finished `2026-11-05T20:04:25Z`.
- Results copied back: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/ew-int-20261105T200154Z` (15 real `out.bin`).
- Exclusive lock: `/home/opencode-agent/rk3588-npu.lock`.

**Gate before rank 1:** do not start while any capture/rocket process is present. Acquire `flock -x -w 900 /home/opencode-agent/rk3588-npu.lock` around the whole runner invocation, record board identity and `pgrep`, and use a fresh output root. If the current worker still holds the lock, wait; do not launch a second copy.

## Captured but unverified

**None.** The only results directory with real output BOs is `ew-int-20261105T200154Z`, and it is verified. The first-attempt evidence directory has `capture.json` files but zero `out.bin`, so it is not a capture. No other family has a results directory with device output. Per the capture rule, no other case is marked captured.

## Prepared

These are individual READY cases that pass the current official runner validator, have no results directory with real output BOs, and are waiting for the single board worker. A family may also contain blocked cases; the counts below are prepared cases only.

| Family | Prepared | Oracle | Runner validation | Family validation | Execution note |
|---|---:|---|---|---|---|
| `ew-fp16` | 54 | present (54/54 with expected) | 54/54 OK | PASS | Prepared, not run. 54 single-task cases. Split into 6 op sub-batches of 9 cases; run FDIV last. |
| `fdiv-systematic` | 8 | none (0/8 with expected) | 8/8 OK | PASS | Prepared, not run. 8 single-task cases, 64-byte BOs, 22-QWORD stream. First in the queue. |
| `conv-fp16` | 7 | present (7/7 with expected) | 7/7 OK | PASS | Prepared, not run. 7 READY cases; grouped/split-OC are two-task jobs. Run single-task cases first, grouped/split-OC last. |
| `conv-gemm-vendor` | 8 | present (9/9 with expected) | 8/9 OK | PASS | Prepared, not run. 8 runner-valid cases. The depthwise case is manifest-READY but runner-invalid and must be skipped until the bundle or runner is fixed. |
| `pooling` | 19 | present (19/19 with expected) | 19/19 OK | PASS | Prepared, not run. 19 READY cases; 2 BLOCKED probes also have job.json and must be excluded by explicit case selection. |

`ew-int` is verified, not prepared; it is deliberately not in the prepared table. `conv-simple` has zero prepared cases: all 7 READY cases are deferred for the odd-word fetch extent. `conv-gemm-vendor` has 8 prepared cases and 1 manifest-READY case that is runner-invalid; see Blocked.

## Blocked

23 cases must not be submitted: 15 manifest BLOCKED plus 8 manifest-READY but runner-invalid.

| Family | Case | Manifest | State | Reason |
|---|---|---|---|---|
| `ew-int` | `int32_div_c8_w2` | BLOCKED | blocked | The source proves DIV/FLOOR/CEIL use floating-point semantics and are not integer operations (OPERATIONS[...]['integer_supported'] = False). There is no trustworthy integer oracle; bundling them as integer EW would mi... |
| `ew-int` | `fp16_four_input_sum_c8_w1` | BLOCKED | blocked | The only multi-input sum in either source is FP16, with FP32 BRDMA/NRDMA operands. This family is integer-only (ew-int); an FP16/FP32 mixed case needs its own oracle and belongs in an ew-fp16 family. It is not an INT8... |
| `ew-int` | `fp16_bs_bn_relu_prelu_c8_w1` | BLOCKED | blocked | ReLU-X and PReLU are emitted only in the FP16 BS/BN auxiliary stages. No integer ReLU path exists in either source, and ReLU6 and batchnorm are never emitted at all. Not an integer elementwise case. |
| `conv-fp16` | `conv_tiles_vendor_abi_blocked` | BLOCKED | blocked | Vendor-only ABI: conv_tiles.py opens /dev/dri/card1 and submits through DRM_IOCTL_RKNPU_MEM_CREATE/MEM_MAP/MEM_SYNC/ACTION/SUBMIT with struct rknpu_submit and RKNPU_JOB_PC. It has no rocket_runtime or drm_rocket_task... |
| `conv-fp16` | `conv_3x3_pad_register_fp16_blocked` | BLOCKED | blocked | No Rocket-capable FP16 builder emits and validates CNA_PAD_CON0. conv_new_clean.py comments the pad register out (lines 547-550) and computes valid-only geometry. conv_mesa_fp16.py does emit CNA_PAD_CON0, but its regi... |
| `conv-fp16` | `conv_split_k_reduction_blocked` | BLOCKED | blocked | Split-K reduction requires accumulation of partial products across tiles. Neither inspected Rocket path provides an accumulator or a second reduction pass: conv_0522._execute_conv_tiles clears the output BO before eve... |
| `conv-simple` | `conv_simple_fp16_1x1_c4_h8_w8_oc16` | READY | blocked_runner_invalid | Manifest READY but the official runner validator rejects this bundle: job.json tasks[0]: declared words [0, 51) fetch as QWORD pairs [0, 52), which exceed regcmd.bin's 51 QWORDs. The task declares an odd regcmd word c... |
| `conv-simple` | `conv_simple_fp16_3x3_c4_h8_w8_oc16` | READY | blocked_runner_invalid | Manifest READY but the official runner validator rejects this bundle: job.json tasks[0]: declared words [0, 51) fetch as QWORD pairs [0, 52), which exceed regcmd.bin's 51 QWORDs. The task declares an odd regcmd word c... |
| `conv-simple` | `conv_simple_fp16_5x5_c4_h8_w8_oc16` | READY | blocked_runner_invalid | Manifest READY but the official runner validator rejects this bundle: job.json tasks[0]: declared words [0, 51) fetch as QWORD pairs [0, 52), which exceed regcmd.bin's 51 QWORDs. The task declares an odd regcmd word c... |
| `conv-simple` | `conv_simple_fp16_1x1_c32_h8_w8_oc32` | READY | blocked_runner_invalid | Manifest READY but the official runner validator rejects this bundle: job.json tasks[0]: declared words [0, 51) fetch as QWORD pairs [0, 52), which exceed regcmd.bin's 51 QWORDs. The task declares an odd regcmd word c... |
| `conv-simple` | `conv_simple_fp16_3x3_c16_h8_w8_oc32` | READY | blocked_runner_invalid | Manifest READY but the official runner validator rejects this bundle: job.json tasks[0]: declared words [0, 51) fetch as QWORD pairs [0, 52), which exceed regcmd.bin's 51 QWORDs. The task declares an odd regcmd word c... |
| `conv-simple` | `simple_conv_int8_5x5_c8_h8_w8_oc32` | READY | blocked_runner_invalid | Manifest READY but the official runner validator rejects this bundle: job.json tasks[0]: declared words [0, 69) fetch as QWORD pairs [0, 70), which exceed regcmd.bin's 69 QWORDs. The task declares an odd regcmd word c... |
| `conv-simple` | `simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64` | READY | blocked_runner_invalid | Manifest READY but the official runner validator rejects this bundle: job.json tasks[0]: declared words [0, 69) fetch as QWORD pairs [0, 70), which exceed regcmd.bin's 69 QWORDs. The task declares an odd regcmd word c... |
| `conv-simple` | `conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2` | BLOCKED | blocked | No source path encodes a convolution stride. The FP16 shape parser accepts an sN field (expt/conv_simple.py:228-238), but _conv_params ignores it (lines 297-311) and make_regs always writes CNA_CONV_CON3 = (1<<3)|1 =... |
| `conv-simple` | `conv_simple_fp16_3x3_c8_h8_w8_oc16_samepad` | BLOCKED | blocked | No SAME-padding path exists in the named sources. The FP16 make_regs() never writes CNA_PAD_CON0 or CNA_PAD_CON1 (expt/conv_simple.py:383-440) and _conv_params computes out_h/out_w = in_h/in_w - k + 1, i.e. valid-only... |
| `conv-simple` | `conv_simple_fp16_3x3_c8_h8_w8_oc16_unpadded_pack` | BLOCKED | blocked | This C8 shape cannot be packed safely with the FP16 builder. For in_c=8, _conv_align_c returns 16 (expt/conv_simple.py:283-286), but _conv_input_pack_c2 returns 8 (lines 289-294). pack_input() then writes c1*c2 = 8 ch... |
| `conv-simple` | `conv_simple_fp16_grouped_3x3_c8_h8_w8_oc8_g2` | BLOCKED | blocked | The grouped path cannot be expressed safely from these sources. The FP16 make_regs() has no group-count register and its known-supported table has no grouped entry (expt/conv_simple.py:207-217,383-440). The only group... |
| `conv-simple` | `simple_conv_int8_addition_c8_h8_w8_oc32` | BLOCKED | blocked | The source's addition-input knobs are not a usable ABI. use_shape() reads addition_input/add_tensor (kernel_6_18/simple_conv.py:83-84), but build_conv_regs() uses them only to change CNA_PAD_CON1 and the single-channe... |
| `conv-gemm-vendor` | `conv_depthwise_3x3_c3_oc3_h11w28` | READY | blocked_runner_invalid | Manifest READY but the official runner validator rejects this bundle: job.json tasks[0] and tasks[1] overlap in the QWORD-pair fetch range ([0, 52) from 52 words and [0, 52) from 52 words). The manifest records repeat... |
| `conv-gemm-vendor` | `conv_byk_c160_h14w14_oc320_k3x3` | BLOCKED | blocked | Vendor BY_K conv path uses explicit multi-core task distribution and a multi-task PC chain. Rocket has no core_mask/subcore_task fields and no bundle patch kind for the runtime regcmd address in PC_BASE_ADDRESS. |
| `conv-gemm-vendor` | `conv_h40_c160_h40w40_oc320_k3x3` | BLOCKED | blocked | Vendor H40 spatial BY_Y conv path distributes six tasks over three cores and uses 17 PC-chain rows. Rocket cannot express the vendor core_mask/subcore_task split, and the PC_BASE_ADDRESS rows require runtime regcmd-ad... |
| `pooling` | `fp32_max_k2s2_zero_write_c4_h2w2` | BLOCKED | blocked | Source expt/pooling.py docstring lines 17-18 and the case flag expect_unsupported=True (lines 937-962) report that this PROC_PRECISION configuration submits successfully (submit_ret==0) but writes all zero, while the... |
| `pooling` | `int32_max_k2s2_zero_write_c4_h2w2` | BLOCKED | blocked | Source expt/pooling.py docstring lines 17-18 and the case flag expect_unsupported=True (lines 937-962) report that this PROC_PRECISION configuration submits successfully (submit_ret==0) but writes all zero, while the... |

**High-risk selection rule:** `pooling` contains two BLOCKED probes with `job.json`; passing the family directory would submit them. `conv-gemm-vendor` contains one manifest-READY case with overlapping duplicate tasks; passing the family directory would record a runner FAIL. `conv-simple` contains five blocked case directories without `job.json`, so family-directory expansion is also not clean there. Use explicit READY case directories for all three.

## Verified but not re-runnable

- `ew-int/int16_add_to_int32_c8_w1`: captured and oracle-verified on 2026-11-05, but the current official runner rejects the bundle because it declares an odd regcmd word count (QWORD-pair fetch extends one QWORD past `regcmd.bin`). Add one zero QWORD of padding before any rerun. This case is **not** in the blocked count because the existing device output and oracle comparison are valid.

## Family paths and manifest hashes

| Family | Path | Manifest SHA256 | Bytes | Generated |
|---|---|---|---:|---|
| `ew-int` | `/home/fedora/rknpu-fpga/build/rk3588-example-captures/ew-int` | `a67136d463c7f15c97afec929b9d55b8986a33c4cbe5377c64cd7dd502d46340` | 52264 | not recorded |
| `ew-fp16` | `/home/fedora/rknpu-fpga/build/rk3588-example-captures/ew-fp16` | `dfa201f37dbe4a36c80ba8ef4f63cdab7730b9496897d216990ea2c287d4d2db` | 157475 | 2026-11-05T20:01:44Z |
| `fdiv-systematic` | `/home/fedora/rknpu-fpga/build/rk3588-example-captures/fdiv-systematic` | `a28f6c7bae6dce9b533523fac069ce59a25d455c515a5821ed2b54e7f4e8505b` | 109949 | 2026-11-05T20:01:19Z |
| `conv-fp16` | `/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-fp16` | `ae7acc1bcdd224defd38b7c082cf5edc168db4b0673afbafbe7754ba1f439282` | 34811 | 2026-11-05T20:28:46.470666+00:00 |
| `conv-simple` | `/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-simple` | `67e9f069f5664bee73d58da7f93d83e9d911d1c1e639c7ec35268a4ad9cad655` | 42994 | 2026-11-05T20:23:14Z |
| `conv-gemm-vendor` | `/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-gemm-vendor` | `e5eee29ab32ff09a7556af8d98d9f07ea21dca2c690c47cbfd3eeaf254b2adb2` | 40125 | 2026-11-05T20:33:06Z |
| `pooling` | `/home/fedora/rknpu-fpga/build/rk3588-example-captures/pooling` | `42b7ae1c9cbe80d48b9f59ed2f675bdc280d6daa7b22e720a7eee8794db0afd7` | 93391 | 2026-11-06 |

If a manifest hash no longer matches, the family changed after this snapshot. Stop and re-index; do not execute the changed bundle against this plan.

## Source examples

Paths and hashes are as recorded in the family manifests. The `conv-fp16` manifest also records additional inspected sources that were not selected for the READY bundles.

### `ew-int`

- `/home/fedora/rk3588/examples/kernel_6_18/elementwise_int.py` — primary integer EW register builder and Rocket tail  
  SHA256 `825c7c2166eed48fd73fc1d31655238928b0fd5677df539d17f7301dc671d329`
- `/home/fedora/rk3588/examples/expt/elementwise_int.py` — cross-check integer EW paths and operation table  
  SHA256 `1c6a43b0d928b744420f4db1762527f5bbb52c7cc92dc2d1ef0aba2ff94b95f8`

### `ew-fp16`

- `/home/fedora/rk3588/examples/elementwise.py` — primary FP16 EW register body, terminal tail and donor oracle  
  SHA256 `242ad9262254f85b1b426ecc4da76735c0541be9dbe57f812417128e8297e0a0`
- `/home/fedora/rk3588/examples/simple_add.py` — cross-check EW_CFG and 8-lane width  
  SHA256 `838b3145a9bd925c5be9ae3ea154b539970f3a69f0099021c02080de50cb0963`
- `/home/fedora/rk3588/experimental/kernel_6_18/elementwise.py` — cross-check EW_CFG and CPU operation oracle  
  SHA256 `7f90bb9d4add99bbbb490d3711ac31d2e7ba44629520a3b74c54e5ffb52825f2`
- `/home/fedora/rknpu-fpga/model/profile.py` — reviewed register/EW_CFG whitelist used by preparation  
  SHA256 `9ec427d601bbfe78197063135a369b0e9945ee2f7bfc2e5737fb97f62f30ba78`

### `fdiv-systematic`

- `/home/fedora/rk3588/examples/elementwise.py` — FDIV task register body, operand classes, terminal PC tail  
  SHA256 `242ad9262254f85b1b426ecc4da76735c0541be9dbe57f812417128e8297e0a0`

### `conv-fp16`

- `/home/fedora/rk3588/examples/kernel_6_18/conv_new_clean.py` — selected Rocket-capable FP16 conv builder and oracle  
  SHA256 `f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51`
- Additional inspected sources:
  - `/home/fedora/rk3588/examples/kernel_6_18/conv_new_clean.py`
  - `/home/fedora/rk3588/examples/kernel_6_18/simple_conv_fp16.py`
  - `/home/fedora/rk3588/examples/kernel_6_18/conv_mesa_fp16.py`
  - `/home/fedora/rk3588/examples/kernel_6_18/conv_new.py`
  - `/home/fedora/rk3588/examples/kernel_6_18/conv_new_trscrs.py`
  - `/home/fedora/rk3588/examples/kernel_6_18/conv_0522.py`
  - `/home/fedora/rk3588/examples/kernel_6_18/conv_draft.py`
  - `/home/fedora/rk3588/examples/conv_tiles.py`

### `conv-simple`

- `/home/fedora/rk3588/examples/expt/conv_simple.py` — FP16 generic command builder, Rocket tail and FP16 oracle  
  SHA256 `c1dac1d8bded072f50ed0953c9ec457050c1bcacfa285918c6539937bc5f1431`
- `/home/fedora/rk3588/examples/conv_simple.py` — cross-reference; same generic make_regs  
  SHA256 `6134263cb50f77fa050bb900c8243e89ac0e29c3f82254c4a02a6d1adb7b1d9a`
- `/home/fedora/rk3588/examples/kernel_6_18/simple_conv.py` — INT8 quantized builder, depthwise/5x5 path and donor oracle  
  SHA256 `40e5c935b57c568d67bfcf44dcba327116e7bde6aa9ee5b22bb2c7bf958ebfd6`
- `/home/fedora/rk3588/examples/kernel_6_18/conv_legacy.py` — shape-table analogues for 5x5 and depthwise  
  SHA256 `5d2aa637ffdd4608151347796d495847a10344637468f75e60b186b849904942`

### `conv-gemm-vendor`

- `/home/fedora/rk3588/examples/gemm.py` — GEMM register builder and test table  
  SHA256 `df0f4b98a1fa265b549ae0be682de1b68b9e23bb8cc8cd110a06e2f4b19e6fe6`
- `/home/fedora/rk3588/examples/conv_gemm.py` — vendor conv/GEMM spatial builder  
  SHA256 `eeb584b025c16091e0f0aff20c23989f7ec99ce9c32b3431ea220eaa578440ae`
- `/home/fedora/rk3588/examples/conv_legacy.py` — legacy conv builder and shape table  
  SHA256 `b4cc1f57ef782fe3f89ec61d4b94f841b2a2820a912609f3755fbf517f9efad9`
- `/home/fedora/rk3588/examples/conv.py` — full 108-QWORD setup-row conv builder  
  SHA256 `07c1595785a3e9cc0d2dd07e6e447a9b3b964fde87310a0d2e68c01d363d2a32`

### `pooling`

- `/home/fedora/rk3588/examples/expt/pooling.py` — extended PPU pooling matrix; primary bundle source  
  SHA256 `2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e`
- `/home/fedora/rk3588/examples/pooling.py` — original PPU pooling matrix; cross-check  
  SHA256 `f4823489e2d06690c11ff01c1659de51523111ed8e793a9ec8b7848db5894e9f`

## Recommended serialized execution order

One board owner, one case at a time, one exclusive lock. Rank 1 starts only after the current worker releases the lock and the pgrep check is clean. Copy results back and rehash before the next rank.

| Rank | Family | Cases | Selection | Oracle | Why / risk |
|---:|---|---:|---|---|---|
| 1 | `fdiv-systematic` | 8 | family directory (all 8 cases READY; no BLOCKED job.json) | none (raw 64-byte output.bin only) | Smallest buffers and command stream, one terminal task, exact validated template. First smoke test after the lock gate. Risk: Special-value operand classes; no oracle; a failure is informative and must not be scored against a CPU division. |
| 2 | `conv-fp16` | 7 | family directory; single-task cases first, then conv_grouped_3x3_c4_h5_w5_oc8_g2 and conv_splitoc_3x3_c16_h9_w9_oc16 | host NumPy naive conv; unpack raw out*.bin first | Small, selected-source FP16 conv family with complete local validation and an oracle for every READY case. Risk: Grouped/split-OC use two independent terminal tasks; zero-frame pad and stride-2 are source-supported variants, not table-covered. |
| 3 | `conv-gemm-vendor` | 8 | explicit 8 runner-valid case directories; exclude conv_depthwise_3x3_c3_oc3_h11w28 | host-numpy expected.bin / expected_surface.bin | Small GEMM and conv cases with oracles; tiny GEMMs provide quick low-risk coverage. Risk: Vendor-ABI-derived; one READY bundle is runner-invalid. Do not pass the family directory. |
| 4 | `pooling` | 19 | explicit 19 READY case directories only; exclude fp32_max_k2s2_zero_write_c4_h2w2 and int32_max_k2s2_zero_write_c4_h2w2 | host NumPy source pool reference; tolerance/index/out_init rules | Moderate case count, simple PPU streams, complete oracles. Runs after the small conv/GEMM families. Risk: Two BLOCKED probes have job.json. Family-directory expansion would submit them. Explicit case selection is mandatory. |
| 5 | `ew-fp16` | 54 | 6 op sub-batches of 9 cases: ADD, SUB, MUL, MAX, NEG, FDIV; explicit case directories per sub-batch | donor CPU NumPy; asserted prefix only | Per-case work is tiny, but this is the largest family. Run last to avoid occupying the board for a long single family. Risk: FDIV is outside the strict FP16 EW RTL profile; NEG is MUL by -1.0; oracle covers only the asserted prefix. |

**Control:** ew-int is already verified. Do not schedule a rerun in this queue. One verified case (int16_add_to_int32_c8_w1) is not re-runnable under the current runner without one QWORD of padding because it declares 31 words in a 31-QWORD regcmd.bin. Use ew-int as a board-health control only if the board, kernel/driver or source revision changed, and pad/regenerate it first.

The order deliberately starts with the smallest, simplest prepared family (`fdiv-systematic`, 8 cases, 64-byte BOs) and the small conv/GEMM families, then the moderate pooling family, and leaves the 54-case `ew-fp16` family for last. It does not schedule any board work in parallel with the current worker.

Per-case acceptance follows `BOARD_RUN_PLAN.md`: `submit_ret == 0`; every declared output file exists at its declared size; `capture.json` records the real BO addresses, hashes and durations; the output is stored unchanged; any oracle comparison is separate and labelled. A failing case is recorded and the worker moves to the next case; no retry, no reset, no fabricated output.

### Deferred until the bundle is fixed

- `conv-simple` (7 READY cases): All 7 READY cases fail the current official runner validation because the task declares 51 or 69 regcmd words while regcmd.bin contains exactly 51 or 69 QWORDs. Rocket fetches the count as QWORD pairs and reads one extra QWORD. Add one zero QWORD of padding (or use an even task count) and regenerate/revalidate before scheduling. The family validator passes, but it does not model the current runner's fetch extent. Re-entry: If fixed, pass only the 7 READY case directories (the five BLOCKED case directories have no job.json), insert after conv-fp16 (rank 2) and before conv-gemm-vendor, and re-index first because the manifest and bundle hashes will change.

## Local validation evidence

All checks were host-only. `runner/validate_bundle.py` imports no device and never opens `/dev/accel/*`. The writer validators were rerun on byte-identical scratch copies under this team directory, then the copies were removed; the logs are retained, and no family bundle was modified. The repository-wide `make test` suite was not used as evidence for this index; the family validators and the official runner validator were run directly.

| Family | Runner validator | Family validator | Combined | Log |
|---|---|---|---|---|
| `ew-int` | 14/15 OK (1 FAIL) | PASS | MIXED | `logs/validate_ew-int-copy2.log` |
| `ew-fp16` | 54/54 OK | PASS | PASS | `logs/validate_ew-fp16-final.log` |
| `fdiv-systematic` | 8/8 OK | PASS | PASS | `logs/validate_fdiv-systematic-copy2.log` |
| `conv-fp16` | 7/7 OK | PASS | PASS | `logs/validate_conv-fp16-final3.log` |
| `conv-simple` | 0/7 OK (7 FAIL) | PASS | FAIL | `logs/validate_conv-simple-final3.log` |
| `conv-gemm-vendor` | 8/9 OK (1 FAIL) | PASS | MIXED | `logs/validate_conv-gemm-vendor-final4.log` |
| `pooling` | 19/19 OK | PASS | PASS | `logs/validate_pooling-final.log` |

Runner validator final result: **110/119 OK, 9 FAIL**, exit `1`. The failures are: 7 `conv-simple` READY cases (51/69 declared words fetch as 52/70 QWORD pairs from 51/69-QWORD regcmd files), 1 `conv-gemm-vendor` READY case (`conv_depthwise_3x3_c3_oc3_h11w28`, overlapping duplicate task ranges), and 1 `ew-int` verified case (`int16_add_to_int32_c8_w1`, 31 words vs 31 QWORDs; not re-runnable without padding).

Family validator notes: `ew-int`: Rerun on a byte-identical copy: 15 READY PASS, 3 BLOCKED shape checks PASS. The family's recorded validation/*.json and *.txt also PASS. Current runner validation is 14/15: int16_add_to_int32_c8_w1 (31 words/31 QWORDs) is verified but not re-runnable without one QWORD of padding. `ew-fp16`: NumPy 2.4.6; 54 cases, 54 oracle recomputes, 0 mismatches, 0 structural errors. `fdiv-systematic`: Rerun on a byte-identical copy: 2150 structural checks, exact 22-QWORD template, 8 cases. No expected.bin is created by design. `conv-fp16`: 7 READY, 3 BLOCKED; schema, sizes, task ranges, tails, patches, layouts and manifest hashes PASS. `conv-simple`: Family validator PASS for the final 7 READY/5 BLOCKED manifest, but all 7 READY cases fail the current official runner validation: 51/69 declared words in a 51/69-QWORD regcmd.bin fetch as 52/70 QWORD pairs. Deferred until padded and regenerated. `conv-gemm-vendor`: Family validator PASS for 9 READY/2 BLOCKED, but it accepts repeat_submissions=2. The official runner validator rejects the depthwise case's duplicate task ranges; 8/9 READY cases are runner-valid. `pooling`: 19 READY, 2 BLOCKED; schema, hashes, regcmd decode, patch indices and all READY oracles PASS. An initial run raced a concurrent prepare.py write and failed an artifact size check; the final rerun passes.

The initial `pooling` run and the first `conv-simple` copy raced concurrent preparation writes; both final reruns pass. The final results are the ones recorded here.

## Oracle status

| Family | Oracle status | READY with expected | READY without expected | Kinds / note |
|---|---|---:|---:|---|
| `ew-int` | present | 15 | 0 | expected.bin + expected.mask.bin; masked byte equality over the full 4096-byte output BO. Host-python formula, not device data. 0xFF mask bytes are asserted; padding is not. |
| `ew-fp16` | present | 54 | 0 | expected.bin per case covers only the first logical_count halfwords. Donor CPU NumPy oracle, explicitly not a device capture. Compare the asserted prefix only; trailing padding is not asserted. |
| `fdiv-systematic` | none | 0 | 8 | oracle: none for all 8 cases. No expected.bin exists. The raw output.bin (64 bytes) is the characterization record; do not substitute a CPU division result. |
| `conv-fp16` | present | 7 | 0 | host_numpy_naive_conv expected.bin for all 7 READY cases. Grouped and split-OC cases also carry expected_out0.bin, expected_out1.bin and expected_combined.bin. Host oracle only; unpack raw out*.bin before comparing. |
| `conv-simple` | present | 7 | 0 | numpy_naive_valid_conv for the 5 FP16 cases and numpy_naive_quantized_conv for the 2 INT8 cases. expected.bin is a logical-layout oracle; raw BO output must be unpacked first. Host oracle only. |
| `conv-gemm-vendor` | present | 9 | 0 | host-numpy expected.bin for all 9 READY cases; GEMM cases also carry expected_surface.bin. FP64 accumulation rounded to the hardware output dtype with recorded tolerance. Host oracle only. |
| `pooling` | present | 19 | 0 | numpy-source-pool-reference expected.bin for all 19 READY cases. FP16 average uses a recorded tolerance; INDEX_EN cases compare the uint16 index region; inout cases start from out_init.bin. Host oracle only. |

No oracle is device data. The only oracle comparison against real device output is the verified `ew-int` masked comparison. All other `expected.bin` files are host-side references for the later worker.

## Risks and caveats

- **HIGH — conv-gemm-depthwise-runner-invalid**: conv-gemm-vendor/cases/conv_depthwise_3x3_c3_oc3_h11w28 is manifest READY but job.json has two tasks both at [0,52). The official runner validator rejects the overlap. The family validator passes because it models repeat_submissions=2. Do not submit this case; pass the other 8 case directories explicitly.
- **HIGH — conv-simple-odd-word-runner-invalid**: All 7 conv-simple READY cases fail the current official runner validation: 51/69 declared words fetch as 52/70 QWORD pairs, but regcmd.bin has only 51/69 QWORDs. The family validator passes because it does not model the QWORD-pair fetch extent. Defer conv-simple until the bundle adds one zero QWORD of padding and is regenerated/revalidated.
- **MEDIUM — ew-int-verified-not-rerunnable**: ew-int/cases/int16_add_to_int32_c8_w1 is verified from the 2026-11-05 board run (31 words, 31 QWORDs), but the current runner would fetch 32 QWORDs. Do not rerun it without one QWORD of padding. The captured evidence remains valid for the earlier executor.
- **HIGH — pooling-blocked-job-json**: pooling contains two BLOCKED probes with job.json. Passing the family directory would submit them. Pass only the 19 READY case directories.
- **MEDIUM — conv-simple-evidence-scope**: The 5 FP16 1x1 cases select FP32 output; mainline Rocket execution of that stream is not separately evidenced. 5x5 and INT8 shapes are generic derivations, not known-supported table entries. INT8 is not FP16 EW-slice evidence.
- **MEDIUM — fdiv-no-oracle**: All 8 fdiv-systematic cases have oracle: none. Their raw output.bin is a characterization record; a CPU division result must not be substituted or used to score them.
- **MEDIUM — conv-fp16-not-pc-linked**: Grouped and split-OC conv-fp16 cases are encoded as independent terminal tasks, not a PC-linked chain. Oracle comparison needs the donor unpack, not raw-BO equality.
- **MEDIUM — ew-fp16-scope**: FDIV is outside the strict FP16 EW RTL profile and NEG is MUL by -1.0 in the donor path. The family is the largest queue (54 cases); split by op and run FDIV last.
- **MEDIUM — concurrent-preparation**: Several family manifests were still being regenerated during this snapshot. All hashes are recorded above. If a manifest hash no longer matches, stop and re-index; do not execute a changed bundle against this plan.
- **HIGH — board-state-unobservable**: No board query was made. The queue must not overlap the current board worker. Start only after the exclusive lock is acquired and pgrep shows no capture process.
- **MEDIUM — evidence-scope**: The only verified capture is ew-int on RK3588 Rocket. It does not validate SystemVerilog, the FPGA image or the full RK3588 NPU. No other family has device output.

## Case census

Full per-case state is in `QUEUE.json`. This census lists every manifest case by family. `READY` here is the manifest status; per-case executability is shown in the state column.

### `ew-int`

- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/ew-int/manifest.json`
- Counts: 15 READY, 3 BLOCKED, 18 total
- READY: `int8_add_c8_w1` (verified), `int8_max_c8_w1` (verified), `int8_min_c8_w1` (verified), `int8_mul_c8_w1` (verified), `int16_add_c8_w1` (verified), `int16_minus_c8_w1` (verified), `int16_mul_c8_w1` (verified), `int32_add_c8_w2` (verified), `int32_max_c8_w2` (verified), `int32_mul_int16_operand_c8_w2` (verified), `int8_add_c9_w1_layout` (verified), `int16_add_c9_w1_layout` (verified), `int16_minus_c9_w1_layout` (verified), `int32_add_c9_w1_layout` (verified), `int16_add_to_int32_c8_w1` (verified; not re-runnable)
- BLOCKED: `int32_div_c8_w2`, `fp16_four_input_sum_c8_w1`, `fp16_bs_bn_relu_prelu_c8_w1`

### `ew-fp16`

- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/ew-fp16/manifest.json`
- Counts: 54 READY, 0 BLOCKED, 54 total
- READY: `add_p1_n8` (prepared), `add_p2_n8` (prepared), `add_p1_n9` (prepared), `add_p2_n9` (prepared), `add_p1_n33` (prepared), `add_p2_n33` (prepared), `add_p1_n1` (prepared), `add_p1_n7` (prepared), `add_p1_n1024` (prepared), `sub_p1_n8` (prepared), `sub_p2_n8` (prepared), `sub_p1_n9` (prepared), `sub_p2_n9` (prepared), `sub_p1_n33` (prepared), `sub_p2_n33` (prepared), `sub_p1_n1` (prepared), `sub_p1_n7` (prepared), `sub_p1_n1024` (prepared), `mul_p1_n8` (prepared), `mul_p2_n8` (prepared), `mul_p1_n9` (prepared), `mul_p2_n9` (prepared), `mul_p1_n33` (prepared), `mul_p2_n33` (prepared), `mul_p1_n1` (prepared), `mul_p1_n7` (prepared), `mul_p1_n1024` (prepared), `max_p1_n8` (prepared), `max_p2_n8` (prepared), `max_p1_n9` (prepared), `max_p2_n9` (prepared), `max_p1_n33` (prepared), `max_p2_n33` (prepared), `max_p1_n1` (prepared), `max_p1_n7` (prepared), `max_p1_n1024` (prepared), `neg_p1_n8` (prepared), `neg_p2_n8` (prepared), `neg_p1_n9` (prepared), `neg_p2_n9` (prepared), `neg_p1_n33` (prepared), `neg_p2_n33` (prepared), `neg_p1_n1` (prepared), `neg_p1_n7` (prepared), `neg_p1_n1024` (prepared), `fdiv_p1_n8` (prepared), `fdiv_p2_n8` (prepared), `fdiv_p1_n9` (prepared), `fdiv_p2_n9` (prepared), `fdiv_p1_n33` (prepared), `fdiv_p2_n33` (prepared), `fdiv_p1_n1` (prepared), `fdiv_p1_n7` (prepared), `fdiv_p1_n1024` (prepared)
- BLOCKED: none

### `fdiv-systematic`

- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/fdiv-systematic/manifest.json`
- Counts: 8 READY, 0 BLOCKED, 8 total
- READY: `fdiv_class_rows_00_01` (prepared), `fdiv_class_rows_02_03` (prepared), `fdiv_class_rows_04_05` (prepared), `fdiv_class_rows_06_07` (prepared), `fdiv_class_rows_08_09` (prepared), `fdiv_class_rows_10_11` (prepared), `fdiv_class_rows_12_13` (prepared), `fdiv_class_rows_14_15` (prepared)
- BLOCKED: none

### `conv-fp16`

- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-fp16/manifest.json`
- Counts: 7 READY, 3 BLOCKED, 10 total
- READY: `conv_1x1_valid_c8_h5_w5_oc8` (prepared), `conv_3x3_valid_c4_h9_w9_oc4` (prepared), `conv_3x3_stride2_c4_h11_w11_oc4` (prepared), `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` (prepared), `conv_depthwise_3x3_c3_h11_w28_oc3` (prepared), `conv_grouped_3x3_c4_h5_w5_oc8_g2` (prepared), `conv_splitoc_3x3_c16_h9_w9_oc16` (prepared)
- BLOCKED: `conv_tiles_vendor_abi_blocked`, `conv_3x3_pad_register_fp16_blocked`, `conv_split_k_reduction_blocked`

### `conv-simple`

- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-simple/manifest.json`
- Counts: 7 READY, 5 BLOCKED, 12 total
- READY: `conv_simple_fp16_1x1_c4_h8_w8_oc16` (runner-invalid), `conv_simple_fp16_3x3_c4_h8_w8_oc16` (runner-invalid), `conv_simple_fp16_5x5_c4_h8_w8_oc16` (runner-invalid), `conv_simple_fp16_1x1_c32_h8_w8_oc32` (runner-invalid), `conv_simple_fp16_3x3_c16_h8_w8_oc32` (runner-invalid), `simple_conv_int8_5x5_c8_h8_w8_oc32` (runner-invalid), `simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64` (runner-invalid)
- BLOCKED: `conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2`, `conv_simple_fp16_3x3_c8_h8_w8_oc16_samepad`, `conv_simple_fp16_3x3_c8_h8_w8_oc16_unpadded_pack`, `conv_simple_fp16_grouped_3x3_c8_h8_w8_oc8_g2`, `simple_conv_int8_addition_c8_h8_w8_oc32`

### `conv-gemm-vendor`

- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/conv-gemm-vendor/manifest.json`
- Counts: 9 READY, 2 BLOCKED, 11 total
- READY: `gemm_m2_n2_k1` (prepared), `gemm_m1_n16_k32` (prepared), `gemm_m2_n16_k32` (prepared), `gemm_m4_n32_k64` (prepared), `conv_1x1_c1_oc6_h4w4` (prepared), `conv_grouped_3x3_c4_oc4_g2_h5w5` (prepared), `conv_legacy_3x3_c4_oc4_h9w9` (prepared), `conv_depthwise_3x3_c3_oc3_h11w28` (runner-invalid), `conv_py_3x3_c32_oc128_h14w14_fullsetup` (prepared)
- BLOCKED: `conv_byk_c160_h14w14_oc320_k3x3`, `conv_h40_c160_h40w40_oc320_k3x3`

### `pooling`

- Manifest: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/pooling/manifest.json`
- Counts: 19 READY, 2 BLOCKED, 21 total
- READY: `fp16_avg_global_k3x5_valid_c8_h3w5` (prepared), `fp16_avg_k2s1_pad1_use_cnt0_c8_h1w1` (prepared), `fp16_avg_k2s1_pad1_use_cnt7_c8_h1w1` (prepared), `fp16_avg_k2s1_valid_c8_h4w4` (prepared), `fp16_max_k2s1_pad1_neg_c8_h2w2` (prepared), `fp16_max_k2s1_valid_c8_h4w4` (prepared), `fp16_max_k2s2_c3_tail_h2w2` (prepared), `fp16_max_k2s2_index_c8_h2w2` (prepared), `fp16_max_k3s2_pad1_c8_h4w4` (prepared), `fp16_min_k2s1_valid_c8_h4w4` (prepared), `int16_avg_q16_k2s2_valid_c8_h2w2` (prepared), `int16_avg_q16_k3x3_valid_c8_h3w3` (prepared), `int16_max_k2s2_valid_c8_h2w2` (prepared), `int16_min_k2s2_valid_c8_h2w2` (prepared), `int8_avg_q16_k2s2_valid_c16_h2w2` (prepared), `int8_avg_q16_k3x3_valid_c16_h3w3` (prepared), `int8_max_k1s1_valid_c32_h1w1` (prepared), `int8_max_k2s2_valid_c16_h2w2` (prepared), `int8_min_k2s2_valid_c16_h2w2` (prepared)
- BLOCKED: `fp32_max_k2s2_zero_write_c4_h2w2`, `int32_max_k2s2_zero_write_c4_h2w2`

## What this does not prove

- It does not prove the board is idle or that any prepared family will submit successfully. No board command was run.
- It does not validate SystemVerilog, the FPGA image, timing or the full RK3588 NPU. The only device evidence is `ew-int` on RK3588 Rocket.
- It does not make any host-side oracle a device capture. `expected.bin` is a test target, not a fallback result.
- It does not establish numerical special-value policy for the prepared FP16 families; those remain candidate behavior until device differential tests.

