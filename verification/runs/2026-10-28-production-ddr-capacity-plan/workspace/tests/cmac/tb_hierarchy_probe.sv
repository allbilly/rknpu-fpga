// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_hierarchy_probe;
    /* verilator lint_off BLKSEQ */
    logic clk, rst_n=0;
    logic [31:0] data[4], result[4];
    initial clk=0;
    always #5 clk=~clk;
    for (genvar k=0;k<4;k++) begin: lanes
        hierarchy_probe_leaf #(.WIDTH(32)) dut(.clk,.rst_n,.data(data[k]),.result(result[k]));
    end
    initial begin
        for (int k=0;k<4;k++) data[k]=32'(k);
        @(posedge clk); #1;
        for (int k=0;k<4;k++) if(result[k]!==0) $fatal(1,"reset");
        @(negedge clk); rst_n=1;
        for(int i=0;i<32;i++) begin
            for(int k=0;k<4;k++) data[k]=32'(i*17+k);
            @(posedge clk); #1;
            for(int k=0;k<4;k++) if(result[k]!==32'(i*17+k+1)) $fatal(1,"independent instance state");
            @(negedge clk);
        end
        rst_n=0; #1;
        for(int k=0;k<4;k++) if(result[k]!==0) $fatal(1,"asynchronous reset");
        $display("PASS hierarchy probe instances=4 outputs=128 resets=2");
        $finish;
    end
    initial begin #10000; $fatal(1,"probe timeout"); end
    /* verilator lint_on BLKSEQ */
endmodule
