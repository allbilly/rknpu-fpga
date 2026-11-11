// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact captured FP16 3x3 C4 task consuming its explicit packed 11x11 zero BO.
// No padding is generated here; the original input BO is read unchanged.
module rk_conv_3x3_pad1_zero_frame_c4_core #(
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
    wire frame_valid = exact_pad1_engine.front.frame_valid;
    wire frame_ready = exact_pad1_engine.frame_ready;
    wire [31:0] frame_output_address = exact_pad1_engine.frame_output_address;
    wire frame_first = exact_pad1_engine.frame_first;
    wire frame_last = exact_pad1_engine.frame_last;
    wire frame_last_output = exact_pad1_engine.frame_last_output;
    wire [511:0] frame_data = exact_pad1_engine.frame_data;
    wire [8191:0] frame_weight = exact_pad1_engine.frame_weight;
    wire [31:0] frame_data_mask = exact_pad1_engine.frame_data_mask;
    wire [511:0] frame_weight_mask = exact_pad1_engine.frame_weight_mask;

    rk_conv_3x3_valid_c4_core #(
        .PAD1_ZERO_FRAME(1'b1), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) exact_pad1_engine (.*);
endmodule
