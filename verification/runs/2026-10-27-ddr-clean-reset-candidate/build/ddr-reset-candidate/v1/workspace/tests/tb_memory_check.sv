`timescale 1ns/1ps
// Run the exact shared scoreboard in both simulators without a large DUT build.
module tb_memory_check;
    localparam logic [31:0] BASE=32'h10000000;
    localparam integer WORDS=8;
    logic [15:0] memory [0:WORDS-1];
    `include "tests/memory_check.svh"
    string path;
    integer expected_checks, allow_empty;
    initial begin
        memory[0]=16'h1234; memory[1]=16'habcd;
        for (integer i=2; i<WORDS; i=i+1) memory[i]=0;
        if (!$value$plusargs("FILE=%s",path) || !$value$plusargs("NCHECKS=%d",expected_checks))
            $fatal(1,"missing scoreboard control metadata");
        if (!$value$plusargs("ALLOW_EMPTY=%d",allow_empty)) allow_empty=0;
        verify_memory(path,"",expected_checks,allow_empty!=0);
        $display("PASS shared memory scoreboard control");
        $finish;
    end
endmodule
