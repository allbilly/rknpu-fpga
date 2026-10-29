# Serial halfword memory crossing

`rtl/ddr/rk_async_mem_port.sv` supplies a separately tested source-preparation
leaf for retaining the qualified 50 MHz accelerator while the MIG UI runs at
133 1/3 MHz. It is not connected to the physical image or the joined DDR model.
The separate [raw descriptor/result crossing](DDR_ASYNC_JOB.md) prepares the
opposite control direction without moving the accelerator onto the UI clock.

The crossing transports one outstanding request: write flag, full 32-bit byte
address and 16-bit data, with a 16-bit response and explicit error bit. It
performs no arithmetic, layout transformation, address truncation or window
translation. Address/alignment admission remains the destination adapter's
responsibility. Ordinary memory errors pass through without becoming success.

Request and response payloads remain held while their toggle witnesses pass
through at least three synchronizer stages. The destination holds requests
stable through backpressure; the source holds responses until consumption.
Source admission can be revoked without withdrawing an offered destination
request or an existing response. A stopped clock delays progress and retains
ownership; it cannot fabricate a completion.

An unsolicited or early destination response latches a protocol fault. The
fault crosses back to the source and blocks new admission. An accepted source
request that has not yet been offered downstream can fail explicitly. Already
offered requests remain stable and drain through the destination handshake.
A later fault does not change an already held response payload; the containing
job/health controller must observe the separate sticky fault when qualifying
completion. The leaf does not establish system-wide first-cause ordering.

Both reset inputs must belong to one audited whole-transaction epoch that
also covers downstream ownership. Unilateral reset/recovery is unsupported.
A joint epoch can invalidate old requests/responses and partial writes; there
is no rollback promise. New admission waits for the platform's actual reset
and readiness barrier.

The [Icarus](../build/async-mem-port-native/iverilog-v3/report.json) and
[Verilator](../build/async-mem-port-native/verilator-v3/report.json) suites each
pass eight cases: three modes at synchronizer depths three and five, plus
specific time-zero rejections of depths zero and two. Modes cover 256 bit-exact
requests/responses with stalls, stopped source/destination clocks, whole-epoch
reset and explicit protocol faults while idle, before forwarding, while a
request is stalled and while a response is held. Seed is `0x3588cdc1`; nominal
test clocks are 20 ns and 7.5 ns. Strict compiler warnings are fatal.

```sh
python3 tools/ddr/run_async_mem.py --simulator iverilog --out build/new-async-icarus
python3 tools/ddr/run_async_mem.py --simulator verilator --out build/new-async-verilator
```

Simulation establishes the bounded protocol behavior only. Physical held-bus
max-delay/skew constraints, synchronizer mapping/CDC, reset routing, integration
with packet ownership, job begin/seal/retire/release and health/fault visibility
remain required. The leaf supplies no global drain acknowledgment, complete
DDR shell, FPGA timing or metastability qualification.

## Mapped constraint preparation

Vivado 2026.1 [standalone synthesis](../build/async-mem-port-mapping/v1/report.json)
maps 150 FDCE registers and 26 LUTs, with no RAM or DSP. Nine registers form
the three marked request, response and fault synchronizers. The unwaived
CDC report contains three CDC-3 informational findings and 66 CDC-15 warnings
for the clock-enable-controlled held payloads. Two OOC clock-source warnings
remain part of that initial mapping receipt; no board clock routing is proved.

`fpga/ddr/async_mem_cdc.tcl` now constrains the default three-stage instance.
It requires the actual 20 ns source and 7.5 ns destination clocks, checks every
49-bit request and 17-bit response correspondence, and applies 15 ns / 40 ns
datapath max-delay and bus-skew bounds. Only asynchronous payload hold and
the three first-stage synchronizer D pins are exempted. Later synchronizer
stages remain timed. No clock groups, CDC waivers or severity changes are added.

The [mapped audit](../build/async-mem-port-mapping/constrained-v1/report.json)
passes every bit and stage, with synthesized request slack +14.485 ns,
response slack at least +39.271 ns and skew slack at least +14.744 ns. The
CDC-15 warnings remain visible. These are unplaced estimates and exact
constraint/mapping checks; placement, routing and reset/epoch integration
remain open. Two mock methods cover the allowed exception scope and rejection
of changed clocks, missing payload/synchronizer registers, changed depth and
invalid hierarchy. The initial mock's nested-list lookup defect was corrected
before accepting its negative controls.

The helper takes an explicit instance and existing clock names:

```tcl
source fpga/ddr/async_mem_cdc.tcl
rk_mem_cdc_constrain engine_crossing sys_clk c0_ui_clk
# After mapping/implementation, preserve reports under a fresh directory:
rk_mem_cdc_audit engine_crossing sys_clk c0_ui_clk $review_directory
```

These commands are preparation for a new integration. They are not applied
to the running BRAM image and do not qualify a physical DDR clock crossing.

The separate [standalone OOC route](../build/async-mem-port-mapping/routed-v1/report.json)
also completes all 91 routable nets with zero routing errors. The same audit
passes all 66 internal data paths after routing: request slack is at least
+14.319 ns, response slack +39.326 ns, and bus-skew slack +14.410/+39.489 ns.
The [independent review](../build/async-mem-port-mapping/routed-v1/root-review.json)
rehashes its inputs/artifacts and preserves every native warning.

This OOC result has abstract ports: Vivado reports missing partition-pin
locations, missing clock-source locations and unperformed OOC connectivity
checks; DRC also reports missing configuration-bank metadata. These warnings
are not waived or treated as board evidence. Internal cell-to-cell held-data
bounds are checked, while port timing, actual clock distribution, electrical
configuration, reset coverage and system integration remain unqualified.
No bitstream or hardware action is part of this route run.
