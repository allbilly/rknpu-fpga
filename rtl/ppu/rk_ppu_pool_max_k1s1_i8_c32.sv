// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact captured INT8 C32 1x1/stride-1 maximum profile
// (int8_max_k1s1_valid_c32_h1w1).
//
// A 1x1 window covers exactly one pixel, so the reduction is the identity on
// the value bytes: the captured device output equals the first 32 input bytes,
// and the remaining 4064 bytes of both BOs are zero. C32 INT8 spans two
// 16-byte atoms, so two atoms in and two atoms out.
//
// Nothing is computed here, and that is the captured contract rather than a
// simplification: the same leaf would be wrong for any kernel larger than 1x1.
// A two-entry buffer presents the atoms back-to-back with independent
// valid/ready on each beat.
module rk_ppu_pool_max_k1s1_i8_c32 (
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
    // Two input atoms become two output atoms unchanged. `beat_q` counts how
    // many atoms have been forwarded; in_ready drops after the second.
    logic [127:0] atom_q [0:1];
    logic [1:0] beat_q;      // input beats accepted
    logic [1:0] emit_q;      // output beats accepted
    logic frame_done_q;

    assign in_ready  = rst_n && !frame_done_q && beat_q < 2'd2;
    assign out_valid = rst_n && beat_q > emit_q;
    assign out_atom  = atom_q[emit_q[0]];
    assign out_last  = rst_n && out_valid && emit_q == 2'd1;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            beat_q <= 2'd0;
            emit_q <= 2'd0;
            frame_done_q <= 1'b0;
            atom_q[0] <= 128'b0;
            atom_q[1] <= 128'b0;
        end else begin
            if (in_valid && in_ready) begin
                atom_q[beat_q[0]] <= in_atom;
                beat_q <= beat_q + 2'd1;
                if (beat_q == 2'd1)
                    frame_done_q <= 1'b1;
            end
            if (out_valid && out_ready)
                emit_q <= emit_q + 2'd1;
        end
    end
endmodule
