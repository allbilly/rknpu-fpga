# Capture-bounded FP16 C3 max-pooling physical tail

Status: **one fixed standalone candidate, simulation-only**. This leaf covers
only `fp16_max_k2s2_c3_tail_h2w2`. It is separate from the unindexed C8,
indexed C8, average and minimum leaves. There is no PPU register decoder,
DMA/RDMA, AXI, full-top integration or FPGA execution.

## Captured contract and provenance

The source is `/home/fedora/rk3588/examples/expt/pooling.py`, SHA-256
`2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e`.
`pool_reference()` at lines 731–758 takes a maximum over each spatial window.
The `three_channels` source example at lines 1162–1182 uses FP16, C3, H2 W2 to
H1 W1, kernel 2x2, stride 2, no padding, `INDEX_EN=0`, `USE_CNT=0`; its three
logical outputs are `[20, 50, 60]`. The source explicitly fills unused physical
channels with `-99` and checks the tail.

The strict fixture manifest is
`tests/ppu_pooling/fixtures/fp16_max_k2s2_c3_tail_h2w2/manifest.json`. It binds:

- capture status `OK`, `submit_ret=0`, `/dev/accel/accel0`, kernel
  `6.18.24-current-rockchip64`, and runner `rocket_run.py 1.0.0`;
- input BO SHA-256
  `3c0a48b29e8a1b468b099de58fec3d16e73eaff64aca711ea9f0b60887cfe9be`;
- source expected and device output BO SHA-256
  `e418e3dc9a8d3e678e369b58d817b8aadd073cd46dca3a7d251c90031a54af14`;
- original 26-QWORD raw command stream SHA-256
  `9dc604e7342f0759b63222d24bbf4721cc50a6b6ec4becad1ffdb0c92205a55c` and the
  separately captured address-patched stream. The leaf does not decode or
  execute either stream.

Input atoms are 16-byte C1HWC2 pixels with a 32-byte line stride and 64 logical
bytes total. Each atom has three logical FP16 lanes followed by five `-99`
physical lanes. The result is one eight-lane/16-byte atom:

```text
logical channels: [20, 50, 60]
physical tail:    [-99, -99, -99, -99, -99]  // FP16 bits 0xd630
```

The captured 4096-byte device output exactly matches the source expected BO.
Only bytes 0–15 are written; bytes 16–4095 remain identical to `out_init.bin`.
All values in this fixture are finite and nonzero. This case does not establish
generic NaN, infinity, signed-zero, subnormal or tie policy. The runner rejects
data outside this pinned input-value contract; unsupported behavior remains
explicitly unqualified.

## Leaf and verification

`rtl/ppu/rk_ppu_pool_max2x2s2_c3_tail_h2w2.sv` consumes four raster-order input
atoms and produces one output atom using a paired valid/ready handshake. It
compares all eight physical lanes, including the five captured tail lanes. The
single-frame leaf rejects another input frame until reset and holds its output
stable under backpressure.

`tools/ppu/run_pool_c3_tail.py` pins all fixture file hashes and mode/layout
fields, independently checks the finite source MAX oracle and tail, validates
capture metadata against the device BO and command stream, and runs Icarus and
Verilator in always-ready and forced-stall modes (seeds `0x3588` and `0x600d`).
The testbench and runner compare all 4096 bytes to the device output and check
all eight lanes, the untouched BO tail, `out_last`, stall stability, and
post-frame input rejection. Contract tests reject mode/shape/layout drift,
non-finite values, zeros and modified physical input tails.

Use:

```sh
make ppu-c3-tail-contract-test
make ppu-c3-tail-four-state-test # Icarus Verilog
make ppu-c3-tail-test            # Verilator
verilator --lint-only -Wall --top-module rk_ppu_pool_max2x2s2_c3_tail_h2w2 \
  rtl/ppu/rk_ppu_pool_max2x2s2_c3_tail_h2w2.sv
```

Focused replay results on source revision `83f599cad5485809090d5867fd0ed9f198e2e3dd`
(the runner also hashes the uncommitted C3 RTL, testbench, runner and fixture
before and after each simulation):

| Simulator | Version | Runs | Input atoms | Output lanes | Full BO mismatches | Stall cycles (always / forced) |
|---|---|---:|---:|---:|---:|---:|
| Icarus Verilog | 13.0 | 2 | 4 | 8 | 0 | 0 / 1 |
| Verilator | 5.048 (2026-04-26 build) | 2 | 4 | 8 | 0 | 0 / 1 |

Both outputs have SHA-256
`e418e3dc9a8d3e678e369b58d817b8aadd073cd46dca3a7d251c90031a54af14`;
there were no compiler warnings. Reports, logs and observed BOs are in
`build/ppu-pooling/c3-tail-iverilog-20261106T194535Z/` and
`build/ppu-pooling/c3-tail-verilator-20261106T194535Z/`. Each report records
the seeds, exact source/fixture hashes, `hardware_accessed=false`, full-BO
comparison, stable output under stall and post-frame input rejection.

This is captured-fixture standalone simulation evidence only. It does not
qualify FPGA execution, RK hardware beyond the source capture, PPU register or
DMA behavior, or any other C3 shape/tail policy.
