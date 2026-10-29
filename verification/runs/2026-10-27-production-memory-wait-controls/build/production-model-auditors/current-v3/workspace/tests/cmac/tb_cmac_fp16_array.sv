// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_fp16_array #(
    parameter int unsigned ATOMIC_C=32,ATOMIC_K=16
);
    // Testbench clock/scoreboard only; DUT lint remains enabled.
    /* verilator lint_off BLKSEQ */
    localparam integer BITS=ATOMIC_C*16+ATOMIC_K*ATOMIC_C*16+ATOMIC_C+ATOMIC_K*ATOMIC_C+ATOMIC_K*44;
    logic clk,rst_n=0,in_valid=0,in_ready,out_valid,out_ready=0,error;
    logic [ATOMIC_C*16-1:0] in_data=0;
    logic [ATOMIC_K*ATOMIC_C*16-1:0] in_weight=0;
    logic [ATOMIC_C-1:0] in_data_mask=0;
    logic [ATOMIC_K*ATOMIC_C-1:0] in_weight_mask=0;
    logic [34:0] in_tag=0,out_tag;
    logic [ATOMIC_K*44-1:0] out_groups,expected;
    logic [BITS-1:0] vectors[0:511];
    integer count,outputs=0,holds=0,resets=0,faults=0;
    string path;
    initial clk=0;
    always #5 clk=~clk;
    rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);
    task automatic tick;@(posedge clk);#1;endtask
    task automatic reset_all;
        @(negedge clk);rst_n=0;in_valid=0;out_ready=0;
        tick();if(in_ready||out_valid||error) $fatal(1,"reset ownership");
        @(negedge clk);rst_n=1;
        tick();if(!in_ready||out_valid||error) $fatal(1,"configuration warmup");
    endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",path)||!$value$plusargs("COUNT=%d",count)) $fatal(1,"missing vectors");
        if(count<1||count>512) $fatal(1,"invalid vector count");
        $readmemh(path,vectors,0,count-1);reset_all();
        for(integer i=0;i<count;i=i+1) begin
            @(negedge clk);
            {in_data,in_weight,in_data_mask,in_weight_mask,expected}=vectors[i];
            in_tag=35'(i);in_valid=1;
            if(!in_ready) $fatal(1,"input not ready");
            tick();
            if(!out_valid||error||out_groups!==expected||out_tag!==35'(i))
                $fatal(1,"sized array mismatch frame=%0d got=%h expected=%h",i,out_groups,expected);
            @(negedge clk);in_valid=0;in_data='1;in_weight='1;in_tag='1;
            repeat(i%4+1) begin
                tick();holds=holds+1;
                if(in_ready||!out_valid||out_groups!==expected||out_tag!==35'(i)||error) $fatal(1,"held result changed");
            end
            if(i==count/2) begin
                // Cancel a held output by reset; it must never leak afterward.
                reset_all();resets=resets+1;
            end else begin
                @(negedge clk);out_ready=1;tick();outputs=outputs+ATOMIC_K;
                if(out_valid||!in_ready||error) $fatal(1,"retirement");
                @(negedge clk);out_ready=0;
            end
        end
`ifndef VERILATOR
        reset_all();@(negedge clk);in_data='x;in_valid=1;tick();
        if(!error||out_valid||in_ready) $fatal(1,"unknown input accepted");
        faults=faults+1;
        repeat(3) begin tick();if(!error||out_valid||in_ready) $fatal(1,"fault not sticky");end
`endif
        reset_all();
        $display("PASS sized FP16 CMAC C=%0d K=%0d frames=%0d checked_outputs=%0d retired_outputs=%0d reset_canceled=%0d held_cycles=%0d faults=%0d",ATOMIC_C,ATOMIC_K,count,count*ATOMIC_K,outputs,resets*ATOMIC_K,holds,faults);
        $finish;
    end
    initial begin #1000000;$fatal(1,"array unit timeout");end
    /* verilator lint_on BLKSEQ */
endmodule
