// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Strict raw-command profile for the two captured signed-INT8 C16 H2W2 tasks.
//
// Only QWORDs 13 (PPU_DST_BASE_ADDR) and 20 (PPU_RDMA_SRC_BASE_ADDR) are
// relocatable. The maximum and minimum captures differ only at QWORD 8
// (PPU_OPERATION_MODE_CFG); every other field is identical. All other words,
// order, reserved bits and the final PC trigger are checked exactly.
//
// This module does not fetch commands or perform DMA. It publishes the
// source-bound 64-byte input / 16-byte output contract to a downstream engine
// after the complete stream has been accepted.
module rk_ppu_pool_i8_k2s2_profile #(
    parameter bit MINIMUM = 1'b0
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        cmd_valid,
    output logic        cmd_ready,
    input  logic [63:0] cmd_data,
    input  logic        cmd_last,
    output logic        profile_valid,
    input  logic        profile_ready,
    output logic [31:0] rdma_src_base,
    output logic [31:0] ppu_dst_base,
    output logic [31:0] rdma_transfer_bytes,
    output logic [31:0] output_write_bytes,
    output logic        busy,
    output logic        error,
    output logic [3:0]  error_code
);
    localparam logic [15:0] TARGET_PPU      = 16'h4001;
    localparam logic [15:0] TARGET_PPU_RDMA = 16'h8001;
    localparam logic [15:0] TARGET_PC       = 16'h0081;

    typedef enum logic [2:0] {
        ST_EMPTY,
        ST_COLLECT,
        ST_PUBLISH,
        ST_DONE,
        ST_FAULT
    } state_t;

    state_t state_q;
    logic [4:0] word_index_q;
    logic [31:0] src_base_q;
    logic [31:0] dst_base_q;
    logic src_seen_q;
    logic dst_seen_q;
    logic [15:0] expected_target;
    logic [15:0] expected_offset;
    logic [31:0] expected_value;
    logic [32:0] src_end;
    logic [32:0] dst_end;

    // QWORD i is one of the fixed capture fields, the final task tail, or one
    // of the two relocations. Values are taken from the pinned fixtures.
    function automatic logic [15:0] target_for(input logic [4:0] index);
        case (index)
            5'd0, 5'd2, 5'd3, 5'd4, 5'd5, 5'd6, 5'd7, 5'd8,
            5'd9, 5'd10, 5'd11, 5'd12, 5'd13, 5'd14, 5'd15, 5'd16:
                target_for = TARGET_PPU;
            5'd1, 5'd17, 5'd18, 5'd19, 5'd20, 5'd21, 5'd22, 5'd23, 5'd24:
                target_for = TARGET_PPU_RDMA;
            5'd25: target_for = TARGET_PC;
            default: target_for = 16'hxxxx;
        endcase
    endfunction

    function automatic logic [15:0] offset_for(input logic [4:0] index);
        case (index)
            5'd0: offset_for = 16'h6004; // PPU_S_POINTER
            5'd1: offset_for = 16'h7004; // PPU_RDMA_S_POINTER
            5'd2: offset_for = 16'h600c; // PPU_DATA_CUBE_IN_WIDTH
            5'd3: offset_for = 16'h6010; // PPU_DATA_CUBE_IN_HEIGHT
            5'd4: offset_for = 16'h6014; // PPU_DATA_CUBE_IN_CHANNEL
            5'd5: offset_for = 16'h6018; // PPU_DATA_CUBE_OUT_WIDTH
            5'd6: offset_for = 16'h601c; // PPU_DATA_CUBE_OUT_HEIGHT
            5'd7: offset_for = 16'h6020; // PPU_DATA_CUBE_OUT_CHANNEL
            5'd8: offset_for = 16'h6024; // PPU_OPERATION_MODE_CFG
            5'd9: offset_for = 16'h6034; // PPU_POOLING_KERNEL_CFG
            5'd10: offset_for = 16'h6040; // PPU_POOLING_PADDING_CFG
            5'd11: offset_for = 16'h6044; // PPU_PADDING_VALUE_1_CFG
            5'd12: offset_for = 16'h6048; // PPU_PADDING_VALUE_2_CFG
            5'd13: offset_for = 16'h6070; // PPU_DST_BASE_ADDR (relocated)
            5'd14: offset_for = 16'h607c; // PPU_DST_SURF_STRIDE
            5'd15: offset_for = 16'h6084; // PPU_DATA_FORMAT
            5'd16: offset_for = 16'h60dc; // PPU_MISC_CTRL
            5'd17: offset_for = 16'h700c; // PPU_RDMA_CUBE_IN_WIDTH
            5'd18: offset_for = 16'h7010; // PPU_RDMA_CUBE_IN_HEIGHT
            5'd19: offset_for = 16'h7014; // PPU_RDMA_CUBE_IN_CHANNEL
            5'd20: offset_for = 16'h701c; // PPU_RDMA_SRC_BASE_ADDR (relocated)
            5'd21: offset_for = 16'h7024; // PPU_RDMA_SRC_LINE_STRIDE
            5'd22: offset_for = 16'h7028; // PPU_RDMA_SRC_SURF_STRIDE
            5'd23: offset_for = 16'h7030; // PPU_RDMA_DATA_FORMAT
            5'd24: offset_for = 16'h7008; // PPU_RDMA_OPERATION_ENABLE
            5'd25: offset_for = 16'h0008; // PC: terminal task boundary
            default: offset_for = 16'hxxxx;
        endcase
    endfunction

    function automatic logic [31:0] value_for(input logic [4:0] index);
        case (index)
            5'd0, 5'd1: value_for = 32'h0000000e;
            5'd2, 5'd3: value_for = 32'h00000001;
            5'd4: value_for = 32'h0000000f;   // 16 INT8 lanes
            5'd5, 5'd6: value_for = 32'h00000000;
            5'd7: value_for = 32'h0000000f;
            5'd8: value_for = MINIMUM ? 32'h00000012 : 32'h00000011;
            5'd9: value_for = 32'h00110101;   // 2x2 kernel, stride 2/2
            5'd10, 5'd11, 5'd12: value_for = 32'h00000000;
            5'd14: value_for = 32'h00000010;
            5'd15: value_for = 32'h00000010;  // INT8 data format
            5'd16: value_for = 32'h00000003;
            5'd17, 5'd18: value_for = 32'h00000001;
            5'd19: value_for = 32'h0000000f;
            5'd21: value_for = 32'h00000020;
            5'd22: value_for = 32'h00000040;
            5'd23: value_for = 32'h00000001;
            5'd24: value_for = 32'h00000001;
            5'd25: value_for = 32'h00000060;  // 26 QWORDs = 0x60 bytes
            default: value_for = 32'hxxxxxxxx;
        endcase
    endfunction

    always_comb begin
        expected_target = target_for(word_index_q);
        expected_offset = offset_for(word_index_q);
        expected_value = value_for(word_index_q);
        src_end = {1'b0, src_base_q} + 33'd64;
        dst_end = {1'b0, dst_base_q} + 33'd16;
    end

    assign cmd_ready = rst_n && !error && (state_q == ST_EMPTY || state_q == ST_COLLECT);
    assign busy = rst_n && (state_q == ST_COLLECT || state_q == ST_PUBLISH);
    assign error = rst_n && state_q == ST_FAULT;
    assign profile_valid = rst_n && !error && state_q == ST_PUBLISH;
    assign rdma_src_base = src_base_q;
    assign ppu_dst_base = dst_base_q;
    assign rdma_transfer_bytes = 32'd64;
    assign output_write_bytes = 32'd16;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state_q <= ST_EMPTY;
            word_index_q <= 5'd0;
            src_base_q <= 32'd0;
            dst_base_q <= 32'd0;
            src_seen_q <= 1'b0;
            dst_seen_q <= 1'b0;
            error_code <= 4'd0;
        end else if (state_q == ST_FAULT) begin
            // Sticky until reset.
        end else if (cmd_valid && cmd_ready) begin
            if (cmd_data[63:48] !== expected_target ||
                cmd_data[15:0] !== expected_offset) begin
                state_q <= ST_FAULT;
                error_code <= word_index_q >= 5'd25 ? 4'd3 : 4'd1;
            end else if (cmd_last !== (word_index_q == 5'd25)) begin
                state_q <= ST_FAULT;
                error_code <= 4'd1;
            end else if (word_index_q == 5'd13 || word_index_q == 5'd20) begin
                // Both addresses are full 32-bit device addresses carried in
                // bits [47:16]. Zero is not a legal operand address; the actual
                // aperture and overlap checks happen in the DMA endpoint, which
                // knows the configured BASE/BYTES.
                if ((^cmd_data[47:16]) === 1'bx || cmd_data[47:16] == 32'd0) begin
                    state_q <= ST_FAULT;
                    error_code <= 4'd2;
                end else begin
                    if (word_index_q == 5'd13) begin
                        dst_base_q <= cmd_data[47:16];
                        dst_seen_q <= 1'b1;
                    end else begin
                        src_base_q <= cmd_data[47:16];
                        src_seen_q <= 1'b1;
                    end
                    word_index_q <= word_index_q + 1'b1;
                    state_q <= ST_COLLECT;
                end
            end else if (cmd_data[47:16] !== expected_value) begin
                state_q <= ST_FAULT;
                error_code <= 4'd1;
            end else if (word_index_q == 5'd25) begin
                if (!src_seen_q || !dst_seen_q ||
                    src_end > 33'h100000000 || dst_end > 33'h100000000 ||
                    (({1'b0, src_base_q} < dst_end) &&
                     ({1'b0, dst_base_q} < src_end))) begin
                    state_q <= ST_FAULT;
                    error_code <= 4'd2;
                end else begin
                    state_q <= ST_PUBLISH;
                end
            end else begin
                word_index_q <= word_index_q + 1'b1;
                state_q <= ST_COLLECT;
            end
        end else if (profile_valid && profile_ready) begin
            state_q <= ST_DONE;
        end
    end
endmodule
