# Captured C8 MAX-with-index raw-command profile and DMA

Status: **one capture-bounded strict profile and owned-DMA candidate,
simulation-only** for `fp16_max_k2s2_index_c8_h2w2`. This adds one source-backed
profile, not general RK3588 PPU support, full-top qualification, routed-image
evidence or FPGA execution.

## Capture and command contract

The pinned case is FP16 maximum pooling with `INDEX_EN=1`, `USE_CNT=0`, C8,
H2xW2 to H1xW1, 2x2 kernel, stride 2 and no padding. The original command is
26 QWORDs (208 bytes). The strict gate admits only QWORD 13 (destination) and
QWORD 20 (input) as job-declared address relocations; all other captured words,
register targets, offsets, values and the final marker are checked. The command
selector includes the captured indexed-mode bit and is distinct from unindexed
C8 MAX.

The checked-in fixture is
`tests/ppu_pooling/fixtures/fp16_max_k2s2_index_c8_h2w2/`. It binds the source
command, relocation list, 4096-byte input/output allocations, initialized
output, successful device capture and complete device output BO. The numeric
admission contract is limited to finite FP16 values and `+0`, with one unique
maximum per channel. The DMA rejects infinities, NaNs, subnormals and `-0`;
the leaf reports an 8-bit per-channel uniqueness mask and a tied maximum is
rejected before any output write. This is capture-bounded behavior, not a
general special-value or tie policy.

## Output layout and serialized traffic

The device output contains eight FP16 values at bytes 0–15, an untouched
16-byte gap at bytes 16–31, and eight encoded positions at bytes 32–47. The
source reference selects the first row-major maximum and encodes local
`(row << 3) | column` positions. The index leaf exports values, indices and
uniqueness as one backpressure-stable result. The DMA buffers the paired result
until all four input atoms and all eight unique maxima have passed validation,
then issues 16 halfword writes: eight value writes and eight index writes at
destination `+32`. The gate reserves the 48-byte output span for range and
overlap checks, but the 16-byte gap is not written. The complete 4096-byte BO
comparison also checks that the gap and tail remain unchanged.

Per job the owned engine fetches 26 QWORDs and issues 104 serialized command
halfword reads, 32 input halfword reads and 16 output halfword writes: **152
single-outstanding transactions**. A same-epoch repeat checks 304 total
transactions and the complete output BO again. No command rewrite beyond the
two declared relocations, runtime CPU arithmetic, layout repair or software
fallback is used.

## Verification and evidence boundary

`make ppu-index-raw-profile-test` and
`make ppu-index-raw-profile-four-state-test` exercise the strict gate in
Verilator and Icarus. Ten profile negative controls cover fixed-value, target,
terminal-marker, address-alignment, address-overlap and address-range failures.
`make ppu-index-raw-dma-test` and
`make ppu-index-raw-dma-four-state-test` run the profile through owned dispatch
kind 3 and the shared raw DMA, compare all 4096 output bytes, check a repeat
job, reject tied maxima and non-finite inputs, and reject a mutated command
field. Each negative DMA run confirms zero output writes.

On source revision `8011ff662f6a6877d0eac4e2e4a03ab3aededc0c`, Icarus Verilog
13.0 and Verilator 5.048 pass the profile and integrated DMA tests. The profile
admits 26 QWORDs with relocations `[13,20]` and rejects ten controls. The DMA
checks 152 transactions/job, 304 for a same-epoch repeat, full 4096-byte BO
equality, gap/tail preservation and three end-to-end negative controls. Receipts:

- `build/ppu-pooling/index-raw-profile-verilator-20261107T050148Z/report.json`;
- `build/ppu-pooling/index-raw-profile-iverilog-20261107T050149Z/report.json`;
- `build/ppu-pooling/index-raw-dma-verilator-20261107T050210Z/report.json`;
- `build/ppu-pooling/index-raw-dma-iverilog-20261107T050211Z/report.json`.

These are simulation results only. The PPU-enabled framework selection has not
received full-top synthesis, placement/routing, timing/DRC qualification or
FPGA execution; the documented K8 image remains PPU-free.
