// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_array_core;
    logic clk,rst_n=0,cmd_valid=0,cancel=0;
    logic [63:0] cmd_data=0,commands[0:48];
    logic [7:0] cancel_code=0;
    wire cmd_ready,busy,acknowledged,frame_done,done,error;
    wire [7:0] error_code;
    wire mem_req_valid,mem_req_ready,mem_req_write,mem_rsp_valid,mem_rsp_ready,mem_rsp_error;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata,mem_rsp_rdata;
    logic [15:0] input_memory[0:1023],weight_memory[0:8191],output_memory[0:2047];
    logic [47:0] expected_reads[0:16383],expected_writes[0:1023];
    logic pending,pending_write,pending_error;
    logic [15:0] response_data;
    logic [31:0] rng;
    integer delay_left,read_requests,write_requests,read_responses,write_responses,acks,frames,jobs;
    integer mode,rows,ai,ao,read_count,write_count;
    string directory;
    initial clk=0;
    always #5 clk=~clk;
    assign mem_req_ready=rst_n&&!pending&&mode!=3&&rng[1:0]!=0;
    assign mem_rsp_valid=rst_n&&pending&&delay_left==0&&mode!=4;
    assign mem_rsp_rdata=response_data;
    assign mem_rsp_error=pending_error;
    rk_cmac_array_core #(.TIMEOUT_CYCLES(128)) dut(.*);
    always @(posedge clk or negedge rst_n) begin: memory_slave
        logic response_fire,expected_ack,expected_frame,expected_done;
        logic [15:0] read_value;
        integer index;
        if(!rst_n) begin
            pending<=0;pending_write<=0;pending_error<=0;response_data<=0;delay_left<=0;
            read_requests<=0;write_requests<=0;read_responses<=0;write_responses<=0;
            acks<=0;frames<=0;jobs<=0;rng<=32'h3588ac16;
            for(integer i=0;i<2048;i=i+1) output_memory[i]<=16'ha55a;
        end else begin
            rng<=rng*32'd1664525+32'd1013904223;
            response_fire=mem_rsp_valid&&mem_rsp_ready;
            expected_ack=response_fire&&pending_write&&!pending_error;
            expected_frame=expected_ack&&write_responses%16==15;
            expected_done=expected_frame&&write_responses==write_count-1;
            if(mem_req_valid&&mem_req_ready) begin
                if(pending||mem_req_addr[0]) $fatal(1,"invalid request ownership/alignment");
                pending<=1;pending_write<=mem_req_write;pending_error<=0;
                delay_left<=int'(rng[5:3])+1;
                if(mem_req_write) begin
                    if(write_requests>=write_count||{mem_req_addr,mem_req_wdata}!==expected_writes[write_requests])
                        $fatal(1,"raw core write mismatch index=%0d addr=%h data=%h expected=%h",write_requests,mem_req_addr,mem_req_wdata,expected_writes[write_requests]);
                    index=int'((mem_req_addr-32'h10040000)>>1);
                    if(index<0||index>=rows*ao*2) $fatal(1,"output write outside physical allocation");
                    output_memory[index]<=mem_req_wdata;
                    write_requests<=write_requests+1;
                    if(write_requests==write_count-1) begin delay_left<=31;pending_error<=mode==2;end
                end else begin
                    if(mem_req_addr>=32'h10010000&&mem_req_addr<32'h10010000+32'(rows*ai*2))
                        read_value=input_memory[(mem_req_addr-32'h10010000)>>1];
                    else if(mem_req_addr>=32'h10020000&&mem_req_addr<32'h10020000+32'(ai*ao*2))
                        read_value=weight_memory[(mem_req_addr-32'h10020000)>>1];
                    else begin read_value=0;$fatal(1,"read outside physical operand allocation addr=%h",mem_req_addr);end
                    if(read_requests>=read_count||{mem_req_addr,read_value}!==expected_reads[read_requests])
                        $fatal(1,"raw core read order/data index=%0d addr=%h",read_requests,mem_req_addr);
                    response_data<=read_value;
                    pending_error<=mode==1&&read_requests==0;
`ifndef VERILATOR
                    if(mode==9&&read_requests==0) response_data<='x;
`endif
                    read_requests<=read_requests+1;
                end
            end
            if(pending) begin
                if(delay_left>0) delay_left<=delay_left-1;
                else if(response_fire) begin
                    pending<=0;
                    if(pending_write) write_responses<=write_responses+1;
                    else read_responses<=read_responses+1;
                end
            end
            if(expected_ack) acks<=acks+1;
            if(expected_frame) frames<=frames+1;
            if(expected_done) jobs<=jobs+1;
            #1;
            if(acknowledged!==expected_ack||frame_done!==expected_frame||done!==expected_done)
                $fatal(1,"raw core completion differs from successful write response");
        end
    end
    task automatic tick;@(posedge clk);#2;endtask
    task automatic reset_all;
        @(negedge clk);rst_n=0;cmd_valid=0;cancel=0;cancel_code=0;
        repeat(3) begin tick();if(cmd_ready||busy||error||done||mem_req_valid||mem_rsp_ready) $fatal(1,"raw reset dominance");end
        @(negedge clk);rst_n=1;repeat(6) tick();if(!cmd_ready||busy||error) $fatal(1,"raw reset release");
    endtask
    task automatic send_word(input logic [63:0] word);
        @(negedge clk);cmd_valid=1;cmd_data=word;
        begin: accept_word
            for(integer age=0;age<256;age=age+1) begin
                @(posedge clk);if(cmd_ready) begin #2;disable accept_word;end
                #2;if(error) $fatal(1,"command unexpectedly rejected");
            end
            $fatal(1,"command input timeout");
        end
        @(negedge clk);cmd_valid=0;
    endtask
    task automatic submit;
        for(integer i=0;i<49;i=i+1) send_word(commands[i]);
    endtask
    task automatic finish_job;
        begin: await_done
            for(integer age=0;age<300000;age=age+1) begin
                tick();if(error) $fatal(1,"raw replay failed code=%0d reads=%0d writes=%0d",error_code,read_requests,write_requests);
                if(done) disable await_done;
                if(!busy||cmd_ready) $fatal(1,"raw job lost ownership before completion");
            end
            $fatal(1,"raw replay simulation-cycle watchdog");
        end
        repeat(8) begin tick();if(error||busy||done||mem_req_valid||!cmd_ready) $fatal(1,"raw replay failed to drain");end
        if(read_requests!=read_count||read_responses!=read_count||write_requests!=write_count||write_responses!=write_count||acks!=write_count||jobs!=1||frames!=write_count/16)
            $fatal(1,"raw replay transaction counts");
        for(integer i=0;i<2048;i=i+1) begin
            if(i<rows*ao*2&&i%32<16) begin
                if(output_memory[i]!==expected_writes[(i/32)*16+i%32][15:0]) $fatal(1,"raw output memory mismatch");
            end else if(output_memory[i]!==16'ha55a) $fatal(1,"raw output gap/sentinel changed");
        end
    endtask
    task automatic expect_fault(input logic [7:0] code);
        begin: await_fault
            for(integer age=0;age<300000;age=age+1) begin tick();if(error) disable await_fault;end
            $fatal(1,"missing raw core fault");
        end
        if(error_code!==code||jobs!=0||done) $fatal(1,"raw fault/completion code=%0d expected=%0d",error_code,code);
        @(negedge clk);cancel=0;cmd_valid=1;cmd_data=commands[0];
        repeat(16) begin tick();if(!error||error_code!==code||busy||cmd_ready||done||mem_req_valid||mem_rsp_ready) $fatal(1,"raw fault not sticky");end
        @(negedge clk);cmd_valid=0;
    endtask
    initial begin
        if(!$value$plusargs("DIRECTORY=%s",directory)||!$value$plusargs("MODE=%d",mode)||!$value$plusargs("ROWS=%d",rows)||
           !$value$plusargs("AI=%d",ai)||!$value$plusargs("AO=%d",ao)||!$value$plusargs("READS=%d",read_count)||!$value$plusargs("WRITES=%d",write_count)) $fatal(1,"missing corpus");
        if(rows<1||ai<32||ao<32||rows*ai>1024||ai*ao>8192||rows*ao*2>2048||read_count<1||read_count>16384||write_count<1||write_count>1024||mode<0||mode>9||mode==8) $fatal(1,"invalid corpus or mode");
        $readmemh({directory,"/commands.hex"},commands,0,48);
        $readmemh({directory,"/input.hex"},input_memory,0,rows*ai-1);
        $readmemh({directory,"/weight.hex"},weight_memory,0,ai*ao-1);
        $readmemh({directory,"/reads.hex"},expected_reads,0,read_count-1);
        $readmemh({directory,"/writes.hex"},expected_writes,0,write_count-1);
        reset_all();
        if(mode==7) begin send_word(64'h9999000000000000);expect_fault(1);end
        else begin
            submit();
            if(mode==0) finish_job();
            else if(mode==5||mode==6) begin
                begin: wait_read
                    for(integer age=0;age<32;age=age+1) begin tick();if(mem_req_valid) disable wait_read;end
                    $fatal(1,"missing raw read for cancel/reset");
                end
                if(mode==5) begin @(negedge clk);cancel=1;cancel_code=3;expect_fault(3);end
                else begin reset_all();submit();finish_job();end
            end else begin
                expect_fault(mode==1||mode==2 ? 8'd5 : mode==9 ? 8'd6 : 8'd8);
                if(mode==2&&(write_requests!=write_count||acks!=write_count-1||frames!=write_count/16-1)) $fatal(1,"failed final write counted as completion");
            end
        end
        $display("PASS raw C32 K16 core mode=%0d reads=%0d writes=%0d acknowledgments=%0d jobs=%0d seed=3588ac16",mode,read_requests,write_requests,acks,jobs);
        $finish;
    end
    initial begin #10000000;$fatal(1,"raw core watchdog");end
endmodule
