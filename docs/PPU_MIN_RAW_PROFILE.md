# Captured C8 minimum-pooling raw-command profile and DMA

Status: **one capture-bounded strict profile and owned-DMA candidate,
simulation-only** for `fp16_min_k2s1_valid_c8_h4w4`. This is separate from the
C3 tail, valid-C8 MAX and padded-negative-C8 MAX profiles. It is not general
RK3588 PPU support, full-top qualification, routed-image evidence or FPGA
execution.

## Captured command and numerical contract

The capture is FP16 minimum pooling, 2x2 kernel, stride 1, valid padding, C8
H4xW4 to H3xW3, `INDEX_EN=0` and `USE_CNT=0`. The source
`pooling.py::pool_reference()` applies `np.min` to each spatial window and
requires exact FP16 output equality. The raw 26-QWORD command uses the same
address relocation entries as the other selected cases (QWORD 13 destination,
QWORD 20 input); every other word remains exact. QWORD 8's full value
`0x4001000000126024` selects minimum pooling. Valid C8 MAX uses
`0x4001000000116024`; a nearby or unsupported value is not ignored.

The fixture is
`tests/ppu_pooling/fixtures/fp16_min_k2s1_valid_c8_h4w4/`. It binds the RK3588
capture, raw command, job patch list, 4096-byte input and initialized output
BOs, and complete captured output BO. The source hash, job and output bytes are
checked by `tools/ppu/run_pool_min.py` and the raw-profile runner. Its 128 input
halfwords are finite normals plus one positive zero; there is no negative zero,
subnormal, infinity or NaN. The integrated raw path enforces that captured data
domain explicitly. It does not claim generic NaN, infinity, subnormal or
signed-zero minimum semantics.

## Transfer and execution contract

The strict profile publishes 256 input bytes and 144 output bytes. The owned
DMA performs exactly 104 command halfword reads, 128 input halfword reads and
72 output halfword writes: **304 serialized transactions per job**. It checks
each input halfword, feeds the fixed minimum leaf, buffers all nine output
atoms, and begins device writes only after all 128 lanes have passed validation
and all nine outputs are buffered. A successful job compares the complete
4096-byte output BO to the device capture, including the initialized untouched
tail. The same-epoch repeat checks 608 total transactions and compares the
complete BO again.

The independent validator is `rtl/ppu/rk_ppu_pool_min_raw_profile.sv`; the
numerical leaf is the existing
`rtl/ppu/rk_ppu_pool_min2x2s1_fp16_capture.sv`; both are integrated by
`rtl/ppu/rk_ppu_pool_raw_dma.sv`. The route is owned dispatch kind 3; layout
kind 2 and its `RKLY` page remain distinct. No host arithmetic, runtime layout
repair, command rewriting beyond the two declared address relocations, or
software-reference fallback is used.

## Verification and evidence boundary

`make ppu-min-raw-profile-test` and
`make ppu-min-raw-profile-four-state-test` replay all 26 QWORDs through the
strict validator in Verilator and Icarus, with 12 negative controls.
`make ppu-min-raw-dma-test` and
`make ppu-min-raw-dma-four-state-test` exercise the owned serialized path,
whole-BO comparison, same-epoch repeat, five invalid input classes and command
mutations; there are 11 end-to-end negative controls. Fixture, geometry,
signature, finite-input and write-order constraints also have Python contract
tests.

On source revision `8011ff662f6a6877d0eac4e2e4a03ab3aededc0c`, Icarus Verilog
13.0 and Verilator 5.048 pass the 26-QWORD profile and all 12 profile controls.
The integrated DMA passes both simulators with 304 transactions per job, 608
over the repeated same-epoch jobs, complete 4096-byte output comparisons and
11 negative controls. The receipts are:

- `build/ppu-pooling/min-raw-profile-iverilog-20261107T030726Z/report.json`;
- `build/ppu-pooling/min-raw-profile-verilator-20261107T030726Z/report.json`;
- `build/ppu-pooling/min-raw-dma-iverilog-20261107T031723Z/report.json`;
- `build/ppu-pooling/min-raw-dma-verilator-20261107T031723Z/report.json`.

These simulator results do not qualify synthesis, placement/routing, timing/DRC,
the K8 FPGA or RK3588 silicon. There is no PPU-enabled bitstream or FPGA
execution result.
