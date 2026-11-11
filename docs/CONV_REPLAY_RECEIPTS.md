# 2026-11-07 convolution replay receipts

One row per exact profile and simulator leg from the `conv-3x3-*-test`
targets. Every row passed all 16 Icarus modes / 14 two-state Verilator
modes for the applicable testbench, with 15 negative controls.

Tool and environment for every row: Icarus Verilog 13.0 (stable) as compiler
and runtime, or Verilator 5.048 2026-04-26; Python 3.14.5; source revision
`8011ff662f6a6877d0eac4e2e4a03ab3aededc0c`; fixed testbench seed
`0x3c4c9a31`; no hardware accessed and no bitstream emitted.

Traffic was independently recomputed from each fixture's declared
`layout.weight_bytes` and `shape.input_channels` and matched every receipt
exactly (reads / writes / frames):

| case | expected | Icarus | Verilator |
|---|---|---|---|
| valid C4 | 900 / 392 / 441 | match | match |
| stride-2 C4 | 1060 / 200 / 225 | match | match |
| pad-1 zero frame | 1060 / 648 / 729 | match | match |
| grouped C2 task0 | 626 / 72 / 81 | match | match |
| grouped C2 task1 | 626 / 72 / 81 | match | match |
| split-OC task0 | 2448 / 392 / 441 | match | match |
| split-OC task1 | 2448 / 392 / 441 | match | match |
| depthwise C3 | 996 / 1872 / 2106 | match | match |

`build/` receipts are workspace-local and excluded from source control.

| case | Icarus receipt | Verilator receipt |
|---|---|---|
| `conv_3x3_valid_c4_h9_w9_oc4` | `build/convolution-3x3-valid-c4/iverilog-20261107T125216Z/report.json` | `build/convolution-3x3-valid-c4/verilator-20261107T125216Z/report.json` |
| `conv_3x3_stride2_c4_h11_w11_oc4` | `build/convolution-3x3-stride2-c4/iverilog-20261107T125755Z/report.json` | `build/convolution-3x3-stride2-c4/verilator-20261107T125755Z/report.json` |
| `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` | `build/convolution-3x3-pad1-zero-frame-c4/iverilog-20261107T130325Z/report.json` | `build/convolution-3x3-pad1-zero-frame-c4/verilator-20261107T130325Z/report.json` |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2_task0` | `build/convolution-3x3-grouped-c2/iverilog-20261107T131005Z/report.json` | `build/convolution-3x3-grouped-c2/verilator-20261107T131005Z/report.json` |
| `conv_grouped_3x3_c4_h5_w5_oc8_g2_task1` | `build/convolution-3x3-grouped-c2/iverilog-20261107T131333Z/report.json` | `build/convolution-3x3-grouped-c2/verilator-20261107T131333Z/report.json` |
| `conv_splitoc_3x3_c16_h9_w9_oc16_task0` | `build/convolution-3x3-splitoc-c16/iverilog-20261107T131701Z/report.json` | `build/convolution-3x3-splitoc-c16/verilator-20261107T131701Z/report.json` |
| `conv_splitoc_3x3_c16_h9_w9_oc16_task1` | `build/convolution-3x3-splitoc-c16/iverilog-20261107T133042Z/report.json` | `build/convolution-3x3-splitoc-c16/verilator-20261107T133042Z/report.json` |
| `conv_depthwise_3x3_c3_h11_w28_oc3` | `build/convolution-3x3-depthwise-c3/iverilog-20261107T134312Z/report.json` | `build/convolution-3x3-depthwise-c3/verilator-20261107T134312Z/report.json` |
