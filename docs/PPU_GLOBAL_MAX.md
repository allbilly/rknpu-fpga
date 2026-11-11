# Source-emitted FP16 C8 global MAX candidate

Status: **strict owned-DMA simulation candidate only** for the donor's
`kernel_stride_16` example. This is not a raw device capture, not general
global-pooling support, and not FPGA qualification.

## Evidence and command boundary

The donor case in `/home/fedora/rk3588/examples/expt/pooling.py` defines FP16
C8 `H16xW16 -> H1xW1`, maximum pooling with a `16x16` kernel and stride. Its
`make_pool_regcmds` emitter supplies the decoded register-to-QWORD encoding;
the donor findings report the 16x16 kernel/stride probe as passing in isolation.
The checked-in fixture
`tests/ppu_pooling/fixtures/fp16_max_k16s16_c8_h16w16/` pins the **emitted**
26-QWORD stream and input/reference BO. It explicitly records
`device_capture: null`: this workspace has no raw command or output capture for
the case. The generated QWORDs must not be described as captured commands.

The strict profile validates every target, offset, fixed value and task-end
marker. Only QWORDs 13 (destination) and 20 (source) are relocatable, matching
the donor job's declared address words. The DMA fetches the words unchanged
apart from those two addresses, validates the profile before reading the 4096
input bytes, and reserves/writes only the 16-byte output atom.

## Numerical and memory contract

The source fixture is exactly `arange(2048, dtype=float16)` in row-major HWC
order. It has one unique maximum per channel, values 2040 through 2047. The
candidate admits only FP16 `+0` and positive normal values through 2047
(`0x67ff`); it rejects negative values including `-0`, subnormals, infinities,
NaNs, and larger positive values. This finite interval and the one source case
do not establish a general RK special-value policy.

The output BO is 4096 bytes. The eight FP16 maxima occupy bytes 0–15; bytes
16–4095 must retain their initialized contents. The Verilator and Icarus DMA
tests compare the complete BO, not just the eight logical values. A successful
job performs 104 command halfword reads, 2048 input halfword reads, and eight
output halfword writes: **2160 serialized transactions**. A same-epoch repeat
checks 4320 total transactions. Input-domain and command/address negative
controls require zero output writes.

## Verification and limits

Run `make ppu-global-raw-dma-test`,
`make ppu-global-raw-dma-four-state-test`, and
`make ppu-global-raw-dma-contract-test`. The tests cover the source-emitted
command stream through owned kind-3 dispatch and shared raw DMA, full-BO
comparison, same-epoch repeat, and rejection of exceptional/out-of-range input,
a mutated fixed register, overlapping BOs, and an unaligned output address.

Reports are under `build/ppu-pooling/global-raw-dma-{verilator,iverilog}-*/`.
They record simulator versions, source revision, source hashes, the deterministic
serialized response schedule, `hardware_accessed=false`,
`vivado_executed=false`, and `bitstream_emitted=false`. Simulation does not
validate the actual PPU silicon or FPGA. The PPU-enabled top has no routed
qualification, and the documented K8 image remains PPU-free. A device capture
with command words, BO allocations/initialization and complete output is still
needed before calling this a capture-bounded replay.
