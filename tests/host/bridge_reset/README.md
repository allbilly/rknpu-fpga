# PCIe bridge reset component controls

This standalone component bench exercises `rtl/host/rk_pcie_bridge_reset.sv` with unequal, stoppable source and destination clocks. It checks common epoch reset, startup reset-edge counts, peer reset witnesses, local settle counts, peer-settled readiness, staggered ready assertion, startup-only ready behavior after clock stoppage, recovery when either clock was stopped through a joint reset, repeated epochs, and invalid parameter rejection.

The common epoch asserts reset asynchronously. Each domain first releases a
separate local reset through `SYNC_STAGES` clock edges; only then does its
functional state count `RESET_EDGES`. The bench checks the exact local release
edge and zero functional state at release, followed by the unchanged reset and
settling edge counts. At the default settings this adds three startup edges
per domain. A stopped domain cannot release its local reset. Physical checks
must preserve timing between reset stages and on local reset recovery/removal;
native simulation does not establish metastability safety.

The output is limited to the reset component contract. It does not instantiate or validate AMD `axi_clock_converter` RTL, PCIe integration, CDC placement, link health, ownership quarantine, Vivado timing, a board, or RK hardware. `s_ready` and `m_ready` record startup history; separate health logic must detect a clock that stops later.

Run the two simulator matrix with `python3 tools/host/run_bridge_reset.py`. The runner uses the existing owned-process helper, preserves simulator argv[0] and executable hashes, records actual host limits without setting them, and writes fresh logs and images under `build/pcie-bridge-reset-v1/`. The focused `host-pcie-bridge-reset-test` target is part of the default `make test` recipe. It covers this reset component only; it does not qualify converter integration or physical PCIe operation.
