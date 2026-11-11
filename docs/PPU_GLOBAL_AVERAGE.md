# Captured FP16 C8 global-average PPU candidate

Status: **one capture-bounded H3×W5 leaf and separate strict raw-command / owned-DMA
candidate; both simulators pass, simulation only**. This is a distinct fixed profile from the captured
2×2 average case and the source-emitted global-MAX candidate. It does not provide
general global pooling or qualify the PPU-enabled FPGA top.

## Captured case and command boundary

The donor case `fp16_avg_global_k3x5_valid_c8_h3w5` is defined in
`/home/fedora/rk3588/examples/expt/pooling.py` lines 820–835: FP16 average,
C8, H3×W5 to H1×W1, kernel and stride 3×5, no padding, `INDEX_EN=0`, and
`USE_CNT=0`. The pinned RK3588 run completed with `status=OK`,
`submit_ret=0`, Rocket runner 1.0.0, on the documented Orange Pi 5 / RK3588S
target. The fixture and per-file SHA-256 values are in
`tests/ppu_pooling/fixtures/fp16_avg_global_k3x5_valid_c8_h3w5/manifest.json`.

The captured stream has 28 QWORDs. The strict profile checks every target,
offset, fixed register value and task tail. Only QWORDs 15 (output base) and 22
(input base) relocate. The raw stream hash is
`0357cf3b6ad80c02f1bb414383471854ce6be9fb13f650f26f0586a275db3797`; the
captured relocated stream hash is
`8a7d7cf5959520d9a5e73ab95e6576a8a80dd56ab2aa02aa1f15939364be5dc3`.
The shared raw DMA fetches the original QWORDs, validates the complete profile
before touching input, reads 240 input bytes, buffers the single 16-byte result,
then issues eight halfword output writes. It introduces no runtime CPU
arithmetic or BO-layout repair.

## Numerical and BO contract

The source reference converts the 3×5 window to FP32, takes the spatial mean,
then converts to FP16 with `atol=0.0625`. On this capture, all eight logical
FP16 output lanes exactly match both source `expected.bin` and device output
SHA-256 `1df313040ac62a607b10c0a212f431d30057f4242c8d5d57be8788273f06fe0d`.
This exact match is fixture evidence only; it does not establish a general
RK3588 average rounding or special-value policy.

The leaf is fixed to 15 input atoms and one output atom. The owned-DMA admission
domain is `+0` and positive normal FP16 values no greater than the captured
maximum `14.875` (`0x4b70`); negative values, subnormals, infinities, NaNs and
larger values fail before any output write. This is a conservative finite-input
candidate boundary, not a claim about all RK PPU behavior. The input BO is 4096
bytes with 240 logical bytes. The output BO is 4096 bytes: bytes 0–15 are the
eight outputs and bytes 16–4095 must remain identical to `out_init.bin`.

## Verification and limits

`make ppu-avg-global3x5-contract-test` checks capture provenance, source
metadata, relocations, shape and full-BO contract. The standalone leaf targets
replay the fixture in Icarus and Verilator. The strict-profile targets exercise
the 28-QWORD stream and 13 malformed-command/address controls. Owned-DMA targets
exercise serialized command/input/output traffic, same-epoch repeated jobs,
full 4096-byte BO comparison and input/profile/address rejections with no writes
on failure.

Fresh focused runs on 2026-11-07 passed all leaf, profile and owned-DMA tests
on Icarus Verilog 13.0 and Verilator 5.048 (2026-04-26 build), Python 3.14.5.
The DMA run records 240 transactions/job, 480 transactions over two same-epoch
jobs, the complete output BO and seven negative controls. Reports:

- `build/ppu-pooling/global-average-leaf-{iverilog,verilator}-20261107T070547Z/`
- `build/ppu-pooling/global-average-raw-profile-verilator-20261107T070548Z/`
- `build/ppu-pooling/global-average-raw-profile-iverilog-20261107T070551Z/`
- `build/ppu-pooling/global-average-raw-dma-{iverilog,verilator}-20261107T070737Z/`

They bind source revision `8011ff662f6a6877d0eac4e2e4a03ab3aededc0c`, explicit
source/fixture hashes and `hardware_accessed=false`;
`vivado_executed=false` and `bitstream_emitted=false`.

Run the candidate with:

```sh
make ppu-avg-global3x5-test ppu-avg-global3x5-four-state-test
make ppu-global-avg-raw-profile-test ppu-global-avg-raw-profile-four-state-test
make ppu-global-avg-raw-dma-test ppu-global-avg-raw-dma-four-state-test
make ppu-global-avg-raw-dma-contract-test
```

Reports are written under `build/ppu-pooling/global-average-*`. They bind the
source revision, tools and source/fixture hashes; simulator runs are not device
or FPGA execution. The PPU-enabled design still requires applicable synthesis,
timing, DRC, board and raw-BO hardware qualification before any hardware claim.
