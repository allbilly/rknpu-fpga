// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One bootstrap per whole-transaction reset. A completed bootstrap is an epoch
// fact, not memory-ready/job admission or a CE/UE recovery result.
module rk_mig_fi_startup_disarm #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, joint_rst_n, sequence_ready, calib_complete, memory_quiescent,
    input logic fi_owner_granted, port_idle,
    input logic guard_ready, guard_rsp_valid,
    input logic [1:0] guard_rsp_response,
    input logic guard_busy, guard_quarantine, guard_mask_disarmed, arbiter_fault,
    output logic owner_request, req_valid,
    output logic [31:0] req_address,
    output logic rsp_ready, startup_complete, fault,
    output logic [7:0] fault_code
);
    typedef enum logic [2:0] {WAIT_READY, SEND, RESPONSE, VERIFY, DONE, FAILED} state_t;
    state_t state;
    logic [1:0] word_index;
    logic [31:0] cycles;
    initial if (TIMEOUT_CYCLES == 0) $fatal(1, "FI startup timeout must be positive");
    assign owner_request = joint_rst_n && state != DONE;
    assign req_valid = joint_rst_n && state == SEND && !fault;
    assign rsp_ready = joint_rst_n && state != DONE;
    assign startup_complete = joint_rst_n && state == DONE && !fault;
    always_comb begin
        case (word_index)
            0: req_address = 32'h300;
            1: req_address = 32'h304;
            default: req_address = 32'h380;
        endcase
    end
    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            state <= WAIT_READY; word_index <= 0; cycles <= 0;
            fault <= 0; fault_code <= 0;
        end else if (state != DONE && state != FAILED) begin
            if (state == WAIT_READY) cycles <= 0;
            else if (cycles < TIMEOUT_CYCLES-1) cycles <= cycles + 1'b1;
            if (guard_quarantine !== 1'b0 || arbiter_fault !== 1'b0) begin
                state <= FAILED; fault <= 1; fault_code <= 8'd1;
            end else if (state != WAIT_READY &&
                         (sequence_ready !== 1'b1 || calib_complete !== 1'b1 ||
                          memory_quiescent !== 1'b1 || fi_owner_granted !== 1'b1)) begin
                state <= FAILED; fault <= 1; fault_code <= 8'd2;
            end else if (state != WAIT_READY && cycles >= TIMEOUT_CYCLES-1 &&
                         !(state == RESPONSE && guard_rsp_valid === 1'b1) &&
                         !(state == VERIFY && guard_busy === 1'b0 && guard_mask_disarmed === 1'b1 && port_idle === 1'b1)) begin
                state <= FAILED; fault <= 1; fault_code <= 8'd3;
            end else begin
                case (state)
                    WAIT_READY: if (sequence_ready === 1'b1 && calib_complete === 1'b1 &&
                                    memory_quiescent === 1'b1 && fi_owner_granted === 1'b1 &&
                                    guard_busy === 1'b0 && port_idle === 1'b1) begin
                        state <= SEND; cycles <= 0;
                    end
                    SEND: if (req_valid && guard_ready) begin state <= RESPONSE; cycles <= 0; end
                    RESPONSE: if (guard_rsp_valid && rsp_ready) begin
                        if (guard_rsp_response !== 2'b00) begin
                            state <= FAILED; fault <= 1; fault_code <= 8'd4;
                        end else begin
                            cycles <= 0;
                            if (word_index == 2) state <= VERIFY;
                            else begin word_index <= word_index + 1'b1; state <= SEND; end
                        end
                    end
                    VERIFY: if (guard_busy === 1'b0 && guard_mask_disarmed === 1'b1 && port_idle === 1'b1)
                        state <= DONE;
                    default: begin state <= FAILED; fault <= 1; fault_code <= 8'd5; end
                endcase
            end
        end
    end
endmodule
