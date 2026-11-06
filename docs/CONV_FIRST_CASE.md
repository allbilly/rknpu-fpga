# Captured FP16 1x1 C8 convolution slice

This is the first functional convolution increment only:
`conv_1x1_valid_c8_h5_w5_oc8`, FP16 input/weights/output, valid 1x1,
stride 1, groups 1, C8/H5/W5 to OC8/H5/W5.

The RTL accepts the captured **54 raw final command QWORDs** unchanged, with
the capture's task-end marker as a sideband on QWORD 54. It strictly validates
the ordered CNA/CORE/DPU body and four-word terminal tail before touching the
operand or output BOs. The body permits only the three address patches defined
by the captured job. It rejects other addresses that are unaligned, overflow
the 32-bit address space or overlap one another. It does not fetch commands
from a DMA descriptor and is not a complete conv DMA/top integration.

`rk_conv_array_front` reads the original 800-byte input and 256-byte weight
BOs. It gathers the eight real C lanes and expands the 8x8 weight values into a
C32/K16 arithmetic frame in hardware: input C8..C31, each kernel's IC8..IC31,
and OC8..OC15 have zero data/weight and disabled masks. The CACC result is
sent to a convolution-specific FP16 atom sink. Each of 25 output atoms starts
at `out_base + atom*16`; the complete FP16 plane stride is 400 bytes. The K8
GEMM `+16/+64` atom advance is not used. Only the real OC0..OC7 plane is
written; the other three aligned output planes are not treated as numeric
results.

## Reproduce

```sh
make generated-check
make conv-first-case-test
```

The test runs Icarus and Verilator against the checked-in capture bytes. It
checks every accepted command, every input/weight read address and value, all
25 expanded frames and masks, all 200 output writes and acknowledgements, the
logical NCHW oracle, and all 1600 bytes of the output BO. It also runs strict
profile negatives (bad target/value/shape/tail/boundary/address/overlap) and
memory-error/timeout cases. There is no software arithmetic, input/weight
repack or runtime output repair.

## Recorded verification

The initial 2026-11-06 focused run passed all 11 modes on Icarus 13.0 and
Verilator 5.048, with seed `0xc08c8a25`. After merging current main into the
isolated worktree (`3e379c9`), the post-merge report again passes all 11 modes
on each simulator and matches hashes for all 28 source/fixture inputs. The
Verilator report retains its 88 warning headers and warning-kind counts. The
post-merge report is `build/convolution-first-case/report.json`.

The first broad regression, on the pre-merge source, stopped at
`ddr-dual-host-npu-test`: its frontend manifest pinned the previous backend
manifest hash. This was not waived; the current-main merge refreshed the
manifest/profile chain. After the merge, `core_source_paths()` selected all 72
expected sources and the full `make test` passed with exit code 0, including
`PASS_ACTUAL_NPU_DUAL_HOST_NATIVE_ONLY` and both process-control runs. Its log
and exit receipt are `build/convolution-first-case/post-main-merge/make-test.log`
and `make-test.rc`.

The full-BO comparison seeds the model's output allocation from the captured
1600-byte post-run BO and requires exact equality after execution. Capture
provenance says only plane 0 (400 bytes) is defined; planes 1..3 are preserved
byte-for-byte as captured padding and are not promoted to a numeric oracle.
The output transaction checks independently require the 200 real FP16 writes
to match both the raw plane-0 capture and the donor `expected.bin` exactly.

Fixtures and their hashes are documented in
[`tests/conv/fixtures/conv_1x1_valid_c8_h5_w5_oc8/README.md`](../tests/conv/fixtures/conv_1x1_valid_c8_h5_w5_oc8/README.md).
Each run writes tool versions, source/fixture/runner hashes, seed, per-mode
results and compiler warning headers under ignored
`build/convolution-first-case/`. The hashed runner defines the exact invocations;
logs and reports are retained, while simulator binaries and Verilator object
directories are regenerable and should be pruned after the results are recorded.

## Limits

- Simulation-only; no board, FPGA, RK differential, full-top Vivado or bitstream
  result is claimed.
- This decoder accepts one captured task profile only. It does not support
  alternate field order, duplicate writes, other shapes/dtypes, true CNA pad,
  stride, spatial windows, groups, depthwise, multi-task, split-K, FP32 output,
  INT8 or general CBUF/CSC behavior.
- The numerical match is bound to this capture and donor arithmetic. It does
  not establish a complete FP16 convolution numerical contract for RK silicon.
