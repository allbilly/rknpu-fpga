# Full512 CMAC timing candidates

The original full C32/K16 startup design routed with all 512 products but
failed the unchanged 20 ns setup requirement at −13.249 ns. Its longest
synthesized path had 66 logic levels, including a serial maximum-exponent
selector. The separate balanced-selector variant preserves the original
one-slot interface and arithmetic. It passed both native simulators and a
source-extracted binary selector proof, then routed at −2.350 ns. Post-route
physical optimization improved that to −1.686 ns, which still fails. Neither
failed design produced a bitstream.

The current candidate adds a real register boundary after operand preparation
and before the compensated DSP lanes and FP44 group reduction. The
implementation retains C32/K16 and 512 parallel products. Its 50 MHz clock,
pin/configuration settings and internal timing/DRC requirements are unchanged.
There is no multicycle timing exception for the arithmetic.

## Numerical boundary

The new cell captures the original sign/pre-shifted mantissa operands, pair
mask, exponent difference, common exponent and donor NaN selection. Weight
still supplies `op_a`, data supplies `op_b`. The existing compensated DSP lane
and 38-bit integer reduction remain unchanged, including reduction order.
The register boundary performs no rounding, dtype conversion or layout repair.
The NaN rule remains weight-before-data, lowest channel first.

The final raw RK command words and physical BO layout remain the execution
boundary. These candidates do not establish RK3588 exceptional-value
equivalence or add support for previously rejected register fields.

## Stream and reset contract

The pipelined array has two registered ownership stages. Preparation captures
on the accepting edge; the result becomes output-valid on the next rising
edge when unstalled. It accepts one
frame per clock when the consumer keeps accepting results. When an output is
held, both stages and their tags freeze, and new input admission stops.

`busy` includes the preparation stage before `out_valid` appears. The generated
CMAC/CACC wrapper connects this signal explicitly. First/last/address tags stay
with their operands; the final memory-write acknowledgment still determines
raw-job completion.

Reset clears valid bits, tags, output ownership and sticky error. Internal
payload registers use configuration INIT=0 and retain their contents across a
runtime reset. No retained payload is observable as a valid result: every
accepted frame overwrites every payload field before it can retire. This
avoids adding 19,200 loads to the engine's asynchronous reset network. It does
not promise a clock-stability detector or transaction rollback.

## Earlier pipeline evidence

Both fresh full512 native suites pass the unchanged 208-frame corpus, checking
3,328 numerical outputs, 3,312 retirements, 16 output-reset cancellations and
520 held cycles. Icarus also passes the original sticky unknown-input fault.
Additional checks fill both stages, hold and drain two frames in order, and
cancel a preparation-stage frame through reset. A corrupted oracle must fail.

The [frozen pipeline package](../build/full512-pipeline-preparation/1793008000/report.json)
binds those exact sources and reports. The completed
[Vivado checkpoint run](../build/full512-pipeline-implementation/1793007479542120029/run.json)
returned zero with the source snapshot intact. Its [routed timing report](../build/full512-pipeline-preparation/1793008000/implementation/timing.rpt)
records +0.045 ns setup slack (45 ps), +0.075 ns hold slack and +9.600 ns pulse
width slack at 20 ns, with zero failing endpoints in all three groups, zero
no-clock and zero unconstrained-internal endpoints. All 512 CMAC products
remain; routed utilization is 267,210 LUTs (89.49%), 35,776 registers, six
BRAM tiles and 515 DSPs total.

The [DRC report](../build/full512-pipeline-preparation/1793008000/implementation/drc.rpt)
records 2,081 warning-level findings: 1,030 DPIP-1, 515 DPOP-1, 515 DPOP-2,
20 REQP-1839 RAM async-control checks and one CHECK-3 rule-limit warning.
No source constraints or DRC waivers changed. Startup/INIT mapping, image and
electrical review, DRC-warning review and mapped validation remain before any
bitstream. The initial Icarus mapped compile was stopped for resource use. A
separate XSIM 2026.1 attempt compiled and elaborated the actual synthesized
array, then failed to initialize: its BASIC license permits 50,000 instances,
whereas this array has 429,342. The corrupted-oracle and golden numerical tests
did not execute; this is not mapped validation. See the
[failed vendor replay](../build/full512-pipeline-implementation/1793007479542120029/mapped-array-xsim/report.json).
No bitstream was emitted or
programmed, and this run makes no full512 hardware/execution claim. The earlier
un-pipelined and balanced-selector timing failures above remain failed records.
Native simulation is not FPGA execution.

A subsequent full-array Icarus compile also failed with `std::bad_alloc`
under an 18 GiB address-space cap; no numerical replay ran. Exporting each
actual mapped kernel reduced resource demand, but did not preserve the
standalone RTL interface. A diagnostic that explicitly drives inputs after
vendor GSR release reached frame 12, then found exported result bit 38 different
from the unchanged oracle. The read-only
[checkpoint pin trace](../build/mapped-boundary-alias-diagnostic/pins.txt)
shows that bit 38 has no physical net at the kernel/array boundary; physical
bit 39 instead feeds the CACC donor's input bit 38. Those two bits are equal
in the original cell's finite and NaN encodings. The array's mask inputs are
also specialized to all ones by the raw front end. Thus this context-optimized
subcell export cannot serve as the original standalone arbitrary-mask/44-bit
interface without a verified boundary model. The original tests and expected
bits remain unchanged. These failed component replays supply no mapped pass;
a closed integrated replay or independently preserved standalone interface is
still required.

The [selected portable timing archive](../verification/runs/2026-10-26-full512-pipeline-timing/index.json)
preserves the exact timing reports, source inputs, ROM data and native-report
summaries. Binary checkpoints and complete simulator execution directories
remain local; the archive is not image or programming admission.

The production `make -j2 test` refresh timed out in its unchanged host Icarus
`async_sub_9` case at 600 seconds. A focused retry with the same source, tools,
binary, inputs and 600-second limit then passed in 499.489 seconds with all
1,600 rows matching. The original whole-suite timeout remains failed; it is
not relabeled as a successful Makefile run. The pipeline-specific tests above
passed independently.

The later [fresh private production refresh](../build/production-refresh-private/20261026T125525Z/report.json)
passes literal `make -j2 test` in 471.858 seconds, with its complete source
copy unchanged at production manifest `d1d0e3d0...f59a`. It checks 1,087,299
numeric comparisons, 249 RTL entries per simulator, all three raw-product
CMAC benches per simulator and all 15 host-BRAM scenarios per simulator.
No test deadline, golden or error expectation changed. This separate complete
run preserves the earlier timeout and focused-retry records; production
simulation does not qualify the experimental full512 image.

## Registered BRAM-control candidate

The RAM warnings identify a concrete topology problem: asynchronously reset
registers drive physical BRAM address pins. A separate candidate adds
`rk_cmac_demo_memory_regport` and a startup-only
`rk_cmac_array_bram_demo_regmem` / `ypcb_cmac_array_regmem_top`. It retains the
qualified two-stage C32/K16 arithmetic, raw commands, apertures, ROM contents,
pad constraints and 20 ns clock. The earlier timing pass applies to its own
frozen source, not this modified candidate.

Both RAM ports now capture address, data, enable and write controls in
initialized registers with no asynchronous reset. An operation accepted on
edge A accesses RAM on edge B and presents its response after edge B. The
response and read data remain stable under backpressure. No new operation is
accepted on that port until its previous response retires. Odd and unmapped
core addresses still produce an explicit error and cannot write RAM.

Reset immediately clears response ownership and blocks admission. A write
accepted before reset may still commit on the following RAM clock edge;
reset provides no rollback. RAM contents are never reset. The controller uses
the host port during initialization/readback and the core port during the raw
job, with a drain boundary between them; simultaneous same-address writes are
not an execution mode. ROM index and startup controller resets are synchronous
to the continuously running system clock. The existing 64-cycle startup hold
and edge-65 release remain unchanged.

The unchanged original memory bench passes under both
[Icarus](../build/regmem-memory/iverilog-1793024000/report.json) and
[Verilator](../build/regmem-memory/verilator-1793024000/report.json): all
3,712 mapped and 4,096 flat halfwords, 11,144 transactions, 3,720 rejections,
held responses and accepted-write/reset behavior. Its only bench edit is the
DUT module name. Fresh complete raw-board suites now pass
[11 Icarus cases](../build/regmem-board/iverilog-reviewed-20261026T110614Z/report.json)
and [10 Verilator cases](../build/regmem-board/verilator-20261026T105744Z/native/report.json).
Every successful workload initializes/checks 4,096 halfwords, reads 196 command
and 6,528 operand halfwords, accepts 12 full frames and completes 64 writes and
acknowledgments in 59,896 cycles. The original fault, abort and fresh-process
checks remain intact. The earlier pipeline board required 44,916 cycles. The
14,980-cycle increase is exactly one additional cycle for each of 8,192 host
initialization/readback operations, 196 command reads, 6,528 operand reads and
64 result writes. The arithmetic pipeline and its unstalled frame rate are
unchanged. The first Verilator producer remains failed at an
unreviewed mixed-reset warning; its fresh successor retains the warning under
an exact source-hash/location review, plus all 54 original donor/prefix
findings. No warning is disabled in the simulator or RTL. Seven warning-review
controls reject missing, duplicated, changed and unknown findings and source
drift. Verilator documents the
[mixed reset style diagnostic](https://verilator.org/guide/latest/warnings.html#cmdoption-arg-SYNCASYNCNET);
the startup-only source-specific reasoning is in
`tools/cmac/regmem/warnings.py`.

The [RAM-only synthesis diagnostic](../build/regmem-memory-synthesis-20261026T105207Z/report.json)
infers block RAM with synchronous address-register drivers and no REQP-1839
findings. Its out-of-context DRC retains a CFGBVS/config-voltage warning; it
does not qualify the complete board. A fresh
[full512 Vivado checkpoint run](../build/full512-regmem-implementation/20261026T111740Z/run.json)
has completed the new source at the same 20 ns target. The exact full
synthesis checkpoint has passed an independent
[RAM topology review](../build/regmem-full-synthesis-drc/root-review.json):
all 276 RAM-control driver connections use FDRE synchronous registers or
constants, with zero REQP-1839 and zero CHECK-3 findings. Its full default
[synthesis DRC report](../build/regmem-full-synthesis-drc/drc.rpt) retains
2,060 DSP pipelining warnings (1,030 DPIP-1, 515 DPOP-1, 515 DPOP-2), with no
severity/rule changes. Its routed DRC retains only those same 2,060 DSP
warnings, with no RAM async-control or rule-limit findings. The later
[independent root review](../build/full512-regmem-implementation/20261026T111740Z/root-init-drc-review.json)
verifies all 65 INIT=0 startup FDREs, their exact 64-stage predecessor chain
and registered release, system clock, pad assignments and zero waivers. All
515 DSPs keep A/B/M/P pipeline selections at zero; the three address helpers
retain an unused default CREG=1 in pure-multiply mode. The arithmetic uses
its qualified external register boundary and meets the routed 20 ns target.
The 2,060 factory performance advisories are reviewed and retained with no
severity or rule changes. The native Tcl audit exited zero, but its wrapper
misread the completion marker and failed in postprocessing; that original
failed wrapper remains unchanged. The separate root review checks the actual
Tcl result, outputs and pinned inputs. No release edge, optical LED polarity
or supply rail was newly measured. Those checkpoint-stage records granted no
image or physical acceptance; the later exact-image/card result is recorded
separately in [CMAC_FPGA_TEST.md](CMAC_FPGA_TEST.md).

The [completed run](../build/full512-regmem-implementation/20261026T111740Z/run.json)
returned zero in 1,880.107 seconds, with all 125 source files and ten output
hashes intact. The [independent timing review](../build/full512-regmem-implementation/20261026T111740Z/root-timing-review.json)
records setup +0.987 ns and hold +0.057 ns across 77,592 endpoints, and pulse
width +9.600 ns across 35,831 endpoints; all three groups have zero failures.
No-clock and unconstrained-internal checks each report zero. The final router
reports zero failed, unrouted or partially routed nets and zero node overlaps.
The design retains all 512 CMAC products and uses 267,240 LUTs (89.50%), 35,822
registers, six BRAM tiles and 515 DSPs. Its routed DCP SHA256 is
`9e3166635b11da4f44877991ee8c15fb9bc11d98727ce20038dba810819bba9f`.
These are exact-source 50 MHz timing results, not an Fmax sweep or measured
physical frequency.

The actual closed top has been
[exported read-only](../build/regmem-closed-mapped-preparation/export-run-20261026T112927Z/report.json)
with all 512 CMAC products, avoiding the optimized subcell-interface boundary.
Its prepared simulation bench uses only the exact clock/three-PAD interface.
Six dummy-DUT controls pass, covering positive completion and rejection of an
inverted checker, FAIL, unknown PAD, missing completion and unstable PASS.
The first closed-design Icarus compile failed after 705.361 seconds under a
24 GiB address-space limit (`calloc() ran out of memory`); no simulation ran.
After Vivado released its memory, a fresh 32 GiB profile passed an explicit
available-memory/swap check with a 4 GiB reserve, but also exhausted memory
after 802.362 seconds. Both failed compiles remain failed; neither ran the
numerical test.

A simulation-only LUT model profile then passed
[3,419,904 four-state comparisons](../build/regmem-fast-lut-proof/20261026T121838Z/report.json)
against AMD's original models: every configured INIT (183 LUT4, 290 LUT5 and
751 LUT6 configurations) with all 0/1/X/Z selector combinations, plus initial
event behavior. Its deliberately wrong-output control rejects. Only those
three primitive behavioral bodies use balanced ternary expressions; all
mapped instances, truth tables, clocks, DSP/RAM/FF models and FPGA sources
remain unchanged. The runner recomputes the complete inventory and derivation
and binds every proof artifact before admitting this profile.

The [proof-bound closed-design replay](../build/regmem-closed-mapped-replay/20261026T122537Z-lutproof/report.json)
compiled in 661.592 seconds under the original 24 GiB limit and is executing
the original tests with their unchanged 7,200-second command limits. The
positive startup test now passes after 6,389.579 seconds:
`PASS closed_mapped_full512_startup pad_pass=1 pad_fail=0 stable_cycles=32 observed_cycles=59973`.
The [independent positive review](../build/full512-regmem-implementation/20261026T111740Z/root-mapped-positive-review.json)
also reconciles that count exactly: the native 59,896 includes 20 post-result
checks; subtract those, add 65 startup edges and the mapped bench's 32 stable
checks to obtain 59,973. The simulation finishes at 1,199,551,000 ps. Numerical
values are inferred from the source-bound internal scoreboard, not directly
read from the physical card.

The deliberately inverted expected-failure checker subsequently rejected
exactly as required (return code 1 after 5,791.955 seconds). The aggregate
report is now `PASS_ACTUAL_CLOSED_FULL512_MAPPED_STARTUP_WITH_PROVEN_LUT_MODEL_ONLY`.
The original memory failures remain failed. This mapped result has no SDF or
physical meaning by itself; later independent image review and actual card
observations supplied the separate [FPGA milestone](CMAC_FPGA_TEST.md).

The [193-file text archive](../verification/runs/2026-10-26-full512-regmem-timing/index.json)
preserves all 125 frozen source files, selected native/timing/INIT/DRC reports,
model proof and observer controls. Its independent copy/hash audit passes.
Checkpoints, full netlists and compiled simulator images remain local. This
archive grants no image or programming admission.

The source-bound `prepare-image.py` refused incomplete and positive-only
mapped reports before any output/native call. After the aggregate pass it
rendered the exact bitstream command. The native template has a valid mocked
path plus 31 emission-blocking scenarios and passes plain Tcl 9.0.3 and vendor
Tcl 8.6.13 controls. Source/path parsing and single-port normalization failures
remain preserved alongside their corrected successors. It pins all qualified
inputs, rechecks native timing/geometry/IO/waivers/pulse/DRC and only sets the
source USR_ACCESS tag. It contains no hardware-manager/programming command.

The native emission exited zero with unchanged inputs and 2,060 known DSP
advisories, followed by independent exact-image review. The resulting image
passed three actual volatile loads, fresh target checks and four positive
SAMPLE captures. See [the physical report](CMAC_FPGA_TEST.md) for hashes,
receipts and finite-workload limitations. Flash was not written.

## Full512 observation preparation

`tools/hardware/sample_cmac512.py` now provides a separate preparation/decoder
profile for the registered-RAM startup candidate. The EW observer and its
acceptance rules remain unchanged. This profile binds the exact preparation
report, 31 selected hardware sources plus ten numerical fixtures, image hash,
compiled LED generic, BSDL cells, target and load receipt. The capture format
has its own `CMACSAMPLE1` namespace. Baselines retain unknown application
status; post-load observations require matching source/profile/image and an
aware load-completion timestamp, valid INIT/DONE, enabled PASS/fail drivers
and continuing heartbeat transitions.

All [20 EW/full512 observer controls](../build/cmac512-observer-controls-v2/audit.json)
pass, including mocked Tcl with only IDCODE/SAMPLE/BYPASS operations. The
[real-source copied-decoder controls](../build/cmac512-observer-copy-controls/20261026T120104Z/audit.json)
also pass under isolated Python outside the checkout and reject a changed
copied ROM. Their bitstream, load receipt and capture are synthetic; no
hardware was accessed. The observer never programs the card and supplies no
image admission. The later actual physical result observes the built-in
4,096-halfword scoreboard output, not direct RAM readback or general RK3588
equivalence; its real receipts are separate from these synthetic controls.
