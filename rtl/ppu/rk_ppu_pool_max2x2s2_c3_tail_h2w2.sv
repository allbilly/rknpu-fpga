// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Capture-bounded standalone PPU candidate for
// fp16_max_k2s2_c3_tail_h2w2 only.
//
// The leaf consumes four captured 16-byte atoms for a C3 H2W2 surface. The
// source fills the five unused physical lanes of every atom with FP16 -99; the
// leaf compares all eight lanes and therefore preserves that captured tail in
// the output atom. No PPU decode, DMA/RDMA, AXI or full-top admission exists.
module rk_ppu_pool_max2x2s2_c3_tail_h2w2 (
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
    logic [127:0] input_atom [0:2];
    logic [1:0] input_count_q;
    logic frame_done_q;
    logic [127:0] window_max;
    logic [127:0] out_atom_q;
    logic out_valid_q;
    logic out_last_q;

    function automatic logic [15:0] fp16_max2(
        input logic [15:0] a,
        input logic [15:0] b
    );
        begin
            // The pinned input is finite and has no signed zeros. Do not infer
            // a PPU special-value policy from this four-input capture.
            if ((a[14:10] == 5'h1f) || (b[14:10] == 5'h1f) ||
                ((a[14:0] == 15'b0) && (b[14:0] == 15'b0) && (a[15] != b[15]))) begin
                fp16_max2 = 16'hxxxx;
            end else if (a[15] != b[15]) begin
                fp16_max2 = a[15] ? b : a;
            end else if (!a[15]) begin
                fp16_max2 = (a[14:0] >= b[14:0]) ? a : b;
            end else begin
                fp16_max2 = (a[14:0] <= b[14:0]) ? a : b;
            end
        end
    endfunction

    always_comb begin
        for (integer lane = 0; lane < 8; lane = lane + 1) begin
            window_max[lane*16 +: 16] = fp16_max2(
                fp16_max2(input_atom[0][lane*16 +: 16],
                          input_atom[1][lane*16 +: 16]),
                fp16_max2(input_atom[2][lane*16 +: 16],
                          in_atom[lane*16 +: 16])
            );
        end
    end

    assign in_ready = rst_n && !frame_done_q && (!out_valid_q || out_ready);
    assign out_valid = out_valid_q;
    assign out_atom = out_atom_q;
    assign out_last = out_last_q;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            input_count_q <= 2'd0;
            frame_done_q <= 1'b0;
            out_atom_q <= 128'b0;
            out_valid_q <= 1'b0;
            out_last_q <= 1'b0;
        end else begin
            if (out_valid_q && out_ready) begin
                out_valid_q <= 1'b0;
                out_last_q <= 1'b0;
            end
            if (in_valid && in_ready) begin
                if (input_count_q == 2'd3) begin
                    out_atom_q <= window_max;
                    out_valid_q <= 1'b1;
                    out_last_q <= 1'b1;
                    frame_done_q <= 1'b1;
                end else begin
                    input_atom[input_count_q] <= in_atom;
                    input_count_q <= input_count_q + 1'b1;
                end
            end
        end
    end
endmodule
