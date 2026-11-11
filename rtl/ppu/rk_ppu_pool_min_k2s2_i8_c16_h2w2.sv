// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact captured INT8 C16 2x2/stride-2 minimum profile.
module rk_ppu_pool_min_k2s2_i8_c16_h2w2 (
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
    rk_ppu_pool_int_k2s2 #(.ELEM_W(8), .LANES(16), .METHOD(1)) core (.*);
endmodule
