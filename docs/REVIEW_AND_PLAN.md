# Implementation plan and acceptance gates

Reviewed 2026-11-03 HKT. This is the active plan. The
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
- Do not impose RAM, memory-high or swap caps on continuation jobs. The user
  explicitly removed those limits; retain source, tool and hardware checks.

## Current progress

Current focus: qualify the service-admission repair in the combined PCIe/JTAG
image. The [published source pair](../rtl/ddr/capacity/service_admission_cofactor/README.md)
passes binary composition and paired native checks. Its independently audited
saved mapping removes all 32 diagnostic CTRL read-data admission dependencies
while retaining 1,999 component FFs/66 owner FFs. Fresh
[full synthesis](../build/capacity-service-admission-full-synth-v1/results-review.json)
passes at 293,553 LUTs/89,807 FFs/516 DSPs with the required full compute and
interface topology. Both fresh codegens and C++ builds pass independent review;
the original sixteen-job warm and twelve-case controller replays are running.
Fresh retained-constant and mapped-interface audits pass. Strict implementation,
placement, routed timing and a new-image FPGA test remain required.

The preceding capacity-admission health cofactor passed full-synthesis review at
293,543 LUTs/89,807 FFs/516 DSPs, with the complete required topology retained.
Both fresh model binaries and constant-retention/mapped-inventory stages pass
review. Its fresh warm replay passes sixteen jobs/1,441,792 BO bytes, and all
twelve controller cases pass their original V4/whole-BO checks. Strict and
placement structural reviews pass. Unrouted placement estimates still fail
setup −1.144 ns and hold −0.392 ns. Its guarded route now fails setup at
−1.109 ns across 3,422 endpoints; hold passes at +0.014 ns. The complete routed
checkpoint and failure review are preserved. Timing and FPGA qualification
remain pending for this source. The component and full-source
receipts are linked in the capacity-admission paragraph below.

The preceding snapshot/publication candidate remains separately qualified by
its saved source and model receipts. That
combined snapshot-scope/result-publication repair has passed independent
[full-synthesis review](../build/snapshot-scope-cofactor-full-synth-v1/results-review.json):
293,628 LUTs, 89,807 FFs and 516 DSPs, retaining all 512 products, sixteen
kernels, both MIGs, both CACC pipelines, PCIe and USER2/UI plus USER3/SYS.
Its 201-input selection changes only source orders 112, 116, 148 and 149
relative to the preceding result/counter candidate. Fresh [constant retention](../build/snapshot-publication-retained-prep-v1/retention-results-review.json)
and [mapped inventory](../build/snapshot-publication-retained-prep-v1/inventory-results-review.json)
pass independent review. Both fresh codegens pass independent warning/artifact
review. Both fresh C++ builds
([warm](../build/snapshot-publication-warm-continuation-v1/build-results-review.json),
[controller](../build/snapshot-publication-controller-continuation-v1/build-results-review.json))
and [strict constraints](../build/snapshot-publication-implementation-prep-v1/strict-results-review.json)
pass independent review. The fresh
[warm replay/whole-BO review](../build/snapshot-publication-warm-replay-v1/results-review.json)
passes sixteen jobs, twelve compute resets, one SYS reset and 1,441,792 BO bytes.
The fresh [controller review](../build/snapshot-publication-controller-replay-v1/results-review.json)
passes all twelve original V4 cases, six complete BO outputs/532,480 bytes,
seven successful SYS resets and 32,768 BIST writes plus 32,768 reads. The fresh
[placement review](../build/snapshot-publication-implementation-prep-v1/placement-results-review.json)
passes all original structural/protection checks; unrouted setup remains
−1.465 ns/TNS −2,527.684 ns across 4,604 endpoints and hold −0.978 ns/THS
−151.362 ns across 1,223 endpoints. Its worst estimated setup path reaches
backend line-data enables from C1 MIG CTRL through full monitor health.
The [fresh guarded route](../build/snapshot-publication-route-prep-v1/source-review.json)
has completed from this reviewed placement checkpoint. Its
[independent failure review](../build/snapshot-publication-route-prep-v1/failure-review.json)
verifies all 450,895 routable nets, zero routing errors, the original protection
inventories and only inherited DRC warnings. Guarded cleanup removes twenty-three
unloaded nets and eight proven-dead O5 buffers without changing routing or
slacks. Setup still fails at −1.208 ns/TNS −1,874.641 ns across 3,925 endpoints;
hold passes at +0.012 ns. The worst path reaches compute-reset block-level state
from C1 CTRL through monitor health and capacity admission. The saved cleaned
checkpoint remains a failed-timing diagnostic, not an accepted image. The
[explicit source candidate](../rtl/ddr/pcie_snapshot_publication/README.md)
preserves all 201 selected inputs through 177 existing repository sources,
22 new HDL files, one header and the separately supplied unchanged XDMA
component. Its source-only renderer runs no model, Vivado or hardware action;
the default targets remain separate. The
[fresh public default regression](../build/snapshot-publication-public-regression-v1/results-review.json)
passes with all 44,020 source inputs unchanged, including 582 tests across
28 unittest runs plus the original native suites. It does not select this
candidate's full-system RTL. Routing and hardware acceptance remain
pending for this source.

The preceding result/counter candidate passed both full-parent model suites
and placement structural checks, but its preserved raw route fails setup at
−1.457 ns; hold passes at +0.014 ns. Cleanup additionally rejects a new
PDRC-61 warning. The read-only diagnostic's Vivado command completed, but its
Python output collector failed on a contract-key mismatch; an
[additive saved-artifact audit](../build/result-counter-zero-pdrc61-probe-v2-artifact-audit-v1/report.json)
records that failure and two inventory-query limitations without changing the
original report. The [fresh guarded O5 cleanup diagnostic](../build/guarded-o5-cleanup-candidate-v1/results-review.json)
now passes: all eight proven-dead O5 buffers are removed, PDRC-61 clears, and
functional connectivity, routing and slacks remain unchanged. That result does
not repair the failed setup timing or qualify the new combined source.
There is no accepted new image. Historical TinyStories
success applies to its earlier image only.

These rows describe separate profiles and source candidates. A passing
earlier image does not qualify a later changed image.

The preceding timing candidate changes only the parent reset-request qualification.
Its [native review](../build/reset-request-qualified-native-v2/results-review.json)
uses the actual CSR and reset sequencer; its
[mapping review](../build/reset-request-qualified-mapped-v1/results-review.json)
checks the same modules and the exact parent expression. Neither compiles the
full parent. The [fresh full-synthesis review](../build/reset-request-qualified-full-synth-v1/results-review.json)
now accepts 293,466 LUTs/89,793 FFs/516 DSPs and the full retained interface/compute
census. The warm C++ build passes; the controller executable has a separate
[saved-artifact acceptance](../build/reset-request-qualified-controller-continuation-v1/build-acceptance-v1/report.json)
after its producer rejected the newly generated static archive. All 491 archive
members match the fresh objects; the original failed producer is unchanged.
The [fresh controller replay review](../build/reset-request-qualified-controller-replay-v2/results-review.json)
passes all twelve original cases, six BO outputs/532,480 data bytes, seven SYS
reset markers and 32,768 BIST writes/reads. Its [strict review](../build/reset-request-qualified-implementation-prep-v1/strict-results-review.json)
passes all thirty artifacts and all original protections. Its
[placement review](../build/reset-request-qualified-implementation-prep-v1/placement-results-review.json)
passes structural checks but still fails unrouted setup −2.099 ns/TNS
−9,773.441 ns across 9,457 endpoints; hold is −0.392 ns.

The first warm replay reached the unchanged 1,800-second wall-clock deadline.
Its [partial-trace diagnostic](../build/reset-request-qualified-warm-timeout-diagnostic-v1/report.json)
finds 31,969,393 complete-line bytes identical to the earlier accepted trace
prefix, out of that trace's 33,756,027 bytes. This is progress diagnosis only,
not completion or numerical acceptance. The [fresh V2 warm wire/BO review](../build/reset-request-qualified-warm-wire-audit-v2/results-review.json)
now passes sixteen jobs, twelve compute resets, one SYS reset and 1,441,792
whole-BO bytes before ACK, including modeled stopped-UI SYS access and stale
lease denial. The simulator reports 1,241.288 seconds under the unchanged
1,800-second deadline using the same executable and fixtures. The first failure
is preserved; resource contention remains a possible cause rather than a proven
diagnosis.

The preceding candidate is a state-qualified monitor READY expression. Source
proof removes only the three read-data fault predicates that require mutually
exclusive READ states; full HEALTH, fault priority and sequential behavior stay
unchanged. Its [paired native review](../build/monitor-ready-state-cofactor-native-v3/results-review.json)
passes 29 Icarus and 23 Verilator original cases, seventeen outputs and state
comparisons, plus a separately scoped 12,288-case four-state expression table.
The [matched OOC review](../build/monitor-ready-state-cofactor-mapped-v1/results-review.json)
checks READY's read-data cone goes from 32 inputs to zero while HEALTH retains
all 32; FFs remain 195 and LUTs change 90→99. The fresh
[201-input full synthesis](../build/monitor-ready-full-synth-v1/results-review.json)
passes at 293,534 LUTs/89,793 FFs/516 DSPs with the complete retained census.
The [strict constrained review](../build/monitor-ready-implementation-prep-v1/strict-results-review.json)
passes the original constant, startup, clock, reset and electrical checks.
Both fresh full-parent codegens and C++ builds pass independent review:
[warm model](../build/monitor-ready-warm-continuation-v1/build-results-review.json)
and [controller model](../build/monitor-ready-controller-continuation-v1/build-results-review.json).
The [fresh warm replay](../build/monitor-ready-warm-replay-v2/results-review.json)
and [wire/whole-BO audit](../build/monitor-ready-warm-wire-audit-v1/results-review.json)
now pass independently: sixteen jobs, twelve compute resets, one SYS reset
and 1,441,792 complete BO bytes before ACK. The actual new executable finishes
in 1,238.839 seconds under the unchanged 1,800-second deadline. It uses ordinary
RAM and actual vendor CTRL/FI leaves; it does not qualify physical MIG/PHY.
The [placement review](../build/monitor-ready-implementation-prep-v1/placement-results-review.json)
now passes its original structural checks at 287,659 LUTs/89,862 FFs/516 DSPs,
but unrouted setup remains −1.624 ns/TNS −6,358.057 ns across 8,646 endpoints;
hold is −0.392 ns. The worst path runs from C1 control decode through full
monitor health and memory availability into the response-payload enable:
nineteen LUT levels and 87.296% estimated net delay, versus twenty-seven levels
in the preceding candidate's worst path. The
[raw route review](../build/monitor-ready-route-prep-v1/results-review.json)
now verifies 450,495/450,495 routable nets and zero routing errors. Setup still
fails at −1.454 ns/TNS −3,941.236 ns across 5,253 endpoints; hold passes at
+0.012 ns. The original 65-register startup inventory fails after routing,
despite the pre-physical-optimization audit retaining 130 protected startup
registers. Read-only checkpoint comparison identifies two new replicas of
the UI startup final-reset register, introduced by physical optimization;
all original 130 protected startup FFs remain. No inventory, timing or
electrical gate is relaxed. Cleanup, detailed audits and image
acceptance were not reached. The
[fresh controller review](../build/monitor-ready-controller-replay-v2/results-review.json)
now accepts all twelve original cases, six complete BO images/532,480 bytes,
seven successful SYS resets and 32,768 BIST writes/reads. Sources, binary and
owned process cleanup pass. This is modeled controller/PHY evidence, not
physical memory or PCIe acceptance.
Routed timing and a new FPGA image remain unqualified.

The next [response-payload zero-bank candidate](../build/jtag-response-zero-bank-native-v1/results-review.json)
preserves all twenty-three outputs, held invalid-cycle data and eleven shared
state fields in the original twenty-eight-reply fixture; Icarus also passes
supplemental four-state cases. [Matched OOC mapping](../build/jtag-response-zero-bank-mapped-v2/results-review.json)
verifies all 512 payload FFs in both designs: memory-availability fanin falls
from 1,024 data/enable pin hits to zero, while control-path dependence remains.
LUTs change 1,763→2,275 and mapped FFs 1,228→1,235; an optimizer-level cause for
the seven-FF difference is not inferred. Its [source-only full-design review](../build/response-zero-full-synth-v1/source-review.json)
binds exactly one replacement, backend order 108, among 201 current inputs.
Both eighty-two-project model crosswalks require the new backend at index seven
and retain the other eighty-one source files byte-for-byte. The
[fresh synthesis review](../build/response-zero-full-synth-v1/results-review.json)
now passes at 293,554 LUTs/89,804 FFs/516 DSPs with all required interfaces,
controllers and products retained. The
[matched full-design fan-in inventory](../build/response-zero-full-fanin-inventory-v1/results-review.json)
records 1,024 old memory-driver and C1 control-address-register hits on payload
D/CE pins versus zero in the new 512-FF bank. This is mapped connectivity,
not routed timing. Both fresh C++ binaries pass exact archive/link/source review.
The fresh [warm wire/BO review](../build/response-zero-warm-wire-audit-v1/results-review.json)
passes sixteen jobs, twelve compute resets, one SYS reset and 1,441,792 complete
BO bytes before ACK. The twelve-case controller replay with host concurrency
two and the original cases, validators and deadlines unchanged has a fresh
[independent review](../build/response-zero-controller-replay-v1/results-review.json)
passing all twelve original cases. This is model-only evidence and does not
qualify routing or hardware.
Fresh [constant retention](../build/response-zero-post-synth-prep-v1/retention-results-review.json)
and [crossing/reset inventory](../build/response-zero-post-synth-prep-v1/inventory-results-review.json)
also pass. The fresh [strict review](../build/response-zero-implementation-prep-v1/strict-results-review.json)
passes the original 35 constant proofs, three retained grounds, 130 protected
startup FFs and original 65-register inventories, clock/reset/electrical gates
and retained interface census. It additionally protects the two original
startup output-net families and verifies all 21 logical segments before and
after optimization. Fresh placement passes structural checks, but unrouted
setup is −2.128 ns and hold is −0.718 ns. The subsequent route attempt stopped
before `route_design` at the post-phys-opt retained assertion-source guard; it
preserves DCP `a7a1635a2102f5cf69eed093dfc7dd3f51ad1822ce60b8fd49cb43dc15921781`.
A [read-only comparison](../build/response-zero-release-source-inventory-v1/results-review.json)
identifies the changed source: all three frontend CLR cones use
`clients_rst_n_reg_replica_1/C` instead of the original register's clock pin.
The other four frontend sources and all six readiness source sets match.
The [in-memory protection probe](../build/retained-assertion-source-property-probe-v1/results-review.json)
protects the seven original declared sources and 75 discovered net segments
while preserving their recorded topology, all 130 startup-cell snapshots and
the unchanged three-family release inventory. Preservation through optimization
and routing still requires fresh proof; no source inventory or guard is relaxed. There is no
routed timing result or new image. A separate private
[UI-stable DONE cofactor component candidate](../build/reset-ui-stable-done-cofactor-native-v1/results-review.json)
passes paired native and [matched OOC review](../build/reset-ui-stable-done-cofactor-mapped-v1/results-review.json): the result-ready CE input count
falls from 32 to zero, LUTs from 320 to 316, and FFs remain 208. It remains a
component-only candidate, not a canonical source or full-parent/physical result.
The fresh full-design [source review](../build/ui-stable-done-full-synth-v1/source-review.json)
binds a [201-record manifest](../build/ui-stable-done-full-synth-v1/source-manifest.json)
with only sequencer order 165 replaced. Its
[warm](../build/ui-stable-done-full-synth-v1/model-crosswalks/warm-82-project-crosswalk.json)
and [controller](../build/ui-stable-done-full-synth-v1/model-crosswalks/controller-82-project-crosswalk.json)
82-project crosswalks change only index 64. Its fresh
[full-synthesis review](../build/ui-stable-done-full-synth-v1/results-review.json)
passes source/resource census at 293,492 LUTs, 89,804 FFs and 516 DSPs. Fresh
[warm](../build/ui-stable-done-warm-continuation-v1/build-results-review.json)
and [controller](../build/ui-stable-done-controller-continuation-v1/build-results-review.json)
C++ builds pass independent review. Fresh [constant retention](../build/ui-stable-done-post-synth-prep-v1/retention-results-review.json)
and [mapped inventory](../build/ui-stable-done-post-synth-prep-v1/inventory-results-review.json)
also pass. The [strict structural review](../build/ui-stable-done-implementation-prep-v1/strict-results-review.json)
passes the original gates, including seven assertion sources/75 net segments
and 130 protected startup registers after optimization; it does not accept
timing. The fresh [placement review](../build/ui-stable-done-implementation-prep-v1/placement-results-review.json)
passes structural checks, including seven assertion sources/75 net segments,
but unrouted setup fails at −2.041 ns/TNS −7,626.422 ns across 9,025 endpoints;
hold fails at −0.469 ns across 1,445 endpoints. The worst reported setup path
runs from the C1 control address through full monitor HEALTH and snapshot-hit
selection into the legacy memory-adapter state enable: 23 logic levels and
9.001 ns data-path delay. Routing must provide its own timing result.

The first warm replay attempt [timed out at the unchanged 1,800-second limit](../build/ui-stable-done-warm-replay-v1/results-review.json).
The read-only [timeout diagnosis](../build/ui-stable-done-warm-timeout-diagnostic-v1/report.json)
matches 33,148,976 complete-line bytes to the prior accepted trace prefix; it
is not a completed replay or whole-BO result. Fresh warm replay V2 now passes
[marker/provenance review](../build/ui-stable-done-warm-replay-v2/results-review.json)
and the [independent wire/whole-BO audit](../build/ui-stable-done-warm-wire-audit-v2/results-review.json):
sixteen jobs, twelve compute resets, one SYS reset and 1,441,792 whole-BO bytes
before ACK. The same binary and fixtures finish in 1,203.315 seconds under
the unchanged 1,800-second deadline. The first timeout remains failed evidence.
The fresh
[controller review](../build/ui-stable-done-controller-replay-v1/results-review.json)
passes all twelve original cases, six complete output buffers/532,480 bytes,
seven SYS resets and 32,768 BIST writes plus 32,768 reads. All source hashes
remain unchanged and owned process groups are closed. The
[guarded route review](../build/ui-stable-done-route-prep-v1/results-review.json)
verifies 451,005/451,005 routable nets and zero routing errors, but setup fails
at −1.801 ns/TNS −4,998.582 ns across 5,759 endpoints; hold passes at +0.013 ns.
All original constant, startup, seven-source and electrical guards pass through
the bounded cleanup, which removes 23 unloaded nets/four proved unused LUT1
buffers without changing timing. The 1,121 input hashes remain unchanged and
owned process groups close. The route remains failed at its strict setup gate;
there is no accepted image. Its worst path traverses C1 CTRL read decode,
monitor HEALTH and capacity admission into a job-result code enable.
These model runs do not qualify physical MIG/PHY behavior,
RK execution or a new FPGA image.

The next isolated [SUBMIT result-zero candidate](../build/job-submit-result-zero-cofactor-candidate-v1/source-review.json)
has source-only review against the exact current controller. It removes two
redundant zero assignments: a result-free admissible state already has zero
code/error, while error results remain sticky and unacknowledgeable until
reset. It changes no latency, numerical datapath, clock or constraint.
Fresh [paired native review](../build/job-submit-result-zero-native-results-review-v2/review.json)
now passes 3,233 Icarus and 2,534 Verilator comparisons, including all original
public outputs/shared state and the invalid-result zero invariant. The
[matched OOC review](../build/job-submit-result-zero-mapped-v1/results-review.json)
verifies memory-ready input hits on the nine result code/error FFs fall from
nine to zero, while both designs retain submit admission dependencies. LUTs
change 205→195 and FFs remain 286. This is component evidence; fresh full-parent
models and routed timing remain required before selecting it. The first native compile selected a
ccache wrapper despite compiler environment variables; that attempt is
preserved and unaccepted. The fresh V2 build explicitly passes the direct
compiler/linker through make arguments, with all original test expectations.

A separate [fabric counter zero-bank source review](../build/fabric-counter-zero-bank-candidate-v1/source-review.json)
accepts the reset-reachable representation proof for five counters and the
last completed write address. Six publication bits replace wide payload zero
enables, preserving all logical 32-bit values, original update/clear priority,
wrap/overflow checks and late drains. No clock, latency or compute grouping
changes. The [basic native review](../build/fabric-counter-zero-bank-native-results-review-v1/review.json)
now passes all original 21 Icarus/19 Verilator protocol cases, comparing 51
outputs, 44 shared state fields and all six logical counter/address values.
The suite does not directly seed overflow or simultaneous clear/increment.
A separate [formal review](../build/fabric-counter-zero-bank-formal-v1/results-review-v2.json)
accepts binary reset observations and conditional matching-point induction;
all 2,581 equivalence points pass. Deliberate reset, full-width wrap and
clear-priority mutations are rejected by the proof checks; the initial narrowed-port
elaboration failure is excluded. This remains a conditional binary result,
not unconditional equivalence from arbitrary independent initial states or a
four-state/physical proof. The [matched OOC review](../build/fabric-counter-zero-bank-mapped-v1/results-review.json)
now verifies 185 payload FFs in both designs, all 740 D/CE observation rows
and twelve publication-control rows. Selected control fanin reaches up to 370
baseline payload points; all seven measured controls reach zero candidate
payload points. Initialization/health dependencies
remain on the publication flags. LUTs change 2,314→2,408 and FFs 1,111→1,117.
The first version-only OOC attempt failed on a missing execution-contract key;
its evidence is preserved, and fresh v2 completed after the runner/contract
and exact-version source checks were corrected. These are component results.

The two repairs are selected in the fresh
[combined full-synthesis review](../build/result-counter-zero-full-synth-v1/results-review.json),
which passes the resource census at 293,584 LUTs, 89,807 FFs and 516 DSPs.
All 512 product lanes, sixteen kernels, both MIGs, two CACC units, PCIe and
USER2/USER3 remain retained. Its 201-record manifest changes only orders 112 and
149. The other 199 source paths/bytes and all parameters/XDC/IP references remain
identical to the immediate parent. Both 82-project model crosswalks change
indices 11 and 48 only, retaining eighty project sources. This run checks
resource fit and retained topology; it does not establish timing. Fresh
[constant retention](../build/result-counter-zero-retained-prep-v1/retention-results-review.json)
and [mapped inventory](../build/result-counter-zero-retained-prep-v1/inventory-results-review.json)
pass independent review with all 35 constant witnesses and three ground nets
retained. Both [warm](../build/result-counter-zero-warm-prep-v1/codegen-results-review.json)
and [controller](../build/result-counter-zero-controller-prep-v1/codegen-results-review.json)
source-generation and warning reviews pass. The
[address composition review](../build/mig-ctrl-address-admissibility-v1/source-composition-review-v1.json)
limits the four vendor CTRL width warnings to this known-reset binary source
profile: the generic model truncates bit 31, while the selected monitor and
guarded FI producers issue only low addresses. The generic alias remains
unqualified; the earlier warm warning-review failure is preserved.

The fresh [warm C++ build](../build/result-counter-zero-warm-continuation-v1/build-results-review.json)
and [controller C++ build](../build/result-counter-zero-controller-continuation-v1/build-results-review.json)
pass independent source/runtime/object/archive review. The fresh
[strict review](../build/result-counter-zero-implementation-prep-v1/strict-results-review.json)
accepts the original clock, electrical, reset and DRC gates, 35 constant-field proofs and
three grounds, 130 startup registers, 21 protected startup net segments and
seven assertion sources/75 segments. This remains a structural diagnostic,
without timing acceptance. The fresh
[warm replay/whole-BO review](../build/result-counter-zero-warm-replay-v1/results-review.json)
passes all sixteen jobs, twelve compute resets, one SYS reset and 1,441,792
complete BO bytes across the unchanged two eight-job phases. Its actual trace
and original numerical/ownership auditors are bound to the new executable.
Controller replay and
placement started after the warm run closed, retaining the original test
deadlines. The first warm replay service was rejected before model
execution because its Python interpreter differed from the reviewed snapshot.
Its journal and failure receipt are preserved; the fresh service uses the exact
reviewed interpreter with unchanged source, fixtures and deadlines. The fresh
[controller review](../build/result-counter-zero-controller-replay-v1/results-review.json)
now accepts all twelve original cases plus the coordinator-fault precheck,
six complete output buffers/532,480 BO bytes, original ECC/recovery assertions
and 32,768 BIST writes plus 32,768 reads. This remains model-only evidence.

The [incremental controller review](../build/result-counter-zero-controller-incremental-review-v3/report.json)
accepts nine completed cases using the unchanged V4 validators, including CE/UE
recovery and held-result controls, with 430,080 whole-BO payload bytes checked.
Capacity, coordinator-fault and late-drain completion were pending in that
snapshot; the complete review above now closes the matrix separately.
The [current emitter source review](../build/result-counter-zero-image-emitter-prep-v1/source-review.json)
and [Tcl review](../build/result-counter-zero-image-emitter-prep-v1/tcl-source-review.json)
retain the original emission/timing/electrical checks and adapt admission to the
new compact model reports. Seven prefix controls pass; an actual emission request
with missing parents is rejected before creating an emission directory. Its
read-only preflight accepts both completed model suites and waits on route and
detailed-audit acceptance. The fresh
[placement review](../build/result-counter-zero-implementation-prep-v1/placement-results-review.json)
passes the original structural protections, but setup is −1.692 ns/TNS
−3,628.345 ns across 6,093 endpoints and hold is −0.392 ns, both unrouted.
The worst setup path reaches the legacy memory adapter FSM through snapshot-hit
selection. The [guarded route failure review](../build/result-counter-zero-route-prep-v1/failure-review.json)
verifies all 450,803 routable nets with zero routing errors and retention of
the original startup/reset/assertion-source protections. Raw setup fails at
−1.457 ns/TNS −2,885.518 ns across 5,720 endpoints; hold passes at +0.014 ns.
The worst routed path now reaches job-result code enables through completion
error qualification. Cleanup stops on PDRC-61#1, dangling O5 at
`SLICE_X186Y398:C5LUT`. That warning is absent from the raw-route DRC and
appears in the cleanup-stage report. The old helper removed four named O5
buffers, while this placement has eight O5 buffers among the exact same
twenty-three guarded unloaded nets. The separately reviewed diagnostic above
removes all eight with the original non-target/DRC/route/slack guards retained.
The initial read-only probe incorrectly expected it in the raw checkpoint and
is preserved as failed. No severity, DRC or timing gate has been relaxed.
No new image has been emitted. SRAM-load preparation still needs fresh bindings
to this emitter and its future image; the renderer below selects the prior image.

Two private candidates remain separate from that failed full design. The
[snapshot-scope cofactor](../build/snapshot-scope-cofactor-candidate-v1/source-review.json)
passes [paired component tests](../build/snapshot-scope-cofactor-native-results-review-v1/review.json)
and [scoped binary composition checks](../build/snapshot-scope-cofactor-equivalence-prep-v1/results-review.json).
Its [matched OOC path](../build/snapshot-scope-cofactor-mapped-v1/timing-depth-review.json)
changes from twelve to eleven LUT levels and 4.582 to 4.175 ns estimated delay,
with unchanged LUT/FF counts and health/abort dependence retained. This is not
full-chip routed timing.
The [result-publication bank](../build/job-result-publication-bank-candidate-v1/source-review.json)
passes [paired native tests](../build/job-result-publication-bank-native-results-review-v1/review.json)
and a [selected-observer binary proof](../build/job-result-publication-bank-formal-v1/inductive-observers-v5/results-review.json)
with a reset base, depth-one induction and a real mutant counterexample. The
proof covers publication/control/protocol observers; earlier induction failures
and the whole-public bounded timeout remain preserved. Its
[matched OOC review](../build/job-result-publication-bank-mapped-v1/results-review-v2.json)
shows completion-error/done input hits on nine payload enables fall from nine
to zero, LUTs 195→181 and FFs 286→286. Error-code data and result-valid state
paths remain measured. The original internal-Q columns have false negatives;
the [offline correction](../build/job-result-publication-bank-mapped-v1/classification-review-v2.json)
confirms active-register dependence from the saved C/Q startpoints. Both
candidates are selected in the private combined full-synthesis profile. They
are not yet promoted to the public source profile or qualified as a new FPGA
image.

The private [SRAM-load renderer](../build/ui-stable-done-sram-load-prep-v1/runner-review.json)
now passes source review against the approved emitter-v2 selection. Its
seven-source assertion crosswalk uses the actual variable net-segment count.
The [programming components](../build/ui-stable-done-hardware-executor-prep-v1/component-results-review-v2.json)
pass twenty device-free controls, including actual transient user scopes
with detached children, server-listener ownership and strict programming
receipt checks. The shared lease remains held through child cleanup; observed
memory/high/swap limits are unlimited. These remain source/preparation results;
no real board lease, programming or application run occurred.

The combined-image TinyStories preparation now uses an acquired RKHO frame
owner instead of reusing the older direct-namespace transport. Device-free
transport and decoder controls preserve raw commands/BOs, retained sequence
wrap, explicit owner release and error rejection. A separate
[synthetic auditor review](../build/ui-stable-done-hardware-executor-prep-v1/combined-auditor-results-review.json)
checks 232 jobs/348 tasks/950,272 BO bytes through the unchanged numerical
checker, with corrupted-logit and BO controls rejected. Its saved data and
regenerated frame envelope are unit-test fixtures, not new RTL or physical
execution evidence.

The [outer application runner](../build/ui-stable-done-hardware-executor-prep-v1/README.md)
now has [independent source/preparation review](../build/ui-stable-done-hardware-executor-prep-v1/application-runner-results-review.json).
Its 35-code/180-static-input inventory binds the model, original raw catalog,
host compiler, native bridge and source-bound worker/auditor. Nine admission
and source-loading controls and four mocked execution controls pass, alongside
the twenty ownership/source-buffer controls. A fresh direct GCC 16.2.1
external-dense host build/load also passes with zero inference positions or
learned projection calls. Worker host libraries remain fresh builds, with
their source/compiler receipts checked against this feasibility build.
The executable path requires one audited volatile load and three serial
phases: first BOS, repeated BOS and full32, each with complete raw-wire/BO
auditing. Its default preflight does not access hardware. Actual image-plan
and trial admission, combined-image inference, independent physical review,
and separate SYS/ECC/PCIe qualification remain pending.

| Active task | Status | Exit gate |
|---|---|---|
| Three-control-fix full models | Passed: 12 controller cases; 16 warm jobs, 12 compute resets and one SYS reset | Bound to that earlier parent |
| Three-control-fix placement | Structural pass; setup −2.257 ns, hold −0.392 ns, both unrouted | Timing remains failed |
| Reset-request repair | Paired native and isolated mapping passed; health-to-quiet 6→2 levels, 2.733→1.441 ns | Fresh full-parent models and implementation |
| New full synthesis | Passed: 293,466 LUTs, 89,793 FFs, 516 DSPs | All 512 products, both MIGs, PCIe, USER2/UI and USER3/SYS retained; no routed timing claim |
| Reset-request candidate full models | Both independently passed: 12 controller cases and 16 warm jobs/1,441,792 BO bytes | Bound to the preceding source; original producer/timeout failures preserved |
| Monitor READY cofactor | Native/component mapping passed; 32→0 read-data READY inputs, HEALTH retains 32 | Fresh full-parent replays and physical timing still required |
| Reset-request candidate placement | Strict structural pass; unrouted setup −2.099 ns and hold −0.392 ns fail | New monitor candidate targets the remaining path; no routed acceptance |
| Monitor candidate full builds | Full synthesis and both fresh C++ builds independently passed | Fresh full-parent replays remain required |
| Monitor candidate implementation | Raw routing completed; setup −1.454 ns fails, hold +0.012 ns passes; startup inventory fails | Preserve failed checkpoint; diagnose inventory and repair actual critical path |
| Monitor candidate full models | Warm replay/wire audit and all twelve controller cases independently passed | Physical MIG/PHY, PCIe and new-image application tests remain separate |
| Response-payload zero bank | Earlier route stopped before `route_design` at the retained assertion-source guard | Preserve the failed checkpoint and its diagnosis |
| DONE cofactor: current routed diagnostic | Controller/warm regressions pass. All 451,005 nets route with zero errors; reset/startup/protected-source and cleanup guards pass. Setup −1.801 ns fails; hold +0.013 ns passes. | Preserve failed route; qualify the next timing repair before another full build |
| SUBMIT result-zero timing repair | Paired native and matched mapping independently pass: nine result FF input cones removed, 205→195 LUTs/286 FFs | Fresh full-parent models and timing before selection |
| Fabric counter zero bank | Original 21/19 protocol cases, conditional formal checks and matched mapping reviewed: 370→0 live-control payload points, +94 LUTs/+6 FFs | Fresh full-parent checks; formal assumptions and direct-simulation limits remain explicit |
| Combined result/counter full design | Both model suites and placement structural checks pass. Raw route: 450,803/450,803 nets, zero route errors; setup −1.457 ns fails, hold +0.014 ns passes. Cleanup rejects new PDRC-61 | Preserve failed route; qualify control-path repairs, diagnose cleanup, then fresh full-parent/physical gates |
| Snapshot-scope and result-publication source candidate | Component/native and scoped binary checks pass; combined full synthesis independently passes at 293,628 LUTs/89,807 FFs/516 DSPs | Retention/inventory, both codegens/C++ builds, strict checks, fresh16-job warm replay and all12 controller cases independently passed; placement structure passes; route/cleanup complete but setup −1.208 ns fails, hold +0.012 ns passes; next admission repair in component qualification |
| Capacity-admission health cofactor v3 | Source, native, binary/four-state equation and matched OOC reviews pass; health path 4→1 levels, 2.492→1.117 ns estimated | Full synthesis, both model suites, retention/inventory, strict and placement structure passed. Route: all 450,829 nets routed, zero errors; setup −1.109 ns fails, hold +0.014 ns passes. Preserve failure; repair the shared diagnostic-completion/admission path |
| Service admission cofactor | Binary composition, sixteen service runs, four owner comparisons and twenty saved-image replays independently pass; saved matched mapping removes 32→0 admission dependencies with unchanged FF counts | Fresh full synthesis, both codegens/C++ builds and retention/inventory audits independently pass. Original sixteen-job warm and twelve-case controller replays are running; strict implementation, placement, routing and physical tests remain required |
| Guarded O5 cleanup | Independent diagnostic passes: eight proven-dead buffers, zero PDRC-61; route and slacks unchanged | Recheck on the new source route; no timing acceptance |
| Combined-image application preparation | Outer runner is source-reviewed; admission/source-loading, mocked execution, ownership and actual direct host-build checks pass. RKHO transport/decoder and synthetic whole-BO auditor controls pass. | Admit the actual image and concrete trial, then perform new-image tests and independent physical review |
| PCIe BRESP sink | [Exact component](../build/xdma-component-response-input-probe-v1/results-review.json) and [integrated strict-checkpoint](../build/integrated-xdma-response-sink-probe-v1/results-review.json) topology reviewed: no AXI-Lite BRESP sink; BVALID and RRESP controls remain connected | Run the read-only converter audit on the eventual routed image; retain host mask/status/readback checks |
| Public regression | [Fresh full serial default suite passed](../build/snapshot-publication-public-regression-v1/results-review.json) with 44,020 inputs unchanged; 582 unittest checks plus original native suites | Default targets remain separate from the candidate full-system model suites; not physical MIG, FPGA, ECC or RK silicon |
| New-image FPGA qualification | Pending | Routed timing/DRC/crossing acceptance, audited volatile load, then JTAG/PCIe and TinyStories tests |

The next private [capacity-admission health cofactor](../build/capacity-admission-health-cofactor-candidate-v3/source-review.json)
changes only the admission predicate of the owner leaf, full-source order 154.
Known-good health and no request make two earlier fault-encoder branches
redundant for admission; public fault encoding, registered state and latency
remain unchanged. A kept combinational non-health predicate places the health
qualification at the last mapped gate. Fresh
[proof review](../build/capacity-admission-health-cofactor-proof-v3/results-review.json)
accepts 126 matched-state binary RTL points, a reset-reachable missing-health
mutant counterexample, and a separate 8,192-vector four-state equation table.
[Native review](../build/capacity-admission-health-cofactor-native-v4/results-review.json)
passes eight original service profiles plus paired owner cycle/state comparisons
in both simulators; Icarus additionally exercises X/Z inputs.
[Matched OOC review](../build/capacity-admission-health-cofactor-mapped-v2/results-review.json)
verifies all four health-input paths shrink from four logic levels/2.492 ns
to one level/1.117 ns estimated delay. LUTs change 108→106, FFs remain 66 and
ports remain 123; public fault-state input dependence and five high fault-code
constant-zero bits are retained. These component results do not qualify full
parent timing or hardware. Fresh
[full synthesis](../build/capacity-admission-health-full-synth-v1/results-review.json)
passes independent review at 293,543 LUTs/89,807 FFs/516 DSPs and the original
full topology. Both fresh C++ builds pass exact archive/object/source review.
Fresh [retention](../build/capacity-admission-health-retained-prep-v1/retention-results-review.json)
and [mapped inventory](../build/capacity-admission-health-retained-prep-v1/inventory-results-review.json)
pass their original checks. The fresh
[warm replay](../build/capacity-admission-health-warm-replay-v1/results-review.json)
passes sixteen jobs, twelve compute resets, one SYS reset and 1,441,792 BO bytes.
The fresh [controller review](../build/capacity-admission-health-controller-replay-v1/results-review.json)
passes all twelve original V4 cases, six complete BO outputs/532,480 bytes,
seven successful SYS resets and 32,768 BIST writes plus 32,768 reads. Fresh
[strict review](../build/capacity-admission-health-implementation-prep-v1/strict-results-review.json)
and [placement review](../build/capacity-admission-health-implementation-prep-v1/placement-results-review.json)
retain the original structural/source/protection gates. Placement setup remains
−1.144 ns/TNS −1,366.967 ns across 3,542 endpoints; hold is −0.392 ns/THS
−158.363 ns across 1,669 endpoints, all unrouted. The worst estimated path
reaches compute-reset UI-stable enables from C1 CTRL. The fresh
[guarded route](../build/capacity-admission-health-route-prep-v1/source-review.json)
completed from the reviewed `c10b055e…` placement checkpoint. Its
[failure review](../build/capacity-admission-health-route-prep-v1/failure-review.json)
verifies all 450,829 routed nets with zero routing errors, unchanged source and
startup/assertion protections, successful guarded cleanup and only inherited
DRC warnings. Setup fails at −1.109 ns/TNS −1,424.385 ns across 3,422 endpoints;
hold passes at +0.014 ns. All one hundred worst paths pass through diagnostic
completion and capacity admission: 72 line-data enables, 24 lease-epoch enables,
three compute-reset state inputs and one FI-owner state input. None ends at
the separately tested idle-counter candidate, so that change alone does not
justify another full build. The next service-admission candidate must prove
the actual diagnostic-reset composition, retain standalone fault rejection,
pass fresh native tests and remove the measured dependency in mapping before
full-parent qualification. Detailed audits, image admission and physical
qualification remain required. Earlier declaration, native-harness and OOC
report-table failures are preserved; none is relabeled as a successful run.

The [published admission owner leaf](../rtl/ddr/capacity/admission_health_cofactor/README.md)
is byte-identical to that tested order-154 selection. Its source index pins
the baseline and candidate hashes; default source lists remain separate.
The current-image [application source review](../build/capacity-admission-health-hardware-executor-prep-v1/application-runner-source-review.json)
and [runner review](../build/capacity-admission-health-hardware-executor-prep-v1/application-runner-runner-review.json)
bind 35 code and 180 static inputs and preserve the serial one-position,
repeat-position and greedy32 TinyStories phases. Device-free preflight waits
for route, detailed audit, accepted image and concrete trial admission. The
initial controls-script hash mismatch and its failed review remain preserved;
the corrected binding passes fresh independent review. No new programming or
application execution is claimed by this preparation.

The next [service admission candidate](../build/capacity-service-admission-cofactor-candidate-v1/CONTRACT.json)
adds a separate owner output for the actual service composition; the original
free-input admission, fault priority and registered updates remain unchanged.
Its [binary composition review](../build/capacity-service-admission-cofactor-review-v1/composition-review.json)
proves the reachable ownership invariant, the actual BIST reset-to-done
implication and equality of the two admission outputs under that composition.
Two faulty or unqualified controls are rejected. The
[fresh native review](../build/capacity-service-admission-cofactor-native-v5/results-review.json)
accepts sixteen service runs and four owner comparisons in Icarus and Verilator,
with assertions enabled in the integrated candidate. The matched service fixture
holds `other_diagnostic_pending=0`; broader parent scenarios remain separate.
The [fresh saved-image replay review](../build/capacity-service-admission-native-image-replay-v2/results-review.json)
additionally binds all twenty executed images, six tools and fresh logs with
unchanged before/after hashes. These are component results, not full-parent
or FPGA qualification. The first matched mapping run fails after baseline
synthesis because its audit expects a redundant owner reset-output alias to
remain connected. The corrected audit verifies the canonical BIST reset
and exclusivity condition, including the actual selected reset/ownership LUT
and the unused folded input in both variants. The original third mapping
producer remains failed because its Python input census includes `clk` while
the Tcl fanin table excludes it. A separate
[saved-artifact review](../build/capacity-service-admission-cofactor-mapped-v3-results-audit-v1/results-review.json)
accepts the unchanged mapped outputs after correcting that clock classification:
32→0 read-data admission dependencies, 1,999 FFs/66 owner FFs unchanged and
2,718→2,719 LUTs. It claims no rerun, routed timing or image acceptance.
Both fresh full-model source selections change only
project indices 53/56, matching full-design orders 154/157; the other eighty
project sources and all model assets retain their bytes.

Earlier source-bound timing milestones follow. The private FI staging-enable, snapshot-capture
and parent-abort/seal-factor candidate passes component native and independent
mapped-artifact reviews; the FI mapping producer's final parser failure remains
preserved. Its [fresh 201-input synthesis review](../build/control-timing-next-physical-synth-results-review-v1/review.json)
accepts 293,537 LUTs, 89,793 FFs, all 512 products/516 DSPs, both MIGs, PCIe
and USER2/UI plus USER3/SYS. The initial next-candidate strict and placement V1
attempts are invalid for this source: [strict V1 was retracted for wrong
checkpoint ancestry](../build/control-timing-next-strict-results-review-v1/retraction-wrong-ancestor-v2.json),
and [placement V1 failed the same ancestor check](../build/control-timing-next-placement-results-review-v1/review.json).
The corrected [strict V2 review](../build/control-timing-next-strict-results-review-v2/review.json)
binds the fresh retained-constant checkpoint `004cb49f`, local apply Tcl and
fresh witness. It passes 35 pre/post constant proofs, three protected grounds
and clock/DRC structural checks across 28 artifacts; it establishes no routed
timing result. The [guarded placement V2 review](../build/control-timing-next-placement-results-review-v2/review.json)
verifies strict V2 DCP `6e4bf67a` and structural gates. Unrouted setup remains
−4.005 ns/TNS −15,097.838 ns across 10,809 endpoints; hold is −0.677 ns.
Routing, image and hardware acceptance remain pending. The older −4.352 ns result below belongs
to the prior combined-source snapshot, not this four-overlay candidate.

The next candidate's separate model suites pass: the [warm reset
review](../build/control-timing-next-warm-results-review-v1/review.json)
checks 16 jobs, 12 compute resets, one SYS reset and 1,441,792 complete BO
bytes before ACK using ordinary RAM and actual vendor CTRL/FI leaves. The
[actual-controller review](../build/control-timing-next-controller-results-review-v1/review.json)
checks 12 cases, seven successful SYS resets, six complete BO images/532,480
bytes and 32,768 BIST writes/reads in a one-MiB model through the legacy
wrapper and encoded-PHY model. These do not qualify physical dual-host
MIG/PHY or a new image. The [serial public regression review](../build/shared-frame-sequence-public-regression-v2-results-review/review.json)
passes the full default suite for its recorded source snapshot. Its Icarus
async SUB(9) case produced all 1,600 expected lines under the unchanged
600-second deadline; the parallel timeout remains preserved beside the
[isolated same-case pass](../build/shared-frame-sequence-icarus-isolated-rerun-v1/run-v1/report.json).
These are host/source results, not hardware qualification. Earlier physical
results remain bound to source tag `60e7abbb` and bitstream `1ca5ae19`.

The next two control rewrites pass component simulation and isolated mapped
review. The [FI action-enable review](../build/fi-command-actions-local-enable-mapped-results-review-v1/review.json)
checks all 96 metadata flops: unrelated CLAIM fanin is absent and original
permission/reset controls remain. The original OOC producer remains failed
on its total-FF equality assumption; actual FFs decrease 1,587→1,585 and the
saved artifacts are reviewed independently without claiming a cause for that
optimizer-level difference. The [compute-health cofactor
review](../build/fi-claim-compute-health-cofactor-mapped-results-review-v1/review.json)
checks removal of the combinational health path only from the projected quiet
cone, retaining the original ready/full-quiet dependencies and 319 FFs. Its
equivalence applies under the reviewed known-health claim premise. The
[fresh 201-input synthesis review](../build/control-timing-fi-claim-next-physical-synth-results-review-v1/review.json)
passes at 293,506 LUTs/89,793 FFs with four changed HDL files relative to the
preceding source snapshot. All 512 products/516 DSPs, both MIGs, PCIe and
USER2/UI plus USER3/SYS remain retained. Fresh
[constant-retention](../build/control-timing-fi-claim-post-synth-retention-results-review-v1/review.json)
and [crossing-inventory](../build/control-timing-fi-claim-post-synth-inventory-results-review-v1/review.json)
reviews pass, binding the actual new SYNTH/OPT checkpoints and original
35 constant proofs, three grounds and retained register inventories.
The [strict constrained review](../build/control-timing-fi-claim-strict-results-review-v1/review.json)
passes all 28 artifacts, 35 pre/post constant proofs, three grounds and the
original clock/reset/crossing/DRC checks. Both fresh full-parent models pass
independent review: the [warm replay](../build/control-timing-fi-claim-warm-results-review-v1/review.json)
checks 16 jobs, 12 compute resets, one SYS reset and 1,441,792 complete BO
bytes; the [actual-controller suite](../build/control-timing-fi-claim-controller-results-review-v1/review.json)
checks all twelve original cases and 32,768 BIST writes/reads in its one-MiB
encoded-PHY model. Their [82 project sources match the physical selection](../build/control-timing-fi-claim-model-physical-crosswalk-v1/review.json).
The [fresh placement review](../build/control-timing-fi-claim-placement-results-review-v1/review.json)
passes its 22 structural artifacts and actual strict-checkpoint binding.
Unrouted setup improves from −4.005 ns to −2.951 ns, but still fails across
8,241 endpoints/TNS −8,247.126 ns; hold is −0.805 ns. The worst setup path
runs from the C1 MIG control decode through transport-release readiness to
the frontend lease-epoch enables. The [fresh raw route review](../build/control-timing-fi-claim-route-results-review-v1/review.json)
verifies the actual `69f4d43f` parent and all 450,547 routable nets with zero
routing errors. Setup still fails at −2.597 ns/TNS −7,344.686 ns across
7,961 endpoints; raw hold is +0.013 ns. The run stops before cleanup/final
acceptance because the original 65-register startup inventory fails. The
[read-only comparison](../build/fi-claim-route-startup-inventory-v1/review.json)
finds the added `u_mailbox/startup/rst_n_reg_replica`; the gate remains failed.
The worst routed path reaches bank-0 command-address enables through memory
readiness. No bitstream or hardware acceptance follows.

The separate [host-accept cofactor native review](../build/fabric-host-accept-cofactor-native-v3-results-review-v1/review.json)
passes all original 21 Icarus/19 Verilator cases, all 50 shared outputs,
44 sequential state fields and eight four-state/four binary directed cases.
Earlier harness elaboration failures remain preserved. Its
[matched mapping review](../build/fabric-host-accept-cofactor-mapped-results-review-v1/review.json)
checks removal of the `job_begin` path only from projected READY, retaining
original READY, health/fault and five owning-state controls. Both designs
have 1,111 FFs; LUTs are 2,298/2,335. The projection is equivalent in
`host_valid && READY`; parent `260936a4` remains uncompiled by these component
tests. It was not selected by that failed route.

The next source combines host acceptance with the
[transport-release cofactor](../build/transport-ready-health-cofactor-native-v3-results-review-v1/review.json)
and [descriptor local enables](../build/job-descriptor-local-enable-mapped-results-review-v1/review.json).
Transport tests cover the original production/timeout128 reset fixtures and
all 256 four-state/16 binary algebra tuples. The descriptor pair compares all
13 outputs and 22 state fields; isolated mapping removes both readiness
inputs from all 99 descriptor storage bits while preserving SUBMIT controls.
The [201-input source review](../build/control-repair-three-fix-physical-source-review-v1/review.json)
checks exactly three replacement modules and 198 unchanged inputs, plus the
actual 195-HDL/two-XDC/XDMA-component read closure. The
[fresh synthesis review](../build/three-control-fixes-synth-results-review-v1/review.json)
passes at 293,520 LUTs/89,793 FFs with all 512 products/516 DSPs, both MIGs,
PCIe and both JTAG chains retained. The
[strict review](../build/three-control-fixes-strict-results-review-v1/review.json)
passes all 30 artifacts, including 35 pre/post constant proofs and the exact
130 startup protections before and after optimization; both original
65-register checks remain unchanged. The
[fresh warm review](../build/three-control-fixes-warm-results-review-v1/review.json)
passes 16 jobs, 12 compute resets, one SYS reset and 1,441,792 complete BO
bytes before ACK. The [controller review](../build/three-control-fixes-controller-results-review-v1/review.json)
passes all twelve original cases, seven SYS success markers, 532,480 complete
BO bytes and 32,768 BIST writes/reads. Its initial relative fixture-path failure
is preserved; the successful execution-only retry keeps the original executable,
V4 validators, case order and deadlines. The
[placement review](../build/three-control-fixes-placement-results-review-v1/review.json)
passes structural checks but retains negative unrouted setup −2.257 ns/TNS
−9,544.823 ns across 9,360 endpoints and hold −0.392 ns. The worst path reaches
FI ownership through reset readiness and request qualification. New routed
timing, image and hardware acceptance remain pending.

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
| Injected ECC/quarantine/recovery | Six full-parent actual-controller cases and six raw RKFI management cases passed independent native review | [Full-parent review](../build/full512-fi-parent-controller-model-v1/root-result-review.json): original K65/SUB9, CE/UE plus raw-job recovery, early ownership and capacity BIST; management/physical-wrapper integration, implementation and physical ECC remain pending |
| Retained whole-transaction reset control | Standalone SYS controller passed both simulators and full default regression | [Control contract](WHOLE_RESET_CONTROL.md), [independent component review](../build/whole-reset-control-root-review-v1/v4-final-review.json), [full regression review](../build/whole-reset-full-regression-v1/independent-review.json): 369 Icarus/329 Verilator checks and eight invalid-parameter controls; `make -j2 test` passed in 574.557 seconds. Retained mailbox, fresh UI witnesses, actual parent/board integration and physical recovery remain pending |
| Joined retained reset and actual-controller ECC | Passed all twelve native scenarios and independent/root review | [V4 root acceptance](../build/whole-reset-terminal-format-results-review-v4/root-acceptance.json): one fresh actual-controller/encoded-PHY executable, coordinator precheck, seven successful SYS resets, CE/UE quarantine/recovery, capacity BIST, held results, cancellation, sealed requests and late-response drainage. Six complete numerical BO images total 532,480 bytes before ACK; all source/binary hashes and process cleanup pass. V3 marker failure is preserved; V4 keeps the original assertions/validators. The [published 72-source core](../rtl/ddr/maintenance_fi/README.md), commit `80f755c`, is byte-identical to the native project selection. Model limits are one MiB/four tasks; physical wrappers, retained mailboxes, CDC/RDC, implementation and FPGA ECC/warm recovery remain pending |
| Live framework integration | All eleven selected EW cases passed physical review | [Complete native trial review](../build/fpga-bringup/full512-ddr-framework-prep-v1/root-result-review.json) on the qualified TinyStories DDR image: 11 jobs, 16 tasks, 1,081,344 BO bytes before ACK; CMAC, broader census and the new capacity image remain separate |
| Compiler CMAC layouts | Standalone raw-command encoder/DMA passed both native simulators | [Contract and test target](LAYOUT_DMA.md), [independent review](../build/backend-layout-root-review-v1/report.json): all 18 captured gathers/16,897 indices, all 65,536 raw halfwords, 34 positive cases twice per simulator, 51 Icarus/50 Verilator negatives; parent/runtime/reset and physical integration remain pending |
| Joined compiler-layout/CMAC parent | Six raw pipelines passed independent numerical/whole-BO review | [Seven-scenario review](../build/framework-layout-parent-replay-v6/root-result-review.json): all 24 stages, 3,358,720 pipeline BO bytes and 122,880 baseline bytes, exact engine read/write counts and original modeled capacity/reset controls; independent AXI RAM/ECC-control model only, with compute-reset/runtime/real-controller/physical qualification pending |
| PCIe plus JTAG system profile | Fresh UI-health source fully routed; setup and DRC acceptance failed | The [independent route review](../build/pcie-ui-health-route-results-review-v1/review.json) verifies 438,776/438,776 routed nets with zero routing errors after the 1,772-second Vivado run. Setup −0.885 ns/TNS −903.611 ns across 2,734 endpoints fails; global hold +0.012 ns passes. The worst path runs from actual C1 MIG control decode through monitor/fabric health into compute-reset control. The RTSTAT-10 warning on 23 unloaded XDMA nets is corrected only on the separately reviewed diagnostic checkpoint below, without adding a waiver. The [strict constrained-source review](../build/pcie-ui-health-constrained-opt-results-review-v2/review.json) and [same-source unused-LUT-input ECO review](../build/pcie-ui-health-lut-cleanup-review-v4/review.json) retain exact clocks, reset/electrical checks and all 512 products/both MIGs. No bitstream or physical PCIe acceptance follows. Detailed routed payload/skew/reset/crossing audits remain open |
| Shared FP48 arithmetic resource candidate | Component tests, resource census and fresh six-shape numerical review passed | The [explicit public source profile](../rtl/ddr/dual_host_shared_cacc/README.md) uses two unchanged donor FP48 pipelines to serve sixteen independent accumulation contexts, with all 512 parallel product lanes retained. The [CACC component review](../build/cacc-context-shared2-review-v1/review.json) and [word-bank front review](../build/cmac-front-word-banks-review-v1/review.json) preserve the original numerical, reset, cancel, hold and error contracts. The [fresh root numerical acceptance](../build/dual-host-shared2-wordbanks-results-review-v1/root-acceptance.json) covers six independent modeled JTAG-to-retained-PCIe runs: 48 jobs/tasks, 36 resets, 4,751,360 complete BO bytes before ACK, 75,008 READ64 and zero PCIe uploads. The exact 96-warning inventory is reviewed. No actual converter, MIG/PHY or FPGA result follows from that numerical model; no accepted FPGA image uses either optimization yet |
| Retained USER2/UI and USER3/SYS mailboxes | Published component passes both native simulators; board integration pending | [Source and test contract](../tests/host/retained_mailbox/README.md), `make host-retained-mailbox-test`: 55 checks per simulator, exact 65-edge startup in both domains, a normal frame retained before and across client reset/UI clock stop, SYS controller identity read without UI edges, correlated sealed-frame denial and one fresh command afterward. The backend is an explicit protocol fixture; no reset request, MIG, BSCANE2 or physical recovery is exercised. The published component has no runtime reset input; frontend admission/drain and physical FI wrapper integration remain required |
| Retained SYS/dual-host/FI physical source integration | Full RTL elaboration and independent source/wiring review passed | The [195-HDL candidate](../build/whole-reset-fi-pcie-physical-source-candidate-v1/CONTRACT.md) connects the actual combined framework/FI backend, retained frontend, SYS controller and five instrumented MIG overlays. The [unmapped result review](../build/whole-reset-fi-pcie-physical-elab-review-v2/review.json) verifies 277 scalar ports, distinct USER2/UI and USER3/SYS mailboxes, 16 C32 kernels/two CACC donors, both 64-bit-payload/72-DQ MIGs with payload ECC_TEST OFF, C1-only CTRL FI permission and all 129 C1 witness bits connected to the logical c0 backend. Clock/configuration-power sources and coordinated PCIe epochs are checked. One explicit XDMA interface stub remains; actual IP binding, joined native transport/reset execution, mapped reset/CDC, route/DRC/timing and physical recovery are unqualified |
| Published dual-host maintenance/FI profile and joined warm replay | Byte-identical 82-source profile published; fresh model/wire recovery passed | The [opt-in source profile](../rtl/ddr/dual_host_maintenance_fi/README.md), commit `830cd93`, keeps FP16 C32/K16/all512 products and the full framework/FI/SYS/frontend union. Its [fresh independent warm review](../build/joined-dual-host-warm-results-review-v3/review.json) accepts 16 jobs, 12 compute resets, one SYS reset and 1,441,792 complete BO bytes before ACK through JTAG and retained PCIe packet paths, with stopped-UI SYS access, an idle held owner, exact 16,384-line reinitialization and stale-lease denial after ACK before owner interpretation. Nine wire-auditor negative controls pass. The first failed test waited for denial before releasing the sealed barrier; the corrected concurrent sender/SYS-ACK sequence follows the original gate contract and changes no DUT/error expectations. This is a one-MiB/four-task ordinary-RAM fixture with actual CTRL/FI leaves; no actual PCIe IP, TAP, MC/PHY, physical ECC, or new-image inference proof |
| Published timeout classification and fresh joined warm replay | Same 82-source profile updated by exactly two RTL files; independent fresh wire/BO audit passed | The [publication crosswalk](../build/maintenance-timeout-publication-v1/crosswalk.json) binds every public source to the new native project selection. Internal classification replaces only two code8 predicates, retaining diagnostics/priority/latency and the C32/K16 contract. The [fresh paired review](../build/whole-reset-fi-timeout-tag-native-review-v1/review.json) and [fresh warm trace review](../build/whole-reset-fi-timeout-tag-joined-results-review-v1/review.json) pass: 16 jobs, 12 compute resets, one SYS reset, 1,441,792 whole-BO bytes before ACK. The actual simulator exits 0; its producer remains failed after a post-run missing `re` import, preserved with separate independent artifact acceptance. This one-MiB/four-task ordinary-RAM/actual-CTRL-FI fixture does not qualify PCIe IP, MC/PHY, physical ECC, new-image inference or RK equivalence; full physical synthesis remains separate |
| Full retained SYS/FI physical implementation | Fresh synthesis, strict constrained structure and placement diagnostics passed; timing remains open | The [195-HDL/201-input synthesis review](../build/whole-reset-fi-timeout-tag-physical-fit-results-review-v1/review.json) accepts 293,733 LUTs/89,799 FFs/516 DSPs, both USER2/USER3 and both MIGs. The [actual mapped inventory](../build/physical-retained-mapped-inventory-results-review-v1/review.json), [retained constants](../build/physical-timeout-tag-constant-retention-results-review-v1/review.json) and [strict constrained review](../build/physical-retained-strict-constrained-results-review-v1/review.json) check five new level crossings, nine release registers, both 65-register configuration startups, 37 readiness and 64 PCIe functional reset endpoints, all 35 original constant proofs, exact clock/DRC/electrical gates and no waivers. [Placement](../build/physical-retained-placement-results-review-v1/review.json) retains those inventories at 287,975 LUTs/89,869 FFs; unrouted setup −4.989 ns/TNS −20,682.686 ns across 12,060 endpoints and hold −0.781 ns remain unaccepted. The worst setup path reaches FI staged-payload CE through 33 logic levels; targeted control fixes need their own qualification before another full build |
| Targeted control-enable timing work | Four published fixes pass paired native, isolated mapping, combined warm, full-synthesis and strict structural review | The layout [native](../build/layout-metadata-enable-native-results-review-v2/review.json) and [mapping](../build/layout-metadata-enable-mapped-results-review-v2/review.json) reviews preserve all original cases and remove request-ready fan-in from all 160 metadata CEs with 450 FFs unchanged. The direct pending-fault factor passes [paired four-state/native](../build/fault-pending-parallel-native-results-review-v2/review.json) and [mapping](../build/fault-pending-parallel-mapped-results-review-v2/review.json) reviews. The selected zero-latency FI word-local payload enable passes [all-cycle paired comparison](../build/fi-payload-enable-native-results-review-v2/review.json) and [mapping](../build/fi-payload-enable-mapped-results-review-v2/review.json): all 512 payload FFs lose CLAIM fan-in while retaining permission controls. It supersedes the deferred one-edge payload-staging alternative. The result-metadata candidate passes [paired native review](../build/control-result-metadata-native-results-review-v3/review.json); its [saved OOC artifact audit](../build/control-result-metadata-mapped-results-review-v1/review.json) verifies all 64 metadata CEs lose error/done fan-in, with 286 FFs unchanged. That OOC producer failed final JSON serialization; its original report remains unchanged. The [combined source review](../build/control-timing-combined-physical-fit-source-review-v1/recheck-v2.json) binds exactly four changed HDL files and 197 unchanged inputs; the [fresh full-synthesis review](../build/control-timing-combined-synth-results-review-v1/review.json) accepts 293,399 LUTs, 89,797 FFs, all 512 product/516 total DSPs, both MIGs, PCIe, both JTAG chains and 277 ports. The [fresh combined warm review](../build/control-timing-combined-warm-results-review-v1/review.json) accepts 16 jobs, 12 compute resets, one SYS reset and 1,441,792 whole-BO bytes before ACK, using ordinary RAM and actual vendor CTRL/FI leaves. The first wire-auditor call used a raw-only fixture missing its goldens; that failure is preserved, and the successful independent audit uses the original hash-bound golden fixture. The [new mapped inventory](../build/control-timing-combined-mapped-inventory-results-review-v1/review.json) preserves all required retained reset/crossing registers. The [fresh strict constrained review](../build/control-timing-combined-strict-results-review-v1/review.json) passes all 35 pre/post constant proofs, exact three protected grounds and retained clock/reset/electrical/DRC gates. The [fresh actual-controller model review](../build/control-timing-combined-controller-results-review-v1/review.json) passes all twelve original scenarios, seven SYS resets, six complete BO images/532,480 bytes and 32,768 BIST writes/reads over one MiB; it uses the legacy test wrapper and encoded PHY. The [fresh placement review](../build/control-timing-combined-placement-results-review-v1/review.json) passes structural gates while retaining negative unrouted setup −4.352 ns/TNS −12,175.012 ns across 8,844 endpoints and hold −0.392 ns. The [read-only 1,000-path diagnosis](../build/control-timing-combined-placement-timing-diagnostic-v2/run-v1/report.json) identifies remaining common CTRL-to-control-enable paths; the 33-level worst path now ends at FI staged-address CE. Further timing corrections need their own native/mapped qualification; this source is not routed or accepted as an image. Physical dual-host MC/PHY, image and hardware qualification remain open. The four selected files and all consuming profile integrity bindings are published locally; current source and historical physical-image evidence remain separate |
| Joined framework/FI core, admission and reset occupancy | All twelve fresh actual-controller model cases and component checks passed independent review | The [full12 review](../build/framework-fi-converged-full12-results-review-v1/review.json) binds one fresh executable, unchanged original marker/whole-BO validators, all twelve numerical/ECC/reset scenarios and closed process groups. The actual-controller/encoded-PHY model is bounded to one MiB/four tasks; positive RKLY/RKRS coverage and the newer dual-host/physical wrapper remain separate. The [focused review](../build/framework-fi-converged-focused-review-v1/review.json) also accepts three-bank descriptor/SUBMIT denial with held-result reads/ACKs, and both production/timeout reset fixtures with health-independent maintenance quiet and three fresh UI edges. This does not qualify FPGA ECC/warm recovery |
| Measured health/fault and owner timing corrections | Three private Boolean changes passed source/native and isolated mapping review; fresh full synthesis passed | The [paired monitor/fabric review](../build/health-fault-parallel-native-results-review-v1/review.json) retains original numerical/protocol/four-state guards and compares all outputs. The [owner comparison](../build/owner-payload-zero-native-review-v1/review.json) retains 259 checks and X/Z selector/payload rejection. Identical isolated queries show monitor [6→5 levels, 3.312→2.965 ns](../build/health-fault-parallel-mapped-review-v1/review.json), fabric [2.348→2.300 ns](../build/fabric-fault-parallel-mapped-review-v1/review.json), and owner [19→8 levels, 4.059→3.422 ns](../build/owner-payload-zero-mapped-review-v1/review.json), without new registers or latency. These estimates cannot be added into a full-design timing claim. The [reviewed 190-record source selection](../build/pcie-health-fault-owner-synth-source-review-v1/review.json) changes exactly monitor, fabric and ordinary owner versus the UI-health base. The [fresh terminal synthesis review](../build/pcie-health-fault-owner-synth-results-review-v1/review.json) verifies 288,160 LUTs, 82,973 FFs, 512 product/516 total DSPs, both MIGs, PCIe and USER2, with uncapped RAM/high/swap. The subsequent [strict constrained audit](../build/pcie-health-fault-owner-constrained-opt-prep-v1/run-v1/report.json) stopped at an EW constant-field witness: optimization removed the inspected boundary connections. Disconnected pins are not accepted as constant zero. The [corrected strict constrained stage](../build/three-fix-retained-constrained-results-review-v3/review.json) now passes all 35 constant proofs, exact three retained grounds, full retention/electrical/clock and reset/CDC structure checks. Fresh placement passes its guards; the following raw routed diagnostic still fails setup at −0.426 ns/TNS −89.576 ns across 619 endpoints (hold +0.012 ns), with the worst path through fault-code encoding/selection into a job result register. Net-only cleanup then exposes four dangling O5 buffer warnings and stops; no new image is accepted. The subsequent [bounded net/four-buffer cleanup](../build/three-fix-dead-lut-cleanup-results-review-v1/review.json) now passes independent diagnostic review: exactly 23 unloaded nets/four unused LUT1 buffers removed, 438,940/438,940 nets fully routed with zero errors, original 2,066 default DRC warnings and no RTSTAT/PDRC findings. Other cells, input load sets, non-target nets and IO are unchanged; setup −0.426 ns and hold +0.012 ns remain unchanged. The next exact code8 classification candidate passes paired native and isolated mapping review. Its [fresh ordinary-profile synthesis review](../build/fault-timeout-tag-full-fit-results-review-v2/review.json) accepts 288,138 LUTs, 82,981 FFs, all 512 products and both MIGs; [strict constrained review](../build/timeout-tag-strict-constrained-results-review-v1/review.json) passes the original 35 proofs/three grounds and structural gates. The [fresh placement](../build/timeout-tag-placement-results-review-v1/review.json) passes structural checks with negative unrouted estimates. The [new route review](../build/timeout-tag-route-results-review-v1/review.json) records all 438,891 nets fully routed and zero routing errors; the reviewed 23-net/four-buffer cleanup preserves setup −0.828 ns, TNS −1,206.249 ns/3,418 endpoints and hold +0.014 ns, with exact inherited DRC and no RTSTAT/PDRC. The producer remains failed on its strict setup gate. Worst paths now pass through pending-fault classification into job result enables; no timing/image acceptance follows |
| Unloaded XDMA route-net cleanup | Guarded net-only ECO passed independent diagnostic review | The [result review](../build/pcie-dead-net-cleanup-results-review-v2/review.json) verifies removal of exactly 23 driver-only nets (eleven scalars/four complete three-bit buses), with cells/placement/IO/other-net protection unchanged. All 438,776 routable nets remain fully routed with zero errors; exact inherited default DRC warnings remain 2,066 and RTSTAT-10 is gone. Setup −0.885 ns and hold +0.012 ns are unchanged. This modifies only the preserved older failed-timing checkpoint; it neither qualifies a new image nor transfers cleanup to changed sources without fresh target revalidation |
| PCIe BAR-path raw-frame mailbox | Standalone component and callback client passed | [Component contract](PCIE_FRAME_MAILBOX.md), `make host-frame-mailbox-test` (also in default `make test`): 1,151 Icarus/1,142 Verilator checks plus eighteen normal/optimized-Python callback controls; full raw framing, staging, backpressure, response observation and sticky faults. PCIe IP, CDC, cross-transport ownership and physical execution remain pending |
| Shared raw-frame ownership mux and client | Same-clock component and callback client passed | [Ownership contract](RAW_FRAME_OWNERSHIP.md), `make host-frame-owner-test`: 259 checks per simulator for session acquire/release, exact response routing, nonowner denial, quiescence, link loss and sticky faults, plus 24 callback controls under normal/optimized Python; actual backend integration, CDC/PCIe and hardware remain pending |
| PCIe/JTAG packet frontend composition | Same-clock packet path passed both simulators | `make host-frame-frontend-test`: 2,090 checks per simulator through real AXI-Lite packet staging and independent JTAG frames; packet ACK/session distinction, nonowner reset/ACK denial and in-flight link-loss quarantine. Backend is scripted; NPU/CDC/PCIe-IP integration remains pending |
| Backend transport-release witness | Witness-only controller tests passed both simulators | [Witness contract](DUAL_HOST_BACKEND.md): actual descriptor-valid bits plus all pending control/memory/reset state; 105 native checks per simulator with all original controller outputs compared cycle by cycle. The current 72-source same-clock NPU/frontend wrapper lints with inherited diagnostics plus a recorded retained-reset sync/async-use diagnostic; The witness-only component does not qualify numerical integration; the current NPU replay is listed below. CDC and physical integration remain pending |
| Shared frontend plus actual NPU | Current 72-source healthy-link EW replay passed independent native review | [Current admission/epoch review](../build/dual-host-npu-public-admission-v3/root-result-review.json): two jobs/four tasks, 204,800 complete BO bytes before job ACK and 3,203 modeled AXI reads; retained-BO JTAG-to-PCIe handoff. Epoch/admission faults have separate 2,090-check frontend and 83 Icarus/71 Verilator mailbox-admission suites. Earlier pre-guard sources remain archived. Actual MIG/PHY, broader CMAC/reset coverage, PCIe IP/CDC and hardware remain pending; the first CMAC/reset shape is listed below |
| CMAC/layout/reset through both frontends | All six shapes passed independent native review | [Root acceptance](../build/dual-host-cmac-six-shape-independent-review-v3/root-acceptance.json): six fresh JTAG-to-retained-PCIe processes, 48 jobs/tasks, 36 compute resets, 48 complete BO images/4,751,360 bytes before ACK and 75,008 READ64s. Actual raw programs, full strobes, zero-data lease writes, ownership and bounded stalls are audited; all 94 inherited diagnostics remain visible with zero normalized semantic delta. This is the public 72-source numerical model profile, with no continuous twelve-epoch, PCIe-IP/CDC, MIG/PHY or FPGA qualification |
| Actual AMD AXI-Lite converter plus reset component | Both native simulators passed the optional public controls | [Public target/contract](../tests/host/actual_converter/README.md), [source-bound result](../build/pcie-public-actual-converter-v3/report.json): Verilator and four-state XSim agree on 419 checks/five epochs, ten channel totals and seven retained write effects, including partial transactions and stopped-clock joint resets. Master and slave are coordinated test fixtures; actual XDMA, NPU crossing, link/clock-loss and physical CDC remain pending |
| Selected PCIe crossing wrapper | Corrected local-reset source passed fresh Verilator and XSim review | The [reset integration review](../build/pcie-local-reset-integration-results-review-v1/review.json) accepts 419 checks, five epochs and seven write effects per simulator after replacing only the bridge reset leaf. Wrapper signals, bench, error expectations and deadlines remain unchanged. The new source synchronizes raw SYS-epoch release separately into each clock domain before functional state leaves reset. Mapped recovery/removal, CDC/RDC, routing and hardware remain separate gates |
| Joined PCIe control plane and retained frontend | Corrected reset passed both simulators at both source clocks | The [fresh integration review](../build/pcie-local-reset-integration-results-review-v1/review.json) accepts all four V20 runs: each has 2,685 checks/eight scenarios, six common epochs, twelve backend accepts and eleven replies. The actual converter/XPM and frontend are exercised with an XDMA fixture and scripted backend. Source hashes remain stable, groups close, and vendor warnings stay visible with no authored warnings. This does not qualify actual XDMA link behavior, numerical execution through the converter, physical CDC or FPGA operation |
| PCIe source health and unsupported DMA termination | UI-only health publication passed fresh component and joined native review | [Fresh native review](../build/pcie-health-ui-qualified-native-results-review-v1/review.json): four clock ratios per simulator, 43 Icarus/34 Verilator health checks per ratio, ten expected invalid-parameter failures, unchanged 956/904 DMA checks, and four actual-converter guard runs at 2,685 checks/eight cases. Joint reset still asserts the local reset asynchronously and releases after fresh UI edges; the published level uses UI-qualified terms. Benches, errors and deadlines remain unchanged. New-source physical CDC, timing and execution retain separate gates |
| Framework transport over raw frame sessions | Callback controls passed | `make ddr-frame-transport-controls`: twelve controls under normal/optimized Python for inherited BO/job/reset methods on an acquired RKHO session; no TAP emulation or endpoint discovery. Actual framework/RTL and physical qualification through this entry remain pending |
| Joined compute-reset parent | All six pipelines and baseline passed independent native review | [Reset/retention review](../build/framework-reset-parent-model-v3/root-result-review.json): 18 actual resets, 24 stages, 50 complete BO images/6,615,040 bytes; dirty state cleared, held-result admission blocked, retained DDR controls sampled on UI edges and no model reinitialization writes; runtime/real-controller/FPGA gates remain pending |
| Actual vendor-controller raw framework pipeline | Functional replay passed with provenance limits | [Independent review](../build/framework-controller-sv-replay-v1/root-controller-review.json): original older-reset profile, real controller/UI/MC/control RTL plus encoded-PHY model; four raw pipeline stages and three resets, eight exact BO images/1,019,904 bytes. Five job images precede job ACK; three retention images follow reset ACK. Exact executable and 407 inputs are bound; Make version, generated-driver prebinding and historical group closure were not recorded. This does not qualify the new reset RTL, interactive Tensor runtime, physical training or FPGA |
| RK numerical/shape differential | Pending | Actual RK outputs remain required for compatibility claims |
| Selected framework CMAC/layout/reset on FPGA | All six physical cases passed independent review | [Physical report](FRAMEWORK_MATMUL_FPGA_TEST.md): one volatile source-tag `60e7abbb` load, 24 jobs/18 hardware layouts/six CMAC, 18 actual compute resets with epochs 0→18, 2,375,680 complete BO bytes before ACK and 164,550 JTAG scans. Original compiler/writer and no-CPU-fallback guards retained; all owned groups close before shared-lease release. Entire backend, PCIe, physical ECC, full capacity and full-model qualification on this image remain separate |
| TinyStories trained tile on current image | Physical compaction/rearm smoke passed independent and root review | [Root acceptance](../build/framework-factored-trained-physical-review-v1/root-acceptance.json): source tag `60e7abbb`, BOS Wq0 first 32 outputs, two CMAC plus two FPGA EW jobs/six tasks, 360,448 complete BO bytes before ACK and 25,945 trained scans. Separate six-line/two-order scratch check passes; target, image and cleanup reviewed. The full32 run on this exact image is accepted separately below |
| TinyStories full32 on current image | One-prompt, 32-position hybrid workload passed root and independent physical review | [Full32 evidence](FRAMEWORK_TINYSTORIES_FPGA_TEST.md): exact source tag `60e7abbb` / bitstream SHA `1ca5ae19…`; all 1,152 FPGA projections and 16,384 logits match the donor oracle, with 28 greedy IDs/text exact. Three phases use one audited volatile load: 7,888 jobs, 11,832 tasks, 32,309,248 complete BO bytes before ACK and 3,290,235 scans. CPU host operators are explicit; no dense CPU fallback or runtime layout repair. Full capacity, ECC injection/recovery and warm reset, PCIe, cold boot, flash and RK equivalence remain separate; receipts are workspace-local |
| Ordinary framework CMAC runtime | All six public-source shapes passed independent native wire/whole-BO review | [Current public profile](../build/framework-public-runtime-coverage-v1/root-result-review.json): 24 jobs, 18 layouts, six unchanged-writer CMAC submissions, 18 resets, 328,587 commands and 2,375,680 BO bytes before ACK; no host tensor/scratch reloads after launch; actual controller and FPGA remain separate |
| Published framework source/profile | Published 68-source ordered selection and explicit runtime/transport entry | [Profile contract](FRAMEWORK_FULL_PROFILE.md): 18 byte-identical RTL variants, 50 reused paths, ten runtime/twenty transport/five source controls; frozen V22 `make test` passed in 1,384.307 seconds; the live runner/test delta has separate [source reconciliation](../build/production-model-auditors/current-v22/current-source-reconciliation.json), with the outer drift failure preserved |
| Framework implementation preparation | Fresh 169-HDL/178-input source closure and nine new reset-level CDC chains prepared | [Source candidate](../build/framework-vivado-prep-v2/preparation.json), [source-only constraint audit](../build/framework-compute-constraint-source-audit-v1/NOTES.md); first launched synthesis hit its 8-GiB aggregate cap and was [OOM-rejected](../build/framework-vivado-run-v2/oom-review.json). The [uncapped retry](../build/framework-vivado-run-v4-uncapped/report.json) follows the user's removal of RAM/swap limits and the former fixed memory-headroom gate; no new mapped/route/image qualification |
| Framework source synthesis/optimization | Mapped review passed; initial route failed setup and corrective run was stopped | [Accepted synthesis](../build/framework-vivado-run-v5-mapped-audit/root-synth-review.json): 297,436 LUTs, 512 product/516 total DSPs, 16 kernels, 242 IOs; nine three-stage reset chains and reset consumers confined to compute. Eighteen estimated hold paths remain pending physical implementation. The [initial route](../build/framework-route-run-v1/report.json) reached setup -1.964 ns before correction. Its [superseded corrective run was stopped](../build/framework-route-run-v1/root-correction-stop.json) after reset-path diagnosis; the routed checkpoint and all input bindings are preserved, with all owned groups closed. No route/image/physical acceptance |
| Local CORE reset-release timing candidate | Numerical and mapped reviews passed; fresh route failed functional UI setup | [Numerical review](../build/framework-reset-local-release-parent-v2/root-result-review.json): seven fresh scenarios, 18 resets, 50 complete BO captures/6,615,040 bytes; wrapper fixture-path failure preserved. [Mapped review](../build/framework-local-release-mapped-audit-v3/root-synth-review.json): 297,505 LUTs, 512 product/516 total DSPs, 242 IOs, 30 sync FFs, all 40 later-stage paths timed, eight compute and eight retained-reset boundaries verified; 20 estimated hold paths await routing. Same fresh RTL/checkpoint was re-audited after correcting overly broad fanout checks and a trimmed global-reset alias; no new timing cuts. [Fresh route](../build/framework-local-release-route-run-v1/report.json) completed but failed setup by 1.615 ns on the functional MIG-control-to-layout-lane-enable path; hold +0.052 ns. Clock/reset exceptions were not loosened and no image was accepted |
| Layout lane-enable timing repair | Numerical and mapped checks passed; V4 routed setup failed | [Root acceptance](../build/framework-layout-enable-parent-v1/root-acceptance.json): seven scenarios, 18 resets, all 50 BO images/6,615,040 bytes exact. Bench output paths still pointed into the prior package; current-run timestamps, strict write-mode captures and all input/log/binary bindings were checked independently, with producer FAIL retained. [Mapped review](../build/framework-layout-enable-mapped-audit-v1/root-mapped-review.json): 297,468 LUTs, all 512 product/516 total DSPs and 242 IOs; all 96 nonclock inputs of 32 lane FFs independent of READY, with two positive controls. The FF selector overcount failure is retained. [V4 route](../build/framework-layout-enable-route-run-v4/report.json) measured setup -2.011 ns/hold +0.051 ns, then hit an undefined directory variable in its post-route lane audit. Both failures are retained. The subsequent diagnosis covers 3,000 negative paths/133 endpoint families; no image is accepted |
| Readiness/quiet/fault Boolean factoring | Fresh numerical replay and mapped synthesis passed | [Independent numerical review](../build/framework-readiness-factor-parent-review-v2/review.json): seven scenarios, 24 pipeline stages, 18 resets and 50 complete BO captures/6,615,040 bytes exact. [Mapped review](../build/framework-readiness-factor-post-audit-v1/root-synth-review.json): 297,353 LUTs, 512 product/516 total DSPs, 16 kernels and 242 IOs. Four-state qualification is scoped to reset-reachable binary ownership/state with arbitrary external X/Z; it does not establish equivalence for forced unknown internal state. Their routed and selected framework FPGA qualifications are listed below |
| Factored-source timing diagnosis | Identical-query comparison passed; same-source physical repair passed final routing/timing review | [Read-only diagnostic](../build/framework-readiness-factor-post-audit-v2/runs/1793298249624458309/report.json): backend response -0.306 ns, compute reset -1.662 ns, fabric/control results -1.319 ns. The [independent diagnostic audit](../build/framework-readiness-factor-diagnostic-review-v1/review.json) verifies real UI control-register origins and consuming D/CE targets for all three families. The any-UI control query returns the same worst path, proving timing visibility rather than an alternate origin. These are unplaced synthesis estimates. The [identical-query mapped comparison](../build/framework-factor-timing-root-review-v1/review.json) verifies unchanged 77-origin and target sets: old estimates -2.238/-4.866/-1.950 ns improve by 1.932/3.204/0.631 ns respectively. The [fresh factored-source route](../build/framework-readiness-factor-route-prep-v3/run-v3/report.json) was interrupted during correction after initial setup -0.421 ns/hold +0.049 ns. The [same-source checkpoint recovery](../build/framework-factor-route-resume-v1/report.json) finished at -0.033 ns setup/+0.049 ns hold and remains failed. One further post-route physical optimization and cleanup now [passes root acceptance](../build/framework-factor-route-repair-root-review-v1/root-acceptance.json): setup +0.001 ns, hold +0.049 ns, pulse +0.264 ns, 291,750 routed LUTs, all 512 product/516 total DSPs and 242 IOs. Independent review verifies all 232 pulse checks, fixed payload/skew budgets, DRC and reset boundaries. [Offline image and IO audit](../build/framework-factored-bitfile-root-review-v1/root-acceptance.json) now pass: 18,735,214-byte bitstream, source tag `60e7abbb`, all 242x8 port properties reviewed. [Selected six-case FPGA execution](FRAMEWORK_MATMUL_FPGA_TEST.md) now passes its exact image/target/lease and wire/BO review; broader physical gates remain separate. Software CRC checking is not claimed. RAM/high/swap remain uncapped |

The frozen V25 1,272-file copy's complete default `make test` exits zero in
1,483.568 seconds with RAM/high/swap uncapped. Its
[root acceptance](../build/production-model-auditors/current-v25/root-acceptance.json)
binds the independent frozen source/native/host review and the later two-file
bridge runner/README correction. The focused target passes again with exactly
105 checks per simulator and six expected invalid-parameter failures. The
producer's post-test JSON inventory error on two list-valued fixtures remains
preserved; both Make commands passed. Older nested commands lacking cleanup
fields remain explicitly unknown. This qualifies the frozen suite plus its
focused delta, not the private timing sources or an FPGA image.

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

The fresh public `make -j2 test` at source commit `e63a200` passes in
707.815 seconds with 20,891 tracked/relevant nonignored inputs unchanged and
all owned processes closed. Its [receipt](../build/health-fault-owner-public-regression-v1/report.json)
records actual tools, test seeds and uncapped RAM/high/swap. This default target
does not select the private timing or physical-integration candidates; their
separate checks above must not be replaced by the public regression result.

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
45-QWORD body. This stage therefore requires the implemented raw-command
layout DMA as well as CMAC; admitting the CMAC class alone is insufficient.
The [fresh six-shape index contract](CMAC_ENCODER_CONTRACT.md) verifies all
16,897 captured gather indices without running tensor arithmetic or gathers.
The new [raw layout encoder and DMA](LAYOUT_DMA.md) now execute those 18 plans
in both native simulators, with complete-aperture comparisons, retained results,
repeat execution and fault drainage. The encoder also accepts the actual
pinned original `RKGather` types for every captured plan. The separate explicit
[full-DDR framework profile](FRAMEWORK_FULL_PROFILE.md) serializes compiler
indices only; hardware moves the original halfwords. Its published 68-source
selection passes all six compiler/final-writer native trials: 24 jobs,
18 layouts, six CMAC submissions, 18 resets and 2,375,680 complete BO bytes
before ACK. The default EW adapter continues rejecting CMAC. The new private
timing sources now pass source-bound routed and offline image acceptance
above and the selected six physical cases now pass [wire/BO review](FRAMEWORK_MATMUL_FPGA_TEST.md). Broader backend and real-controller coverage remain separate. The older actual-controller functional
replay does not qualify the changed source.

Retain the original standalone CMAC reset boundary: the pinned final writer
calls `reset_npu()` after success. The explicit full-DDR runtime implements
that call through RKRS with quiescence, exact epoch acknowledgment and retained
BOs; its six native trials verify no host tensor/scratch reloads after launch.
Do not bypass the reset or change the clean-context flag to obtain a pass.
The separate [compute-reset preparation candidate](../build/framework-reset-candidate-v1/CONTRACT.md)
now passes [component review](../build/framework-reset-candidate-v1/root-result-review.json)
in both native simulators, including fresh-edge acknowledgment, stopped clocks,
held results and sticky faults. Component evidence alone does not qualify
the joined final-writer path or an FPGA image; the separate public-entry
native review above covers the former, and physical qualification is pending.
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
The local `make backend-test` recipe passes all eleven pinned backend
compiler/RTL cases; portable fixtures run under `make backend-layout-test`.
The [source/RTL workflow](../.github/workflows/test.yml) registers the portable
default regression and a separate compiler-to-EW-RTL job using the exact
backend revision. Both preserve test receipts and logs. Local workflow
validation and actual remote CI execution retain separate evidence; remote
execution has not been triggered in this session.

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

The callback-only host wrapper is documented in
[FI_HOST_PREPARATION.md](FI_HOST_PREPARATION.md). Its public
`make ddr-fi-client-controls` target runs normal and optimized fake-register
tests only; this does not verify SystemVerilog or the physical register path.

The separate [raw RKFI parent trial](../build/ddr-fi-management-parent-prep-v5/native-v1/report.json)
now selects 129 actual-controller/model sources: 126 unchanged sources, two
management parent/router replacements and the register leaf. HDL generation
passed with no new warnings against the reviewed controller baseline and the
fresh C++ build passed. Its first normal case then failed a new bench check
that incorrectly treated the one-cycle retirement pulse as held status. The
corrected [sticky-witness rerun](../build/ddr-fi-management-parent-prep-v6/native-v1/report.json)
now passes [independent six-case review and root acceptance](../build/ddr-fi-management-parent-results-review-v1/root-acceptance.json).
Normal CMAC/EW, early ownership, actual CE/UE with raw-job recovery, and capacity
BIST/reset pass with 327,680 complete numerical BO bytes before job ACK. The
bench uses raw register frames, requires all sixteen line-result reads before
ACK, retains a nonzero mask through joint reset, and checks bootstrap disarm.
The [inventory erratum](../build/ddr-fi-management-publication-review-v2/review.json)
records that the V6 source manifest's bench entry still names the V5 hash;
actual native inputs, approval, executed command and before/after hashes bind
the corrected V6 bench. The original files and failed V5 run remain unchanged.
This source set has no complete physical MIG wrapper and provides no FPGA or
physical ECC qualification.

Physical retained-mask recovery also needs an explicit live whole-transaction
reset control. The [read-only reset reference inventory](../build/ddr-fi-live-reset-reference-v1/source-map.json)
confirms that the current frozen board top ties `reset_req_valid` low. Driving
that input in the native bench does not qualify a board-accessible control.
The inspected OpenTPU and ZYNQ-NVDLA controls are not a qualified replacement
for this reset domain. The separate [whole-reset SYS controller](WHOLE_RESET_CONTROL.md)
now passes native protocol/freshness/timeout controls and the full default
regression. It is not selected by a board profile. Retained maintenance mailbox,
UI admission/drain witnesses, actual parent/reset integration and physical tests
remain required before claiming live mask bootstrap recovery; SRAM
reconfiguration qualifies the separately documented reconfiguration path only.
The private [retained UI bridge review](../build/whole-reset-ui-bridge-review-v1/review.json)
and [frame-gate recheck](../build/whole-reset-frame-gate-review-v1/recheck-v2.json)
now pass component tests with scripted witnesses/backends. The gate seals before
publishing quiet, rejects open-admission X/Z frames, and blocks or withdraws
quiet on a sticky protocol fault. The proposed 133-source actual-controller
wrapper also gates readiness on fault and uses the real coordinator. Its
[fresh V9 matrix](../build/whole-reset-fi-parent-prep-v9/native-v1/report.json)
compiled and passed five cases, then failed capacity reset recovery after the
BIST itself passed. The drain predicate rejected `capacity_selected`, while
the capacity owner intentionally retains selection after completion until a
whole reset. The [reviewed correction](../build/whole-reset-capacity-drain-source-review-v1/review.json)
permits that selected owner only with its real completed, healthy and drained
result; the other drain conditions remain. A separate held-request observer
also hit its 50,000-UI-cycle window; its [test-only correction](../build/whole-reset-sealed-window-source-review-v1/review.json)
uses the existing full-initialization allowance and still needs a fresh replay.
The subsequent [V4 twelve-case root acceptance](../build/whole-reset-terminal-format-results-review-v4/root-acceptance.json)
passes the corrected FI-only composition, including seven successful SYS resets
and 532,480 complete numerical BO bytes before ACK. That source is published
as the separate maintenance/FI profile. It does not qualify the newer combined
framework/FI candidate, a board-accessible maintenance path or physical recovery.

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

The [clock/reset contract](PCIE_CLOCK_RESET.md) records the actual AMD
AXI-Lite converter's local-clock reset behavior and the unselected bridge-reset
preparation component. Joint reset while a PCIe clock is stopped requires a
fresh-edge handshake before admission; link/PERST/compute reset must not clear
retained owner/mailbox state. Component initialization readiness does not prove
later clock liveness or qualify vendor-IP integration.

The next native transport increment is the original four-job `(1,16,32)`
framework pipeline with compute resets, first through JTAG and then through
the PCIe packet frontend while retaining all BOs. The separate
[test-only retained-image oracle](../build/dual-host-retained-oracle-review-v2/review.json)
passes all 24 qualified job snapshots/2,375,680 complete BO bytes across the
six shapes, six repeated pipelines, unchanged-zero write controls and output
atom-gap checks. It accepts only exact job records from the six pinned,
independently reviewed captures; it is never imported by the hardware runtime.
It does not establish new frontend, numerical, PCIe-IP or hardware execution.
The first new replay build was deliberately stopped before simulation after
bench review found invalid global write-count and timing-dependent poll
comparisons. Its failed receipt remains preserved. The corrected
[bounded-backpressure replay](../build/dual-host-cmac-reset-run-v4/runs/1793302311265726287/run-report.json)
now has [independent native acceptance](../build/dual-host-cmac-reset-post-root-review-v1/root-acceptance.json):
eight jobs/tasks, six resets and 720,896 complete BO bytes before ACK across
both frontends, with zero PCIe host uploads. Its producer remains failed
because the original trace reviewer misaligned an intermediate post-ACK reset
sample with the terminal sample. The separate post-run audit validates the
unchanged 61,968,775-byte actual trace, all BOs, ownership and warning conditions.
The later [six-shape root acceptance](../build/dual-host-cmac-six-shape-independent-review-v3/root-acceptance.json)
now qualifies 48 jobs/tasks, 36 resets and 4,751,360 complete BO bytes before ACK
across six independently initialized model processes. The actual producer is
terminal PASS with a separate terminal warning review; an earlier interim
warning-review hash remains preserved, with its exact old producer bytes
unavailable. Only extra live job-status reads use the reviewed 32-UI-edge
sampling cadence; the original raw programs and all error/deadline guards
remain unchanged. These results do not qualify continuous twelve-epoch handoff,
actual PCIe IP/CDC, MIG/PHY or FPGA execution.

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

The [bounded saved-fixture inventory](../build/rk-existing-fixture-inventory-v1/report.json)
now hashes thirteen selected files from the local RK3588 donor. Inspected logs
contain selected command windows or reported convolution comparisons, rather
than a complete supported EW/GEMM command plus initialized/post-submit BO
fixture. One H14-named log identifies an H112 case in its header, so it cannot
be joined to a local model by filename. Full raw I/O capture and provenance
remain required; this bounded search does not establish RK equivalence or
exclude fixtures elsewhere.

The [passive DRM capture primitives](BACKEND_CAPTURE.md#passive-drm-capture-preparation)
now record original submit structures and complete physical BO extents around
the unchanged blocking ioctl, with explicit diagnostic cache syncs and failed
capture/ownership handling. Device-free tests cover these primitives only.
A pinned real-device case runner, actual RK outputs and the FPGA differential
remain required; no silicon compatibility result is inferred from this preparation.

The [offline EW case preparation](../build/rk-ew-silicon-case-prep-v1/results-review.json)
now verifies eighteen original compiler programs: ADD/SUB/MUL at lengths
7/8/9/31/32/33, each with finite and special-value input images. Its 126 artifacts
include complete 4,096-byte A/B/output-before mappings with explicit zero/A5
padding. These are compiler programs and initialized input fixtures, not final
device-address command words, real allocations or observed hardware outputs.
The workspace-only case-runner preparation has thirteen device-free tests and
default preflights; no RK device was opened. Identifying the actual RK3588 host,
auditing that target and capturing its raw results remain required.
The [portable source/input handoff](../verification/runs/2026-11-01-rk-ew-capture-preparation/README.md)
preserves 134 regular payloads with a standalone archive verifier and a checked
relocated preflight. It contains initialization images and compiler IR, not
observed RK outputs or numerical-equivalence evidence.

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
