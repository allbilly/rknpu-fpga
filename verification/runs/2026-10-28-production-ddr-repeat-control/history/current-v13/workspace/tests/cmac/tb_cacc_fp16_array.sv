// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cacc_fp16_array;
    localparam integer K=16;
    logic clk,rst_n=0,in_valid=0,in_first=0,in_last=0,out_ready=0,cancel=0;
    wire in_ready,out_valid,busy,error;
    logic [K*44-1:0] in_groups;
    logic [32:0] in_tag=0;
    wire [32:0] out_tag;
    wire [K*32-1:0] out_values;
    logic [7:0] cancel_code=0;
    wire [7:0] error_code;
    logic [1250:0] vectors[0:511];
    logic [K*44-1:0] group;
    logic [K*32-1:0] expected;
    logic [31:0] rng=32'h3588ca16;
    integer count,frames=0,outputs=0,faults=0,resets=0,cancels=0,held=0;
    string path;
    initial clk=0;
    always #5 clk=~clk;
    rk_cacc_fp16_array #(.ATOMIC_K(K)) dut(.*);
    task automatic tick;@(posedge clk);#1;endtask
    task automatic reset_all;
        @(negedge clk);rst_n=0;in_valid=0;out_ready=0;cancel=1;cancel_code=4;in_groups=0;
        repeat(3) begin tick();if(in_ready||out_valid||busy||error||error_code!==0) $fatal(1,"reset dominance");end
        @(negedge clk);rst_n=1;cancel=0;cancel_code=0;
        repeat(6) begin tick();if(out_valid||busy||error) $fatal(1,"stale reset state");end
        if(!in_ready) $fatal(1,"idle not ready");
    endtask
    task automatic send(input logic [K*44-1:0] data,input logic first,last,input logic [32:0] tag);
        @(negedge clk);in_valid=1;in_groups=data;in_first=first;in_last=last;in_tag=tag;
        begin: accepted
            for(integer age=0;age<32;age=age+1) begin
                @(posedge clk);
                if(in_ready) begin #1;disable accepted;end
                #1;if(error) $fatal(1,"unexpected error waiting input");
            end
            $fatal(1,"acceptance timeout");
        end
        @(negedge clk);in_valid=0;
    endtask
    task automatic partial_done;
        begin: partial_wait
            for(integer age=0;age<16;age=age+1) begin
                tick();if(error||out_valid||!busy) $fatal(1,"partial ownership");
                if(in_ready) disable partial_wait;
            end
            $fatal(1,"partial timeout");
        end
    endtask
    task automatic finish_frame(input logic [K*32-1:0] values,input logic [32:0] tag,input integer stall);
        begin: final_wait
            for(integer age=0;age<16;age=age+1) begin
                tick();if(error||!busy) $fatal(1,"final ownership");
                if(out_valid) disable final_wait;
            end
            $fatal(1,"final timeout");
        end
        @(negedge clk);in_valid=1;in_groups=0;in_first=1;in_last=1;in_tag=~tag;
        repeat(stall+1) begin
            tick();held=held+1;
            if(!out_valid||out_values!==values||out_tag!==tag||in_ready||!busy||error)
                $fatal(1,"held frame mismatch got=%h expected=%h tag=%h",out_values,values,out_tag);
        end
        @(negedge clk);in_valid=0;out_ready=1;tick();
        if(out_valid||busy||error||!in_ready) $fatal(1,"atomic retirement");
        @(negedge clk);out_ready=0;outputs=outputs+K;
    endtask
    task automatic sticky(input logic [7:0] code);
        if(!error||error_code!==code) $fatal(1,"wrong fault got=%h expected=%h",error_code,code);
        repeat(16) begin
            @(negedge clk);in_valid=1;out_ready=1;cancel=0;tick();
            if(!error||error_code!==code||in_ready||out_valid||busy) $fatal(1,"fault escaped bank");
        end
    endtask
    task automatic known_frame(input logic two_groups);
        for(integer k=0;k<K;k=k+1) begin
            group[k*44+:44]={6'(30+k),38'd1048576};
            expected[k*32+:32]=32'h3f800000+(32'(k+int'(two_groups))<<23);
        end
        send(group,1,!two_groups,33'd17);
        if(two_groups) begin partial_done();repeat(12) tick();send(group,0,1,33'd17);end
        finish_frame(expected,33'd17,7);
    endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",path)||!$value$plusargs("COUNT=%d",count)) $fatal(1,"missing vectors");
        if(count<1||count>512) $fatal(1,"invalid count");
        $readmemh(path,vectors,0,count-1);reset_all();
        for(integer i=0;i<count;i=i+1) begin
            rng=rng*32'd1664525+32'd1013904223;
            repeat(int'(rng[2:0])) tick();
            send(vectors[i][1250:547],vectors[i][546],vectors[i][545],vectors[i][544:512]);frames=frames+1;
            if(vectors[i][545]) finish_frame(vectors[i][511:0],vectors[i][544:512],int'(rng[5:3]));
            else partial_done();
        end
        // Distinct per-kernel powers of two expose lane swaps and state sharing.
        known_frame(0);known_frame(1);
        // One invalid kernel must fault the entire atomic frame, not emit a
        // partial set of results from the otherwise legal kernels.
        for(integer k=0;k<K;k=k+1) begin
            reset_all();group=0;group[k*44+:44]={6'd30,3'b001,35'd0};
            send(group,1,1,17);sticky(6);faults=faults+1;
        end
        reset_all();send(0,0,1,17);sticky(6);faults=faults+1;
        reset_all();send(0,1,0,17);partial_done();send(0,1,1,17);sticky(6);faults=faults+1;
        reset_all();send(0,1,0,17);partial_done();send(0,0,1,18);sticky(6);faults=faults+1;
        reset_all();group=0;group[43:0]={6'h3f,38'd1};send(group,1,1,17);sticky(6);faults=faults+1;
`ifndef VERILATOR
        reset_all();group=0;group[K*44-1-:44]='x;send(group,1,1,17);sticky(6);faults=faults+1;
        reset_all();send(0,1'bx,1,17);sticky(6);faults=faults+1;
        reset_all();send(0,1,1'bx,17);sticky(6);faults=faults+1;
        reset_all();send(0,1,1,33'bx);sticky(6);faults=faults+1;
`endif
        for(integer age=0;age<9;age=age+1) begin
            reset_all();send(0,1,1,17);repeat(age) tick();
            reset_all();resets=resets+1;known_frame(1);
        end
        for(integer phase=0;phase<4;phase=phase+1) begin
            reset_all();
            if(phase!=0) send(0,1,phase!=1,17);
            if(phase==3) repeat(8) tick();
            @(negedge clk);cancel=1;cancel_code=2;tick();sticky(2);cancels=cancels+1;
        end
        reset_all();@(negedge clk);cancel=1;cancel_code=0;tick();sticky(6);cancels=cancels+1;
        reset_all();known_frame(1);
        $display("PASS CACC FP16 array K=16 frames=%0d outputs=%0d faults=%0d resets=%0d cancels=%0d held=%0d seed=3588ca16",frames,outputs,faults,resets,cancels,held);
        $finish;
    end
    initial begin #2000000;$fatal(1,"CACC array watchdog");end
endmodule
