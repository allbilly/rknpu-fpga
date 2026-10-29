// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
`ifdef VERILATOR
// Two-state checker: preserve the condition/interface, without claiming X/Z
// coverage. Icarus below uses the original NVIDIA four-state implementation.
module nv_assert_no_x #(parameter severity_level=0,width=32,options=0,msg="VIOLATION") (
    input clk,reset_,start_event,
    input [width-1:0] test_expr
);
    initial begin
        if (severity_level!=0||options!=0||width<1) $fatal(1,"unsupported assertion configuration");
    end
    always @(posedge clk) begin
        if (reset_&&start_event&&$isunknown(test_expr)) $fatal(1,"ERROR : %s : %m",msg);
    end
endmodule
`else
`include "nv_assert_no_x.vlib"
`endif
