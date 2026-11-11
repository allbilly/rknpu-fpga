# Captured FP16 split-OC C16 3×3 candidate

Status: **two promoted one-task captures with pinned fixtures and a
parameterized raw replay**. This is not general split-OC support, a descriptor
DMA, full-top integration or FPGA qualification.

## Source and tasks

`conv_splitoc_3x3_c16_h9_w9_oc16_task0` and `..._task1` are the two promoted
one-task jobs of the 2026-11-05 `conv-fp16` split-OC case. The parent two-task
job is **BLOCKED / MULTITASK_ROCKET_JOB_UNSUPPORTED**: the board executed only
task 0 and left task 1's output BO all zero. The promoted runs matched their
per-task oracles exactly (`submit_ret=0`, 0 mismatches, max abs diff 0.0). The
pinned donor is `conv_new_clean.py`, SHA-256
`f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51`.

Each task is FP16 valid 3×3, C16/H9/W9 → OC8/H7/W7, stride 1, groups 1 — one
OC8 half of a `C16 → OC16` convolution. Both tasks share the same 54-QWORD
command template (`a60a4448…`) and the same 2,592-byte input BO; only the
kh-major weight half and the output BO differ. QWORDs 21, 27 and 35 remain the
three declared address relocations.

The geometry registers differ from the C4 stride-1 capture at QWORDs 8
(`0x000f0010`), 11 (`0x00000900`), 13 (`0x03030008`), 14 (`0x0000001b`) and 40
(`0x0007001f`); the contract test pins them. The weight BO range is 2,304 bytes
rather than 1,152, so the profile's weight bounds are parameterized too.

## Packed data and expected checks

The input BO is NC1HWC2 C2=8: two C1 planes of 81 pixels × 8 lanes. Plane 0
carries C0..C7 and plane 1 carries C8..C15; a pixel advances 16 bytes within a
plane. Weights are kh-major `[ky][kx][OC][align_C=16]` with eight real kernels
and sixteen real input lanes — 1,152 halfwords per task. The 3,328-byte output
BO is NC1HWC2 with width stride 52 atoms; the 49 atoms carry eight defined OC
lanes.

The contract test verifies every defined halfword against the host oracle and
the captured device BO. The rest of the output BO is **not** a numerical oracle:
the board capture retains prior-job bytes there, so the replay checks untouched
bytes against a canary.

## RTL

`rk_conv_3x3_valid_c4_profile` gained an elaboration-time `SPLIT_OC_C16`
selector. `rk_conv_3x3_valid_c4_front` is now parameterized by real channels,
kernels, `align_c`, packed C2 width and derived plane count, so the same
schedule emits nine kh-major frames for C2/K4, C4/K4 and C16/K8 without literal
capture tables. `rk_conv_3x3_splitoc_c16_core` is the exact-profile wrapper.

`make conv-3x3-splitoc-c16-test` runs the contract test and both one-task
replays in Icarus and Verilator. Passing these simulations does not validate
the blocked parent two-task job, the full C16→OC16 shape in one job, a
descriptor DMA, an AXI/top endpoint, FPGA execution or RK3588 compatibility.
