# conv-gemm-vendor board run 20261105T214000Z

Scope: the 10 `READY` bundles in
`build/rk3588-example-captures/conv-gemm-vendor/` (4 GEMM, 3 ordinary conv,
2 split depthwise one-task cases, 1 conv.py full-setup case). The 3 `BLOCKED`
cases were not staged and were not submitted. No other family was touched.
No FPGA bitstream was programmed, no flash action was performed, no `sudo`
was used, and no vendor `rknpu` ioctl was used. This is RK3588 mainline
Rocket execution only; **no FPGA execution is claimed**.

## Board identity

- hostname: `orangepi5`
- OS: Armbian 26.8.3 resolute
- kernel: `Linux 6.18.24-current-rockchip64 #2 SMP PREEMPT Wed Apr 22 11:22:34 UTC 2026 aarch64`
- board Python: `3.14.4`
- device: `/dev/accel/accel0`, char `261:0`
- capture device audit: `major=261 minor=0`, `sysfs_device=/sys/devices/platform/rknn`,
  compatible `xunlong,orangepi-5`, `rockchip,rk3588s`
- host revision: `f9b00d8f9a48ab4dea20cb30148890cd9f1443ee`
- host comparison Python: `/usr/bin/python3 3.14.8`, NumPy `2.4.6`

## Runner and staging

- `runner/pinned/` was empty, so the fallback runner
  `build/rk3588-example-captures/runner/rocket_run.py` was used.
- required/actual sha256:
  `a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd`
  (identical on host and board).
- unique board paths:
  - queue: `/home/opencode-agent/rk3588-example-captures/queue-20261105T214000Z/conv-gemm-vendor/`
  - tools: `/home/opencode-agent/rk3588-example-captures/tools-conv-gemm-vendor-20261105T214000Z/rocket_run.py`
  - run output: `/home/opencode-agent/rk3588-example-captures/runs/20261105T214000Z/conv-gemm-vendor/`
- host result tree:
  `build/rk3588-example-captures/results/conv-gemm-vendor-20261105T214000Z/`
- only the 10 READY case directories were staged: 10 case directories,
  0 `BLOCKED.md`, 54 bundle files. `sha256sum -c` on the staged queue was
  `54/54 OK` both before and after the run.
- local validation before staging:
  - family validator `tools/validate_bundles.py`:
    `PASS: READY=10 BLOCKED=3 cases=13 max_regcmd_words=112 rocket_max=131072`
  - shared `runner/validate_bundle.py` run per case, one at a time:
    10/10 `OK`, no failures (would have stopped on the first failure).

## Execution and lock

One invocation, all 10 cases, strictly sequential:

```text
flock -x -w 900 /home/opencode-agent/rk3588-npu.lock \
  python3 .../tools-conv-gemm-vendor-20261105T214000Z/rocket_run.py \
    --device /dev/accel/accel0 \
    --out .../runs/20261105T214000Z/conv-gemm-vendor \
    .../queue-20261105T214000Z/conv-gemm-vendor
```

- lock acquired: `2026-11-05T21:39:03Z`
- runner finished: `2026-11-05T21:39:04Z`
- lock released: `2026-11-05T21:39:04Z`
- `RUNNER_RC=0`, `FLOCK_RC=0`
- lock file `/home/opencode-agent/rk3588-npu.lock`, dev/inode `45825/134534`
  (`b3:01:20d86`).
- The inline `/proc/locks` check in the runner log printed
  `LOCK_NOT_FOUND_IN_PROC_LOCKS`. That check formatted the device as
  `b301:20d86` instead of `b3:01:20d86`; the lock itself was acquired by
  `flock -x` (immediate `LOCK_ACQUIRED`, exit 0) and held across the single
  runner process. No second submit process was started.
- Case start/finish timestamps do not overlap. The runner is single-process
  and processed the queue in sorted order:
  `conv_1x1_c1_oc6_h4w4`, `conv_depthwise..._task0`,
  `conv_depthwise..._task1`, `conv_grouped_3x3_c4_oc4_g2_h5w5`,
  `conv_legacy_3x3_c4_oc4_h9w9`, `conv_py_3x3_c32_oc128_h14w14_fullsetup`,
  `gemm_m1_n16_k32`, `gemm_m2_n16_k32`, `gemm_m2_n2_k1`,
  `gemm_m4_n32_k64`.
- Pre-run `pgrep -af 'rk3588|rocket|capture|python3'` saw only the 31-day-old
  system `supervisord` and the pgrep shell wrapper; post-run `pgrep` saw the
  same. No other capture worker was present. No other capture process ran.

## Results

All 10 submissions returned `submit_ret == 0` and runner `status == OK`.
`status == OK` is the runner's completion/readback status, not a numerical
acceptance. Exact comparison is reported first; tolerance is the manifest
tolerance (`0.1` GEMM, `0.2` conv, `0.12` for the conv.py full-setup case).
`exact` means byte-for-byte equality of the compared surface, not just
within tolerance.

### GEMM: raw FP32 surface and logical MxN

| case | submit_ret | raw surface exact | logical MxN exact | max abs diff | > 0.1 | result |
|---|---:|---|---|---:|---:|---|
| `gemm_m2_n2_k1` | 0 | 4096/4096 B (1024/1024 f32) | 16/16 B (4/4 f32) | 0 | 0 | exact PASS |
| `gemm_m1_n16_k32` | 0 | 4096/4096 B (1024/1024 f32) | 64/64 B (16/16 f32) | 0 | 0 | exact PASS |
| `gemm_m2_n16_k32` | 0 | 4096/4096 B (1024/1024 f32) | 128/128 B (32/32 f32) | 0 | 0 | exact PASS |
| `gemm_m4_n32_k64` | 0 | 4049/4096 B (978/1024 f32) | 465/512 B (82/128 f32) | 9.5367431640625e-07 | 0 | tolerance PASS; not exact |

The `gemm_m4_n32_k64` differences are FP32 accumulator-order rounding, not
out-of-tolerance values. First difference: logical element 4, logical byte
offset 16, raw surface byte 16; got `-13.499343872070312`, expected
`-13.499342918395996`, delta `-9.5367431640625e-07`.

### Conv: unpacked FP16/NCHW logical output

| case | submit_ret | logical NCHW exact | max abs diff | > tol | result |
|---|---:|---|---:|---:|---|
| `conv_1x1_c1_oc6_h4w4` | 0 | 192/192 B (96/96 f16) | 0 | 0 | exact PASS |
| `conv_grouped_3x3_c4_oc4_g2_h5w5` | 0 | 72/72 B (36/36 f16) | 0 | 0 | exact PASS |
| `conv_legacy_3x3_c4_oc4_h9w9` | 0 | 392/392 B (196/196 f16) | 0 | 0 | exact PASS |
| `conv_depthwise_3x3_c3_oc3_h11w28_task0` | 0 | 100/1404 B (48/702 f16) | 12.84375 | 636 | **FAIL tolerance** |
| `conv_depthwise_3x3_c3_oc3_h11w28_task1` | 0 | 100/1404 B (48/702 f16) | 12.84375 | 636 | **FAIL tolerance** |
| `conv_py_3x3_c32_oc128_h14w14_fullsetup` | 0 | 36854/36864 B (18422/18432 f16) | 0.015625 | 0 | tolerance PASS; not exact |

The two depthwise split outputs are byte-identical to each other:
sha256 `23762b457623a1a1de52bc5b954bd6e4fd70ea9ce395c480c398e3456ff68e7f`,
7552 bytes each. Both are wrong in the same way.

The conv.py full-setup differences are small FP16 rounding differences
(10/18432 elements; max `0.015625`, below the manifest `0.12`). First
difference: logical element 1738 (channel 12, row 0, col 10), logical byte
offset 3476, raw output byte 2472; got `1.9765625`, expected `1.9755859375`,
delta `+0.0009765625`.

## Depthwise split-case failure

Observed: each depthwise output contains only the first 16 NCHW positions
(row 0, cols 0-15) of each of the 3 channels: 48 of 702 elements are exact,
654 are zero-filled, 636 exceed the `0.2` tolerance. First failure:

- logical element 16 (channel 0, row 0, col 16)
- logical byte offset 32; raw output byte 256
- got `0.0`, expected `7.359375`, delta `-7.359375`

Largest failure: logical element 182 (channel 0, row 7, col 0), logical byte
offset 364, raw output byte 2912; got `0.0`, expected `-12.84375`.
Last failing element: 701 (channel 2, row 8, col 25), logical byte offset
1402, raw output byte 3732. Both task 0 and task 1 show the same pattern.

Evidence from the command stream itself: the DPU `DATA_CUBE_CHANNEL` field is
`0x1f` (31), i.e. 32 hardware output channels, and `SURFACE_ADD` (0x40c0) is
`7552` bytes. That is 2 groups of 16 channels, so the command stream requires
`2 * 7552 = 15104` output bytes. Both split `job.json` files declare only
`7552` output bytes. The prior known-good depthwise capture in
`results/conv-fp16-20261105T205900Z/` used the same logical input and
expected data (input sha256 `0fd41346...`, expected sha256 `226ed017...`),
had the same `SURFACE_ADD=7552`/channel-field 31 geometry, but allocated
15104 output bytes and matched the oracle exactly (702/702 f16, max diff 0;
prior output sha256 `431f470e...`). This is a concrete bundle defect: the
output BO is half the size required by the bundle's own command stream. The observed run also took
531 ms / 508 ms in the output wait, above the 500 ms scheduler timeout stated
in the family README; the partial 16-position output is consistent with an
aborted/stalled job, but the exact hardware failure mode is not claimed
without a corrected rerun.

The conv_legacy-derived stream also differs from the prior conv_new_clean
stream by lacking three explicit zero writes to RDMA state
(`RDMA_S_POINTER`, `RDMA_ERDMA_CFG`, `RDMA_FEATURE_MODE_CFG`;
`kernel_6_18/conv_new_clean.py:486-488`). The prior source comments those as
clearing stale DPU-RDMA state. That may be an
additional cross-job-state factor; it is recorded as an observation, not
proven as the cause. No retry and no bundle modification was performed.

## Padding and tails

All reported padding/tail bytes are zero in the returned BOs.

| case | padding/tail |
|---|---|
| `gemm_m2_n2_k1` | 1020 f32 / 4080 B padding, all zero |
| `gemm_m1_n16_k32` | 1008 f32 / 4032 B padding, all zero |
| `gemm_m2_n16_k32` | 992 f32 / 3968 B padding, all zero |
| `gemm_m4_n32_k64` | 896 f32 / 3584 B padding, all zero |
| `conv_1x1_c1_oc6_h4w4` | 160 unused within the 512-B read region (320 B) + 1792-element tail (3584 B); all zero |
| `conv_grouped_3x3_c4_oc4_g2_h5w5` | 60 unused within the 192-B read region (120 B) + 1952-element tail (3904 B); all zero |
| `conv_legacy_3x3_c4_oc4_h9w9` | 636 unused within the 1664-B read region (1272 B) + 1216-element tail (2432 B); all zero |
| `conv_depthwise..._task0` | within the declared 7552-B BO: 3074 elements (6148 B) outside the 702 logical values, all zero; no tail. The BO is 7552 B short of the 15104-B DPU-required surface. |
| `conv_depthwise..._task1` | same as task 0 |
| `conv_py_3x3_c32_oc128_h14w14_fullsetup` | no padding/tail; 18432/18432 elements consumed |

DPU surface geometry checks:

| case | channel field | hw channels | 16-ch groups | SURFACE_ADD | required | declared BO | sufficient |
|---|---:|---:|---:|---:|---:|---:|---|
| `conv_1x1_c1_oc6_h4w4` | 15 | 16 | 1 | 512 | 512 | 4096 | yes |
| `conv_grouped_3x3_c4_oc4_g2_h5w5` | 15 | 16 | 1 | 384 | 384 | 4096 | yes |
| `conv_legacy_3x3_c4_oc4_h9w9` | 15 | 16 | 1 | 1664 | 1664 | 4096 | yes |
| `conv_depthwise..._task0` | 31 | 32 | 2 | 7552 | 15104 | 7552 | **no** |
| `conv_depthwise..._task1` | 31 | 32 | 2 | 7552 | 15104 | 7552 | **no** |
| `conv_py_3x3_c32_oc128_h14w14_fullsetup` | 127 | 128 | 8 | 4608 | 36864 | 36864 | yes |

## Hash verification and bytes read

- `capture.json`: 10/10 present, hashes identical on board and host.
- `output.bin`: 10/10 present, hashes identical on board and host.
- Host re-hash of all 20 capture/output files matches the board list exactly
  (`CAPTURE_OUTPUT_HASHES_IDENTICAL`).
- The complete 21-file board run tree (10 capture.json, 10 output.bin,
  runner.log) also matches byte-for-byte on both sides
  (`hash-compare-run-tree.txt`: `RUN_TREE_HASHES_IDENTICAL (21 files)`).
- Each `capture.json` records the correct local `job.json`, source `regcmd.bin`,
  input hashes, output size and output hash; the host comparison reported
  `checksum_failures: []`.
- Total output BO bytes read back: **80,640 bytes**
  (4x4096 GEMM + 3x4096 ordinary conv + 2x7552 depthwise + 36864 conv.py).
- Capture metadata copied: 56,563 bytes (`capture.json` total), plus the
  880-byte runner log. Complete board run tree copied to the host result tree.

## Artifacts

- `host-analysis/comparison.json` - machine-readable per-case exact/tolerance
  and padding/tail results.
- `host-analysis/summary.tsv` - flat per-case summary.
- `host-analysis/mismatch_offsets.json` - first exact mismatches with both
  logical and raw output byte offsets.
- `host-analysis/compare.py` - host comparison script (reads the copied
  output BOs; never substitutes expected data).
- `hashes-board-captures-outputs.sha256`,
  `hashes-host-captures-outputs.sha256` - the 20 capture/output hashes.
- `hash-compare-run-tree.txt` - all 21 board run-tree files match on both
  sides.
- `hash-board-run.sha256`, `hash-host-run.sha256`, `runner.log`,
  `pgrep-pre-submit.txt`, `pgrep-post-run.txt`, `bundle-verify-after.txt`.

No tracked source, test or doc was modified; no commit was made. No FPGA
execution is claimed.
