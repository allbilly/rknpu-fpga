# conv-fp16 RK3588 Rocket capture report

Run ID: `20261105T205900Z` (board UTC)
Family: `conv-fp16` (7 READY, 3 BLOCKED)
Owner: single authorized board worker. No other capture worker ran.

## Scope and safety

- Only the 7 READY case directories were staged. The 3 BLOCKED cases were not
  staged or submitted.
- No other family was touched.
- No FPGA programming/flashing, no `sudo`, no device reset, no retry.
- No tracked source, test or doc was modified; `git status` shows zero tracked
  changes. Nothing was committed.
- No FPGA execution is claimed. All device results are mainline Rocket NPU
  capture results on the RK3588.

## Board identity

- Host: `orangepi5`
- Kernel: `6.18.24-current-rockchip64 #2 SMP PREEMPT Wed Apr 22 11:22:34 UTC 2026 aarch64`
- Board compatible: `xunlong,orangepi-5`, `rockchip,rk3588s`
- Python: `3.14.4`
- Device: `/dev/accel/accel0`, char `261:0`, mode `crw-rw---- root render`
- Sysfs: `/sys/devices/platform/rknn`
- Mainline Rocket UAPI; no vendor `rknpu` device used.
- Lock: `/home/opencode-agent/rk3588-npu.lock`, inode `134534`.

## Runner provenance

The requested path
`build/rk3588-example-captures/runner/pinned/rocket_run-a51d.py` **did not
exist** at run time (`runner/pinned/` was empty). The exact required bytes were
found at:

- `build/rk3588-example-captures/runner/rocket_run.py`
- `build/rk3588-example-captures/results/fdiv-systematic-20261105T204746Z/tools/rocket_run-a51d.py`

Both hash to:

```
a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd
```

The same bytes were staged to the unique board tools directory and re-hashed
there. No substitute runner was used.

Wrapper script: `tools-conv-fp16-20261105T205900Z/run_locked.sh`
(sha256 `b72a09c31cefc5a1b02c79f41562c92376bc74fa4e43c9702f0056ae08e07cb2`).

## Unique paths

Board:

- Runner: `/home/opencode-agent/rk3588-example-captures/tools-conv-fp16-20261105T205900Z/rocket_run-a51d.py`
- Queue: `/home/opencode-agent/rk3588-example-captures/queue-conv-fp16-20261105T205900Z/conv-fp16`
- Run: `/home/opencode-agent/rk3588-example-captures/runs/20261105T205900Z/conv-fp16`
- Runner log: `/home/opencode-agent/rk3588-example-captures/runs/20261105T205900Z/runner.log`

Host copy:
`build/rk3588-example-captures/results/conv-fp16-20261105T205900Z/`

## Preflight and staging verification

- Initial `pgrep -af 'rk3588|rocket|capture|python3'` matched only the board
  `supervisord` and the `pgrep` shell itself. No capture worker existed.
- Host `validate_bundles.py`: `PASS: schema, sizes, task ranges, tails,
  patches, layouts and hashes`; 7 READY / 3 BLOCKED / 10 total.
- Host `validate_bundle.py`: 7/7 `OK`, invoked one case at a time.
- Board `rocket_run.py --validate-only`: 7/7 `OK`, exit 0, no device opened.
- Staged case files: 64, all sha256-identical on host and board.
- Board queue contains exactly the 7 READY case directories; no BLOCKED,
  `tiles`, or `pad_register` case was present.

## Execution

One locked invocation only:

```
flock -x -w 900 /home/opencode-agent/rk3588-npu.lock \
  python3 .../rocket_run-a51d.py \
    --device /dev/accel/accel0 \
    --out .../runs/20261105T205900Z/conv-fp16 \
    .../queue-conv-fp16-20261105T205900Z/conv-fp16
```

- Lock acquired: `2026-11-05T21:00:47Z`
- Lock released: `2026-11-05T21:00:50Z`
- `/proc/locks`: `12: FLOCK ADVISORY WRITE 3626572 b3:01:134534 0 EOF`
- Flock parent PID 3626572; inner shell/python PID 3626573; wrapper PID 3626566.
- Elapsed: 3 s. Runner exit 0.
- Pre-lock and post-run pgrep showed only `supervisord` and the wrapper.
- No second submit process, no retry, no reset.

Per-case ioctl results (all `capture.json` `status: OK`, `errors: []`,
`cleanup_errors: []`):

| Case | Tasks | submit_ret |
|---|---|---|
| conv_1x1_valid_c8_h5_w5_oc8 | 1 | 0 |
| conv_3x3_pad1_zero_frame_c4_h9_w9_oc4 | 1 | 0 |
| conv_3x3_stride2_c4_h11_w11_oc4 | 1 | 0 |
| conv_3x3_valid_c4_h9_w9_oc4 | 1 | 0 |
| conv_depthwise_3x3_c3_h11_w28_oc3 | 1 | 0 |
| conv_grouped_3x3_c4_h5_w5_oc8_g2 | 2 | 0 |
| conv_splitoc_3x3_c16_h9_w9_oc16 | 2 | 0 |

`submit_ret == 0` is the ioctl result only; completion was confirmed by the
output `PREP_BO` wait. It does not by itself establish numerical correctness.

## Readback and integrity

- 9 output BOs, **35,392 bytes total**, read completely as returned.
- 7 `capture.json` files, 43,823 bytes.
- Complete board run tree: 17 files, 80,561 bytes including `runner.log`.
- Full board run tree and host copy: all 17 sha256 values match.
- Final capture.json + output re-hash: all 16 files match on both sides.
- `out1.bin` for both multi-task cases is an all-zero BO, confirmed by matching
  board and host hashes; it was not replaced by expected data.

## Host comparison method

`exact` means bitwise equality of the FP16 element after applying the manifest
`output_layouts` (NC1HWC2 or flat_1x1) unpack. Raw file-vs-NCHW byte compare is
not layout-compatible and is not used. `atol` is the manifest value `0.2`.
Bytes outside the defined `out_c * out_h * out_w` region (aligned channel lanes
and stride tails) are reported separately and are not pass/fail data.

## Per-case results

| Case / task | Defined elems | Exact bit mismatches | Over atol=0.2 | Max abs diff | Padding/tail |
|---|---:|---:|---:|---:|---:|
| 1x1 C8H5W5 OC8, out | 200 | 0/200 | 0/200 | 0 | 600 elems (1200 B), 175 nonzero |
| 3x3 C4H9W9 OC4, out | 196 | 0/196 | 0/196 | 0 | 1468 elems (2936 B), 539 nonzero |
| 3x3 s2 C4H11W11 OC4, out | 100 | 0/100 | 0/100 | 0 | 796 elems (1592 B), 275 nonzero |
| 3x3 pad1 zero-frame, out | 324 | 0/324 | 0/324 | 0 | 2364 elems (4728 B), 891 nonzero |
| depthwise C3H11W28 OC3, out | 702 | 0/702 | 0/702 | 0 | 6850 elems (13700 B), 0 nonzero |
| grouped task0, out0 | 36 | 0/36 | 0/36 | 0 | 348 elems (696 B), 0 nonzero |
| grouped task1, out1 | 36 | **36/36** | **34/36** | **11.9375** | 348 elems (696 B), 0 nonzero |
| split-OC task0, out0 | 392 | 0/392 | 0/392 | 0 | 1272 elems (2544 B), 0 nonzero |
| split-OC task1, out1 | 392 | **392/392** | **388/392** | **52.25** | 1272 elems (2544 B), 0 nonzero |

Combined, task0 then task1, against `expected_combined.bin`:

- grouped: exact 36/72, over atol 34/72, max 11.9375 -> FAIL.
- split-OC: exact 392/784, over atol 388/784, max 52.25 -> FAIL.

### Exact mismatches

All failing elements are in task 1 of the two multi-task cases; every observed
value is `0x0000` (`0.0`). Full offsets/values are in
`host-analysis/mismatches.csv` (428 rows).

Grouped task1 (36 defined values, all bit-mismatched):

- `byte_offset=0`, oc0 h0 w0: got `0x0000` (0.0), expected `0xc7fe` (-7.9921875)
- `byte_offset=16`, oc0 h0 w1: got `0x0000` (0.0), expected `0xc9f8` (-11.9375)  <- max
- `byte_offset=32`, oc0 h0 w2: got `0x0000` (0.0), expected `0x3c89` (1.1337890625)
- `byte_offset=48`, oc0 h1 w0: got `0x0000` (0.0), expected `0x34c9` (0.299072265625)
- `byte_offset=64`, oc0 h1 w1: got `0x0000` (0.0), expected `0xc32f` (-3.591796875)
- `byte_offset=80`, oc0 h1 w2: got `0x0000` (0.0), expected `0xb7d9` (-0.490478515625)
- Two exact mismatches are within atol: offset 50 expected `0xa60f` (-0.0236663818359375); offset 98 expected `0x2cb7` (0.07366943359375).

Split-OC task1 (392 defined values, all bit-mismatched):

- `byte_offset=0`, oc0 h0 w0: got `0x0000` (0.0), expected `0xca14` (-12.15625)
- `byte_offset=16`, oc0 h0 w1: got `0x0000` (0.0), expected `0xc1aa` (-2.83203125)
- `byte_offset=32`, oc0 h0 w2: got `0x0000` (0.0), expected `0x4cf0` (19.75)
- `byte_offset=48`, oc0 h0 w3: got `0x0000` (0.0), expected `0x4f16` (28.34375)
- `byte_offset=64`, oc0 h0 w4: got `0x0000` (0.0), expected `0x506e` (35.4375)
- `byte_offset=80`, oc0 h0 w5: got `0x0000` (0.0), expected `0x4d3a` (20.90625)
- Max: `byte_offset=442`, oc5 h3 w6: got `0x0000` (0.0), expected `0x5288` (52.25).
- Four exact mismatches are within atol: offsets 624, 548, 630, 718 (expected 0.14306640625, -0.0947265625, 0.11212158203125, 0.0826416015625).

### Padding/tails

The nonzero padding above is inside the allocated output BO but outside the
manifest-defined tensor region (aligned channel lanes / stride tails). It is not
compared to the oracle and is not treated as a pass or fail. The grouped and
split-OC output BOs had fully zero padding/tails.

## Outcome

- 5/7 READY cases: exact bit-for-bit match and atol pass on every defined
  element.
- 2/7 READY cases: task 0 exact and atol pass; task 1 output BO is entirely
  zero, so task 1 and the combined comparison fail atol. This is recorded as a
  capture result, not retried or patched.
- Both task descriptors were present and patched (`regcmd_dma` 0 and 432;
  task 1 buffers/addresses visible in `capture.json`), and both tasks have the
  same terminal tail. No submit error was reported. The observed evidence is
  that the second terminal task did not write its output BO. No root-cause fix
  or schema/runner change was attempted here.

## Evidence files

- `host-analysis/validation/` - host and board validation logs
- `host-analysis/comparison/` - detailed and official comparator logs
- `host-analysis/comparison_summary.json` - structured per-task results
- `host-analysis/mismatches.csv` - every exact/over-atol mismatch with offsets
- `host-analysis/hashes/` - staged and run-tree hash lists plus verification
- `host-analysis/board-final-identity.txt` - final board re-hash and identity
- `host-analysis/ssh-capture.log` - locked wrapper/runner console log
- `runner.log` (in run tree) - lock provenance, runner output, pgrep
