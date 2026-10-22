# RKNPU-sized CMAC first

The user's current priority is the RKNPU-sized CMAC and its NVDLA numerical
verification, before further board-demo/consolidation work. The new sources
are `rtl/cmac/rk_cmac_fp16_cell.sv` and `rtl/cmac/rk_cmac_fp16_array.sv`.
They now have a separate raw-command-connected candidate under
`rtl/cmac/rk_cmac_array_core.sv`, with first integration simulation running.
It has not replaced the existing serialized C64 core or board top. No new
tensor execution interface or CPU fallback is introduced.

## Geometry and sources

The local RK3588 TRM transcription at `/home/fedora/npu/docs/rk3588_trm.md`
states 512 FP16 MAC operations per cycle per core (lines 417–420), 16 FP16
kernels per group (2269–2270), and a 32x32 INT8 single-core array mode
(2343–2352). Together these support the working FP16 geometry **C32 × K16**.
The 32-channel numerical group is an explicit inference from these hardware
counts and kernel grouping, consistent with the backend's IC32/OC16 layout;
storage packing alone was not sufficient to establish it. RK exceptional
values and the exact accumulator boundary still require hardware comparison.

This corrects the prior implementation's blanket 64-pair donor grouping
assumption. That older implementation and its tests remain preserved, not
silently relabeled as C32 evidence. NVIDIA's `nvdlav1` uses C64 FP16 cells;
the new array has 16 independently evaluated output kernels with 32 parallel
donor multiplier instances each: 512 products per accepted frame. It is not
the earlier single time-multiplexed Booth lane.

The current cell reuses NVIDIA's multiplier partial-row representation,
alignment, compensation and FP44 output format. The parallel reduction
currently has a combinational path; neither 50 MHz timing nor efficient DSP
mapping has been established. Inferred-DSP replacement is a later equivalence
step, not a reason to silently change numerical behavior.

The source `~/ypcb/ref/ZYNQ-NVDLA`, revision
`8879622518b9d500b024b80466156968f5e48056`, is an `nv_small` FPGA integration.
Its generated CMAC cell has C8, 8-bit signed inputs, 19-bit output and inferred
`*` operations under `DESIGNWARE_NOEXIST`. Its README identifies the 8x8
INT8-small integration and provides Tengine INT8 examples, reports and SDK
sanity code. These are useful FPGA/control/scaling references, not an FP16
oracle. The checkout was inspected without modification.

The user-supplied article https://zhuanlan.zhihu.com/p/630822241 returned HTTP
403 during inspection; its contents have not been assumed or summarized.
Official configuration and verification references inspected:
https://nvdla.org/hw/v2/scalability.html and
https://nvdla.org/hw/v2/verif_guide.html . The v2 scalability table describes
INT8 `nv_small` C8/K8 and `nv_large` C64/K32; these must not be mislabeled as
FP16 tests. The inspected `master` MAC is integer arithmetic, whereas the
local `nvdlav1` arithmetic donor supports FP16.

## Unit boundary

An accepted frame broadcasts C FP16 inputs to K independently packed weight
vectors. Presence masks suppress lanes, including their NaNs; disabled lanes
are conceptually zero. NVDLA's nonzero-mask interface is different, so the
reference adapter explicitly materializes that zero value and derives the
matching nonzero bits. This is test-only interface adaptation, not a host
runtime layout/arithmetic fixup.

Each kernel returns an FP44 group: six exponent bits and a signed 38-bit
mantissa, with the inherited donor NaN encoding. Weight NaNs precede data
NaNs, with lowest active channel first. The cell retains separate-row donor
alignment, not rounded half products. The array has one elastic result slot,
holds the complete K-result frame and tag under backpressure, and can replace
a retiring frame each cycle after its reset/configuration warmup. Reset drops
pending results; unknown input/tag/mask data faults in four-state simulation.
The leaf has no RK command decoder; eventual execution must still enter
through the existing final raw command words.

## Actual checks and next acceptance

`tools/cmac/gen_array_vectors.py` generated 208 C32/K16 frames and 3,328
expected FP44 results, covering uniform exceptional values, every single
channel, random finite/raw encodings and masks. It executes NVIDIA's original
integer Booth helper and independently computes the sized grouping policy.
The existing C64 fixtures are unchanged.

`tools/cmac/test_array.py` checks the actual 512-multiplier array's results,
tags, held output and reset cancellation; Icarus adds unknown input rejection.
Its full Icarus arithmetic/reset run reached its 7,200-second simulation limit
without a final result and is recorded as **FAIL (timeout)**, not a pass:
`build/rknpu-cmac-array/c32k16/iverilog-1789989217662343531/report.json`.
No assertions or expected values were changed. This timeout is separate from
the completed full-array streaming test below. Both full-array Verilator lint
stages have passed, with only the recorded original-donor warnings. Its C++
binary compilation subsequently reached the 7,200-second limit and the runner
records **FAIL (compile timeout)** at
`build/rknpu-cmac-array/c32k16/verilator-1789989216803834842/report.json`.
This is not an arithmetic mismatch or a completed simulation. The separate
two-state retry below now passes; full-array four-state X rejection remains
unverified by this timed-out run.

The original Verilator build spent over an hour optimizing two generated
C++ amalgamation units at `-Os`. A separate `tools/cmac/test_array_o0.py` run
copies the exact generated C++/headers/Makefiles into an isolated directory and
builds at `-O0`, preserving all 208 vectors and every bench assertion. It checks
both completed lint steps and source/vector hashes before reuse, leaves the
original generated source untouched, and records the host compiler flags separately.
The new build and complete native hold/reset test now **pass** at
`build/rknpu-cmac-array/c32k16/verilator-o0-1789997834430105657/report.json`.
Verilator checks all 208 frames and 3,328 outputs, 520 held cycles, 3,312
retired outputs and 16 reset-canceled pending outputs, with zero arithmetic
mismatches. Compilation took 3,563.413 seconds and simulation 615.734 seconds.
This is the unchanged full test, not a reduced corpus; it does not include
Icarus-only X injection. After this completed pass, the audited orphan compiler
processes from the already failed original build were terminated with SIGTERM;
their source, partial objects and failed report remain intact.
The new passing run is archived with its exact generated C++, source,
lint logs, compiler flags and test output under
`verification/runs/2026-09-21-cmac-c32k16-native-hold-reset/`:
1,139 verified members, archive SHA256
`933587ba7d1a6dcb0208ed9613744e20ecd26ceca2cf0ed3877fa97027fcda3b`.

### Hierarchical simulation experiment

To make complete integration regression more practical,
`tools/cmac/test_hier_array.py` starts a separate Verilator 5.048 build using
`tools/cmac/array_hierarchy.vlt` to partition the repeated C32 cell. This uses
[Verilator's documented hierarchical compilation](https://verilator.org/guide/latest/verilating.html#hierarchical-verilation),
not different RTL or a numerical substitute. All 16 kernels, 512 multipliers,
208 vectors and original bench assertions remain. The first required gate is
exact equality with the completed flat-model test's output/hold/reset result;
board tests are not switched to this simulation strategy before that passes.
Hierarchy partitioning is not a synthesis change or an FPGA CPU fallback.

The experiment was stopped and is recorded as `FAIL` at
`build/rknpu-cmac-array/c32k16/hierarchical-1790003524808266837/report.json`.
Its compiler introduced an additional `DECLFILENAME` diagnostic by renaming
the parameterized module to `rk_cmac_fp16_cell_b` while retaining the original
filename. The generated hierarchy arguments explicitly record that mapping,
and the generated library wrapper has the expected C32 data/mask widths.
No arithmetic or width diagnostic is newly waived. Inspection of the emitted
top-level C++ found embedded donor multiplier classes and no protected-library
calls. The compiler was still compiling those classes, so only its audited
process group was terminated with SIGTERM (return code -15, 1,603.804 seconds).
Its runner recorded the failure normally; no source or report was rewritten
to convert it to a pass, and no generated files were deliberately removed.

`tools/cmac/replay_hier_array.py` is prepared to reuse that binary only after
the compiler exits successfully and the strict runner terminates with exactly
this extra-warning rejection. It checks the complete warning-location set,
exact diagnostic text, generated mapping/interface, all source/vector hashes,
and actual top-level library calls with no embedded donor multiplier classes,
then runs every assertion against the unchanged full corpus. The added
partition-use gate rejects this emitted top in a negative test. The terminated
run is also ineligible for replay because its compiler did not exit zero.
Thus the generated wrapper/plan alone is not accepted as proof of partitioning.
No completed hierarchical simulation is claimed for that aborted run. The
corrected experiment below is separate; the original Icarus runs continue
without interruption.

```sh
make -f fpga/cmac/Makefile cmac-hier-test \
  FLAT_REPORT=build/rknpu-cmac-array/c32k16/verilator-o0-<run>/report.json
# Verilator 5.048 generated-name review, only after that strict run finishes:
make -f fpga/cmac/Makefile cmac-hier-replay \
  COMPILED_REPORT=build/rknpu-cmac-array/c32k16/hierarchical-<run>/report.json
```

### Explicit hierarchy parameter transport experiment

The [5.048 parameter-substitution source](https://github.com/verilator/verilator/blob/v5.048/src/V3Param.cpp)
requires a nonempty hierarchy-parameter-file path to enter its sub-run
library-substitution branch. The stock generated CMAC top arguments omitted
that option. This suggested a tool-path issue, not an arithmetic RTL defect.

`tools/cmac/probe_hierarchy.py` now reproduces the difference on four small
sequential instances. The completed report is
`build/hierarchy-probe/1790005879174187890/report.json`, status
`PASS_HIERARCHY_TOOL_PROBE_ONLY`: stock compilation has no protected-library
calls, while an explicit empty parameter file enables them. Both executables
pass 128 independent-instance outputs and two reset checks. The explicit
sub-run supplies its hierarchy makefile fragment and links the already-built
leaf library. Three earlier probe failures remain recorded: clock-init lint,
a comment inadvertently parsed as a tool pragma, and a missing makefile
fragment. No warning expectation or numerical golden was weakened.

This small probe does not validate CMAC. `tools/cmac/test_hier_array_explicit.py`
requires its source-matching pass and the full flat CMAC pass, builds a fresh
C32 library, then generates the C32/K16 top with the same parameter-file
transport. Before C++ compilation it requires actual library calls and rejects
embedded donor multiplier classes. It then executes the unchanged full
208-frame/3,328-output hold/reset bench and requires exact equality with the
flat result. All RTL, masks, values, assertions and seed stay unchanged.
The corrected full-width run now passes at
`build/rknpu-cmac-array/c32k16/hierarchical-explicit-1790006092695327721/report.json`.
All 3,328 checked outputs match, with 3,312 retired outputs, 16 reset-cancelled
outputs and 520 held cycles, seed `35883216`. Its source manifest is
`17abe4b073da0e63a4020141ff66ebd4da6f973c0c4d6ca6521674b8bd0c92ad`.
Recorded durations are 266.418 seconds for the fresh C32 library build,
2.391 seconds for top generation, 82.632 seconds for top compilation and
427.386 seconds for simulation. These are this run's measurements, not a
controlled benchmark or a hardware timing result. The library can now be
used for further two-state integration tests while preserving the RTL and
checking the exact source/artifact hashes.

The initial verified library uses `-O0` host C++ compilation. A separate
`tools/cmac/rebuild_hier_array.py` experiment now replays all six recorded
build/test commands into new output directories with only `OPT_FAST`,
`OPT_SLOW` and `OPT_GLOBAL` changed to `-O2`. It verifies the original source
and artifact hashes, simulator/compiler versions, unchanged 208-frame corpus,
actual generated library calls and exact output/hold/reset result. It also
checks that both compile logs contain `-O2` and no `-O0` compiler invocations.
No RTL, numerical policy, simulator assertion, fast-math setting or physical
constraint changes. The run passes at
`build/rknpu-cmac-array/c32k16/hierarchical-o2-1790007529867178162/report.json`;
all 3,328 comparisons, 16 reset cancellations and 520 held cycles match the
original result. Fresh cell compilation took 645.941 seconds, top compilation
154.609 seconds and simulation 24.883 seconds (versus 427.386 seconds for the
earlier unoptimized simulation). These are observed run times, not a controlled
benchmark or FPGA timing measurements. The verified optimized library is now
used by a separate full AXI run; the original run remains independent.
The optimized build is archived with 1,461 verified members under
`verification/runs/2026-09-22-c32k16-optimized-host/`, archive SHA256
`3b99014037942a157f9ce2630733f899427cfc0bb53a60f7d1a53cec9acb0807`.

```sh
make -f fpga/cmac/Makefile hierarchy-probe
make -f fpga/cmac/Makefile cmac-hier-explicit-test \
  FLAT_REPORT=build/rknpu-cmac-array/c32k16/verilator-o0-<run>/report.json \
  PROBE_REPORT=build/hierarchy-probe/<run>/report.json
make -f fpga/cmac/Makefile cmac-hier-o2-test \
  SOURCE_REPORT=build/rknpu-cmac-array/c32k16/hierarchical-explicit-<run>/report.json
```

The additional `tests/cmac/tb_cmac_fp16_stream.sv` and
`tools/cmac/test_stream.py` exercise consecutive accepted frames, simultaneous
retirement/replacement, input gaps and independently stalled outputs. A
scoreboard checks every frame and tag before retirement, with a required
64-frame continuous acceptance burst and a complete drain/duplicate check.
The deterministic flow-control seed is `0x35883216`. C32/K1 isolation now
passes in Icarus: 208 frames/outputs, 65 consecutive accepted frames, 186
simultaneous retirements/replacements and 33 output-stall cycles. The separate
C32/K1 arithmetic/reset test also passes all 208 comparisons, 520 held cycles,
one reset-canceled output and one sticky unknown-input fault. These use Icarus
13.0. The full **C32/K16 streaming run now passes independently**: all 208
frames and 3,328 outputs, 65 consecutive accepted frames, 186 simultaneous
retirements/replacements and 33 output-stall cycles over 272 simulated cycles.
Report: `build/rknpu-cmac-array/c32k16/stream-iverilog-1789990348504772352/report.json`.
This is an actual full-width result, not an inferred pass from K1; the separate
arithmetic/reset/X-rejection run remains a distinct gate.
This adds coverage rather than replacing reset, X-rejection or numerical tests.
The completed K1 reports and K16 C-model result are archived together under
`verification/runs/2026-09-21-cmac-c32k1-native/`; the index distinguishes their
configurations and proof scope.

`tools/cmac/check_nvdla_mac_cell.py` additionally extracts the **entire unchanged
NvdlaMacCell class**, executes its FP16 calculation with real SystemC 3.0.2
types, and compares every expected output. C32 is embedded into the unchanged
C64 reference using zero/masked upper channels. This is stronger than running
only its Booth helper but is still not the full NVDLA TLM model or original
`nvdla_utb` regression. Its first adapter compile failed because NVIDIA's
printf-style FAIL macro was incorrectly bound to a one-string exception;
the retained retry preserves format arguments. No donor arithmetic was edited.
The second attempt compiled but could not load `libsystemc`; this installation's
pkg-config file has no `libdir` variable. Using its actual `-L` directory as
the runtime search path fixes the adapter. The fresh third run **passes all
3,328 outputs with zero mismatches**, executing the unchanged class under
SystemC 3.0.2. Its source-bound report is
`build/rknpu-cmac-array/c32k16/nvdla-mac-cell-1789989595701148341/report.json`.
The two failed harness attempts and their source snapshots remain retained.
Original unused-variable/parameter warnings remain in the C++ compile log.
This C-model result does not substitute for native RTL reset/fault testing.

The native-width C64/K1 cross-check now also passes all 240 outputs against
the unchanged full `NvdlaMacCell` class, at
`build/rknpu-cmac-array/c64k1/nvdla-mac-cell-1789992945543571311/report.json`.
Both the resized implementation in C64 mode and the original donor RTL are
tested on those same vectors. The unchanged original donor RTL now passes
all 240 outputs at native C64 width, in
`build/rknpu-cmac-array/c64k1/nvdla-rtl-1789993009413047184/report.json`.
The resized implementation's **C64-mode RTL run now also passes** all 240
comparisons, 600 held cycles, one reset-canceled result and one unknown-input
fault, at `build/rknpu-cmac-array/c64k1/iverilog-1789993007214850821/report.json`.
All three native-width checks are preserved together under
`verification/runs/2026-09-21-cmac-c64-cell-comparison/`.

`tools/cmac/audit_vectors.py` measures the unchanged C32/K16 input corpus.
All coarse exponent gaps 0 through 14 occur in groups with no selected NaN,
all four sign combinations occur, and every input channel is active in
numeric groups. There are 968 groups with both weight and data NaNs, 1,088
with multiple NaN-priority candidates, and 4,118 masked NaN operand occurrences
(data operands are counted per kernel). This is input-stimulus coverage,
not simulator coverage or another arithmetic pass. The report is
`build/rknpu-cmac-array/c32k16/stimulus-audit-1789993170134529105.json`.

`tools/cmac/test_nvdla_rtl.py` now runs the **unchanged native C64 MAC RTL**
directly, including its original exponent pipeline, NaN selection and CSA
reduction. A test-only pin adapter prepares mantissas according to
`NV_NVDLA_CMAC_CORE_active.v`, zero-pads upper channels and presents exponent
inputs one cycle before active data. It checks public outputs without forcing
internal nets. The three original MAC/exponent/NaN sources and `NV_DW_minmax`
are verified byte-for-byte against the pinned `~/hw` Git revision before
compilation. The first harness compilation omitted `NV_DW_minmax` and failed;
that report and runner snapshot are retained. Subsequent runs failed on the
first zero vector with unknown product-row bits. Read-only diagnostics found
an unknown row tag while the public nonzero masks and exponent shift were
zero. The current harness drives its public operand buses after time zero,
while reset is asserted and valid is zero, avoiding declaration-initializer
ordering in the donor's explicit-sensitivity unpacking blocks. No internal
forcing, RTL edit or expected-output change was made. A focused one-frame
diagnostic now produces known rows and the correct zero result; its deliberately
shortened read range emits a too-many-vector-words warning and is not counted
as a full regression. The corrected **complete C32/K1 donor-RTL run now passes
all 208 outputs**, using Icarus 13.0 and native C64 hardware with zero-padded
upper lanes. Its exact source-bound report is
`build/rknpu-cmac-array/c32k1/nvdla-rtl-1789991069710362248/report.json`.
It is archived with the matching resized-cell and streaming checks under
`verification/runs/2026-09-21-cmac-c32-donor-rtl/`. The complete **C32/K16 donor
RTL run now also passes all 3,328 outputs** from the same 208-frame corpus:
`build/rknpu-cmac-array/c32k16/nvdla-rtl-1789991180400388948/report.json`.
Together with the passing resized-array streaming run and unchanged whole
`NvdlaMacCell` class, this establishes agreement on this corpus between the
new C32/K16 RTL, original C64 RTL with zero-padded inputs, and NVIDIA arithmetic
model. It is not exhaustive equivalence. The three completed reports are
archived under `verification/runs/2026-09-21-cmac-c32k16-stream-donor/`.
Failed harness snapshots and diagnostic
logs remain alongside the retry reports. This is direct donor
arithmetic testing, not the upstream `nvdla_utb` test suite.

The upstream `nvdla_utb` tests are broader register/whole-unit sequences, not
standalone CMAC arithmetic vectors. The local v1 simulation Makefile uses VCS;
VCS/xrun were not found. No original upstream UTB pass is claimed. Reusing its
applicable tests and/or scoreboard in the available open-source simulator,
plus native-dimension donor differential tests, remains required work.

The local `origin/master` snapshot `1a65f1f5b48268accaa47c95f95c2601918be095`
was inspected through Git without changing the `nvdlav1` checkout. Its
`nv_large_test_list_L0.py` contains INT8 convolution and image-input tests;
the v1 trace tree contains INT16 convolution traces, not named FP16 traces.
The master CMAC scoreboard is a UVM transaction comparator connected to the
SystemC reference, not a standalone FP16 golden-vector file. Consequently,
these existing tests cannot be relabeled as passes of the new FP16-only leaf.

From the repository root:

```sh
make -f fpga/cmac/Makefile cmac-test                 # C32/K16, Verilator
make -f fpga/cmac/Makefile cmac-test TOOL=iverilog
make -f fpga/cmac/Makefile cmac-stream-test TOOL=iverilog
make -f fpga/cmac/Makefile cmac-nvdla-model
make -f fpga/cmac/Makefile cmac-nvdla-rtl ATOMIC_K=1 # original C64 RTL, C32 embedding
make -f fpga/cmac/Makefile cmac-map                # full internal array, XC7 area only
```

Reports are under `build/rknpu-cmac-array/c32k16/`, with separate tool runs and
preserved failures. C8 remains untested; C64/K1 comparison results are recorded
above. Production `make test` remains
separate and does not cover these new nested sources. The numerical and
streaming/hold/reset passes apply only to the listed corpus. Remaining full-array
four-state fault verification, complete raw/host integration regression, actual NVDLA test reuse and FPGA
mapping/timing must precede claims of a completed RKNPU CMAC port.

`tools/cmac/map_array.py` attempted full C32/K16 mapping with Yosys 0.65.
The runner checks the elaborated hierarchy for exactly 512 original multiplier
instances, then maps to XC7 primitives and checks nonconstant group/tag/flow
outputs. No I/O pads or clock buffer are inserted: this is an internal leaf,
not thousands of proposed package pins. Its LUT/FF/DSP counts are pending.
The elaborated hierarchy has been inspected and contains exactly 512
donor multiplier instances. The default primitive-mapping run failed at its
14,400-second wall-clock limit (14,405.773 seconds including shutdown), report
`build/rknpu-cmac-array/c32k16/yosys-1789991337653886449/report.json`.
It produced no completed primitive count or mapped functional result.
This area/structure run does not stand in for native or mapped numerical tests,
device fit, a routed clock target, electrical checks or a board result.

For the later resource comparison, AMD's
[UG474 v1.9, Table 2](https://docs.amd.com/r/en-US/ug474_7Series_CLB/7-Series-FPGA-CLB-Resources)
lists 298,600 six-input LUTs and 597,200 flip-flops for 7K480T, in 74,650
slices. [DS180 v2.6.1, Table 6](https://docs.amd.com/v/u/en-US/ds180_7Series_Overview)
lists 1,920 DSP slices and 955 36-Kb block RAMs (34,380 Kb total).
These are device capacities, verified against the official tables on
2026-09-22, not available resources after the complete NPU/DDR/PCIe shell.
Primitive-count fractions alone cannot prove routability, timing, legal
packing, pin assignment or electrical signoff. The mapper does not alter its
checks or target based on these reference figures.

The default run spent most of its time in Yosys's SAT-based `share`
optimization, checking potential sharing across the explicitly parallel lanes.
`tools/cmac/map_array_unshared.py` starts a separate source-bound experiment
that retains all installed `synth_xilinx` stages except this optional resource
sharing pass. It checks the installed coarse-stage command list exactly before
constructing that alternative and retains hierarchy, primitive, arithmetic/
control-presence and final `check -assert` gates. No numerical assertion,
physical constraint or DRC/timing gate is removed. The original timeout remains
a failure. The alternative full C32/K16 run also failed at its 14,400-second
limit (14,407.680 seconds including shutdown), recorded at
`build/rknpu-cmac-array/c32k16/yosys-unshared-1789997728584167597/report.json`;
ABC had not returned a completed whole-array mapping. There is no primitive
count, mapped functional result or area/fit claim from this run.

A separate hierarchy-preserving synthesis completed at
`build/rknpu-cmac-array/c32k16/yosys-hierarchical-1790009807873001832/report.json`.
Yosys returned zero, but the report is FAIL after 2,659.145 seconds: the old
recursive counter descended into blackbox INV/LUT declarations containing
`$specify2` timing metadata. It mistook those timing records for hardware.
The failed report and saved netlist remain unchanged.
`tools/cmac/map_array_hierarchical.py` requires the source-matching full native
C32/K16 pass. It retains the C32 module through synthesis so ABC can map one
cell implementation, with sixteen parallel hardware instances. It then
removes only that hierarchy attribute and flattens the mapped primitives.
The installed Yosys help confirms that `flatten` respects `keep_hierarchy`.
No RTL edit, resource sharing, serial MAC or smaller array is substituted.

The new gate requires 512 elaborated donor multipliers, sixteen mapped kernel
instances of one module type, equal expanded primitive counts before/after
final flattening, and the existing nonconstant arithmetic/control outputs.
It retains all XC7 stages apart from the same optional SAT `share` pass.
The earlier flat mapping has timed out independently. A separate recheck,
`build/rknpu-cmac-array/c32k16/yosys-hierarchical-recheck-1790012809729728661/report.json`,
validates the saved synthesis with `tools/cmac/check_hierarchical_mapping.py`.
The primitive-aware counter treats only known, declared blackbox primitives
as leaves and permits only timing metadata inside their declarations. Unknown
hardware, timing cells in the actual design, nonblackbox primitives and
unexpected implementation modules remain failures. Six counter tests pass.
The original geometry, before/after primitive-count equality, output-presence
and source-integrity gates are retained. The recheck now passes after 209.250
seconds, without modifying the saved netlist or failed report. Counts are
512,248 LUT1..6 primitives, 758 FDCE, 5,280 CARRY4, 2,128 MUXF7, 752 MUXF8,
758 INV and zero DSP48E1, with all 512 elaborated multipliers and sixteen
mapped C32 kernel instances retained. These are primitive counts, not packed
physical LUT utilization or timing. The synthesis log's estimated 329,383
logic cells also exceeds the device's 298,600 LUT capacity, making area a
concrete concern; neither estimate substitutes for legal placement/routing.
The completed synthesis/recheck and its exact dependencies are archived at
`verification/runs/2026-09-22-c32k16-mapping-recheck/`: 1,154 verified members,
65,929,437 bytes, archive SHA256
`667b5648e7c9b35193f06d2775395454ca830d622661f4c69d345b9de3f96fec`.

The first attempt at `yosys-hierarchical-1790009698767825876` is retained as
FAIL (manually stopped with SIGTERM, return code -15, 80.684 seconds). Its
elaborated JSON proved that parameter derivation did not preserve the attribute
placed on the original cell template; it had begun flattening the array.
The corrected runner places the attribute on the derived module after
elaboration and asserts exactly one retained module and sixteen instances
before expensive synthesis. No running RTL test or original mapping was
stopped, and no arithmetic or constraint was changed.

```sh
make -f fpga/cmac/Makefile cmac-map-unshared
make -f fpga/cmac/Makefile cmac-map-hierarchical \
  NATIVE_REPORT=build/rknpu-cmac-array/c32k16/verilator-o0-<run>/report.json
make -f fpga/cmac/Makefile cmac-o0-test \
  GENERATED_REPORT=build/rknpu-cmac-array/c32k16/verilator-<run>/report.json
```

`tools/cmac/test_mapped_array.py` prepares the next functional-netlist gate.
It requires completed, source-matching native and mapping reports before
generating a harness. It reuses the arithmetic/hold/tag/reset assertions,
retains default Xilinx GSR, drives operand pins after time zero during reset,
and excludes only native simulation-X injection. Smoke mode selects and records
32 unchanged vector rows; full mode checks all rows. No goldens are recomputed.
The full replay is now compiling at
`build/rknpu-cmac-array/c32k16/mapped-full-1790013072942514731/report.json`.
It uses the completed mapping recheck and source-matching flat native result,
all 208 unchanged frames and 3,328 expected outputs. There is no mapped
functional pass yet.

```sh
make -f fpga/cmac/Makefile cmac-mapped-test \
  MAPPING_REPORT=build/rknpu-cmac-array/c32k16/yosys-<run>/report.json \
  NATIVE_REPORT=build/rknpu-cmac-array/c32k16/iverilog-<run>/report.json \
  SUITE=smoke
```

## Parallel accumulation and the connecting seam

`rtl/cmac/rk_cacc_fp16_array.sv` adds sixteen independent instances of the
existing donor-based FP48 reducer. Input is a complete sixteen-kernel FP44
frame with common first/last flags and a stable reduction tag. Output is a
complete sixteen-kernel **FP32** frame, not FP16 output tensors. Every child
accepts and retires together; lane faults cancel the whole frame, and divergent
output-valid/tag state is an explicit failure. Cancellation is acyclic, sticky
and reset-dominated. One active reduction context exists per kernel. This
does not claim pipelined one-frame-per-cycle accumulator feedback.

The new `tools/cmac/cacc_reference.py` extracts the previously audited dyadic
reference. Its output was checked against all 9,144 unchanged direct-donor
reference tuples before generating the bank corpus. That extraction check
tests Python code, not the new RTL. `gen_cacc_array_vectors.py` groups the
existing 208 C32/K16 CMAC golden frames into 15 ordered reductions, maintaining
independent partial values for all kernels; no FPGA runtime arithmetic is
introduced and no existing CMAC expected output is rewritten.

The full **K16 CACC bank passes Icarus 13.0**: 208 frames, 432 checked kernel
outputs (240 corpus results plus 192 directed/reset results), 24 rejected
cases, nine reset ages, five cancellations and 163 held-output cycles, seed
`0x3588ca16`. Tests include distinct per-kernel powers of two, two-group
feedback, an invalid finite input in each individual lane, malformed NaNs,
first/tag sequencing and unknown operands/control/tag bits. Source-bound report:
`build/rknpu-cacc-array/c32k16/iverilog-1789993693952208946/report.json`.
It is archived under `verification/runs/2026-09-21-cacc-k16-native/`.
**Verilator 5.048 now passes the same 432 output checks**, 20 rejection
cases, nine reset ages, five cancellations and 163 held cycles. Its four
fewer rejection cases are the Icarus-only X checks, not omitted hardware
fault expectations. Both lint stages retain only unchanged donor diagnostics.
Report: `build/rknpu-cacc-array/c32k16/verilator-1789993698024637035/report.json`.
The two-simulator evidence is archived together under
`verification/runs/2026-09-21-cacc-k16-two-sim/`.

`rtl/cmac/rk_cmac_cacc_fp16_array.sv` connects the new CMAC result frame to
that bank, including first/last/tag buffering, backpressure, cancellation and
sticky aggregate faults. The **C32/K1 connecting-pipeline test passes** the
same 208 physical-operand frames: 15 corpus outputs plus ten reset-recovery
outputs, ten reset phases, three cancellations and 110 held cycles, seed
`0x3588cc16`. It compiles without warnings in Icarus 13.0. Report:
`build/rknpu-cmac-cacc-array/c32k1/iverilog-1789993912816511301/report.json`;
archive: `verification/runs/2026-09-21-cmac-cacc-c32k1/`.
The **full C32/K16 connecting-pipeline test now passes independently**: 208
operand frames, 400 checked outputs (including reset recovery), ten reset
phases, three cancellations and 110 held cycles, seed `0x3588cc16`. Report:
`build/rknpu-cmac-cacc-array/c32k16/iverilog-1789994572151338454/report.json`.
This is actual full-width Icarus execution, not extrapolation from K1.
It is archived with the complete arithmetic-to-memory test under
`verification/runs/2026-09-21-c32k16-cacc-datapath-full/`.

```sh
make -f fpga/cmac/Makefile cacc-array-test TOOL=iverilog
make -f fpga/cmac/Makefile cacc-array-test TOOL=verilator
make -f fpga/cmac/Makefile cmac-cacc-test ATOMIC_K=1 # Icarus, reduced-kernel seam check
make -f fpga/cmac/Makefile cmac-cacc-test            # Icarus, full K16
```

These modules are internal arithmetic units, not an alternative tensor-level
execution boundary. The separate raw-command candidate now joins them as
described below, but its integration validation is incomplete. Full CBUF/CSC,
host endpoint and board integration remain absent. The internal output-conversion/write connection
is described below. These modules do not change
the prior serialized C64 fixtures. Raw-command C32 integration and physical
mapping/timing remain required after the current array/seam gates pass.

## OC16 output serialization and full-width arithmetic-to-memory seam

`rtl/cmac/rk_cmac_frame_output.sv` snapshots sixteen FP32 results and a
physical output atom address. It reuses the unchanged donor converter adapter
and acknowledged writer, advancing the lane only after a successful response.
Sixteen halfwords occupy 32 bytes; the enclosing raw-command scheduler must
provide the next atom's address, including the existing 32-byte gap. Bases
remain 16-byte aligned, as in the existing raw profile, and the complete atom
must fit below the exclusive 2^32 boundary. No CPU packing is added.

`frame_done` pulses only on the sixteenth successful write response. Job
`done` additionally requires the snapshotted last-frame flag. A failed final
response cannot produce either completion, even if the memory write already
committed. Invalid addresses/data, cancellation and bus/timeout errors remain
explicit sticky faults until joint reset with the memory adapter.

The source-current **Icarus serializer test passes** 23 frames/seven jobs,
398 requests/391 acknowledgments, 12 fault cases, three cancellations and
three reset cases. It includes 17 golden frames (15 CACC reference results
plus two directed conversion-edge frames), physical gaps/sentinel checks,
base zero, the top-of-address-space atom, a 16-but-not-32-byte aligned atom,
first/middle/final response errors, both timeout phases and X rejection.
Report: `build/rknpu-frame-output/iverilog-1789994589063423630/report.json`.
The initial Verilator attempt failed on unused high bits of a testbench index.
An explicit loaded-corpus bounds check fixes that warning; the failed report
and original passing Icarus snapshot are retained. Fresh Icarus was rerun
after the bench edit; **the fresh Verilator run also passes** 23 frames,
seven jobs, 397 requests/391 acknowledgments, eight fault cases, three
cancellations and three resets. The four-state run has four additional
X-rejection cases and one extra failed request. No RTL, expected data, or
error expectation was changed for this correction. The Verilator report is
`build/rknpu-frame-output/verilator-1789994589561562261/report.json`;
both final-source reports are archived under
`verification/runs/2026-09-21-frame-output-two-sim/`.

`rtl/cmac/rk_cmac_array_datapath.sv` now connects the full C32/K16 CMAC,
K16 CACC, converter and frame writer. It propagates address/last metadata,
retains job ownership through input gaps, stops accepting after the final
reduction, and gates memory traffic on any aggregate error. Its full-width
Icarus **smoke test now passes**: six unchanged operand frames form three
output atoms (48 acknowledged writes), followed by a separate failed-final-write
test with 16 requests, 15 successful acknowledgments, error 5 and zero completions.
The **full 208-frame suite now also passes** in Icarus: 15 output atoms and
240 checked writes, followed by the same failed-final-write scenario with
16 requests, 15 acknowledgments, error 5 and zero completions. Report:
`build/rknpu-array-datapath/full-iverilog-1789995612775337330/report.json`.
The completed full-width pipeline and arithmetic-to-memory reports are archived
together under `verification/runs/2026-09-21-c32k16-cacc-datapath-full/`.
The completed smoke evidence is archived under
`verification/runs/2026-09-21-array-datapath-smoke/`.
Report: `build/rknpu-array-datapath/smoke-iverilog-1789994858539684252/report.json`.

```sh
make -f fpga/cmac/Makefile frame-output-test TOOL=iverilog
make -f fpga/cmac/Makefile frame-output-test TOOL=verilator
make -f fpga/cmac/Makefile array-datapath-test SUITE=smoke
make -f fpga/cmac/Makefile array-datapath-test # full suite
```

The new datapath is now connected to the raw-command-driven C32/K16 operand
assembler in a separate core whose integration test is running, as described
below. It has not replaced the existing serialized C64 core,
and its direct testbench inputs are unit stimuli, not a new host execution
API. The root `make test` does not cover these nested new units. Its fresh
production regression completed successfully at unchanged production source
identity `09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`;
the final Icarus raw-product report completed at 2026-09-21 12:57:13 UTC.
`make generated-check` was also rerun successfully after the new unit edits.
None of these tests establish routed timing, FPGA operation or RK equality.

## Raw-command frame assembly and memory arbitration

`rtl/cmac/rk_cmac_array_front.sv` accepts final 64-bit command words through
the unchanged strict `rk_cmac_profile` decoder. It assembles each C32/K16 frame
from 32 physical input reads and 512 physical weight reads, walking row,
OC16 block, then IC32 group. It supplies first/last-reduction flags and the
physical output atom address without rewriting raw commands or runtime host
packing. A complete stalled frame remains stable. `stream_done` means only
that the final input frame transferred, not that output memory completed.

`tools/cmac/gen_array_front_vectors.py` independently regroups the existing
physical-address oracle for seven unchanged real-encoder command fixtures:
76 frames and 41,344 halfword reads. It verifies all 49 command words and their
captured SHA256 before use. Operand bytes are synthetic, not RK observations.
The source-current Icarus run passes 13 successful replays, 14 memory-fault
cases, five reset phases, three cancellations and three profile rejections;
109 frames are checked including recovery/repeated runs, seed `0x3588af16`.
Report: `build/rknpu-array-front/iverilog-1789996087539663840/report.json`.
The first Verilator attempt rejected testbench integer-as-boolean and duplicate
initialization warnings. Those were corrected explicitly; no RTL, oracle or
error expectation changed. The prior Icarus snapshot remains archived under
`verification/runs/2026-09-21-array-front-initial/`; the fresh Icarus evidence is
under `verification/runs/2026-09-21-array-front-iverilog-final/`.
**Fresh Verilator 5.048 also passes** 13 good replays, ten memory-fault cases,
five reset phases, three cancellations, three profile rejections and 109
checked frames. Its four fewer fault cases are native-X tests. Report:
`build/rknpu-array-front/verilator-1789996089308911655/report.json`.
Both final-source runs are archived together under
`verification/runs/2026-09-21-array-front-two-sim/`.

`rtl/cmac/rk_cmac_rw_arbiter.sv` supplies one-outstanding fair read/write
arbitration for the new connected raw core. It snapshots a request before
exposing it to memory, holds its owner through stalls and the response, and
alternates when both clients request. Cancellation is sticky; an unsolicited
response fails explicitly. Reader/writer timeouts must cancel the enclosing
core; the arbiter does not add a second timeout policy. The standalone bench
checks 36 transfers, 16 fair pairs, stalled-write ownership, three cancellation
phases and an unsolicited-response fault. **Both source-bound simulator runs
now pass**, with strict Verilator lint and no warning waivers:
`build/rknpu-rw-arbiter/iverilog-1789996476698377636/report.json` and
`build/rknpu-rw-arbiter/verilator-1789996478142699789/report.json`.
They are archived under `verification/runs/2026-09-21-cmac-rw-arbiter-two-sim/`.
Both modules are now connected in the new candidate described below; the
standalone passes do not establish that connection's correctness.

```sh
make -f fpga/cmac/Makefile array-front-test TOOL=iverilog
make -f fpga/cmac/Makefile array-front-test TOOL=verilator
make -f fpga/cmac/Makefile rw-arbiter-test TOOL=iverilog
make -f fpga/cmac/Makefile rw-arbiter-test TOOL=verilator
```

## Connected C32/K16 raw-command candidate

`rtl/cmac/rk_cmac_array_core.sv` joins the unchanged strict terminal profile,
physical operand assembler, full C32/K16 datapath and fair one-outstanding
memory arbiter. The public execution input is only final 64-bit RK words;
the output is the existing halfword memory request/response interface.
It blocks new commands until the active job drains and propagates child
faults through a registered cancellation path, while immediately gating all
handshakes on error. Job completion is the final successful output-write
response, never the input assembler's `stream_done` pulse. An unexpected
read request from the output-only writer is an explicit internal fault.

`tools/cmac/gen_array_core_vectors.py` preserves all seven original command
images and their static synthetic operand bytes, and generates new C32—not
old C64—numerical goldens. A further K=65 finite-valued physical operand case
retains the same command words and exercises three-group accumulation with
64 distinct finite outputs. These are test inputs, not runtime host fixups.
The corpus has 88 C32/K16 frames, 1,408 CMAC groups and 1,088 output halfwords.
It uses the executed NVIDIA Booth helper and the independently tested dyadic
CACC policy. Its converter extraction was checked against all 272 existing
frame-output goldens before use. No earlier expected-output file was edited.

`tools/cmac/check_array_core_model.py` executes the already source-pinned
original full `NvdlaMacCell` SystemC model on these physical operands.
**All 1,408 group values pass with zero mismatches** at
`build/rknpu-array-core/model-1789997372644957885/report.json`.
This is a newly executed check of the new corpus, not a copied prior result;
the report retains the exact reused executable, its source and SystemC provenance.
It verifies only the CMAC reference values, not connected RTL or final writes.
The new execution evidence and its exact dependencies are archived under
`verification/runs/2026-09-21-array-core-cmac-model/`.

The new raw-core Icarus bench checks every physical read and numerical write,
preserves output gaps, delays the final write response, and tests first-read
error, final-write error, both memory timeout phases, cancellation, unknown
read data, unsupported commands and (full suite) reset recovery. The smoke
suite replays one unchanged two-row fixture plus seven fault cases; the full
suite replays all eight operand cases plus reset recovery. Compilation passed
without warnings. Its first numerical smoke replay now passes: 2,176 checked
physical reads, 64 numerical writes, 64 acknowledgments and one job completion
for `m2_n17_k31`, seed `0x3588ac16`. The subsequent first-read-error and
final-write-error cases also pass. The latter checks 2,176 reads, 64 writes,
only 63 successful acknowledgments and zero job completions. All eight smoke
cases now pass, including both timeout phases, cancellation, unsupported raw
target and unknown read data:
`build/rknpu-array-core/smoke-iverilog-1789997236682288790/report.json`.
The completed source-bound archive is
`verification/runs/2026-09-21-array-core-smoke/` (252 verified members).
This is one successful raw-core numerical case plus seven faults, not a complete regression,
full CBUF/CSC, DMA/host integration or FPGA result.

`tools/cmac/replay_array_core.py` can reuse the completed, source-matching
Icarus compile without repeating elaboration. It snapshots the parent report
and pins the binary and all RTL/bench/vector dependencies, but runs every
selected simulation afresh. Its `protocol` suite separately checks the six
early read-error/timeout/cancel/unsupported-command/X scenarios, without
waiting behind a numerical job. This is additional early integration evidence,
not a substitute for the pending successful-output and final-write-fault tests.
The completed protocol run is at
`build/rknpu-array-core/replay-protocol-1789997968220387664/report.json`.
**All six cases pass**: first-read bus error, request timeout, response timeout,
cancellation, unsupported raw command and unknown read data. Each checks its
expected sticky error and absence of output writes/job completion. The
source-bound archive is `verification/runs/2026-09-21-array-core-protocol/`.
This protocol-only result does not include a successful numerical job or the
final-write error. A separate
30-second verbose diagnostic was stopped at its wall-clock limit without
output and supplies no pass/fail evidence about the DUT; the main runs were
not interrupted or restarted.
The `finite` option now passes the complete K65 finite replay at
`build/rknpu-array-core/replay-finite-1789999512347772900/report.json`:
6,528 checked operand reads, 64 numerical writes/acknowledgments and one
completed job, seed `3588ac16`. This exercises three C32 reduction groups,
not the old C64 grouping. `full` runs all cases and faults and remains unrun.

```sh
make -f fpga/cmac/Makefile array-core-test SUITE=smoke
make -f fpga/cmac/Makefile array-core-test # full suite, not yet run
make -f fpga/cmac/Makefile array-core-model
make -f fpga/cmac/Makefile array-core-replay SUITE=protocol \
  COMPILED_REPORT=build/rknpu-array-core/smoke-iverilog-<run>/report.json
```

## C32/K16 command-DMA candidate

`rtl/cmac/rk_cmac_array_dma.sv` now connects the new raw core to physical
command-buffer fetch. It derives the bounded descriptor/framing controller
from the existing serialized-core DMA without changing that older module.
The descriptor amount remains **45 body QWORDs**; the fetcher reads all
49 final QWORDs (196 little-endian halfword responses), checks the four tail
keys in order, and forwards the exact words into `rk_cmac_array_core`.
Wrong amounts, misalignment, command-buffer endpoint overflow, premature or
misordered tails, profile errors, memory errors and timeouts remain sticky
failures. It neither executes tensor operations directly nor repacks operands.

Command fetch owns the shared memory interface until the final trigger is
accepted. The numerical core then owns it through the final output response.
`acknowledged`, `frame_done` and job `done` retain the core's successful-write
semantics; fetching or forwarding the last command is not job completion.
DMA faults also cancel the child core. Joint reset with the memory adapter is
required after a fault. This remains a single terminal job, not EW chaining,
full PC scheduling, PCIe/DDR transport or host-driver integration.

`tests/cmac/tb_cmac_array_dma.sv` checks every command fetch address and
forwarded word, then uses the unchanged C32 physical read/write corpus. It
checks output gaps, delayed final-write completion, command/data memory
faults, descriptor/tail/profile rejection and command/operand reset recovery.
`tools/cmac/test_array_dma.py` records exact sources, fixtures and seed
`0x3588ad16`. The first smoke run compiled without warnings at
`build/rknpu-array-dma/smoke-iverilog-1790000569138071924/report.json`.
Its wrong-body-count test passes with zero command or operand memory access;
unknown raw target rejection also passes after four command reads and one
forwarded word, without operand reads or output writes. The numerical replay
now also passes: 196 command reads, all 49 unchanged words, 2,176 operand reads,
64 numerical writes, 64 acknowledgments and one completed job. The final-write
error case also passes: the same 196 command reads, 49 words, 2,176 operand
reads and 64 write requests, but only 63 successful acknowledgments and zero
completed jobs. All four DMA smoke cases now pass. Full numerical-corpus and
reset-recovery regression remains unrun; this is not full DMA signoff.

`tools/cmac/replay_array_dma.py` reuses only the completed, source-matching
compile and executes selected cases afresh. The twelve-case descriptor,
framing, profile and early-memory-fault suite has started at
`build/rknpu-array-dma/replay-protocol-1790001034170399719/report.json`.
It preserves the original binary/sources and records a snapshot of the parent
report. Its protocol-only status cannot establish numerical output, reset
recovery or final-write-error coverage. Those remain separate tests. All twelve
cases now pass: operand error, command request/response timeout, command bus
error, unknown raw target, premature trigger, unknown command data/status,
wrong amount, misalignment, command endpoint overflow and swapped tail keys.
Each verifies its exact fetch/forward count and zero output writes/completions.
The completed source-bound evidence is archived under
`verification/runs/2026-09-21-array-dma-protocol/` (258 verified members).

```sh
make -f fpga/cmac/Makefile array-dma-test SUITE=smoke
make -f fpga/cmac/Makefile array-dma-test SUITE=protocol
make -f fpga/cmac/Makefile array-dma-test SUITE=full
make -f fpga/cmac/Makefile array-dma-replay SUITE=protocol \
  COMPILED_REPORT=build/rknpu-array-dma/smoke-iverilog-<run>/report.json
```

## C32/K16 AXI endpoint candidate

`rtl/cmac/rk_cmac_array_axi.sv` connects the new DMA/numerical path to the
existing `rk_cmac_job_control` and `rk_cmac_axi_mem` helpers. This is a separate
candidate top, not a substitution into the older C64 endpoint, production EW
top or board source manifest. Descriptor address/body amount/tag are submitted
through AXI-Lite; the hardware fetches all 49 final RK QWORDs from AXI RAM.
The RKCM transport identity and version remain `0x524b434d`/`0x00010000`, with
body amount 45 and one terminal task. That version identifies the descriptor
ABI, not a runtime geometry-discovery interface or established RK equivalence.

The memory contract remains one halfword request per aligned 512-bit RAM beat,
two asserted write byte strobes, and completion only after the final successful
B response. The 31-bit external address interface explicitly rejects device
addresses with bit 31 set rather than truncating them. Ordinary RAM covering
the entire read beat is required; this is not an MMIO adapter. Single-clock
operation and joint reset of the core, adapter and downstream transaction
state are required; reset does not roll back completed writes. No PCIe, MIG,
CDC, ECC recovery, host driver or runtime CPU fixup is introduced.

`tests/cmac/tb_cmac_array_axi.sv` submits jobs only through public AXI-Lite
ports and uses an independently stalled behavioral AXI RAM. It retains
AW/W/AR stability checks, response ordering, transport attributes, IRQ/result
ownership, memory-admission rejection, repeated jobs, partial-write reset,
early/final bus errors and request/response timeouts. New explicit fault
transaction-count checks distinguish rejection before bus access from errors
after the first or last transferred write. Seed is `0x3588ae16`.

`tools/cmac/test_array_axi.py` assembles test RAM images from the existing
source-pinned **C32** physical operands and numerical write corpus. It does
not use older C64 output goldens, recompute arithmetic, change command words,
or repack operands. All eight cases pass the preparation consistency checks:
exact command-byte SHA, physical input/weight lengths, every oracle read,
unique output addresses, output gaps and 64-byte boundary guards. This is
test-image validation, not an RTL pass. Successful simulation must return
every checked RAM halfword unchanged or equal to its saved numerical golden.

The first full-width Icarus smoke run is at
`build/rknpu-array-axi/smoke-iverilog-1790001647450457731/report.json`.
Compilation passed without warnings. Descriptor misalignment passes with no
AXI memory transactions; unknown raw target passes after exactly four AXI
reads and no writes. Numerical replay now passes through public AXI-Lite/AXI
ports, including status/tag/task/IRQ and the complete checked memory image,
seed `3588ae16`. All three smoke cases pass, not the full integration suite.
The six-case protocol suite now passes at
`build/rknpu-array-axi/protocol-iverilog-1790005004996448438/report.json`:
read error, read-response timeout, read-address timeout, unaligned descriptor,
unsupported raw target and bit-31 address rejection. Each keeps the expected
error and access-count checks; no successful output is inferred from a fault
test. Full numerical-corpus, write-fault and reset/repeat coverage remains unrun.
The smoke suite checks descriptor misalignment, unknown raw target and one
complete numerical job. `protocol` checks six early faults; `full` requests
all eight numerical fixtures, ten fault/reset cases and a repeated job.

`tools/cmac/test_array_axi_hier.py` now runs that same full 19-case bench using
the source-verified library from the passing full CMAC regression. It reuses
the exact checked test RAM images; it neither regenerates raw command words
nor computes runtime results. It pins the completed Icarus smoke report,
CMAC report and CACC/output donor-warning baselines. Only testbench-local
blocking-assignment warnings and exact previously recorded donor locations
are accepted; DUT warnings outside those baselines fail. Top generation must
show actual library calls and no embedded donor multiplier classes before
compilation begins. Each successful job still requires complete checked-memory
equality, and every fault retains the existing status/transaction expectations.

The original unoptimized full run is
`build/rknpu-array-axi/full-hierarchical-1790007099041360032/report.json`:
generation, library-use checks and C++ compilation passed. Its first numerical
case was manually stopped with SIGTERM after 2,809.281 seconds once the optimized
run below passed that case. The original report records FAIL, return code -15,
and zero completed tests; it is not numerical evidence. Its earlier
attempt remains failed at `full-hierarchical-1790007048706080687` because the
runner initially omitted the donor multiplier's already-recorded filename
diagnostic; the retry imports that exact location from the passing CMAC report.
No RTL, command, golden or fault expectation changed. That failed attempt
provides no full AXI pass.

The same unchanged runner and full corpus completed with the passing
optimized-host CMAC library at
`build/rknpu-array-axi/full-hierarchical-1790008635729125119/report.json`.
The terminal report, inspected on 2026-10-05, is
`PASS_RAW_ARRAY_AXI_FULL_HIERARCHICAL_ONLY`: all 19 cases pass, comprising
eight numerical fixtures, ten faults and the repeated-job test. Public
status/tag/task/IRQ checks and complete saved memory-image comparisons remain
enabled. This is actual two-state integration evidence, not a pass inferred
from the CMAC unit, four-state coverage or a physical FPGA result. Earlier
failed attempts above remain separate and unchanged.
The completed source-bound archive is
`verification/runs/2026-10-05-array-axi-full-hierarchical/`: 1,850 verified
members, 126,142,052 bytes, SHA256
`049931b2ff0abe08dd04151a7b0a9dc0ec939265f62daab68caebf41c9f9261c`.

```sh
make -f fpga/cmac/Makefile array-axi-test SUITE=smoke
make -f fpga/cmac/Makefile array-axi-test SUITE=protocol
make -f fpga/cmac/Makefile array-axi-test SUITE=full
```

## Isolated fixed-FP16 partial-row experiment

`rtl/cmac/experimental/rk_cmac_fp16_rows.sv` specializes the pinned donor's
FP16 branch without replacing the running C32/K16 baseline. Source evidence
is `NV_NVDLA_CMAC_CORE_MAC_mul.v`: mode registers at lines 100..204,
radix-4 recoding at 325..448, unchanged carry-save tree inputs/reduction at
456..578, and separate row shifts/output gating at 588..669. The new module
retains the original Booth helper and all three original carry-save tree
instances; it does not replace the rows with IEEE or inferred multiplication.
It is derived NVIDIA-licensed source, not an unrelated arithmetic model.

The contract is sign plus pre-shifted magnitude inputs, paired nz masks,
permanently valid operands and fixed FP16 mode. It is not a raw-binary16 ALU.
Both 32-bit rows and their 8-bit sign tag must match after the donor's one-clock
configuration warmup. The existing array's `configured`/ready gate must remain
if this experiment is ever integrated. Pre-configuration behavior is different
and explicitly outside the comparison; no array integration is claimed.

`tools/cmac/test_fixed_fp16_rows.py` now composes a three-step configuration
proof with an arbitrary-operand combinational row proof. Reset/setup must prove
`active=1`, all four donor FP16 mode bits set and its INT8 bit clear before
those constants may be propagated into the second proof. No operand, mask,
shift, row, tag or comparison output is assumed. Its RTL
bench separately sweeps all 65,536 first-operand encodings, deterministic
second operands, all sixteen shifts and both paired-mask states: 2,097,152
row/tag comparisons, four reset/setup sequences, seed `3588f016`.
The first run at
`build/rknpu-fixed-fp16-rows/verilator-1790012655634768662/report.json`
is preserved as FAIL: its formal subprocess was deliberately stopped with
SIGTERM (-15, 435.917 seconds) after an independent lint check found the
bench clock's declaration-initialization warning. It produced no proof or
counterexample. Only that owned process was stopped. Moving clock
initialization into an initial statement fixes the bench diagnostic without
changing the experimental RTL, oracle or comparison expectations.
The subsequent run is preserved at
`build/rknpu-fixed-fp16-rows/verilator-1790013115817944133/report.json`.
The runner now compiles and simulates before the formal step, so bench
failures are detected first. Compilation passes in 165.178 seconds and
Verilator 5.048 simulation passes in 40.495 seconds: all 2,097,152 row/tag
comparisons and four reset/setup sequences match the unmodified donor, seed
`3588f016`, source manifest
`48712cb50d130479fbae92dadac9b6c27f7389f84a56034c0dc9754a35048880`.
Its original combined formal step timed out at 7,200 seconds, so the overall
report is FAIL despite the completed simulation. It produced no proof or
counterexample. The new composed run is
`build/rknpu-fixed-fp16-rows/verilator-1791205650993616772/report.json`.
Its unchanged simulation passes all 2,097,152 comparisons and four reset/setup
sequences (Verilator 5.048, seed `3588f016`). The configuration/nonvacuity lemma
passes in 17.149 seconds. Its word-level datapath subprocess was stopped with
SIGTERM after a separate boolean-lowered diagnostic completed the same proof;
the original overall report is preserved as FAIL. The fresh source-bound
runner at `build/rknpu-fixed-fp16-rows/verilator-1791207221389481729/report.json`
adds `techmap; opt -full; check -assert` before the same SAT comparison,
transforming both sides and adding no assumptions. It reruns the unchanged
simulation and both proofs. That fresh run now completes with
`PASS_FIXED_FP16_ROWS_EXPERIMENT_ONLY`, source manifest
`f4b75c99987b5d67da76f3281270a25ea2f07451a8096aa57220dad9da8fdaa8`:
Verilator 5.048 simulation passes all 2,097,152 comparisons and four resets in
119.305 seconds, with seed `3588f016`. Yosys 0.65 (commit
`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`) reports SAT SUCCESS for the
configuration/nonvacuity lemma (50.634 seconds) and the arbitrary-operand
post-configuration datapath comparison (90.593 seconds). The composed result
is `PASS_COMPOSED_POST_CONFIGURATION_ROWS_AND_ACTIVE_COMPARE`, not reset-cycle,
full-array or physical FPGA equivalence. This specialization changes no active
baseline source or numerical golden.
The completed 26-member proof archive is
`verification/runs/2026-10-05-fixed-fp16-composed-proof/`, SHA256
`a8c81bd5d9e42543fd2037e523de7dfc76ab5c84cde4f4730c1017516588f574`.

`tools/cmac/map_fp16_rows.py` characterizes the original and specialized
partial-row helpers with identical sign/magnitude, shift and paired-mask
inputs. It uses the same installed XC7 synthesis stages, omitting only the
optional SAT `share` pass, and requires eight retained Booth instances before
mapping each variant. Primitive-aware counting and output-presence checks
remain enabled. Its separate area-only run passes at
`build/rknpu-fixed-fp16-rows/area-1790013401846001242/report.json`.
The original helper maps to 937 LUT1..6, 356 MUXF7, 117 MUXF8 and one FDCE;
the fixed helper maps to 668 LUT1..6, 201 MUXF7, 25 MUXF8 and no flip-flops.
Neither uses DSP48E1. This is 269 fewer LUT primitives (28.7%) for the
unconstrained single-helper comparison, not a projected full-array fit.
Yosys 0.65 took 151.752 seconds for the original and 137.860 seconds for the
fixed variant, with source manifest
`155cd6157299f409ffbbfa2e9cee048b7c28425c9fc9b765c6b11e676aeff71c`.
The 23-member area-only archive is
`verification/runs/2026-09-22-fixed-fp16-row-area/`, SHA256
`af77e56aa53bed9aeedc2744df688cfffdda7e69ac6897b39bf9c58eb2f73554`.
The static variant's post-setup contract is explicit; its unused clock/reset
pins are not evidence of reset-cycle equivalence. No full-array resource
saving, numerical mapping pass or physical fit follows from this experiment.

Two separate experimental modules, `rk_cmac_fp16_cell_fixed.sv` and
`rk_cmac_fp16_array_fixed.sv`, now connect that helper at full C32/K16 size.
`tools/cmac/test_fixed_array.py` checks their entire text against the baseline
with only the reviewed helper/module/unused-clock-port substitutions. Weight
and data operand order, NaN priority, FP44 compensation/reduction, configured
warmup, handshake, tags, reset and error logic are unchanged. The original
unit bench changes only its DUT module name: all 208 frames, 3,328 expected
outputs, hold cycles and reset-cancellation assertions are retained.

The initial hierarchical native experiment is preserved as FAIL at
`build/rknpu-cmac-array/c32k16/fixed-hierarchical-1790013991731455943/report.json`,
source manifest
`1e8a0e5cfa7f6cdeffd18f988236af374e56025aa9d367ad9b6a6a1e4aafc27f`.
Its fresh cell compilation passed, but top generation stopped on an unused
`last_combo_seqnum__V` timestamp in Verilator 5.048's generated combinational
protectlib wrapper, not an arithmetic mismatch. The new runner accepts only
that exact generated-wrapper diagnostic/line; DUT warnings retain their
original gates. It now requires a completed source-matching row simulation
and formal PASS before starting, not a RUNNING parent. Host C++ still uses
`-O2`; actual library calls, absence of embedded donor arithmetic and the full
unchanged corpus remain mandatory. It is not yet a replacement for the original
array or a raw-path, mapped numerical or physical signoff result.
The fresh full-array native run, started only after the composed row proof
completed, is
`build/rknpu-cmac-array/c32k16/fixed-hierarchical-1791208877880399503/report.json`.
It now completes with `PASS_FIXED_MODE_CMAC_NATIVE_EXPERIMENT_ONLY`, source
`99d2995a83400a902a0997772632cf4a7c9ba3c040a2cc9a20b9b0cc51054dfa`.
Verilator 5.048 and GCC 16.2.1 build the real combinational library/top and
pass all 208 frames, 3,328 checked outputs, 3,312 retired outputs, sixteen
reset-canceled outputs and 520 held cycles, with zero faults. Simulation takes
33.460 seconds; no assertion, golden, ready/reset gate or arithmetic was
changed. The old failed report remains separate. This is native two-state
full-array evidence, not raw integration, mapped arithmetic or physical fit.
Its completed source-bound archive is
`verification/runs/2026-10-05-fixed-c32k16-native/`, with 1,363 verified members
and SHA256 `d0830483825d90eeda6bfb2dc379937000648ed3d7cfc426b7e54d9848457fc8`.

An independent mapped-helper numerical gate was launched at
`build/rknpu-fixed-fp16-rows/mapped-iverilog-1791212868241216795/report.json`,
source `7d440d0e78018090fe2d56cf265392718ef33ab00d3740000f0d989e98cf66fc`.
`tools/cmac/test_fixed_rows_mapped.py` verifies the completed helper area and
native/composed-proof manifests, checks the mapped primitive counts and
replays the actual `fixed_mapped.v` against original NVIDIA RTL. It uses the
unmodified Xilinx functional primitive models and default GSR. A generated
copy of the original row bench changes only its name, DUT instance, PASS
marker, external input initialization at 1 ns and a 200 ns startup wait.
The first attempt at
`build/rknpu-fixed-fp16-rows/mapped-iverilog-1791212639598868648/report.json`
remains FAIL on unknown primitive outputs at its first comparison with
declaration-time initialization. The fresh run drives external inputs after
primitive initialization, without changing the netlist, vendor models or
comparison expectations. Five harness-only control methods pass in
`build/fixed_rows_mapped_controls_20261005.log`.
All 2,097,152 comparisons, all operand and
alignment/mask sweeps, four reset/setup calls and seed `3588f016` remain.
No completed mapped PASS is claimed yet. This isolated helper gate is not
full-array netlist correctness, routed timing/SDF, physical fit or FPGA/RK
acceptance; the original full-array mapped timeout remains a failure.
The supervisor session 50087 ended with SIGTERM/exit 143 on the 2026-10-06
inspection while its exact vvp child, PID 351851, remained live under PID 1.
The original report's RUNNING field is stale supervisory state, not acceptance.
The child and a read-only GDB 17.2 exit observer were last confirmed live
before the managed PID-namespace transition. The observer log is
`build/mapped_rows_orphan_gdb_20261006.log`; no terminal inferior status was
recorded. Old tool handles are now unavailable and host PIDs are hidden, which
does not establish that either job stopped. No restart or final simulator exit
code/mapped PASS is inferred from that observation failure or partial logs.

```sh
make -f fpga/cmac/Makefile cmac-fixed-rows-mapped-test \
  AREA_REPORT=build/rknpu-fixed-fp16-rows/area-1790013401846001242/report.json \
  ROWS_REPORT=build/rknpu-fixed-fp16-rows/verilator-1791207221389481729/report.json
```

`tools/cmac/prove_fixed_rows_mapped.py` separately checks the actual same
mapped helper against unchanged experimental row RTL with symbolic binary
inputs. All 37 operand/shift/paired-nz bits are free; both 32-bit rows and the
8-bit tag are compared individually, not replaced by their compensated sum.
The composed donor configuration/datapath proof is a mandatory source-matching
parent. Actual LUT/MUX definitions are copied unchanged from installed Yosys,
including their license, and flattened as functional logic, not blackboxes.
Boolean graph gates reject state, assumptions, unmodeled cells, changed input
widths/constants, coupled input variables and truncated comparisons or outputs.
A deliberately flipped comparison tag bit must produce a real SAT countermodel
before the actual proof runs. No input values are assumed and no accelerator
RTL/netlist is modified.

The first attempt remains FAIL at
`build/rknpu-fixed-fp16-rows/mapped-formal-1791218249659797216/report.json`,
before SAT: Yosys retains unused library/ABC-placeholder definitions and its
final `opt_share` creates seventeen word-level `$mux` cells. The corrected
runner specifically lowers those MUXes, exports only the unchanged comparison
module and retains the strict cell whitelist. An instantiated arithmetic
blackbox/unknown cell would still fail. Eight synthetic safety methods pass in
`build/mapped_rows_formal_controls_strict_graph_20261006.log`; they are not
the symbolic result. The fresh real run now completes at
`build/rknpu-fixed-fp16-rows/mapped-formal-1791218804185727590/report.json`.
It reports `PASS_MAPPED_FIXED_FP16_ROWS_BINARY_FORMAL_ONLY`, source SHA256
`fba405afef9b283d7edb70caed72f5f77d564dd8b278e288965ccabea276c99b`,
Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`). The real negative
SAT check finds a countermodel in 14.268 seconds, and the actual comparison
proves all 72 output bits over all 37 relevant binary inputs in 19.684 seconds.
The completed archive is
`verification/runs/2026-10-06-mapped-fp16-helper-binary-proof/`, with 64 verified
members and SHA256 `2c3b76f3c1bacdf005119296fec3d3101eece4562ce814bc81ee8ffe2b2f961e`.
This binary proof cannot replace the incomplete vendor-model
four-state corpus, validate startup/GSR, or establish full-array numerical,
RK special-value or physical FPGA timing/DRC acceptance.

```sh
make -f fpga/cmac/Makefile cmac-fixed-rows-formal-control-test
make -f fpga/cmac/Makefile cmac-fixed-rows-mapped-formal \
  AREA_REPORT=build/rknpu-fixed-fp16-rows/area-1790013401846001242/report.json \
  ROWS_REPORT=build/rknpu-fixed-fp16-rows/verilator-1791207221389481729/report.json
```

A separate full binary mapped replay is now implemented by
`tools/cmac/test_fixed_mapped_array.py`. It requires completed current full-CMAC
area and full fixed-array native evidence, preserves the actual mapped C32
kernel and every top-shell circuit bit, and instantiates all sixteen kernels.
The JSON-to-Verilog export only aliases kernel and hardware-instance names; no arithmetic
RTL or blackbox substitutes for the partition. The original 208-frame bench,
all 3,328 checked/3,312 retired/16 reset-canceled outputs and 520 held cycles
are required. A single flipped first-frame golden bit must cause a real
numerical assertion failure before the untouched corpus executes.
Eight initial synthetic safety methods pass in
`build/fixed_mapped_array_controls_20261006.log`; fifteen current export/parameter
methods pass in `build/fixed_mapped_array_instance_alias_controls_20261006.log`.
The first actual attempt at
`build/rknpu-cmac-array/c32k16/fixed-mapped-binary-1791221355297301197/`
was intentionally interrupted after its export exposed undriven unused debug
aliases (session 97587, exit 130), before any arithmetic result. Its unchanged
report/logs and separate `interruption_audit.json` are retained, not a PASS.
The corrected structural exporter emits only existing mapped cells and bit
wires; a real Yosys roundtrip must preserve every circuit endpoint connection,
cell type/parameter, module default and port bit. No hardware cell is pruned or
replaced. The second real attempt remains FAIL at
`build/rknpu-cmac-array/c32k16/fixed-mapped-binary-1791222379477890874/report.json`:
its exporter incorrectly rejects the kernel's actual constant-zero `invalid`
output. That output is now preserved literally, not repaired; input constraints
remain forbidden. Only known Yosys `$scopeinfo` debug metadata (384 cells here)
is omitted, matching the existing primitive counter. A third attempt remains
FAIL at `build/rknpu-cmac-array/c32k16/fixed-mapped-binary-1791222742341384170/report.json`:
real Yosys re-reads private `$abc...` names as escaped user identifiers, and the
strict circuit comparison rejects that namespace mismatch. Explicit reversible
instance aliases, with the full bijection recorded, address only those names;
the circuit verifier does not normalize or merge them. The fresh run is
`build/rknpu-cmac-array/c32k16/fixed-mapped-binary-1791223429684393546/report.json`,
driver `build/fixed_mapped_array_instance_alias_driver_20261006.log`, not yet a numerical PASS.
Its actual Yosys export roundtrip now passes full circuit identity at source
`c77e1ad4c53c6bdc4556184e52c95290ef48a04ac8222d5f957ee4ba88c69c7d`;
the mapped C32 library was last observed compiling before the managed
PID-namespace transition. Its old host handle is no longer observable;
its report remains incomplete, not evidence of a stopped job. The 208-frame arithmetic test is still
required, and no full mapped numerical acceptance is inferred from this gate.
The unchanged installed Yosys primitive model is used with Verilator, so this
is explicitly binary functional mapping, not UNISIM GSR/four-state, exhaustive
array equivalence, raw-board replay or physical timing/DRC acceptance.
Ignored specify/unnamed-generate diagnostics are accepted only as immutable
functional-model metadata and recorded explicitly, never as timing evidence.
Undriven/width/latch/unmodeled diagnostics remain failures; physical build gates
and numerical/error/hold/reset assertions are unchanged.

```sh
make -f fpga/cmac/Makefile cmac-fixed-mapped-control-test
make -f fpga/cmac/Makefile cmac-fixed-mapped-test \
  AREA_REPORT=build/rknpu-cmac-array/c32k16/fixed-area-1791207358609699523/report.json \
  FIXED_REPORT=build/rknpu-cmac-array/c32k16/fixed-hierarchical-1791208877880399503/report.json
```

`tools/cmac/test_fixed_array_board.py` prepares the next raw-command integration
gate without editing the original array, board bench or ROM. It requires a
completed source-matching full fixed-array native PASS, the composed proof
snapshot, all original 208 frames/3,328 outputs, verified library calls, and the
completed original nine-mode board report. It generates a source-bound copy of
`rk_cmac_cacc_fp16_array.sv` with exactly one changed instance type:
`rk_cmac_fp16_array` becomes `rk_cmac_fp16_array_fixed`. The decoder, DMA,
CACC, output conversion/writes, BRAM, reset/LED logic and full RAM oracle are
unchanged. Icarus runs all nine modes; Verilator runs modes 0..6 and 8 with the
verified combinational CMAC library. Mode 7 remains four-state only.

The nine runner-control methods pass at
`build/rknpu-fixed-board-control/1791209463136018270/report.json`.
These are synthetic Python control fixtures, not HDL evidence. They check the
single substitution, source list, full transaction/readback counts, watchdog
boundaries, source/artifact hashes, completed native/proof metadata and exact
warning locations. An actual invocation with the still-RUNNING native parent
fails before creating an integration directory or launching HDL tools; its log
is `build/fixed_board_running_parent_rejection_20261005.log`. After the native
PASS, fresh raw-board runs start at
`build/rknpu-fixed-array-board/verilator-1791210829751522794/report.json` and
`build/rknpu-fixed-array-board/iverilog-1791210828043361091/report.json`.
The Verilator run now completes with
`PASS_FIXED_RAW_ARRAY_BOARD_TWO_STATE_HIERARCHICAL_EXPERIMENT_ONLY`, source
`6eb8d1d22ff6af849e2b98b0f7384052ca8571283e8030202c5dfdae3e4ec7fd`.
All eight modes 0..6 and 8 pass under Verilator 5.048/GCC 16.2.1, including
complete K65 RAM readback, reset during command/frame/readback, repeat after
success, command/readback faults and watchdog expiry. The Icarus report
records modes 0..6 passing and mode 7 RUNNING. Its supervisor/simulator were
last confirmed live before the managed PID-namespace transition; current host
liveness and completion cannot be established here. No restart or completed
nine-case four-state result is inferred. The completed
two-state evidence is frozen in
`verification/runs/2026-10-05-fixed-array-board-two-state/`: 1,731 verified
members, 96,844,787 archive bytes, SHA256
`a5fb49ef516bc13083b73e226fbfa668d3c80ca689510ed31a8db82542774673`.
The experimental
statuses deliberately cannot satisfy the unchanged baseline Vivado build gate.

```sh
make -f fpga/cmac/Makefile array-fixed-board-test TOOL=verilator \
  FIXED_REPORT=build/rknpu-cmac-array/c32k16/fixed-hierarchical-<run>/report.json \
  BOARD_REPORT=build/rknpu-array-board/full-iverilog-1790008149115028405/report.json \
  CACC_REPORT=build/rknpu-cacc-array/c32k16/verilator-<run>/report.json \
  OUTPUT_REPORT=build/rknpu-frame-output/verilator-<run>/report.json
# Repeat with TOOL=iverilog for all nine four-state modes.
```

### Separate fixed-mode physical-build preparation

`tools/cmac/vivado_fixed_array.py` uses the unchanged checkpoint Tcl and
electrical/timing/DRC gates. It generates only the single audited internal
CMAC instance substitution, and the synthesis list selects the experimental
rows/cell/array. Raw decoder, DMA, CACC/output, board ROM, RAM, pins, part and
20 ns clock are unchanged. `prepare` is source packaging only, at
`build/rknpu-fixed-array-vivado/prepare-1791210251059099091/report.json`
(`PREPARED_FIXED_ARRAY_VIVADO_ONLY`); no HDL or Vivado runs in that action.

`run` requires this fixed variant's completed native/proof report and **all
nine fixed-mode Icarus board modes**. It rejects the original array's full
board PASS as well as two-state, incomplete, stale or mismatched evidence.
It checks original/generated source lists, full RAM and transaction counts,
the native snapshot actually used by the board test, and all source/artifact
hashes. A successful implementation would have the distinct status
`ROUTED_FIXED_ARRAY_CHECKPOINT_REVIEW_REQUIRED`; no implementation has run.

The shared reviewed-checkpoint emitter now dispatches explicitly between
baseline and fixed source profiles. The fixed branch revalidates both native
and nine-mode board evidence and their implementation snapshots. Cross-profile
statuses cannot authorize emission, and all existing physical checks and
explicit human review requirements remain. A real fixed prepare report was
correctly rejected before any emission directory/tool was created; log:
`build/fixed_bitstream_prepare_rejection_20261005.log`.

Fresh source-bound mocked controls pass under Tcl 9.0.3 and Xilinx Tcl 8.6.13:
eighteen methods each at
`build/rknpu-fixed-array-build-control/1791210538916975755/report.json`, and
eleven emitter methods each at
`build/rknpu-bitstream-emitter-control/1791210538182242952/report.json`.
Their combined 25-member archive is
`verification/runs/2026-10-05-fixed-build-and-emitter-controls/`, SHA256
`822ef11df1a29105d19b490b4801b8592a28ab1014fbb8422fa6a067482b1f11`.
These are control-flow/source-profile tests with all Vivado commands mocked,
not evidence for FPGA part support, numerical synthesis, timing closure, DRC
or physical board settings.

```sh
make -f fpga/cmac/Makefile array-fixed-build-control-test
make -f fpga/cmac/Makefile array-fixed-vivado-prepare
# Only after the fixed native/proof and all nine fixed Icarus modes pass:
RK_CONFIRM_BOARD=YPCB_00338_1P1 make -f fpga/cmac/Makefile array-fixed-vivado \
  FIXED_REPORT=build/rknpu-cmac-array/c32k16/fixed-hierarchical-1791208877880399503/report.json \
  BOARD_REPORT=build/rknpu-fixed-array-board/iverilog-<run>/report.json
# Review/emission uses array-bitstream-review/array-bitstream with the new
# build/rknpu-fixed-array-vivado/run-<run>/report.json, never a prepare report.
```

`tools/cmac/map_fixed_array.py` independently measures the full experimental
C32/K16 XC7 area without substituting area counts for numerical acceptance.
It checks 512
partial-row helpers and sixteen parallel kernel instances, preserves C32
hierarchy during mapping, omits only the optional SAT share pass, then checks
primitive counts through final flattening. It uses the primitive-aware timing
metadata handling from the completed baseline recheck. The first run at
`build/rknpu-cmac-array/c32k16/fixed-area-1791206313793473296/report.json`
was stopped after source inspection found that the shared primitive counter
permits only the original cell's hierarchy name. Its FAIL report is retained.
The corrected runner counts the explicitly checked experimental kernels and
top-shell primitives separately, without broadening the shared counter's
unknown-hierarchy or timing-metadata gates. The completed fresh run is
`build/rknpu-cmac-array/c32k16/fixed-area-1791207358609699523/report.json`.
Its status is `PASS_FIXED_CMAC_XC7_AREA_EXPERIMENT_ONLY`, source SHA256
`36a07f4cc3307b177678a4daef92b86682ea0555785c9b5b2cb6e1bf46615d98`,
using Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`). The actual
7,823.696-second mapping retains 512 helpers and sixteen C32 kernels and checks
hierarchical against flattened primitive counts: 466,264 LUT1..6, 742 FDCE,
5,280 CARRY4, 1,616 MUXF7, 640 MUXF8 and no DSP48E1. LUT primitive count is
8.98% below the baseline's 512,248; the isolated helper's 28.7% saving does
not transfer unchanged to the complete array. The log estimates 287,863
logic cells for CMAC alone, before CACC/control/RAM. Neither that estimate nor
the primitive count establishes packed fit, routed 50 MHz timing or numerical
netlist acceptance. The original raw-command path is unchanged.

The complete source-bound area evidence is frozen in
`verification/runs/2026-10-06-fixed-c32k16-area/`: 34 verified members,
30,370,426 archive bytes, SHA256
`fdb46ddb5cb8625e369ccffc3a09dfc0461fdd1a3e48a1bf2f06be6be6f7a020`.
The independent archive checksum passes. This archive preserves the area-only
scope, including the completed hierarchical/flattened primitive equality check.

### Partitioned complete-board area experiment

`tools/cmac/map_fixed_board.py` requires that full fixed-CMAC area report to
finish successfully, plus current full fixed-array native/proof and completed
fixed-board integration evidence. It copies the actual mapped array/kernel
modules without altering their ports, parameters, cells or wiring, preserves
sixteen C32 kernels, and maps all remaining raw K65 board RTL. There is no
dummy multiplier, arithmetic blackbox, serialized CMAC or CPU fallback.
Decoder, DMA, all sixteen CACC contexts, output conversion/writes, ROM/RAM,
reset and LED sources remain unchanged. The complete physical source profile
and portable ROM images are source-bound even though this area-only action
does not apply physical pin/timing constraints or authorize a bitstream.

Only the optional SAT `share` stage is omitted, as in the CMAC measurement;
the remaining installed `synth_xilinx` stage list is checked exactly. Unknown
hardware leaves fail. Reused kernel primitive counts must remain identical;
all sixteen instances, live board I/O and actual BRAM inference are mandatory.
Keeping the mapped kernel boundary limits cross-boundary optimization, so
these counts are not a Vivado packed-utilization or physical-fit result.
Two-state integration may feed this separate area experiment; the full
nine-mode four-state Vivado/bitstream prerequisite is not relaxed.

Ten current synthetic control methods pass in
`build/fixed_board_mapping_controls_20261006.log` (the earlier
eight-method log remains historical). A real invocation with the
RUNNING CMAC mapping report is rejected before any output directory or tool
is created; its exit-one log is
`build/fixed_board_mapping_running_parent_rejection_20261005.log`.
The actual intermediate partition separately passes the module/parameter/
primitive import-shape check in
`build/fixed_board_mapping_actual_partition_check_20261005.log`, but that is
not completed whole-board mapping.

The first real whole-board attempt remains FAIL at
`build/rknpu-fixed-board-area/1791215511983936941/report.json`: Yosys
`read_json` does not preserve the mapped array's parameter interface, and
elaboration rejects the caller's `TAG_WIDTH`. The corrected run uses a
wire-only SystemVerilog adapter retaining the original port/parameter header
and an explicit C32/K16/TAG35 rejection guard. Only the imported array's module
key is aliased; its complete body and the mapped kernel are unchanged. The
generated join still changes exactly one CMAC instance type. This is not an
arithmetic, reset, oracle or raw-command modification. The fresh run at
`build/rknpu-fixed-board-area/1791215830399703096/report.json` now completes
with `PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY`, source SHA256
`f768971dbde9bc2098b2b2ea68c3094f3c13db60acbeac158f6aadc01f140350`.
Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`) completes the
actual 8,397.386-second mapping with all sixteen unchanged C32 kernels and
512 parallel products. The whole board contains 512,159 LUT1..6, 17,310
flip-flops, 6,550 CARRY4, 5,589 MUXF7, 1,570 MUXF8, six RAMB36E1 and no
DSP48E1. This includes the actual CACC/output/DMA/decoder/ROM/RAM/reset/LED
path, not just CMAC. Its 322,911-LC log estimate is 8.14% above the target's
298,600 LUT sites in the official UG474 resource table linked above, so the
CMAC-alone 287,863-LC estimate did not establish whole-board feasibility.
Primitive counts and estimated packing do not prove legal placed utilization
or failure: further area work and actual implementation are still required.
No numerical netlist, pin/electrical/DRC, routed timing, bitstream or FPGA/RK
acceptance is claimed by this completed mapping.

The complete source-bound whole-board area archive is
`verification/runs/2026-10-06-fixed-full-board-area/`: 1,759 verified members,
132,432,059 bytes, SHA256
`e1e7358fb40774cfe04985f9e730265565b9cfc7cc16efeb85b8be3d9007788d`.
The independent checksum passes; original failed elaboration evidence remains
separate and is not relabeled as a completed area pass.

`tools/cmac/check_fixed_partition_binding.py` separately uses real Yosys on
that actual mapped partition and generated adapter, with no dummy arithmetic.
Its positive C32/K16/TAG35 import checks all sixteen actual kernels; three
negative elaborations require the adapter's `$fatal` for C8, K8 and TAG34.
It verifies the adapter and imported module bodies against the completed CMAC
mapping, records source/artifact hashes and tool version, and does not accept
numerical equivalence or physical fit. The completed report is
`build/rknpu-fixed-partition-binding/1791216942676771849/report.json`, status
`PASS_ACTUAL_FIXED_PARTITION_IMPORT_BOUNDARY_ONLY`, source SHA256
`406e61c18df3f06e5f7bc3f8e0745c3da55b6681f1c3ed1eab1d6c448a515a38`.
Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`) completes exact
geometry in 96.263 seconds and rejects C8/K8/TAG34 in 75.384/68.051/67.131
seconds. The rejected commands return one specifically at the adapter's
`$fatal` during parameter derivation; unrelated compiler errors do not pass.

```sh
python3 tools/cmac/check_fixed_partition_binding.py \
  --mapping-report build/rknpu-fixed-board-area/1791215830399703096/report.json
```

```sh
# Only after the full fixed-area report completes successfully:
make -f fpga/cmac/Makefile array-fixed-area \
  AREA_REPORT=build/rknpu-cmac-array/c32k16/fixed-area-1791207358609699523/report.json \
  FIXED_REPORT=build/rknpu-cmac-array/c32k16/fixed-hierarchical-1791208877880399503/report.json \
  BOARD_REPORT=build/rknpu-fixed-array-board/verilator-1791210829751522794/report.json
```

### Read-only shared-input cone analysis

`tools/cmac/analyze_shared_kernel_cones.py` examines the completed actual
whole-board netlist without altering it. Each kernel is the same C32 module;
only input bits connected to the identical parent bit in all sixteen instances
seed the analysis. Identicalness propagates through unchanged combinational
primitive functions with all inputs established; private weight inputs and
state/DSP outputs are barriers. Unknown cells/pins, undriven inputs, cycles,
multiple drivers, conflicting input aliases and parameter overrides fail.
This is structural opportunity analysis, not a transformed netlist or numerical
or physical acceptance gate.

Twelve synthetic controls pass in
`build/shared_kernel_cone_make_controls_20261006.log` under Python 3.14.5.
The actual read-only run completes at
`build/rknpu-shared-kernel-cones/1791225362316126979/report.json`, status
`PASS_SHARED_INPUT_CONE_ANALYSIS_ONLY`, source SHA256
`ca9dd7cea5da0d04d44e9a23fce503b64f8072b32bfff2aeb1f20a6fcb6fe7bc`.
All 512 data bits and both 32-bit masks are identical across the actual board's
sixteen kernels; none of the 512 weight bits is shared. The eligible cone per
kernel contains 973 LUTs (608 LUT3, 231 LUT2, 62 LUT5, 70 LUT6, two LUT4) and
seven MUXF7. Sharing one copy could remove 14,595 LUT primitives and 105 MUXF7
across sixteen kernels, leaving a hypothetical 497,564 whole-board LUT
primitives. No cells have actually been removed. That primitive saving cannot
be subtracted directly from the 322,911-LC packing estimate or establish fit.
Any implementation still needs circuit-equivalence validation, the unchanged
full numerical/raw-command/hold/reset/fault suites and fresh mapping/timing.

```sh
make -f fpga/cmac/Makefile array-shared-cone-control-test
make -f fpga/cmac/Makefile array-shared-cone-analysis \
  MAPPING_REPORT=build/rknpu-fixed-board-area/1791215830399703096/report.json
```

### Separate reversible mapped-board preparation

`tools/cmac/prepare_shared_board.py` now constructs a separate actual
whole-board candidate from that completed mapping. It extracts only the
established identical-input combinational cone once, with fresh shared wires
feeding all sixteen otherwise private kernels. Independent reverse expansion
must literally restore every original module, port, cell, parameter and wire.
No product, private weight, state, raw decoder, DMA, CACC/output or RAM
behavior is substituted, serialized or retimed. This sharing contract is
specific to the actual board wiring, not arbitrary independent weight-mask
inputs on the standalone array. Fifteen reverse-expansion controls pass.

The first actual attempt remains FAIL at
`build/rknpu-shared-board-prepare/1791227248744199991/report.json`, source
`f7fcd586f15af67bd765810f82c868e77aa38b02ab8678422018c8120d54caac`.
Its binary-only exporter rejects the board's literal RAMB36E1 string modes.
Its exact runner is preserved under that directory's `snapshot/`, SHA256
`99bd8dfe9e17c52930f8275919b02576420838d27226ab497a60f55f43531539`.
No numerical or export PASS is claimed for that failure.

The new `tools/cmac/export_board_netlist.py` explicitly supports the declared
BRAM string-mode whitelist; unknown modes, initialization files, expressions
and nonliteral parameters fail. Numeric parameters and INIT bits are retained
exactly. The older array export/simulation runner stays unchanged while its
host job may still exist. Five export controls pass, including a real small
Yosys roundtrip retaining BRAM strings, INIT bits, ports and parameter defaults.
Combined controls are in
`build/shared_board_prepare_bram_export_controls_20261006.log`.
The fresh sharing preparation is at
`build/rknpu-shared-board-prepare/1791228867345797456/report.json`, source
`6aebd8948816b39684521b9d1c3571fea8d931ffde795cb6dd9250c092f8ad38`.
Its candidate counts remove 14,595 LUTs and 105 MUXF7. The real full-board
Yosys export now completes with exit zero in 474.895 seconds and passes full
port-bit/cell/type/parameter/default/wire-incidence identity. The independent
hierarchy/elaboration check completes with exit zero in 454.917 seconds,
followed by literal reverse expansion and unchanged-source checks. Final
status is `PREPARED_SHARED_CONE_BOARD_NETLIST_ONLY`: 497,564 LUT primitives,
17,310 FF, six RAMB36E1 and no DSPs. Yosys estimates 311,781 logic cells,
still above the target's 298,600 LUT sites; neither count establishes placed
fit. Full numerical/raw-board and physical gates remain incomplete.
The completed preparation is frozen in
`verification/runs/2026-10-06-shared-cone-board-preparation/`: 1,774 verified
members, 143,392,401 bytes, archive SHA256
`928746112ff1290cce9b3a58ea703bc17cbda8448bec39769916ec1315956fd4`.
The archive and its member hashes are verified; this does not upgrade the
preparation's numerical or physical acceptance.

`tools/cmac/pair_board_luts.py` adds another separate reversible candidate:
two LUT1..5 functions with exactly the same variable input wires become one
LUT6_2, with I5 tied high and the two functions in separate INIT halves.
Original input pin order and binary constants are preserved; repeated
correlated input wires are retained unpaired, not silently constrained.
Every original function class must additionally pass real unchanged Yosys
primitive-model comparison for **all 0/1/X/Z input combinations**, including a
real first-class/first-pattern one-bit mutation that must fail. Exact circuit
export/roundtrip, hierarchy and unchanged-source gates follow. This is not
UNISIM/GSR or routed-delay verification and does not change the donor's
carry-save rows, exceptional values or raw-command execution boundary.
Eleven controls pass, including actual two- and five-input HDL model checks
and negative detection, in
`build/board_lut_pair_controls_full_patterns_20261006.log`.
The first full actual-board attempt is preserved FAIL at
`build/rknpu-paired-board-prepare/1791228952700524867/report.json`, source
`d20e2b6a031f116972d354209f6a2559870ba2f50b925880629d1c7fe7359e20`;
its reversible candidate has 125,163 LUT pairs and 386,996 LUT primitives,
with unchanged non-LUT hardware. The 650 actual function classes require
496,096 four-state comparisons. The deliberate first-class/first-pattern
mutated INIT is rejected by real Icarus with exit code one, as required.
The unchanged exhaustive corpus now passes with actual exit zero:
`PASS LUT_PAIR_FOUR_STATE classes=650 comparisons=496096` in 111.160 seconds,
using Icarus/vvp 13.0 and unchanged installed Yosys 0.65 functional models.
The Yosys export itself exits zero in 411.619 seconds, but the strict full-circuit
identity gate rejects it: Verilog turns the private RTLIL `$paramod` module name
into a public identifier with an additional leading backslash. The failed
report and exact pre-run source snapshot remain unchanged; its local passing
function-class gate is not completed board preparation or numerical acceptance.
The fresh read-only full-export diagnostic, captured in
`build/paired_private_module_namespace_diagnostic_20261006.txt`, explicitly
applies the recorded instance-name bijection and the single module/type-name
edit, then proves complete circuit-signature equality. This confirms the
namespace conversion explains the entire failed export, without relabeling
that attempt PASS.
An explicit reversible module-name bijection now updates every instance's
module-type reference before export, without normalizing names in the verifier.
Fourteen pairing controls pass in
`build/board_lut_pair_module_alias_frozen_input_controls_20261006.log`, including
a real-Yosys unaliased counterexample and exact aliased roundtrip. Altered truth
tables, connections, types and module references still fail circuit comparison.
Compile-time and execution-time model/bench/class/executable manifests are
bound to the final artifacts; no old proof log substitutes for a new run.
The fresh actual preparation completes at
`build/rknpu-paired-board-prepare/1791231501256738760/report.json`, source
`be6e430f161c3627dc55d4ab31628259abd84745972826078af7ecf76486398f`.
Its newly executed 650-class corpus passes all 496,096 four-state comparisons
with exit zero in 147.414 seconds. The deliberate first-pattern INIT mutation
is rejected with exit one in 24.757 seconds. These are new logs with pre-compile
and pre-execution artifact bindings, not the previous attempt's logs. Full
export exits zero in 562.411 seconds, passing exact circuit identity;
hierarchy/check-assert exits zero in 470.437 seconds. Final literal restoration
and unchanged-source checks also pass. Status is
`PREPARED_LUT6_2_BOARD_CANDIDATE_ONLY`, with 125,163 pairs, 386,996 LUT
primitives and unchanged 17,310 FF/six RAMB36E1/no DSPs. Its source-bound archive
now completes in `verification/runs/2026-10-06-lut-paired-board-preparation/`:
1,789 verified members, 145,247,002 bytes, SHA256
`3ebf34d861e1d250e2df0092c99be6fdf7e45e74d0410c176f88d16f7f2f7101`.
The archiver's actual exit zero and independent archive checksum are observed;
this is structural/function-class evidence, not full-board numerical signoff.
Primitive savings do not translate directly to the LC packing
estimate: small LUT pairs may already be assumed by that estimate. No timing,
DRC, electrical or full numerical/hold/reset/fault prerequisite is waived.

```sh
make -f fpga/cmac/Makefile array-shared-board-control-test
make -f fpga/cmac/Makefile array-shared-board-prepare \
  MAPPING_REPORT=build/rknpu-fixed-board-area/1791215830399703096/report.json
make -f fpga/cmac/Makefile array-lut-pair-control-test
make -f fpga/cmac/Makefile array-lut-pair-prepare \
  MAPPING_REPORT=build/rknpu-fixed-board-area/1791215830399703096/report.json
```

`tools/cmac/test_paired_mapped_array.py` prepares full-array binary numerical
replay using the actual paired C32 kernel, not arithmetic RTL replacements.
The original array/board kernels differ only in debug netnames; all other
module fields and the full circuit signature must agree before binding. The
array registers, protocol shell, all sixteen instances and original 208-frame
bench remain unchanged, with 3,328 numerical results, tag/backpressure/reset/
fault checks and the real first-frame golden-bit negative control. Parent
preparation, model/bench/executable bindings, literal pair restoration and
complete export identity must pass before any execution directory is created.
Shared-cone parents are rejected because their board-specific mask-sharing
contract does not apply to arbitrary standalone array inputs. The new runner's
12 controls pass in
`build/paired_mapped_array_frozen_export_final_controls_20261006.log`.
An actual CLI invocation rejects the saved failed parent with exit one at
the completed-parent gate, before any output directory is created; see
`build/paired_mapped_actual_failed_parent_rejection_20261006.log`.
The fresh RUNNING parent is also rejected at the same gate with actual exit
one in `build/paired_mapped_actual_running_parent_rejection_20261006.log`.
These refusals are not an actual mapped numerical PASS. The now-completed
source-valid parent permits the actual full-array replay, launched with log
`build/paired_mapped_array_actual_replay_20261006.log`. Its process handle is
was confirmed live while running. Parent validation completed, and the retained execution report
is `build/rknpu-cmac-array/c32k16/paired-mapped-binary-1791235676061104658/report.json`,
Post-export source is
`7628fe92b06a2ea58ae4731ef978967cd0d4ba1abb377d4ecf601bc7fc08ecfd`;
the runner extends its initial input manifest with the frozen model/export
artifacts before compilation, not with edited RTL or replaced parent evidence.
Real Yosys export exits zero in 144.139 seconds, with full circuit identity;
hierarchical mapped-kernel compilation exits zero after 13,610.36 seconds.
The run remains FAIL: top generation exits zero but the strict warning gate
rejects `INITIALDLY` on the unchanged Yosys FDCE model's `initial Q <= INIT`
at line 692. No 208-frame/3,328-output numerical execution occurred. The
source/export/compiled files and exact failure remain retained; the vendor
model and warning expectations have not been changed. Neither an absent execution directory during validation nor an
observation delay is treated as failure or grounds to restart the run.

```sh
make -f fpga/cmac/Makefile cmac-paired-mapped-control-test
make -f fpga/cmac/Makefile cmac-paired-mapped-test \
  AREA_REPORT=build/rknpu-cmac-array/c32k16/fixed-area-1791207358609699523/report.json \
  FIXED_REPORT=build/rknpu-cmac-array/c32k16/fixed-hierarchical-1791208877880399503/report.json \
  PAIRED_REPORT=build/rknpu-paired-board-prepare/1791231501256738760/report.json
```

### Independent vendor-model check and mapped-board bench binding

`tools/cmac/test_lut_pair_unisim.py` adds a separate actual Xilinx-model
function-class gate. The existing cache `build/reference/xilinx-unisim` is
clean at `1c8e05fd1e9a79ceb8b996a0996674122eed086f`; the tool pins SHA256 for
LUT1..5, LUT6_2 and the Apache-2.0 license, and compiles only frozen,
unmodified vendor files without XIL_TIMING/XIL_DR. It rechecks the completed
pair parent, actual class/certificate domain and literal restoration, then
requires the original exhaustive comparison count and a real first-pattern
INIT-bit negative. Inputs and executable bytes are bound before each compile
and simulation and checked afterward. This is not full-array/raw-board,
GSR/sequential/BRAM, SDF or physical verification.

The first small vendor-model control fails at class 1/pattern zero; its log
remains `build/lut_pair_unisim_and_binding_controls_20261006.log`.
The preserved diagnostic `build/unisim_lut_startup_probe_20261006/report.json`
shows already-zero input regs leave procedural LUT4/5/O5 models unevaluated:
reference outputs are X and the paired outputs are X/1. Initializing driven
regs to X before applying the same first pattern yields reference and paired
1/1, then passes all 2,080 comparisons. The separate vendor harness changes
only these initializers; all pin ties, patterns, delays, comparisons, fatal
assertions and the negative INIT mutation remain unchanged. Constant-only
classes are explicitly unsupported by that startup harness, never discarded;
all 650 actual classes have one to five variable inputs. Seven controls pass
in `build/lut_pair_unisim_startup_and_binding_controls_20261006.log`.
The full actual run completes at
`build/rknpu-lut-pair-unisim/1791235044716807822/report.json`, source
`026b134bb7186717a31436ba6c6c3cfee6fde11ab7023050fd2326eb925d6322`,
with master log `build/lut_pair_unisim_actual_650_class_20261006.log`.
Actual status is `PASS_LUT_PAIR_UNISIM_FUNCTION_CLASSES_ONLY`: all 650 classes
pass 496,096 comparisons, with actual exit zero in 999.601 seconds under
Icarus/vvp 13.0. The real INIT-bit negative exits one in 51.910 seconds.
Both compile/run bindings, final source and artifact checks pass. This does
not promote full-board or mapped-array numerical, GSR/BRAM, physical or RK
acceptance. Its completed source-bound archive is
`verification/runs/2026-10-06-lut-pair-unisim-function-classes/`:
1,819 verified members, 149,221,464 bytes and SHA256
`3880d7ebc4e72d8767a40d6be4a5c329daa4d4f32d4d3e2ae80a8c2034fb6067`.
The separate archive checksum check returns `evidence.tar.gz: OK`.
The independent current-artifact audit also passes in
`build/lut_pair_unisim_completed_artifact_audit_20261006.log`, checking exact
model/bench bytes, all compile and execution bindings, command codes and
positive/negative markers. This audit does not execute an additional simulation.

### Dedicated-output audit and union-fanin opportunity analysis

Raw LUT6_2 counts are not packed LUT-site savings. [UG474](https://docs.amd.com/r/en-US/ug474_7Series_CLB/Look-Up-Table)
allows two functions with at most five combined variable inputs, A6 high and
separate O5/O6 outputs. Carry-select and F7 mux inputs require O6; carry DI
can use O5 or the documented bypass. The local nextpnr packer can split pairs
whose halves already have carry/mux constraints, or insert feed-through LUTs.
Neither truth-table equivalence nor a nominal capacity comparison establishes
the final physical count.

`tools/cmac/audit_lut_pair_sinks.py` revalidates the completed pair parent's
literal restoration, full export identity, proof bindings, source and artifacts,
then records every direct CARRY4.S and MUXF7.I0/I1 consumer on both outputs.
Its six small controls pass; these are not HDL or physical-board tests.
The actual read-only C32/K16 audit completes at
`build/rknpu-lut-pair-sink-audit/1791243516491521479/report.json`, source
`6d4bdc8c2d477baa4050d5ee8c0d6ff4bb532eb0a4530e9542119a185f174105`.
Weights are the actual top once and kernel sixteen times. Among 125,163 pairs,
1,160 have an O5 output feeding an O6-only consumer; 1,036 of these have both
outputs requiring O6, and 124 have only the O5 output requiring reorientation.
There are 1,120 pairs with a dedicated O6-output sink, including the same 1,036
dual-role pairs. This does not repair any pair, count extra required physical
sites, prove numerical behavior, or accept a fit/bitstream.
Its completed source-bound archive is
`verification/runs/2026-10-06-lut-output-role-audit/`: 1,795 verified members,
145,395,106 bytes, SHA256
`ed83fe21c3c1c7f7206c48a35191e2953fb659001e14edb2c49b4361d76fba3c`.
Independent checksum verification passes; this remains read-only audit evidence.

`tools/cmac/analyze_union_lut_pairs.py` separately suggests disjoint residual
LUT1..5 pairs whose input union fits five variables, including differing input
sets. Deterministic subset-indexed greedy selection preserves original pin
order/constants and excludes self-fed pairs, repeated correlated inputs and
pairs whose two outputs both require O6. Existing LUT6_2 cells and their
conflicts remain untouched; constant-only pairs remain explicitly unmatched
because the vendor startup harness needs a driven input. This is a read-only
opportunity analysis, not a maximum matching or a new accepted netlist.
Ten small controls pass, including six explicit primitive fixtures with 8,352
exhaustive 0/1/X/Z comparisons under each of Yosys and pinned, unmodified Xilinx
models, and a real INIT-bit negative under each. These fixtures do not validate
the actual full-board proposal domain. All full-array, raw-board and physical
gates remain required before promoting a later transformed candidate.

The actual analysis completes at
`build/rknpu-union-lut-opportunities/1791243648348492686/report.json`, source
`d53bc186af68cb6d67d13f81023e20327aaa0e1e8d663dfbe08463a3a3fd0fd8`.
It finds 4,444 disjoint proposals per kernel and 9,876 in the top, totaling
80,980, with 5,135 unique classes. All use differing variable-fanin sets and
have driven inputs. The projected 306,016 LUT primitives still exceed 298,600
nominal sites, before packing overhead and existing pair-conflict repair.
No hardware was changed.
The completed private-original opportunity-analysis archive is
`verification/runs/2026-10-06-union-lut-opportunity-analysis/`: 1,795 verified
members, 145,802,572 bytes, SHA256
`9e889371e74533602cd4ebedb47a581f5a6325afcdd3ccb01fd67039438f320a`.
Independent checksum verification passes. This freezes the read-only analysis,
not the still-running actual function-class proof or a transformed netlist.

The final tiny frozen-model control is
`build/rknpu-union-lut-model-controls/1791243692822360481/report.json`, source
`3544c01e39e220798b6e7091754bf6645d102b2af92db275f893f2391b44315b`.
It records Icarus/vvp 13.0, all imported verification sources and executed
frozen models. Its archive
`verification/runs/2026-10-06-union-lut-frozen-model-controls/` has 47 verified
members, 147,913 bytes and SHA256
`2efefbf47361fcd54d1b40cbf223a963b44a98b4ddce6ab0663f92998242679e`;
the independent checksum check passes. The earlier source-lighter control
remains retained with its exact executed test source, not relabeled as this run.

`tools/cmac/test_union_lut_functions.py` prepares the actual exhaustive class
gate: exact analysis hashes, proposal wiring/role/domain replay, frozen Yosys
and pinned Xilinx models, compile/execution bindings and real INIT-bit negatives.
Three admission controls pass. The actual 5,135-class run now passes its Yosys
negative and all 9,163,648 four-state comparisons. Its independent UNISIM
negative and positive compilation pass, but the full positive records FAIL
after 14,402.133 seconds with no completed return code at
`build/rknpu-union-lut-functions/1791244138678464917/report.json`.
The report finishes at 06:46:33 UTC; the four-hour timeout is not a demonstrated
numerical mismatch and is not relabeled PASS. Its executed source/model/bench
and binary hashes and logs remain preserved. No overall two-model class PASS
is claimed. Combined shared-cone/LUT
pairing separately completes at
`build/rknpu-paired-board-prepare/1791244011823377237/report.json`.
The private-kernel mapped-array runner cannot validate that cross-kernel variant.
Neither preparation nor an analysis projection is physical/numerical acceptance.

The combined preparation now passes exact literal pair restoration, all 650
classes/496,096 four-state comparisons and the real negative, full export
identity, hierarchy and final source checks. It completes with 372,401 LUT
primitives and 125,163 pairs, source
`4566dbb42b3e7c280e001f2ffc9baa4c19732b77ff8e58843952f293290e145f`.
This is 14,595 fewer primitives than the private-original paired candidate;
it remains above nominal capacity and is not full-board numerical or packed
physical acceptance. The shared boundary has no standalone-array equivalence
claim; the existing private-array runner still explicitly rejects it.
`tools/cmac/analyze_shared_union_lut_pairs.py` prepares a separate read-only
analysis for its actual top/private/shared module boundary, weighted 1/16/1.
It requires completed pair and shared parents, exact source/artifact/proof-input
hashes, the original completed mapping and exact physical resource counts.
Five admission/weighting controls pass in
`build/shared_union_lut_admission_controls_20261006.log`. A real invocation
against the still-running parent exits one before creating analysis output:
`build/shared_union_lut_running_parent_refusal_20261006.log`.
The private-original mapped-array admission rule remains unchanged. This
analyzer does not transform hardware or rerun the parent's circuit proofs.
The actual shared-board analysis completes in
`build/shared_union_lut_actual_completed_parent_analysis_20261006.log`.
Its completed report is
`build/rknpu-shared-union-lut-opportunities/1791248184077959387/report.json`,
source `9d185e83a508c12d6ca81cfb650cf725bc8cc23a9209153bd1efc71b0d8e1ae0`.
It finds 4,007 proposals per private kernel, 436 in the shared data module and
9,876 in the top: 74,424 weighted disjoint proposals and 5,113 classes,
projecting 297,977 LUT primitives before existing output-role repairs. There
are still 1,036 dual-O6 conflicts and 124 O5-only reorientation cases. Splitting
the former raises the projection to 299,013, 413 above nominal sites, before
other packing overhead. No physical fit is inferred. An exact class-set
comparison finds 125 shared-board classes absent from the private-original
5,135-class domain; the earlier class proof cannot cover this new candidate.

`tools/cmac/prepare_shared_union_board.py` implements the separate reversible
full-board transform. It replays the completed analysis's exact proposal
domain, replaces each disjoint pair with recorded truth table/pin bindings,
splits old pairs whose two outputs require O6, and swaps output roles plus INIT
halves for O5-only conflicts. It requires zero remaining direct O5 conflicts,
all original nonreplacement hardware/boundaries/metadata restored literally,
every changed binary function, exact 1/16/1 copies and weighted resources,
full real-Yosys export identity and hierarchy checks. It does not provide
function-class HDL, full-board numerical, packed-fit or timing acceptance.
Five control methods pass, with real topology/INIT/metadata/domain/role
mutations, in `build/shared_union_board_literal_controls_20261006.log`.
The actual preparation now completes at
`build/rknpu-shared-union-board-prepare/1791249619184767694/report.json`,
source `531440d359df6f83a45a10136be6c64bce1dfc31d611c03e2e6f1304d1fc4b88`.
It has measured 299,013 LUT primitives and 5,321 changed function classes and
passes exact real export identity, hierarchy and final-source checking.
The actual supervisor exits zero; status is
`PREPARED_SHARED_UNION_LUT_STRUCTURAL_CANDIDATE_ONLY`.
It retains all 512 products and sixteen kernels. This completed structural
status is explicitly not numerical or physical acceptance, and the measured
count remains above nominal LUT capacity.

`tools/cmac/test_shared_union_board_functions.py` independently regenerates
that actual reversible function domain from the completed analysis. Frozen
Yosys and pinned, unmodified Xilinx models each require exhaustive 0/1/X/Z
comparisons and a real INIT-bit negative, compile/executable bindings and
final literal restoration/source checks. The small three-class union/split/
swap fixture completes 2,304 comparisons under each model and both negatives:
`build/rknpu-shared-union-board-functions/1791249420276843422/report.json`,
source `68f2af27c14c3aba955e4796926321060115d951610d31292a2fa5ea82bad1a8`.
That is a fixture, not the actual full-board domain. The actual full-domain
run now completes in `build/shared_union_role_actual_complete_function_classes_20261006.log`.
Its actual report is
`build/rknpu-shared-union-board-functions/1791251036169899868/report.json`:
5,321 classes and 9,284,320 comparisons now pass under each frozen Yosys and
pinned unmodified UNISIM model, with both real one-bit negatives. Source
fingerprint: `64d8f57c5a32008a8d7fe044fdab123ce2818ab1b69fb94161f70829b52e7532`.
The actual UNISIM positive takes 13,885.792 seconds and the Yosys positive
3,394.685 seconds. This is complete combinational function-domain acceptance,
not full-array/raw-board reset/fault numerical, augmented-domain, packed-fit,
timing/electrical/DRC, bitstream or FPGA/RK acceptance.

Its [completed source-bound archive](../verification/runs/2026-10-06-shared-union-completed-functions/index.json)
preserves 99 verified members/776,874,431 uncompressed bytes, SHA256
`33bf12d960cbdd8d0568aa2086299437afaa6ca8f67c8758f909c8b63f777cc2`.
All actual class binaries, model/source bindings and real negatives are
retained; the independent archive checksum passes. This does not cover a
different augmented pairing domain or transfer whole-board acceptance.

```sh
make -f fpga/cmac/Makefile array-lut-pair-sinks-control-test
make -f fpga/cmac/Makefile array-lut-pair-sinks-audit \
  PAIRED_REPORT=build/rknpu-paired-board-prepare/1791231501256738760/report.json
make -f fpga/cmac/Makefile array-union-lut-control-test
make -f fpga/cmac/Makefile array-union-lut-analyze \
  PAIRED_REPORT=build/rknpu-paired-board-prepare/1791231501256738760/report.json
make -f fpga/cmac/Makefile array-union-lut-proof-control-test
make -f fpga/cmac/Makefile array-union-lut-function-test \
  UNION_ANALYSIS_REPORT=build/rknpu-union-lut-opportunities/1791243648348492686/report.json
make -f fpga/cmac/Makefile array-shared-union-lut-control-test
# This paired parent now completes, but analysis remains read-only:
make -f fpga/cmac/Makefile array-shared-union-lut-analyze \
  PAIRED_REPORT=build/rknpu-paired-board-prepare/1791244011823377237/report.json
make -f fpga/cmac/Makefile array-shared-union-board-control-test
make -f fpga/cmac/Makefile array-shared-union-function-fixture
make -f fpga/cmac/Makefile array-shared-union-board-prepare \
  UNION_ANALYSIS_REPORT=build/rknpu-shared-union-lut-opportunities/1791248184077959387/report.json
make -f fpga/cmac/Makefile array-shared-union-function-test \
  UNION_ANALYSIS_REPORT=build/rknpu-shared-union-lut-opportunities/1791248184077959387/report.json
```

### Residual cofactor search and improved union matching

`tools/cmac/analyze_cofactor_lut_pairs.py` searches unchanged residual LUT6
and LUT1..5 cells after excluding every completed union proposal. A small
function can be proposed for O5 only if it exactly equals the six-input
function's zero cofactor after actual pin permutation. The selector remains
a live sixth input; constants and original small-LUT pin order are recorded,
not simplified out of a future HDL class. Repeated correlated inputs, feedback
and direct O6-only small-output consumers are explicitly excluded. This is a
read-only binary opportunity analysis, not a circuit or four-state proof.
The actual search completes at
`build/rknpu-cofactor-lut-opportunities/1791251883579897261/report.json`, source
`b942f6452c3da2a3134e2b8616dd53c35e4ae081c44d1c5649c59a985487883a`.
There are zero proposals in each private/shared module and six in the top,
six weighted proposals/classes total. Its conditional primitive projection
is 299,007, still 407 above nominal capacity before packing overhead. The
actual six-class domain has no HDL result; the synthetic fixture below is
not substituted for it. This opportunity does not resolve the area gate.
The current local nextpnr `split_lut6_2()` only constrains constant-I5 halves
together, and XC7 placement rejects an ordinary six-input/5LUT pair. No
conditional primitive reduction is treated as packed savings or a fit.

`tools/cmac/test_cofactor_lut_functions.py` provides a separate exhaustive
six-live-input fixture/actual-domain gate under frozen installed Yosys and
seven unmodified UNISIM LUT models at commit
`1c8e05fd1e9a79ceb8b996a0996674122eed086f`. Its small fixture completes all
4,096 six-input 0/1/X/Z patterns, 8,192 output comparisons per model, and both
real corrupted-INIT negatives:
`build/rknpu-cofactor-lut-functions/1791251928343613213/report.json`, source
`1cc7406871b1abf31dff83b984d11638fbddd946a2ccb8d3e72049142087f188`.
Seven selection and five harness controls pass. This validates one synthetic
fixture, not the actual board opportunity domain or any physical sharing.
The [source-bound fixture archive](../verification/runs/2026-10-06-cofactor-small-frozen-model-fixture/index.json)
contains 64 verified members, 137,996 bytes; independent checksum verification
passes. No model, original RTL or existing failure assertion was changed.

`tools/cmac/analyze_augmented_union_pairs.py` separately tries length-three
augmenting paths on the exact completed shared-board matching: one old pair
is replaced by two legal pairs with previously unmatched endpoints. Every
accepted graph edit is independently replayed, every final proposal's binary
table and necessary O6 role is rederived, and all 1/16/1 module copies remain.
Five graph controls pass, including reused endpoints, illegal/self-feeding
edges and direct O6-role conflicts. Actual analysis completes with exit zero in
`build/augmented_union_actual_board_analysis_20261006.log`, report
`build/rknpu-augmented-union-lut-opportunities/1791252561015561093/report.json`.
It finds one extra pair in the private kernel (sixteen copies) and none in
the shared module or board top: 74,440 total additional disjoint proposals.
After the unchanged 1,036 output-role repairs, the conditional projection is
298,997 LUT primitives, 397 above nominal sites. The
[completed source-bound archive](../verification/runs/2026-10-06-augmented-union-completed-analysis/index.json)
preserves 54 verified members/6,042,623 bytes, SHA256
`d82a486c447ee701bf20d457b7a2e5db7f15ffbc09a59f168e1dd3d3eb45fdc2`.
No new function-domain, transformed-netlist or packed-fit acceptance is inferred.
This is not maximum
matching, a transformed circuit or permission to reuse the old class proof;
any revised domain needs new numerical and physical gates.

```sh
make -f fpga/cmac/Makefile array-cofactor-lut-control-test
make -f fpga/cmac/Makefile array-cofactor-function-fixture
make -f fpga/cmac/Makefile array-cofactor-lut-analyze \
  UNION_ANALYSIS_REPORT=build/rknpu-shared-union-lut-opportunities/1791248184077959387/report.json
make -f fpga/cmac/Makefile array-augmented-union-control-test
make -f fpga/cmac/Makefile array-augmented-union-analyze \
  UNION_ANALYSIS_REPORT=build/rknpu-shared-union-lut-opportunities/1791248184077959387/report.json
```

### Isolated carry-prefix DSP lane

The separate [carry-prefix contract and evidence](DSP_PREFIX_CARRY.md) records
a fresh all-67-input binary comparator proof and all 135,680 native lane/tag
fixtures. Identical-interface mapping measures 657 original-DSP-lane LUTs
versus 616 prefix-lane LUTs, with one DSP each. Exact source derivation
preserves the original magnitude multiply, bias, compensation and tag logic.
Both actual failed harness runs are preserved with executed-source snapshots.
Six initial harness controls and generated-source checks pass. Its own actual
mapped replay subsequently completes all 135,680 native and mapped fixtures
with two real negatives. A separate full prefix array passes C32/K16/TAG35
hierarchy/wiring preparation and now passes its full original 208-frame
four-state numerical corpus: 3,328 checked outputs, 520 held cycles,
sixteen reset-canceled outputs and the X-input fault case. The first full-area run fails its diagnostic checker after
Yosys returns zero and is source-archived (69 members); fresh full synthesis
with exact ABC module/step checks now completes: 398,168 LUT primitives,
742 FDCEs and all 512 DSPs/sixteen kernels. This is 9,184 fewer LUT primitives
than the original full DSP array, not a placed-fit or timing result.
Its own raw-board compile now
retains one prefix array, sixteen cells, 512 lanes and 512 carry helpers.
All nine four-state board modes now pass against this variant's own completed
independent parents. The full 208-frame mapped-array compiler exits zero, but
its strict diagnostic gate rejects an omitted DSP pin before numerical replay.
A separate whole-board
mapper and frontend-only preparation retain all sixteen actual mapped
kernels; 70 current prefix software controls pass, not numerical or physical
tests, including a real small export/readback check. See the linked contract
for the completed 123-member mapped, 72-member hierarchy and 431-member
raw-board/preparation archives and the new 87-member native-array archive.
There is no all-X leaf or completed mapped-array acceptance,
physical fit/timing/DRC or FPGA/RK acceptance. No old full-array
result transfers to it, and no physical or numerical gate is weakened.
The first real imported-array/native-shell frontend fails JSON serialization
of a pre-existing FDCE library process; its 193-member executed-source failure
archive preserves the original run and partial graph. A real small design-only
export control passes exact native/DSP/FF circuit identity; the fresh full
frontend now completes with one checked wire-only wrapper, an unchanged
imported array and sixteen unchanged mapped kernels/512 CMAC DSPs. The second
source-diagnostic/wrapper-alias failure remains separately archived as FAIL.
The successful frontend's 228-member archive is frontend preparation only,
not whole-board synthesis or numerical acceptance. All nine raw-board modes
now pass; full mapped-array numerical acceptance remains absent. Actual full-board
mapping has been launched with its own completed numerical/area parents.
The [completed all-nine-mode archive](../verification/runs/2026-10-06-dsp-prefix-full-nine-mode-raw-board/index.json)
preserves 507 verified members and the original complete raw command/input/
output and reset/fault contracts; it is not physical or mapped-array acceptance.
A prefix-specific Vivado checkpoint package now binds 77 source files; all
18 mocked build/admission controls pass under both Tcl runtimes. Its own
173-member archive does not authorize physical acceptance or bitstream
emission. Full Vivado and configuration-bank confirmation remain unavailable;
no pin, clock, timing/DRC gate or parallel product is reduced.
The distinct prefix reviewed-bitstream emitter now revalidates all four own
parents and the routed implementation, binds all reviewed reports/checkpoint,
and repeats the full 512-product guard. Its 20 admission/emission controls
pass under both Tcl runtimes; all Vivado calls are mocked. An actual prepared
report is rejected before output/tool creation. The fresh 112-method
preparation suite passes, and a separate actual model control completes
4,259,904 DSP/1,024 binary carry comparisons with two real negatives. It does
not admit full-array compiler warnings. The separate source-bound Icarus run
now passes the full DSP/binary corpus and all 1,048,576 four-state carry cases,
with both real negatives. Its 18-member archive is distinct from the full-array
compiler failure. An actual unchanged-model cone audit proves the 26 omitted
inputs outside the zero-register P cone and rejects a legal registered
counterexample reaching CEA2/CLK/RSTA. Its 28-member archive and read-only
inventory bind all 1,152 missing-pin notices to 32 actual DSPs; fourteen software
diagnostic-preparation controls pass. No main-array diagnostic is waived;
full mapped numerical and physical acceptance remain pending. See
[the prefix contract](DSP_PREFIX_CARRY.md) for commands and source-bound
archives, including the 128-member reviewed-emitter preparation archive.
The earlier completed production `make test` is at unchanged source
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`;
that regression does not cover these nested experimental sources. The preceding
source-identical attempt fails the third product-bench compiler's 600-second
deadline; both 247-entry RTL suites pass, but product Icarus is not run.
The complete failed attempt and stable products are archived separately.
The subsequent [fresh literal production snapshot](../build/rknpu-dsp-prefix-pin-cone-production-regression/1791300029293915642/report.json)
passes both 247-entry RTL suites, all three product benches per simulator,
49 Python tests, 1,087,299 numeric comparisons and 82 equal memory images.
The unchanged deadlines and source manifest are retained; this is not prefix
or physical acceptance. Its [2,812-member fresh archive](../verification/runs/2026-10-07-dsp-prefix-fresh-production-snapshot-pass/index.json)
is independently checksum-verified; the old timeout remains FAIL.
[RAM-width capture work](DSP_PREFIX_BOARD_NORMALIZATION.md)
now verifies all 54 actual full-board RAM port resizes, including 22 silent
constant-only changes, and unchanged original final circuit. Its 254-member
archive is independently revalidated. The actual initial-driver capture finds
real consumers on all 288 warning bits; the corrected connectivity audit
proves their 107-mux cones unobservable and removed after cleanup.
Separate source-bound structural diagnostic admission now passes its complete
original remaining gates and numerical-parent revalidation. No complete-board
numerical or physical acceptance is inferred, and the original failed
gate/report remain unchanged. Its independent archive now completes actual
proof/circuit/structure revalidation, preserving both counter harness failures.
Full-board observation retention now passes actual frontend checks for all 22
signals and the four-bit state, retaining the original sixteen kernels/512
products. The exact existing mapped-bench probe still refuses twelve
missing/dead/recoded observations; no nine-mode check is weakened or remapped
numerical result claimed.
Fresh full-board remapping now passes from the completed retention parent:
all 22 observations, four-bit state, sixteen kernels/512 CMAC DSPs and fresh
strict RAM/diagnostic/structure gates remain. Counts are 445,816 LUT primitives,
17,519 flip-flops, 515 DSPs and six BRAMs; the 294,538 logic-cell estimate is
not placed fit or timing. The missing-help startup failure is archived before
correction and ten controls pass. [Model/export preparation](DSP_PREFIX_BOARD_NORMALIZATION.md)
now includes an actual small DSP export roundtrip for 32 kernel/three shell
configurations, a preserved pinned-model unknown-product failure, and corrected
testbench startup/negative controls. The separate exhaustive vendor carry
truth table now passes all 1,048,576 cases, recording 415,001 four-state
differences from the old oracle while all 1,024 binary cases agree.
The settled original DSP/CARRY corpus finishes FAIL at the first four-state
Z-input discrepancy after complete DSP/binary carry execution; the actual
source-bound failure is archived rather than promoted. The newest actual
production regression now passes both 247-entry RTL suites, all product
benches per simulator and 82 equal memory images at unchanged source.
The new full-prefix mapped-board runner has eight passing controls and a
separate unmodified pinned DSP model inventory. Its first full-size attempt
completed exact circuit export but was interrupted during compilation; the
[897-file interruption archive](../verification/runs/2026-10-07-dsp-prefix-observed-mapped-board-interruption/index.json)
preserves the stale nonterminal report and unaccepted partial executable.
An [unchanged-source fresh retry](../build/dsp_prefix_observed_mapped_board_retry_launch_20261007.json)
is supervised by a host user service against its own completed parents.
Full numerical acceptance still requires a real negative and all nine unchanged
raw-board modes. All sixteen kernels/512 products,
20 ns clock and physical electrical/timing/DRC gates are unchanged.

Later exact-model binary proof and source-specific kernel/top diagnostic
admission now pass. Both real FDCE controls pass 129 checks and a wrong-golden
negative while preserving actual INIT=X/reset behavior. Whole-board mapping
finishes but remains FAIL at its original diagnostic gate; read-only exact
kernel-identity accounting counts 442,838 LUTs, 17,310 flip-flops, 512 CMAC plus
three shell DSPs and six BRAMs. Its 292,445 estimated logic cells do not prove
placed fit. Two actual generated-top diagnostic/interface failures are frozen
before corrections. The subsequent full replay matches every original
208-frame/3,328-output/hold/reset fixture and fresh negative, but complete
build/mapped acceptance is refused because make masks two archive errors.
That actual result is frozen in its own 291-member qualified archive. A
fresh equivalent relative-library-path run has clean compilation, exact
ten-kernel-object/nine-top-object archive membership and a passing real
negative; the original full positive now passes all 208 frames/3,328 outputs,
hold/reset/tag checks in 335.154 seconds. The checkpoint driver has
a separate source-bound clean-replay admission with eight passing controls,
while all eighteen original physical-flow mocks still pass under both Tcl
runtimes. The 112-method preparation suite passes again, and independent
actual mapped checkpoint admission passes its hashes/parents. The clean
380-member source-bound archive is verified. The separate actual checkpoint
preflight also completes all four own parents (native/mapped/area/all-nine-board)
and retains a 97-source/105-artifact package without invoking Vivado. An actual
review-template request against it is correctly refused because it is not
routed implementation. Physical
acceptance remains incomplete; raw words, full geometry and all
electrical/timing/DRC gates are unchanged. See the prefix contract for evidence.

### Isolated corrected DSP lane: native and area evidence, proof pending

`rtl/cmac/experimental/rk_cmac_fp16_lane_dsp.sv` is a new, isolated
compensated-lane representation. A separate experimental C32/K16 array now
uses it, but neither variant is promoted into a raw command path or FPGA top.
Inputs are the existing donor's sign/pre-shifted
15-bit magnitudes, not IEEE FP16 encodings. The new proof boundary has 37
unconstrained binary input bits and all 40 lane-sum/tag bits, not equality of
the older helper's two carry-save rows and tag (72 bits).

The donor's eight Booth rows have unsigned bias `0x55550000`. The experiment
uses a signed magnitude multiply targeted to a DSP, adds that bias, retains
the original first unshifted carry-save row and subtracts the discarded-low-bit
carry before applying `-(bias >> shift)`. That carry is necessary because the
donor shifts its two rows separately. No generic IEEE product/rounding policy
or compatibility of an uncorrected inferred multiply is assumed.
The existing row helper and NVIDIA sources are unchanged.

Actual Icarus/vvp 13.0 simulation completes 135,680 binary comparisons at seed
`0x3588d501`: 144 directed operand pairs and 4,096 random pairs, each with all
16 shifts and both masks. The deliberate comparison-bit negative exits one
with a real `LANE_DSP_MISMATCH`. These executed native checks are recorded in
`build/rknpu-lane-dsp-experiment/1791245109358910557/report.json`, full driver
source `98a5f19744b394e09a33769a0fcdb0eeaa5187dca166f7c65869394eb6e005b3`.
That overall report remains **FAIL**: its next graph admission rejects Yosys
`$scopeinfo` metadata before SAT. The completed native stage is not relabeled
as a completed proof or successful overall run.

An actual diagnostic with the carry correction removed finds a mismatch even
with both magnitudes nonzero: `a=0002 b=0001 shift=2 nz=1`, donor lane
`ffffffff`, uncorrected lane `00000000`, tag `3c`. This is sign/pre-shifted
helper data, not IEEE halfword input or an RK capture. The deliberately wrong
variant is under `build/`, not hardware source or an accepted optimization.

The initial independent area run also remains FAIL at
`build/rknpu-lane-dsp-area/1791245396051327210/report.json`: its strict primitive
counter refuses retained `cmac_lane_dsp_miter` hierarchy. No hardware whitelist
was broadened. The corrected proof lowers with documented
`flatten -noscopeinfo`; the corrected area flow uses `synth_xilinx -flatten`
to prune the unselected miter side before counting. Both selected area tops
retain identical 37-input/40-output port widths, distinct free input bits,
strict primitive definitions and expected zero/one DSP counts. Five current
driver/domain control methods pass in
`build/lane_dsp_corrected_driver_controls_20261006.log`; they are synthetic
admission checks, not the arithmetic proof or FPGA evidence.

The independent word-level binary SAT attempt is retained as FAIL at
`build/rknpu-lane-dsp-formal/1791246379606266318/report.json`, source
`ab4dd86cda5d3346f3809513d7e3140e4bc7d97c404a58d57e349caa9e9cb2c6`.
It rejects the actual one-bit negative with a countermodel in 7.537 seconds;
the unchanged full-domain proof reaches the supervisor's 1,000-second timeout
without a proof result. No binary equivalence PASS or numerical defect is
inferred from that timeout. The first separate Boolean-lowered attempt remains FAIL at
`build/rknpu-lane-dsp-boolean-formal/1791247786100359307/report.json`, source
`137de912ff1605b7b9d1c09e2c09fa1fefd5cd387cfc1139b5a19077f22e9504`.
It first checks the same word-level domain, then uses `techmap`, optimization
and ABC AND-gate lowering on both sides. The second graph must still have all
37 free binary inputs and exact output widths, with only AND/NOT cells and no
state, assumptions or arithmetic blackboxes. Both real negative and positive
SAT gates remain mandatory. Its negative graph's ABC lowering reaches the
1,000-second supervisor timeout before SAT, preserving executed snapshots.
The correction uses documented direct `aigmap` whole-design lowering, without
ABC, selections, input constraints or arithmetic abstractions. Ten current
DSP-domain/library/lowering controls pass in
`build/lane_dsp_direct_aig_admission_controls_20261006.log`.
The actual new run is
`build/rknpu-lane-dsp-boolean-formal/1791249053260131418/report.json`, source
`e05f9bd5c25d224e515f1240cb61553257001792bf64878e304c498ae7bc1770`.
Both actual AIG lowerings complete with all 37 distinct free inputs and exact
outputs. The real negative finds its SAT countermodel in 42.798 seconds.
The positive SAT command reaches 84,738 variables/215,491 clauses, then the
supervisor's 1,000-second timeout (actual 1,000.913 seconds). This report
remains FAIL with `binary_lane_sum_equivalence=false`; no proof PASS or
arithmetic defect is inferred from the timeout. Its logs, graphs and exact
executed source snapshots are retained without changing the input domain.

The first flattened comparable XC7 area attempt is retained as FAIL at
`build/rknpu-lane-dsp-area/1791246380555163094/report.json`, source
`e38b95362cf49938fafc3244de6bb006b6ea3fc263822070f0eb3be60ff4e2fa`.
Both actual synthesis commands exit zero. The reference counts 765 LUTs and
zero DSPs; the candidate's synthesis output lists 652 LUTs and one DSP. The
overall strict counter then rejects four `$logic_and` cells in the blackbox
DSP48E1 declaration, so the diagnostic candidate count is not accepted area.
The installed Yosys `xilinx/cells_sim.v` lines 3518..3521 show these are four
CEP-enabled conditional clock-to-P/PCOUT specify paths, not multiplier logic.

`tools/cmac/lane_dsp_library.py` adds an isolated counter view for exactly
those four qualifiers: scalar unsigned ANDs, constant zero/one and CEP inputs,
distinct internal outputs that drive exactly one `$specify3.EN`, CLK source,
unknown timing data and exactly the P/PCOUT destination/polarity pairs. Any
arithmetic, extra sink, primitive-port driver, changed width/clock/data or
unknown library cell still fails. It changes neither the source library,
primitive instances nor global CMAC counters, and is not timing signoff.
Two real software mutation-control methods pass. The new isolated counter
also completes a read-only diagnostic over both retained mappings,
confirming exactly those four timing-only qualifiers and the listed counts:
`build/lane_dsp_retained_actual_timing_qualifier_diagnostic_20261006.log`.
The original area report remains FAIL; this diagnostic is not new synthesis,
binary equivalence, mapped numerical or physical acceptance. The corrected fresh area
run completes at `build/rknpu-lane-dsp-area/1791247789492729744/report.json`, source
`7b701f5311742932408264abb99446d46e108d82624a10449ebadc4c289475a3`;
status `PASS_ISOLATED_LANE_DSP_XC7_AREA_ONLY`: 765 reference LUTs/zero DSPs,
652 candidate LUTs/one DSP. Fresh reference/candidate synthesis exits zero
in 385.426/331.374 seconds, with strict signature, primitive and qualifier
checks passed. These tools record Yosys 0.65 and exact
commands/source/artifact hashes. No isolated count establishes full-array
resources, physical sites, placement or timing.

The earlier combined focused Make controls pass fourteen methods: five proof/area-domain,
two library-qualifier, two Boolean-domain and five shared-board admission/
weighting methods, in `build/lane_dsp_boolean_library_shared_controls_20261006.log`.
Generated sources still match their generators. The controls are not the SAT
proof, full mapped numerical replay or physical FPGA result.

The completed native stage, exact original failed driver snapshots and carry
diagnostics are frozen under
`verification/runs/2026-10-06-corrected-dsp-lane-native-and-driver-failures/`:
57 verified members, 1,330,334 bytes, archive SHA256
`f785fe464bf6c2128f81cd42831cedf7d0b8dd79b148fd00bdd052f83f18b6b0`.
The independent archive checksum passes. Later harness edits are not substituted
for the executed sources. No proof/area/full-array/four-state startup/board/
timing/electrical/DRC/bitstream or RK acceptance is inferred from that archive.

### Actual mapped DSP-lane replay and full C32/K16 DSP candidate

`tools/cmac/test_mapped_lane_dsp.py` requires the completed isolated area
report and exact current source/artifact hashes. It exports the actual
`cmac_lane_actual_area` graph through Yosys, including the DSP's real string
parameters, and requires independent round-trip circuit identity. The mapped
compile excludes the native DSP candidate body and uses a frozen, unchanged
installed Yosys XC7 functional library. The original donor miter and bench
change only the candidate module type; each native and mapped phase requires
the original 135,680 binary comparisons and its real one-bit negative.

The first actual job finishes FAIL at
`build/rknpu-lane-dsp-mapped-binary/1791253423351655016/report.json`.
Exact export identity and the fresh native 135,680-comparison positive and
negative pass. The mapped compile/real negative pass; its positive corpus
times out after 1,800.264 seconds, without a PASS or observed numerical
mismatch. The original report remains FAIL. A separate 90-second verbose
probe of the unchanged compiled binary reaches simulation time 2,688 ns;
it is not corpus acceptance or a hardware performance measurement.
`tools/cmac/replay_mapped_lane_dsp.py` verifies the terminal timeout, original
source/model/executable bindings and completed native/export stages. It
explicitly inherits only completed parent commands 0..12, not a new native
run or the failed positive, then executes a fresh mapped negative and all
135,680 unchanged positive comparisons with a 14,400-second budget. The
continuation completes PASS at
`build/rknpu-dsp-mapped-lane-replay/1791256801119025767/report.json`.
Its fresh mapped positive runs for 6,013.375 seconds and passes all 135,680
original comparisons, seed `3588d501`, 4,096 samples. The fresh mapped
negative also passes its real mismatch contract. Source SHA256 is
`789b2f47fa7c50119752939b5620c61744a14e3f093185deb32553dcbea30b0a`.
The completed native/export stages are explicitly inherited, not rerun;
the original timed-out report remains FAIL. The
[completed mapped-lane archive](../verification/runs/2026-10-06-dsp-actual-mapped-lane-completion/index.json)
preserves 87 verified members/3,342,026 bytes, SHA256
`624c8198c367ef6886758ef003fe42b86579c4d7db42b1a56febbfc006cb6b57`.
It contains the failed parent, bound compiled binaries, unchanged frozen
XC7 model, executed sources and fresh logs. This establishes isolated
mapped binary fixtures only, not full-array, raw-board or physical acceptance.
The independent archive checksum passes.
Its four controls pass in
`build/mapped_dsp_bound_replay_admission_controls_20261006.log`.
Four original source/domain/marker admission controls pass in
`build/mapped_lane_dsp_admission_controls_20261006.log`.

The isolated full-width candidate consists of
`rtl/cmac/experimental/rk_cmac_fp16_cell_dsp.sv` and
`rtl/cmac/experimental/rk_cmac_fp16_array_dsp.sv`.
`tools/cmac/dsp_array_contract.py` verifies their exact offline derivation
from the fixed variant: substitute already-compensated lane sums, preserving
all 512 products, sixteen kernels, FP44 encoding, masks/exponents,
weight-before-data/lowest-channel NaN priority, invalid tags, warmup, hold,
reset cancellation, sticky faults and the 35-bit tag. The raw QWORD execution
boundary is unchanged; no runtime CPU arithmetic or layout fixup is added.
Five literal-contract controls pass in
`build/dsp_array_literal_contract_controls_20261006.log`.

The original full-array native runner, `tools/cmac/test_dsp_array_native.py`,
finishes FAIL at `build/rknpu-dsp-array-native/1791262976458807986/report.json`,
source `524d67bd1685705d4078ce82abf2fea96561093191776194c571c4cc4b7e8464`.
It rejects a still-running mapped-lane parent and
requires all 208 original oracle frames/3,328 outputs, the original numerical,
hold/reset and X-input fault assertions, and an actual first-frame negative.
Actual Icarus 13.0 compilation passes in 178.438 seconds; the unchanged
first-frame mismatch negative passes in 283.773 seconds. Its unchanged full
positive corpus exceeds the 14,400-second budget at 09:10:42 UTC without a
recorded numerical mismatch. The [executed timeout archive](../verification/runs/2026-10-06-dsp-full-native-timeout/index.json)
preserves 71 verified members/61,638,124 uncompressed bytes, SHA256
`19c2adb35eac421e412d43d014cff4bcf0931d75cabdaa8f9edd705252ab3fdb`.
It remains FAIL; no native-array PASS or reduced-corpus acceptance is claimed.
Four prerequisite/marker controls pass in
`build/dsp_array_native_admission_controls_20261006.log`.
The actual strict Verilator lint job exits one due to three warnings: the
unchanged donor Booth module's filename and the existing lane's two empty
output connections. Its failure is retained in
`build/dsp_array_actual_strict_lint_20261006.log`; the actual version is
recorded in `build/dsp_array_strict_lint_tool_version_20261006.log`.
No lint PASS or warning waiver is claimed, and source changes must not
invalidate independently running source-bound candidate jobs.

`tools/cmac/map_dsp_array.py` separately measures the complete candidate as
area/structure only. It preserves the C32 module during mapping, retains all
sixteen physical instances, and requires 512 elaborated lanes and 32 mapped
DSPs per kernel/512 overall, identical flattened/partitioned counts, the
complete independent input domain and nonconstant output/control wires.
Only the previously source-bound donor array-lowering notices are admitted;
unknown warnings and hardware still fail. The global primitive counter is
unchanged. The four DSP CEP timing qualifiers are inspected solely in the
counter view; actual stored hardware and simulation models are unmodified.
Six structural/flow controls pass in
`build/dsp_array_area_admission_controls_20261006.log`.
The initial actual full-array flow stops at the exclusive `map_dsp` label,
then resumes at `map_memory`, unintentionally skipping DSP mapping. The actual
mapped hierarchy retains sixteen kernels but contains no DSP48E1s. The real
[stage-endpoint control](../verification/runs/2026-10-06-dsp-stage-probe-1791260786574133774/index.json)
executes two independent kernels/four signed products: `begin:map_dsp` leaves
four `$mul` cells and zero DSPs, whereas `begin:coarse` executes XILINX_DSP
and produces four DSP48E1s with no unmapped multiplies. Its 17-member archive
contains 2,237,224 bytes, SHA256
`736b258a3bbbb565ec6ae69d25fb86ac720d9a2e13579c1144e0a20dd2a6a972`.
The two earlier probe preflight failures remain separately source-snapshotted;
ordinary fixture modules need name selection, and the standard library
whitebox finalization is required before the intermediate JSON export. These
corrections change neither the diagnostic products nor CMAC RTL.

After that actual diagnosis, the known-wrong full run is deliberately
interrupted through its exact unified-exec handle 10703, which returns 130.
The killed namespace leaves its saved report `RUNNING`; that stale status and
the incomplete flat JSON are not accepted as a live job or synthesis result.
Its unchanged report, executed sources, logs and exports are preserved in the
[interrupted-flow archive](../verification/runs/2026-10-06-dsp-interrupted-exclusive-stage-flow/index.json):
54 verified members/29,824,537 bytes, SHA256
`4610aee86a992dcf0ffe99c6c093105cfb192b0ce1ff21efe9d39b683302fc92`.
The independent archive checksum passes. The report is not relabeled PASS.
The corrected mapper uses `begin:coarse`,
immediately asserts 32 mapped DSP cells in the retained kernel, and still
requires 32 per kernel/512 total after complete primitive mapping. The fresh
actual job is `build/rknpu-dsp-array-area/1791261222250630875/report.json`,
source `4b98ffb80c5df9de0c191a2ff320f164817df9ffc83fbd4ff0e35a059c76a6ca`,
with log `build/dsp_array_actual_corrected_full_xc7_area_20261006.log`.
The actual corrected run now completes at 06:28:13 UTC, with supervisor
session 93125 exiting zero. It executes XILINX_DSP, passes the early 32-DSP
assertion and the complete elaboration, hierarchical/flattened primitive,
source/artifact and known-warning gates. Final counts retain all sixteen
kernels/512 DSP48E1 products, 407,352 LUT primitives and 742 FDCEs. Six corrected
structural/flow controls also pass. This is the completed area/structure gate,
not mapped numerical acceptance, packed utilization, placed fit, physical
timing/electrical/DRC or bitstream readiness. Its
[actual-source archive](../verification/runs/2026-10-06-dsp-corrected-full-array-area/index.json)
now preserves 87 independently verified members/51,385,619 archive bytes,
SHA256 `3bf477561b9d8d70ac6ac6c29432757ab9606ec286d9a6597cb48d4cc49ee5d2`.
The separate checksum command exits zero. The first archival preflight used a
nonexistent supplemental stage-index path and failed before creating an archive;
its script and failure log remain in `build/`. The corrected archival lookup
does not alter synthesis evidence or relabel that failure.

`tools/cmac/prove_lane_dsp_components.py` starts a separate decomposition of
the unresolved whole-lane proof, using unchanged donor hardware rather than
repeating the timed-out full multiply/alignment graph. The real job at
`build/rknpu-dsp-lane-component-proofs/1791255314304645720/report.json`
completes the Booth recoder (19 free bits), actual 5×24/4×32 carry-save
modular-sum lemmas (120/128 free bits), and digit reconstruction (16 free
bits), each with a real SAT negative. The overall job then fails before the
conditional-carry SAT: its checker omitted that theorem's logical-AND guard.
The [executed-stage/failure archive](../verification/runs/2026-10-06-dsp-component-proofs-admission-failure/index.json)
preserves 66 verified members/105,426 bytes, SHA256
`3a4585210ecb32cb5bf5cee2413bfd376d5ff3b40d2048fcf4e1ecf5675cbcd9`;
its checksum is independently verified. The old failed report and exact old
driver are not substituted with later sources.
The correction audits only the carry theorem's single scalar AND, driven
by logical-NOT of the explicit overflow output and reduction-OR of all 32
compared bits, driving the mismatch output. Changed widths, pin roles,
predicate/reduction inputs, extra guards or guards on other lemmas fail;
the global lane/cell gates and theorem are unchanged. Five current controls
pass in `build/dsp_component_corrected_guard_admission_controls_20261006.log`.
A fresh complete suite finishes PASS at
`build/rknpu-dsp-lane-component-proofs/1791255882165369405/report.json`.
All five actual positive SAT proofs and their real negatives complete,
including the conditional carry theorem. The
[completed five-lemma archive](../verification/runs/2026-10-06-dsp-component-proofs-complete/index.json)
contains 73 verified members/111,921 bytes, SHA256
`4ecd3fbf8c39dcfdd5628b43ff7e70ef814378ae5410fa6b347e4bdedc0622c0`;
its independent checksum passes.
Every lemma preserves all its unconstrained inputs and rejects assumptions,
state, arithmetic blackboxes or a hidden full multiplier. The carry theorem
explicitly applies only when the unsigned row sum does not overflow. Concrete
donor range bounds are not established by that suite; no whole-lane binary
equivalence is inferred from these component proofs.

`tools/cmac/prove_lane_dsp_tree_ranges.py` separately completes the actual
5×24 and 4×32 full-integer row-sum identities, conditional on the complete
input sum fitting 24/32 bits. All 120/128 binary inputs remain free, and
25/33 row-sum bits are compared with an explicit audited overflow guard;
there are no assume cells or narrowed domains. Both real bit-flip negatives
and positive SAT proofs pass at
`build/rknpu-dsp-tree-range-proofs/1791256884356343154/report.json`.
The [conditional-tree archive](../verification/runs/2026-10-06-dsp-conditional-tree-integer-proofs/index.json)
preserves 43 verified members/66,805 bytes, SHA256
`e38c7a91030c2892ae789ea5d3e5af24781e5c26d12a44ba3831188e1a6d5c1a`,
with independent checksum PASS. Four admission controls pass separately.

`tools/cmac/audit_lane_dsp_ranges.py` then elaborates the actual specialized
row RTL and checks all eight Booth instances, binary magnitude/sign domains,
every tree input bit, padding, ordering, tree parameters and the final
eight-bit high-group shift. Conservative unsigned bounds use actual
17-bit selected words/one-bit inversion outputs, not sampled recoder values.
Each five-word sum is at most 11,141,120, below 2²⁴. Applying the completed,
source-identical integer-tree lemmas gives a final sum at most 2,863,267,840,
below 2³²; this discharges the unsigned no-overflow condition required by the
discarded-carry theorem. The audit finishes PASS at
`build/rknpu-dsp-donor-ranges/1791257753788291713/report.json`.
The [range archive](../verification/runs/2026-10-06-dsp-source-bound-donor-ranges/index.json)
preserves 64 verified members/118,007 bytes, SHA256
`b97485a9af9791923fa8be4ec9d7ebaa20d89af89743ff68bbecc20d4caa55d1`.
Five current admission controls pass. The
[first range-audit failure](../verification/runs/2026-10-06-dsp-donor-range-admission-failure/index.json)
is preserved: Yosys elaboration exits zero, but strict warning admission
rejects the donor's array-lowering notices. The corrected audit admits only
the two exact source-bound donor notices; unknown warnings still fail.
Neither the bounds nor the component proofs establish multiply
distributivity, exact compensated-lane composition, full-array/raw-board,
physical FPGA or RK-silicon equivalence. Production and experimental RTL are
unchanged by this proof/audit increment.

`tools/cmac/audit_lane_dsp_product.py` now checks the unshifted donor product
identity using the actual elaborated row wiring and the completed unchanged
recoder, integer-tree and range proofs. All fifteen magnitude coefficients
are checked exactly: weights 1, 4, 16, 64, 256, 1024, 4096 and 16384, bias
`0x55550000`, and the eight Booth digits `[0,1,1,2,-2,-1,-1,0]`. All coefficient
residuals are zero. The integer row sum equals the bias plus the signed
15-by-15-bit magnitude product, ranging from 357,957,631 to 2,505,310,209.
Three real certificate corruptions are rejected; these are mathematical
certificate controls, not new HDL/SAT negatives. The completed report is
`build/rknpu-dsp-product-certificate/1791259360344972675/report.json`, status
`PASS_SOURCE_BOUND_UNSHIFTED_DONOR_PRODUCT_CERTIFICATE_ONLY`.
The [product-certificate archive](../verification/runs/2026-10-06-dsp-unshifted-product-certificate/index.json)
preserves 142 verified members/254,180 bytes, SHA256
`d655bcd21315c831334a7c15db917901e136fc08847e0e492eb740eab9f89906`.
Six admission controls pass. The initial JSON tuple/list serialization
preflight failure remains preserved in the
[original preflight archive](../verification/runs/2026-10-06-dsp-product-preflight-failure/index.json);
its correction retains every shape and numerical value.

`tools/cmac/prove_lane_dsp_composed.py` composes that exact product identity,
the no-overflow bound and the completed discarded-carry SAT lemma with
audited whole-module glue contracts in
`tests/cmac/dsp_lane_composition_contract.json`. All 32 exponent/pair-mask
control states are checked. The actual native miter's 37 independent binary
input bits and all 40 compensated sum/tag output bits are retained. Fresh
complete actual and negative HDL lowering execute, followed by a real
bit-flip SAT countermodel. The positive result is **checked mathematical
composition**, not a newly executed monolithic positive SAT proof; earlier
direct SAT timeouts remain FAIL. The completed report is
`build/rknpu-dsp-composed-lane-certificate/1791259718323122667/report.json`,
status `PASS_COMPOSED_BINARY_LANE_SUM_TAG_CERTIFICATE_ONLY`.
The [composed-certificate archive](../verification/runs/2026-10-06-dsp-composed-binary-lane-certificate/index.json)
preserves 175 verified members/374,123 bytes, SHA256
`c6ffcf44c1dc18a30e55b007a1bfff11143a20d926e38d20c57e352365a74326`.
Both certificate archive checksums pass independently. Five composition
admission controls pass. The contract covers the specialized native binary
lane domain, not generic IEEE half multiplication, reset/configuration/X
behavior, mapped primitives, the complete array/raw board, physical FPGA or
RK silicon. The separate actual mapped-lane fixture gate has now passed;
full-array and subsequent board acceptance remain independent requirements.

`tools/cmac/prepare_dsp_board.py` prepares and compiles the full raw K65 BRAM
board path with exactly one offline CMAC-array substitution in the unchanged
CMAC/CACC join. It preserves all other synthesis/simulation sources, command
decode/DMA, CACC, output conversion/writer, BRAM, reset/fault/watchdog checks
and the original full board bench. Source ordering excludes the original/fixed
array and cell bodies; the compiled hierarchy must contain exactly sixteen
DSP cells and 512 lane instances without baseline/fixed fallback instances.
The actual Icarus 13.0 compile finishes zero after 277.936 seconds at
`build/rknpu-dsp-board-preparation/1791258184152384268/report.json`, source
`2ca2de4c8d55fae4a4253578bb61b520a4082f816a79fc3dbf46ba531ae8d147`.
Its compiled hierarchy inspection confirms exactly sixteen DSP cells and
512 lanes, with no baseline/fixed fallback instances. The original bench
and all compile-input hashes are checked again after compilation.
The [completed compile-preparation archive](../verification/runs/2026-10-06-dsp-full-raw-board-compile-preparation/index.json)
preserves 118 verified members/5,901,431 bytes, SHA256
`f684b7582b13ebc3b380d22af31685dfe537b849ef6a8171ab4604c12ee4d5c0`.
Its three admission controls pass in
`build/dsp_raw_board_preparation_admission_controls_20261006.log`.
This is compilation preparation only: no board mode executes, no candidate
is promoted, and no numerical/physical/Vivado/bitstream gate is satisfied.
Full native-array and subsequent nine-mode raw-board acceptance remain
separate prerequisites. Nothing connects to or programs physical hardware.

`tools/cmac/replay_dsp_board.py` now prepares the actual nine-mode replay of
that unchanged compiled binary. It requires a completed source-bound full
C32/K16 native report, its completed mapped-lane parent, and the composed
binary-lane certificate. All nested source/artifact/compile/execution/stimulus
hashes and original full-domain logs are checked. The compiled join must be
the exact single substitution, the binary must retain all sixteen cells/512
lanes, and all original synthesis sources, bench, RAM images and XC7K480T
50 MHz constraints remain bound. Fresh executions must pass modes 0 through
8 in order, including four-state unknown readback, full 4,096-halfword
initialization/readback, 196 command reads, 6,528 operand reads, 64 writes and
acknowledgments on success, plus the original reset/fault/watchdog contracts.
No reduced corpus, baseline/fixed fallback or runtime CPU repair is allowed.

Nine admission/marker control methods pass in
`build/dsp_board_full_nine_mode_admission_controls_20261006.log`; these are
software controls, not board simulation. The expanded focused candidate
regression also passes all 47 software control methods in
`build/dsp_all_candidate_admission_controls_after_board_replay_20261006.log`.
A separate actual read-only admission
check of the completed compiled board and composition evidence also passes
in `build/dsp_board_actual_compilation_and_composition_admission_20261006.log`.
No native-array evidence is fabricated to launch the runner. The original
positive subsequently times out, so its failed report cannot authorize replay. The
[new replay-preparation archive](../verification/runs/2026-10-06-dsp-nine-mode-board-replay-preparation/index.json)
preserves twenty verified members/134,743 bytes, SHA256
`f77b18a87458f710f9a256d64a5fe6d27ce58dde8512b4585c2cffdd1703544a`.
Its independent archive checksum passes.
It records zero executed board modes and preserves the archiver's initial
import failure separately from the corrected completed lane archive; that
preflight failure is neither an HDL failure nor a successful archive run.
The Make target, after the independent native-array gate passes, is:

```sh
make -f fpga/cmac/Makefile array-dsp-board-replay \
  NATIVE_REPORT='<completed-full-DSP-native-report>' \
  PREPARED_REPORT=build/rknpu-dsp-board-preparation/1791258184152384268/report.json \
  COMPOSED_REPORT=build/rknpu-dsp-composed-lane-certificate/1791259718323122667/report.json
```

The new runner does not promote the candidate or satisfy baseline Vivado,
mapped-array/board, placed-fit/timing/electrical/DRC or bitstream gates.

`tools/cmac/map_dsp_board.py` prepares the next complete raw-board area stage.
It requires a completed full C32/K16 DSP-array mapping and a completed actual
nine-mode DSP-board report, including current full-native, mapped-lane,
composition, compiled-binary and RAM-image bindings. Neither RUNNING reports
nor compile-only preparation satisfy those gates. The actual previously
mapped C32 kernel is reused sixteen times; both implementation module bodies
are copied unchanged, not replaced with arithmetic blackboxes. Only the array
module key is aliased, with a wire-only caller wrapper that rejects geometry
other than C32/K16/TAG35 because `read_json` drops parameter interfaces.
The surrounding synthesis sources remain the original DMA/decoder/CACC/
conversion/writer/ROM/RAM/reset/LED sources, with one literal DSP-array join.

The flow uses the corrected exclusive endpoint `begin:coarse`, retains the
early 32-DSP kernel assertion, and omits only the audited optional SHARE pass.
Final checks require sixteen real kernels and the same complete kernel
port bits, primitive types/parameters and pin-wire incidence, independently
of wire numbering. Counts alone cannot substitute for that circuit check.
All 512 CMAC DSP products must remain; any separately inferred shell DSPs
are counted independently. Full-board BRAM, nonconstant original clock/reset/
LED ports and strict known-primitive/library gates remain required. The
timing-qualifier adjustment is only the source-audited counter view; stored
hardware and functional models are not rewritten. Unknown synthesis warnings
and unmodeled hardware fail, rather than being hidden for area acceptance.

Eight new mock admission/structure tests pass in
`build/dsp_full_board_area_admission_controls_20261006.log`; the expanded
software control regression passes all 55 methods in
`build/dsp_all_candidate_admission_controls_after_board_area_20261006.log`.
These are controls, not actual whole-board synthesis or numerical evidence.
The [source-bound full-board area preparation archive](../verification/runs/2026-10-06-dsp-full-board-area-preparation/index.json)
preserves 28 verified members/155,967 bytes, SHA256
`cc6668380f62e3d2cd487f855c22c81a35efd78868a8822807ee482304018550`.
It explicitly records no actual whole-board synthesis or bitstream acceptance.
The independent archive checksum passes.
The full-array resource job now completes its area/structure gate with 512
DSPs, 407,352 LUT primitives and 742 flip-flops. The new board mapper and its
full native numerical prerequisite have not yet run to completion.
Once the independent full-array and nine-mode board reports actually pass:

```sh
make -f fpga/cmac/Makefile array-dsp-board-area \
  AREA_REPORT=build/rknpu-dsp-array-area/1791261222250630875/report.json \
  BOARD_REPORT=<completed-DSP-nine-mode-board-report>
```

The resulting stage is area/structure only. Mapped-array/board numerical,
packed physical fit, setup/hold, electrical/DRC, reviewed bitstream and
explicitly authorized hardware programming remain separate gates.

### Full DSP mapped-array binary harness preparation

`tools/cmac/test_dsp_mapped_array.py` prepares replay of the actual mapped
C32/K16 array, retaining sixteen kernels and all 512 DSP products. It requires
completed source-bound full-array native and resource reports; RUNNING parents
are rejected. The unchanged original bench retains all 208 frames, 3,328
checked outputs, 3,312 retirements, sixteen reset-canceled outputs, 520 held
cycles and a fresh first-frame expected-output-bit negative. Verilator's
original two-state guard excludes the native-only X probe, so this binary
marker requires zero X faults and makes no four-state/GSR claim. No error
assertions are deleted or numerical expectations changed.

The official Yosys structural exporter preserves the actual DSP string
parameters. Its omission of resolved module parameter declarations is recorded
separately under the exact C32/K16/TAG35 geometry contract; their metadata-only
separation and all hardware instance aliases must be reversible. The complete
port-bit, primitive-parameter and wire-incidence signature must roundtrip
exactly. The actual kernel is compiled once as a protected combinational
library and instantiated sixteen times; there is no arithmetic fallback.
Unknown diagnostics fail. Only audited export/model metadata and the exact
generated library timestamp notice are admitted.

Nine harness/export controls pass in
`build/dsp_full_mapped_array_harness_primitive_export_controls_20261006.log`,
including a small actual Yosys 0.65 exporter roundtrip, not numerical simulation.
The expanded software suite passes 80 methods in
`build/dsp_all_candidate_admission_controls_after_mapped_array_actual_20261006.log`.
The missing mock primitive declaration and intermediate exporter assumption/
private-name/unmapped-cell preflight failures remain recorded; none is relabeled
as a numerical PASS. The [preparation archive](../verification/runs/2026-10-06-dsp-full-mapped-array-preparation/index.json)
records the exact sources, controls and failure snapshots. The full mapped-array
runner is not yet executed. Its 67 verified members/218,381 archive bytes have
SHA256 `d75009d0425bef588d048246ee8a9ab14fb3b7aca32e432040e588d0378e6bab`;
the independent checksum passes. Once both independent parents actually complete:

```sh
make -f fpga/cmac/Makefile array-dsp-mapped-test \
  AREA_REPORT=build/rknpu-dsp-array-area/1791261222250630875/report.json \
  NATIVE_REPORT='<completed-full-DSP-native-report>'
```

This is binary functional mapped-array verification, not full raw-board,
placed-fit/timing/electrical/DRC, bitstream or physical FPGA/RK acceptance.

#### Prepared full DSP-array stock Vivado checkpoint flow

`tools/cmac/vivado_dsp_array.py` supplies a separate
`dsp-compensated-c32k16` source profile, not promotion into the baseline or
fixed-FP16 flows. The initial actual preparation runs the unchanged raw K65 ROM check,
freezes 73 source/dependency files and renders the checkpoint Tcl at
`build/rknpu-dsp-array-vivado/prepare-1791271180004003603/report.json`.
It returns `PREPARED_DSP_ARRAY_VIVADO_ONLY`, source
`fed73114933890b1da7a7452de98ef467a20ce22db37bcaa7bd78a5b16836443`.
No HDL, Vivado, checkpoint or bitstream is executed/generated by preparation;
existing strict source lint warnings remain unresolved, not waived.

The run action independently verifies all four completed current DSP reports:
actual full-array area, full native fixtures, mapped binary fixtures and all
nine four-state raw-board modes. It binds their exact parent paths, source
hashes and immutable snapshots; incomplete or different variant reports fail.
The mapped negative must have a real integer nonzero exit and the original
first-frame mismatch; an absent exit code is not a passing negative.

The original Tcl is retained with only three reversible additions: preserve
hierarchy at synthesis, require sixteen C32 kernels with exactly 32 DSP48E1s
each before the post-synthesis checkpoint, and repeat that gate after routing.
Literal name-prefix matching handles bracketed generate names, rejects
duplicate ownership and excludes unrelated shell DSPs. Actual Vivado naming
and mapping remain untested. The exact part, pins, raw ROM, original downstream
RTL, 20 ns clock, BRAM, setup/hold, electrical, DRC and report-review gates are
unchanged. The flow is checkpoint-only and cannot emit/program a bitstream.
The initial reviewed bitstream emitter did not admit this new profile; the
source-bound follow-up below adds it without changing the physical/review gates.

Seventeen actual Tcl/admission control methods pass separately under Tcl
9.0.3 and Xilinx Tcl 8.6.13. All Vivado commands are mocked; these tests do not
establish physical behavior. The expanded DSP software suite passes 97 methods.
`make generated-check` and Python syntax checks exit zero. The
[source-bound preparation archive](../verification/runs/2026-10-06-dsp-vivado-checkpoint-preparation/index.json)
preserves 282 independently checked members/587,967 bytes, SHA256
`e5403205bbc5d9e4d1de0d454566d0e47efe7d863b001bd516a418a78402b132`.
The independent archive checksum command exits zero.

The subsequent integration exposes a caller-dependent fingerprint: taking
every loaded project module adds unrelated emitter/caller imports to the
standalone driver's source set. A real one-method software preflight fails
on the unexpected `tools/capture_current_backend.py` addition. Its exact old
driver/test/log snapshot is preserved in
`build/dsp_vivado_caller_dependency_preflight_sources_20261006.tar.gz`;
the failed control is not relabeled PASS. Tracking only the driver's referenced
project module/function/class closure fixes this. The fresh standalone
preparation is `build/rknpu-dsp-array-vivado/prepare-1791272511421279871/report.json`,
source `b5a2775ee6f559bb7e7ae6d06573b9cacbb5cb631aac015f5c459fca03c1ec89`.
All 24 original tool dependencies and 73 total build inputs remain covered;
the emitter must reproduce this exact source set after importing the driver.

`tools/cmac/emit_array_bitstream.py` now has an explicit DSP-profile branch.
It requires the DSP routed status and revalidates all four exact variant parents
and their snapshots, rather than accepting baseline/fixed or prepared status.
The existing named human reviewer, physical-board evidence, every report/checkpoint
hash, legal board-verified electrical pair, original 20 ns clock, BRAM,
setup/hold and DRC gates remain. The DSP emission Tcl adds only the same full
sixteen-kernel/512-product guard immediately before `write_bitstream`; no
constraints are changed. Board evidence is selected from the DSP variant's
validated parent bundle, not the baseline field. A real review-template CLI
probe rejects the current prepared report with exit one before emission.
No Vivado or actual bitstream has run; mock review assertions are not board facts.

Fresh controls pass 18 build/admission methods and 21 reviewed-emission
methods under both Tcl 9.0.3 and Xilinx Tcl 8.6.13, plus 98 DSP software
methods. Generated and Python syntax checks exit zero. The
[follow-up source-bound archive](../verification/runs/2026-10-06-dsp-reviewed-emitter-preparation/index.json)
preserves 288 independently verified members/592,551 bytes, SHA256
`88f98359fcdec8d77c947818f29b56e643dce2a2b62a3bf665c8b776af722332`;
its separate checksum command exits zero. The initial archive and failed
caller preflight retain their own executed sources, not current-source PASS
claims. This still does not establish completed DSP native/mapped/board gates,
actual Vivado fit/timing/electrical/DRC, a reviewed checkpoint or a bitstream.

```sh
make -f fpga/cmac/Makefile array-dsp-build-control-test array-dsp-vivado-prepare
# Only after all four DSP gates actually complete, full Vivado is installed,
# and the original board/electrical constraints are independently verified:
RK_CONFIRM_BOARD=YPCB_00338_1P1 make -f fpga/cmac/Makefile array-dsp-vivado \
  AREA_REPORT=build/rknpu-dsp-array-area/1791261222250630875/report.json \
  NATIVE_REPORT='<completed-full-DSP-native-report>' \
  BOARD_REPORT='<completed-nine-mode-DSP-board-report>' \
  MAPPED_REPORT='<completed-full-DSP-mapped-array-report>'
```

The subsequent fresh production `make test` session 33524 is observed exiting
zero at 06:46:37 UTC, with unchanged production source
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
Its [separate source-bound archive](../verification/runs/2026-10-06-dsp-full-mapped-preparation-production-regression/index.json)
preserves 1,466 verified members/11,463,750 bytes, SHA256
`2c77ea07afb5ec7b71758ca3b7999e69baf7a4a1a5104c7e1689e96afc7afcb3`;
the independent checksum exits zero. It verifies 247 original entries and
three product benches per simulator, 49 Python methods, 1,087,299 seeded C++
comparisons and 82 matching cross-simulator memory images. This fresh run does
not test the experimental DSP-array or its mapped numerical/physical behavior.

The subsequent fresh production `make test` session 46217 also exits zero,
observed at 08:14:53 UTC. Its
[source-bound archive](../verification/runs/2026-10-06-dsp-reviewed-emitter-production-regression/index.json)
contains 1,466 verified members/11,463,314 bytes, SHA256
`b5447ed034bfb765abda609b4c313865d9ec3a247c05afce2b236534fd404453`;
the separate archive checksum exits zero. All 247 existing entries and three
product benches per simulator, 49 Python methods, 1,087,299 seeded numeric
comparisons and 82 matching memory images pass at unchanged production source
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
It is independent production evidence, not a test of the prefix/DSP arrays.

The subsequent fresh production `make test` session 85878 also exits zero,
observed at 08:45:03 UTC. Its [source-bound archive](../verification/runs/2026-10-06-dsp-prefix-carry-production-regression/index.json)
preserves 1,466 verified members/11,462,708 compressed bytes, SHA256
`ce5d3dfbccb7daf892b79bbda51182d74940a6155b7afd3d39d142a9b1543c8a`.
The independent checksum passes. The unchanged production source retains all
247 existing entries and three product benches per simulator, 49 Python
methods, 1,087,299 seeded numeric comparisons and 82 matching memory images.
It does not validate the separately running prefix array or physical FPGA.

The fresh production `make test` session 90266 independently exits zero.
The subsequent fresh session 27921 also exits zero and is frozen in the
[stage-correction production archive](../verification/runs/2026-10-06-dsp-stage-fix-production-regression/index.json):
1,466 verified members/11,463,556 bytes, SHA256
`70b45b7a25df75c1cc71dd0ee021bf100bdca2e02b591e121afd52055053a85c`.
It retains all 247 existing entries plus three product benches per simulator,
49 Python methods, 1,087,299 C++ comparisons and 82 matching memory images.
This is fresh production evidence, not acceptance of the nested experimental
DSP-array or transformed board netlists. The earlier archive below is retained.
Session 90266's [source-bound production archive](../verification/runs/2026-10-06-full-dsp-preparation-production-regression/index.json)
contains 1,466 verified members/11,463,601 bytes, SHA256
`b11bd4d2bfeb69dc3c9abaa3bb09f53e0a8d45b924359ebbd42f19aeda317e3f`;
the independent archive checksum passes. It executes 247 original entries
plus three product benches per native simulator, 49 Python methods and
1,087,299 C++ numeric comparisons at seed `0x3588`, with 82 matching saved
memory images. Production source is unchanged at
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
This does not test the nested DSP-array or transformed-board candidates.

```sh
make -f fpga/cmac/Makefile lane-dsp-mapped-control-test array-dsp-control-test
make -f fpga/cmac/Makefile lane-dsp-component-control-test
make -f fpga/cmac/Makefile lane-dsp-component-proofs
make -f fpga/cmac/Makefile lane-dsp-replay-control-test \
  lane-dsp-tree-range-control-test lane-dsp-donor-range-control-test
make -f fpga/cmac/Makefile lane-dsp-tree-range-proofs
make -f fpga/cmac/Makefile array-dsp-board-preparation-control-test
make -f fpga/cmac/Makefile array-dsp-board-prepare
make -f fpga/cmac/Makefile lane-dsp-donor-ranges \
  TREE_REPORT=build/rknpu-dsp-tree-range-proofs/1791256884356343154/report.json
make -f fpga/cmac/Makefile lane-dsp-mapped-test \
  LANE_AREA_REPORT=build/rknpu-lane-dsp-area/1791247789492729744/report.json
make -f fpga/cmac/Makefile lane-dsp-replay \
  TIMED_OUT_REPORT=build/rknpu-lane-dsp-mapped-binary/1791253423351655016/report.json
# Requires completed continuation PASS, not its current RUNNING report:
make -f fpga/cmac/Makefile array-dsp-native-test \
  LANE_REPORT=build/rknpu-dsp-mapped-lane-replay/1791256801119025767/report.json
make -f fpga/cmac/Makefile array-dsp-area \
  LANE_AREA_REPORT=build/rknpu-lane-dsp-area/1791247789492729744/report.json
```

```sh
make -f fpga/cmac/Makefile lane-dsp-control-test
make -f fpga/cmac/Makefile lane-dsp-experiment # Full native, SAT and area stages
make -f fpga/cmac/Makefile lane-dsp-formal     # Fresh binary SAT only
make -f fpga/cmac/Makefile lane-dsp-boolean-formal # Fresh Boolean-lowered SAT
make -f fpga/cmac/Makefile lane-dsp-area       # Fresh isolated comparable area only
```

### Continuing mapped-board observation binding

`tools/cmac/bind_mapped_board_bench.py` audits the unmodified raw-board bench's
22 internal observations and three force/release targets against actual
exported hardware, requiring exact names, native widths and live wire bits.
It never guesses aliases, decodes a recoded FSM from a synthesis log or
derives the expected error code from the selected test mode. Seven controls
pass, including real Icarus scalar and bus-concatenation force/release checks,
in the same control log. The actual audit exits two at
`build/rknpu-mapped-board-bench-binding/1791234166975612331/report.json`, source
`7f70376857c03b3e678cd599370fe35c4b2cfa98d427789ff6b2dfde1fe3b3b1`:
`INCOMPLETE_MAPPED_RAW_BOARD_BENCH_BINDING_ONLY`, ten bindings and twelve
issues. These include missing handshake/error-code aliases, an address wire
absent from exported hardware and the original four-bit controller state now
eleven bits. No bound bench or numerical acceptance is produced. Completing
this gate needs source-evidenced, hardware-connected observability and state
bindings or a fresh verification-aware mapping, not skipped fault tests or
substituted expected outputs.

`tools/cmac/prepare_observed_board.py` starts that source-evidenced work from
the completed original mapping's exact import script and source hashes. It
performs proc/flatten, asserts every one of the 22 original hierarchical wire
names exists, adds keep attributes before optimization and disables recoding
only for the native four-bit demo state. It then requires the original
width/live-wire/force-point contract, all retention attributes, sixteen actual
kernel instances and complete imported-kernel circuit identity. The production
RTL and raw command path are unchanged. Three script/audit controls pass in
`build/observed_board_prepare_independent_fixture_controls_20261006.log`.
The initial control failure is retained in
`build/observed_board_prepare_controls_20261006.log`: its dead-wire fixture
accidentally shared the net and port bit lists, so the mutation also made the
new bit live. Separate fixture lists correct that test without changing the
audit or its rejection expectations.
The first real pre-mapping preparation fails at
`build/rknpu-observable-board-premap/1791236250182514989/report.json`, source
`6b3f289bbee80daaf5b04a43a1609b917ba14bbbc089e1b56edc91bff0835f0e`.
Yosys exits one in 522.597 seconds: strict check reports 288 undriven compiler
`$bitselwrite$pos` temporary bits in command-DMA/profile lowering. The exact
old tool is retained in that run's source snapshot, matching its recorded hash;
the FAIL and log are unchanged. No undriven check or error expectation is waived.
The corrected preparation adds board-shell-only `opt_expr -keepdc` and
`opt_clean` after all observation keep attributes, before the same
`check -assert`. It never uses setundef, undriven replacement or dont-care mux
removal, and does not optimize the imported CMAC kernel. Only the three exact
existing array-to-register lowering messages (donor input/temp arrays and
configuration regs), also present in the original mapping, are classified;
new driver/width warnings still fail. Four controls pass in
`build/observed_board_prepare_keepdc_cleanup_controls_20261006.log`.
The second real run fails at
`build/rknpu-observable-board-premap/1791237101705754113/report.json`, source
`b47320fdd4373db41c7c55e2a2ca604b0e88391f7ff3ef20a6ba94206e1152ee`.
Yosys exits one in 665.779 seconds: the unchanged strict check reports zero
problems, then JSON export rejects processes in the behavioral FDCE library
definition. This FAIL and its pre-run snapshots remain unchanged.
The next correction uses documented `write_json -selected` with exactly the
complete board and preserved kernel modules. It removes no hardware cells and
does not blackbox or lower the kernel; primitive instances remain intact and
their library is reloaded at mapping/simulation. Post-export module-set,
sixteen-instance and full kernel-circuit identity checks remain mandatory.
Six controls pass in
`build/observed_board_prepare_selected_module_boundary_controls_20261006.log`,
including a real Yosys FDCE-library negative and successful selected export
retaining the primitive, plus altered/missing circuit rejection controls.
The fresh complete preparation completes at
`build/rknpu-observable-board-premap/1791238537797494685/report.json`, source
`de1ad0462b41af3aac966cd75746b0976f69576c46929a3e15b19c08193c79e5`;
real Yosys preparation/export exits zero in 589.065 seconds. The complete
process exits zero, status `PREPARED_ORIGINAL_RAW_BOARD_OBSERVABILITY_ONLY`:
all 22 exact observations, native four-bit state, retention attributes,
sixteen actual instances, full kernel-circuit identity and final source checks
pass. This is completed retention preparation, not mapped numerical acceptance.
Its completed source-bound archive is
`verification/runs/2026-10-06-original-board-observability-preparation/`:
1,767 verified members, 136,037,626 bytes and SHA256
`2193648101687393b8a8191f423cd5d17ec455af50f6a54e1b7e38160e4f6f78`.
The independently executed archive checksum check passes. This archive
preserves the completed retention preparation, not the later live mapping.

`tools/cmac/map_observed_board.py` prepares the next fresh mapping gate from
only a completed source-bound retention parent. It retains the original
complete-board XC7 mapping stage sequence, reloads the primitive library and
requires all 22 observations/native four-bit state, inferred BRAM, board I/O,
sixteen instances and exact unchanged kernel circuit after mapping. Two
stage/parent controls pass in `build/observed_board_mapping_stage_controls_20261006.log`.
They do not execute full mapping or the board numerical/fault/reset suite.
The combined make targets pass all six preparation and two mapping controls
in `build/observed_board_all_preparation_mapping_controls_20261006.log`.
An actual CLI invocation also rejects the saved failed preparation with exit
one before mapping in
`build/observed_board_mapping_actual_failed_parent_rejection_20261006.log`.
Fresh complete-board mapping from the accepted retention parent is retained
with log `build/observed_board_actual_complete_mapping_20261006.log`.
Its failed report is
`build/rknpu-observable-board-mapping/1791239329138833352/report.json`, source
`7a6ba2697f78a067ee4f86b84c3c60f09fb481b1dd63aa0e3c9b06b4d33ce57c`.
The real Yosys command exits zero after 9,902.834 seconds and reports zero
structural problems, but the runner's unchanged strict warning gate rejects
RAM port-width normalization messages. Status remains FAIL, with the original
log and pre-run sources preserved. Subsequent observation/kernel/count/
final-source gates did not execute. The generated netlist is not an accepted
mapped-board or numerical result; neither warnings nor error expectations
have been waived to promote it.
Even a successful preparation is not optimized XC7 mapping or raw-board
numerical/fault/reset, area, timing/DRC or FPGA acceptance; those gates still
need actual fresh execution.

```sh
make -f fpga/cmac/Makefile array-lut-pair-unisim-control-test
make -f fpga/cmac/Makefile array-lut-pair-unisim-test \
  PAIRED_REPORT=build/rknpu-paired-board-prepare/1791231501256738760/report.json
make -f fpga/cmac/Makefile array-mapped-bench-binding-control-test
make -f fpga/cmac/Makefile array-mapped-bench-binding \
  MAPPING_REPORT=build/rknpu-fixed-board-area/1791215830399703096/report.json
make -f fpga/cmac/Makefile array-observed-board-prepare-control-test
make -f fpga/cmac/Makefile array-observed-board-prepare \
  MAPPING_REPORT=build/rknpu-fixed-board-area/1791215830399703096/report.json
make -f fpga/cmac/Makefile array-observed-board-mapping-control-test
# Use only a completed source-valid retention report:
make -f fpga/cmac/Makefile array-observed-board-map \
  PREPARATION_REPORT=build/rknpu-observable-board-premap/COMPLETED_RUN/report.json
```

### Full observed mapped-board replay preparation

`tools/cmac/unisim_board_models.py` pins 17 actual XC7 primitive models,
`glbl.v` and the Apache-2.0 license from the clean Xilinx cache at
`1c8e05fd1e9a79ceb8b996a0996674122eed086f`. Only the actual candidate's
required models are frozen byte-for-byte. Unpinned primitives, including
DSP48E1 for this candidate, fail explicitly. These are simulation models,
not implementation sources; default global startup is never disabled.

The real small FDPE/RAMB36E1/default-GSR control completes with
`PASS_OBSERVED_BOARD_UNISIM_MODEL_CONTROL_ONLY` at
`build/rknpu-unisim-board-model-control/1791240157609981117/report.json`, source
`47a751cb4bd42518e7f5e92300c7cd546fced368dc567ff5694daae84a680fee`.
Icarus/vvp 13.0 compilation exits zero in 3.456 seconds; the actual simulation
exits zero in 1.836 seconds. It checks INIT/default 100 ns startup, preset and
clock enable, WRITE_FIRST RAM, separate-address reads, unknown data and
retention. The same executable rejects a deliberately wrong read value with
exit one in 2.593 seconds. Input/executable and final source hashes pass.
Its source-bound archive has 25 verified members, 118,274 bytes and SHA256
`099612503c8c12bc498c2904c653b8fb23ff3713a66b9a3c4badddc6d53c3fc8`, under
`verification/runs/2026-10-06-observed-board-unisim-model-control/`.
This is not a C32/K16 numerical, raw-board, physical timing or FPGA test.

Two preceding actual wrapper failures remain unchanged:
`build/rknpu-unisim-board-model-control/1791239946994200613/report.json`
rejects the pinned model's implicit typical-delay warnings, and
`build/rknpu-unisim-board-model-control/1791240074464718887/report.json`
rejects Icarus 13's source-located `$finish` diagnostic after a successful
HDL simulation. The corrections select the documented default `-Ttyp`
explicitly and accept only the exact finish statement/path/352000 ps
diagnostic. The inspected model delay triples are identical `100:100:100`;
no model, clock, stimulus, golden or fatal assertion is edited or waived.
Both failed executions retain their exact executed runner source snapshots.

`tools/cmac/test_observed_mapped_board.py` requires a completed source-bound
observable mapping, unchanged sixteen-kernel circuit, all 22 original
observation bindings and exact C32/K16/512-product/20 ns/part contract.
It exports only actual hardware with recorded reversible module/instance
names and requires a real Yosys complete-circuit roundtrip. The unchanged
original raw-board bench is rebound only to evidenced bit wires; all forces,
error codes, reset checks, numeric/address goldens and counts are preserved.
It compiles pinned functional RAM/FF/LUT models with default `glbl` startup,
then requires all nine original modes, including MODE 7 unknown readback.
Successful modes must still check all 4,096 RAM halfwords, 196 command reads,
6,528 operand reads and 64 writes/acknowledgments.

Before the positive suite, the same executable must reject output zero's
single deliberately flipped golden data bit. That mutation lives only in an
isolated test working directory; addresses, other expected outputs, original
golden files and hardware remain unchanged. No CPU execution fallback,
arithmetic replacement, mode-derived expected value, skipped mode or altered
error expectation is provided. Full-board numerical acceptance stays false
unless every real simulation and byte-binding gate completes successfully.
The original bench releases reset at 122 ns, after default GSR at 100 ns;
no reset/startup delay is added to this full-board harness.

The combined preparation targets pass 14 controls (3 model/result inventory,
3 mapped-runner, 6 source-retention and 2 mapping-stage controls) in
`build/observed_board_full_preparation_controls_20261006.log`.
They include wire-only bench/provenance mutations and rejection of altered
fault codes, unknown-data checks and full-memory counts; these controls are
not a full mapped-board execution. The current runner's actual CLI rejects
the live unfinished mapping with exit one before output creation in
`build/observed_mapped_board_current_running_parent_rejection_20261006.log`.
No full observed mapped-board numerical result exists yet.

```sh
make -f fpga/cmac/Makefile array-unisim-model-control-test
make -f fpga/cmac/Makefile array-unisim-model-control
make -f fpga/cmac/Makefile array-observed-mapped-control-test
# Only after the observable mapping completes all source/circuit/tap gates:
make -f fpga/cmac/Makefile array-observed-mapped-test \
  MAPPING_REPORT=build/rknpu-observable-board-mapping/COMPLETED_RUN/report.json
```

The further fresh native regression (actual make session 45060) completes
with exit zero in `build/fpga_preparation_regression_selected_observed_mapping_20261006.log`.
All 49 Python methods, 1,087,299 numeric comparisons, 247 original entries and
three CMAC benches per simulator pass; all 82 cross-simulator memory images
and eleven host/direct images per simulator match. Its completed archive,
`verification/runs/2026-10-06-observed-board-preparation-production-regression/`,
has 1,466 verified members, 11,462,970 bytes and SHA256
`f98dc1fc0276e420651bbde5b51aa3d030de494ff5bcc2dafdb8fe8bad2aed86`.
Actual report timestamps start after 22:20 UTC on 2026-10-05 and finish
before their own final JSON writes. Production source remains unchanged at
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`;
the new preparation tools/controls and mapped candidates are separate gates,
not covered by this native production pass.

The fresh production regression during these preparations completes with
actual make exit zero (session 69270), log
`build/fpga_preparation_regression_shared_candidate_20261006.log`.
Both simulators pass all 247 original entries and three raw-product benches;
49 Python methods, 1,087,299 numeric comparisons, 82 equal cross-simulator
memory images and eleven host/direct images per simulator also pass.
Production source remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
Only vector generators are held unchanged for concurrent tests; all test
targets run. The newly written reports and log are source/timestamp verified
and frozen in `verification/runs/2026-10-06-shared-candidate-production-regression/`:
1,466 verified members, 11,462,758 archive bytes, SHA256
`ccbff8190236eff19ebe3cb00e0f8626abd3b843ecd7c149a491182cfe1e4acf`.
This is fresh production native evidence, not testing the changed mapped
candidate or physical hardware. Generated checks and the complete root
SHA256 manifest also pass for the new preparation sources.

A further newly executed production regression completes with actual make
exit zero (session 57078), log
`build/fpga_preparation_regression_module_alias_20261006.log`. All the same
247 entries/three extra benches per simulator, 49 Python methods and
1,087,299 numeric comparisons pass; 82 cross-simulator and eleven host/direct
images per simulator match. The actual fresh timestamps, current unchanged
production source and all output hashes are verified by
`build/archive_paired_preparation_production_regression_20261006.py` and frozen
in `verification/runs/2026-10-06-paired-preparation-production-regression/`:
1,466 verified members, 11,463,169 bytes, SHA256
`8bca3dc0714ef79af8c4d2e3f2133af6488fd2541f52379f386d861deed2189d`.
The nested preparation tools have their separate controls above; this root
regression does not constitute their full numerical or physical acceptance.

The next fresh production run also completes (actual make session 67597,
exit zero), log `build/fpga_preparation_regression_unisim_and_binding_20261006.log`.
The same unchanged source and complete regression/image checks are independently
verified and frozen in `verification/runs/2026-10-06-unisim-preparation-production-regression/`:
1,466 members, 11,463,013 bytes, SHA256
`075b1bc3b47face3ac3078856eeacab82ea650ae82fe084269e6fd377590f8cd`.
Its archive checksum is independently checked. The experimental tools retain
their separate controls; no mapped numerical or physical acceptance is inferred.

## C32/K16 YPCB BRAM self-test candidate

`fpga/cmac/ypcb_cmac_array_top.sv` and
`rtl/cmac/rk_cmac_array_bram_demo.sv` now connect the new command-DMA/array
to the existing synchronous trace RAM and the YPCB reset/LED wrapper. The
separate source list is `fpga/cmac/array_sources.json`. The original C64
board top, production EW top and constraints are unchanged. This remains
the intended XC7K480T FFG1156-2 at 50 MHz; no DRC, timing or electrical
requirement is relaxed and no board programming is performed.

The new autonomous self-test initializes all 4,096 RAM halfwords, fetches
the unchanged 49-QWORD terminal K65 job, performs C32/K16 reduction and
acknowledged writes, then checks every RAM halfword. It uses the new finite
C32 corpus: two physical rows, AI=96, AO=32, twelve operand frames, 6,528
operand reads and 64 output writes. The old C64 output goldens and 12,288-read
schedule are not reused. Pass/fail latch until reset; watchdog/readback faults
reset the engine and local response ownership without resetting RAM contents.
The four physical trace windows are unchanged, not a runtime gather, a general
device allocator or a reduced-capacity CBUF.

`tools/cmac/gen_array_board.py` explicitly imports a source-verified reference
fixture once, refusing an overwrite. The packaged files under
`tests/cmac/array_data/` retain their hashes and original reference report.
ROM regeneration and `--check` work from those portable files, without the
scratch build tree. Consistency checking passes for the exact command SHA,
all 6,528 expected reads, 64 distinct-address finite writes and 4,096-halfword
ROM/readback image. These offline test-image checks are not HDL verification
or runtime CPU computation.

`tests/cmac/tb_cmac_array_bram_demo.sv` checks the new physical read/write
sequence, initialization/readback ownership, three-edge reset release,
off-edge reset assertion, sticky LED status, command/arithmetic/readback
reset recovery, command-memory fault, readback mismatch/X and watchdog abort.
Its first full-width Icarus smoke run is at
`build/rknpu-array-board/smoke-iverilog-1790002165055702382/report.json`;
Icarus 13.0 compilation passes without warnings. The first command-memory
fault test passes after all 4,096 halfwords are initialized: exactly one command
read, no operand reads or writes, the expected bus error, and sticky/quiescent
failure. The watchdog-abort case (mode 8) also passes: 4,096 initialized
halfwords, 196 command reads, 20 operand reads, zero writes/acknowledgments,
one expected fault and 12,812 cycles. The run checks sticky/quiescent failure
after the injected watchdog expiry; this is not a natural-timeout duration
test or a physical board result. The numerical smoke case (mode 0) now also
passes: 4,096 initialized and 4,096 checked halfwords, 196 command reads,
6,528 operand reads, 64 writes/acknowledgments, one successful job and 44,915
cycles. All three smoke cases pass at source manifest
`09f41e33f3f5eaf43881ad2bad47d724e618204970448e50c8c88ea18f68a008`.
The source-bound archive is `verification/runs/2026-09-22-array-board-smoke/`
(264 verified members). The full nine-case four-state suite completed at
`build/rknpu-array-board/full-iverilog-1790008149115028405/report.json`.
The terminal report, inspected on 2026-10-05, is
`PASS_RAW_ARRAY_BOARD_FULL_RTL_ONLY`: all modes 0..8 pass, including unknown
readback mode 7, reset during command/frame/readback, repeated success and
watchdog abort. The complete source-bound archive has 269 verified members,
SHA256 `87d1a747680364691bc8c92a88a2db220ca44dc24d443e36537e784167342dea`,
under `verification/runs/2026-10-05-array-board-full-four-state/`.
This closes the original baseline's full-board simulation prerequisite only;
it does not validate modified fixed-mode RTL, mapped arithmetic, timing/fit
or the physical card.

`tools/cmac/test_array_board_hier.py` adds a separate two-state replay of the
unchanged board bench with the source-verified optimized CMAC library. It
requires the passing Icarus smoke report and exact source/artifact hashes,
checks actual generated library calls, and runs modes 0..6 and 8 with all
original count, numerical, reset and fault assertions. Mode 7 is explicitly
four-state-only; the full nine-mode Icarus physical-build prerequisite is
unchanged. No raw command, ROM image, golden, RTL or electrical constraint
is modified by this runner.

The first run, `two-state-hierarchical-1790009127579281113`, failed on the
intentional synchronized-reset lint diagnostic previously documented for the
earlier board top. Source review confirms asynchronous transaction-state reset
and synchronous BRAM transaction enables, without RAM data reset. The runner
now records exactly one `SYNCASYNCNET` at `ypcb_cmac_array_top.sv:9`; all other
local DUT diagnostics fail. The failed report is preserved. The fresh run at
`build/rknpu-array-board/two-state-hierarchical-1790009222786041132/report.json`
has passed generation/library-use checks, compilation (207.431 seconds), and
the complete K65 numerical case (461.922 seconds). Its mode-0 result exactly
matches the completed Icarus smoke result: 6,528 operand reads, 64 acknowledged
writes, 4,096 initialized and checked halfwords, and 44,915 cycles. Mode 1 also
passes with exactly one command read, no operand reads/writes, the expected
fault and sticky/quiescent failure (12,313 cycles), matching Icarus. Mode 2 now
also passes after 315.220 seconds: all 6,528 operand reads and 64 output
acknowledgments complete, then the first readback detects the injected mismatch
and stays faulted/quiescent (32,630 cycles). Mode 3 passes reset during command
fetch and full numerical restart after 540.622 seconds: one reset, one
successful job, all 6,528 operand reads, 64 acknowledged writes and 4,096
readback checks; the restarted job takes 44,915 cycles. Mode 4 also passes
reset after an accepted C32 frame (562.663 seconds), with the same complete
fresh-job counts, numerical outputs and readback checks. Mode 5 passes reset
during readback after 742.823 seconds, again completing the entire restarted
job with all 4,096 readback checks. Mode 6 passes reset/repeat after success
(846.986 seconds), completing two jobs with one reset; the final job retains
all 6,528 operand reads, 64 acknowledged writes and 4,096 readback checks.
Mode 8 passes injected watchdog expiry (112.208 seconds): 196 command reads,
20 operand reads, zero writes/acks, sticky fault and quiescence.
All eight two-state cases now pass, with final source/artifact validation:
`PASS_RAW_ARRAY_BOARD_TWO_STATE_HIERARCHICAL_ONLY`, source manifest
`f6a289e097a192d72b872ebc56ce9f989f662b1afbe50b8b57363d352adb1b39`.
The four-state-only unknown-readback case is not included. This pass does
not satisfy the full nine-case Icarus physical-build gate.
An added negative build-control case rejects its distinct two-state success
status at the unchanged full-Icarus gate. All nine control methods pass again
on Tcl 9.0.3 and Xilinx Tcl 8.6.13; source-bound mock evidence is archived at
`verification/runs/2026-09-22-array-build-two-state-gate/`. This is not Vivado
execution or physical signoff.

`make generated-check` and the portable board-ROM check pass after this
increment. A fresh production `make -o vectors -o cmac-vectors test` exits zero,
with its log at `build/array_board_production_regression_20260921.log`: 49 Python
methods, 1,087,299 C++ comparisons, and 247 tests plus three CMAC benches in
each of Verilator 5.048 and Icarus 13.0. The
two vector-generation targets are explicitly held unchanged to preserve the
source-pinned fixtures used by simultaneous candidate tests; all test targets
still run. That production regression does not cover the new nested board
sources, which require the separate test above.

```sh
make -f fpga/cmac/Makefile array-board-check
make -f fpga/cmac/Makefile array-board-test SUITE=smoke
make -f fpga/cmac/Makefile array-board-test SUITE=full
make -f fpga/cmac/Makefile array-board-hier-test \
  BOARD_REPORT=build/rknpu-array-board/smoke-iverilog-<run>/report.json \
  CMAC_REPORT=build/rknpu-cmac-array/c32k16/hierarchical-o2-<run>/report.json \
  CACC_REPORT=build/rknpu-cacc-array/c32k16/verilator-<run>/report.json \
  OUTPUT_REPORT=build/rknpu-frame-output/verilator-<run>/report.json
```

## Prepared Vivado array build, not an implementation result

`tools/cmac/vivado_array.py` renders `fpga/cmac/build_array.tcl.in` from the
separate array source manifest and saves a source snapshot and ROM check.
`prepare` runs no Vivado commands and returns `PREPARED_ARRAY_VIVADO_ONLY`.
The current prepared job is
`build/rknpu-array-vivado/prepare-1791207556155270773/report.json`.

`run` requires a completed, source-matching **full nine-case board RTL** report,
all test/command successes, simulator provenance and matching artifact hashes.
It rejects a core-only, smoke, stale, failed or running report. It then requires
explicit board confirmation, full `vivado` (not Lab), and exact
`xc7k480tffg1156-2` part support. The real current incomplete smoke report was
passed to this gate and correctly rejected before launching Vivado at
`build/rknpu-array-vivado/run-1790003167203178619/report.json`.
This expected rejection is not a physical build attempt.

The Tcl preserves the existing pin constraints, legal paired configuration
settings, BRAM requirement, finite nonnegative setup/hold slack checks and
blocking/unknown DRC-severity rejection. It additionally verifies the named
clock remains 20 ns and adds the documented
[pulse-width report](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/report_pulse_width).
It stops at checkpoints/reports and explicitly rejects bitstream emission;
there is no hardware connection or programming command. Even a future
successful run is labeled `ROUTED_ARRAY_CHECKPOINT_REVIEW_REQUIRED`, not
physical signoff: unconstrained paths, pulse-width results, warnings and
actual board electrical facts still require review. No values are guessed.

The nine build-control test methods in `tests/cmac/test_array_build.py` pass
under both Tcl 9.0.3 and the installed Xilinx Tcl 8.6.13. All Vivado operations
are mocked; these tests create no checkpoint or bitstream and validate no HDL,
part support, physical timing or DRC. Source-bound report:
`build/rknpu-array-build-control/1790003115115168186/report.json`.
The source-bound mock evidence is archived under
`verification/runs/2026-09-21-array-build-control/` (254 verified members).
The first Xilinx-interpreter attempt failed at startup because its library
path was missing; that failure remains recorded. The corrected runner sets
only the child process's vendor library/Tcl paths and retains the same tests.

```sh
make -f fpga/cmac/Makefile array-build-control-test
make -f fpga/cmac/Makefile array-vivado-prepare
# Only once the full board RTL suite passes and full Vivado is installed:
RK_CONFIRM_BOARD=YPCB_00338_1P1 make -f fpga/cmac/Makefile array-vivado \
  BOARD_REPORT=build/rknpu-array-board/full-iverilog-<run>/report.json
```

Vivado status update: the user later installed the full suite at
`/home/fedora/vivado/2026.1/Vivado`; its version command reports
`vivado v2026.1` (not Lab). The source-bound C32/K16 synthesis-only attempt is
recorded at
[`build/rknpu-dsp-prefix-array-vivado/synth-1791552618590027876/report.json`](../build/rknpu-dsp-prefix-array-vivado/synth-1791552618590027876/report.json).
Its source, parent-artifact and ROM checks pass, but Vivado exits before
synthesis with `valid license was not found` (exit 42). No synthesized design,
checkpoint, implementation or bitstream was produced. The user retains the
AMD account login/license acceptance; no license bypass was attempted. The
earlier wget handoff is historical, not the current installation state.

### Reviewed checkpoint to bitstream, prepared but unrun

`tools/cmac/emit_array_bitstream.py` and `fpga/cmac/emit_array.tcl.in` add a
separate opt-in emission stage; the existing implementation still stops at a
routed checkpoint. This is preparation for the user's bitstream objective,
not a Vivado result. The emitter requires the matching completed full-board
simulation, current implementation source/artifact hashes, the same Vivado
version and an explicit human review of all six reports, routed DCP and build
script. `review-template` binds their hashes but sets **every acceptance to
false**. Board/part/pins/clock/reset, configuration-bank supply/strap, routes,
BRAM, utilization/route completion, setup/hold, unconstrained paths/exceptions,
pulse width and DRC/warnings must each be reviewed. A reviewer and physical
board-evidence record are required; no helper auto-accepts those facts.

The real routed checkpoint must already contain the reviewed electrical pair.
Emission cannot set properties, waive DRC, change constraints or reroute; it
rechecks the part, voltage/CFGBVS, 20 ns clock, BRAM, setup/hold and DRC before
`write_bitstream`. `RK_CONFIRM_BOARD=YPCB_00338_1P1` and
`RK_EMIT_BITSTREAM=1` remain explicit prerequisites. No hardware target, FPGA
programming or flash command exists. Modified fixed-mode RTL will need its
own fresh integration/build evidence before it can use this path.

```sh
# After the source-matching routed implementation exists:
make -f fpga/cmac/Makefile array-bitstream-review \
  IMPLEMENTATION_REPORT=build/rknpu-array-vivado/run-<run>/report.json
# Review actual reports and physical evidence, then complete that review.json.
RK_CONFIRM_BOARD=YPCB_00338_1P1 RK_EMIT_BITSTREAM=1 \
  make -f fpga/cmac/Makefile array-bitstream \
  IMPLEMENTATION_REPORT=build/rknpu-array-vivado/run-<run>/report.json \
  REVIEW=build/rknpu-array-bitstream/review-template-<run>/review.json
```

The YPCB-specific reference
`/home/fedora/ypcb/openFPGALoader/bpiOverJtag/constr_xc7k_ffg1156.xdc`
at commit `98fea265076226e56d884137228ba5745a762455` specifies 1.8 V/GND.
That is source evidence for this board model, not physical confirmation of
the current card. It has not been silently selected as this build's settings.
