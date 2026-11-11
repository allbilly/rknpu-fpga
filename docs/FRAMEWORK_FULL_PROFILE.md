# Explicit full-DDR framework profile

`tools.backend.full_runtime.install()` provides the separate FP16 CMAC/layout
profile. Supply an explicit `tools.ddr.framework_transport.FullDdrRawTransport`
with an already audited raw link and exclusive ownership. Importing either
module does not connect, program hardware or recover a failed transaction.
Registration retains the existing single-owner/single-registration contract.

For the separate witness-enabled dual-host image, use
`tools.ddr.frame_transport.FullDdrFrameTransport` with an explicitly acquired
`tools.host.raw_frame_session.RawFrameSession`. It reuses the same BO, job,
profile and compute-reset methods over one raw-frame exchange callback. It
checks all four namespace identities and all three idle job banks before
admitting writes. It calls no JTAG initializer, creates no device lock and
opens no physical endpoint. A PCIe caller can supply the
[MMIO packet client's](PCIE_FRAME_MAILBOX.md) `exchange` and `close` callbacks
to `RawFrameSession`, identifying physical source 2; the existing JTAG entry
continues to use its audited scan transport. The dual-host image additionally
requires the [RKHO ownership bank](RAW_FRAME_OWNERSHIP.md).

The caller owns per-transport exclusion and audits the image and endpoint.
Call `transport.release()` explicitly after complete BO readback and job ACK.
`transport.close()` closes the supplied session without releasing or resetting
hardware. Backend and RKHO management requests share the session's completion
sequence allocator, including release after a backend request. A physical
retained-mailbox caller must seed the session from its captured completion
sequence; this software contract does not qualify a physical JTAG adapter.
`make ddr-frame-transport-controls` runs fifteen callback controls
under normal and optimized Python and is included in default `make test`.
These checks cover raw bytes, reset/retention, result ownership, release,
deadlines and failure poisoning; they do not qualify PCIe IP, CDC or hardware.

The base full-DDR framework exposes four exact namespaces. The C3 PPU increment
adds the opt-in fifth bank shown below; it is not required for the existing EW,
CMAC, layout or reset profile.

| Bank | Offset | Identity | Purpose |
|---|---:|---:|---|
| RKAD | `0x000` | `0x524b4144` | HALF EW raw jobs |
| RKCD | `0x100` | `0x524b4344` | FP16 C32/K16 raw CMAC jobs |
| RKPP | `0x300` | `0x524b5050` | Capture-bounded C3 raw PPU jobs; optional (`ENABLE_PPU=0` by default) |
| RKLY | `0x400` | `0x524b4c59` | Static raw-halfword layouts |
| RKRS | `0x500` | `0x524b5253` | Quiescent compute reset |

All banks use ABI 1.0; RKRS additionally requires capability `0x00010004`.
The existing qualified TinyStories/capacity images do not provide this complete
interface. Their prior results do not qualify this profile or a changed image.
The ordinary `tools.backend.runtime.install()` entry remains the EW profile.

The original pinned renderer, 45-QWORD CMAC emitter, `_submit_bodies` and
`_submit` remain the execution path. The CMAC descriptor retains amount 45,
enable mask `0x0d`, and the original four-QWORD tail. The runtime compares
the actual materialized words to the original encoder before submission.
It reads every complete owned BO before successful job ACK.

CMAC images admit FP16 output without activation and static, complete,
unit-stride, zero-fill halfword gathers. Compiler indices become command
metadata for the [raw layout DMA](LAYOUT_DMA.md). The FPGA reads and writes
the operand bytes. Runtime index buffers, partial gathers, literal gathers
inside CMAC images, mixed CMAC/EW images, FP32 CMAC output, activations and
integer precision remain explicit failures. EW-only images retain their
existing HALF/literal-initializer contract. Logical and physical allocation
bounds, disjoint CMAC operands/output, and layout span checks apply.

The constructor and original standalone writer reset calls use the real RKRS
protocol. Reset requires all three job banks idle and unstaged, verifies an
exact epoch increment and held successful result, ACKs that result, then waits
for fresh readiness. One absolute deadline covers each transport reset. No BO
upload/download occurs during reset: the original writer may already have
placed its next commands in its CPU shadow. Only successful reset marks the
compute context clean. A partial transaction failure poisons the owner.

`make backend-full-controls` runs ten byte-only runtime methods and twenty
transport/reset methods. Runtime tests reconstruct the captured metadata from
`tests/backend_layout/fixtures.json` using original pinned backend types; no
private capture binary is required. The twenty transport methods also run
inside `make test`. The runtime methods require the pinned tinygrad checkout;
an unavailable checkout is reported explicitly.

The preparation candidate passes six actual Tensor/compiler/final-writer
native trials with [independent wire and complete-BO replay](../build/framework-full-runtime-coverage-v1/root-result-review.json):
24 jobs, 18 hardware layouts, six CMAC submissions, 18 compute resets,
328,587 raw commands and 2,375,680 BO bytes before ACK. CPU gather calls and
creation of CPU workload programs are blocked. Five pinned CPU queue-control
helpers initialize explicitly before each workload. These trials use actual
full512 numerical RTL with independent AXI RAM/minimal ECC-control models.
The [fresh public-entry replay](../build/framework-public-runtime-coverage-v1/root-result-review.json)
passes the same six shapes and whole-BO totals from its then-current public
68-source selection. It also verifies no host tensor/scratch BO reloads after
launch. That historical replay does not cover the C3 increment. The current
framework and framework-factored manifests each bind 83 sources. They preserve
the 68 baseline source slots/order, select a PPU-enabled dispatch replacement
at the original dispatch slot, and append separate C3, valid-C8, padded-C8,
minimum-C8, average-C8, indexed-C8 and source-emitted global-MAX profile gates
and pooling leaves plus their shared raw DMA. The global-MAX command is
source-emitted, not device-captured.
Their hash/order checks pass, and focused Icarus/Verilator tests cover the
factored owned dispatch and RKPP lifecycle. The previously recorded Verilator
lint/elaboration was for the 81-source snapshot before the global-MAX increment
and is stale for the current 83-source RTL; it is not evidence for the current
top. The current 83-source parent has not received full-top synthesis, implementation or
FPGA/RK qualification. Protocol mocks do not establish those gates.

The earlier 75-source hierarchy's lint result predates minimum, average and
indexed pooling and is stale for the current source. Historical lint results
are lint/elaboration only, not synthesis, placement/routing, timing closure or
hardware evidence.

The original 68-source parent used fifty reused paths and eighteen variants in
the framework directory. The current 83-source C3/C8/padded-C8/minimum/average/indexed/global-MAX candidate is published
through `rtl/ddr/framework/sources.json`; it retains the 68 baseline source
slots/order, substitutes the PPU-enabled dispatch at its original slot and
appends the fifteen PPU engine sources. `tools.ddr.framework_profile.source_paths()`
checks every selected hash and rejects duplicate or escaping paths before a
compiler runs. Variants retain their original module names: compile the
explicit ordered manifest, not a recursive glob containing both variants.
Five source-selection controls run inside `make test`.
