// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Shared signed-integer 2x2/stride-2 atom reducer, parameterized by element
// width and lane count.
//
// A captured surface is four 16-byte C1HWC2 atoms. For 16 x INT8 the four
// atoms hold 16 channels each; for 8 x INT16 they hold 8 channels each. Either
// way a 2x2/stride-2 window covers the whole 2x2 surface and reduces to one
// output atom.
//
// METHOD selects maximum (0) or minimum (1). Comparisons are plain signed
// two's-complement ordering; the result is always one of the inputs, so no
// saturation applies. The accumulator is seeded from the first atom because a
// zero seed would bias positive-only (MAX) or negative-only (MIN) lanes.
//
// No register decode, RDMA/WDMA, AXI, padding generation or special-value
// policy is present. The captured cases are exact (tolerance 0.0).
module rk_ppu_pool_int_k2s2 #(
    parameter integer ELEM_W = 8,   // 8 or 16
    parameter integer LANES = 16,   // (128 / ELEM_W)
    parameter int unsigned METHOD = 0    // 0 = maximum, 1 = minimum
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
    localparam int unsigned ATOMS = 4;

    logic [127:0] acc_q;
    logic [1:0] count_q;
    logic frame_done_q;
    logic [127:0] reduced;
    logic [127:0] out_atom_q;
    logic out_valid_q;
    logic out_last_q;

    initial begin
        if (ELEM_W != 8 && ELEM_W != 16)
            $fatal(1, "signed-integer reducer supports 8- or 16-bit elements");
        if (LANES != 128 / ELEM_W)
            $fatal(1, "lane count must fill exactly one 16-byte atom");
        if (METHOD != 0 && METHOD != 1)
            $fatal(1, "signed-integer reducer supports only max (0) or min (1)");
    end

    function automatic logic [ELEM_W-1:0] reduce2(
        input logic [ELEM_W-1:0] a,
        input logic [ELEM_W-1:0] b
    );
        logic signed [ELEM_W-1:0] sa, sb;
        begin
            sa = a;
            sb = b;
            reduce2 = (METHOD == 0) ? ((sa >= sb) ? a : b) : ((sa <= sb) ? a : b);
        end
    endfunction

    always_comb begin
        for (integer lane = 0; lane < LANES; lane = lane + 1)
            reduced[lane*ELEM_W +: ELEM_W] =
                reduce2(acc_q[lane*ELEM_W +: ELEM_W],
                        in_atom[lane*ELEM_W +: ELEM_W]);
    end

    assign in_ready  = rst_n && !frame_done_q && (!out_valid_q || out_ready);
    assign out_valid = out_valid_q;
    assign out_atom  = out_atom_q;
    assign out_last  = out_last_q;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            acc_q <= 128'b0;
            count_q <= 2'd0;
            frame_done_q <= 1'b0;
            out_atom_q <= 128'b0;
            out_valid_q <= 1'b0;
            out_last_q <= 1'b0;
        end else begin
            if (out_valid_q && out_ready)
                out_valid_q <= 1'b0;

            if (in_valid && in_ready) begin
                if (count_q == 2'd0) begin
                    acc_q <= in_atom;
                    count_q <= 2'd1;
                end else if (count_q == 2'(ATOMS - 1)) begin
                    out_valid_q <= 1'b1;
                    out_atom_q <= reduced;
                    out_last_q <= 1'b1;
                    frame_done_q <= 1'b1;
                    count_q <= 2'd0;
                end else begin
                    acc_q <= reduced;
                    count_q <= count_q + 2'd1;
                end
            end
        end
    end
endmodule
