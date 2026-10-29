// CONTROL-TEST-ONLY substitutes for the child asynchronous engines.
// These models implement start/request/response/result handshakes only. They
// contain no arithmetic, MIG behavior, ECC, or timing qualification and must
// never appear in an FPGA source list or be executed as a numerical test.
`timescale 1ns/1ps
module dispatch_control_engine #(
    parameter bit IS_CMAC = 1'b0,
    parameter integer REQUEST_OFFSET = 32'h10,
    parameter logic [15:0] REQUEST_DATA = 16'he100
) (
    input wire ui_clk, ui_rst_n, ui_admission_enable,
    input wire ui_start_valid,
    output wire ui_start_ready,
    input wire [31:0] ui_start_address, ui_start_amount,
    output wire ui_result_valid, ui_result_error,
    output wire [7:0] ui_result_code,
    output wire [31:0] ui_result_tasks,
    input wire ui_result_ready,
    output wire ui_fault,
    output wire ui_mem_req_valid,
    input wire ui_mem_req_ready,
    output wire ui_mem_req_write,
    output wire [31:0] ui_mem_req_addr,
    output wire [15:0] ui_mem_req_wdata,
    input wire ui_mem_rsp_valid,
    input wire [15:0] ui_mem_rsp_rdata,
    input wire ui_mem_rsp_error,
    output wire ui_mem_rsp_ready
);
    logic active, request_pending, response_pending, result_pending;
    logic result_error, fault_latched;
    logic [7:0] result_code;
    logic [31:0] result_tasks, held_address, held_amount;
    logic [4:0] timeout_count;
    wire timeout_case = active && held_amount == 32'h0000dead && !fault_latched;

    assign ui_start_ready = ui_rst_n && ui_admission_enable && !active && !fault_latched;
    assign ui_mem_req_valid = ui_rst_n && request_pending;
    assign ui_mem_req_write = IS_CMAC ? 1'b0 : 1'b1;
    assign ui_mem_req_addr = active ? held_address + REQUEST_OFFSET : 32'b0;
    assign ui_mem_req_wdata = active ? REQUEST_DATA : 16'b0;
    assign ui_mem_rsp_ready = ui_rst_n && response_pending;
    assign ui_result_valid = ui_rst_n && result_pending;
    assign ui_result_error = result_error;
    assign ui_result_code = result_code;
    assign ui_result_tasks = result_tasks;
    assign ui_fault = ui_rst_n && fault_latched;

    always_ff @(posedge ui_clk or negedge ui_rst_n) begin
        if (!ui_rst_n) begin
            active <= 0;
            request_pending <= 0;
            response_pending <= 0;
            result_pending <= 0;
            result_error <= 0;
            fault_latched <= 0;
            result_code <= 0;
            result_tasks <= 0;
            held_address <= 0;
            held_amount <= 0;
            timeout_count <= 0;
        end else begin
            if (ui_start_valid && ui_start_ready) begin
                active <= 1;
                request_pending <= 1;
                response_pending <= 0;
                result_pending <= 0;
                result_error <= 0;
                result_code <= 0;
                result_tasks <= 0;
                held_address <= ui_start_address;
                held_amount <= ui_start_amount;
                timeout_count <= 0;
            end else if (timeout_case) begin
                if (timeout_count == 5'd4) begin
                    // Model an E8 engine timeout while its first request is
                    // still offered. Preserve that request and owner for drain.
                    fault_latched <= 1;
                    result_pending <= 1;
                    result_error <= 1;
                    result_code <= 8;
                    result_tasks <= 0;
                end else timeout_count <= timeout_count + 1'b1;
            end

            if (ui_mem_req_valid && ui_mem_req_ready) begin
                request_pending <= 0;
                response_pending <= 1;
            end
            if (ui_mem_rsp_valid && ui_mem_rsp_ready) begin
                response_pending <= 0;
                if (!fault_latched) begin
                    result_pending <= 1;
                    result_error <= ui_mem_rsp_error ||
                        (ui_mem_rsp_rdata !== (IS_CMAC ? 16'hc002 : 16'he001));
                    if (ui_mem_rsp_error ||
                        (ui_mem_rsp_rdata !== (IS_CMAC ? 16'hc002 : 16'he001))) begin
                        fault_latched <= 1;
                        result_code <= 5;
                        result_tasks <= 0;
                    end else begin
                        result_code <= 0;
                        result_tasks <= IS_CMAC ? 32'd1 : 32'd2;
                    end
                end
                // A late response after E8 is drained but cannot replace the
                // already reported failure or release this selected owner.
            end
            if (result_pending && ui_result_ready && !result_error && !fault_latched) begin
                result_pending <= 0;
                active <= 0;
                request_pending <= 0;
                response_pending <= 0;
            end else if (result_pending && ui_result_ready && result_error) begin
                result_pending <= 0;
                // Faulted ownership, request offer and any late return remain
                // until coordinated reset; never reselect the other engine.
            end
        end
    end
endmodule

module rk_ew_async_engine #(
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter int unsigned MAX_TASKS = 4095,
    parameter int unsigned JOB_SYNC_STAGES = 3,
    parameter int unsigned MEMORY_SYNC_STAGES = 3
) (
    input wire ui_clk, ui_rst_n, ui_admission_enable,
    input wire ui_start_valid,
    output wire ui_start_ready,
    input wire [31:0] ui_start_address, ui_start_amount,
    output wire ui_result_valid, ui_result_error,
    output wire [7:0] ui_result_code,
    output wire [31:0] ui_result_tasks,
    input wire ui_result_ready,
    output wire ui_fault,
    input wire core_clk, core_rst_n,
    output wire ui_mem_req_valid,
    input wire ui_mem_req_ready,
    output wire ui_mem_req_write,
    output wire [31:0] ui_mem_req_addr,
    output wire [15:0] ui_mem_req_wdata,
    input wire ui_mem_rsp_valid,
    input wire [15:0] ui_mem_rsp_rdata,
    input wire ui_mem_rsp_error,
    output wire ui_mem_rsp_ready
);
    dispatch_control_engine #(.IS_CMAC(1'b0), .REQUEST_OFFSET(32'h10),
        .REQUEST_DATA(16'he100) ) model (
        .ui_clk, .ui_rst_n, .ui_admission_enable, .ui_start_valid, .ui_start_ready,
        .ui_start_address, .ui_start_amount, .ui_result_valid, .ui_result_error,
        .ui_result_code, .ui_result_tasks, .ui_result_ready, .ui_fault,
        .ui_mem_req_valid, .ui_mem_req_ready, .ui_mem_req_write, .ui_mem_req_addr,
        .ui_mem_req_wdata, .ui_mem_rsp_valid, .ui_mem_rsp_rdata, .ui_mem_rsp_error,
        .ui_mem_rsp_ready
    );
    wire unused_core = core_clk ^ core_rst_n;
    wire unused_parameters = (TIMEOUT_CYCLES == 0) || (MAX_TASKS == 0) ||
                             (JOB_SYNC_STAGES == 0) || (MEMORY_SYNC_STAGES == 0) || unused_core;
endmodule

module rk_cmac_async_engine #(
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter int unsigned JOB_SYNC_STAGES = 3,
    parameter int unsigned MEMORY_SYNC_STAGES = 3,
    parameter int unsigned PERMIT_SYNC_STAGES = 3
) (
    input wire ui_clk, ui_rst_n, ui_admission_enable, ui_rearm_permit,
    input wire ui_start_valid,
    output wire ui_start_ready,
    input wire [31:0] ui_start_address, ui_start_amount,
    output wire ui_result_valid, ui_result_error,
    output wire [7:0] ui_result_code,
    output wire [31:0] ui_result_tasks,
    input wire ui_result_ready,
    output wire ui_fault,
    input wire core_clk, core_rst_n,
    output wire ui_mem_req_valid,
    input wire ui_mem_req_ready,
    output wire ui_mem_req_write,
    output wire [31:0] ui_mem_req_addr,
    output wire [15:0] ui_mem_req_wdata,
    input wire ui_mem_rsp_valid,
    input wire [15:0] ui_mem_rsp_rdata,
    input wire ui_mem_rsp_error,
    output wire ui_mem_rsp_ready
);
    dispatch_control_engine #(.IS_CMAC(1'b1), .REQUEST_OFFSET(32'h20),
        .REQUEST_DATA(16'hc200) ) model (
        .ui_clk, .ui_rst_n, .ui_admission_enable, .ui_start_valid, .ui_start_ready,
        .ui_start_address, .ui_start_amount, .ui_result_valid, .ui_result_error,
        .ui_result_code, .ui_result_tasks, .ui_result_ready, .ui_fault,
        .ui_mem_req_valid, .ui_mem_req_ready, .ui_mem_req_write, .ui_mem_req_addr,
        .ui_mem_req_wdata, .ui_mem_rsp_valid, .ui_mem_rsp_rdata, .ui_mem_rsp_error,
        .ui_mem_rsp_ready
    );
    wire unused_core = core_clk ^ core_rst_n;
    wire unused_parameters = (TIMEOUT_CYCLES == 0) ||
        (JOB_SYNC_STAGES == 0) || (MEMORY_SYNC_STAGES == 0) ||
        (PERMIT_SYNC_STAGES == 0) || unused_core || !ui_rearm_permit;
endmodule
