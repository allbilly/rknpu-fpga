# Shared data preparation for the full512 DDR design

The first combined design exceeded XC7K480T capacity. Its 512 product DSPs
were present, but the original source consumed 306,557 LUTs before normal
optimization. Default optimization and ExploreArea reduced this to 304,389
and 303,585 LUTs respectively; both retained the UTLZ-1 resource error.

| Experiment | LUTs | Product DSPs | Interpretation |
|---|---|---|---|
| Original full design, synthesis | 306,557 | 512 | Over capacity |
| Original full design, default optimization | 304,389 | 512 | Over capacity |
| Original full design, ExploreArea | 303,585 | 512 | Over capacity |
| Original full design, rebuilt hierarchy | 350,552 | 512 | Rejected; larger |
| Isolated original array | 235,309 | 512 | Comparison boundary only |
| Isolated shared-preparation array | 225,584 | 512 | 9,725 fewer LUTs; registers unchanged |
| Shared-preparation full design, synthesis | 295,994 | 512 | Nominal capacity fit; routing unproven |
| Fresh constrained full design, default optimization | 293,826 | 512 | Source/resource checks and independent repaired-route qualification pass |

The full candidate retains both original DDR controllers and all 516 total
DSPs. It uses 290,966 logic LUTs plus 5,028 LUTs for memory/shift registers,
62,126 registers and no BRAM. There are 2,606 nominal LUTs spare. The
[independent resource review](../build/full512-ddr-preparation/combined-shared-data-full-synth-v1/root-resource-review-v1.json)
rehashes all 334 source/tool inputs and native outputs. Its default DRC has
2,066 existing pipelining/buffering warnings, zero resource errors and no
critical-warning events. No DRC severity, clock, pin or voltage requirement
changed. This is synthesis evidence, not placement or timing acceptance.

Fresh source synthesis and constrained default optimization now complete in
1,648.781 seconds. The [independent post-opt source review](../build/full512-ddr-preparation/shared-data-constrained-prep-v4/root-post-opt-review.json)
checks 293,826 LUTs (289,684 logic, 3,568 LUTRAM and 574 SRL), 61,210 registers,
all 512 products/516 total DSPs, both controller blocks and 242 ports. There
are 4,774 nominal LUTs spare. All 35 constant rows and 101 boundary observations
retain their three exact ground anchors through optimization. This still
does not prove packable fit or routed timing.

The [constrained-source archive](../verification/runs/2026-10-28-full512-ddr-constrained-source/index.json)
preserves 360 payloads in 2,912,186 stored bytes. Independent rehash checks all
819 input references, including the exact 160 source copies, their origins,
the synthesis controls and post-opt inventory inputs. The checkpoint itself
is hash-listed, with source and structure evidence kept separate from routing.

## Refactoring contract

The unpromoted candidate moves identical data-side work from sixteen C32
kernels into one combinational preparation block. It computes the original
sign/pre-shifted magnitude, exponent slice, masked nonzero flag and lowest-
channel data-NaN payload once. Each kernel keeps its own weight preparation,
pair exponent maximum, alignment, integer reduction and payload registers.

Weight NaNs still take priority over data NaNs. Data-NaN propagation remains
independent of the corresponding weight mask, as in the original donor-based
cell. Sign/payload choice, subnormal preparation and all original expressions
are preserved. There is no new pipeline stage, rounding boundary, register
field, BO layout or host arithmetic operation. The 512 multipliers remain.

The [candidate source preparation](../build/full512-ddr-preparation/shared-data-candidate-v2/preparation.json)
identifies the two changed cell/array files and the new shared block. It is
separate from the public qualified arithmetic selection until its own
equivalence and integration results are complete.

## Required qualification

The reference-versus-candidate Verilator test passes eight directed groups
and 10,000 deterministic random groups at each C=8/32/64, with capture-low
input churn. Directed cases include zeros, subnormals, finite extremes,
infinities, NaN sign/payload priority and independent masks. Random groups
include 2,500 raw-bit and 7,500 finite-exponent groups per C. These are sampled
equivalence checks against the original RTL, not an exhaustive proof or RK
silicon differential result.

The changed arithmetic also passes all nine original shared-dispatch CMAC
numerical/fault modes in both Icarus and Verilator. The
[independent source/log review](../build/full512-ddr-preparation/shared-data-dispatch-numerical-v1/both-simulators-root-review-v1.json)
checks unchanged raw K65 fixtures, seed and counters, both actual executables,
and the elaborated sixteen C32 kernels/512 product lanes. The passing repeat
mode retains 98 command words, 13,056 operand reads, 128 writes, 13,576
responses and two safe rearms. Its halfword UI memory is a test model;
complete controller-model fault/recovery and physical DDR remain separate.

The original aggregate Icarus run reached its unchanged 300-second cap and
remains failed. The complete input corpus now passes in independent ranges
under the same per-command cap. The
[independent coverage and RNG audit](../build/full512-ddr-preparation/shared-data-candidate-v2/equivalence-v2/fine-shards-v1/root-review.json)
checks all 26 C32/C64 shards, the full C8 run and all three Verilator sizes:
exactly 10,000 random groups per C, with no gaps or overlaps and matching RNG
boundaries. No group-count, error expectation or deadline was reduced. The
initial test generator's mask draw was corrected before qualification; the
earlier source and failed attempt remain preserved.

The original shared-endpoint controller tests in [DDR_FULL512_MODEL.md](DDR_FULL512_MODEL.md)
do not qualify modified arithmetic. A fresh trained controller-model build
with 112 HDL sources now passes its unchanged CMAC/EW/CMAC replay in
2,125.131 seconds. Its [independent execution review](../build/full512-ddr-preparation/shared-data-trained-model-v1/root-execution-review-v1.json)
checks the same trained vectors, all 27,614 modeled PHY returns, 96 writes,
two safe CMAC rearms and 270,336 complete BO bytes before the three ACKs.
The separate [same-executable controller matrix](DDR_FULL512_MODEL.md#shared-data-controller-numerical-fault-and-recovery-matrix)
now passes all 12 CMAC and 21 EW cases; its modeled PHY remains distinct from
physical DDR qualification.

The [read-only mapped inventory](../build/full512-ddr-preparation/shared-data-mapped-facts-v1/dual-cdc-inventory-v4/output/root-review.json)
also passes: EW 64/37 descriptor/result bits, CMAC 64/10 bits, nine status
chains, the CMAC permit chain, both memory crossings and four strict board-reset
banks. CMAC task bits31:1 require explicit single-driver ground proofs at all
three actual boundaries; all eight error-code bits remain dynamic and timed.
This inventory applies no exceptions and does not qualify CDC timing.
The optimized checkpoint also passes its own strict inventories. Its native
query exited zero; the producer's misplaced terminal-marker check remains
failed, with a [separate independent acceptance](../build/full512-ddr-preparation/shared-data-route-postopt-inventory-v1/root-review.json)
bound to all 170 inputs and actual stdout/facts. Placement and routing completed,
but its original setup fails at -0.551 ns. The subsequent native repair passes
setup/hold/pulse at +0.004/+0.048/+0.264 ns and all strict project audits.
Its wrapper provenance failure remains preserved. The fresh qualification
described in the [timing repair](DDR_TIMING_REPAIR.md) now passes independent
review of all 343 inputs and 422,138 fully routed nets. Exact-image and physical
qualification remain necessary.
No candidate bitstream has been emitted or programmed.

The [portable shared-data logical archive](../verification/runs/2026-10-28-shared-data-logical-v2/index.json)
preserves 1,090 selected source/evidence payloads in 7,092,601 stored bytes.
Independent review rehashes every stored, decompressed and original payload
and resolves all 1,726 included input-closure references. The original archive's
449 compressed-path metadata errors remain preserved; v2 copies its payloads
unchanged and corrects the index references. The selected archive contains
completed logical and read-only mapped results; live synthesis and fault-matrix
outputs are explicitly excluded.
