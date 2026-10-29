# Verification evidence

Current source, review and validation results are recorded in the
[project README](../README.md) and [implementation plan](../docs/REVIEW_AND_PLAN.md).
The dated results below remain evidence for their original source snapshots.

The historical full32 DDR archive has a packaging inconsistency: its index
both includes `payload/build/tinystories-full-oracle/v1/arithmetic/oracle.so`
and lists the same source as a hash-only exclusion. The included 12,664-byte
CPU-oracle library has SHA-256
`dabb4aa33d17edf6a11e0ea62e1efe2ca54370aeb938d39b16796796c9d26a5d`.
The original archive and index are preserved verbatim. Statements below about
compiled-object exclusions have this exception; the library is a historical
reference artifact and supplies no qualification for changed source or tools.

The [full32 DDR physical archive](runs/2026-10-28-full512-ddr-full32-fpga/index.json)
preserves 678 payloads in 61,613,646 stored bytes. Root independently rehashes
all source/stored/decompressed bytes, all 77 physical artifacts and 479 bound
image/model/runtime references. It retains the accepted one-prompt model
workload, all three actual phase captures, binary BO/logit data and the prior
v4 failure. Compiled images/tools remain hash-only references. Selected DDR
inference passes; full capacity, injected ECC/recovery, PCIe and RK equivalence
remain unqualified.

The [V16 production capacity-RTL archive](runs/2026-10-28-production-ddr-capacity-rtl/index.json)
preserves 2,705 payloads in 19,539,956 stored bytes. Root independently rehashes
all payloads, the complete 1,105-file source snapshot, both full host reports,
all twelve capacity cases and 1,128 compiled/tool exclusions. Serial Make
passes in 876.048 seconds with unchanged source/copy hashes. V15 is retained
as report/review lineage. This is source/native evidence only.

The [capacity AXI/BIST archive](runs/2026-10-28-ddr-capacity-axi-sim/index.json)
preserves 410 payloads in 2,679,925 stored bytes. Root independently checks
every original/stored/decompressed payload, all 219 coverage references and
1,103 hash-only exclusions. Current qualification uses the expanded private
v16 and fresh public runs. The earlier private v15 post-run bench mutation,
its forensic diff and the historical producer-bound bytes are explicit.
This is bounded AXI/control-model evidence, not physical capacity.

The [FI-leaf archive v2](runs/2026-10-28-ddr-ecc-fi-leaf-sim-v2/index.json)
preserves 89 payloads in 426,668 stored bytes. Independent root rehash checks
every original/stored/decompressed payload, all 85 coverage references and
226 hash-only exclusions. It includes all six vendor sources named by the
injection-obligations review. Both native leaf outcomes are preserved beside
the failed Icarus footer-parser receipt; no controller/decoder/PHY, physical
injection or recovery qualification follows from these leaf tests.

The [capacity-controller simulation archive](runs/2026-10-28-ddr-capacity-controller-sim/index.json)
preserves 235 source/evidence payloads in 4,848,190 stored bytes, including
pattern mapping, bounded sweep tests and their failed attempts. Root
independently rehashes all original/stored/decompressed payloads and all 309
hash-only exclusions. The sweep result covers a 256-byte model and default
two-GiB boundary elaboration; real MIG integration and physical capacity
remain unqualified.

The [first DDR BOS archive](runs/2026-10-28-full512-ddr-first-bos/index.json)
preserves 498 verbatim payloads totaling 65,844,133 bytes. Independent root
rehash checks every original/archive pair, all 12 binary exclusions and the
read-only audit-view references. The accepted control completes one position,
36 learned FPGA projections, 232 raw jobs, 348 tasks and 950,272 output-BO
bytes with all 512 logits matching. The overall v4 observer-path failure
remains failed, and this archive makes no full32 claim.

The [V15 capacity-plan source archive](runs/2026-10-28-production-ddr-capacity-plan/index.json)
preserves 2,619 payloads in 19,892,855 stored bytes, with all 1,230 coverage
references and every source/stored/decompressed payload independently rehashed.
It contains the 1,098-file V15 snapshot, full default regression and seven
supplemental capacity controls. The supplemental scope is software-only;
physical capacity remains unqualified.

The [full512 DDR trained FPGA archive](runs/2026-10-28-full512-ddr-trained-fpga/index.json)
preserves 397 payloads in 4,106,430 stored bytes. One audited volatile load
passed scratch and four trained raw jobs with 360,448 complete BO bytes before
ACK, 26,204 actual scans and 8,732 commands. Both traces and all four binary
readbacks are included. Root independently rehashes every payload and all 527
coverage references; bitstream/checkpoints/tools are hash-only exclusions.
Full-model inference, capacity, injected ECC, recovery and PCIe remain open.

The [production DDR repeat-control archive](runs/2026-10-28-production-ddr-repeat-control/index.json)
preserves the V14 run and V13 source history: 5,210 payloads in 37,940,410
stored bytes, with all 2,439 coverage references independently checked.
Serial Make passed in 794.096 seconds with 89 DDR controls, 61 TinyStories
controls and both complete native host suites. This source/native snapshot
does not qualify any physical model inference.

The [full512 DDR timing archive](runs/2026-10-28-full512-ddr-timing/index.json)
preserves the independently qualified routed result: setup +0.004 ns, hold
+0.048 ns and pulse +0.264 ns, zero failing endpoints and 422,138 fully routed
nets. It includes 406 payloads in 3,965,773 stored bytes and all 343 input
references, with native tools/checkpoints hash-identified as exclusions. The
original native repair pass and wrapper provenance failure remain preserved
beside the fresh successful qualification. Independent root rehash covers all
source/stored/decompressed bytes and references. No image or physical DDR
application acceptance follows from this timing result alone.

The [production full512 DRC-gate archive](runs/2026-10-28-production-full512-drc-gate/index.json)
preserves the completed V13 run: 2,615 payloads, 19,208,376 stored bytes and
1,222 coverage references, including all 1,095 copied sources and both source
reviews. Serial Make passes in 890.086 seconds, with 84 DDR software controls,
61 TinyStories controls and the original native suites. The three new emitter
controls reject changed warning counts, unknown DRC rules and severities.
Root independently rehashes all source/stored/decompressed bytes and coverage
references. This source/native result does not admit a bitstream or hardware.

The [prior production DDR model-auditor archive](runs/2026-10-28-production-ddr-model-auditors/index.json)
preserves the completed V12 run: 2,613 payloads, 19,193,963 stored bytes and
1,218 coverage references, including all 1,095 private source inputs. Default
Make passes in 902.088 seconds, with 81 DDR software controls and 61 TinyStories
controls alongside the original native suites. Independent root rehash checks
every stored, decompressed and source payload. This is source/native evidence;
it does not qualify routed timing or physical DDR inference.

The [shared-data controller archive](runs/2026-10-28-shared-data-controller-33/index.json)
preserves 662 payloads in 3,893,933 stored bytes for all 12 CMAC and 21 EW
numerical/fault/recovery cases on the same executable. Independent root rehash
checks all stored/decompressed/source bytes and 2,775 input-closure references
across six completed groups. The 112 HDL sources and five headers are included;
the ELF and native tools are hash-identified exclusions. The PHY and one-MiB
memory window are modeled. Routed timing and physical DDR remain separate.

The [full512 DDR constrained-source archive](runs/2026-10-28-full512-ddr-constrained-source/index.json)
preserves 360 payloads in 2,912,186 stored bytes. Its 293,826-LUT optimized
design retains all 512 product DSPs, both controllers and the exact 242-port
interface. All 819 coverage references and every stored/decompressed/source
payload pass independent rehash. The post-opt inventory producer's marker
location failure remains failed beside separate acceptance of the actual
native exit-zero facts. Routing, timing, image and physical gates remain separate.

The [shared-data logical archive v2](runs/2026-10-28-shared-data-logical-v2/index.json)
preserves 1,090 payloads in 7,092,601 stored bytes. It includes complete sampled
cell equivalence in both simulators, both nine-mode dispatcher suites, the
2,125.131-second trained CMAC/EW/CMAC controller replay, and strict read-only
mapped inventories. Every payload and all 1,726 included input references pass
independent rehash/path verification. The prior archive's 449 missing gzip
suffixes remain a failed metadata receipt; v2 preserves identical payloads.
Original simulator failures remain failed. Live synthesis/fault runs, native
binaries and generated C++ are excluded. This supplies no routed timing,
physical DDR or RK silicon qualification.

The [production full512 image-control archive](runs/2026-10-28-production-full512-image-controls/index.json)
preserves 2,611 payloads in 19,176,796 stored bytes, including all 1,093 private
source files and 1,216 exact coverage references. Serial `make test` passes in
1,024.229 seconds, with 61 TinyStories controls, 66 DDR controls and both full
host suites. Independent rehash validates every stored, decompressed and
original payload and every coverage path. The image-emission tests are offline;
no image, routed timing or physical DDR qualification comes from this run.

The [prior production DDR/model-profile archive](runs/2026-10-28-production-ddr-model-profile/index.json)
preserves 2,601 selected payloads in 19,126,361 stored bytes, including the
complete 1,090-file source copy, native reports/logs, both full host receipts,
resource admission and independent review. Serial `make test` passes in
978.148 seconds with 61 TinyStories controls, 58 DDR software/auditor controls
and six dual-control native commands. Every archived, decompressed and source
payload is independently rehashed. Native build outputs/tools remain excluded
with hashes and reasons. This default regression does not qualify the optional
full512 controller composition, physical DDR or PCIe.

The [full512 shared-dispatch logical archive](runs/2026-10-27-full512-dispatch-logical/index.json)
preserves 155 selected payloads in 811,044 stored bytes. Both simulators pass
all nine original CMAC numerical/fault/reset modes through the actual shared
dispatcher, retaining sixteen C32 kernels and 512 product lanes. The repeat
case checks 98 original command words, 13,056 operand reads, 128 writes,
13,576 responses and two safe rearms. Original fixture bytes, seed and error
expectations remain unchanged. Independent review rehashes both input maps,
all archived/decompressed payloads and all 18 native logs. Strict Verilator
compile failure and reviewed-warning compilation retain separate receipts.
This is numerical component evidence; joined DDR, physical execution, CDC and
routed timing remain unqualified. See [the source contract](../docs/DDR_DUAL_ENDPOINT.md).

The [first physical CH1 DDR archive](runs/2026-10-27-ch1-ddr-first-fpga/index.json)
preserves 575 selected payloads, including all 122 actual-used HDL sources,
the two XDC copies, original fixtures and complete actual JTAG scan trace.
One volatile load passed CH1 initialization, 768 scratch bytes and a captured
SUB(9) job with two tasks. Independent replay checks 24,238 scans and 8,078
mailbox commands, including all 102,400 owned BO bytes before ACK. All 511
image-admission inputs are accounted for: 505 textual inputs are included;
four compiled images/checkpoints and two native tool wrappers remain excluded
with hashes. The first failed auditor receipt remains failed beside the
passing corrected audit. Full capacity, injected ECC faults/recovery,
full512/DDR, PCIe, RK equivalence and production electrical signoff remain
open; software CRC validation was not performed. See the
[physical report](../docs/DDR_FPGA_TEST.md).

The [fresh production archive](runs/2026-10-27-production-memory-wait-controls/index.json)
preserves1,065 files, including the complete1,051-file private source snapshot
and selected actual reports/logs for serial `make test` in1,035.709seconds.
All55 TinyStories controls and11 DDR controls pass, alongside both249-entry
EW suites, both15-case host suites and the numerical corpus. The independent
review rechecks sources, reports and both full host receipts. The archive
occupies8,115,851bytes; source and decompressed copies are independently
rehashed. Optional async/CDC sources are copied for provenance, with their
native qualification separate. Compiled images, bulkvectors and the full
native artifact DAG are excluded; this supplies no physical DDR/PCIe/RK proof.

The [unpromoted reset-candidate archive](runs/2026-10-27-ddr-clean-reset-candidate/index.json)
preserves1,160 source/evidence files in8,957,113bytes. Original32/23 reset
cases, five new public-status cases and two joined fault cases pass; actual
118-source MIG synthesis and scoped mapped status/job/memory checks pass.
The new source removes six unknown-level CDC findings and registers the SYS
admission witness. The mapped audit covers nine status chains/27 registers,
167 held payload bits, four constant bits and18 job/memory synchronizer
stages. Original-circuit and wrong-clock negative controls reject.
All archived/source/decompressed bytes are independently rehashed. This is a
source candidate, not the active main RTL: full21-case runtime, twelve remaining
reset/vendor findings, platform timing and physical DDR/full512/PCIe/RK remain
open. Active recovery artifacts, compiled images and external vendor bodies
are excluded. See the [reset review](../docs/DDR_LIFECYCLE.md#mapped-reset-findings-and-private-candidate).

The [complete32-position TinyStories FPGA archive](runs/2026-10-27-tinystories-full32-fpga/index.json)
preserves331 files and49,234,220 stored bytes, including the complete actual
JTAG trace, reviewed local sources, original raw programs, BO observations,
host model operators, CPU reference and independent auditors. All1,152
learned projections run on the full512 FPGA; all16,384 logits and28 generated
token IDs match the donor-policy reference. The independent decoder/replay
checks2,743,153 scans,914,383 commands,7,424 jobs,11,136 tasks and30,408,704
complete output BO bytes before ACK. The index hashes original and archived
bytes; deterministic gzip entries decompress to the exact recorded contents.
Explicit CPU host operators remain, with no learned-dense fallback. Images,
checkpoints and native tools are excluded; JTAG inference supplies no physical
DDR, PCIe or RK equivalence claim. Flash is unchanged. See the
[physical report](../docs/TINYSTORIES_FPGA_TEST.md).

The [twenty-case logical DDR archive](runs/2026-10-27-ddr-all20-logical/index.json)
preserves 130 selected local-source/text entries and their exact hashes.
Nine completed positive cases, ten fault/recovery cases and a separately
verified repeated SUB(9) use the same native binary and original deadlines.
The independent union passes all twenty cases; the original positive shard's
repeat timeout, failed status and partial output remain preserved. Thirteen
successful jobs compare 1,282,048 physical BO bytes in the encoded-PHY model.
This archive excludes external generated/vendor sources and the native binary;
it supplies no full binary DAG, pad/training, physical DDR, PCIe or RK proof.

The [earlier production archive](runs/2026-10-27-production-ddr-controls/index.json)
preserves the complete 1,002-file private source snapshot and selected actual
logs, host readbacks and reports for serial `make test` at source
`2a3d4a7b195b`. The run passed in 1,107.786 seconds, including both 249-entry
EW suites, both 15-case host suites, 73 root unit methods, 53 host controls,
28 TinyStories controls and 11 DDR endpoint controls. Independent current-source
rehashing and both full host receipt verifiers pass. Compiled images and bulk
generated vectors are excluded; this selected archive is not a complete binary
artifact DAG. It supplies no full joined-MC, mapped or physical result, and
excludes optional original-MIG work added afterward.

The [original-profile MIG source archive](runs/2026-10-27-original-mig-source/index.json)
preserves 48 selected files for unchanged-input RZQ/7 source generation in
Vivado 2026.1. Its native run returns zero, hashes 141 generated artifacts and
has a separate source-binding audit of 169 actual wrapper ports, geometry,
clock constraints and generated-template omissions. Source generation and the
separately prepared WIDTH1 arbiter definition supply no complete generated-PHY,
matched-model, implementation, board clock/electrical or physical DDR result.
See [the source preparation report](../docs/DDR_ORIGINAL_MIG.md).

The [2026-10-26 EW FPGA archive](runs/2026-10-26-ew-startup-fpga/index.json)
preserves raw passive JTAG captures and selected source/implementation/image
receipts for three successful volatile-SRAM loads. Four captures contain 404
positive scoreboard-output samples and 32 heartbeat transitions. See the
[hardware scope and result](../docs/EW_FPGA_TEST.md); this supplies no direct
memory readback, GEMM, DDR, PCIe or RK silicon result. Bitstream/DCP and
compiled simulator binaries remain outside this selected text archive.

The [full512 FPGA startup archive](runs/2026-10-27-full512-regmem-fpga/index.json)
preserves three actual volatile-SRAM load receipts and four positive passive
captures: 404 samples, 32 heartbeat transitions, PASS=1 / FAIL=0, drivers
enabled and INIT/DONE valid. Its 101-row pre-load baseline remains UNKNOWN
and excluded. All 512 CMAC products are bound to the reviewed image; the
finite K65 workload's terminal scoreboard output is observed, with no direct
RAM readback or broader RK/host/DDR/PCIe/electrical claim. Flash was not written.

The [USER2 host-controlled FPGA archive](runs/2026-10-27-host-user2-fpga/index.json)
preserves 228 text/source files, including raw numeric scans and complete BO
inputs/readbacks. Eleven positive jobs complete sixteen tasks; all 1,077,248
owned bytes match before ACK. Unknown-register E1 persists across reconnect
and TAP reset, then explicit SRAM reconfiguration recovers it. Two actual
loads pass. The independent auditor decodes 106,662 scans and 35,550 mailbox
commands. This is raw captured EW execution in BRAM; live compiler-to-card,
full512 host, DDR/PCIe and RK equivalence remain separate. See the
[physical report](../docs/HOST_FPGA_TEST.md). Flash was not written.

The [TinyStories preflight archive](runs/2026-10-27-tinystories-preflight/index.json)
preserves78 text/source files: pinned static input metadata, unmodified C
reference/license and CPU generation, finite unity-copy RTL controls, and the
first trained BOS query tile replay on all512 pipeline products. It includes
the original dependency failure and full-Make timeout. This is preparation
and component/reference execution, not RKNPU TinyStories FPGA inference.
The [application plan](../docs/TINYSTORIES.md) distinguishes the later raw-EW
compaction and focused-timeout replay results from this frozen snapshot.

The [TinyStories shared-endpoint archive](runs/2026-10-27-tinystories-dual-route/index.json)
preserves 145 files: frozen full512/dual-endpoint source, corrected native
runs, routed reset/CDC/timing reports, raw-program metadata and CPU model
references. Its 50 MHz checkpoint passes setup +0.640 ns, hold +0.056 ns and
pulse +9.600 ns with all 512 products retained. This archive has no FPGA
image/checkpoint or physical acceptance claim.

The [physical trained-tile archive](runs/2026-10-27-tinystories-trained-tile-fpga/index.json)
preserves 85 files for the exact new image and actual BOS Wq tile: two raw
CMAC jobs and two linked FPGA compactions, all 360,448 owned BO bytes matched
before ACK. The independent decoder checks 25,894 actual JTAG scans and
8,630 mailbox commands. Large text reports/scans are gzip-compressed; the
index binds both archived and original bytes. Small complete BO readbacks
are retained directly. Images/checkpoints are excluded and flash is unchanged.
This is trained-tile execution; full-model inference remains a separate gate.
See the [physical report](../docs/TINYSTORIES_FPGA_TEST.md).

The [first complete model-forward archive](runs/2026-10-27-tinystories-first-forward-fpga/index.json)
preserves 41 closed files for one physical BOS forward through all five
TinyStories-260K layers and the output head. All 36 learned projections run
on the FPGA; every actual input/output pair, original command/task BO and
resident weight tile passes independent raw-scan audit. All 512 logits match
the donor-policy oracle bit-exactly and greedy sampling produces token 403,
`Once`. The run completes 232 raw jobs/348 tasks and reads 950,272 complete
mutable-output BO bytes before ACK. Explicit CPU host operators remain; the
longer32-position run is excluded from that first-forward archive. Its later
complete physical producer and independent full32 audit now pass; see the
[physical report](../docs/TINYSTORIES_FPGA_TEST.md).

The [registered-RAM full512 timing archive](runs/2026-10-26-full512-regmem-timing/index.json)
preserves 193 text/source files, including the complete 125-file frozen
snapshot. Its newer routed 50 MHz result has setup +0.987 ns, hold +0.057 ns
and pulse width +9.600 ns, all with zero failures. RAM async-control findings
are absent; the remaining 2,060 DSP advisories retain factory severity. The
routed INIT/IO/DSP review and source-copy audit pass. This archive contains no
checkpoint, full netlist, simulator binary, bitstream or full512 hardware
result; mapped startup and final image admission remain separate gates.

The earlier [full512 pipeline timing archive](runs/2026-10-26-full512-pipeline-timing/index.json)
records the separate 50 MHz routed timing pass: setup +0.045 ns, hold +0.075 ns
and pulse +9.600 ns, with zero failing endpoints and all 512 products retained.
It preserves warning-level DRC findings and source/ROM inputs. This is timing
evidence only; mapped validation, warning/startup/image review and actual
full512 FPGA execution remain separate gates.

Git includes the text reports, indexes and checksum manifests. Compressed
`runs/**/*.tar.gz` evidence archives, build outputs and logs remain local and
are ignored. Links into those locations require the original workspace or its
separately preserved evidence. An index or checksum alone does not reproduce
a run or qualify modified sources.

The [2026-10-26 reviewed full regression](../build/plan-ddr-lifecycle-implementation/1792976927285576710/production-validation.json)
records actual `make -j2 test` exit 0, both 249-entry EW suites, both raw-product
CMAC suites and both 15-scenario USER2 host suites in 429.182 seconds.
Its [copied receipts](../build/plan-ddr-lifecycle-implementation/1792976927285576710/production-evidence.json)
preserve 1,485 selected source/artifact files. The independently scoped
[USER2 BRAM package](../build/host-jtag-preparation/1792967662198630675/report.json)
binds its current native source, binaries, commands, logs and stimuli; its
separate [eight preparation controls](../build/host-preparation-review-1792955479549759890/report.json)
cover the final foreign-artifact-origin fix. Board review remains incomplete.
The original aggregation-label failure and earlier host attempts are preserved;
the reviewed summary changes no test outcome. No Vivado or hardware result is
supplied by these source/preparation checks.

The [DDR metadata/source audit](../build/ddr-interface-audit/1792970299029233481/copy-audit.json)
records fourteen passing command checks, including thirteen unit methods in
normal and optimized Python, copied verification and tamper rejection. The
actual original MIG inspection remains blocked with eight source conflicts
and five integration blockers. A [separate archive inventory](../fpga/ddr/xdma_archive_reference.json)
provides generated logical-interface sources with an explicitly different
output-drive profile. Neither artifact implements a DDR lifecycle wrapper,
simulates MIG or qualifies physical memory.

The [ECC control monitor](../docs/DDR_ECC_MONITOR.md) is a separately qualified
leaf. Its [reviewed Make target](../build/plan-ddr-monitor-implementation/1792971553929950788/monitor-validation-reviewed.json)
passes 29 Icarus/23 Verilator portable cases and all 21 actual archived-control
cases per simulator, plus nine runner regressions. The
[23 copied-evidence checks](../build/ddr-monitor-copy-audit/1792974487715872025/report.json)
preserve all 74 selected files, including source, binaries, command logs and
parameter headers. Exact command/version/image/input binding and the required
absolute header macro reject the reproduced metadata and shadowing failures.
These results leave initialization, retirement and whole-domain reset pending;
no DDR-ready or successful-job result is supplied.

The separate [reset/fence component target](../build/plan-ddr-lifecycle-implementation/1792976927285576710/protocol-validation.json)
passes reset 32/23 and fence 71/54 Icarus/Verilator cases, plus six parameter
rejections per simulator and nine verifier regressions. Its
[23 evidence checks](../build/ddr-lifecycle-copy-audit/1792980569267619617/report.json)
preserve 68 selected files and originals. Actual-MC qualification separately
passes all six directed scheduling/ECC cases in both simulators for the
WIDTH=1-fixed source variant, with official functional primitives and modeled
PHY returns. It preserves the original failure, 512 derived-arbiter rows and
384 larger-width equivalence rows. The
[25 copied-evidence checks](../build/ddr-mc-copy-audit/1792981883884855148/report.json)
preserve all 272 selected files and originals. See [scope and exact receipts](../docs/DDR_LIFECYCLE.md).
The original archived controller, joined platform, physical DDR, global drain
and successful application execution are not qualified by these checks.

The separate [full512 startup-native profile](../build/plan-full512-startup-implementation/1792966979950932621/startup-native-summary.json)
passes 22 Icarus and 20 Verilator cases with unchanged K=65 oracles and actual
16-kernel/512-lane hierarchy. Its [checkpoint package](../build/full512-startup-preparation/1792967676447887367/report.json)
keeps the original arithmetic DAG as an external current prerequisite. The old
R28 reset qualification is not relabelled as startup proof. Physical INIT/FF
mapping, reconfiguration, fit/timing/DRC and execution remain unproved.
The [actual startup package audit](../build/full512-startup-package-audit/1792967676447887367/report.json)
passes eleven controls, preserving all 184 package files and 275 original
qualified files. Isolated copied-source verification never treats unavailable
external arithmetic-parent evidence as build permission.

The optional [ILA preparation controls](../build/plan-debug-implementation/1792961083679149070/debug-validation-final.json)
pass under Tcl 9.0.3 and vendor Tcl 8.6.13. The full regression included the
initial fourteen controls; the final snapshot-import fix passed sixteen
targeted controls afterward. These are source/preparation checks only, with
unchanged RTL and no debug-core implementation or physical capture.
The [autonomous](../build/ew-debug-preparation/1792962351826175702/report.json)
and [USER2 host](../build/ew-debug-preparation/1792962351620948606/report.json)
debug packages pass [23 copied-evidence checks](../build/ila-package-audit/1792962791198091922/report.json),
including isolated copied validators and rejection of changed sources,
artifacts and generated Tcl. Both still reject build admission for missing
board review; the normal RTL and full 512-product target are preserved.

The separate [production compiler-to-RTL run](../build/backend-rtl/1792958040917797032/report.json)
passes ten numerical Tensor cases and one compiled runtime-gather rejection.
Original compiler/writer code-object calls, locally compiled program images,
unchanged command/task bytes, 11 submissions/16 tasks and 1,081,344 complete BO
bytes are verified. This source-bound `RKNPUFPGA` adapter uses an injected frame
RTL process and test TAP shim; it is not full tinygrad, DDR/PCIe, FPGA or RK
silicon validation. See [the runtime contract](../docs/BACKEND_RUNTIME.md).
The [frozen evidence package](../build/backend-copy-audit/1792958403533425061/package)
passes [14 integrity and execution-binding controls](../build/backend-copy-audit/1792958403533425061/audit.json),
including verification without access to the original run or tinygrad checkout.

## Preserved production source and regression history

The latest [2026-10-09 private generated-C++ OPT0 production regression](../build/source-identical-production-opt0/1791512642277187031/report.json)
completes **PASS at11:23:11.900HKT**, actual make0/3540.766s, with the same101
production sources and all frozen command/input/golden buffers before/after.
Both EW suites pass247 entries; all three CMAC raw-product benches pass under
each simulator;49 host/model methods and1,087,299 C++ comparisons/seed0x3588 pass.
All five fresh source-bound reports and original warning/assertion/deadline
guards pass. Verilator5.048/Icarus13.0 actually execute the suites, with no
cached verification result inherited. All82 fresh EW observed memory images
agree byte-for-byte. The [complete execution/admission record](../build/source_identical_production_opt0_preflight_actual_20261009.md)
retains exact commands, profiles, actual logs and false physical acceptance
flags. Only private generated-C++ OPT_FAST/OPT_SLOW=-O0 change; reference-model
flags, RTL, backend encoder boundary, raw buffers/goldens and deadlines do not.

The [earlier2026-10-09 default-profile whole attempt](../build/source-identical-production-regression/1791508511941204286/report.json)
remains FAIL/make2/3030.576s: job-control and CMAC-operand builds exceed the
unchanged600s limit. This later private profile does not relabel those failures
or supply full C32/K16 shared mapped-board numerical, placement/route, timing,
electrical/DRC, FPGA/RK or bitstream acceptance. Full placement and baseline
mapped mode6 are still separate live workers.

The [optional full native metadata-export producer](../build/openxc7/full-native-cluster-export-1791520499945966327/report.json)
completes at12:47:06HKT on2026-10-09: actual native pack0/334.702s and whole
packed-graph `cmp`0/12.927s. All523,522 cells,515 DSPs/six BRAMs and checksum
77f1fde0 are retained. Every exported cluster has an individual geometry
witness:20,414 roots/104,250 children/29 exact classes,zero zero-candidate
classes. This is explicitly not a joint occupancy/fixed-BEL/control-set/timing
check, full placement or signoff. The
[actual record](../build/full_native_cluster_export_preflight_actual_20261009.md)
preserves the original diagnostic failures and separate transport-only recheck;
no unfinished placement or numerical result is inherited as acceptance.

The earlier [2026-10-07 source-identical production rerun](../build/rknpu-dsp-prefix-pin-cone-production-regression/1791382469904905494/report.json)
is **FAIL**, finishing at `2026-10-07T14:57:36.700021+00:00`: actual
`make -j2 -o vectors -o cmac-vectors test` returns 2 and its supervisor
returns 1. Verilator's `tb_cmac_product_front` compilation exceeds the unchanged
600-second wall budget. Its report records two completed product benches,
then TIMEOUT without a compiler return code; no third numerical run is
accepted. A later linked executable does not change that result. Earlier
completed source-identical passes below remain historical evidence, not a
PASS for this attempt. Neither the source, corpus nor error expectations were
changed, and the separate mapped-board continuation remains an independent
run with its own gates.
Its [terminal failure archive](runs/2026-10-07-resume-production-compile-timeout/index.json)
now verifies 2,798 members and 230,263,965 bytes, SHA256
`ad9b712d79cb799065fcc6d5394b86594cf9defc3216d5a0cd18bf6fc16957be`.
The original FAIL, partial reports, corpus, compiler output and source snapshot
are preserved. Packaging a failed regression does not supply acceptance.

The [new local Himbaechel inventory](../docs/OPENXC7.md)
checks actual database timing types and all 1,739 candidate dependency hashes.
The selected database has only a DEFAULT speed grade and no DSP48E1 timing
model. Its BRAM models and hold-repair support do not establish timing coverage
for the full 512-product board. Four synthetic parser controls and generated
checks pass in the [fresh software-only record](../build/himbaechel_timing_inventory_controls_20261007.json);
no physical signoff, bitstream or RK acceptance is inferred.

Source manifest `09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`
adds the openXC7 characterization runner, five unit tests and its Make target.
Existing RTL and tests are unchanged. A fresh `make -j4 test` exits zero:
49 Python methods, 1,087,299 C++ numeric comparisons, generated checks,
247 original entries plus three CMAC benches per simulator. These are new
native results, not copied mapping or physical evidence. The completed
[source-bound archive](runs/2026-09-21-openxc7-baseline/index.json) verifies
all 82 cross-simulator memory images and eleven host/direct images per
simulator match, with the original 610 stimuli unchanged.
The separate donor-based conversion/write candidates below are outside this
production source manifest. See [OPENXC7.md](../docs/OPENXC7.md) for tool-build
status and the incomplete physical-signoff coverage.

A subsequent complete `make test` rerun during staged CMAC host work also
passes at the same production source. Its
[fresh archive](runs/2026-09-21-cmac-host-production-baseline/index.json)
retains the actual new logs and all 82 matching cross-simulator memory images.
It does not cover the staged donor/board sources under `build/`.

The 2026-10-05 `make -j2 -o vectors -o cmac-vectors test` rerun also exits
zero at the unchanged production source. Its
[fresh preparation archive](runs/2026-10-05-fpga-preparation-production-baseline/index.json)
verifies 1,466 members, SHA256
`af991e198dbc6e4d762be24875a823ff3fa7f562730ff2af4ba4ca642fcaf044`.
It preserves the actual logs, 49 Python methods, 1,087,299 numeric comparisons,
247 original entries and three additional benches per simulator, all 82
matching cross-simulator memory images and eleven host/direct images per
simulator. Only the two vector generators were held fixed; every test target
executed. Report serialization occurs after the final console write, so each
reported finish is checked against its own JSON write timestamp. This is
native production evidence, not experimental fixed-array or FPGA signoff.

The subsequent 2026-10-06 production rerun also completes at that unchanged
source, with its actual Icarus report finishing at `2026-10-06T00:02:49.319311+00:00`.
Its [fresh source-bound archive](runs/2026-10-06-lut-pair-sinks-production-regression/index.json)
has 1,466 verified members and 11,462,999 bytes, SHA256
`9dcc51c05d5881aa20d9b9d5e9fb4fc2aff8f3dc9d80268dceaae04d3ba360f0`.
Independent checksum verification passes. It retains 49 Python methods,
1,087,299 numeric comparisons, 247 original entries plus three new benches
per simulator, 82 equal memory images and eleven host/direct images each.
It does not cover the nested experimental DSP-lane RTL or its new unit tools.
A further fresh production `make -j2 -o vectors -o cmac-vectors test` rerun
exits zero at the same source. Both current reports have 247 passing entries
and the CMAC reports have three passing benches each; Icarus finishes at
`2026-10-06T01:33:59.841571+00:00`. Its actual log is
`build/fpga_preparation_regression_corrected_dsp_lane_20261006.log`.
Its [fresh source/timestamp/output archive](runs/2026-10-06-shared-union-role-production-regression/index.json)
verifies all 82 matching cross-simulator memory images and eleven host/direct
images per simulator: 1,466 members, 11,463,540 bytes, SHA256
`3feedb3fb787c50b1a9e076269c40642b7ea03d326bd21b62f84d464924b0d19`.
Independent archive checksum verification passes. This is production native
evidence only, not experimental DSP/shared-union netlist or physical acceptance.

## Isolated corrected DSP-lane native stage and retained failures

The [native-stage and failure archive](runs/2026-10-06-corrected-dsp-lane-native-and-driver-failures/index.json)
has 57 verified members and 1,330,334 bytes, SHA256
`f785fe464bf6c2128f81cd42831cedf7d0b8dd79b148fd00bdd052f83f18b6b0`;
independent checksum verification passes. Actual Icarus/vvp 13.0 completes
135,680 binary lane-sum/tag comparisons with seed `0x3588d501` and a real
comparison-bit negative. The overall original driver remains FAIL on Yosys
scope-metadata admission before SAT; the original area driver remains FAIL
on retained miter hierarchy. Their executed sources are archived as exact
snapshots, not replaced by later corrected runner code.

The correction-omission diagnostic also records a real nonzero-magnitude
counterexample: `0002`, `0001`, shift two, mask one gives donor `ffffffff`
versus uncorrected zero. These are sign/pre-shifted lane magnitudes, not IEEE
FP16 bits or RK captures. A new, separate experimental C32/K16 DSP array is
prepared; it is not promoted into the raw-command board path.
The word-level proof times out after 1,000 seconds, without establishing
equivalence. Flattened candidate synthesis lists 652 LUTs and one DSP versus
765 reference LUTs, but the strict counter rejects DSP library timing
qualifiers, leaving that overall area attempt FAIL. The fresh isolated area
run now passes its exact library/signature gates at source
`7b701f5311742932408264abb99446d46e108d82624a10449ebadc4c289475a3`:
765 reference LUTs/zero DSPs and 652 candidate LUTs/one DSP. This is isolated
XC7 area, not numerical or physical acceptance. The first Boolean attempt
also times out before SAT; direct AIG lowering completes both graphs and
the real SAT negative, but its positive SAT reaches the 1,000-second
supervisor timeout and remains FAIL without binary equivalence. Fourteen earlier focused
control methods pass, including explicit timing-qualifier wiring mutations,
but are not arithmetic or physical proofs.
See [the CMAC experiment contracts](../docs/RKNPU_SIZED_CMAC.md) for exact
source hashes, reports and commands. Full-array/raw-board/startup/physical
gates, FPGA programming and RK-silicon acceptance remain separate and unmet.

The first actual mapped-lane replay finishes FAIL at
`build/rknpu-lane-dsp-mapped-binary/1791253423351655016/report.json`.
Real export/round-trip identity and the fresh native 135,680-comparison
positive/negative pass; mapped compile/negative pass, but its positive
simulation times out after 1,800.264 seconds. The failed parent is preserved.
A bounded verbose probe shows time advancing, not a numerical PASS. A separate
hash-bound continuation explicitly inherits only its unchanged completed
native/export commands, executes a fresh mapped negative and retains all
135,680 original positive comparisons with a 14,400-second budget. It completes
at `build/rknpu-dsp-mapped-lane-replay/1791256801119025767/report.json`;
the fresh mapped positive passes in 6,013.375 seconds, seed `3588d501`,
4,096 samples. The [completed actual mapped-lane archive](runs/2026-10-06-dsp-actual-mapped-lane-completion/index.json)
preserves 87 verified members/3,342,026 bytes, SHA256
`624c8198c367ef6886758ef003fe42b86579c4d7db42b1a56febbfc006cb6b57`.
The unchanged failed parent and exact compiled/model/source bindings remain
in that archive; inherited native/export stages are not presented as newly
executed. Four continuation controls pass. This is isolated mapped binary
fixture acceptance, not full-array, board or physical validation.
The independent archive checksum passes.
The original full DSP-array native runner finishes FAIL at
`build/rknpu-dsp-array-native/1791262976458807986/report.json` after verifying
that completed mapped-lane parent. Its actual full-array compile and original
first-frame negative pass; its full 208-frame positive times out after 14,400
seconds without a recorded numerical mismatch. The
[executed timeout archive](runs/2026-10-06-dsp-full-native-timeout/index.json)
preserves 71 verified members/61,638,124 uncompressed bytes, SHA256
`19c2adb35eac421e412d43d014cff4bcf0931d75cabdaa8f9edd705252ab3fdb`.
That failure remains immutable and does not authorize board or mapped replay.
The candidate's actual strict Verilator
lint exits one on three vendor filename/empty-output-connection warnings;
the failure is retained without a waiver. The initial full-array area flow
unintentionally skips the DSP stage because the ending label is exclusive.
A real [two-kernel/four-product synthesis control](runs/2026-10-06-dsp-stage-probe-1791260786574133774/index.json)
confirms zero DSPs/four unmapped multiplies at `begin:map_dsp`, versus four
DSP48E1s/no unmapped multiplies at `begin:coarse`. Its archive preserves 17
verified members/2,237,224 bytes. The known-wrong full run is deliberately
interrupted through handle 10703, returning 130; its unsaved `RUNNING` report
and incomplete export are preserved in the
[54-member interrupted-flow archive](runs/2026-10-06-dsp-interrupted-exclusive-stage-flow/index.json),
29,824,537 bytes, SHA256
`4610aee86a992dcf0ffe99c6c093105cfb192b0ce1ff21efe9d39b683302fc92`.
Its independent checksum passes; no numerical/resource acceptance is claimed.
The corrected full-array area job now completes at
`build/rknpu-dsp-array-area/1791261222250630875/report.json`, with supervisor
session 93125 exiting zero at the completed resource gate. It executes DSP
mapping and passes the early 32-DSP kernel assertion, complete original
elaboration and identical hierarchical/flattened primitive-count gates.
The final sixteen-kernel/512-product design has 512 DSP48E1s, 407,352 LUT
primitives and 742 FDCEs, source
`4b98ffb80c5df9de0c191a2ff320f164817df9ffc83fbd4ff0e35a059c76a6ca`.
Its [actual-source archive](runs/2026-10-06-dsp-corrected-full-array-area/index.json)
preserves 87 verified members/51,385,619 bytes, SHA256
`3bf477561b9d8d70ac6ac6c29432757ab9606ec286d9a6597cb48d4cc49ee5d2`;
the independent checksum command exits zero. The earlier archival preflight
failed on a nonexistent supplemental stage-index path before archive creation;
its source and log remain preserved, not relabeled PASS. This is area/structure
only, not full-array numerical, raw-board, packed physical fit,
timing/electrical/DRC or bitstream acceptance.
Four mapped-lane, five literal-contract, four native-admission and six
area/structure control methods pass separately; they are not HDL execution
or physical acceptance. See
[the DSP candidate contracts](../docs/RKNPU_SIZED_CMAC.md#actual-mapped-dsp-lane-replay-and-full-c32k16-dsp-candidate)
for exact commands and live evidence paths. The production `make test` run
does not cover these nested experimental DSP sources.

The actual component SAT job separately passes the 19-bit Booth recoder,
120/128-bit donor carry-save modular-sum lemmas and 16-bit digit reconstruction,
including their real negatives. It then fails before conditional-carry SAT
because the checker omitted the theorem's logical-AND guard. Its
[exact executed-stage/failure archive](runs/2026-10-06-dsp-component-proofs-admission-failure/index.json)
contains 66 verified members/105,426 bytes, SHA256
`3a4585210ecb32cb5bf5cee2413bfd376d5ff3b40d2048fcf4e1ecf5675cbcd9`,
with independent checksum PASS. The corrected fresh suite completes all five
positive SAT proofs and real negatives, including the explicit conditional
carry theorem. Its [completed archive](runs/2026-10-06-dsp-component-proofs-complete/index.json)
preserves 73 verified members/111,921 bytes, SHA256
`4ecd3fbf8c39dcfdd5628b43ff7e70ef814378ae5410fa6b347e4bdedc0622c0`,
with independent checksum PASS. No theorem, assertion or input domain is weakened.

The separate actual conditional full-integer 5×24/4×32 proofs pass with all
120/128 free input bits, 25/33 compared bits and real bit-flip negatives.
Their [archive](runs/2026-10-06-dsp-conditional-tree-integer-proofs/index.json)
preserves 43 verified members/66,805 bytes. The subsequent actual-wiring
unsigned-range audit checks the eight recoders, exact packed tree inputs,
parameters and shifts, then applies those source-identical lemmas. It proves
each 24-bit group sum is at most 11,141,120 and the final 32-bit unsigned sum
at most 2,863,267,840, discharging the conditional carry theorem's no-overflow
requirement. Its [completed archive](runs/2026-10-06-dsp-source-bound-donor-ranges/index.json)
preserves 64 verified members/118,007 bytes, SHA256
`b97485a9af9791923fa8be4ec9d7ebaa20d89af89743ff68bbecc20d4caa55d1`.
The [first strict-notice failure](runs/2026-10-06-dsp-donor-range-admission-failure/index.json)
remains archived. Only the two exact source-bound donor array-lowering notices
are admitted on rerun; unknown warnings fail. Four tree-domain and five current
range-audit admission controls pass separately. These component/range results
alone are not whole-lane, full-array, raw-board, physical or RK acceptance.

The subsequent source-bound integer product certificate now passes with all
fifteen magnitude coefficients and exact bias `0x55550000`, using unchanged
completed recoder/tree/range lemmas and actual donor wiring. Three certificate
corruptions are rejected; no new HDL or SAT execution is claimed for that
certificate. Its [archive](runs/2026-10-06-dsp-unshifted-product-certificate/index.json)
preserves 142 verified members/254,180 bytes, SHA256
`d655bcd21315c831334a7c15db917901e136fc08847e0e492eb740eab9f89906`.
The initial serialization preflight failure and executed source are
[preserved separately](runs/2026-10-06-dsp-product-preflight-failure/index.json).
Six current admission controls pass.

The [composed binary lane certificate](runs/2026-10-06-dsp-composed-binary-lane-certificate/index.json)
now establishes all 37 independent native binary input bits and all 40
compensated sum/tag bits by checked mathematical composition. It binds the
product/no-overflow identities, completed conditional-carry SAT lemma, exact
whole-module glue contracts and all 32 exponent/pair-mask states. Fresh complete
HDL lowering and a real SAT bit-flip countermodel pass. This is not a newly
executed monolithic positive SAT proof; old timed-out proofs remain FAIL.
The archive preserves 175 verified members/374,123 bytes, SHA256
`c6ffcf44c1dc18a30e55b007a1bfff11143a20d926e38d20c57e352365a74326`;
both certificate archive checksums pass independently. Five composition
admission controls pass. This does not cover reset/configuration/X, mapped
primitives, full-array/raw-board or physical FPGA/RK behavior. The actual
mapped-lane and subsequent full-array acceptance gates remain unchanged.

The full DSP raw-board compile preparation completes separately. One literal
array substitution preserves the original raw-command/DMA/CACC/output/BRAM
path and full board bench. Its three admission controls pass; the actual
Icarus 13.0 compile exits zero after 277.936 seconds and confirms all sixteen
cells/512 lanes, excluding baseline/fixed fallbacks. No board mode is executed,
and compilation is not full-array or
raw-board numerical acceptance, physical implementation or bitstream readiness.
Its [completed compile-preparation archive](runs/2026-10-06-dsp-full-raw-board-compile-preparation/index.json)
preserves 118 verified members/5,901,431 bytes, SHA256
`f684b7582b13ebc3b380d22af31685dfe537b849ef6a8171ab4604c12ee4d5c0`.

The subsequent full nine-mode DSP raw-board replay driver is prepared in
`tools/cmac/replay_dsp_board.py`. Nine software admission/marker methods pass,
and its actual read-only validation accepts the completed compiled full board
and composed binary-lane certificate with all nested source and artifact
bindings. It requires the completed 208-frame full native-array positive
before launching any mode. All original known/X corruption, reset/repeat,
transaction-count and watchdog contracts remain required; the original bench
and compiled binary are unchanged. No board mode or bitstream PASS is claimed.
The [new replay-preparation archive](runs/2026-10-06-dsp-nine-mode-board-replay-preparation/index.json)
preserves twenty verified members/134,743 bytes, SHA256
`f77b18a87458f710f9a256d64a5fe6d27ce58dde8512b4585c2cffdd1703544a`.
Its scope explicitly records zero executed modes; the initial archiver import
failure is retained and is not relabeled a successful archival or HDL result.
The independent archive checksum passes. The expanded focused candidate
regression passes all 47 software control methods, including the new nine
board-runner methods; it does not replace actual full-array/board simulation.
See [the exact replay command and scope](../docs/RKNPU_SIZED_CMAC.md#actual-mapped-dsp-lane-replay-and-full-c32k16-dsp-candidate).

The subsequent `tools/cmac/map_dsp_board.py` is prepared with eight passing
mock admission/structure controls; the expanded candidate software regression
passes all 55 methods. It requires completed full-array mapping and actual
nine-mode DSP-board acceptance. Its whole-board flow retains sixteen actual
mapped C32 kernels/512 CMAC DSP products, unchanged kernel primitive/pin-wire
identity, original surrounding raw-board RTL, BRAM and nonconstant original
board I/O. The corrected DSP-stage endpoint and strict unknown-warning/cell
failures remain. No actual complete DSP-board synthesis, mapped numerical,
physical fit/timing/DRC or bitstream acceptance is claimed from preparation.
The [exact source-bound preparation archive](runs/2026-10-06-dsp-full-board-area-preparation/index.json)
preserves 28 verified members/155,967 bytes, SHA256
`cc6668380f62e3d2cd487f855c22c81a35efd78868a8822807ee482304018550`.
The independent archive checksum passes.

The subsequent full DSP mapped-array binary runner is prepared in
`tools/cmac/test_dsp_mapped_array.py`. Nine harness/export controls pass,
including a small actual Yosys 0.65 roundtrip with DSP string parameters;
the expanded DSP control regression passes 80 methods. All actual mapped
primitive parameters, port bits and wiring remain exact, with reversible
instance aliases and separately recorded resolved geometry declarations.
The original 208-frame numerical/hold/tag/reset bench and a fresh failing
first-frame golden-bit control remain required. Its original Verilator
guard excludes only the native X probe; this is explicitly binary-only,
not four-state/GSR, full-board or physical evidence. Completed independent
native/resource parents are mandatory before execution. The
[source-bound preparation archive](runs/2026-10-06-dsp-full-mapped-array-preparation/index.json)
preserves the new sources, actual controls and intermediate failed preflight
logs/snapshots. No full mapped-array numerical or bitstream PASS is claimed.
It contains 67 verified members/218,381 archive bytes, SHA256
`d75009d0425bef588d048246ee8a9ab14fb3b7aca32e432040e588d0378e6bab`;
the independent archive checksum passes.

The DSP-source stock Vivado checkpoint flow is now prepared in
`tools/cmac/vivado_dsp_array.py`, with unchanged raw-board transport, part,
pins, ROM and physical/review gates. Run requires all four completed current
DSP native/mapped-binary/resource/nine-mode board reports, verifies their
source/snapshot bindings and checks sixteen 32-DSP kernels before a checkpoint
and after routing. Actual preparation returns `PREPARED_DSP_ARRAY_VIVADO_ONLY`
at `build/rknpu-dsp-array-vivado/prepare-1791271180004003603/report.json`;
no HDL or Vivado executes. Strict source lint warnings are not waived.
Seventeen admission/build controls pass under both Tcl 9.0.3 and Xilinx Tcl
8.6.13 with Vivado mocked, and 97 DSP software controls pass. Generated and
Python syntax checks exit zero. The
[preparation archive](runs/2026-10-06-dsp-vivado-checkpoint-preparation/index.json)
preserves 282 verified members/587,967 bytes, SHA256
`e5403205bbc5d9e4d1de0d454566d0e47efe7d863b001bd516a418a78402b132`.
The independent checksum command exits zero.
It does not establish actual hierarchy naming, fit, timing/electrical/DRC,
bitstream or FPGA/RK acceptance. That initial emitter did not admit the
DSP profile; the separate build flow remains checkpoint-only.

The subsequent caller-independence control exposes a real fingerprint failure
when an unrelated module is loaded. The old driver/test/log snapshot and exit-one
preflight remain preserved. The corrected driver's referenced dependency closure
retains all 24 actual tools/73 build inputs and produces fresh preparation at
`build/rknpu-dsp-array-vivado/prepare-1791272511421279871/report.json`, source
`b5a2775ee6f559bb7e7ae6d06573b9cacbb5cb631aac015f5c459fca03c1ec89`.
The reviewed emitter now has an explicit DSP-profile branch requiring the
variant's routed status and all four current native/mapped/resource/board parents.
Original human review, electrical, hash, clock, BRAM, setup/hold and DRC gates
remain; the actual checkpoint must retain sixteen 32-DSP kernels before emission.
The real prepared-report CLI probe correctly exits one before emitting anything.
No actual Vivado, bitstream or physical result is claimed from these controls.
The fresh build/admission suite passes 18 methods and the reviewed-emission
suite passes 21 methods under both Tcl runtimes; 98 DSP software methods,
generated-source and Python syntax checks pass. The
[follow-up archive](runs/2026-10-06-dsp-reviewed-emitter-preparation/index.json)
preserves 288 verified members/592,551 bytes, SHA256
`88f98359fcdec8d77c947818f29b56e643dce2a2b62a3bf665c8b776af722332`.
The independent checksum exits zero. Older sources/controls and the actual
caller preflight failure remain preserved, not relabeled as current-source
passes. Full numerical/board/physical acceptance and reviewed emission remain
pending.

The fresh production `make test` session 90266 exits zero and is frozen in
[the separate production archive](runs/2026-10-06-full-dsp-preparation-production-regression/index.json):
1,466 verified members/11,463,601 bytes, SHA256
`b11bd4d2bfeb69dc3c9abaa3bb09f53e0a8d45b924359ebbd42f19aeda317e3f`.
Its independent archive checksum passes. It preserves 247 original entries
and three product benches per simulator, 49 Python methods, 1,087,299 seeded
C++ comparisons and 82 matching cross-simulator memory images. It does not
validate the nested experimental DSP-array or transformed board netlists.

The subsequent fresh production `make test` session 27921 also exits zero.
Its [new source-bound archive](runs/2026-10-06-dsp-stage-fix-production-regression/index.json)
preserves 1,466 verified members/11,463,556 bytes, SHA256
`70b45b7a25df75c1cc71dd0ee021bf100bdca2e02b591e121afd52055053a85c`.
It independently checks the same complete production corpus, source
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`,
with all report times within this fresh run window. No old log is copied onto
modified RTL, and no experimental DSP-array, packed fit/timing, bitstream or
physical FPGA/RK acceptance is inferred.

The subsequent production `make test` session 33524 is also observed exiting
zero. Its [fresh archive](runs/2026-10-06-dsp-full-mapped-preparation-production-regression/index.json)
contains 1,466 verified members/11,463,750 bytes, SHA256
`2c77ea07afb5ec7b71758ca3b7999e69baf7a4a1a5104c7e1689e96afc7afcb3`;
the independent checksum exits zero. The complete unchanged production corpus
passes at source `09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`:
247 original entries and three product benches per simulator, 49 Python
methods, 1,087,299 seeded C++ comparisons and 82 matching memory images.
This is not experimental DSP-array, mapped numerical, physical FPGA or RK
acceptance, and the earlier independent production archives are retained.

The subsequent production `make test` session 46217 exits zero, observed at
08:14:53 UTC. Its [fresh archive](runs/2026-10-06-dsp-reviewed-emitter-production-regression/index.json)
preserves 1,466 verified members/11,463,314 bytes, SHA256
`b5447ed034bfb765abda609b4c313865d9ec3a247c05afce2b236534fd404453`;
the independent checksum passes. It retains the same unchanged production
source, 247 existing entries and three product benches per simulator, 49 Python
methods, 1,087,299 numeric comparisons and 82 matching memory images. No
experimental prefix/DSP-array or physical acceptance is inferred.

The subsequent source-bound production `make test` session 85878 exits zero,
observed at 08:45:03 UTC. Its [fresh archive](runs/2026-10-06-dsp-prefix-carry-production-regression/index.json)
preserves 1,466 verified members/11,462,708 compressed bytes, SHA256
`ce5d3dfbccb7daf892b79bbda51182d74940a6155b7afd3d39d142a9b1543c8a`;
the independent checksum passes. All original production coverage is retained,
not transferred to experimental prefix-array or physical acceptance.

The separate [carry-prefix DSP-lane experiment](../docs/DSP_PREFIX_CARRY.md)
now passes a real 67-input binary comparator SAT proof and all 135,680 native
binary fixtures, including both fresh real negatives. Fresh same-interface
XC7 mapping measures 657 original-DSP-lane LUTs versus 616 prefix-lane LUTs,
with one DSP each. Six harness controls and generated-source checks pass.
The [completed source-bound archive](runs/2026-10-06-dsp-prefix-binary-area/index.json)
preserves 76 verified members/3,487,864 bytes, SHA256
`e46de1ceae79f775f1da8a3054cfc42908754f8497592b21ff1b03feed47d5f1`.
Both actual failed harness/source snapshots are retained in that archive.
There is no all-X, mapped numerical, full-array/raw-board, packed-fit,
physical timing/DRC, bitstream or FPGA/RK acceptance.

The subsequent [actual mapped prefix replay](runs/2026-10-06-dsp-prefix-actual-mapped-lane/index.json)
now completes both fresh native and mapped 135,680-case phases and their real
corrupted-result negatives. Exact export identity and unchanged model/source/
binary bindings are checked; the native prefix body is excluded from mapped
compilation. The archive preserves 123 verified members/42,066,507 uncompressed
bytes, SHA256 `2240b5722eb611a82f6961f366571efa944ceab1c744212b6648773eecb91dec`.
This supersedes only the isolated lane's pending mapped-fixture status, not
all-X, full-array/raw-board or physical acceptance.

The [full prefix-array preparation archive](runs/2026-10-06-dsp-prefix-full-array-preparation/index.json)
preserves 72 verified members/2,906,873 uncompressed bytes, SHA256
`5b71775da684e218e23c7f72cde59ae538235b010fd74b48933088a6c8d6ab1b`.
Real native C32/K16/TAG35 elaboration retains sixteen kernels/512 products and
exact kernel stripes, with original source/NaN/hold/reset/fault derivation.
Nineteen preparation controls and six subsequent area controls pass; these
are software/structural checks, not array numerical or resource acceptance.
After its own mapped leaf passed, the full prefix-array native test compiled,
passed its real first-frame negative, and completed the unchanged 208-frame
positive in 5,305.372 seconds. The
[completed native archive](runs/2026-10-06-dsp-prefix-full-native-pass/index.json)
preserves 87 verified members/70,311,913 uncompressed bytes, SHA256
`6ec8fdd3fa10a2e1591c4676bebd2deadd10ff431da8c1696682582817e3d16f`.
All 3,328 outputs, 520 held cycles, sixteen reset cancellations and the
native X-input fault case pass under Icarus/vvp 13.0. Exact source, compile,
binary, stimulus and actual logs are reverified before and after packing.
This supersedes only its pending native-fixture status; mapped/raw-board
numerical, exhaustive-X and physical acceptance remain separate.
The first full-array resource run returns zero
from Yosys but fails its native-only diagnostic checker on two ABC `scorr`
combinational-cut notices; no area acceptance is inferred. Its
[executed-source failure archive](runs/2026-10-06-dsp-prefix-array-mapping-diagnostics-failure/index.json)
preserves 69 verified members/783,887,762 uncompressed bytes, SHA256
`7b1c05453e4418dd97883296699c2a401633c68cdb5443db5a4c51463a3627a3`.
The independent checksum passes. A fresh full synthesis with exact module,
step, completion and diagnostic-count checks now completes at
`build/rknpu-dsp-prefix-array-area/1791280469545641864/report.json`, source
`13fc1cf854926b5af17529afcfd84ad85d9b8083fd1e112182af858400568c57`.
Actual mapping takes 978.315 seconds and its make supervisor exits zero.
Native/partition/flattened structural gates retain sixteen kernels, 512 DSPs,
398,168 LUT primitives and 742 FDCEs. This is area/structure evidence only;
the original FAIL is not relabeled, and physical gates are unchanged.
The [completed own-area archive](runs/2026-10-06-dsp-prefix-full-array-area/index.json)
preserves 126 verified members/813,738,102 uncompressed bytes, SHA256
`3fb7b98a7fe50fee69b1b4136a88db96e490531279527ef70db3a5ebb6bbd1de`.
The independent admission verifier rechecks actual stripes, saved source and
artifact bindings, diagnostic context and partition/flat primitive identity
before and after archiving. Numerical and physical acceptance remain separate.

The [own prefix raw-board preparation archive](runs/2026-10-06-dsp-prefix-raw-board-preparation/index.json)
preserves 431 verified members/112,328,879 uncompressed bytes, SHA256
`4f27d5746b67411d5239a9bdf6f6e5b797a20c909b626e4bf5d3b249c776911b`.
Actual ROM check and Icarus 13 compilation pass in the completed report;
compilation takes 52.436 seconds and retains one array/sixteen cells/512
lanes/512 carry helpers, with no fallback hardware. Its donor-to-compensated-
to-prefix binary certificate is verified read-only, not a new monolithic SAT.
The nine-mode replay and full mapped-array binary runner are prepared. All
53 software controls in that preparation archive pass with no skips, including a real small Yosys
export/readback check. Actual commands refuse pending native/area parents
before numerical execution. Both checker/control and archiver-precheck
failures retain executed source/logs. No board mode, full mapped numerical,
physical FPGA or bitstream PASS is claimed.

After native completion, its independent full nine-mode raw-board replay now
passes; the 208-frame actual mapped-array compiler subsequently exits zero but
fails its strict missing-pin diagnostic gate before numerical replay. The new whole-board mapper
and native-shell frontend preparation plus real library export add 17 controls;
all 70 current prefix
software controls pass. The initial frontend constant-input control failure
and its exact executed source/test are retained, with the missing full port
guard added rather than weakening the expectation. The frontend stops before
synthesis and cannot stand in for board mapping, numerical or physical gates.
All nine raw-board modes now pass, including the original X-readback fault.
The suite finishes at 12:57:51 UTC with source
`c14e5d8cb50d7eff42739880b10bfdc29c7ff1ef8edde960034dc0a06db49577`.
Full-board mapping has been launched using its own completed area and raw-board
parents; no full-board resource or physical acceptance is claimed. The fresh
all-nine suite's [completed archive](runs/2026-10-06-dsp-prefix-full-nine-mode-raw-board/index.json)
preserves 507 verified members/16,460,558 compressed bytes, SHA256
`ecb008874c69d4141c67a937f2d429b9b2218ecd18b94a6e68edae63c9e2ccee`.
All source/input/binary/parent bindings and actual complete mode logs are
revalidated before and after packaging. Full-board synthesis is now live at
`build/rknpu-dsp-prefix-board-area/1791291727991236024/report.json`, source
`be55d57e08c7e2807d4785b6d116393084d9c7f8fde04ae32d6bc88442a1c9ba`.
The fresh
[current 70-control archive](runs/2026-10-06-dsp-prefix-70-profile-alias-controls/index.json)
preserves 126 verified members/1,182,625 uncompressed bytes, SHA256
`7192c8fe7ba09274f0359169e2242cfca0327740b2aeeaca219b3d8377cd1dec`.

The first full frontend actually fails while JSON serializes a blackbox FDCE
library process, after reporting zero structural CHECK problems. Its
[executed-source failure archive](runs/2026-10-06-dsp-prefix-board-frontend-library-process-failure/index.json)
preserves 193 verified members/114,321,757 uncompressed bytes, SHA256
`f8f8c67bcfb9933c13c4fe65dff85e9b44e67d56ac327f89259d1c6ddce6d587`;
the independent checksum passes. Design-only export leaves native modules and
mapped circuits intact and omits only existing library blackbox definitions.
A real DSP/FDCE export control passes its original failure negative and exact
native-module/primitive/parameter/pin-incidence comparison. Its initial
baseline-setup failure retains executed source/logs. The second actual run
returns zero from Yosys but remains FAIL at its source-specific profile
diagnostic guard. Read-only inspection additionally identifies a mapped-array
`hdlname` alias mistaken for a second parameter wrapper. Its
[executed-source failure archive](runs/2026-10-06-dsp-prefix-board-frontend-profile-diagnostic-failure/index.json)
preserves 193 verified members/118,715,196 uncompressed bytes, SHA256
`22fcdd2a1cf7e6d46b0bcd023870619ec58dc3146b1d1e72afdd1d3c69314f12`.
Both original failures remain FAIL; diagnostic, source and full circuit guards
are corrected without changing hardware or negative expectations.

The fresh third full frontend now completes under Yosys 0.65 in 169.251
seconds at source
`416afc693761a9c62176dcca0a5212365031a91e46551b1465ff0a28db385bfb`.
Its [completed source-bound archive](runs/2026-10-06-dsp-prefix-board-mapping-preparation/index.json)
preserves 228 verified members/118,972,621 uncompressed bytes, SHA256
`d2935a0db30be5892c095defeab2ced258f9d8eb3d9b4ea0f17331c5bfa42501`.
One parameter wrapper, the imported array and all sixteen kernels retain exact
port/cell/primitive/parameter/pin incidence identity; all 512 CMAC DSPs remain.
This is imported-array/native-shell frontend preparation, not whole-board
synthesis, mapped numerical, physical implementation or FPGA/RK acceptance.

The [prefix-specific Vivado checkpoint-preparation archive](runs/2026-10-06-dsp-prefix-vivado-checkpoint-preparation/index.json)
preserves 173 verified members/400,266 compressed bytes, SHA256
`c7f8e4731fadbb51a42eb790a32287bbc64c31b29821d05c6e9f2427a575e31f`.
It binds 77 source files at
`b0508d3be9c28960608f074052ad13fc859675ad796867f70968e37d8215c741`.
All 18 build/admission controls pass under each of Tcl 9.0.3 and vendor Tcl
8.6.13. The initial unwrapped vendor-Tcl startup failure is preserved; the
installed loader supplies its missing library environment. All Vivado calls
remain mocked. Own current native/mapped/area/all-nine-board evidence, full
Vivado, original electrical/timing/DRC review and 512 post-synth/post-route CMAC
DSPs are mandatory. No checkpoint or bitstream is generated in preparation.

The subsequent fresh production `make -j2 -o vectors -o cmac-vectors test`
also exits zero (session 12063). Its
[source-bound archive](runs/2026-10-06-dsp-prefix-mapping-diagnostics-production-regression/index.json)
preserves 1,466 verified members/11,462,415 compressed bytes, SHA256
`a0b07914de68b7c7b6a62a2e0f561c9cabaeb44278e8c3f25e97fd5774394820`;
the independent checksum passes. It retains unchanged production source
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`,
247 existing entries and three product benches per simulator, 49 Python tests,
1,087,299 seeded numeric comparisons and 82 matching memory images. The
archive freezes executed build inputs before the new prefix test-target
additions. It does not validate experimental prefix arrays or physical FPGA.

The later production regression also exits zero (session 91531), with the
same unchanged production source, corpus and generated-vector bindings. Its
[fresh source-bound archive](runs/2026-10-06-dsp-prefix-board-mapping-preparation-production-regression/index.json)
preserves 1,466 verified members/11,462,582 compressed bytes, SHA256
`a98c9ce5c79a6e5157028638a19f4df53b937f44368316bb4067b8c4ca1d5cd7`.
The independent archive checksum passes. The fresh `make test` after prefix
Vivado preparation also completes with actual exit zero (session 37833).
Its [fresh source-bound archive](runs/2026-10-06-dsp-prefix-vivado-preparation-production-regression/index.json)
preserves 1,466 verified members/11,462,095 compressed bytes, SHA256
`900f70fbad99b850b3db5f2c03b0793d327e4b4c4009b3c36ffe5c15c84a1de6`.
Its independent checksum passes, and the current production source is still
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
This does not transfer acceptance to the new nested experimental sources.

The [actual unchanged primitive-model Verilator archive](runs/2026-10-06-dsp-prefix-primitive-model-verilator/index.json)
preserves 50 verified members/1,367,128 compressed bytes, SHA256
`e27e7fce2e5660e699b504a60f8b9a631e4cca7fc383b0af22d17a9658b7e3db`.
It completes 4,259,904 DSP and 1,024 binary carry comparisons and both real
wrong-golden negatives, using the parameters/bias of all 32 actual-kernel DSPs and
unchanged installed model. Four source/result controls and a fresh combined
92-method preparation suite pass. The archive freezes the disconnected-alias
audit (449 warnings/4,673 alias bits, no port or primitive-pin connection) and
a saved prefix of the live main compiler log. It admits no main diagnostic,
full-array, raw-board or physical result. Live Icarus exhaustive four-state
model, mapped-array and raw-board runs are excluded.

The [completed source-bound Icarus primitive-model archive](runs/2026-10-06-dsp-prefix-primitive-model-iverilog/index.json)
now preserves 18 verified members/958,649 compressed bytes, SHA256
`ce5be3ac5551c1cb159ac610901766e12435129996b8a4e34a7c233e27982140`.
It completes 4,259,904 DSP, 1,024 binary carry and 1,048,576 four-state carry
comparisons, with both original real first-case wrong-golden negatives.
Its source is `5dd8a5c107cb9f97ad0be29cbc6cce7d05da355efb3ddaad81b94e08d1da4e55`;
Icarus/vvp 13.0 finishes at 13:15:37 UTC. Positive/real carry-negative times
are 1,706.964/1,192.661 seconds. It is still isolated primitive evidence.

The main actual mapped-array compiler then finishes at 13:21:17 UTC with
Verilator return code zero after 8,919.809 seconds. Its strict harness rejects
`PINMISSING` at exported source line 170398, before top generation or replay.
The [completed original failed report](../build/rknpu-dsp-prefix-array-mapped-binary/1791283708506179317/report.json)
and compiled library are preserved; no numerical PASS is claimed.
The [executed-source compiler-failure archive](runs/2026-10-06-dsp-prefix-mapped-compile-diagnostic-failure/index.json)
preserves 179 verified members/50,309,059 compressed bytes and all 87 completed
compile products, SHA256
`b703a49b3f16d2ba156f735b9f0ec79536ff8685942ac0be5e68b335d718b5c4`.
Its original diagnostic rejection and completed independent parents are
revalidated before and after packaging. No original failure is relabeled PASS.
The [completed actual-model omitted-pin cone archive](runs/2026-10-06-dsp-prefix-omitted-pin-cone/index.json)
preserves 28 verified members/978,568 compressed bytes, SHA256
`24b97dc14df47ea1cbe80aa28015d7fab092075fd19d07c4c3ea7d704beb34e6`.
Every omitted DSP input is independently unconstrained. The actual zero-register
P cone reaches only A[24:0]/B[17:0]; the real legal registered counterexample
reaches CEA2/CLK/RSTA and is rejected. Model bytes are unchanged, and YOSYS
preprocessing of simulation-only checks is recorded.
The [read-only completed diagnostic inventory](../build/rknpu-dsp-prefix-compile-inventory/1791293575685709813/report.json)
accounts for 10,594 notices and bijectively binds all 1,152 missing-pin notices
to 32 actual DSPs: 832 input and 320 output notices. Fourteen primitive/cone/
inventory software controls pass. Width, initialization, combinational scheduling,
carry-vector and disconnected-alias diagnostics remain unadmitted. No warning
class, DUT/model behavior, numerical case or error expectation is weakened.
The [completed read-only inventory/control archive](runs/2026-10-06-dsp-prefix-completed-compile-inventory/index.json)
preserves 33 verified members/4,274,007 compressed bytes, SHA256
`8574bbce256900858ba7e9e1959a8dd3ea6d6fbe595d183374e96f4887dcad7c`.
The preceding source-identical production `make test` is terminal FAIL: both
247-entry original RTL suites and 1,087,299 numeric comparisons pass; two
Verilator product benches pass, but the third build exceeds its unchanged
600-second limit. Product Icarus does not execute. The
[actual failed attempt archive](runs/2026-10-06-dsp-prefix-production-snapshot-compile-timeout/index.json)
preserves 2,798 verified members/230,217,549 compressed bytes, SHA256
`aa81413e17d2c4a6b1a9f14b7998743fca94ce77d834fd93dceb71082293be75`.
Original production outputs are unchanged, and no old PASS is copied into this attempt.

The subsequent [fresh literal snapshot](../build/rknpu-dsp-prefix-pin-cone-production-regression/1791300029293915642/report.json)
is terminal PASS at unchanged production source `09f1c3f65ba9...`: 49 Python
tests, 1,087,299 numeric comparisons, both 247-entry RTL suites, all three
product benches under each simulator and 82 equal memory images. The actual
`make -j2 -o vectors -o cmac-vectors test` command exits zero after 2,045.520
seconds. Only vector generation is held; every test target executes. The
preceding timeout remains FAIL. This does not validate nested prefix RTL,
physical fit/timing/DRC or RK silicon.
Its [completed literal-source archive](runs/2026-10-07-dsp-prefix-fresh-production-snapshot-pass/index.json)
verifies 2,812 members/230,342,315 compressed bytes, SHA256
`3cd8d0ec17f7f771124e0ca0197bfedf50f6e929c2423177fbce76b7f1ea7b0a`.
The [newest actual production snapshot](../build/rknpu-dsp-prefix-pin-cone-production-regression/1791310099280059265/report.json)
also completes PASS at the same production source: 49 Python tests,
1,087,299 numeric comparisons, both 247-entry RTL suites, all three product
benches per simulator and 82 equal memory images. Its actual complete
`make -j2 -o vectors -o cmac-vectors test` exits zero after 2,675.892 seconds;
the older archive is not relabeled as evidence of this newer run.
The [separate full-prefix mapped-board runner](../tools/cmac/test_dsp_prefix_observed_mapped_board.py)
and pinned DSP-model profile have [eight passing controls](../build/dsp_prefix_observed_mapped_board_controls_20261007.log).
The [first full-size attempt](../build/rknpu-dsp-prefix-observed-mapped-board/1791313743637550758/report.json)
completed its own mapping/native prerequisites and the real Yosys export
roundtrip with exact whole-circuit port bits, parameters and pin/wire incidence.
Executed source is `8f1055fe4bb5...`; the actual Yosys 0.65 export exits zero
after 138.954 seconds. Its supervisor was interrupted during Icarus/vvp 13.0
compilation. A [fresh host-wide observation](../build/dsp_prefix_observed_mapped_board_interruption_observation_20261007.json)
confirms no compiler or supervisor remains. The [897-file interruption archive](runs/2026-10-07-dsp-prefix-observed-mapped-board-interruption/index.json)
verifies all stored bytes independently, including the unchanged stale
RUNNING report and 1,054,777,344-byte unaccepted partial executable. Its
213,260,499-byte archive has SHA256
`b879f1c9feb02f213b6a28b52e2a50901844d5a94fbb11f933e3bf4e696b77c8`.
It establishes neither a compiler returncode nor numerical/RTL acceptance.
An [unchanged-source fresh retry](../build/dsp_prefix_observed_mapped_board_retry_launch_20261007.json)
ran under host user service
`rknpu-dsp-prefix-observed-mapped-board-retry-20261007.service`, with a
separate master log and fresh output directory. Its [fresh report](../build/rknpu-dsp-prefix-observed-mapped-board/1791355721215888508/report.json)
records source `340b978a3717...` and actual Yosys export PASS in 115.705 seconds.
Icarus 13.0 compilation returns zero after 3,369.436 seconds with its existing
diagnostic gate satisfied. The [immutable compile-only observation](../build/dsp_prefix_observed_mapped_board_retry_compile_pass_20261007.json)
independently verifies executable SHA256
`b1ca3a1f5f5292bc84ec45f9986863437a033d4c4ee3627f7fe98ad9d72b01f3`.
Its real same-executable negative now completes the intended first-output
golden-bit rejection with return code 1 in 6,689.497 seconds. The
[actual negative log](../build/rknpu-dsp-prefix-observed-mapped-board/1791355721215888508/negative.log)
records that exact mismatch. At the 2026-10-07 11:20 UTC live-process
observation, positive mode 0 was running and no positive mode had completed.
The run later ends as FAIL at 13:44:26 UTC with `TimeoutExpired` on mode 0's
unchanged 14,400-second wall-time budget. The command records 14,405.105
seconds including termination, an empty positive log and no recorded return
code; no numerical mismatch or positive PASS is inferred. The supervisor
exits with status 1, and no supervisor or simulator remains.
The [903-member terminal failure archive](runs/2026-10-07-dsp-prefix-observed-mapped-board-timeout/index.json)
independently verifies all stored bytes and actual source/circuit/bench/model
bindings. Its 326,660,967-byte archive has SHA256
`742881ea8675e7e6bd5a16088a4e9c20c6aebeed9fcb325164af83c7a0479813`.
The original report remains FAIL with zero completed positive modes. A fresh
check revalidates the accepted executable/compile-input hashes and identical
negative/mode-0 execution-input identities, including the exact first-output
negative fixture; it does not rerun HDL or establish positive acceptance.
All nine unchanged numerical modes remain necessary; no mapped-board
numerical or physical acceptance follows from the negative alone. Any
longer-budget replay must be separately source-checked and leave this failure
unchanged.
Separate [initial runtime samples](../build/rknpu-dsp-prefix-observed-mapped-board/1791355721215888508/runtime_mode0_stack_observation.json)
and a [hash-bound follow-up](../build/rknpu-dsp-prefix-observed-mapped-board/1791355721215888508/runtime_mode0_stack_followup_observation.json)
record simulated time advancing from 0.97 to 6.31 to 184.09 microseconds.
Their raw readings, time-unit conversions, clean debugger detaches and explicit
nonacceptance flags have been independently checked. They establish scheduler
progress between observations only, not a completed command, output, mode,
numerical suite or physical gate. The executed source and compiler inputs are
unchanged; these diagnostic metadata files are outside those manifests.
A recorded 26/27-GiB soft/hard host memory guard applies only to this service.
Compiler completion and host-memory recovery precede the guard application;
the full 512-product source, compiler inputs, fixtures and acceptance rules
remain unchanged. This is a host execution limit, not physical-fit evidence.
The terminal-run archive tool has three passing controls, refusing live/partial
or cross-profile PASS and never promoting an actual FAIL. Fresh re-execution
of those three controls and `make generated-check` passes. The separate
interruption builder does not weaken that tool's admission gate. The terminal
retry bundle preserves a timeout failure, not a numerical PASS.
The separate [longer-budget continuation](../tools/cmac/resume_dsp_prefix_observed_mapped_board.py)
rechecks the exact failed profile, source/circuit/bench/model bindings, every
archived member and the accepted executable/compile inputs before reuse.
It re-executes the real negative and all nine original modes, checking the
runtime program and input/executable identities around every simulation.
Only the host wall budget is lengthened to 24 hours per command; HDL timeouts,
full C32/K16/512 geometry, 20 ns clock and functional/physical gates are unchanged.
The old report and archive remain FAIL. Its [actual software qualification](../build/dsp_prefix_observed_board_resume_qualification_20261007.json)
records eight new continuation controls, eight original replay controls,
three original archive controls and generated checks, all with return code 0.
The [14:15 UTC live-launch evidence](../build/dsp_prefix_observed_board_resume_launch_20261007.json)
records the [mapped continuation](../build/rknpu-dsp-prefix-observed-board-continuation/1791382468965621354/report.json)
in admission and a separate [complete production make test](../build/rknpu-dsp-prefix-pin-cone-production-regression/1791382469904905494/report.json)
running in a source-identical snapshot, preserving existing results and
live replay inputs. Launches, software fixtures and running service status
are not numerical or physical acceptance. The distinct continuation PASS
profile requires its fresh negative plus all nine modes; the old terminal
archiver intentionally refuses it. Do not start a duplicate live job.
The [separate continuation archiver](../tools/cmac/archive_dsp_prefix_observed_board_continuation.py)
requires a terminal admission-bound report and rechecks the original failure,
bundle, circuit/model/binary/input contracts. It verifies only fresh logs
inside this continuation's own directory, with exact runtime argv, fixture
cwd, return codes, mode results and transaction/error counts. FAIL is not
promoted. Its [actual software qualification](../build/dsp_prefix_observed_board_continuation_archive_qualification_20261007.json)
records seven new archive controls plus all 19 earlier controls, generated
checks and the actual CLI's status-1 rejection of the RUNNING report without
creating a bundle. The original archive gate and running replay source are
unchanged. This does not establish a terminal bundle, HDL completion or a
physical/RK-silicon PASS.
Separate [whole-board RAM normalization diagnostics](../docs/DSP_PREFIX_BOARD_NORMALIZATION.md)
now complete actual full mapping in 1,785.453 seconds and verify all 54
RAMB36E1 port changes: 32 reported plus 22 silent constant-only input resizes.
The final circuit matches the original full board, with all sixteen kernels
and 512 CMAC DSPs plus three shell DSPs/six BRAMs. Its
[254-member independently revalidated archive](runs/2026-10-07-dsp-prefix-full-board-ram-normalization/index.json)
has SHA256 `902f302c3db398cd524e1497e38e58ce8052af6001a3ed6fe570507f6c57426a`.
The separate [initial-driver capture](../build/rknpu-dsp-prefix-initial-driver-fanout/1791305786269181565/report.json)
completes in 209.197 seconds; all 288 warning bits have actual consumers.
The [corrected connectivity audit](../build/rknpu-dsp-prefix-initial-driver-cones/1791306673247975368/report.json)
now proves their 107 pure-mux cones unobservable and wholly removed after
cleanup, with 14 passing software controls. Its initial tuple/list harness
failure is [archived before correction](runs/2026-10-07-dsp-prefix-initial-driver-cone-harness-failure/index.json).
Separate [exact-line structural diagnostic admission](../build/rknpu-dsp-prefix-board-diagnostic-admission/1791306879354271482/report.json)
now passes at source `040acb13f113...`, recomputing both proofs and all original
remaining structure/numerical-parent gates. Eight software controls pass;
the original failed mapping report/gate remain unchanged. Its
[completed independently revalidated archive](runs/2026-10-07-dsp-prefix-board-diagnostic-admission/index.json)
repeats the actual proof/circuit/structure audits, preserving both preceding
counter harness failures; no archive PASS is inferred from either failed attempt.
The [original mapped-board bench probe](../build/dsp_prefix_mapped_board_bench_binding_actual_20261007.json)
refuses twelve missing/dead/recoded observations, including the eleven-bit
recoded state. The [source-bound full-board retention frontend](../build/rknpu-dsp-prefix-observed-board-preparation/1791307426641654447/report.json)
now passes actual Yosys 0.65 execution in 174.340 seconds, source
`3cfdd9b91aaf...`, preserving all 22 original observations, the four-bit state
and unchanged sixteen kernels/512 products. Its four script controls pass;
no remapped or full-board numerical/physical result is claimed from preparation.

The subsequent [actual observation-preserving remap](../build/rknpu-dsp-prefix-observed-board-mapping/1791308955335106261/report.json)
now passes at source `94527de2feb6...` after 2,634.549 seconds: all original
observations/state and sixteen kernels/512 CMAC products survive, with fresh
strict RAM/diagnostic/structure gates and four zero-problem CHECK results.
Counts are 445,816 LUT primitives, 17,519 flip-flops, 515 DSPs and six BRAMs.
Its 294,538 estimated logic cells do not prove placed fit or timing, and no
whole-board numerical PASS follows.
The [completed source-bound mapping archive](runs/2026-10-07-dsp-prefix-full-observed-board-mapping-pass/index.json)
verifies 767 members/60,467,297 compressed bytes and records the checked
installed-tool hashes; it is not an independent synthesis or numerical rerun.
Its initial help-only
startup failure is [frozen before correction](runs/2026-10-07-dsp-prefix-observed-mapping-help-guard-failure/index.json);
ten corrected controls pass. The separate
[actual 32-kernel/3-shell DSP export control](../build/rknpu-dsp-prefix-board-export-control/1791310216574124677/report.json)
passes real Yosys roundtrip identity at source `8d7ae8d96419...`, with six
controls and the [private-name failure](runs/2026-10-07-dsp-prefix-board-export-private-name-failure/index.json)
preserved before reversible aliasing. This is not whole-board export acceptance.
The [pinned vendor-model initial unknown failure](runs/2026-10-07-dsp-prefix-unisim-initial-unknown-failure/index.json)
is preserved before a testbench-only input-settling correction and stronger
known-result negative checks. Seven controls pass; the actual settled positive
now finishes FAIL at case 1,027 after complete DSP/binary carry execution.
Its [source-bound failure archive](runs/2026-10-07-dsp-prefix-unisim-legacy-carry-oracle-failure/index.json)
retains the original full-corpus failure, both real negatives and the exact
simulation-time/control-flow witness; no old four-state PASS is inferred.
Fresh complete production regression remains live. The separate
[vendor carry truth-table archive](runs/2026-10-07-dsp-prefix-unisim-carry-truth-pass/index.json)
now preserves all 1,048,576 actual vendor-oracle comparisons and the real
wrong-golden negative at source `1cb2df295368...`: 415,001 old-oracle four-state
differences remain explicit, first at case three; all 1,024 binary cases agree.
The combined 27-method control suite passes. See
[scope and actual evidence](../docs/DSP_PREFIX_BOARD_NORMALIZATION.md).

The [actual model binary proof archive](runs/2026-10-06-dsp-prefix-actual-model-binary-proof/index.json)
preserves the completed all-74-input/all-48-P-bit signed-product/bias proof
and real SAT negative. Its initial width-shape failure is frozen separately.
The whole-board mapper exits zero after 2,737.486 seconds but remains FAIL
at its strict diagnostic gate. Its
[433-member failure archive](runs/2026-10-06-dsp-prefix-whole-board-diagnostic-failure/index.json)
and [53-member read-only structure inventory](runs/2026-10-06-dsp-prefix-board-diagnostic-structure-inventory/index.json)
preserve exact original sixteen-kernel wiring and completed counts: 442,838 LUTs,
17,310 flip-flops, 512 CMAC plus three shell DSPs and six BRAMs. Accounting for
288 early temporary-driver notices and 32 RAM width normalizations does not
admit warnings or prove RAM padding/dataflow, numerical behavior or placed fit.
The later source-bound before/after RAM audit above separately establishes
padding/dataflow safety for this exact run, without promoting the old FAIL.

Source-specific closed-kernel admission now succeeds using actual cone/proof,
disconnected-alias and completed primitive evidence. The first actual top
generation returns zero but rejects two new notices; its
[214-member failure archive](runs/2026-10-06-dsp-prefix-mapped-continuation-top-diagnostic-failure/index.json)
preserves that result. The unchanged FDCE models pass 129 checks and a real
negative in each simulator; their
[68-member archive](runs/2026-10-06-dsp-prefix-actual-fdce-startup-reset-controls/index.json)
retains actual INIT=X/reset behavior. Only its exact initial-assignment site
and one redundant invalid-signal alias are supported by the new top admission.
A subsequent actual attempt passes those admissions but fails a combo-only
generated-interface expectation; its
[130-member failure archive](runs/2026-10-06-dsp-prefix-generated-top-interface-guard-failure/index.json)
records missing early source capture honestly. A separately bound corrected
interface contract verifies all operand/mask/output widths and the actual
combo_update/any-change-weight seq_update callbacks without rewriting the model.
Its four controls pass, in addition to the 23 preceding diagnostic methods.
The subsequent actual full replay matches all 208 frames/3,328 outputs, 520
held cycles and sixteen reset cancellations, with a fresh real negative.
Two GNU `ar` errors are masked by the stock make recipe despite exit zero;
the [291-member qualified archive](runs/2026-10-06-dsp-prefix-full-mapped-replay-unadmitted-ar-diagnostics/index.json)
retains the observed numerical result but refuses complete build/mapped gate
acceptance. SHA256 is
`9f41f7ababa0eeb48ddb6b1aaf6903e6264906cb833c3d366ae3c04097bca9dd`.
A fresh run changes only the equivalent hierarchy-library make path and
independently rejects archive/link diagnostics. Its compilation is clean and
all ten original kernel/nine top objects are verified in the merged archive;
the real negative passes and the complete positive now passes all 208 original
frames/3,328 checked outputs, 520 holds and sixteen reset cancellations.
Its [actual closed report](../build/rknpu-dsp-prefix-array-generated-top-replay/1791299462883001240/report.json)
is source `9296473e960bc6fb6da061ac741fa4072e3711e909dc7f0bff7a2ccd2386927a`.
Six new
build controls pass (33 diagnostic methods total). Eight new checkpoint
admission controls and the original eighteen physical-flow mocks also pass;
the independent source/parent admission now passes this actual completed
result. Its [clean 380-member archive](runs/2026-10-06-dsp-prefix-full-clean-mapped-replay/index.json)
has verified SHA256
`ed23af42cdc78e4c0faf46f9fbc0c45e6f70757a7e9d930c436610c07259399e`.
The fresh 112-method preparation suite also passes, with
emission mocks under both Tcl runtimes. None establishes electrical facts,
implementation, bitstream, physical FPGA or RK3588 evidence. A fresh isolated
production `make test` is running and is not assigned an old PASS.

The [actual four-parent checkpoint preflight](../build/rknpu-dsp-prefix-checkpoint-preflight/1791300567915026382/report.json)
also completes: own native, clean mapped, area and all-nine-mode four-state
raw-board evidence are revalidated together, with unchanged full geometry,
exact part and 20 ns constraints. It binds 97 source inputs at
`aaaf21a87dc802ca1972c6a8de5ede6851529458e9c6ae1b0d65396bbb747e1f`
and retains 105 source/package artifacts. No Vivado is invoked, routed DCP or
bitstream produced. A real emitter review-template request against this
preparation status exits one before review/output creation: completed routed
implementation is still mandatory.

The new prefix-only reviewed emitter's 20 admission/emission methods pass
under Tcl 9.0.3 and AMD Tcl 8.6.13 with all Vivado operations mocked. The
actual prepared Vivado report is rejected with exit one before output/tool
creation. Own completed native/mapped/area/all-nine-board parents, current
routed implementation and explicit electrical/report review are mandatory;
only a sixteen-kernel/512-product guard is added to the original physical
emission template. No bitstream or programming result is claimed.
The [completed source-bound emitter preparation archive](runs/2026-10-06-dsp-prefix-reviewed-emitter-preparation/index.json)
preserves 128 verified members/282,421 compressed bytes, SHA256
`0c8268f47a251b2468a4eba17d2e74a4e3b1d80d0b134359c471bd1c5c6f4d21`.
Its 38-file control closure is
`7d034899d6566f5ea17717b164e58157924d0dbc4b98a2fd27be6fee873e91e7`.
The current aggregate passes 112 distinct preparation methods without skips;
the 20 emitter methods are repeated under both Tcl runtimes. Live numerical
runs are excluded from this archive and are not relabeled accepted.

## Staged donor numerical pipeline

The [C32/K16 mapping archive](runs/2026-09-22-c32k16-mapping-recheck/index.json)
preserves completed synthesis and the passing primitive-aware recheck, with
1,154 verified members. It records 512,248 LUT primitives and no DSP blocks;
mapped numerical replay and physical fit remain unverified. The original
failed timing-metadata counter report is retained, not relabeled.

The separate [fixed-FP16 helper area archive](runs/2026-09-22-fixed-fp16-row-area/index.json)
records 937 versus 668 LUT primitives under identical helper input contracts
and synthesis stages. It is not a full-array resource or correctness result.
The specialization separately passes 2,097,152 donor row/tag comparisons.
The original monolithic formal attempt timed out; the original full-array
attempt failed on an unused timestamp in a generated simulator wrapper.
Both failures remain recorded. A boolean-lowered arbitrary-operand row proof
passed diagnostically on 2026-10-05, alongside a passing configuration lemma.
The fresh source-bound runner now completes with both SAT proofs and all
2,097,152 comparisons/four resets passing:
`build/rknpu-fixed-fp16-rows/verilator-1791207221389481729/report.json`, source
`f4b75c99987b5d67da76f3281270a25ea2f07451a8096aa57220dad9da8fdaa8`.
This is composed post-configuration helper equivalence only. The fresh
fixed-array native run now passes at
`build/rknpu-cmac-array/c32k16/fixed-hierarchical-1791208877880399503/report.json`;
all 208 frames/3,328 outputs and the original hold/reset checks pass, with
source `99d2995a83400a902a0997772632cf4a7c9ba3c040a2cc9a20b9b0cc51054dfa`.
The [composed helper proof archive](runs/2026-10-05-fixed-fp16-composed-proof/index.json)
preserves 26 verified members, SHA256
`a8c81bd5d9e42543fd2037e523de7dfc76ab5c84cde4f4730c1017516588f574`.
The completed [fixed full-array native archive](runs/2026-10-05-fixed-c32k16-native/index.json)
preserves 1,363 verified members, SHA256
`d0830483825d90eeda6bfb2dc379937000648ed3d7cfc426b7e54d9848457fc8`.
No full fixed-array mapped numerical or physical pass is claimed.

A separate actual XC7-helper numerical replay was launched at
`build/rknpu-fixed-fp16-rows/mapped-iverilog-1791212868241216795/report.json`,
source `7d440d0e78018090fe2d56cf265392718ef33ab00d3740000f0d989e98cf66fc`.
It uses the completed helper area's actual `fixed_mapped.v`, original NVIDIA
reference RTL and unmodified Xilinx functional primitive models. The original
2,097,152 row/tag comparisons, four reset/setup calls and seed `3588f016` are
retained. Only the DUT/module names, PASS marker, input initialization at 1 ns
and a 200 ns default-GSR startup wait change in a generated bench copy. The
first attempt's declaration-time initialization leaves primitive outputs
unknown at the first comparison and remains FAIL at
`build/rknpu-fixed-fp16-rows/mapped-iverilog-1791212639598868648/report.json`.
The fresh run changes only the external harness initialization, retaining
every case-inequality and coverage check; no vendor model or DUT is changed.
Five harness-only controls pass in
`build/fixed_rows_mapped_controls_20261005.log`. No completed mapped result is
claimed yet, and this isolated helper cannot establish full C32/K16 mapping,
routed delays, fit, electrical validity or physical FPGA/RK acceptance.
On 2026-10-06 the original supervisor session 50087 completed with exit 143
(SIGTERM), but its exact simulator child, PID 351851, remained live under PID 1.
The old report's RUNNING field is therefore not proof of a live supervisor or
completed acceptance. The child is not killed/restarted; a read-only GDB 17.2
exit observer is attached, with output in
`build/mapped_rows_orphan_gdb_20261006.log`. Its eventual real inferior exit and
complete numerical marker must be observed before any completed result is used.

A new binary-only mapped-helper symbolic check now passes at
`build/rknpu-fixed-fp16-rows/mapped-formal-1791218804185727590/report.json`.
Status is `PASS_MAPPED_FIXED_FP16_ROWS_BINARY_FORMAL_ONLY`, source SHA256
`fba405afef9b283d7edb70caed72f5f77d564dd8b278e288965ccabea276c99b`,
using Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`).
It compares both partial rows and the tag against unchanged experimental RTL,
retains all 37 relevant binary input bits, and requires the completed composed
donor configuration/datapath proof. Actual installed Yosys LUT/MUX truth tables
are frozen unchanged; no arithmetic blackbox or input assumption is allowed.
A deliberately flipped comparison bit must yield a real countermodel.
The actual negative SAT check finds that countermodel in 14.268 seconds;
the unchanged comparison proves all 72 output bits in 19.684 seconds.
Eight synthetic graph/miter safety methods pass in
`build/mapped_rows_formal_controls_strict_graph_20261006.log`; they are not the
proof. The first attempt at `mapped-formal-1791218249659797216` remains FAIL
before SAT because its export includes unused library definitions and residual
word-level MUXes. The corrected runner lowers only those MUXes and exports the
unchanged comparison module without broadening its accepted cell whitelist.
This check does not replace the vendor-model four-state/startup corpus,
establish full-array numerical equivalence, or physical/RK acceptance.
The [mapped-helper binary proof archive](runs/2026-10-06-mapped-fp16-helper-binary-proof/index.json)
contains 64 verified members and 3,394,185 bytes, SHA256
`2c3b76f3c1bacdf005119296fec3d3101eece4562ce814bc81ee8ffe2b2f961e`.

`tools/cmac/test_fixed_mapped_array.py` adds the next complete numerical gate:
the actual hierarchical full-CMAC XC7 partition with all sixteen C32 kernels,
all 208 original frames and 3,328 output comparisons. Only kernel/instance-name
aliases and an external binary-model harness are generated; cells, truth tables,
connections and all numerical/hold/reset/tag assertions remain intact.
The first eight synthetic harness/shape methods pass in
`build/fixed_mapped_array_controls_20261006.log`; fifteen current structural
export/parameter methods pass in `build/fixed_mapped_array_instance_alias_controls_20261006.log`.
They are not a mapped numerical PASS. The first real attempt is preserved at
`build/rknpu-cmac-array/c32k16/fixed-mapped-binary-1791221355297301197/`.
Its actual compile exposes 122 undriven unused debug-alias warnings; it was
intentionally interrupted (session 97587, exit 130) before arithmetic testing.
`interruption_audit.json` records why its first runner's RUNNING field is stale.
The strict undriven-signal gate remains. The corrected exporter retains each
actual cell/type/parameter and port bit, omitting only unused debug aliases.
Real Yosys roundtrip plus wire-incidence/cell/default-parameter identity must
pass before compiling. A second real attempt remains FAIL at
`build/rknpu-cmac-array/c32k16/fixed-mapped-binary-1791222379477890874/report.json`:
the actual mapped kernel's `invalid` output is the constant zero, and the first
structural exporter incorrectly forbids every constant port. The corrected
export preserves that actual constant output exactly; constant input constraints
remain rejected, and constant/topology mutations remain checked. Known Yosys
`$scopeinfo` debug cells (384 here) are excluded just as in the existing primitive
counter, not treated as hardware or arithmetic stubs. A third real attempt
remains FAIL at
`build/rknpu-cmac-array/c32k16/fixed-mapped-binary-1791222742341384170/report.json`:
its strict graph comparison finds RTLIL-private `$abc...` names re-read as
escaped user identifiers. The fresh export adds a recorded, reversible
per-module hardware-instance bijection rather than normalizing verifier names;
distinct private/user names remain distinct. It is now running at
`build/rknpu-cmac-array/c32k16/fixed-mapped-binary-1791223429684393546/report.json`,
driver `build/fixed_mapped_array_instance_alias_driver_20261006.log`.
The actual Yosys roundtrip now passes full port-bit/cell-type/parameter/default
and wire-incidence equality at source
`c77e1ad4c53c6bdc4556184e52c95290ef48a04ac8222d5f957ee4ba88c69c7d`;
the mapped C32 library was last observed compiling before the managed
PID-namespace transition. Its old tool handle/host PID are not now observable;
that does not establish a stopped job. This is an export-integrity gate, not
the pending full mapped numerical PASS.
It compiles actual mapped arithmetic once into a library instantiated sixteen
times, requires real library calls, and first demands a real first-frame
mismatch from a single flipped golden bit. The full unchanged corpus must then
pass. Its unchanged installed Yosys functional models and Verilator give
two-state mapped evidence only, not UNISIM GSR/four-state or physical signoff.
Only immutable primitive-model specify/unnamed-generate metadata diagnostics
are classified as nonfunctional; ignored specify timing is explicitly recorded,
never accepted as timing/DRC evidence. Undriven/width/latch/unmodeled diagnostics
remain failures. The earlier structural-control run's two fixture failures are
preserved in `build/fixed_mapped_array_structural_controls_20261006.log`: its
floating test input was only renumbered, not rewired, and its instance-count
string assumed one space. The corrected fixture connects the input and checks
whitespace-independent counts without changing the required rejection cases.

The new fixed-array raw-board runner retains the entire original K65 board
bench and changes only one internal CMAC instance in a generated wrapper.
Its nine synthetic control methods pass at
`build/rknpu-fixed-board-control/1791209463136018270/report.json`.
These validate evidence/count/warning gates, not HDL integration. An actual
RUNNING-parent rejection is recorded in
`build/fixed_board_running_parent_rejection_20261005.log`; that rejected
invocation created no execution directory. The fresh fixed raw-board run now
passes all eight modes 0..6 and 8 at
`build/rknpu-fixed-array-board/verilator-1791210829751522794/report.json`,
status `PASS_FIXED_RAW_ARRAY_BOARD_TWO_STATE_HIERARCHICAL_EXPERIMENT_ONLY`,
source `6eb8d1d22ff6af849e2b98b0f7384052ca8571283e8030202c5dfdae3e4ec7fd`.
It records Verilator 5.048/GCC 16.2.1 and the unchanged directed K65 fixture,
complete 4,096-halfword RAM readback, 6,528 operand reads and 64 acknowledged
writes for each successful job. Four-state mode 7 is not covered. The separate
Icarus report remains incomplete at
`build/rknpu-fixed-array-board/iverilog-1791210828043361091/report.json`.
Modes 0..6 are recorded PASS and mode 7 RUNNING; host liveness was last
confirmed before the managed PID-namespace transition. The missing old tool
handle/hidden host PID is not terminal evidence; no restart or completion is inferred.
The [fixed-board two-state archive](runs/2026-10-05-fixed-array-board-two-state/index.json)
contains 1,731 verified members and 96,844,787 bytes, archive SHA256
`a5fb49ef516bc13083b73e226fbfa668d3c80ca689510ed31a8db82542774673`.
Its independent archive checksum also passes. The baseline board/Vivado statuses
are not reused for the fixed variant.

The full experimental CMAC area report now completes at
`build/rknpu-cmac-array/c32k16/fixed-area-1791207358609699523/report.json`,
status `PASS_FIXED_CMAC_XC7_AREA_EXPERIMENT_ONLY`, source SHA256
`36a07f4cc3307b177678a4daef92b86682ea0555785c9b5b2cb6e1bf46615d98`.
Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`) maps all 512 helpers
and sixteen C32 kernels in 7,823.696 seconds. Hierarchical and flattened counts
match: 466,264 LUT primitives, 742 FDCE, 5,280 CARRY4, 1,616 MUXF7, 640 MUXF8,
no DSP48E1. This is 8.98% fewer LUT primitives than the baseline; the 287,863-LC
log estimate is for CMAC alone, not packed whole-board fit or timing acceptance.
The [full fixed-CMAC area archive](runs/2026-10-06-fixed-c32k16-area/index.json)
contains 34 verified members and 30,370,426 bytes, SHA256
`fdb46ddb5cb8625e369ccffc3a09dfc0461fdd1a3e48a1bf2f06be6be6f7a020`.
Its independent archive checksum passes; its scope remains area-only.

The new `tools/cmac/map_fixed_board.py` prepares partitioned whole-board XC7
area measurement, including actual CACC, output conversion, DMA, decoder,
ROM/RAM and reset/LED logic. It requires completed current fixed CMAC mapping
and integration evidence and reuses the actual mapped C32 kernel sixteen
times, not an arithmetic blackbox. Ten current synthetic control methods pass in
`build/fixed_board_mapping_controls_20261006.log`; an actual RUNNING mapping
parent is rejected with exit code one before any mapping directory/tool is
created (`build/fixed_board_mapping_running_parent_rejection_20261005.log`).
An import-shape/primitive-count check of the actual completed intermediate
partition passes in `build/fixed_board_mapping_actual_partition_check_20261005.log`.
The first real attempt remains FAIL at
`build/rknpu-fixed-board-area/1791215511983936941/report.json`, because Yosys
JSON import loses the mapped array's `TAG_WIDTH` parameter interface. The
corrected run adds a wire-only original-port adapter with an explicit
C32/K16/TAG35 rejection guard, aliases only the imported array module key, and
leaves the mapped arithmetic and raw board path unchanged. Its report is
`build/rknpu-fixed-board-area/1791215830399703096/report.json` now completes
with `PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY`, source SHA256
`f768971dbde9bc2098b2b2ea68c3094f3c13db60acbeac158f6aadc01f140350`.
The actual Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`)
mapping takes 8,397.386 seconds and retains all 512 parallel products and
sixteen original mapped C32 kernels. Whole-board counts are 512,159 LUT1..6,
17,310 flip-flops, 6,550 CARRY4, 5,589 MUXF7, 1,570 MUXF8, six RAMB36E1 and
no DSP48E1. The 322,911-LC estimate is 8.14% above the target's 298,600 LUT
sites; this motivates area reduction but does not prove placed packing or
routed fit. No numerical netlist or physical-fit/timing/electrical/DRC PASS,
bitstream, board programming or RK-silicon acceptance is inferred.

The [complete fixed-board area archive](runs/2026-10-06-fixed-full-board-area/index.json)
now contains 1,759 verified members and 132,432,059 bytes, SHA256
`e1e7358fb40774cfe04985f9e730265565b9cfc7cc16efeb85b8be3d9007788d`.
Its independent archive checksum passes. The archive freezes the actual
complete-board mapping and source-bound parent evidence, without promoting
its area-only scope into numerical or physical acceptance.

A source-bound read-only shared-cone analysis now completes at
`build/rknpu-shared-kernel-cones/1791225362316126979/report.json`, status
`PASS_SHARED_INPUT_CONE_ANALYSIS_ONLY`, source SHA256
`ca9dd7cea5da0d04d44e9a23fce503b64f8072b32bfff2aeb1f20a6fcb6fe7bc`.
It checks the actual identical data/mask input bits and propagates only through
unchanged combinational primitives, never state, DSPs or private weight inputs.
The per-kernel eligible 973-LUT/seven-MUXF7 cone implies a possible 14,595-LUT/
105-MUXF7 saving across sixteen instances. The netlist remains unchanged;
497,564 remaining LUT primitives is hypothetical, not mapped/packed acceptance.
Twelve synthetic safety controls pass under Python 3.14.5 in
`build/shared_kernel_cone_make_controls_20261006.log`; no simulation, synthesis
or place/route tool is invoked by the analysis. Its result cannot be substituted
for the pending full mapped numerical and raw-board physical gates.

A separate actual shared-cone board candidate now requires literal reverse
expansion and real full-port/cell/parameter/wire-incidence Yosys export
identity. Its first attempt is preserved FAIL at
`build/rknpu-shared-board-prepare/1791227248744199991/report.json`: the old
binary-only exporter cannot encode the board's RAMB36E1 string parameters.
The exact failed runner has a source-hash-matching snapshot in that directory.
A dedicated fail-closed BRAM literal exporter now has five passing controls,
including a real small Yosys roundtrip; fifteen sharing/restoration controls
also pass in `build/shared_board_prepare_bram_export_controls_20261006.log`.
The fresh actual preparation completes at
`build/rknpu-shared-board-prepare/1791228867345797456/report.json`, source
`6aebd8948816b39684521b9d1c3571fea8d931ffde795cb6dd9250c092f8ad38`.
Its real full-board Yosys export completes with exit zero in 474.895 seconds
and passes full port-bit/cell/type/parameter/default/wire-incidence identity.
Independent hierarchy/elaboration exits zero in 454.917 seconds, followed by
literal restoration and unchanged-source checks. Final status is
`PREPARED_SHARED_CONE_BOARD_NETLIST_ONLY`: 497,564 LUT primitives with
17,310 FF, six RAMB36E1 and no DSPs. Its 311,781 estimated logic cells still
exceed the target's 298,600 LUT sites;
this is not full numerical, packed area, physical timing/DRC or FPGA evidence.
The [completed shared-cone preparation archive](runs/2026-10-06-shared-cone-board-preparation/index.json)
has 1,774 verified members, 143,392,401 bytes and SHA256
`928746112ff1290cce9b3a58ea703bc17cbda8448bec39769916ec1315956fd4`.
Independent checksum verification matches; acceptance remains preparation-only.

The separate LUT6_2 pairing preparation preserves the two exact original
same-variable-fanin LUT functions and requires exhaustive **0/1/X/Z**
comparison under unchanged installed Yosys functional models for each actual
function class. A real mutated INIT bit must fail before the unchanged class
corpus is accepted. This complements literal reverse expansion and real
export/elaboration checks, not full raw-board numerical/hold/reset/fault or
UNISIM/GSR/physical verification. Eleven controls, including real Icarus
two- and five-input checks, pass in
`build/board_lut_pair_controls_full_patterns_20261006.log`.
The first actual attempt is preserved FAIL at
`build/rknpu-paired-board-prepare/1791228952700524867/report.json`, source
`d20e2b6a031f116972d354209f6a2559870ba2f50b925880629d1c7fe7359e20`.
Its reversible candidate has 125,163 LUT pairs/386,996 LUT primitives, not
placed utilization. All 650 actual function classes require 496,096
four-state comparisons. The real deliberate first-pattern INIT mutation is
rejected with exit one; all 496,096 unchanged comparisons now pass with exit
zero in 111.160 seconds under Icarus/vvp 13.0 and unchanged Yosys 0.65
functional models. Export exits zero in 411.619 seconds, but the complete
circuit-identity gate fails because the private RTLIL `$paramod` module name
changes namespace on the Verilog roundtrip. No completed candidate is claimed.
The fresh whole-export read-only diagnostic in
`build/paired_private_module_namespace_diagnostic_20261006.txt` confirms that
this single explicit module/type-name edit explains the entire strict
circuit-signature difference; the old FAIL and frozen sources are unchanged.
The new reversible module/type-reference bijection preserves the strict
verifier; a real small Yosys counterexample and exact aliased roundtrip pass
among fourteen controls in
`build/board_lut_pair_module_alias_frozen_input_controls_20261006.log`.
A fresh full preparation completes at
`build/rknpu-paired-board-prepare/1791231501256738760/report.json`, source
`be6e430f161c3627dc55d4ab31628259abd84745972826078af7ecf76486398f`.
Its newly executed 650-class/496,096-comparison corpus passes with exit zero
in 147.414 seconds, and the deliberate INIT mutation is rejected with exit
one in 24.757 seconds. Full export exits zero in 562.411 seconds, with exact
circuit identity, and hierarchy/check-assert exits zero in 470.437 seconds.
Final literal restoration/source checks pass, giving
`PREPARED_LUT6_2_BOARD_CANDIDATE_ONLY`: 125,163 pairs/386,996 LUT primitives,
unchanged 17,310 FF/six RAMB36E1/no DSPs. Its
[completed source-bound archive](runs/2026-10-06-lut-paired-board-preparation/index.json)
has 1,789 verified members, 145,247,002 bytes and SHA256
`3ebf34d861e1d250e2df0092c99be6fdf7e45e74d0410c176f88d16f7f2f7101`.
Actual archive exit zero and the independent archive checksum are observed.
The independent fresh audit in
`build/lut_pair_fresh_function_class_artifact_audit_20261006.log` verifies the
current source, both pre-compile input and pre-execution executable manifests,
exact generated benches, unchanged installed/frozen model bytes and actual
positive/negative markers. It accepts only this local function-class subgate.
Its proof inputs and compiled executables are hash-bound before actual compile
and execution, then checked against the final artifacts; earlier logs are not
carried forward. A separate full-array replay runner retains the original
mapped array registers/protocol and all 208-frame assertions while importing
only the literally verified paired C32 kernel. Its controls are not an actual
mapped numerical PASS, and it refuses failed or running paired parents.
Twelve controls pass in
`build/paired_mapped_array_frozen_export_final_controls_20261006.log`; an actual
CLI refusal of the saved failed parent exits one before output creation in
`build/paired_mapped_actual_failed_parent_rejection_20261006.log`.
The actual fresh RUNNING parent is also refused at that gate with exit one
in `build/paired_mapped_actual_running_parent_rejection_20261006.log`.
The combined make-target preparation controls pass all 46 methods (12 replay,
14 pairing, 15 sharing and five export controls) in
`build/mapped_candidate_all_preparation_controls_20261006.log`. These include
real small tool counterexamples but are not a completed full numerical or
physical gate.
No old numeric/area/physical acceptance is copied into either new candidate.
The physical LC estimate cannot be reduced by subtracting raw LUT savings.
The actual paired full-array replay remains FAIL using the completed parent,
with log `build/paired_mapped_array_actual_replay_20261006.log`; it has no
completed numerical PASS yet. Its fresh execution report is
`build/rknpu-cmac-array/c32k16/paired-mapped-binary-1791235676061104658/report.json`,
Post-export source is
`7628fe92b06a2ea58ae4731ef978967cd0d4ba1abb377d4ecf601bc7fc08ecfd`,
after including the frozen model/export artifacts in the input manifest.
The real export exits zero in 144.139 seconds with full circuit identity;
hierarchical kernel compilation exits zero after 13,610.36 seconds. Top
generation exits zero but its strict warning gate rejects the unmodified
Yosys FDCE model's `INITIALDLY` at line 692 (`initial Q <= INIT`). Numerical
execution has not run. The failure and generated/compiled files are retained;
neither the model nor the warning expectations were changed to promote it.

A separate pinned, unmodified UNISIM LUT1..5/LUT6_2 gate completes at
`build/rknpu-lut-pair-unisim/1791235044716807822/report.json`, source
`026b134bb7186717a31436ba6c6c3cfee6fde11ab7023050fd2326eb925d6322`.
It requires all 650 actual classes/496,096 four-state comparisons and a real
INIT-bit negative, with pre-compile/pre-execution hashes. The initial small
model-control failure and exact zero-input versus X-to-first-pattern startup
diagnostic remain preserved. The vendor harness changes only driven input
initialization, not models, pins, patterns, delays, assertions or counts;
constant-only classes explicitly fail this harness. Seven controls pass in
`build/lut_pair_unisim_startup_and_binding_controls_20261006.log`.
Actual status is `PASS_LUT_PAIR_UNISIM_FUNCTION_CLASSES_ONLY`: all 650 classes
pass 496,096 comparisons with exit zero in 999.601 seconds; the INIT-bit
negative exits one in 51.910 seconds. Both compile/run bindings and final
source/artifact checks pass. Its
[completed source-bound archive](runs/2026-10-06-lut-pair-unisim-function-classes/index.json)
has 1,819 verified members, 149,221,464 bytes and SHA256
`3880d7ebc4e72d8767a40d6be4a5c329daa4d4f32d4d3e2ae80a8c2034fb6067`;
the independent archive checksum check passes. This does
not validate mapped-array/full-board numerical, GSR/BRAM, timing/DRC or RK. See
[the detailed numerical and startup contract](../docs/RKNPU_SIZED_CMAC.md#independent-vendor-model-check-and-mapped-board-bench-binding).
The independent audit in
`build/lut_pair_unisim_completed_artifact_audit_20261006.log` verifies the
current model/bench bytes, exact command order/codes, compile and executable
bindings, final hashes and markers. This is not an additional HDL execution.

The separate actual direct-output-role audit completes at
`build/rknpu-lut-pair-sink-audit/1791243516491521479/report.json`, source
`6d4bdc8c2d477baa4050d5ee8c0d6ff4bb532eb0a4530e9542119a185f174105`.
It rechecks the actual paired parent and weights the top once/kernel sixteen
times. Of 125,163 pairs, 1,036 have both outputs feeding O6-only carry-select
or F7 consumers, and 124 more have only O5 doing so. This read-only audit
does not repair packing or validate a physical fit; six small controls pass.
Its [completed archive](runs/2026-10-06-lut-output-role-audit/index.json)
has 1,795 verified members, 145,395,106 bytes and SHA256
`ed83fe21c3c1c7f7206c48a35191e2953fb659001e14edb2c49b4361d76fba3c`;
independent checksum verification passes.
The new union-fanin opportunity analyzer leaves all hardware unchanged.
Ten small controls include six actual primitive fixtures, each model passing
8,352 four-state comparisons plus a real INIT-bit negative. These are not
full-board proposal-domain proofs. The final frozen-model control is
`build/rknpu-union-lut-model-controls/1791243692822360481/report.json`, source
`3544c01e39e220798b6e7091754bf6645d102b2af92db275f893f2391b44315b`.
Its [source-bound archive](runs/2026-10-06-union-lut-frozen-model-controls/index.json)
has 47 verified members, 147,913 bytes and SHA256
`2efefbf47361fcd54d1b40cbf223a963b44a98b4ddce6ab0663f92998242679e`;
the independent checksum check passes.
Actual analysis `build/rknpu-union-lut-opportunities/1791243648348492686/report.json`,
source `d53bc186af68cb6d67d13f81023e20327aaa0e1e8d663dfbe08463a3a3fd0fd8`,
finds 80,980 additional disjoint proposals/5,135 classes, projecting 306,016
LUT primitives, still above 298,600 nominal sites. No netlist changed or fit
was accepted. Three proof-admission controls pass. The actual class proof
passes 9,163,648 Yosys four-state comparisons. UNISIM negative/positive compile
stages pass, but its actual positive records FAIL after 14,402.133 seconds
with no completed return code in
`build/rknpu-union-lut-functions/1791244138678464917/report.json`.
The four-hour timeout is not a demonstrated numerical mismatch; its exact
source/model/bench/binary hashes and logs remain preserved. There is no overall
two-model PASS. Combined shared-cone/LUT pairing now completes literal restoration,
650-class/496,096-comparison four-state checks and real negative, exact export,
hierarchy and current source checks at
`build/rknpu-paired-board-prepare/1791244011823377237/report.json`, source
`4566dbb42b3e7c280e001f2ffc9baa4c19732b77ff8e58843952f293290e145f`:
372,401 LUT primitives and 125,163 pairs. This is preparation, not a full-board
numerical or physical fit result. The read-only shared-board union analysis
completes with 74,424 further proposals/5,113 classes and a 297,977-LUT
projection. Repairing its 1,036 existing dual-O6 conflicts raises this to
299,013, still above nominal capacity. No packed fit is accepted. The actual
reversible full-board transform now completes export identity, hierarchy and
final-source checks at status `PREPARED_SHARED_UNION_LUT_STRUCTURAL_CANDIDATE_ONLY`;
the independent full-domain class gate now passes all 5,321 classes and
9,284,320 four-state comparisons under each of frozen Yosys and pinned unchanged
UNISIM, with both real one-bit negatives. Its source is
`64d8f57c5a32008a8d7fe044fdab123ce2818ab1b69fb94161f70829b52e7532`.
This is combinational class acceptance, not whole-board numerical or physical
acceptance, and does not cover a changed augmented pairing domain. Five new
literal/admission controls pass. Their small union/split/
swap fixture passes three classes/2,304 exhaustive four-state comparisons
under each of Yosys and unmodified pinned Xilinx models, with both real
negatives, at source `68f2af27c14c3aba955e4796926321060115d951610d31292a2fa5ea82bad1a8`.
The fixture does not validate the actual whole-board domain. See the
[dedicated-output and union-fanin contracts](../docs/RKNPU_SIZED_CMAC.md#dedicated-output-audit-and-union-fanin-opportunity-analysis).

The [completed actual class archive](runs/2026-10-06-shared-union-completed-functions/index.json)
preserves 99 verified members/776,874,431 uncompressed bytes, SHA256
`33bf12d960cbdd8d0568aa2086299437afaa6ca8f67c8758f909c8b63f777cc2`.
Its actual binaries, unchanged model/source bindings and both real negatives
are retained, and the independent archive checksum passes. Scope remains
class-only, not whole-board or physical acceptance.
The new cofactor fixture passes one actual synthetic class/8,192 four-state
output comparisons in each unchanged model library, and both real negatives,
at source `1cc7406871b1abf31dff83b984d11638fbddd946a2ccb8d3e72049142087f188`.
Its [completed source-bound archive](runs/2026-10-06-cofactor-small-frozen-model-fixture/index.json)
contains 64 verified members, 137,996 bytes and SHA256
`5fc6e24870ba220637429977da85f5a3f6e6c67b5e6969d49bf97114b14ad9cc`;
independent checksum verification passes. The actual residual board search
completes with only six top-level proposals/classes and a conditional
299,007-LUT projection, still over nominal capacity. Its actual domain has
no HDL acceptance. The separate length-three matching analysis now completes
with sixteen further weighted proposals, for 74,440 total. Its repaired
conditional projection is 298,997 LUT primitives, 397 above nominal sites.
The [completed analysis archive](runs/2026-10-06-augmented-union-completed-analysis/index.json)
contains 54 verified members/6,042,623 bytes, SHA256
`d82a486c447ee701bf20d457b7a2e5db7f15ffbc09a59f168e1dd3d3eb45fdc2`;
the independent archive checksum passes. No changed circuit or fresh
function-domain HDL acceptance is inferred. Seventeen new
selection/harness/graph controls pass; none proves whole-board equivalence or
physical savings. The existing openXC7 packer does not preserve live-I5 pair
sharing. See the [packing-search contracts](../docs/RKNPU_SIZED_CMAC.md#residual-cofactor-search-and-improved-union-matching).
The [completed private-original analysis archive](runs/2026-10-06-union-lut-opportunity-analysis/index.json)
has 1,795 verified members, 145,802,572 bytes and SHA256
`9e889371e74533602cd4ebedb47a581f5a6325afcdd3ccb01fd67039438f320a`;
independent checksum verification passes. No transformed hardware or function-
class proof result is inferred from that read-only analysis archive.

Seven exact-name/width/live-wire mapped-board bench-binding controls also
pass in that log, including real Icarus force/release controls. The actual
audit exits two at
`build/rknpu-mapped-board-bench-binding/1791234166975612331/report.json`, source
`7f70376857c03b3e678cd599370fe35c4b2cfa98d427789ff6b2dfde1fe3b3b1`,
with `INCOMPLETE_MAPPED_RAW_BOARD_BENCH_BINDING_ONLY`: ten bindings/twelve
issues, including lost observations, a debug-only address and four-bit state
recoded to eleven bits. No guessed aliases, mode-derived golden values or
skipped fault assertions are accepted, and no bound bench is produced.
A source-evidenced pre-mapping retention run now starts from the original
import and source hashes at
`build/rknpu-observable-board-premap/1791236250182514989/report.json`, source
`6b3f289bbee80daaf5b04a43a1609b917ba14bbbc089e1b56edc91bff0835f0e`.
It requires all 22 original names/widths/live force points, keep attributes,
native four-bit state with recoding disabled and unchanged actual imported
kernel circuit. Three controls pass in
`build/observed_board_prepare_independent_fixture_controls_20261006.log`;
the preceding fixture-list alias failure is preserved separately. The actual
first run exits one in 522.597 seconds because strict check reports 288
undriven compiler `$bitselwrite$pos` temporary bits. Its FAIL/log and exact
pre-run tool snapshot remain unchanged. The corrected board-only cleanup
retains keep attributes and `check -assert`, uses opt_expr -keepdc/opt_clean,
and never replaces undriven nets or removes dont-care mux inputs. Only three
exact source array-lowering notices already present in the original mapping
are classified; new warnings still fail. Four controls pass in
`build/observed_board_prepare_keepdc_cleanup_controls_20261006.log`.
The second real run at
`build/rknpu-observable-board-premap/1791237101705754113/report.json`, source
`b47320fdd4373db41c7c55e2a2ca604b0e88391f7ff3ef20a6ba94206e1152ee`,
also fails with actual exit one in 665.779 seconds. Strict check reports zero
problems, but JSON export rejects processes in the behavioral FDCE library.
Its failure and pre-run snapshots are preserved. The next correction exports
exactly the full board and preserved kernel modules using documented
write_json -selected; it does not remove hardware or blackbox primitives.
Six controls pass in
`build/observed_board_prepare_selected_module_boundary_controls_20261006.log`,
including the real Yosys library-process failure and corrected primitive-retaining
export. The fresh complete preparation completes at
`build/rknpu-observable-board-premap/1791238537797494685/report.json`, source
`de1ad0462b41af3aac966cd75746b0976f69576c46929a3e15b19c08193c79e5`.
Real Yosys preparation/export exits zero in 589.065 seconds and the complete
process exits zero. Status is `PREPARED_ORIGINAL_RAW_BOARD_OBSERVABILITY_ONLY`:
all 22 exact observations, retained native four-bit state, sixteen actual
instances, full kernel identity and final source checks pass.
Its [completed source-bound retention archive](runs/2026-10-06-original-board-observability-preparation/index.json)
has 1,767 verified members, 136,037,626 bytes and SHA256
`2193648101687393b8a8191f423cd5d17ec455af50f6a54e1b7e38160e4f6f78`;
the independent checksum check passes. This is preparation evidence only,
not the later live mapping or full-board numerical/physical acceptance.
The downstream complete-stage mapping tool has two passing controls in
`build/observed_board_mapping_stage_controls_20261006.log`; it requires a
completed retention parent and fresh complete mapping with all original taps
and unchanged sixteen-kernel hardware. The controls do not execute that mapping.
The combined make targets pass all eight controls in
`build/observed_board_all_preparation_mapping_controls_20261006.log`. The
actual CLI rejects the saved failed preparation with exit one at the parent
gate in `build/observed_board_mapping_actual_failed_parent_rejection_20261006.log`.
Fresh full-board mapping from that accepted parent remains FAIL with log
`build/observed_board_actual_complete_mapping_20261006.log`. Real Yosys exits
zero after 9,902.834 seconds, but the strict log gate rejects RAM port-width
normalization warnings before observation/kernel/final-source gates execute.
No mapping, numerical or physical acceptance is claimed; no warning is waived.
Its retained failed report is
`build/rknpu-observable-board-mapping/1791239329138833352/report.json`, source
`7a6ba2697f78a067ee4f86b84c3c60f09fb481b1dd63aa0e3c9b06b4d33ce57c`.

The separate actual FDPE/RAMB36E1/default-GSR functional-model control passes
at `build/rknpu-unisim-board-model-control/1791240157609981117/report.json`,
source `47a751cb4bd42518e7f5e92300c7cd546fced368dc567ff5694daae84a680fee`,
with status `PASS_OBSERVED_BOARD_UNISIM_MODEL_CONTROL_ONLY`.
Icarus/vvp 13.0 compile/positive execution exit zero; the deliberately wrong
read value is rejected by the same executable with exit one. The pinned
models, startup, RAM known/unknown/retention checks and all fatal assertions
are unchanged. Its
[source-bound archive](runs/2026-10-06-observed-board-unisim-model-control/index.json)
has 25 verified members, 118,274 bytes and SHA256
`099612503c8c12bc498c2904c653b8fb23ff3713a66b9a3c4badddc6d53c3fc8`.
This small model control is not full-board or FPGA proof. Two preceding
wrapper failures and their executed source snapshots remain preserved; the
documented explicit default `-Ttyp` and exact Icarus finish-diagnostic
corrections alter no model or HDL checks.

The full observed mapped-board runner is now prepared, not executed. It
requires actual completed mapping, exact circuit/tap evidence, a real literal
export roundtrip, unmodified pinned functional models/default startup and all
nine original numerical/fault/reset modes, including unknown data. A real
first-output golden-bit negative must fail using the same compiled hardware;
only its isolated test cwd's golden changes. The combined 14 preparation
controls pass in `build/observed_board_full_preparation_controls_20261006.log`;
these are not a full-board numerical result. Current actual CLI rejection of
the unfinished mapping is retained in
`build/observed_mapped_board_current_running_parent_rejection_20261006.log`.
See [the full runner/model contracts and retained failures](../docs/RKNPU_SIZED_CMAC.md#full-observed-mapped-board-replay-preparation).

The latest fresh production make session 45060 completes with exit zero,
master log `build/fpga_preparation_regression_selected_observed_mapping_20261006.log`.
Its [source/timestamp/output-verified archive](runs/2026-10-06-observed-board-preparation-production-regression/index.json)
has 1,466 verified members, 11,462,970 bytes and SHA256
`f98dc1fc0276e420651bbde5b51aa3d030de494ff5bcc2dafdb8fe8bad2aed86`.
The unchanged production source, 49 Python methods, 1,087,299 numeric
comparisons, 247 original entries plus three benches per simulator,
82 cross-simulator images and eleven host/direct images per simulator pass.
This does not validate the new nested preparation tools or mapped candidates.

The fresh production rerun during these new preparations exits zero (actual
session 69270), with its new log at
`build/fpga_preparation_regression_shared_candidate_20261006.log`.
All 247 original entries and three additional benches per simulator pass,
along with 49 Python methods and 1,087,299 numeric comparisons. All 82 saved
cross-simulator memory images and eleven host/direct images per simulator
match. Current production source is unchanged at
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
The [new source-bound production archive](runs/2026-10-06-shared-candidate-production-regression/index.json)
has 1,466 verified members, 11,462,758 bytes and SHA256
`ccbff8190236eff19ebe3cb00e0f8626abd3b843ecd7c149a491182cfe1e4acf`.
The archiver checks each report's actual fresh timestamps, source/command/
artifact hashes and exact output-image equality; no prior logs are copied as
evidence for this new run. It does not test either modified mapped candidate.

The further fresh production run (actual make session 57078, exit zero) has
log `build/fpga_preparation_regression_module_alias_20261006.log` and the
same unchanged production source and complete regression counts. Its
[independently source/timestamp/output-verified archive](runs/2026-10-06-paired-preparation-production-regression/index.json)
has 1,466 verified members, 11,463,169 bytes and SHA256
`8bca3dc0714ef79af8c4d2e3f2133af6488fd2541f52379f386d861deed2189d`.
The nested preparation tools require their own gates; the root regression
does not validate the modified mapped candidates, timing/DRC or hardware.

The subsequent fresh native make session 67597 also exits zero with log
`build/fpga_preparation_regression_unisim_and_binding_20261006.log`.
Its [new source/timestamp/output-verified archive](runs/2026-10-06-unisim-preparation-production-regression/index.json)
has 1,466 verified members, 11,463,013 bytes and SHA256
`075b1bc3b47face3ac3078856eeacab82ea650ae82fe084269e6fd377590f8cd`.
All unchanged production-source, complete regression and image equality gates
pass, and the archive checksum is independently checked. Experimental
preparation/mapping controls remain separate from this native regression.

An additional real-Yosys import-boundary check at
`build/rknpu-fixed-partition-binding/1791216942676771849/report.json` uses
the actual mapped partition and adapter, not synthetic arithmetic. Exact
C32/K16/TAG35 import and sixteen actual kernels pass; C8, K8 and TAG34 are
each rejected specifically by the adapter's parameter guard in real Yosys.
The report completes with `PASS_ACTUAL_FIXED_PARTITION_IMPORT_BOUNDARY_ONLY`,
source SHA256 `406e61c18df3f06e5f7bc3f8e0745c3da55b6681f1c3ed1eab1d6c448a515a38`,
Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`). This cannot
establish numerical netlist or physical acceptance. The fresh production
`make -j2 -o vectors -o cmac-vectors test` now completes with actual exit zero
(session 24814),
log `build/fpga_preparation_regression_20261006.log`;
production source SHA256 remains `09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
Only vector generators are held fixed to preserve concurrent candidate inputs;
all test targets execute. Both simulators pass 247 original entries and three
additional raw-product benches, with 82 equal cross-simulator memory images;
49 Python methods and 1,087,299 numeric comparisons also pass.
The [fresh production regression archive](runs/2026-10-06-fpga-preparation-production-baseline/index.json)
contains 1,466 verified members and 11,463,379 bytes, SHA256
`8ddd58e95d04e50a8f1887d0206ed2d75afe4e843cb93eeb87de71e5f1adcbca`.
No old completion status is copied into this run; production native regression
does not validate the experimental mapped C32/K16 candidate or physical FPGA.

The complete two-state C32/K16 board replay now passes all eight selected
modes (0..6 and 8), including numerical readback, command/readback faults,
reset during command/frame/readback, repeat after success and injected
watchdog expiry. Its source-bound report is
`build/rknpu-array-board/two-state-hierarchical-1790009222786041132/report.json`.
This does not include four-state unknown-readback mode 7 and does not satisfy
the unchanged full-Icarus build prerequisite by itself. The complete
[nine-mode four-state board archive](runs/2026-10-05-array-board-full-four-state/index.json)
now closes that simulation prerequisite for the unchanged baseline: 269
verified members, SHA256
`87d1a747680364691bc8c92a88a2db220ca44dc24d443e36537e784167342dea`.
All modes 0..8 pass, including unknown readback and reset/restart faults.
This is not evidence for subsequently modified RTL or the physical card.
The original full mapped-netlist replay timed out at its 14,400-second limit
and remains FAIL at
`build/rknpu-cmac-array/c32k16/mapped-full-1790013072942514731/report.json`.

The full optimized-host AXI run also completed: all 19 public-port numerical,
fault and repeat cases pass at
`build/rknpu-array-axi/full-hierarchical-1790008635729125119/report.json`,
status `PASS_RAW_ARRAY_AXI_FULL_HIERARCHICAL_ONLY`. Complete saved memory,
status/tag/task/IRQ checks remained enabled. This is two-state RTL integration,
not physical FPGA, RK silicon or four-state equivalence.
The completed [full AXI archive](runs/2026-10-05-array-axi-full-hierarchical/index.json)
preserves 1,850 verified members, SHA256
`049931b2ff0abe08dd04151a7b0a9dc0ec939265f62daab68caebf41c9f9261c`.

The current [bitstream-emitter control report](../build/rknpu-bitstream-emitter-control/1791210538182242952/report.json)
passes eleven methods per Tcl 9.0.3 and Xilinx Tcl 8.6.13, with source snapshots,
interpreter hashes and actual logs. All Vivado operations are MOCKED. The
separate emitter cannot operate without a matching completed routed checkpoint
and explicit human electrical/report review; no checkpoint or bitstream was
created by those tests. See [the staged build instructions](../docs/RKNPU_SIZED_CMAC.md#reviewed-checkpoint-to-bitstream-prepared-but-unrun).
The separate fixed-mode checkpoint flow packages its sources at
`build/rknpu-fixed-array-vivado/prepare-1791210251059099091/report.json`;
no Vivado implementation has run. It requires the fixed variant's own
completed native/proof and all nine Icarus board modes. The shared emitter
revalidates the matching source profile and cannot substitute original-array
evidence. Eighteen fixed-build control methods per interpreter also pass at
`build/rknpu-fixed-array-build-control/1791210538916975755/report.json`.
Their [combined control archive](runs/2026-10-05-fixed-build-and-emitter-controls/index.json)
has 25 verified members, SHA256
`822ef11df1a29105d19b490b4801b8592a28ab1014fbb8422fa6a067482b1f11`.
All physical operations in these tests are mocked. The actual fixed prepare
report is rejected by emission before any output directory/tool is created;
log: `build/fixed_bitstream_prepare_rejection_20261005.log`.

A fresh production regression at the unchanged `09f1c3f65ba9...` source
completed successfully on 2026-09-22, logged at
`build/board_hierarchy_production_regression_20260922.log`. The command was
`make -o vectors -o cmac-vectors test`: all tests ran, while the two vector
generation targets were held fixed for concurrent source-bound candidate
runs. It includes 49 Python methods, 1,087,299 C++ comparisons, 247 original
entries and three CMAC benches in each simulator. It does not cover the
new experimental partial-row specialization or mapping recheck. Their live
evidence and explicit limits are in [RKNPU_SIZED_CMAC.md](../docs/RKNPU_SIZED_CMAC.md).

The [two-state build-gate archive](runs/2026-09-22-array-build-two-state-gate/index.json)
records nine passing build-control methods on each of Tcl 9.0.3 and Xilinx
Tcl 8.6.13, now explicitly rejecting the new two-state board status as a
substitute for the required full Icarus report. Its 254 members are verified.
All Vivado operations are mocked; no implementation or physical signoff ran.

The [optimized-host CMAC archive](runs/2026-09-22-c32k16-optimized-host/index.json)
preserves the passing unchanged 208-frame/3,328-output hold/reset bench after
rebuilding the verified partitioned simulator with host C++ `-O2`. No RTL,
vectors, assertions or numerical policy changed. The measured simulation time
was 24.883 seconds; this is not an FPGA timing result. The archive verifies
1,461 members, SHA256
`3b99014037942a157f9ce2630733f899427cfc0bb53a60f7d1a53cec9acb0807`.
Full AXI and board-wrapper integration with this library remain separate gates.

The C32/K16 [BRAM board-wrapper smoke archive](runs/2026-09-22-array-board-smoke/index.json)
preserves three passing Icarus 13.0 cases: command-memory failure, watchdog
abort and the complete finite K65 numerical job. The numerical case checks
6,528 operand reads, 64 acknowledged output writes and all 4,096 RAM halfwords
after execution (44,915 cycles). The archive verifies 264 members, SHA256
`9d542e07f678854d7b0c8acfacbec500d79d7c7d17a3542679d19339f2ae1708`.
The full nine-case reset/readback-fault suite remains running. No physical
card, full-suite or FPGA timing pass is implied by this smoke result.

The [full C32/K16 partitioned CMAC archive](runs/2026-09-22-c32k16-explicit-hierarchy/index.json)
preserves fresh library/top builds and the passing unchanged 208-frame native
bench: 3,328 checked outputs, 3,312 retired outputs, 16 reset-cancelled outputs
and 520 held cycles. Actual library calls and absence of embedded multiplier
classes were checked before top compilation. All results equal the completed
flat-model result; no RTL or golden changed. The archive verifies 1,350 members,
SHA256 `6682d2dbf8a3ad89adad80dae292c66a90c524381ed52e6f05d36597386a59a8`.
This enables further two-state integration testing, not FPGA/RK acceptance.

The [hierarchy-tool probe archive](runs/2026-09-21-hierarchy-tool-probe/index.json)
preserves a small four-instance Verilator 5.048 diagnostic: stock hierarchy
arguments omit actual library calls; explicit parameter-file transport enables
them. Both versions pass 128 outputs and two reset checks. This is a simulator
workaround check, not a CMAC numerical pass or FPGA evidence. The full-width
follow-up is described in [RKNPU_SIZED_CMAC.md](../docs/RKNPU_SIZED_CMAC.md).

The C32/K16 [AXI protocol archive](runs/2026-09-21-array-axi-protocol/index.json)
preserves six passing Icarus 13.0 early-fault cases, seed `3588ae16`: read error,
response/address timeout, descriptor alignment, unsupported raw target and
high-address rejection. It verifies 270 members, SHA256
`57afbbde774adc9e609d511d2552d8199463caaa734445403e34e76bd00becdf`.
Write-fault, reset/repeat and full numerical-corpus acceptance remain separate.

The C32/K16 [finite-core and DMA/AXI smoke archive](runs/2026-09-21-array-core-finite-dma-axi-smoke/index.json)
preserves the passing K65 raw-core replay (6,528 reads, 64 acknowledged writes),
all four DMA smoke cases including final-write failure, and all three AXI
smoke cases including numerical memory-image comparison. Icarus 13.0 runs use
seeds `3588ac16`, `3588ad16` and `3588ae16`, respectively. The archive verifies
288 members; its SHA256 is
`722b7970fb8038ad7dda3cad6f48a889e5b20ee1625675aea6dfa4f1579b1f08`.
These are selected full-width integration tests, not full-suite, board or RK
silicon acceptance.

The C32/K16 [DMA protocol archive](runs/2026-09-21-array-dma-protocol/index.json)
preserves twelve passing early-fault/framing scenarios with exact command
fetch/forward counts and no output writes or job completions. Numerical DMA
replay and final-write faults are separate evidence, not implied by this suite.
The [array build-control archive](runs/2026-09-21-array-build-control/index.json)
preserves nine mocked test methods on each of Tcl 9.0.3 and Xilinx Tcl 8.6.13.
It is not HDL simulation or a Vivado implementation result.

The C32/K16 [native hold/reset archive](runs/2026-09-21-cmac-c32k16-native-hold-reset/index.json)
preserves the full 208-frame, 3,328-output Verilator test, 520 held cycles and
16 reset-canceled outputs. The source-identical generated C++ was compiled
separately at `-O0`; original timeout reports remain failures. This is native
two-state verification, not full-array Icarus X rejection or physical timing.

The separate C32/K16 [raw-core smoke archive](runs/2026-09-21-array-core-smoke/index.json)
now preserves eight passing Icarus integration cases: one unchanged numerical
command stream with 2,176 reads and 64 acknowledged outputs, plus first/final
memory errors, both timeout phases, cancellation, unsupported command and
unknown read data. It covers that smoke suite only, not the full raw corpus,
DMA/AXI/board integration, upstream UTB or RK silicon.

The staged [CACC reduction archive](runs/2026-09-21-cacc-reduction/index.json)
now preserves direct donor tests, fresh native reduction tests and the passing
functional XC7 netlist replay: 2,712 groups and 204 outputs, with faults,
resets, cancellation and output stalls. The original synthesis-X and mapped
startup failures remain in the archive. It does not establish raw GEMM or
physical timing. The newly joined [raw numerical core](../docs/CMAC_NVDLA_CORE_CANDIDATE.md)
passes the full 16-entry Verilator and 19-entry Icarus suites, and XC7
primitive mapping. The [native core archive](runs/2026-09-21-cmac-core-native/index.json)
preserves both source-bound native suites. Functional netlist replay remains
in progress; no raw-core FPGA or RK result is claimed.

The staged [CMAC AXI native archive](runs/2026-09-21-cmac-axi-native/index.json)
preserves the new public-port host integration: all 19 Verilator entries pass,
with ten successful address/value images equal to their expected images.
The eight numerical fixtures alone check 92,768 AXI transactions. Separate
Icarus control/adapter tests pass seven and six reset scenarios respectively;
these are not a substitute for the still-running four-state numerical suite.
The archive includes donor licenses, exact sources and the failed/terminated
first reset-style attempts. It does not prove PCIe/DDR, physical timing, FPGA
execution or RK numerical equivalence. See
[CMAC_NVDLA_AXI_CANDIDATE.md](../docs/CMAC_NVDLA_AXI_CANDIDATE.md).

The [CMAC BRAM board-wrapper archive](runs/2026-09-21-cmac-bram-native/index.json)
preserves all eight passing Verilator K=65 wrapper tests, including complete
8 KiB RAM readback, fault/watchdog handling and three reset phases. It records
one reviewed synchronized-reset lint location and retains the preceding lint
failures/snapshots. Separate memory-aperture tests now pass in both simulators;
full board-wrapper Icarus and mapping remain running. None of these results
comes from the physical card. See
[CMAC_BRAM_BOARD_CANDIDATE.md](../docs/CMAC_BRAM_BOARD_CANDIDATE.md).

## Preceding source: raw-command/product integration

Source manifest `db97404570f55ffc3ca603816b3fc797953333ff4fac6e352f82a18970188765`
promotes the four decoder/reader/operand/product leaves into `rtl/`, adds
`rk_cmac_product_front`, portable seven-case command fixtures, vector generators
and three additional benches in `make test`. The existing EW RTL, host endpoint
and board constraints are unchanged. Fresh `make -j4 test` exits zero: 44 Python
methods, 1,087,299 C++ reference comparisons, strict lint, generated checks,
247 original entries and three extra benches per simulator. All 82 saved EW
memory images agree across simulators, including eleven host/direct comparisons
each. All 610 original stimulus files are unchanged. Verilator 5.048 and Icarus
13.0 report zero warnings for these native checks. See
[the path contract](../docs/CMAC_PRODUCT_PATH.md) and the
[fresh source-bound archive](runs/2026-09-21-db97404570f5/index.json).

The new wrapper has no accumulation or output writes. It holds command
ownership across all multiplier stages and cancels buffered products on faults.
The separate whole-endpoint mapping result below belongs to its earlier
snapshot; no mapped simulation of the new path, physical timing or hardware
success is inferred here.

Fresh mapping of the complete raw-product path itself now passes at this
revision: four DSP48E1, 1,959 FDCE and 2,053 LUT1..6 cells, Yosys 0.65,
251.325 seconds. Two warnings are retained (register-array replacement and
ABC combinational network). This is primitive mapping, not simulation of the
mapped path, placement, timing closure or hardware validation.

The initial new-wrapper preflight failed because the bench's random sink
inserted a forty-first final stall while its assertion required exactly forty.
A diagnostic observed all 8,192 products, 16,384 reads and both completion
counters correctly, with no DUT fault. The corrected driver makes the final
transfer deterministic after forty cycles, retaining that exact assertion.
Icarus also exposed a time-zero unknown-address callback in the behavioral
RAM; reads now occur only on accepted requests. DUT and expected products are
unchanged. The [failure archive](runs/2026-09-21-product-path-preflight-failure/index.json)
retains both findings and the deliberately interrupted first regression.

A separate [NVIDIA conversion audit](../docs/NVDLA_CONVERSION_AUDIT.md) now
records forty actual outputs from the unmodified donor RTL. It confirms
finite saturation and low-bit NaN payload truncation, not RK equivalence.
Its [archive](runs/2026-09-21-nvdla-conversion-audit/index.json) includes the
source snapshots with their original license/notices; this is not production
integration or a change to the project's numerical policy.

Under the user's NVDLA-baseline direction, a separate
[donor conversion/write tail](../docs/CMAC_OUTPUT_NVDLA.md) now connects the
unmodified converter to the unchanged result writer. Its corrected-runner
four-state integration, Verilator integration and XC7 mapping pass. This is
not accumulated GEMM, production-path integration or RK
silicon verification. The earlier IEEE-style candidate and tests remain
unchanged; the new suite explicitly labels its different donor contract.

A separate [stateful CACC candidate](../docs/CACC_REDUCTION_CANDIDATE.md)
adds ordered donor FP48 feedback and held FP32 output. Both native simulators
pass 2,712 synthetic FP44 groups with protocol/fault/reset checks. The direct
donor audit compares 9,144 partial and 9,144 final results to an independent
dyadic reference. A synthesis-only constant-reject bug was found in the
wrapper's X checks and corrected; the first structural mapping pass is not
accepted as working arithmetic. Fresh native results pass after that fix;
functional mapped-netlist acceptance remains pending. None of this accepts
new raw GEMM commands or establishes RK/FPGA behavior.

The corrected standalone integration-only Icarus run also passes at the current
source: 53,247 product/tag checks, thirteen successful streams, thirteen fault
cases, three reset cases and eighty full-buffer stall cycles. Its separate
report is `build/cmac_product_corrected_preflight_report.json`. The full suite
has since independently passed: each simulator checks 230,433 leaf products,
53,297 operand pairs and 53,247 integrated products/tags. Source hashes,
artifact hashes, promoted-source identity and unchanged baseline stimuli were
rechecked before archiving. This validates the raw-product increment only.

A separate [result-write candidate](../docs/CMAC_WRITER_CANDIDATE.md), still
under `build/` and outside that production manifest, also passes both native
simulators and default XC7 mapping. Verilator/Icarus check eleven successful
streams, eleven/fifteen faults and two resets, with zero native warnings.
Yosys maps to 91 FDCE, 70 LUTs and 12 CARRY4, retaining one ABC warning.
Its [separate archive](runs/2026-09-21-cmac-writer-candidate/index.json) records
synthetic result values and output-layout gaps, not accumulation, integrated
GEMM, mapped simulation, timing or RK/FPGA execution.

The separate [post-accumulation conversion candidate](../docs/FP32_TO_FP16_CANDIDATE.md)
also passes both native simulators: 330,793 conversion/tag comparisons each,
four reset cases, full throughput and backpressure, with zero final-source
native warnings. Default XC7 mapping uses 367 flip-flops and 202 LUTs and
retains one ABC warning. Its [archive](runs/2026-09-21-fp32-to-fp16-candidate/index.json)
is separate from the production manifest and earlier warning-producing
preflight. This does not establish RK numerical parity or integrate GEMM.
A fresh unchanged-production `make -j4 test` is running in
`build/fp32_conversion_baseline_test.log`; the completed production archive
above remains the evidence for that unchanged source until this rerun finishes.

The converter and writer are now joined in a
[staged output tail](../docs/CMAC_OUTPUT_CANDIDATE.md). Final-source Icarus
passes sixteen completed streams, fifteen faults, ten cancellations and five
reset phases, with 1886 requests/1875 acknowledgments and zero warnings.
Zero memory timeout is explicitly rejected. Default XC7 mapping passes with
279 flip-flops, 304 LUTs and 27 CARRY4, retaining one ABC warning. Verilator also
passes sixteen completed streams, eleven faults, nine cancellations and five
resets, with 1821 requests/1812 acknowledgments and zero warnings. Its
[separate source-bound archive](runs/2026-09-21-cmac-output-candidate/index.json)
checks both leaf hashes against their independent archives. The tail remains
outside the production manifest and is not connected to an accumulator or the
raw command frontend. No mapped simulation or physical validation is claimed.

## Previous source: native and full mapped-endpoint checks pass

Source manifest:
`f927a501cec9b66beae84f160bef333a849beb0a148d043d5951ea4febb5c4fc`.
The address-only CMAC leaf and its bench are now in `rtl/` and `tests/`,
byte-identical to the independently tested staged candidate. Normal lint and
both RTL suites include it (thirteen benches, 247 passing result entries each).
It remains unconnected to the decoder, DMA, arithmetic, host and board top.
No additional RK command profile is accepted.

`tests/tb_host_axi_netlist.sv` and `tools/run_host_mapped.py` now provide the
checked-in whole-endpoint mapped test with an explicit post-time-zero reset
transition. `make host-mapped-check` requires current successful RTL and
focused-map reports, maps the 128/4 test configuration and retains all twenty
unchanged checks. Default-parameter mapping remains separate. Fresh full
regression, focused host mapping and corrected full mapped replay have been
started. Fresh `make -j2 test PYTHON=/usr/bin/python3` exited 0: 44 Python
methods, 1,087,299 C++ comparisons (76.396 seconds), generated checks, strict
lint and both complete RTL suites pass. Verilator 5.048 and Icarus 13.0 each
pass all 247 entries with zero warnings. All 82 cross-simulator memory images
agree, including eleven host/direct comparisons per simulator. The 610 prior
stimulus files and all pre-host design RTL/board files are unchanged.

Focused host mapping plus mapped-control simulation also pass. These completed
checks are retained in [the current native archive](runs/2026-09-21-f927a501cec9/current_index.json).
The full mapped-endpoint replay has now also passed all twenty runs, including
all nine fault injections, partial-write reset and repeated jobs. All eleven
saved images equal the current native direct-memory RTL images. Its separate
[mapped archive](runs/2026-09-21-f927a501cec9-mapped/index.json) records actual
full-netlist execution, not inferred success from native simulation. No fresh
board synthesis, Vivado implementation, physical timing or hardware test is
claimed here.

The complete mapped DUT is elaborated with the bench's parameters 128/4;
default 65536/4095 mapping remains the separate focused result. The only bench
adaptation removes that already-fixed parameter override. All stimulus and
assertions remain unchanged. Default Xilinx global startup and public inputs
are retained; the checked wrapper drives a reset transition after time zero.
No DUT state or vendor primitive is forced. The previous failed startup
attempt remains archived below. The mapped compile retains 37 warnings (one
inherited timescale, ten DSP typical-delay messages, 26 unused DSP-port
connections); Yosys retains one ABC warning. They are recorded, not physical
DRC waivers, and the simulation contains no routed delays/SDF or MIG model.

The prior standalone address check passed 375,895 transfers per simulator,
eleven full walks and 22/24 rejected configurations, with zero warnings.
Its raw-byte packing reference and 11,616 compiler lane-map checks also passed.
That evidence and the failed mapped attempt are retained in
[the supplement](runs/2026-09-21-060fe287ecda-supplement/index.json).
Numerical GEMM, hardware layout execution, PCIe/MIG integration and actual
FPGA/RK validation remain outstanding.

A separately staged raw CMAC profile decoder passes 1,920 cases in each of
Verilator 5.048 and Icarus 13.0, plus four Icarus unknown-value cases. It is not
part of the production source manifest above and is not connected to execution.
Its [independent archive](runs/2026-09-21-cmac-profile-candidate/index.json)
retains the initial lint failure and the corrected zero-warning checks. See
[the candidate contract](../docs/CMAC_PROFILE_CANDIDATE.md) for exact scope.

The subsequent staged raw-command/address/operand integration passes 53,297
checked pairs in each simulator, including stalls, read faults, exact timeouts,
five reset phases and downstream ownership. Icarus additionally rejects unknown
error status on either read. Its default-parameter XC7 mapping passes with
1,464 FDCE, 1,986 LUT2..6 and three DSP48E1 cells for shape/range calculations.
It performs no numerical MAC or output writes and is not production-integrated.
See [the operand candidate archive](runs/2026-09-21-cmac-operand-candidate/index.json)
and [contract](../docs/CMAC_OPERAND_CANDIDATE.md). Its mapped netlist is untested;
mapping is not physical FPGA evidence.

The separate exact FP16-product candidate passes 230,433 value/tag comparisons
in each simulator, including full-throughput traffic, backpressure and four
reset cases (seed `0x3588ca04`). Strict lint and both simulator builds have zero
warnings. Default 131-bit-tag XC7 mapping uses one DSP48E1, 492 FDCE and 156
LUT1..6, retaining one ABC warning. The
[product archive](runs/2026-09-21-fp16-product-candidate/index.json) includes
the initial bench-transition failure and corrected fresh runs. This is a
standalone staged leaf, not production GEMM or a verified accumulation policy;
its mapped netlist, FPGA timing and RK numerical equivalence remain untested.

## Previous source: host-control endpoint, 2026-09-21

Source manifest:
`060fe287ecda9567bd5fd65dc7f893a36761c5945236552680d3a38376ead764`.
Fresh `make -j2 test PYTHON=/usr/bin/python3` and `make host-synth-check
PYTHON=/usr/bin/python3` both exited 0. Results are not inferred from the prior
attempt below. The only source change since that attempt is the mapped test
wrapper: a post-time-zero idle-address transition, retaining default Xilinx
global startup and every assertion. No DUT RTL, arithmetic, error policy,
board constraint or vendor primitive changed for this correction.

| Fresh check | Actual result |
|---|---|
| Software and build-control | 44 Python methods pass; generated checks and strict lint pass |
| Numeric design model | 1,087,299 comparisons pass, seed `0x3588`, 76.196 seconds; C++, not RTL |
| Verilator 5.048 / Icarus 13.0 | 246 result entries each, twelve benches, zero warnings |
| Saved memories | 82 cross-simulator images agree; eleven host/direct images agree in each simulator |
| Preservation | All 610 prior vector files unchanged; all pre-host design RTL and board files unchanged |
| XC7 host control mapping | 286 FDRE, 457 LUT1..6, no DSP |
| XC7 complete endpoint mapping | 1,085 FDRE, 4,497 LUT1..6, one DSP48E1, default parameters 65536/4095 |
| Mapped control simulation | PASS at 19.935 us simulated time, 27.432 seconds wall time; mock engine |
| Full Vivado build | UNAVAILABLE, exit 2; no implementation, timing closure, bitstream or board test |

Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`) retains one ABC
warning per mapped top. Icarus retains one inherited-timescale warning when
compiling the exported control netlist. Exact messages are in the report logs;
none is a physical DRC waiver. Host AXI backpressure seed is `0x3588c510`.
The native integrated tests use timeout/task-limit parameters 128/4. Default
endpoint mapping does not establish its 65536-cycle timeout behavior on silicon.

[current.json](current.json) indexes the completed source-bound evidence.
The additional full-endpoint mapped replay at test parameters 128/4 finished
with **sixteen passes and four failures**, not acceptance. It uses a behavioral
AXI RAM, not MIG/DDR. Injected RRESP, first/final BRESP, and high-address error
cases fail their unchanged assertions, although both RTL simulators pass.
A trace shows adapter state bit 3 and error-register enable remain unknown
after startup in this harness. Adding an external reset transition at 1/2 ns
while retaining the 200 ns clock hold and default GSR makes that state known
and passes the complete RRESP-error test. No DUT state, vendor primitive,
command or assertion was changed. This is not yet a passing twenty-case rerun.
A simplified isolated LUT4/FDRE reproducer did not reproduce the unknown state;
that negative diagnostic is retained. The full-cone startup behavior still
needs scrutiny rather than a blanket claim that any static reset fails.
Earlier mapped-board results remain historical evidence for their
own snapshots, even though the board RTL is unchanged.

The completed results establish RTL and mapped-control checks only, not full
mapped-endpoint acceptance or a completed NPU.
PCIe/MIG/reset/ECC integration, FP16 GEMM, the runtime layout path, RK3588
differential captures, and physical FPGA validation remain unfinished.

### Preserved first host-control attempt: `c4e3d828c3bd`

The current worktree adds `rk_job_control`, `rk_ew_axi`, two RTL benches and a
focused endpoint/control XC7 mapping check. Full `make test` passed at source
`c4e3d828c3bd`: 44 Python methods, 1,087,299 C++ comparisons, strict lint and all
246 entries in each of Verilator and Icarus (zero warnings, twelve benches).
All 82 cross-simulator memory dumps agree; eleven host-path dumps in each
simulator also equal their direct-memory counterparts. The first focused synthesis check mapped both tops,
but its mapped-control simulation failed on an unknown first read response.
A minimal test reproduced a pinned primitive-model startup issue: static
declaration-initialized inputs did not trigger the LUT model's event-sensitive
evaluation. Driving the address after time zero under reset made the same
mapped netlist pass all control assertions in a diagnostic run. No DUT state,
vendor primitive or expected result was changed. That snapshot's checked-in
mapped harness lacked the initialization transition. Its failed check and
passing diagnostic are retained in
[the attempt archive](runs/2026-09-21-c4e3d828c3bd/current_index.json), not counted
as final mapped-control acceptance.
The unchanged board's previous mapping remains historical, source-bound evidence.
See [HOST_CONTROL.md](../docs/HOST_CONTROL.md) for scope and reset/ownership rules.

## Previous verified source: AXI-memory adapter, 2026-09-21

Source manifest:
`2434cc400305a77900e5d0f6706619182a06bfcb3df653b4c75efcdd5048de8f`.
This increment adds `rk_axi_mem` and its AXI/DMA bench; the existing arithmetic,
decoder, DMA, board RTL, constraints and all 610 prior vector files are unchanged.
Only the Makefile and RTL/synthesis runners change among existing source files.
See [AXI_MEMORY.md](../docs/AXI_MEMORY.md) for the 512-bit/31-bit memory contract,
ordinary-RAM restriction, ECC integration caveat and joint-reset requirements.

| Fresh check | Actual result |
|---|---|
| `make -j2 test PYTHON=/usr/bin/python3` | PASS, exit 0: generated checks, 44 Python methods, numeric model, strict lint and both simulators |
| Verilator 5.048 | PASS: all 225 result entries across ten benches; zero warnings |
| Icarus 13.0 | PASS: all 225 result entries across ten benches; zero warnings |
| New AXI tests in each simulator | PASS: protocol/lane/reset bench, nine production DMA replays, six DMA bus-error/timeout cases |
| Memory comparisons | PASS: 71 cross-simulator images; all nine AXI images also match their direct halfword-memory counterparts in each simulator |
| C++ numeric model | PASS: 1,087,299 comparisons, seed `0x3588`, 76.439 s; not RTL/hardware evidence |
| `make synth-check PYTHON=/usr/bin/python3` | PASS, exit 0: board mapping and functional netlist self-test/reset, standalone DMA mapping, standalone AXI mapping |
| Standalone AXI mapping | 72 FDRE, 1,081 LUT1..6, 18 CARRY4, 354 MUXF7, 69 MUXF8; no placed utilization or Fmax claim |
| Board mapping | Two RAMB36E1, one DSP48E1, 800 flip-flops, 3,304 LUT1..6; unchanged BRAM board top |
| Mapped-board simulation | PASS at 85.060 us simulated time; 340.399 s host time; unchanged 100 us HDL timeout |
| Full Vivado | UNAVAILABLE, exit 2; no P&R, timing closure, bitstream or hardware execution |

The new AXI backpressure seed is `0x3588a512`; prior seeds remain unchanged.
Yosys reported eleven board-map warnings, one standalone-DMA warning and one
standalone-AXI warning. The board netlist compile retains ten typical-delay
warnings from the Xilinx DSP model. Exact messages and commands are retained.
No constraint, error expectation, DRC or timing gate was relaxed.

Supplemental mapped-AXI functional simulation **passed all 16 runs**: the
protocol bench, nine production captures and six DMA faults. All nine observed
memory images match the direct RTL images byte for byte. Its separate report
distinguishes the mapped adapter from the still-RTL DMA/core and behavioral RAM
slave. The archived `build/axi_mapped_wrapper.sv` holds the test clock for 200 ns
before normal operation, preserving the default Xilinx global startup model.
No model or reset check is disabled. One inherited-timescale warning from the
Yosys-exported module is retained in the mapped compile log. Exact export,
compile and simulation commands are recorded in `axi_mapped_report.json`.
Neither path is a MIG simulation or a physical DDR test.
The board top remains BRAM-only, and FP16 GEMM/full-NPU support, PCIe/MIG
integration, RK numerical differential captures and physical validation remain
unfinished. The prior `a7c0c42d885e` archive below validates only its own source.

[current.json](current.json) indexes this increment's source-bound evidence in
[runs/2026-09-21-2434cc400305/](runs/2026-09-21-2434cc400305/). The archive contains
only the logs/artifacts referenced by this run, its sources, fixtures, docs and
mapped adapter harness. Earlier debug runs are not acceptance evidence.

## Previous verified source: captured-DMA board self-test, 2026-09-21

Source manifest:
`a7c0c42d885e700e3606baf36ead92ba9a1e5a9b6ec5fb69a1faeee0ec51692a`.
`ypcb_top` now runs the unchanged production SUB(9) command chain through
`rk_ew_dma`, a fixed checked BRAM aperture, and complete memory readback.
See [DMA_BOARD_DEMO.md](../docs/DMA_BOARD_DEMO.md) for command hashes, memory
windows, sequencing and the limited scope. The legacy demo remains tested.

| Fresh check | Actual result |
|---|---|
| `make -j2 test PYTHON=/usr/bin/python3` | PASS: generated sources, 44 Python methods, numeric model, strict core/DMA/board lint, both simulators |
| C++ numeric model | PASS: 1,087,299 comparisons, seed `0x3588`; not RTL or hardware evidence |
| Verilator 5.048 | PASS: 12,963 ALU vectors, 140 legacy scenarios, 62 DMA scenarios and six additional benches; 209 result entries, nine benches |
| Icarus 13.0 | PASS: same suite, including unknown-readback rejection in both demos |
| DMA board demo | PASS: two tasks, 324 accelerator requests, 32 writes, 336 initialized and 336 checked halfwords; interrupted execution, faults, watchdog and recovery |
| Sparse aperture | PASS: 80 checked transfers plus adjacent-request/reset tests; both ports, window boundaries, gaps, odd/unmapped addresses and nonaliasing |
| Prior stimulus preservation | PASS: all 610 archived EW/DMA vector files byte-identical, retaining all 140+62 scenario expectations |
| Cross-simulator memory | PASS: all 62 DMA observed-memory dumps byte-identical |
| Xilinx Tcl 8.6.13 | PASS: ten mocked-Vivado build-control methods; not physical implementation |
| `make synth-check PYTHON=/usr/bin/python3` | PASS: fresh DMA board XC7 mapping, BRAM gate, functional mapped-board self-test/reset, and standalone DMA mapping |
| Software demo replay | PASS: legacy three-task demo and captured two-task DMA demo; software only |
| Full Vivado build | UNAVAILABLE, exit 2; no P&R, timing closure or bitstream |

The mapped board uses two RAMB36E1 blocks (one ROM and one working RAM), one
DSP48E1, 800 flip-flops and 3,304 LUT1..6 primitives. The standalone DMA top
uses one DSP48E1, 731 flip-flops and 3,137 LUTs. These are technology-mapped
counts, not placed utilization or frequency results. The mapped board test
uses only clock/reset/LED ports and the pinned Xilinx functional primitives;
it passes startup and reset/restart at simulated time 85.060 us, within the
unchanged 100 us HDL timeout. Host simulation took 340.987 seconds; that time
is not an FPGA performance measurement.

Both HDL runners reported zero warnings; Verilator `-Wall` remains fatal.
Yosys retained eleven board-map warnings (one ABC and ten RAM/ROM port-width
normalizations), one standalone-DMA ABC warning, and ten typical-delay warnings
from Icarus compiling the unchanged Xilinx DSP model. All warnings and commands
are in the detailed reports; none is a waived physical DRC. Vector seeds remain
`0x3588`, ALU backpressure `0x12345678`, and memory backpressure `0x35881234`.
The new board/aperture tests are directed.

[current.json](current.json) indexes fresh reports, exact sources, logs,
generated fixtures, observed dumps and mapped netlists in
[runs/2026-09-21-a7c0c42d885e/](runs/2026-09-21-a7c0c42d885e/).
Only this run's referenced logs are archived as current evidence. The incomplete
`2cd46a2112b3` attempt is explicitly labeled separately; it exposed the naming
warning corrected before this run. No old passing log validates changed RTL.

The arithmetic, decoder, DMA engine, BRAM implementation, legacy generated ROM,
XDC and electrical/timing/DRC gates are unchanged. The build Tcl change selects
the new board RTL sources. This remains an autonomous EW test, not a complete
NPU, RK silicon differential result, full tinygrad runtime, GEMM or PCIe/DDR
implementation. Numerical special-value behavior remains candidate. No board
or flash was programmed.

## Historical raw PC DMA replay: `919841ce0b86`

Source manifest:
`919841ce0b8685bde4844b861ae027a85aaf80fe1ad73d98d1e20ce9def5e1a1`.
The separate `rk_ew_dma` top fetches unchanged command BOs, validates finite
task framing and follows encoded EW chains. The raw-word core retains its
terminal-only rejection contract. No arithmetic datapath, board constraint,
electrical setting or timing/DRC gate was changed. See [PC_DMA.md](../docs/PC_DMA.md).

| Fresh check | Actual result |
|---|---|
| `make -j2 test PYTHON=/usr/bin/python3` | PASS: generated sources, 41 Python methods, numeric model, strict core/DMA/board lint, both simulators |
| C++ numeric model | PASS: 1,087,299 comparisons, seed `0x3588`; not RTL or hardware evidence |
| Verilator 5.048 | PASS: 12,963 ALU vectors, 140 legacy scenarios, 62 DMA scenarios and four other benches; 207 result entries |
| Icarus 13.0 | PASS: the same seven-bench suite, including four-state readback failure detection |
| Production DMA replay | PASS: nine verbatim ADD/SUB/MUL captures, lengths 8/9/33, including two-task SUB; full mapped-memory comparisons |
| Legacy stimulus preservation | PASS: all 423 archived vector files, including all 140 scenario records and ALU stimuli, byte-identical |
| Xilinx Tcl 8.6.13 | PASS: ten mocked-Vivado build-control methods; not physical implementation |
| `make synth-check PYTHON=/usr/bin/python3` | PASS: fresh board XC7 mapping, BRAM gate and functional mapped self-test/reset; separate standalone DMA mapping |
| Software demo replay | PASS: three tasks, 72 transactions; software only |
| Full Vivado build | UNAVAILABLE, exit 2; no P&R, timing closure or bitstream |

The mapped board demo remains one RAMB36E1, one DSP48E1, 478 flip-flops and
2,272 LUT1..6 primitives. The standalone DMA top maps to one DSP48E1, 731
flip-flops and 3,137 LUT1..6 primitives. DMA is not integrated into the board
demo, and its mapped netlist was not simulated. These are technology-mapped
counts, not placed utilization or timing results.

Tool versions and all commands are retained in the detailed reports. Both HDL
runners reported no warnings; Verilator `-Wall` remains fatal. Yosys retained
ten board-map warnings (one ABC and nine RAM-width normalization warnings),
one standalone-DMA ABC warning, and ten typical-delay selection warnings from
Icarus compiling the unchanged Xilinx DSP model. None is a waived Vivado DRC.
Seeds remain vectors `0x3588`, ALU backpressure `0x12345678`, memory backpressure
`0x35881234`. DMA simulation uses timeout 128 and task limit 4; the standalone
mapping uses the defaults 65536 and 4095.

[the saved index](runs/2026-09-21-919841ce0b86/current_index.json) indexes that run's reports and artifact archive in
[runs/2026-09-21-919841ce0b86/](runs/2026-09-21-919841ce0b86/).
The archive includes portable production BO fixtures, generated inputs/expected
values, per-case observed memory dumps, actual tool logs and the tested sources.
Only this run's referenced logs are archived as current evidence. The nine
production captures' observed memories are byte-identical between simulators.
Inputs and expected values are synthetic; neither simulator supplies RK silicon
goldens. Numerical special-value policy remains candidate behavior. FP16 GEMM,
PCIe/DDR, full tinygrad coverage, physical FPGA testing and RK3588 differential
validation are unfinished. No card or flash was programmed.

Vortex's FP16 tensor-core pipelines were source-audited as possible later donors;
none was imported or simulated. See [LOCAL_REFERENCES.md](../docs/LOCAL_REFERENCES.md).

## Historical initialized EW profile: `16fee6eb0780`

Source manifest:
`16fee6eb0780f29f391346d44161b084a377908ea160a82135be85f11c23e787`.
The generator, RTL decoder and software profile now implement the current
backend's 13-register FP16 bypass/unity initialization group. Unknown fields,
unsupported values, partial initialization and dimension mismatches still fail.
No arithmetic datapath, board electrical constraint or timing/DRC gate changed.
See [EW_INITIALIZATION.md](../docs/EW_INITIALIZATION.md) for the exact contract.

Fresh checks for this manifest:

| Check | Actual result |
|---|---|
| `make -j2 test PYTHON=/usr/bin/python3` | PASS: generated checks, 38 Python methods, numeric comparisons, strict lint, both RTL simulators |
| C++ numeric model | PASS: 1,087,299 comparisons, seed `0x3588`; not RTL or silicon evidence |
| Verilator 5.048 | PASS: 12,963 ALU vectors, 140 command/memory scenarios and four other benches; 145 result entries |
| Icarus 13.0 | PASS: the same suite, including four-state unknown-readback rejection |
| Original vector preservation | All 77 old scenario records unchanged; ALU vectors byte-identical to archived `6f9a9681713f` |
| Build control under Xilinx Tcl 8.6.13 | PASS: ten mocked-Vivado control-flow tests; not physical implementation |
| `make synth-check PYTHON=/usr/bin/python3` | PASS: Yosys 0.65 XC7 mapping, BRAM inference and functional mapped-board self-test/reset |
| `make demo-replay PYTHON=/usr/bin/python3` | PASS: software-only three-task replay |
| `make fpga PYTHON=/usr/bin/python3` | UNAVAILABLE, exit 2: full Vivado absent |

The mapped self-test has one RAMB36E1, one DSP48E1, 478 flip-flop primitives and
2,272 LUT1..6 primitives. This is not placed utilization or timing closure, and
the mapped self-test uses the existing three terminal demo operations. The
initialized profile's additional cases run in the regular RTL suite. Fatal
Verilator `-Wall` policy is unchanged. Mapping/primitive-model warnings are
retained in the synthesis report, not waived as physical DRC results.

The separate current-backend capture uses production `to_program` and the actual
final runtime writer at `078eee94d8f1912bb63ce786c250d2c24984844a`. Nine synthetic
input cases retain raw command/task/argument/scratch BOs. Their 31-word initialized
body is recognized, but raw replay stops at E7 on the nonzero PC next-address.
The RTL capture check verifies rejection with no memory transactions; it is
**not a passing arithmetic/backend replay**. No command words were rewritten,
no runtime tensor gather was allowed, and no hardware outputs are supplied.

[the saved index](runs/2026-09-21-16fee6eb0780/current_index.json) indexes that run. Detailed reports, source manifest,
logs, stimuli and capture files are archived under
[runs/2026-09-21-16fee6eb0780/](runs/2026-09-21-16fee6eb0780/).
All arithmetic exceptional-value behavior remains candidate until RK differential
tests. PC DMA, FP16 GEMM, PCIe/DDR integration, full backend coverage, Vivado
implementation and physical board execution are unfinished. Nothing was programmed.

## Historical Fedora continuation: `6f9a9681713f`

The strict FP16 EW slice now passes actual RTL simulation and a functional XC7-mapped self-test. This is not a completed NPU, timing closure, a bitstream, or hardware validation.

The tested source-manifest SHA256 is `6f9a9681713fc61a1338e72237eaa333e4ee14911079126524ba628b634ff7ae`. This unpacked tree has no Git commit. The reports include every file hash in that manifest; documentation and the separately hashed backend-encoder check are outside it. Run timestamps are recorded in UTC (2026-09-20), which is 2026-09-21 locally.

| Check actually run | Result and scope |
|---|---|
| `make generated-check` | PASS: register file and demo ROM match their generators |
| Python unit tests | PASS: 30 methods (20 model/fixture, 10 build-control) |
| Build Tcl control flow | PASS: ten methods under Tcl 9.0.3 and Xilinx Tcl 8.6.13, with Vivado commands mocked; not implementation/DRC/timing evidence |
| C++ integer arithmetic vs independent Python oracle | PASS: 1,087,299 comparisons; not an RTL test |
| Strict Verilator core and board-top lint | PASS: `-Wall`, no nonfatal-warning override |
| Verilator RTL | PASS: 12,963 ALU vectors, 77 command/memory scenarios, plus four additional testbenches; 82 result entries |
| Four-state Icarus RTL | PASS: same suite, including actual X-valued readback fault injection |
| Software demo replay | PASS: ADD/SUB/MUL, three tasks, 72 halfword transactions; software only |
| Yosys XC7 mapping | PASS: `check -assert`, primitive mapping, block-RAM inference gate, and final `check -assert` |
| Mapped board netlist with functional Xilinx models | PASS: self-test, reset and restart through the board ports |
| Actual candidate tinygrad backend encoder/PC-tail writer | PASS: nine final raw command streams into RTL, with synthetic BO input/expected data |
| `make fpga` | UNAVAILABLE (exit 2): full Vivado not installed; Vivado Lab alone cannot run this build |
| RK3588 differential comparison | NOT RUN: no hardware command/input/output captures supplied |
| YPCB physical self-test, DRC, placement/routing and timing | NOT RUN; no card or flash was programmed |
| Full tinygrad runtime integration / `test_ops` | NOT IMPLEMENTED by this slice; no success claim |

[current.json](current.json) is the current machine-readable index. The [run directory](runs/2026-09-21-6f9a9681713f/) contains copies of the five detailed reports, build-control logs and an `evidence.tar.gz` archive with the tested sources, generated stimuli, actual logs, backend command fixtures and mapped netlist. Paths inside the reports refer to the original workspace or the archive's `build/` tree. Intermediate failed/debugging runs are not included as acceptance evidence. The explicitly named `expected_old_build_failure.log` demonstrates a regression against the prior build script, not a failing current test or a physical FPGA test. The archive is not a bitstream.

### Tools, seeds and warnings

- Verilator: `5.048 2026-04-26 rev vUNKNOWN-built20260426`.
- Icarus Verilog: `13.0 (stable) (v13_0)`.
- Yosys: `0.65`, commit `aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`.
- C++: `c++ (GCC) 16.1.1 20260515 (Red Hat 16.1.1-2)`; test-runner Python: `3.14.5`.
- Build-control Tcl: default `9.0.3`; installed Xilinx runtime `8.6.13`. Both runs mock every Vivado command and generate no bitstream.
- Vector/numeric seed: `0x3588`; ALU backpressure: `0x12345678`; memory backpressure: `0x35881234`. Demo/board/netlist tests are directed, not random.
- RTL build/simulation commands reported no warnings. Yosys reports one ABC combinational-network warning and nine RAM port-width normalization warnings; Icarus reports ten typical-delay selection warnings in the unmodified DSP48E1 model. These are retained in the detailed reports, not hidden. Both structural check gates and the functional netlist test passed; this is not a claim that Vivado DRC or timing would pass.

The mapped board top has one RAMB36E1, one DSP48E1, 454 flip-flop primitives and 2,234 LUT1..6 primitives. This is a technology-mapped cell count, not placed utilization or a speed estimate. The simulation uses the pinned official Xilinx functional models in `tests/vendor/xilinx-unisim`, including global startup behavior. Their internal functional delays do not substitute for routed/SDF timing. Yosys's declaration-only RAM simulation stubs were insufficient and are not used to claim this test passed.

### Changes exercised by this run

The follow-up changes only `fpga/build.tcl` and adds `tests/test_fpga_build.py` within the source manifest; CI additionally installs Tcl, and the documentation is updated. The RTL and XDC remain byte-identical to snapshot `cfe7ccecd056`. All checks above were nonetheless rerun for the new full source manifest.

The build script now validates electrical-variable pairs and boolean options before synthesis, applies supplied configuration-bank properties before checkpoints/implementation/DRC, and requires block-RAM inference. Missing timing paths, nonfinite/unavailable/negative setup or hold slack, and blocking or unknown DRC severity stop the build. The ordering test detects four expected failures against the archived old script and passes all four legal pairs against the fixed script. The ten control-flow methods do not evaluate actual voltage, delay or DRC results, and do not replace full Vivado. No constraints or DRC severities were relaxed.

The preceding RTL hardening is also re-exercised:

The four-state test exposed a self-test bug: ordinary inequality could let unknown readback data evade the mismatch path. The demo now uses case inequality and verifies both known corruption and unknown data, sticky failure, and reset recovery. Other changes make simulator timescales and testbench initialization/widths explicit, reject invalid static RAM/timeout parameters, and extend backpressure, RAM and board-reset checks.

All original 38 command scenarios retain their error expectations. The 77-case set adds missing required registers, mutated fixed fields, a stalled-request timeout, and faults after committed writes or on the last write. Raw final command QWORDs remain the execution boundary; no runtime CPU arithmetic or layout fallback was added. Exceptional FP16 behavior remains a candidate policy until compared with RK silicon.

### Reproduce

```sh
make generated-check
make test
make demo-replay
make synth-check
```

To repeat only the build-control tests with the installed Xilinx Tcl runtime:

```sh
RK_TEST_TCLSH=/home/fedora/vivado/2026.1.1/Vivado_Lab/bin/xtclsh \
  python3 -m unittest discover -s tests -p test_fpga_build.py -v
```

The optional backend encoder check requires the exact clean checkout and Python dependencies described in [BACKEND_CAPTURE.md](../docs/BACKEND_CAPTURE.md). It runs the backend's real final encoder, intercepting only BO allocation/submission; no DRM device is opened. The earlier unconfirmed candidate pin was `c6784623afc4f116ae7dc326ab9842e6bf9a3dcf`; the current supplied backend and capture evidence are described above. RK differential captures remain a compatibility acceptance target, not a blocker to donor-based implementation. The former unavailable-Vivado/open-source-route description is historical; the current continuation uses Vivado and retains all timing/electrical gates. Hardware actions still require explicit authorization and an audited target/electrical configuration.

## Historical delivery evidence (unchanged)

The earlier Fedora snapshot and its reports remain under [runs/2026-09-21-cfe7ccecd056/](runs/2026-09-21-cfe7ccecd056/). That run validated the earlier build script and 20 Python test methods; it is not the acceptance record for the build-control changes above. Its archive checksum is preserved.

The top-level `status.json`, `model_test.log`, `numeric_report.json`, `demo_replay.log`, `fresh_source_build.log`, `rtl_attempt.log`, `rtl_report.json` and `fpga_attempt.log` are from the original source-delivery environment. That environment lacked Verilator and Vivado, generated only 38 engine scenarios, and executed no RTL. Those logs do **not** validate the modified sources and have not been relabeled as current passes.

`delivery_SHA256SUMS` preserves the original package manifest. Existing root checksum manifests are historical package-integrity records, not evidence that unrun tests passed; they are preserved, not refreshed or newly created under the user's current no-SHA256SUMS instruction. Current executed reports retain embedded source/input fingerprints. Do not validate today's modified tree against `delivery_SHA256SUMS` or copy these old software-only results forward as fresh RTL evidence.
