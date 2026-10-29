// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// ISOLATED binary carry-prefix experiment; no array or board acceptance.
// Select unsigned comparison of the low 4*shift bits, for shift=0..7.
// This is not a four-state relational-operator equivalence claim.
module rk_cmac_fp16_discarded_carry (
    input wire [31:0] first_row, total,
    input wire [2:0] shift,
    output wire carry
);
    wire [7:0] greater;
    assign greater[0] = 1'b0;
    for (genvar nibble=0; nibble<7; nibble=nibble+1) begin: prefixes
        wire [3:0] a = first_row[nibble*4+:4];
        wire [3:0] s = total[nibble*4+:4];
        assign greater[nibble+1] = (a > s) || ((a == s) && greater[nibble]);
    end
    assign carry = greater[shift];
endmodule
