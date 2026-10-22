# Local reuse candidates — source audit, not execution evidence

The user supplied these repositories for continuing the FPGA implementation.
The 2026-09-21 home-directory inventory was read-only and excluded credential
contents. None of these candidates has been integrated by this audit, and old
test logs do not establish success against modified RTL.

## Vortex floating-point paths

`/home/fedora/vortex` finished its user-started clone during this continuation.
Inspected revision: `5ce5a1a915b06c42c60393a7ea24168e0e01078f`.

The strongest FP16 candidates are under **`hw/rtl/tcu`**, not the selected scalar
FPU configuration:

- `tfr/VX_tcu_tfr_mul_f16.sv` extracts FP16 sign/exponent/mantissa and implements
  an 11-by-11 mantissa product, optionally using DSP48 inference via `USE_DSP`.
  SHA256: `41c58778019b44355e533a19c7283326f74b74fef2f70bdecce386057b1d82ea`.
- `tfr/VX_tcu_fedp_tfr.sv` supplies multiply, exponent alignment, accumulation
  and normalization stages, with explicit pipeline enables and lane metadata.
  Its accumulator-width assertion permits only 27..32 bits; this is not the
  NVIDIA CACC 48-bit format. SHA256:
  `62dbf8bb7b41cad3f67723fdc65778579f40ebf801b4e4910f37a7de2a4ac908`.
  The configured pipeline is explicitly restricted to four or five stages and
  advances under a shared `enable`; it is not a ready/valid elastic leaf. Any
  reuse needs to preserve stall-aligned operands, classification and reduction
  metadata rather than only delaying the output data.
- `tfr/VX_tcu_tfr_norm_round.sv` contains RNE logic and outputs FP32. Its
  `exp_underflow` branch selects zero, not a general gradual-underflow result.
  That is a compatibility question, not a reason to change this project's
  candidate FP16 policy without silicon evidence.
- `fpnew/VX_tcu_fpnew_mulfp32.sv` wraps `fpnew_fma_multi` with FP16 source,
  FP32 destination and RNE. The enclosing `VX_tcu_fedp_fpnew.sv` reduces via a
  tree of FP32 adders then adds C. That rounding/reduction order cannot simply
  replace RK CMAC/CACC. Wrapper SHA256:
  `2e52b11376528f80ceecf099540fa88352f48c76800d78debbf9340a80f46d2d`.

`hw/rtl/fpu/VX_fpu_fpnew.sv` enables FP32, or FP32+FP64 in its 64-bit
configuration, not FP16 in its present format mask. `VX_fma_unit_rtl.sv` is
parameterized but advertises F32/F64; parameterization alone is not FP16 proof.
The `third_party/cvfpu` and `third_party/hardfloat` directories were empty at
inspection. No Vortex configure, build, simulation or FPGA test was run. Any
future Vortex test must use its documented generated out-of-tree build flow.
Keep Apache-2.0 notices and audit transitive licenses before importing leaves.

## Other useful inputs

| Location | Useful material | Compatibility boundary |
|---|---|---|
| `/home/fedora/hw`, `8e06b1b9d85aab65b40d43d08eec5ea4681ff715` | NVIDIA nvdlav1 FP16 CMAC, CACC fp48 and C models | Strong arithmetic reference; not proven RK equivalence |
| `/home/fedora/soDLA`, `66d9b2683aea6fe787fbde5b8ca19abb825d1247` | Chisel control/storage and generated RTL | Selected CMAC is signed integer, not FP16 |
| `/home/fedora/ypcb/ref/LC480T/YPCB-00338-1P1` | XDMA, MEMTest, platform Vivado project ZIPs | Board-reference candidates; audit pins/clock/reset/electrical and generated IP first |
| `/home/fedora/ypcb/ref/ypcb_00338_1p1_hack/examples/YPCB_00338_1P1_systest` | Unpacked XDMA and MIG IP/constraints | XDMA metadata requests X8, 5.0 GT/s and 128-bit AXI-MM; not a verified active link |
| `/home/fedora/nvdla/examples/vp` | Capture parsers, register logs, buffer dumps, output.dimg | NVDLA VP, not RK silicon; do not pair a stale output with another run |
| `/home/fedora/hw/verif/traces/traceplayer` | Transactions plus input/weight/expected output files | Official NVDLA test vectors, primarily inspected INT16 cases |
| `/home/fedora/tinynvdla` | CBUF ownership/CSC sequencing, trace adapters and educational RTL | INT8 convolution and separate software FP16 SDP, not FP16 GEMM RTL |
| `/home/fedora/tinygrad_nvdla` | Direct-register native SDP ADD/MUL reference | CPU SUB negation and dtype conversion paths cannot enter this FPGA runtime |
| `/home/fedora/verigpu/src/float` | Pipelined floating add/multiply and tests | Selected parameters are FP32; source/test presence is not RK validation |

`/home/fedora/nvdla/ref/test_result.md` explicitly reports historical false
positives (CRC failures despite exit zero), address-offset errors and unverified
outputs. Reuse its raw inputs and infrastructure only with fresh, independent
result checks. No matched raw-command/input/output **RK3588 silicon** replay
bundle was identified in the inspected directories. A subsequent Git-history
audit found deleted raw GEM dumps in `/home/fedora/npu` at `2cd0173`, including
input and output bytes matching a printed RKNN convolution run. Their task,
command and log address bindings conflict, so they are not yet a matched
replay bundle. See [HISTORICAL_CAPTURES.md](HISTORICAL_CAPTURES.md).

The current working Rockchip encoder remains `/home/fedora/tinygrad` at
`078eee94d8f1912bb63ce786c250d2c24984844a`; these donors do not replace it.
See [EW_INITIALIZATION.md](EW_INITIALIZATION.md) for this increment's actual
implementation and captured final command boundary.

## NVIDIA arithmetic seam: preserve the distinction

Follow-up read-only inspection of the same `~/hw` commit locates the FP16
calculation in `cmod/cmac/NV_NVDLA_cmac.h`, not just the transport `.cpp`.
Its `cal_fp16_exp`, `cal_fp16_mul` and `calculation_fp16` routines choose a
group maximum from exponent portions, align signed products to that scale,
and reduce the group. The shown implementation uses 64 parallel channels and
emits a six-bit exponent plus 38-bit signed significand. This is not an IEEE
FP32 sum or an independently rounded FP16 product stream.

`cmod/cacc/NV_NVDLA_cacc.cpp::cacc_fp16_add` explicitly extracts those 44 bits.
The default header selects an eight-bit exponent and 40-bit significand (48
bits total); `NVDLA_GENERIC_CACC_USE_39_BIT_FP_ADDER` selects a different 39-bit
configuration. `cacc_fp48_to_fp32` is a separate conversion seam. A module name
containing FP16 or FP48 alone is not a complete numerical contract.

The CMAC header also has channel-priority NaN payload handling. Its debug
comparison explicitly substitutes signed 65536 for infinity encodings, while
the multiplier preparation uses a hidden one for nonzero encoded exponents.
These are reasons to audit the actual exception/alignment paths, not assume
IEEE multiplication semantics from the format name or use this donor as an RK
oracle. No NVIDIA C-model execution or RK equivalence was established here.
In particular, the user's RK IC32 packing does not prove a 64-channel numerical
reduction group identical to this donor.

The donor RTL `vmod/nvdla/cacc/NV_NVDLA_CACC_CALC_fp_48b.v` further shows that
the final FP32 conversion rounds the absolute mantissa by adding its guard
bit (`fp32_mant_cut[14]`), without an even-LSB tie test. This source expression
implies nearest/ties-away behavior at that seam, not the Vortex RNE rule.
Its partial-sum rounding separately uses
`mant_sum_guard & (~mant_sum_sign | mant_sum_stick)` on a signed mantissa.
The module exposes input/output valid signals but no ready/backpressure port;
an elastic integration would need bounded buffering or controlled issue.
These are source observations only: this CACC RTL has not been simulated in
this audit, and neither its rounding nor its reduction group is an RK oracle.

Inspected SHA256 pins:

- `cmod/cmac/NV_NVDLA_cmac.h`: `c188324560888dacd858c396dba3155cf7e9124dda8405984db8cc1018baa58a`
- `cmod/cacc/NV_NVDLA_cacc.cpp`: `e2142ba2076b40628cf900832136153007e71d256973cc7c449cbff459512a52`
- `cmod/cacc/NV_NVDLA_cacc.h`: `673cb3dab7d7904b1d10501c9ad564d04e2da7acf7fa63b9913a2a65dbfb50a1`
- `vmod/nvdla/cacc/NV_NVDLA_CACC_CALC_fp_48b.v`: `ef3dbfb8b56f4359f6554af9e3c07e3b47b87423b255c17aaedeeb0dc94b7028`

## Output conversion: a donor name is not an IEEE/RK contract

A subsequent [direct conversion audit](NVDLA_CONVERSION_AUDIT.md) compiled the
unmodified NVIDIA `HLS_fp32_to_fp16.v` with Icarus. Forty directed observations
confirmed the inspected C++ source's finite saturation and low-bit NaN payload
truncation, including `7f800000 -> 7bff` and `7fc00000 -> 7c00`. Sixteen cases
differ from the project's infinity/canonical-NaN reference. No RK output was
captured and no NVIDIA RTL was integrated. This rules out treating that donor
as an interchangeable IEEE converter without an explicit policy decision and
hardware differential evidence.
