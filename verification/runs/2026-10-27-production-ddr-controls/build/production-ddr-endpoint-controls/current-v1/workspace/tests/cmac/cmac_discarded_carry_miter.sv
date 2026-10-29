// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module cmac_discarded_carry_miter (
    input wire [31:0] first_row, total,
    input wire [2:0] shift,
    output wire reference_carry, actual_carry, mismatch
);
    wire [4:0] amount = {shift, 2'b00};
    wire [31:0] mask = (32'h00000001 << amount) - 32'd1;
    assign reference_carry = (first_row & mask) > (total & mask);
    rk_cmac_fp16_discarded_carry actual (.first_row, .total, .shift, .carry(actual_carry));
    assign mismatch = reference_carry ^ actual_carry;
endmodule
