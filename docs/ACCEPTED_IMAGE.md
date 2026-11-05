# Accepted FPGA image (SYS-reset profile)

This is the latest physically accepted bitstream in the workspace. It is stored
in-tree at the user's explicit request; other build artifacts remain ignored.

| Field | Value |
|---|---|
| Bitstream | `build/framework-factored-sys-reset-v1/emission/full512-sys-reset.bit` |
| SHA-256 | `415ab79f582a20dde0f6b8aa300b38e3b4e15a182ed2e4242e398a7349f869b7` |
| Bytes | 18,735,214 |
| Source tag | `b0fe4374` (not asserted to be a Git commit) |
| Top | `ypcb_ddr_dual_top` |
| Part | `xc7k480tffg1156-2` |
| Routed timing | setup WNS +0.001 ns, hold WHS +0.051 ns, pulse WPWS +0.264 ns, zero failing endpoints |
| Utilisation | 292,430 LUTs, 66,506 FFs, 516 DSPs |
| Programming | volatile only; no flash written |

Physical evidence on this exact image:

- one SYS START/ACK, attempts and epoch 0→1, post-reset raw K65/SUB(9) PASS;
- full32 TinyStories PASS without a second reset or reprogramming:
  32 positions, 1,152 projections, 7,424 raw jobs, 11,136 tasks;
- output text: `Once upon a time, there was a little girl named Lily. She loved
  to play outside in the park. One`.

Receipts are preserved next to the image and under
`build/fpga-bringup/framework-factored-sys-reset-prep-v1/` and
`build/fpga-bringup/framework-factored-sys-reset-tinystories-prep-v1/`.

**Scope limit:** this image predates the 2026-11-06 MAX/special-value RTL
change (commit `ed41392`). It does not contain FP16 MAX or the captured
`0x7c01` NaN policy. A fresh route, timing closure, image audit and physical
run are required before claiming those features on hardware. No board
programming or flash action is implied by this file.
