// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Capture-bounded standalone PPU candidate for
// fp16_min_k2s1_valid_c8_h4w4 only.
//
// The leaf consumes the captured 4x4 C8 surface and emits its 3x3 valid
// 2x2/stride-1 minimum. It has no PPU register decode, DMA/RDMA, AXI or
// full-top admission. The input fixture is finite and contains no -0; no
// generic special-value or signed-zero PPU behavior is inferred here.
module rk_ppu_pool_min2x2s1_fp16_capture (
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
    logic [127:0] window_min;
    logic [127:0] out_atom_q;
    logic         out_valid_q;
    logic         out_last_q;
    logic         frame_done_q;

    function automatic logic [15:0] fp16_min2(
        input logic [15:0] a,
        input logic [15:0] b
    );
        begin
            // The capture has finite operands and no negative zero. Exceptional
            // encodings and the opposite-signed-zero tie remain unqualified.
            if ((a[14:10] == 5'h1f) || (b[14:10] == 5'h1f) ||
                ((a[14:0] == 15'b0) && (b[14:0] == 15'b0) && (a[15] != b[15]))) begin
                fp16_min2 = 16'hxxxx;
            end else if (a[14:0] == 15'b0 && b[14:0] == 15'b0) begin
                fp16_min2 = a;
            end else if (a[15] != b[15]) begin
                fp16_min2 = a[15] ? a : b;
            end else if (!a[15]) begin
                fp16_min2 = (a[14:0] <= b[14:0]) ? a : b;
            end else begin
                fp16_min2 = (a[14:0] >= b[14:0]) ? a : b;
            end
        end
    endfunction

    function automatic logic [15:0] fp16_min4(
        input logic [15:0] a,
        input logic [15:0] b,
        input logic [15:0] c,
        input logic [15:0] d
    );
        begin
            fp16_min4 = fp16_min2(fp16_min2(a, b), fp16_min2(c, d));
        end
    endfunction

    assign prev_col = (col == 2'b00) ? 2'b00 : col - 1'b1;

    always_comb begin
        for (integer lane = 0; lane < 8; lane = lane + 1) begin
            window_min[lane*16 +: 16] = fp16_min4(
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
                    out_atom_q  <= window_min;
                    out_last_q  <= (row == 2'd3) && (col == 2'd3);
                end
                if (row == 2'd3 && col == 2'd3) begin
                    frame_done_q <= 1'b1;
                end
                if (col == 2'd3) begin
                    col <= 2'b00;
                    row <= (row == 2'd3) ? 2'b00 : row + 1'b1;
                    cur_sel <= ~cur_sel;
                end else begin
                    col <= col + 1'b1;
                end
            end
        end
    end
endmodule
