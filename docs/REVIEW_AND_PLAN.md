# Implementation plan and acceptance gates

Reviewed 2026-10-31 HKT. This is the active plan. The
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
| Joined framework/FI core, admission and reset occupancy | All twelve fresh actual-controller model cases and component checks passed independent review | The [full12 review](../build/framework-fi-converged-full12-results-review-v1/review.json) binds one fresh executable, unchanged original marker/whole-BO validators, all twelve numerical/ECC/reset scenarios and closed process groups. The actual-controller/encoded-PHY model is bounded to one MiB/four tasks; positive RKLY/RKRS coverage and the newer dual-host/physical wrapper remain separate. The [focused review](../build/framework-fi-converged-focused-review-v1/review.json) also accepts three-bank descriptor/SUBMIT denial with held-result reads/ACKs, and both production/timeout reset fixtures with health-independent maintenance quiet and three fresh UI edges. This does not qualify FPGA ECC/warm recovery |
| Measured health/fault and owner timing corrections | Three private Boolean changes passed source/native and isolated mapping review; fresh full synthesis passed | The [paired monitor/fabric review](../build/health-fault-parallel-native-results-review-v1/review.json) retains original numerical/protocol/four-state guards and compares all outputs. The [owner comparison](../build/owner-payload-zero-native-review-v1/review.json) retains 259 checks and X/Z selector/payload rejection. Identical isolated queries show monitor [6→5 levels, 3.312→2.965 ns](../build/health-fault-parallel-mapped-review-v1/review.json), fabric [2.348→2.300 ns](../build/fabric-fault-parallel-mapped-review-v1/review.json), and owner [19→8 levels, 4.059→3.422 ns](../build/owner-payload-zero-mapped-review-v1/review.json), without new registers or latency. These estimates cannot be added into a full-design timing claim. The [reviewed 190-record source selection](../build/pcie-health-fault-owner-synth-source-review-v1/review.json) changes exactly monitor, fabric and ordinary owner versus the UI-health base. The [fresh terminal synthesis review](../build/pcie-health-fault-owner-synth-results-review-v1/review.json) verifies 288,160 LUTs, 82,973 FFs, 512 product/516 total DSPs, both MIGs, PCIe and USER2, with uncapped RAM/high/swap. The subsequent [strict constrained audit](../build/pcie-health-fault-owner-constrained-opt-prep-v1/run-v1/report.json) stopped at an EW constant-field witness: optimization removed the inspected boundary connections. Disconnected pins are not accepted as constant zero; a proof-preserving correction is in preparation. Placement/routing and timing acceptance remain open |
| Unloaded XDMA route-net cleanup | Guarded net-only ECO passed independent diagnostic review | The [result review](../build/pcie-dead-net-cleanup-results-review-v2/review.json) verifies removal of exactly 23 driver-only nets (eleven scalars/four complete three-bit buses), with cells/placement/IO/other-net protection unchanged. All 438,776 routable nets remain fully routed with zero errors; exact inherited default DRC warnings remain 2,066 and RTSTAT-10 is gone. Setup −0.885 ns and hold +0.012 ns are unchanged. This modifies only the preserved older failed-timing checkpoint; it neither qualifies a new image nor transfers cleanup to changed sources without fresh target revalidation |
| PCIe BAR-path raw-frame mailbox | Standalone component and callback client passed | [Component contract](PCIE_FRAME_MAILBOX.md), `make host-frame-mailbox-test` (also in default `make test`): 1,151 Icarus/1,142 Verilator checks plus seventeen normal/optimized-Python callback controls; full raw framing, staging, backpressure, response observation and sticky faults. PCIe IP, CDC, cross-transport ownership and physical execution remain pending |
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
