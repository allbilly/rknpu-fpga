# Two-clock raw EW engine boundary

`rtl/ddr/rk_ew_async_engine.sv` joins the real, unchanged `rk_ew_dma` to the
[descriptor/result crossing](DDR_ASYNC_JOB.md) and
[halfword memory crossing](DDR_ASYNC_MEMORY.md). This separate source profile
keeps command decoding and FP16 EW execution on SYS50 while control and the
memory destination use the intended 133 1/3 MHz UI clock. It is not connected
to MIG, the joined DDR owner, USER2 or the running FPGA image.

The UI interface accepts only the original 32-bit command byte address and
32-bit amount. The DMA fetches the actual final QWORD bytes from memory and
retains its existing register, precision, shape, framing and task checks.
There is no tensor-operation input, command rewriting, arithmetic repair,
layout transformation or CPU fallback. The crossing returns the original
terminal error/code/task count as one held result for each accepted descriptor.

The adapter captures the DMA's one-cycle `done` or sticky `error` exactly once
per owned start. Consuming an error result does not reset the DMA or reopen
admission: `ui_fault` remains sticky until the joint transaction reset. Ordinary
raw errors retain their original codes. The result remains stable while held,
including if a later protocol fault appears separately. The containing UI
owner must qualify successful completion with its current health/fault state.

New admission can be disabled without withdrawing an owned start or memory
request. A DMA timeout cannot cancel a request already offered in the UI
domain; that request and a later response still belong to the old transaction.
A failed DMA can stop consuming its local response. The outer memory owner
must drain/quarantine that transaction or reset the whole epoch before reuse.
There is no timeout retry, unilateral reset, implicit rearm or rollback.

Both clocks receive reset from one audited transaction epoch. The crossing
halves assert reset asynchronously; a dedicated core-domain register holds
the unchanged synchronous DMA reset through its first fresh edge after
release. An assertion while the core clock is stopped must therefore reach
the DMA before a newly delivered descriptor can execute. The containing
platform still owns reset coverage and release for its other clients,
initialization, memory contents and host sessions.

The terminal result is not a DDR retirement receipt, ECC snapshot, readback
fence or host result ACK. Before connecting this composition to the actual
DDR owner, qualify that owner's job begin/seal/retire/release handshakes,
current health, first-cause/error reservation and reset epoch. The full512
CMAC path remains the performance target; this EW clock-boundary component
supplies no replacement full-array implementation or GEMM qualification.

The native testbench uses complete original ADD/SUB/MUL BO captures at logical
lengths 8/9/33. A bounded halfword test memory runs on the UI clock and the real
EW DMA runs on SYS50. Every positive case compares all original BO bytes,
including commands, tasks, scratch, padding and guards, and checks independent
command-fetch/read/write/response counts. Other directed cases exercise
repeated SUB(9), exact E1/E5/E8 propagation, held results, late responses,
offered-request timeout, stopped clocks and joint-reset recovery. The CPU
decoder generates test goldens only and is absent from hardware execution.

```sh
python3 tools/ddr/run_async_ew.py --simulator iverilog --out build/new-ew-async-icarus
python3 tools/ddr/run_async_ew.py --simulator verilator --out build/new-ew-async-verilator
```

The first Icarus snapshot passed all 34 cases. Verilator then rejected three
strict diagnostics: the absolute testbench include, a large bitmap initializer
and mixed synchronous/asynchronous use of the original core reset. Those
receipts remain preserved. The revised source uses a relative frozen include,
elementwise bitmap initialization and the dedicated DMA reset register above.
The final [Icarus](../build/async-ew-boundary-native/iverilog-v3/report.json) and
[Verilator](../build/async-ew-boundary-native/verilator-v3/report.json) suites
each pass 36 cases: eighteen scenarios at synchronizer depths three and five.
The added stopped-core-reset case first observes an actual E1, stops the core
clock, asserts and releases the joint epoch while that clock stays stopped,
then queues original raw work before resuming it. Full output and exact counts
pass; this tests the purpose of the DMA reset register. All numerical goldens,
error expectations, strict warnings and deadlines remain unchanged. The
[source/binary/log/output rehash](../build/async-clock-scope-controls/v1/receipt.json)
checks both native matrices. These simulations establish no physical clock/
reset distribution, metastability, MIG training, physical DDR or RK equivalence.

The first combined [native mapping](../build/async-ew-clock-mapping/constrained-v1/report.json)
is rejected by the strict job-result register inventory at bit 36. The saved
netlist removes error-code bits 7:4: this EW source produces only E1 through
E8, so those bits are constant zero. A separate
[read-only native query](../build/async-ew-clock-mapping/constant-query-v2/report.json)
finds the four source boundary pins and top-level result ports on actual
`GROUND` nets; the intermediate result output pins are unconnected. The
generic default `full8` profile still rejects missing registers. The explicit
`ew_e1_e8` profile now verifies all four input pins and observable output ports
have exactly one `GROUND` net/driver, their unused child outputs are disconnected,
and the corresponding high-bit registers are absent. It admits only those four
proven constant bits. Missing dynamic registers, changed input/output values,
directions, drivers or unsupported profile names still fail. No unused registers
are forced into the design to obtain a pass.

Both CDC report helpers now scope a hierarchical instance with the documented
[`report_bus_skew -cells` option](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/report_bus_skew).
Their earlier global reports assumed only one crossing. Three mock controls
verify distinct instance scopes, standalone behavior and rejection of missing,
duplicate, primitive or invalid hierarchy. This source change has separate
evidence; the earlier standalone mapping receipts retain their frozen helpers.

The fresh [combined native mapping](../build/async-ew-clock-mapping/constrained-v2/report.json)
and [independent rehash](../build/async-ew-clock-mapping/constrained-v2/root-review.json)
now pass 167 active held-data paths plus those four constant bits and eighteen
synchronizer stages. Job descriptor/result bounds remain 40/15 ns and memory
request/response bounds 15/40 ns; minimum synthesized path slack is respectively
+39.485/+14.485 and +14.485/+39.271 ns. Each instance's two bus-skew groups pass
separately. The mapped component uses 2,936 LUTs, 1,140 registers and one DSP.
Its 167 CDC-15 warnings, six CDC-3 informational findings, three case-equality
lowering warnings and the timing notice retain their native severity. This
unplaced component result supplies no board timing, physical DDR or full512
resource result. Constant-field and instance-scope mock controls have separate
[source-bound evidence](../build/async-job-constant-controls/v2/receipt.json).

The later [actual MIG/platform checkpoint audit](../build/async-ew-clock-mapping/v2-job-memory-cdc-v2/report.json)
and [independent rehash](../build/async-ew-clock-mapping/v2-job-memory-cdc-v2/root-review.json)
also pass the167 dynamic payload bits, four constant bits and18 synchronizer
stages with the same bounds. This uses the explicit `ew_engine_e1_e8` profile:
the platform does not export `ui_result_code`, so the proof requires the actual
`rk_ew_async_engine` parent, its `job_crossing` child and all four constant
output pins inside that engine. It checks their internal single-driver GROUND
nets with the documented
[`get_nets -boundary_type lower` query](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/get_nets).
The first attempt queried an unused external segment and failed; that receipt
is preserved. An absent net remains a failure. Eight job and three instance-
scope [control methods](../build/async-job-engine-observer-controls/v1/report.json)
pass, including wrong/missing module, pin, driver,
internal net and dynamic-register rejections. The generic `full8` profile
remains strict, and the earlier top-port profile is unchanged.

This is not a whole-platform CDC pass. The actual checkpoint retains six
CDC-1 and13 CDC-10 critical findings around reset/barrier/vendor circuitry,
plus other native CDC diagnostics. Reset release, admission witnesses and
vendor clock/reset paths require their own source-bound review; no global
clock cuts, waivers, routing, bitstream or physical DDR result is supplied.
