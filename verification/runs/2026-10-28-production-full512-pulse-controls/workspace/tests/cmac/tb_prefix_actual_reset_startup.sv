// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Selected actual controller fixture, not a full-board or electrical proof.
module tb_prefix_actual_reset_startup;
    reg clk=0;
    always #10 clk=~clk;
    reg buffered_reset_n=1;
    reg [@OTHER_LAST@:0] producer_input='x;
    wire [49:0] controller_state;
    wire [2:0] reset_chain;
    wire [3:0] demo_state;
    wire [11:0] word_index;
    wire host_enable,host_we,core_enable,core_we;
    actual_prefix_reset_controller actual(.clk,.buffered_reset_n,.producer_input,
        .controller_state,.reset_chain,.demo_state,.word_index,
        .host_enable,.host_we,.core_enable,.core_we);
    reg [2:0] expected_reset=0;
    integer negative=0,total_writes=0,prefix_writes=0,complete_prefixes=0,reset_pulses=0;
    integer sampled_edges=0;
    reg monitor=0;

    always @(posedge clk or negedge buffered_reset_n) begin
        if (!buffered_reset_n) expected_reset<=0;
        else if (glbl.GSR) expected_reset<=0;
        else expected_reset<={expected_reset[1:0],1'b1};
    end

    always @(posedge clk) begin
        if (monitor) begin
            if (reset_chain[2]===1'b0) prefix_writes=0;
            else if (reset_chain[2]!==1'b1) $fatal(1,"unknown actual outer reset");
            else if (host_enable===1'b1&&host_we===1'b1) begin
                if (prefix_writes>=4096||word_index!==12'(prefix_writes))
                    $fatal(1,"actual initialization address mismatch got=%h expected=%0d",word_index,prefix_writes);
                prefix_writes=prefix_writes+1;
                total_writes=total_writes+1;
            end
        end
        #2;
        if (monitor) begin
            sampled_edges=sampled_edges+1;
            if (reset_chain!==expected_reset)
                $fatal(1,"actual reset chain mismatch got=%b expected=%b",reset_chain,expected_reset);
            if ($isunknown(controller_state)||$isunknown(demo_state)||$isunknown(word_index))
                $fatal(1,"unknown actual controller state after default GSR state=%b index=%b",demo_state,word_index);
            if ($isunknown({host_enable,host_we,core_enable,core_we}))
                $fatal(1,"unknown actual BRAM pin during initialization");
            if (core_enable!==1'b0||core_we!==1'b0)
                $fatal(1,"actual core RAM access before first START");
            if (host_enable===1'b1&&host_we!==1'b1)
                $fatal(1,"actual sensitive host read during initialization");
            if (!$isunknown(producer_input)) $fatal(1,"fixture unknown producers changed");
        end
    end

    task automatic asynchronous_restart;
        @(negedge clk);#3;buffered_reset_n=0;
        #2;
        if (reset_chain!==3'b000||controller_state!==50'b0||
            {host_enable,host_we,core_enable,core_we}!==4'b0000)
            $fatal(1,"actual asynchronous reset did not clear selected controller and pins");
        prefix_writes=0;
        reset_pulses=reset_pulses+1;
        @(negedge clk);buffered_reset_n=1;
    endtask

    task automatic finish_prefix;
        wait(demo_state===4'd3);#3;
        if (prefix_writes!=4096) $fatal(1,"actual initialization prefix incomplete got=%0d",prefix_writes);
        complete_prefixes=complete_prefixes+1;
    endtask

    initial begin
        if($value$plusargs("NEGATIVE=%d",negative)) begin end
        #1;
        if(glbl.GSR!==1'b1||reset_chain!==3'b000)
            $fatal(1,"default GSR or actual zero-INIT reset chain missing");
        if(controller_state!==50'bx) $fatal(1,"actual unknown controller INIT changed");
        if({host_enable,host_we,core_enable,core_we}!==4'b0000)
            $fatal(1,"actual BRAM enables/writes not masked during default GSR");
        wait(glbl.GSR===1'b0);#2;
        if(reset_chain!==(negative?3'b100:3'b000))
            $fatal(1,"actual reset startup mismatch phase=after_gsr got=%b expected=%b",reset_chain,negative?3'b100:3'b000);
        if(controller_state!==50'b0) $fatal(1,"actual controller did not asynchronously clear after GSR");
        monitor=1;
        finish_prefix();
        asynchronous_restart();
        wait(prefix_writes==1);
        asynchronous_restart();
        wait(prefix_writes==2048);
        asynchronous_restart();
        finish_prefix();
        monitor=0;
        if(total_writes!=10241||complete_prefixes!=2||reset_pulses!=3||sampled_edges<30000)
            $fatal(1,"incomplete actual controller startup corpus writes=%0d prefixes=%0d resets=%0d edges=%0d",total_writes,complete_prefixes,reset_pulses,sampled_edges);
        $display("PASS actual selected controller vendor startup registers=53 unknown_producers=@OTHER_BITS@ default_gsr=100ns physical_A_writes=10241 complete_prefixes=2 asynchronous_resets=3; not full-board startup or physical signoff");
        $finish;
    end
    initial begin #1000000;$fatal(1,"selected controller startup deadline");end
endmodule
