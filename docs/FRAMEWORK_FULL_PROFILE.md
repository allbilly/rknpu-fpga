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
hardware. `make ddr-frame-transport-controls` runs twelve callback controls
under normal and optimized Python and is included in default `make test`.
These checks cover raw bytes, reset/retention, result ownership, release,
deadlines and failure poisoning; they do not qualify PCIe IP, CDC or hardware.

The required image exposes four exact namespaces:

| Bank | Offset | Identity | Purpose |
|---|---:|---:|---|
| RKAD | `0x000` | `0x524b4144` | HALF EW raw jobs |
| RKCD | `0x100` | `0x524b4344` | FP16 C32/K16 raw CMAC jobs |
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
now passes the same six shapes and whole-BO totals from a newly compiled public
68-source selection. It also verifies no host tensor/scratch BO reloads after
launch. Actual-controller, implementation, FPGA and RK compatibility remain
separate gates; protocol mocks do not establish them.

The byte-identical 68-source parent is published through
`rtl/ddr/framework/sources.json`. Fifty sources reuse existing paths and eighteen
variants live in that directory. `tools.ddr.framework_profile.source_paths()`
checks every selected hash and rejects duplicate or escaping paths before a
compiler runs. Those variants retain their original module names: compile the
explicit ordered manifest, not a recursive glob containing both variants.
Five source-selection controls run inside `make test`.
