# Captured FP16 valid 3×3 C4 convolution candidate

Status: **three standalone capture-bounded spatial convolution candidates**:
valid stride-1 C4, valid stride-2 C4, and explicit-zero-frame C4. Two promoted
grouped-task C2 slices have their own separate contract. These exact profiles
do not imply general stride, padding, grouped or spatial convolution support,
descriptor DMA, full-top integration or FPGA qualification.

## Source and captured case

The case `conv_3x3_valid_c4_h9_w9_oc4` is a single successful task from the
2026-11-05 `conv-fp16` Rocket run on Orange Pi 5 / RK3588S, Linux
`6.18.24-current-rockchip64`, `/dev/accel/accel0`, `rocket_run.py` 1.0.0.
The pinned source is
`/home/fedora/rk3588/examples/kernel_6_18/conv_new_clean.py` at SHA-256
`f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51`.
The builder and oracle evidence is in
`tests/conv/fixtures/conv_3x3_valid_c4_h9_w9_oc4/{provenance.json,job.json,device_capture.json}`.

The donor defines FP16 C4/H9/W9 to OC4/H7/W7, valid 3×3, stride 1, groups 1.
The capture contains 54 QWORDs; only QWORDs 21 (feature input), 27 (weights)
and 35 (output) are address relocations. The original template hash is
`e9f7bb0ecbce9301dec9fee8fbc44bc4cbce2e9c9ebe8fd48dc94eac0672725a`; applying
only the job's three `value32` patches at `0x1000`, `0x2000` and `0x3000`
reproduces the captured command hash
`274a23fbad839349fc89d41eb12265ed5873d67fa2534b70dc0241e50731778c`.
The strict decoder checks all targets, offsets, values and the terminal task
boundary before any operand read or output write.

The separate [`stride-2 C4 profile`](CONV_SPATIAL_3X3_STRIDE2_C4.md) has its
own exact 54-QWORD register schedule for C4/H11/W11 → OC4/H5/W5. The
[`explicit-zero-frame profile`](CONV_SPATIAL_3X3_PAD1_ZERO_FRAME_C4.md) and the
[`grouped-task C2 profile`](CONV_SPATIAL_3X3_GROUPED_C2.md) likewise keep
their own register deltas. All of these profiles share only the three
job-declared address relocations; one capture's geometry registers are never
admitted by another capture's decoder.


## Shape, operand and output contracts

- `a.bin` is the original 2,592-byte NC1HWC2 feature buffer. C2 is 8: the first
  C1 plane contains C0–C3 and four zero lanes; the second 1,296-byte C1 plane is
  zero. A pixel advances 16 bytes within a plane. The spatial front reads the
  four real FP16 values from the first plane and masks the other 28 C32 lanes.
- `w.bin` is the original 1,152-byte kh-major tensor `[ky][kx][OC][align_C=16]`.
  Each of nine taps supplies four output kernels and four real input channels;
  unused C32/K16 lanes are zero and masked.
- `expected.bin` contains 196 FP16 values in logical NCHW order. The source
  oracle uses FP64 accumulation of FP16 operands followed by one FP16 rounding;
  the donor's tolerance is `atol=0.2`.
- The RK output allocation is 3,328 bytes in NC1HWC2 with C2=8, four C1 planes
  and a 52-atom plane stride. The 196 logical values occupy lanes C0–C3 of the
  first 49 atoms. Only those logical values are numerical oracles. Captured
  channel padding and the remainder of the output BO are not promoted to
  stable numerical results.

The standalone front loads the captured weights and real input values into
local storage, then emits nine kh-major CMAC frames for each of 49 output
atoms. The existing C32/K16 FP16 CMAC/CACC and acknowledged FP16 atom writer
are reused. This small local-store schedule is not a full RK CBUF/CSC model.
The host still supplies the original raw command words and packed BOs; there is
no tensor-op shortcut, software arithmetic, operand repack or runtime output
repair.

The bounded raw profile rejects unsupported writes, bad framing, unaligned or
overlapping buffers and 33-bit range overflow. Memory errors and read/write
timeouts are sticky failures. A failed command profile must not touch operand
or output memory. The finite random capture is the only numerical domain
compared here; no general FP16 special-value policy is inferred from it.

## Verification

Run:

```sh
make generated-check
make conv-3x3-valid-c4-test
python3 -m unittest tests.conv.test_3x3_valid_c4_contract -v
```

The dual-simulator runner checks the capture hash and three relocations, every
operand read address, all 441 window frames and masks, all 392 C2-lane writes,
the defined device/oracle outputs and canary preservation outside the written
first-plane region. Fifteen strict-profile, bus-error, timeout and extra-word
controls are included. The recorded run used source revision
`8011ff662f6a6877d0eac4e2e4a03ab3aededc0c`, Python 3.14.5, Icarus Verilog
13.0 (all 16 modes passed) and Verilator 5.048 (14 modes passed; the two X/Z
address tests are skipped because it is a two-state simulator). The fixed
testbench handshake seed is `0x3c4c9a31`. Verilator emitted 97 warning headers;
the complete compile log is preserved rather than suppressing or recasting the
warning inventory. Four fixture/source/layout contract tests also passed.
Reports under `build/convolution-3x3-valid-c4/` bind per-file source/fixture
hashes and retain simulator logs. These runs do not access the RK target or
FPGA; they do not establish full-top or physical qualification.
