// Test-only binary model equivalence; never substitutes arithmetic in FPGA RTL.
module dsp_prefix_actual_model_miter #(
    parameter integer NEGATIVE = 0
) (
    input [29:0] A,
    input [17:0] B,
    input [25:0] omitted,
    output [47:0] actual,
    output [47:0] expected,
    output ok
);
    // This module is the exact completed unchanged-model elaboration JSON.
    dsp_prefix_omitted_input_cone_control actual_model(.A(A), .B(B), .omitted(omitted), .P(actual));
    wire signed [42:0] mathematical_product = $signed(A[24:0]) * $signed(B);
    wire [47:0] mathematical_sum = {{5{mathematical_product[42]}}, mathematical_product} + 48'h000055550000;
    assign expected = mathematical_sum ^ (NEGATIVE ? 48'h1 : 48'h0);
    assign ok = actual == expected;
endmodule
