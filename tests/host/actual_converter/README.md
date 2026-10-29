# Actual AMD AXI Clock Converter functional controls

`tb_actual_converter_reset.sv` instantiates the installed
`axi_clock_converter_v2_1_36_axi_clock_converter` model with the public
`rk_pcie_bridge_reset`. The [source contract](source-contract.json) records
the five AMD files and exact converter settings. The runner resolves a
Vivado installation from `--vivado-root` or `RK_VIVADO_ROOT`; it accepts either
the Vivado directory itself or its parent directory containing `Vivado/`. If
both sources are provided, their selected vendor files must match the same
content hashes.

The bench uses an independently implemented AXI-Lite slave, with separate AW
and W capture, address/protection/strobe errors, held responses, and a retained
word/write count outside the common reset. It checks GSR release, staggered
startup readiness, 4.0 ns and 7.5 ns stoppable clocks, four interrupted-channel
reset cases, recovery, no stale responses or replay, and exact cumulative S/M
handshake counts. Full-AXI-only inputs are tied off, and their unused outputs
are recorded as observations rather than assigned a zero-value contract.

The reset wrapper covers the shared converter epoch. A physical shell must
assert it together with upstream request quiescence and reset handling for any
queues or owners before releasing the bridge. The wrapper does not detect a
later link/clock loss, synchronize PCIe link health, preserve independently
reset transactions, provide CDC placement/timing signoff, or qualify PCIe,
XDMA, NPU arithmetic, a board, or RK execution.

The runner executes Verilator first and may execute four-state XSim on the
same source when selected; the XSim dependency-only probe is a separate
scope-limited receipt. It records visible vendor/authored warnings, tool
versions, hashes, and owned process-group cleanup. It sets no memory, swap, or
CPU limits. The optional `host-pcie-actual-converter-test` target is not part
of default `make test`; set `RK_VIVADO_ROOT` or pass `--vivado-root` and use a
fresh `--out` directory.

The private V1 baseline has an independent 419-check Verilator/XSim review at
`build/pcie-actual-converter-root-review-v1/root-result-review.json`. Its
receipt is a reference for this portable control; the public target creates a
new source-bound receipt.
