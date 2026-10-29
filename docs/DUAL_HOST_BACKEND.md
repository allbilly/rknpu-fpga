# Backend witness for transport-session release

The witness-enabled source profile is selected through
`tools.ddr.dual_host_profile.source_paths()`. It hash-binds the 68-source FP16
C32/K16 base, substitutes three modules under `rtl/ddr/dual_host/`, and compiles
67 sources after omitting the uninstantiated predecessor dual-bank controller.
The original framework profile and its source-bound synthesis/route inputs
remain separate.

The current full `rk_dual_host_ddr` selection adds the five same-clock
frontend/top files as an explicit 72-source closure. This includes
`rtl/host/rk_transport_epoch_guard.sv`; the backend-profile count above does
not include those frontend files.

The leaf controller exports `descriptor_empty` directly from its real
`fields_valid` register. This becomes false after any successful address,
amount or tag staging write, even while every engine is idle. A rejected
write or an unsuccessful ACK cannot clear it. Existing successful-result ACK
and joint reset clear the staged descriptor as before.

The three-bank controller exports `session_quiet`: existing `control_quiet`
AND all three descriptor-empty witnesses. The existing quiet predicate includes
ownership, launches, IRQs, held B/R responses, partial AW/W transactions and
offered AXI requests. Compute-island reset retains its earlier quiet contract;
transport handoff uses the stricter witness.

The parent exports `transport_release_ready`. It requires healthy initialized
DDR, the existing fabric/engine/control/memory/fence quiescence predicate,
`session_quiet`, no blocked/in-progress/held/failed compute reset, and an idle
raw backend with no offered request or response. This is a hardware witness,
not a software read of status bits.

The intended composition connects that parent output to the frontend's
`release_ready`. The frontend reset must use the same retained client epoch
as the backend. Neither PCIe link reset nor a compute reset may independently
clear transport ownership. PCIe/JTAG clock crossings must publish synchronized
source-health levels before requests can enter the frontend.

The integrated frontend qualifies the PCIe source with
`rk_transport_epoch_guard`. Four consecutive known-high UI samples are
required before PCIe can claim the backend. After any known-high sample, a
later low or unknown synchronized health level latches `pcie_epoch_fault`
through link recovery; the fault contributes to PCIe IRQ and removes PCIe
source health. The guard does not reset or gate packet-mailbox AXI channels.
JTAG remains independent and may continue when the PCIe epoch has failed.
Only the common retained reset clears the epoch.

The frontend passes its qualified PCIe epoch as the mailbox's
`admission_enable`. AXI AW/W ready signals remain available; each accepted
half records whether admission was known high. If a half was accepted while
disabled, or admission is not known high when both halves pair, the write
returns SLVERR and cannot change staged words, commit a frame or ACK a packet.
Reads while disabled return SLVERR with zero data. Already held B/R responses
stay stable when admission changes. After link recovery, only a new complete
write pair accepted during the healthy epoch can stage another frame.

These added outputs do not extend or replace the final command-word decoder.
Raw commands, BO formats, unsupported-field errors and numerical datapaths
remain the original selected implementation. Witness source/native checks
must pass before combined NPU integration, implementation and board tests;
this source selection alone is not physical qualification.

The three-bank witness test passes 105 checks in both Icarus and Verilator,
including a cycle comparison of every original controller output. This proves
the added empty-state outputs do not change that tested control behavior;
NPU integration uses the separate current replay below; CDC and physical
qualification remain separate.

The archived 71-source parent/frontend composition passed full hierarchy lint.
Its review records inherited vendor diagnostics, the command-line width
literal used for the model aperture, and mixed synchronous/asynchronous use of
the retained client reset. That result is frozen in
`build/dual-host-npu-public-v1/source-snapshot.json` and does not bind the new
epoch-guard source. The current 72-source parent has separate fresh compilation
and numerical replay evidence below; physical clock/reset audits remain mandatory.

`make ddr-session-quiet-test` runs that comparison in both simulators and is
included in default `make test`. Fresh receipts record source hashes, Git
revision, dirty state, actual tool versions and deterministic stimulus.
`make host-transport-epoch-test` runs the standalone guard with FRESH_CYCLES=2
and 4, invalid 0/1/65537 parameter fixtures, and normal/X/Z/sticky/joint-reset
controls. Icarus exercises four-state cases; Verilator is two-state.
The integrated frontend component now passes 2,090 checks in each native
simulator, including startup-disqualified AW/W halves and explicit B/R errors
after admission loss; its standalone component receipt is
`build/host-frame-mailbox/20261029T120216322222Z/report.json`.
The [full numerical NPU/frontend replay](../build/dual-host-npu-replay-run-v2/root-result-review.json)
now passes independent native review: two raw SUB(9) jobs with four linked
tasks, 204,800 complete BO bytes checked before NPU ACK, and 3,203 modeled
physical AXI reads. JTAG releases epoch 1 and PCIe claims epoch 2, reruns the
retained program/BOs without reload, and explicitly releases after packet and
NPU acknowledgments. Early acquisition, nonowner memory writes/reset/ACK and
held-result release are denied. The frozen per-transport markers label the
two linked tasks as `jobs=2`; the review records the actual two-job total.
This uses the full numerical RTL with independent AXI RAM/minimal ECC-control
models and one retained frontend clock. Actual MIG/PHY, PCIe IP/CDC, CMAC/reset
coverage through both hosts and physical qualification remain separate.

The [archived public-source replay](../build/dual-host-npu-public-v1/root-result-review.json)
passes compilation and exact two-job/four-task BO checks for its frozen
71-source snapshot. The current `make ddr-dual-host-npu-test` recipe builds the
72-source closure, including the retained PCIe link-epoch guard and per-half
mailbox admission snapshots. The current native result is linked below; the
archived 71-source result applies only to its earlier frozen snapshot.

The current 72-source healthy-link EW replay now passes
[independent review](../build/dual-host-npu-public-admission-v3/root-result-review.json)
with the epoch guard and per-half mailbox admission snapshots selected. Both
jobs compare all 1,600 complete BO lines before their job ACK. This uses the
independent AXI RAM/minimal ECC-control model; actual PCIe IP/CDC, physical
interfaces and the separate local-release FPGA reset candidate remain unqualified.
