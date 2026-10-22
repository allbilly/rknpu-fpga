// SPDX-License-Identifier: MIT
// Structural JSON-export control only: one DSP/FF, not array or numerical evidence.
module prefix_frontend_library_bridge(
    input clk, reset, input [29:0] data, input [17:0] weight,
    output [47:0] product, output captured
);
    DSP48E1 #(.AREG(0), .BREG(0), .USE_MULT("MULTIPLY")) control_dsp(
        .A(data), .B(weight), .P(product));
    FDCE #(.INIT(1'b0)) control_ff(
        .C(clk), .CE(1'b1), .CLR(reset), .D(product[0]), .Q(captured));
endmodule
module prefix_frontend_library_export_control(
    input clk, reset, input [29:0] data, input [17:0] weight,
    output [47:0] product, output captured
);
    prefix_frontend_library_bridge native_wire_bridge(.*);
endmodule
