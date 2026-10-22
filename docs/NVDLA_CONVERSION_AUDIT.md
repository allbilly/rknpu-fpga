# NVIDIA output-conversion audit

This is donor evidence, **not RK3588 numerical evidence**. It does not change
the EW arithmetic policy, integrate NVIDIA RTL, or establish a GEMM accumulator
contract. No donor checkout was modified.

The reported overflow/NaN difference is **NVIDIA RTL versus this project's
earlier IEEE-style conversion reference**, not a demonstrated NVIDIA RTL bug
or an executed NVIDIA C-model-versus-RTL mismatch. The C-model was inspected,
not run. Following the user's direction, the unmodified NVIDIA datapath is
now the working output-conversion baseline; the original candidate evidence
is preserved separately. See [NVDLA_CONVERTER_ADAPTER.md](NVDLA_CONVERTER_ADAPTER.md).

The clean `/home/fedora/tinygrad` branch `rockchip-2608-1500`, commit
`078eee94d8f1912bb63ce786c250d2c24984844a`, supplies path-specific compiler
evidence in `tinygrad/renderer/rockchip.py`: finite intermediates repair the
infinite-numerator FDIV sign at lines 987–990; raw-half classification handles
NaNs at 1123–1128; raw INT16 selection preserves nonfinite arms at 1130–1146;
and finite-min lowering substitutes -65504 for selected -infinity constants
at 909–912. These are source observations, not newly executed backend tests.
They support preserving the existing compiler decompositions and avoiding a
blanket IEEE hardware contract. They do not establish that every RK arithmetic
unit uses this particular FP32-to-FP16 converter's special-value policy.

At `/home/fedora/hw` revision
`8e06b1b9d85aab65b40d43d08eec5ea4681ff715`, the FP16-processing branch of
`cmod/hls/sdp/sdp_c.cpp` calls `Fp32ToFp16`. In
`cmod/hls/include/nvdla_float.h`, that selects `FpWidthDec` with denormals
enabled. The normal and subnormal paths use guard/sticky/least-bit RNE logic.
But its `SetToInf` helper sets the exponent to all-ones-minus-one and the
fraction to all ones: it saturates to the largest finite value. The final NaN
branch copies the sign and truncates the input fraction to the output width;
it does not necessarily retain the input quiet bit or a nonzero payload.

## Direct RTL observations

The unmodified `vmod/vlibs/HLS_fp32_to_fp16.v` was compiled with Icarus 13.0.
Forty directed values covered signed zero, FP32 subnormals, FP16 underflow
midpoints, the normal/subnormal boundary, even/odd rounding ties, overflow,
infinities and several NaN payloads. Each output was also stalled for three
cycles and checked stable before acceptance. The bench rejects extra outputs.
All observations matched the separately evaluated source hypothesis. Sixteen
differed from this project's RNE/infinity/canonical-NaN conversion reference.

| FP32 input bits | Observed FP16 bits | Meaning |
|---|---|---|
| `3f801000` | `3c00` | Tie rounds to even at 1.0 |
| `33000000` | `0000` | Halfway below the least positive half rounds to zero |
| `33000001` | `0001` | Just above that midpoint preserves a subnormal |
| `477ff000` | `7bff` | 65520 clamps, rather than rounding to infinity |
| `7f800000` | `7bff` | Positive infinity becomes largest finite half |
| `7fc00000` | `7c00` | This quiet NaN loses its payload and becomes infinity |
| `7fc00123` | `7d23` | Low fraction bits survive; not canonical quiet NaN |

These are actual donor RTL outputs, not results inferred solely from C++ names.
The C++ model itself was not compiled/executed. This is not exhaustive over
FP32 values, is not a timing-calibrated model, and does not prove that RK uses
the same conversion behavior. In particular, these results must not silently
replace the current candidate's overflow or NaN policy.

The runner is `build/audit_nvdla_conversion.py`, the bench is
`build/tb_nvdla_fp32_to_fp16_audit.sv`, and results are under
`build/nvdla_conversion_audit`. The compilation retains one inherited-time-unit
warning with its affected-module list; no donor source or warning policy was
modified to suppress it. The source-bound
[archive](../verification/runs/2026-09-21-nvdla-conversion-audit/index.json)
includes unmodified donor snapshots and their NVIDIA/Mentor notices and license.
They are evidence copies, not production source imports.

## Pinned files

- `cmod/hls/include/nvdla_float.h`: `b020e2ccc140a2d4f8e7c59514b9ee24bf07697bc06a3730f3d3b61fbd9d4f6b`
- `cmod/hls/sdp/sdp_c.cpp`: `5bb64d60d184d525f45331ba69f44cdd27550ec44f96458671d19684034186a4`
- `vmod/vlibs/HLS_fp32_to_fp16.v`: `56755f347c87a7c8b33458dbdfd2630d57f4dbc4aa1f8f3b2a4dfefedc0401cd`
