// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact captured INT16 C8 3x3/stride-3 Q16 average profile
// (int16_avg_q16_k3x3_valid_c8_h3w3).
module rk_ppu_pool_avg_q16_i16_c8_k3x3 (
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
    rk_ppu_pool_int_avg #(.ELEM_W(16), .LANES(8), .KH(3), .KW(3)) core (.*);
endmodule
