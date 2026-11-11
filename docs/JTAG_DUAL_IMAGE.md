# Pin-free host-drivable image (`ypcb_jtag_dual_top`)

Status: **RTL complete, both simulators pass, and a real bitstream exists.**
Nothing programmed; no board run; this is not a qualification result.

## Why this image exists

`ypcb_dual_endpoint_top` is host-drivable but cannot become a bitstream: its
32-bit AXI4-Lite slave is a top-level port, and 152 of 156 logical ports had
no `IOSTANDARD` and no `LOC` (`NSTD-1` + `UCIO-1`). Inventing pin locations for
a 32-bit AXI header that the public board files never mention would be worse
than leaving it unbuilt.

This image removes that port instead. The board's only documented pins are
`SYS_CLK` (AA28) and the three LEDs (P30/M30/N30), and the host path is the
board-proven OpenTPU USER2 JTAG mailbox, which is a configuration interface, not
package I/O.

```
BSCANE2 (USER2)
      |  640-bit frames
      v
otpu_jtag_mailbox  ->  rk_jtag_axil_bridge  ->  AXI4-Lite
                                                    |
                                        ypcb_dual_endpoint_top
                                        (conv page, pooling page, BRAM window)
```

## Frame mapping

| Opcode | Mailbox meaning | AXI behaviour |
|---|---|---|
| 1 | register read | one 32-bit read |
| 2 | register write | one 32-bit write, data[31:0] |
| 3 | 64-byte read | 16 consecutive 32-bit reads, packed into data[511:0] |
| 4 | 64-byte write | 16 consecutive 32-bit writes of data[511:0] |

Status codes: `0` success, `4` misaligned, `5` malformed frame, `7` downstream
error, `0x80` timeout. `7` and `0x80` quarantine until a joint reset, matching
`rk_jtag_backend`; nothing is silently retried or dropped.

The adapter is a pure transport: it changes no address, no byte and no
arithmetic. The words a host writes are the words the engines read.

## Evidence

| Check | Result | Receipt |
|---|---|---|
| `rk_jtag_axil_bridge` unit bench | PASS, 9 sequences, all status paths | `make jtag-axil-bridge-test` |
| Dual-top AXI replay, Icarus | 4/4 modes PASS | `build/dual-endpoint/iverilog-20261108T152510Z` |
| Mailbox replay, Verilator | 5/5 modes PASS | `build/jtag-dual/verilator-20261109T013805Z` (modes 0-4, real tool version and source hashes) |
| Dual-top AXI replay, Verilator | 4/4 modes PASS | `build/dual-endpoint/verilator-20261108T154302Z` |
| Mailbox replay, Icarus | not recorded | Verilator is the mailbox evidence; Icarus would need very long wall-clock per 640-edge frame scan |
| Page-presence gate | PASS | `build_jtag_dual.tcl.in` asserts each of the four page instances exists before implementation |
| Vivado synthesis/implementation | **PASS, bitstream emitted** | `build/jtag-dual-image/20261109T073000Z` |

The Verilator job replays are the important ones: mode 1 loads the frozen
`conv_simple_fp16_3x3_c4_h8_w8_oc16` command and operand BOs entirely through
64-byte frame writes, submits through the transport page, waits for the
completion line, and compares the **complete 4096-byte output BO** (191
frames). Mode 2 does the same for `int8_max_k2s2_valid_c16_h2w2` (208 frames).
The 4096-byte compare includes the bytes the engines must leave untouched, so a
write outside the captured window fails the test.

## Build profile

`fpga/jtag_dual/sources.json`, `fpga/jtag_dual.xdc`,
`fpga/jtag_dual/build_jtag_dual.tcl.in`, `tools/dual/vivado_jtag_dual.py`.

The XDC assigns only `AA28` and the three LED pins, asserts `LVCMOS18`, and
creates the single 20.000 ns `sys_clk`. It deliberately contains no `LOC` for
any AXI or JTAG signal, and a contract test fails if one appears. The rendered
Tcl applies the reviewed `fpga/host/mailbox_cdc.tcl` constraints and audits
(`rk_host_cdc_constrain`, `rk_host_cdc_audit`), asserts exactly one `BSCANE2`
with `JTAG_CHAIN=2`, and keeps every existing gate: board confirmation, explicit
LED polarity, matched `CONFIG_VOLTAGE`/`CFGBVS`, one 20 ns clock, inferred BRAM,
zero negative max/min slack, zero `no_clock` and unconstrained-internal-endpoint
findings, and no blocking DRC severity.

## Bitstream

`build/jtag-dual-image/20261109T001500Z/implementation/rk_jtag_dual.bit`
— 18,735,215 bytes, SHA-256
`73dd0365055b4664c2d8d05af634d05a754cc333808fd2ed1c5d974706c94cf7`.

| Gate | Value |
|---|---|
| WNS | **+0.044 ns** |
| WHS | **+0.058 ns** |
| Failing endpoints | 0 (54,369 total) |
| Routing | 155,156 / 155,156 nets fully routed, 0 errors |
| BRAM | 8 × RAMB36 |
| LUTs / registers / DSPs | 96,749 / 41,140 / 0 |
| Pulse width | all MET (min period 166.666, low/high 83.333/83.333 on the TCK domain) |
| Mailbox payload bounds | held→req 40.000 ns MET (39.283), response 333.332 ns MET |
| `no_clock` / unconstrained internal | 0 / 0 |
| DRC | `CHECK-3` (rule-limit notice) + `REQP-1839` ×20 (RAMB36 async control, same class the conv image carries) — warnings only, no blocking severity |
| Configuration bank | `CONFIG_VOLTAGE 1.8` / `CFGBVS GND`, supplied explicitly |

The mailbox CDC audit ran on the routed design and wrote
`mailbox_cdc.tsv`, `mailbox_cdc.rpt`, `mailbox_bus_skew.rpt`,
`mailbox_held_timing.rpt` and `mailbox_response_timing.rpt`. Every
synchronizer stage carries `ASYNC_REG` and `DONT_TOUCH`, and only the
first-stage `D` pin is exempted from setup.

This is a **third** bitstream, and the first one whose host port is physically
realisable: no invented pins, no waived DRC, no cut clock. It is still a
bring-up image with two selected profiles, not the example framework.

## What is not established

* No programming, no cold boot, no host driver run on the card.
* The JTAG mailbox path has never been exercised on the physical card.
* Only one conv-simple profile and one pooling profile are wired in.
* The donor audit still says `cold_boot_verified=false` and
  `physical_pcie_verified=false`. A JTAG mailbox is not PCIe and does not
  change that record.
