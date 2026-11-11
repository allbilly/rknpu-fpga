# First conv board image

Status: **real bitstream emitted; no board run, no cold boot, not a
qualification image.** This records what was built and what it does not prove.

## What is in the image

`fpga/ypcb_conv_simple_top.sv` is the first top-level design in this repository
that carries convolution RTL to a bitstream:

| Block | Source | Role |
|---|---|---|
| startup reset | `rtl/rk_startup_reset.sv` | 64 held edges, config restart |
| conv self-test | `rtl/cmac/rk_conv_simple_self_test.sv` | loads BOs, replays stream, checks result |
| captured data | `rtl/cmac/rk_conv_simple_demo_rom.sv` | generated from the frozen fixture |
| raw endpoint | `rtl/cmac/rk_conv_simple_dma.sv` | 52-QWORD fetch, aperture/overlap checks |
| strict profile | `rtl/cmac/rk_conv_simple_profile.sv` | exact per-capture register table |
| spatial front | `rtl/cmac/rk_conv_3x3_valid_c4_front.sv` | KH/KW, channel blocks, chunked weights |
| arithmetic | `rk_cmac_cacc_fp16_array` + donor NVDLA | unmodified CMAC/CACC |
| output | `rtl/cmac/rk_conv_output_atom.sv` | FP16 atom writer |
| memory | `rtl/rk_bram.sv` | 32 KiB single aperture |

External I/O is the audited 50 MHz clock and three LEDs. There is no PCIe, MIG
or host driver, so this is a self-test bring-up, not the conv framework.

## Evidence

Simulation, both simulators, complete output BO:

```
PASS conv board image logic iverilog  PASS conv board image logic verilator
```

with two negative controls per simulator (mutated expected byte, mutated input
pixel) each terminating with `board conv self-test FAILED code=51`.

The 52-QWORD descriptor endpoint added in this increment replays all eight
modes in Icarus, each with its own receipt:

| Mode | Scenario | Result |
|---|---|---|
| 0 | captured job | PASS, complete 1152-byte BO, 208 command reads, 576 writes |
| 1 | `start_amount` 51 | code 1, zero traffic |
| 2 | unaligned command base | code 3, zero traffic |
| 3 | command block at aperture end | code 3, zero traffic |
| 4 | input base aliases command block | code 3, no output write |
| 5 | memory error on first command read | code 5, one read |
| 6 | memory never ready | code 8, zero traffic |
| 7 | two sequential jobs | PASS, 416 command reads, 1152 writes |

## Bitstream

| Field | Value |
|---|---|
| Path | `build/conv-image/20261108T171500Z/implementation/rk_conv_simple.bit` |
| Bytes | 18,735,217 |
| SHA-256 | `cddb583b961636868432a9d0e8af5ea4d015fc0d80f4046e8d6836bb4b848b08` |
| Header design | `ypcb_conv_simple_top` |
| Header part | `7k480tffg1156` |
| Vivado | 2026.1 |
| WNS / WHS | **+0.412 ns / +0.076 ns**, 0 failing endpoints |
| BRAM | 8 × RAMB36E1 |
| LUTs | 46,026 (15.4 %) |
| DSPs | 0 |
| `no_clock` | 0 |
| `unconstrained_internal_endpoints` | 0 |
| DRC | `CHECK-3` (rule-limit notice), `REQP-1839` ×20 (RAMB36 async control), `RTSTAT-10` (2 unroutable nets) |
| CFGBVS-1 | **gone** — `CONFIG_VOLTAGE 1.8` / `CFGBVS GND` were applied |

The electrical pair came from donor evidence, recorded with hashes in
`docs/BOARD_ELECTRICAL_EVIDENCE.md`.

## Open DRC findings, not waived

`REQP-1839`: the BRAM's write port address is driven by `rk_cmac_rw_arbiter`
registers that carry an asynchronous reset. Vivado warns that the RAM address
may glitch while that reset asserts. This is the arbiter's existing async-reset
style, which every conv profile already used; it is not introduced by this
image. Fixing it properly means making the arbiter's reset synchronous (or
qualifying the RAM's write enable), which is a change to shared RTL that should
not ride along with a bring-up image. Tracked as remaining work.

`RTSTAT-10`: two bits of `error_code` have no routable load. They are
upper bits of the self-test's error bus that the LED-only interface never
observes. Cosmetic for this image, but the same bus feeds the AXI endpoint
later, so it will resolve when conv is host-driven.

`CHECK-3` is a report-limit notice, not a design failure.

## Not established

* **No board run.** Nothing was programmed; the card was never touched.
* **No cold boot.** Configuration from flash was not exercised.
* **No physical PCIe.** This image has no PCIe at all.
* **Timing margin is thin on the full design:** +0.412 ns setup at 50 MHz
  reflects a small image. The conv-simple profile is 15.4 % of the LUTs; a
  multi-profile image will not hold that margin automatically.
* **One profile only:** the image contains `conv_simple_fp16_3x3_c4_h8_w8_oc16`.
  The 5×5 and C16 profiles simulate but are not in this bitstream.
