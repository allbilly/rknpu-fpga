// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Standalone first PPU increment: FP16 maximum pooling, 2x2 kernel, stride 1,
// valid (no) padding, eight FP16 channels per 16-byte C1HWC2 atom.
//
// The core is independent of the NVDLA PDP. It consumes one input atom per
// accepted handshake and produces one output atom per accepted input after the
// first row and first column. Two ping-pong row buffers hold the previous
// input row; the current row is compared as it arrives with a one-atom
// history register. The datapath is lane-wise: no channel mixing, rounding,
// accumulation, register decode or memory access is present.
//
// MAX ordering follows the project's captured RK elementwise FP16 MAX policy:
// IEEE encoded order for finite/infinite values, +0 over -0, and 0x7c01 if any
// operand is NaN. The signed-zero/NaN choices are candidate PPU behavior: the
// retained capture contains finite values (including negative inputs), but no
// NaN, infinity, signed-zero or subnormal payload.
module rk_ppu_pool_max2x2s1_c8 #(
    parameter int unsigned IN_H = 4,
    parameter int unsigned IN_W = 4
) (
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
    localparam int unsigned OUT_H = IN_H - 1;
    localparam int unsigned OUT_W = IN_W - 1;
    localparam int unsigned COL_W = (IN_W <= 1) ? 1 : $clog2(IN_W);
    localparam int unsigned ROW_W = (IN_H <= 1) ? 1 : $clog2(IN_H);
    localparam logic [COL_W-1:0] LAST_COL = COL_W'(IN_W - 1);
    localparam logic [ROW_W-1:0] LAST_ROW = ROW_W'(IN_H - 1);

    logic [127:0] line [0:1][0:IN_W-1];
    logic         cur_sel;
    logic [ROW_W-1:0] row;
    logic [COL_W-1:0] col;
    logic [COL_W-1:0] prev_col;
    logic [127:0] curr_prev;
    logic [127:0] window_max;
    logic [127:0] out_atom_q;
    logic         out_valid_q;
    logic         out_last_q;

    initial begin
        if (IN_H < 2) $fatal(1, "IN_H must be at least 2 for a 2x2 kernel");
        if (IN_W < 2) $fatal(1, "IN_W must be at least 2 for a 2x2 kernel");
    end

    // Captured RK FP16 MAX ordering. This is a comparison-only helper, not a
    // general FP16 ALU; no arithmetic or conversion is performed.
    function automatic logic [15:0] fp16_max2(
        input logic [15:0] a,
        input logic [15:0] b
    );
        logic a_nan, b_nan;
        begin
            a_nan = (&a[14:10]) && (|a[9:0]);
            b_nan = (&b[14:10]) && (|b[9:0]);
            if (a_nan || b_nan) begin
                fp16_max2 = 16'h7c01;
            end else if ((a[14:0] == 15'b0) && (b[14:0] == 15'b0)) begin
                fp16_max2 = 16'h0000; // +0 wins over -0
            end else if (a[15] != b[15]) begin
                fp16_max2 = a[15] ? b : a;
            end else if (!a[15]) begin
                fp16_max2 = (a[14:0] >= b[14:0]) ? a : b;
            end else begin
                fp16_max2 = (a[14:0] <= b[14:0]) ? a : b;
            end
        end
    endfunction

    function automatic logic [15:0] fp16_max4(
        input logic [15:0] a,
        input logic [15:0] b,
        input logic [15:0] c,
        input logic [15:0] d
    );
        begin
            fp16_max4 = fp16_max2(fp16_max2(a, b), fp16_max2(c, d));
        end
    endfunction

    assign prev_col = (col == {COL_W{1'b0}}) ? {COL_W{1'b0}} : col - 1'b1;

    // Previous input row is read from the inactive line buffer. Current row
    // contributions are the one-atom history and this accepted atom.
    always_comb begin
        for (integer lane = 0; lane < 8; lane = lane + 1) begin
            window_max[lane*16 +: 16] = fp16_max4(
                line[~cur_sel][prev_col][lane*16 +: 16],
                line[~cur_sel][col][lane*16 +: 16],
                curr_prev[lane*16 +: 16],
                in_atom[lane*16 +: 16]
            );
        end
    end

    assign in_ready  = rst_n && (!out_valid_q || out_ready);
    assign out_valid = out_valid_q;
    assign out_atom  = out_atom_q;
    assign out_last  = out_last_q;

    wire emit = (row != {ROW_W{1'b0}}) && (col != {COL_W{1'b0}});

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            cur_sel    <= 1'b0;
            row        <= {ROW_W{1'b0}};
            col        <= {COL_W{1'b0}};
            curr_prev  <= 128'b0;
            out_atom_q <= 128'b0;
            out_valid_q <= 1'b0;
            out_last_q  <= 1'b0;
        end else begin
            if (out_valid_q && out_ready) begin
                out_valid_q <= 1'b0;
            end
            if (in_valid && in_ready) begin
                line[cur_sel][col] <= in_atom;
                curr_prev <= in_atom;
                if (emit) begin
                    out_valid_q <= 1'b1;
                    out_atom_q  <= window_max;
                    out_last_q  <= (row == LAST_ROW) && (col == LAST_COL);
                end
                if (col == LAST_COL) begin
                    col <= {COL_W{1'b0}};
                    row <= (row == LAST_ROW) ? {ROW_W{1'b0}} : row + 1'b1;
                    cur_sel <= ~cur_sel;
                end else begin
                    col <= col + 1'b1;
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (OUT_H < 1) $fatal(1, "OUT_H must be positive");
        if (OUT_W < 1) $fatal(1, "OUT_W must be positive");
    end
`endif
endmodule
