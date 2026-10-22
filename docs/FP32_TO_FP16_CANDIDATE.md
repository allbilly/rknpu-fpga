# Staged post-accumulation output converter

`build/rk_fp32_to_fp16.sv` is an original three-stage elastic conversion leaf.
It is not in the production source manifest or connected to the raw-product
frontend, EW endpoint or board. A separate [staged output tail](CMAC_OUTPUT_CANDIDATE.md)
now joins it to the writer. It must be placed after
accumulation, never used to round individual FP16 products to half precision.
It does not implement the accumulator, generic DPU scaling or GEMM.

## Source evidence and unresolved RK behavior

The local RK TRM describes `RKNN_dpu_out_cvt_scale.fp32tofp16_en` and, at
`RKNN_dpu_out_cvt_shift` (0x4088), an even-tie versus unconditional-carry
rounding selection. It does not establish the accumulator width/order, nor
does this description alone prove precisely how the rounding field affects
the selected floating conversion path. The current backend's CMAC emitter
enables FP32-to-FP16 with unity scale but does not write `OUT_CVT_SHIFT` in
its 45-word body. Do not pretend that omission is a captured numerical result.

Inspected source pins:

- `~/npu` revision `e02707ca9b010372f1c506c7f3a2fa2c9f2beb8e`,
  `docs/rk3588_trm.md`, SHA256
  `4c3e78945393f74e74a36fabaf6954885f5eca5cbd38c70b97d49ce4e8836c0f`.
- `~/tinygrad` revision `078eee94d8f1912bb63ce786c250d2c24984844a`,
  `tinygrad/renderer/rockchip.py::emit_cmac_stage`.

The implemented **candidate** contract uses nearest/even, gradual FP16
underflow, signed zeros/infinities, infinity on finite overflow and canonical
positive quiet NaN `0x7e00`. No exception flags or NaN payload preservation are
provided. Finite conversion, especially ties, still needs RK differential
observations; the special-value policy is explicitly not established on RK.
The [NVIDIA donor audit](NVDLA_CONVERSION_AUDIT.md) demonstrated a different
overflow/NaN policy, so that donor cannot silently settle this question.

## Datapath and ownership

Stage 0 classifies the FP32 word, selects a target half exponent and a
right-shift count. For normals, the 24-bit significand is shifted by 13.
For half subnormals, FP32 encoded exponents 102..112 select shifts 24..14.
Smaller magnitudes round to signed zero; exponent 102 includes the minimum
half-subnormal midpoint. FP32 subnormals are all below this threshold.

Stage 1 rounds using guard, sticky and retained least-significant bits. The
11-bit quotient and 12-bit carry result cover every finite case. Stage 2 packs
the result, including the subnormal-to-normal carry and the finite-to-infinity
overflow carry. Special-value classification and opaque tags advance with
their data through every stage.

Default tag width is 97 bits, sufficient for destination/row/channel/last
metadata, but this leaf does not interpret or validate those fields. Width
zero is invalid. Three independent ready/valid stages allow one conversion
per cycle after filling and hold all data/tags under output backpressure.
Reset cancels buffered conversions. The surrounding job controller must reset
consumers consistently and retain command ownership through final write ack.

## Independent reference and tests

`build/gen_fp32_to_fp16_vectors.py` uses Python `struct` binary-format
conversion, not a port of the RTL shifting/rounding algorithm. FP32 values are
exactly represented by Python binary64 before the binary16 pack. Overflow and
NaN handling are explicit parts of the candidate oracle, not hardware data.

There are 330,760 vectors:

- 65,536 half encodings expanded to FP32;
- 190,458 predecessor/midpoint/successor cases across every adjacent finite
  positive-half boundary, reflected to the negative range;
- 10 overflow-midpoint neighbors, 5,120 exponent/fraction edge cases,
  4,100 low/quiet NaN payload cases and 65,536 seeded random FP32 encodings.

`build/tb_fp32_to_fp16.sv` also checks all 97 tag bits, exact three-stage
latency, continuous full throughput, full-pipeline backpressure, random
input/output gaps, drain without duplicates, reset with one/two/three buffered
records and reset after simultaneous consume/refill. The seed is `0x3588ca07`.

The initial strict lint caught unused upper rounding bits; widths were reduced
to the proven 11-bit quotient/12-bit carry range without changing expectations.
Icarus then reported three `always_comb` sensitivity limitations. The final
packing expression was rewritten as continuous assignments, without a warning
waiver. The first compiled preflight source is retained separately and must
not be treated as verification of the rewritten source.

Fresh source-bound Icarus 13.0 and Verilator 5.048 checks pass through
`build/run_fp32_to_fp16.py`, with zero native compile/run warnings. Both report
330,793 comparisons, four reset cases, 43,720 stalled-output cycles and
399,564 total cycles. Icarus additionally verifies the zero-tag-width parameter
fails at time zero with the intended message and nonzero exit status.

Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`) maps the default
97-bit-tag leaf to 362 FDCE, five FDPE, 202 LUT2..6, 15 CARRY4, twenty MUXF7
and two MUXF8 in 108.694 seconds. No DSP or BRAM is required. One ABC
combinational-network warning is retained; no internal unlowered cells remain.
This is primitive mapping, not simulation of that mapped netlist or timing.

The [candidate archive](../verification/runs/2026-09-21-fp32-to-fp16-candidate/index.json)
contains exact sources, independent vectors, commands, executable/log hashes,
exported netlist/JSON and the earlier preflight source/logs separately. A
short duplicate progress-diagnostic simulation was deliberately interrupted;
it is labeled diagnostic-only and did not replace or interrupt either final
source-bound run. Production source remains `db97404570f5`; a new baseline
`make -j4 test` is also running, distinct from its previously completed archive.
No RK, physical FPGA, mapped-netlist simulation or routed timing test has run.
