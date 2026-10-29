// NVDLA Open Source Project
// Copyright(c) 2016 - 2017 NVIDIA Corporation. Licensed under the
// NVDLA Open Hardware License; see rtl/vendor/nvdla/LICENSE.+// Derived from NV_NVDLA_CMAC_CORE_MAC_mul.v, nvdlav1 revision
// 8e06b1b9d85aab65b40d43d08eec5ea4681ff715.
`timescale 1ns/1ps
// EXPERIMENTAL: strict FP16 specialization of the donor's partial rows.
// Not wired into the candidate array. The caller must retain its configured
// warmup/ready gate: equivalence is claimed only after donor FP16 setup.
// Inputs are sign plus pre-shifted magnitude, NOT raw binary16 operands.
// Paired nz bits and permanently asserted operand-valid match the C32 cell.
// Preserve both carry-save rows BEFORE alignment; replacing them with a
// rounded/inferred product would change the donor's truncation behavior.
module rk_cmac_fp16_rows (
    input wire [15:0] op_a, op_b,
    input wire [3:0] exp_sft,
    input wire pair_nz,
    output wire [31:0] res_a, res_b,
    output wire [7:0] res_tag
);
    wire [16:0] codes = {1'b0, op_a[14:0], 1'b0};
    wire [16:0] selected [8];
    wire [7:0] inverted;
    wire [23:0] low_a, low_b, high_a, high_b;
    wire [31:0] row_a, row_b;
    wire [119:0] inputs_low, inputs_high;
    for (genvar i=0; i<8; i=i+1) begin: booth
        NV_NVDLA_CMAC_CORE_MAC_booth recode (
            .code(codes[2*i+:3]), .is_8bit(1'b0),
            .sign(op_a[15]^op_b[15]), .src_data({1'b0,op_b[14:0]}),
            .out_data(selected[i]), .out_inv(inverted[i]));
    end
    assign inputs_low = {
        {17'b0,inverted[3],6'b0},
        {1'b0,selected[3],1'b0,inverted[2],4'b0},
        {3'b0,selected[2],1'b0,inverted[1],2'b0},
        {5'b0,selected[1],1'b0,inverted[0]},
        {7'b0,selected[0]}};
    assign inputs_high = {
        {17'b0,inverted[7],6'b0},
        {1'b0,selected[7],1'b0,inverted[6],4'b0},
        {3'b0,selected[6],1'b0,inverted[5],2'b0},
        {5'b0,selected[5],1'b0,inverted[4]},
        {7'b0,selected[4]}};
    NV_DW02_tree #(5,24) low_tree (.INPUT(inputs_low),.OUT0(low_a),.OUT1(low_b));
    NV_DW02_tree #(5,24) high_tree (.INPUT(inputs_high),.OUT0(high_a),.OUT1(high_b));
    NV_DW02_tree #(4,32) final_tree (
        .INPUT({{high_b,8'b0},{high_a,8'b0},{8'b0,low_b},{8'b0,low_a}}),
        .OUT0(row_a),.OUT1(row_b));
    assign res_a = (!pair_nz || exp_sft[3]) ? 32'b0 : row_a >> {exp_sft[2:0],2'b0};
    assign res_b = (!pair_nz || exp_sft[3]) ? 32'b0 : row_b >> {exp_sft[2:0],2'b0};
    assign res_tag = (!pair_nz || exp_sft[3]) ? 8'b0 : 8'hf0 >> exp_sft[2:0];
endmodule
