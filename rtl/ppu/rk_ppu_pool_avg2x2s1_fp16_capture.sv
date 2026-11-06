// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Capture-bounded PPU candidate for fp16_avg_k2s1_valid_c8_h4w4 only.
//
// This leaf has no PPU register decode, RDMA/DMA, AXI, or top-level admission.
// The supported replay is the captured finite FP16 C8/H4/W4 surface, valid
// 2x2/stride-1 average, INDEX_EN=0 and USE_CNT=0. Its source contract is
// float32 accumulation/mean followed by FP16 conversion, atol=0.0625. The
// captured input is finite and the device result is exact for this fixture.
// No generic PPU, IEEE special-value, or non-captured rounding claim is made.
module rk_ppu_pool_avg2x2s1_fp16_capture (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         in_valid,
    output logic         in_ready,
    input  logic [127:0] in_atom,
    output logic         out_valid,
    input  logic         out_ready,
    output logic [127:0] out_atom,
    output logic         out_last
);
    localparam int unsigned IN_W = 4;
    localparam int unsigned COL_W = 2;
    localparam int unsigned ROW_W = 2;

    logic [127:0] line [0:1][0:IN_W-1];
    logic         cur_sel;
    logic [ROW_W-1:0] row;
    logic [COL_W-1:0] col;
    logic [COL_W-1:0] prev_col;
    logic [127:0] curr_prev;
    logic [127:0] window_average;
    logic [127:0] out_atom_q;
    logic         out_valid_q;
    logic         out_last_q;
    logic         frame_done_q;

    // A binary16 finite value is represented in signed units of 2^-24.
    // This is an exact aligned finite-input sum, not a special-value FPU.
    function automatic logic signed [42:0] fp16_to_units(input logic [15:0] value);
        logic [42:0] magnitude;
        logic [10:0] significand;
        begin
            if (value[14:10] == 5'd0) begin
                magnitude = {{33{1'b0}}, value[9:0]};
            end else begin
                significand = {1'b1, value[9:0]};
                magnitude = {{32{1'b0}}, significand} << (value[14:10] - 1'b1);
            end
            fp16_to_units = value[15] ? -$signed(magnitude) : $signed(magnitude);
        end
    endfunction

    // Round the exact four-term finite sum divided by four to binary16 using
    // nearest/even. The 2^-24 input quantum and factor-of-four divisor are
    // pinned to this captured source/reference contract; exceptional encodings
    // deliberately produce unknown simulation data rather than an IEEE claim.
    function automatic logic [15:0] fp16_average4(
        input logic [15:0] a,
        input logic [15:0] b,
        input logic [15:0] c,
        input logic [15:0] d
    );
        logic signed [42:0] total;
        logic [42:0] magnitude;
        logic [11:0] significand;
        logic sign_bit;
        logic guard_bit;
        logic sticky_bit;
        integer highest;
        integer shift_amount;
        integer exponent_field;
        integer bit_index;
        begin
            if ((a[14:10] == 5'h1f) || (b[14:10] == 5'h1f) ||
                (c[14:10] == 5'h1f) || (d[14:10] == 5'h1f)) begin
                fp16_average4 = 16'hxxxx;
            end else begin
                total = fp16_to_units(a) + fp16_to_units(b) +
                        fp16_to_units(c) + fp16_to_units(d);
                sign_bit = total[42];
                magnitude = sign_bit ? $unsigned(-total) : $unsigned(total);
                if (magnitude == 43'b0) begin
                    fp16_average4 = 16'h0000;
                end else begin
                    highest = 0;
                    for (bit_index = 0; bit_index < 43; bit_index = bit_index + 1) begin
                        if (magnitude[bit_index]) highest = bit_index;
                    end
                    if (highest < 12) begin
                        // Subnormal destination quantum is 2^-24; mean is
                        // magnitude/4 such quanta. The two discarded bits
                        // suffice for exact nearest/even rounding.
                        significand = 12'(magnitude >> 2);
                        guard_bit = magnitude[1];
                        sticky_bit = magnitude[0];
                        if (guard_bit && (sticky_bit || significand[0]))
                            significand = significand + 1'b1;
                        if (significand >= 12'd1024)
                            fp16_average4 = {sign_bit, 5'd1, 10'd0};
                        else
                            fp16_average4 = {sign_bit, 5'd0, significand[9:0]};
                    end else begin
                        shift_amount = highest - 10;
                        significand = 12'(magnitude >> shift_amount);
                        guard_bit = magnitude[shift_amount - 1];
                        sticky_bit = 1'b0;
                        for (bit_index = 0; bit_index < 43; bit_index = bit_index + 1) begin
                            if (bit_index < shift_amount - 1)
                                sticky_bit = sticky_bit | magnitude[bit_index];
                        end
                        if (guard_bit && (sticky_bit || significand[0]))
                            significand = significand + 1'b1;
                        exponent_field = highest - 11;
                        if (significand[11]) begin
                            significand = significand >> 1;
                            exponent_field = exponent_field + 1;
                        end
                        if (exponent_field >= 31)
                            fp16_average4 = 16'hxxxx;
                        else
                            fp16_average4 = {sign_bit, exponent_field[4:0], significand[9:0]};
                    end
                end
            end
        end
    endfunction

    assign prev_col = (col == 2'b00) ? 2'b00 : col - 1'b1;

    always_comb begin
        for (integer lane = 0; lane < 8; lane = lane + 1) begin
            window_average[lane*16 +: 16] = fp16_average4(
                line[~cur_sel][prev_col][lane*16 +: 16],
                line[~cur_sel][col][lane*16 +: 16],
                curr_prev[lane*16 +: 16],
                in_atom[lane*16 +: 16]
            );
        end
    end

    assign in_ready  = rst_n && !frame_done_q && (!out_valid_q || out_ready);
    assign out_valid = out_valid_q;
    assign out_atom  = out_atom_q;
    assign out_last  = out_last_q;

    wire emit = (row != 2'b00) && (col != 2'b00);

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            cur_sel      <= 1'b0;
            row          <= 2'b00;
            col          <= 2'b00;
            curr_prev    <= 128'b0;
            out_atom_q   <= 128'b0;
            out_valid_q  <= 1'b0;
            out_last_q   <= 1'b0;
            frame_done_q <= 1'b0;
        end else begin
            if (out_valid_q && out_ready) begin
                out_valid_q <= 1'b0;
                out_last_q  <= 1'b0;
            end
            if (in_valid && in_ready) begin
                line[cur_sel][col] <= in_atom;
                curr_prev <= in_atom;
                if (emit) begin
                    out_valid_q <= 1'b1;
                    out_atom_q  <= window_average;
                    out_last_q  <= (row == 2'd3) && (col == 2'd3);
                end
                if ((row == 2'd3) && (col == 2'd3)) begin
                    frame_done_q <= 1'b1;
                end else if (col == 2'd3) begin
                    col <= 2'b00;
                    row <= row + 1'b1;
                    cur_sel <= ~cur_sel;
                end else begin
                    col <= col + 1'b1;
                end
            end
        end
    end
endmodule
