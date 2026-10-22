# Review of the handoff and next implementation gates

## What remains valid

The compiler should keep emitting RK register/task images. A functional model should decode those bytes, use simulated device addresses, and expose incorrect encodings or memory layouts. RTL verification should use the same stimulus and compare output bytes. FPGA throughput may differ from Rockchip silicon; matching undocumented pipeline latency is not the goal.

The user reports that their ~1500-line tinygrad backend passes hardware test_ops and that the required reverse engineering is already available. Treat that work as the starting point. Do not spend the next iteration rewriting the backend or inventing a second high-level compiler.

## What needed correction

**soDLA FP16 is not established by choosing a precision field.** The inspected `soDLA_beta/src/main/scala/nvdla/cmac/NV_NVDLA_CMAC_CORE_mac.scala` computes signed-integer products and reduces them. That leaf is not an FP16 multiplier. This source finding invalidates the earlier blanket assumption that an RK register adapter over soDLA immediately gives a usable FP16 GEMM path. It does not establish what every uninspected soDLA module or branch supports. Inspect actual chosen leaves and generated RTL before reuse.

**Preserve observable capacity/layout, not just register names.** Reducing physical lanes can be implemented by time-multiplexing. Reducing software-visible CBUF capacity or changing channel/weight atom packing cannot silently be done while promising unmodified existing commands. Preserve the logical contract, virtualize it with correct behavior, explicitly reject an unsupported profile, or deliberately add a compiler capability target. The demo's 4 KiB RAM is backing device memory for a tiny EW workload, not an implementation of RK CBUF.

**A common register list is not the whole runtime ABI.** A PCIe FPGA still needs allocation/address translation, command delivery, completion, reset, error and ordering contracts. It is not automatically a /dev/dri/card1 rknpu device. No DRM or PCIe driver has been added here.

**Simulation consensus is not automatic bug attribution.** If Python and RTL agree but RK differs, they may share an erroneous specification. Even if RK and Python agree, a difference can be in the RTL testbench or transport. Keep raw register bytes, input/output images, seeds and hardware provenance before deciding where a defect lives.

**RTL cycle accuracy has a target.** Simulating this RTL describes the timing of this new implementation, not the unreleased RK3588 implementation. This package is not a NaviSim-style calibrated Rockchip timing model.

## What this delivery chose to implement

Use SystemVerilog for a small direct DPU/RDMA FP16 EW path, avoiding a pretend soDLA integration. It has real register decoding, explicit mode rejection, actual integer-built FP16 arithmetic, a memory controller and concrete tests. No imported soDLA RTL/Chisel source is bundled. Somnia/soDLA remain references and potential later leaf-module donors.

The first vertical path changed from GEMM to EW because the inspected EW register sequence gives a closed, reviewable command/memory contract, while the proposed soDLA CMAC does not supply verified FP16 arithmetic. This is an implementation decision, not a claim that GEMM reverse engineering is unavailable in the user's repositories.

## Work packages, in acceptance order

### Current user-directed implementation assumptions

The user has directed continued development with NVIDIA's FP16 hardware as the
numerical donor and the `rockchip-2608-1500` backend's existing special-case
decompositions. Treat the corresponding NVDLA datapaths as the **working
baseline**, not generic IEEE arithmetic imposed across all NPU units. The donor
conversion mismatch is not a demonstrated NVIDIA defect. Map each selected
path and register mode before reuse; do not infer that every EW operation has
the output converter's saturation behavior. RK bit-exact exceptional-value
compatibility remains a candidate claim until differential evidence exists;
its absence does not prevent donor-based implementation work. Existing tests
are not silently changed, and compile-time decompositions still reach the FPGA
through final raw command words, without runtime CPU fixups.

On 2026-10-23 the user selected Vivado, using OpenTPU's setup as the reference,
and retired openXC7 placement/routing from this continuation. Preserve the
historical openXC7 sources, reports and failed attempts; do not restart that
toolchain or use its results as physical signoff. OpenTPU's abandoned build
work is also not resumed. The current authorization is documentation, review,
fixes and preparation only: do not start a Vivado synthesis/implementation
build or program the FPGA/flash.

Retain the full C32/K16 DSP-prefix candidate with 512 parallel CMAC products;
the smaller EW top remains a separate regression target. The existing
`python3 tools/cmac/vivado_dsp_prefix_array.py prepare` action validates its
source profile and generated ROM and writes source/Tcl snapshots without
validating numerical parents or launching Vivado. It must retain all source,
numerical, electrical, timing, fit and DRC gates. Its `synth` and `run` actions require a later user
instruction to build.

The recorded 2026-10-09 full Vivado 2026.1 version probe passed, while the
separate synthesis-only attempt exited 42 before synthesis because no valid
license was found. That is historical evidence. Read-only inspection on
2026-10-23 found the settings script, launcher and a local license file, but
did not test current license checkout. Follow OpenTPU's normal shell setup
with `VIVADO_ROOT="$HOME/vivado/2026.1/Vivado"` and
`source "$VIVADO_ROOT/settings64.sh"`; see [FPGA.md](FPGA.md). No fresh synthesis,
implementation, timing, electrical, DRC or hardware result is implied.

### A. Establish executable RTL evidence

Run `make rtl-test`; fix HDL compile issues and warnings, then every failing arithmetic/protocol case. Archive the Verilator version, build logs, vector seeds and test results. Add directed four-state checks with a second simulator where practical. Verify the BRAM demo's reset/restart behavior. Do not change failure checks to manufacture a pass.

Acceptance: all generated ALU vectors, all engine scenarios and the BRAM demo pass real HDL simulation. **Passed on the Fedora continuation source snapshot `6f9a9681713f`:** 12,963 ALU vectors and 77 engine scenarios with Verilator and Icarus, plus RAM protocol, readback fault and board reset tests. The original 38 scenarios are retained with their error expectations unchanged. The original delivery did not pass this gate; consult `verification/README.md` for the current source-bound result.

### B. Bind the subset to a real backend trace

Pin the current backend and RK reference repository commits. Capture one emitted terminal FP16 ADD, SUB and MUL command stream plus exact initialized BO bytes and raw hardware outputs. Replay without semantic rewriting through the Python decoder and RTL harness. If the backend uses extra valid registers or a different mode, add that precisely evidenced profile rather than deleting the decoder's checks.

Exercise signed zeros, subnormals, overflow, NaN/infinity, tail groups, alignment, aliasing and task boundaries. Record hardware reset state and any tolerance; do not imply byte-exact arithmetic from a loose allclose result.

Acceptance: supported captured streams replay successfully with appropriately justified numerical comparisons. This will not by itself pass the entire backend suite.

Historical partial evidence: nine final streams from the earlier candidate backend's own EW encoder and PC-tail writer passed RTL with synthetic buffers (ADD/SUB/MUL, logical lengths 8/9/33). This is not an RK3588 output capture and does not close gate B.

The user has now supplied `/home/fedora/tinygrad` at
`078eee94d8f1912bb63ce786c250d2c24984844a` as the current source. Production
compilation/final-writer captures are saved by `tools/capture_current_backend.py`.
This source emits 13 additional initialized FP16 fields, now explicitly modeled
and checked in the decoder/RTL. The separate `rk_ew_dma` top now fetches unchanged
command BOs and follows their linked PC tasks; the raw-word port still refuses
nonzero PC metadata. Nine portable production captures and 53 synthetic DMA
cases exercise this boundary. See `docs/PC_DMA.md` and fresh source-bound reports.
RK hardware observations are still needed; this does not close gate B.

### C. Put the EW slice on YPCB

Use the existing known-good clock/reset/LED board work to check `fpga/ypcb.xdc`. Run synthesis/implementation with the correct installed part support. Confirm inferred BRAM rather than a large flop RAM, resource use, setup/hold timing and configuration-bank settings. Use SRAM/JTAG programming initially rather than rewriting boot flash.

The current board demo initializes and checks 336 halfwords in a bounded BRAM aperture and executes the unchanged production SUB(9) DMA chain, including intermediate scratch and padded lanes. The original three-terminal-operation raw-port demo remains a separate regression bench. See `docs/DMA_BOARD_DEMO.md`. Add ILA probes for state, start-valid/ready, memory handshakes and error code during board debug.

Acceptance: the actual board self-test passes after reset and repeated reconfiguration. No measured Fmax, area or board success is currently available.

The Fedora continuation's DMA-based board top **passes** XC7 primitive mapping, a block-RAM inference assertion and functional mapped-netlist self-test/reset simulation using Xilinx's models. The current mapped board top contains two RAMB36E1 blocks (ROM and working RAM) and one DSP48E1; these are synthesis counts, not placed utilization. No routed delays/SDF are included. It is a prerequisite check, not this package's physical board acceptance. Local board pin/clock/part references are now commit-pinned. A reviewed implementation/signoff flow (the existing Vivado flow or a sufficiently verified open-source route) and verified configuration-bank settings are still needed before producing a reviewed bitstream.

The build-control follow-up fixes electrical-property ordering: supplied CONFIG_VOLTAGE/CFGBVS settings are now validated before synthesis and applied before checkpoints, implementation and DRC. It also requires BRAM inference and rejects missing/nonfinite/negative timing results or blocking/unknown DRC severity. Ten control-flow test methods pass under Tcl 9.0.3 and the installed Xilinx Tcl 8.6.13, with all Vivado operations mocked. No physical constraint is relaxed; these tests do not close gate C or replace a full Vivado run.

### D. Add the FP16 GEMM path, not an integer stand-in

Current increment: the previously staged profile, reader/operand front and
exact-product leaf are promoted into `rtl/` and joined by
`rk_cmac_product_front`. Portable captured commands and independent physical
BO/product oracles feed three extra benches through `make test`. The fresh
regression passes: 247 original entries and all three new benches per simulator.
See [CMAC_PRODUCT_PATH.md](CMAC_PRODUCT_PATH.md).
This connects raw commands through reads and products, not accumulation,
output writes, runtime gathers or the EW DMA/host/board path. Earlier staged
results discussed below remain evidence for their own snapshots only.

The corrected integration-only Icarus bench now passes 53,247 products/tags;
fresh complete-path XC7 mapping and full native regression also pass. This
does not close the numerical GEMM or physical gates. An additional
[donor conversion audit](NVDLA_CONVERSION_AUDIT.md)
confirms that the NVIDIA FP32-to-FP16 RTL saturates overflow/infinity and can
truncate a NaN payload to zero. Do not silently inherit that behavior or assume
the donor settles RK's product, accumulation or output-conversion policies.

Derive a *single supported* CNA/CORE/DPU 1x1-convolution/GEMM profile from the already-working examples/current backend. Preserve source and weight packing, counts, strides, logical CBUF allocation, CSC traversal, product/accumulator behavior, and output placement. Reuse the user's existing CSC model where it provides verified behavior; do not ignore existing simulation work.

Suggested components are `rk_cna_profile`, `rk_cbuf`, `rk_csc`, `rk_cmac_fp16`, `rk_cacc`, and DPU output conversion. These names describe the next work; no stub versions are supplied or counted as implemented. Decide leaf interfaces only after the actual source audit. Each stream should carry explicit valid, ready, data, lane/coordinate tags and end-of-reduction information. Retiming must preserve those tags.

Parameterize physical lane count while retaining logical channel groups and CBUF semantics. Start with one output accumulator and a serialized correct inner product if that reduces implementation risk. Do not round every multiplication to FP16 before accumulating unless that is what the observed RK numerical contract requires. Likewise, do not reorder reductions merely because mathematical addition is associative.

Audit soDLA's selected CBUF/CSC/CMAC/CACC/DMA modules independently. Integer control/storage components may be reusable after layout and interface checks. An FP16 datapath must be supplied explicitly. Keep upstream licensing and provenance if code is imported later.

The local `/home/fedora/hw` nvdlav1 checkout at
`8e06b1b9d85aab65b40d43d08eec5ea4681ff715` does supply FP16 CMAC RTL and
`NV_NVDLA_CACC_CALC_fp_48b.v`, with C-model product/alignment/accumulation references.
These are substantially stronger arithmetic inputs than the selected soDLA
integer MAC, but do not establish bit-exact equivalence to RK3588. Additional
YPCB XDMA and MIG project sources are under `/home/fedora/ypcb/ref/`; they are
candidate transport/DDR references, not an audited integrated FPGA shell.

The user also supplied `/home/fedora/vortex` at
`5ce5a1a915b06c42c60393a7ea24168e0e01078f`. Its tensor-core TFR path has an
FP16 11-by-11 mantissa multiplier with optional DSP inference and pipelined
alignment/accumulation. The TFR output is FP32 and its normalization flushes
exponent underflow; the alternative FPnew path uses FP16-to-FP32 multiplication
and an FP32 adder tree. These are useful implementation candidates, not evidence
of RK-compatible reduction/rounding. The selected scalar FPU is not the FP16
donor. See `docs/LOCAL_REFERENCES.md` for paths, hashes and dependency caveats.
No Vortex RTL was imported or simulated during this source audit.

The current compiler/final-writer audit now retains seven actual CMAC command
cases, including K=65, without executing gathers or tensor arithmetic. It
establishes a distinct 45-body-word/4-tail-word CMAC framing and exposes the
compiler's runtime input/output layout steps. See
[CMAC_ENCODER_CONTRACT.md](CMAC_ENCODER_CONTRACT.md). These are not hardware
captures or implemented GEMM support; host layout steps must not enter the
FPGA runtime as CPU fixups.

The `rk_cmac_address` leaf supplies packed address/tag sequencing and has
standalone and combined two-simulator evidence. It is now connected inside
the separate raw-product path, but not the EW host endpoint. It does not
supply CBUF, accumulation or hardware gather execution. See
[CMAC_ADDRESS_CANDIDATE.md](CMAC_ADDRESS_CANDIDATE.md). This does not close D.

The original staged raw CMAC profile decoder validates the 45-word FP16
body and distinct terminal tail. Its independent contract and RTL benches pass
1,920 cases per simulator, including seven unchanged compiler captures; Icarus
also passes four unknown-value rejections. That candidate is now promoted
unchanged into the separate raw-product path. See
[CMAC_PROFILE_CANDIDATE.md](CMAC_PROFILE_CANDIDATE.md). This neither integrates
CMAC DMA framing nor accepts GEMM in the production execution path.

A staged operand reader now connects that decoder to the address sequencer and
read-only halfword memory traffic. It carries the raw input/weight data and all
coordinate/reduction tags through response delays and consumer backpressure.
Its integration tests pass separately in both simulators, with 53,297 checked
operand pairs each; XC7 primitive mapping also passes. See
[CMAC_OPERAND_CANDIDATE.md](CMAC_OPERAND_CANDIDATE.md). Operand-stream completion
is not arithmetic completion or the final output-write acknowledgment.

A separate three-stage elastic FP16-product leaf preserves finite products
exactly in FP32 encoding, carrying the full 131-bit operand tag. Both simulators
pass 230,433 comparisons including stalls and reset cancellation; XC7 mapping
uses one DSP48E1. See [FP16_PRODUCT_CANDIDATE.md](FP16_PRODUCT_CANDIDATE.md).
It is now connected to the separate operand path, but does not choose accumulation
precision, reduction order or RK special-value behavior. In particular, its
FP32 output is not the NVIDIA donor's grouped 44-bit CMAC/CACC interface.

A separate [staged result writer](CMAC_WRITER_CANDIDATE.md) passes both native
simulators and XC7 mapping under `build/`. It accepts converted halfwords and completes only
after the final successful write response. It is not in the raw-command path; do not
treat its synthetic layout tests as numerical GEMM or RK capture evidence.

A [staged FP32-to-FP16 output converter](FP32_TO_FP16_CANDIDATE.md) now passes
330,793 comparisons in each native simulator and XC7 mapping. It is intended
only after accumulation, not between products and the accumulator. Its RNE
and exceptional-value contract remains a candidate; the RK TRM's generic
rounding description does not supply the missing numerical hardware evidence.
The converter and writer are now joined in a separate
[staged output tail](CMAC_OUTPUT_CANDIDATE.md), not to an accumulator or the
raw-command frontend. Final-source Verilator, four-state simulation and XC7
mapping pass. The wrapper retains stream
ownership through input gaps and final write acknowledgment, closes on the
last accepted result, and propagates sticky upstream cancellation.

Following the user's donor-baseline direction, a separate
[NVDLA converter adapter](NVDLA_CONVERTER_ADAPTER.md) now wraps the unmodified
NVIDIA output converter with raw tags and single-inflight flow control.
Verilator and the full four-state numerical run each pass 330,799 comparisons
with reset/backpressure checks, and XC7 mapping passes. The four-state runner
remains failed because its subsequent zero-tag-width parameter compilation
crashes Icarus; that rejection test is not counted as passed. A distinct
[donor-based output tail](CMAC_OUTPUT_NVDLA.md) now joins it to the unchanged
writer, with passing four-state integration, Verilator integration and XC7
mapping. It is not integrated with accumulation.
Earlier RNE/infinity/
canonical-NaN candidate tests and archives remain unchanged and are not
relabeled as donor-baseline evidence.

A [stateful NVDLA CACC candidate](CACC_REDUCTION_CANDIDATE.md) now accepts
ordered FP44 groups, retains the donor FP48 partial sum and buffers final FP32
results with raw tags. Direct donor tests compare 9,144 partial/final pairs
against an independent dyadic oracle. The reduction tests cover 2,712 groups,
faults, gaps, cancellation and resets. A synthesis-only constant-reject bug
in the wrapper's X checks was caught by inspecting the mapped netlist; that
initial structural pass is not accepted as working arithmetic. The fix retains
four-state rejection tests and adds nonconstant-control/arithmetic-presence
gates. Fresh native tests pass in both simulators; mapped-netlist verification
now also passes after a documented vendor-model startup harness correction.
Group formation from
actual FP16 operands, raw-command integration and final memory completion are
still required. Do not feed IEEE FP32 product bits into the FP44 interface.

A [staged serialized 64-pair FP16 group former](CMAC_GROUP_CANDIDATE.md) now
reuses the unmodified NVIDIA Booth multiplier and carry-save tree. Tests use
the executed integer Booth helper from the NVIDIA C-model header, not the
full SystemC model. Verilator and XC7 mapping pass; four-state testing remains
in progress. No numerical
GEMM or new raw-command acceptance is claimed. Its 64-pair donor grouping is
distinct from the RK backend's 32-channel storage atom and remains a working
assumption until the actual grouping is established.

A new [staged raw numerical core](CMAC_NVDLA_CORE_CANDIDATE.md) now joins the
unchanged terminal profile/reader to these donor leaves and acknowledged
output writes. Its full Verilator suite passes all 16 entries, including eight
fixture replays with 90,112 read transactions, 1,216 group values/tags and
1,088 acknowledged output halfwords. Whole-core XC7 primitive mapping now
passes; all 19 full four-state entries now pass as well. Functional netlist
replay remains running.
This is not a promoted host/board or full tinygrad
implementation. No runtime CPU gathers or arithmetic fixups were added.

A separate [staged CMAC DMA wrapper](CMAC_NVDLA_DMA_CANDIDATE.md) now consumes
the actual standalone descriptor's 45-word body count, fetches all 49 final
QWORDs unchanged and feeds the numerical core. It keeps CMAC framing distinct
from EW chaining. All 23 Verilator entries pass, including eight numerical
fixtures, two reset phases and repeated jobs. Icarus regression is running;
initial descriptor, framing, fetch and operand fault tests pass. No complete
four-state pass is claimed yet. DMA-wrapper XC7 mapping now passes; it is not
in the production host/board top.

A separate [staged CMAC AXI endpoint](CMAC_NVDLA_AXI_CANDIDATE.md) now joins
that DMA path to AXI-Lite job control and a 512-bit AXI RAM adapter. Its RKCM
identity makes the body-count convention explicit. Initial lint exposed
mixed reset styles; the corrected staged control/adapter use joint
asynchronous reset assertion. All 19 public-port Verilator numerical/fault/
reset entries now pass, and all ten successful saved memory images equal
their expected images. Four-state verification is running; no mapped endpoint,
PCIe/DDR, board or RK equivalence result is claimed yet.

A separate [staged CMAC BRAM board demo](CMAC_BRAM_BOARD_CANDIDATE.md) now
implements autonomous K=65 command-DMA replay and complete 8 KiB RAM checking.
Its eight-entry Verilator wrapper/reset/fault regression passes; four-state
testing and XC7 mapping are running. It keeps physical command
and operand addresses unchanged and does not add runtime CPU packing. The
production top remains the earlier EW demo; neither top is board-validated.

Acceptance: real small GEMM traces match RK at shape and packing boundaries, including K around atom boundaries (for example 7/8/9 and 31/32/33, plus the user's K=65 regression where applicable). Extend to full backend coverage incrementally, with an explicit supported-profile manifest.

### E. Host transport and full CI

Introduce a host transport independently from arithmetic: DMA/PIO command queue, 32/64-bit address policy, completion/interrupt records, timeouts and reset. Reuse a proven YPCB PCIe shell only with a verified lane/pin/clock/reset map. Add the FPGA transport underneath the existing final register encoder; don't bypass it by passing a tensor op directly to the FPGA.

The first memory-side component is now `rk_axi_mem`: a serial 16-bit-to-512-bit
AXI adapter matching the inspected local MIG-side widths, with aligned full-beat
reads, masked writes and B-channel completion. It does not integrate MIG, CDC,
PCIe or a host-visible queue. The nine production EW BO fixtures are additional
AXI behavioral-slave test targets; see [AXI_MEMORY.md](AXI_MEMORY.md) for contracts
and the source-bound verification reports for actual results.

The intended CI path is `test_ops -> existing compiler -> final regcmd/BOs -> simulator or RTL`. The current repository is not yet installed as a tinygrad runtime and makes no claim to that coverage. Longer-term driver emulation can wrap the model in the user's macOS VP; a VP is not required for the standalone emulator or RTL testbench.

## Deferred deliberately

The internal `rk_ew_axi` endpoint now joins AXI-Lite job control to raw-command
DMA and the AXI memory adapter. This advances package E without bypassing the
backend's final encoder. Its versioned descriptor/result contract and explicit
failures are in [HOST_CONTROL.md](HOST_CONTROL.md); fresh source-bound regression
and focused XC7 mapping pass at `f927a501cec9`, including mapped-control
simulation. All twenty whole-endpoint functional mapped replays now pass at
that source, and all eleven output images equal native RTL. The corrected
external reset-startup harness retains default GSR and all error assertions;
the prior sixteen-pass/four-failure attempt remains archived.
It is not a PCIe/MIG shell: the inspected
XDMA reference has its AXI-Lite master disabled, and CDC, calibration/ECC recovery,
host coherence and interrupt delivery still need integration. The board top and
electrical constraints are unchanged. Full NPU/GEMM and physical gates remain.

Three-core scheduling, overlapping ping-pong register groups, general convolution, LUT/activation and conversion modes, PPU, quantized/integer paths, calibrated timing modeling, host driver emulation and a full SystemC model are not counted as completed by this delivery. The implemented PC fetcher is serial EW-only, not a general RKNPU scheduler. Add broader modes when demanded by concrete backend streams, with tests before broad compatibility claims.
