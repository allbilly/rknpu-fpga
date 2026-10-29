// Separate timing candidate: all512 products retained; no FPGA acceptance.
// EXPERIMENTAL prefix-carry variant; no array numerical or FPGA acceptance.
// EXPERIMENTAL: compensated DSP lanes; no promotion or FPGA acceptance.
// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One RK3588 core's proposed FP16 geometry: C32 x K16 = 512 parallel
// products per accepted frame. This is an internal CSC->CMAC->CACC boundary,
// NOT a tensor-operation execution API or a replacement for raw RK commands.
module rk_cmac_fp16_array_dsp_prefix_balanced_max #(
    parameter int unsigned ATOMIC_C=32,ATOMIC_K=16,TAG_WIDTH=35
) (
    input wire clk,rst_n,in_valid,
    output wire in_ready,
    input wire [ATOMIC_C*16-1:0] in_data,
    input wire [ATOMIC_K*ATOMIC_C*16-1:0] in_weight,
    input wire [ATOMIC_C-1:0] in_data_mask,
    input wire [ATOMIC_K*ATOMIC_C-1:0] in_weight_mask,
    input wire [TAG_WIDTH-1:0] in_tag,
    output logic out_valid,
    input wire out_ready,
    output logic [ATOMIC_K*44-1:0] out_groups,
    output logic [TAG_WIDTH-1:0] out_tag,
    output logic error
);
    wire [ATOMIC_K*44-1:0] groups;
    wire [ATOMIC_K-1:0] invalid;
    logic configured,legal;
    initial if(ATOMIC_K==0||TAG_WIDTH==0) $fatal(1,"invalid CMAC dimensions");
    for(genvar k=0;k<ATOMIC_K;k=k+1) begin: kernels
        rk_cmac_fp16_cell_dsp_prefix_balanced_max #(.ATOMIC_C(ATOMIC_C)) cell_core(
            .data(in_data),.weight(in_weight[k*ATOMIC_C*16+:ATOMIC_C*16]),
            .data_mask(in_data_mask),.weight_mask(in_weight_mask[k*ATOMIC_C+:ATOMIC_C]),
            .result(groups[k*44+:44]),.invalid(invalid[k]));
    end
    assign in_ready=rst_n&&configured&&!error&&(!out_valid||out_ready);
    always @* begin
        legal=!(|invalid);
`ifndef SYNTHESIS
        if((^{in_data,in_weight,in_data_mask,in_weight_mask,in_tag})===1'bx) legal=0;
`endif
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin configured<=0;out_valid<=0;out_groups<=0;out_tag<=0;error<=0;end
        else begin
            configured<=1;
            if(out_valid&&out_ready) out_valid<=0;
            if(in_valid&&in_ready) begin
                if(!legal) begin error<=1;out_valid<=0;end
                else begin out_groups<=groups;out_tag<=in_tag;out_valid<=1;end
            end
        end
    end
endmodule
