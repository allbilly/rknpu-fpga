// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_frame_output;
    logic clk,rst_n=0,in_valid=0,in_last=0,cancel=0;
    wire in_ready,busy,acknowledged,frame_done,done,error;
    logic [511:0] in_values=0;
    logic [31:0] in_address=0;
    logic [7:0] cancel_code=0;
    wire [7:0] error_code;
    wire mem_req_valid,mem_req_write,mem_rsp_ready;
    logic mem_req_ready=0,mem_rsp_valid=0,mem_rsp_error=0;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic [767:0] vectors[0:63];
    logic [15:0] memory[0:2047],expected_memory[0:2047];
    integer count,requests=0,acks=0,frames=0,jobs=0,faults=0,cancels=0,resets=0;
    string path;
    initial clk=0;
    always #5 clk=~clk;
    rk_cmac_frame_output #(.TIMEOUT_CYCLES(32)) dut(.*);
    task automatic tick;@(posedge clk);#1;endtask
    task automatic reset_all;
        @(negedge clk);rst_n=0;in_valid=0;cancel=1;cancel_code=4;
        mem_req_ready=0;mem_rsp_valid=0;mem_rsp_error=0;
        repeat(3) begin
            tick();if(in_ready||busy||acknowledged||frame_done||done||error||error_code!==0||mem_req_valid||mem_rsp_ready) $fatal(1,"reset dominance");
        end
        @(negedge clk);cancel=0;cancel_code=0;rst_n=1;
        repeat(6) begin tick();if(busy||error||mem_req_valid||mem_rsp_ready||done) $fatal(1,"stale reset state");end
        if(!in_ready) $fatal(1,"idle not ready");
    endtask
    task automatic submit(input integer row,input logic [31:0] address,input logic last);
        if(row<0||row>=count) $fatal(1,"frame index outside loaded corpus");
        @(negedge clk);in_valid=1;in_values=vectors[row][767:256];in_address=address;in_last=last;
        if(!in_ready) $fatal(1,"unexpected input stall");
        tick();@(negedge clk);in_valid=0;
        // Poison inactive producer pins: conversion must use the full snapshot.
        in_values=~vectors[row][767:256];in_address=~address;in_last=~last;
    endtask
    task automatic wait_request(input integer row,lane,input logic [31:0] base);
        begin: wait_req
            for(integer age=0;age<64;age=age+1) begin
                tick();if(error||!busy||in_ready||acknowledged||frame_done||done) $fatal(1,"ownership before request");
                if(mem_req_valid) disable wait_req;
            end
            $fatal(1,"missing write request");
        end
        if(!mem_req_write||mem_req_addr!==base+32'(lane*2)||mem_req_wdata!==vectors[row][lane*16+:16])
            $fatal(1,"write mismatch row=%0d lane=%0d got=%h/%h expected=%h/%h",row,lane,mem_req_addr,mem_req_wdata,base+32'(lane*2),vectors[row][lane*16+:16]);
    endtask
    task automatic take_request(input integer row,lane,input logic [31:0] base);
        wait_request(row,lane,base);
        repeat((lane%5)+1) begin
            tick();if(!mem_req_valid||mem_req_addr!==base+32'(lane*2)||mem_req_wdata!==vectors[row][lane*16+:16]||in_ready||!busy) $fatal(1,"stalled request changed");
        end
        @(negedge clk);mem_req_ready=1;tick();requests=requests+1;
        if(mem_req_valid||!mem_rsp_ready||acknowledged||frame_done||done) $fatal(1,"request is not completion");
        if(base>=32'h10040000&&base<32'h10041000) memory[int'((base-32'h10040000)>>1)+lane]=vectors[row][lane*16+:16];
        @(negedge clk);mem_req_ready=0;
    endtask
    task automatic reply(input integer lane,input logic last,input logic failed);
        repeat(lane==15 ? 23 : (lane%3)+1) begin
            tick();if(!mem_rsp_ready||mem_req_valid||acknowledged||frame_done||done||in_ready||!busy) $fatal(1,"response wait ownership");
        end
        @(negedge clk);mem_rsp_valid=1;mem_rsp_error=failed;tick();
        if(failed!==1'b0) begin
            if(!error||error_code!==5||acknowledged||frame_done||done) $fatal(1,"failed response completed");
        end else begin
            if(!acknowledged||frame_done!==(lane==15)||done!==(lane==15&&last)) $fatal(1,"completion not final ack");
            acks=acks+1;
            if(lane==15) begin frames=frames+1;if(last) jobs=jobs+1;end
        end
        @(negedge clk);mem_rsp_valid=0;mem_rsp_error=0;tick();
        if(!error&&(acknowledged||frame_done||done)) $fatal(1,"completion pulse repeated");
        if(lane==15&&!error&&(!in_ready||busy)) $fatal(1,"frame not released");
    endtask
    task automatic complete(input integer row,input logic [31:0] base,input logic last);
        submit(row,base,last);
        for(integer lane=0;lane<16;lane=lane+1) begin take_request(row,lane,base);reply(lane,last,0);end
    endtask
    task automatic sticky(input logic [7:0] code);
        if(!error||error_code!==code) $fatal(1,"wrong error code got=%h expected=%h",error_code,code);
        repeat(12) begin
            @(negedge clk);cancel=0;in_valid=1;mem_req_ready=1;mem_rsp_valid=1;tick();
            if(!error||error_code!==code||in_ready||busy||mem_req_valid||mem_rsp_ready||acknowledged||frame_done||done) $fatal(1,"sticky fault escaped");
        end
    endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",path)||!$value$plusargs("COUNT=%d",count)) $fatal(1,"missing vectors");
        if(count<1||count>64) $fatal(1,"invalid count");
        $readmemh(path,vectors,0,count-1);
        for(integer i=0;i<2048;i=i+1) begin memory[i]=16'ha55a;expected_memory[i]=16'ha55a;end
        reset_all();
        for(integer row=0;row<count;row=row+1) begin
            for(integer lane=0;lane<16;lane=lane+1) expected_memory[row*32+lane]=vectors[row][lane*16+:16];
            complete(row,32'h10040000+32'(row*64),row==count-1);
        end
        for(integer i=0;i<2048;i=i+1) if(memory[i]!==expected_memory[i]) $fatal(1,"gap/sentinel changed at %0d",i);
        complete(0,0,1);complete(count-1,32'hffffffe0,1);complete(count-1,32'h10040010,1);
        // First, middle and final response failure: writes may have committed,
        // but no final completion may escape on a failed response.
        for(integer at=0;at<3;at=at+1) begin
            reset_all();submit(count-1,32'h10040000,1);
            for(integer lane=0;lane<=(at==0 ? 0 : at==1 ? 7 : 15);lane=lane+1) begin
                take_request(count-1,lane,32'h10040000);
                reply(lane,1,lane==(at==0 ? 0 : at==1 ? 7 : 15));
            end
            sticky(5);faults=faults+1;
        end
        for(integer phase=0;phase<2;phase=phase+1) begin
            reset_all();submit(0,32'h10040000,1);
            if(phase==0) wait_request(0,0,32'h10040000);else take_request(0,0,32'h10040000);
            repeat(33) tick();sticky(8);faults=faults+1;
        end
        for(integer bad=0;bad<3;bad=bad+1) begin
            reset_all();submit(0,bad==0 ? 32'h10040001 : bad==1 ? 32'h10040002 : 32'hfffffff0,1);
            sticky(4);faults=faults+1;
        end
`ifndef VERILATOR
        reset_all();submit(0,32'bx,1);sticky(4);faults=faults+1;
        reset_all();submit(0,32'h10040000,1'bx);sticky(6);faults=faults+1;
        reset_all();@(negedge clk);in_values='x;in_address=32'h10040000;in_last=1;in_valid=1;tick();sticky(6);faults=faults+1;
        reset_all();submit(0,32'h10040000,1);take_request(0,0,32'h10040000);reply(0,1,1'bx);sticky(5);faults=faults+1;
`endif
        for(integer phase=0;phase<3;phase=phase+1) begin
            reset_all();submit(0,32'h10040000,1);
            if(phase==1) wait_request(0,0,32'h10040000);
            if(phase==2) take_request(0,0,32'h10040000);
            @(negedge clk);cancel=1;cancel_code=2;tick();sticky(2);cancels=cancels+1;
        end
        for(integer phase=0;phase<3;phase=phase+1) begin
            reset_all();submit(0,32'h10040000,1);
            if(phase==1) wait_request(0,0,32'h10040000);
            if(phase==2) begin take_request(0,0,32'h10040000);reply(0,1,0);take_request(0,1,32'h10040000);end
            reset_all();resets=resets+1;complete(0,32'h10040000,1);
        end
        $display("PASS OC16 frame output corpus=%0d frames=%0d jobs=%0d faults=%0d cancels=%0d resets=%0d requests=%0d acknowledgments=%0d",count,frames,jobs,faults,cancels,resets,requests,acks);
        $finish;
    end
    initial begin #2000000;$fatal(1,"frame output watchdog");end
endmodule
