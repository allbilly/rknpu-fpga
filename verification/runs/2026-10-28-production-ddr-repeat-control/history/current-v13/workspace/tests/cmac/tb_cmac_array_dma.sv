// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_array_dma;
    logic clk,rst_n=0,start_valid=0;
    logic [31:0] start_address=32'h100e0000,start_amount=45;
    logic [63:0] commands[0:48];
    wire start_ready,busy,acknowledged,frame_done,done,error;
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
    integer command_requests,command_responses,command_handshakes;
    logic pending_command;
    string directory;
    initial clk=0;
    always #5 clk=~clk;
    assign mem_req_ready=rst_n&&!pending&&mode!=3&&rng[1:0]!=0;
    assign mem_rsp_valid=rst_n&&pending&&delay_left==0&&mode!=4;
    assign mem_rsp_rdata=response_data;
    assign mem_rsp_error=pending_error;
    rk_cmac_array_dma #(.TIMEOUT_CYCLES(128)) dut(.*);
    always @(posedge clk or negedge rst_n) begin: memory_slave
        logic response_fire,expected_ack,expected_frame,expected_done;
        logic [15:0] read_value;
        logic accepted_command;
        integer index;
        if(!rst_n) begin
            pending<=0;pending_write<=0;pending_error<=0;response_data<=0;delay_left<=0;
            read_requests<=0;write_requests<=0;read_responses<=0;write_responses<=0;
            acks<=0;frames<=0;jobs<=0;rng<=32'h3588ad16;
            command_requests<=0;command_responses<=0;command_handshakes<=0;pending_command<=0;
            for(integer i=0;i<2048;i=i+1) output_memory[i]<=16'ha55a;
        end else begin
            rng<=rng*32'd1664525+32'd1013904223;
            accepted_command=dut.core.cmd_valid&&dut.core.cmd_ready;
            if(accepted_command) begin
                if(command_handshakes>=49||dut.core.cmd_data!==commands[command_handshakes])
                    $fatal(1,"DMA changed a final command word");
                command_handshakes<=command_handshakes+1;
            end
            response_fire=mem_rsp_valid&&mem_rsp_ready;
            expected_ack=response_fire&&pending_write&&!pending_error;
            expected_frame=expected_ack&&write_responses%16==15;
            expected_done=expected_frame&&write_responses==write_count-1;
            if(mem_req_valid&&mem_req_ready) begin
                if(pending||mem_req_addr[0]) $fatal(1,"invalid request ownership/alignment");
                pending<=1;pending_write<=mem_req_write;pending_error<=0;pending_command<=0;
                delay_left<=int'(rng[5:3])+1;
                if(mem_req_write) begin
                    if(command_responses!=196||command_handshakes!=49) $fatal(1,"write before final command");
                    if(write_requests>=write_count||{mem_req_addr,mem_req_wdata}!==expected_writes[write_requests])
                        $fatal(1,"raw core write mismatch index=%0d addr=%h data=%h expected=%h",write_requests,mem_req_addr,mem_req_wdata,expected_writes[write_requests]);
                    index=int'((mem_req_addr-32'h10040000)>>1);
                    if(index<0||index>=rows*ao*2) $fatal(1,"output write outside physical allocation");
                    output_memory[index]<=mem_req_wdata;
                    write_requests<=write_requests+1;
                    if(write_requests==write_count-1) begin delay_left<=31;pending_error<=mode==2;end
                end else if(mem_req_addr>=32'h100e0000&&mem_req_addr<32'h100e0188) begin
                    if(command_requests>=196||mem_req_addr!==32'h100e0000+32'(command_requests*2)||
                       read_requests!=0||write_requests!=0) $fatal(1,"command fetch order/ownership");
                    index=int'((mem_req_addr-32'h100e0000)>>1);
                    response_data<=commands[index/4][16*(index%4)+:16];
                    pending_command<=1;
                    pending_error<=mode==5&&command_requests==0;
`ifndef VERILATOR
                    if(mode==9&&command_requests==0) response_data<='x;
                    if(mode==15&&command_requests==0) pending_error<=1'bx;
`endif
                    command_requests<=command_requests+1;
                end else begin
                    if(command_responses!=196||command_handshakes!=49) $fatal(1,"operand before final command");
                    if(mem_req_addr>=32'h10010000&&mem_req_addr<32'h10010000+32'(rows*ai*2))
                        read_value=input_memory[(mem_req_addr-32'h10010000)>>1];
                    else if(mem_req_addr>=32'h10020000&&mem_req_addr<32'h10020000+32'(ai*ao*2))
                        read_value=weight_memory[(mem_req_addr-32'h10020000)>>1];
                    else begin read_value=0;$fatal(1,"read outside physical operand allocation addr=%h",mem_req_addr);end
                    if(read_requests>=read_count||{mem_req_addr,read_value}!==expected_reads[read_requests])
                        $fatal(1,"raw core read order/data index=%0d addr=%h",read_requests,mem_req_addr);
                    response_data<=read_value;
                    pending_error<=mode==1&&read_requests==0;
                    read_requests<=read_requests+1;
                end
            end
            if(pending) begin
                if(delay_left>0) delay_left<=delay_left-1;
                else if(response_fire) begin
                    pending<=0;
                    if(pending_write) write_responses<=write_responses+1;
                    else if(pending_command) command_responses<=command_responses+1;
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
        @(negedge clk);rst_n=0;start_valid=0;start_address=32'h100e0000;start_amount=45;
        repeat(3) begin tick();if(start_ready||busy||error||done||mem_req_valid||mem_rsp_ready) $fatal(1,"raw reset dominance");end
        @(negedge clk);rst_n=1;repeat(6) tick();if(!start_ready||busy||error) $fatal(1,"raw reset release");
    endtask
    task automatic submit;
        @(negedge clk);
        if(!start_ready) $fatal(1,"DMA descriptor not ready");
        if(mode==10) start_amount=49;
        if(mode==11) start_address=32'h100e0002;
        if(mode==12) start_address=32'hfffffff0;
        start_valid=1;tick();@(negedge clk);start_valid=0;
    endtask
    task automatic finish_job;
        begin: await_done
            for(integer age=0;age<300000;age=age+1) begin
                tick();if(error) $fatal(1,"raw replay failed code=%0d reads=%0d writes=%0d",error_code,read_requests,write_requests);
                if(done) disable await_done;
                if(!busy||start_ready) $fatal(1,"raw job lost ownership before completion");
            end
            $fatal(1,"raw replay simulation-cycle watchdog");
        end
        repeat(8) begin tick();if(error||busy||done||mem_req_valid||!start_ready) $fatal(1,"raw replay failed to drain");end
        if(command_requests!=196||command_responses!=196||command_handshakes!=49||read_requests!=read_count||read_responses!=read_count||write_requests!=write_count||write_responses!=write_count||acks!=write_count||jobs!=1||frames!=write_count/16)
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
        @(negedge clk);start_valid=1;
        repeat(16) begin tick();if(!error||error_code!==code||busy||start_ready||done||mem_req_valid||mem_rsp_ready) $fatal(1,"raw fault not sticky");end
        @(negedge clk);start_valid=0;
    endtask
    initial begin
        if(!$value$plusargs("DIRECTORY=%s",directory)||!$value$plusargs("MODE=%d",mode)||!$value$plusargs("ROWS=%d",rows)||
           !$value$plusargs("AI=%d",ai)||!$value$plusargs("AO=%d",ao)||!$value$plusargs("READS=%d",read_count)||!$value$plusargs("WRITES=%d",write_count)) $fatal(1,"missing corpus");
        if(rows<1||ai<32||ao<32||rows*ai>1024||ai*ao>8192||rows*ao*2>2048||read_count<1||read_count>16384||write_count<1||write_count>1024||mode<0||mode>15) $fatal(1,"invalid corpus or mode");
        $readmemh({directory,"/commands.hex"},commands,0,48);
        $readmemh({directory,"/input.hex"},input_memory,0,rows*ai-1);
        $readmemh({directory,"/weight.hex"},weight_memory,0,ai*ao-1);
        $readmemh({directory,"/reads.hex"},expected_reads,0,read_count-1);
        $readmemh({directory,"/writes.hex"},expected_writes,0,write_count-1);
        reset_all();
        if(mode==7) commands[0]=64'h9999000000000000;
        if(mode==8) commands[0]=commands[48];
        if(mode==13) commands[45]=commands[46];
        submit();
        if(mode==0) finish_job();
        else if(mode==6||mode==14) begin
            begin: wait_reset_phase
                for(integer age=0;age<30000;age=age+1) begin
                    tick();
                    if(error) $fatal(1,"reset setup fault");
                    if((mode==6&&command_requests==20)||(mode==14&&read_requests==1))
                        disable wait_reset_phase;
                end
                $fatal(1,"missing DMA reset phase");
            end
            reset_all();submit();finish_job();
        end else begin
            expect_fault(mode==1||mode==2||mode==5||mode==15 ? 8'd5 :
                         mode==9 ? 8'd6 : mode==7 ? 8'd1 :
                         mode==8||mode==13 ? 8'd3 :
                         mode>=10&&mode<=12 ? 8'd7 : 8'd8);
            if(mode==2&&(command_requests!=196||read_requests!=read_count||
                         write_requests!=write_count||acks!=write_count-1||frames!=write_count/16-1))
                $fatal(1,"failed final write counted as completion");
            if(mode!=2&&(write_requests!=0||acks!=0||frames!=0))
                $fatal(1,"early DMA fault produced output");
            if(mode>=10&&mode<=12&&(command_requests!=0||read_requests!=0))
                $fatal(1,"invalid descriptor performed memory access");
        end
        $display("PASS DMA C32 K16 core mode=%0d command_reads=%0d command_words=%0d reads=%0d writes=%0d acknowledgments=%0d jobs=%0d seed=3588ad16",mode,command_requests,command_handshakes,read_requests,write_requests,acks,jobs);
        $finish;
    end
    initial begin #10000000;$fatal(1,"raw core watchdog");end
endmodule
