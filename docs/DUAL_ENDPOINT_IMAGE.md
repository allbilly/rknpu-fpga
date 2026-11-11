# Dual-endpoint host-drivable image

Status: **RTL and simulation complete; nothing programmed, no board run.**
This is the first image in the repository where a host — not a ROM — loads the
fixtures and submits the jobs. It is still not a qualification result.

## What the image contains

`fpga/ypcb_dual_endpoint_top.sv` puts three address regions behind one
AXI4-Lite slave port:

| Region | Range | Identity | Contents |
|---|---|---|---|
| Memory window | `0x0000_0000`–`0x0000_7fff` | — | 32 KiB shared BRAM, host-loadable |
| Conv page | `0x0000_8000`–`0x0000_8fff` | `RKCS` `0x524b4353` | `rk_conv_simple_axi` |
| Pool page | `0x0000_9000`–`0x0000_9fff` | `RKPP` `0x524b5050` | `rk_ppu_pool_axi` |
| Unmapped | `0xa000` upward | — | `rk_axil_error_slave`, always SLVERR |

Each page keeps the 12-bit register layout of `rk_job_control`, so one host
driver ABI covers all of them:

| Offset | Register |
|---|---|
| `0x00` | `DEVICE_ID` (RO) |
| `0x04` | `ABI_VERSION` (RO, `0x0001_0000`) |
| `0x08` | `STATUS` (RO) |
| `0x0c` | `COMMAND` (WO, 1 = submit, 2 = acknowledge) |
| `0x10` | `START_ADDRESS` (RW) |
| `0x14` | `START_AMOUNT` (RW) |
| `0x18` | `JOB_TAG` (RW) |
| `0x1c` | `RESULT_TAG` (RO) |
| `0x20` | `RESULT_TASKS` (RO) |
| `0x24` | `RESULT_CODE` (RO) |

`STATUS` bits: `[0]` can_submit, `[1]` active, `[2]` result_valid,
`[3]` result_error, `[4]` memory_ready, `[5]` engine error, `[6]` engine busy,
`[7]` reserved 0, `[10:8]` descriptor fields valid.
Typical values: `0x700` (all fields written), `0x710` (memory ready),
`0x711` (can submit), `0x712` (running).

## Why the front end buffers

AXI-Lite makes `AW` and `W` independent channels; a master may present `W`
before `AW`. Both transport pages only complete a register write when they have
seen *both* halves in the same cycle, so the top collects `AW` and `W` and then
presents them together. It does not rewrite either: the pages see exactly the
address and data the host supplied. A read address is dispatched exactly once
per transaction, and the response target is latched, so a host that changes
`ARADDR` mid-transaction cannot have its response routed to another page.

## Memory arbitration

One BRAM request port, three potential clients (conv engine, pooling engine,
host bridge):

* the host bridge is enabled only while both engines are idle;
* each engine's `memory_ready` is the complement of the other engine's `busy`
  **and** of the host bridge's `busy`, so no submit can start while a host
  memory access is in flight;
* the arbiter latches `owner_q` at the grant and holds it until the response
  handshake, so every response returns to the client that issued the request;
* a host access to the memory window while an engine runs stalls on AXI
  backpressure. `rk_bram` forbids host access to RAM used by the accelerator,
  so stalling is the only correct behaviour: no drop, no redirect, no aliasing.

This is transport arbitration, not an NPU scheduler. There is no queue,
reordering or preemption, and a refused submit is an explicit SLVERR.

## The host load path

`rk_axil_mem_bridge` turns one 32-bit AXI access into two 16-bit memory
transactions, because the engines' serialized memory port is halfword wide.
It rejects, rather than partially applies:

* partial byte strobes (anything other than `4'hf`),
* addresses outside `[BASE, BASE+BYTES)` or not 4-byte aligned,
* protected (`awprot`/`arprot != 0`) accesses.

A memory response error becomes an AXI SLVERR. When `host_enable` is low the
bridge withdraws `awready`/`wready`/`arready`, which is how the host is held off
while an engine owns the memory. Its state machine is one priority ladder in a
single `always_ff`; an earlier `case`-with-`default` form silently cancelled the
transition it was meant to accompany, which is why it is written this way.

## Replay evidence

`tools/dual/run_dual_endpoint.py` drives four modes in both simulators. Modes 1
and 2 load the frozen fixture through the memory window, submit through the
transport page with a real AXI master, wait for the completion line, and read
the **complete 4096-byte output BO** back through the same window.

```
mode 0  page identities, register isolation, unmapped-address SLVERR,
        memory-window round trip, no spurious completion
mode 1  conv-simple job end to end   (conv_simple_fp16_3x3_c4_h8_w8_oc16)
mode 2  pooling job end to end       (int8_max_k2s2_valid_c16_h2w2)
mode 3  sequential conv then pooling, with cross-page exclusion asserted
        while the conv job runs (pooling can_submit withdrawn, host window
        closed, bridge not claiming the port)
```

The runner asserts that the fixture hashes are unchanged before and after, that
the capture's own BO placement matches the image layout (conv `0x1000/0x2000/`
`0x3000`, pooling `0x1000`/`0x2000`), and that the patched command stream hash
is stable. Receipts live under `build/dual-endpoint/<sim>-<stamp>/mode-*/`.

`tests/tb_axil_mem_bridge.sv` is a separate unit bench for the bridge: it covers
round trip, partial strobe rejection, unaligned rejection, out-of-range
rejection, protected access, `W`-before-`AW`, `AW`-before-`W`, and the disabled
stall.

## Build profile

`fpga/dual/sources.json` + `fpga/dual/build_dual.tcl.in` + `tools/dual/vivado_dual.py`
render a standalone Vivado build. The profile declares no generated ROM (this
image loads its data from the host), and the renderer refuses a `generated`
block rather than ignoring it. The Tcl keeps every existing gate:

* `RK_CONFIRM_BOARD=YPCB_00338_1P1` required,
* `RK_LED_ACTIVE_LOW` supplied explicitly when a bitstream is requested,
* `RK_CONFIG_VOLTAGE`/`RK_CFGBVS` required as a matched pair,
* one `sys_clk` at exactly 20.000 ns,
* at least one inferred RAMB18E1/RAMB36E1,
* zero negative max/min slack, recognized `no_clock` and
  `unconstrained_internal_endpoints` reports,
* no blocking DRC severity,
* `RK_EMIT_BITSTREAM` defaults to 0.

The current top (`build/dual-image/20261108T134500Z`, 2026-11-08 13:45)
reached route and wrote `routed.dcp`, `timing.rpt`, `drc.rpt`:
**WNS +0.260 ns, WHS +0.055 ns, 8 RAMB36 tiles, 46,819 LUTs, 19,972
registers, 0 DSPs, 0 failing endpoints**. It stopped before a bitstream on
`NSTD-1`: **152 of 156 logical ports have no `IOSTANDARD`, and 152 have no
`LOC`**. Every one of those is the 32-bit AXI4-Lite slave port.

That is the honest blocker: the AXI slave is a top-level port, and no
board-level pin budget for it has been established. The audited board pins are
only `SYS_CLK` (AA28), the three LEDs and `SYS_RSTN` (R28); the public board
files identify no host-facing AXI header. Inventing pin assignments would be
worse than leaving the image unbuilt, so `RK_EMIT_BITSTREAM` is not enabled for
this profile.

### Pin-free host wrapper (now built)

**The pin-free wrapper produced a real bitstream**: see
`docs/JTAG_DUAL_IMAGE.md` and `build/jtag-dual-image/20261109T001500Z`.
Use that image for any host-driven work. The remainder of this section
describes the wrapper, which is what makes the bare-AXI endpoint usable.

The one board-proven host path in this repository is the USER2 JTAG mailbox
(`fpga/host/ypcb_jtag_ew_top.sv` + `fpga/host/mailbox_cdc.tcl`), which needs no
extra pins. `rtl/host/rk_jtag_axil_bridge.sv` turns the mailbox's frozen frames
into AXI4-Lite transactions:

| Opcode | Mailbox meaning | Adapter behaviour |
|---|---|---|
| 1 | register read | one 32-bit AXI read at `address` |
| 2 | register write | one 32-bit AXI write, data[31:0] |
| 3 | 64-byte read | 16 consecutive 32-bit AXI reads, packed into data[511:0] |
| 4 | 64-byte write | 16 consecutive 32-bit AXI writes of data[511:0] |

Status codes are explicit: `0` success, `4` misaligned, `5` malformed frame,
`7` downstream (SLVERR/DECERR) error, `0x80` timeout. A `7` or `0x80` quarantines
the bridge until a joint reset, exactly like `rk_jtag_backend`; no transaction
is ever silently dropped. The unit bench `tests/host/tb_jtag_axil_bridge.sv`
covers every one of those paths plus AW/W channel reordering.

`fpga/ypcb_jtag_dual_top.sv` wires BSCANE2 (USER2) -> mailbox -> adapter ->
`ypcb_dual_endpoint_top`, so the only package pins are `SYS_CLK` and the three
LEDs. `tests/tb_ypcb_jtag_dual.sv` drives the same three blocks through 640-bit
frames only. Its mode 0 passes (page identities, word and block round trips,
misaligned-block refusal, unmapped-page downstream error and quarantine). The
full job replays (modes 1 and 2, which load every BO through block writes and
compare the whole output BO) are implemented and compile; Icarus needs long
wall-clock time for them because the 640-bit JTAG scan is simulated at the
conservative 166.666 ns TCK model, so their receipts are not yet recorded.

Wrapping was the point: it removes the `NSTD-1`/`UCIO-1` blocker without
changing a single byte of the endpoint path.

## What is not established

* No bitstream for the current top, no programming, no cold boot, no PCIe link,
  no host driver.
* The donor audit still records `cold_boot_verified=false` and
  `physical_pcie_verified=false`.
* WNS/WHS above belong to the superseded 2026-11-08 draft, not to the current
  top with the host bridge, buffered front end, error slave and arbitration.
* Only one conv-simple profile and one pooling profile are wired into this
  image. The other profiles need their parameters selected at elaboration; the
  two pages are parameterised for that but no multi-profile image exists.
