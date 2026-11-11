// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Signed-integer pooling average over one captured surface, dividing by the
// kernel area.
//
// Semantics pinned from the four frozen captures (see
// docs/PPU_Q16_AVERAGE.md):
//
//   int8_avg_q16_k2s2, int16_avg_q16_k2s2    area 4
//   int8_avg_q16_k3x3, int16_avg_q16_k3x3    area 9
//
// Every captured lane value equals sum_of_window / area. Reciprocal
// multiplication with the captured Q16 registers (0x8000 for area 4, 0x5555
// for area 9) reproduces the k2s2 captures but **not** the k3x3 captures,
// whereas division by the area reproduces all four. This leaf therefore
// divides; it does not multiply by a reciprocal.
//
// In all four fixtures every lane sum is an exact multiple of the area, so
// truncation toward zero and floor division agree and the captures cannot
// distinguish them. This leaf uses signed truncation toward zero, which is
// Verilog's own `/` rule on signed operands, and records that as candidate
// behaviour until a capture with a non-exact sum exists.
//
// One surface is KH*KW atoms of LANES lanes; C16 INT8 is one atom per pixel and
// C8 INT16 likewise. The divisor is a compile-time constant, so synthesis maps
// it to shifts and adds rather than a variable divider. No PPU decode, DMA/AXI,
// padding or special-value policy.
module rk_ppu_pool_int_avg #(
    parameter integer ELEM_W = 8,   // 8 or 16
    parameter integer LANES = 16,   // 128 / ELEM_W
    parameter integer KH = 2,
    parameter integer KW = 2
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
    localparam int unsigned ATOMS = KH * KW;
    localparam int unsigned AREA = ATOMS;
    // Widest possible lane sum: ATOMS elements of ELEM_W signed bits.
    localparam int unsigned SUM_W = ELEM_W + $clog2(ATOMS + 1);
    localparam int unsigned COUNT_BITS = (ATOMS <= 1) ? 1 : $clog2(ATOMS);

    typedef enum logic [1:0] {COLLECT, EMIT} state_t;
    state_t state_q;

    logic signed [SUM_W-1:0] acc_q [0:LANES-1];
    logic [COUNT_BITS-1:0] count_q;
    logic frame_done_q;
    logic [127:0] out_atom_q;
    logic out_valid_q, out_last_q;

    initial begin
        if (ELEM_W != 8 && ELEM_W != 16)
            $fatal(1, "integer average supports 8- or 16-bit elements");
        if (LANES != 128 / ELEM_W)
            $fatal(1, "lane count must fill exactly one 16-byte atom");
        if (ATOMS < 1 || ATOMS > 64)
            $fatal(1, "integer average supports kernels up to 64 taps");
    end

    // Signed truncation toward zero is exactly Verilog's `/` on signed
    // operands. The divisor must be SIGNED as well: Verilog makes the result
    // unsigned as soon as either operand is unsigned, and `SUM_W'(AREA)` is.
    // (An unsigned divide here produced 0xB7 instead of -16 on a -144 sum.)
    localparam logic signed [SUM_W-1:0] AREA_SIGNED = SUM_W'(AREA);

    function automatic logic signed [ELEM_W-1:0] lane_average(
        input logic signed [SUM_W-1:0] total
    );
        logic signed [SUM_W-1:0] quotient;
        begin
            quotient = total / AREA_SIGNED;
            lane_average = quotient[ELEM_W-1:0];
        end
    endfunction

    assign in_ready  = rst_n && !frame_done_q && (!out_valid_q || out_ready);
    assign out_valid = out_valid_q;
    assign out_atom  = out_atom_q;
    assign out_last  = out_last_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= COLLECT;
            count_q <= '0;
            frame_done_q <= 1'b0;
            out_atom_q <= 128'b0;
            out_valid_q <= 1'b0;
            out_last_q <= 1'b0;
        end else begin
            if (out_valid_q && out_ready)
                out_valid_q <= 1'b0;

            case (state_q)
                COLLECT: if (in_valid && in_ready) begin
                    for (integer l = 0; l < LANES; l = l + 1) begin
                        logic signed [ELEM_W-1:0] elem;
                        logic signed [SUM_W-1:0] running;
                        elem = in_atom[l*ELEM_W +: ELEM_W];
                        running = (count_q == 0) ? SUM_W'(elem)
                                                 : acc_q[l] + SUM_W'(elem);
                        acc_q[l] <= running;
                        // On the final atom the completed sum is divided by
                        // the kernel area and latched as this lane's result.
                        if (count_q == COUNT_BITS'(ATOMS - 1))
                            out_atom_q[l*ELEM_W +: ELEM_W] <= lane_average(running);
                    end
                    if (count_q == COUNT_BITS'(ATOMS - 1)) begin
                        count_q <= '0;
                        state_q <= EMIT;
                    end else begin
                        count_q <= count_q + 1'b1;
                    end
                end

                EMIT: begin
                    out_valid_q <= 1'b1;
                    out_last_q <= 1'b1;
                    frame_done_q <= 1'b1;
                    state_q <= EMIT;   // one frame per reset
                end

                default: state_q <= COLLECT;
            endcase
        end
    end
endmodule
