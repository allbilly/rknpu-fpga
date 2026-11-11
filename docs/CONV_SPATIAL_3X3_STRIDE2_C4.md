# Captured FP16 valid 3×3 C4 stride-2 candidate

Status: **standalone RTL candidate passes Icarus and Verilator replay**. This is
one exact task, not general stride support, padding support, a descriptor DMA,
full-top integration, or FPGA qualification.

## Capture and command contract

`conv_3x3_stride2_c4_h11_w11_oc4` is a successful one-task Rocket run from
2026-11-05 on Orange Pi 5 / RK3588S, Linux `6.18.24-current-rockchip64`,
`/dev/accel/accel0`, `rocket_run.py` 1.0.0. The pinned donor is
`/home/fedora/rk3588/examples/kernel_6_18/conv_new_clean.py`, SHA-256
`f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51`.
Portable provenance and device evidence are under
`tests/conv/fixtures/conv_3x3_stride2_c4_h11_w11_oc4/`.

The operation is FP16 valid 3×3, C4/H11/W11 → OC4/H5/W5, stride 2, groups 1.
Its 54 raw QWORDs have only the three job-declared value relocations at QWORDs
21 (input), 27 (weights), and 35 (output). The stream is not rewritten. It is
not admitted by the stride-1 decoder: compared with that capture, the exact
geometry-dependent register changes are QWORDs 5, 6, 7, 9, 10, 15, 23, 24, 25,
30, 36, 37, 38, 44, and 49. The contract test pins every changed value and
rejects unlisted differences.

## Operand, schedule and output contract

The input BO is 3,872 bytes in NC1HWC2 with C2=8. The front fetches C0..C3 from
the first packed C1 plane, at 16-byte pixel stride; the other C2 lanes and the
second C1 plane are zero in the capture. The 1,152-byte weights are kh-major,
with 16 input slots per output kernel; the arithmetic frame masks only C0..C3
and OC0..OC3. Each output `(y,x)` consumes nine kh-major windows rooted at
`(2*y, 2*x)`.

The engine reads 576 weight and 484 input halfwords, emits 225 reduction frames,
and produces 25 output atoms. Each atom writes eight halfwords at a 16-byte
stride: OC0..OC3 are checked against the 100-element NCHW source oracle and
device capture, while the padded OC lanes must be zero. The logical result is
200 bytes; the full captured output BO is 1,792 bytes with width stride 28.
Simulation must preserve all unwritten bytes as canaries; captured padding is
not a numerical oracle. The fixture's 100 defined values match the successful
RK device output exactly. Special-value behavior is not established.

## Verification boundary

Run `make conv-3x3-stride2-c4-test`. The fixture contract test verifies the
pinned one-task capture, source hash
metadata, three relocations, exact register delta, packed input/weight layout,
and all defined device output elements. The raw profile and spatial core are a
standalone command-stream candidate. They are not connected to the FPGA top or
the existing 49-QWORD CMAC DMA path. No FPGA, RK target, or bitstream is used by
the RTL simulation tests.

The 2026-11-07 run used source revision
`8011ff662f6a6877d0eac4e2e4a03ab3aededc0c`, Python 3.14.5, Icarus Verilog
13.0 (all 16 modes passed) and Verilator 5.048 (14 modes passed; the two X/Z
address tests are skipped because it is a two-state simulator). The fixed
handshake seed was `0x3c4c9a31`. Verilator recorded 97 warning headers; compile
logs and per-file hashes are retained in
`build/convolution-3x3-stride2-c4/iverilog-20261107T081557Z/` and
`build/convolution-3x3-stride2-c4/verilator-20261107T081557Z/`.
