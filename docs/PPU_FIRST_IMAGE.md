# First pooling FPGA image

Status: **routed checkpoint with real timing closure; no bitstream, no board
run, no qualification.** This document records what was built, from which
sources, and what it does not establish.

## What the image contains

`fpga/ypcb_ppu_i8_top.sv` is the first top-level design in this repository that
instantiates conv/pool RTL. It is intentionally narrow:

| Block | Source | Role |
|---|---|---|
| startup reset | `rtl/rk_startup_reset.sv` | 64 held edges, configuration restart |
| ROM self-test | `rtl/ppu/rk_ppu_pool_self_test.sv` | loads BO, launches, checks result |
| captured data | `rtl/ppu/rk_ppu_pool_demo_rom.sv` | generated from the frozen fixture |
| descriptor endpoint | `rtl/ppu/rk_ppu_pool_i8_k2s2_dma.sv` | 26-QWORD fetch, strict gate |
| raw profile | `rtl/ppu/rk_ppu_pool_i8_k2s2_profile.sv` | exact captured field check |
| pooling leaf | `rtl/ppu/rk_ppu_pool_int_k2s2.sv` | signed INT8 2×2/stride-2 max |
| memory | `rtl/rk_bram.sv` | 8 KiB single BRAM aperture |

External I/O is the audited 50 MHz clock and three LEDs only. There is no PCIe,
no MIG/DDR controller and no host driver, so this is not the conv/pool
framework and cannot run the general example corpus.

## Generated ROM

`tools/ppu/gen_pool_demo.py` reads
`tests/ppu_pooling/fixtures/int8_max_k2s2_valid_c16_h2w2` and emits
`rtl/ppu/rk_ppu_pool_demo_rom.sv`. It copies:

* the frozen 26-QWORD command stream with only QWORDs 13 and 20 retargeted to
  this image's BRAM windows (`0x10001000` output, `0x10000200` input),
* the 64-byte input operand the endpoint actually reads,
* the eight captured output halfwords `3164 2f62 2d60 2b5e 295c 275a 2558 2356`.

The generator fails if any manifest hash differs, if input bytes outside the
64-byte window are nonzero, or if the captured output tail is nonzero.
`make generated-check` runs it with `--check`.

## Build profile

`fpga/ppu/sources.json` pins:

* top `ypcb_ppu_i8_top`, part `xc7k480tffg1156-2`, 20 ns clock,
* the eight synthesis sources explicitly (no globbing),
* constraints `fpga/ypcb_ppu_i8.xdc` (AA28 clock, P30/M30/N30 LEDs),
* the single generated ROM and its fixture binding,
* sim benches for board, endpoint and leaf.

`tools/ppu/vivado_ppu.py` re-validates that profile, re-runs the ROM generator
check, renders `fpga/ppu/build_ppu.tcl.in`, and refuses an output directory that
already exists. It extracts WNS/WHS, applied DRC rows and RAMB36E1 count from
the reports; a missing report is a failure, not a pass.

## Verification performed

| Check | Result |
|---|---|
| Verilator lint, board testbench | 0 errors, 0 warnings |
| Icarus 13.0 board replay | PASS |
| Verilator 5.048 board replay | PASS |
| Descriptor endpoint, 9 modes, both sims | PASS |
| Synthesis | PASS |
| Placement/routing | PASS |
| Setup WNS / hold WHS | **+14.633 ns / +0.037 ns**, 0 failing endpoints |
| BRAM inference | 2 × RAMB36E1 |
| DRC | one warning: `CFGBVS-1` (no CONFIG_VOLTAGE/CFGBVS supplied) |
| Bitstream | **none emitted** |
| Negative controls | mutated expected byte → code 0x51; mutated input pixel → code 0x51 (both sims) |

Receipt: `build/ppu-image/20261108T015400Z/inputs.json` with
`status: PASS`, `vivado_executed: true`, `bitstream_emitted: false`, a recorded
source-hash list that is still current, and Vivado v2026.1 logs. Two earlier
attempts (one predating the final `METHOD` width edit, one aborted on the board
confirmation guard) were deleted rather than kept as soft evidence.

The 14.633 ns setup slack is against the 20 ns 50 MHz clock and reflects how
small this image is; it is not evidence about the full conv/pool framework or
the previously failing full EW image (WNS −0.328 ns).

The `CFGBVS-1` warning is real and unresolved: the image was implemented without
`CONFIG_VOLTAGE`/`CFGBVS` because the board's configuration-bank supply and strap
are not established in this repository. The gate treats that as acceptable only
for a routed checkpoint; emitting a bitstream with it unresolved is refused.

## What is still required

1. A board-verified `CONFIG_VOLTAGE`/`CFGBVS` pair (and LED polarity) to emit
   `rk_ppu_i8.bit` with `RK_EMIT_BITSTREAM=1`.
2. A separately authorized programming action and an audited board run.
3. The general framework: AXI-Lite endpoint for conv, PCIe/MIG transport,
   remaining pooling leaves, conv-gemm-vendor and conv-simple capture/RTL.

Nothing here claims FPGA execution of any captured task. The simulations prove
the image's logic reaches the captured result from reset release; Vivado proves
it synthesises, places and routes at the constrained clock. Neither proves
silicon behaviour.
