// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Raw terminal RK CMAC words -> tagged exact FP16 products, NOT GEMM results.
// No accumulation, writes, finite DMA framing, or completed-job indication.
// A fault cancels buffered products; jointly reset this path and memory.
module rk_cmac_product_front #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, rst_n,
    input logic cmd_valid,
    output logic cmd_ready,
    input logic [63:0] cmd_data,
    input logic downstream_busy,
    output logic busy, address_done, operand_done, product_done, error,
    output logic [7:0] error_code,
    output logic mem_req_valid,
    input logic mem_req_ready,
    output logic [31:0] mem_req_addr,
    input logic mem_rsp_valid,
    output logic mem_rsp_ready,
    input logic [15:0] mem_rsp_rdata,
    input logic mem_rsp_error,
    output logic product_valid,
    input logic product_ready,
    output logic [31:0] product_value,
    output logic [31:0] product_output_address, product_row, product_oc, product_ic,
    output logic product_first, product_last, product_last_output
);
    logic operand_valid, operand_ready, multiply_ready, multiply_valid;
    logic [15:0] operand_input, operand_weight;
    logic [31:0] operand_output_address, operand_row, operand_oc, operand_ic;
    logic operand_first, operand_last, operand_last_output;
    logic [130:0] input_tag, output_tag;
    logic [1:0] pending_products;
    logic input_fire, output_fire;

    rk_cmac_operand_front #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) operands (
        .clk, .rst_n, .cmd_valid, .cmd_ready, .cmd_data,
        .downstream_busy(downstream_busy || pending_products != 0),
        .busy, .address_done, .stream_done(operand_done), .error, .error_code,
        .mem_req_valid, .mem_req_ready, .mem_req_addr,
        .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata, .mem_rsp_error,
        .operand_valid, .operand_ready, .operand_input, .operand_weight,
        .operand_output_address, .operand_row, .operand_oc, .operand_ic,
        .operand_first, .operand_last, .operand_last_output
    );
    assign input_tag = {operand_output_address, operand_row, operand_oc, operand_ic,
                        operand_first, operand_last, operand_last_output};
    assign {product_output_address, product_row, product_oc, product_ic,
            product_first, product_last, product_last_output} = output_tag;
    assign operand_ready = !error && multiply_ready;
    assign product_valid = !error && multiply_valid;
    assign input_fire = operand_valid && operand_ready;
    assign output_fire = product_valid && product_ready;
    rk_fp16_product #(.TAG_WIDTH(131)) multiply (
        .clk, .rst_n, .in_valid(operand_valid && !error), .in_ready(multiply_ready),
        .in_a(operand_input), .in_b(operand_weight), .in_tag(input_tag),
        .out_valid(multiply_valid), .out_ready(product_ready && !error),
        .out_product(product_value), .out_tag(output_tag)
    );

    // Count *all* occupied multiplier stages, not only its output-valid bit.
    // This retains ownership across pipeline latency and after operand_done.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin pending_products <= 0; product_done <= 0; end
        else begin
            product_done <= output_fire && product_last && product_last_output;
            if (!error) begin
                case ({input_fire, output_fire})
                    2'b10: pending_products <= pending_products + 1'b1;
                    2'b01: pending_products <= pending_products - 1'b1;
                    default: begin end
                endcase
            end
        end
    end
endmodule
