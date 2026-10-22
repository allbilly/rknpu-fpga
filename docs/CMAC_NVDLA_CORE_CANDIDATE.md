# Staged raw-command NVDLA numerical core

`build/rk_cmac_nvdla_core.sv` connects the existing strict terminal CMAC
decoder and operand reader to the donor-based numerical pipeline and result
writer. It consumes the existing final register words, not tensor operations.
This candidate is separate from the production EW DMA/AXI endpoint and board
top. It is not yet a complete tinygrad device or an RK-compatible full NPU.

```text
49 unchanged QWORDs → packed halfword reads → 64-pair group → FP44 CACC
                                                           ↓
                           final write acknowledgment ← FP16 ← FP32
```

The numerical chain is `build/rk_nvdla_cmac_pipe.sv`: the serialized
[group former](CMAC_GROUP_CANDIDATE.md), [CACC](CACC_REDUCTION_CANDIDATE.md)
and [NVDLA conversion/write tail](CMAC_OUTPUT_NVDLA.md). The earlier
IEEE-style FP32 product leaf is not used in this path.

## Boundary and numerical contract

The accepted command fields are unchanged from
[CMAC_PROFILE_CANDIDATE.md](CMAC_PROFILE_CANDIDATE.md): complete 45-word body,
three markers and terminal enable `0x0d`, FP16 input/output, no ReLU. Unknown,
unsupported, incomplete, inconsistent and invalid-range profiles remain
explicit faults. There is no implicit CPU arithmetic or layout repair.

Reads traverse physical `rows × ai` input and packed `ao × ai` weight BOs,
with the existing IC32/OC16 panel layout. All physical input channels are
read. The group collector gathers consecutive channel pairs for one output,
checks channel/first/address/row/output-channel metadata continuity, and
submits groups of 64 to the NVDLA arithmetic path. A short last group is
zero-filled in RTL; no extra memory reads or host padding operation is added.
The 64-channel **numerical grouping is a donor-based working assumption**,
not proven merely by RK's 32-channel storage atom.

The group former retains NVIDIA's separately aligned Booth carry-save rows,
sign compensation and group NaN priority. CACC preserves group order and
its donor FP48 feedback format. Final FP32 results are converted once with
NVIDIA's finite RNE/underflow, saturation and NaN-payload behavior. Neither
individual products nor partial sums are rounded to FP16. These are not yet
Rockchip differential observations.

Output addresses remain byte addresses from the existing walker:
`base + row*ao*4 + (oc/16)*64 + (oc%16)*2`. Only those halfwords are written;
the holes between OC16 panels are preserved. Compiler-generated runtime
gathers outside this raw CMAC stage are still unimplemented. Synthetic
physical BO fixtures are verification inputs, not a runtime fallback that
repacks user tensors on the CPU.

## Ownership, memory and faults

The collector retains one frame and the group former retains another. The
numerical chain uses backpressure between stages. CACC serializes dependent
groups; only its final result enters conversion. Raw tags carry destination,
first/last group and final-output status without arithmetic on the tags.

One shared halfword memory transaction is outstanding. The arbiter chooses
between reads and writes, locks a request while backpressured, and retains
response ownership until the corresponding response handshake. It cannot
switch a stalled read to a newly available write. Requests and responses
retain the existing timeout/error contracts; this is not an AXI/DDR bridge.

`address_done` and `operand_done` expose the original intermediate progress
pulses. Neither completes the job. `done` and `acknowledged` come from
successful write responses; `done` requires the final output's response.
Command ownership persists through collection, arithmetic, conversion and
the final acknowledgment, including gaps and stalls.

Aggregate errors immediately suppress every external handshake. A root
register preserves the first error code and distributes cancellation to the
numerical leaves without a combinational error/cancel loop. E1/E2/E3/E4/E6
remain profile/metadata errors and E5/E8 remain memory error/timeout. Joint
reset of the core and memory transport is required after a fault; acknowledged
or partially performed writes are not rolled back. No board programming is
part of this candidate.

## Verification status

`build/gen_cmac_nvdla_core_vectors.py` preserves all seven captured compiler
command streams byte-for-byte. It generates seven finite physical-BO cases
and an additional mixed-special-value K=65 case: 45,056 input/weight pairs,
1,216 FP44 groups and 1,088 output halfwords. The expected path uses the
executed, unmodified NVIDIA integer Booth helper, the independent exact-dyadic
CACC oracle, and Python `struct` finite conversion plus the audited donor
exception rules. It does not execute the full SystemC model or an RK board.
Generation seed: `0x3588ca15`; RTL protocol seed: `0x3588ca16`.

The **Verilator 5.048 K=65 smoke replay passes** at encoded rows=2, ai=96,
ao=32: 12,288 reads, 128 group comparisons, 64 numerical/address-checked
writes and 64 successful acknowledgments, in 83,084 simulation cycles.
Every read's packing/order, group tag/value, output hole, request stability
and final-ack completion is checked. This is not a hardware cycle measurement.

The **full Verilator suite passes all 16 entries**: the eight fixture replays
above plus read/write errors, request/response timeouts, unknown target,
incomplete trigger, reset during arithmetic and repeat submission without
reset. The eight fixture replays alone check 90,112 read transactions,
1,216 group values/tags and 1,088 acknowledged numerical outputs. Extra reset
and repeat cases complete three more jobs; fault cases remain separate.

The first Icarus
integration compile succeeded with no warnings, but the runner incorrectly
required an inherited warning and stopped before simulation. That failed
acceptance record is retained; it is not a DUT failure or a four-state pass.
`build/run_cmac_nvdla_core_iverilog.py` corrects only that runner check: the
explicitly timed compatibility helpers make this compile warning-free.
Its source-bound full four-state suite now passes all 19 entries, adding
unknown read data and read/write status checks. The original Verilator
runner/source snapshot remains unchanged. The
[two-simulator archive](../verification/runs/2026-09-21-cmac-core-native/index.json)
preserves both completed suites and their exact sources and stimuli. These
are native RTL results, not mapped-netlist or board evidence.

Initial mapping stopped before synthesis because `proc` left unused dynamic
part-select temporaries that `check` reported as undriven. A diagnostic using
normal `opt_clean` after `proc` reports zero problems. The fresh `yosys_v2`
mapping uses that cleanup, retains both strict checks and all arithmetic/state
presence gates, and **passes with Yosys 0.65**: 6,548 flip-flops, 10,574
LUT1..6, 346 CARRY4 and three DSP48E1 primitives. These are internal mapping
counts, not placed utilization or timing. No RTL, DRC or timing constraint was weakened;
the first failure and runner are preserved under `yosys/`.

Runners: `build/run_cmac_nvdla_core.py`, the Icarus continuation above, and
`build/run_cmac_nvdla_core_mapping.py`. Reports and per-case logs are under
`build/cmac_nvdla_core_candidate/`. A new
`build/run_cmac_nvdla_core_mapped.py` retains the native read/group/write
scoreboards for functional netlist replay. Its first compile found that
optimization removed the separate group-valid and accumulator-ready names.
The corrected `build/run_cmac_nvdla_core_mapped_seam_fix.py` observes the
retained accumulator `issue` net (`accept && legal`) instead: every issued
group is still compared and any rejected group still fails the core-error
check. It also explicitly selects typical vendor specify values with
`-Ttyp`, rather than leaving min/typ/max selection implicit. Both harness
attempts are retained; no DUT or primitive source was changed.
The corrected smoke run terminated as a failure: its mode-9 replay reached
the 7,200-second wall-time timeout. It uses unmodified vendor primitives,
default GSR, and the mapped
default timeout (65,536), excludes native-only X injection, and triggers
reset from observed bus progress rather than an optimized FSM encoding.
The terminal report is
`build/cmac_nvdla_core_candidate/mapped_smoke_seam_fix/report.json`.
Earlier completed modes do not turn that timeout into a suite pass. This is
the prior serialized C64 candidate, not the new parallel C32/K16 array.
No mapped functional pass, physical
timing, FPGA execution or RK numerical equivalence is established here.

A separate [staged standalone CMAC DMA wrapper](CMAC_NVDLA_DMA_CANDIDATE.md)
now fetches final command-buffer words into this core. It is not yet promoted
into the EW host endpoint or board top.
