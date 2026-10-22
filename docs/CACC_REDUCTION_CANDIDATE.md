# NVDLA FP44-group reduction candidate

`build/rk_nvdla_cacc.sv` adds ordered accumulation state around the unmodified
NVIDIA `NV_NVDLA_CACC_CALC_fp_48b.v`. It stores the donor's 48-bit partial sum,
feeds that value into the next accepted group, and holds the final FP32 result
and raw tag under output backpressure. This advances the numerical pipeline;
it is not a complete CMAC, GEMM engine or new accepted raw-command profile.

The standalone wrapper now has a staged raw-pipeline integration under test
in `build/rk_cmac_nvdla_core.sv` and `build/rk_nvdla_cmac_pipe.sv`, connecting
the raw operand frontend and [NVDLA output tail](CMAC_OUTPUT_NVDLA.md).
That integration is not yet validated. In particular, the earlier
FP32-encoded individual products must not be connected to its FP44 input by a
bit cast. A [staged group former](CMAC_GROUP_CANDIDATE.md) is now under test;
its integration before this interface remains necessary. The user-directed NVDLA arithmetic baseline
does not prove RK uses the same numerical group size.

## Numerical contract

Donor revision: `8e06b1b9d85aab65b40d43d08eec5ea4681ff715`.
Donor CACC SHA256:
`ef3dbfb8b56f4359f6554af9e3c07e3b47b87423b255c17aaedeeb0dc94b7028`.

Finite input groups contain exponent `e = in_group[43:38]` in 0..62 and a
signed 38-bit mantissa `m = in_group[37:0]`, representing `m * 2**(e-50)`.
The donor requires the highest three mantissa bits to agree, restricting the
admitted mantissa to `-2**35 .. 2**35-1`. Zero is identified by its mantissa.
The internal partial sum is an eight-bit exponent plus normalized signed
40-bit mantissa, representing `m * 2**(e-101)`; it is not IEEE binary48.

Partial-sum quantization and final FP32 conversion follow the donor's
nearest/ties-away behavior, not a generic FP32 RNE adder. The independent
oracle uses exact integer dyadic addition and magnitude rounding; it does not
translate the RTL's aligner/guard/sticky equations. Signed normalization
includes the asymmetric exact negative-power-of-two representation.

Input exponent 63 denotes a NaN. The wrapper requires a nonzero ten-bit
payload in bits 36:27; sign is bit 37. The donor discards lower payload bits,
preserves a prior partial NaN ahead of a later incoming NaN, and emits its
ten payload bits in the low ten FP32 mantissa bits. Zero surviving payload is
an explicit E6 rejection in this admitted interface, not silently accepted as
an infinity. Unknown input/tag/first/last bits are also E6 in four-state tests.
These are a documented donor-based candidate contract, not RK observations.

## Reduction ownership and flow control

Each input is a group value plus `in_first`, `in_last` and an opaque raw tag
(default 33 bits, suitable for address plus final-output flag). The first
group must assert `in_first`; subsequent groups must clear it and keep the
same tag. The final group asserts `in_last`. Missing/repeated first and changed
tags fail E6. Tags are not arithmetic operands or host layout transformations.

Only one donor group is in flight. The next group waits until a partial sum
has been captured for feedback. Final conversion goes into a held output
register; no new reduction is accepted until that output is consumed. `busy`
spans gaps between groups, including an empty arithmetic pipeline. Output
transfer is numerical completion only, not a memory write acknowledgment.
The enclosing output tail must retain job ownership until its final write ack.

`cancel` immediately suppresses handshakes and latches a fault until joint
reset. Codes 1..8 survive; zero, unknown and out-of-range codes become E6.
Reset clears donor valid state, feedback, ownership and the held output, and
dominates cancellation. No runtime CPU fallback is used. `TAG_WIDTH=0` has an
explicit time-zero failure; its dedicated rejection test is still pending.

## Open-source compatibility changes

The original `NV_DW_lsd.v` has an input-dependent loop termination condition;
Yosys rejected it with `2nd expression of procedural for-loop is not constant`.
`build/nvdla_compat/NV_DW_lsd.v` retains its interface and sign-transition rule
but uses a bounded loop that freezes after the first transition. The original
must terminate by index zero; visiting remaining indices without changing the
result preserves that rule. Explicit sizing avoids introducing width warnings.
The used widths are 36 and 44; the compatibility helper rejects unsupported
parameter configurations rather than inventing their behavior.

Icarus comparison against a module-name-only copy of the original passes
10,218 checks at width 36, 10,266 at width 44 and 10,306 at width 8. Coverage
includes every leading-sign count, directed bit boundaries, 10,000 seeded
inputs per width, all eight-bit inputs, and X/Z injections. Seed: `0x3588ca12`.
This is simulation plus a loop-equivalence argument, not a formal proof.

NVIDIA's original procedural assertion helper is retained for Icarus. Its
Z-sensitive reset tests cannot be elaborated by the installed Verilator.
`build/nvdla_compat/nv_assert_never.v` therefore supplies a known-0/1 checker
for that two-state simulator and selects the donor's direct-reset assertion
branch. All five original CACC assertion expressions remain enabled. The
runner rejects every unexpected `ERROR :` line, independent of executable
exit status. A deliberate illegal FP44 input must trigger exactly the first
checker; this prevents an accidentally disabled assertion configuration from
passing. The compatibility checker is not claimed equivalent for X/Z inputs.

## Current evidence

The fresh Icarus arithmetic audit passes **9,144 partial and 9,144 final
comparisons**, including alignment gaps around 38/40/80 bits, cancellation,
rounding ties, NaN priority, masked operands and ordered feedback sequences.
The deliberate assertion probe passes with the original NVIDIA checker.
Seed: `0x3588ca10`. The C-model remains inspected, not executed.

The stateful reduction wrapper passes fresh Icarus with **2,712 groups,
204 completed outputs, nine explicit faults, nine resets, seven cancellations
and 979 held-output cycles**, seed `0x3588ca11`. It checks partial feedback
against the independent oracle, stream tags, held output, an 80-cycle input
gap and fresh work after reset. The 194 generated reductions include lengths
around 7/8/9, 31/32/33 and 65, plus 129 groups; these are synthetic FP44 groups,
not those many FP16 channels or raw GEMM captures.

Both native simulator suites passed the pre-fix source. The initial Yosys
invocation also returned success, but review of its netlist found `legal=0`
and `issue=0`, with the arithmetic removed and only 11 flip-flops left.
That structural pass is **not accepted as a mapped accumulator result**.
The explicit simulation-X comparison caused a synthesis-only constant-reject
path. The fix confines X/Z detection to simulation, retaining all hardware
field/sequence checks. Fresh Icarus passes with the same 2,712-group results
and unchanged fault expectations. Fresh Verilator also passes: 204 outputs,
five known-input faults, nine resets, six cancellations and 979 held cycles.
The corrected synthesis retains 357 flip-flops and 1786 LUTs, unlike the
constant-reject netlist. Its first strengthened runner rejected a missing
`legal` temporary name that Yosys had legitimately merged into a LUT; the
actual `issue`, donor-valid and partial-state boundaries are present and
nonconstant. A fresh run validates those retained boundaries and arithmetic
resource presence. Both earlier failed acceptance records remain unchanged.
A functional netlist attempt failed at its first transaction: a legality LUT
was unknown even though its input data and reset were known. A standalone
unmodified Xilinx LUT6 reproducer isolates the Icarus time-zero event-model
sensitivity: declaration-initialized zero inputs leave its output unknown,
whereas an input transition produces the expected one. The reproducer and
source-bound report are under `build/cacc_reduction_candidate/lut_startup/`.
An external-input transition under reset clears the original first-transaction
failure. That diagnostic was explicitly terminated after isolating the cause;
it is not a full-suite pass. The fresh `mapped_v2` runner applies `in_group=0`
at 1 ns, under reset, instead of initializing it at time zero. All known-input
tests, default GSR, DUT logic and vendor models are unchanged. The full suite
now **passes**: 2,712 groups, 204 outputs, five known-input faults, nine resets,
six cancellations and 979 held cycles, using the same seed and numerical
expectations as native RTL. This is functional primitive-model simulation,
not routed timing or hardware evidence. The original
failed mapped attempt remains in `mapped/`. The pre-fix
sources, tests and reports are preserved in `build/cacc_pre_synthesis_fix.tar.gz`.
Native reports are generated by
`build/run_cacc_native.py`; the completed mapping uses `build/run_cacc.py`.
Their manifests differ in runner/assertion-helper files, so common arithmetic
source identity must be checked explicitly rather than equating entire
manifests. The initial source/runner/tool-compatibility failures are retained
under the candidate directories, not relabeled as successful runs.

Physical timing, FPGA programming, RK differential testing and integrated
numerical GEMM remain unestablished by this standalone reduction evidence.
