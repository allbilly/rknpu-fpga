// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact captured FP16 valid 3x3 C4/H11/W11 -> OC4/H5/W5 stride-2 profile.
// The wrapped engine selects this exact register template at elaboration; no
// runtime command field can widen the accepted geometry.
module rk_conv_3x3_stride2_c4_core #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        cmd_valid,
    output logic        cmd_ready,
    input  logic [63:0] cmd_data,
    input  logic        cmd_last,
    output logic        busy,
    output logic        acknowledged,
    output logic        frame_done,
    output logic        done,
    output logic        error,
    output logic [7:0]  error_code,
    output logic        mem_req_valid,
    input  logic        mem_req_ready,
    output logic        mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input  logic        mem_rsp_valid,
    output logic        mem_rsp_ready,
    input  logic [15:0] mem_rsp_rdata,
    input  logic        mem_rsp_error
);
    // Internal observation aliases are available to the focused testbench;
    // they are not part of the command or memory interface.
    wire frame_valid = exact_stride2_engine.front.frame_valid;
    wire frame_ready = exact_stride2_engine.frame_ready;
    wire [31:0] frame_output_address = exact_stride2_engine.frame_output_address;
    wire frame_first = exact_stride2_engine.frame_first;
    wire frame_last = exact_stride2_engine.frame_last;
    wire frame_last_output = exact_stride2_engine.frame_last_output;
    wire [511:0] frame_data = exact_stride2_engine.frame_data;
    wire [8191:0] frame_weight = exact_stride2_engine.frame_weight;
    wire [31:0] frame_data_mask = exact_stride2_engine.frame_data_mask;
    wire [511:0] frame_weight_mask = exact_stride2_engine.frame_weight_mask;

    rk_conv_3x3_valid_c4_core #(
        .STRIDE2(1'b1), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) exact_stride2_engine (.*);
endmodule
