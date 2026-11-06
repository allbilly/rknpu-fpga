// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Isolated one-capture PPU candidate for
// fp16_max_k2s1_pad1_neg_c8_h2w2. This is not a configurable pooling engine.
//
// It buffers the captured 2x2 C8 input and emits the 3x3 output surface with
// the observed 0xfc00 (-infinity) padding value. Captured input lanes are
// finite negative FP16 values. The comparison below is intentionally limited
// to that data plus the observed -infinity pad; it does not define general
// NaN, signed-zero or other special-value MAX behavior.
module rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2 (
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
    localparam logic [15:0] PAD_VALUE = 16'hfc00;

    logic [127:0] input_atom [0:3];
    logic [1:0] input_count_q;
    logic [3:0] output_index_q;
    logic input_full_q;
    logic output_done_q;

    integer output_y;
    integer output_x;
    integer input_y;
    integer input_x;
    integer ky;
    integer kx;
    integer lane;
    logic [15:0] sample;
    logic [15:0] lane_max;
    logic [127:0] output_atom_comb;

    // Both operands are either a captured finite-negative lane or the
    // captured -infinity pad. For these encodings, the smaller magnitude
    // field is the larger numeric value. No other FP16 class is specified.
    function automatic logic [15:0] max_negative_or_pad(
        input logic [15:0] a,
        input logic [15:0] b
    );
        begin
            max_negative_or_pad = (a[14:0] <= b[14:0]) ? a : b;
        end
    endfunction

    assign in_ready = rst_n && !input_full_q;
    assign out_valid = rst_n && input_full_q && !output_done_q;
    assign out_last = out_valid && (output_index_q == 4'd8);
    assign out_atom = output_atom_comb;

    // Output (y,x) maps to a 2x2 window in the one-cell padded input plane.
    // Every out-of-range coordinate is explicitly the captured -infinity pad.
    always_comb begin
        output_y = int'(output_index_q) / 3;
        output_x = int'(output_index_q) % 3;
        output_atom_comb = 128'b0;
        input_y = 0;
        input_x = 0;
        sample = PAD_VALUE;
        lane_max = PAD_VALUE;

        if (input_full_q && !output_done_q) begin
            for (lane = 0; lane < 8; lane = lane + 1) begin
                lane_max = PAD_VALUE;
                for (ky = 0; ky < 2; ky = ky + 1) begin
                    for (kx = 0; kx < 2; kx = kx + 1) begin
                        input_y = output_y + ky - 1;
                        input_x = output_x + kx - 1;
                        sample = PAD_VALUE;
                        if ((input_y >= 0) && (input_y < 2) &&
                            (input_x >= 0) && (input_x < 2)) begin
                            sample = input_atom[input_y * 2 + input_x][lane*16 +: 16];
                        end
                        lane_max = max_negative_or_pad(lane_max, sample);
                    end
                end
                output_atom_comb[lane*16 +: 16] = lane_max;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            input_count_q <= 2'b0;
            output_index_q <= 4'b0;
            input_full_q <= 1'b0;
            output_done_q <= 1'b0;
            for (integer atom = 0; atom < 4; atom = atom + 1)
                input_atom[atom] <= 128'b0;
        end else begin
            if (in_valid && in_ready) begin
                input_atom[input_count_q] <= in_atom;
                if (input_count_q == 2'd3) begin
                    input_full_q <= 1'b1;
                end else begin
                    input_count_q <= input_count_q + 1'b1;
                end
            end

            if (out_valid && out_ready) begin
                if (output_index_q == 4'd8) begin
                    output_done_q <= 1'b1;
                end else begin
                    output_index_q <= output_index_q + 1'b1;
                end
            end
        end
    end
endmodule
