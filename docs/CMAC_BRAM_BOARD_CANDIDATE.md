# Staged autonomous CMAC BRAM board demo

`build/ypcb_cmac_top.sv` is a separate, staged YPCB-facing top. The production
`fpga/ypcb_top.sv` and its constraints are unchanged. No physical build result,
bitstream, programming or board execution is claimed here.

The controller initializes 4,096 halfwords, submits the unchanged captured
K=65 terminal command buffer through `rk_cmac_nvdla_dma`, waits for the final
output acknowledgment and transport drain, then compares every RAM halfword
with a synchronous expected-value ROM. This checks inputs, weights, commands,
output holes and guards as well as numerical output. No CPU arithmetic or
runtime packing is used in the execution path. The synthetic operands and
donor-policy outputs are inherited from the existing numerical fixture;
`build/gen_cmac_bram_demo.py` packages them without recomputing arithmetic.

The case has two encoded rows, 96 physical input channels and 32 output
channels: 196 command halfword reads, 12,288 operand halfword reads, 128
numerical groups and 64 output writes/acknowledgments. These are the captured
physical dimensions, not a newly invented tensor-operation interface.

## Memory and lifecycle

The 8 KiB dual-port RAM provides four fixed trace apertures, not an allocator,
RK CBUF or runtime gather engine. Device addresses remain unchanged:

| Device base | Aperture bytes including guards | Flat RAM byte offset |
|---|---:|---:|
| `10010000` | 448 | 0 |
| `10020000` | 6,208 | 448 |
| `10040000` | 320 | 6,656 |
| `100e0000` | 448 | 6,976 |

Odd and unmapped core addresses return explicit errors. One transaction per
port is outstanding; a held response prevents another request. The host
initialization/readback port and core port have disjoint ownership phases.
RAM contents/data registers are not reset, permitting block-RAM inference;
response ownership resets asynchronously. A completed write survives reset.

Pass and failure latch until external reset. Core errors retain E1..E8;
readback mismatch is `fd`, watchdog expiration is `fe`, and an invalid
controller state is `fc`. Failure jointly resets DMA and local memory
response ownership, quiescing transactions without rolling back RAM writes.
The watchdog allows 1,048,576 active controller cycles.

The wrapper has the production board's clock/reset/three-LED port names and
intended 50 MHz input. Reset asserts asynchronously and releases through
three clocked stages. LED0=pass, LED1=fail, LED2=heartbeat; polarity remains
configurable and electrically unverified. There are no DDR, PCIe, flash or
fan-control outputs.

## Verification and retained failures

`build/run_cmac_bram_demo.py` runs the actual staged board wrapper, raw DMA,
donor arithmetic and synchronous RAM/ROM. Eight Verilator modes cover normal
completion, command response error, readback corruption, resets during fetch,
MAC and readback, repeat-after-reset, and watchdog abort. Icarus adds unknown
readback rejection. Every successful run must initialize and check all 4,096
halfwords and match every physical read and numerical write address/data.
The reset task checks assertion off the clock edge and exactly three rising
edges before release. Verilator 5.048 passes all eight entries under
`verilator_v4/`: six successful jobs across five success/reset modes and
three expected-failure modes. Each completed run takes 62,109 cycles including
initialization and complete readback with this local RAM, not the stalled
bus used by other suites. This is functional simulation, not measured FPGA
timing. The full nine-entry board Icarus run is now started under `iverilog_v4/`;
no complete four-state board pass is claimed yet.

Initial `verilator/` and `verilator_v2/` attempts stopped at reset lint;
`verilator_v3/` stopped at verification-scoreboard blocking-assignment lint.
Their reports and changed-source snapshots are retained. The current runner
accepts exactly one reviewed `SYNCASYNCNET` location at the synchronized
reset declaration: that signal drives asynchronous ownership reset and
clocked BRAM transaction enables. Resetting the RAM data ports to silence
this warning would change the memory architecture. The warning is recorded,
not globally disabled; every other local DUT warning remains a failure.
Blocking-assignment lint is disabled only inside the imperative testbench.
No arithmetic expectation, fault assertion, electrical or timing check was
relaxed.

`build/check_cmac_demo_memory.py` independently tests all 3,712 mapped
halfwords, all 4,096 flat host locations, odd addresses, aperture boundaries,
held responses and reset after an accepted write. The first Icarus run
passed; Verilator stopped at the bench clock's declaration initializer.
The corrected bench initializes the clock in an explicit initial process;
the first report/sources are retained under `memory_checks/`, and the fresh
two-simulator result is under `memory_checks_v2/`. That corrected run passes
in Icarus 13.0 and Verilator 5.048: 11,144 core transactions, 3,720 explicit
rejections and all 4,096 host readbacks, including retention of a write whose
response was canceled by reset. The memory DUT was unchanged by the bench fix.

The [Verilator board-wrapper archive](../verification/runs/2026-09-21-cmac-bram-native/index.json)
preserves the eight passed board modes, donor sources/licenses, exact ROM and
fixture inputs, and all three preceding lint failures with source snapshots.
The separate memory-leaf report and ongoing board Icarus/mapping runs are not
included in that archive's pass claim.

`build/run_cmac_bram_mapping.py` requires a passed source-matched board
Verilator report before mapping. It checks BRAM/arithmetic/pad presence and
nonconstant status but does not establish functional netlist correctness,
placement, timing or hardware success. The source-matched mapping run is now
started under `yosys/`; no mapping result is claimed until it terminates.

All of these are staged `build/` sources outside the current production
`make test` manifest. Promotion, licensed donor packaging, mapped functional
verification and exact-part physical checks remain necessary. This narrow
board demo does not replace the full NPU, hardware movement, DDR/PCIe and
tinygrad-runtime work.
