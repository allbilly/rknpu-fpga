# Captured FP16 grouped-task C2 3×3 candidate

Status: **two promoted one-task captures with pinned fixtures and a
parameterized raw replay**. This is not general grouped convolution support,
a descriptor DMA, full-top integration or FPGA qualification.

## Source and tasks

`conv_grouped_3x3_c4_h5_w5_oc8_g2_task0` and `..._task1` are the two promoted
one-task jobs of the 2026-11-05 `conv-fp16` grouped case. The parent two-task
job is **BLOCKED / MULTITASK_ROCKET_JOB_UNSUPPORTED**: on that kernel the board
executed only task 0 and left task 1's output BO all zero. The promoted cases
run each task alone, and the board matched each oracle exactly (`submit_ret=0`,
0 mismatches, max abs diff 0.0). The pinned donor is
`conv_new_clean.py`, SHA-256
`f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51`.

Each task is FP16 valid 3×3, C2/H5/W5 → OC4/H3/W3, stride 1, groups 1 — the
group slice of a `groups=2` convolution. The two cases share one 54-QWORD
command template (`29b60f0b…`) because only the per-group operand and output
BOs differ; QWORDs 21, 27 and 35 are the three declared relocations.

## Packed data and expected checks

The input BO is the donor's NC1HWC2 C2=8 packing: 25 pixels × 16 bytes in each
of two C1 planes, 800 bytes total. C0/C1 hold the group's real channels, the
remaining six lanes are zero, and the second plane is entirely zero. Weights
are the usual kh-major `[ky][kx][OC][align_C=16]` 1,152-byte image, with real
IC lanes 0..1 and OC kernels 0..3. The 768-byte output BO is NC1HWC2 with
width stride 12 atoms and align_out_c=32; its nine 8-lane atoms carry four
defined OC lanes each.

The contract test verifies every defined halfword against the host oracle and
the captured device BO. Padded OC lanes and the rest of the output BO are
**not** a numerical oracle: the board capture retains prior-job bytes there,
which is why the replay checks untouched bytes against a canary instead of
treating the captured padding as expected data.

## RTL

`rk_conv_3x3_valid_c4_profile` gained an elaboration-time `GROUPED_C2`
selector with the captured register deltas at QWORDs 5, 7, 8, 9, 10, 15, 23,
24, 25, 30, 36, 37, 38, 44 and 49 and the 800/768-byte BO bounds.
`rk_conv_3x3_valid_c4_front` is parameterized by real channels, kernels,
`align_c` and packed C2 width, so the same schedule emits nine kh-major frames
for C2/K4 and C4/K4 without literal capture tables.
`rk_conv_3x3_grouped_c2_core` is the exact-profile wrapper.

`make conv-3x3-grouped-c2-test` runs the contract test and both one-task
replays in Icarus and Verilator. Passing these simulations does not validate
the blocked parent two-task job, a descriptor DMA, an AXI/top endpoint, FPGA
execution or RK3588 compatibility.
