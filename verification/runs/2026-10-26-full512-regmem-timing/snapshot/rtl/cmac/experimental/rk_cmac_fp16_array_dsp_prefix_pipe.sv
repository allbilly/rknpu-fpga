// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Separate two-stage CMAC timing candidate, retaining C32/K16=512 products.
// One frame/cycle when unstalled; global stall preserves both tagged stages.
// busy includes the newly registered preparation stage, before out_valid.
module rk_cmac_fp16_array_dsp_prefix_pipe #(
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
    output logic error,
    output wire busy
);
    wire [ATOMIC_K*44-1:0] groups;
    wire [ATOMIC_K-1:0] invalid;
    logic configured,prepared_valid;
    logic [TAG_WIDTH-1:0] prepared_tag;
    wire advance=!out_valid||out_ready;
    wire accept=in_valid&&in_ready;
`ifndef SYNTHESIS
    wire input_legal=(^{in_data,in_weight,in_data_mask,in_weight_mask,in_tag})!==1'bx;
`else
    wire input_legal=1'b1;
`endif
    wire capture=accept&&input_legal;
    initial if(ATOMIC_K==0||TAG_WIDTH==0)$fatal(1,"invalid CMAC dimensions");
    assign in_ready=rst_n&&configured&&!error&&advance;
    assign busy=rst_n&&!error&&(prepared_valid||out_valid);
    for(genvar k=0;k<ATOMIC_K;k=k+1)begin: kernels
        rk_cmac_fp16_cell_dsp_prefix_pipe #(.ATOMIC_C(ATOMIC_C)) cell_core(
            .clk,.capture,.data(in_data),
            .weight(in_weight[k*ATOMIC_C*16+:ATOMIC_C*16]),
            .data_mask(in_data_mask),.weight_mask(in_weight_mask[k*ATOMIC_C+:ATOMIC_C]),
            .result(groups[k*44+:44]),.invalid(invalid[k]));
    end
    always_ff @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            configured<=0;prepared_valid<=0;prepared_tag<=0;
            out_valid<=0;out_groups<=0;out_tag<=0;error<=0;
        end else begin
            configured<=1;
            if(!error&&advance)begin
                if((accept&&!input_legal)||(prepared_valid&&((|invalid)!==1'b0)))begin
                    error<=1;prepared_valid<=0;out_valid<=0;
                end else begin
                    out_valid<=prepared_valid;
                    if(prepared_valid)begin out_groups<=groups;out_tag<=prepared_tag;end
                    prepared_valid<=accept;
                    if(accept)prepared_tag<=in_tag;
                end
            end
        end
    end
endmodule
