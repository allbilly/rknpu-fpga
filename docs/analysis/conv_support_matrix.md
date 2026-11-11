# Convolution support matrix (generated from capture manifests)

Workspace-local working data derived from `build/rk3588-example-captures/*`
and `tests/conv/fixtures/`. It is not a device capture record.

## conv-fp16: READY 9, BLOCKED 5, total 14

| case | status | shape | stride | groups | QWORDs | fixture | note |
|---|---|---|---|---|---|---|---|
| `conv_1x1_valid_c8_h5_w5_oc8` | READY | C8 5x5 k1x1 -> OC8 5x5 | 1 | 1 | ? | no |  |
| `conv_3x3_valid_c4_h9_w9_oc4` | READY | C4 9x9 k3x3 -> OC4 7x7 | 1 | 1 | ? | yes |  |
| `conv_3x3_stride2_c4_h11_w11_oc4` | READY | C4 11x11 k3x3 -> OC4 5x5 | 2 | 1 | ? | yes |  |
| `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` | READY | C4 9x9 k3x3 -> OC4 9x9 | 1 | 1 | ? | yes | explicit-zero-frame |
| `conv_depthwise_3x3_c3_h11_w28_oc3` | READY | C3 11x28 k3x3 -> OC3 9x26 | 1 | 3 | ? | no |  |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2_task0` | READY | C2 5x5 k3x3 -> OC4 3x3 | 1 | 1 | 54 | yes |  |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2_task1` | READY | C2 5x5 k3x3 -> OC4 3x3 | 1 | 1 | 54 | yes |  |
| `conv_splitoc_3x3_c16_h9_w9_oc16_task0` | READY | C16 9x9 k3x3 -> OC8 7x7 | 1 | 1 | 54 | yes |  |
| `conv_splitoc_3x3_c16_h9_w9_oc16_task1` | READY | C16 9x9 k3x3 -> OC8 7x7 | 1 | 1 | 54 | yes |  |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2` | BLOCKED | C4 5x5 k3x3 -> OC8 3x3 | 1 | 2 | ? | no | blocked |
| `conv_splitoc_3x3_c16_h9_w9_oc16` | BLOCKED | C16 9x9 k3x3 -> OC16 7x7 | 1 | 1 | ? | no | blocked |
| `conv_tiles_vendor_abi_blocked` | BLOCKED | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no | blocked |
| `conv_3x3_pad_register_fp16_blocked` | BLOCKED | C4 9x9 k3x3 -> OC4 ?x? | 1 | 1 | ? | no | blocked |
| `conv_split_k_reduction_blocked` | BLOCKED | C16 9x9 k3x3 -> OC16 ?x? | 1 | 1 | ? | no | blocked |

## conv-gemm-vendor: READY 10, BLOCKED 3, total 13

| case | status | shape | stride | groups | QWORDs | fixture | note |
|---|---|---|---|---|---|---|---|
| `gemm_m2_n2_k1` | READY | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no |  |
| `gemm_m1_n16_k32` | READY | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no |  |
| `gemm_m2_n16_k32` | READY | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no |  |
| `gemm_m4_n32_k64` | READY | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no |  |
| `conv_1x1_c1_oc6_h4w4` | READY | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no |  |
| `conv_grouped_3x3_c4_oc4_g2_h5w5` | READY | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no |  |
| `conv_legacy_3x3_c4_oc4_h9w9` | READY | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no |  |
| `conv_depthwise_3x3_c3_oc3_h11w28` | BLOCKED | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no | MULTITASK_ROCKET_JOB_UNSUPPORTED: Rocket board execution completes only the first task of a two-task job; task 1 alone passes exactly. The source double submit is split into _task0 and _task1 one-task cases. |
| `conv_depthwise_3x3_c3_oc3_h11w28_task0` | READY | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no |  |
| `conv_depthwise_3x3_c3_oc3_h11w28_task1` | READY | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no |  |
| `conv_py_3x3_c32_oc128_h14w14_fullsetup` | READY | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no |  |
| `conv_byk_c160_h14w14_oc320_k3x3` | BLOCKED | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no | Vendor BY_K conv path uses explicit multi-core task distribution and a multi-task PC chain. Rocket has no core_mask/subcore_task fields and no bundle patch kind for the runtime regcmd address in PC_BASE_ADDRESS. |
| `conv_h40_c160_h40w40_oc320_k3x3` | BLOCKED | C? ?x? k?x? -> OC? ?x? | ? | ? | ? | no | Vendor H40 spatial BY_Y conv path distributes six tasks over three cores and uses 17 PC-chain rows. Rocket cannot express the vendor core_mask/subcore_task split, and the PC_BASE_ADDRESS rows require runtime regcmd-address patching that the bundle schema does not have. |

## conv-simple: READY 7, BLOCKED 5, total 12

| case | status | shape | stride | groups | QWORDs | fixture | note |
|---|---|---|---|---|---|---|---|
| `conv_simple_fp16_1x1_c4_h8_w8_oc16` | READY | C4 8x8 k1x1 -> OC16 ?x? | 1 | 1 | ? | no |  |
| `conv_simple_fp16_3x3_c4_h8_w8_oc16` | READY | C4 8x8 k3x3 -> OC16 ?x? | 1 | 1 | ? | no |  |
| `conv_simple_fp16_5x5_c4_h8_w8_oc16` | READY | C4 8x8 k5x5 -> OC16 ?x? | 1 | 1 | ? | no |  |
| `conv_simple_fp16_1x1_c32_h8_w8_oc32` | READY | C32 8x8 k1x1 -> OC32 ?x? | 1 | 1 | ? | no |  |
| `conv_simple_fp16_3x3_c16_h8_w8_oc32` | READY | C16 8x8 k3x3 -> OC32 ?x? | 1 | 1 | ? | no |  |
| `simple_conv_int8_5x5_c8_h8_w8_oc32` | READY | C8 8x8 k5x5 -> OC32 ?x? | 1 | 1 | ? | no |  |
| `simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64` | READY | C64 8x8 k3x3 -> OC64 ?x? | 1 | 64 | ? | no |  |
| `conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2` | BLOCKED | C8 8x8 k3x3 -> OC16 ?x? | 2 | 1 | ? | no | blocked |
| `conv_simple_fp16_3x3_c8_h8_w8_oc16_samepad` | BLOCKED | C8 8x8 k3x3 -> OC16 ?x? | 1 | 1 | ? | no | blocked |
| `conv_simple_fp16_3x3_c8_h8_w8_oc16_unpadded_pack` | BLOCKED | C8 8x8 k3x3 -> OC16 ?x? | 1 | 1 | ? | no | blocked |
| `conv_simple_fp16_grouped_3x3_c8_h8_w8_oc8_g2` | BLOCKED | C8 8x8 k3x3 -> OC8 ?x? | 1 | 2 | ? | no | blocked |
| `simple_conv_int8_addition_c8_h8_w8_oc32` | BLOCKED | C8 8x8 k3x3 -> OC32 ?x? | 1 | 1 | ? | no | blocked |

## Exact-profile RTL coverage

| profile selector | REAL_C | REAL_K | ALIGN_C | geometry | frames/atom |
|---|---|---|---|---|---|
| `VALID` (valid C4 stride-1) | 4 | 4 | 16 | 9x9 -> 7x7 | 9 |
| `STRIDE2` (valid C4 stride-2) | 4 | 4 | 16 | 11x11 -> 5x5 | 9 |
| `PAD1_ZERO_FRAME` (explicit zero frame) | 4 | 4 | 16 | 11x11 -> 9x9 | 9 |
| `GROUPED_C2` (promoted grouped task) | 2 | 4 | 16 | 5x5 -> 3x3 | 9 |
| `SPLIT_OC_C16` (promoted split-OC task) | 16 | 8 | 16 | 9x9 -> 7x7 | 9 |
| `DEPTHWISE_C3` (captured depthwise, groups=3) | 3 | 3 | 8 | 11x28 -> 9x26 | 9 |

The six profiles share one parameterized front/core chain. Blocked parent cases
are blocked by Rocket multi-task behaviour (`MULTITASK_ROCKET_JOB_UNSUPPORTED`)
or by format (vendor ABI, pad register, split-K), not by a missing spatial
geometry. `conv-gemm-vendor` and `conv-simple` families report shape fields our
families' manifests do not carry; their support requires GEMM/1x1/k5x5/int8
paths that are outside the current 3x3 FP16 slice.

conv-fp16 now has all nine READY cases covered by an exact profile: the
1x1 C8 case (`CONV_FIRST_CASE`), four C4 spatial cases, two promoted grouped
slices, two promoted split-OC slices and the depthwise case. The remaining
conv-fp16 BLOCKED entries are the two multi-task parents plus the three
format blockers (vendor ABI, pad register, split-K).
