# Exact FP16 product candidate

**Current location:** the unchanged leaf is now `rtl/rk_fp16_product.sv`,
connected to the [raw product path](CMAC_PRODUCT_PATH.md). The leaf bench and
new wrapper are in a fresh expanded regression, currently running. The
standalone results below retain their original source scope and do not prove
the new integration.

`build/rk_fp16_product.sv` is an original, internal arithmetic leaf. It accepts
two raw FP16 operands plus an opaque tag, and emits an FP32-encoded product with
that tag. It does not introduce a tensor-operation API, change the raw-command
execution boundary, or add production GEMM support. It is currently separate
from the staged command/operand path and from the EW engine.

## Finite arithmetic contract

For a finite half, let `E` be the encoded exponent, except use 1 when the
encoded exponent is zero. Let `M` be the ten fraction bits with an implicit
leading one for normal values and zero for subnormals. Its magnitude is
`M * 2^(E-25)`. Thus the exact product has integer significand `P = Ma*Mb`
(at most 22 bits) and scale `2^(Ea+Eb-50)`.

For nonzero `P`, let `k` be its highest set-bit index. The FP32 biased exponent
is `Ea+Eb+k+77`; the fraction is the lower 23 bits of `P << (23-k)`. The implicit
leading one is not stored. There is no rounding step: FP32 has 24 significant
bits and can exactly carry the entire finite product. The nonzero range begins
at 2^-48 and ends at 65504 squared, entirely within FP32's normal range.

This specifically avoids the existing EW multiplier's rounded FP16 output,
which would lose small products and overflow large ones before accumulation.
It does **not** select an accumulation precision, reduction tree, intermediate
rounding order or final FP16 conversion rule. Those remain separate contracts.

Input subnormals are preserved. The provisional special-value policy produces
sign-XOR zero and infinity, and positive canonical quiet NaN `0x7fc00000` for
NaN operands or zero times infinity. NaN payloads and exception flags are not
exposed. These policies are candidates, not established RK3588 silicon behavior.

## Pipeline and tags

The three register stages perform operand classification/preparation, an
11-by-11 significand multiply, and FP32 normalization/encoding. Each stage has
its own valid bit and space/backpressure condition. Bubbles may fill unused
slots while a later stage is stalled. Output data and tag remain stable until
accepted; no flag or tag is advanced independently of its data.

When unstalled, output data become valid after the third capture edge and the
next edge can consume them. The full pipeline accepts and produces one product
per cycle. This is this implementation's timing, not calibrated RK timing.
Default tag width is 131 bits, enough for four 32-bit coordinate/address fields
and three boundary flags from the operand path. The leaf treats tags as opaque.
Reset cancels every buffered transaction. It does not report a GEMM/job done.

## Reference-source relationship

The inspected Vortex commit and file hashes are recorded in
[LOCAL_REFERENCES.md](LOCAL_REFERENCES.md). Its TFR FP16 leaf confirms the
11-by-11 significand product and classification pattern. Its FPnew wrapper
selects FP16 input and FP32 output, but requires additional dependencies and
does not expose this project's elastic tagged interface. No Vortex code was
imported, modified or simulated here. Neither source proves RK reduction order.

The NVIDIA donor uses a grouped, exponent-aligned 44-bit CMAC result and a
separate configurable accumulator format; see the additional source audit in
`LOCAL_REFERENCES.md`. The FP32-encoded product here is not that wire format and
cannot be connected directly to its CACC input. Its canonical-NaN policy also
does not preserve NVIDIA's channel-priority payload behavior.

## Verification scope

The independent generator uses Python binary64 multiplication of `struct`-decoded
halves, followed by FP32 packing. It explicitly checks that every finite value
is preserved exactly. The 230,400 vectors include all 65,536 encodings in the
first operand against two partners, all encodings in the second operand against
a bijection, a 32-by-32 special/boundary grid and 32,768 seeded random pairs.
This is not exhaustive over all 2^32 operand pairs and is not a silicon capture.

The HDL bench additionally checks full 131-bit tags, full-pipeline stalls,
128 consecutive full-throughput transfers, randomized source/sink stalls,
drain behavior and four reset/cancellation cases. The expected comparison count
is 230,433, including restart checks. Verilator 5.048 and Icarus 13.0 both
pass all 230,433 comparisons, with four reset cases, 30,466 stall cycles and
278,375 total cycles each, seed `0x3588ca04`. Strict lint and simulator builds
have zero warnings. Simulation took 8.444 seconds in Verilator and 326.803
seconds in Icarus. Results are under `build/fp16_product_candidate/report.json`;
the source-bound [archive](../verification/runs/2026-09-21-fp16-product-candidate/index.json)
also retains the vectors, executables and mapping results. The production
source remains `f927a501cec9`; this leaf is not part of its normal regression.

The initial run failed because the bench left output-ready high over an
unobserved clock when switching from throughput to random traffic. The observed
value/tag were exactly vector 129 while the scoreboard still expected 128.
The bench now holds output-ready low across that transition. DUT RTL, arithmetic
expectations and assertions are unchanged; the failed source/logs are retained
in `build/fp16_product_bench_transition_failure.tar.gz` and both simulators
passed fresh runs against the corrected bench.

XC7 mapping is checked separately in `build/fp16_product_mapping/report.json`.
Yosys 0.65 maps the default 131-bit-tag leaf successfully to one DSP48E1,
492 FDCE, 156 LUT1..6, four CARRY4, 27 MUXF7 and seven MUXF8 cells. It retains
one ABC combinational-network warning. There are no remaining internal
unmapped cells. These are synthesis counts, not placed utilization or Fmax;
the mapped product netlist has not been simulated.
Neither mapping nor this arithmetic test proves accumulated GEMM, physical
timing, integration with PCIe/DDR, or an FPGA/RK hardware result.
