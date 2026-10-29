`timescale 1ns/1ps
module tb_demo;
    logic clk,rst_n=0,pass,fail;
    logic [7:0] error_code;
    integer cycles;
    initial begin clk=0; cycles=0; end
    always #10 clk=~clk;
    rk_ew_demo dut(.*);
    always @(posedge clk) if (rst_n) begin
        cycles<=cycles+1;
        if (cycles>2000000) $fatal(1,"demo timeout");
        if (fail) $fatal(1,"demo error %02h",error_code);
    end
    initial begin
        repeat(4) @(negedge clk);
        rst_n=1;
        wait(pass || fail);
        @(negedge clk);
        if (fail) $fatal(1,"demo failed %02h",error_code);
        $display("PASS BRAM-only three-operation demo, cycles=%0d",cycles);
        // Reset/restart also tests that no stale BRAM or configuration is needed.
        rst_n=0;
        repeat(4) @(negedge clk);
        rst_n=1;
        wait(pass || fail);
        @(negedge clk);
        if (fail) $fatal(1,"demo restart failed %02h",error_code);
        $display("PASS BRAM demo restart");
        $finish;
    end
endmodule
