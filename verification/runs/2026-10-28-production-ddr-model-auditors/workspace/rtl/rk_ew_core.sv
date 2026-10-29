// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Host-neutral top. cmd_data contains an ACTUAL RK regcmd QWORD, not an abstract
// tensor operation. Device-memory addresses are byte addresses, never host pointers.
module rk_ew_core #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, rst_n,
    input logic cmd_valid,
    output logic cmd_ready,
    input logic [63:0] cmd_data,
    output logic busy, done, error,
    output logic [7:0] error_code,
    output logic mem_req_valid,
    input logic mem_req_ready,
    output logic mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input logic mem_rsp_valid,
    output logic mem_rsp_ready,
    input logic [15:0] mem_rsp_rdata,
    input logic mem_rsp_error
);
    logic cfg_valid, cfg_ready, engine_busy, reg_error, engine_error;
    logic [7:0] reg_error_code, engine_error_code;
    logic [1:0] cfg_op;
    logic [16:0] cfg_count;
    logic [31:0] cfg_a, cfg_b, cfg_dst;
    logic [31:0] unused_next_address, unused_next_amount;
    assign busy = engine_busy || cfg_valid;
    assign error = reg_error || engine_error;
    assign error_code = reg_error ? reg_error_code : engine_error_code;
    rk_ew_regs regs (
        .clk(clk), .rst_n(rst_n), .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_data(cmd_data),
        .engine_busy(engine_busy), .engine_error(engine_error),
        .cfg_valid(cfg_valid), .cfg_ready(cfg_ready), .cfg_op(cfg_op), .cfg_count(cfg_count),
        .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_dst(cfg_dst), .error(reg_error), .error_code(reg_error_code),
        .cfg_next_address(unused_next_address), .cfg_next_amount(unused_next_amount)
    );
    rk_ew_engine #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) engine (
        .clk(clk), .rst_n(rst_n), .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
        .cfg_op(cfg_op), .cfg_count(cfg_count), .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_dst(cfg_dst),
        .busy(engine_busy), .done(done), .error(engine_error), .error_code(engine_error_code),
        .mem_req_valid(mem_req_valid), .mem_req_ready(mem_req_ready), .mem_req_write(mem_req_write),
        .mem_req_addr(mem_req_addr), .mem_req_wdata(mem_req_wdata), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rsp_rdata(mem_rsp_rdata), .mem_rsp_error(mem_rsp_error)
    );
endmodule
