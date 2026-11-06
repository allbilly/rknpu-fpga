# Capture-bounded FP16 average PPU leaf

Status: **one fixed standalone candidate, simulation-only**. The source is
`rtl/ppu/rk_ppu_pool_avg2x2s1_fp16_capture.sv`. It does not connect to the raw
command decoder, backend, PPU registers, DMA/RDMA, AXI, a full top or an FPGA.
No board or hardware was accessed for this RTL increment.

## Fixed case and evidence

This leaf admits only the captured case
`fp16_avg_k2s1_valid_c8_h4w4`: FP16 average, 2x2 kernel, stride 1, zero
padding, C8 H4 W4 to H3 W3, `INDEX_EN=0`, `USE_CNT=0`, one surface. Its input
uses 16-byte C1HWC2 atoms and 64-byte lines in a 4096-byte BO. Its nine output
atoms occupy 144 bytes at 48-byte line stride in the original 4096-byte output
BO. Bytes 144 through 4095 remain initialized and unwritten.

The fixture copies the source bundle's `in.bin`, `expected.bin`, `job.json` and
`regcmd.bin`, plus the original device `out.bin` (renamed
`device_out.bin`), initialized output BO and device `capture.json`. SHA-256 and
byte counts for all fixture files are in
`tests/ppu_pooling/fixtures/fp16_avg_k2s1_valid_c8_h4w4/manifest.json`. It also
binds source example SHA-256
`2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e`, pooling
bundle manifest SHA-256
`42b7ae1c9cbe80d48b9f59ed2f675bdc280d6daa7b22e720a7eee8794db0afd7` and
device capture metadata SHA-256
`6623a95632b1f85e235b27779d62f362c3cdc217fb069ac2119be10d8f110860`.
The original decoded `regcmd.txt` is hash-bound but not copied because its
tab-delimited format has trailing empty patch columns; the byte-exact QWORD
stream is retained as `regcmd.bin` without normalization.

The device metadata records `status=OK`, `submit_ret=0`, `/dev/accel/accel0`,
`rockchip,rk3588s` / `xunlong,orangepi-5`, kernel
`6.18.24-current-rockchip64`, and `rocket_run.py 1.0.0`. The device BO SHA-256
is `bea3f03feb736de6e310172765cdfc560bcbd8bb81e90d6ff9e7f0ba45fb7545`; the
source `expected.bin` has the same hash and is byte-identical over the complete
4096 bytes. This is capture evidence, not a new device run.

## Numerical contract boundary

The source `pool_reference()` at `examples/expt/pooling.py` lines 731–758
converts each window to FP32, takes the mean over the two spatial axes, then
casts the result to FP16. The case definition at lines 796–818 pins 2x2/stride-1
and sets absolute tolerance to **0.0625**. The captured input consists of 128
finite FP16 lanes in the logical surface, spanning −4 through 11.875. For this
input, all 72 device output lanes exactly equal the source oracle; each output
is representable in FP16. The RTL uses a finite-value exact aligned sum and a
nearest/even final pack, which satisfies that fixed source tolerance on the
captured data.

This does **not** establish a general RK PPU FP16 rounding mode: the source
contract's tolerance is retained, while exact equality is an observation for
this fixture only. NaN/infinity policy, non-captured finite values, alternate
accumulation orders, padding, other shapes/kernels/strides, other average
precisions, `USE_CNT` values, `INDEX_EN`, minimum/maximum and global pooling
remain unsupported and unqualified. The RTL intentionally emits unknown
simulation data for exponent-31 inputs rather than assigning them an inferred
special-value result. The module accepts one frame and refuses a seventeenth
input atom until reset.

## Interface and tests

The leaf uses a single-clock valid/ready stream of 16-byte atoms. It consumes
exactly 16 raster-order atoms and emits nine raster-order atoms. Output data and
`out_last` stay stable whenever a valid output is stalled. Reset is required
before another frame. It has no shape, method, padding or index inputs to
silently ignore.

The runner checks fixture hashes and the fixed mode/shape contract before
compilation. Icarus Verilog and Verilator each run always-ready and deterministic
backpressure modes (seeds `0x3588` and `0x600d`). Tests check 16 input handshakes,
nine output handshakes, final-beat marking, output stability under stalls and
rejection of any post-frame input. The whole 4096-byte BO is accounted for:
each of 72 FP16 lanes must be within 0.0625 of both the device output and source
oracle; every byte in the untouched tail must equal `out_init.bin`. Runner
reports also record exact-byte differences as diagnostics. A separate Python
negative-control test mutates the method, geometry, padding, index/use-count,
layout stride and tolerance; each unsupported variant must be rejected.

Focused run results: Icarus Verilog 13.0 and Verilator 5.048 (2026-04-26
build), two modes each, 16 input atoms and nine output atoms per run. Both
simulators report zero source/device lane tolerance violations, exact zero
byte differences for this capture, max absolute difference 0.0 and zero tail
mismatches. The backpressure run observes one output-stall cycle in each
simulator; its stable-output assertion and the post-frame input rejection pass.
Reports are `build/ppu-pooling/average-iverilog-20261106T163901Z/report.json`
and `build/ppu-pooling/average-verilator-20261106T163901Z/report.json`. Both
record Python 3.14.5, GCC 16.2.1, seeds, fixture/source hashes, no warnings,
and `hardware_accessed=false`. The report's Git revision is the candidate's
base commit `d78644b`; `git_status_before` records the isolated candidate's
uncommitted files, while explicit RTL/test/fixture SHA-256s bind the run.

Run:

```sh
make ppu-avg-contract-test
make ppu-avg-four-state-test # Icarus
make ppu-avg-test            # Verilator
verilator --lint-only -Wall --top-module rk_ppu_pool_avg2x2s1_fp16_capture \
  rtl/ppu/rk_ppu_pool_avg2x2s1_fp16_capture.sv
```

Reports, logs and observed BOs are written under `build/ppu-pooling/average-*`;
simulator build products are pruned by default. Every report binds the source
and fixture hashes, source revision, tool versions, seeds and
`hardware_accessed=false`. Icarus/Verilator tests are simulation evidence only;
they are not full-top, FPGA, Vivado or RK silicon qualification.
