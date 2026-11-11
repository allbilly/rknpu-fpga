// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// INTERNAL FP32 post-accumulation tail. Not a raw command port or a GEMM engine.
//
// `rk_cmac_output_nvdla` converts the CACC result to FP16 with the donor
// `HLS_fp32_to_fp16` and writes one halfword. That is wrong for any capture
// whose device output is FP32 — the `conv-gemm-vendor` GEMM family and
// `conv_simple_fp16_1x1_c4_h8_w8_oc16` both have 32-bit output, and their
// `OUT_CVT_SCALE` register is 0x0, i.e. conversion explicitly disabled.
//
// This tail therefore performs **no conversion**: the CACC value is committed
// unchanged through `rk_cmac_fp32_writer`, which writes two halfwords per value.
// The address is taken from the incoming tag, exactly as the FP16 tail does.
// Cancellation and error aggregation keep the same 1..8 code family, and a
// fault stays latched until a joint reset.
module rk_cmac_output_fp32 #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        in_valid,
    output logic        in_ready,
    input  logic [31:0] in_value,
    input  logic [31:0] in_address,
    input  logic        in_last,
    input  logic        cancel,
    input  logic [7:0]  cancel_code,
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
    logic writer_ready, writer_busy, writer_ack, writer_done, writer_error;
    logic writer_req_valid, writer_rsp_ready;
    logic [7:0] writer_code, saved_code, normalized_cancel_code;
    logic active, closing, fault_latched, accept;

    always_comb begin
        case (cancel_code)
            1,2,3,4,5,6,7,8: normalized_cancel_code = cancel_code;
            default: normalized_cancel_code = 6;
        endcase
    end

    // `closing` blocks any further value after the final one was accepted, so a
    // frame cannot silently gain an extra output element.
    assign in_ready = rst_n && !error && !closing && writer_ready;
    assign accept = in_valid && in_ready;

    assign error = rst_n && (fault_latched || writer_error || cancel);
    assign error_code = !rst_n ? 8'd0 : fault_latched ? saved_code :
                        writer_error ? writer_code :
                        cancel ? normalized_cancel_code : 8'd0;
    // active spans input gaps, not only occupied stages. A final accepted input
    // closes this stream until its successful write acknowledgment.
    assign busy = rst_n && !error &&
                  ((active && !writer_done) || writer_busy);
    assign acknowledged = writer_ack && !error;
    assign done = writer_done && !error;
    assign mem_req_valid = writer_req_valid && !error;
    assign mem_rsp_ready = writer_rsp_ready && !error;

    rk_cmac_fp32_writer #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) writer (
        .clk, .rst_n,
        .result_valid(in_valid && !closing && !error),
        .result_ready(writer_ready),
        .result_address(in_address), .result_value(in_value),
        .result_last(in_last),
        .busy(writer_busy), .acknowledged(writer_ack), .done(writer_done),
        .error(writer_error), .error_code(writer_code),
        .mem_req_valid(writer_req_valid), .mem_req_ready(mem_req_ready && !error),
        .mem_req_write(mem_req_write), .mem_req_addr(mem_req_addr),
        .mem_req_wdata(mem_req_wdata),
        .mem_rsp_valid(mem_rsp_valid && !error), .mem_rsp_ready(writer_rsp_ready),
        .mem_rsp_error(mem_rsp_error)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active <= 0; closing <= 0; fault_latched <= 0; saved_code <= 0;
        end else begin
            if (!fault_latched && (writer_error || cancel)) begin
                fault_latched <= 1;
                saved_code <= writer_error ? writer_code : normalized_cancel_code;
            end
            if (!error) begin
                if (writer_done) begin active <= 0; closing <= 0; end
                if (accept) begin
                    active <= 1;
                    if (in_last) closing <= 1;
                end
            end
        end
    end
endmodule
