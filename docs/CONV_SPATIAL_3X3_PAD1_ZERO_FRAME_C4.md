# Captured FP16 3×3 C4 explicit-zero-frame candidate

Status: **strict raw profile and spatial replay pass in Icarus and Verilator**.
This remains one source-bounded candidate, not general SAME padding or general
3×3 convolution support.

## Source and task

`conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` is one successful 54-QWORD Rocket task
from the 2026-11-05 `conv-fp16` run on Orange Pi 5 / RK3588S, Linux
`6.18.24-current-rockchip64`, `/dev/accel/accel0`, `rocket_run.py` 1.0.0. The
pinned donor is `conv_new_clean.py`, SHA-256
`f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51`. Fixture,
device capture, operands, expected output and provenance are under
`tests/conv/fixtures/conv_3x3_pad1_zero_frame_c4_h9_w9_oc4/`.

The donor realizes pad=1 by supplying an **explicit** 11×11 zero-framed input
buffer for a valid 3×3 operation; the task itself is valid convolution. The FPGA
candidate must consume that captured BO exactly. It must not synthesize padding
or perform runtime host layout repair. Only QWORDs 21, 27 and 35 are declared
address relocations. Relative to the captured H9/W9 stride-1 valid profile, the
exact register-value differences are QWORDs 5, 7, 9, 10, 15, 23, 24, 25, 30,
36, 37, 38, 44 and 49; the contract test pins their values.

## Packed data and expected checks

The input BO is 3,872 bytes in NC1HWC2, C2=8: its first 11×11 plane contains
C0..C3 and four zero lanes, the second C1 plane is zero, and the one-pixel
border is explicitly zero in all channels. Weights are the same kh-major 1,152
byte layout used by the other pinned C4 tasks. The 5,376-byte output BO is
NC1HWC2 with output width stride 84 and align_out_c=32. It contains an 81×4
logical FP16 output; the successful RK capture matches all 324 source-oracle
halfwords exactly. Padding bytes are not a numerical oracle and must remain
untouched outside the defined write span.

`make conv-3x3-pad1-zero-frame-c4-test` checks the fixture/profile contract and
replays all 54 raw QWORDs in both simulators. The 2026-11-07 run used source
revision `8011ff662f6a6877d0eac4e2e4a03ab3aededc0c`, Python 3.14.5 and seed
`0x3c4c9a31`. Icarus Verilog 13.0 passed all 16 modes; Verilator 5.048 passed
the 14 two-state-applicable modes and recorded 98 warning headers. Each run
checked 1,060 reads (576 weights, 484 input), 729 frames, 648 halfword writes,
all 324 defined output halfwords, untouched BO bytes and 15 negative controls.
The corrected output-range control uses aligned base `0xffffeb10`, for which
the 5,376-byte exclusive endpoint overflows 32 bits. Receipts are under
`build/convolution-3x3-pad1-zero-frame-c4/{iverilog,verilator}-20261107T083709Z/`.

The standalone candidate is not connected to the FPGA top or a qualified DMA
endpoint. These simulations do not establish special-value policy, FPGA
execution or general padding support.
