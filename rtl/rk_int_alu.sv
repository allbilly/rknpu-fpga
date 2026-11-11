// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Original, synthesis-oriented integer elementwise ALU for the captured ew-int
// family. Semantics are derived from the captured RK3588 bundles and the source
// examples' integer_expected() (see docs/EW_INT.md):
//   ADD/MINUS : signed add/sub, clamped to the destination dtype
//   MUL       : signed product, clamped to the destination dtype
//   MAX/MIN   : signed maximum/minimum (EW_EQUAL_EN capture family)
// The INT32-MUL signed-INT16 second-operand limitation is a property of the
// captured MUL lane and is applied by the engine before this module (the engine
// sign-extends the truncated operand), so this ALU always sees 32-bit signed
// operands and the destination dtype.
//
// Evidence caveat: the 15 READY captured lanes never overflow, so clamping is
// source-formula behaviour (kernel_6_18 saturate()) rather than a differentially
// captured overflow lane. No FP16 value, NaN or rounding path exists here.
module rk_int_alu (
    input  logic              clk,
    input  logic              rst_n,
    input  logic              in_valid,
    output logic              in_ready,
    input  logic [2:0]        in_op,     // 0 ADD, 1 MINUS, 2 MUL, 3 MAX, 4 MIN
    input  logic [1:0]        in_dtype,  // 0 INT8, 1 INT16, 2 INT32 (result dtype)
    input  logic signed [31:0] in_a,
    input  logic signed [31:0] in_b,
    output logic              out_valid,
    input  logic              out_ready,
    output logic signed [31:0] out_data
);
    function automatic logic signed [31:0] saturate(
        input logic signed [63:0] value, input logic [1:0] dtype
    );
        begin
            case (dtype)
                2'd0: saturate = (value > 64'sd127) ? 32'sd127 :
                                 (value < -64'sd128) ? -32'sd128 : value[31:0];
                2'd1: saturate = (value > 64'sd32767) ? 32'sd32767 :
                                 (value < -64'sd32768) ? -32'sd32768 : value[31:0];
                2'd2: saturate = (value > 64'sd2147483647) ? 32'sd2147483647 :
                                 (value < -64'sd2147483648) ? -32'sh80000000 : value[31:0];
                default: saturate = 32'sd0;
            endcase
        end
    endfunction

    function automatic logic signed [31:0] calculate(
        input logic [2:0] op, input logic [1:0] dtype,
        input logic signed [31:0] a, input logic signed [31:0] b
    );
        logic signed [31:0] selected;
        logic signed [63:0] wide;
        begin
            selected = 32'sd0;
            wide = 64'sd0;
            // Explicit 64-bit signed arithmetic; a and b are 32-bit signed.
            case (op)
                3'd0: wide = $signed({{32{a[31]}}, a}) + $signed({{32{b[31]}}, b});
                3'd1: wide = $signed({{32{a[31]}}, a}) - $signed({{32{b[31]}}, b});
                3'd2: wide = $signed({{32{a[31]}}, a}) * $signed({{32{b[31]}}, b});
                3'd3: selected = ($signed(a) >= $signed(b)) ? a : b;
                3'd4: selected = ($signed(a) <= $signed(b)) ? a : b;
                default: selected = 32'sd0;
            endcase
            if (op == 3'd3 || op == 3'd4) calculate = selected;
            else calculate = saturate(wide, dtype);
        end
    endfunction

    assign in_ready = (!out_valid || out_ready);

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            out_data <= 32'sd0;
        end else if (in_valid && in_ready) begin
            out_valid <= 1'b1;
            out_data <= calculate(in_op, in_dtype, in_a, in_b);
        end else if (out_valid && out_ready) begin
            out_valid <= 1'b0;
        end
    end
endmodule
