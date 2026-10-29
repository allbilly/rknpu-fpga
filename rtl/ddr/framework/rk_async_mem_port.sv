// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One-outstanding halfword memory crossing. No address/layout/arithmetic change.
// Both resets must belong to one audited whole-transaction epoch. Unilateral
// reset/recovery is unsupported; reset may leave partial downstream writes.
// Held request/response buses need source-bound physical max-delay/skew checks.
module rk_async_mem_port #(
    parameter int unsigned SYNC_STAGES = 3
) (
    input wire s_clk, s_rst_n, s_admission_enable,
    input wire s_mem_req_valid, s_mem_req_write,
    input wire [31:0] s_mem_req_addr,
    input wire [15:0] s_mem_req_wdata,
    output wire s_mem_req_ready,
    output logic s_mem_rsp_valid,
    output logic [15:0] s_mem_rsp_rdata,
    output logic s_mem_rsp_error,
    input wire s_mem_rsp_ready,
    output wire s_protocol_fault,
    input wire d_clk, d_rst_n,
    output logic d_mem_req_valid,
    output wire d_mem_req_write,
    output wire [31:0] d_mem_req_addr,
    output wire [15:0] d_mem_req_wdata,
    input wire d_mem_req_ready, d_mem_rsp_valid,
    input wire [15:0] d_mem_rsp_rdata,
    input wire d_mem_rsp_error,
    output wire d_mem_rsp_ready,
    output logic d_protocol_fault,
    output wire s_quiet,d_quiet
);
    localparam integer STAGES = SYNC_STAGES < 3 ? 3 : SYNC_STAGES;
    logic [48:0] request_held, request_latched;
    logic [16:0] response_held;
    logic request_toggle, response_toggle;
    logic s_outstanding, s_response_seen, d_request_seen, d_wait_response;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] request_sync;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] response_sync;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] fault_sync;

    initial begin
        if (SYNC_STAGES < 3) $fatal(1,"Memory crossing requires at least three synchronizer stages");
    end

    assign s_quiet=!s_outstanding&&!s_mem_rsp_valid&&!s_mem_req_valid&&!s_protocol_fault&&
        response_sync[STAGES-1]==s_response_seen&&request_toggle==s_response_seen;
    assign d_quiet=!d_mem_req_valid&&!d_wait_response&&!d_mem_rsp_valid&&!d_protocol_fault&&
        request_sync[STAGES-1]==d_request_seen&&response_toggle==d_request_seen;
    // Revoking admission never withdraws an owned request or response.
    assign s_mem_req_ready = s_rst_n && s_admission_enable &&
                             !s_outstanding && !s_mem_rsp_valid && !s_protocol_fault;
    assign s_protocol_fault = s_rst_n && fault_sync[STAGES-1];
    assign d_mem_req_write = request_latched[48];
    assign d_mem_req_addr = request_latched[47:16];
    assign d_mem_req_wdata = request_latched[15:0];
    assign d_mem_rsp_ready = d_rst_n && d_wait_response;

    always_ff @(posedge s_clk or negedge s_rst_n) begin
        if (!s_rst_n) begin
            request_held <= 0; request_toggle <= 0;
            s_outstanding <= 0; s_response_seen <= 0;
            response_sync <= 0; fault_sync <= 0;
            s_mem_rsp_valid <= 0; s_mem_rsp_rdata <= 0; s_mem_rsp_error <= 0;
        end else begin
            response_sync <= {response_sync[STAGES-2:0],response_toggle};
            fault_sync <= {fault_sync[STAGES-2:0],d_protocol_fault};
            if (s_mem_req_valid && s_mem_req_ready) begin
                request_held <= {s_mem_req_write,s_mem_req_addr,s_mem_req_wdata};
                request_toggle <= !request_toggle;
                s_outstanding <= 1;
            end
            if (s_outstanding && response_sync[STAGES-1] != s_response_seen) begin
                s_response_seen <= response_sync[STAGES-1];
                s_mem_rsp_rdata <= response_held[15:0];
                s_mem_rsp_error <= response_held[16] || s_protocol_fault;
                s_mem_rsp_valid <= 1;
            end
            if (s_mem_rsp_valid && s_mem_rsp_ready) begin
                s_mem_rsp_valid <= 0; s_outstanding <= 0;
            end
        end
    end

    always_ff @(posedge d_clk or negedge d_rst_n) begin
        if (!d_rst_n) begin
            request_sync <= 0; d_request_seen <= 0;
            request_latched <= 0; d_mem_req_valid <= 0; d_wait_response <= 0;
            response_held <= 0; response_toggle <= 0; d_protocol_fault <= 0;
        end else begin
            request_sync <= {request_sync[STAGES-2:0],request_toggle};
            if (d_mem_rsp_valid && !d_wait_response) d_protocol_fault <= 1;
            if (!d_mem_req_valid && !d_wait_response && request_sync[STAGES-1] != d_request_seen) begin
                d_request_seen <= request_sync[STAGES-1];
                request_latched <= request_held;
                if (d_protocol_fault || d_mem_rsp_valid) begin
                    // No downstream request is owned yet: fail this accepted
                    // source request explicitly instead of issuing new work.
                    response_held <= {1'b1,16'b0};
                    response_toggle <= request_sync[STAGES-1];
                end else d_mem_req_valid <= 1;
            end
            if (d_mem_req_valid && d_mem_req_ready) begin
                d_mem_req_valid <= 0; d_wait_response <= 1;
            end
            if (d_mem_rsp_valid && d_mem_rsp_ready) begin
                response_held <= {d_mem_rsp_error || d_protocol_fault,d_mem_rsp_rdata};
                response_toggle <= d_request_seen;
                d_wait_response <= 0;
            end
        end
    end
endmodule
