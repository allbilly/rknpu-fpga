# Staged CMAC raw profile decoder

**Current location:** the unchanged candidate has been promoted to
`rtl/rk_cmac_profile.sv` and connected in the separate
[raw product path](CMAC_PRODUCT_PATH.md). Fresh combined verification is
running. The staged results and paths below describe their archived snapshot,
not validation of the new integration. The EW host/board path is unchanged.

This is an **unconnected development leaf**, currently under
`build/rk_cmac_profile.sv`. It does not modify the production EW decoder, DMA,
host endpoint or board top. No GEMM command is newly executable. Numerical
CMAC/CACC, memory requests, CBUF behavior, hardware runtime gathers and job
completion are not implemented by this leaf.

## Boundary and evidence

The leaf consumes actual 64-bit register words and emits a backpressured
internal physical-layout configuration. It never consumes tensor operations
or logical matmul plans. Interface facts come from the pinned production
`emit_cmac_stage` and standalone final writer described in
[CMAC_ENCODER_CONTRACT.md](CMAC_ENCODER_CONTRACT.md).

Seven complete 49-QWORD compiler/final-writer artifacts are replayed without
modifying any byte. An additional 137 shape cases use the actual pinned emitter
with synthetic stage specifications; these are explicitly not compiled tensor
or silicon captures. Further mutation cases test the whitelist and consistency
checks. No backend runtime, CPU gather or tensor arithmetic is called.

The initial profile is terminal, FP16 input/output, with ReLU disabled. It
requires every one of the 45 body fields and three terminal markers, followed
by enable `0x0d`. FP32 output, ReLU, EW enable, foreign targets/registers and
nonzero terminal markers fail explicitly. This is not the finite command-DMA
framer: CMAC's descriptor counts 45 body words, while its four tail words are
also mandatory. A missing trigger leaves this raw port pending, not completed.

## Validation and lifecycle

Fixed values are checked on each write. Dynamic fields retain all 32 bits;
their redundant encodings, shape limits, grain size, bank allocation and strides
are checked together at enable. An invalid fixed write is sticky even if a
later write would repair it. Valid duplicate writes are last-write-wins.
Required fields may arrive in different orders; the complete-profile bitmap
prevents stale configuration reuse between tasks.

Physical rows are 1..2047. Input/output channels are multiples of 32, and input
channels are at least output channels, as required by the pinned compiler's
`max(aligned_K, aligned_N)` layout. Input channels are at most 4096 and at most
384 for multi-row stages. Full input and weight capacities remain 327680 and
360448 bytes. This does not implement or shrink the logical CBUF.

The grain validator uses a small constant table instead of a divider. The
independent software oracle uses the encoder's integer ceiling equation;
actual emitted cases exercise all 128 input-channel groups. Since
`ceil(effective_K/32) == physical_input_channels/32` for the pinned layout,
the line stride can be validated without inventing a logical-K register.

All three bases require 16-byte alignment. Full physical BO ends may equal
2^32 but not exceed it, including the output holes. Read-only input/weight
aliasing is allowed; any output overlap is rejected. This is a 32-bit internal
contract, not an expansion of the separate AXI adapter's 31-bit aperture.

Error codes retain existing meanings: E1 unknown field, E2 unsupported fixed
value or enable, E3 missing field, E4 address/range/overlap, E6 inconsistent or
unsupported physical shape. Four-state unknown fixed values, shape, address
and trigger must fail rather than produce a valid configuration.

The configuration remains stable until accepted. Commands are blocked while
it is pending, while the engine is busy/faulted, or after a decoder fault.
Reset cancels pending configuration, partial field collection and sticky faults.
Configuration acceptance is not task completion, and the future engine must
retain ownership until its final acknowledged output write.

## Verification status

The software oracle has produced 1,920 cases: 274 accepted configurations,
1,645 rejections and one unterminated list. Every required field is omitted,
every value bit is individually flipped, and foreign target/offset, duplicate,
shape/capacity, overlap and endpoint cases are included. The raw RTL bench also
checks configuration stalls, busy/error interlocks, reset and sticky faults;
Icarus has four additional unknown-value cases.

Verilator 5.048 and Icarus 13.0 both passed all 1,920 cases, with four additional
unknown-value cases in Icarus. The corrected lint, compilation and simulation
commands have zero warnings. Actual results are recorded in
`build/cmac_profile_candidate/report.json` with source/stimulus fingerprints,
tool versions, commands and logs, and retained in the
[candidate archive](../verification/runs/2026-09-21-cmac-profile-candidate/index.json).
This is RTL simulation, not synthesis or numerical GEMM evidence.
Strict lint initially rejected an implicit integer-to-boolean file
descriptor check in the bench. That failure is retained; the bench now compares
the descriptor explicitly with zero, without suppressing the warning.

The normal source snapshot remains frozen while its native and mapped checks
run. This staged leaf must be reviewed, promoted and included in a fresh
source-bound regression before it can be counted as production source.

The separately tested [operand-front candidate](CMAC_OPERAND_CANDIDATE.md) now
connects this decoder to the address walker and halfword reads. That staged
integration is not connected to production DMA, numerical GEMM or the board.
