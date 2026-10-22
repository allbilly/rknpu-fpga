# Historical RK raw captures: useful, not yet a matched replay bundle

Read-only donor audit, 2026-09-21. No RK or FPGA execution was performed.
The working tree alone is insufficient: `/home/fedora/npu` commit `5c355af`
removed tracked dump files. Commit
`2cd0173624ac21f707b0facf624d8b2a65dcdb92` retains the artifacts below.
Retrieve exact bytes with `git -C /home/fedora/npu show COMMIT:PATH`;
do not check out or modify the donor repository to recover them.

## Small convolution evidence

The named workload has input NCHW `(1,3,5,7)`, weights `(6,3,2,3)` and
120 logical outputs. Its raw files are under `ops_rknn/dump/`:

| Artifact | Observed content |
|---|---|
| `gem1-dump` | Task descriptor with command address `0xffce8a40` |
| `gem2-dump` | 12 KiB BO; 576-byte packed weight prefix and candidate 112-QWORD command window at `0xa40` |
| `gem5-dump` | 105 logical FP16 inputs, NHWC with row width padded from 7 to 8 |
| `gem6-dump` | 120 logical FP16 outputs, 20 pixels with 8 channel slots (6 logical) |
| `conv2d_i1357_w6323_fp16_fulldump.h` | RKNN run log with printed input and actual output |

All 105 input and 120 output halfwords match the corresponding printed decimal
values converted to FP16. The complete 4096-byte `gem6-dump` also equals
`ops_reg/dump/gem4-dump` from the same commit (Git blob
`4acabb149c029aafc6f94154f285d0e4fe2079b9`). These are content checks, not
proof of when or in which invocation each buffer was captured.

The weight generator `ops_rknn/generate_conv2d_models.py` and host reference
`ops_rknn/conv2d_multi.cpp` define weights by `(oc+kh+kw)%3` as `1,-1,0`,
identical across the three input channels. The 576-byte prefix matches
`kh, kw, oc, padded_ic` order with eight input-channel slots. An initial audit
incorrectly assumed `oc, kh, kw, padded_ic` and failed. Inspecting the actual
rows and CSC within-output-block traversal corrected that audit assumption;
no captured bytes or RTL/test expectations were changed. Repeated weights
cannot establish a unique general permutation, and this shape does not test
channel-atom boundaries.

## Why this is not yet a replay golden

The capture addresses contradict a single-run interpretation:

| Evidence | Address |
|---|---|
| Saved first-task command pointer | `0xffce8a40` |
| Raw CNA weight address | `0xffcf4000` |
| Command pointer implied by that BO and offset | `0xffcf4a40` |
| Raw CNA input / DPU output | `0xffcf3000` / `0xffcf2000` |
| Full-dump log's weight allocation | `0xffec8000` |
| Separate `ops_rknn/run_output.txt` weight allocation | `0xffcf4000` |

Same commit does not mean same run. The saved GDB scripts also do not by
themselves bind every raw output to a completed submission and reset state.
Do not repair descriptors, relocate commands or pair buffers solely by GEM
handle and then claim an unchanged silicon capture.

The current strict EW endpoint also rejects this convolution profile and its
high device addresses. These files do not close differential gate B or prove
RK special-value/reduction behavior. They are candidates for reconstructing
provenance and deriving a future explicitly supported CNA/CSC contract.

## Reproducible local audit

The continuation's `build/audit_npu_history.py` extracts pinned Git blobs,
records blob IDs and SHA256s, checks the counts/content above and asserts the
address mismatch. Its successful inspection report is
`build/npu_history_2cd0173/report.json`; the initial weight-order assertion
failure remains in `build/npu_history_audit.log`. These build artifacts are
not portable checked-in fixtures or an RTL verification result.

Other history leads include `e6feba9` (ADD 1x8), `e46ea49` (MUL),
`a6bf275` (FP32 accumulation ADD), `509027c` (1D convolution), and
`d4a2c4f` (batches). Their names are not validation claims. Before using any,
check raw task-to-command addresses, buffer sizes/layouts, capture phase,
driver/runtime versions and post-execution output provenance independently.
