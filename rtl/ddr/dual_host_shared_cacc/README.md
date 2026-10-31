# Shared FP48 pipelines and word-bank input storage

This explicit FP16 C32/K16 profile retains all 512 parallel product lanes.
Sixteen independent accumulation contexts share two unchanged NVIDIA FP48
arithmetic pipelines. Input and weight words use statically enabled 16-bit
register banks. The CACC variant explicitly requires K16. Original raw command
words, task/error contracts and per-context accumulation order remain; the
hardware path has no CPU arithmetic fallback or runtime layout repair.

Run `python3 tools/ddr/dual_host_shared_cacc_profile.py --check`, or import
`core_source_paths()` from that module for the ordered 72-source list. Exactly
two entries replace the preceding factored dual-host profile; the other seventy
sources reuse their public bytes and order. Compile that list, since recursive
source globs include alternative definitions. Existing default profiles retain
their source selections. This profile is the NPU and same-clock two-transport
frontend; it does not include vendor MIG/PHY or XDMA sources, a physical shell,
the asynchronous converter, or the PCIe bridge reset component.

The [fresh root numerical acceptance](../../../build/dual-host-shared2-wordbanks-results-review-v1/root-acceptance.json)
binds six independently initialized model processes: 48 jobs/tasks, 36 compute
resets, 4,751,360 complete output-buffer bytes before ACK and 75,008 READ64.
JTAG initializes BOs, then the modeled PCIe frontend reuses them without host
uploads. All original errors/deadlines and the exact 96-warning inventory are
reviewed. Publication preserves the two qualified source files byte-for-byte;
source crosswalks establish that identity, rather than transferring old logs
to modified RTL.

The separate [combined resource census](../../../build/pcie-shared-cacc2-wordbanks-fit-review-v1/review.json)
measures 288,101 LUTs for its own frozen source set with both optimizations,
all 512 product lanes, both MIGs and actual XDMA. It proves neither physical
fit nor timing for this public source selection. Fresh corrected-reset combined
synthesis and constrained implementation have separate gates. No new routed
image, FPGA, PCIe, physical ECC or RK-equivalence qualification is claimed.

The current shared `rk_layout_dma.sv` has the locally qualified metadata-enable
correction described in the [factored framework profile](../framework_factored/README.md).
The profile ordering and architecture remain unchanged. The numerical and
warning receipts above retain their frozen source scope; the changed common
layout source has separate paired/mapped checks and fresh 82-source warm
integration, rather than a new execution of those historical 72-source suites.
