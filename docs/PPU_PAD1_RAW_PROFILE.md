# Captured padded-negative C8 PPU raw-command profile and DMA

Status: **one capture-bounded strict profile and owned-DMA candidate,
simulation-only** for `fp16_max_k2s1_pad1_neg_c8_h2w2`. This is separate from
the C3 tail and valid-padding C8 profiles. It is not general RK3588 PPU support,
full-top qualification, routed-image evidence or FPGA execution.

## Capture and numerical contract

The capture is FP16 maximum pooling, 2x2 kernel, stride 1, one-cell padding,
C8 H2xW2 to H3xW3. The observed pad value is `0xfc00` (`-infinity`); all 32
logical input halfwords are finite negative normal FP16 values. This candidate
does not define MAX semantics for NaNs, signed zero, infinities in the input,
subnormals or any other data domain. The existing isolated leaf
`rtl/ppu/rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2.sv` performs the fixed one-frame
pool operation and requires reset before reuse.

The checked-in fixture is
`tests/ppu_pooling/fixtures/fp16_max_k2s1_pad1_neg_c8_h2w2/`. It binds the device
capture, raw 26-QWORD command, job patch list, input BO, initialized output BO
and captured output BO. The capture receipt records an RK3588 device run of
`pooling.py`; the source and register/emitter hashes are checked by
`tools/ppu/run_pool_pad1_raw_profile.py`. The source capture and command table
remain preserved under `build/rk3588-example-captures/`.

Only job-defined address QWORDs 13 (destination) and 20 (input) are relocated.
The integrated path fetches all 26 QWORDs from memory and leaves every other
bit unchanged. QWORD 2 value `1` is shared with the C3 command; the exact QWORD 5
signature (`0x4001000000026018`) selects padded C8, while the C3 QWORD 5 value
is zero. Valid C8 remains selected by QWORD 2 value `3`. Each profile then
validates its complete stream independently; a near match is rejected, not
silently ignored or rewritten.

## Transfer and output contract

The raw validator publishes 64 input bytes and 144 output bytes. The owned DMA
therefore performs exactly 104 command halfword reads, 32 input halfword reads
and 72 output halfword writes: **208 serialized transactions per job**. It
checks every input lane as finite-negative normal FP16, buffers all nine
16-byte results, and only then begins output writes. A successful job compares
the complete 4096-byte output BO with the device capture; bytes after the first
144 are required to remain equal to the initialized output BO. The same-epoch
repeat test checks 416 total transactions and the complete BO again.

The implementation is in `rtl/ppu/rk_ppu_pool_pad1_raw_profile.sv` and the
shared `rtl/ppu/rk_ppu_pool_raw_dma.sv`. The route uses owned dispatch kind 3;
layout kind 2 and its `RKLY` page remain distinct. No CPU arithmetic, command
rewriting beyond the two explicit address relocations, output repair, or
software-reference fallback is involved.

## Verification

`make ppu-pad1-raw-profile-test` and
`make ppu-pad1-raw-profile-four-state-test` replay the strict command validator
in Verilator and Icarus. Twelve controls cover malformed fields, early/late
task endings, address alignment/range/overlap and unknown address data.
`make ppu-pad1-raw-dma-test` and
`make ppu-pad1-raw-dma-four-state-test` exercise the serialized memory route,
full-BO comparison, same-epoch repeat, dispatch ownership, command mutations,
address overlap and five rejected input classes. The profile manifest and
serialized transaction arithmetic have separate Python contract tests.

On the recorded source revision `8011ff662f6a6877d0eac4e2e4a03ab3aededc0c`,
Icarus Verilog 13.0 and Verilator 5.048 pass the 26-QWORD gate and all 12
negative controls. The integrated route passes both simulators with 208
transactions per job, 416 over two same-epoch jobs, complete 4096-byte BO
comparisons, 13 negative controls and no writes for invalid input/profile cases.
Receipts are:

- `build/ppu-pooling/pad1-raw-profile-iverilog-20261107T025305Z/report.json`;
- `build/ppu-pooling/pad1-raw-profile-verilator-20261107T025305Z/report.json`;
- `build/ppu-pooling/pad1-raw-dma-iverilog-20261107T025306Z/report.json`;
- `build/ppu-pooling/pad1-raw-dma-verilator-20261107T025306Z/report.json`.

Before minimum-pooling admission, the selected 75-source framework-factored top
passed Verilator lint and elaboration with 64 warnings; this did not qualify
synthesis or physical implementation. The present manifests now include 79
sources, and require their own updated lint/elaboration evidence.

These simulator tests do not qualify FPGA RTL, the full top, timing/DRC, the
physical K8 card or RK3588 silicon. The selected framework manifests include
this profile, but there is no fresh synthesis, place/route, bitstream or
hardware-execution result for the PPU-enabled image.
