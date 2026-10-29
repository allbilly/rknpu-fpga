// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// INTERNAL operand reader, not a GEMM engine or CBUF implementation.
// One outstanding halfword read; response must follow request acceptance.
// Reset this leaf and its memory adapter together after faults/interruption.
module rk_cmac_reader #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, rst_n,
    input logic pair_valid,
    output logic pair_ready,
    input logic [31:0] input_address, weight_address, output_address,
    input logic [31:0] row_index, output_channel, input_channel,
    input logic first_product, last_product, last_output,
    output logic busy, error,
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
    typedef enum logic [2:0] {IDLE, INPUT_REQ, INPUT_WAIT, WEIGHT_REQ, WEIGHT_WAIT, EMIT} state_t;
    state_t state;
    logic [31:0] input_base, weight_base, stalled_cycles;
    logic memory_state, progress;
    initial begin
        if (TIMEOUT_CYCLES == 0) $fatal(1,"TIMEOUT_CYCLES must be positive");
    end
    assign pair_ready = rst_n && !error && state == IDLE;
    assign busy = rst_n && !error && state != IDLE;
    assign mem_req_valid = rst_n && !error && (state == INPUT_REQ || state == WEIGHT_REQ);
    assign mem_req_addr = state == INPUT_REQ ? input_base : weight_base;
    assign mem_rsp_ready = rst_n && !error && (state == INPUT_WAIT || state == WEIGHT_WAIT);
    assign operand_valid = rst_n && !error && state == EMIT;
    assign memory_state = state == INPUT_REQ || state == INPUT_WAIT || state == WEIGHT_REQ || state == WEIGHT_WAIT;
    assign progress = (mem_req_valid && mem_req_ready) || (mem_rsp_valid && mem_rsp_ready);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; error <= 0; error_code <= 0; stalled_cycles <= 0;
            input_base <= 0; weight_base <= 0;
            operand_input <= 0; operand_weight <= 0;
            operand_output_address <= 0; operand_row <= 0; operand_oc <= 0; operand_ic <= 0;
            operand_first <= 0; operand_last <= 0; operand_last_output <= 0;
        end else if (!error) begin
            if (!memory_state || progress) stalled_cycles <= 0;
            else stalled_cycles <= stalled_cycles + 1;
            case (state)
                IDLE: if (pair_valid && pair_ready) begin
                    if (input_address[0] == 0 && weight_address[0] == 0 && output_address[0] == 0) begin
                        input_base <= input_address; weight_base <= weight_address;
                        operand_output_address <= output_address; operand_row <= row_index;
                        operand_oc <= output_channel; operand_ic <= input_channel;
                        operand_first <= first_product; operand_last <= last_product; operand_last_output <= last_output;
                        state <= INPUT_REQ;
                    end else begin error <= 1; error_code <= 4; end
                end
                INPUT_REQ: if (mem_req_valid && mem_req_ready) state <= INPUT_WAIT;
                INPUT_WAIT: if (mem_rsp_valid && mem_rsp_ready) begin
                    operand_input <= mem_rsp_rdata;
                    state <= WEIGHT_REQ;
                end
                WEIGHT_REQ: if (mem_req_valid && mem_req_ready) state <= WEIGHT_WAIT;
                WEIGHT_WAIT: if (mem_rsp_valid && mem_rsp_ready) begin
                    operand_weight <= mem_rsp_rdata;
                    state <= EMIT;
                end
                EMIT: if (operand_valid && operand_ready) state <= IDLE;
                default: begin state <= IDLE; error <= 1; error_code <= 6; end
            endcase
            // A failed read must never emit a partial operand pair. Unknown
            // error status also rejects in four-state simulation, not success.
            if (mem_rsp_valid && mem_rsp_ready) begin
                if (mem_rsp_error == 0) begin end
                else begin state <= IDLE; error <= 1; error_code <= 5; end
            end else if (memory_state && !progress && stalled_cycles >= TIMEOUT_CYCLES-1) begin
                state <= IDLE; error <= 1; error_code <= 8;
            end
        end
    end
endmodule
