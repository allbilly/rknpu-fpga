// SPDX-License-Identifier: MIT
// Small exporter-only control: one DSP, not full-array numerical evidence.
module rk_cmac_fp16_cell_dsp_xc7 #(parameter ATOMIC_C=32)(
    input [511:0] data, weight, input [31:0] data_mask, weight_mask,
    output [43:0] result, output invalid
);
    wire [47:0] product;
    DSP48E1 #(.AREG(0), .BREG(0), .USE_MULT("MULTIPLY")) \$control_dsp (
        .A(data[29:0]), .B(weight[17:0]), .P(product));
    assign result=product[43:0];
    assign invalid=data_mask[0];
endmodule
module rk_cmac_fp16_array_dsp #(
    parameter ATOMIC_C=32, ATOMIC_K=16, TAG_WIDTH=35
)(input [511:0] data, weight, input [31:0] data_mask, weight_mask,
    output [43:0] result, output invalid);
    rk_cmac_fp16_cell_dsp_xc7 \1control_kernel (.*);
endmodule
