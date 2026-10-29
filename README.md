# RK-NPU FPGA: first register-stream RTL slice

Evidence links under `build/` refer to workspace-local receipts and are not
included in a source checkout. Portable records are linked through
`verification/runs/` indexes. The newer framework/layout/reset and production
regression preparation reviews have not yet been archived there.

**Current direction, 2026-10-23:** use Vivado for implementation, with the
OpenTPU Vivado workflow as the reference. OpenXC7 placement/routing work is
retired from the continuation; its scripts and evidence remain historical.
The initial source/preparation pass was followed on 2026-10-26 by explicit
authorization to start FPGA testing as needed.

**Compute configuration:** the selected FP16 group is **C32/K16**: 32
input/reduction channels and 16 output kernels, with 512 parallel product
lanes. Here kernel K is GEMM's output dimension N, not GEMM's reduction K.
This describes our implemented parallel dot-product datapath; it does not
establish a square systolic topology for RK3588 silicon or measured end-to-end
MACs per clock. INT8/INT4 arithmetic and doubled INT8 throughput are unsupported.
See the [precision and layout boundary](docs/CMAC_ENCODER_CONTRACT.md#precision-and-compute-group-terminology).

**Application priority, 2026-10-27:** check
[TinyStories-260K before general tinygrad integration](docs/TINYSTORIES.md).
The CPU reference and complete 32-position donor-policy oracle pass, matching
28 greedy token IDs/text. All 36 learned projections have prepared FP16 tiles
totaling 557,056 bytes and 116 original raw programs. The shared full512
CMAC/EW/USER2 endpoint passes both native suites and routed 50 MHz timing:
setup +0.640 ns, hold +0.056 ns and pulse +9.600 ns, with zero failures.
Its [complete 32-position physical inference](docs/TINYSTORIES_FPGA_TEST.md)
now passes independent raw-wire audit: all 1,152 learned projections execute
on the FPGA, with every dense input/output and all 16,384 logits matching
the donor-policy oracle exactly. It generates the same 28 greedy token IDs
and text through 7,424 raw jobs and 11,136 tasks. The audit checks 2,743,153
actual JTAG scans and 30,408,704 complete output-buffer bytes before ACK.
Attention, normalization and other host operators remain explicitly on the
CPU, with no learned-dense CPU fallback or runtime CPU layout repair.
The earlier RPC/OOM and memory-guard failures retain their failed receipts.
The passing session uses the same image, unchanged 2 GiB admission minimum
and transport deadlines, with bounded waiting only at idle projection boundaries.
The [portable full32 archive](verification/runs/2026-10-27-tinystories-full32-fpga/index.json)
preserves 331 source/evidence files, including the complete actual JTAG trace;
compiled images/checkpoints and native tools remain excluded and hash-identified.
The earlier trained tile also passes repeated CMAC/FPGA compaction, with
360,448 complete BO bytes independently audited before ACK. Flash is unchanged.

**Full512 CH1 DDR inference passed, 2026-10-28:** the same complete TinyStories
workload now [passes independent physical review with DDR](docs/DDR_FULL512_FPGA_TEST.md).
All 1,152 learned FPGA projections, 16,384 logits and 28 generated token IDs
match the donor reference and the BRAM result exactly. The raw-wire audit
checks 2,984,893 JTAG scans, 7,424 jobs, 11,136 tasks and 30,408,704 complete
output-buffer bytes before ACK. First and repeated BOS controls also pass in
the same loaded controller epoch. All owned processes close; flash is unchanged.
The [portable full32 DDR archive](verification/runs/2026-10-28-full512-ddr-full32-fpga/index.json)
preserves 678 payloads, with every source/stored/decompressed byte and the
77 physical/479 image-model-runtime references independently verified.
Full memory capacity, injected ECC/recovery, PCIe and RK equivalence retain
their separate gates.

**Live tinygrad EW passed, 2026-10-29 HKT:** all eleven selected framework
cases pass [independent physical review](build/fpga-bringup/full512-ddr-framework-prep-v1/root-result-review.json)
on that same full512 CH1 DDR image. The pinned original compiler and final
writer execute ADD/SUB/MUL at lengths 8/9/33 and repeated SUB(9), while a runtime
gather is explicitly rejected. Review replays 117,578 actual JTAG scans,
11 FPGA jobs, 16 tasks and 1,081,344 complete BO bytes before ACK. There is no
numeric CPU fallback or runtime layout repair. The one volatile reload has
exact target/image receipts; every owned process closes before lease release,
and flash is unchanged. [CMAC framework layout support](docs/BACKEND_RUNTIME.md),
the complete backend suite and selected framework coverage on the later
capacity image retain separate gates.

**Full two-GiB capacity and raw-job recovery passed, 2026-10-29 HKT:** the
new [full512 CH1 capacity image](docs/DDR_CAPACITY_FPGA_TEST.md), tag `2c8f17dd`,
passes two complete global trials: 67,108,864 writes and 67,108,864 reads,
terminal status `0x68`, zero fault codes/sources. Original K65 CMAC and SUB(9)
pass before and after a second audited SRAM load, with 245,760 complete BO
bytes checked before ACK. Independent review consumes 59,130 actual JTAG scans
and 19,702 commands, rehashes all 234 frozen inputs and 60 physical artifacts,
and verifies exact DNA/IDCODE/TCK plus cleanup before lease release. All 512
product DSPs and both controllers remain; flash is unchanged. This qualifies
capacity and reconfiguration recovery, with physical FI/PCIe and full TinyStories
on this diagnostic image retaining separate gates.
The [portable capacity archive](verification/runs/2026-10-29-full512-capacity-fpga/index.json)
preserves 426 payloads, including all six complete traces and 171 hardware
sources. Independent byte review verifies source, stored and decompressed
content, all 60 physical artifacts and 234 preparation bindings; bitfiles,
checkpoints and native tools remain excluded and hash-identified.

**Framework CMAC layout component passed, 2026-10-29 HKT:** the
[raw-command layout encoder/DMA](docs/LAYOUT_DMA.md) passes both native
simulators for all 18 captured compiler gathers and 16,897 indices. Each
simulator also transports every raw halfword value, runs 34 positive cases
twice with complete-aperture comparisons, and checks 51 Icarus/50 Verilator
negative controls. Actual pinned compiler types pass the encoder check.
The default EW entry continues rejecting CMAC. The separate explicit
[full-DDR runtime](docs/FRAMEWORK_FULL_PROFILE.md) now has the integrated native
result below. This component has no new FPGA qualification.

**Joined full512 raw matmul pipelines passed, 2026-10-29 HKT:** the
[independent parent-model review](build/framework-layout-parent-replay-v6/root-result-review.json)
accepts all six captured compiler shapes through input layout, weight layout,
unchanged CMAC commands and output layout. All 24 stages check exact engine
read/write volumes and complete BO bytes before ACK: 3,358,720 pipeline bytes,
plus 122,880 baseline K65/SUB9 bytes. The original modeled one-MiB capacity
BIST/global-reset controls also pass. This uses actual full512 numerical RTL
and the joined parent/fabric with independent AXI RAM and minimal ECC-control
models. Actual MIG/PHY, framework reset/runtime, implementation and FPGA
qualification remain separate gates. Earlier failed attempts retain their own
receipts; the review binds each actual scenario to its source, immutable
simulator image and observed BOs.

**Joined compute-reset parent passed, 2026-10-29 HKT:** a fresh
[independent review](build/framework-reset-parent-model-v3/root-result-review.json)
accepts all six layout/CMAC pipelines with three actual compute resets each,
plus the original K65/SUB9 baseline. All 18 resets clear dirty compute state,
retain complete owned BOs and reject new work while their results are held.
The review compares 50 observed images totaling 6,615,040 BO bytes and binds
121 frozen inputs, 68 RTL sources and the compiled image. The seven scenarios
finish in 757.994 seconds with no new HDL warnings. Common assertion of both
compute reset trees repairs an observed CDC epoch mismatch; each tree retains
its local release sequencing. DDR reset/initialization signals are checked on
UI clock edges and modeled write counts remain unchanged across compute reset.
Actual MIG/PHY, framework runtime, timing and FPGA qualification remain pending.

**First ordinary framework matmul passed in native RTL, 2026-10-29 HKT:**
the pinned compiler and original final writer now execute logical FP16
`(M,N,K)=(1,16,32)` through three raw hardware layout jobs and one CMAC job.
The [independent wire/whole-BO review](build/framework-full-runtime-e2e-v2/root-result-review.json)
replays all 34,464 commands and compares 360,448 complete owned BO bytes before
ACK against a separate raw-layout/exact-finite-dot oracle. Constructor,
pre-CMAC and post-CMAC resets use the actual reset service. CPU gather calls
and creation of CPU workload programs are blocked; five pinned CPU queue
helpers initialize explicitly before the workload. This is an unselected
runtime candidate using actual full512 RTL with independent AXI RAM/ECC-control
models, not physical or RK qualification. The earlier instrumentation failure
is preserved. Six-shape runtime coverage and actual-controller/image integration
remain required before changing the default adapter's CMAC rejection.

**Public full-DDR framework profile passed six native shapes, 2026-10-29 HKT:**
the [current public-source review](build/framework-public-runtime-coverage-v1/root-result-review.json)
accepts all six actual Tensor/compiler/final-writer trials through the rebuilt
full512 endpoint: 24 jobs, 18 hardware layouts, six CMAC submissions, 18 compute
resets, 328,587 commands and 2,375,680 complete BO bytes before ACK. A separate
wire audit proves no host reload of tensor or scratch BOs after each pipeline
starts. The six scenarios complete in 741.109 seconds with up to four native
processes. The [explicit profile](docs/FRAMEWORK_FULL_PROFILE.md), its 68-source
ordered RTL selection and 35 protocol/source controls are now public paths.
This uses independent AXI RAM/minimal ECC-control models. The fresh complete
V22 regression and actual-vendor-controller runtime trial are running; physical
implementation and FPGA/RK qualification remain separate.

**Current production validation, 2026-10-29 HKT:** the fresh V21 source copy
passes complete serial `make test` in 1,088.121 seconds. Its
[independent review](build/production-model-auditors/current-v21/root-review.json)
rehashes all 1,133 original/copied files, all existing numerical/RTL/host
receipts, the strict capacity-parent matrix and both new layout suites.
The increment adds exactly six layout source/test paths and changes only
`Makefile` relative to V20. The separate compute-reset and dispatcher
preparation candidates are outside this source snapshot. Their separate native
parent review above does not qualify the production runtime or physical image.

**Preceding production validation, 2026-10-29 HKT:** the fresh V20 source copy
passes serial `make test` in 1,048.195 seconds.
[Independent review](build/production-model-auditors/current-v20/root-review.json)
rehashes all 1,127 original/copied files and the complete native/host receipts.
The three-file raw-status auditor increment adds six mutation controls;
all sixteen pass, including exact descriptor-valid bits and active ownership.
The strict capacity-parent verifier accepts all 32 commands, 15 result groups,
12 simulator images and 38 source/import bindings. This default source/native
qualification remains separate from the physical result above.

**Preceding production validation, 2026-10-28 HKT:** the fresh V19 source copy
passes serial `make test` in 1,246.321 seconds under a one-CPU/six-GiB limit.
The [independent review](build/production-model-auditors/current-v19/root-review.json)
rehashes all 1,127 original/copied inputs and the complete numerical/RTL/host
receipts, including the admission timing fix. The published capacity-parent
profile's strict verifier accepts 32 commands, 15 result groups, 12 simulator
images and 38 source/import bindings, including the paired original/candidate
controllers, 12 client, 12 capacity-wire and ten raw-job wire controls.
This qualifies source/native tests; capacity-enabled routing and physical
capacity remain separate pending gates.

The V20 result above covers the later three-file wire-auditor increment.
V19 remains a preserved earlier source snapshot.

The subsequent [explicit EW-DDR runtime admission](docs/BACKEND_RUNTIME.md)
passes its separate 23-control/eleven-scenario compiler-to-RTL regression.
It preserves the default BRAM behavior and the original final encoder.
The V19 complete default regression also passes after that two-file change;
the eleven selected physical DDR framework cases pass as described above.
The preceding
[V18 snapshot](build/production-model-auditors/current-v18/root-review.json) and
[V17 snapshot](build/production-model-auditors/current-v17/root-review.json)
remain preserved separately.

**Current capacity timing fix, 2026-10-29 HKT:** fresh synthesis of the
descriptor-admission change passes its
[independent review](build/full512-capacity-admission-vivado-run-v3/root-synth-review.json),
with 295,763 LUTs, all 512 product DSPs, 516 total DSPs and 242 IOs.
[Placement/routing](build/full512-capacity-admission-route-run-v1/report.json)
and one targeted repair both failed setup by 9 ps. The measured path drives
the capacity adapter's 96-bit retirement snapshot enable. A new source variant
stores one acceptance bit for the strict monitor's validated constant tuple;
all fault and retirement checks remain. Its
[paired adapter comparison](build/full512-capacity-retire-snapshot-controls-v1/root-paired-v3-review.json)
and [fast parent model](build/full512-capacity-retire-fast-model-v1/root-result-review.json)
pass. Its [fresh actual-controller model](build/full512-capacity-retire-controller-v1/root-result-review.json)
also passes full modeled one-MiB BIST/reset, with 32,768 writes and reads.
Fresh [source synthesis](build/full512-capacity-retire-vivado-run-v1/root-synth-review.json)
passes at 295,757 LUTs with all 512 product/516 total DSPs and 242 IOs.
Fresh [placement/routing](build/full512-capacity-retire-route-run-v1/root-route-review.json)
now passes independent review: setup +0.027 ns, hold +0.052 ns and pulse
+0.264 ns, with zero failures or routing errors. All 512 product DSPs remain;
the routed LUT count is 290,266. The exact DRC inventory and all 232 reported
pulse rows pass, together with the reset/CDC/source checks.
The complete V19 regression and the
[fresh actual-controller-source capacity model](build/full512-capacity-parent-admission-controller-v1/root-result-review.json)
pass. That model checks the full modeled 1 MiB/two-trial BIST and global reset;
the physical two-GiB result now passes as described above. Fresh image/test preparation
binds the retirement variant under source tag `2c8f17dd`; seven offline
admission controls pass. The routed IO review passes all 242 ports/1,936
properties. The successful emission corrects only two audit-helper prefix
arguments after the first stopped before writing a bitfile; all constant,
timing and DRC gates remain. The independent bitfile audit and physical
capacity/reconfiguration trial pass; the earlier tag `670fdaf8` does not qualify
this source. This diagnostic work preserves the earlier independently qualified
TinyStories images. See the [active plan](docs/REVIEW_AND_PLAN.md).

**Preceding V16 validation:** serial `make test` passed
in 876.048 seconds with copied-source manifest `7c4d4cdc91c0`, including both 249-entry EW suites,
both 15-case host suites, 61 TinyStories controls, 11 DDR endpoint controls,
89 additional DDR software controls and six dual-control native commands. The
[independent source/host review](build/production-model-auditors/current-v16/root-review.json)
checks all 1,105 copied/live inputs and both complete host receipts. Seven
software capacity controls and twelve bounded capacity-native cases now pass
inside default Make. The [V16 portable archive](verification/runs/2026-10-28-production-ddr-capacity-rtl/index.json)
preserves 2,705 payloads, including the complete source snapshot, host/capacity
receipts and V15 report history. Root independently rehashes all payloads,
the 1,105 source bindings and 1,128 binary/tool exclusions. The
[preceding V15 archive](verification/runs/2026-10-28-production-ddr-capacity-plan/index.json)
retains its separate 1,098-file source snapshot and results.
The new emitter gate checks exact warning counts for both DRC ruledecks before
writing a checkpoint or bitstream; its 14 focused controls pass.
The DDR model audit adds an explicit repeated-BOS gate; all 17 focused DDR
controls and 61 TinyStories controls pass within the completed V16 snapshot.
The prior private run's missing-build-fixture failure remains preserved; the corrected
channel controls pass in a source-only copy and retain a separate full-package
audit. Default Make does not qualify the complete joined DDR numerical design.
The async components have separate native/mapping results. Both the direct
CMAC bridge and its new shared-dispatch composition pass all nine modes in
both simulators; the two-clock EW/DDR model passes its independent same-ELF
21-case union. These results remain separate from the default Make snapshot.
The earlier
[selected production archive](verification/runs/2026-10-27-production-ddr-controls/index.json)
preserves its own 1,107.786-second snapshot.
A separate [original-profile MIG generation](docs/DDR_ORIGINAL_MIG.md) now
produces actual RZQ/7 controller sources. Their real-source async EW composition
now has a routed EW/DDR checkpoint with setup +0.105 ns, hold +0.039 ns and
pulse width +0.264 ns; project reset/job/memory/mailbox audits pass. See
[the board preparation and remaining gates](docs/DDR_BOARD_PREPARATION.md).
That checkpoint is the C0-active historical baseline. The explicit CH1-active
profile now has its separate routed image and first physical result below,
retaining both original controllers and ECC.

The [shared full512/EW DDR source candidate](docs/DDR_DUAL_ENDPOINT.md) now
has separate CSR banks and a global owner through readback/ACK. All nine
original K65 numerical/fault modes pass in both simulators through the actual
512-product dispatcher. Its independently rehashed
[155-file logical archive](verification/runs/2026-10-27-full512-dispatch-logical/index.json)
preserves both native suites and the exact source/golden bytes. The first
[joined AXI/UI/MC model executions](docs/DDR_FULL512_MODEL.md) also pass their
independent checks for original K65 CMAC and SUB(9), on the same binary with
separate reset epochs. The original trained tile also passes CMAC/EW/CMAC
reuse in one controller epoch with 270,336 BO bytes checked before ACK. The
[shared-data area candidate](docs/DDR_AREA_CANDIDATE.md) has a nominal
293,826-LUT constrained post-opt fit with all 512 products. Its cell equivalence and
nine dispatcher modes pass in both simulators, and its fresh trained controller
reuse passes with 270,336 BO bytes checked before ACK. Mapped inventory checks
pass, and all 33 controller cases pass. The first routed checkpoint fails setup
at -0.551 ns; hold and pulse pass at +0.048/+0.264 ns. The native repair now
passes setup/hold/pulse at +0.004/+0.048/+0.264 ns, with all strict audits.
Its wrapper preserves a provenance failure caused by an unused emitter-origin
change. A fresh strict requalification and independent review now pass, checking
all 343 inputs and 422,138 fully routed nets with zero routing errors. The
[portable timing archive](verification/runs/2026-10-28-full512-ddr-timing/index.json)
preserves that result and the failed parent receipts. See the
[timing diagnosis and repair](docs/DDR_TIMING_REPAIR.md). Its emitted image now
passes the independent bitfile audit and the physical trained-tile result below.

**First physical full512 DDR milestone, 2026-10-28:** the
[audited trained-tile trial](docs/DDR_FULL512_FPGA_TEST.md) passes on CH1 with
all 512 products retained. One reviewed volatile load reached INIT/DONE and
source tag `5e99f881`. Six scratch lines passed in two write orders, then the
unchanged CMAC/EW/CMAC/EW sequence matched all 360,448 complete BO bytes before
ACK. Independent replay checks 26,204 JTAG scans and 8,732 commands, bound to
the exact image, target DNA and raw IDCODE. Cleanup completes before shared
lease release. Flash is untouched. The later full-model DDR result above
passes separately; capacity/ECC injection/recovery, PCIe and RK equivalence remain open.

The [first complete physical DDR BOS forward](build/fpga-bringup/full512-ddr-model-prep-v4/root-first-bos-review.json)
also passes independent replay: all 36 learned projections, 232 raw jobs,
348 tasks, 950,272 complete output-BO bytes and all 512 donor-policy logits
match. It generates token 403, `Once`. That run then failed on observer-path
bookkeeping before repeated BOS; its overall failure is preserved. A fresh
session with the corrected runner has now passed both first and repeated BOS
under independent root replay on one loaded controller epoch. Both produce
the same exact logit row and token. The completed 32-position DDR workload
now [passes independent root acceptance](build/fpga-bringup/full512-ddr-model-prep-v5/root-full32-review.json).

The next [capacity-test increment](docs/DDR_CAPACITY_PREPARATION.md) adds a
64-byte sweep sequencer, AXI adapter and existing fence/ECC-monitor composition.
`make ddr-capacity-controls` passes seven software controls and six bounded
configurations in each simulator, including nonzero/high-boundary addresses
and fault/drain behavior. The target is now part of default `make test`; the
fresh V16 full regression passes with an independent source/receipt review. No capacity
image has been built or programmed, and physical capacity remains unqualified.
The integrated diagnostic service separately passes modeled ownership,
sweep/fault/recovery tests and Vivado OOC resource synthesis: 1,821 LUTs,
2,094 registers, no BRAM/DSP. Full-parent wiring and fast modeled normal-job,
one-MiB BIST and reset replay now pass. Fresh full-parent synthesis passes
at 295,755 LUTs with all 512 products and both controllers; placement/routing
is active. Image review and physical capacity testing remain open. See the
[active execution plan](docs/REVIEW_AND_PLAN.md).

**First physical DDR milestone, 2026-10-28 HKT:** the
[CH1 scratch and raw EW trial](docs/DDR_FPGA_TEST.md) passes independent
actual-wire audit. One reviewed volatile-SRAM load reached initialized,
healthy CH1 memory. Six scratch lines passed in both write orders, then the
unchanged captured SUB(9) program completed two tasks with all 102,400 owned
BO bytes matching before ACK. The audit checks 24,238 actual JTAG scans and
8,078 mailbox commands, bound to source tag `a2dfec21` and the exact image.
Its routed setup/hold/pulse margins are +0.006/+0.035/+0.264 ns. The
[portable archive](verification/runs/2026-10-27-ch1-ddr-first-fpga/index.json)
preserves frozen sources and the complete actual trace. Flash is unchanged.
Full capacity, injected ECC faults/recovery, full512/DDR, PCIe, RK equivalence
and production electrical qualification remain open.

**Logical DDR milestone, 2026-10-27:** the
[independent same-binary union](build/ddr-endpoint-current/independent-all20-o3-union-v2.json)
passes all twenty raw BO/fault/recovery cases. The original repeat timeout is
preserved; its unchanged retry passes under the original 1,800-second limit.
The [130-entry selected archive](verification/runs/2026-10-27-ddr-all20-logical/index.json)
preserves the local sources and actual text evidence. The
[new SYS50/UI133 composition](docs/DDR_ASYNC_ENDPOINT.md) adds a separate
terminal-count fault case. Its optimized host-read path now passes all21
logical cases with [portable source and raw evidence](verification/runs/2026-10-27-ddr-read-snapshot-all21/index.json).
Physical DDR/PCIe and full512/DDR integration remain open.

**FPGA milestone passed, 2026-10-26:** the separate EW startup image passed
three volatile-SRAM loads on the YPCB XC7K480T, including repeated
reconfiguration. Four passive JTAG captures contain 404 valid observations
of PASS=1 / FAIL=0 and 32 heartbeat transitions. Its built-in scoreboard
checks the unchanged SUB(9) raw-command workload and 336 mapped halfwords.
See the [hardware report and preserved raw evidence](docs/EW_FPGA_TEST.md).
The 50 MHz Vivado implementation passes setup, hold, pulse width and routing
checks with zero waivers. Flash is unchanged. This result covers the autonomous
EW BRAM self-test; full GEMM, host transport, DDR, PCIe and RK3588 equivalence
retain their separate acceptance gates.
Keep the full C32/K16 DSP-prefix candidate with 512 parallel CMAC products as
the performance target; this EW milestone supplies no full-array fit result.

**Full512 FPGA milestone passed, 2026-10-27:** the registered-RAM-control
C32/K16 image passed three volatile-SRAM loads, including two reconfigurations,
on the YPCB XC7K480T. Four passive JTAG captures contain 404 valid observations
of PASS=1 / FAIL=0 and 32 heartbeat transitions. Its source-bound finite K65
scoreboard executes the raw 49-QWORD program, twelve full frames and 64
numerical writes, then checks all 4,096 halfwords. SAMPLE observes its terminal
outputs; it does not directly read RAM. Flash is unchanged. See the
[physical report and preserved evidence](docs/CMAC_FPGA_TEST.md).
This validates the autonomous workload; general GEMM/RK equivalence, host
transport, DDR, PCIe and broader backend coverage retain separate gates.

**Full512 timing fixed, 2026-10-26:** the registered-RAM-control pipeline now
passes routed timing at the unchanged 50 MHz target: setup +0.987 ns, hold
+0.057 ns and pulse width +9.600 ns, with zero failing endpoints and no
unclocked/unconstrained internal endpoints. It retains all 512 CMAC products,
using 267,240 LUTs (89.50%), 35,822 registers, six BRAM tiles and 515 total
DSPs. Routed DRC has zero RAM async-control findings; 2,060 DSP pipelining
advisories retain their original severity. Both complete native board suites
pass (11 Icarus and 10 Verilator cases). The independent routed INIT/IO/DSP
review is complete. Mapped startup and its expected-rejection control passed,
followed by exact-image review and the physical result above. See the
[current timing review](build/full512-regmem-implementation/20261026T111740Z/root-timing-review.json)
and [implementation notes](docs/CMAC_PIPELINE_TIMING.md). Its
[193-file text archive](verification/runs/2026-10-26-full512-regmem-timing/index.json)
preserves the complete frozen source snapshot and selected reports without
checkpoints, netlists or compiled images.

Timing history: the original [full512 routed build](build/full512-vivado-implementation/1792992222236656161/run.json)
retained all 512 CMAC products but failed setup at WNS -13.249 ns. The separate
balanced-selector candidate also failed: routed WNS was -2.350 ns and
post-route optimization reached -1.686 ns. Neither produced a bitstream. A new
registered-preparation-stage candidate now has a routed timing report at the
unchanged 20 ns clock: setup WNS +0.045 ns (45 ps), hold WHS +0.075 ns and pulse
width +9.600 ns, with zero failing endpoints in all three groups. No-clock and
unconstrained-internal endpoint checks each report zero. Routed utilization is
267,210 LUTs (89.49%), 35,776 registers, six BRAM tiles and 515 total DSPs,
including 512 CMAC products. The DRC report contains 2,081 warning-level
findings: DSP input/output pipelining advice, 20 RAM async-control findings and
one rule-limit warning. No source constraint or DRC waiver changed. Startup,
image, electrical and DRC-warning review plus mapped validation remain before
any bitstream; the vendor mapped replay exceeded its license instance limit.
The registered-BRAM-control candidate passes both complete native board suites
and the newer routed timing checks above. See the pipeline timing notes for its
contract, export-boundary diagnosis and current evidence. Those earlier
variants emitted no bitstream; the newer registered-RAM image has the separate
physical result above. See the
[timing candidate notes](docs/CMAC_PIPELINE_TIMING.md),
[frozen source package](build/full512-pipeline-preparation/1793008000/report.json),
[routed timing report](build/full512-pipeline-preparation/1793008000/implementation/timing.rpt),
[DRC report](build/full512-pipeline-preparation/1793008000/implementation/drc.rpt), and
[current build receipt](build/full512-pipeline-implementation/1793007479542120029/run.json).
The [selected timing evidence](verification/runs/2026-10-26-full512-pipeline-timing/index.json)
is preserved in the repository without binary checkpoints or an image-admission claim.

**Source implementation increment, 2026-10-26:** a separate EW startup-reset
profile now runs the unchanged captured SUB(9) self-test without consuming
R28. It uses an initialized delay chain and registered reset output, informed
by the preserved OpenTPU registered-reset reference. The existing external-R28
profile remains available. `make fpga-prepare-startup` freezes sources and a
checkpoint-only Vivado script without starting Vivado; its board-review fields
begin incomplete. See [implementation and commands](docs/REVIEW_AND_PLAN_HISTORY.md#current-implementation-increment-ew-board-bring-up).

A separate [USER2 host-controlled BRAM candidate](docs/HOST_JTAG_BRAM.md) now
connects the unchanged raw-command DMA and job controller to OpenTPU's frozen
mailbox framing, with stdlib XVC and native Vivado scan clients. Its exact
50 MHz routed image passes CDC, startup, timing and image review. The
[physical USER2 test](docs/HOST_FPGA_TEST.md) now passes all nine captured
ADD/SUB/MUL workloads, repeated SUB(9), explicit E1 fault persistence across
TAP reset/reconnect, and SUB(9) after SRAM reconfiguration. Eleven successful
jobs complete sixteen linked tasks with all 1,077,248 owned BO bytes compared
before ACK. Two volatile loads pass; flash is unchanged. This tests captured
raw final-word BOs; live compiler-to-card, full C32/K16 host execution, DDR and
PCIe retain separate gates.

The [latest passing full production regression](build/production-dual-endpoint/20261026T203139Z/report.json)
passes serial `make test` in1260.964seconds:73 root unit methods,1,087,299 C++ comparisons,
249 EW RTL entries and three raw-product CMAC benches in each simulator. Its
separate host suites pass all15 scenarios per simulator and53 host controls.
The private copy also passes21 TinyStories controls and both registered-RAM
native suites. Application-driver controls/code added later have separate
evidence; they are not attributed to that earlier copy.
The production source manifest is
`eff34ab69dcb5bbf6bb8c70f10d91e34047725469e60c139242ddff5d97f5f9f`;
the host profile separately binds
`35bab7f90f268167956ee6dfc147c5074c0086e923067fd4bd28e82f65736f26`.
The earlier [parallel full Make run](build/production-tinystories-controls/20261026T182707Z/report.json)
failed when the unchanged Icarus host SUB(9) case exceeded its600-second
limit. That failure is preserved. Its [unchanged-case replay](build/tinystories-host-timeout-replay/20261026T184305Z/report.json)
passed in654.328 seconds with all1600 memory rows matching; it does not
relabel the full Make run as passing.
The later serial pass retains all individual deadlines; its asynchronous
Icarus case completes in565.728seconds, within the unchanged600-second limit.
All [82 EW memory images](build/plan-ddr-lifecycle-implementation/1792976927285576710/memory-image-comparison.json)
and [13 host readback images](build/plan-ddr-lifecycle-implementation/1792976927285576710/host-memory-image-comparison.json)
match between simulators. This verifies the selected source in simulation, not
startup on the card, timing, electrical signoff or an FPGA image. The
serialized numerical CMAC remains a separate qualification and preparation
profile; the full C32/K16 prerequisite chain is not waived.

The new [DDR source checker](docs/AXI_MEMORY.md#controller-source-admission)
passes thirteen portable unit methods. Its audit records fourteen passing
command checks, including both unit modes, isolated verification and tampering.
It rejects the incomplete original MIG binding with five integration blockers;
it does not implement or simulate a DDR lifecycle wrapper. A separately
pinned archive supplies actual generated AXI/ECC sources for further offline
binding, with an explicitly different output-drive profile. No electrical
setting or original qualification was changed to use that candidate.

The separate [ECC control monitor](docs/DDR_ECC_MONITOR.md) now verifies that
archive's actual control interface, configures IRQ reporting and quarantines
while preserving pending transactions. Its portable cases pass 29 Icarus and
23 Verilator scenarios; all 21 archived-control scenarios pass per simulator.
Nine runner regressions and [23 evidence checks](build/ddr-monitor-copy-audit/1792974487715872025/report.json)
also pass. Joined initialization, AW/ownership tracking, platform recovery and
DDR job admission remain pending; a clean monitor snapshot supplies no
successful-job proof.

The new [reset and fence components](docs/DDR_LIFECYCLE.md) pass both simulators,
including stopped clocks, stale-permit revocation and current-fault priority.
A separately identified one-requestor arbiter fix also enables six directed
ordering/ECC cases against the actual archived MC in both simulators. The
original defective controller remains unqualified. This establishes component
and modeled-controller evidence; the joined DDR job path and physical memory
remain unverified.

The separate [production backend integration](docs/BACKEND_RUNTIME.md) now
compiles real tinygrad Tensor programs through the unchanged Rockchip final
writer and executes their bytes on the RTL frame endpoint. Its
[reviewed run](build/backend-rtl/1792958040917797032/report.json) passes ten
numerical cases and one explicit runtime-gather rejection: 11 submissions,
16 linked tasks and 1,081,344 complete BO bytes checked. This is an offline
`RKNPUFPGA` device alias with an injected test link, not full `test_ops`, a
physical JTAG result or a complete RK backend.

Optional [ILA preparation](docs/FPGA_DEBUG.md) now covers autonomous EW and
host-controlled USER2 profiles, with 14 probes and separate USER1 debug-hub
ownership. Sixteen source/control checks pass under Tcl 9.0.3 and vendor
Tcl 8.6.13. The final snapshot dependency fix was checked after the full
regression; it changes no RTL, probe Tcl or default physical flow. No debug
core was implemented and no capture was performed.

**Full-size offline qualification, 2026-10-26:** the fresh
[own-parent-validated checkpoint package](build/rknpu-dsp-prefix-checkpoint-preflight/1792950744001340936/report.json)
now admits its exact current area/native/raw-board/mapped parents. The native
and mapped arrays retain all 512 products and pass the original 208-frame
corpus; all nine raw-board modes pass. The mapped-library checker now validates
each generated protection-hash pair and its unconditional initialization
check, with original failures preserved. See [qualification details](docs/REVIEW_AND_PLAN_HISTORY.md#full-c32k16-qualification-refresh-2026-10-26).
This is source preparation and simulation, with no Vivado implementation,
physical fit/timing signoff, reviewed bitstream or FPGA execution result.

The separate [full 512-product startup profile](docs/CMAC_ARRAY_STARTUP.md)
now reuses the unchanged DSP-prefix array with configuration-time reset and
no R28 input. Its [fresh native suites](build/plan-full512-startup-implementation/1792966979950932621/startup-native-summary.json)
pass 22 Icarus and 20 Verilator cases, including both LED polarities and complete
K=65 memory/numerical checks. The original R28 profile and its parents remain
unchanged. Native cold starts do not establish physical reconfiguration or
mapped startup behavior.
The [startup checkpoint package](build/full512-startup-preparation/1792967676447887367/report.json)
also passes [eleven copy-audit controls](build/full512-startup-package-audit/1792967676447887367/report.json).
Its source/evidence integrity is verified; board review and current external
arithmetic parents are still required before any separately authorized build.

The [serialized numerical board package](build/plan-source-implementation-1792942734594175489/serial-vivado-reviewed/report.json)
separately binds all eight Verilator and nine Icarus board modes, including
the actual compiled binaries and complete command logs. Both it and the
[EW startup package](build/ew-fpga-preparation/startup-1792967662354184758/report.json)
remain `SOURCE_INTACT_REVIEW_PENDING`: no completed board/electrical review,
Vivado build, bitstream or hardware pass is implied.
The [USER2 BRAM package](build/host-jtag-preparation/1792967662198630675/report.json)
also binds both complete host suites and independently copied evidence, with
the same pending board-review status.

**Historical review validation, 2026-10-23 03:26 HKT:** the fresh
[`make -j2 test` run](build/review-all-20261022T190646Z/final-production/production-validation.json)
passes in 296.016 seconds: 57 unit methods, 1,087,299 C++ comparisons, both
247-entry EW suites and all three raw-product CMAC benches in each simulator.
All five reports match source manifest
`bb6a5366036d6d951b74a1c48b018b4634f9261cee02a674cee4096fc6903d2d`,
unchanged during the run; all [82 simulator memory images](build/review-all-20261022T190646Z/final-production/memory-image-comparison.json)
match byte-for-byte. The [first whole attempt](build/review-all-20261022T190646Z/production-validation.json)
remains failed at the Verilator packed-buffer parser portability issue; the
corrected parser was checked in both simulators before this fresh retry.
This is production simulation evidence only. No Vivado build or native
openXC7 implementation ran. Full C32/K16 build admission still rejects its
separate stale parent evidence; the preparation artifact does not waive that
gate or establish FPGA/RK compatibility, timing, DRC or bitstream readiness.

**Historical status, 2026-10-09:** that source-identical production regression passes both 247-entry EW RTL suites, all three CMAC product benches per simulator, 49 host/model methods and 1,087,299 C++ comparisons. It uses private generated-C++ OPT0 flags with unchanged source, inputs, assertions and deadlines; the earlier default-profile compile TIMEOUT/FAIL records remain failed. These results do not validate the current review edits; their fresh regression is separate. This is not accumulated GEMM or full C32/K16 mapped-board acceptance. Physical FPGA validation, timing closure and RK3588 differential captures remain pending. No bitstream is supplied. See [verification/README.md](verification/README.md) for source-bound evidence.

Historical full-size preparation: the corrected-mux engine completes
[small native qualification at 06:26:34 HKT on 2026-10-09](build/openxc7/recursive-mux-feedthrough-qualification-1791497608027018932/report.json).
The [fresh full C32/K16 pack](build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json)
completes at 06:48:48 HKT, retaining 512 parallel CMAC products/515 total DSPs,
six BRAMs and the 50 MHz target. Its 523,522-cell census and necessary LUT bound
295,195 versus 298,600 available pass; this is not placed fit or timing acceptance.
The [new full placement report](build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json)
passes fresh input/source admission, 27 host guard tests and generated checks;
its native child starts at 07:02:43 HKT and later reaches the main analytical
placer for 419,259 roots. It terminates at 19:02:48 HKT with the original
43,200-second host timeout (`FAIL_PREFIX_SHARED_RECURSIVE_MUX_HEAP_PLACE`,
native return -9); no `placed.json` is produced. This is a timeout, not a fit
rejection or a completed placement. A guarded 24-hour retry is refused at
source admission because Fedora's Python 3.14.8 update changed a recorded
`/usr/bin/python3.14` input hash; the old qualification cannot authorize a
retry under the changed environment. A fresh current-environment qualification
and pack chain is required before another placement attempt.
The [source-bound log-scope audit](build/openxc7/recursive-mux-analytic-scope-typed-1791501546954868842/report.json)
confirms that its 419,259 analytic roots are not the 523,522-cell packed census.
The running wrapper's incorrect count assertion is preserved; full-output
membership/BEL validation remains required, not replaced by this diagnostic.
The [separate complete-output reviewer](tools/openxc7/review_valid_pack_recursive_mux_completed_placement.py)
is prepared with 16 passing host controls and rejects the current producer
before output/tools. It requires genuine zero-code native completion and all
original full-cell/BEL/DSP/clock guards; no actual full review has run. The
preserved producer is now timed out, not RUNNING. The earlier direct invocation
was rejected while it was live; no post-timeout review invocation has run.
The [review-aware full-route handoff](tools/openxc7/route_reviewed_recursive_mux_full_board.py)
is separately prepared with 57 passing host controls and generated checks.
The prior invocation was rejected while placement was live; after its timeout,
no route command was launched. The original failed history and all full-route
guards remain; no completed review or full route exists.
The matching [frame/packet handoffs](build/reviewed_recursive_mux_frames_packets_preflight_actual_20261009.md)
are prepared: 36 frame controls and 14 explicit-physical-scope packet controls
pass, and the combined route/frame/packet selection passes 107 host methods.
Initial fixture-race/missing-report-flag failures remain preserved. No actual
full conversion/packet has run; any future packet remains NOT_FOR_PROGRAMMING
until the separate numerical/timing/electrical/DRC/CRC gates pass.
The [fresh bounded placement-state audit](build/openxc7/recursive-mux-observed-heap-samples-1791505404695579980/report.json)
observes two different ordinary LUT searches and a queue change from 290432
to 279179 entries. This confirms changing native work, not a placed percentage,
convergence, full-cluster audit or completed placement; the same worker is kept.
The [later four-snapshot audit](build/openxc7/recursive-mux-observed-heap-samples-1791532179521796957/report.json)
captures another changing root and queue 68076→66904, with the native
no-reset iteration counter rising 2868835→2921452. The worker is still in
strict legalization; those internal counters are not fit, completion or ETA.
See [the exact live capture and limits](docs/OPENXC7.md).
The [optional full native cluster export](build/full_native_cluster_export_preflight_actual_20261009.md)
now completes at12:47:06 HKT. The entire523,522-cell packed graph is
byte-identical to its parent, retaining515 DSPs/six BRAMs. All20,414 exported
clusters (29 exact geometry classes) have individual location witnesses; none
has zero candidates. Overlapping witnesses are not a joint fit, full placement,
route or timing acceptance. The original full placement worker is unchanged.
The [fresh saved-small-packet CRC census](build/small_packet_crc_scope_actual_20261009.md)
observes 546 packets, zero CRC-register writes and three CRC resets in the
unchanged small encoding sample. Frame-data/ECC comparison does not close this
separate gate; qualified CRC emission/verification remains required. This is
not a full-size numerical or physical result, and the initial IDCODE-probe
failure is retained separately.
The [offline packet-CRC reader qualification](build/packet_crc_reader_qualification_actual_20261009.md)
now passes 12 host controls, 10,000 executed C++-header comparisons and four
actual-corpus cases, including both literal normal-fixture CRCs and real
corruption rejections. It rejects the unchanged CRC-free K480 sample. No new
packet is emitted by the reader or physical gate accepted.
The [separate CRC emission/readback preparation](build/packet_crc_emission_readback_preflight_actual_20261009.md)
now emits a small candidate at 09:41:42 HKT, adding exactly two CRC writes while
preserving the original payload/header bytes except the length field. Fresh
native decoding, all-frame/data/ECC comparison, software CRC checking and both
actual emitted-candidate corruption negatives complete at 10:01:40 HKT, exit0,
with final source revalidation. This is
not full-target or physical acceptance. The matching full-target CRC emitter
and native readback checker are prepared, with 15/11 first host controls and
the separate combined 26-method selection passing.
Neither has run on a completed full packet; unfinished/other-profile producers
are rejected before output or native execution. No SHA256SUMS is created.
The fresh source-identical whole `make test` completes FAIL at 10:05:53 HKT:
all 247 Icarus EW entries pass, but both unchanged 600-second Verilator compile
limits recur. Live fixtures and original worker limits remain unchanged;
missing host/numeric/CMAC-Icarus completion is not inherited from old runs.
A [separate source-identical generated-C++ OPT0 whole retry](build/source_identical_production_opt0_preflight_actual_20261009.md)
starts at 10:24:02 HKT, with six passing host controls. It changes only private
compiler make variables, not RTL, reference-model flags, tests, warnings or
deadlines, and still requires all five original source-bound reports. The
actual first 12,963-vector ALU run and job-control test pass, the latter building
in 441.753 seconds within the unchanged deadline. The CMAC operand build also
passes in 483.132 seconds; its unchanged test checks 53,297 operand pairs.
The exact-product bench passes 230,433 comparisons; all three Verilator CMAC
benches complete PASS_RAW_PRODUCT_PATH_ONLY at 11:13:34 HKT, including 53,247
product-front checks. Both 247-entry EW suites and all three Icarus CMAC benches
now pass as well. The [whole retry](build/source-identical-production-opt0/1791512642277187031/report.json)
completes PASS at 11:23:11.900 HKT, actual make0/3540.766 seconds, with all five
fresh source-bound reports and final source/input revalidation. All 82 fresh
EW memory images agree across simulators. This is production simulation only,
not a shared full-board numerical or physical result. The requested
[fresh home configuration-reference search](build/home_configuration_reference_followup_actual_20261009.md)
corroborates OpenTPU's explicit 1.8/GND candidate, without finding physical
Bank 0 supply/strap proof in the inspected scope; electrical gates stay intact.
At 19:00:33 HKT, the [latest accepted live-placement audit](build/openxc7/recursive-mux-observed-heap-samples-1791543672115849118/report.json)
compares queue entries 60,116→60,000 and observes another unplaced `SLICE_LUTX`
root change. This is active legalizer search, not a placed-cell census,
placement percentage, convergence estimate or fit result. At 19:01 HKT the
same native worker remains live, about 11h58m into its original 12-hour limit.
It terminates at 19:02:48 HKT with `TimeoutExpired` and return -9; no
`placed.json` exists. The guarded longer-timeout retry then rejects the changed
system-Python input hash before producing output or launching nextpnr. The
mapped-board continuation remains `RUNNING/mode7`, with its preserved parent
failure; this is simulation only, not a physical board test. A fresh check at
19:30 HKT still finds the report `RUNNING/mode7` with parent `FAIL`. The
separate Vivado 2026.1 installer is still extracting under `~/vivado`; its
19:30:13 log reports 220,998 of 549,699
files processed, but `Vivado/bin/vivado` is not present yet. Routing, timing,
electrical/DRC and bitstream acceptance remain false.
At 19:29 HKT, a fresh native five-mux feedthrough probe with the unchanged
c68c135 engine and seed 3588 exits zero. The structural checker confirms 21
placed cells on 21 distinct BELs, two inserted identity LUTs and four truth
comparisons. This is a small no-route probe, not current full-target
qualification/packing or fit acceptance.
The shared numerical compile remains allocation
FAIL; an unchanged-input, wider-host-address-space retry is prepared but
unlaunched. There is no test-ready full-size bitstream.

At 19:50 HKT, the [fresh prefix-DSP checkpoint preflight](build/rknpu-dsp-prefix-checkpoint-preflight/1791546345898619133/report.json)
revalidates the full C32/K16 area, native-array, nine-mode raw-board and mapped-array
parents against current source/artifact hashes. It completes with
`PREPARED_OWN_PARENTS_VALIDATED_FULL_C32K16_PREFIX_CHECKPOINT_ONLY` and a new
`build.tcl`; the ROM source check passes. The 18 Tcl build/evidence controls also
pass under Tcl 9.0.3 with every Vivado call mocked. This runs no Vivado, creates no
checkpoint or bitstream, and leaves physical-fit/signoff flags false. The separate mapped-board
continuation still has its real negative and modes 0–6 passed, with mode 7 running
and mode 8 pending; this is simulation evidence only. The Vivado 2026.1 installer
has extracted 308,701 of 549,699 files at 19:50:48 HKT. Its `Vivado/bin/vivado`
loader has appeared but `-version` still fails because the installation's
`prodversion` file is absent. No implementation was launched.

At 19:58 HKT, the saved mapped-board continuation remains `RUNNING/mode7`:
fresh modes 0–6 all pass, with mode 8 pending; the live Icarus process is still
active. This is mapped-netlist simulation only. The Vivado 2026.1 installer is
also still active and has extracted 348,773 of 549,699 files; `vivado -version`
still fails because `Vivado/bin/unwrapped/lnx64.o/prodversion` is absent.
`make generated-check` passes at the current source. The host sample reports
16 GiB available RAM and 4.2 GiB free swap, while the installer, mapped replay,
and other XC7K480T routes remain active, so no additional full placement or
implementation was launched. No routed checkpoint or bitstream is produced.

At20:08 HKT, the current full Vivado driver is freshly source-bound as
[PREPARED_DSP_PREFIX_ARRAY_VIVADO_ONLY](build/rknpu-dsp-prefix-array-vivado/prepare-1791547705025634147/report.json),
source SHA256 `c04a218f73354d29fb5911d11030396edca66a203bf761ccc2a01c63c0fd4a78`;
its raw-ROM generated-source check passes. A distinct `synth` action now uses
the same completed area/native/mapped/all-nine-board parents and checks all
16×32 CMAC DSPs plus BRAM after synthesis, then stops at `post_synth.dcp` and
the synthesis utilization report. It contains no placement, routing, timing/
DRC signoff or bitstream command; the original full `run` gates and reviewed
emitter remain unchanged. The focused Tcl control suite passes all 21 methods
under Tcl 9.0.3 with Vivado calls mocked, including rejection of a 31-DSP
kernel before checkpoint creation, correct binding of the four parent reports,
and rejection of synth-only evidence by the bitstream emitter. Generated
checks pass. This is preparation/control evidence only: no Vivado synthesis or
implementation has run.
The 20:08 HKT live recheck finds the installer at 361,874/549,699 files; the
launcher now reaches `prodversion` but fails to load `libxv_common.so`, which
is still missing during partial extraction. The mapped replay is still
`RUNNING/mode7` with modes 0–6 passed. Installer logs report 99% CPU busy; these
existing jobs remain untouched and no new large placement was launched.

At 20:15 HKT, the actual full-profile `synth` admission validates all four
completed parents, their source snapshots and the raw-ROM check, then exits
`FAIL` before launching Vivado because the executable name `vivado` is not on
`PATH`; its source-bound report is
[here](build/rknpu-dsp-prefix-array-vivado/synth-1791547857112887601/report.json).
This is not a synthesis failure. The next invocation must pass the installed
path with `--vivado /home/fedora/vivado/2026.1/Vivado/bin/vivado`. At 20:16 HKT
the live installer has reached 402,114/549,699 files; that exact wrapper still
fails to load missing `libxv_common.so`. The mapped replay remains mode7 and
the installer reports 99% CPU busy; no implementation or bitstream exists.

At 20:33 HKT, the full-tool install is still incomplete: its `prodversion`
binary exists, but `Vivado/settings64.sh` and
`Vivado/lib/lnx64.o/libxv_common.so` are absent. Running `vivado -version`
natively fails on that missing library. A version-only probe with the
2026.1.1 Vivado Lab library path exits successfully but reports `vivado v`
without a release number, so that mixed runtime is not accepted for synthesis.
The live mapped-board continuation remains `RUNNING/mode7` with modes 0–6
passed. A fresh `make generated-check` passes; no synthesis, implementation,
bitstream emission or hardware programming has occurred.

At 21:39 HKT, full Vivado 2026.1 is now installed at
`/home/fedora/vivado/2026.1/Vivado`; its native version banner is
`vivado v2026.1`. The exact-path full C32/K16 synthesis-only attempt validates
all four source-bound parent reports, checks the generated ROM and version, then
Vivado exits 42 before synthesis because no valid license is available. Its
report is [here](build/rknpu-dsp-prefix-array-vivado/synth-1791552618590027876/report.json)
(source SHA256 `e46495c43d59a2b382a5ecb1dec698e9be3d6e4a9ea210bb8fdaa52ac6141649`).
No synthesis checkpoint, implementation, timing/DRC result or bitstream was
produced. License variables remain unset; the license manager is left for the
user, and no AMD account action was taken. The full-source driver now accepts
the real lowercase `vivado v2026.1` banner and rejects Lab/malformed banners;
its 22 focused controls pass. The subsequent `nice -n 19 make test` completes
exit 0 by 21:29:58 HKT: 49 Python methods, both 247-entry EW suites, all three
CMAC benches in each simulator and 1,087,299 C++ comparisons. The reports record
Verilator 5.048, Icarus 13.0, numeric seed `0x3588` and CMAC seeds
`0x3588ca03`–`0x3588ca05`: [Verilator RTL](build/rtl/report.json),
[numeric model](build/numeric_report.json), [Icarus RTL](build/iverilog/report.json),
[Verilator CMAC](build/cmac_verilator/report.json) and
[Icarus CMAC](build/cmac_iverilog/report.json). This is simulation evidence,
not FPGA or RK acceptance.

The requested fresh home-wide board-reference search finds no YPCB schematic
or physical Bank 0 supply/CFGBVS strap proof. The local `1.8 V / GND` pair still
traces to the OpenTPU XDC candidate; board XML, pinout spreadsheets and the
listed vendor software archives add no electrical measurement. This does not
change the fail-closed electrical gate. The mapped-board Icarus continuation
is still `RUNNING/mode7` (modes 0–6 passed), not a hardware test.

At 21:46 HKT, a low-priority refresh attempt for the openXC7 native mux engine
is refused by its preserved source-binding guard before creating an output
report, compiling, or invoking nextpnr. The first stale input is
`/usr/bin/python3.14`: the qualification chain records Python 3.14.7 / SHA256
`0d64bd6d66d68dac91cdadafc46e22d4f09f22bdc997aaae870f42865b024a3e`, while the
current Python 3.14.8 hashes to
`df5a95e6119c051c43ab78993af48f8a53c54a25a475dacd1428c322251eb8b0`. A fresh
qualification and pack must start at the first stale ancestor; no parent hash
or timeout guard is waived. Two unrelated XC7 nextpnr routes, the Vivado
installer and the mapped-board Icarus continuation remain active, with about
16 GiB RAM available, so no new full-size placement is launched.

A [fresh read-only host sample at13:12HKT](build/full_target_host_frequency_observation_actual_20261009.md)
reports all eight CPU policies near399MHz despite configured1.4–2.0GHz limits,
with96–98% interval CPU busy time. The low-clock cause remains unproven;
host settings and unrelated jobs are not changed. Both original preparation
workers remain live. These host observations are not FPGA timing evidence.

At15:49:55HKT the separate OpenTPU static-route service failed in its
`full-ddr800-route` stage (exit1) and its process exited; this is not an RKNPU
result. A fresh capacity sample then showed16.02GiB available RAM and6.20GiB
free swap, still below the unchanged numerical-retry requirements of24GiB RAM
and28GiB combined. The retry remains unlaunched. The original full placement
and mapped mode6 processes are still live; no test-ready bitstream exists.

At15:56HKT, a fresh process census finds Xilinx `xsetup` still running from
`/tmp` with its installer JVM at9.21GiB RSS, while the only installed executable
under `~/vivado` remains `Vivado_Lab/bin/vivado_lab`. A Vortex XC7K480T route is
also active. Available RAM is13.05GiB and free swap6.46GiB, so the numerical
retry remains below both its RAM and combined-capacity admission floors. These
separate jobs were left untouched.

This is an original SystemVerilog prototype of a **strict RK3588 DPU/RDMA FP16 elementwise subset**, plus a standalone Python emulator, arithmetic design model, Verilator testbenches, and a YPCB BRAM-only self-test top. It is **not a completed RK3588 NPU, not a completed soDLA fork, and not an integrated tinygrad device**.

The existing ~1500-line tinygrad backend and its hardware `test_ops` success are project inputs supplied by the user; this work does not re-validate that backend or replace its compiler. The FPGA path must eventually consume its actual encoded commands, without runtime CPU arithmetic or host layout-fixing fallbacks.

## What was implemented

Current priority: [RKNPU-sized C32 × K16 FP16 CMAC](docs/RKNPU_SIZED_CMAC.md).
The full-size carry-prefix candidate now completes literal-input preparation
and native openXC7 packing, retaining all 512 CMAC DSPs plus three shell DSPs.
The separate full-size native placement attempt failed on 2026-10-08 at a
nonfinite exponential assertion in the host static placer. A numeric control
reproduces float-overload overflow on valid device coordinates; an isolated
double-overload backend now passes fresh native legality qualification. Its
full-size retry reaches strict legalization but fails its six-hour native
limit at 10:01:31 HKT on 2026-10-08, without a completed placement. This timeout
does not establish that the design cannot fit. The RTL arithmetic and full C32/K16 target
are unchanged.
An isolated corrected-DSP engine with physically bounded strict-search sampling
and progress counters now passes fresh small native qualification. Its separate
full-size static retry now finishes **FAIL at 23:31:46 HKT on 2026-10-08** at
the unchanged twelve-hour host limit, without a placed checkpoint. The separate
original unshared HeAP attempt was retired at 02:19:24 HKT on 2026-10-09 after
fresh exact-input revalidation of its proved LUT-capacity conflict; its signal-stop
FAIL, sources and logs are retained. All original native validity
guards, normal refinement, 512 products and the 50 MHz clock remain required.
The separate imported-checkpoint checker now passes the 49-cell carry control,
286-cell DSP/BRAM control and eight actual corruption rejections. Its explicit
empty-CARRY-port handling is comparison-only, never an execution-input repair.
The separate corrected full-route handoff has fifteen passing software controls,
including full-target admission and comparison-only empty LUT output declarations.
It is prepared but has not executed a full native scan or route.
An actual test-only 50-cell checkpoint now reproduces the old native checker's
rejection of a declared, disconnected paired LUT output. A separate opt-in
literal-empty-output import/checker extension has compiled cleanly; its host
controls and fresh small native qualification now pass, including all seventeen
expected rejections and four 49/49/50/286-cell routes. Its first qualification
FAIL remains preserved: the new unused test LUT omitted the native default
binding-strength declaration. A separate test fixture now declares that same
effective strength, without changing native guards or full-size inputs.
The separate v2 full-route handoff has nineteen passing software controls;
actual source-bound revalidation now passes and full placement is still required
before route admission. These small controls are not a full-board result. The full-size input,
running placement and production RTL are untouched.
A separate [native HeAP procedure qualification](build/openxc7/native-heap-qualification-1791457692353795739/report.json)
failed on an incorrect log/phase expectation: the native tool genuinely rejected
the illegal constrained pair before analytic placement. Its evidence is unchanged.
A [separate continuation](build/openxc7/native-heap-early-constraints-1791458660562002118/report.json)
also failed before native placement: its generic diagnostic parser mistook C++
symbol names in successful `nm` output for errors. A
[typed-inspection qualification](build/openxc7/native-heap-typed-inspection-1791459029556778888/report.json)
completed all native commands, but remains **FAIL** at strict FASM parsing of
an unmodeled repeated HCLK buffer-enable feature. Its negative and three positive
placements pass, with 1,024 LUT comparisons. A separate
[source-bound clock-feature qualification](build/openxc7/native-heap-clock-features-1791461172554993544/report.json)
now revalidates those exact unchanged native artifacts and passes all four DSP
and six BRAM configuration comparisons. Clock repetition is admitted only at
the multiplicity of distinct, one-owner PIPs in the bound device database;
unknown/conflicting features remain failures. The old failure and parser are
unchanged, and no new native P&R execution is claimed by this read-only check.
The [original full C32/K16 HeAP placement attempt](build/openxc7/full-prefix-native-heap-place-1791461555717052444/report.json)
retains all 515 DSPs and six BRAMs but supplies no completed placement or route.
It was deliberately stopped only after the
[fresh complete capacity/identity audit](build/openxc7/original-capacity-supersession-audit-1791483476679187066/report.json)
recomputed the 302,998-versus-298,600 position conflict and matched its exact
running input/engine/policy/checksum. The signal-stop result is not a native
rejection or timeout; [retirement evidence](build/openxc7/original-capacity-supersession-audit-1791483476679187066/RETIREMENT.md)
is retained separately. The full-size shared candidate below remains the target.
Its six host controls pass. The updated v2 route handoff passes twenty-seven
host controls and retains the entire 515-DSP/six-BRAM full-target comparator;
it has not executed a full route and requires actual full placement first.
A separate [HeAP frame-conversion check](build/openxc7/native-heap-frame-control-1791462156684206950/report.json)
now passes with eleven fresh host controls, conversion of all unchanged saved
raw FASM statements, complete exact-part tilegrid frame coverage and actual
readback of all 64 corrected DSP features and both source-bound HCLK bits.
Both actual-frame corruption negatives are rejected. This is a small saved
native encoder-chain check, not full-board frame conversion or a bitstream.
The [full-board frame handoff](tools/openxc7/convert_full_heap_frames.py) is now
prepared with nineteen passing host guard tests. It requires completed actual
full HeAP routing, rechecks the full circuit/BEL/native-feature evidence, and
requires all 8,240 corrected DSP feature bits and every actual HCLK bit. It
rejects the current incomplete placement before conversion; no full-board
frame conversion has been executed.
A [full packed-graph matching bound](build/openxc7/full-lut-sharing-bound-1791469159980053569/report.json)
now establishes a capacity conflict for this exact mapping under the current
native LUT rules: at least 302,998 physical positions versus 298,600 available.
The calculation retains all 512 products and is deliberately optimistic;
it is not a claim that another equivalent C32/K16 mapping cannot fit. A separate
full-size area optimization is now needed. A separate
[shared-cone candidate](build/rknpu-dsp-prefix-shared-export/1791470852571972438/report.json)
now passes literal circuit restoration, real-Yosys export identity and hierarchy
checks, removing 14,610 LUTs while retaining all 515 DSPs, six BRAMs and 17,519
FFs. Its first generic-export failure remains preserved. Its 431,206 mapped LUTs
are not physical-position utilization. The separate
[full packing-input preparation](build/openxc7/full-prefix-shared-pack-input-1791471918232843068/report.json)
now completes independent real-Yosys flatten identity and exact circuit
restoration after physical IO insertion at **23:49:46 HKT**. The separate
[native packing/capacity census](build/openxc7/full-prefix-shared-native-pack-1791474646490498829/report.json)
now completes at **00:22:43 HKT on 2026-10-09**, with all 4,474 bound
source/input paths unchanged. Actual native packing takes 650.607 seconds;
the complete census measures 523,410 cells, including **488,080 packed LUTs,
17,519 FFs, all 515 DSPs and six BRAMs**. The source-bound necessary LUT-position
bound is **295,139 versus 298,600 available**. This removes the earlier proven
conflict, but is an optimistic lower bound, not placed-fit evidence.
The separate [shared-prefix HeAP handoff](tools/openxc7/place_prefix_shared_board.py)
passes thirteen new and six unchanged native-HeAP guard controls; all 183
shared-prefix controls and generated checks pass together. Its
[actual full-size worker](build/openxc7/full-prefix-shared-native-heap-place-1791476631447626227/report.json)
finishes **FAIL at 01:07:51 HKT**: after initial analytic iterations 0–3,
the mux `rk_mapped_cell_86668.rk_mapped_cell_22977` exhausts 10,001 legal-placement
attempts. Native execution returns 125 after 2,088.468 seconds; no placed
checkpoint is produced. All 512 products, the exact -2 part, 50 MHz and normal
refinement/legality checks remain required. A separate
[actual host-expression reproduction](build/openxc7/shared-heap-arithmetic-cxx-driver-1791480180109061866/report.json)
confirms signed 32-bit overflow in the bound HeAP default search-limit calculation
at this graph's 523,410 cells. This does not establish that correcting it will
place the mux or fit the full design. No native engine has been repaired/replaced
by that diagnostic. Shared numerical replay and physical gates remain open.
The separate [one-expression counter-safe HeAP build](build/openxc7/counter-safe-heap-engine-1791481639500508440/report.json)
now completes **at 01:54:46 HKT on 2026-10-09**. It reproduces the qualified
parent executable byte-for-byte, passes all nine executed overflow/counter-boundary
fixtures, and compiles/links only the changed HeAP object. Its finite limit is
2,147,483,646; legality, refinement, RNG and the 512-product target are unchanged.
This is a tool build, not placement acceptance. The
[fresh native qualification](tools/openxc7/qualify_counter_safe_heap.py) has ten
passing guards. Its [first actual attempt](build/openxc7/counter-safe-heap-qualification-1791482371308735092/report.json)
passes the expected illegal-pair rejection and all three positive placements,
but finishes **FAIL at 02:49:50 HKT** when small routing reaches its 2.5 GiB hard
memory cap. This is not a routing pass. A [separate unchanged-source 4 GiB attempt](build/openxc7/counter-safe-heap-qualification-1791485725278039585/report.json)
reruns and passes all placement controls, but also finishes **FAIL at 03:10:02 HKT**
at its hard memory cap while setting up routing resources. The completed donor
native route used a 6 GiB hard cap and swap. A [fresh unchanged 6 GiB/2 GiB-swap attempt](build/openxc7/counter-safe-heap-qualification-1791486974423403401/report.json)
attempt now completes **QUALIFIED at 03:33:00 HKT**. Its fresh small native route
returns zero in 329.493 seconds; all DSP/BRAM/clock comparisons and before/after
source checks pass. Neither earlier failure is inherited as qualification
evidence. This is small engine qualification, not full placed fit. The
[counter-safe full placement handoff](tools/openxc7/place_counter_safe_prefix_shared_board.py)
passes 24 guards and requires completed fresh qualification plus the unchanged
native packing checksum and actual corrected limit. Its [own full-target worker](build/openxc7/full-prefix-shared-counter-safe-heap-place-1791488628202327384/report.json)
starts at **03:39:43 HKT**. Its actual native run now matches the saved packing
checksum, completes initial analytic iterations 0–3, and logs the corrected
finite **2,147,483,646** attempt limit in the main placer. A subsequent
[read-only cluster geometry audit](build/openxc7/observed-native-mux-geometry-1791492921043041558/report.json)
finds zero compatible root locations in all 52 database tile-type/root cases
for the actual stuck mux cluster. That attempt is deliberately stopped and
retained as **signal-stop FAIL at 04:58:16 HKT**, not native rejection/timeout
or whole-design infeasibility. Fresh isolated packer correction and qualification
are needed; no completed full native placement or route is claimed.
The [recursive mux feed-through candidate](tools/openxc7/build_mux_feedthrough_candidate.py)
now has five passing source/admission controls and a passing generated-source
check. Its [first build/probe](build/openxc7/recursive-mux-feedthrough-engine-1791494566705295223/report.json)
stops at **05:22:54 HKT** with an Icarus test-bench elaboration error, before
native packing or candidate compilation. The [separate explicit-instance retry](tools/openxc7/build_explicit_mux_feedthrough_candidate.py)
retains all guards, has seven passing controls, and starts at **05:25:38 HKT**
with the same 1 GiB/no-swap bounds. A separate smoke test passes 16,384
vendor-model four-state vectors/32,768 comparisons and the genuine wrong-output
negative. Fresh source-bound HDL replay, actual old/new native pack probes and
placement/routing qualification remain pending; production RTL, old evidence
and the full target are unchanged.
That [explicit attempt](build/openxc7/recursive-mux-feedthrough-explicit-engine-1791495022548762731/report.json)
now completes the fresh HDL replay, byte-identical parent relink and actual
parent native pack. It stops **FAIL at 05:30:51 HKT** at a comparison-only
output-buffer-name lookup. The saved native fixture reproduces the illegal
extra mux level. A [source-evidenced native-I/O-name retry](tools/openxc7/build_native_io_mux_feedthrough_candidate.py)
retains all graph/parameter/export guards, passes 11 host controls, and starts
at **05:33:31 HKT** under the same 1 GiB/no-swap bounds. Its
[actual attempt](build/openxc7/recursive-mux-feedthrough-native-io-engine-1791495496575181522/report.json)
now completes **BUILT at 05:42:16 HKT** after fresh HDL positive/negative,
byte-parent relink, isolated object/ELF compilation and both native pack probes.
The actual new mux graph replaces the extra mux levels with two identity LUTs
and preserves the original output exports. This is not placement/routing or
full-array acceptance. The [fresh qualification harness](tools/openxc7/qualify_recursive_mux_feedthrough.py)
passes 13 host controls and adds actual corrected-mux placement to every
original native legality/refinement/LUT/DSP/BRAM/clock gate. Its separate full
backend qualification starts at **06:09:20 HKT** and completes
[QUALIFIED at 06:26:34 HKT](build/openxc7/recursive-mux-feedthrough-qualification-1791497608027018932/report.json)
after all original native gates plus corrected-mux placement and final source
revalidation. This is small-feature qualification, not full fit or timing signoff.
The [bounded mux placement probe](tools/openxc7/probe_recursive_mux_native_placement.py)
has 14 passing host controls. Its first memory-admission observation is below
the unchanged two-GiB private-job/headroom gate and launches nothing; a later
fresh observation passes and starts the separate probe at **05:47:56 HKT**.
The [actual small probe](build/openxc7/recursive-mux-native-placement-probe-1791496225072484294/report.json)
completes **PASS at 05:53:29 HKT**: native placement returns zero in 75.657
seconds, all 21 cells have unique BELs, both identity LUTs and all three exported
mux outputs are retained. Normal refinement/legality checks pass; no routing
or interior timing paths exist in this fixture. This is not full backend
qualification, full C32/K16 fit or 50 MHz timing closure.
The [fresh full pack handoff](tools/openxc7/pack_recursive_mux_prefix_shared_board.py)
and [fresh full placement handoff](tools/openxc7/place_recursive_mux_prefix_shared_board.py)
pass 18 and 21 host methods respectively. Both require completed fresh backend
qualification and preserve all 515 DSPs/six BRAMs and original guards. The fresh
full pack now completes at **06:48:48 HKT**, with its own 523522-cell census,
checksum77f1fde0 and necessary LUT bound295195 versus298600 available. The full
placement supervisor starts at **06:50:19 HKT**; fresh source/input admission,
21 placement controls, six native guard controls and generated checks pass.
Its native child starts at **07:02:43 HKT**, without placement acceptance yet.
The new [route handoff](tools/openxc7/route_recursive_mux_prefix_shared_board.py)
and [frame handoff](tools/openxc7/convert_recursive_mux_shared_frames.py) pass
48/29 host methods, retaining complete new-graph identity and original native
scan/router/DSP/BRAM/clock/frame gates. The combined corrected-mux handoff suite
passes **143 methods in 70.896 seconds** with Python 3.14.5; its
[fresh log](build/recursive_mux_handoffs_host_controls_actual_20261009.log)
is not native full packing/placement/routing, numerical or FPGA evidence.
The [full packet roundtrip handoff](tools/openxc7/assemble_recursive_mux_shared_unreviewed_bits.py)
passes nine host checks. It requires the actual completed full route/frame chain
and fresh DSP/clock-bit readbacks before using the qualified assembler/decoder.
Its prospective output is explicitly unreviewed/`NOT_FOR_PROGRAMMING`, not a
test-ready image or timing/electrical/DRC/configuration-CRC acceptance. It has
not assembled the full target.
The expanded seven-module handoff suite passes **152 host methods in 85.459
seconds**; its [fresh log](build/recursive_mux_all_handoffs_host_controls_actual_20261009.log)
is separate from native pack/placement, numerical and physical evidence.
The separate [analytic-log scope diagnostic](tools/openxc7/audit_typed_recursive_mux_analytic_scope.py)
now binds the actual compiled HeAP source/object and live engine, confirming
that the analytic log counts only its active-root subset. Its thirteen host
controls pass; the original wrapper/expected error are not changed, and no
replacement placement acceptance is supplied. The first diagnostic metadata
rejection is preserved. This diagnostic does not validate the exact active set
or accept the complete full-output circuit/BEL/numerical/physical gates.
The [counter-safe route handoff](tools/openxc7/route_counter_safe_prefix_shared_board.py)
passes 42 host controls and retains the same qualified v2 scanner/router base,
complete circuit identity and feature gates. The combined shared-prefix suite
passes 306 methods; these controls are not a full native placement/route or
numerical/physical acceptance result.
The [shared frame handoff](tools/openxc7/convert_counter_safe_shared_frames.py)
passes 25 host controls and requires this exact graph's actual completed route,
all 8,240 corrected DSP bits, every bound clock bit and complete exact-part
frame geometry. It has not converted a full route or emitted a bitstream.
The isolated [small native packet-encoding control](build/openxc7/small-native-heap-bit-encoding-1791491349869461344/report.json)
completes **PASS at 04:33:39 HKT**: actual open-source assembly/decoding preserves
all 46,336 frames and 4,679,936 data/ECC words, including 444 zero-filled frames;
both actual decoded-bit corruption negatives are rejected. It checks only the
completed four-DSP/six-BRAM sample, not the full C32/K16 target. Its unreviewed
artifact is explicitly `NOT_FOR_PROGRAMMING`; timing/electrical/DRC/configuration
CRC and numerical gates stay false. No `SHA256SUMS` is created.
The separate [shared full-route handoff](tools/openxc7/route_prefix_shared_board.py)
passes 38 host controls, including all 27 unchanged route guards. It refuses
unfinished placement before tools/output and has not executed full routing.
The candidate's [own numerical-replay input preparation](tools/cmac/continue_prefix_shared_replay.py)
now **passes at 01:04:23 HKT**, binding 1,215 source paths and thirty own
artifacts. Its nineteen counter/model/bench controls pass. The first
resource-census failure is preserved; the separate continuation applies the
existing strict DSP timing-declaration qualifier only to the counting view.
The exact 488,407-primitive literal hardware, all 515 DSP configurations, six
BRAMs, 22 live observation wires and unmodified vendor models are verified.
The separate [own nine-mode numerical runner](tools/cmac/test_prefix_shared_observed_board.py)
passes fifteen guards, including eight unchanged original replay guards.
Its [actual fresh worker](build/rknpu-dsp-prefix-shared-observed-board/1791479366724278074/report.json)
starts **01:09:26 HKT**, admits 1,248 paths and reaches full-board compilation
with Icarus 13.0. No old executable or numerical result is inherited; the real
wrong-output negative and all nine original raw-board modes remain mandatory.
This first compilation finishes **FAIL at 03:32:44 HKT**, before numerical
execution, after a kernel OOM kill at the 14 GiB hard cap. Its original
21,600-second compile budget is not exhausted. The failure and all inputs/logs
are preserved. After the audited placement retirement, a [fresh unchanged-source
24 GiB/2 GiB-swap attempt](build/rknpu-dsp-prefix-shared-observed-board/1791493285871405865/report.json)
starts at **05:01:12 HKT** and reaches actual compilation. All original source,
negative/nine-mode, compile/mode/outer deadlines and expected outputs stay
unchanged; no partial executable or shared numerical PASS is accepted.
It finishes **FAIL at 06:07:28 HKT**, compile exit1/3957.642 seconds, with
Icarus `calloc() ran out of memory`, before any numerical mode. The private
24 GiB hard RAM/address-space and 2 GiB swap limits remain intact; a scoped
soft-threshold adjustment did not produce a compile or numerical PASS.
The [separate wider-address runner](tools/cmac/test_prefix_shared_observed_board_as32.py)
passes 18 host controls. It preserves the failed attempt and changes only a
new private virtual-address ceiling from 24 to 32 GiB, not RAM/swap caps,
hardware/models/raw inputs/goldens, the real negative, nine modes or deadlines.
It is prepared but unlaunched, not a compile or numerical PASS.
The [fresh read-only launch-policy revalidation](build/shared_numeric_as32_launch_admission_actual_20261009.json)
preserves all three original admission floors: 24 GiB available RAM, 3.5 GiB
free swap and 28 GiB combined capacity. Combined capacity alone is insufficient;
the actual check holds the launch because available RAM is below 24 GiB.
The 3.5 GiB free-swap admission floor is not the hard swap cap: the preserved
terminal unit confirms 24 GiB hard RAM/2 GiB hard swap and the original
900,000-second outer deadline. All 1,256 preserved failure bindings revalidate;
the AS32 runner's main has not executed and no numerical acceptance is granted.
Original mapped replay continues unchanged; the superseded original placement
is retained as a signal-stop FAIL. No physical or numerical acceptance follows
from the bound or structural candidate.
Packing is not placed fit; timing/electrical/DRC
signoff and bitstream emission remain open. The precision-fixed backend now
passes fresh small native reload/routing qualification. The full-routing
admission and export-identity gate passes fourteen controls, saved small-export
identity checks and the full packed LUT contract inventory; no full native
route has run. See [OPENXC7.md](docs/OPENXC7.md)
for the actual attempt reports and exact limitations.
The new parallel 512-product array passes a 208-frame streaming test with
3,328 results also checked against original NVDLA MAC RTL and its arithmetic
model. The full native Verilator hold/reset test also passes, including a
separate source-verified partitioned build for integration regression. Full-array
XC7 primitive mapping and the nine-case four-state board suite now pass;
baseline mapped numerical acceptance and physical fit/timing remain incomplete.
The separate carry-prefix DSP variant below now has clean full mapped binary
fixture acceptance and an own-parent-validated checkpoint package. Separate C32/K16
raw-command, DMA, AXI and BRAM-board candidates are now implemented, with
all 19 two-state raw AXI integration cases passing. They do not replace the earlier serialized
path or production top, and no upstream `nvdla_utb` or FPGA pass is claimed.

The 2026-10-05 preparation work adds a separate reviewed-checkpoint bitstream
emitter, with source/report hashes and explicit electrical/report acceptance.
Its control tests are mocks, not Vivado implementation. The fixed-FP16 C32/K16
optimization remains experimental. Its fresh row simulation and composed
post-configuration proofs and full 208-frame/3,328-output native array test
pass. Its fresh eight-case two-state raw-board suite and full-CMAC area
measurement now pass. The latter retains all 512 products and sixteen kernels,
mapping to 466,264 LUT primitives (about 9% fewer than the baseline), not a
verified physical fit. The mapped helper now passes binary symbolic equivalence
for all 37 relevant input bits and all 72 row/tag output bits. Complete-board
mapping now passes its area/structure gates: 512,159 LUT primitives, 17,310
flip-flops and six RAMB36E1 blocks, with no DSPs. The 322,911 logic-cell
estimate exceeds the target's 298,600 LUT sites; area reduction remains needed,
and neither estimate proves placed fit. The nine-case four-state board suite
has recorded seven passing modes; completion remains unconfirmed.
The separate mapped-helper Icarus supervisor exited with SIGTERM while its
simulator child was last observed live before the managed-sandbox transition;
no completed four-state mapped PASS is claimed. Full fixed-array binary mapped
replay remains incomplete. The old host process handles are not observable
from the new PID namespace; this is not evidence that those runs stopped.
The separate reversible shared-cone board candidate now completes exact
circuit/export and hierarchy checks, with 497,564 LUT primitives. Its 311,781
logic-cell estimate still exceeds the target's LUT-site count. The first
same-fanin LUT6_2 attempt fails the strict export gate because of a private
module-name conversion; the fresh reversible-name candidate now completes
strict export, hierarchy and source checks, with 386,996 LUT primitives.
Full paired-array replay compiles its kernel but fails the top-generation
vendor INITIALDLY warning gate before numerical execution. Independent UNISIM checks pass all
650 actual function classes/496,096 four-state comparisons. A raw-board bench
binding probe explicitly fails preparation because
observation signals were removed and the controller state was recoded.
Fresh source-bound retention preparation preserves all 22 original
observations and the native four-bit state. Remapping exits zero in Yosys
but fails its strict RAM-width-warning gate before the later checks.
A full nine-mode mapped-board runner is prepared, with pinned functional
RAM/startup models and a real small model control, but has no full-board result.
Their controls and structural gates are not
full-board numerical, packed-fit or timing acceptance; production RTL is unchanged.
A completed read-only output-role audit finds 1,036 pairs whose two outputs
both need O6-only consumers. A separate union-fanin analysis finds 80,980
additional disjoint proposals, projecting 306,016 LUT primitives, still above
nominal capacity. Real small four-state model controls pass; the actual full-class
Yosys comparisons pass, while its UNISIM positive records a timeout failure.
Combined shared-cone/LUT pairing now completes literal
restoration, export identity, class tests and hierarchy checks at 372,401 LUT
primitives. No transformed
netlist or physical fit is accepted from that projection.
A separate corrected DSP-lane experiment now passes 135,680 actual binary
HDL comparisons. It compares the compensated lane sum/tag, retaining the
donor's discarded-low-bit carry correction; it does not replace the array.
The initial proof and area harness failures are preserved with executed source
snapshots. Word-level proof and the first Boolean lowering time out without
establishing equivalence. Direct AIG lowering now completes both graphs and
the real SAT negative; the positive SAT proof times out after 1,000 seconds.
Fresh isolated area
mapping passes: 765 reference LUTs versus 652 candidate LUTs and one DSP,
with strictly audited timing-only library qualifiers. This is not numerical
or physical acceptance; the original area failures remain recorded.
Neither is a completed FPGA/RK or full-array result. A separate
full C32/K16 DSP candidate is now prepared with exact donor FP44, NaN,
mask/tag and array hold/reset/fault contracts. The first actual mapped-lane
positive times out at 1,800 seconds; a hash-bound continuation preserves its
full corpus and executes a fresh negative. That replay now passes all 135,680
actual mapped comparisons; the old timeout remains FAIL. The first
full-array resource run skipped the DSP stage because its ending label was
exclusive; it was interrupted without acceptance. A real four-product
synthesis control confirms the corrected endpoint. Fresh full-array resource
mapping now passes, retaining 512 DSPs, 407,352 LUT primitives and 742 flip-flops
across all sixteen kernels. These are mapping counts, not physical fit. The full native
array compiles and passes its original first-frame negative, but its complete
208-frame positive times out after four hours. That actual failure is archived;
no native-array acceptance is claimed.
Strict lint has recorded unresolved warnings.
Independent component and conditional integer-tree proofs now pass. A separate
actual-wiring range audit establishes the donor's unsigned no-overflow bound.
Source-bound exact integer coefficients now establish the unshifted donor
product identity. A checked mathematical composition establishes the native
binary compensated lane sum/tag identity for all 37 input and 40 output bits,
with fresh complete lowering and a real SAT negative. This is not a new
monolithic positive SAT run, mapped-lane or full-array acceptance.
A separate [carry-prefix DSP lane](docs/DSP_PREFIX_CARRY.md) now passes its
67-input binary comparator proof and all 135,680 native HDL fixtures. Fresh
same-interface mapping measures 657 versus 616 LUT primitives, retaining one
DSP per lane (6.24% fewer isolated LUTs). Both actual harness failures are
preserved. Its actual mapped DSP/LUT replay now also passes all 135,680 binary
fixtures and its real negative. A separate full C32/K16 prefix array preserves
all 512 products and passes native hierarchy/wiring preparation; its full
208-frame four-state numerical test now passes all 3,328 checked outputs,
hold/reset cancellation and the X-input fault case. The first full-area run fails
its diagnostic checker after successful Yosys execution and is source-archived;
a fresh run with exact module/step diagnostic checks now passes full-array
mapping at 398,168 LUT primitives, 742 flip-flops and 512 DSPs. These are not
placed-fit or timing results. Its own full
raw-board compilation now retains one array/sixteen cells/512 lanes/512 helpers.
The full nine-mode four-state raw-board replay now passes against its own
completed independent array parents. The original full mapped-array compiler exits zero,
but its strict diagnostic gate fails at an omitted DSP pin before numerical
replay; that failed attempt provides no numerical acceptance.
The whole-board mapper and
frontend-only preparation retain all sixteen actual mapped kernels; 70 current
software controls pass. Fresh actual frontend preparation now completes with
exact imported-array/kernel wiring identity and 512 retained CMAC DSPs;
all nine raw-board modes pass, and full-board mapping has been launched. The prefix
Vivado checkpoint package is prepared, and its 18 mocked build/admission
controls pass under both Tcl runtimes. Its separate
[reviewed emitter](tools/cmac/emit_dsp_prefix_bitstream.py) now has 20 passing
controls under each runtime and rejects prepared/cross-profile evidence;
all numerical, electrical, timing/DRC and 512-product gates remain. The
112-method preparation suite also passes. Separate actual primitive-model
Verilator and Icarus controls each pass 4,259,904 DSP and 1,024 binary carry
comparisons; Icarus also passes all 1,048,576 four-state carry combinations.
Both retain their real wrong-golden negatives. A new actual-model cone audit
proves all 26 omitted DSP inputs disconnected from P in the exact zero-register
configuration, and correctly rejects a legal registered counterexample.
A completed compiler inventory binds all 1,152 missing-pin notices to the
32 actual DSPs. Fourteen diagnostic-preparation software controls pass.
Those earlier controls do not admit compiler diagnostics. A subsequent exact-model
binary proof and a separate source-specific admission/reuse continuation are now
prepared. A full mapped replay matches every original 208-frame/3,328-output
fixture and real negative, but its complete gate is refused because the build
masks two archive errors. That result is frozen before a fresh equivalent
relative-library-path correction. The new compilation is clean with exact
kernel/top object membership and now passes the complete original 208-frame
mapped binary replay, with a fresh real negative. The independent checkpoint
admission now passes its source/parents. Its 380-member archive is verified,
and the separate checkpoint package admits this variant's own native, mapped,
area and all-nine-mode raw-board reports. No Vivado, routed checkpoint or
bitstream is inferred from that package. Whole-board
Yosys execution is complete but its strict diagnostic gate fails. A read-only
inventory confirms unchanged sixteen-kernel wiring and counts 442,838 LUT
primitives, 17,310 flip-flops, 512 CMAC DSPs plus three shell DSPs and six BRAMs;
these are not accepted placed-fit, timing or DRC results.
The earlier non-prefix DSP candidate still has no all-X leaf or completed
mapped-array numerical or physical acceptance; isolated savings are not a
full-array fit claim. The [whole-board normalization capture](docs/DSP_PREFIX_BOARD_NORMALIZATION.md)
now verifies all 54 actual RAM port-width changes and unchanged final circuit.
The separate initial-driver audit proves every warned bit confined to 107
dead muxes, despite real direct consumers. Separate source-bound structural
diagnostic admission now passes; the original failed report/gate are unchanged.
Original mapped-board observation retention now passes actual frontend checks
for all 22 signals and the four-bit state. Fresh full-size remapping now passes
its strict structure, observation and fresh RAM/diagnostic gates: 445,816 LUT
primitives, 17,519 flip-flops, 512 CMAC plus three shell DSPs and six BRAMs.
The 294,538 logic-cell estimate is not placed-fit or timing evidence.
Its initial missing-help startup failure is archived, and ten corrected controls
pass. A small real-Yosys DSP export roundtrip also passes for all 32 kernel and
three shell configurations, with reversible names and unchanged parameters/wiring.
Pinned vendor-model replay exposed a startup-sensitive unknown product;
that failed run is archived before a testbench-only settling correction.
The settled model run completes the DSP/binary carry corpus, then fails the
unchanged old four-state oracle at its first Z-input difference; that failure
is archived. The separate exhaustive vendor carry truth-table control passes,
explicitly recording 415,001 four-state differences from the old oracle;
all 1,024 binary cases agree.
None is a full-board numerical or physical PASS. See
[current mapped-board preparation](docs/DSP_PREFIX_BOARD_NORMALIZATION.md).
The separate full-prefix mapped-board runner now has eight passing control
tests and an explicit pinned DSP-model inventory. Its first full-size attempt
completed exact circuit export but was interrupted during compilation; the
[897-file interruption archive](verification/runs/2026-10-07-dsp-prefix-observed-mapped-board-interruption/index.json)
preserves its nonterminal report and unaccepted partial executable unchanged.
An [unchanged-source fresh retry](build/dsp_prefix_observed_mapped_board_retry_launch_20261007.json)
is supervised by a host user service and revalidates the same completed parents.
No full-board numerical result is claimed. An earlier unchanged-source
production regression passes both 247-entry RTL suites, all three product
benches per simulator and 82 equal memory images. The latest 2026-10-07
rerun instead records a 600-second product-front Verilator compile timeout;
its terminal failure is archived, not counted as a new PASS.
No physical board acceptance follows.
The later [unchanged-executable mapped-board continuation](build/rknpu-dsp-prefix-observed-board-continuation/1791382468965621354/report.json)
now passes its real wrong-golden negative and positive mode 0: all 4,096 words
are initialized/checked, with 6,528 operand reads and 64 output writes.
Mode 1 passes its expected command-fault case, and mode 2 now passes its
expected readback-fault case. Mode 3 has since completed its reset/reinitialization case in 18,600.413
seconds, again checking all 4,096 words and 64 output writes. Mode 4 now also
passes in 20,754.567 seconds with those complete checks; mode 5 is running
under the same unchanged supervisor. Five of nine suite modes are complete; this
is not all-nine-mode numerical acceptance or FPGA evidence.
Separate [DSP/BRAM feature-corruption controls](build/openxc7/prefix-native-feature-controls-1791406115670927321/report.json)
pass four source-bound software methods. The first literal native configuration
control reaches its 600-second host limit during placement and is retained as
FAIL. The next run completes routing but correctly fails an unapplied clock
constraint caused by its missing port-net alias. The clock-bound retry now
passes actual native routing/FASM and all four DSP/six-BRAM feature comparisons,
with the same part, 50 MHz, seed and legality gates. The full routing runner
adds mandatory comparison of every actual 515-DSP/six-BRAM configuration;
that full gate is prepared, not executed. See [native configuration preparation](docs/OPENXC7.md#literal-native-dspbram-configuration-control).
The [fresh small native frame-database control](build/openxc7/prefix-frame-database-control-1791412166359639486/report.json)
now also passes strict FASM conversion and exact-part frame validation: 7,668
input statements, 97 source-defined injected/default statements and 45,892
complete tilegrid frames. No bitstream assembly is executed. This is an
encoder-chain control, not full-board routing, startup, timing or electrical
acceptance; see [frame-database preparation](docs/OPENXC7.md#actual-small-native-fasm-frame-database-control).
A later [full packed/saved-FASM audit](build/openxc7/upstream-dsp-constant-gap-audit-1791413435055802734/report.json)
confirms an upstream DSP constant-encoding defect in the current native engine:
eight tile-only control-pin declarations are absent on each of all 515 DSPs,
and 64 required tie/inverter-disable features differ in the saved four-DSP
FASM. A separately qualified packer/FASM correction is required before reviewed
bitstream emission. The older source-consistency PASS records remain unchanged;
see [the actual encoding gap](docs/OPENXC7.md#upstream-dsp-tile-constant-encoding-gap-confirmed-in-actual-artifacts).
The [isolated corrected-encoder build](build/openxc7/dsp-constant-engine-1791414105309267504/report.json)
has completed cleanly after reproducing the precision engine byte-for-byte;
only the two DSP-related objects change. Its separate 39-tie comparison
policy now passes [fresh native qualification](build/openxc7/dsp-constant-qualification-1791414657664905509/report.json):
the unchanged LUT legality controls, full 515-DSP pack, and actual four-DSP/
six-BRAM routing/FASM checks. A [full packed identity audit](build/openxc7/corrected-full-pack-identity-1791415739115873319/report.json)
also passes for all 538,118 cells, allowing only the intended 4,120 tile-pin
disconnections and tie attributes. Ordinary wiring, non-DSP cells and DSP
parameters remain unchanged. Placement transfer, full routing and physical
signoff are still open.
The corrected engine's [fresh DSP/BRAM checkpoint control](build/openxc7/corrected-dsp-checkpoint-control-1791417172851071744/report.json)
completes actual placement and reload, then fails its comparison gate at
08:08:10 HKT on 2026-10-08. The native reader drops 1,108 empty input
declarations; connected pins, parameters and attributes are unchanged. This
FAIL and its original gate are preserved. The [separate continuation](build/openxc7/corrected-dsp-checkpoint-resume-1791418453459203706/report.json)
now passes at 08:19:59 HKT from that source-bound placement, with seven fresh
controls, actual reload, expected duplicate-BEL rejection, routing and all
four-DSP/six-BRAM feature comparisons. It restores only missing empty-input
metadata in a comparison-only view; every physical BEL and original logical
pin/wire relationship is checked. This is not a new placement or full-board
route. The separate [corrected native FASM frame control](build/openxc7/corrected-frame-database-control-1791417523073936205/report.json)
now passes at 08:06:16 HKT: strict actual conversion, complete exact-part
tilegrid frame geometry and readback of all 64 added DSP feature bits, with
a comparison-only bit-corruption negative. Five new software controls and
generated-source checks also pass. Readback targets are comparison-only,
never converter circuit inputs. Neither control establishes a full-board route
or physical signoff; no bitstream assembly was run.
The separate [corrected full-feature comparator](tools/openxc7/check_full_corrected_native_features.py)
now passes twelve [fresh software controls](build/openxc7/corrected-full-feature-controls-1791419723411135879/report.json)
against saved native DSP/BRAM artifacts. Its full census requires all 515 DSPs,
six BRAMs and sixteen 32-DSP kernels; small controls cannot pass it. This is
comparator preparation, not a full routed result or placement-transfer admission.
Read-only debugger samples at approximately 08:31–08:32 HKT confirm active
strict legalization and a queue reduction from 170,261 to 170,257 entries.
Placement remains incomplete; this does not establish fit or timing.
An [exact placement-copy correction helper](tools/openxc7/correct_placed_dsp_constants.py)
also passes twelve structural controls. A [fresh small native transfer test](build/openxc7/corrected-placement-transfer-control-1791420228939723426/report.json)
now passes fresh old-engine placement, exact four-DSP correction, corrected
reload, duplicate-BEL rejection and real corrected routing. Every one of its
286 BEL assignments and original logical connections is checked, together
with all four DSP/six-BRAM feature configurations. This is a small control,
not full-array transfer or signoff.
Plain checkpoint reload checks identity, not an architecture-validity rescan.
The [post-placement LUT pair audit](build/openxc7/postplace-LUT-pair-audit-1791421199482239714/report.json)
now checks source-defined A6 mode ties and fixed shared-pin incidence on saved
small native outputs, with thirteen passing controls. It distinguishes
pre-placement input counting from post-placement mode pins and exact
post-route export mirrors. Its initial FAIL is preserved; this is not a new
native validity scan or full-board result.
An isolated opt-in native checkpoint checker builds cleanly against the
corrected encoder's actual linked CMake object. Its first native qualification
preserves the illegal/three-positive placement controls and rejects six
corruptions, but fails its imported positive's carry-associated legality scan.
A separate tag-only candidate, with strict physical DI-role checks and two
additional corruption cases, now passes separate source-bound small carry
qualification, including the 49-cell and 286-cell native routes. The first
failed reports and original gates remain unchanged; small qualification is
not full placement-transfer admission or physical signoff.
No new `SHA256SUMS` manifest is written.
The [full physical-input BRAM output audit](build/openxc7/prefix-bram-output-audit-1791406793437962391/report.json)
now checks all 432 BRAM output bits against every primitive and top-level port.
It finds 24,576 unknown INIT bits on lanes with no consumers and 65,536 on
consumed working-RAM lanes. All 131,072 consumed ROM bits match the packaged
source image. The [separate literal-wire audit](build/openxc7/prefix-memory-wiring-audit-1791408308815007879/report.json)
also verifies all 32 ROM bits, 16 working-RAM data bits and twelve-bit addresses
against the original mapped signal aliases. A [new local-control audit](build/openxc7/prefix-bram-control-wiring-1791422081130315089/report.json)
checks all six BRAMs and exhaustively evaluates six actual LUT drivers over
1,024 binary cut-point assignments. Effective host/core writes match the
declared fire and write signals; eight corruption-control methods pass.
The [actual mapped address-cone proof](build/openxc7/prefix-bram-address-selected-binary-resume-1791439177232717008/report.json)
passes at **14:01:32 HKT on 2026-10-08**. Its complete shared cone retains 557
actual cells and 624 unconstrained FDCE Q bits. Fresh vendor-versus-synthesis
binary qualification matches all 570,368 instance comparisons, and the executed
wrong-golden corpus is rejected. The warning-free actual SAT positive and real
wrong-golden SAT negative both pass their exact gates. Only complete
byte-identical definitions of the nine used combinational primitive types are
selected from the unchanged library; no function, RTL or hardware input is
modified. Thirty host controls and generated checks pass. All eight earlier
failures remain preserved; see [the detailed provenance](docs/OPENXC7.md).
This proves the twelve translated-address bits, ready and mapped core-fire
relations at the coherent binary producer-output boundary. It does **not**
prove four-state library equivalence, sequential transitions, temporal
ownership, write-before-read/startup independence, full numerical/physical
acceptance or bitstream readiness. No new `SHA256SUMS` file is created.
The separate actual working-BRAM overwrite qualifier has seven passing controls,
including compilation of its complete six-instance vendor-model corpus. Its
first actual run fails a string-versus-integer admission lookup before native
execution or input binding. The separate exact-key continuation has nine
passing controls, including direct full-source admission; its fresh native run
compiles the six unchanged vendor-model instances, but fails the first cold
read at 132 ns: mapped-X returns `xX00`, rather than all X, while zero/one
return `0000`/`ffff`. The strict real-negative gate rejects that failure;
neither the intended wrong-golden check nor the positive overwrite sweep
completes. A separate read-only model trace investigates this discrepancy
without changing that expectation, the frozen failure, or hardware input.
The read-only trace locates all 144 corrupted internal memory INIT parameters
in one instance of the combined six-RAM compilation. Three independent
two-RAM contexts preserve all 148 INIT/output parameter values per instance
and the expected cold values. A new full-corpus qualifier runs each startup
view separately, retaining its original X/zero/one expectations and strict
finite wrong-golden/positive gates. Its
[actual source-bound run](build/openxc7/isolated-working-bram-overwrite-1791442579674052605/report.json)
passes all three complete primitive corpora at 14:58:29 HKT, with all 4,096
cold words, 12,288 writes, 20,480 known reads, 12,288 READ_FIRST checks and
34 retention checks **per view**. This is primitive overwrite qualification,
not board-controller ownership/startup, FPGA or RK3588 acceptance.
The [actual initialization-state proof](build/openxc7/prefix-initialization-state-independence-1791444759482712816/report.json)
passes at **15:35:17 HKT**. It independently retraces the actual 497-cell cone,
qualifies all 508,928 vendor-versus-synthesis binary instance comparisons and
uses a separately qualified fold of the four actual FDCE state registers.
Both executed one-bit wrong-golden negatives are rejected. In current states
0–2, independently changing the two copies' sixteen-bit host read data cannot
change the four next-state bits when all other 679 producer values are shared.
This is a **conditional binary single-step proof**, not reachability,
initialization completion, temporal ownership, write-before-read, four-state
library equivalence or full-board/physical acceptance. The full C32/K16 target,
production RTL, live replay and placement remain unchanged; no new
`SHA256SUMS` manifest is written. See [the exact scope and provenance](docs/OPENXC7.md).
The [broader 47-bit controller/nine-control proof](build/openxc7/prefix-initialization-controller-independence-1791446683425337841/report.json)
now passes at **16:07:49 HKT**. It includes the complete index, watchdog and
error storage plus three response-ownership/error bits, retaining 1,245 actual
mapped cells. All 1,274,880 fresh vendor/library binary instance comparisons,
the executed wrong corpus and both actual SAT gates pass. Separate qualification
checks all 47 literal FDCE configurations with 752 checks each for seeded Q,
asynchronous behavior and next-edge folding. Revalidation binds all 724 saved
paths. In initialization states 0–2, the 47 next-storage bits and nine observed
controls are independent of host read data **for one binary step with all other
producer values shared**. This still does not establish temporal initialization,
write-before-read, full-board startup or physical/bitstream acceptance.
The [DMA-inclusive 50-bit extraction](build/openxc7/prefix-temporal-controller-cone-1791448312463936386/report.json)
adds the three actual DMA state bits and request-valid control without shrinking
the target. Both the paired miter and reset-guarded clocked model pass native
frontend checks. Its [fresh primitive qualification](build/openxc7/prefix-temporal-controller-primitives-1791449421248666952/report.json)
passes at **16:51:56 HKT**: all 50 literal FDCE configurations, 1,356,800
vendor/library binary instance comparisons and 1,600 actual clear-root checks.
The clear dependencies establish a single post-edge clear fixed point in the
binary edge model. This is preparation for induction, not an induction PASS,
four-state startup, numerical acceptance or a test-ready bitstream.
The [source-bound binary temporal continuation](build/openxc7/prefix-binary-temporal-ownership-wavejson-1791450218791135300/report.json)
passes at **17:09:41 HKT**, including actual base cases and induction at length
1. After an observed sampled reset, it proves controller port exclusivity,
arbitrary-probe prefix coverage and that core requests require all 4,096
initialization writes. The real wrong-golden trace is separately checked.
This is a binary positive-edge abstraction with other producers free each
cycle, not four-state startup, initialization liveness, RAM retention,
full numerical or physical/bitstream acceptance. The first trace-parser failure
is retained. A [fresh isolated production suite](build/source-identical-production-regression/1791450268992775192/report.json)
finishes **FAIL at 17:44:51 HKT**: both 247-entry EW RTL suites and 1,087,299
C++ comparisons pass, but the original 600-second Verilator build limit stops
`tb_cmac_product_front` after two product/operand benches pass. The CMAC Icarus
target does not execute. The failure, limits and unchanged source/fixtures are
retained; this is not a complete production regression PASS.
The [expanded actual-BRAM pin attempt](build/openxc7/prefix-actual-bram-barrier-1791452093147189951/report.json)
also remains FAIL: its library and binary initialization subproofs complete,
but an unused core-write trace wire is optimized away before the temporal
negative can execute. A [separate stronger core-write continuation](build/openxc7/prefix-actual-bram-core-write-1791453537307521260/report.json)
passes at **18:05:37 HKT** with actual base cases and induction at length 1.
After an observed sampled binary reset, it proves physical port exclusivity,
initialization before sensitive reads and effective core-write gating. Original
artifacts, register folds and native proof limits are unchanged. This still
does not establish four-state startup, full mapped numerical or physical
acceptance, or a test-ready bitstream.
The [actual reset/controller startup fixture](build/openxc7/prefix-actual-reset-startup-1791455659250174969/report.json)
finishes **FAIL at 18:43:18 HKT on 2026-10-08**. It freshly traces 1,331 cells
and 53 literal FDCEs, retaining unchanged vendor models/default GSR. The real
wrong-golden negative is rejected at 102 ns, but the positive fails at 172 ns
with an unknown error-code field in FAILED state. A
[read-only observer replay](build/openxc7/failed-reset-readonly-trace-1791456691562076912/report.json)
reproduces the same failure and shows the actual reset chain releasing before
that transition. The fixture holds 968 unowned producers X, including the
engine's fault/saved-code registers; it does not model their actual reset or
reachable behavior. The failure is preserved, not changed into a startup PASS
or called a production RTL bug. Full placement and mapped replay continue.
An [exact-board historical archive audit](build/openxc7/ypcb-configuration-reference-archive-1791453077631362251/report.json)
finds missing CFGBVS/configuration-voltage properties and a timing violation
in the reference XDMA build. Its existing bitstream is not electrical evidence
for this design. Actual Bank 0 voltage and the board's CFGBVS strap remain
unverified; no electrical/emission gate is waived.
Full raw-command DSP-board compile preparation completes with one literal
array substitution and unchanged downstream arithmetic, transport and bench.
The compiled hierarchy retains all sixteen cells and 512 lanes.
The full nine-mode replay runner now has nine passing admission controls and
checks the actual source-bound compiled board and composition certificate.
It still requires completed full-array native evidence before execution;
no raw-board mode or physical implementation PASS is claimed.
The subsequent full-board DSP mapper is prepared, with eight passing
structural/admission controls. It requires completed independent array/board
gates and checks unchanged mapped kernel wiring, not counts alone.
The full DSP mapped-array binary runner is now prepared with nine passing
harness/export controls and an expanded 80-test DSP control regression. A
small real Yosys control checks DSP string parameters and exact export wiring;
the full 208-frame mapped-array numerical run has not been executed.
The separate DSP-source Vivado checkpoint package is now prepared and archived.
The initial seventeen build/admission controls pass under both Tcl runtimes.
A fresh caller-independent source binding and DSP-profile reviewed emitter
are now implemented, with 18 build and 21 emission controls passing under both
Tcl runtimes and 98 DSP software controls passing. No prepared report can
authorize emission. Its run action
requires this variant's own completed
native, mapped binary, resource and nine-mode four-state board reports. It
retains the original physical gates and checks all 512 CMAC DSPs before a
checkpoint and after routing, and the emitter repeats that resource guard.
Preparation and mocked controls are not Vivado execution or signoff.
None of these is a full-array numerical or physical PASS. A separate read-only
shared-board union-fanin analyzer completes with 74,424 further proposals,
projecting 297,977 LUTs before existing output-role repairs. Splitting the
1,036 dual-O6 pairs raises that projection to 299,013, still above nominal
capacity. The reversible full-board transform completes exact export,
hierarchy and source checks; its independent full-domain function checks now
pass all 5,321 classes/9,284,320 four-state comparisons under each unchanged
model, with both real negatives. These are class proofs, not whole-board
numerical or physical acceptance. The small fixture passes 2,304 four-state
comparisons under each of Yosys and unmodified Xilinx models, with real
negatives; it is not a full-board proof. All sixteen kernels/512 products remain.
A separate residual six-input/cofactor packing search completes with only six
top-level proposals; its conditional projection is still above capacity. A
length-three rematching analysis completes with only sixteen further proposals;
its repaired conditional projection is 298,997 LUTs, 397 above nominal sites.
No transformed circuit or packed fit is accepted. The cofactor fixture passes 8,192 four-state
comparisons per unchanged model and both real negatives; this does not prove
actual board savings, and the current openXC7 packer does not preserve live-I5
pair sharing. No resources, numerical gates or physical checks are waived.
A separate fixed-variant Vivado flow requires its own nine-mode four-state
evidence and retains the original physical/review gates. No full-target bitstream has been
generated, and the FPGA/flash have not been programmed.

```text
actual RK register QWORDs
          |
          v
rk_ew_regs: target/address/value decode, complete-task validation
          |
          v
rk_ew_engine: read A -> read B -> FP16 operation -> write result
          |                    |
          |                    v
          |               rk_fp16_alu
          v
16-bit request/response memory interface
          |
          +-- testbench memory with stalls, delays and faults
          +-- rk_bram -> autonomous YPCB self-test
```

The command profile comes from `allbilly/rk3588/examples/elementwise.py`, including the real target IDs, byte register offsets, QWORD layout, shape encoding and terminal task tail. See `docs/SOURCES.md` and `docs/INTERFACE.md`. It is not an invented ADD/MUL command language and does not read tinygrad's high-level plans.

| Component | File | Scope |
|---|---|---|
| RK command decoder | `rtl/rk_ew_regs.sv` | Strict, complete one-task profile; unsupported fields fail |
| Execution controller | `rtl/rk_ew_engine.sv` | One outstanding memory request; ordered completion; sticky faults |
| FP16 datapath | `rtl/rk_fp16_alu.sv` | ADD, SUB, MUL; integer-built normalization/rounding |
| Candidate CMAC address leaf | `rtl/rk_cmac_address.sv` | Packed address/tag sequencing, also used by the separate product path |
| Candidate CMAC product path | `rtl/rk_cmac_product_front.sv` | Raw terminal commands to reads and tagged exact products; no accumulation, output writes, host or board integration |
| Integration top | `rtl/rk_ew_core.sv` | Raw command input and byte-addressed device memory |
| PC DMA top | `rtl/rk_ew_dma.sv` | Fetch unchanged command QWORDs and execute linked EW tasks |
| AXI memory adapter | `rtl/rk_axi_mem.sv` | Halfword requests to 512-bit AXI beats; not yet integrated with MIG/DDR |
| Host job control | `rtl/rk_job_control.sv` | One descriptor/result slot over AXI-Lite; explicit access errors and level IRQ |
| Internal host endpoint | `rtl/rk_ew_axi.sv` | Control, raw-command DMA and AXI memory adapter; single clock, no PCIe/MIG shell |
| BRAM adapter | `rtl/rk_bram.sv` | Synchronous RAM with separate initialization/readback port |
| Board DMA self-test | `rtl/rk_ew_dma_demo.sv`, `rtl/rk_dma_demo_rom.sv`, `rtl/rk_demo_memory.sv` | Unchanged production SUB(9), two tasks, bounded BRAM aperture and full readback |
| Legacy self-test | `rtl/rk_ew_demo.sv`, `rtl/rk_demo_rom.sv` | Three raw-port operations retained as regression |
| Board top/constraints | `fpga/ypcb_top.sv`, `fpga/ypcb.xdc` | Clock/reset/LEDs only; no DDR or PCIe |
| Functional emulator | `model/profile.py`, `model/sim.py` | Raw little-endian command bytes and mapped device buffers |
| Numeric references | `model/half.py`, `model/half_datapath.cpp` | Independent floating reference and integer design model |
| RTL verification | `tests/tb_*.sv`, `tools/run_rtl.py` | Verilator and four-state Icarus tests; tool absence is not a pass |
| Synthesis check | `tools/run_synth.py` | XC7 primitive mapping, BRAM inference gate and mapped-netlist self-test |

## Run the checks

From this directory, with Python 3.10+, a C++17 compiler and `tclsh`:

```sh
make model-test
make demo-replay
```

The software suite includes model/fixture tests, Vivado and openXC7 build-control tests, and **1,087,299 C++-versus-Python arithmetic comparisons**. Vivado build-script tests run Tcl with mocked commands; neither set of build-control tests performs physical implementation or validates timing/DRC. The numeric comparisons test the C++ arithmetic design, **not the SystemVerilog translation**. Reports and logs from new runs go under `build/`; archived source-bound evidence goes under `verification/runs/`. Historical delivery evidence is labeled separately in `verification/README.md`.

With a Verilator installation supporting `--binary` and `--timing`:

```sh
make rtl-test
```

This builds and runs thirteen HDL testbenches: 12,963 ALU vectors with continuous input and output backpressure; 140 command/memory scenarios; the BRAM demo; direct RAM protocol tests; demo fault injection; and board reset/LED tests. Verilator `-Wall` warnings are fatal. The scenarios include every required register omitted, every fixed field mutated, request/response timeouts, and faults after partial output writes or on the final write acknowledgment. The original 77 scenarios are retained; 63 exercise the explicit current-backend initialization group. A separate 62-case DMA bench replays nine unchanged production BO captures and tests chaining, framing, faults and reset. Two additional benches verify the captured-command board demo and its sparse memory aperture. The AXI and host-control benches described below test the memory adapter and internal endpoint.

```sh
make four-state-test # Same suite in Icarus, including unknown-readback fault injection
make synth-check    # Yosys XC7 mapping plus Icarus simulation of the mapped board netlist
make test           # Software, strict core/DMA/board lint, Verilator and Icarus
```

The RTL and synthesis reports record tool versions, exact commands, source SHA256 manifests, vector seeds and per-test results. A source edit during a run invalidates that run. This unpacked tree has no Git revision, so the content manifest identifies its source. `.github/workflows/test.yml` also runs the synthesis check; remote CI has not been executed. `make generated-check` detects stale generated register/ROM sources.

The AXI-memory increment adds a tenth bench: directed protocol checks, nine
production DMA replays through a behavioral 512-bit AXI RAM slave, and six
DMA fault cases. It retains every earlier test. See [AXI_MEMORY.md](docs/AXI_MEMORY.md)
for the actual local MIG widths, full-beat access contract and reset limitations.
The board top is still BRAM-only; an AXI adapter is not an integrated DDR system.

The host-control increment adds two more benches (twelve total). The standalone
control test checks the AXI-Lite transport ABI and lifecycle. The integrated test
submits nine production captures through public control ports, injects nine
faults, repeats jobs and resets during partial output writes. See
[HOST_CONTROL.md](docs/HOST_CONTROL.md) for registers, ownership and joint-reset
requirements. `make host-synth-check` maps the new endpoint and runs the mapped
control bench; `make synth-check` includes it after the existing board checks.
The preceding full regression and focused host mapping pass at source `060fe287ecda`:
246 entries per simulator, 82 matching cross-simulator memory images and a
passing mapped-control test. The initial whole-endpoint netlist attempt exposed
four startup-sensitive AXI error failures. At preceding source `f927a501cec9`,
all twenty tests pass using the corrected external reset-startup harness, with
all eleven output images equal to native RTL. The initial failures remain
archived. No DUT logic, vendor primitive or error expectation was changed to
correct that harness. This is functional netlist simulation, not a board test.

The address-only CMAC leaf adds the thirteenth original bench and is now used
by the separate raw-product path, not the EW endpoint. Its packed addresses,
tags, stalls and rejection checks passed
standalone and in the fresh combined regression. See
[CMAC_ADDRESS_CANDIDATE.md](docs/CMAC_ADDRESS_CANDIDATE.md). No GEMM command is
newly accepted. `make host-mapped-check` runs the full mapped endpoint suite
with the corrected startup wrapper, after matching `rtl-test` and
`host-synth-check` reports exist. CI now requests that check; remote CI is unrun.

The historical `verification/check_backend_encoder.py` check passed nine streams from an earlier candidate encoder, not the current user-supplied backend. The new `tools/capture_current_backend.py` uses the actual production compiler and final writer from `/home/fedora/tinygrad` at `078eee94d8f1912bb63ce786c250d2c24984844a`, retaining all BOs and raw words. Its initialized FP16 body, nonzero guard address and linked SUB are now implemented through the separate `rk_ew_dma` top. See `docs/PC_DMA.md` for the raw command-memory contract and portable capture fixtures. See `docs/EW_INITIALIZATION.md` and `docs/BACKEND_CAPTURE.md`. Neither check supplies RK silicon outputs or installs a tinygrad FPGA runtime.

## FPGA build

The following describes the initial preparation profile; the
[active plan](docs/REVIEW_AND_PLAN.md) records later build/physical results
and the current capacity increment. Its original preparation-only restriction
was superseded by the user's authorization for Vivado and audited SRAM tests.

That preparation uses `python3 tools/cmac/vivado_dsp_prefix_array.py prepare`
for the full C32/K16 DSP-prefix candidate. This checks the source profile and
generated ROM and writes source/Tcl snapshots and a preparation report. It does
not validate numerical parents, launch Vivado or establish synthesis, timing,
DRC or a usable bitstream.
The original preparation pass did not authorize its `synth` or `run` actions.

The [preparation report](build/rknpu-dsp-prefix-array-vivado/prepare-1792696631656679983/report.json)
and its `build.tcl` retain the full 32×16/512-product target. The separate
[read-only parent check](build/review-all-20261022T190646Z/cmac-vivado-parents-readonly.json)
rejects the saved prerequisites because their recorded `tools/cmac/vivado_array.py`
hash predates the reviewed banner-parser fix. Preparation does not override
that rejection or carry earlier numerical/physical results forward.

OpenTPU supplies the tool setup reference: set
`VIVADO_ROOT="$HOME/vivado/2026.1/Vivado"` and source
`"$VIVADO_ROOT/settings64.sh"` when preparing a shell for a later authorized
run. The settings file, Vivado launcher and a local license file were found by
read-only inspection on 2026-10-23; no current license checkout was tested.
OpenTPU's abandoned implementation work is not resumed or used as this
project's build evidence. The existing small-EW build instructions below are
separate from the full C32/K16 preparation target.

A separate [staged donor-based numerical core](docs/CMAC_NVDLA_CORE_CANDIDATE.md)
now connects unchanged terminal CMAC words through physical operand reads,
FP16 groups, accumulation, conversion and acknowledged output writes. Its
full Verilator and Icarus suites and XC7 primitive mapping pass; functional
netlist verification is in progress. A separate
[staged CMAC DMA wrapper](docs/CMAC_NVDLA_DMA_CANDIDATE.md) now fetches its
unchanged final command-buffer words; all 23 Verilator tests pass and
four-state regression is running. Its separate XC7 mapping passes.
Neither candidate is yet promoted into the production source, EW host
endpoint or FPGA top, and does not implement the compiler's runtime gathers.

A separate [staged CMAC AXI endpoint](docs/CMAC_NVDLA_AXI_CANDIDATE.md)
connects that DMA/numerical path to public AXI-Lite control and 512-bit AXI
RAM transactions. All 19 Verilator numerical, fault and reset integration
tests pass; four-state verification is running. It is not a PCIe/DDR shell
or a board-validated accelerator.

A [staged autonomous CMAC BRAM board demo](docs/CMAC_BRAM_BOARD_CANDIDATE.md)
now connects unchanged K=65 command DMA and donor arithmetic to synchronous
RAM, full initialization/readback and the YPCB clock/reset/LED wrapper.
All eight Verilator board-wrapper tests pass; four-state testing and XC7
mapping are running. This is not the production top or a physical FPGA result.

The separate [raw CMAC product path](docs/CMAC_PRODUCT_PATH.md) now joins the
strict terminal profile decoder, packed address walker, halfword reader and
exact FP16-to-FP32 product pipeline. Its new regression uses portable unchanged
compiler captures and synthetic operands; `make test` includes `make cmac-test`
and `make cmac-four-state-test`. It does not accept GEMM in the EW host endpoint
or produce accumulated output tensors. Older candidate archives are retained
as historical evidence, not carried forward as passes for this integration.

First pass `make rtl-test`. Then review the board constraints and `docs/FPGA.md`. The intended device in the referenced board files is `xc7k480tffg1156-2`, using the single-ended 50 MHz clock.

```sh
RK_CONFIRM_BOARD=YPCB_00338_1P1 make fpga
```

This invokes **Vivado synthesis/implementation**, not Vivado Lab. By default it stops at a routed checkpoint and reports. The recorded 2026-10-09 full Vivado 2026.1 version probe passed; the separate full C32/K16 synthesis-only [attempt](build/rknpu-dsp-prefix-array-vivado/synth-1791552618590027876/report.json) then exited 42 before synthesis because no valid license was found. That dated attempt establishes neither current license availability nor completed synthesis or implementation. This EW implementation flow remains unrun. Yosys mapping does not establish setup/hold timing, pin validity or DRC for the actual part. Bitstream emission additionally requires explicitly confirmed configuration-bank electrical settings, described in `docs/FPGA.md`. Nothing programs the board or flash automatically.

The earlier exact-part **openXC7** characterization route is retained as
[historical work](docs/OPENXC7.md). It is retired from the continuation;
Vivado is the implementation path. Existing openXC7 results do not establish
timing/DRC signoff or authorize another placement/routing attempt.

The self-test's logical outputs are LED0=pass, LED1=fail, LED2=heartbeat. Electrical LED polarity is configurable; it was not established by this review. The top instantiates no DDR, PCIe, flash or fan-control interfaces. A passing self-test would establish only this small EW path, not a usable tinygrad PCIe accelerator.

## Important review correction: soDLA is not proven drop-in FP16

The inspected `NV_NVDLA_CMAC_CORE_mac.scala` uses signed-integer multiplication and reduction. An RK register adapter cannot turn that into an FP16 CMAC/CACC path. This is a specific source finding, not a claim about every uninspected soDLA file. Accordingly, this delivery contains an independent FP16 EW slice, not a nominal soDLA fork with unverified arithmetic. See `docs/REVIEW_AND_PLAN.md` for the selective-reuse plan.

## Explicit limitations

The EW endpoint accepts only ADD/SUB/MUL in the fixed FP16, contiguous, eight-element-group profile, optionally with the complete 13-register bypass/unity initialization group. The separate CMAC product path has its own narrow terminal profile. For EW, the count is `8*(width+1)`; padded elements really are read and written. Width 0..7999 gives 8..64000 physical elements per task, subject to mapped memory capacity. DPU/RDMA widths and the optional WDMA width must agree. Sixteen-byte buffer alignment and 32-bit device addresses are required. Exact in-place output is allowed; partial output/input overlap is rejected.

No complete GEMM/convolution, CNA/CBUF/CSC/CMAC/CACC engine, PPU, LUT, quantized path, FP32 output tensor, general conversion pipeline, three-core scheduling, ping-pong overlap, hardware register readback, DRM ABI, PCIe transport, DDR controller, or tinygrad runtime hook is implemented. The partial CMAC path supplies tagged products only. The fixed 4 KiB self-test RAM is **not** a reduced RK CBUF. Its six trace-only windows expose 672 bytes, not the full original BO allocations; see `docs/DMA_BOARD_DEMO.md`.

The FP16 numerical policy is round-to-nearest-even, gradual underflow, infinities, signed zero and canonical quiet NaN `0x7e00`. Its match to RK3588 exceptional-value behavior is not established. The test vectors are synthetic; they must not be relabeled hardware goldens. In particular, the rounded FP16 MUL result must **not** be substituted for a wider CMAC product/accumulation pipeline.

## Next acceptance gate

Finish the fresh capacity-enabled full512 placement/routing, review and audit
its image, then run the physical two-GiB sweep and normal-job recovery.
Live framework coverage, injected ECC, PCIe and matched RK command/input/output
traces retain separate gates. See the [active plan](docs/REVIEW_AND_PLAN.md)
for their order, dependencies and acceptance criteria.
