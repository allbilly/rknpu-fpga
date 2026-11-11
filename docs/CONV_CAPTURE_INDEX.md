# Captured convolution profile index

This page lists every RK3588 convolution capture that currently has an exact
RTL profile and replay, plus the cases that remain blocked. Each row is one
pinned job, not a general shape claim.

## Exact profiles with replay evidence

| Profile selector | Case | Shape | QWORDs | Status |
|---|---|---|---:|---|
| 1×1 C8 (first case) | `conv_1x1_valid_c8_h5_w5_oc8` | C8 5x5 k1x1 → OC8 5x5 | 54 | dual-simulator sibling bench |
| `VALID` | `conv_3x3_valid_c4_h9_w9_oc4` | C4 9x9 k3x3 → OC4 7x7, s1 | 54 | Icarus + Verilator |
| `STRIDE2` | `conv_3x3_stride2_c4_h11_w11_oc4` | C4 11x11 k3x3 → OC4 5x5, s2 | 54 | Icarus + Verilator |
| `PAD1_ZERO_FRAME` | `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` | C4 9×9 zero frame → OC4 9x9 | 54 | Icarus + Verilator |
| `GROUPED_C2` | `conv_grouped_3x3_c4_h5_w5_oc8_g2_task0` | C2 5x5 k3x3 → OC4 3x3 | 54 | Icarus + Verilator |
| `GROUPED_C2_TASK1` | `conv_grouped_3x3_c4_h5_w5_oc8_g2_task1` | C2 5x5 k3x3 → OC4 3x3 | 54 | Icarus + Verilator |
| `SPLIT_OC_C16` | `conv_splitoc_3x3_c16_h9_w9_oc16_task0` | C16 9x9 k3x3 → OC8 7x7 | 54 | Icarus + Verilator |
| `SPLIT_OC_C16_TASK1` | `conv_splitoc_3x3_c16_h9_w9_oc16_task1` | C16 9x9 k3x3 → OC8 7x7 | 54 | Icarus + Verilator |
| `DEPTHWISE_C3` | `conv_depthwise_3x3_c3_h11_w28_oc3` | C3 11×28 k3x3 depthwise → OC3 9×26 | 54 | Icarus + Verilator |

All nine profiles of the `conv-fp16` READY set now have a pinned fixture under
`tests/conv/fixtures/`, a contract test, and a replay path that passes in **both**
Icarus Verilog 13.0 and Verilator 5.048 (see
[`CONV_REPLAY_RECEIPTS.md`](CONV_REPLAY_RECEIPTS.md) for the exact receipts). The register
tables are emitted from those fixtures by `tools/conv/gen_conv_profiles.py`
into `rtl/cmac/rk_conv_3x3_profiles.svh`, and `make generated-check` fails if
the header drifts from the captures.

## Blocked cases, and why

| Case | Blocker | Evidence |
|---|---|---|
| `conv_grouped_3x3_c4_h5_w5_oc8_g2` | Rocket executed only task 0; task 1 output BO all zero | promoted one-task cases are the runnable form |
| `conv_splitoc_3x3_c16_h9_w9_oc16` | Same multi-task defect | promoted one-task cases are runnable |
| `conv_tiles_vendor_abi_blocked` | vendor `DRM_IOCTL_RKNPU_*` ABI, no Rocket path | `conv_tiles.py` |
| `conv_3x3_pad_register_fp16_blocked` | no Rocket-capable FP16 builder emits `CNA_PAD_CON0` | `conv_new_clean.py` comments it out; `conv_mesa_fp16.py` emits it with uint8 semantics |
| `conv_split_k_reduction_blocked` | no accumulation contract; tile offsets are zero | `conv_0522.py` |

Blocked cases are blocked by **submission/register semantics**, not by a
missing spatial geometry. The explicit-zero-frame case is a valid 3×3
convolution over a host-packed border, which is why it is runnable while the
true pad-register case is not.

## What is still missing for FPGA execution

Nothing in this index is connected to an AXI/top endpoint, and no bitstream or
board run backs any of it. The descriptor wrapper `rk_conv_3x3_c4_dma` covers
the three C4 profiles; the grouped, split-OC and depthwise cores are currently
raw-stream endpoints only. See
[`CONV_SPATIAL_3X3_C4_DMA.md`](CONV_SPATIAL_3X3_C4_DMA.md) for the wrapper
contract and its one-shot-then-rearm lifecycle.
