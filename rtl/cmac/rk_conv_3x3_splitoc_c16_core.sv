// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact captured FP16 split-OC C16/H9/W9 -> OC8/H7/W7 task. The wrapped engine
// selects this exact register template at elaboration; no runtime command
// field can widen the accepted geometry. Both promoted group tasks share the
// same command words and differ only in their operand/output BOs.
module rk_conv_3x3_splitoc_c16_core #(
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
    wire frame_valid = splitoc_engine.front.frame_valid;
    wire frame_ready = splitoc_engine.frame_ready;
    wire [31:0] frame_output_address = splitoc_engine.front.frame_output_address;
    wire frame_first = splitoc_engine.front.frame_first;
    wire frame_last = splitoc_engine.front.frame_last;
    wire frame_last_output = splitoc_engine.front.frame_last_output;
    wire [511:0] frame_data = splitoc_engine.front.frame_data;
    wire [8191:0] frame_weight = splitoc_engine.front.frame_weight;
    wire [31:0] frame_data_mask = splitoc_engine.front.frame_data_mask;
    wire [511:0] frame_weight_mask = splitoc_engine.front.frame_weight_mask;

    rk_conv_3x3_valid_c4_core #(
        .SPLIT_OC_C16(1'b1), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) splitoc_engine (.*);
endmodule
