# Dual-host maintenance/FI preparation profile

This explicitly selected profile lists 82 ordered project RTL sources for
`rk_whole_reset_dual_host_parent`, FP16 C32/K16 with all 512 products and the
two shared CACC pipelines. It combines the framework EW/CMAC/layout/reset
backend, FI management, normal JTAG/PCIe packet ownership and retained SYS
maintenance controller. It is not selected by the default FPGA build.

Run `python3 tools/ddr/dual_host_maintenance_fi_profile.py --check` to verify
its exact source order, hashes and architecture. The manifest contains no
vendor MIG/PCIe implementation, memory/PHY model, fixture or testbench.

The current source publication is byte-identical to the 82 project sources
in the fresh timeout-classification warm replay. The
[publication crosswalk](../../../build/maintenance-timeout-publication-v1/crosswalk.json)
identifies the two changed RTL files and all 80 unchanged files. The fabric
exports an internal exact-code-8 timeout tag; the parent uses it for its two
timeout classifications. Diagnostic codes, priority, registers, latency,
numerical behavior and unsupported-field failures stay unchanged. The
[paired Icarus/Verilator review](../../../build/whole-reset-fi-timeout-tag-native-review-v1/review.json)
checks the original outputs/state, initialization permission and four-state
behavior, plus equality of the tag to the original diagnostic classification.

The selected `(1,16,32)` fresh warm model run completes sixteen layout/CMAC
jobs, twelve compute resets and one whole SYS reset. Its
[independent wire and whole-BO review](../../../build/whole-reset-fi-timeout-tag-joined-results-review-v1/review.json)
checks 1,441,792 complete BO bytes before ACK, the original final command
records, both scripted JTAG/retained-PCIe packet paths, stopped-UI SYS access,
an idle held owner, exact 16,384-line reinitialization and stale-lease denial
after SYS ACK without forwarding to the new owner. The same unchanged wire
auditor has nine saved-trace corruption/omission controls. The simulator exits
successfully, but its producer wrapper remains failed because a missing Python
`re` import stopped post-run validation. That original report is preserved;
the separate independent audit accepts the actual fresh trace and BO files.

This is an ordinary-RAM model with actual vendor CTRL/FI leaves; it rejects
nonzero FI corruption at a RAM write. It is not actual MC/PHY, PCIe-IP/CDC,
TAP or FPGA execution. Its one-MiB/four-task geometry does not qualify the
default two-GiB span or 4095 tasks. Separately scoped actual-controller
ECC/reset receipts do not qualify physical ECC in this composition.

The normal raw request/response interface is UI-clocked and the maintenance
raw interface is SYS-clocked. Upstream mailboxes must retain offered frames
across runtime reset and stopped clocks. `cfg_reset` and `ui_power_rst_n` are
configuration-lifetime resets released on their own clocks, never client,
MIG, link, PERST or TAP resets. The new frontend epoch output coordinates
packet/owner reset; retained gates and the AXI request seal survive it.

New commands stop at maintenance admission, accepted work/results drain, and
only actual backend/frontend quiet may authorize the SYS reset. An idle held
owner may cross an audited whole reset; outstanding or uncertain work may not.
The host must fence submissions and invalidate old handles on whole reset;
there is no automatic stale retry, CPU arithmetic fallback or layout repair.
Unsupported fields and original sticky errors remain explicit failures.

A physical integration must provide the exact C1 MC/FI witnesses, retain both
MIGs and both normal transports, and connect the independently retained SYS
mailbox. Broader joined recovery tests, mapped reset/CDC, placement/routing,
DRC/timing, image/target audit and actual application/ECC tests remain required.
No bitstream, board or RK-silicon equivalence follows from this source profile.
