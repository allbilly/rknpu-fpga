// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One raw descriptor/result crossing, intended for UI133 control -> SYS50 core.
// Carries the original 32-bit command address/amount, not a tensor operation.
// Result capture is not memory retirement, fence/ECC proof or result ACK.
// Both resets must belong to one audited whole-transaction epoch, including
// the core and its memory crossing. No unilateral reset, cancellation or retry.
module rk_async_job_port #(
    parameter int unsigned SYNC_STAGES = 3
) (
    input wire s_clk, s_rst_n, s_admission_enable,
    input wire s_start_valid,
    output wire s_start_ready,
    input wire [31:0] s_start_address, s_start_amount,
    output logic s_result_valid, s_result_error,
    output logic [7:0] s_result_code,
    output logic [31:0] s_result_tasks,
    input wire s_result_ready,
    output wire s_protocol_fault,
    input wire d_clk, d_rst_n,
    output logic d_start_valid,
    input wire d_start_ready,
    output wire [31:0] d_start_address, d_start_amount,
    input wire d_result_valid, d_result_error,
    input wire [7:0] d_result_code,
    input wire [31:0] d_result_tasks,
    output wire d_result_ready,
    output logic d_protocol_fault,
    output wire s_quiet,d_quiet
);
    localparam integer STAGES = SYNC_STAGES < 3 ? 3 : SYNC_STAGES;
    logic [63:0] descriptor_held, descriptor_latched;
    logic [40:0] result_held;
    logic request_toggle, result_toggle;
    logic s_outstanding, s_result_seen, d_request_seen, d_wait_result;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] request_sync;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] result_sync;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] fault_sync;
    wire valid_result = (d_result_error === 1'b0 && d_result_code === 8'b0) ||
                        (d_result_error === 1'b1 && (^d_result_code !== 1'bx) && d_result_code != 0);

    initial begin
        if (SYNC_STAGES < 3) $fatal(1,"Job crossing requires at least three synchronizer stages");
    end

    // Quiet proves toggle equality and no offered/pending transfers.
    // No reset gating: reset values themselves describe empty state.
    assign s_quiet=!s_outstanding&&!s_result_valid&&!s_start_valid&&!s_protocol_fault&&
        result_sync[STAGES-1]==s_result_seen&&request_toggle==s_result_seen;
    assign d_quiet=!d_start_valid&&!d_wait_result&&!d_result_valid&&!d_protocol_fault&&
        request_sync[STAGES-1]==d_request_seen&&result_toggle==d_request_seen;
    // Loss of admission blocks only new ownership; it cannot withdraw a start.
    assign s_start_ready = s_rst_n && s_admission_enable && !s_outstanding &&
                           !s_result_valid && !s_protocol_fault;
    assign s_protocol_fault = s_rst_n && fault_sync[STAGES-1];
    assign d_start_address = descriptor_latched[63:32];
    assign d_start_amount = descriptor_latched[31:0];
    assign d_result_ready = d_rst_n && d_wait_result;

    always_ff @(posedge s_clk or negedge s_rst_n) begin
        if (!s_rst_n) begin
            descriptor_held <= 0; request_toggle <= 0;
            s_outstanding <= 0; s_result_seen <= 0; result_sync <= 0; fault_sync <= 0;
            s_result_valid <= 0; s_result_error <= 0; s_result_code <= 0; s_result_tasks <= 0;
        end else begin
            result_sync <= {result_sync[STAGES-2:0],result_toggle};
            fault_sync <= {fault_sync[STAGES-2:0],d_protocol_fault};
            if (s_start_valid && s_start_ready) begin
                descriptor_held <= {s_start_address,s_start_amount};
                request_toggle <= !request_toggle; s_outstanding <= 1;
            end
            if (s_outstanding && result_sync[STAGES-1] != s_result_seen) begin
                s_result_seen <= result_sync[STAGES-1];
                {s_result_error,s_result_code,s_result_tasks} <= result_held;
                s_result_valid <= 1;
            end
            if (s_result_valid && s_result_ready) begin
                s_result_valid <= 0; s_outstanding <= 0;
            end
        end
    end

    always_ff @(posedge d_clk or negedge d_rst_n) begin
        if (!d_rst_n) begin
            request_sync <= 0; d_request_seen <= 0; descriptor_latched <= 0;
            d_start_valid <= 0; d_wait_result <= 0;
            result_held <= 0; result_toggle <= 0; d_protocol_fault <= 0;
        end else begin
            request_sync <= {request_sync[STAGES-2:0],request_toggle};
            if (d_result_valid && !d_wait_result) d_protocol_fault <= 1;
            if (!d_start_valid && !d_wait_result && request_sync[STAGES-1] != d_request_seen) begin
                d_request_seen <= request_sync[STAGES-1];
                descriptor_latched <= descriptor_held;
                if (d_protocol_fault || d_result_valid) begin
                    // No core start is owned yet. An early/unsolicited result
                    // is a protocol failure, never completion of this new job.
                    result_held <= {1'b1,8'd5,32'b0};
                    result_toggle <= request_sync[STAGES-1];
                end else d_start_valid <= 1;
            end
            if (d_start_valid && d_start_ready) begin
                d_start_valid <= 0; d_wait_result <= 1;
            end
            if (d_result_valid && d_result_ready) begin
                if (valid_result) result_held <= {d_result_error,d_result_code,d_result_tasks};
                else begin
                    d_protocol_fault <= 1;
                    result_held <= {1'b1,8'd5,d_result_tasks};
                end
                result_toggle <= d_request_seen; d_wait_result <= 0;
            end
        end
    end
endmodule
