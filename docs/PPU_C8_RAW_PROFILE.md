# Captured C8 PPU raw-command profile and DMA

Status: **capture-bounded strict-profile and owned-DMA candidate, simulation-only**
for `fp16_max_k2s1_valid_c8_h4w4`. This is a distinct profile from the C3
stride-2/channel-tail case in [PPU_C3_RAW_PROFILE.md](PPU_C3_RAW_PROFILE.md).
It does not imply general RK3588 PPU, full-top, routed-image or FPGA execution
support.

## Capture and numerical contract

The pinned capture is FP16 maximum pooling, kernel 2x2, stride 1, valid padding,
C8 H4xW4 to H3xW3. The PPU source is
`/home/fedora/rk3588/examples/expt/pooling.py` lines 271–373 and 796–818,
SHA-256 `2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e`.
The register definitions are pinned from `experimental/rockchip.py`
(`6b5630f962e2f38dc96936ad8c39bb374124584bd68a136f34db8c92af421e4d`), and
the raw emitter from `experimental/pool.py`
(`dfe39e86686d1133e5731ecbc7056ae7d10163bc9af9db52aacf92f1f9482d70`). The
device capture manifest SHA-256 is
`8e6f0fda3787bcc568b0759d50d14506d19ee4fda12c636227371d172fc441f0`.

The checked-in fixture
`tests/ppu_pooling/fixtures/fp16_max_k2s1_valid_c8_h4w4/manifest.json` binds the
208-byte, 26-QWORD command
(`75f7c70eb3eafc8345a634633f9c45df231dad1195f79ad1f9a2ea7038a4cebf`) and its
device-relocated form
(`32a8fe3772f79dd74bc1ed6952055d5b2720ccdfbb4bdd11c516ada15142f649`). Only
QWORDs **13** (`PPU_DST_BASE_ADDR`) and **20**
(`PPU_RDMA_SRC_BASE_ADDR`) relocate; both retain the captured 16-byte
alignment/address checks. Compared with the C3 stream, this profile differs at
QWORDs **2–7, 9, 14–15, 17–19, 21–22**. It is not admitted by broadening the C3
validator: the raw engine first selects the exact QWORD-2 shape signature, then
passes the unchanged stream to the corresponding independent strict gate.

The logical input is 128 FP16 lanes: 127 finite normal values and one `+0`
(range -4 to 11.875). The DMA accepts finite normal values and `+0`, and rejects
NaN, either infinity, subnormal values and `-0`. It validates all 256 input
bytes before the first device output write. The numerical result is the exact
lane-wise maximum of each 2x2 window; no conversion, rounding, CPU arithmetic or
layout repair is used. Signed-zero/NaN behavior outside this admitted input
domain remains candidate behavior, not a hardware-established RK policy.

The input has 16-byte atoms, 64-byte line stride and 256-byte surface/transfer
window. The output has nine atoms, 48-byte line stride and 144-byte
surface/transfer window. Each BO is 4096 bytes. The pinned device output is
`39d178de3e4a7dd020c66d23437b18082ec2c00541efbc979b773f8bee45ce60`; bytes
144–4095 equal the initialized output BO. The test compares all 4096 bytes.

## Integrated serialized path

`rtl/ppu/rk_ppu_pool_raw_dma.sv` keeps the original QWORD bytes, chooses only the
captured C3, valid-C8 or padded-C8 signature, and uses separate strict profile
gates. The valid-C8 route
performs 104 command halfword reads, 128 input halfword reads and 72 output
halfword writes: **304 single-outstanding serialized transactions**. Since the
streaming pooling leaf can hold one output atom while accepting the next inputs,
the DMA buffers the nine leaf-produced atoms internally. It validates the
entire input stream and collects all nine outputs before issuing the 144 output
bytes; this is bounded on-chip buffering, not a CPU fallback or output BO
repair. C3 retains its original 144-transaction contract.

PPU still uses owned-dispatch kind 3, distinct from layout kind 2. The opt-in
RKPP control bank remains page `0x300`; RKLY remains page `0x400`.

## Simulation evidence

The C8 profile gate passes Icarus Verilog 13.0 and Verilator 5.048, checking all
26 captured QWORDs, stable profile backpressure and ten strict negative
controls:

- `build/ppu-pooling/c8-raw-profile-iverilog-20261107T015043Z/report.json`;
- `build/ppu-pooling/c8-raw-profile-verilator-20261107T015043Z/report.json`.

The integrated C8 path passes both simulators, including one valid job and a
second same-epoch job. Each job compares the complete 4096-byte output BO; the
repeat checks 608 cumulative transactions. Seven negative controls cover
returned memory error, descriptor count, aperture escape, raw register
mutation, infinity, subnormal and negative zero. Infinity rejects at the first
input halfword; subnormal and negative zero reject at halfwords 100 and 127,
after pooling has already produced buffered outputs. All three issue no output
writes.

- `build/ppu-pooling/c8-raw-dma-iverilog-20261107T021027Z/report.json`;
- `build/ppu-pooling/c8-raw-dma-verilator-20261107T021040Z/report.json`.

The reports bind source revision, fixture/source hashes, simulator versions and
test outcomes. Neither simulator accessed hardware or ran Vivado. The C8 tests
are wired into `make test` as `ppu-c8-raw-profile-*` and `ppu-c8-raw-dma-*`.

The selected framework manifests now bind 83 ordered sources, including the
separate padded-negative C8, minimum-pooling, average-pooling and MAX-with-index
profiles and leaves. The PPU-enabled selection has not
received synthesis, placement/routing, timing/DRC qualification or FPGA
execution. The currently documented K8 image remains PPU-free.
