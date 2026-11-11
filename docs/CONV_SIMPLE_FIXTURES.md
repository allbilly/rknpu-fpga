# Frozen conv-simple captures

Four `conv-simple` device captures are frozen under `tests/conv/fixtures/`.
They are the first fixtures in this repository for the `conv_simple.py` example
family.

## Frozen and admissible

| Case | Geometry | Output | BO bytes |
|---|---|---|---:|
| `conv_simple_fp16_3x3_c4_h8_w8_oc16` | C4 8×8 → OC16 k3×3 | FP16 | 1152 |
| `conv_simple_fp16_5x5_c4_h8_w8_oc16` | C4 8×8 → OC16 k5×5 | FP16 | 512 |
| `conv_simple_fp16_3x3_c16_h8_w8_oc32` | C16 8×8 → OC32 k3×3 | FP16 | 2304 |
| `conv_simple_fp16_1x1_c4_h8_w8_oc16` | C4 8×8 → OC16 k1×1 | FP32 | 4096 |

Each manifest binds the packed input, packed weight, raw 52-QWORD command
stream, host expected bytes, device output bytes and a recomputed oracle, all by
SHA-256. The capture's own BO placement is recorded: the 5×5 and C16 cases
place the output at `0x4000` and `0x5000` because the weight BO occupies
`0x2000..0x3c00`.

## Device/host-oracle divergences (live-reverified 2026-11-10 — device wins)

Three captures are **not frozen**, because the host oracle used at freeze time
disagrees with the device surface. They are **not** device faults: the live P0
job (two locked Rocket submissions per case, run1 == run2 byte-identical, both
byte-identical to the frozen 2026-11-05 device captures) reproduced the device
output exactly. The captures are valid device evidence; the `expected.bin`
oracles are what is wrong. None of these cases is in the six-page image.

| Case | Live-verified divergence from the host oracle |
|---|---|
| `conv_simple_fp16_1x1_c32_h8_w8_oc32` | **structural placement, not rounding.** The device emits only 6 of the oracle's 8 1,024-byte chunks: expected chunks 0,1,4,5,6,7 land in device slots 0..5 and slots 6,7 are zero-filled; 5,941/8,192 bytes differ, first at offset 2048 (device `d1 4b 7e c0` = -3.9733775 f32 vs oracle `92 df 4f 40` = 3.2480206). The oracle's layout model is wrong for this C32 FP32-output case. |
| `simple_conv_int8_5x5_c8_h8_w8_oc32` | 7 bytes equal `expected + 1` at offsets 117, 144, 388, 408, 434, 478, 510; every other byte equal, zero tail. A device output-conversion rounding behaviour the oracle does not model. |
| `simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64` | 13 bytes equal `expected + 1` at offsets 423, 438, 460, 518, 630, 646, 740, 1154, 1182, 1392, 1496, 1561, 1949; zero tail. Same conversion class. |

Device surfaces, the old oracles and a machine-readable diff are preserved in
`build/rk3588-live-verify/J05-device-oracles/` (see its `README.md` and
`manifest.json`); future RTL or fixtures for these cases must use the device
surface, not the old host oracle. Live evidence is classified **class A**
(oracle/fixture defect) in
[RK3588_LIVE_VERIFICATION_JOBS.md](RK3588_LIVE_VERIFICATION_JOBS.md) §7: no RTL
or bitstream change is implied, and the current six-page image is unaffected.

`conv_simple_fp16_1x1_c4_h8_w8_oc16` **now executes** as profile 3. Its device
output is FP32, so it uses `rk_cmac_fp32_writer` and the
`rk_conv_output_c1c2_fp32` placement stage instead of the FP16 atom writer. The
captured surface was measured, not assumed: it is `[c1][pixel][c2=4]` with a
plane stride of `PIXELS*C2` words, and that mapping reproduces all 1024 words
within 2.4e-7. Plain NCHW and NHWC both disagree by whole values, so an earlier
NCHW-transpose premise was wrong and its module was deleted rather than kept.

Evidence: `tools/conv/run_conv_simple_fp32.py --simulator both`, complete
4096-byte BO, 2048 halfword writes, 63/1024 words differing at the last bit
(worst 4.77e-7 against an explicit 0.001 bound).

## Independent oracle

For every frozen case the freezer recomputes the complete output BO from the
packed operand BOs alone, in pure Python, using the documented layout:

* input `[c1][H][width_stride][c2]` (or NHWC when `in_c <= c2`),
* weight `[oc_chunk][kh][kw][oc_lane][align_c]`,
* output `[c1][out_width_stride][c2]`, stride rounded up to 4 atoms.

The recomputation matches `expected.bin` **byte for byte**, and `expected.bin`
matches the device output byte for byte. That is why these cases are usable as
oracles and why the rejected ones are not.

## Executing path

`rtl/cmac/rk_conv_simple_profile.sv` checks the 52 raw words against
`rtl/cmac/rk_conv_simple_profiles.svh`, which
`tools/conv/gen_conv_simple_profiles.py` emits from the fixtures. Only QWORDs
18/24/32 may vary; a second stream after a complete job is code 7; a nonzero
padding word is code 2.

`rtl/cmac/rk_conv_simple_core.sv` wires that decoder to
`rk_conv_3x3_valid_c4_front` (now parameterised over KH/KW, channel blocks and
chunked weight BOs), the donor CMAC/CACC arithmetic and, selected at
elaboration by `OUTPUT_FP16`, either the FP16 output atom writer or the FP32
`rk_conv_output_c1c2_fp32` stage, with one arbitrated memory master. RTL
transposes nothing and computes no address in software: the FP32 stage places
each value at its captured plane/slot address, and the value itself is never
altered.

Evidence: `tools/conv/run_conv_simple.py` runs 13 modes per FP16 profile in
both simulators — complete output BO, six raw-profile rejections, four memory
faults and one second-stream rejection. The FP32 profile is a single-job replay
(`tools/conv/run_conv_simple_fp32.py`) because the extra modes were written for
the FP16 atom path.
