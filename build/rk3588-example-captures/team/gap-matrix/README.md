# Example to FPGA RTL gap matrix

This directory is a static, device-free census of every Python example under
`/home/fedora/rk3588/examples`, including `expt/` and `kernel_6_18/`, plus the
six supporting Markdown notes. It maps the RKNPU hardware blocks those examples
exercise to the RTL that actually exists in this repository.

Artifacts:

- `EXAMPLE_MATRIX.json` — machine-readable example census, block support,
  capture accounting and top gaps.
- `GAP_MATRIX.md` — readable census, block table and top-five gap report.
- `generate_matrix.py` — regenerates both files from the current manifests,
  existing results and the hard-coded per-file metadata.

No board access was used: no `ssh`, `scp`, submit, FPGA programming or flash.
No tracked source, test or doc outside this directory was edited.

## Method

1. Enumerate every `*.py` under `/home/fedora/rk3588/examples` and record its
   entry point, CLI, device ABI (`/dev/dri/card1` vendor, `/dev/accel` Rocket,
   or device-free subcommands), hardware blocks and register families. The six
   `.md` files are recorded as notes.
2. Load every `build/rk3588-example-captures/*/manifest.json`.
3. Load existing `build/rk3588-example-captures/results/*/summary.json` and
   their `compare.json` / `evidence/comparison.json`. A case counts as
   **captured** only if its case directory contains `capture.json` and
   `out.bin`; oracle PASS is counted separately.
4. Read the actual RTL (`rtl/rk_fp16_alu.sv`, `rtl/rk_ew_*.sv`,
   `rtl/cmac/*`, `rtl/rk_cmac_*.sv`, `rtl/ddr/framework/*`) and the relevant
   docs (`docs/INTERFACE.md`, `docs/PC_DMA.md`,
   `docs/CMAC_PROFILE_CANDIDATE.md`, `docs/FRAMEWORK_FULL_PROFILE.md`,
   `docs/REVIEW_AND_PLAN.md`).
5. Classify each example and bundle case. Labels are non-exclusive because a
   file can be runnable, vendor-only and blocked by a missing RTL block at the
   same time.

## Status vocabulary

| Status | Meaning |
|---|---|
| `captured_exact` | Real RK3588 capture plus an exact oracle comparison. |
| `captured_tolerance` | Real capture plus a tolerance PASS that is not byte-exact. |
| `captured_known_divergence` | Real capture that differs from the declared oracle; the difference is known and scoped. |
| `captured_truth_table` | Truth-table/characterization capture with no pass/fail oracle by design (`fdiv-systematic`). |
| `captured_unverified` | Real capture but no completed oracle comparison. |
| `captured_not_implemented` | Device proves the operation, but the FPGA RTL does not implement it (FDIV). |
| `prepared_not_run` | `READY`, runner-valid bundle with no real output BO yet. |
| `blocked_missing_abi` | Needs a vendor RKNPU / multi-core / PC-chain ABI the Rocket/FPGA path does not provide. |
| `blocked_missing_rtl` | An arithmetic or data-movement block has no RTL. |
| `blocked_unsupported_dtype_shape` | Dtype, geometry, pad/stride/grouped contract, oracle or source evidence unsupported. |
| `blocked_multitask_execution` | Multi-task Rocket job unsupported; the case is BLOCKED or split into one-task bundles. |
| `blocked_bundle_integrity` | Manifest READY but the official runner validator rejects the bundle. |
| `unknown` | Semantics or output contract not established. |

## Snapshot at generation

- 25 Python examples: 17 runnable, 6 duplicates, 2 drafts.
- 6 notes.
- 7 capture bundles, **140** manifest cases:
  - 122 READY, 18 BLOCKED.
  - **122 captured on RK3588 Rocket**: 54 `ew-fp16`, 15 `ew-int`,
    19 `pooling`, 8 `fdiv-systematic`, 9 `conv-fp16`, 10 `conv-gemm-vendor`,
    7 `conv-simple`.
  - 107 exact PASS, 2 tolerance-only PASS, 5 known divergences,
    8 truth-table cases, 0 captured-unverified.
  - 0 prepared but not run.
  - 0 current runner-invalid.
  - 18 blocked: 3 missing ABI, 12 dtype/shape/oracle, 3 multi-task execution.
- 0 FPGA executions of these bundles.

`ew-int` is 15/15 exact; `int16_add_to_int32_c8_w1` is a 31-QWORD bundle that
needs one zero fetch-padding QWORD only for generic-runner replay. `pooling`
is 19/19 full-BO exact over 77,824 bytes; the 2 blocked FP32/INT32 probes were
not run. `fdiv-systematic` is 8/8 captured, 512 bytes and 256 operand classes,
with oracle none by design.

`ew-fp16` is 54 captured: 52/54 donor-oracle exact. The two FDIV A/7 cases
`fdiv_p1_n33` and `fdiv_p1_n1024` differ on 20 halfwords; the three-guard-bit
ties-to-even contract explains them and matches 1452/1452 real lanes. This is a
known divergence from the donor oracle, not global truncation. The 32-lane
finite sweep and the 256-class truth table are correctly rounded nearest-even.

`conv-fp16` is 9/9 exact after the multi-task split (35,392 bytes); the 5
BLOCKED cases are 2 combined multi-task, pad-register, split-K and vendor ABI.
`conv-gemm-vendor` is 10/10 PASS (8 exact, 2 tolerance; 95,744 bytes counting
the 15,104-byte depthwise rerun). The depthwise `_task0`/`_task1` rerun is
702/702 exact after the 15,104-byte BO fix. `conv-simple` is 4/7 exact: 1
FP32-output C32 structural placement/zero-fill mismatch and 2 INT8 +1 LSB
output-conversion divergences. Only selected N=8 EW commands have an RTL
simulation receipt; the full captured queues have not been replayed through
RTL or FPGA.

## Key RTL facts used

- The implemented EW endpoint is strict FP16 ADD/SUB/MUL/MAX at eight lanes,
  with a fixed register profile. NEG is MUL by -1. FDIV is explicitly rejected.
- No integer EW, BS/BN/LUT arithmetic, PPU, CNA/CBUF/CSC convolution, or
  general RDMA/surface path exists in `rtl/`.
- A strict FP16 C32/K16 CMAC/CACC terminal profile exists, but it is not a
  general GEMM or convolution engine and is not the default EW board endpoint.
- `rk_ew_dma` supports linked EW tasks and raw PC command fetch, not the
  vendor `core_mask`/`subcore_task` ABI or general DPU RDMA.

## Caveats

- `READY` is a preparation state, never a capture.
- RK3588 Rocket captures do **not** validate the FPGA, SystemVerilog timing,
  a bitstream, or flash.
- RTL simulation and C++/Python tests do not validate the physical FPGA or
  RK silicon.
- The queue-index team snapshot is stale for this census: it still lists
  runner-invalid and prepared counts that the current job fixes and new
  captures supersede. This census re-derives counts from the current manifests
  and result directories; rerunning `generate_matrix.py` will pick up later
  results.
- Capture results are consumed as host-side receipts. This census did not
  independently re-audit the board run, oracle implementation or result hashes.
- The bundle state changed during the refresh: `conv-gemm-vendor` and
  `conv-fp16` split multi-task cases into one-task READY bundles. The queue is
  now 140 cases, not 134; 122 READY are all captured and 18 are BLOCKED.
- The FDIV correction is specific: the 32-lane finite sweep and the 256-class
  truth table are correctly rounded nearest-even; the EW FP16 A/7 cases
  `fdiv_p1_n33` and `fdiv_p1_n1024` are the known divergence. The
  three-guard-bit ties-to-even contract explains the 20 halfwords and matches
  1452/1452 real lanes. Do not generalize that exception to all FDIV inputs or
  describe FDIV as globally truncating.
- `pooling` is 19/19 full-BO exact over 77,824 bytes; the 2 blocked FP32/INT32
  probes were not run. `fdiv-systematic` is 8/8 captured, 512 bytes and 256
  operand classes, with no pass/fail oracle by design.
- `conv-fp16` is 9/9 exact after the multi-task split (35,392 bytes). The 5
  BLOCKED cases are 2 combined multi-task, pad-register, split-K and vendor
  ABI. The old `conv-fp16-20261105T205900Z` tree retains 2 now-BLOCKED combined
  captures (8,192 bytes) as task-1-all-zero evidence.
- `conv-gemm-vendor` is 10/10 PASS (8 exact, 2 tolerance; 95,744 bytes counting
  the 15,104-byte depthwise rerun). The depthwise `_task0`/`_task1` rerun is
  702/702 exact after the 15,104-byte BO fix; `conv-gemm-vendor-20261105T214000Z`
  contributes the other 8 cases.
- `conv-simple` is 4/7 exact: the FP32-output C32 case is a structural
  placement/zero-fill mismatch, and the two INT8 cases each differ at +1 LSB
  on a small prefix subset. These are known divergences, not exact passes.
- Examples marked duplicate/draft are recorded as such for census purposes;
  this is not a claim that their register programming was independently
  verified.
- `__pycache__/*.pyc` files under the examples tree are generated bytecode,
  not source examples, and are excluded from the census.
- Some files are vendor-ABI only, so they cannot execute directly on the
  Rocket/FPGA path even when the underlying block exists.
- No capture bundle is ever a CPU oracle. The JSON records the oracle status
  separately from the device output.

## Regenerate

```sh
cd /home/fedora/rknpu-fpga
python3 build/rk3588-example-captures/team/gap-matrix/generate_matrix.py
```

The generator reads only the manifests/results/RTL/docs and writes only
`EXAMPLE_MATRIX.json` and `GAP_MATRIX.md` in this directory.
