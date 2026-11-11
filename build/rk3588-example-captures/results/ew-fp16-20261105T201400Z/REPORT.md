# ew-fp16 real RK3588 capture report

Run id: `20261105T201400Z` (UTC). This report covers only the 54 READY `ew-fp16` bundles. No other capture family was executed or modified. No FPGA bitstream was built, loaded or run.

## Board identity

| Item | Value |
|---|---|
| Hostname | `orangepi5` |
| User | `opencode-agent` (uid 1002, gid 1002; groups 1002,100(users),990(render)) |
| Kernel | `6.18.24-current-rockchip64 #2 SMP PREEMPT Wed Apr 22 11:22:34 UTC 2026 aarch64` |
| Board Python | `Python 3.14.4` |
| Device | `/dev/accel/accel0`, char `261:0`, `crw-rw---- root render` |
| Driver | Rocket bound at `/sys/devices/platform/rknn/driver`; `rocket` module loaded |
| Vendor rknpu | absent: no `/dev/rknpu*`; no vendor rknpu device was used |
| Board UTC at identity capture | `2026-11-05T20:17:00Z` |

## Paths

- Board queue: `/home/opencode-agent/rk3588-example-captures/queue-ew-fp16-20261105T201400Z/`
  - cases: `.../cases/` (54 directories)
  - runner: `.../tools/ew_int_run.py`
  - device outputs: `.../out/`
  - logs: `.../logs/` (`preflight.txt`, `run.log`, `run.exit`, `outputs-sha256.txt`)
- Host results: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/ew-fp16-20261105T201400Z/`
  - copied device tree: 54 case directories + `summary.json`
  - evidence: `evidence/` (comparison, hashes, logs, exact divergence bits)

## Race prevention and lock

- The first board command was `pgrep -af 'rk3588|rocket|capture|python3'`; it showed only `/usr/bin/supervisord` (PID 2023819). No capture worker existed, so the run proceeded.
- The check was repeated immediately before the run (`2026-11-05T20:14:43Z`) and after it (`20:15:17Z`, `20:17:43Z`); each time only supervisord and the inspecting shell appeared. The advisory lock was free before and after.
- The whole 54-case allocation/submit/readback batch ran in exactly one invocation of `flock -x -w 900 /home/opencode-agent/rk3588-npu.lock`. The wrapper recorded `LOCK_ACQUIRED_UTC=2026-11-05T20:14:58Z WRAPPER_PID=3564184`, runner exit 0, `LOCK_RELEASE_UTC=2026-11-05T20:14:59Z`, and `FLOCK_RC=0`.
- One runner process processed the cases strictly sequentially (sorted directory order). No second submit process was launched. No retry was performed.

## Local bundle validation (before board access)

Command: `/usr/bin/python3 tools/validate.py` in `build/rk3588-example-captures/ew-fp16` (host Python 3.14.8, NumPy 2.4.6).

- 54 total, 54 READY, 0 BLOCKED; 0 structural errors; result PASS.
- Donor-oracle recompute: 54 checked, 0 mismatches.
- Manifest hashes, 22-QWORD regcmd template, three zero address placeholders, input patterns, 4096-byte inputs and expected.bin sizes were checked. This is a host structural/oracle check, not hardware validation.
- Evidence: `evidence/local-validation.log`, `evidence/tool_versions.txt`.
- Actual repo HEAD during this run: `6aa8e7a8054311ff7e60db5de6fd397a22540c82` (the manifest records the earlier preparation revision `d54d33bc8f910059b6237d54d77e173737282869`). Inputs are deterministic closed-form patterns with no RNG or seed.

## Runner provenance and compatibility

- Reused `build/rk3588-example-captures/board-worker/ew-int/ew_int_run.py` unchanged.
- Host and board SHA-256 both: `1ed990e7b1617ad606ae688980987e89e241789304d9b0e57a92cfa368b88e9a`.
- It correctly reads the ew-fp16 schema: one 22-QWORD task (`regcmd_offset_words=0`), exactly three `value32` patches at indices 14/15/16 for `out`/`a`/`b`, and 4096-byte `a`, `b`, `out` BOs. No schema extension was needed.
- The queue copied to the board was hash-identical to the host queue: 270/270 bundle files matched (`evidence/queue-board-sha256.txt` vs `evidence/queue-host-sha256.txt`).

## Execution result

- 54 cases executed; 54 `submit_ret == 0`; 54 `capture.json` status `OK`; 0 runner failures; 0 capture errors or cleanup errors.
- Every case read back the full 4096-byte output BO exactly as returned (54 x 4096 = **221184 bytes total**). The runner wrote that raw BO to `out.bin`; `expected.bin` was never substituted for device output.
- Capture durations sum to 91,659,152 ns; the lock was held for about 1 second.
- The output tree was copied back whole. Board and host hashes of all 54 `capture.json`, all 54 `out.bin`, and `summary.json` agree (109 files; hash-list SHA-256 `0f9fa62bff0caf20aee7f72c434a5955839c4501cbc2f57f2b68856fc1f57425`). Each capture's `hashes.out` equals its `out.bin` SHA-256.

## Logical-region comparison

Comparison is only over the manifest-declared logical region: the first `2*logical_count` bytes of the device BO versus `expected.bin`. The expected files are donor CPU NumPy results, not device captures.

| Op | Cases | Logical PASS | Logical FAIL | Mismatched halfwords | Non-finite cases |
|---|---:|---:|---:|---:|---:|
| ADD | 9 | 9 | 0 | 0 | 0 |
| FDIV | 9 | 7 | 2 | 20 | 0 |
| MAX | 9 | 9 | 0 | 0 | 0 |
| MUL | 9 | 9 | 0 | 0 | 0 |
| NEG | 9 | 9 | 0 | 0 | 0 |
| SUB | 9 | 9 | 0 | 0 | 0 |

Overall: **52/54 logical PASS, 2/54 logical FAIL**, 20 mismatched halfwords out of 6792 logical halfwords. No logical, padding or tail halfword decoded as Inf/NaN. The two failing cases are `fdiv_p1_n33` and `fdiv_p1_n1024`.

### Full-BO padding, reported separately

These are not counted as logical mismatches. For every one of the 54 cases, the physical padding lanes `[logical_count, padded_count)` and the rest of the 4096-byte BO `[padded_count, 2048)` read back as all zero halfwords. Thus the full-BO-vs-zero-padded-expected difference outside the logical region is 0 halfwords; `padding_nonzero_halfwords=0` and `tail_nonzero_halfwords=0` for every case. See `evidence/comparison.json` for per-case counts.

### FDIV divergence from the donor CPU oracle

The nine FDIV cases are finite-operand cases only. Seven match the donor CPU oracle exactly. Two cases contain 20 divergent logical halfwords. Every divergence is a positive finite value exactly one FP16 ULP below the donor result; the donor value is the nearest FP16 to the exact quotient, while the device value is the adjacent lower value (truncation toward zero for these positive quotients). No Inf/NaN or signed-zero anomaly was observed. This is reported as a real-device FDIV divergence, not forced to PASS.

| Case | Halfword | Byte offset | A (hex/f16) | B (hex/f16) | Exact quotient | Expected (hex/f16) | Device (hex/f16) | Device-expected bits |
|---|---:|---:|---|---|---|---|---|---:|
| fdiv_p1_n33 | 17 | 34 | 0x4c80 / 18.0 | 0x4700 / 7.0 | 2.5714285714285716 | 0x4125 / 2.572265625 | 0x4124 / 2.5703125 | -1 |
| fdiv_p1_n1024 | 17 | 34 | 0x4c80 / 18.0 | 0x4700 / 7.0 | 2.5714285714285716 | 0x4125 / 2.572265625 | 0x4124 / 2.5703125 | -1 |
| fdiv_p1_n1024 | 49 | 98 | 0x5240 / 50.0 | 0x4700 / 7.0 | 7.1428571428571432 | 0x4725 / 7.14453125 | 0x4724 / 7.140625 | -1 |
| fdiv_p1_n1024 | 57 | 114 | 0x5340 / 58.0 | 0x4700 / 7.0 | 8.2857142857142865 | 0x4825 / 8.2890625 | 0x4824 / 8.28125 | -1 |
| fdiv_p1_n1024 | 129 | 258 | 0x5810 / 130.0 | 0x4700 / 7.0 | 18.571428571428573 | 0x4ca5 / 18.578125 | 0x4ca4 / 18.5625 | -1 |
| fdiv_p1_n1024 | 185 | 370 | 0x59d0 / 186.0 | 0x4700 / 7.0 | 26.571428571428573 | 0x4ea5 / 26.578125 | 0x4ea4 / 26.5625 | -1 |
| fdiv_p1_n1024 | 273 | 546 | 0x5c48 / 274.0 | 0x4700 / 7.0 | 39.142857142857146 | 0x50e5 / 39.15625 | 0x50e4 / 39.125 | -1 |
| fdiv_p1_n1024 | 329 | 658 | 0x5d28 / 330.0 | 0x4700 / 7.0 | 47.142857142857146 | 0x51e5 / 47.15625 | 0x51e4 / 47.125 | -1 |
| fdiv_p1_n1024 | 385 | 770 | 0x5e08 / 386.0 | 0x4700 / 7.0 | 55.142857142857146 | 0x52e5 / 55.15625 | 0x52e4 / 55.125 | -1 |
| fdiv_p1_n1024 | 441 | 882 | 0x5ee8 / 442.0 | 0x4700 / 7.0 | 63.142857142857146 | 0x53e5 / 63.15625 | 0x53e4 / 63.125 | -1 |
| fdiv_p1_n1024 | 449 | 898 | 0x5f08 / 450.0 | 0x4700 / 7.0 | 64.285714285714292 | 0x5405 / 64.3125 | 0x5404 / 64.25 | -1 |
| fdiv_p1_n1024 | 505 | 1010 | 0x5fe8 / 506.0 | 0x4700 / 7.0 | 72.285714285714292 | 0x5485 / 72.3125 | 0x5484 / 72.25 | -1 |
| fdiv_p1_n1024 | 561 | 1122 | 0x6064 / 562.0 | 0x4700 / 7.0 | 80.285714285714292 | 0x5505 / 80.3125 | 0x5504 / 80.25 | -1 |
| fdiv_p1_n1024 | 617 | 1234 | 0x60d4 / 618.0 | 0x4700 / 7.0 | 88.285714285714292 | 0x5585 / 88.3125 | 0x5584 / 88.25 | -1 |
| fdiv_p1_n1024 | 673 | 1346 | 0x6144 / 674.0 | 0x4700 / 7.0 | 96.285714285714292 | 0x5605 / 96.3125 | 0x5604 / 96.25 | -1 |
| fdiv_p1_n1024 | 729 | 1458 | 0x61b4 / 730.0 | 0x4700 / 7.0 | 104.28571428571429 | 0x5685 / 104.3125 | 0x5684 / 104.25 | -1 |
| fdiv_p1_n1024 | 785 | 1570 | 0x6224 / 786.0 | 0x4700 / 7.0 | 112.28571428571429 | 0x5705 / 112.3125 | 0x5704 / 112.25 | -1 |
| fdiv_p1_n1024 | 841 | 1682 | 0x6294 / 842.0 | 0x4700 / 7.0 | 120.28571428571429 | 0x5785 / 120.3125 | 0x5784 / 120.25 | -1 |
| fdiv_p1_n1024 | 913 | 1826 | 0x6324 / 914.0 | 0x4700 / 7.0 | 130.57142857142858 | 0x5815 / 130.625 | 0x5814 / 130.5 | -1 |
| fdiv_p1_n1024 | 969 | 1938 | 0x6394 / 970.0 | 0x4700 / 7.0 | 138.57142857142858 | 0x5855 / 138.625 | 0x5854 / 138.5 | -1 |

Full machine-readable divergence data, including operands and exact fractions: `evidence/fdiv_divergence.json` and `evidence/fdiv_divergence.txt`.

## Per-case results

Every row is a real device capture. `submit_ret` is the runner return from the single submit for that case.

| Case | Op | Pattern | N | Padded | submit_ret | Logical | Mismatch halfwords | Padding nonzero | Tail nonzero |
|---|---|---|---:|---:|---:|---|---:|---:|---:|
| add_p1_n8 | ADD | p1 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| add_p2_n8 | ADD | p2 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| add_p1_n9 | ADD | p1 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| add_p2_n9 | ADD | p2 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| add_p1_n33 | ADD | p1 | 33 | 40 | 0 | PASS | 0 | 0 | 0 |
| add_p2_n33 | ADD | p2 | 33 | 40 | 0 | PASS | 0 | 0 | 0 |
| add_p1_n1 | ADD | p1 | 1 | 8 | 0 | PASS | 0 | 0 | 0 |
| add_p1_n7 | ADD | p1 | 7 | 8 | 0 | PASS | 0 | 0 | 0 |
| add_p1_n1024 | ADD | p1 | 1024 | 1024 | 0 | PASS | 0 | 0 | 0 |
| sub_p1_n8 | SUB | p1 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| sub_p2_n8 | SUB | p2 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| sub_p1_n9 | SUB | p1 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| sub_p2_n9 | SUB | p2 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| sub_p1_n33 | SUB | p1 | 33 | 40 | 0 | PASS | 0 | 0 | 0 |
| sub_p2_n33 | SUB | p2 | 33 | 40 | 0 | PASS | 0 | 0 | 0 |
| sub_p1_n1 | SUB | p1 | 1 | 8 | 0 | PASS | 0 | 0 | 0 |
| sub_p1_n7 | SUB | p1 | 7 | 8 | 0 | PASS | 0 | 0 | 0 |
| sub_p1_n1024 | SUB | p1 | 1024 | 1024 | 0 | PASS | 0 | 0 | 0 |
| mul_p1_n8 | MUL | p1 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| mul_p2_n8 | MUL | p2 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| mul_p1_n9 | MUL | p1 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| mul_p2_n9 | MUL | p2 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| mul_p1_n33 | MUL | p1 | 33 | 40 | 0 | PASS | 0 | 0 | 0 |
| mul_p2_n33 | MUL | p2 | 33 | 40 | 0 | PASS | 0 | 0 | 0 |
| mul_p1_n1 | MUL | p1 | 1 | 8 | 0 | PASS | 0 | 0 | 0 |
| mul_p1_n7 | MUL | p1 | 7 | 8 | 0 | PASS | 0 | 0 | 0 |
| mul_p1_n1024 | MUL | p1 | 1024 | 1024 | 0 | PASS | 0 | 0 | 0 |
| max_p1_n8 | MAX | p1 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| max_p2_n8 | MAX | p2 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| max_p1_n9 | MAX | p1 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| max_p2_n9 | MAX | p2 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| max_p1_n33 | MAX | p1 | 33 | 40 | 0 | PASS | 0 | 0 | 0 |
| max_p2_n33 | MAX | p2 | 33 | 40 | 0 | PASS | 0 | 0 | 0 |
| max_p1_n1 | MAX | p1 | 1 | 8 | 0 | PASS | 0 | 0 | 0 |
| max_p1_n7 | MAX | p1 | 7 | 8 | 0 | PASS | 0 | 0 | 0 |
| max_p1_n1024 | MAX | p1 | 1024 | 1024 | 0 | PASS | 0 | 0 | 0 |
| neg_p1_n8 | NEG | p1 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| neg_p2_n8 | NEG | p2 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| neg_p1_n9 | NEG | p1 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| neg_p2_n9 | NEG | p2 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| neg_p1_n33 | NEG | p1 | 33 | 40 | 0 | PASS | 0 | 0 | 0 |
| neg_p2_n33 | NEG | p2 | 33 | 40 | 0 | PASS | 0 | 0 | 0 |
| neg_p1_n1 | NEG | p1 | 1 | 8 | 0 | PASS | 0 | 0 | 0 |
| neg_p1_n7 | NEG | p1 | 7 | 8 | 0 | PASS | 0 | 0 | 0 |
| neg_p1_n1024 | NEG | p1 | 1024 | 1024 | 0 | PASS | 0 | 0 | 0 |
| fdiv_p1_n8 | FDIV | p1 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| fdiv_p2_n8 | FDIV | p2 | 8 | 8 | 0 | PASS | 0 | 0 | 0 |
| fdiv_p1_n9 | FDIV | p1 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| fdiv_p2_n9 | FDIV | p2 | 9 | 16 | 0 | PASS | 0 | 0 | 0 |
| fdiv_p1_n33 | FDIV | p1 | 33 | 40 | 0 | FAIL | 1 | 0 | 0 |
| fdiv_p2_n33 | FDIV | p2 | 33 | 40 | 0 | PASS | 0 | 0 | 0 |
| fdiv_p1_n1 | FDIV | p1 | 1 | 8 | 0 | PASS | 0 | 0 | 0 |
| fdiv_p1_n7 | FDIV | p1 | 7 | 8 | 0 | PASS | 0 | 0 | 0 |
| fdiv_p1_n1024 | FDIV | p1 | 1024 | 1024 | 0 | FAIL | 19 | 0 | 0 |

Machine-readable: `evidence/per_case.tsv`; per-case capture details and BO addresses are in each case `capture.json`.

## Evidence inventory

| File | Purpose |
|---|---|
| `summary.json` | runner summary: 54/54 OK, 54 submit_ret 0, 221184 bytes |
| `<case>/capture.json` | real BO addresses, handles, patches, hashes, durations, submit result |
| `<case>/out.bin` | full 4096-byte device readback, unmodified |
| `evidence/comparison.json` | per-case logical/padding/tail comparison and exact mismatch bits |
| `evidence/comparison.txt` | human-readable per-case logical lines and mismatches |
| `evidence/fdiv_divergence.json` | machine-readable FDIV exact-bit divergence |
| `evidence/fdiv_divergence.txt` | human-readable FDIV exact-bit divergence |
| `evidence/per_case.tsv` | per-case submit_ret and comparison table |
| `evidence/outputs-sha256.txt` | board-side hashes, first pass |
| `evidence/outputs-host-sha256.txt` | host-side hashes, first pass; identical to board |
| `evidence/outputs-final-board.txt` | board-side hashes, final re-hash |
| `evidence/outputs-final-host.txt` | host-side hashes, final re-hash; identical digest |
| `evidence/queue-*.txt`, `runner-host-sha256.txt`, `tool_versions.txt` | copied-queue and tool provenance |
| `evidence/preflight.txt`, `evidence/postrun.txt`, `evidence/run.log`, `evidence/run.exit`, `evidence/board_identity.txt` | board identity, pre/post race check, lock log, final 54x4096-byte output check |
| `evidence/local-validation.log` | host validation output |
| `evidence/compare_fp16.py` | host comparison script (stdlib only) |

## Claim boundary

This is RK3588 Rocket NPU silicon execution through `/dev/accel/accel0` only. No FPGA synthesis, bitstream load, board programming, flash, or physical FPGA execution occurred or is claimed. No tracked source, test, or documentation file was modified, and nothing was committed; all new files are under the ignored `build/` tree.

