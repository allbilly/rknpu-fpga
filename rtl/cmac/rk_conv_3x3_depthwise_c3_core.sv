// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact captured FP16 depthwise 3x3 C3/H11/W28 -> OC3/H9/W26 task. Each of the
// three kernels reduces only its own input channel; the donor's
// depthwise_spatial_major weight BO is consumed unchanged. This is one exact
// capture, not general depthwise support.
module rk_conv_3x3_depthwise_c3_core #(
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
    wire frame_valid = depthwise_engine.front.frame_valid;
    wire frame_ready = depthwise_engine.frame_ready;
    wire [31:0] frame_output_address = depthwise_engine.front.frame_output_address;
    wire frame_first = depthwise_engine.front.frame_first;
    wire frame_last = depthwise_engine.front.frame_last;
    wire frame_last_output = depthwise_engine.front.frame_last_output;
    wire [511:0] frame_data = depthwise_engine.front.frame_data;
    wire [8191:0] frame_weight = depthwise_engine.front.frame_weight;
    wire [31:0] frame_data_mask = depthwise_engine.front.frame_data_mask;
    wire [511:0] frame_weight_mask = depthwise_engine.front.frame_weight_mask;

    rk_conv_3x3_valid_c4_core #(
        .DEPTHWISE_C3(1'b1), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) depthwise_engine (.*);
endmodule
