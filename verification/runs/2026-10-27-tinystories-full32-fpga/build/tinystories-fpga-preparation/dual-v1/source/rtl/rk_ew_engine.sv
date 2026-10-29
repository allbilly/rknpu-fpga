// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Serial memory-to-memory DPU EW slice. One outstanding memory transaction.
// A response is required for BOTH reads and writes. Responses may be delayed,
// but must not appear before the cycle after request acceptance. Faults latch;
// reset this core AND its memory adapter together before resuming after a fault.
module rk_ew_engine #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, rst_n,
    input logic cfg_valid,
    output logic cfg_ready,
    input logic [1:0] cfg_op,
    input logic [16:0] cfg_count,
    input logic [31:0] cfg_a, cfg_b, cfg_dst,
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
    typedef enum logic [3:0] {
        IDLE, A_REQ, A_WAIT, B_REQ, B_WAIT, CALC_REQ, CALC_WAIT, W_REQ, W_WAIT
    } state_t;
    state_t state;
    logic [31:0] a_addr, b_addr, dst_addr;
    logic [16:0] remaining;
    logic [1:0] op;
    logic [15:0] a_value, b_value, result;
    logic alu_in_valid, alu_in_ready, alu_out_valid, alu_out_ready;
    logic [15:0] alu_result;
    logic memory_state, progress;
    logic [31:0] stalled_cycles;

    initial begin
        if (TIMEOUT_CYCLES == 0) $fatal(1, "TIMEOUT_CYCLES must be positive");
    end

    assign cfg_ready = (state == IDLE) && !error;
    assign busy = (state != IDLE);
    assign alu_in_valid = (state == CALC_REQ);
    assign alu_out_ready = (state == CALC_WAIT);
    assign memory_state = (state == A_REQ) || (state == A_WAIT) ||
        (state == B_REQ) || (state == B_WAIT) || (state == W_REQ) || (state == W_WAIT);
    assign progress = (mem_req_valid && mem_req_ready) || (mem_rsp_valid && mem_rsp_ready);
    rk_fp16_alu alu (
        .clk(clk), .rst_n(rst_n), .in_valid(alu_in_valid), .in_ready(alu_in_ready),
        .in_op(op), .in_a(a_value), .in_b(b_value),
        .out_valid(alu_out_valid), .out_ready(alu_out_ready), .out_data(alu_result)
    );

    always_comb begin
        mem_req_valid = 0;
        mem_req_write = 0;
        mem_req_addr = 0;
        mem_req_wdata = result;
        mem_rsp_ready = 0;
        case (state)
            A_REQ: begin mem_req_valid = 1; mem_req_addr = a_addr; end
            B_REQ: begin mem_req_valid = 1; mem_req_addr = b_addr; end
            W_REQ: begin mem_req_valid = 1; mem_req_addr = dst_addr; mem_req_write = 1; end
            A_WAIT, B_WAIT, W_WAIT: mem_rsp_ready = 1;
            default: begin end
        endcase
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state <= IDLE; done <= 0; error <= 0; error_code <= 0;
            a_addr <= 0; b_addr <= 0; dst_addr <= 0; remaining <= 0; op <= 0;
            a_value <= 0; b_value <= 0; result <= 0; stalled_cycles <= 0;
        end else begin
            done <= 0;
            if (!memory_state || progress) stalled_cycles <= 0;
            else stalled_cycles <= stalled_cycles + 1;
            case (state)
                IDLE: if (cfg_valid && cfg_ready) begin
                    if ((cfg_count == 0) || (cfg_count > 64000) || (cfg_op == 3)) begin
                        error <= 1; error_code <= 8'd6;
                    end else begin
                        a_addr <= cfg_a; b_addr <= cfg_b; dst_addr <= cfg_dst;
                        remaining <= cfg_count; op <= cfg_op; state <= A_REQ;
                    end
                end
                A_REQ: if (mem_req_ready) state <= A_WAIT;
                A_WAIT: if (mem_rsp_valid) begin a_value <= mem_rsp_rdata; state <= B_REQ; end
                B_REQ: if (mem_req_ready) state <= B_WAIT;
                B_WAIT: if (mem_rsp_valid) begin b_value <= mem_rsp_rdata; state <= CALC_REQ; end
                CALC_REQ: if (alu_in_ready) state <= CALC_WAIT;
                CALC_WAIT: if (alu_out_valid) begin result <= alu_result; state <= W_REQ; end
                W_REQ: if (mem_req_ready) state <= W_WAIT;
                W_WAIT: if (mem_rsp_valid) begin
                    if (remaining == 1) begin state <= IDLE; done <= 1; end
                    else begin
                        remaining <= remaining - 1;
                        a_addr <= a_addr + 2; b_addr <= b_addr + 2; dst_addr <= dst_addr + 2;
                        state <= A_REQ;
                    end
                end
                default: begin state <= IDLE; error <= 1; error_code <= 8'd6; end
            endcase
            // These overrides have priority over normal completion/advancement.
            if (mem_rsp_valid && mem_rsp_ready && mem_rsp_error) begin
                state <= IDLE; done <= 0; error <= 1; error_code <= 8'd5;
            end else if (memory_state && !progress && (stalled_cycles >= TIMEOUT_CYCLES - 1)) begin
                state <= IDLE; done <= 0; error <= 1; error_code <= 8'd8;
            end
        end
    end
endmodule
