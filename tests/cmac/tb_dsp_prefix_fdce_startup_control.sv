// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_dsp_prefix_fdce_startup_control;
    logic clk=0,ce=0,clear=0,data=0;
    wire [2:0] q;
    integer negative=0,checks=0;
    logic expected=0;
    FDCE #(.INIT(1'b0)) init_zero(.C(clk),.CE(ce),.CLR(clear),.D(data),.Q(q[0]));
    FDCE #(.INIT(1'b1)) init_one(.C(clk),.CE(ce),.CLR(clear),.D(data),.Q(q[1]));
    FDCE #(.INIT(1'bx)) actual_init(.C(clk),.CE(ce),.CLR(clear),.D(data),.Q(q[2]));
    task automatic check_all;
        if(q!=={3{expected}}) $fatal(1,"FDCE startup mismatch case=%0d q=%b expected=%b",checks,q,expected);
        checks=checks+1;
    endtask
    initial begin
        if($value$plusargs("NEGATIVE=%d",negative)) begin end
        #1;
        if(q[1:0] !== (2'b10 ^ (negative!=0 ? 2'b01 : 2'b00)))
            $fatal(1,"FDCE startup mismatch case=0 q=%b",q);
`ifndef VERILATOR
        if(q[2] !== 1'bx) $fatal(1,"actual INIT=x not retained in four-state model");
`endif
        // Reset, not an assumed INIT value, establishes all actual INIT=x flops.
        clear=1;#1;expected=0;check_all();clear=0;
        for(integer i=0;i<32;i=i+1) begin
            clk=0;ce=(i&2)!=0;data=(i&1)!=0;clear=(i&4)!=0;
            #1;if(clear) expected=0;check_all();
            clk=1;#1;if(clear) expected=0;else if(ce) expected=data;check_all();
            data=~data;#1;check_all();
            clk=0;#1;check_all();
        end
        if(checks!=129) $fatal(1,"FDCE control count mismatch");
        $display("PASS actual prefix FDCE startup/reset control checks=129 init_variants=0/1/X; not array or FPGA acceptance");
        $finish;
    end
endmodule
