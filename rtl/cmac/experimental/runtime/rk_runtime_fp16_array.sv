// SPDX-License-Identifier: MIT
// ADDITIVE EXPERIMENTAL COPY (task-13): frozen rk_cmac_fp16_array is NOT
// modified; this copy instantiates rk_runtime_fp16_cell (C=16 capable).
`timescale 1ns/1ps
// One RK3588 core's proposed FP16 geometry: C32 x K16 = 512 parallel
// products per accepted frame. This is an internal CSC->CMAC->CACC boundary,
// NOT a tensor-operation execution API or a replacement for raw RK commands.
//
// The cell is a three-leg pipeline (see rk_cmac_fp16_cell). This module owns the
// corresponding elastic frame pipe: a valid/tag chain of the same depth and the
// final out_groups/out_tag register, so a frame in flight always has a stable
// place to wait for the CACC. in_ready is the head of that chain, so no frame is
// dropped or duplicated under backpressure; the frame sequence and tags are
// unchanged (only the accept-to-out delay grew by two cycles, which the front's
// 24-144-cycle frame assembly and the CACC's one-group-per-two-cycles accept
// rate both absorb without a throughput change).
//
// Exactness and error semantics are unchanged:
//   * the result is the same 44-bit donor arithmetic for every input;
//   * an X/Z operand frame is rejected at the seam exactly as before;
//   * a frame whose donor row tag is not one of the nine legal sign tags sets
//     the sticky error and is never emitted.
module rk_runtime_fp16_array #(
    parameter int unsigned ATOMIC_C=16,ATOMIC_K=16,TAG_WIDTH=35
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
    logic configured,illegal_input;
    // Pipeline state: s1 = cell leg 1, s2 = cell leg 2, out_groups = leg 3.
    logic s1_valid,s2_valid;
    logic [TAG_WIDTH-1:0] s1_tag,s2_tag;
    logic s3_ready,s2_advance,s1_advance;
    logic s1_capture,s2_capture,s3_capture;
    initial if(ATOMIC_K==0||TAG_WIDTH==0) $fatal(1,"invalid CMAC dimensions");

    for (genvar k=0;k<ATOMIC_K;k=k+1) begin: kernels
        rk_runtime_fp16_cell #(.ATOMIC_C(ATOMIC_C)) cell_core(
            .clk,.rst_n,.data(in_data),
            .weight(in_weight[k*ATOMIC_C*16+:ATOMIC_C*16]),
            .data_mask(in_data_mask),
            .weight_mask(in_weight_mask[k*ATOMIC_C+:ATOMIC_C]),
            .stage1_en(s1_capture),.stage2_en(s2_capture),
            .result(groups[k*44+:44]),.invalid(invalid[k]));
    end

    // Elastic handshake: the last stage holds its result until out_ready, and
    // each upstream stage stalls only when the next one is full.
    assign s3_ready = !out_valid || out_ready;
    assign s2_advance = !s2_valid || s3_ready;
    assign s1_advance = !s1_valid || s2_advance;
    assign in_ready = rst_n && configured && !error && s1_advance;
    assign s1_capture = rst_n && !error && s1_advance;
    assign s2_capture = rst_n && !error && s2_advance;
    assign s3_capture = rst_n && !error && s3_ready;

    always @* begin
        illegal_input = 1'b0;
`ifndef SYNTHESIS
        // X/Z are simulator states, not electrical detectors; a frame whose
        // operands are not fully known is rejected rather than latched.
        if((^{in_data,in_weight,in_data_mask,in_weight_mask,in_tag})===1'bx)
            illegal_input = 1'b1;
`endif
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            configured<=0;out_valid<=0;out_groups<=0;out_tag<=0;error<=0;
            s1_valid<=0;s2_valid<=0;s1_tag<=0;s2_tag<=0;
        end else begin
            configured<=1;
            if(s1_capture) begin
                s1_valid<=in_valid;
                s1_tag<=in_tag;
            end
            if(s2_capture) begin
                s2_valid<=s1_valid;
                s2_tag<=s1_tag;
            end
            if(in_valid&&in_ready&&illegal_input) begin
                // Rejected at the seam: never enters the pipeline, never
                // emits, and the existing sticky-error behaviour is kept.
                error<=1'b1;out_valid<=1'b0;s1_valid<=0;s2_valid<=0;
            end else if(s3_capture) begin
                if(s2_valid&&(|invalid)) begin
                    // Illegal donor row tag: hard error, frame dropped.
                    error<=1'b1;out_valid<=1'b0;
                end else begin
                    out_valid<=s2_valid;
                    if(s2_valid) begin
                        out_groups<=groups;
                        out_tag<=s2_tag;
                    end
                end
            end
        end
    end
endmodule
