// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Candidate INTERNAL address-only leaf. Not an executable NPU/tensor interface.
// Future raw-command validation must supply physical ai/ao, never logical K/N.
// No arithmetic, memory requests, CBUF implementation or job completion here.
module rk_cmac_address (
    input logic clk, rst_n,
    input logic config_valid,
    output logic config_ready,
    input logic [31:0] config_rows, config_input_channels, config_output_channels,
    input logic [31:0] config_input_base, config_weight_base, config_output_base,
    output logic busy, walk_done, error,
    output logic pair_valid,
    input logic pair_ready,
    output logic [31:0] input_address, weight_address, output_address,
    output logic [31:0] row_index, output_channel, input_channel,
    output logic first_product, last_product, last_output
);
    logic [31:0] rows, ai, ao, weight_origin;
    logic [31:0] input_row_base, output_row_base, weight_block_base, weight_output_base;
    logic [63:0] input_bytes, weight_bytes, output_bytes;
    logic [63:0] input_end, weight_end, output_end;
    logic valid_config;

    // Full physical BO ranges, including output holes, must be addressable.
    // Limits follow the pinned backend's _cmac_shape_supported contract.
    assign input_bytes = {53'b0, config_rows[10:0]} * {51'b0, config_input_channels[12:0]} * 64'd2;
    assign weight_bytes = {50'b0, config_output_channels[13:0]} * {51'b0, config_input_channels[12:0]} * 64'd2;
    assign output_bytes = {53'b0, config_rows[10:0]} * {50'b0, config_output_channels[13:0]} * 64'd4;
    assign input_end = {32'b0, config_input_base} + input_bytes;
    assign weight_end = {32'b0, config_weight_base} + weight_bytes;
    assign output_end = {32'b0, config_output_base} + output_bytes;
    assign valid_config = config_rows > 0 && config_rows <= 2047 &&
            config_input_channels >= 32 && config_input_channels <= 4096 &&
            config_output_channels >= 32 && config_output_channels <= 16383 &&
            config_input_channels[4:0] == 0 && config_output_channels[4:0] == 0 &&
            (config_rows == 1 || config_input_channels <= 384) &&
            input_bytes <= 327680 && weight_bytes <= 360448 &&
            config_input_base[3:0] == 0 && config_weight_base[3:0] == 0 && config_output_base[3:0] == 0 &&
            input_end <= 64'h100000000 && weight_end <= 64'h100000000 && output_end <= 64'h100000000 &&
            !(output_end > {32'b0, config_input_base} && input_end > {32'b0, config_output_base}) &&
            !(output_end > {32'b0, config_weight_base} && weight_end > {32'b0, config_output_base});

    assign config_ready = rst_n && !busy && !error;
    assign pair_valid = rst_n && busy;
    assign first_product = input_channel == 0;
    assign last_product = input_channel == ai - 1;
    assign last_output = row_index == rows - 1 && output_channel == ao - 1;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy <= 0;
            walk_done <= 0;
            error <= 0;
            rows <= 0;
            ai <= 0;
            ao <= 0;
            weight_origin <= 0;
            input_row_base <= 0;
            output_row_base <= 0;
            weight_block_base <= 0;
            weight_output_base <= 0;
            input_address <= 0;
            weight_address <= 0;
            output_address <= 0;
            row_index <= 0;
            output_channel <= 0;
            input_channel <= 0;
        end else begin
            walk_done <= 0;
            if (config_valid && config_ready) begin
                if (valid_config) begin
                    busy <= 1;
                    rows <= config_rows;
                    ai <= config_input_channels;
                    ao <= config_output_channels;
                    weight_origin <= config_weight_base;
                    input_row_base <= config_input_base;
                    output_row_base <= config_output_base;
                    weight_block_base <= config_weight_base;
                    weight_output_base <= config_weight_base;
                    input_address <= config_input_base;
                    weight_address <= config_weight_base;
                    output_address <= config_output_base;
                    row_index <= 0;
                    output_channel <= 0;
                    input_channel <= 0;
                end else error <= 1;
            end
            if (pair_valid && pair_ready) begin
                if (!last_product) begin
                    input_channel <= input_channel + 1;
                    input_address <= input_address + 2;
                    // IC32 -> next 16x32 panel: 1024 - 31*2 bytes.
                    weight_address <= weight_address + (input_channel[4:0] == 31 ? 32'd962 : 32'd2);
                end else if (last_output) begin
                    busy <= 0;
                    walk_done <= 1;
                end else begin
                    input_channel <= 0;
                    if (output_channel != ao - 1) begin
                        output_channel <= output_channel + 1;
                        input_address <= input_row_base;
                        if (output_channel[3:0] == 15) begin
                            weight_block_base <= weight_block_base + (ai << 5);
                            weight_output_base <= weight_block_base + (ai << 5);
                            weight_address <= weight_block_base + (ai << 5);
                            output_address <= output_address + 34;
                        end else begin
                            weight_output_base <= weight_output_base + 64;
                            weight_address <= weight_output_base + 64;
                            output_address <= output_address + 2;
                        end
                    end else begin
                        output_channel <= 0;
                        row_index <= row_index + 1;
                        input_row_base <= input_row_base + (ai << 1);
                        input_address <= input_row_base + (ai << 1);
                        output_row_base <= output_row_base + (ao << 2);
                        output_address <= output_row_base + (ao << 2);
                        weight_block_base <= weight_origin;
                        weight_output_base <= weight_origin;
                        weight_address <= weight_origin;
                    end
                end
            end
        end
    end
endmodule
