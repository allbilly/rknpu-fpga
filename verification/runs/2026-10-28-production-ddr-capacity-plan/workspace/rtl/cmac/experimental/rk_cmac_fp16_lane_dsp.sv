// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// ISOLATED EXPERIMENT; not connected to an array, raw-command path or FPGA top.
// Inputs have the existing donor's sign/pre-shifted 15-bit magnitude format,
// not IEEE FP16. Binary lane-sum equivalence is the required new proof boundary.
// Keep the donor's separate-row truncation correction and sign compensation.
module rk_cmac_fp16_lane_dsp (
    input wire [15:0] op_a, op_b,
    input wire [3:0] exp_sft,
    input wire pair_nz,
    output wire [31:0] lane_sum,
    output wire [7:0] res_tag
);
    wire [31:0] original_row_a;
    // Only the donor's first unshifted carry-save row is needed to compute
    // the low-bit carry. Synthesis may prune its unused second row/tag output.
    rk_cmac_fp16_rows original (
        .op_a(op_a), .op_b(op_b), .exp_sft(4'd0), .pair_nz(1'b1),
        .res_a(original_row_a), .res_b(), .res_tag()
    );
    wire signed [15:0] magnitude_a = $signed({1'b0, op_a[14:0]});
    wire signed [15:0] magnitude_b = $signed({1'b0, op_b[14:0]});
    wire signed [15:0] signed_a = (op_a[15] ^ op_b[15]) ? -magnitude_a : magnitude_a;
    (* use_dsp = "yes" *) wire signed [31:0] product = signed_a * magnitude_b;
    // The eight donor Booth rows carry a fixed unsigned bias 0x55550000.
    // This identity still needs proof over all binary inputs; no IEEE policy
    // or generic inferred-multiply compatibility is assumed.
    wire [31:0] biased_sum = $unsigned(product) + 32'h55550000;
    wire [4:0] shift_amount = {exp_sft[2:0], 2'b00};
    wire [31:0] low_mask = (32'h00000001 << shift_amount) - 32'd1;
    // For S=A+B without overflow, carry from the discarded low bits is
    // exactly (A mod 2^s) > (S mod 2^s). Discarding this bit would change the
    // donor's result, even though its unshifted product identity is correct.
    wire discarded_carry = (original_row_a & low_mask) > (biased_sum & low_mask);
    wire [31:0] compensation = -(32'h55550000 >> shift_amount);
    wire [31:0] corrected = (biased_sum >> shift_amount)
        - {31'd0, discarded_carry} + compensation;
    assign lane_sum = (!pair_nz || exp_sft[3]) ? 32'd0 : corrected;
    assign res_tag = (!pair_nz || exp_sft[3]) ? 8'd0 : 8'hf0 >> exp_sft[2:0];
endmodule
