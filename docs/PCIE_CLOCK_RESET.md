# PCIe clock and retained-reset preparation

This is an integration contract, not a qualified PCIe shell. The current
`rk_dual_host_ddr` profile still accepts same-clock AXI-Lite and synchronized
health inputs. Its native EW replay does not test asynchronous PCIe traffic.

The independent UI clock owns the packet mailbox, transport lease and NPU
backend. JTAG must remain usable when the PCIe reference clock is absent.
XDMA `axi_aclk` is the PCIe-side AXI clock; an asynchronous AXI-Lite crossing
must carry every address, protection, data, strobe, response and handshake
signal into the UI domain. Addresses and data are 32 bits. The packet BAR
provides the existing raw-frame protocol; it does not map tensor operations
or grant direct DMA access to the NPU's retained BOs.

Only the retained whole-transaction reset may reset the crossing, packet
mailbox and transport ownership. The upstream AXI master must also be reset
or demonstrably quiescent for that whole epoch; clearing only the converter
while the master retains VALID or outstanding transactions can replay an old
request or misassociate a response. The native test master clears its bus
state on the same epoch. Actual XDMA reset/quiescence wiring remains unqualified. PERST#, `user_lnk_up`, XDMA `axi_aresetn`, and
compute reset must not independently clear those states. Link/clock loss must
reach the UI health logic and latch quarantine through link recovery. An
accepted request may already have had effects; reconnecting must not retry it
or return ownership to another host. Recovery uses the explicit joint epoch.

The OpenTPU `c0182863` and ZYNQ-NVDLA references inform IP settings, pins and
independent clock generation. Their resets incorporate PCIe resets into
host-side state. Copying those reset connections would violate this contract.
See the [reference inventory](../build/pcie-reference-inventory-v1/NOTES.md).

AMD's installed Vivado 2026.1 `axi_clock_converter_v2_1` source implements
asynchronous AXI4-Lite with five independent `lite_async` channels. Each
channel's reset-delay register and FSM reset on its own clock edges. Its
`xpm_cdc_handshake` instance has no reset input. A joint reset pulse therefore
does not establish that a stopped PCIe-clock side has cleared. The separate
non-Lite FIFO reset logic is not evidence for the Lite path. The relevant
source is `data/ip/xilinx/axi_clock_converter_v2_1/hdl/axi_clock_converter_v2_1_vl_rfs.v`
under the Vivado installation: `lite_async` reset/FSM/handshake at lines
510–646, and the five-channel Lite composition at lines 1614–1775. The XGUI
maps `ACLK_ASYNC=1`, `PROTOCOL=AXI4LITE`, and `SYNCHRONIZATION_STAGES=3`;
the generated XCI and wrapper still need independent verification.

The unselected [reset component](../rtl/host/rk_pcie_bridge_reset.sv) prepares
that initialization boundary. After an observed common assertion, both reset
outputs remain low until each domain has observed at least eight local
edges and a synchronized peer reset witness. Each then releases through
three local stages, observes five further local edges, and exchanges a
settled witness. The UI/JTAG frontend does not use these bridge reset outputs.
A clock stopped during initialization leaves PCIe unavailable without holding
the UI frontend in reset. Readiness records initialization history; later
clock loss needs a separate health detector. The two ready flags need not
rise together: synchronize destination readiness before exposing upstream
traffic. No unilateral link reset or automatic recovery is provided.

This component is not selected in the 72-source NPU profile or any FPGA
image. `make host-pcie-bridge-reset-test` passes 105 checks in each of Icarus
and Verilator across three reset epochs, plus six expected invalid-parameter
failures. Its [source-bound receipt](../build/pcie-bridge-reset-v1/20261029T145710085796Z/report.json)
records all 19 owned process groups closed and unchanged source hashes, with
RAM/high/swap uncapped. It does not instantiate the AMD converter. Actual
converter simulation with stopped clocks and stale handshakes,
generated-wrapper/CDC constraints, combined resource
fit, routing, bitfile audit and independent physical JTAG/PCIe execution are
separate gates. In particular, counter values alone do not qualify the
vendor handshake after reset. Physical integration must also capture a
link/clock-loss event when the PCIe clock stops, rather than assuming a
source-clocked pulse reaches the UI synchronizer.

The installed, unmodified converter/XPM/infrastructure sources now elaborate
in Verilator with an explicit vendor `glbl glbl();` instance in the test top.
The [dependency receipt](../build/pcie-actual-converter-dependencies-v1/attempt-6-glbl-wrapper/report.json)
records all primary source hashes and visible diagnostics. This uses normal
XPM simulation mode, without `ONESPIN` or `SYNTHESIS` defines, and proves
elaboration only. The separate optional
[public functional target](../tests/host/actual_converter/README.md),
`make host-pcie-actual-converter-test`, now
[passes both Verilator and four-state XSim](../build/pcie-public-actual-converter-v3/report.json):
419 checks, five common epochs, exact ten-channel handshake counts and seven
write effects. Both use the unmodified vendor sources and one initial GSR
event. Partial writes and held B/R responses are checked through stopped-clock
joint resets. The test master and slave reset their transaction state under
that same epoch; this does not qualify real XDMA reset/clock-loss handling,
NPU operation through the crossing or physical CDC. The target is optional
and requires the hash-pinned installed Vivado sources.

The [generated XDMA metadata review](../build/pcie-xdma-generated-review-v1/review.json)
finds that both requested probe modes resolve to DMA for this target, including
the attempted bridge-only configuration. Both templates expose the 19 required
AXI-Lite signals. The child PCIe metadata enables a 1 MiB BAR0 and 64 KiB BAR1;
BAR2 is disabled. The metadata does not establish which BAR routes to the
mailbox. The optional export failure is retained, and neither bridge-only
area savings nor combined resource fit is qualified.

The [completed V4 generation and root review](../build/pcie-xdma-v4-root-review-v1/root-acceptance.json)
now bind 136 generated files and unchanged source inputs. The corrected IP
export command completed successfully. A separate
[direct-top declaration audit](../build/pcie-xdma-v4-wrapper-review-v1/review.json)
verifies 62 required ports, including all 19 AXI-Lite signals, M_AXI's
64-bit addresses/128-bit data, PCIe x8 and clock/reset ports. Its negative
controls reject internal-module decoys and wrong widths or directions. This
audit supplies the interface admission missing from the producer's broader
HDL-token check; the frozen producer is unchanged.

Effective mode remains DMA and BAR2 remains disabled. Requested 250 MHz,
the `axi_aclk` annotation of 125 MHz and interface annotations of 100 MHz
are recorded separately; actual clock and BAR behavior are unqualified.
IP-only synthesis area, combined fit, CDC, routing and physical execution
remain required.
