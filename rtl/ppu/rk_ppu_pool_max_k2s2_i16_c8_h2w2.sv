// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact captured INT16 C8 2x2/stride-2 maximum profile.
module rk_ppu_pool_max_k2s2_i16_c8_h2w2 (
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
    rk_ppu_pool_int_k2s2 #(.ELEM_W(16), .LANES(8), .METHOD(0)) core (.*);
endmodule
