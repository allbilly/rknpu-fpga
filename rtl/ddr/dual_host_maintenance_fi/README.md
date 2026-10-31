# Dual-host maintenance/FI preparation profile

This explicitly selected profile lists 82 ordered project RTL sources for
`rk_whole_reset_dual_host_parent`, FP16 C32/K16 with all 512 products and the
two shared CACC pipelines. It combines the framework EW/CMAC/layout/reset
backend, FI management, normal JTAG/PCIe packet ownership and retained SYS
maintenance controller. It is not selected by the default FPGA build.

Run `python3 tools/ddr/dual_host_maintenance_fi_profile.py --check` to verify
its exact source order, hashes and architecture. The manifest contains no
vendor MIG/PCIe implementation, memory/PHY model, fixture or testbench.

The current 82-source selection matches the four-fix combined source set.
Layout metadata capture uses its local command state; pending-fault classification
uses the directly qualified event bits; job metadata follows the active descriptor
while CSR reads remain masked during execution; and FI payload words use their
own address-qualified write enable. Raw commands, numerical operations, error
contracts and visible latency remain unchanged. The
[publication crosswalk](../../../build/control-timing-four-fix-publication-prep-v1/applied.json)
records the exact selected bytes and consuming manifest updates.

The [fresh warm replay and whole-BO review](../../../build/control-timing-combined-warm-results-review-v1/review.json)
passes sixteen layout/CMAC jobs, twelve compute resets, one whole SYS reset and
1,441,792 complete BO bytes before ACK. Both scripted transport paths, retained
BOs, stopped-UI SYS access and stale-lease denial are checked. The actual simulator
and runner pass. An initial wire-auditor invocation used the raw-only fixture
without its golden images; that failure is preserved. The successful audit uses
the original hash-bound golden fixture and unchanged expectations.

The [component and mapping evidence](../../../docs/REVIEW_AND_PLAN.md) is separate
from the [full physical-source synthesis](../../../build/control-timing-combined-synth-results-review-v1/review.json):
293,399 LUTs, 89,797 FFs, all 512 product/516 total DSPs, both MIGs, PCIe,
USER2/USER3 and 277 ports. The fresh
[strict constrained audit](../../../build/control-timing-combined-strict-results-review-v1/review.json)
passes its original constant, electrical, clock and retained reset/crossing
checks. [Fresh placement](../../../build/control-timing-combined-placement-results-review-v1/review.json)
passes its structural gates, with negative unrouted estimates of −4.352 ns
setup and −0.392 ns hold. Routed timing and new-image acceptance remain open.
The result-metadata component's OOC producer failed final JSON serialization;
its separately reviewed saved artifacts establish its mapping evidence, while
that original failed producer remains unchanged.

The warm fixture uses ordinary RAM and actual vendor CTRL/FI leaves. It does
not model MC/PHY or physical ECC corruption, PCIe IP/CDC, TAP or FPGA execution.
Its one-MiB/four-task geometry does not qualify the default two-GiB span or
4095 tasks. The [fresh actual-controller fixture](../../../build/control-timing-combined-controller-results-review-v1/review.json)
passes all twelve cases, seven SYS resets, six complete BO images/532,480 bytes
and 32,768 BIST writes/reads over one MiB. It uses a separate legacy test
wrapper and encoded PHY; these results do not qualify the physical dual-host
composition.

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
