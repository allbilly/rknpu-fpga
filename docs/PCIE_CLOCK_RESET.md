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

The separate crossing-wrapper candidate now has its own
[fresh independent functional review](../build/pcie-axil-crossing-native-results-review-v2/review.json).
Verilator 5.048 and four-state XSim 2026.1 each pass all 419 controls,
five epochs and seven retained write effects. The adapter preserves all
19 AXI-Lite signals and does not gate VALID/READY with readiness or health.
The earlier Verilator attempt stopped before simulation on testbench filename
and unused-constant warnings; that receipt is preserved. The corrected bench
retains its original control body and uses no warning waiver. These results
qualify the wrapper's directed functional controls, not an XDMA master,
joined NPU transactions or physical CDC.

The [source-health candidate review](../build/pcie-source-health-review-v2/review.json)
checks 125/250 MHz source clocks against 50/133 MHz UI clocks, stopped clocks
and short link/reset pulses. The
[unsupported-DMA responder review](../build/pcie-dma-decerr-review-v1/review.json)
checks DECERR responses through 256-beat bursts, backpressure, IDs and faulted
drainage. The responder has no connection to either MIG or retained NPU BOs.
These source-bound component results remain distinct from combined execution.
The unchanged [source-health](../rtl/host/rk_pcie_source_health.sv) and
[DECERR](../rtl/host/rk_pcie_dma_decerr.sv) leaves now have
[portable tests](../tests/host/pcie_components/README.md) under
`make host-pcie-components-test`, included in default `make test`. The
[fresh public run](../build/pcie-components-native-20261030T131739727757Z/report.json)
passes four ratios per simulator, ten expected invalid-parameter failures,
956 four-state Icarus DMA checks and 904 Verilator DMA checks. All 46 owned
process groups close and bound source bytes remain unchanged. The
[public source/results review](../build/pcie-components-public-review-v1/review.json)
passes. The subsequent full default `make -j2 test` also
[passes independent review](../build/pcie-components-public-review-v1/full-regression-review.json):
exit zero in 805.386 seconds, 20,859 before/after/current source hashes equal,
and the nested PCIe component receipts reviewed. The local source increment
is committed as `5f3cd97`; remote CI and hardware remain unqualified.

The [combined control-plane contract](../build/pcie-control-plane-candidate-v1/CONTRACT.md)
now wires all 75 generated XDMA ports: 19 AXI-Lite signals through the actual
converter, 35 DMA signals to the DECERR responder, and explicit clock/reset,
link, interrupt and configuration-management policy. The common coordinator
epoch resets XDMA and the converter together. PERST additionally resets
XDMA and invalidates health; it must not clear retained packet/owner state.
The retained guard must quarantine accepted or partial traffic through link
recovery. Integrated loss/partial-transaction tests remain required.

The later [joined protocol-model review](../build/pcie-controlplane-guard-results-review-v19/review.json)
passes Verilator and four-state XSim at source clocks 125/250 MHz and UI
133 MHz. Each run checks 2,685 conditions across eight scenarios and six common
epochs. The actual converter, health, DECERR and retained frontend are used;
XDMA and the numerical backend are scripted fixtures. Tests cover PCIe absent
at boot with usable JTAG, exact raw frames, partial AW/W, held B/R, source clock
loss, sticky quarantine through recovery and fresh-edge joint reset. Every
owned group closes and all bound sources remain unchanged.

The selected vendor converter's reverse R channel acknowledges the UI producer
after the CPU-side R handshake returns across the synchronizer. Consequently,
the UI mailbox's observed mask can lag the completed CPU reads. The real host
client already reads CSR `0x14` before ACK; the joined test now uses that same
causal fence before requiring all twenty observed bits. A held final CPU R
keeps bit 19 unset. Consuming it later completes the mask, while the retained
epoch fault still rejects ACK. Earlier tests that assumed immediate visibility
or a full UI mask before CPU consumption remain failed, with no DUT changes.

The first combined resource-census candidate retains USER2, both original
MIGs and all 512 products. Completion is explicitly polling-only, with
`usr_irq_req=0` and inactive configuration-management requests. No MSI
notification service is offered. Its top has no warm-reset command source;
retained reset/ECC recovery must still converge with the combined shell.
Synthesis/optimization, physical constraints, CDC/RDC, routing and execution
are separate gates; this wiring is not an accepted FPGA image.

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
are recorded separately; actual clock and BAR behavior are unqualified. A
separate [root-accepted OOC IP area estimate](../build/pcie-xdma-ooc-results-review-v1/root-acceptance.json)
(acceptance SHA-256 `8f4e04d04dc5abb3c9ad8e375fe3536d0385035b8ba4d1495b343cb72e2f3c31`)
and [independent review](../build/pcie-xdma-ooc-results-review-v1/review.json)
reports 19,201 LUTs, 21,203 flip-flops, 24 RAMB36, one RAMB18, zero DSPs, one
`PCIE_2_1`, eight `GTXE2_CHANNEL`, two `GTXE2_COMMON`, and zero unresolved
nonprimitive black boxes. The OOC `axi_aclk` had a 4 ns constraint. This is a
standalone synthesized-IP area/cell census only; it does not qualify the actual
clock or BAR mapping, combined shell fit, place/route/timing, or physical PCIe.
The later [combined source-netlist census](../build/pcie-combined-fit-results-review-v1/review.json)
retains the actual XDMA, USER2, both MIGs and all sixteen C32 kernels/512 product
DSPs. Its optimized resource report has 318,084 total LUTs and 516 DSPs. The
[read-only device-budget query](../build/pcie-combined-area-probe-v1/device-utilization.rpt)
reports 298,600 available LUTs: the mapped count exceeds that budget by 19,484
(106.53 percent utilization). This is a measured combined census, not the sum
of standalone estimates and not placement/routing acceptance. An area
optimization experiment is required before proceeding toward implementation;
retain all products/controllers and every timing/electrical gate. Combined fit,
CDC/RDC, routing and physical execution remain required. A same-netlist
`ExploreArea` experiment reduces the count to 316,809 LUTs, still 18,209 over
budget. A separate [shared-accumulation-context candidate](../build/cacc-context-shared2-review-v1/review.json)
preserves all 512 product lanes and sixteen FP48 contexts with two original
NVIDIA arithmetic pipelines. Its unchanged numerical/control bench and
standalone OOC results pass review; whole-system raw jobs, resource fit and
routed timing remain unqualified. Its fresh combined build re-synthesizes all
NPU/MIG RTL rather than reusing an earlier NPU checkpoint.

The shared-context-only whole-source census subsequently completed at 300,129
LUTs, still 1,529 over budget. A second component candidate changes only the
front's payload storage to explicit 16-bit word enables. Its original numerical,
reset, cancel and fault bench passes unchanged; standalone OOC measures
14,049 to 2,038 LUTs with the same three address-arithmetic DSPs. These component
savings cannot be added as a fit proof. The new two-override whole-source build
retains all 512 products, both MIGs, USER2 and XDMA; combined fit, unchanged raw
jobs, timing and hardware remain unqualified.
