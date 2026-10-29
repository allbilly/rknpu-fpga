// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Test-only single-outstanding 64-byte line sweep. Not an RK command endpoint.
// Integration must grant exclusive memory ownership and jointly reset this
// engine, its adapter, the qualified fence and every affected transaction.
// retire_* requests the existing exact-final-write-address fence plus a fresh
// ECC snapshot; it is not a substitute for that controller-specific witness.
module rk_ddr_capacity_sweep #(
    parameter logic [30:0] BASE_ADDR = 0,
    parameter logic [31:0] SPAN_BYTES = 32'h80000000,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, joint_rst_n,
    input logic start_valid,
    output logic start_ready,
    input logic [31:0] seed,
    input logic initialization_complete, calibration_complete,
    input logic ecc_monitor_healthy, owner_exclusive,
    output logic busy, done, fault,
    output logic [7:0] fault_code,
    output logic trial,
    output logic [31:0] completed_writes, completed_reads,
    output logic [30:0] mismatch_address,
    output logic [511:0] mismatch_expected, mismatch_actual,

    output logic line_valid,
    input logic line_ready,
    output logic line_write,
    output logic [30:0] line_address,
    output logic [511:0] line_wdata,
    input logic line_rsp_valid,
    output logic line_rsp_ready,
    input logic line_rsp_error,
    input logic [511:0] line_rdata,

    output logic retire_valid,
    input logic retire_ready,
    output logic [30:0] retire_last_write_address,
    input logic retire_rsp_valid,
    output logic retire_rsp_ready,
    input logic retire_rsp_ok,
    input logic [31:0] retire_ecc_status, retire_ecc_onoff, retire_ecc_irq_mask
);
    localparam logic [32:0] END_ADDR = {2'b0,BASE_ADDR} + {1'b0,SPAN_BYTES};
    localparam logic [30:0] LAST_ADDR = 31'(END_ADDR - 33'd64);
    typedef enum logic [2:0] {IDLE, LINE_REQUEST, LINE_RESPONSE, RETIRE_REQUEST,
                             RETIRE_RESPONSE, RESULT, QUARANTINE} state_t;
    state_t state;
    logic active, writing, retire_after_reads;
    logic request_pending, response_pending, retire_pending, retire_waiting;
    logic [30:0] cursor, final_write_address;
    logic [31:0] captured_seed, wait_cycles;
    logic pattern_valid, line_accept, line_complete, retire_accept, retire_complete;
    logic progress, fault_now;
    logic invalid_start_seed;
    logic [7:0] current_fault;
    logic [511:0] expected_data;

    initial begin
        if (SPAN_BYTES < 64 || SPAN_BYTES[5:0] != 0 || BASE_ADDR[5:0] != 0 ||
            END_ADDR > 33'h080000000 || TIMEOUT_CYCLES == 0)
            $fatal(1,"Capacity sweep needs aligned nonempty31-bit span and positive timeout");
    end
    rk_ddr_capacity_pattern pattern (
        .address(cursor), .seed(captured_seed), .trial(trial),
        .valid(pattern_valid), .data(expected_data)
    );
    assign start_ready = joint_rst_n && state == IDLE && !fault;
    assign busy = joint_rst_n && active;
    // Pending transactions remain stable after a fault until accepted/drained.
    assign line_valid = joint_rst_n && request_pending;
    assign line_write = writing;
    assign line_address = cursor;
    assign line_wdata = expected_data;
    assign line_rsp_ready = joint_rst_n && (response_pending || fault);
    assign retire_valid = joint_rst_n && retire_pending;
    assign retire_last_write_address = final_write_address;
    assign retire_rsp_ready = joint_rst_n && (retire_waiting || fault);
    assign line_accept = line_valid && line_ready;
    assign line_complete = line_rsp_valid && line_rsp_ready && response_pending && !request_pending;
    assign retire_accept = retire_valid && retire_ready;
    assign retire_complete = retire_rsp_valid && retire_rsp_ready && retire_waiting && !retire_pending;
    assign progress = line_accept || line_complete || retire_accept || retire_complete;

    always_comb begin
        invalid_start_seed = 1'b0;
`ifndef SYNTHESIS
        if ((^seed) === 1'bx) invalid_start_seed = 1'b1;
`endif
    end

    always_comb begin
        current_fault = 0;
        if (start_valid && start_ready && invalid_start_seed) current_fault = 1;
        else if ((active || (start_valid && start_ready)) &&
            (initialization_complete !== 1'b1 || calibration_complete !== 1'b1 ||
             ecc_monitor_healthy !== 1'b1 || owner_exclusive !== 1'b1)) current_fault = 1;
        else if (active && pattern_valid !== 1'b1) current_fault = 1;
        else if (active && line_rsp_valid !== 1'b0 &&
                 (line_rsp_valid !== 1'b1 || !response_pending || request_pending)) current_fault = 2;
        else if (active && retire_rsp_valid !== 1'b0 &&
                 (retire_rsp_valid !== 1'b1 || !retire_waiting || retire_pending)) current_fault = 3;
        else if (line_complete && line_rsp_error !== 1'b0) current_fault = 5;
        else if (line_complete && !writing && line_rdata !== expected_data) current_fault = 4;
        else if (retire_complete && (retire_rsp_ok !== 1'b1 || retire_ecc_status !== 0 ||
                 retire_ecc_onoff !== 1 || retire_ecc_irq_mask !== 3)) current_fault = 3;
        else if (active && (request_pending || response_pending || retire_pending || retire_waiting) &&
                 !progress && wait_cycles >= TIMEOUT_CYCLES-1) current_fault = 6;
        fault_now = current_fault != 0;
    end

    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            state <= IDLE; active <= 0; writing <= 1; trial <= 0;
            retire_after_reads <= 0; request_pending <= 0; response_pending <= 0;
            retire_pending <= 0; retire_waiting <= 0; cursor <= BASE_ADDR;
            final_write_address <= BASE_ADDR; captured_seed <= 0; wait_cycles <= 0;
            done <= 0; fault <= 0; fault_code <= 0;
            completed_writes <= 0; completed_reads <= 0;
            mismatch_address <= 0; mismatch_expected <= 0; mismatch_actual <= 0;
        end else begin
            if (line_accept) begin request_pending <= 0; response_pending <= 1; end
            if (line_complete) response_pending <= 0;
            if (retire_accept) begin retire_pending <= 0; retire_waiting <= 1; end
            if (retire_complete) retire_waiting <= 0;
            if (progress || !active) wait_cycles <= 0;
            else if (wait_cycles < TIMEOUT_CYCLES) wait_cycles <= wait_cycles+1'b1;

            if (!fault && fault_now) begin
                fault <= 1; fault_code <= current_fault; active <= 0; state <= QUARANTINE;
                if (current_fault == 4) begin
                    mismatch_address <= cursor; mismatch_expected <= expected_data; mismatch_actual <= line_rdata;
                end
            end
            if (!fault && !fault_now) begin
                case (state)
                    IDLE: if (start_valid && start_ready) begin
                        captured_seed <= seed; cursor <= BASE_ADDR; writing <= 1; trial <= 0;
                        active <= 1; request_pending <= 1; state <= LINE_REQUEST;
                    end
                    LINE_REQUEST: if (line_accept) state <= LINE_RESPONSE;
                    LINE_RESPONSE: if (line_complete) begin
                        if (writing) begin
                            completed_writes <= completed_writes+1'b1;
                            final_write_address <= cursor;
                            if ((!trial && cursor == LAST_ADDR) || (trial && cursor == BASE_ADDR)) begin
                                retire_after_reads <= 0; retire_pending <= 1; state <= RETIRE_REQUEST;
                            end else begin
                                cursor <= trial ? cursor-31'd64 : cursor+31'd64;
                                request_pending <= 1; state <= LINE_REQUEST;
                            end
                        end else begin
                            completed_reads <= completed_reads+1'b1;
                            if (cursor == LAST_ADDR) begin
                                retire_after_reads <= 1; retire_pending <= 1; state <= RETIRE_REQUEST;
                            end else begin
                                cursor <= cursor+31'd64; request_pending <= 1; state <= LINE_REQUEST;
                            end
                        end
                    end
                    RETIRE_REQUEST: if (retire_accept) state <= RETIRE_RESPONSE;
                    RETIRE_RESPONSE: if (retire_complete) begin
                        if (!retire_after_reads) begin
                            writing <= 0; cursor <= BASE_ADDR; request_pending <= 1; state <= LINE_REQUEST;
                        end else if (!trial) begin
                            trial <= 1; writing <= 1; cursor <= LAST_ADDR;
                            request_pending <= 1; state <= LINE_REQUEST;
                        end else begin
                            done <= 1; active <= 0; state <= RESULT;
                        end
                    end
                    RESULT, QUARANTINE: begin end
                    default: begin fault <= 1; fault_code <= 2; active <= 0; state <= QUARANTINE; end
                endcase
            end
        end
    end
endmodule
