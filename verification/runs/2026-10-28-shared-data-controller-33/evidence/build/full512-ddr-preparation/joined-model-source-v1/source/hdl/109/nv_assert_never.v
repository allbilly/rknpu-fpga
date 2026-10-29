// SPDX-License-Identifier: MIT
// Simulation adapter only. All five donor assertion expressions stay enabled.
`timescale 1ns/1ps
`ifdef VERILATOR
// The two-state simulator cannot elaborate the original helper's Z-sensitive
// reset checks. Match its known-0/1 reset and violation behavior. The runner
// rejects any ERROR line, even when the HDL executable exits successfully.
`define FV_ASSERT_ON
module nv_assert_never #(parameter severity_level=0,options=0,msg="VIOLATION") (
    input clk,reset_,test_expr
);
    integer error_count;
    reg reset_seen;
    initial begin
        error_count=0;reset_seen=0;
        if (severity_level!=0 || options!=0) $fatal(1,"unsupported assertion configuration");
    end
    always @(posedge clk or negedge reset_) begin
        if (!reset_) reset_seen<=1;
        else if (reset_seen && test_expr) begin
            error_count<=error_count+1;
            $display("ERROR : %s : original donor condition : %m",msg);
        end
    end
endmodule
`else
// Retain NVIDIA's actual procedural four-state checker in Icarus.
`include "nv_assert_never.vlib"
`endif
