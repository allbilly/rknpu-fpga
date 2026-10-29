# Dual-host actual NPU replay test

## Frozen 71-source pre-epoch baseline

The dated 71-source result is preserved in
[`build/dual-host-npu-public-v1`](../../../build/dual-host-npu-public-v1). Its
`source-snapshot.json` freezes the pre-epoch-guard public inputs, and its
[`root-result-review.json`](../../../build/dual-host-npu-public-v1/root-result-review.json)
accepts that exact 71-source actual-NPU replay. This result does not bind the
later PCIe link-epoch guard source.

## Current 72-source profile

`tb_dual_host_npu_replay.sv` executes the current 72-source
`rk_dual_host_ddr` profile around the original EW SUB9 raw program. The added
source is `rk_transport_epoch_guard`, integrated into the same-clock frontend.
The test keeps the fast AXI RAM and minimal ECC-control model as an independent
test target; it is not MIG/PHY, PCIe IP/CDC, FPGA execution, or RK silicon
evidence. The current 72-source replay passes its separate source-bound native
review; the frozen 71-source result remains tied to its own sources.

The replay sequence denies an early claim before DDR is initialized, checks all
16,384 initialization writes and the hardware release witness, runs one JTAG
job containing two original raw tasks, compares the complete 1,600-line BO
image before ACK, releases lease epoch 1, then replays the same retained raw
program through PCIe at epoch 2 without uploading the BOs again. While PCIe
owns the active job, nonowner JTAG write/reset/job-ACK attempts are denied. It
compares all 1,600 complete BO lines through 20-DWORD AXI-Lite packets before
NPU ACK, checks that packet ACK leaves the global lease owned, and releases only
after the hardware witness permits it.

The PCIe source now needs four consecutive known-high UI samples before it can
claim the backend. Once it has observed any known-high sample, a later low or
unknown synchronized health input latches the PCIe epoch fault through link
recovery. The fault contributes to PCIe IRQ and removes PCIe source health;
JTAG remains an independent source. Only the common retained reset clears the
epoch. The guard does not gate/reset AXI-Lite channels or supply the external
PCIe CDC/IP. See [`PCIE_LINK_EPOCH.md`](../../../docs/PCIE_LINK_EPOCH.md).

The vectors are generated for each run from the public captured SUB9 fixture
and independent endpoint oracle in `tools.ddr.endpoint_vectors`. Their
`capture_sub_9` upload and expected files were compared byte-for-byte with the
accepted run-v2 fixture: 220,800 bytes each, SHA-256
`68cf7b0689343f22c979db0312eb718906a34d51c54e893699039f7630c885fb` (upload)
and `aca0f96badf878e82a9358eb2e5405f1ff97db706220e25e712555c38f10efec`
(expected). This is the original captured workload; the independent expected
file is a test oracle, not runtime fallback.

`rk_fast_parent_axi_model.sv` is the accepted independent model copied
byte-for-byte from preparation-v4, SHA-256
`7d6262e9442c1aea96e425fec764fb2fe762c83efef575a392f32b43d05cc9b2`.
The strict line-image parser reuses the byte-identical public
`tests/ddr/endpoint/strict_line_image.svh`.

`make ddr-dual-host-npu-test` regenerates the hash-pinned captured fixtures,
builds the explicit 72-source selection and runs it in a fresh output
directory. It is included in default `make test`; no private preparation files
or external compiler checkout are required. The current 72-source result is included in the accepted V25 frozen default
suite and its [root acceptance](../../../build/production-model-auditors/current-v25/root-acceptance.json);
the dated 71-source receipt remains tied to its frozen snapshot.

The current same-clock frontend component passes 2,090 checks in each native
simulator; its receipt is
`build/host-frame-mailbox/20261029T120216322222Z/report.json`. The standalone
`make host-transport-epoch-test` checks the four-sample arming boundary and
sticky link-loss behavior, including X/Z controls in Icarus. These component
checks and the same-clock 72-source NPU replay retain separate scopes; neither
establishes physical PCIe/CDC qualification.
