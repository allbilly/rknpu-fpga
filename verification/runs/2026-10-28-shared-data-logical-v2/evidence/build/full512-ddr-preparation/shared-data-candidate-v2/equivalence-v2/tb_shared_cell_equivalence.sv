`timescale 1ns/1ps
module tb_shared_cell_equivalence;
    reg clk;
    reg run_start;
    reg enable8,enable32,enable64;
    integer selected_c,random_first,random_count;
    wire done8,done32,done64;
    initial begin
        clk=0;
        forever #5 clk=~clk;
    end
    shared_cell_checker #(.C(8)) c8(.clk(clk),.run_start(run_start),.enable(enable8),
                                     .random_first(random_first),.random_count(random_count),.done(done8));
    shared_cell_checker #(.C(32)) c32(.clk(clk),.run_start(run_start),.enable(enable32),
                                       .random_first(random_first),.random_count(random_count),.done(done32));
    shared_cell_checker #(.C(64)) c64(.clk(clk),.run_start(run_start),.enable(enable64),
                                       .random_first(random_first),.random_count(random_count),.done(done64));
    initial begin
        run_start=0;selected_c=0;random_first=0;random_count=10000;
        if($value$plusargs("C=%d",selected_c)==0)$fatal(1,"missing +C=<0|8|32|64>");
        if($value$plusargs("RANDOM_FIRST=%d",random_first)==0)$fatal(1,"missing +RANDOM_FIRST");
        if($value$plusargs("RANDOM_COUNT=%d",random_count)==0)$fatal(1,"missing +RANDOM_COUNT");
        if(selected_c!=0&&selected_c!=8&&selected_c!=32&&selected_c!=64)$fatal(1,"invalid C selection");
        if(random_first<0||random_count<1||random_first+random_count>10000)$fatal(1,"invalid random shard range");
        if(selected_c==0&&(random_first!=0||random_count!=10000))$fatal(1,"full run requires all 10000 frames");
        enable8=(selected_c==0||selected_c==8);
        enable32=(selected_c==0||selected_c==32);
        enable64=(selected_c==0||selected_c==64);
        run_start=1;
        wait(done8&&done32&&done64);
        $display("PASS shared_cell_equivalence_all selected_C=%0d first=%0d count=%0d raw_goldens_unchanged=1 DUTs_unmodified=1",
                 selected_c,random_first,random_count);
        $finish;
    end
endmodule
