# Captured C3 PPU raw-command profile gate

Status: **capture-bounded raw-command DMA candidate, simulation-only** for
`fp16_max_k2s2_c3_tail_h2w2`. It composes the strict profile gate, a serialized
16-bit command/input/output DMA, the standalone C3 pooling leaf and the selected
framework's owned UI-dispatch path. The opt-in RKPP control bank is distinct
from RKLY. This is not a requalified K8 image, routed full-top qualification or
FPGA/RK execution.

The shared `rk_ppu_pool_raw_dma` also selects the separate captured C8 profile;
see [the C8 contract](PPU_C8_RAW_PROFILE.md). C8 has a distinct strict gate and
numerical/layout contract and does not widen this C3 profile.

## Admission boundary

`rtl/ppu/rk_ppu_pool_raw_dma.sv` fetches the original 26 raw 64-bit QWORDs
from command memory and supplies them unchanged to
`rtl/ppu/rk_ppu_pool_c3_raw_profile.sv`. The gate checks target,
offset, exact value, order, final-word marker and every non-address bit. Only
the job's two `value32` patches are accepted:

| QWORD | Register | Capture address | Admitted check |
|---:|---|---:|---|
| 13 | `PPU_DST_BASE_ADDR` (`0x6070`) | `0x2000` | Nonzero, 16-byte aligned, 16-byte window does not overflow or overlap input |
| 20 | `PPU_RDMA_SRC_BASE_ADDR` (`0x701c`) | `0x1000` | Nonzero, 16-byte aligned, 64-byte window does not overflow or overlap output |

No other word is relocatable. At runtime, the two base values may vary only
within the listed address constraints; all other command encodings and
register writes remain exact. The parser faults permanently until reset on
the first mismatch. It publishes
the fixed profile only after all 26 QWORDs and the terminal `PC_OPERATION_ENABLE`
QWORD have been accepted. `profile_valid/profile_ready` holds the profile stable
until downstream acceptance. A downstream engine must use that handshake; the
fixed profile wires alone are not an execution interface.

The accepted ordered register stream is exactly:

| QWORD | Target / byte offset | Captured value |
|---:|---|---:|
| 0 | PPU / `0x6004` | `0x0000000e` |
| 1 | RDMA / `0x7004` | `0x0000000e` |
| 2–4 | PPU / `0x600c`, `0x6010`, `0x6014` | `1, 1, 2` |
| 5–7 | PPU / `0x6018`, `0x601c`, `0x6020` | `0, 0, 2` |
| 8 | PPU / `0x6024` | `0x00000011` |
| 9 | PPU / `0x6034` | `0x00110101` |
| 10–12 | PPU / `0x6040`, `0x6044`, `0x6048` | `0, 0, 0` |
| 13 | PPU / `0x6070` | relocated destination `0x00002000` |
| 14 | PPU / `0x607c` | `0x00000010` |
| 15 | PPU / `0x6084` | `0x00000012` |
| 16 | PPU / `0x60dc` | `0x00000003` |
| 17–19 | RDMA / `0x700c`, `0x7010`, `0x7014` | `1, 1, 2` |
| 20 | RDMA / `0x701c` | relocated source `0x00001000` |
| 21–23 | RDMA / `0x7024`, `0x7028`, `0x7030` | `0x20, 0x40, 2` |
| 24 | RDMA / `0x7008` | `1` |
| 25 | PC / `0x0008` | `0x00000060` (terminal trigger) |

The gate's registered-field/transfer contract is:

| Field | Admitted value | Meaning for this capture |
|---|---:|---|
| PPU input cube | W-1=1, H-1=1, C-1=2 | 2x2, three logical FP16 channels |
| RDMA input cube | W-1=1, H-1=1, C-1=2 | Same captured 2x2xC3 shape |
| RDMA format | 2 | FP16 (`PPU_RDMA_DATA_FORMAT.IN_PRECISION`) |
| RDMA line/surface stride | 32 / 64 bytes | Two 16-byte pixel atoms per row / four atoms per 2x2 input plane |
| RDMA transfer window | 64 bytes | 2x2 physical input atoms; BO allocation is separately 4096 bytes |
| PPU operation | max=1, flying=1, `INDEX_EN=0`, `USE_CNT=0` | Fixed source-backed maximum-pooling mode |
| Kernel/stride/padding | 2x2 / 2x2 / zero | Encoded as the captured raw `0x00110101` kernel word and zero padding |
| Output format | raw `0x12` | FP16 precision 2 and captured `INDEX_ADD=1` field |
| Output stride/write window | 16 / 16 bytes | One eight-lane physical atom; three values plus five captured `-99` tail lanes |
| Output burst length | 3 | `PPU_MISC_CTRL.BURST_LEN` from the captured raw word |

The addresses are 32-bit byte addresses and windows are half-open: input
`[src,src+64)`, output `[dst,dst+16)`. This profile deliberately requires
16-byte alignment for both addresses; the captured output register also marks
its low four bits reserved. The parser rejects overlap and arithmetic past
`0x1_0000_0000`. The DMA checks each command/input/output access against its
configured aperture, but has no per-BO length descriptor. Simulation compares
all 4096 output BO bytes; a real memory integration must still establish
allocation mapping and visibility for both full BOs. The software reference is
never an execution path.

## Serialized DMA and owned dispatch

After start admission, the engine requires exactly 26 QWORDs and an 8-byte
aligned command address, fetches all 208 command bytes as 104 serialized
halfword reads, and only then presents the unchanged QWORDs to the strict gate.
After profile acceptance it reads 32 halfwords (64 bytes), forms four captured
16-byte input atoms, runs the C3 leaf, and issues eight acknowledged output
halfword writes (16 bytes). There is one outstanding memory transaction and no
second memory master. The output tail bytes are not rewritten by the engine.

The DMA rejects command/input/output window overlap, aperture escape, invalid
descriptor count/alignment, unexpected memory responses, memory errors and
memory timeout before successful completion. Simulation checks that output
bytes not directly written remain exactly as initialized. The valid case
accounts for 104 command reads + 32 input reads + 8 output writes = 144
serialized transactions.

Both `rtl/ddr/framework_factored/rk_layout_compute_dispatch_ppu.sv` (the
K8-selected source variant) and `rtl/ddr/framework/rk_layout_compute_dispatch_ppu.sv`
admit PPU as
kind 3, separately from layout kind 2. PPU and layout share the auxiliary owned
slot and memory request path. Successful status retires through the parent job
control/ACK owner; fault ownership remains held. The optional `RKPP` AXI-Lite
bank uses page `0x300` and identity `0x524b5050`; existing `RKLY` stays at
`0x400`. `ENABLE_PPU` defaults to 0, and is enabled only in the selected
framework endpoint instantiations. Other endpoint variants remain unchanged.

## Simulation evidence

The captured C3 path passed Icarus Verilog 13.0 and Verilator 5.048. Each run
compiles the real factored owned-dispatch module and shared C3/C8/padded-C8 engine; only the
independent EW/CMAC dispatch child is stubbed in this focused test. The valid
run fetches the complete command, compares the full 4096-byte output BO, and
checks exactly 144 serialized transactions. A second same-epoch job also passes
after ACK, proving the single-frame profile validator and pooling leaf are both
reset/re-armed for each accepted command; that run checks 288 cumulative
transactions and the complete BO. Four negative controls cover a returned
memory error (code 5), invalid QWORD count (code 1), out-of-aperture start
(code 3), and mutated raw register value (code 2); none writes output memory.
Reports:

- `build/ppu-pooling/c3-raw-dma-iverilog-20261107T020630Z/report.json`;
- `build/ppu-pooling/c3-raw-dma-verilator-20261107T020630Z/report.json`.

The separate RKPP control test passes on Icarus 13.0 and Verilator 5.048. It
checks identity, readiness-gated SUBMIT, kind-3 ownership, successful result
readback/ACK and held fault ownership. Reports:

- `build/ppu-pooling/c3-job-control-iverilog-20261107T004810Z/report.json`;
- `build/ppu-pooling/c3-job-control-verilator-20261107T004810Z/report.json`.

## Evidence and provenance

The pinned C3 fixture is
`tests/ppu_pooling/fixtures/fp16_max_k2s2_c3_tail_h2w2/manifest.json`. It binds
the original stream hash
`9dc604e7342f0759b63222d24bbf4721cc50a6b6ec4becad1ffdb0c92205a55c`, patched
capture stream hash
`2aea54d33e144aaf796b6523f66a40f7567c9997d4b69edc73f989587f5c8178`, both
4096-byte BOs, and the device output hash
`e418e3dc9a8d3e678e369b58d817b8aadd073cd46dca3a7d251c90031a54af14`.
`tools/ppu/run_pool_c3_raw_profile.py` independently pins all fixture file
hashes and the current source hashes for:

- `/home/fedora/rk3588/examples/expt/pooling.py`:
  `2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e`;
- `/home/fedora/rk3588/experimental/rockchip.py`:
  `6b5630f962e2f38dc96936ad8c39bb374124584bd68a136f34db8c92af421e4d`;
- `/home/fedora/rk3588/experimental/pool.py`:
  `dfe39e86686d1133e5731ecbc7056ae7d10163bc9af9db52aacf92f1f9482d70`.

The independent register source defines `PPU_DST_BASE_ADDR` low reserved bits,
byte strides, `PPU_DATA_FORMAT` precision/index fields, `PPU_MISC_CTRL.BURST_LEN`
and RDMA precision at the corresponding PPU/RDMA offsets. The example encoder
emits the 2x2 C3 shape and formats the raw QWORD stream. The profile is not a
general decoder inferred from unrelated register writes.

Run the profile, DMA and RKPP control tests:

```sh
make ppu-c3-raw-profile-contract-test
make ppu-c3-raw-profile-four-state-test # Icarus Verilog
make ppu-c3-raw-profile-test            # Verilator
make ppu-c3-raw-dma-contract-test
make ppu-c3-raw-dma-four-state-test     # Icarus Verilog
make ppu-c3-raw-dma-test                # Verilator
make ppu-c8-raw-profile-contract-test
make ppu-c8-raw-profile-four-state-test # Icarus Verilog
make ppu-c8-raw-profile-test            # Verilator
make ppu-c8-raw-dma-contract-test
make ppu-c8-raw-dma-four-state-test     # Icarus Verilog
make ppu-c8-raw-dma-test                # Verilator
make ppu-c3-job-control-contract-test
make ppu-c3-job-control-four-state-test # Icarus Verilog
make ppu-c3-job-control-test            # Verilator
verilator --lint-only -Wall --top-module rk_ppu_pool_c3_raw_profile \
  rtl/ppu/rk_ppu_pool_c3_raw_profile.sv
```

The testbench replays all 26 patched original QWORDs and checks profile
backpressure. Ten negative controls alter a non-address register value,
alignment, target, early/late terminal marker, source/destination overlap,
32-bit DMA-window overflow, operation mode, stride, or the source address's
four-state knownness. Each must fault and must not publish a profile. The
unknown-value case is a four-state check in Icarus; Verilator is two-state and
reduces that injection to the separately-invalid zero address. The runner also
fails on fatal/assertion output even if a simulator exits with status zero. The
contract test verifies that only QWORDs 13 and 20 change during relocation.

Passing these checks establishes only the stated C3 simulation contract. The
framework manifests bind 75 selected sources, but the complete source set has
not been requalified for synthesis or implementation. The separate routed K8
snapshot/worktree is still the prior PPU-free image: it has not been updated,
rerouted or hardware-tested with this candidate.
