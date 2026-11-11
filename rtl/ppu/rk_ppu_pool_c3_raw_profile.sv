// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Strict raw-command profile gate for the captured
// fp16_max_k2s2_c3_tail_h2w2 task only.
//
// Input words retain the RK 64-bit raw format:
//   {target[15:0], value[31:0], byte_offset[15:0]}.
// Only the two address relocations at QWORDs 13 and 20 vary. All other words,
// order, reserved bits, and final PC trigger are checked exactly. This module
// does not fetch commands or perform DMA; it publishes the source-bound
// 2x2/C3/FP16 DMA contract to a downstream engine after the complete stream.
module rk_ppu_pool_c3_raw_profile (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         cmd_valid,
    output logic         cmd_ready,
    input  logic [63:0]  cmd_data,
    input  logic         cmd_last,
    output logic         profile_valid,
    input  logic         profile_ready,
    output logic [31:0]  rdma_src_base,
    output logic [31:0]  ppu_dst_base,
    output logic [12:0]  rdma_input_width_m1,
    output logic [12:0]  rdma_input_height_m1,
    output logic [12:0]  rdma_input_channels_m1,
    output logic [31:0]  rdma_line_stride_bytes,
    output logic [31:0]  rdma_surface_stride_bytes,
    output logic [1:0]   rdma_format,
    output logic [12:0]  ppu_input_width_m1,
    output logic [12:0]  ppu_input_height_m1,
    output logic [12:0]  ppu_input_channels_m1,
    output logic [12:0]  ppu_output_width_m1,
    output logic [12:0]  ppu_output_height_m1,
    output logic [12:0]  ppu_output_channels_m1,
    output logic [3:0]   kernel_width_m1,
    output logic [3:0]   kernel_height_m1,
    output logic [3:0]   stride_width_m1,
    output logic [3:0]   stride_height_m1,
    output logic [14:0]  padding_cfg,
    output logic [1:0]   pool_method,
    output logic         ppu_flying,
    output logic         index_en,
    output logic [2:0]   use_cnt,
    output logic [31:0]  output_data_format,
    output logic [31:0]  output_surface_stride_bytes,
    output logic [3:0]   output_burst_len,
    output logic [31:0]  rdma_transfer_bytes,
    output logic [31:0]  output_write_bytes,
    output logic         busy,
    output logic         error,
    output logic [3:0]   error_code
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

    function automatic logic [15:0] target_for(input logic [4:0] index);
        begin
            case (index)
                5'd0, 5'd2, 5'd3, 5'd4, 5'd5, 5'd6, 5'd7, 5'd8,
                5'd9, 5'd10, 5'd11, 5'd12, 5'd13, 5'd14, 5'd15,
                5'd16: target_for = TARGET_PPU;
                5'd1, 5'd17, 5'd18, 5'd19, 5'd20, 5'd21, 5'd22,
                5'd23, 5'd24: target_for = TARGET_PPU_RDMA;
                5'd25: target_for = TARGET_PC;
                default: target_for = 16'hxxxx;
            endcase
        end
    endfunction

    function automatic logic [15:0] offset_for(input logic [4:0] index);
        begin
            case (index)
                5'd0:  offset_for = 16'h6004;
                5'd1:  offset_for = 16'h7004;
                5'd2:  offset_for = 16'h600c;
                5'd3:  offset_for = 16'h6010;
                5'd4:  offset_for = 16'h6014;
                5'd5:  offset_for = 16'h6018;
                5'd6:  offset_for = 16'h601c;
                5'd7:  offset_for = 16'h6020;
                5'd8:  offset_for = 16'h6024;
                5'd9:  offset_for = 16'h6034;
                5'd10: offset_for = 16'h6040;
                5'd11: offset_for = 16'h6044;
                5'd12: offset_for = 16'h6048;
                5'd13: offset_for = 16'h6070;
                5'd14: offset_for = 16'h607c;
                5'd15: offset_for = 16'h6084;
                5'd16: offset_for = 16'h60dc;
                5'd17: offset_for = 16'h700c;
                5'd18: offset_for = 16'h7010;
                5'd19: offset_for = 16'h7014;
                5'd20: offset_for = 16'h701c;
                5'd21: offset_for = 16'h7024;
                5'd22: offset_for = 16'h7028;
                5'd23: offset_for = 16'h7030;
                5'd24: offset_for = 16'h7008;
                5'd25: offset_for = 16'h0008;
                default: offset_for = 16'hxxxx;
            endcase
        end
    endfunction

    function automatic logic [31:0] value_for(input logic [4:0] index);
        begin
            case (index)
                5'd0, 5'd1: value_for = 32'h0000000e;
                5'd2, 5'd3, 5'd17, 5'd18: value_for = 32'h00000001;
                5'd4, 5'd7, 5'd19: value_for = 32'h00000002;
                5'd5, 5'd6, 5'd10, 5'd11, 5'd12: value_for = 32'h00000000;
                5'd8:  value_for = 32'h00000011;
                5'd9:  value_for = 32'h00110101;
                5'd14: value_for = 32'h00000010;
                5'd15: value_for = 32'h00000012;
                5'd16: value_for = 32'h00000003;
                5'd21: value_for = 32'h00000020;
                5'd22: value_for = 32'h00000040;
                5'd23: value_for = 32'h00000002;
                5'd24: value_for = 32'h00000001;
                5'd25: value_for = 32'h00000060;
                default: value_for = 32'hxxxxxxxx;
            endcase
        end
    endfunction

    function automatic logic address_word(input logic [4:0] index);
        address_word = (index == 5'd13) || (index == 5'd20);
    endfunction

    logic [15:0] expected_target;
    logic [15:0] expected_offset;
    logic [31:0] expected_value;
    logic [32:0] src_end;
    logic [32:0] dst_end;

    always_comb begin
        expected_target = target_for(word_index_q);
        expected_offset = offset_for(word_index_q);
        expected_value = value_for(word_index_q);
        src_end = {1'b0, src_base_q} + 33'd64;
        dst_end = {1'b0, dst_base_q} + 33'd16;
    end

    assign cmd_ready = rst_n && (state_q == ST_EMPTY || state_q == ST_COLLECT);
    assign profile_valid = rst_n && (state_q == ST_PUBLISH);
    assign busy = (state_q == ST_COLLECT) || (state_q == ST_PUBLISH);
    assign rdma_src_base = src_base_q;
    assign ppu_dst_base = dst_base_q;

    // The fixed fields below are the decoded outputs of the one admitted
    // captured command. They are not a general register programming API.
    assign rdma_input_width_m1          = 13'd1;
    assign rdma_input_height_m1         = 13'd1;
    assign rdma_input_channels_m1       = 13'd2;
    assign rdma_line_stride_bytes       = 32'd32;
    assign rdma_surface_stride_bytes    = 32'd64;
    assign rdma_format                  = 2'd2;
    assign ppu_input_width_m1            = 13'd1;
    assign ppu_input_height_m1           = 13'd1;
    assign ppu_input_channels_m1         = 13'd2;
    assign ppu_output_width_m1           = 13'd0;
    assign ppu_output_height_m1          = 13'd0;
    assign ppu_output_channels_m1        = 13'd2;
    assign kernel_width_m1               = 4'd1;
    assign kernel_height_m1              = 4'd1;
    assign stride_width_m1               = 4'd1;
    assign stride_height_m1              = 4'd1;
    assign padding_cfg                   = 15'd0;
    assign pool_method                   = 2'd1;
    assign ppu_flying                    = 1'b1;
    assign index_en                      = 1'b0;
    assign use_cnt                       = 3'd0;
    assign output_data_format            = 32'h00000012;
    assign output_surface_stride_bytes   = 32'd16;
    assign output_burst_len              = 4'd3;
    assign rdma_transfer_bytes           = 32'd64;
    assign output_write_bytes            = 32'd16;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state_q     <= ST_EMPTY;
            word_index_q<= 5'd0;
            src_base_q  <= 32'd0;
            dst_base_q  <= 32'd0;
            src_seen_q  <= 1'b0;
            dst_seen_q  <= 1'b0;
            error       <= 1'b0;
            error_code  <= 4'd0;
        end else begin
            if (cmd_valid && cmd_ready) begin
                if (cmd_data[63:48] !== expected_target ||
                    cmd_data[15:0] !== expected_offset) begin
                    error <= 1'b1;
                    error_code <= 4'd1;
                    state_q <= ST_FAULT;
                end else if (cmd_last !== (word_index_q == 5'd25)) begin
                    error <= 1'b1;
                    error_code <= 4'd1;
                    state_q <= ST_FAULT;
                end else if (address_word(word_index_q)) begin
                    if ((^cmd_data[47:16]) === 1'bx ||
                        cmd_data[47:16] == 32'd0 ||
                        cmd_data[19:16] != 4'd0) begin
                        error <= 1'b1;
                        error_code <= 4'd3;
                        state_q <= ST_FAULT;
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
                    error <= 1'b1;
                    error_code <= 4'd2;
                    state_q <= ST_FAULT;
                end else if (word_index_q == 5'd25) begin
                    if (!src_seen_q || !dst_seen_q ||
                        src_end > 33'h100000000 || dst_end > 33'h100000000 ||
                        (({1'b0, src_base_q} < dst_end) &&
                         ({1'b0, dst_base_q} < src_end))) begin
                        error <= 1'b1;
                        error_code <= 4'd3;
                        state_q <= ST_FAULT;
                    end else begin
                        state_q <= ST_PUBLISH;
                    end
                end else begin
                    word_index_q <= word_index_q + 1'b1;
                    state_q <= ST_COLLECT;
                end
            end

            if (profile_valid && profile_ready)
                state_q <= ST_DONE;
        end
    end
endmodule
