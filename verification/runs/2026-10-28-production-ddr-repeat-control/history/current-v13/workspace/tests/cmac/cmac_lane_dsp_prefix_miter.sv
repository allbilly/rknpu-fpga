// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module cmac_lane_dsp_miter (
    input wire [15:0] op_a, op_b,
    input wire [3:0] exp_sft,
    input wire pair_nz,
    output wire [31:0] reference_lane, actual_lane,
    output wire [7:0] reference_tag, actual_tag,
    output wire [39:0] difference,
    output wire mismatch
);
    rk_cmac_fp16_lane_dsp reference (.op_a, .op_b, .exp_sft, .pair_nz,
        .lane_sum(reference_lane), .res_tag(reference_tag));
    rk_cmac_fp16_lane_dsp_prefix actual (.op_a, .op_b, .exp_sft, .pair_nz,
        .lane_sum(actual_lane), .res_tag(actual_tag));
    assign difference = {reference_lane ^ actual_lane, reference_tag ^ actual_tag};
    assign mismatch = |difference;
endmodule
