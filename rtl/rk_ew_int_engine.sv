// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Serial memory-to-memory integer elementwise engine for the captured ew-int
// family. One outstanding 16-bit memory transaction; a response is required for
// both reads and writes (same contract as the frozen rk_ew_engine).
//
// Addressing is the captured native-dtype contiguous lane order:
//   lane i: src_a + i*in_item, src_b + i*in_item, dst + i*out_item
// For the captured C1WC2 surface streams width==1 is required by
// rk_ew_int_regs, and the source pack_c1wc2() rule then reduces exactly to this
// contiguous order ((channel//atom)*1*atom + channel%atom == channel), so the
// surface padding bytes are never touched (the capture mask excludes them).
//
// The INT32-MUL signed-INT16 operand limitation from the captured stream is
// applied here: only the low signed halfword of the EW operand is used.
// 1-byte destinations use a read-modify-write halfword (the BRAM has no byte
// strobes); 2/4-byte destinations are aligned by the decoder contract.
// Errors: 4 invalid config/address, 5 memory bus error, 6 shape, 8 timeout.
// This is additive RTL; rtl/rk_ew_engine.sv (FP16) is untouched.
module rk_ew_int_engine #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic        clk, rst_n,
    input  logic        cfg_valid,
    output logic        cfg_ready,
    input  logic [2:0]  cfg_op,        // 0 ADD, 1 MINUS, 2 MUL, 3 MAX, 4 MIN
    input  logic [1:0]  cfg_dtype,     // ALU result dtype: 0 INT8, 1 INT16, 2 INT32
    input  logic [1:0]  cfg_in_item,   // 0 -> 1 byte, 1 -> 2 bytes, 2 -> 4 bytes
    input  logic [1:0]  cfg_out_item,
    input  logic [15:0] cfg_count,     // logical lanes, 1..64000
    input  logic [31:0] cfg_a, cfg_b, cfg_dst,
    output logic        busy, done, error,
    output logic [7:0]  error_code,
    output logic        mem_req_valid,
    input  logic        mem_req_ready,
    output logic        mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input  logic        mem_rsp_valid,
    output logic        mem_rsp_ready,
    input  logic [15:0] mem_rsp_rdata,
    input  logic        mem_rsp_error
);
    typedef enum logic [3:0] {
        IDLE, A_REQ, A_WAIT, B_REQ, B_WAIT, D_REQ, D_WAIT,
        C_REQ, C_WAIT, W_REQ, W_WAIT
    } state_t;
    state_t state;

    logic [31:0] a_addr, b_addr, dst_addr;
    logic [15:0] remaining;
    logic [2:0] op;
    logic [1:0] dtype, in_item, out_item;
    logic [1:0] wi;
    logic [15:0] a_word0, a_word1, b_word0, b_word1, d_word;
    logic signed [31:0] result;
    logic [31:0] stalled_cycles;
    logic memory_state, progress;

    logic alu_in_valid, alu_in_ready, alu_out_valid, alu_out_ready;
    logic signed [31:0] alu_result;
    logic signed [31:0] operand_a, operand_b;
    logic [1:0] wwords, awords, bwords;
    logic mul_s16;
    logic [15:0] wdata;
    logic [7:0] a_byte, b_byte;

    initial begin
        if (TIMEOUT_CYCLES == 0) $fatal(1, "TIMEOUT_CYCLES must be positive");
    end

    assign cfg_ready = (state == IDLE) && !error;
    assign busy = (state != IDLE);
    assign wwords = (out_item == 2'd2) ? 2'd2 : 2'd1;
    assign awords = (in_item == 2'd2) ? 2'd2 : 2'd1;
    // Captured INT32-MUL limitation: the EW MUL operand decodes as signed INT16.
    assign mul_s16 = (op == 3'd2) && (dtype == 2'd2);
    assign bwords = mul_s16 ? 2'd1 : awords;

    assign alu_in_valid = (state == C_REQ);
    assign alu_out_ready = (state == C_WAIT);
    assign memory_state = (state == A_REQ) || (state == A_WAIT) ||
        (state == B_REQ) || (state == B_WAIT) ||
        (state == D_REQ) || (state == D_WAIT) ||
        (state == W_REQ) || (state == W_WAIT);
    assign progress = (mem_req_valid && mem_req_ready) ||
                      (mem_rsp_valid && mem_rsp_ready);

    rk_int_alu alu (
        .clk(clk), .rst_n(rst_n),
        .in_valid(alu_in_valid), .in_ready(alu_in_ready),
        .in_op(op), .in_dtype(dtype),
        .in_a(operand_a), .in_b(operand_b),
        .out_valid(alu_out_valid), .out_ready(alu_out_ready),
        .out_data(alu_result)
    );

    // 1-byte sources use a halfword read: select the addressed byte lane.
    assign a_byte = a_addr[0] ? a_word0[15:8] : a_word0[7:0];
    assign b_byte = b_addr[0] ? b_word0[15:8] : b_word0[7:0];

    // Sign-extend the captured little-endian native-dtype operands.
    always_comb begin
        operand_a = 32'sd0;
        operand_b = 32'sd0;
        case (in_item)
            2'd0: operand_a = {{24{a_byte[7]}}, a_byte};
            2'd1: operand_a = {{16{a_word0[15]}}, a_word0[15:0]};
            default: operand_a = {a_word1, a_word0};
        endcase
        if (mul_s16) operand_b = {{16{b_word0[15]}}, b_word0[15:0]};
        else case (in_item)
            2'd0: operand_b = {{24{b_byte[7]}}, b_byte};
            2'd1: operand_b = {{16{b_word0[15]}}, b_word0[15:0]};
            default: operand_b = {b_word1, b_word0};
        endcase
    end

    // Destination write data and the 1-byte read-modify-write merge.
    always_comb begin
        wdata = 16'd0;
        case (out_item)
            2'd0: wdata = dst_addr[0] ? {result[7:0], d_word[7:0]}
                                      : {d_word[15:8], result[7:0]};
            2'd1: wdata = result[15:0];
            default: wdata = wi[0] ? result[31:16] : result[15:0];
        endcase
    end

    always_comb begin
        mem_req_valid = 1'b0;
        mem_req_write = 1'b0;
        mem_req_addr = 32'd0;
        mem_req_wdata = wdata;
        mem_rsp_ready = 1'b0;
        case (state)
            A_REQ: begin
                mem_req_valid = 1'b1;
                mem_req_addr = {a_addr[31:1], 1'b0} + {30'd0, wi[0], 1'b0};
            end
            B_REQ: begin
                mem_req_valid = 1'b1;
                mem_req_addr = {b_addr[31:1], 1'b0} + {30'd0, wi[0], 1'b0};
            end
            D_REQ: begin
                mem_req_valid = 1'b1;
                mem_req_addr = {dst_addr[31:1], 1'b0};
            end
            W_REQ: begin
                mem_req_valid = 1'b1;
                mem_req_write = 1'b1;
                mem_req_addr = (out_item == 2'd0) ? {dst_addr[31:1], 1'b0}
                                                  : {dst_addr[31:1], 1'b0} +
                                                    {30'd0, wi[0], 1'b0};
            end
            A_WAIT, B_WAIT, D_WAIT, W_WAIT: mem_rsp_ready = 1'b1;
            default: begin end
        endcase
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state <= IDLE;
            done <= 1'b0;
            error <= 1'b0;
            error_code <= 8'd0;
            a_addr <= 32'd0; b_addr <= 32'd0; dst_addr <= 32'd0;
            remaining <= 16'd0; op <= 3'd0; dtype <= 2'd0;
            in_item <= 2'd0; out_item <= 2'd0;
            wi <= 2'd0; a_word0 <= 16'd0; a_word1 <= 16'd0;
            b_word0 <= 16'd0; b_word1 <= 16'd0; d_word <= 16'd0;
            result <= 32'd0; stalled_cycles <= 32'd0;
        end else begin
            done <= 1'b0;
            if (!memory_state || progress) stalled_cycles <= 32'd0;
            else stalled_cycles <= stalled_cycles + 32'd1;
            case (state)
                IDLE: if (cfg_valid && cfg_ready) begin
                    if ((cfg_count == 16'd0) || (cfg_count > 16'd64000) ||
                        (cfg_op > 3'd4) || (cfg_in_item > 2'd2) ||
                        (cfg_out_item > 2'd2)) begin
                        error <= 1'b1;
                        error_code <= 8'd6;
                    end else begin
                        a_addr <= cfg_a;
                        b_addr <= cfg_b;
                        dst_addr <= cfg_dst;
                        remaining <= cfg_count;
                        op <= cfg_op;
                        dtype <= cfg_dtype;
                        in_item <= cfg_in_item;
                        out_item <= cfg_out_item;
                        wi <= 2'd0;
                        state <= A_REQ;
                    end
                end
                A_REQ: if (mem_req_ready) state <= A_WAIT;
                A_WAIT: if (mem_rsp_valid) begin
                    if (wi[0]) a_word1 <= mem_rsp_rdata;
                    else a_word0 <= mem_rsp_rdata;
                    if (wi == awords - 2'd1) begin
                        wi <= 2'd0;
                        state <= B_REQ;
                    end else begin
                        wi <= wi + 1'b1;
                        state <= A_REQ;
                    end
                end
                B_REQ: if (mem_req_ready) state <= B_WAIT;
                B_WAIT: if (mem_rsp_valid) begin
                    if (wi[0]) b_word1 <= mem_rsp_rdata;
                    else b_word0 <= mem_rsp_rdata;
                    if (wi == bwords - 2'd1) begin
                        wi <= 2'd0;
                        if (out_item == 2'd0) state <= D_REQ;
                        else state <= C_REQ;
                    end else begin
                        wi <= wi + 1'b1;
                        state <= B_REQ;
                    end
                end
                D_REQ: if (mem_req_ready) state <= D_WAIT;
                D_WAIT: if (mem_rsp_valid) begin
                    d_word <= mem_rsp_rdata;
                    state <= C_REQ;
                end
                C_REQ: if (alu_in_ready) state <= C_WAIT;
                C_WAIT: if (alu_out_valid) begin
                    result <= alu_result;
                    wi <= 2'd0;
                    state <= W_REQ;
                end
                W_REQ: if (mem_req_ready) state <= W_WAIT;
                W_WAIT: if (mem_rsp_valid) begin
                    if (wi == wwords - 2'd1) begin
                        if (remaining == 16'd1) begin
                            state <= IDLE;
                            done <= 1'b1;
                        end else begin
                            remaining <= remaining - 16'd1;
                            a_addr <= a_addr + (32'd1 << in_item);
                            b_addr <= b_addr + (32'd1 << in_item);
                            dst_addr <= dst_addr + (32'd1 << out_item);
                            wi <= 2'd0;
                            state <= A_REQ;
                        end
                    end else begin
                        wi <= wi + 1'b1;
                        state <= W_REQ;
                    end
                end
                default: begin
                    state <= IDLE;
                    error <= 1'b1;
                    error_code <= 8'd6;
                end
            endcase
            // Fault overrides have priority over normal completion/advancement.
            if (mem_rsp_valid && mem_rsp_ready && mem_rsp_error) begin
                state <= IDLE;
                done <= 1'b0;
                error <= 1'b1;
                error_code <= 8'd5;
            end else if (memory_state && !progress &&
                         (stalled_cycles >= TIMEOUT_CYCLES - 1)) begin
                state <= IDLE;
                done <= 1'b0;
                error <= 1'b1;
                error_code <= 8'd8;
            end
        end
    end
endmodule
