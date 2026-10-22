# Isolated DSP-lane carry-prefix experiment

The candidate passes its binary comparator proof and all 135,680 native HDL
fixtures. Fresh identical-interface XC7 mapping measures 657 LUT primitives
for the original compensated DSP lane and 616 for the prefix lane, with one
DSP48E1 each: 41 fewer LUTs, or 6.24%. These are isolated mapping counts,
not full-array savings or physical LUT-site occupancy.

The [candidate lane](../rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv)
is a byte-checked derivative with only three edits: the module name, removal
of the low mask, and replacement of the discarded-bit comparison with the
[prefix helper](../rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv).
It is not installed in the original DSP array or production top. Separate
full prefix-array and raw-command board-compile candidates are now prepared.
No encoder, command words, donor multiply/bias/compensation/tag arithmetic,
transport or runtime CPU arithmetic/layout path is changed.

## Contract and actual evidence

The helper compares the low `4*shift` bits of the first donor row and biased
product sum, for shifts 0..7. A fresh real SAT miter retains all 67 independent
binary inputs. The positive proof passes; a freshly inverted mismatch produces
a real countermodel with exit one. Its indexed selection is audited as one
unsigned 8-by-3-bit `$shiftx` selecting one bit directly with the shift port.
State, assumptions, hidden multiplication, constant/aliased inputs and unknown
graph cells remain explicit failures.

Exact source derivation composes that lemma into binary identity with the
original compensated lane on all 37 input and 40 lane/tag output bits. This
is not a new monolithic donor-product SAT proof. The unchanged native fixture
bench separately checks 135,680 cases, seed `0x3588d501`, with original case
inequality, watchdog and count assertions. A fresh corrupted-result HDL
negative exits one as expected.

Tools actually executed: Yosys 0.65 at
`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`, Icarus/VVP 13.0. The
[completed report](../build/rknpu-dsp-prefix-carry/1791274959598085907/report.json)
records source fingerprint
`0ed4e977bbfbee2a36a2a7a8d5489916de7d5b57addd00386dd66d267abf6b80`,
commands, source snapshots, graphs, models, binaries and stimulus bindings.
Six software harness controls and generated-source checks also pass, not
additional numerical or FPGA tests.

Both actual harness failures retain their executed sources: initial rejection
of the indexed-selection graph, and later rejection of ABC's combinational
notice. The corrected gate audits exactly three copies of each source-specific
NVIDIA memory-lowering notice and one ABC notice at the observed `scorr` step,
and separately requires no flip-flops. Unknown messages and changed
sites/counts/context fail. ABC's combinational early-return cases are in its
[primary source](https://github.com/berkeley-abc/abc/blob/master/src/base/abci/abc.c).
No physical electrical, DRC or timing gate is relaxed.

The [source-bound archive](../verification/runs/2026-10-06-dsp-prefix-binary-area/index.json)
contains 76 verified members/3,487,864 bytes, including both failure archives.
SHA256: `e46de1ceae79f775f1da8a3054cfc42908754f8497592b21ff1b03feed47d5f1`.

## Actual mapped replay and full-array preparation

The [mapped replay report](../build/rknpu-dsp-prefix-mapped-binary/1791276416466370316/report.json)
now completes with 135,680 comparisons in each of the fresh native and actual
mapped phases, seed `0x3588d501`, and two real corrupted-result negatives with
exit one. The mapped positive takes 949.103 seconds. Actual hardware remains
616 LUT primitives and one DSP48E1. Standard Yosys export/readback checks
every port bit, cell type, parameter and wire incidence. Mapped compilation
excludes the native prefix candidate and uses the unchanged installed Xilinx
functional model. This is binary fixture evidence, not exhaustive mapped/X
equivalence or physical timing simulation.

Its [completed archive](../verification/runs/2026-10-06-dsp-prefix-actual-mapped-lane/index.json)
preserves 123 verified members/42,066,507 uncompressed bytes, SHA256
`2240b5722eb611a82f6961f366571efa944ceab1c744212b6648773eecb91dec`.
Source fingerprint:
`d8a60982658d1971456f99eb27b2e325a805aaab9b24ec483dee1827eb19aad3`.

The [cell](../rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix.sv) and
[array](../rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix.sv) are literal
derivatives retaining donor FP44 encoding, NaN priority, masks, tags, warmup,
hold/reset cancellation and sticky faults. Real native Yosys elaboration
checks C32/K16/TAG35, sixteen kernels, all 512 parallel lanes and independent
kernel operand stripes. Its [preparation archive](../verification/runs/2026-10-06-dsp-prefix-full-array-preparation/index.json)
preserves 72 verified members/2,906,873 uncompressed bytes, SHA256
`5b71775da684e218e23c7f72cde59ae538235b010fd74b48933088a6c8d6ab1b`.
Nineteen software controls, generated-source checks and an independent
source/graph/diagnostics audit pass; a real admission command rejects the
then-pending mapped parent. These are preparation, not array numerical tests.

After its own mapped parent completed, the independent full-array native
runner started at
`build/rknpu-dsp-prefix-array-native/1791277744017318986/report.json`.
It compiles in 40.195 seconds and catches the first-frame wrong golden in
73.588 seconds. The unchanged 208-frame positive now passes in 5,305.372
seconds, with 3,328 checked outputs, 3,312 retired outputs, 520 held cycles,
sixteen reset-canceled outputs and the native X-input fault case. Icarus and
vvp are both 13.0; seed remains `0x35883216`. The completed source fingerprint
is `001a6b3cdd08df1aab050ced2194ab46875352d6fb9d8681755a398b4381e5d3`.
Actual source/compiler/binary/stimulus/log bindings are reverified.
Its [completed native archive](../verification/runs/2026-10-06-dsp-prefix-full-native-pass/index.json)
preserves 87 verified members/70,311,913 uncompressed bytes, SHA256
`6ec8fdd3fa10a2e1591c4676bebd2deadd10ff431da8c1696682582817e3d16f`.
This is the full native fixture gate, not exhaustive-X, mapped, raw-board,
physical or RK-silicon acceptance.

The first full-array XC7 run returns zero from Yosys in 1,237.333 seconds,
but its native-only diagnostic checker rejects two ABC `scorr`
combinational-cut notices. The report remains **FAIL**, not accepted area.
Its [executed-source failure archive](../verification/runs/2026-10-06-dsp-prefix-array-mapping-diagnostics-failure/index.json)
preserves 69 members/783,887,762 uncompressed bytes, including all actual
graphs and netlist, SHA256
`7b1c05453e4418dd97883296699c2a401633c68cdb5443db5a4c51463a3627a3`.
The independent checksum passes. The corrected checker requires exactly one
notice in each exact C32-kernel/top extraction, complete `scorr`/notice/`dc2`
lines and completed ABC reintegration, plus the same six source-specific donor
notices. Unknown messages, modules, counts and contexts still fail. Eight
controls pass; the initial control failure and checker/test snapshots are
retained after a negative caught incomplete `dc2` line matching. No RTL,
resource, electrical, DRC or timing check is relaxed.

A fresh full synthesis, not reuse of the failed run's netlist, now completes at
[its own area report](../build/rknpu-dsp-prefix-array-area/1791280469545641864/report.json), source
`13fc1cf854926b5af17529afcfd84ad85d9b8083fd1e112182af858400568c57`.
Actual Yosys execution takes 978.315 seconds; the make supervisor exits zero.
All native/partition/flattened structural and diagnostic gates pass, retaining
sixteen kernels, 512 DSP48E1s, 398,168 LUT primitives and 742 FDCEs. That is
9,184 fewer LUT primitives (2.25%) than the original full DSP array's 407,352,
not the isolated leaf's 6.24%. Yosys estimates 258,295 logic cells; neither that
estimate nor primitive counts prove placed fit. Complete-board mapping and
physical packing, setup/hold, electrical and DRC checks remain mandatory.

Its [completed area archive](../verification/runs/2026-10-06-dsp-prefix-full-array-area/index.json)
preserves 126 verified members/813,738,102 uncompressed bytes, SHA256
`3fb7b98a7fe50fee69b1b4136a88db96e490531279527ef70db3a5ebb6bbd1de`.
The independent replay admission verifier checks actual native operand stripes,
partition/flat counts, all saved source/artifact bindings and exact diagnostics
before and after archiving. This is area/structure evidence, not numerical
array or physical acceptance.

## Raw-board compile and full mapped-array replay preparation

The [actual raw-board preparation](../build/rknpu-dsp-prefix-board-preparation/1791279040601062152/report.json)
completes ROM checking and Icarus 13 compilation; compilation takes 52.436
seconds. Source fingerprint:
`7e5fee8ad4c88dbf84971be366d9a0b68eb4a527bb2eb7a18f25dd74c30e7cc1`.
One literal array substitution retains the original final command words,
decoder, DMA, CACC, output writer, BRAM, reset/fault/watchdog bench, exact part
and 20 ns clock. The compiled hierarchy has one prefix array, sixteen cells,
512 lanes and 512 carry helpers, with original/fixed/DSP fallbacks rejected.
No numerical board mode runs during compilation.

The [nine-mode replay runner](../tools/cmac/replay_dsp_prefix_board.py)
requires this variant's completed full native array and mapped leaf, plus an
actual source-bound donor-to-compensated-to-prefix binary composition
certificate. Its endpoints are 37 input/40 output bits with the separate
67-input carry comparator lemma; it is not a new monolithic SAT or all-X proof.
Real read-only admission verifies the compiled board and certificate. A real
earlier replay command refuses the then-pending native report (Python exit
one, make exit two); that refusal is preserved. After native completion, a
fresh full nine-mode execution starts at
`build/rknpu-dsp-prefix-board-replay/1791283576368477085/report.json`.
Its original raw QWORDs, compiled board, operands and output goldens remain
bound. All nine original modes now pass actual vvp execution in 954.776,
237.644, 1,495.357, 879.884, 696.393, 1,183.551, 1,482.184, 780.871 and
136.821 seconds respectively. The suite completes at 12:57:51 UTC, with the
original X-readback fault case, resets/restart, raw-command/readback faults
and watchdog checks intact. Its source remains
`c14e5d8cb50d7eff42739880b10bfdc29c7ff1ef8edde960034dc0a06db49577`.
This is full native raw-board fixture acceptance, not physical FPGA, full-array
mapped or RK compatibility acceptance. No all-X leaf equivalence is claimed.
The [completed all-nine-mode archive](../verification/runs/2026-10-06-dsp-prefix-full-nine-mode-raw-board/index.json)
preserves 507 verified members/16,460,558 compressed bytes, SHA256
`ecb008874c69d4141c67a937f2d429b9b2218ecd18b94a6e68edae63c9e2ccee`.
Executed binary, raw inputs, exact mode logs and independently revalidated
native/compiled/composition parents are frozen; no old mode result transfers.

The [full mapped-array runner](../tools/cmac/test_dsp_prefix_mapped_array.py)
and [own-area verifier](../tools/cmac/dsp_prefix_mapped_contract.py) now retain
all 208 binary frames/3,328 outputs, hold/tag/reset checks and the real
first-frame wrong-golden negative. The actual 32-DSP kernel is compiled once
but instantiated sixteen times; no arithmetic RTL replaces it. Export/readback
checks every port bit, cell type, parameter and wire incidence, retaining actual
DSP string parameters and the unchanged installed primitive model. Native and
area parents must be completed, source-current and bind the same prefix leaf.
During preparation, an actual command rejects the then-pending area report
with exit one before run creation. Both area and native-array parents are
now complete. Fresh full mapped execution starts at
`build/rknpu-dsp-prefix-array-mapped-binary/1791283708506179317/report.json`;
actual export/readback identity passes. The kernel compiler subsequently exits
zero but the original diagnostic gate fails before top generation, as recorded
below. No full mapped numerical result is claimed yet.
Its actual compiler diagnostics are still unadmitted. A read-only audit of
the actual mapped JSON finds all 449 undriven-warning aliases/4,673 bits
disconnected from every port and primitive pin. This does not admit the
remaining library warnings, prove the full array numerically, or change the
original source-bound diagnostic checker.
After area completion, a fresh make command passes the real own-area
admission verifier and then refuses the still-pending native parent (Python
exit one, make exit two). Its actual log is
`build/dsp_prefix_full_mapped_array_rejects_pending_native_after_area_pass_20261006.log`;
no mapped execution directory or numerical result is produced.

Fifty-three preceding software controls pass together with no skips: six carry,
seven mapped-leaf, six native-array, eight area, four board-preparation,
eleven board-replay and eleven mapped-array controls. The last group includes
a real small Yosys 0.65 export/readback control, not full-array simulation.
The new whole-board mapper adds twelve controls and the frontend preparation
adds four; a separate real library-export control adds one. All 70 current
controls pass through the final aggregate make target,
without skips. The [current source-bound control archive](../verification/runs/2026-10-06-dsp-prefix-70-profile-alias-controls/index.json)
preserves 126 verified members/1,182,625 uncompressed bytes, SHA256
`7192c8fe7ba09274f0359169e2242cfca0327740b2aeeaca219b3d8377cd1dec`.
A control caught missing full port validation in the frontend's
wire-only wrapper; the executed failing runner/test and log are preserved,
and the full port guard was added without changing the negative expectation.
Generated-source checks pass. These software controls are not HDL numerical
or physical FPGA acceptance.

The [whole-board mapper](../tools/cmac/map_dsp_prefix_board.py) requires its
own completed area and all nine raw-board modes, checks source-bound binary
composition, and reuses the actual 32-DSP kernel sixteen times. Primitive
type, parameter and every pin/wire incidence must stay unchanged; BRAM,
nonconstant original board IO, exact part and 20 ns clock remain required.
After the all-nine-mode raw-board completion, actual whole-board mapping is
launched with this variant's own completed area and board reports at
`build/rknpu-dsp-prefix-board-area/1791291727991236024/report.json`, source
`be55d57e08c7e2807d4785b6d116393084d9c7f8fde04ae32d6bc88442a1c9ba`.
Actual Yosys synthesis finishes in 2,737.486 seconds and exits zero, but the
strict diagnostic gate rejects early generated-temporary driver notices and
RAM port-width normalizations. The report remains FAIL. Its
[executed-source archive](../verification/runs/2026-10-06-dsp-prefix-whole-board-diagnostic-failure/index.json)
preserves all 433 members, including the complete graph/netlist; the independent
archive checksum passes. A corrected read-only
[diagnostic/structure inventory](../build/dsp_prefix_whole_board_diagnostic_inventory_exact_source_sites_20261006.json)
accounts for exactly 288 initial driver notices, 32 RAM width notices, three
source-lowering notices and one shell ABC notice. The three later CHECK passes
report zero problems. Every early notice is matched to its exact source
expression, generated name and bit span; all sixteen actual mapped kernels
retain original port/cell/parameter/pin incidence. Final counts are 442,838 LUT
primitives, 17,310 flip-flops, 512 CMAC plus three shell DSPs and six RAMB36E1s.
This accounting does not admit the mapping warnings or prove pre-normalization
RAM padding/dataflow, numerical replay or physical fit. The original inventory
parser failure is [preserved before correction](../verification/runs/2026-10-06-dsp-prefix-board-inventory-parser-failure/index.json).
A separate
[real frontend preparation](../tools/cmac/prepare_dsp_prefix_board_mapping.py)
loads that same imported array and the original native board shell. It stops
before synthesis/ABC and cannot replace the mapper's numerical prerequisites
or establish complete-board resources, mapped numerical behavior or fit.

Its first actual full frontend returns one from Yosys after 283.424 seconds:
CHECK reports zero problems, but JSON export fails on processes inside the
pre-existing blackbox FDCE library definition. That is **FAIL**, not prepared
hardware. The [executed failure archive](../verification/runs/2026-10-06-dsp-prefix-board-frontend-library-process-failure/index.json)
preserves 193 verified members/114,321,757 uncompressed bytes, including the
partial JSON and original executed sources/script, SHA256
`f8f8c67bcfb9933c13c4fe65dff85e9b44e67d56ac327f89259d1c6ddce6d587`.
Its independent checksum passes. Standard design-only JSON export now omits
only existing library blackbox definitions; no hardware module is converted
into a blackbox. A real DSP/FDCE control reproduces the original failure and
passes exact native-module/primitive-parameter/pin-incidence identity with the
design-only export. Its initial comparison failure is retained: the baseline
lacked hierarchy annotation before cleanup, which removed its native bridge.
Matching hierarchy setup was added without weakening circuit identity.
The second real frontend returns zero from Yosys in 411.960 seconds but
remains **FAIL**: its preparation checker rejects the original profile's
register-memory lowering notice. A subsequent read-only graph audit also
finds that the imported implementation retains the original array's `hdlname`,
which must not be counted as a second parameter wrapper. Its
[immutable executed-source failure archive](../verification/runs/2026-10-06-dsp-prefix-board-frontend-profile-diagnostic-failure/index.json)
preserves 193 verified members/118,715,196 uncompressed bytes, SHA256
`22fcdd2a1cf7e6d46b0bcd023870619ec58dc3146b1d1e72afdd1d3c69314f12`.
The diagnostic guard now admits exactly the two donor notices and the
source-specific profile notice at line 154; any other warning still fails.
The wrapper guard excludes only the separately circuit-verified mapped array.
No hardware logic, supported register field or negative expectation changes.

The fresh third run now completes at
`build/rknpu-dsp-prefix-board-mapping-preparation/1791287585409515446/report.json`,
source `416afc693761a9c62176dcca0a5212365031a91e46551b1465ff0a28db385bfb`.
Actual Yosys 0.65 frontend execution takes 169.251 seconds and retains one
exact wire-only parameter wrapper, one unchanged imported array and sixteen
unchanged 32-DSP mapped kernels. All 512 CMAC DSPs remain. Its
[completed archive](../verification/runs/2026-10-06-dsp-prefix-board-mapping-preparation/index.json)
preserves 228 verified members/118,972,621 uncompressed bytes, SHA256
`d2935a0db30be5892c095defeab2ced258f9d8eb3d9b4ea0f17331c5bfa42501`;
the independent checksum passes. Both original failures remain FAIL.
This establishes frontend preparation only: the native shell is not mapped,
and no whole-board resources, mapped numerical or physical result transfers.

The [completed raw-board/replay preparation archive](../verification/runs/2026-10-06-dsp-prefix-raw-board-preparation/index.json)
preserves 431 verified members/112,328,879 uncompressed bytes, SHA256
`4f27d5746b67411d5239a9bdf6f6e5b797a20c909b626e4bf5d3b249c776911b`.
It includes the actual board binary, source snapshots, endpoint certificate,
53 controls, both pending-parent refusals and preserved checker/archiver
failures. Mutable running native/area reports are excluded. No board mode or
full mapped-array numerical acceptance is inferred from this archive.

## Prefix-specific Vivado checkpoint preparation

The [prefix Vivado driver](../tools/cmac/vivado_dsp_prefix_array.py) is now
prepared at
`build/rknpu-dsp-prefix-array-vivado/prepare-1791288047721885832/report.json`,
source `b0508d3be9c28960608f074052ad13fc859675ad796867f70968e37d8215c741`.
Its caller-independent closure binds 77 source files. Only the CMAC join is
substituted; raw K65 words, DMA, CACC/output conversion, BRAM, reset/LEDs,
`xc7k480tffg1156-2`, original pins and 20 ns clock are unchanged. Its run
requires this prefix variant's own completed area/native/mapped-binary and
all nine four-state raw-board reports; old compensated/fixed results cannot
authorize it. It checks sixteen 32-DSP kernels after synthesis and again after
routing and retains all original electrical, setup/hold, DRC and review gates.
No preparation report authorizes bitstream emission or programming.

All 18 build/admission methods pass under system Tcl 9.0.3 and vendor Tcl
8.6.13, with **all Vivado operations mocked**. The first direct unwrapped
vendor runtime fails before build controls because `libtcl8.6.so` is missing
from its library environment; its failed log remains. The installed AMD
loader supplies that environment, and the fresh full 18-method run passes.
No tool installation, RTL or test expectation was changed. The
[source-bound checkpoint-preparation archive](../verification/runs/2026-10-06-dsp-prefix-vivado-checkpoint-preparation/index.json)
preserves 173 verified members/400,266 compressed bytes, SHA256
`c7f8e4731fadbb51a42eb790a32287bbc64c31b29821d05c6e9f2427a575e31f`.
This is source/script preparation and mocked safety controls, not actual
Vivado synthesis, placement, timing/DRC signoff or a ready-to-test bitstream.
Full Vivado is still unavailable on PATH; the user handles AMD download/login.
The fresh combined target also passes all 88 software/export/preparation
methods with no skips; 18 of these mock Vivado and are not FPGA tests.

## Actual primitive-model diagnostic controls

The [isolated model runner](../tools/cmac/test_dsp_prefix_primitive_models.py)
checks the unchanged installed DSP48E1/CARRY4 model, not replacement arithmetic
or a CMAC execution fallback. It verifies every parameter and constant pin
against all 32 DSPs in the actual mapped kernel. Its Verilator run completes
4,259,904 DSP comparisons (64 signed boundary pairs, all 2,048 squared
11-bit mantissa pairs and 65,536 seeded signed pairs), 1,024 binary carry
cases and both real first-case wrong-golden negatives. Seed is `35883216`;
the positive takes 17.490 seconds. Verilator 5.048 executes the actual model.
Four software source/result controls pass, and the combined preparation target
now passes all 92 preceding methods without skips. The Icarus control now
completes the same full DSP/binary carry corpus and all 1,048,576 four-state
carry combinations. Its positive takes 1,706.964 seconds; the real carry
negative takes 1,192.661 seconds, traversing the original full DSP corpus
before rejecting carry case zero. No cases are shortened or skipped.

The [completed Verilator model archive](../verification/runs/2026-10-06-dsp-prefix-primitive-model-verilator/index.json)
preserves 50 verified members/1,367,128 compressed bytes, SHA256
`e27e7fce2e5660e699b504a60f8b9a631e4cca7fc383b0af22d17a9658b7e3db`.
It also freezes the read-only disconnected-alias audit and an immutable prefix
of the then-live main compiler log. Live Icarus/full-array/raw-board results
are excluded. Compiler-diagnostic admission, full-array, raw-board and physical
acceptance remain false; isolated numerical success cannot waive warnings.

The [completed source-bound Icarus archive](../verification/runs/2026-10-06-dsp-prefix-primitive-model-iverilog/index.json)
preserves 18 verified members/958,649 compressed bytes, SHA256
`ce5be3ac5551c1cb159ac610901766e12435129996b8a4e34a7c233e27982140`.
It completes at 13:15:37 UTC with source
`5dd8a5c107cb9f97ad0be29cbc6cce7d05da355efb3ddaad81b94e08d1da4e55`.
This is one unchanged primitive model, not full mapped-array acceptance.

## Actual omitted-input cone and completed compiler diagnostic failure

The full mapped-array compiler finishes at 13:21:17 UTC. Verilator exits zero
after 8,919.809 seconds, but the original strict harness rejects `PINMISSING`
at exported source line 170398, before top generation or numerical replay.
The [completed failed report](../build/rknpu-dsp-prefix-array-mapped-binary/1791283708506179317/report.json)
retains its executed source and original failure; no PASS is transferred from
earlier isolated or native results. Its source is
`467cef465d6d5fa1d3c93aba98c79cc4a17d0676e0ceb79baf7a0242251d37d1`.
The completed compiled library is preserved for a future separately audited
continuation, not accepted for replay here.
The [executed-source compiler-failure archive](../verification/runs/2026-10-06-dsp-prefix-mapped-compile-diagnostic-failure/index.json)
preserves 179 verified members/50,309,059 compressed bytes, including all 87
completed compile products, SHA256
`b703a49b3f16d2ba156f735b9f0ec79536ff8685942ac0be5e68b335d718b5c4`.
The original diagnostic rejection is reproduced before and after packaging.

The [new test-only cone runner](../tools/cmac/audit_dsp_prefix_pin_cone.py)
elaborates the unchanged installed Yosys DSP48E1 functional model with the
parameters/constants of all 32 actual-kernel DSPs. Every omitted input is an
independently unconstrained top-level bit, not tied off. Its flattened P cone
contains one multiplier, four adders and one NOT; it depends on exactly A[24:0]
and B[17:0], and none of the 26 omitted input bits. No stateful or opaque cell
is admitted into that cone. The real legal `AREG=ACASCREG=1` counterexample
adds an `$sdffe`, reaches CEA2/CLK/RSTA, and fails the zero-register gate.
Six software controls reject bad shapes, state, unknown cells, missing operands,
undriven outputs and duplicate drivers.

The [completed actual-cone archive](../verification/runs/2026-10-06-dsp-prefix-omitted-pin-cone/index.json)
preserves 28 verified members/978,568 compressed bytes, SHA256
`24b97dc14df47ea1cbe80aa28015d7fab092075fd19d07c4c3ea7d704beb34e6`.
Yosys 0.65 takes 2.302/2.286 seconds for the registered negative/actual positive
at source `52bd1534c75cce075159c8aaeb4bbe70338d9679378e7243e9ba724adec097bc`.
The YOSYS macro removes simulation-only checks; model bytes are unchanged.
Model-wide tri-state frontend notices are recorded, not admitted as main
compiler diagnostics. This is structural elaboration, not numerical equivalence,
all-X behavior or physical FPGA evidence.

The [completed read-only compiler inventory](../build/rknpu-dsp-prefix-compile-inventory/1791293575685709813/report.json)
records all 10,594 notices. Its 1,152 `PINMISSING` notices bijectively identify
the exact 32 actual mapped DSP source sites: 832 omitted-input notices and 320
omitted-output notices. Four controls reject missing, duplicate, connected/
unknown pins, wrong instances and unparsed diagnostics; the combined primitive/
cone/inventory target passes fourteen methods. Other classes remain unadmitted:
449 UNDRIVEN, eight WIDTHEXPAND, two WIDTHTRUNC, one PROCASSINIT, twelve COMBDLY
and one UNOPTFLAT, alongside existing metadata/unused notices. No blanket warning
waiver, DUT/model rewrite, arithmetic replacement or numerical/error expectation
change occurs.
The [completed inventory/control archive](../verification/runs/2026-10-06-dsp-prefix-completed-compile-inventory/index.json)
preserves 33 verified members/4,274,007 compressed bytes, SHA256
`8574bbce256900858ba7e9e1959a8dd3ea6d6fbe595d183374e96f4887dcad7c`.
That earlier archive admits no compiler diagnostic and excludes then-live
whole-board mapping and the isolated production regression. Both runs are now
terminal failures, not pending or transferable PASS results.

```sh
make -f fpga/cmac/Makefile array-dsp-prefix-diagnostic-preparation-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-pin-cone-test \
  MAPPED_REPORT=build/rknpu-dsp-prefix-array-mapped-binary/1791283708506179317/report.json
make -f fpga/cmac/Makefile array-dsp-prefix-compile-inventory-test \
  MAPPED_REPORT=build/rknpu-dsp-prefix-array-mapped-binary/1791283708506179317/report.json \
  CONE_REPORT=build/rknpu-dsp-prefix-pin-cone/1791292942878886716/report.json
```

## Actual model proof, exact diagnostic admission and generated-top continuation

The [unchanged-model binary proof](../tools/cmac/prove_dsp_prefix_actual_model.py)
now passes under all 74 unconstrained binary A/B/omitted input bits, comparing
all 48 P bits against signed A[24:0]*B plus the exact bias modulo 2^48.
The real one-bit wrong-golden SAT negative fails. Yosys 0.65 takes 1.439/1.427
seconds for negative/positive; no input assumptions, model substitution or
all-X claim is introduced. Source is
`1d817725c6669239fbb2196539b99908003d934d596f508fc8d826fdeac7d554`.
The [completed proof archive](../verification/runs/2026-10-06-dsp-prefix-actual-model-binary-proof/index.json)
has 34 verified members, SHA256
`b7d08ebf1d510951146c31e34db3942a21503d16a20c2d433b5d2316c0ea03f7`.
The [initial proof-shape failure](../verification/runs/2026-10-06-dsp-prefix-actual-model-proof-shape-failure/index.json)
remains preserved: standard `wreduce` resolved differing multiplier operand
widths before ordinary opt-merge; the mathematical miter and negative did not change.

The separate [closed-kernel admission](../tools/cmac/dsp_prefix_compile_admission.py)
now verifies the exact missing-pin bijection/disconnected omitted-input cone,
unobserved undriven aliases, fixed model width/initialization/combination sites,
bitwise-acyclic carry recurrence and the completed actual primitive controls.
It preserves the original failed compiler and qualifies only its unchanged
library for binary fixture replay. Unknown, changed and duplicated diagnostics
remain failures. Its first actual continuation reaches top generation: Verilator
returns zero after 80.282 seconds, but the exact-subset gate rejects two new
notices. The [214-member executed failure archive](../verification/runs/2026-10-06-dsp-prefix-mapped-continuation-top-diagnostic-failure/index.json)
retains this FAIL, the checker and all generated C++.

The [actual FDCE controls](../tools/cmac/test_dsp_prefix_fdce_startup.py) pass
129 startup/reset/enabled-clock/hold checks and a real first-check negative in
each of Verilator 5.048 and Icarus 13.0. All 742 actual array flops have INIT=X;
Icarus retains that unknown until reset, and both controls establish binary
state through reset rather than inventing an initial value. The full unchanged
bench resets before observing outputs after its 200 ns startup. Their
[68-member archive](../verification/runs/2026-10-06-dsp-prefix-actual-fdce-startup-reset-controls/index.json)
is isolated model evidence, not full-array acceptance. The second notice is
exactly a redundant alias [1:0] for invalid[6/8]; those bits retain real kernel
drivers and shell LUT consumers. The [top admission](../tools/cmac/dsp_prefix_top_compile_admission.py)
supports only those two exact source sites with this evidence.

A subsequent generated-top attempt passes both admissions but fails an
unexecuted combo-only library-operation expectation before C++ compilation.
The [130-member interface-guard failure archive](../verification/runs/2026-10-06-dsp-prefix-generated-top-interface-guard-failure/index.json)
honestly records that this early guard preceded the original run's source
fingerprint. Its unchanged current harness, actual error and copied products
are frozen. Actual Verilator divides the inputs between combo_update
(data/masks) and seq_update (any weight change, not a clock edge); both bridge
functions apply exact-width operands and evaluate the same mapped model.
The [new interface contract](../tools/cmac/dsp_prefix_protected_library_contract.py)
checks complete operand/output coverage, callbacks and wrapper/library
protection hash. Four software controls reject omitted operands, wrong widths,
missing evaluation, changed hashes and edge-sensitive weight callbacks.
The first source-bound full replay matches all 3,328 original outputs from
208 frames, including 3,312 retired outputs, sixteen reset cancellations and
520 held cycles. Its fresh wrong-golden negative fails as expected. However,
the stock make recipe masks two `ar` errors while returning zero. The
[291-member qualified archive](../verification/runs/2026-10-06-dsp-prefix-full-mapped-replay-unadmitted-ar-diagnostics/index.json)
preserves that actual numerical result, source, binary and installed make
template, but explicitly refuses complete build/full-mapped acceptance. Its
SHA256 is `9f41f7ababa0eeb48ddb6b1aaf6903e6264906cb833c3d366ae3c04097bca9dd`.
The original broad PASS label is not treated as signoff.

The [separate source-bound clean replay](../tools/cmac/resume_dsp_prefix_generated_top.py)
changes only the generated `VM_HIER_LIBS` absolute path to an equivalent
relative path. The stock archive extraction and make dependency paths are
checked to resolve to the same unchanged library. All generated C++, mapped
RTL, models, operand fixtures and numerical expectations remain unchanged.
Its fresh compilation completes without tool diagnostics, and exact archive
membership verifies ten original kernel objects plus nine generated top
objects. The fresh wrong-golden negative passes with exit one in 6.137 seconds;
the full 208-frame positive now passes in 335.154 seconds, preserving all 3,328
checks, 3,312 retired outputs, sixteen reset cancellations and 520 held cycles.
Verilator is 5.048, GCC 16.2.1, GNU Make 4.4.1 and GNU ar 2.46.1; source is
`9296473e960bc6fb6da061ac741fa4072e3711e909dc7f0bff7a2ccd2386927a`.
The [actual completed report](../build/rknpu-dsp-prefix-array-generated-top-replay/1791299462883001240/report.json)
records binary fixture acceptance only. Six [build-contract controls](../tests/cmac/test_dsp_prefix_build_contract_control.py)
pass, including rejection of the actual masked archive errors; the expanded
diagnostic suite has 33 passing methods.

A [new checkpoint admission verifier](../tools/cmac/verify_dsp_prefix_clean_replay.py)
requires completed clean logs, every original fixture and command, exact
protected callbacks, unchanged copied C++, library membership, source/artifact
hashes and this variant's actual independent parents. The earlier unclean
PASS is rejected. Eight admission controls and all eighteen original mocked
checkpoint controls pass under each Tcl runtime. The complete 112-method
preparation suite also passes again, including the 20 emitter controls under
both runtimes. Independent actual admission/source revalidation now passes
for that exact closed report. The
[380-member clean numerical/control archive](../verification/runs/2026-10-06-dsp-prefix-full-clean-mapped-replay/index.json)
is written and all members independently verified, SHA256
`ed23af42cdc78e4c0faf46f9fbc0c45e6f70757a7e9d930c436610c07259399e`.
No old failure or unclean build is relabeled accepted.

The separate [checkpoint package](../build/rknpu-dsp-prefix-checkpoint-preflight/1791300567915026382/report.json)
now completes all four actual own-parent admissions: this exact area/native/
clean mapped result and all nine raw-board modes. Its 97 source inputs bind at
`aaaf21a87dc802ca1972c6a8de5ede6851529458e9c6ae1b0d65396bbb747e1f`;
105 artifacts include the unchanged physical-gate build Tcl and literal source
snapshots. Exact part `xc7k480tffg1156-2`, 20 ns clock and all sixteen 32-DSP
kernels remain. Vivado is not invoked and no DCP or bitstream exists. The actual
review-template request against this preparation report exits one at
`Completed routed prefix implementation required`, before creating a review
or emission output. Preparation cannot authorize emission.
No electrical, timing, DRC or geometry gate changes; these controls are not
an implemented checkpoint or FPGA result.

For the requested full Vivado 2026.1 installation, AMD's current
[device-tier table](https://docs.amd.com/r/en-US/ug973-vivado-release-notes-install-license/Device-Availability-by-Subscription-Tier)
lists all Kintex-7 devices under Basic, and its current
[licensing table](https://www.amd.com/en/products/software/adaptive-socs-and-fpgas/vivado/vivado-licensing-options.html)
lists Linux support and a free annually renewed Basic license. This includes
the XC7K480T device family; installed exact part support still needs a live
tool check. A valid license is
[required before launch](https://docs.amd.com/r/en-US/ug973-vivado-release-notes-install-license/Supported-Devices-and-Features).
These links were checked on 2026-10-06. AMD account login, license generation
and agreement acceptance remain the user's actions; no paid purchase or
installed/license-working toolchain is inferred from this documentation.

The preceding unchanged-production `make test` attempt is FAIL: both original
247-entry RTL suites and 1,087,299 numeric comparisons pass, but the third
Verilator product-bench build hits its unchanged 600-second limit after two
product benches pass. Product Icarus does not execute. The
[2,798-member timeout archive](../verification/runs/2026-10-06-dsp-prefix-production-snapshot-compile-timeout/index.json)
preserves all stable partial products at original source `09f1c3f65ba9...`.
The earlier completed production PASS remains evidence only for its own run.
The fresh literal production snapshot now completes every `make test` target
with the same frozen stimuli and deadlines: 49 Python tests, 1,087,299 numeric
comparisons, 247 original RTL tests and all three product benches per simulator,
plus 82 equal memory images. Its [actual completed report](../build/rknpu-dsp-prefix-pin-cone-production-regression/1791300029293915642/report.json)
records exit zero after 2,045.520 seconds at unchanged source `09f1c3f65ba9...`.
No old result is transferred and no nested prefix RTL or physical FPGA
acceptance is inferred. Its [completed fresh archive](../verification/runs/2026-10-07-dsp-prefix-fresh-production-snapshot-pass/index.json)
verifies 2,812 members and 230,342,315 compressed bytes, SHA256
`3cd8d0ec17f7f771124e0ca0197bfedf50f6e929c2423177fbce76b7f1ea7b0a`.
The [whole-board RAM normalization capture](DSP_PREFIX_BOARD_NORMALIZATION.md)
now independently verifies all 54 actual RAM port resizes (32 reported plus
22 silent constant-only changes) and unchanged final whole-board circuit.
Its [254-member archive](../verification/runs/2026-10-07-dsp-prefix-full-board-ram-normalization/index.json)
is checksum-verified. A separate actual initial-driver capture finds real
consumers on all 288 warned bits; a corrected conservative audit now proves
their 107-mux cones entirely unobservable and removed after cleanup.
Separate source-bound structural diagnostic admission now passes after
recomputing both proofs, original remaining structure gates and independent
numerical parents. Its source is `040acb13f113...`; no full-board numerical or
physical acceptance follows. The original failed report/gate remain unchanged.
The [completed independent diagnostic archive](../verification/runs/2026-10-07-dsp-prefix-board-diagnostic-admission/index.json)
repeats the actual proofs/circuit and structure checks; both archive counter
harness failures remain preserved. The exact nine-mode bench binding probe
refuses missing/recoded observations. Source-bound full-board observation
retention now passes real Yosys frontend execution, preserving all 22 signals,
the four-bit state and unchanged sixteen kernels/512 products. Four script
controls pass; this is not remapping or a new numerical result.

Fresh observation-preserving remapping now passes at source `94527de2feb6...`,
retaining all 22 observations, the four-bit state, sixteen kernels/512 CMAC
DSPs, and fresh safe RAM/strict diagnostic gates. It counts 445,816 LUT
primitives, 17,519 flip-flops, 515 DSPs and six BRAMs; its 294,538 logic-cell
estimate is not placed fit or timing. Its initial help probe failure is
source-archived before correction; ten controls pass. The
[current model/export preparation](DSP_PREFIX_BOARD_NORMALIZATION.md)
also records a real source-bound DSP roundtrip PASS for all 32 kernel/three
shell configurations, with six controls and the initial private-name failure
preserved. Pinned vendor-model execution exposes an initial zero-input event
issue; its actual failure is archived, and the corrected testbench-only
settling/result checks have seven passing controls. The settled positive now
fails the unchanged old four-state oracle at case 1,027 after completing the
DSP/binary carry corpus; its actual failure/source are independently archived.
Fresh unchanged-source production regression now passes both 247-entry RTL
suites and all three product benches per simulator, with 82 equal memory
images; it does not cover nested prefix RTL. The separate exhaustive
vendor carry truth-table check now passes all 1,048,576 comparisons, with
415,001 explicit differences from the old oracle; all 1,024 binary cases agree.
The complete 27-method control suite passes. None is whole-board mapped numerical or
physical acceptance, and the original arithmetic/oracle remains unchanged.
The separate full-prefix mapped-board runner now has eight passing controls
and an explicit pinned DSP model profile. Its first full-size attempt completed
exact circuit export but was interrupted during compilation. The
[897-file interruption archive](../verification/runs/2026-10-07-dsp-prefix-observed-mapped-board-interruption/index.json)
retains the stale nonterminal report and unaccepted partial executable unchanged.
An [unchanged-source fresh retry](../build/dsp_prefix_observed_mapped_board_retry_launch_20261007.json)
is supervised by a host user service against the same completed mapping/native
parents. Real negative and all nine unchanged raw-board modes remain required;
no whole-board numerical acceptance is inferred from interruption or launch.

```sh
make -f fpga/cmac/Makefile array-dsp-prefix-extended-diagnostic-control-test
```

The completed package can be reproduced without Vivado or programming:

```sh
python3 tools/cmac/prepare_dsp_prefix_checkpoint.py \
  --area-report build/rknpu-dsp-prefix-array-area/1791280469545641864/report.json \
  --native-report build/rknpu-dsp-prefix-array-native/1791277744017318986/report.json \
  --board-report build/rknpu-dsp-prefix-board-replay/1791283576368477085/report.json \
  --mapped-report build/rknpu-dsp-prefix-array-generated-top-replay/1791299462883001240/report.json
```

## Prefix-only reviewed bitstream emission preparation

The [new reviewed emitter](../tools/cmac/emit_dsp_prefix_bitstream.py) accepts
only `ROUTED_DSP_PREFIX_ARRAY_CHECKPOINT_REVIEW_REQUIRED` from this variant.
It revalidates this profile's own completed native, mapped binary, area and
all-nine-mode raw-board evidence; older compensated/fixed/baseline results
cannot authorize it. The implementation, source, checkpoint, review and all
reviewed reports are content-bound and checked again after emission. The
review template sets all nine human acceptance checks false. No review or
physical electrical facts are fabricated.

The unchanged physical emission template gains only the prefix hierarchy's
sixteen-kernel/32-DSP-per-kernel check before `write_bitstream`. Original exact
part, 20 ns clock, confirmed configuration supply/strap, BRAM, setup/hold and
DRC checks remain; no constraint, severity or timing exception is changed.
Twenty admission/emission methods pass under both Tcl 9.0.3 and AMD Tcl
8.6.13, with every Vivado call mocked. The actual prepared checkpoint report
is rejected with exit one before any output directory or tool is created.
No bitstream, card or flash programming has occurred.

The fresh aggregate now passes 112 distinct preparation methods with no skips,
including the 20 emitter methods repeated under both Tcl runtimes. The
[completed source-bound emitter archive](../verification/runs/2026-10-06-dsp-prefix-reviewed-emitter-preparation/index.json)
preserves 128 verified members/282,421 compressed bytes, SHA256
`0c8268f47a251b2468a4eba17d2e74a4e3b1d80d0b134359c471bd1c5c6f4d21`.
Its control closure binds 38 files at
`7d034899d6566f5ea17717b164e58157924d0dbc4b98a2fd27be6fee873e91e7`;
this is code/control evidence, not HDL numerical or Vivado implementation.

```sh
make -f fpga/cmac/Makefile array-dsp-prefix-preparation-control-test
# Only after this profile's own completed routed implementation and review:
make -f fpga/cmac/Makefile array-dsp-prefix-bitstream-review-template \
  IMPLEMENTATION_REPORT='<completed-prefix-routed-implementation-report>'
RK_CONFIRM_BOARD=YPCB_00338_1P1 RK_EMIT_BITSTREAM=1 \
  make -f fpga/cmac/Makefile array-dsp-prefix-bitstream \
  IMPLEMENTATION_REPORT='<completed-prefix-routed-implementation-report>' \
  REVIEW='<explicitly-reviewed-prefix-review-json>'
```

## Remaining gates

The helper is binary-only: a known high nibble can dominate a lower X, unlike
the original whole-word relational operator. The completed full-array mapped
binary fixture result above is not all-X leaf or whole-board mapped numerical
acceptance. There is no placed fit/timing/DRC,
bitstream, FPGA or RK3588 acceptance. RK special-value compatibility remains
candidate behavior. Integration must retain sixteen kernels/512 products and
independently execute all mapped, hold/reset/fault and raw-command board gates.
Old array results cannot transfer to this variant.

```sh
make -f fpga/cmac/Makefile cmac-dsp-prefix-control-test
make -f fpga/cmac/Makefile cmac-dsp-prefix-test
make -f fpga/cmac/Makefile cmac-dsp-prefix-mapped-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-area-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-board-preparation-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-board-replay-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-mapped-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-board-area-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-board-mapping-preparation-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-frontend-library-export-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-all-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-vivado-control-test
make -f fpga/cmac/Makefile array-dsp-prefix-vivado-prepare
# Requires this variant's own completed area and native-array reports:
make -f fpga/cmac/Makefile array-dsp-prefix-mapped-test \
  AREA_REPORT='<completed-prefix-array-area-report>' \
  NATIVE_REPORT='<completed-prefix-array-native-report>'
```
