# Dual-host maintenance/FI preparation profile

This explicitly selected profile lists 82 ordered project RTL sources for
`rk_whole_reset_dual_host_parent`, FP16 C32/K16 with all 512 products and the
two shared CACC pipelines. It combines the framework EW/CMAC/layout/reset
backend, FI management, normal JTAG/PCIe packet ownership and retained SYS
maintenance controller. It is not selected by the default FPGA build.

Run `python3 tools/ddr/dual_host_maintenance_fi_profile.py --check` to verify
its exact source order, hashes and architecture. The manifest contains no
vendor MIG/PCIe implementation, memory/PHY model, fixture or testbench.

The publication is byte-identical to the project portion of the fresh joined
native candidate. Its selected `(1,16,32)` normal replay passes eight actual
layout/CMAC jobs, six compute resets and 720,896 complete BO bytes before ACK,
first through raw JTAG frames and then through the PCIe packet frontend with
retained BOs. The wire checker compares the original final command records,
owner/lease behavior, every expected BO byte and the ACK order. See the
[source publication crosswalk](../../../build/joined-dual-host-source-publication-v1/crosswalk.json)
and [normal wire receipt](../../../build/joined-dual-host-warm-native-candidate-v1/native-v2/normal-wire-review.json).
This is an independent ordinary-RAM model with actual vendor CTRL/FI leaves;
it rejects nonzero FI corruption at a RAM write. It is not actual MC/PHY,
PCIe-IP/CDC, TAP or FPGA execution. The model uses one MiB and four tasks;
default two-GiB capacity and 4095 tasks are not qualified by it. The fresh
whole-reset replay is a separate pending gate; a normal numerical pass does
not establish warm recovery. Separately scoped core ECC/reset receipts do
not qualify this new frontend composition.

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
mailbox. Fresh joined recovery tests, mapped reset/CDC, placement/routing,
DRC/timing, image/target audit and actual application/ECC tests remain required.
No bitstream, board or RK-silicon equivalence follows from this source profile.
