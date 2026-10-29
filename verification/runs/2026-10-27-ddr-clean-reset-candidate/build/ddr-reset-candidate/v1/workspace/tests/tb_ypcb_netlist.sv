`timescale 1ns/1ps
// This test uses only board ports and the mapped Xilinx primitive models.
// No RTL hierarchy, force, or behavioral memory bypass is used.
module tb_ypcb_netlist;
    reg SYS_CLK = 0, SYS_RSTN = 1;
    wire [2:0] led_3bits_tri_o;
    always #10 SYS_CLK = ~SYS_CLK;
    ypcb_top dut (.*);
    task automatic check_pass;
        begin
            wait (led_3bits_tri_o[0] === 1'b1 || led_3bits_tri_o[1] === 1'b1);
            @(negedge SYS_CLK);
            if (led_3bits_tri_o !== 3'b001)
                $fatal(1, "mapped demo failed: LEDs=%b", led_3bits_tri_o);
        end
    endtask
    initial begin
        check_pass();
        #2 SYS_RSTN = 0;
        #3 SYS_RSTN = 1;
        repeat (4) @(negedge SYS_CLK);
        if (led_3bits_tri_o[0] !== 1'b0) $fatal(1, "mapped reset did not clear pass");
        check_pass();
        $display("PASS mapped YPCB: BRAM/DSP/LUT self-test and reset/restart (functional primitive models)");
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "mapped YPCB test timeout");
    end
endmodule
