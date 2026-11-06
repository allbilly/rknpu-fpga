# Frozen capture fixture: `conv_1x1_valid_c8_h5_w5_oc8`

Source: RK3588 Rocket run `conv-fp16-20261105T222300Z`, capture started
`2026-11-05T22:22:18Z`, completed successfully at `22:22:19Z`; Linux
6.18.24-current-rockchip64, `/dev/accel/accel0`. The capture records one
54-QWORD task, input DMA address `0x1000`, weight `0x2000`, and output `0x3000`.
These are the exact task BOs and patched command words used by the RTL test.

| File | Bytes | SHA-256 | Use |
|---|---:|---|---|
| `a.bin` | 800 | `fa1cfc610a9d473bbef852dac62bef6d63f67727b0d8a20587962b0418739c71` | Original packed input BO |
| `w.bin` | 256 | `52a1b39b6ef32d87bed51b67d32b67073f2aefae3fc96d265a0a82b6ba838418` | Original packed weight BO |
| `expected.bin` | 400 | `7a364a2c20910f0b00f4f522856009ed69d5a477ea4b9fdee5ac146193d2058c` | Donor NCHW FP16 oracle |
| `regcmd.bin` | 432 | `d2436a39835aac6c926b6ab0ed608a30b46f71616dbc0c8b56390b0cbbe51328` | Captured 54-word stream after only job-declared address patches |
| `out.bin` | 1600 | `82f8bdb91b780e54f6d90b1ea4281d01913f7561d688f0e5a75df89b5f604f0e` | Complete captured device output BO |

The original unpatched `regcmd.bin` hash is
`a66063b1df7be1c913ee9851a65270a0644a98312db640fbc58216a97855ac6c`.
The capture job patches only words 21/27/35 (CNA feature, CNA weight, DPU
destination), to the three addresses above. The fixture `regcmd.bin` is the
resulting actual raw command stream; no register or command is synthesized by
the RTL test.

Capture record: `capture.json` in the local
`build/rk3588-example-captures/results/conv-fp16-20261105T222300Z/board-run/`
tree. Its output hash/size and command stream hash/size agree with this frozen
fixture. Plan and geometry: [`docs/CONV_FIRST_CASE.md`](../../../../docs/CONV_FIRST_CASE.md)
and [`build/convolution-architecture/PLAN.md`](../../../../build/convolution-architecture/PLAN.md).

Only output plane 0 (400 bytes) is defined by the capture. The other 1200 bytes
are retained solely so the RTL check can compare the complete captured BO and
detect any write outside the supported plane; they are not a numeric oracle.
