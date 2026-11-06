// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// RK flat_1x1 FP16 atom sink. A C32/K16 CACC frame is zero-padded in hardware
// for the unused OC8..OC15 half; only the captured OC0..OC7 atom is written.
// The output address is supplied by the conv scheduler (16-byte atom stride),
// never by the K8 GEMM atom-advance logic.
module rk_conv_output_atom #(
    parameter int unsigned TIMEOUT_CYCLES=65536
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         in_valid,
    output logic         in_ready,
    input  logic [511:0] in_values,
    input  logic [31:0]  in_address,
    input  logic         in_last,
    input  logic         cancel,
    input  logic [7:0]   cancel_code,
    output logic         busy,
    output logic         acknowledged,
    output logic         frame_done,
    output logic         done,
    output logic         error,
    output logic [7:0]   error_code,
    output logic         mem_req_valid,
    input  logic         mem_req_ready,
    output logic         mem_req_write,
    output logic [31:0]  mem_req_addr,
    output logic [15:0]  mem_req_wdata,
    input  logic         mem_rsp_valid,
    output logic         mem_rsp_ready,
    input  logic         mem_rsp_error
);
    rk_cmac_frame_output #(.ATOMIC_K(8), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)) writer(
        .clk, .rst_n, .in_valid, .in_ready, .in_values(in_values[255:0]),
        .in_address, .in_last, .cancel, .cancel_code, .busy, .acknowledged,
        .frame_done, .done, .error, .error_code, .mem_req_valid, .mem_req_ready,
        .mem_req_write, .mem_req_addr, .mem_req_wdata, .mem_rsp_valid,
        .mem_rsp_ready, .mem_rsp_error);
endmodule
