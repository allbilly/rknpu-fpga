// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Actual raw K65 CMAC program and unchanged donor-policy numerical fixture.
// The UI halfword memory model is not MIG, DDR training or physical hardware.
module tb_cmac_async_engine;
    logic ui_clk,core_clk,ui_run=1,core_run=1;
    initial begin ui_clk=0;core_clk=0;end
    always begin #3.75;if(ui_run)ui_clk=~ui_clk;end
    always begin #10;if(core_run)core_clk=~core_clk;end
    logic ui_rst_n=0,core_rst_n=0,ui_admission_enable=0,ui_rearm_permit=0;
    logic ui_start_valid=0,ui_result_ready=0;
    logic [31:0] ui_start_address=32'h100e0000,ui_start_amount=45;
    wire ui_start_ready,ui_result_valid,ui_result_error,ui_fault;
    wire [7:0] ui_result_code;
    wire [31:0] ui_result_tasks;
    wire ui_mem_req_valid,ui_mem_req_write,ui_mem_rsp_ready;
    wire [31:0] ui_mem_req_addr;
    wire [15:0] ui_mem_req_wdata;
    logic ui_mem_rsp_valid,ui_mem_rsp_error;
    logic [15:0] ui_mem_rsp_rdata;
    logic pending,pending_command,pending_error;
    logic [15:0] pending_data;
    logic [3:0] pending_delay;
    logic hold_requests=0,hold_returns=0;
    logic [31:0] rng;
    wire ui_mem_req_ready=ui_rst_n&&!hold_requests&&!pending&&!ui_mem_rsp_valid&&rng[0];
    rk_cmac_async_engine #(.TIMEOUT_CYCLES(256)) dut(.*);
    logic [63:0] commands[0:48];
    logic [15:0] inputs[0:191],weights[0:3071],outputs[0:2047];
    logic [47:0] expected_reads[0:6527],expected_writes[0:63];
    integer mode,command_requests,command_responses,read_requests,write_requests,responses;
    integer admissions,consumptions,command_words,reset_edges;
    logic stalled_request,stalled_result;
    logic [48:0] held_request;
    logic [40:0] held_result;
    string directory;

    always @(posedge ui_clk or negedge ui_rst_n) begin: memory_model
        logic [15:0] value;
        integer index;
        if(!ui_rst_n)begin
            pending<=0;pending_command<=0;pending_error<=0;
            pending_data<=0;pending_delay<=0;ui_mem_rsp_valid<=0;ui_mem_rsp_error<=0;ui_mem_rsp_rdata<=0;
            command_requests<=0;command_responses<=0;read_requests<=0;write_requests<=0;responses<=0;
            admissions<=0;consumptions<=0;rng<=32'h3588ad16;
            stalled_request<=0;stalled_result<=0;held_request<=0;held_result<=0;
            for(integer i=0;i<2048;i=i+1)outputs[i]<=16'ha55a;
        end else begin
            rng<=rng*32'd1664525+32'd1013904223;
            if(ui_start_valid&&ui_start_ready)admissions<=admissions+1;
            if(ui_result_valid&&ui_result_ready)consumptions<=consumptions+1;
            if(stalled_request&&(!ui_mem_req_valid||
                {ui_mem_req_write,ui_mem_req_addr,ui_mem_req_wdata}!==held_request))
                $fatal(1,"CMAC crossing withdrew/changed an owned memory request");
            stalled_request<=ui_mem_req_valid&&!ui_mem_req_ready;
            held_request<={ui_mem_req_write,ui_mem_req_addr,ui_mem_req_wdata};
            if(stalled_result&&(!ui_result_valid||
                {ui_result_error,ui_result_code,ui_result_tasks}!==held_result))
                $fatal(1,"CMAC held terminal result changed");
            stalled_result<=ui_result_valid&&!ui_result_ready;
            held_result<={ui_result_error,ui_result_code,ui_result_tasks};
            if(ui_mem_req_valid&&ui_mem_req_ready)begin
                if(pending||ui_mem_rsp_valid||ui_mem_req_addr[0])$fatal(1,"CMAC memory ownership/alignment");
                pending<=1;pending_command<=0;
                pending_error<=0;pending_data<=0;pending_delay<={1'b0,rng[4:2]};
                if(ui_mem_req_write)begin
                    if({ui_mem_req_addr,ui_mem_req_wdata}!==expected_writes[write_requests%64])
                        $fatal(1,"CMAC raw write mismatch index=%0d addr=%h data=%h",write_requests,ui_mem_req_addr,ui_mem_req_wdata);
                    index=int'((ui_mem_req_addr-32'h10040000)>>1);
                    if(index<0||index>=128)$fatal(1,"CMAC output outside physical allocation");
                    outputs[index]<=ui_mem_req_wdata;write_requests<=write_requests+1;
                end else if(ui_mem_req_addr>=32'h100e0000&&ui_mem_req_addr<32'h100e0188)begin
                    if(ui_mem_req_addr!==32'h100e0000+32'((command_requests%196)*2))
                        $fatal(1,"CMAC final-word fetch order changed");
                    index=int'((ui_mem_req_addr-32'h100e0000)>>1);
                    pending_data<=commands[index/4][16*(index%4)+:16];pending_command<=1;
                    pending_error<=mode==1&&command_requests==0;
                    command_requests<=command_requests+1;
                end else begin
                    if(ui_mem_req_addr>=32'h10010000&&ui_mem_req_addr<32'h10010180)
                        value=inputs[(ui_mem_req_addr-32'h10010000)>>1];
                    else if(ui_mem_req_addr>=32'h10020000&&ui_mem_req_addr<32'h10021800)
                        value=weights[(ui_mem_req_addr-32'h10020000)>>1];
                    else begin value=0;$fatal(1,"CMAC operand outside physical allocation %h",ui_mem_req_addr);end
                    if({ui_mem_req_addr,value}!==expected_reads[read_requests%6528])
                        $fatal(1,"CMAC operand request order/data changed index=%0d",read_requests);
                    pending_data<=value;read_requests<=read_requests+1;
                end
            end
            if(pending&&!hold_returns)begin
                if(pending_delay!=0)pending_delay<=pending_delay-1'b1;
                else begin
                    pending<=0;ui_mem_rsp_valid<=1;ui_mem_rsp_error<=pending_error;ui_mem_rsp_rdata<=pending_data;
                    if(pending_command)command_responses<=command_responses+1;
                end
            end
            if(ui_mem_rsp_valid&&ui_mem_rsp_ready)begin ui_mem_rsp_valid<=0;responses<=responses+1;end
        end
    end
    always @(posedge core_clk or negedge core_rst_n)begin
        if(!core_rst_n)begin command_words<=0;reset_edges<=0;end
        else begin
            if(dut.engine.engine.core.cmd_valid&&dut.engine.engine.core.cmd_ready)begin
                if(dut.engine.engine.core.cmd_data!==commands[command_words%49])
                    $fatal(1,"CMAC bridge changed a raw final command word");
                command_words<=command_words+1;
            end
            if(dut.dma_rst_n&&!dut.engine.child_rst_n)begin
                if(dut.memory_pending||dut.mem_req_valid||dut.mem_rsp_valid)
                    $fatal(1,"CMAC numerical reset discarded crossing ownership");
                reset_edges<=reset_edges+1;
            end
        end
    end
    task automatic reset_epoch;
        ui_start_valid=0;ui_result_ready=0;ui_admission_enable=0;ui_rearm_permit=0;
        ui_rst_n=0;core_rst_n=0;hold_requests=0;hold_returns=0;
        repeat(6)@(negedge core_clk);core_rst_n=1;
        @(negedge ui_clk);ui_rst_n=1;ui_rearm_permit=1;
        repeat(8)@(negedge core_clk);ui_admission_enable=1;
    endtask
    task automatic kick;
        integer guard;
        guard=0;@(negedge ui_clk);
        while(!ui_start_ready)begin
            @(negedge ui_clk);guard=guard+1;if(guard>2000)$fatal(1,"CMAC descriptor admission timeout");
        end
        ui_start_valid=1;@(posedge ui_clk);
        if(!ui_start_ready)$fatal(1,"CMAC descriptor did not transfer");
        @(negedge ui_clk);ui_start_valid=0;
        // Withdrawing unstrobbed metadata must not change an accepted job.
        ui_start_address=0;ui_start_amount=0;
    endtask
    task automatic await_result(input logic [7:0] code,input logic [31:0] tasks);
        integer guard;
        guard=0;
        while(!ui_result_valid)begin
            @(negedge ui_clk);guard=guard+1;if(guard>1000000)$fatal(1,"CMAC async result watchdog");
        end
        if(ui_result_error!==(code!=0)||ui_result_code!==code||ui_result_tasks!==tasks||ui_start_ready)
            $fatal(1,"Wrong CMAC terminal result error=%b code=%0d tasks=%0d expected=%0d/%0d",ui_result_error,ui_result_code,ui_result_tasks,code,tasks);
        repeat(32)@(negedge ui_clk);
    endtask
    task automatic consume;
        @(negedge ui_clk);ui_result_ready=1;
        @(posedge ui_clk);if(!ui_result_valid)$fatal(1,"CMAC result disappeared before consumption");
        @(negedge ui_clk);ui_result_ready=0;repeat(8)@(negedge ui_clk);
        if(ui_result_valid)$fatal(1,"Duplicate CMAC result");
    endtask
    task automatic check_success(input integer jobs);
        if(ui_fault||pending||ui_mem_rsp_valid||ui_mem_req_valid||
           command_requests!=jobs*196||command_responses!=jobs*196||command_words!=jobs*49||
           read_requests!=jobs*6528||write_requests!=jobs*64||responses!=jobs*6788||
           dut.engine.rearm_count!=32'(jobs)||reset_edges!=jobs*2)
            $fatal(1,"CMAC success preceded exact raw memory drain/rearm requests=%0d/%0d/%0d responses=%0d resets=%0d",command_requests,read_requests,write_requests,responses,reset_edges);
        for(integer i=0;i<2048;i=i+1)begin
            if(i<128&&i%32<16)begin
                if(outputs[i]!==expected_writes[(i/32)*16+i%32][15:0])$fatal(1,"CMAC physical output mismatch");
            end else if(outputs[i]!==16'ha55a)$fatal(1,"CMAC output padding/sentinel changed");
        end
    endtask
    logic [7:0] expected_code;
    integer jobs;
    initial begin
        if(!$value$plusargs("DIRECTORY=%s",directory)||!$value$plusargs("MODE=%d",mode)||mode<0||mode>8)
            $fatal(1,"Explicit CMAC fixture directory/mode required");
        $readmemh({directory,"/commands.hex"},commands,0,48);
        $readmemh({directory,"/input.hex"},inputs,0,191);
        $readmemh({directory,"/weight.hex"},weights,0,3071);
        $readmemh({directory,"/reads.hex"},expected_reads,0,6527);
        $readmemh({directory,"/writes.hex"},expected_writes,0,63);
        reset_epoch();
        if(mode==2)ui_start_amount=44;
        if(mode==3)commands[0][63:48]=16'hffff;
        if(mode==4)hold_requests=1;
        if(mode==5)begin @(negedge core_clk);core_run=0;end
        if(mode==8)hold_returns=1;
        kick();
        if(mode==5)begin
            ui_rearm_permit=0;repeat(8)@(negedge ui_clk);core_run=1;
        end
        if(mode==6)begin
            wait(write_requests==64);@(negedge ui_clk);hold_returns=1;ui_rearm_permit=0;
            repeat(8)@(negedge core_clk);hold_returns=0;
        end
        if(mode==7)begin
            wait(command_requests>=1);@(negedge core_clk);core_run=0;
            repeat(60)@(negedge ui_clk);
            if(ui_result_valid)$fatal(1,"Stopped CMAC core invented completion");
            core_run=1;wait(command_requests>=3);@(negedge ui_clk);ui_run=0;
            repeat(60)@(negedge core_clk);ui_run=1;
        end
        if(mode==8)begin
            wait(pending);repeat(4)@(negedge ui_clk);
            if(ui_result_valid||ui_fault)$fatal(1,"CMAC joint reset setup already terminated");
            reset_epoch();ui_start_address=32'h100e0000;ui_start_amount=45;kick();
        end
        if(mode==0||mode==7||mode==8)begin
            jobs=mode==0?2:1;
            for(integer job=1;job<=jobs;job=job+1)begin
                if(job!=1)begin ui_start_address=32'h100e0000;ui_start_amount=45;kick();end
                await_result(0,1);check_success(job);consume();
            end
            if(admissions!=jobs||consumptions!=jobs)$fatal(1,"CMAC job/result count mismatch");
        end else begin
            expected_code=mode==1||mode==5?8'd5:mode==2?8'd7:mode==3?8'd1:mode==4?8'd8:8'd6;
            await_result(expected_code,0);
            if(mode==4)begin
                if(!ui_mem_req_valid)$fatal(1,"CMAC timeout withdrew an already owned UI request");
                hold_requests=0;wait(responses==1);repeat(16)@(negedge ui_clk);
                if(!ui_result_valid||ui_result_code!=8)$fatal(1,"Late response replaced CMAC timeout");
            end
            consume();ui_rearm_permit=1;repeat(32)@(negedge core_clk);
            if(!ui_fault||ui_start_ready||ui_result_valid||reset_edges!=0||dut.engine.rearm_count!=0)
                $fatal(1,"CMAC fault escaped quarantine or rearmed");
            if(mode!=6&&write_requests!=0)$fatal(1,"Early CMAC error wrote output");
            if((mode==2||mode==5)&&(command_requests!=0||read_requests!=0))
                $fatal(1,"Rejected CMAC descriptor performed memory IO");
        end
        $display("PASS async_cmac_boundary mode=%0d admitted=%0d consumed=%0d command_words=%0d operand_reads=%0d writes=%0d responses=%0d rearm=%0d seed=3588ad16 raw_K65_two_clocks_only",
            mode,admissions,consumptions,command_words,read_requests,write_requests,responses,dut.engine.rearm_count);
        $finish;
    end
    initial begin #100000000;$fatal(1,"CMAC async wall-cycle watchdog");end
endmodule
