# Retained PCIe link epoch

The physical PCIe shell must keep the NPU, ownership mux, packet mailbox and
DDR transaction state in their joint retained reset epoch. A PCIe reset cannot
clear or reassign an existing backend owner. The existing frontend accepts
already synchronized health levels; it does not implement a clock crossing.

`rk_transport_epoch_guard` is a preparation component in that retained UI
domain. Its `up` input must already represent synchronized PCIe link and
AXI-interface readiness. At startup, an absent or unknown link cannot admit
traffic. The default requires four consecutive known-high UI samples before
`ready` rises. Once any known-high sample has occurred, a subsequent low or
unknown level latches `failed`, even if the first high interval was too short
to arm. A later link recovery cannot clear it. Only the joint retained reset
starts a new transport epoch.

The current same-clock `rk_pcie_jtag_frame_frontend` connects this guard's
`ready` and `seen_up` state to PCIe source health and exposes sticky
`pcie_epoch_fault`; that fault also contributes to PCIe IRQ. The current public
`rk_dual_host_ddr` selection is 72 RTL sources with the epoch guard included.
The health input remains an already-synchronized UI-domain level; this
integration does not add CDC logic.

After PCIe health has risen, a subsequent loss invalidates PCIe even if the
external link recovers. The owner mux therefore cannot accept another PCIe
claim or forward its backend request. An existing PCIe owner remains latched
and faults through link recovery until joint retained reset. JTAG health is
independent and remains usable when there is no PCIe-owned backend session.
The epoch guard does not reset the packet mailbox or gate its AXI-Lite channels;
an in-flight partial transaction remains retained. The packet mailbox snapshots
admission separately on AW and W; either disqualified half, or admission loss
before write commit, returns SLVERR without staging, START or ACK effects.
Disabled reads return SLVERR and zero data. Already held responses remain
stable and drain normally. AXI VALID/READY are not withdrawn by link health.

Connect qualified `ready` to the PCIe source-health input of the ownership
frontend when assembling the physical shell. An owned PCIe session then
quarantines on link loss through the existing ownership fault. A JTAG session
may continue using its independent healthy source. Never use PCIe PERST#,
XDMA AXI reset, or link recovery to reset the guard or shared backend.

This guard supplies no AXI channel gating, CDC FIFO, PCIe IP, IRQ mapping or
physical integration. Requests already offered at an AXI boundary still need
normal stable-valid/drain handling. The physical shell must bind vendor CDC
reset behavior, synchronized health, fault reporting and recovery before this
component can qualify an end-to-end transport. Its output alone is not a
clock-crossing or board result.

The standalone guard passes strict Icarus/Verilator checks at FRESH_CYCLES=2
and 4, including invalid-parameter fatal controls; Icarus additionally checks
X/Z poisoning. The integrated same-clock frontend test passes 2,090 checks in
each simulator. The separate mailbox-admission suite passes 83 Icarus/71
Verilator checks. These component results do not qualify PCIe IP/CDC, a
physical shell or board behavior.

The current 72-source healthy-link EW replay now passes
[independent review](../build/dual-host-npu-public-admission-v3/root-result-review.json)
with the epoch guard and per-half mailbox admission snapshots selected. Both
jobs compare all 1,600 complete BO lines before their job ACK. This uses the
independent AXI RAM/minimal ECC-control model; actual PCIe IP/CDC, physical
interfaces and the separate local-release FPGA reset candidate remain unqualified.
