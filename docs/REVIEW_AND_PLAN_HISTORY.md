> Historical snapshot of `docs/REVIEW_AND_PLAN.md`, retained on 2026-10-28.
> Its dated status, authorization and "next" statements describe prior source
> snapshots. The [active plan](REVIEW_AND_PLAN.md) governs current work.

# Review of the handoff and next implementation gates

## Application priority: smallest TinyStories first

The user placed TinyStories inference before general tinygrad integration and
delegated the design after checking other local projects. The selected
[TinyStories-260K plan and evidence](TINYSTORIES.md) keeps the original model
dimensions, puts every learned projection on the full512 datapath, and uses
explicit CPU transformer operators for the remaining work. Static FP16 weight
tiles fit in1MiB BRAM, so this first model need not wait for DDR/PCIe.
The fresh official CPU reference and complete32-position donor-policy CPU
oracle pass, with28 greedy token IDs/text matching the FP32 reference.
They do not establish FPGA model inference.

The registered-reset shared CMAC/EW/USER2 endpoint now passes all five modes
in both simulators, including numerical/compaction/rearm, ownership through
ACK and explicit faults/reset. All116 raw tile programs are prepared through
the original emitters/final writer. Fresh Vivado source1e01179c passes synthesis
and registered-reset-cone checks with512 products,256BRAM and516totalDSPs.
The new checkpoint now passes routed50MHz timing: setup+0.640ns, hold+0.056ns
and pulse+9.600ns, zero failures/route errors, with273317LUTs and all512products.
Registered-reset/CDC gates pass;2064 factory DSP advisories retain severity,
with no RAM async-control findings. See the
[checkpoint review](../build/tinystories-vivado/20261026T203942Z/root-review.json).
Exact-image review and the [first physical trained tile](TINYSTORIES_FPGA_TEST.md)
now pass: two CMAC jobs and two FPGA compactions, all 360,448 owned BO bytes
checked before ACK, with independent actual-scan replay. The standalone
application driver also passes one complete physical BOS forward: all 36 learned projections,
232 raw jobs and 348 tasks pass, with actual program/input/weight/output bytes
audited and all 512 logits bit-identical to the donor-policy reference. It
generated token 403, `Once`. The first 32-position attempt later failed at
native RPC timeout during a host-wide OOM. Its captured-data audit verifies
20 full positions and738 complete projections. The Lab retry's host-memory
guard stopped it after18 positions and681 projections; its completed prefix
is independently verified. Both full-run receipts remain failed. The next
same-image runtime adds bounded waiting at idle projection boundaries with
unchanged memory/transport limits; its55 controls and CPU-only full32 oracle
pass separately.
The fresh wait-enabled session has since passed a new audited volatile load,
repeated BOS control and complete32-position inference. Its
[independent raw-wire audit](../build/tinystories-streaming-model-audit/full32-idle-wait-v1.json)
passes all1,152 learned projections,7,424 raw jobs,11,136 tasks and16,384
logits, checking30,408,704 complete output-buffer bytes before ACK. All28
greedy IDs and generated text match the fixed donor reference. This closes
the selected hybrid TinyStories/JTAG milestone; the earlier failed attempts
retain their statuses. CPU host operators remain explicit, and there is no
learned-dense CPU fallback or runtime CPU layout repair.
Retain all512 products, raw final-word execution, explicit unsupported-field
failures and no runtime CPU layout/arithmetic repairs. General framework
integration resumes after the model milestone; all original DDR, PCIe and RK
differential requirements remain in scope.

## Build profiles and incremental acceptance

Use shared RTL and explicit build profiles, with separate immutable sources,
images and receipts. Keep C32/K16 with all 512 products as the compute target.
The smaller EW profile qualifies memory/transport independently; it does not
replace full512 acceptance or create new 64/128/256 compute variants.

| Profile | Completion gate | Current evidence |
|---|---|---|
| `ew_bram` | Physical raw EW jobs, full BO readback, faults and recovery | Passed for its frozen startup and USER2 images |
| `full512_bram` | Physical TinyStories 32 positions, 1,152 learned projections and exact logits | Passed; preserve as the application baseline |
| `ew_ddr` | Complete logical matrix, source-bound CDC/reset review, routed timing/DRC and physical DDR/ECC/ownership/recovery | All 21 optimized logical cases pass. The first CH1 physical scratch and raw SUB(9) pass, including complete BO readback before ACK; broader ECC/recovery/capacity and electrical qualification remain open |
| `full512_ddr` | Combined resource/timing fit and the same physical TinyStories workload backed by DDR | Selected model milestone passes: all 32 positions, 1,152 FPGA learned projections and 16,384 exact logits. Controller33, timing/IO/image and trained tile also pass with all512 products. Broader capacity/ECC/recovery qualification remains open |
| `full512_system` | PCIe and JTAG application execution with the broader supported backend subset | Pending; both interfaces retain independent evidence gates |

Advance `full512_ddr` through the following smaller acceptance gates. Preserve
the passing BRAM application image and EW/DDR image throughout this work.
Each gate binds its own source, tool versions, test inputs and result; a
simulation or synthesis result cannot close a physical gate.

| Full512 DDR increment | Required result | Current evidence |
|---|---|---|
| Candidate arithmetic and controller model | Reference/candidate equivalence, unchanged trained CMAC/EW/CMAC replay, and numerical/fault/recovery composition | Shared-data cell comparisons and nine dispatcher modes pass in both simulators. The fresh trained controller replay passes all 270,336 BO bytes before ACK; the complete same-executable 12-CMAC/21-EW controller union passes |
| Constrained implementation | Mapped clock/reset/CDC checks, retained 512 products and both controllers, successful placement/routing and setup/hold/pulse checks | Passed independent fresh qualification: +0.004/+0.048/+0.264 ns, 422,138 fully routed nets, zero route errors and all 343 bound inputs unchanged. Original route/provenance failures remain preserved |
| First physical trained tile | DDR scratch, then CMAC/EW/CMAC/EW with all four complete BOs checked before ACK (360,448 bytes) | Physical PASS; independent image/load/target/raw-wire review checks 768 scratch bytes, 360,448 BO bytes, 26,204 scans and 8,732 commands |
| Physical TinyStories | One forward position, a repeated-position trial, then all 32 positions with every learned projection on FPGA and exact reference logits | Passed in one loaded epoch: both BOS controls and complete32, with 1,152 FPGA projections, 7,424 raw jobs, 11,136 tasks and all 16,384 logits exact. Independent review checks 2,984,893 scans and 30,408,704 output-BO bytes before ACK |
| Full capacity and ECC/recovery | Full-span physical sweep, source-bound ECC injection, quarantine and joint-reset recovery | Parent wiring and fresh modeled one-MiB normal/BIST/reset replay pass. Full synthesis passes at 295,755 LUTs with 512 products, 516 DSPs and both controllers; fresh place/route is running. Physical two-GiB sweep and ECC/recovery remain pending |

The [reviewed image emission](../build/full512-ddr-preparation/full512-image-prep-v12/emission-report.json)
completed natively in 1,256.917 seconds. The first 20-minute attempt remains
TIMEOUT; the fresh 40-minute workflow retained identical design/checks and
produced the independently audited `d627b715` image with source tag `5e99f881`.
Its [first physical trained trial](DDR_FULL512_FPGA_TEST.md) now passes complete
image/load/target/trace review; 33 offline controls preceded that execution.
The first complete DDR BOS [passes independent root replay](../build/fpga-bringup/full512-ddr-model-prep-v4/root-first-bos-review.json),
including 950,272 complete output-BO bytes and all 512 logits. It generated
token 403, `Once`. The v4 run remains FAIL because subsequent observer-path
bookkeeping stopped before repeated BOS; the successful control is preserved.
The [fresh three-phase model trial](../build/fpga-bringup/full512-ddr-model-prep-v5/root-execution-review.json)
completed after 38 offline controls. It used one volatile load, first BOS,
repeated BOS and full32 execution, with identical model/data/numerical checks.
Each phase must pass its independent raw-wire audit before advancement.
Both controls in that fresh session now [pass root replay](../build/fpga-bringup/full512-ddr-model-prep-v5/root-bos-controls-review.json).
Their logits hashes match exactly, and each generates token 403, `Once`.
The full32 worker started only after those controls passed. The completed
workload now [passes root acceptance](../build/fpga-bringup/full512-ddr-model-prep-v5/root-full32-review.json):
all 32 positions, 1,152 learned projections, 7,424 jobs, 11,136 tasks and
16,384 logits match, including 28 token IDs/text. The independent root replay
checks all 2,984,893 scans and 30,408,704 output-BO bytes before ACK. All 479
image/model/runtime bindings and 77 physical artifacts retain their hashes;
every owned process group is absent. This closes the selected DDR model
milestone, with capacity/ECC/recovery/PCIe/RK acceptance still open.

The [full-span capacity preparation](DDR_CAPACITY_PREPARATION.md) now defines
the complete two-GiB address/pattern/order contract and passes seven offline
controls, including an aliased-memory rejection. Its pattern leaf
passes 4,162 vectors and mapped-logic review; its sweep sequencer now passes
bounded Icarus/strict-Verilator protocol tests and independent source/log
review. The new public AXI adapter/BIST composition now passes six bounded
configurations in each simulator, including nonzero/high-boundary addresses,
fault quarantine and the actual fence/monitor leaves. Default `make test`
includes the new target; the fresh 1,105-file V16 regression passes in 876.048
seconds under independent source/native/complete-host review. Subsystem
mapping uses 1,642 LUTs and 1,958 FFs, with no DSP/RAM. These steps run no
hardware and do not close capacity/ECC/recovery acceptance.

Use these capability increments before introducing additional compute sizes.
The current full512 BRAM result already establishes the selected compute
target. A future lane-count variant would require its own numerical, shape,
layout and command-support contract and would not replace this target.

Check combined resource fit before completing all physical EW/DDR tests.
The passing full512 TinyStories image uses 273,317 routed LUTs. The separate
read-snapshot EW/DDR board candidate synthesizes to 34,028 LUTs, including
26,300 in the two-channel MIG. These are different designs and implementation
stages; their sum is not a combined utilization result. They establish that
headroom is tight and that the actual shared full512/DDR composition needs an
early synthesis result. Retain all 512 products while evaluating that result.
The [independently checked source inventory](../build/full512-ddr-preparation/source-inventory-v1-root-review.json)
binds the existing 51-file/37-HDL-source full512 BRAM profile. Preserve its
generated CACC wrapper and selected pipelined DSP-prefix arithmetic when
joining DDR; the similarly named default CMAC sources are not an equivalent
physical selection. This inventory supplies no combined fit result.
The [new CMAC clock bridge](DDR_CMAC_ASYNC.md) supplies the next source
component: raw UI descriptors and memory traffic around that unchanged
arithmetic, with guarded numerical-child rearming. Its numerical tests and
fault/reset modes now pass in both simulators. The new shared dispatcher
passes its separate routing/ownership controls with test-only child models;
it does not yet qualify numerical composition or complete CSR/DDR integration.
The [staged shared EW/CMAC DDR endpoint](DDR_DUAL_ENDPOINT.md) now supplies
two CSR banks and a global owner through selected readback/ACK. Its control
benches pass both register-bank simulators and the four-state dispatcher
controls. The combined 151-HDL source has separate frontend review for early
resource synthesis. Complete numerical/fault composition, joined-model
verification, mapped CDC/timing and physical full512 integration remain pending.
The first shared-dispatch numerical increment now passes all nine original
full512 K65 modes in both Icarus and Verilator with exact counters and an
independent source/log audit. The first [actual joined controller-model cases](DDR_FULL512_MODEL.md)
now independently pass K65 CMAC and SUB(9) in separate reset epochs, with
complete BO readback before ACK. The original trained tile also passes
CMAC/EW/CMAC reuse in one controller epoch, checking 270,336 BO bytes before
the three ACKs. The full new fault/recovery matrix, shared-data area candidate
and physical full512/DDR retain separate requirements.

The [shared-data area candidate](DDR_AREA_CANDIDATE.md) now has a nominal
full-design synthesis fit: 295,994 LUTs, all 512 product DSPs and both original
controllers. Its 2,606-LUT spare count is not routing acceptance. Preserve
all original-source over-capacity receipts and qualify the changed arithmetic
independently before integrating the physical implementation.

Functional goldens and error expectations stay consistent across applicable
profiles. Traffic counts and resource/timing contracts describe each actual
implementation explicitly. In particular, the new host READ64 snapshot must
prove one physical read per complete host packet; the old halfword-read
inventory and its failed receipts are not rewritten. The
[board preparation](DDR_BOARD_PREPARATION.md) and
[snapshot contract](DDR_HOST_READ_SNAPSHOT.md) identify the current work.

The [first physical CH1 test](DDR_FPGA_TEST.md) now supplies the next measured
increment: one source-bound volatile load, 768 scratch bytes across six
addresses and two write orders, followed by captured SUB(9), two tasks and
102,400 complete owned BO bytes before ACK. Independent decoding checks all
24,238 actual scans and 8,078 mailbox commands. The exact CH1 image passes
routed setup/hold/pulse at +0.006/+0.035/+0.264 ns; no timing or electrical
requirement changed. Full capacity, injected ECC faults, live-reset recovery
and production electrical signoff are not established. Preserve this passing
EW/DDR image independently while building full512/DDR.

## Current implementation increment: EW board bring-up

The 2026-10-25/26 source work implements a separate startup-reset EW board profile
and a no-build preparation tool. The first physical milestone remains the
captured SUB(9) DMA self-test, with all 336 mapped halfwords compared. The full
C32/K16, 512-product candidate remains the later performance target; no
smaller image is counted as full-array acceptance.

| Step | Source/preparation work | Current evidence | Required completion evidence |
|---|---|---|---|
| Board inputs | Target, 50 MHz clock, pad encoding, reset profile and configuration-bank facts | Exact target, routed IO/configuration and 65 initialized reset registers reviewed; license/device support passed | Recheck target and image for every later hardware test |
| EW in BRAM | Raw command DMA/BRAM test, startup-reset wrapper and immutable preparation | Vivado signoff passed; three SRAM loads and four captures passed, with 404 samples and 32 heartbeat transitions | Complete for this autonomous built-in workload; host-submitted jobs remain separate |
| Serialized GEMM | Donor CMAC/CACC/converter/writer and K=65 BRAM candidate | Eight/nine candidate modes pass; package intact | Reviewed implementation, 64 acknowledged outputs and 4,096 RAM comparisons on hardware |
| Host-controlled BRAM | Existing job/memory ABI through USER2; original compiler/final writer under the byte transport | Physical raw-BO EW milestone and complete32-position full512/EW TinyStories inference pass, with independent actual-scan and complete-buffer audits; flash unchanged | General live compiler-to-card integration follows the completed TinyStories milestone. IRQ/heartbeat are not PASS indicators |
| Full C32/K16 | All 512 products and grouping/reduction/layout contract | Registered-RAM pipeline routes at50MHz with setup+0.987ns/hold+0.057ns/pulse+9.600ns, zero failures. Native21cases and mapped startup/expectedrejection pass. Three actual SRAM loads and four positive captures (404rows/32heartbeat transitions) pass the finiteK65 built-in scoreboard | Additional workloads and RK differential/special-value qualification; host/runtime/DDR/PCIe remain separate. SAMPLE is indirect scoreboard observation, not RAM readback |
| DDR, then PCIe/backend | Add memory/transport independently; extend the bounded EW compiler path | All 21 optimized two-clock logical cases pass. The CH1 routed image passes its first physical scratch and raw SUB(9), with complete BO readback before ACK. The CMAC bridge passes nine modes in both simulators; shared-dispatch controls pass separately | Complete shared full512/DDR CSR/scheduling, numerical/fault composition and early combined fit. Qualify broader physical DDR/ECC/recovery, full512 TinyStories/DDR, PCIe and backend coverage |

On 2026-10-26 the user explicitly authorized FPGA testing as needed. This
permits the fresh EW Vivado implementation and an audited volatile-SRAM test
after exact-image review; it does not authorize permanent flash writes.
`progress.md` is not used. The scoped board review selects noninverted output
pad encoding for passive JTAG SAMPLE observation. It leaves optical LED
polarity unknown and makes no new rail-voltage measurement claim. The exact
clock/pins and known-used 1.8 V/GND configuration remain required.
The [hardware report](EW_FPGA_TEST.md) and
[preserved observations](../verification/runs/2026-10-26-ew-startup-fpga/index.json)
bind the implementation, exact image, target and physical captures. SAMPLE
observes the built-in scoreboard output; it does not directly read its 336
halfwords. The separate [USER2 physical report](HOST_FPGA_TEST.md) now supplies
complete host readback and fault/reconfiguration evidence for the strict EW
BRAM endpoint. It uses captured raw final words. TinyStories application
execution now precedes actual framework compilation through to the card.

The requested `~/ZYNQ-NVDLA` reference was inspected after this milestone.
Its independent JTAG/DDR/PCIe clocks, decoded address windows, scratch readback
and sentinel tests inform subsequent preparation. Its INT8 accelerator and
64-bit AXI-to-512-bit native CH1 path are different from this FP16/raw-word,
512-bit AXI-to-MIG design. Its `0x80000000..0xffffffff` DDR aperture is outside
the current 31-bit host transport contract; copying its runtime addresses or
raising that limit without a new source/shape/ownership contract is invalid.
The original joined DDR timeout remains a failed historical receipt. Later
structured simulations passed one numerical case, ECC and host-timeout faults,
and a separately reviewed reset recovery. Their original source is preserved;
the current job-controller parameterization and strengthened model bounds need
fresh evidence. The [repeatable current-source runner](DDR_ENDPOINT.md#repeatable-current-source-runner)
now builds the actual logical controller composition and runs all 20 raw-BO
workload/fault/recovery cases. Complete that qualification before preparing an
independently audited DDR/PCIe integration.
Separate [original-profile MIG source generation](DDR_ORIGINAL_MIG.md) now
passes without changing the original RZQ/7 project. Its new generated
ports/parameters have a source audit, while model/PHY, clock/electrical and
implementation qualification remain separate. An earlier full production
`make test` passed at source `2a3d4a7b195b`, including its DDR controls.
See [the reference comparison](LOCAL_REFERENCES.md#zynq-nvdla-integration-reference-2026-10-27).

The [fresh default regression](../build/production-model-auditors/current-v11/root-review.json)
passes serial `make test` in 908.108 seconds at source `22acfca257f9`, with
61 TinyStories controls, 11 DDR endpoint controls, 69 additional DDR software
controls and six dual-control native commands. Its independent review checks
all 1,093 copied/live inputs, command/core reports and both complete host
receipts. The prior private missing-build-fixture failure remains failed;
portable channel controls and the separate frozen-package audit now pass.
Optional numerical components and the joined EW/DDR composition retain
separate evidence; default Make does not qualify joined DDR or physical memory.

The original full512 route failed setup timing at WNS -13.249 ns; the
separate balanced-selector route/post-route results also failed at -2.350 ns
and -1.686 ns. Neither produced a bitstream. The registered-preparation
candidate has now routed at 20 ns. Its timing report records setup +0.045 ns
(45 ps), hold +0.075 ns and pulse width +9.600 ns, with zero failing endpoints
in all three groups. The no-clock and unconstrained-internal checks each report
zero. Routed utilization is 267,210 LUTs (89.49%), 35,776 registers, six BRAM
tiles and 515 DSPs including 512 CMAC products. The DRC report contains 2,081
warning-level findings: 1,030 DPIP-1, 515 DPOP-1, 515 DPOP-2, 20 REQP-1839 and
one CHECK-3 rule-limit warning. No source constraint or DRC waiver changed. See
the [timing candidate notes](CMAC_PIPELINE_TIMING.md),
[frozen source package](../build/full512-pipeline-preparation/1793008000/report.json),
[routed timing report](../build/full512-pipeline-preparation/1793008000/implementation/timing.rpt),
[DRC report](../build/full512-pipeline-preparation/1793008000/implementation/drc.rpt), and
[current run receipt](../build/full512-pipeline-implementation/1793007479542120029/run.json).
Startup/image/electrical review, DRC-warning review and mapped validation remain
before bitstream; the vendor mapped replay exceeded its license instance limit.
The registered-BRAM-control candidate passes both complete native board suites
and now passes routed 50 MHz timing: setup +0.987 ns, hold +0.057 ns and pulse
width +9.600 ns, all with zero failures. Its routed DRC has no RAM async-control
findings; the 2,060 remaining DSP advisories and routed INIT/IO evidence are
reviewed. The exact image now passes the [full512 physical startup test](CMAC_FPGA_TEST.md),
including repeated volatile configuration. See the pipeline timing notes for its
contract, export-boundary diagnosis and current evidence. Earlier variants remain
failed/unprogrammed; the newer source has its own exact-image and physical
receipts. The EW result did not waive any full512 gate.

The optional [ILA source preparation](FPGA_DEBUG.md) now supplies the requested
state/start/memory/error probe plans for both EW startup and host-controlled
profiles. It preserves the qualified functional RTL and all default physical
flows. Actual debug-core implementation, probe mapping and capture remain
unexecuted; the autonomous profile observes latched state, while the host
profile provides an arm-before-SUBMIT candidate.

### Implemented reset profiles and reference

The existing `fpga/ypcb_top.sv` / `fpga/ypcb.xdc` profile is retained unchanged.
It still requires an audited external R28 reset input. OpenTPU's board notes
say that pin is unwired, so its actual connection must not be assumed here.

The new `fpga/ypcb_ew_startup_top.sv` and `fpga/ypcb_ew_startup.xdc` expose only
the clock and LEDs. `rtl/rk_startup_reset.sv` holds a registered active-low
reset through 64 rising edges and releases it on edge 65. Its independent
synchronous request input restarts the full interval; this autonomous top
ties that input low and restarts through reconfiguration. No external button
or JTAG runtime reset is implied. The original clock/LED pins and 20 ns target
are preserved, and no internal timing exception is added.

The design reference is the registered reset in the preserved OpenTPU
`c0182800` package, `evidence/dual-host/otpu_host_reset.sv`, SHA256
`517b7c49b2755aa2150b1dfaadca74a4af0efcb3117e6a5b9aad4839b1a53538`.
Its counter decode does not directly drive the reset output. RKNPU uses an
initialized flip-flop delay chain followed by a registered output, avoiding
a multi-bit counter transition at configuration release. It is a separate
implementation for one clock; it does not import the
donor's PCIe transitions, MMCM lock logic or hardware qualification. The
OpenTPU checkout and its abandoned runtime-clock effort remain untouched.

AMD documents configuration initialization in
[UG474](https://docs.amd.com/r/en-US/ug474_7Series_CLB/Global-Controls-GSR-and-GTS)
and constant register initialization in
[UG901](https://docs.amd.com/r/en-US/ug901-vivado-synthesis/Initial-Values).
This profile relies on initialized flip-flops and a continuously running,
valid 50 MHz board clock. The delay chain is not a clock-lock/stability detector.
The [SHREG_EXTRACT setting](https://docs.amd.com/r/en-US/ug901-vivado-synthesis/SHREG_EXTRACT)
requests flip-flops rather than an SRL implementation for that chain.
The selected EW run now verifies the actual 65-register INIT/topology and
successful repeated reconfiguration. It does not measure the exact release
edge on a physical probe or supply a clock-stability detector.

### Preparation commands and admission

```sh
make fpga-prepare-startup   # new profile; no R28 input, no Vivado invocation
make fpga-prepare           # preserved external-R28 profile, also preparation only
```

`tools/prepare_ew_fpga.py` freezes sources, the exact constraint profile and
checkpoint Tcl under a fresh `build/ew-fpga-preparation/` directory. It writes
an incomplete `board-review.json`; electrical values and LED polarity are
not guessed. It can bind the selected profile to both simulator reports:

```sh
python3 tools/prepare_ew_fpga.py prepare --profile startup \
  --verilator-report path/to/current/rtl/report.json \
  --iverilog-report path/to/current/iverilog/report.json
python3 tools/prepare_ew_fpga.py verify build/ew-fpga-preparation/SELECTED_PACKAGE
```

The supplied reports must have the matching production source manifest,
successful commands/tests and the actual selected board/reset test entries.
A full regression after these source edits supplies new evidence; earlier
passes cannot qualify this modified profile. The source identity now includes
root FPGA `.tcl.in` templates so their control tests are also bound.

`verify` checks every frozen file, generated Tcl and attached simulator report.
Each selected test is tied to its actual compile and execution arguments,
binary, PASS result, tool-version logs and runtime stimulus files. These
artifacts are copied into the package and rechecked independently of the
original run directory. A source-matching summary without execution artifacts
is rejected, including older producer reports lacking this evidence schema.
Changes to the selected live hardware sources also block command generation
until a fresh package and matching evidence are prepared.
It reports outstanding board/numerical review instead of treating preparation
as build admission. After all recorded review requirements pass, `command`
prints a future Vivado invocation and environment; it never executes them.
That command still needs separate build authorization and actual tool/license
support. The generated flow stops at a checkpoint, preserves BRAM, clock,
setup/hold, unconstrained-internal-endpoint and DRC gates, and saves route and
pulse-width reports for review. Bitstream emission and programming are absent.

The completed EW hardware run used a separate source-bound electrical/pad
review, since the legacy preparation form cannot express unknown optical LED
polarity with known logical pad encoding. The legacy form stays incomplete.
An independent native checkpoint audit, exact-image review and exclusive cable
lease supplied the later gates; no constraint, severity or timing check was
weakened. Its text evidence is preserved with the hardware report.

The old full C32/K16 prerequisite set remains stale and is preserved as
historical evidence. The fresh full-size qualification and own-parent
checkpoint preparation below now pass the existing source-admission checks.
The independent EW milestone does not supply or waive that array evidence.

### Current source verification

The [current production run](../build/plan-full512-startup-implementation/1792966979950932621/production-validation.json)
passes `make -j2 test` in 491.103 seconds: 73 root Python methods, 1,087,299 numeric
comparisons, 249 entries under each of Verilator 5.048 and Icarus 13.0, and
three raw-product CMAC benches in each simulator, plus the separate host suites
described below. All five production reports match the
unchanged source manifest
`d1d0e3d0bffd0ffadee9e9eb4b14020c985d772ce716ad2936894f2b4003f59a`.
All 82 observed memory images agree between simulators. The prior counter
candidate's passing run is preserved separately and is not evidence for the
final flip-flop-chain revision. New tests retain strict warning/error policies.

The preparation controls exercise missing/stale evidence, snapshot and Tcl
tampering, source drift, invalid electrical pairs, optimized-Python rejection
paths and mocked Vivado clock/BRAM/timing/DRC failures. The new RTL benches
exercise both LED polarities, initial reset timing, synchronous restart and
reassertion during a hold. None is a physical FPGA or RK3588 test.

### Optional ILA source preparation

The explicit gate-C probe work is implemented as two separate
[debug preparation profiles](FPGA_DEBUG.md), without changing qualified RTL or
default physical flows. Both freeze 14 ordered probes and 204 bits, source-bound
FSM codebooks, buffered SYS-clock selection and USER1 debug-hub ownership.
The host variant retains the exact USER2 mailbox and all original CDC bounds.
Its package-only primitive selector permits the additional USER1 owner without
weakening the mailbox checks. Acquisition must keep shared TCK at or below 6 MHz.

The [autonomous package](../build/ew-debug-preparation/1792962351826175702/report.json)
supports latched post-startup observation; no initial startup capture is claimed.
The [host package](../build/ew-debug-preparation/1792962351620948606/report.json)
is the candidate for arming before a raw SUBMIT. Both remain
`SOURCE_INTACT_REVIEW_PENDING`. Actual ILA implementation, mapped channel
inspection and physical acquisition remain acceptance work.

The full regression above included fourteen initial debug controls. The final
packaging import-closure fix passed
[sixteen targeted controls](../build/plan-debug-implementation/1792961083679149070/debug-validation-final.json)
under ordinary Tcl 9.0.3 and clean vendor Tcl 8.6.13; it changes no RTL or probe
Tcl. All [23 real copied-package controls](../build/ila-package-audit/1792962791198091922/report.json)
pass, including isolated copied-source verification outside the checkout,
blocked original evidence, corruption rejection and unchanged final package
bytes. No new Vivado, physical timing or board result is supplied by these checks.

### Separate serialized GEMM preparation

`tools/cmac/prepare_serial_board.py` packages the existing numerical CMAC BRAM
profile from `fpga/cmac/sources.json`. It does not accept EW or raw-product
evidence as full numerical GEMM evidence. Its own complete Verilator and
Icarus board suites, including all eight/nine modes, must match the numerical
source manifest. The qualified producer now records the executed simulator
binary's hash, verifies it after replay, and retains it with the bound logs.
Python `-O` is rejected so the existing verification assertions remain active.
The producer and preparer share an exact full-line result parser; counts such
as `acks=640` cannot pass an `acks=64` requirement. Admission also requires
the complete compile/version/lint command history and exact source/top/output
arguments. Matching result summaries alone cannot qualify a package.

```sh
python3 tools/cmac/run.py test --suite board --tool verilator --jobs 2
python3 tools/cmac/run.py test --suite board --tool iverilog --jobs 2
python3 tools/cmac/prepare_serial_board.py prepare \
  --verilator-report path/to/current/serialized-verilator/report.json \
  --iverilog-report path/to/current/serialized-iverilog/report.json
```

These test commands run HDL simulators only. The preparation command copies
the actual numerical reports, binaries and logs and writes a separate source
snapshot, checkpoint Tcl and incomplete board review. It never launches
Vivado. Numerical-input identity and build-tool identity are recorded
separately; no existing full-array source guard is changed. The serialized
profile still uses external R28 and remains blocked on that reset/board
review. The EW startup profile does not silently change the serialized or
full-array reset architecture. `verify` checks integrity; `command` only
prints a future invocation after every recorded prerequisite passes.

The [current serialized package](../build/plan-source-implementation-1792942734594175489/serial-vivado-reviewed/report.json)
binds the fresh eight-mode Verilator and nine-mode Icarus board suites at
numerical source SHA256
`6875b182c912d98fe0db47ff0eeea111ce933f9e6d532c0be47ca1274503cc85`.
Its separate 93-file package source hash is
`8feb74d029780adfdef14beaf4dc3f598cf9457673f97c290e1f15489fe85529`.
The [copy audit](../build/plan-source-implementation-1792942734594175489/serial-copied-evidence-final.json)
checks all 14 Verilator and 13 Icarus artifacts against the originals. Both
this package and the [current EW startup package](../build/ew-fpga-preparation/startup-1792967662354184758/report.json)
pass integrity verification and correctly refuse command generation while
board review remains incomplete. No numerical result is a physical-board pass.

### Host-controlled BRAM source increment, 2026-10-26

The [USER2 BRAM candidate](HOST_JTAG_BRAM.md) implements the next independent
source milestone. It copies only the pinned OpenTPU mailbox, retains its
wire format and CDC architecture, maps register traffic onto the existing job
controller, and transfers unchanged BO bytes into a 1 MiB BRAM window. The
stdlib XVC client verifies TAP and ABI identities before writes and serializes
both process and thread owners. Normal successful jobs use the existing
SUBMIT/result/ACK lifecycle. There is no new arithmetic interface, runtime CPU
layout repair, reset opcode or implicit fault recovery.

The physical shell, bounded CDC constraints and checkpoint-only preparation
are separate from the autonomous EW, serialized numerical CMAC and full
C32/K16 profiles. Its prepared shell exposes startup reset and LEDs, without
R28. Board/electrical review starts incomplete. Actual BSCANE2 operation,
routing/timing/CDC review and FPGA execution remain acceptance work under a
later explicit build/programming instruction. DDR and PCIe are not integrated.

Subagent review identified and repaired generated-stimulus identity, complete
XVC operation deadlines and rejection of AXI-Lite responses before a prior
request handshake. Focused controls retain the original numerical expectations
and all original negative cases. Fresh native reports and the bound preparation
package are recorded separately below; earlier attempts remain historical.

The [current full regression](../build/plan-full512-startup-implementation/1792966979950932621/production-validation.json)
records actual `make -j2 test` exit 0 in 491.103 seconds. Both existing 249-entry
EW suites, both three-bench raw-product CMAC suites and both 15-scenario USER2
suites pass. There are 73 root unit methods, 23 transport controls, five
stimulus-identity controls and 1,087,299 independent C++ numerical comparisons.
The final host source manifest is
`980adc4825924530625d9e270f727fd9a91e10b901e76ef244bb276b72aed9f7`.
The real tools are Verilator 5.048 and Icarus Verilog 13.0. All
[13 host readback images](../build/plan-full512-startup-implementation/1792966979950932621/host-memory-image-comparison.json)
match across simulators, including the retained partial-write image.

The preceding host increment's original aggregation receipt remains failed because the wrapper expected
generic `PASS` from the correctly scoped `PASS_RAW_PRODUCT_PATH_ONLY` CMAC
reports. Its [reviewed receipt](../build/plan-host-implementation/1792954943176295058/production-validation-reviewed.json) rechecks their exact scope, actual command
return 0, all source identities and both complete host reports; it changes no
test result or expectation. The first host attempts also remain historical:
the first Verilator pass predates review fixes, and the first Icarus attempt
finished all scenarios but correctly failed its source-change guard.

The [current USER2 preparation package](../build/host-jtag-preparation/1792967662198630675/report.json)
binds both complete native reports and freezes 40 source/preparation files at
SHA256 `e753deb615e25a99f8542c5eed62e19b0119e35b27aa7d3c29870513fe7d9c30`.
It verifies as `SOURCE_INTACT_REVIEW_PENDING` and refuses command generation
because board review is incomplete. After the full numerical regression,
the preparation-only foreign-artifact-origin fix passed all
[eight preparation controls](../build/host-preparation-review-1792955479549759890/report.json);
the numerical/native protocol source identity stayed unchanged. Reports from
another workspace are copied from their recorded execution root; copied package
verification uses its own source/artifact roots. No hardware review fields were
filled in to obtain admission.

All [11 real copied-package controls](../build/host-copy-audit/1792955642798984887/report.json)
pass on the preceding package with the same frozen source: verification succeeds with both original artifact directories blocked;
copied binary/log/stimulus corruption and changed execution bindings are
rejected. All package bytes and original evidence are unchanged after the
controls. The two original native reports and their bound artifacts were
preserved, and actual command generation still rejects the missing board review.
The [current package audit](../build/plan-debug-implementation/1792961083679149070/host-package-current-audit.json)
separately verifies its fresh copied reports with both new original artifact
directories blocked, unchanged package bytes and incomplete board review.

### Production backend source increment, 2026-10-26

The [RKNPUFPGA adapter](BACKEND_RUNTIME.md) now connects the pinned, clean
tinygrad source to the existing host byte transport. It keeps the original
`to_program`, Rockchip renderer, `_run_ew_ops` and final command writer. The
device alias maps compilation to the original ROCKCHIP target so its existing
optimization rules remain active. The foreign checkout and original ROCKCHIP
device are unchanged; no DRM device or implicit network connection is created.

The adapter validates complete HALF EW images and literal-only scratch
initializers before execution. Runtime gathers, other precision modes, unsafe
views and unmodeled submission fields fail explicitly. CPU synchronization is
byte copying only. The original writer's BOs, task descriptors, guard pages and
linked PC tails are preserved. One original submit becomes one RKEW job, with
complete BO readback before ACK and sticky owner poisoning on failure.

The [current integration run](../build/backend-rtl/1792958040917797032/report.json)
passes all eleven scenarios: fresh Tensor ADD/SUB/MUL at lengths 8/9/33,
repeated SUB(9), and explicit rejection of a compiled runtime-gather graph.
Its ten numerical cases execute 11 actual RTL jobs and 16 linked tasks and
check 1,081,344 complete BO bytes. The negative case reaches the production
compiler/renderer but makes no final-writer call or descriptor submission.
The exact source manifest is
`f38a9c0bf870857565721aca440de6e823c81d811ffe5f551687c399dcdb88ca`.
The real tools are Verilator 5.048 and GCC 16.2.1; fifteen runtime, nine trace
and two runner controls pass. The earlier ten-case snapshot remains historical;
its resolved compiler-wrapper version probe was corrected before this run.

The [frozen compiler/RTL package](../build/backend-copy-audit/1792958403533425061/package)
contains 27 selected sources and 61 artifacts. All
[14 copied-evidence controls](../build/backend-copy-audit/1792958403533425061/audit.json)
pass, including verification with both the original run and foreign backend
checkout blocked. Missing program images, changed source/binaries/frames and
altered compiler/writer execution records fail admission. Original reports and
all final package bytes remain unchanged.

Run `TINYGRAD_ROOT="$HOME/tinygrad" make backend-test`. This is a separate
compiler integration target so the portable fixture-based `make test` does not
require an external checkout. The backend tests inject a local frame RTL link,
forbid TCP/DRM access and observe original compiler/writer code-object calls.
They do not validate physical BSCANE2/JTAG, pass the full tinygrad census,
integrate CMAC into this runtime, or supply missing RK differential outputs.

### Full C32/K16 qualification refresh, 2026-10-26

The separate [full-size startup wrapper](CMAC_ARRAY_STARTUP.md) adds a
configuration-initialized reset to the unchanged DSP-prefix board design,
without consuming R28 or reducing its sixteen kernels/512 products. The
[fresh startup-native result](../build/plan-full512-startup-implementation/1792966979950932621/startup-native-summary.json)
passes 22 Icarus and 20 Verilator cases, both LED polarities, complete K=65
workloads, applicable faults and partial-stop/fresh-process cold starts. Each
successful run retains 4,096 initialization/readback words, 196 command reads,
6,528 operand reads, 64 numerical writes/acks and twelve frames. These cold
processes do not prove runtime reset or physical reconfiguration. Original R28
top/bench evidence remains separate and unchanged. The current native source
manifest is `dc250720fee290859232b2a7f255084eb9ecdd755b92670ba10459f8cf77ecef`.
Mapped startup-board, physical INIT/FF mapping, fit/timing and actual execution
remain unproved; native results do not waive the arithmetic-parent gates.

The [startup checkpoint package](../build/full512-startup-preparation/1792967676447887367/report.json)
freezes the 113-file build/preparation snapshot at
`e6da99945ee063189fb685536560dbe7b232ae574c39975ab630fbcdf9d0281f`.
All [eleven actual copy controls](../build/full512-startup-package-audit/1792967676447887367/report.json)
pass with 184 package files and 275 original evidence files unchanged.
Copied startup-native evidence is independently verifiable; the arithmetic
parent DAG is explicitly external and must remain current for build-command
admission. Missing board review still blocks that command. Neither the
startup native result nor the package claims mapped startup, physical reset,
fit/timing, DRC or actual FPGA execution.

The original qualification commands were rerun from the first stale
dependency, preserving all 512 products, numerical vectors, real wrong-output
negatives, assertions and deadlines. No native openXC7 implementation or
Vivado build was executed. The fresh parents are:

| Qualification | Current evidence |
|---|---|
| Declared geometry | [Hierarchy preparation](../build/rknpu-dsp-prefix-array-preparation/1792946912499360589/report.json): 16 kernels, 32 lanes each |
| Prefix lane and mapped primitive behavior | [Carry/area proof](../build/rknpu-dsp-prefix-carry/1792946912492855114/report.json) and [actual mapped-lane replay](../build/rknpu-dsp-prefix-mapped-binary/1792947018073372362/report.json) |
| Full-array area | [Current area report](../build/rknpu-dsp-prefix-array-area/1792947201846706713/report.json), retaining 512 DSP products; physical fit is unproven |
| Native four-state array | [208-frame replay](../build/rknpu-dsp-prefix-array-native/1792947201927138428/report.json): 3,328 checked outputs, holds, reset cancellation and X-input rejection |
| Raw-command board | [All nine Icarus modes](../build/rknpu-dsp-prefix-board-replay/1792947718359945807/report.json), using the full-size prefix array |
| Actual mapped array | [Clean mapped replay](../build/rknpu-dsp-prefix-array-generated-top-replay/1792950494827304453/report.json): original 208-frame corpus and fresh wrong-output negative, with exact archive-member checks |

The mapped compiler's original [kernel diagnostic rejection](../build/rknpu-dsp-prefix-array-mapped-binary/1792947727353053546/report.json)
and [top-generation rejection](../build/rknpu-dsp-prefix-array-mapped-continuation/1792948669543018156/report.json)
remain `FAIL`. Existing source-specific cone, model, primitive, FDCE startup
and diagnostic-inventory controls qualified the exact reused compiled
library. The later [historical-hash guard rejection](../build/rknpu-dsp-prefix-array-generated-top-replay/1792948939065645041/report.json)
also remains failed; none of these failures is relabelled as acceptance.

That last rejection exposed a checker bug: it required the single historical
protection hash `2969735049`. The fresh wrapper and bridge both contain
`3807618499`. [Verilator 5.048's generator](https://raw.githubusercontent.com/verilator/verilator/v5.048/src/V3ProtectLib.cpp)
derives a hash from its emitted C++ AST and writes the same value to both
files. The contract now requires one matching, canonical unsigned 32-bit
value and the active unconditional hash-check-before-create initializer.
Operand/mask widths, callbacks, evaluation and output checks are retained.
Seven controls reject mismatches, missing/duplicate calls, comments, disabled
or reordered calls and conditional wrapping. The [actual compiled-library probe](../build/plan-source-implementation-1792942734594175489/protection-hash-runtime-control/runtime-linked-report.json)
accepts its matching hash and rejects a one-bit mismatch. The final full
mapped replay was executed after this checker fix.

The [own-parent-validated checkpoint preparation](../build/rknpu-dsp-prefix-checkpoint-preflight/1792950744001340936/report.json)
now has status `PREPARED_OWN_PARENTS_VALIDATED_FULL_C32K16_PREFIX_CHECKPOINT_ONLY`.
All four current area/native/board/mapped parents were validated, the ROM
check passed, and `build.tcl` plus source snapshots were written. Its source
SHA256 is `ba36cf856e1c55d1f3441fa1e08377136026ec6db2ea8c7f0c636d0dce38401b`.
This clears the stale offline prerequisite chain for this exact source set.
Actual Vivado execution, physical fit/timing/electrical/DRC review, image
emission and board execution remain pending under the no-build instruction.

The [production regression rerun](../build/plan-source-implementation-1792942734594175489/qualification-refresh-production/production-validation.json)
also passes `make -j2 test` in 162.443 seconds at the unchanged production
source manifest above. The nested mapped-library checker has its separate
targeted controls and actual full mapped replay; the production suite alone
does not qualify that checker or the full-array implementation.

## What remains valid

The compiler should keep emitting RK register/task images. A functional model should decode those bytes, use simulated device addresses, and expose incorrect encodings or memory layouts. RTL verification should use the same stimulus and compare output bytes. FPGA throughput may differ from Rockchip silicon; matching undocumented pipeline latency is not the goal.

The user reports that their ~1500-line tinygrad backend passes hardware test_ops and that the required reverse engineering is already available. Treat that work as the starting point. Do not spend the next iteration rewriting the backend or inventing a second high-level compiler.

## What needed correction

**soDLA FP16 is not established by choosing a precision field.** The inspected `soDLA_beta/src/main/scala/nvdla/cmac/NV_NVDLA_CMAC_CORE_mac.scala` computes signed-integer products and reduces them. That leaf is not an FP16 multiplier. This source finding invalidates the earlier blanket assumption that an RK register adapter over soDLA immediately gives a usable FP16 GEMM path. It does not establish what every uninspected soDLA module or branch supports. Inspect actual chosen leaves and generated RTL before reuse.

**Preserve observable capacity/layout, not just register names.** Reducing physical lanes can be implemented by time-multiplexing. Reducing software-visible CBUF capacity or changing channel/weight atom packing cannot silently be done while promising unmodified existing commands. Preserve the logical contract, virtualize it with correct behavior, explicitly reject an unsupported profile, or deliberately add a compiler capability target. The demo's 4 KiB RAM is backing device memory for a tiny EW workload, not an implementation of RK CBUF.

**A common register list is not the whole runtime ABI.** A PCIe FPGA still needs allocation/address translation, command delivery, completion, reset, error and ordering contracts. It is not automatically a /dev/dri/card1 rknpu device. No DRM or PCIe driver has been added here.

**Simulation consensus is not automatic bug attribution.** If Python and RTL agree but RK differs, they may share an erroneous specification. Even if RK and Python agree, a difference can be in the RTL testbench or transport. Keep raw register bytes, input/output images, seeds and hardware provenance before deciding where a defect lives.

**RTL cycle accuracy has a target.** Simulating this RTL describes the timing of this new implementation, not the unreleased RK3588 implementation. This package is not a NaviSim-style calibrated Rockchip timing model.

## What this delivery chose to implement

Use SystemVerilog for a small direct DPU/RDMA FP16 EW path, avoiding a pretend soDLA integration. It has real register decoding, explicit mode rejection, actual integer-built FP16 arithmetic, a memory controller and concrete tests. No imported soDLA RTL/Chisel source is bundled. Somnia/soDLA remain references and potential later leaf-module donors.

The first vertical path changed from GEMM to EW because the inspected EW register sequence gives a closed, reviewable command/memory contract, while the proposed soDLA CMAC does not supply verified FP16 arithmetic. This is an implementation decision, not a claim that GEMM reverse engineering is unavailable in the user's repositories.

## Work packages, in acceptance order

### Current user-directed implementation assumptions

The user has directed continued development with NVIDIA's FP16 hardware as the
numerical donor and the `rockchip-2608-1500` backend's existing special-case
decompositions. Treat the corresponding NVDLA datapaths as the **working
baseline**, not generic IEEE arithmetic imposed across all NPU units. The donor
conversion mismatch is not a demonstrated NVIDIA defect. Map each selected
path and register mode before reuse; do not infer that every EW operation has
the output converter's saturation behavior. RK bit-exact exceptional-value
compatibility remains a candidate claim until differential evidence exists;
its absence does not prevent donor-based implementation work. Existing tests
are not silently changed, and compile-time decompositions still reach the FPGA
through final raw command words, without runtime CPU fixups.

On 2026-10-23 the user selected Vivado, using OpenTPU's setup as the reference,
and retired openXC7 placement/routing from this continuation. Preserve the
historical openXC7 sources, reports and failed attempts; do not restart that
toolchain or use its results as physical signoff. OpenTPU's abandoned build
work is also not resumed. The original authorization covered source changes,
review fixes and preparation. On 2026-10-26 the user additionally authorized
FPGA testing as needed; the first build targets the separate EW startup image,
with image-specific review before temporary SRAM programming. Flash writes
remain unauthorized.

Retain the full C32/K16 DSP-prefix candidate with 512 parallel CMAC products;
the smaller EW top remains a separate regression target. The existing
`python3 tools/cmac/vivado_dsp_prefix_array.py prepare` action validates its
source profile and generated ROM and writes source/Tcl snapshots without
validating numerical parents or launching Vivado. It must retain all source,
numerical, electrical, timing, fit and DRC gates. Its `synth` and `run` actions require a later user
instruction to build.

The recorded 2026-10-09 full Vivado 2026.1 version probe passed, while the
separate synthesis-only attempt exited 42 before synthesis because no valid
license was found. That is historical evidence. Read-only inspection on
2026-10-23 found the settings script, launcher and a local license file, but
did not test current license checkout. Follow OpenTPU's normal shell setup
with `VIVADO_ROOT="$HOME/vivado/2026.1/Vivado"` and
`source "$VIVADO_ROOT/settings64.sh"`; see [FPGA.md](FPGA.md). No fresh synthesis,
implementation, timing, electrical, DRC or hardware result is implied.

### A. Establish executable RTL evidence

Run `make rtl-test`; fix HDL compile issues and warnings, then every failing arithmetic/protocol case. Archive the Verilator version, build logs, vector seeds and test results. Add directed four-state checks with a second simulator where practical. Verify the BRAM demo's reset/restart behavior. Do not change failure checks to manufacture a pass.

Acceptance: all generated ALU vectors, all engine scenarios and the BRAM demo pass real HDL simulation. **Passed on the Fedora continuation source snapshot `6f9a9681713f`:** 12,963 ALU vectors and 77 engine scenarios with Verilator and Icarus, plus RAM protocol, readback fault and board reset tests. The original 38 scenarios are retained with their error expectations unchanged. The original delivery did not pass this gate; consult `verification/README.md` for the current source-bound result.

### B. Bind the subset to a real backend trace

Pin the current backend and RK reference repository commits. Capture one emitted terminal FP16 ADD, SUB and MUL command stream plus exact initialized BO bytes and raw hardware outputs. Replay without semantic rewriting through the Python decoder and RTL harness. If the backend uses extra valid registers or a different mode, add that precisely evidenced profile rather than deleting the decoder's checks.

Exercise signed zeros, subnormals, overflow, NaN/infinity, tail groups, alignment, aliasing and task boundaries. Record hardware reset state and any tolerance; do not imply byte-exact arithmetic from a loose allclose result.

Acceptance: supported captured streams replay successfully with appropriately justified numerical comparisons. This will not by itself pass the entire backend suite.

Historical partial evidence: nine final streams from the earlier candidate backend's own EW encoder and PC-tail writer passed RTL with synthetic buffers (ADD/SUB/MUL, logical lengths 8/9/33). This is not an RK3588 output capture and does not close gate B.

The user has now supplied `/home/fedora/tinygrad` at
`078eee94d8f1912bb63ce786c250d2c24984844a` as the current source. Production
compilation/final-writer captures are saved by `tools/capture_current_backend.py`.
This source emits 13 additional initialized FP16 fields, now explicitly modeled
and checked in the decoder/RTL. The separate `rk_ew_dma` top now fetches unchanged
command BOs and follows their linked PC tasks; the raw-word port still refuses
nonzero PC metadata. Nine portable production captures and 53 synthetic DMA
cases exercise this boundary. See `docs/PC_DMA.md` and fresh source-bound reports.
RK hardware observations are still needed; this does not close gate B.

### C. Put the EW slice on YPCB

Use the existing known-good clock/reset/LED board work to check `fpga/ypcb.xdc`. Run synthesis/implementation with the correct installed part support. Confirm inferred BRAM rather than a large flop RAM, resource use, setup/hold timing and configuration-bank settings. Use SRAM/JTAG programming initially rather than rewriting boot flash.

The current board demo initializes and checks 336 halfwords in a bounded BRAM aperture and executes the unchanged production SUB(9) DMA chain, including intermediate scratch and padded lanes. The original three-terminal-operation raw-port demo remains a separate regression bench. See `docs/DMA_BOARD_DEMO.md`. Add ILA probes for state, start-valid/ready, memory handshakes and error code during board debug.

Acceptance: the actual board self-test passes after reset and repeated
reconfiguration. **Passed for the startup EW workload on 2026-10-26:** three
SRAM loads, four positive captures, 404 samples and 32 heartbeat transitions.
The routed implementation uses 3,168 LUTs, 895 registers, one RAMB36E1 and one
DSP48E1 at the unchanged 50 MHz constraint. Setup/hold/pulse slack is
1.188/0.067/9.600 ns. Four DSP pipelining advice warnings remain, with no
blocking DRC or waivers. This is target-frequency signoff, without an Fmax
sweep, SDF simulation, optical measurement or external memory readback.
See [EW_FPGA_TEST.md](EW_FPGA_TEST.md).

The Fedora continuation's DMA-based board top **passes** XC7 primitive mapping, a block-RAM inference assertion and functional mapped-netlist self-test/reset simulation using Xilinx's models. The current mapped board top contains two RAMB36E1 blocks (ROM and working RAM) and one DSP48E1; these are synthesis counts, not placed utilization. No routed delays/SDF are included. It is a prerequisite check, not this package's physical board acceptance. Local board pin/clock/part references are now commit-pinned. The selected Vivado implementation/signoff flow and verified configuration-bank settings are still needed before producing a reviewed bitstream.

The build-control follow-up fixes electrical-property ordering: supplied CONFIG_VOLTAGE/CFGBVS settings are now validated before synthesis and applied before checkpoints, implementation and DRC. It also requires BRAM inference and rejects missing/nonfinite/negative timing results or blocking/unknown DRC severity. Ten control-flow test methods pass under Tcl 9.0.3 and the installed Xilinx Tcl 8.6.13, with all Vivado operations mocked. No physical constraint is relaxed; these tests do not close gate C or replace a full Vivado run.

### D. Add the FP16 GEMM path, not an integer stand-in

Current increment: the previously staged profile, reader/operand front and
exact-product leaf are promoted into `rtl/` and joined by
`rk_cmac_product_front`. Portable captured commands and independent physical
BO/product oracles feed three extra benches through `make test`. The fresh
regression passes: 247 original entries and all three new benches per simulator.
See [CMAC_PRODUCT_PATH.md](CMAC_PRODUCT_PATH.md).
This connects raw commands through reads and products, not accumulation,
output writes, runtime gathers or the EW DMA/host/board path. Earlier staged
results discussed below remain evidence for their own snapshots only.

The corrected integration-only Icarus bench now passes 53,247 products/tags;
fresh complete-path XC7 mapping and full native regression also pass. This
does not close the numerical GEMM or physical gates. An additional
[donor conversion audit](NVDLA_CONVERSION_AUDIT.md)
confirms that the NVIDIA FP32-to-FP16 RTL saturates overflow/infinity and can
truncate a NaN payload to zero. Do not silently inherit that behavior or assume
the donor settles RK's product, accumulation or output-conversion policies.

Derive a *single supported* CNA/CORE/DPU 1x1-convolution/GEMM profile from the already-working examples/current backend. Preserve source and weight packing, counts, strides, logical CBUF allocation, CSC traversal, product/accumulator behavior, and output placement. Reuse the user's existing CSC model where it provides verified behavior; do not ignore existing simulation work.

Suggested components are `rk_cna_profile`, `rk_cbuf`, `rk_csc`, `rk_cmac_fp16`, `rk_cacc`, and DPU output conversion. These names describe the next work; no stub versions are supplied or counted as implemented. Decide leaf interfaces only after the actual source audit. Each stream should carry explicit valid, ready, data, lane/coordinate tags and end-of-reduction information. Retiming must preserve those tags.

Parameterize physical lane count while retaining logical channel groups and CBUF semantics. Start with one output accumulator and a serialized correct inner product if that reduces implementation risk. Do not round every multiplication to FP16 before accumulating unless that is what the observed RK numerical contract requires. Likewise, do not reorder reductions merely because mathematical addition is associative.

Audit soDLA's selected CBUF/CSC/CMAC/CACC/DMA modules independently. Integer control/storage components may be reusable after layout and interface checks. An FP16 datapath must be supplied explicitly. Keep upstream licensing and provenance if code is imported later.

The local `/home/fedora/hw` nvdlav1 checkout at
`8e06b1b9d85aab65b40d43d08eec5ea4681ff715` does supply FP16 CMAC RTL and
`NV_NVDLA_CACC_CALC_fp_48b.v`, with C-model product/alignment/accumulation references.
These are substantially stronger arithmetic inputs than the selected soDLA
integer MAC, but do not establish bit-exact equivalence to RK3588. Additional
YPCB XDMA and MIG project sources are under `/home/fedora/ypcb/ref/`; they are
candidate transport/DDR references, not an audited integrated FPGA shell.

The user also supplied `/home/fedora/vortex` at
`5ce5a1a915b06c42c60393a7ea24168e0e01078f`. Its tensor-core TFR path has an
FP16 11-by-11 mantissa multiplier with optional DSP inference and pipelined
alignment/accumulation. The TFR output is FP32 and its normalization flushes
exponent underflow; the alternative FPnew path uses FP16-to-FP32 multiplication
and an FP32 adder tree. These are useful implementation candidates, not evidence
of RK-compatible reduction/rounding. The selected scalar FPU is not the FP16
donor. See `docs/LOCAL_REFERENCES.md` for paths, hashes and dependency caveats.
No Vortex RTL was imported or simulated during this source audit.

The current compiler/final-writer audit now retains seven actual CMAC command
cases, including K=65, without executing gathers or tensor arithmetic. It
establishes a distinct 45-body-word/4-tail-word CMAC framing and exposes the
compiler's runtime input/output layout steps. See
[CMAC_ENCODER_CONTRACT.md](CMAC_ENCODER_CONTRACT.md). These are not hardware
captures or implemented GEMM support; host layout steps must not enter the
FPGA runtime as CPU fixups.

The `rk_cmac_address` leaf supplies packed address/tag sequencing and has
standalone and combined two-simulator evidence. It is now connected inside
the separate raw-product path, but not the EW host endpoint. It does not
supply CBUF, accumulation or hardware gather execution. See
[CMAC_ADDRESS_CANDIDATE.md](CMAC_ADDRESS_CANDIDATE.md). This does not close D.

The original staged raw CMAC profile decoder validates the 45-word FP16
body and distinct terminal tail. Its independent contract and RTL benches pass
1,920 cases per simulator, including seven unchanged compiler captures; Icarus
also passes four unknown-value rejections. That candidate is now promoted
unchanged into the separate raw-product path. See
[CMAC_PROFILE_CANDIDATE.md](CMAC_PROFILE_CANDIDATE.md). This neither integrates
CMAC DMA framing nor accepts GEMM in the production execution path.

A staged operand reader now connects that decoder to the address sequencer and
read-only halfword memory traffic. It carries the raw input/weight data and all
coordinate/reduction tags through response delays and consumer backpressure.
Its integration tests pass separately in both simulators, with 53,297 checked
operand pairs each; XC7 primitive mapping also passes. See
[CMAC_OPERAND_CANDIDATE.md](CMAC_OPERAND_CANDIDATE.md). Operand-stream completion
is not arithmetic completion or the final output-write acknowledgment.

A separate three-stage elastic FP16-product leaf preserves finite products
exactly in FP32 encoding, carrying the full 131-bit operand tag. Both simulators
pass 230,433 comparisons including stalls and reset cancellation; XC7 mapping
uses one DSP48E1. See [FP16_PRODUCT_CANDIDATE.md](FP16_PRODUCT_CANDIDATE.md).
It is now connected to the separate operand path, but does not choose accumulation
precision, reduction order or RK special-value behavior. In particular, its
FP32 output is not the NVIDIA donor's grouped 44-bit CMAC/CACC interface.

A separate [staged result writer](CMAC_WRITER_CANDIDATE.md) passes both native
simulators and XC7 mapping under `build/`. It accepts converted halfwords and completes only
after the final successful write response. It is not in the raw-command path; do not
treat its synthetic layout tests as numerical GEMM or RK capture evidence.

A [staged FP32-to-FP16 output converter](FP32_TO_FP16_CANDIDATE.md) now passes
330,793 comparisons in each native simulator and XC7 mapping. It is intended
only after accumulation, not between products and the accumulator. Its RNE
and exceptional-value contract remains a candidate; the RK TRM's generic
rounding description does not supply the missing numerical hardware evidence.
The converter and writer are now joined in a separate
[staged output tail](CMAC_OUTPUT_CANDIDATE.md), not to an accumulator or the
raw-command frontend. Final-source Verilator, four-state simulation and XC7
mapping pass. The wrapper retains stream
ownership through input gaps and final write acknowledgment, closes on the
last accepted result, and propagates sticky upstream cancellation.

Following the user's donor-baseline direction, a separate
[NVDLA converter adapter](NVDLA_CONVERTER_ADAPTER.md) now wraps the unmodified
NVIDIA output converter with raw tags and single-inflight flow control.
Verilator and the full four-state numerical run each pass 330,799 comparisons
with reset/backpressure checks, and XC7 mapping passes. The four-state runner
remains failed because its subsequent zero-tag-width parameter compilation
crashes Icarus; that rejection test is not counted as passed. A distinct
[donor-based output tail](CMAC_OUTPUT_NVDLA.md) now joins it to the unchanged
writer, with passing four-state integration, Verilator integration and XC7
mapping. It is not integrated with accumulation.
Earlier RNE/infinity/
canonical-NaN candidate tests and archives remain unchanged and are not
relabeled as donor-baseline evidence.

A [stateful NVDLA CACC candidate](CACC_REDUCTION_CANDIDATE.md) now accepts
ordered FP44 groups, retains the donor FP48 partial sum and buffers final FP32
results with raw tags. Direct donor tests compare 9,144 partial/final pairs
against an independent dyadic oracle. The reduction tests cover 2,712 groups,
faults, gaps, cancellation and resets. A synthesis-only constant-reject bug
in the wrapper's X checks was caught by inspecting the mapped netlist; that
initial structural pass is not accepted as working arithmetic. The fix retains
four-state rejection tests and adds nonconstant-control/arithmetic-presence
gates. Fresh native tests pass in both simulators; mapped-netlist verification
now also passes after a documented vendor-model startup harness correction.
Group formation from
actual FP16 operands, raw-command integration and final memory completion are
still required. Do not feed IEEE FP32 product bits into the FP44 interface.

A [staged serialized 64-pair FP16 group former](CMAC_GROUP_CANDIDATE.md) now
reuses the unmodified NVIDIA Booth multiplier and carry-save tree. Tests use
the executed integer Booth helper from the NVIDIA C-model header, not the
full SystemC model. Verilator and XC7 mapping pass; four-state testing remains
in progress. No numerical
GEMM or new raw-command acceptance is claimed. Its 64-pair donor grouping is
distinct from the RK backend's 32-channel storage atom and remains a working
assumption until the actual grouping is established.

A new [staged raw numerical core](CMAC_NVDLA_CORE_CANDIDATE.md) now joins the
unchanged terminal profile/reader to these donor leaves and acknowledged
output writes. Its full Verilator suite passes all 16 entries, including eight
fixture replays with 90,112 read transactions, 1,216 group values/tags and
1,088 acknowledged output halfwords. Whole-core XC7 primitive mapping now
passes; all 19 full four-state entries now pass as well. Functional netlist
replay remains running.
This is not a promoted host/board or full tinygrad
implementation. No runtime CPU gathers or arithmetic fixups were added.

A separate [staged CMAC DMA wrapper](CMAC_NVDLA_DMA_CANDIDATE.md) now consumes
the actual standalone descriptor's 45-word body count, fetches all 49 final
QWORDs unchanged and feeds the numerical core. It keeps CMAC framing distinct
from EW chaining. All 23 Verilator entries pass, including eight numerical
fixtures, two reset phases and repeated jobs. Icarus regression is running;
initial descriptor, framing, fetch and operand fault tests pass. No complete
four-state pass is claimed yet. DMA-wrapper XC7 mapping now passes; it is not
in the production host/board top.

A separate [staged CMAC AXI endpoint](CMAC_NVDLA_AXI_CANDIDATE.md) now joins
that DMA path to AXI-Lite job control and a 512-bit AXI RAM adapter. Its RKCM
identity makes the body-count convention explicit. Initial lint exposed
mixed reset styles; the corrected staged control/adapter use joint
asynchronous reset assertion. All 19 public-port Verilator numerical/fault/
reset entries now pass, and all ten successful saved memory images equal
their expected images. Four-state verification is running; no mapped endpoint,
PCIe/DDR, board or RK equivalence result is claimed yet.

A separate [staged CMAC BRAM board demo](CMAC_BRAM_BOARD_CANDIDATE.md) now
implements autonomous K=65 command-DMA replay and complete 8 KiB RAM checking.
Its eight-entry Verilator wrapper/reset/fault regression passes; four-state
testing and XC7 mapping are running. It keeps physical command
and operand addresses unchanged and does not add runtime CPU packing. The
production top remains the earlier EW demo; neither top is board-validated.

Acceptance: real small GEMM traces match RK at shape and packing boundaries, including K around atom boundaries (for example 7/8/9 and 31/32/33, plus the user's K=65 regression where applicable). Extend to full backend coverage incrementally, with an explicit supported-profile manifest.

### E. Host transport and full CI

Introduce a host transport independently from arithmetic: DMA/PIO command queue, 32/64-bit address policy, completion/interrupt records, timeouts and reset. Reuse a proven YPCB PCIe shell only with a verified lane/pin/clock/reset map. Add the FPGA transport underneath the existing final register encoder; don't bypass it by passing a tensor op directly to the FPGA.

The first memory-side component is now `rk_axi_mem`: a serial 16-bit-to-512-bit
AXI adapter matching the inspected local MIG-side widths, with aligned full-beat
reads, masked writes and B-channel completion. It does not integrate MIG, CDC,
PCIe or a host-visible queue. The nine production EW BO fixtures are additional
AXI behavioral-slave test targets; see [AXI_MEMORY.md](AXI_MEMORY.md) for contracts
and the source-bound verification reports for actual results.

The [OpenTPU reference review](LOCAL_REFERENCES.md#opentpu-board-and-transport-reference-2026-10-26)
confirms useful independent-host-clock, reset-drain and CDC patterns, but does
not supply a compatible DDR shell or a complete calibration/ECC recovery
policy. Keep the existing ECC MIG interface as the source preparation basis;
do not silently adopt OpenTPU's spare-lane/no-CH0-ECC profile. Before adding a
DDR lifecycle wrapper, bind one controller/channel's address window, widths,
IDs, clocks, calibration/initialization signals, ECC event meaning and joint
reset acknowledgment to its actual generated interface. The wrapper's directed
tests must cover admission before readiness, calibration loss or an
uncorrectable error during each AXI phase, outstanding handshakes, suppression
of successful completion after a fault, and recovery through verified drain
or joint reset. The current `memory_ready` admission bit alone supplies none
of that recovery. This remains source work to implement, not DDR acceptance.

The first binding check is now implemented as
`tools/ddr/check_interface.py`, with thirteen portable unit methods and
[fourteen recorded command checks](../build/ddr-interface-audit/1792970299029233481/copy-audit.json),
including both unit modes, isolated verification and tampering.
The original inputs remain `BLOCKED_DDR_INTEGRATION`: the generated controller
is absent, ECC metadata conflicts, and event/initialization/joint-reset bindings
are incomplete. No lifecycle wrapper was supplied with guessed signals.
The [archive source reference](../fpga/ddr/xdma_archive_reference.json) now
identifies generated controller HDL with matching logical widths and
byte-identical template/example files. Its configuration differs at both
channels' output-drive settings, RZQ/6 instead of RZQ/7. Continue logical
source binding under that separate identity; preserve the original electrical
preparation and blocked report. See [commands and evidence](AXI_MEMORY.md#controller-source-admission).

The next bound component is the [ECC control monitor](DDR_ECC_MONITOR.md).
It owns the actual archived control interface, programs/readbacks IRQ mask 3,
requires ECC enabled and zero sticky status, and quarantines on IRQ,
calibration loss, bus errors or timeout while preserving pending requests.
The lifecycle source trace shows why exported UI ECC vectors cannot be used
as valid-qualified raw events and why a clean status read after B cannot
authorize job success. A source-bound retirement/quiescence witness,
initialization ownership and whole-domain reset coordinator remain required
before joining this component to the job/DMA/AXI composite.

The [reviewed monitor target](../build/plan-ddr-monitor-implementation/1792971553929950788/monitor-validation-reviewed.json)
passes 29 Icarus/23 Verilator portable cases, 21 archived-control cases per
simulator and nine runner regressions. The
[23 evidence checks](../build/ddr-monitor-copy-audit/1792974487715872025/report.json)
also pass with all 74 selected files and originals unchanged. This is the
control-leaf source milestone; it supplies no initialized-memory, retirement,
whole-domain recovery or physical application result.

The [reset/fence source increment](DDR_LIFECYCLE.md) now implements the owned
SYS/UI0/UI1 reset sequence, actual branch-release barrier and readback-fence
protocol. Native reset cases pass 32 Icarus/23 Verilator; fence cases pass
71/54, with six specific invalid-parameter rejections per simulator and nine
verifier methods. Current faults suppress completion while pending requests
and already released reset branches remain stable. Stopped-clock timeout
revokes in-flight release permits before a later clock restart.

The actual archived MC has a WIDTH=1 periodic-read arbiter defect, so its
original source remains unqualified. A separately pinned source variant
defines that missing inhibit input, retains WIDTH>=2 behavior and preserves
the archive/electrical settings. Six directed MC/ECC cases pass identically
in both simulators with modeled PHY returns; the unrelated-bank read returns
before pending writes, while the exact-last-address read remains ordered.
This supports the selected source ordering argument. It does not establish
caller ownership/AW history, initialized memory, full AXI/UI/PHY integration,
original-BD reset coverage, physical DDR or RK numerical acceptance. Joining
the unchanged job/DMA/AXI components remains the next implementation step.

The intended CI path is `test_ops -> existing compiler -> final regcmd/BOs -> simulator or RTL`.
The separate [process-scoped RKNPUFPGA runtime](BACKEND_RUNTIME.md) now supplies
that route for the explicitly tested HALF EW subset through real Tensor
compilation and final-writer execution. It does not pass the full tinygrad
`test_ops` census or support runtime CPU gathers. Longer-term driver emulation
can wrap the model in the user's macOS VP; a VP is not required for the
standalone emulator or RTL tests.

The separate [USER2 BRAM source milestone](HOST_JTAG_BRAM.md) supplies a host
byte transport and one-job completion lifecycle without requiring a PCIe
shell. Its native tests consume the existing unchanged production BO captures;
its low-level Python tests are mocks, not live execution. The new backend
integration adds actual compiler-to-RTL execution for its supported subset.
A live source-audited image, broader backend coverage and DDR/PCIe remain
separate gates. The BRAM implementation does not waive their address,
visibility, reset or physical-map requirements.

## Deferred deliberately

The internal `rk_ew_axi` endpoint now joins AXI-Lite job control to raw-command
DMA and the AXI memory adapter. This advances package E without bypassing the
backend's final encoder. Its versioned descriptor/result contract and explicit
failures are in [HOST_CONTROL.md](HOST_CONTROL.md); fresh source-bound regression
and focused XC7 mapping pass at `f927a501cec9`, including mapped-control
simulation. All twenty whole-endpoint functional mapped replays now pass at
that source, and all eleven output images equal native RTL. The corrected
external reset-startup harness retains default GSR and all error assertions;
the prior sixteen-pass/four-failure attempt remains archived.
It is not a PCIe/MIG shell: the inspected
XDMA reference has its AXI-Lite master disabled, and CDC, calibration/ECC recovery,
host coherence and interrupt delivery still need integration. The board top and
electrical constraints are unchanged. Full NPU/GEMM and physical gates remain.

Three-core scheduling, overlapping ping-pong register groups, general convolution, LUT/activation and conversion modes, PPU, quantized/integer paths, calibrated timing modeling, host driver emulation and a full SystemC model are not counted as completed by this delivery. The implemented PC fetcher is serial EW-only, not a general RKNPU scheduler. Add broader modes when demanded by concrete backend streams, with tests before broad compatibility claims.
