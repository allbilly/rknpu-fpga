# Captured FP16 depthwise C3 3×3 candidate

Status: **pinned capture, strict profile and diagonal depthwise frame
emission**. This is one exact depthwise capture, not general depthwise
convolution support, a descriptor DMA, full-top integration or FPGA
qualification.

## Source and task

`conv_depthwise_3x3_c3_h11_w28_oc3` is one successful 54-QWORD Rocket task
from the 2026-11-05 `conv-fp16` run on Orange Pi 5 / RK3588S, Linux
`6.18.24-current-rockchip64`, `/dev/accel/accel0`, `rocket_run.py` 1.0.0. The
pinned donor is `conv_new_clean.py`, SHA-256
`f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51`, using the
`depthwise_spatial_major` weight packing and `CNA_CONV_CON1` depthwise mode.

The task is FP16 depthwise valid 3×3, C3/H11/W28 → OC3/H9/W26, stride 1,
groups 3. Unlike the promoted grouped tasks, this capture is a **single**
task; there is no blocked multi-task parent. QWORDs 21, 27 and 35 remain the
three declared relocations, but the capture placed its weight and output BOs
at `0x3000` and `0x4000` rather than the sequential `0x2000`/`0x3000` used by
the other conv captures. The runner and testbench now read each fixture's own
address map instead of assuming one global placement.

Register deltas versus the C4 stride-1 capture are pinned at QWORDs 4, 5, 7,
8, 9, 10, 11, 12, 13, 14, 15, 23, 24, 25, 26, 28, 29, 30, 33, 36, 37, 38,
40, 42, 44 and 49; the contract test asserts each value.

## Packed data and expected checks

The input BO is 4,928 bytes: one NC1HWC2 C2=8 C1 plane of 11×28 pixels at a
16-byte pixel stride, with real C0..C2 and five zero lanes. Weights are the
donor's `depthwise_spatial_major [ky][kx][c2_out=8]` image — 144 bytes, real
lanes 0..2 only. The 15,104-byte output BO is NC1HWC2 with width stride 236
atoms; 234 atoms × 3 channels are defined.

The contract test verifies every defined halfword against the host oracle and
the captured device BO (`exact_mismatch_elements = 0`, `max_abs_diff = 0.0`,
padding tail entirely zero in this capture). The untouched bytes are still
checked against a canary in the replay rather than treated as an oracle.

## RTL

`rk_conv_3x3_valid_c4_profile` gained `DEPTHWISE_C3`, and
`rk_conv_3x3_valid_c4_front` gained `DEPTHWISE`: with it, each kernel lane
reduces exactly its own input channel, so the frame carries a **diagonal**
weight mask (`32'd1 << kernel`) and the tap's 8-lane depthwise weight block.
`rk_conv_3x3_depthwise_c3_core` is the exact-profile wrapper. No CPU arithmetic
or layout repair is involved: the packed BO is consumed as captured.

`tools/conv/gen_conv_profiles.py` now emits `rtl/cmac/rk_conv_3x3_profiles.svh`
directly from the eight pinned fixtures' relocated QWORD streams, so the
register tables can no longer drift from the captures. `make generated-check`
verifies the header is current.

`make conv-3x3-depthwise-c3-test` runs the contract test and the replay in
Icarus and Verilator. The 2026-11-07 Icarus run used source revision
`8011ff662f6a6877d0eac4e2e4a03ab3aededc0c`, Python 3.14.5 and seed
`0x3c4c9a31`; all 16 modes passed with 996 operand reads (72 weight, 924
input), 1,872 output halfword writes, 2,106 spatial frames and 15 negative
controls. Receipt:
`build/convolution-3x3-depthwise-c3/iverilog-20261107T123651Z/report.json`.

Passing these simulations does not validate other depthwise shapes,
CNA_PAD_CON0 padding, a descriptor DMA, an AXI/top endpoint, FPGA execution or
RK3588 compatibility.

## Two capture-driven corrections found by this case

1. The capture relocated its weight and output BOs at `0x3000` and `0x4000`,
   not the sequential `0x2000`/`0x3000` every other conv capture used. The
   runner and testbench previously assumed one global placement; both now take
   each fixture's own `command.addresses` map, and the relocated stream hashes
   to the captured `255bc33de373…`.
2. The depthwise weight image is `[ky][kx][C2]`, i.e. one lane per tap. An
   earlier version indexed it as `[tap][kernel][align_C]`, which produced an
   unsupported donor `res_tag` and a code-6 fault instead of results.

