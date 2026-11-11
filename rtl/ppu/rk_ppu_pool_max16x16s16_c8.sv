// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One-frame, source-bounded FP16 C8 global maximum over 16x16 input atoms.
// The owner admits only +0 and finite positive normal FP16 lanes. Under that
// explicit domain, unsigned half encodings preserve numeric ordering.
module rk_ppu_pool_max16x16s16_c8 (
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
    logic [7:0] atom_count_q;
    logic [15:0] maximum_q [0:7];
    logic [15:0] maximum_next [0:7];
    logic [127:0] out_atom_q;
    logic out_valid_q;
    integer lane;

    always_comb begin
        for (integer i = 0; i < 8; i = i + 1) begin
            if (atom_count_q == 8'd0 || in_atom[i*16 +: 16] > maximum_q[i])
                maximum_next[i] = in_atom[i*16 +: 16];
            else
                maximum_next[i] = maximum_q[i];
        end
    end

    assign in_ready = rst_n && !out_valid_q;
    assign out_valid = rst_n && out_valid_q;
    assign out_atom = out_atom_q;
    assign out_last = out_valid;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            atom_count_q <= 8'd0;
            out_atom_q <= 128'd0;
            out_valid_q <= 1'b0;
            for (lane = 0; lane < 8; lane = lane + 1)
                maximum_q[lane] <= 16'd0;
        end else begin
            if (out_valid_q && out_ready)
                out_valid_q <= 1'b0;
            if (in_valid && in_ready) begin
                for (lane = 0; lane < 8; lane = lane + 1)
                    maximum_q[lane] <= maximum_next[lane];
                if (atom_count_q == 8'd255) begin
                    for (lane = 0; lane < 8; lane = lane + 1)
                        out_atom_q[lane*16 +: 16] <= maximum_next[lane];
                    out_valid_q <= 1'b1;
                end else begin
                    atom_count_q <= atom_count_q + 1'b1;
                end
            end
        end
    end
endmodule
