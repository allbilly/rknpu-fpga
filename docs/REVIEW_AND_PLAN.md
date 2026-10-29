# Implementation plan and acceptance gates

Reviewed 2026-10-29 HKT. This is the active plan. The
[previous plan and dated implementation history](REVIEW_AND_PLAN_HISTORY.md)
preserve earlier decisions, receipts and failures; dated instructions there
are not current authorization or status.

Links into `../build/` refer to local receipts excluded from source control.
The linked `../verification/runs/` indexes identify portable records; newer
preparation reviews without an archive link remain workspace-local.

## Goal and fixed contracts

Build an incrementally qualified FPGA implementation underneath the existing
backend's final encoder. TinyStories-260K is the first application; general
tinygrad integration follows. This remains a narrow supported FP16 design,
not a complete RK3588 implementation or a completed soDLA fork.

- Execute original final command QWORDs, task descriptors and BO contents.
  Do not submit tensor operations around the encoder or add runtime CPU
  arithmetic/layout repair to the FPGA path. Unsupported fields fail explicitly.
- Retain FP16 C32/K16: sixteen output kernels, thirty-two input products each,
  all 512 parallel CMAC products. This is a precision-specific compute group;
  it does not assert RK silicon systolic topology or INT8 C32/K32 support.
  Capability increments do not introduce smaller compute targets.
- Retain both original DDR controllers, their source-bound channel mapping,
  ECC configuration and electrical settings. The current workload uses CH1.
- TinyStories places every learned projection on FPGA. Embeddings,
  normalization, attention, RoPE, SwiGLU, KV management and sampling remain
  explicit CPU operators. There is no learned-projection CPU fallback.
- Use Vivado. OpenXC7 and the abandoned OpenTPU implementation are historical.
  OpenTPU and ZYNQ-NVDLA are references, not transferred qualification.
- Vivado builds and audited temporary SRAM tests are authorized as needed.
  Bind the exact image and audited target before programming. Flash is
  unauthorized. Preserve the shared board lease throughout hardware ownership.
- Never weaken timing, DRC, CDC, reset or electrical checks to emit an image.
  Each changed source/image needs its own applicable evidence.

## Current progress

These rows describe separate profiles and source candidates. A passing
earlier image does not qualify a later changed image.

| Increment | Status | Evidence and remaining boundary |
|---|---|---|
| EW startup and USER2/BRAM | Passed selected physical tests | [EW](EW_FPGA_TEST.md), [host raw jobs](HOST_FPGA_TEST.md); not general RK compatibility |
| Full512/BRAM TinyStories | Passed full32 physical workload | [1,152 FPGA projections and exact logits](TINYSTORIES_FPGA_TEST.md) |
| Full512/DDR TinyStories | Passed full32 physical workload | [Same model on CH1](DDR_FULL512_FPGA_TEST.md): 1,152 projections, 16,384 logits, 28 token IDs; independent raw-wire review |
| Original capacity parent modeled execution | Fast model and real controller capacity model passed | [Fast normal/BIST/reset replay](../build/full512-capacity-parent-root-replay-v1/report.json), [one-MiB real-controller BIST/reset review](../build/full512-capacity-parent-validation-v4/root-result-review.json); these receipts precede the admission RTL fix |
| Capacity parent full synthesis | Passed | [295,755 LUTs, 512 product DSPs, 516 total DSPs, both controllers](../build/full512-capacity-vivado-run-v2/root-synth-review.json) |
| Original capacity parent routing | Failed setup by 52 ps; focused repair still failed by 44 ps | [First failure](../build/full512-capacity-route-run-v1/report.json), [focused repair](../build/full512-capacity-targeted-repair-run-v2/report.json); no timing acceptance or bitstream |
| Admission-factor timing fix | Synthesis passed; route and one targeted repair both failed setup by 9 ps | [Independent synthesis review](../build/full512-capacity-admission-vivado-run-v3/root-synth-review.json): 295,763 LUTs, 512 product/516 total DSPs, 242 IOs; [route failure](../build/full512-capacity-admission-route-run-v1/report.json), [repair failure](../build/full512-capacity-admission-targeted-repair-run-v1/report.json); no timing acceptance |
| Retirement snapshot timing fix | Passed independent routed timing, DRC, CDC/reset and source review | [Route acceptance](../build/full512-capacity-retire-route-run-v1/root-route-review.json): setup +0.027 ns, hold +0.052 ns, pulse +0.264 ns, zero failures; 290,266 routed LUTs, 512 product/516 total DSPs and 242 IOs |
| Current capacity parent with actual controller sources | Passed full modeled 1 MiB BIST/reset review | [Retirement-source result](../build/full512-capacity-retire-controller-v1/root-result-review.json): 123 HDL sources, 32,768 writes/reads, status `0x68`, global reset return; no physical capacity qualification |
| Capacity image and physical-runner preparation | Emission, IO and independent bitfile audit passed; source tag `2c8f17dd` | [Actual bitfile audit](../build/full512-capacity-retire-image-prep-v2/bitfile-audit.json), [successful physical image binding](../build/fpga-bringup/full512-capacity-retire-prep-v2/image-review.json); prior failures preserved, all gates retained |
| Physical two-GiB capacity and recovery | Passed full physical BIST and raw jobs after deliberate volatile reconfiguration | [Physical report](DDR_CAPACITY_FPGA_TEST.md): 67,108,864 writes/reads, status `0x68`, zero faults; four K65/SUB9 jobs, 245,760 BO bytes before ACK; live reset, physical FI/PCIe and full-model qualification on this image remain separate |
| Injected ECC/quarantine/recovery | Six full-parent actual-controller cases passed independent review; management bank component also passed | [Full-parent review](../build/full512-fi-parent-controller-model-v1/root-result-review.json): original K65/SUB9, CE/UE plus raw-job recovery, early ownership and capacity BIST; management/physical-wrapper integration, implementation and physical ECC remain pending |
| Live framework integration | All eleven selected EW cases passed physical review | [Complete native trial review](../build/fpga-bringup/full512-ddr-framework-prep-v1/root-result-review.json) on the qualified TinyStories DDR image: 11 jobs, 16 tasks, 1,081,344 BO bytes before ACK; CMAC, broader census and the new capacity image remain separate |
| Compiler CMAC layouts | Standalone raw-command encoder/DMA passed both native simulators | [Contract and test target](LAYOUT_DMA.md), [independent review](../build/backend-layout-root-review-v1/report.json): all 18 captured gathers/16,897 indices, all 65,536 raw halfwords, 34 positive cases twice per simulator, 51 Icarus/50 Verilator negatives; parent/runtime/reset and physical integration remain pending |
| Joined compiler-layout/CMAC parent | Six raw pipelines passed independent numerical/whole-BO review | [Seven-scenario review](../build/framework-layout-parent-replay-v6/root-result-review.json): all 24 stages, 3,358,720 pipeline BO bytes and 122,880 baseline bytes, exact engine read/write counts and original modeled capacity/reset controls; independent AXI RAM/ECC-control model only, with compute-reset/runtime/real-controller/physical qualification pending |
| PCIe plus JTAG system profile | Pending | Combined fit, memory/queue/reset contract and independent physical execution through both transports |
| Joined compute-reset parent | All six pipelines and baseline passed independent native review | [Reset/retention review](../build/framework-reset-parent-model-v3/root-result-review.json): 18 actual resets, 24 stages, 50 complete BO images/6,615,040 bytes; dirty state cleared, held-result admission blocked, retained DDR controls sampled on UI edges and no model reinitialization writes; runtime/real-controller/FPGA gates remain pending |
| RK numerical/shape differential | Pending | Actual RK outputs remain required for compatibility claims |
| Ordinary framework CMAC runtime | All six public-source shapes passed independent native wire/whole-BO review | [Current public profile](../build/framework-public-runtime-coverage-v1/root-result-review.json): 24 jobs, 18 layouts, six unchanged-writer CMAC submissions, 18 resets, 328,587 commands and 2,375,680 BO bytes before ACK; no host tensor/scratch reloads after launch; actual controller and FPGA remain separate |
| Published framework source/profile | Published 68-source ordered selection and explicit runtime/transport entry | [Profile contract](FRAMEWORK_FULL_PROFILE.md): 18 byte-identical RTL variants, 50 reused paths, ten runtime/twenty transport/five source controls; complete V22 regression running from a fresh 1,159-file source copy |

The new layout increment adds six source/test paths and extends the default
`make test` recipe with `backend-layout-test`. The fresh V21 regression
passes in 1,088.121 seconds from an independently reviewed 1,133-file source
copy, retaining the one-CPU/six-GiB/zero-swap limits and existing test gates.
Its [root review](../build/production-model-auditors/current-v21/root-review.json)
rehashes all inputs/copies and numerical/RTL/host receipts, the unchanged
32-command capacity-parent matrix, both compiled layout images and all
169 layout case markers/fixtures/logs. V20 below remains evidence for its
earlier source snapshot. The private reset/dispatcher preparation candidates
are excluded from this V21 qualification.

The preceding source/native regression V19 passes its complete default recipe in
1,246.321 seconds from a fresh 1,127-file source copy, including the admission
timing fix, published capacity-parent profile and client/wire controls. Its
[independent review](../build/production-model-auditors/current-v19/root-review.json)
checks both complete host receipts and the expanded 32-command parent matrix
with 15 result groups, 12 simulator images and 38 source bindings.
That earlier snapshot remains source/native evidence. The fresh V20 regression
now passes serial `make test` in 1,048.195 seconds after the three-file
raw-auditor/test increment. Its [independent review](../build/production-model-auditors/current-v20/root-review.json)
rehashes all 1,127 original/copied inputs, both complete host receipts and the
strict parent matrix, including all sixteen raw-wire controls. The
[capacity preparation document](DDR_CAPACITY_PREPARATION.md) records the
component contracts and source-bound results.

The two-file EW-DDR runtime/test increment has its own passing
`make backend-test` and 23 runtime controls, and is included in the passing
V19 full-source snapshot. V18 and V17 remain preserved separately.

The later admission RTL timing fix has separate paired-controller, parent-lint
and fast-model receipts. Its focused public regression and strict verifier
pass 32 commands, 15 result groups, 12 simulator binaries and 38 source inputs.
It is covered by V19; the earlier V18 snapshot predates this RTL change.
Fresh admission-source synthesis passed its independent review, but its route
and one supported targeted repair both failed setup by 9 ps. The admission
parent also passes its fresh actual-controller-source
model: 1,437.140 seconds under the unchanged 1,800-second case deadline,
32,768 writes and reads, and global reset return. Root rehashes 154 inputs.
This is a standalone modeled-capacity test; the current K65/SUB9 normal cases
remain separate fast-parent receipts. The earlier controller-model receipt
is not transferred to the new RTL.

The new retirement-snapshot variant stores one acceptance bit instead of the
96-bit constant tuple published by the strict monitor. Paired comparisons of
all 44 adapter outputs, including known asserted/deasserted reset cycles, and
the fresh fast-parent normal-job/BIST/reset model pass. The separate fresh
actual-controller model also passes its independent review: 123 HDL sources,
32,768 writes and reads, status `0x68`, reset return, 1,311.126 seconds under
the unchanged 1,800-second deadline. All 143 bound inputs rehash unchanged.
Fresh source synthesis passes independent review: 295,757 LUTs, 512 product
DSPs, 516 total DSPs and 242 IOs, with all 358 bound inputs unchanged.
Fresh placement/routing ran from checkpoint SHA-256
`11ad0d557c1ad83806e1690dd3f3dd02dc9bcc232a9c7545bc2fe764214f6dee`.
All six route helpers and implementation/timing/DRC gates retain their
reviewed behavior; root rehashed 379 prepared inputs before launch.
Its independently reviewed result now passes setup +0.027 ns, hold +0.052 ns
and pulse +0.264 ns, with no failing endpoints or routing errors. All 232
reported pulse rows and the exact 2,066-warning DRC inventory pass. Root
rehashes 381 inputs and 58 outputs; both original controllers, all 512 product
DSPs, 516 total DSPs and 242 IOs remain. The accepted routed checkpoint is
`042df439b963bbb20f7d1695754c643ad693016a94f043f40f60079c34934286`.
Earlier failed route receipts remain preserved.

The capacity milestone is complete for the exact reviewed image. The next
application milestone is **ordinary framework CMAC with hardware layouts and
an actual quiescent reset contract**. Management/physical ECC and PCIe source
integration may proceed independently. Preserve the already qualified images
and source-bound receipts; batch changed application-image features before
fresh full-model qualification.

The accepted capacity bitfile has SHA-256
`de982cd7e6c41d13de8e1f047c92fd515ab590e6958339a1dd37135642bef2a4`.
Its physical review rehashes 234 frozen inputs and 60 physical artifacts and
replays all six traces through EOF. Earlier failed emission and physical
attempts retain their own receipts. The status-auditor fix derives bits 10:8
from observed descriptor writes, requires active ownership and rejects all
error/reserved bits; it changes no RTL or bitfile and passes sixteen controls.
The [portable physical archive](../verification/runs/2026-10-29-full512-capacity-fpga/index.json)
preserves 426 payloads, all six traces, all 171 hardware sources and the
234 preparation bindings. Its independent byte review verifies every
source/stored/decompressed payload and all 60 physical artifacts.

## Execution order and exit criteria

### 1. Finish the current capacity route — passed

The fresh route completed with setup -0.052 ns, hold +0.039 ns and pulse
+0.264 ns, and was rejected by its setup gate. All 395 inputs stayed unchanged;
the failed receipt and fully routed checkpoint are preserved. Its 290,178-LUT
result retains the unchanged full512 source profile.

The scoped targeted physical repair from that exact checkpoint also finished
with setup -0.044 ns and remains rejected. Preserve both failed runs.
The measured worst path runs from MIG C1 control-register decode through the
ECC-health/fault chain into descriptor clock enables, with 86.8% routing
delay. The repair uses critical-cell replication and placement/routing
optimization, followed by router TNS cleanup. Vivado rejected the first
focused attempt's optimizer TNS flag before optimization; that failed receipt
is preserved, and the corrected run omits only that unsupported flag.
No further blind physical-only retries are planned. The admission timing fix
factors descriptor-write/SUBMIT/ACK guards using the parent's direct
live-block/busy predicate, while retaining the original status, fault-code,
completion and ownership expressions. It adds no state or latency. Paired
original/candidate controllers pass in Icarus and Verilator; four-state guard
truth checks, parent lint and the new fast-parent raw-job/BIST/reset test pass.
Fresh synthesis passed in run-v3; root rehashed all 445 bound inputs and the
actual mapped reports/checkpoint. The measured post-opt count is 295,763 LUTs,
with all 512 product DSPs, 516 total DSPs and 242 IOs retained. The initial
resource preflight launched no Vivado and remains preserved. The process-only memory estimate understated
the parallel synthesis aggregate. Its bounded cap was adjusted from 8 to 10,
then 12 GiB using recorded host/cgroup measurements, without OOM or changes
to source, clocks, numerical/error expectations or implementation checks.
The new source profile has 171 files: one parent replacement and two added
control modules; all 168 other files retain their bytes. Old checkpoints and
timing/model receipts do not qualify that revised RTL.

The admission route ran from post-opt checkpoint SHA-256
`7774b05086b75a10648b45d881264fcc621fe71447d73789c234a4201633c081`.
Its three constant-anchor names were derived from this synthesis's actual
101 post-opt observations. Imported and routed module censuses require one
dual and two per-bank admission controllers. The unchanged global setup/hold
gate now runs before the expensive detailed helper audits so a failed route
is rejected sooner; every existing helper and pulse/DRC check still gates a
successful result. Before native launch, the route's prospective memory cap
was set to 12 GiB with a 20 GiB host-available minimum, retaining 8 GiB beyond
the full cap; the previous single-process route measured an 8.2 GiB peak.
This resource choice changes no source, implementation directive, deadline or
FPGA acceptance threshold. It completed fully routed but failed setup with
WNS -0.009 ns, TNS -0.049 ns and seven endpoints; hold +0.050 ns and pulse
+0.264 ns passed. One supported targeted physical repair left the same
setup failure. Both failed receipts are retained; no further physical-only
retry of that checkpoint is planned.

The measured worst path terminates at the capacity adapter's retirement-ECC
snapshot register clock enables, with a common enable driving 96 bits.
The new [retirement variant](../build/full512-capacity-retire-snapshot-variant-v1/derivation.json)
stores only acceptance of the actual monitor's invariant tuple
`status=0, onoff=1, irq_mask=3`; its outputs reconstruct the same tuple.
All fence, timeout, fault, pending-response and snapshot handshakes remain.
This is a specialization for that strict monitor, not a generic arbitrary
snapshot implementation. The public generic adapter remains unchanged.
The fresh 171-file source set replaces only that adapter; the other 170
files retain their bytes. The new synthesis uses source elaboration rather
than an old checkpoint. Its actual-controller model also recompiles the
changed adapter and asserts the monitor publication invariant.

Accept only complete routing, finite nonnegative setup/hold slack and every
reported pulse-width row, no missing/unconstrained internal clocks, and the
reviewed exact DRC policy. Recheck all 512 products, both MIGs, IO/electrical
settings, DSP selection, reset branches, CDC/mailbox paths and constants.
If timing fails, diagnose the actual paths and qualify any correction with
fresh applicable source/model/mapping evidence. Keep all 512 products.

### 2. Review and emit the capacity image — passed

After routing passes, review its input bindings and reports, emit a fresh
source-tagged bitfile and independently audit that bitfile. Reuse the audited
lease/loader/transport utilities; retain exact source, tool, image and target
identity. Do not reuse an earlier image's tag or physical receipt.

Use the prepared bounded physical runner and the published
[capacity client](../tools/ddr/capacity_client.py). Verify the exact RKMT
identity, ABI, full window and healthy normal banks before seed/START.
Unknown management addresses, wrong image, busy ownership, bad responses or
health loss must fail. The client must not connect, reprogram, reset,
reconnect or fall back implicitly.

### 3. Test physical capacity, then recover normal execution — passed via reconfiguration

Under the audited board lease, temporarily load the reviewed image. Check
calibration/ECC initialization, scratch access and original raw K65/SUB(9)
controls with complete BO readback before ACK.

Run the complete CH1 byte window `0..0x7fffffff`:

1. Write every 64-byte line ascending, then read every line ascending.
2. Write every line descending with complemented data, then read ascending.

Acceptance requires 33,554,432 distinct lines, exactly **67,108,864 writes
and 67,108,864 reads**, four retirement/ECC witnesses, final RKMT status
`0x68`, no mismatch and healthy final status. Preserve actual wire/controller
observations and all sixteen expected/actual words on mismatch. Immediate
write/read pairs or a partial span cannot qualify capacity.

After diagnostic ownership, use the supported audited whole-domain reset
or volatile reconfiguration path. Reinitialize memory and reload the exact
original BOs before normal jobs; no arithmetic/layout reconstruction.
Verify normal execution and fault recovery in the new epoch. Record each
operation actually performed; do not infer a live reset from reconfiguration.
This gates normal-job recovery acceptance on the capacity-enabled image;
it does not invalidate the previously qualified application image.

The completed physical review confirms both trials, exact terminal counts,
strict final health and original K65/SUB9 execution before and after the second
audited SRAM load. The BIST compares DDR data internally; JTAG observes its
source-bound management witnesses rather than every memory payload. All owned
groups stop before lease release; flash is unchanged. See the
[complete result and evidence boundaries](DDR_CAPACITY_FPGA_TEST.md).

### 4. Resume live framework coverage

The pinned existing compiler/final writer now passes the selected HALF EW
ADD/SUB/MUL cases through the real FPGA byte transport: lengths 8/9/33,
repeated SUB(9), and explicit runtime-gather rejection. Independent review
checks all 11 jobs, 16 tasks, 1,081,344 BO bytes before ACK and 117,578 actual
scans on the existing qualified TinyStories DDR image. Owned processes close
before lease release; flash is unchanged. This is selected coverage rather
than the complete upstream `test_ops` suite or the new capacity image.
Then extend the framework adapter to submit the already-supported raw CMAC
path; the TinyStories runner already exercises that FPGA datapath. Requalify
it on the intended image and add compiler-required hardware layout operations
still missing. Keep explicit rejections for runtime gathers or
other unsupported profiles until FPGA support exists.

Source inspection of the pinned `_lower_cmac_reduce` confirms that ordinary
CMAC lowering emits two input-dependent gathers and an output gather around
the CMAC command. The upstream runtime executes them on the CPU, outside the
45-QWORD body. Admitting the CMAC class alone cannot qualify this stage:
define and implement those layouts at the raw-command/hardware boundary
before claiming ordinary framework matmul without CPU layout work.
The [fresh six-shape index contract](CMAC_ENCODER_CONTRACT.md) verifies all
16,897 captured gather indices without running tensor arithmetic or gathers.
The new [raw layout encoder and DMA](LAYOUT_DMA.md) now execute those 18 plans
in both native simulators, with complete-aperture comparisons, retained results,
repeat execution and fault drainage. The encoder also accepts the actual
pinned original `RKGather` types for every captured plan. The private FPGA
extension serializes compiler indices only; hardware moves the original
halfwords. The joined parent now passes the separate raw-pipeline and actual
compute-reset native reviews listed above. Production transport/framework
dispatch and actual-controller/FPGA qualification remain pending; the default
adapter still explicitly rejects CMAC.
Also implement the original standalone CMAC reset boundary: the pinned final
writer calls `reset_npu()` after success, and the current adapter correctly
rejects that unsupported operation. Define quiescence and BO retention/reload;
do not bypass the reset or change the clean-context flag to obtain a pass.
The separate [compute-reset preparation candidate](../build/framework-reset-candidate-v1/CONTRACT.md)
now passes [component review](../build/framework-reset-candidate-v1/root-result-review.json)
in both native simulators, including fresh-edge acknowledgment, stopped clocks,
held results and sticky faults. It is absent from the production source/image;
the final-writer integration and physical qualification remain required.
The later common-assert reset candidate now passes the joined native parent
[review](../build/framework-reset-parent-model-v3/root-result-review.json):
actual quiet/ready witnesses, reset CSR/router and all 18 reset epochs across
six unchanged layout/CMAC pipelines, with 50 complete BO images compared.
The independent AXI RAM/minimal ECC-control model retains its initialized
contents; this does not qualify the actual MIG/PHY, runtime adapter or FPGA.
The separate [three-kind dispatcher candidate](../build/framework-layout-dispatch-candidate-v1/CONTRACT.md)
also passes [protocol review](../build/framework-layout-dispatch-candidate-v1/root-result-review.json)
in both simulators, using the actual layout DMA with explicitly nonnumeric
EW/CMAC children. It checks selected ownership, held results, malformed
layout commands, fault/late drainage and blocked retries. It does not qualify
the actual parent, EW/CMAC arithmetic, DDR fence, reset composition or FPGA.

Record a supported-operation census, shape/dtype limits, raw commands,
complete BO comparisons, timeouts, ownership and recovery. Preserve the
`test_ops -> existing compiler -> final commands/BOs -> RTL or FPGA` path;
passing selected cases does not mean the entire backend suite passes.
Add the supported compiler/RTL cases to a reproducible CI target with the
backend revision pinned; keep portable fixture tests runnable without that
external checkout. Report local and remote CI execution separately.
The local workflow now includes the pinned backend compiler/RTL job and
portable fixture checks. Its local `make backend-test` recipe passes all
eleven cases; remote execution of this new workflow has not been triggered
by this session.

Source preparation for this step can proceed while Vivado runs. Physical
execution requires the reviewed intended image and serialized board access;
it does not depend on completing every future ECC injection case.

### 5. Qualify a separate ECC injection profile

Keep ordinary ECC health monitoring strict. First evaluate the independently
controlled FI-register access described in the [source map](DDR_CAPACITY_PREPARATION.md#ecc-injection-boundary),
retaining the normal payload layout where the actual vendor source permits.
That option needs its own pinned source variant and all diagnostic/normal
qualification; the current image still rejects FI writes. Enabling the full ECC_TEST mode changes the
generated 64-bit payload interface to 72 bits and adds width adaptation;
repeat relevant normal numerical/controller tests before injection claims.
Bind injection, valid event observation, retirement and control arbitration
to actual vendor sources. Exported UI error vectors alone are not valid events.

The source candidate now separates the control-leaf permission argument from
the parent's payload mode, and the actual control/mask component passes both
simulators. The vendor control hardwires OKAY responses and aliases denied
reads to a tied-off DUMMY value. Add strict project-side address, access,
strobe, reserved-bit and ownership validation before forwarding; do not infer
write acceptance or armed state from that vendor response/readback. The
current capacity build and public FI rejection behavior remain unchanged.

The internal guard now passes coupled actual-vendor tests, including denied
fields with no forwarded transaction, silent vendor OKAY without a mask
witness, late draining requests after timeout, reset-invalidated mask knowledge,
and faults while a successful response is held for acceptance. The separate
startup/control composition now also passes both simulators with actual
vendor control and FI leaves. It zeros all nine mask bytes before monitor
setup, retains ownership through pending control traffic, separates initial
memory admission from an early diagnostic request, and requires joint-reset
recovery after a nonzero arm even if the mask is subsequently cleared.
Tests cover bootstrap timeouts, missing write witnesses and raw IRQ quarantine.
The new explicit-port candidate carries mask writes, exact FI-leaf clear,
MC ECC validity/classification/address and read-data-valid through the vendor
wrappers. FI-control permission is a separate parameter, overridden only for
physical C1; both payload ECC_TEST modes remain OFF. It is absent from the
current capacity source set. Icarus wrapper elaboration failed on retained
vendor attribute syntax; that attempt is preserved and is not a port-binding
pass. Full generated-wrapper/parent qualification remains required.

A separate [actual-MC native test](../build/ddr-fi-mc-service-test-v1/root-result-review.json)
now passes independent review in Verilator 5.048. The original vendor FI leaf
changes exactly bits `0x1` and `0x3` in stored encoded data, with the artificial
read-corruption hook tied off. Actual MC-valid CE/UE events each occur once:
CE corrects the full returned buffer and UE returns SLVERR with the expected
uncorrected data. The ordinary monitor quarantines both cases; dirty ownership
persists after mask clear. Joint reset, bootstrap disarm and an explicit line
rewrite restore normal operation. All 76 native inputs rehash unchanged;
1,280 complete readback bytes, 13 mask writes and 20 actual clear observations
are checked. The encoded-PHY model has no physical training/pads. Next connect
the prepared witness ports and service to full-parent data arbitration,
full-span initialization, diagnostic read/retirement control and recovery.
No host API or physical ECC qualification is admitted by these results.

The private [full-parent composition](../build/full512-fi-parent-source-v1/derivation.json)
now adds a validated raw 64-byte diagnostic request interface and a data mux
ahead of the existing capacity mux. Capacity START and FI acquisition cannot
take ownership together. A separate descriptor/SUBMIT admission block leaves
accepted launches, original result readback and ACK drainage intact. A
pre-initialization quiet output derives from pending transaction state rather
than requiring initialization complete. The bootstrap disarm therefore runs
before the full-span initializer, including after a reset with a retained mask.
Any effectful diagnostic data request retains ownership until joint reset;
AXI B completion alone cannot return normal ownership.

The [line interface component](../build/ddr-fi-line-access-test-v2/root-result-review.json)
passes 24 Icarus and 19 Verilator controls, including invalid requests, expected
UE response, skew/stalls, stable held responses and timeout/late drainage.
The [full-parent fast model](../build/full512-fi-parent-fast-model-v1/root-result-review.json)
passes original K65/SUB9 whole-BO comparisons (122,880 bytes), full modeled
one-MiB BIST/reset, early FI request through 16,384-line initialization,
readback/ACK before FI acquisition, denied capacity START during FI, and
retained-mask disarm before reinitialization. Its actual vendor CTRL/FI leaves
produce the witnesses; the ordinary RAM model explicitly fails any data write
with a nonzero FI mask and cannot qualify ECC corruption. Root rehashes all
85 native inputs; no new diagnostics are admitted.

The fresh 128-source actual-controller model now passes its
[independent six-case review](../build/full512-fi-parent-controller-model-v1/root-result-review.json).
Compilation takes 509.615 seconds under the original aggregate 3,600-second
budget, and every case completes under the unchanged 1,800-second deadline.
Original CMAC/EW jobs, early FI ownership, actual valid CE/UE with raw-job
recovery, and capacity BIST/reset all pass on the same fresh executable with
separate reset cases. Root rehashes all 142 inputs and 327,680 complete
numerical BO bytes before ACK, including both recovered raw SUB(9) runs.
The encoded-PHY model does not qualify physical training/pads or the new RKFI
page. Generated-wrapper qualification, management/host integration, fresh
implementation and physical ECC tests remain required.

A separate [RKFI management candidate](../build/ddr-fi-management-source-v1/CONTRACT.md)
now defines explicit ownership, raw control/line commands, mask/MC event
observations and complete result readback before ACK at page `0x300`.
Its standalone [component review](../build/ddr-fi-management-tests-root-v3/root-result-review.json)
passes 85 Icarus and 76 Verilator register writes, with four control and three
line requests per simulator. Tests cover raw result stability, all sixteen R
handshakes before ACK, timeout/late drain, ownership/control/response faults,
and four-state rejection. No RTL errors/deadlines were relaxed; bench failures
are preserved. Full raw-backend/parent/MIG and physical qualification of this
new bank remain pending. It is absent from the capacity image under preparation.

The FI mask is write-only, affects the first 72-bit codeword, clears on a
controller write with clear priority, and has no reset port. Explicitly zero
all nine mask bytes after an aborted armed test before recovery admission.
Verify physical correctable and uncorrectable events, quarantine, no false
success, pending-transaction behavior, disarm and whole-domain recovery.
Use separate diagnostic expectations without relaxing ordinary job checks.

### 6. Build and qualify the PCIe/JTAG system profile

First define allocation/device addresses, 32/64-bit policy, command delivery,
completion/interrupts, visibility/coherence, timeout, ownership and reset.
Audit the chosen PCIe lane/pin/clock/reset map; an XDMA reference is not an
integrated shell or an automatically compatible DRM device.

The [read-only reference inventory](../build/pcie-reference-inventory-v1/NOTES.md)
now pins 36 source/report/receipt files from OpenTPU and ZYNQ-NVDLA, including
the actual IP settings, pins, reference clock/reset, BAR/interface widths and
address windows. OpenTPU records separate JTAG and Mac PCIe runs on the same
image; the raw Mac receipts are absent locally and no concurrent two-host
test is recorded. The inspected ZYNQ-NVDLA receipt explicitly leaves PCIe
untested. These references inform integration; no result qualifies this design.

Check actual combined resource fit early, retaining both interfaces,
controllers and all 512 products. Qualify routing/timing/DRC, then run actual
application jobs through PCIe and JTAG independently. JTAG success does not
prove PCIe, and configuration DONE does not prove application execution.
Rerun the complete TinyStories workload on the stable final application
image before claiming that image's full-model qualification.

### 7. Establish RK compatibility and broaden supported profiles

Pin the backend and RK reference revisions. Capture actual RK raw commands,
initialized BOs, outputs and reset/provenance for supported ADD/SUB/MUL and
GEMM profiles. Compare complete bytes or state a justified tolerance.

Cover signed zeros, subnormals, overflow, NaN/infinity, tail groups, lengths
7/8/9 and 31/32/33, K=65, alignment, exact/partial aliasing and linked tasks.
Preserve source/weight atom packing, logical CBUF semantics, strides,
traversal, reduction/rounding order and output placement. Preserve original
software-visible capacity or reject an unsupported profile explicitly.

Use the audited NVDLA FP16 leaves as the working numerical donor, with
selected conversion/accumulation behavior documented per path. The inspected
soDLA integer MAC is not an FP16 substitute. Donor agreement and Python/RTL
consensus do not establish RK equivalence or identify a defect's location.
Use the [donor audit](NVDLA_CONVERSION_AUDIT.md) and
[local source references](LOCAL_REFERENCES.md) when extending support.
This evidence collection and fixture preparation can proceed independently
of the capacity/ECC hardware sequence.

The numbered list prioritizes the next physical milestone, not a dependency
chain for all work. Framework, RK fixtures and PCIe contract/fit preparation
may proceed independently; only physical access is serialized by the lease.

## Original work packages remain in scope

| Original package | Current disposition |
|---|---|
| A. Executable RTL evidence | Established for frozen subsets; run generated/native/four-state and appropriate mapped checks after source changes |
| B. Real backend and RK traces | Actual compiler captures and selected RTL execution exist; actual RK differential remains step 7 |
| C. EW board bring-up | Selected startup and raw USER2 physical milestones passed; preserve their exact image scope |
| D. FP16 GEMM | Selected full512 raw GEMM/TinyStories passed; broader shapes, gathers, layouts and RK semantics remain steps 4 and 7 |
| E. Host transport and CI | JTAG and supported source runtime exist; live framework, broader census and PCIe/system remain steps 4 and 6 |

Three-core scheduling, overlapping ping-pong groups, general convolution,
LUT/activation/conversion modes beyond supported paths, PPU, quantized/integer
paths, calibrated RK timing, host-driver emulation and a full SystemC model
remain deferred. Add modes from concrete backend evidence with contracts and
tests; neither a narrow workload nor this reorganization closes those items.

## Verification and work discipline

Run `make generated-check` after edits and `make test` when available; use
focused tests for the changed contract, and retain unavailable-tool limits.
Record actual tool versions, source identity, seeds and tests. C++ arithmetic,
RTL simulation, mapped simulation, route/timing, bitfile audit, volatile load,
application execution, PCIe and flash are separate evidence levels.

After repeated harness failures, inspect the bench and protocol directly
before another expensive compile. Freeze test inputs before execution and
use fresh observation paths. Sparse BO fixtures require fresh zeroed backing
memory or complete BO uploads; reset alone does not clear RAM.

Review a completed milestone once and retain its source-bound receipt;
optional packaging must not delay the active image or physical test. Repeat
full32 inference when qualifying a changed application image, rather than
after every preparation-only edit. Preserve failures and earlier images;
never copy an old pass forward as evidence for modified RTL.
