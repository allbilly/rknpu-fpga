// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Atomic K-kernel FP44 frame reduction. Each kernel owns a separate original
// NVDLA FP48 accumulator. This is an internal CMAC/CACC seam, not a host API.
// One reduction context per kernel; no claim of one-frame-per-cycle feedback.
module rk_cacc_fp16_array #(
    parameter int unsigned ATOMIC_K=16,TAG_WIDTH=33
) (
    input wire clk,rst_n,in_valid,
    output wire in_ready,
    input wire [ATOMIC_K*44-1:0] in_groups,
    input wire in_first,in_last,
    input wire [TAG_WIDTH-1:0] in_tag,
    output wire out_valid,
    input wire out_ready,
    output wire [ATOMIC_K*32-1:0] out_values,
    output wire [TAG_WIDTH-1:0] out_tag,
    input wire cancel,
    input wire [7:0] cancel_code,
    output wire busy,error,
    output wire [7:0] error_code
);
    wire [ATOMIC_K-1:0] lane_ready,lane_valid,lane_busy,lane_error;
    wire [ATOMIC_K*TAG_WIDTH-1:0] lane_tags;
    wire [ATOMIC_K*8-1:0] lane_codes;
    logic fault,disagree;
    logic [7:0] saved_code,normalized_cancel,child_code;
    wire all_ready=&lane_ready;
    wire all_valid=&lane_valid;
    wire issue=in_valid&&in_ready;
    wire retire=out_ready&&out_valid;
    initial if(ATOMIC_K==0||TAG_WIDTH==0) $fatal(1,"invalid CACC dimensions");
    always @* begin
        case(cancel_code)
            1,2,3,4,5,6,7,8:normalized_cancel=cancel_code;
            default:normalized_cancel=6;
        endcase
        child_code=6;
        for(integer k=ATOMIC_K-1;k>=0;k=k-1)
            if(lane_error[k]) child_code=lane_codes[k*8+:8];
        // All donors receive the same issue/final controls and have fixed
        // latency. A partial frame or divergent saved tag is an explicit fault.
        disagree=(|lane_valid)&&!all_valid;
        for(integer k=1;k<ATOMIC_K;k=k+1)
            if(all_valid&&lane_tags[k*TAG_WIDTH+:TAG_WIDTH]!=lane_tags[0+:TAG_WIDTH]) disagree=1;
    end
    assign error=rst_n&&(fault||cancel||(|lane_error)||disagree);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : cancel ? normalized_cancel :
                      (|lane_error) ? child_code : disagree ? 8'd6 : 8'd0;
    assign in_ready=rst_n&&!error&&all_ready;
    assign out_valid=rst_n&&!error&&all_valid;
    assign out_tag=lane_tags[0+:TAG_WIDTH];
    assign busy=rst_n&&!error&&(|lane_busy);
    for(genvar k=0;k<ATOMIC_K;k=k+1) begin: kernels
        rk_nvdla_cacc #(.TAG_WIDTH(TAG_WIDTH)) accumulator(
            .clk,.rst_n,.in_valid(issue),.in_ready(lane_ready[k]),
            .in_group(in_groups[k*44+:44]),.in_first,.in_last,.in_tag,
            .out_valid(lane_valid[k]),.out_ready(retire),
            .out_value(out_values[k*32+:32]),.out_tag(lane_tags[k*TAG_WIDTH+:TAG_WIDTH]),
            // No combinational aggregate-error feedback into child cancel.
            .cancel(cancel||fault),.cancel_code(fault ? saved_code : normalized_cancel),
            .busy(lane_busy[k]),.error(lane_error[k]),.error_code(lane_codes[k*8+:8]));
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin fault<=0;saved_code<=0;end
        else if(!fault&&error) begin fault<=1;saved_code<=error_code;end
    end
endmodule
