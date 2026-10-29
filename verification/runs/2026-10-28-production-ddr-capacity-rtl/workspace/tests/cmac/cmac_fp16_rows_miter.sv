// SPDX-License-Identifier: MIT
// Formal boundary: original donor has entered its fixed FP16 mode.
// All 32 operand bits, all 16 shift codes and paired nz are unconstrained.
module cmac_fp16_rows_miter (
    input wire clk,rst_n,pair_nz,
    input wire [15:0] op_a,op_b,
    input wire [3:0] exp_sft,
    output wire mismatch,active
);
    wire [31:0] ref_a,ref_b,res_a,res_b;
    wire [7:0] ref_tag,res_tag;
    reg configured;
    always @(posedge clk or negedge rst_n)
        if(!rst_n) configured<=0;else configured<=1;
    NV_NVDLA_CMAC_CORE_MAC_mul original (
        .nvdla_core_clk(clk),.nvdla_core_rstn(rst_n),
        .cfg_is_fp16(1'b1),.cfg_is_int8(1'b0),.cfg_reg_en(1'b1),
        .op_a_dat(op_a),.op_b_dat(op_b),.op_a_nz({2{pair_nz}}),
        .op_b_nz({2{pair_nz}}),.op_a_pvld(1'b1),.op_b_pvld(1'b1),
        .exp_sft,.res_a(ref_a),.res_b(ref_b),.res_tag(ref_tag));
    rk_cmac_fp16_rows dut(.*);
    assign active=rst_n && configured;
    assign mismatch=active && ({res_a,res_b,res_tag}!={ref_a,ref_b,ref_tag});
endmodule
