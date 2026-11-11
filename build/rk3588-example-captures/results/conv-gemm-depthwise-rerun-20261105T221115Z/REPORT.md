# Conv depthwise split-case rerun — 2026-11-05T22:12:57Z

Run ID: `20261105T221115Z`

Result: **PASS**. Both corrected 15104-byte-output cases returned
`submit_ret=0`, both full BOs were read back, and all 702 logical NCHW FP16
values per case are bit-exact against `expected.bin`.

Scope: this is a **mainline Rocket RK3588 NPU capture**. It is **not** an FPGA
execution, does not program or flash the FPGA, and makes no new numerical
special-value policy claim.

## Cases

- `conv_depthwise_3x3_c3_oc3_h11w28_task0`
- `conv_depthwise_3x3_c3_oc3_h11w28_task1`

Both case bundles were used exactly as found. No bundle file was modified.

## Board and runner

| Item | Value |
|---|---|
| Board | `orangepi5`, `xunlong,orangepi-5` / `rockchip,rk3588s` |
| Kernel | `6.18.24-current-rockchip64 #2 SMP PREEMPT Wed Apr 22 11:22:34 UTC 2026 aarch64` |
| Board Python | 3.14.4 |
| Device | `/dev/accel/accel0` (major/minor 261:0, `/sys/devices/platform/rknn`) |
| Lock | `/home/opencode-agent/rk3588-npu.lock`, `flock -x -w 900` |
| Runner | `rocket_run.py` version 1.0.0, sha256 `a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd` |

The board had no `runner/` or `runner/pinned/` directory, so the validated local
runner with the required sha256 was staged into the fresh run tree.

## Preflight and race control

- Family validator (sha256 `aed1d84ecdbbb39d0b30feddcea2692c128dc66d21cf8011f664e1272dcbce56`):
  `PASS: READY=10 BLOCKED=3 cases=13 max_regcmd_words=112 rocket_max=131072`.
- Shared validator (sha256 `2aa8503e338a47bef064fbd47cf24a6d695eacf6171ab966f8c70b6b3cb2b064`):
  `OK` for both case directories.
- `rocket_run.py --validate-only`: `OK` for both case directories.
- `pgrep -af 'rk3588|rocket|capture|python3'` immediately before the run
  matched only `/usr/bin/supervisord` (PID 2023819). No rocket, capture or
  rk3588 process was present.
- Both cases ran sequentially in **one** flock invocation:
  `flock -x -w 900 /home/opencode-agent/rk3588-npu.lock python3 <staged runner> --device /dev/accel/accel0 --out .../conv-gemm-depthwise-rerun <task0> <task1>`.
- No retry, reset, sudo, programming or flashing was performed.

Staged bundle hashes were checked on the board with `sha256sum -c`; all 10
bundle files matched the host originals. The staged runner hash matched
`a51de01f...26cd`.

## Board results

| Case | status | submit_ret | output bytes | output sha256 |
|---|---|---:|---:|---|
| `..._task0` | OK | 0 | 15104 | `431f470ed23f321f115a9af03db2edba170d5ac3e036efb08c10834aba0faacf` |
| `..._task1` | OK | 0 | 15104 | `431f470ed23f321f115a9af03db2edba170d5ac3e036efb08c10834aba0faacf` |

Total output BO bytes read back: **30208** (2 x 15104).

Both cases produced byte-identical output. That is expected: each is the same
one-task command stream with identical inputs and weights. The hash also equals
the earlier 15104-byte depthwise capture's output hash, but this run stands on
its own new board evidence.

Capture durations (ns) from `capture.json`:

| Case | output PREP/wait | total |
|---|---:|---:|
| `..._task0` | 254038 | 1643518 |
| `..._task1` | 111415 | 1163734 |

Each capture records one task with `regcmd_offset_words=0`,
`regcmd_words=52`, `regcmd_dma=0`; addresses were regcmd `0`, input `4096`,
weight `12288`, output `16384`. Both captures have empty `errors` and
`submit_error: null`.

## Logical NCHW comparison

The logical values were extracted with the source geometry
`_unpack_flat_1x1_output(out_c=3, out_h=9, out_w=26,
out_width_stride=236, c2=8)` from the first 7552-byte surface.

| Case | exact FP16 | max abs diff | > 0.2 tolerance |
|---|---:|---:|---:|
| `..._task0` | **702/702** | **0.0** | 0 |
| `..._task1` | **702/702** | **0.0** | 0 |

No mismatches, no first-mismatch entry, and no values outside the manifest
`tolerance_abs: 0.2`.

## Padding and tails

The 15104-byte BO is two 7552-byte DPU surface groups. Surface group 0
(offsets 0..7551) is the 16-channel read window used by the 702-value oracle;
surface group 1 (offsets 7552..15103) is unused.

| Region | Elements | Bytes | Nonzero |
|---|---:|---:|---:|
| Logical values | 702 | 1404 | 702 (expected data) |
| Logical-channel padding (channels 0-2, positions 234-235 of each 236) | 6 | 12 | 0 |
| Non-logical channels 3-15 in surface 0 | 3068 | 6136 | 0 |
| Surface group 1 (channels 16-31) | 3776 | 7552 | 0 |
| Beyond declared BO tail | 0 | 0 | 0 |
| **Total unused/padding** | **6850** | **13700** | **0** |

The full BO is 7552 FP16 elements (15104 bytes); 702 logical + 6850 unused =
7552. All unused regions are zero in both cases. There is no additional tail
because the corrected BO exactly matches the command stream's two-surface
requirement.

## Hash verification

Board and host copies of the complete run tree (2 capture.json, 2 output.bin,
runner.log, run-window.txt, preflight-pgrep.txt) are byte-identical; see
`hashes/board_run_tree.sha256` and `hashes/local_run_tree.sha256`.

| Item | sha256 |
|---|---|
| task0 capture.json | `7252e44d205393ad1c15cea73d92f59285512db6e1c3f0b81173aa8aada23cb7` |
| task1 capture.json | `cd0c6592a53cd85f32a7946c11c036e03177bc63fb43b872e597c87a494a5e7b` |
| output.bin (both) | `431f470ed23f321f115a9af03db2edba170d5ac3e036efb08c10834aba0faacf` |
| task0 job.json | `2f7a414ca8bada02ef78b59d464a406c4be507fda4a91a1a604d59f89eb62c15` |
| task1 job.json | `6b127060700836a4fac42af1f24e01cac97fcb20f94ac9861589e527ad1fbf14` |
| regcmd.bin (source, both) | `906cacd0c93fa9f24cbf5d2c86cd191bb1c613418a26c6113a8131148cadc329` |
| regcmd patched (both) | `4e41d625037ae873e263c6b2e38d11ea3fcf23ab2470147a014f98ed8cedc302` |
| input.bin (both) | `0fd41346970b0ddbc0f89d5b0899ae998a6b22a06b3f66b867d917c9ba4bc28f` |
| weight.bin (both) | `4e3f77532434f10413425550076b0901ca3ff4f0886ed1b1f60de9757063ba31` |
| expected.bin (both) | `226ed017f7e120c54613da5f876d102851149eb541b87c4ad3bb30a0a286228b` |

Each capture's recorded `job_json`, `regcmd_source`, input and weight hashes
match the host bundle; each recorded output hash and size match the reread BO.
The board-side staging check is in `hashes/board_staging_verification.log`.

## Artifacts

- `board-run/` — unchanged board run tree copied back from the board.
- `host-analysis/compare.py` — stdlib-only oracle/padding comparison.
- `host-analysis/comparison.json`, `comparison.txt` — machine-readable and flat
  results.
- `run_manifest.json` — run, board, runner, validation and case metadata.
- `preflight/` — host validator logs, bundle hashes, tool versions, staging
  checksum list.
- `hashes/` — board/host run-tree hashes and board output listing.

## Limits

- Mainline Rocket on the RK3588 NPU only; **no FPGA execution is claimed**.
- One run, no retries, no device reset between cases.
- The result confirms this corrected 15104-byte bundle geometry for these two
  one-task split cases; it does not generalize to other shapes, the blocked
  two-task bundle, or vendor multicore paths.
