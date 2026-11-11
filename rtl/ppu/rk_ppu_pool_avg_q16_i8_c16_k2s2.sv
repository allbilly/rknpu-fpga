// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact captured INT8 C16 2x2/stride-2 Q16 average profile
// (int8_avg_q16_k2s2_valid_c16_h2w2). Divide-by-area semantics.
module rk_ppu_pool_avg_q16_i8_c16_k2s2 (
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
    rk_ppu_pool_int_avg #(.ELEM_W(8), .LANES(16), .KH(2), .KW(2)) core (.*);
endmodule
