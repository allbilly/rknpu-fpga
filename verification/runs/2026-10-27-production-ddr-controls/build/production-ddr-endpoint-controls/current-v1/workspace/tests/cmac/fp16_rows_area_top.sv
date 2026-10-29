// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Area-only comparison with identical external operand/shift/mask ports.
// STATIC_MODE=1 has the documented post-configuration equivalence contract;
// its unused clock/reset ports do not imply reset-cycle equivalence.
module fp16_rows_area_top #(parameter integer STATIC_MODE=0) (
    input wire clk,rst_n,pair_nz,
    input wire [15:0] op_a,op_b,
    input wire [3:0] exp_sft,
    output wire [31:0] res_a,res_b,
    output wire [7:0] res_tag
);
    initial if(STATIC_MODE!=0 && STATIC_MODE!=1) $fatal(1,"invalid area mode");
    if(STATIC_MODE==0) begin: baseline
        NV_NVDLA_CMAC_CORE_MAC_mul original (
            .nvdla_core_clk(clk),.nvdla_core_rstn(rst_n),
            .cfg_is_fp16(1'b1),.cfg_is_int8(1'b0),.cfg_reg_en(1'b1),
            .op_a_dat(op_a),.op_b_dat(op_b),.op_a_nz({2{pair_nz}}),
            .op_b_nz({2{pair_nz}}),.op_a_pvld(1'b1),.op_b_pvld(1'b1),
            .exp_sft,.res_a,.res_b,.res_tag);
    end else begin: specialized
        rk_cmac_fp16_rows fixed_rows(.op_a,.op_b,.pair_nz,.exp_sft,.res_a,.res_b,.res_tag);
    end
endmodule
