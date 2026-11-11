// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// FP32 output writer: commits an already converted 32-bit value as two
// consecutive halfword writes over the serialized 16-bit memory port.
//
// Every existing writer in this repository is halfword-wide and converts to
// FP16 (`rk_cmac_writer`, `rk_conv_output_atom`). Captures whose device output
// is FP32 (`conv_simple_fp16_1x1_c4_h8_w8_oc16` and the four frozen
// `conv-gemm-vendor` GEMM cases) therefore have no writer at all. This module
// is that missing piece and nothing more: it does not convert, round or
// reorder. The value it is handed is the value written.
//
// Contract:
//   * one outstanding value at a time;
//   * the low halfword is written at `result_address`, the high halfword at
//     `result_address + 2`, both acknowledged before the value completes;
//   * `result_address` must be 4-byte aligned, otherwise error code 4;
//   * any memory error aborts with code 5 without writing the high halfword;
//   * a stall longer than TIMEOUT_CYCLES aborts with code 8;
//   * `done` pulses only on the last acknowledged write of a value whose
//     `result_last` was set. Partial writes are never retracted; the platform
//     must reset the writer together with the memory after any fault.
//
// This is a transport primitive. It is not a GEMM engine, does not read
// operands and makes no numerical decision.
module rk_cmac_fp32_writer #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        result_valid,
    output logic        result_ready,
    input  logic [31:0] result_address,
    input  logic [31:0] result_value,
    input  logic        result_last,
    output logic        busy,
    output logic        acknowledged,
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
    input  logic        mem_rsp_error
);
    // Each halfword has its own request and response state, so a response can
    // never be attributed to the wrong beat. Codes are 0..4, no overlap.
    localparam logic [2:0] IDLE     = 3'd0,
                           LOW_REQ  = 3'd1,
                           LOW_RSP  = 3'd2,
                           HIGH_REQ = 3'd3,
                           HIGH_RSP = 3'd4;
    logic [2:0] state_q;
    logic       half_q;          // 1 once the high halfword is being written
    logic [31:0] address_q, value_q;
    logic       last_q;
    logic [31:0] stalled_q;

    assign result_ready = rst_n && !error && state_q == IDLE;
    assign busy = rst_n && !error && state_q != IDLE;
    assign mem_req_valid = rst_n && !error &&
                           (state_q == LOW_REQ || state_q == HIGH_REQ);
    assign mem_req_write = 1'b1;
    assign mem_req_addr = address_q + (half_q ? 32'd2 : 32'd0);
    assign mem_req_wdata = half_q ? value_q[31:16] : value_q[15:0];
    assign mem_rsp_ready = rst_n && !error &&
                           (state_q == LOW_RSP || state_q == HIGH_RSP);

    initial begin
        if (TIMEOUT_CYCLES == 0)
            $fatal(1, "FP32 writer timeout must be positive");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= IDLE;
            half_q <= 1'b0;
            address_q <= 32'd0;
            value_q <= 32'd0;
            last_q <= 1'b0;
            stalled_q <= 32'd0;
            acknowledged <= 1'b0;
            done <= 1'b0;
            error <= 1'b0;
            error_code <= 8'd0;
        end else begin
            acknowledged <= 1'b0;
            done <= 1'b0;
            if (!error) begin
                // Progress in any request or response clears the stall counter.
                if (mem_req_ready || mem_rsp_valid)
                    stalled_q <= 32'd0;
                else if (state_q != IDLE)
                    stalled_q <= stalled_q + 1'b1;

                case (state_q)
                    IDLE: if (result_valid && result_ready) begin
                        if (result_address[1:0] != 2'b00 ||
                            result_address > 32'hffff_fffc) begin
                            error <= 1'b1;
                            error_code <= 8'd4;
                        end else begin
                            address_q <= result_address;
                            value_q <= result_value;
                            last_q <= result_last;
                            half_q <= 1'b0;
                            stalled_q <= 32'd0;
                            state_q <= LOW_REQ;
                        end
                    end

                    LOW_REQ: if (mem_req_ready) begin
                        half_q <= 1'b0;
                        state_q <= LOW_RSP;
                    end

                    LOW_RSP: if (mem_rsp_valid) begin
                        if (mem_rsp_error) begin
                            error <= 1'b1;
                            error_code <= 8'd5;
                        end else begin
                            acknowledged <= 1'b1;
                            half_q <= 1'b1;
                            state_q <= HIGH_REQ;
                        end
                    end

                    HIGH_REQ: if (mem_req_ready) begin
                        half_q <= 1'b1;
                        state_q <= HIGH_RSP;
                    end

                    HIGH_RSP: if (mem_rsp_valid) begin
                        if (mem_rsp_error) begin
                            error <= 1'b1;
                            error_code <= 8'd5;
                        end else begin
                            acknowledged <= 1'b1;
                            done <= last_q;
                            state_q <= IDLE;
                        end
                    end

                    default: begin
                        error <= 1'b1;
                        error_code <= 8'd6;
                        state_q <= IDLE;
                    end
                endcase

                if (state_q != IDLE && stalled_q >= TIMEOUT_CYCLES - 1) begin
                    error <= 1'b1;
                    error_code <= 8'd8;
                    acknowledged <= 1'b0;
                    done <= 1'b0;
                    state_q <= IDLE;
                end
            end
        end
    end
endmodule
