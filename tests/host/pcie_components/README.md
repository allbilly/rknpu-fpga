# Public PCIe source-health and DMA DECERR component tests

This directory contains portable public native tests for two standalone leaves. `rk_pcie_source_health` qualifies the divided PCIe heartbeat and link/reset/bridge readiness feeding the retained epoch guard. Its published level depends on the UI-local reset-release qualifier: common reset assertion still clears that local pipeline asynchronously, and release still requires the existing three UI edges. The health output no longer includes a direct raw SYS-reset combinational term. `rk_pcie_dma_decerr` safely terminates unsupported XDMA M_AXI traffic with DECERR and no DDR/NPU side effects. Neither test instantiates PCIe IP or accesses hardware.

The runner exercises four source/UI clock ratios, the four-state X/Z cases in Icarus, all five invalid-parameter cases in both simulators, and the original directed DMA protocol bench in both simulators. The DMA bench adds only a check counter and final count display; the original PASS marker, stimulus, timeouts, and assertions are preserved.

Run `make host-pcie-components-test` for both simulators. The runner creates a fresh timestamped output directory under `build/` unless `--out` is supplied. It uses `tools.owned_process.run_owned`, records actual tool/source hashes and logs, and applies no CPU/RAM/swap caps.

These controls do not qualify physical PCIe, CDC/RDC, timing, board integration, or a bitstream.
