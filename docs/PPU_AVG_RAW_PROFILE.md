# Captured C8 average-pooling raw-command profile and DMA

Status: **one capture-bounded strict profile and owned-DMA candidate,
simulation-only** for `fp16_avg_k2s1_valid_c8_h4w4`. It remains separate from
the MAX and minimum profiles; it is not general RK3588 PPU support, full-top
qualification, routed-image evidence or FPGA execution.

## Captured command and numerical contract

The pinned case is FP16 average pooling, 2x2 kernel, stride 1, valid padding,
C8 H4xW4 to H3xW3, `INDEX_EN=0`, `USE_CNT=0`. The original command is 28
QWORDs (224 bytes), distinct from the 26-QWORD max/min profiles. Only QWORD 15
(output base) and QWORD 22 (input base) relocate according to the captured job;
the runner verifies all other command bytes remain unchanged. The strict gate
checks every target, register offset, fixed value, terminal marker and address
field. QWORD 8 identifies average mode (`0x4001000000106024`); the two captured
FP17 reciprocal words are checked exactly.

The fixture under
`tests/ppu_pooling/fixtures/fp16_avg_k2s1_valid_c8_h4w4/` binds the source
command, job patch list, 4096-byte input and initialized output BOs, and the
complete device output BO. The 128 input lanes are finite normal FP16 values in
`[-4, 11.875]` plus `+0`. The DMA rejects infinities, NaNs, subnormals, `-0`,
and values outside that captured interval. This is a capture-bounded admission
contract, not a general special-value or IEEE arithmetic policy.

## Transfer and execution contract

The strict profile publishes a 256-byte input transfer and 144-byte output
transfer. The shared DMA fetches all 28 QWORDs and performs 112 command
halfword reads, 128 input halfword reads and 72 output halfword writes: **312
single-outstanding serialized transactions per job**. It validates all input
lanes and buffers the nine output atoms before beginning writes. A successful
job compares the complete 4096-byte output BO, including the initialized tail;
the same-epoch repeat checks 624 total transactions and compares the full BO
again. The standalone leaf was byte-exact against this device capture in both
simulators; this establishes no hardware result for the integrated RTL.

The independent validator is `rtl/ppu/rk_ppu_pool_avg_raw_profile.sv`; the
capture-bounded average leaf is
`rtl/ppu/rk_ppu_pool_avg2x2s1_fp16_capture.sv`; both run through
`rtl/ppu/rk_ppu_pool_raw_dma.sv` and owned dispatch kind 3. Layout kind 2 and
its `RKLY` page remain distinct. No runtime CPU arithmetic, layout repair,
software fallback or command rewrite beyond the two declared relocations is
used.

## Verification and evidence boundary

`make ppu-avg-raw-profile-test` and
`make ppu-avg-raw-profile-four-state-test` replay the strict command gate in
Verilator and Icarus. Fifteen end-to-end negative controls cover command
mutations, descriptor/aperture/address failures and invalid FP16 inputs,
including out-of-range values and a late invalid lane; rejected input produces
no output writes. The DMA suite also checks a valid job, a same-epoch repeat and
complete BO comparisons.

On source revision `8011ff662f6a6877d0eac4e2e4a03ab3aededc0c`, Icarus Verilog
13.0 and Verilator 5.048 pass the raw profile (28 QWORDs, relocations `[15,22]`,
12 profile negative controls) and integrated DMA (312 transactions/job, 624
for repeated jobs, complete 4096-byte BO comparisons and 15 end-to-end negative
controls). Receipts:

- `build/ppu-pooling/avg-raw-profile-iverilog-20261107T033425Z/report.json`;
- `build/ppu-pooling/avg-raw-profile-verilator-20261107T033425Z/report.json`;
- `build/ppu-pooling/avg-raw-dma-iverilog-20261107T034859Z/report.json`;
- `build/ppu-pooling/avg-raw-dma-verilator-20261107T034859Z/report.json`.

These are simulation results only. The PPU-enabled source selection has not
received full-top synthesis, placement/routing, timing/DRC qualification or
FPGA execution; the currently documented K8 image remains PPU-free.
