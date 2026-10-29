// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_fp16_product;
    localparam integer N = 230400;
    logic clk, rst_n;
    initial clk=0;
    always #5 clk=~clk;
    logic in_valid, in_ready, out_valid, out_ready;
    logic [15:0] in_a, in_b;
    logic [130:0] in_tag, out_tag;
    logic [31:0] out_product;
    rk_fp16_product dut(.*);
    logic [63:0] vectors [0:N-1];
    string vector_path;
    logic [31:0] rng;
    integer base, sent, received, compared, cycles, stalls, reset_cases;
    integer sent_before, received_before;
    logic holding_output, input_taken;
    logic [162:0] held_output;

    function automatic logic [130:0] tag(input integer index);
        logic [31:0] x;
        x=32'(index)*32'd1664525+32'h3588ca04;
        return {x^32'hbf149861,~x,32'(index),x*32'd1013904223,3'(index)};
    endfunction
    task automatic drive(input integer index);
        in_a=vectors[index][63:48];in_b=vectors[index][47:32];in_tag=tag(index);
    endtask
    task automatic tick;
        logic input_fire, output_fire, pre_valid, pre_ready;
        logic [31:0] value;
        logic [130:0] metadata;
        @(posedge clk);
        input_fire=in_valid && in_ready;
        output_fire=out_valid && out_ready;
        pre_valid=out_valid;pre_ready=out_ready;value=out_product;metadata=out_tag;
        #1;
        cycles=cycles+1;
        input_taken=input_fire;
        if (rst_n) begin
            if (holding_output && (pre_valid!==1 || {value,metadata}!==held_output))
                $fatal(1,"output or full-width tag changed while stalled");
            holding_output=pre_valid && !pre_ready;
            held_output={value,metadata};
            if (holding_output) stalls=stalls+1;
            if (output_fire) begin
                if (received>=sent) $fatal(1,"spurious product");
                if (value !== vectors[base+received][31:0] || metadata !== tag(base+received))
                    $fatal(1,"product/tag mismatch index=%0d A=%h B=%h got=%h expected=%h tag=%h expected_tag=%h",base+received,
                           vectors[base+received][63:48],vectors[base+received][47:32],value,vectors[base+received][31:0],metadata,tag(base+received));
                received=received+1;compared=compared+1;
            end
            if (input_fire) sent=sent+1;
            if (sent-received>3 || sent<received) $fatal(1,"elastic occupancy outside 0..3");
        end
    endtask
    task automatic reset_pipe(input integer first_index);
        @(negedge clk);rst_n=0;in_valid=0;out_ready=0;in_a=0;in_b=0;in_tag=0;
        repeat(2) begin
            tick();
            if (in_ready!==0 || out_valid!==0) $fatal(1,"reset handshake");
        end
        base=first_index;sent=0;received=0;holding_output=0;input_taken=0;
        @(negedge clk);rst_n=1;
        repeat(4) begin
            tick();
            if (out_valid!==0 || in_ready!==1) $fatal(1,"reset leaked an old product");
        end
    endtask
    task automatic fill(input integer count);
        for (integer i=0;i<count;i=i+1) begin
            @(negedge clk);in_valid=1;out_ready=0;drive(base+sent);
            if (in_ready!==1) $fatal(1,"early input stall while filling");
            tick();
            if (out_valid !== (i==2)) $fatal(1,"three-stage latency changed");
        end
        @(negedge clk);in_valid=0;
    endtask
    task automatic stream(input integer count,input logic randomized);
        while (received<count) begin
            @(negedge clk);
            rng=rng*32'd1664525+32'd1013904223;
            out_ready=!randomized || rng[5:3]!=0;
            // Retain the entire offered input until its actual handshake.
            if (!in_valid || input_taken) begin
                in_valid=sent<count && (!randomized || rng[2:0]!=0);
                if (in_valid) drive(base+sent);
            end
            tick();
        end
        @(negedge clk);in_valid=0;out_ready=1;
        repeat(4) begin tick();if (out_valid!==0) $fatal(1,"extra product after drain");end
        if (sent!=count) $fatal(1,"input count mismatch");
    endtask

    initial begin
        rst_n=0;in_valid=0;out_ready=0;in_a=0;in_b=0;in_tag=0;
        rng=32'h3588ca04;base=0;sent=0;received=0;compared=0;cycles=0;stalls=0;reset_cases=0;holding_output=0;input_taken=0;held_output=0;
        if (!$value$plusargs("VECTORS=%s",vector_path)) $fatal(1,"missing VECTORS");
        $readmemh(vector_path,vectors);
        // Cancel one, two and three live stages. The full pipeline is held
        // under output backpressure; replacement tags differ after each reset.
        for (integer depth=1;depth<=3;depth=depth+1) begin
            reset_pipe(depth*16);fill(depth);
            if (depth==3) begin
                repeat(20) begin
                    tick();if (in_ready!==0 || out_valid!==1) $fatal(1,"full pipeline did not hold");
                end
            end
            reset_pipe(100+depth*16);reset_cases=reset_cases+1;stream(8,0);
        end
        // Also reset a full pipeline immediately after a successful output.
        reset_pipe(200);fill(3);
        @(negedge clk);in_valid=1;drive(base+sent);out_ready=1;
        tick();
        if (received!=1 || sent!=4) $fatal(1,"simultaneous consume/refill");
        reset_pipe(300);reset_cases=reset_cases+1;stream(8,0);

        reset_pipe(0);fill(3);
        // Fourth input must remain unaccepted until downstream releases space.
        @(negedge clk);in_valid=1;drive(base+sent);
        repeat(32) begin
            tick();if (in_ready!==0 || out_valid!==1 || sent!=3 || received!=0) $fatal(1,"full-pipeline backpressure");
        end
        // Full-throughput window: one input AND output every cycle.
        for (integer i=0;i<128;i=i+1) begin
            @(negedge clk);out_ready=1;in_valid=1;drive(base+sent);
            sent_before=sent;received_before=received;
            tick();
            if (sent!=sent_before+1 || received!=received_before+1) $fatal(1,"throughput bubble");
        end
        // stream() starts on the following falling edge. Hold the output
        // during the intervening rising edge so no transfer escapes tick().
        @(negedge clk);in_valid=0;out_ready=0;
        stream(N,1);
        if (compared!=N+33 || reset_cases!=4 || stalls<52) $fatal(1,"incomplete product test");
        $display("PASS exact FP16 product vectors=%0d compared=%0d reset_cases=%0d stalls=%0d cycles=%0d seed=3588ca04",N,compared,reset_cases,stalls,cycles);
        $finish;
    end
    initial begin #30000000;$fatal(1,"FP16 product HDL timeout");end
endmodule
