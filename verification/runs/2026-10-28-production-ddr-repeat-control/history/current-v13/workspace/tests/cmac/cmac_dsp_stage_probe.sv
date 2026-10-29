// Synthesis-stage diagnostic only: four independent signed products.
// This is not a reduced CMAC implementation or an array acceptance test.
module cmac_dsp_stage_probe_kernel(
  input wire signed [15:0] a0, b0, a1, b1,
  output wire signed [31:0] p0, p1
);
  assign p0 = a0 * b0;
  assign p1 = a1 * b1;
endmodule

module cmac_dsp_stage_probe(
  input wire [127:0] operands,
  output wire [127:0] products
);
  cmac_dsp_stage_probe_kernel k0(
    .a0(operands[15:0]), .b0(operands[31:16]),
    .a1(operands[47:32]), .b1(operands[63:48]),
    .p0(products[31:0]), .p1(products[63:32])
  );
  cmac_dsp_stage_probe_kernel k1(
    .a0(operands[79:64]), .b0(operands[95:80]),
    .a1(operands[111:96]), .b1(operands[127:112]),
    .p0(products[95:64]), .p1(products[127:96])
  );
endmodule
