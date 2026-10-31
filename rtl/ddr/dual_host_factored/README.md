# Factored full512 dual-host source profile

This explicit source selection adds the existing real-descriptor ownership
witnesses and same-clock PCIe/JTAG packet frontends to the factored FP16
C32/K16 compute profile. It retains all 512 products. One new parent copy
differs from the qualified factored parent only by the existing transport
release witness; 71 selected paths reuse their current public bytes.

Run `python3 tools/ddr/dual_host_factored_profile.py --check`, or import
`core_source_paths()` from that module to obtain the ordered 72-source list.
The backend manifest retains its uninstantiated predecessor for compatibility
with the shared manifest validator; the helper excludes that predecessor
before adding the five frontend sources. Compile the returned list, rather
than recursively globbing directories with alternative module definitions.

The [native root acceptance](../../../build/dual-host-factored-six-shape-results-review-v1/root-acceptance.json)
binds six independently initialized model processes: 48 jobs/tasks, 36 compute
resets, 48 complete BO images/4,751,360 bytes checked before ACK and 75,008
READ64 operations. Each shape runs through JTAG epoch 1 and then PCIe epoch 2
using retained BOs with no PCIe uploads. The full warning counter matches the
earlier native baseline plus exactly two source-reviewed reset warnings.

These tests use independent AXI RAM/minimal ECC-control models and a common
frontend clock. Actual PCIe IP/CDC, MIG/PHY, combined fit, routing and FPGA
execution remain unqualified for this source selection. The earlier physical
JTAG matmul and TinyStories results retain their own image scope.

The current shared `rk_layout_dma.sv` has the locally qualified metadata-enable
correction described in the [factored framework profile](../framework_factored/README.md).
The profile ordering and architecture remain unchanged. The numerical and
warning receipts above retain their frozen source scope; the changed common
layout source has separate paired/mapped checks and fresh 82-source warm
integration, rather than a new execution of those historical 72-source suites.
