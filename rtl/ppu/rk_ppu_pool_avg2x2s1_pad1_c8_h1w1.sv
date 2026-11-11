// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact captured FP16 2x2/stride-1, padded-1 C8 H1W1 average profiles
// (fp16_avg_k2s1_pad1_use_cnt0_c8_h1w1 and ..._use_cnt7_...).
//
// A 1x1 input padded by one on every side is a 3x3 surface whose only real tap
// is at (1,1). A 2x2 window at stride 1 produces four output pixels, and every
// one of the four windows contains that single real tap, so all four outputs
// equal `v / 4`. That is exactly what both captures hold: input +8.0 and every
// one of the four output atoms +2.0, with the captured tail zero.
//
// Padding is FP16 +0 (PPU_PADDING_VALUE_1_CFG = 0), contributing zero to each
// sum. USE_CNT=0 and USE_CNT=7 captured identical outputs, so this leaf
// divides by the padded window area (four taps) and implements no count-driven
// divisor. That the count field has no effect is captured behaviour for these
// two 1x1 cases only, not a general rule.
//
// Division by 4 is exact by decrementing the FP16 exponent. Only normal
// operands appear in the captures; an exceptional input is an explicit fault
// rather than an invented special-value ordering.
module rk_ppu_pool_avg2x2s1_pad1_c8_h1w1 (
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
    localparam int unsigned C = 8;

    function automatic logic [15:0] fp16_div4(input logic [15:0] a);
        logic [4:0] exponent;
        begin
            if (a == 16'h0000)
                fp16_div4 = 16'h0000;       // +0 stays +0
            else if (a == 16'h8000)
                fp16_div4 = 16'h8000;       // -0 stays -0, exact
            else if (a[14:10] == 5'h1f || a[14:10] == 5'd0)
                fp16_div4 = 16'hxxxx;       // inf/NaN/subnormal: explicit fault
            else begin
                exponent = a[14:10];
                if (exponent < 5'd2)
                    fp16_div4 = 16'hxxxx;   // would underflow; not captured
                else
                    fp16_div4 = {a[15], exponent - 5'd2, a[9:0]};
            end
        end
    endfunction

    logic [127:0] mean_q;
    logic [127:0] mean_next;
    logic [127:0] out_atom_q;
    logic frame_done_q;
    logic out_valid_q, out_last_q;
    logic [2:0] out_beat_q;

    // Combinational so the quotient is available in the same cycle as the
    // accepted atom; a registered `mean_q` would be sampled one cycle stale.
    always_comb begin
        for (integer lane = 0; lane < C; lane = lane + 1)
            mean_next[lane*16 +: 16] = fp16_div4(in_atom[lane*16 +: 16]);
    end

    assign in_ready  = rst_n && !frame_done_q;
    assign out_valid = out_valid_q;
    assign out_atom  = out_atom_q;
    assign out_last  = out_last_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mean_q <= 128'b0;
            out_atom_q <= 128'b0;
            frame_done_q <= 1'b0;
            out_valid_q <= 1'b0;
            out_last_q <= 1'b0;
            out_beat_q <= 3'd0;
        end else begin
            if (out_valid_q && out_ready) begin
                if (out_beat_q == 3'd3) begin
                    out_valid_q <= 1'b0;
                    out_last_q <= 1'b0;
                end else begin
                    out_atom_q <= mean_q;
                    out_valid_q <= 1'b1;
                    out_last_q <= (out_beat_q == 3'd2);
                    out_beat_q <= out_beat_q + 3'd1;
                end
            end
            if (in_valid && in_ready) begin
                mean_q <= mean_next;
                frame_done_q <= 1'b1;
                out_beat_q <= 3'd0;
                // Present the first of the four identical mean atoms. The
                // other three follow as `out_ready` drains them.
                out_atom_q <= mean_next;
                out_valid_q <= 1'b1;
                out_last_q <= 1'b0;
            end
        end
    end
endmodule
