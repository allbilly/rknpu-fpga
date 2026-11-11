# conv-fp16 board run 20261105T222300Z

Status: **PASS** — 9/9 READY cases `status=OK`, `submit_ret=0`; all 9 matched the oracle exactly (0 byte/element mismatches) and within `atol=0.2`.

No FPGA execution is claimed. Nothing was programmed or flashed. No tracked files were edited by this run.

## Board identity

| Field | Value |
|---|---|
| Hostname | `orangepi5` |
| Kernel | `6.18.24-current-rockchip64` |
| Python | `3.14.4` |
| Device | `/dev/accel/accel0 (major/minor 261,0)` |
| Compatible | `xunlong,orangepi-5 / rockchip,rk3588s` |
| Runner sha256 | `a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd` |
| Runner version | `1.0.0` |

The pinned runner path `build/rk3588-example-captures/runner/pinned/` was empty, so the required default runner was used and its sha256 was verified identical on host and board.

## Paths

- Board staging: `/home/opencode-agent/rk3588-example-captures/runs/20261105T222300Z/staging/conv-fp16`
- Board output: `/home/opencode-agent/rk3588-example-captures/runs/20261105T222300Z/conv-fp16`
- Host copy: `build/rk3588-example-captures/results/conv-fp16-20261105T222300Z/board-run`
- Comparison: `build/rk3588-example-captures/results/conv-fp16-20261105T222300Z/host-analysis/comparison/comparison.json`
- Hashes: `build/rk3588-example-captures/results/conv-fp16-20261105T222300Z/host-analysis/hashes`
- Validation: `build/rk3588-example-captures/results/conv-fp16-20261105T222300Z/host-analysis/validation`

## Lock and race control

- One `flock -x -w 900 /home/opencode-agent/rk3588-npu.lock` invocation enclosed the whole 9-case runner.
- Lock acquired `2026-11-05T22:22:18Z`, released `2026-11-05T22:22:23Z`; `flock` exit 0, runner exit 0.
- Preflight `flock -n` lock-free check: exit 0.
- Pre-run and post-run `pgrep -af 'rk3588|rocket|capture|python3'` showed only the pre-existing `supervisord` process; no other capture/submit process.
- Sequential only, one invocation, no retries, no reset/reprogram between cases.

## Per-case results

| Case | Task | submit_ret | Output | BO bytes | Exact | Byte diffs | over atol | max abs diff | Padding nonzero / total |
|---|---:|---:|---|---:|---|---:|---:|---:|---:|
| `conv_1x1_valid_c8_h5_w5_oc8` | 1 | 0 | `out.bin` | 1600 | YES | 0 | 0 | 0 | 175 / 600 |
| `conv_3x3_valid_c4_h9_w9_oc4` | 1 | 0 | `out.bin` | 3328 | YES | 0 | 0 | 0 | 539 / 1468 |
| `conv_3x3_stride2_c4_h11_w11_oc4` | 1 | 0 | `out.bin` | 1792 | YES | 0 | 0 | 0 | 275 / 796 |
| `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` | 1 | 0 | `out.bin` | 5376 | YES | 0 | 0 | 0 | 891 / 2364 |
| `conv_depthwise_3x3_c3_h11_w28_oc3` | 1 | 0 | `out.bin` | 15104 | YES | 0 | 0 | 0 | 0 / 6850 |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2_task0` | 1 | 0 | `out0.bin` | 768 | YES | 0 | 0 | 0 | 0 / 348 |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2_task1` | 1 | 0 | `out1.bin` | 768 | YES | 0 | 0 | 0 | 0 / 348 |
| `conv_splitoc_3x3_c16_h9_w9_oc16_task0` | 1 | 0 | `out0.bin` | 3328 | YES | 0 | 0 | 0 | 0 / 1272 |
| `conv_splitoc_3x3_c16_h9_w9_oc16_task1` | 1 | 0 | `out1.bin` | 3328 | YES | 0 | 0 | 0 | 0 / 1272 |

Exact means the defined output region, after applying the manifest `output_layouts`, is byte-identical to the expected `expected.bin` / `expected_out0.bin` / `expected_out1.bin`. The raw BO is wider than the compact oracle, so raw BO bytes are not directly compared to the oracle. Full output BOs were read back by the runner, copied unchanged, and re-hashed.

## Totals

- Output BO bytes read back: **35392** (9 output buffers)
- Defined oracle bytes: **4756** (2378 FP16 elements)
- Padding/tail bytes reported separately: **30636** (15318 FP16 elements)
- Exact byte/element mismatches: **0 byte(s)**, **0** element bit mismatches
- Over `atol=0.2`: **0** elements; max abs diff **0**

## Padding and tails

Padding is not part of the oracle contract. It is reported separately, not treated as a mismatch:

| Case | Tail elements | Tail nonzero | Channel-padding elements | Channel-padding nonzero |
|---|---:|---:|---:|---:|
| `conv_1x1_valid_c8_h5_w5_oc8` | 0 | 0 | 600 | 175 |
| `conv_3x3_valid_c4_h9_w9_oc4` | 96 | 0 | 1372 | 539 |
| `conv_3x3_stride2_c4_h11_w11_oc4` | 96 | 0 | 700 | 275 |
| `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` | 96 | 0 | 2268 | 891 |
| `conv_depthwise_3x3_c3_h11_w28_oc3` | 64 | 0 | 6786 | 0 |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2_task0` | 96 | 0 | 252 | 0 |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2_task1` | 96 | 0 | 252 | 0 |
| `conv_splitoc_3x3_c16_h9_w9_oc16_task0` | 96 | 0 | 1176 | 0 |
| `conv_splitoc_3x3_c16_h9_w9_oc16_task1` | 96 | 0 | 1176 | 0 |

Four single-task cases had non-zero (including Inf) values in the aligned channel padding. The depthwise and four promoted cases had zero padding. The four promoted cases' raw BOs were also compared to the stored diagnostic evidence:

- `conv_grouped_3x3_c4_h5_w5_oc8_g2_task0`: raw equal to `evidence_diagnostic_out0.bin` = **False**; raw byte diffs = 72, of which defined-region diffs = 0 and padding diffs = 72; evidence defined region exact = True.
- `conv_grouped_3x3_c4_h5_w5_oc8_g2_task1`: raw equal to `evidence_diagnostic_out1.bin` = **False**; raw byte diffs = 72, of which defined-region diffs = 0 and padding diffs = 72; evidence defined region exact = True.
- `conv_splitoc_3x3_c16_h9_w9_oc16_task0`: raw equal to `evidence_diagnostic_out0.bin` = **True**; raw byte diffs = 0, of which defined-region diffs = 0 and padding diffs = 0; evidence defined region exact = True.
- `conv_splitoc_3x3_c16_h9_w9_oc16_task1`: raw equal to `evidence_diagnostic_out1.bin` = **True**; raw byte diffs = 0, of which defined-region diffs = 0 and padding diffs = 0; evidence defined region exact = True.

The two grouped promoted cases differ from their diagnostic evidence only in 72 padding bytes each; their defined 72-byte outputs are exact. This confirms the padding is not a stable part of the contract.

## Scope control

- Exactly the **9 READY** case directories were staged on the board.
- The **5 BLOCKED** cases were not staged and not submitted:
  - `conv_3x3_pad_register_fp16_blocked` — `manifest_reason_recorded` — No Rocket-capable FP16 builder emits and validates CNA_PAD_CON0. conv_new_clean.py comments the pad register out (lines 547-550) and computes valid-only geometry. conv_mesa_fp16.py
  - `conv_grouped_3x3_c4_h5_w5_oc8_g2` — `MULTITASK_ROCKET_JOB_UNSUPPORTED` — MULTITASK_ROCKET_JOB_UNSUPPORTED: the RK3588 Rocket v6.18 board path executed only task 0 of a two-task job. The original run's task 0 output matched exactly while task 1's output 
  - `conv_split_k_reduction_blocked` — `manifest_reason_recorded` — Split-K reduction requires accumulation of partial products across tiles. Neither inspected Rocket path provides an accumulator or a second reduction pass: conv_0522._execute_conv_
  - `conv_splitoc_3x3_c16_h9_w9_oc16` — `MULTITASK_ROCKET_JOB_UNSUPPORTED` — MULTITASK_ROCKET_JOB_UNSUPPORTED: the RK3588 Rocket v6.18 board path executed only task 0 of a two-task job. The original run's task 0 output matched exactly while task 1's output 
  - `conv_tiles_vendor_abi_blocked` — `manifest_reason_recorded` — Vendor-only ABI: conv_tiles.py opens /dev/dri/card1 and submits through DRM_IOCTL_RKNPU_MEM_CREATE/MEM_MAP/MEM_SYNC/ACTION/SUBMIT with struct rknpu_submit and RKNPU_JOB_PC. It has 
- No other family was touched.
- The host-side family validator read the retained BLOCKED evidence directories only to verify their hashes; none was copied to the board or submitted.

## Validation and hashes

- Family validator: PASS (9 READY, 5 BLOCKED), exit 0.
- Shared runner validator: 9/9 READY cases OK, exit 0 each.
- `rocket_run.py --validate-only`: 9/9 READY cases OK, exit 0 each.
- Board and host `postrun.sha256` manifests: identical; `sha256sum -c` **99/99 OK** on both sides.
- Staged tree hashes: 75/75 files identical between host staging and board staging before execution.
- Every capture output size and recorded `output_sha256` matches the copied output file (9/9).

## Claims

- This is an RK3588 board capture via the mainline Rocket UAPI on `/dev/accel/accel0`.
- **No FPGA execution is claimed.** The FPGA was not programmed or flashed; no sudo was used.
- The input bundles and `expected*.bin` oracles are host-side preparation artifacts, not device outputs.

