// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// INTERNAL arithmetic candidate. Exact finite FP16 product in FP32 encoding;
// not a rounded-half multiplier, reduction tree, accumulator or GEMM engine.
// Three elastic stages carry classification and opaque tags with the data.
// Special-value policy remains candidate behavior pending RK differential tests.
module rk_fp16_product #(
    parameter int unsigned TAG_WIDTH = 131
) (
    input logic clk, rst_n,
    input logic in_valid,
    output logic in_ready,
    input logic [15:0] in_a, in_b,
    input logic [TAG_WIDTH-1:0] in_tag,
    output logic out_valid,
    input logic out_ready,
    output logic [31:0] out_product,
    output logic [TAG_WIDTH-1:0] out_tag
);
    logic v0, v1, v2, r0, r1, r2;
    logic [10:0] ma0, mb0;
    logic [21:0] product1;
    logic [5:0] exponent0, exponent1;
    logic sign0, sign1, nan0, nan1, inf0, inf1, zero0, zero1;
    logic [TAG_WIDTH-1:0] tag0, tag1;
    logic [4:0] leading;
    logic [22:0] fraction;
    logic [7:0] exponent32;
    logic [31:0] encoded;
    wire a_zero = in_a[14:0] == 0;
    wire b_zero = in_b[14:0] == 0;
    wire a_inf = in_a[14:10] == 31 && in_a[9:0] == 0;
    wire b_inf = in_b[14:10] == 31 && in_b[9:0] == 0;
    wire a_nan = in_a[14:10] == 31 && in_a[9:0] != 0;
    wire b_nan = in_b[14:10] == 31 && in_b[9:0] != 0;
    initial begin
        if (TAG_WIDTH == 0) $fatal(1,"TAG_WIDTH must be positive");
    end

    assign r2 = !v2 || out_ready;
    assign r1 = !v1 || r2;
    assign r0 = !v0 || r1;
    assign in_ready = rst_n && r0;
    assign out_valid = rst_n && v2;

    // Finite half: M * 2^(effective_exp-25), M <= 2047. Product P has at
    // most 22 significant bits; FP32's 24 bits preserve all of them exactly.
    // Nonzero finite products span 2^-48 through (65504)^2, so no FP32
    // subnormal, overflow, rounding or flush is required in this leaf.
    always_comb begin
        leading = 0;
        for (integer i=0; i<22; i=i+1)
            if (product1[i]) leading = 5'(i);
    end
    // The implicit leading one at bit 23 is deliberately not stored.
    assign fraction = {1'b0,product1} << (5'd23-leading);
    assign exponent32 = {2'b0,exponent1} + {3'b0,leading} + 8'd77;
    assign encoded = nan1 ? 32'h7fc00000 : inf1 ? {sign1,8'hff,23'b0} :
                     zero1 ? {sign1,31'b0} : {sign1,exponent32,fraction};

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v0<=0;v1<=0;v2<=0;
            ma0<=0;mb0<=0;product1<=0;exponent0<=0;exponent1<=0;
            sign0<=0;sign1<=0;nan0<=0;nan1<=0;inf0<=0;inf1<=0;zero0<=0;zero1<=0;
            tag0<=0;tag1<=0;out_product<=0;out_tag<=0;
        end else begin
            if (r2) begin
                v2<=v1;
                if (v1) begin out_product<=encoded;out_tag<=tag1;end
            end
            if (r1) begin
                v1<=v0;
                if (v0) begin
                    product1<=ma0*mb0;exponent1<=exponent0;
                    sign1<=sign0;nan1<=nan0;inf1<=inf0;zero1<=zero0;tag1<=tag0;
                end
            end
            if (r0) begin
                v0<=in_valid;
                if (in_valid) begin
                    ma0<={in_a[14:10]!=0,in_a[9:0]};
                    mb0<={in_b[14:10]!=0,in_b[9:0]};
                    exponent0<=(in_a[14:10]==0 ? 6'd1 : {1'b0,in_a[14:10]}) +
                               (in_b[14:10]==0 ? 6'd1 : {1'b0,in_b[14:10]});
                    sign0<=in_a[15]^in_b[15];
                    nan0<=a_nan || b_nan || (a_inf && b_zero) || (b_inf && a_zero);
                    inf0<=a_inf || b_inf;
                    zero0<=a_zero || b_zero;
                    tag0<=in_tag;
                end
            end
        end
    end
endmodule
