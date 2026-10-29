// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// STAGED raw-command-to-operand stream. No MAC, output write or job completion.
// Future enclosing engine must hold downstream_busy through final write ack.
module rk_cmac_operand_front #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, rst_n,
    input logic cmd_valid,
    output logic cmd_ready,
    input logic [63:0] cmd_data,
    input logic downstream_busy,
    output logic busy, address_done, stream_done, error,
    output logic [7:0] error_code,
    output logic mem_req_valid,
    input logic mem_req_ready,
    output logic [31:0] mem_req_addr,
    input logic mem_rsp_valid,
    output logic mem_rsp_ready,
    input logic [15:0] mem_rsp_rdata,
    input logic mem_rsp_error,
    output logic operand_valid,
    input logic operand_ready,
    output logic [15:0] operand_input, operand_weight,
    output logic [31:0] operand_output_address, operand_row, operand_oc, operand_ic,
    output logic operand_first, operand_last, operand_last_output
);
    logic config_valid, config_ready, decode_error, walk_busy, walk_error, read_busy, read_error;
    logic [7:0] decode_error_code, read_error_code;
    logic [31:0] config_rows, config_input_channels, config_output_channels;
    logic [31:0] config_input_base, config_weight_base, config_output_base;
    logic pair_valid, pair_ready;
    logic [31:0] input_address, weight_address, output_address, row_index, output_channel, input_channel;
    logic first_product, last_product, last_output;

    rk_cmac_profile profile (
        .clk, .rst_n, .cmd_valid, .cmd_ready, .cmd_data,
        .engine_busy(walk_busy || read_busy || downstream_busy), .engine_error(walk_error || read_error),
        .config_valid, .config_ready, .config_rows, .config_input_channels, .config_output_channels,
        .config_input_base, .config_weight_base, .config_output_base,
        .error(decode_error), .error_code(decode_error_code)
    );
    rk_cmac_address addresses (
        .clk, .rst_n, .config_valid, .config_ready, .config_rows, .config_input_channels, .config_output_channels,
        .config_input_base, .config_weight_base, .config_output_base,
        .busy(walk_busy), .walk_done(address_done), .error(walk_error),
        .pair_valid, .pair_ready, .input_address, .weight_address, .output_address,
        .row_index, .output_channel, .input_channel, .first_product, .last_product, .last_output
    );
    rk_cmac_reader #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) reader (
        .clk, .rst_n, .pair_valid, .pair_ready, .input_address, .weight_address, .output_address,
        .row_index, .output_channel, .input_channel, .first_product, .last_product, .last_output,
        .busy(read_busy), .error(read_error), .error_code(read_error_code),
        .mem_req_valid, .mem_req_ready, .mem_req_addr, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata, .mem_rsp_error,
        .operand_valid, .operand_ready, .operand_input, .operand_weight,
        .operand_output_address, .operand_row, .operand_oc, .operand_ic,
        .operand_first, .operand_last, .operand_last_output
    );
    assign error = decode_error || walk_error || read_error;
    assign error_code = decode_error ? decode_error_code : read_error ? read_error_code : walk_error ? 8'd6 : 8'd0;
    assign busy = rst_n && !error && (config_valid || walk_busy || read_busy || downstream_busy);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) stream_done <= 0;
        else stream_done <= operand_valid && operand_ready && operand_last && operand_last_output;
    end
endmodule
