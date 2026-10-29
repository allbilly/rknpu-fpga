// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_nvdla_dma;
    logic clk,rst_n=0,start_valid=0,start_ready;
    logic [31:0] start_address=32'h100e0000,start_amount=45;
    logic busy,address_done,operand_done,acknowledged,done,error;
    logic [7:0] error_code;
    logic mem_req_valid,mem_req_ready,mem_req_write,mem_rsp_valid,mem_rsp_ready,mem_rsp_error;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_req_wdata,mem_rsp_rdata;
    initial clk=0;
    always #5 clk=~clk;
    rk_cmac_nvdla_dma #(.TIMEOUT_CYCLES(32)) dut(.*);
    logic [63:0] commands[0:48];
    logic [15:0] input_mem[0:4095],weight_mem[0:8191],output_mem[0:1023],expected_mem[0:1023];
    logic [48:0] output_words[0:511];
    logic [78:0] group_words[0:2047];
    logic [31:0] rng;
    logic slave_pending,slave_write,slave_last,response_error,checking,job_open,request_stalled;
    logic [15:0] response_data;
    logic [48:0] held_request;
    integer rows,ai,ao,group_count,mode,delay_count,reads,writes,responses,acks,dones,groups;
    integer address_pulses,operand_pulses,good_jobs,faults,resets,cycles,command_reads;
    string root_path,path;
    assign mem_req_ready=rst_n&&!slave_pending&&rng[2:0]!=0&&!(mode==3&&command_reads==0);
    assign mem_rsp_valid=rst_n&&slave_pending&&delay_count==0&&!(mode==4&&reads==1)&&!(mode==21&&command_reads==1);
    assign mem_rsp_rdata=response_data;
    assign mem_rsp_error=response_error;
    function automatic logic [15:0] read_half(input logic [31:0] address);
        if (address>=32'h100e0000&&address<32'h100e0188&&address[0]==0)
            return commands[(address-32'h100e0000)>>3][16*((address>>1)&3)+:16];
        if (address>=32'h10010000&&address<32'h10010000+32'(rows*ai*2)&&address[0]==0)
            return input_mem[(address-32'h10010000)>>1];
        if (address>=32'h10020000&&address<32'h10020000+32'(ao*ai*2)&&address[0]==0)
            return weight_mem[(address-32'h10020000)>>1];
        $fatal(1,"unmapped read %h",address);return 0;
    endfunction
    function automatic integer output_index(input logic [31:0] address);
        if (address>=32'h10040000&&address<32'h10040000+32'(rows*ao*4)&&address[0]==0)
            return int'((address-32'h10040000)>>1);
        $fatal(1,"unmapped write %h",address);return 0;
    endfunction
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rng<=32'h3588ca16;slave_pending<=0;slave_write<=0;slave_last<=0;
            delay_count<=0;response_data<=0;response_error<=0;
        end else begin
            rng<=rng*32'd1664525+32'd1013904223;
            if (mem_req_valid&&mem_req_ready) begin
                if (slave_pending) $fatal(1,"multiple outstanding transactions");
                slave_pending<=1;slave_write<=mem_req_write;delay_count<=int'(rng[8:6]);
                slave_last<=mem_req_write&&writes==rows*ao-1;
                if (mem_req_write) begin
                    output_mem[output_index(mem_req_addr)]<=mem_req_wdata;
                    // Delay the final acknowledgment to expose premature done.
                    if (writes==rows*ao-1) delay_count<=23;
                    response_error<=mode==2&&writes==0;
`ifndef VERILATOR
                    if (mode==6&&writes==0) response_error<=1'bx;
`endif
                end else begin
                    response_data<=read_half(mem_req_addr);
                    response_error<=mem_req_addr>=32'h100e0000 ? mode==12 : mode==1&&reads==0;
`ifndef VERILATOR
                    if ((mode==5&&reads==0&&mem_req_addr<32'h100e0000)||mode==13) response_error<=1'bx;
                    if ((mode==11&&reads==0&&mem_req_addr<32'h100e0000)||mode==14) response_data<='x;
`endif
                end
            end
            if (slave_pending) begin
                if (delay_count!=0) delay_count<=delay_count-1;
                else if (mem_rsp_valid&&mem_rsp_ready) slave_pending<=0;
            end
        end
    end
    task automatic tick;
        logic req_fire,rsp_fire,expect_ack,expect_done,group_fire,pre_req,pre_ready;
        logic [48:0] request_bits;
        logic [78:0] group_bits;
        logic [31:0] expected_address;
        integer pair_index,r,c,k;
        @(posedge clk);
        pre_req=mem_req_valid;pre_ready=mem_req_ready;
        request_bits={mem_req_write,mem_req_addr,mem_req_wdata};
        req_fire=pre_req&&pre_ready;rsp_fire=mem_rsp_valid&&mem_rsp_ready;
        expect_ack=rsp_fire&&slave_write&&(mem_rsp_error===1'b0);expect_done=expect_ack&&slave_last;
        group_fire=dut.core.pipeline.group_valid&&dut.core.pipeline.accum_ready&&!error;
        group_bits={dut.core.pipeline.group_tag,dut.core.pipeline.group_value};
        #1;cycles=cycles+1;
        if (checking&&rst_n) begin
            if (request_stalled&&!error&&(pre_req!==1||request_bits!==held_request)) $fatal(1,"arbiter changed stalled request");
            request_stalled=pre_req&&!pre_ready&&!error;held_request=request_bits;
            if (req_fire) begin
                job_open=1;
                if (request_bits[48]) begin
                    if (writes>=rows*ao||request_bits[47:0]!==output_words[writes][48:1])
                        $fatal(1,"write mismatch index=%0d got=%h expected=%h",writes,request_bits[47:0],output_words[writes][48:1]);
                    expected_mem[output_index(request_bits[47:16])]=request_bits[15:0];writes=writes+1;
                end else if (request_bits[47:16]>=32'h100e0000) begin
                    if (command_reads>=196||request_bits[47:16]!==32'h100e0000+32'(command_reads*2))
                        $fatal(1,"command fetch order/address mismatch index=%0d",command_reads);
                    command_reads=command_reads+1;
                end else begin
                    if (command_reads!=196) $fatal(1,"operand before complete command fetch");
                    if (reads>=rows*ao*ai*2) $fatal(1,"extra read");
                    pair_index=reads/2;r=pair_index/(ao*ai);c=(pair_index/ai)%ao;k=pair_index%ai;
                    expected_address=reads%2==0 ? 32'h10010000+32'((r*ai+k)*2) :
                        32'h10020000+32'(((c/16)*(ai/32)*512+(k/32)*512+(c%16)*32+k%32)*2);
                    if (request_bits[47:16]!==expected_address) $fatal(1,"read packing/order index=%0d got=%h expected=%h",reads,request_bits[47:16],expected_address);
                    reads=reads+1;
                end
            end
            if (group_fire) begin
                if (groups>=group_count||group_bits!==group_words[groups]) $fatal(1,"group seam mismatch index=%0d got=%h expected=%h",groups,group_bits,group_words[groups]);
                groups=groups+1;
            end
            if (rsp_fire) responses=responses+1;
            if (acknowledged!==expect_ack||done!==expect_done) $fatal(1,"completion not tied to successful final write response");
            if (acknowledged) acks=acks+1;
            if (address_done) address_pulses=address_pulses+1;
            if (operand_done) operand_pulses=operand_pulses+1;
            if (done) begin
                if (address_pulses!=1||operand_pulses!=1) $fatal(1,"completed before raw operand stream drained");
                dones=dones+1;job_open=0;
            end
            if (job_open&&!error&&(!busy||start_ready)) $fatal(1,"raw command ownership lost before acknowledgment");
        end
    endtask
    task automatic clear_counters;
        reads=0;writes=0;responses=0;acks=0;dones=0;groups=0;command_reads=0;
        address_pulses=0;operand_pulses=0;job_open=0;request_stalled=0;
    endtask
    task automatic reset_all;
        checking=0;@(negedge clk);rst_n=0;start_valid=0;start_address=32'h100e0000;start_amount=45;
        repeat(3) tick();
        if (busy||done||acknowledged||error||start_ready||mem_req_valid||mem_rsp_ready) $fatal(1,"reset quiescence");
        clear_counters();@(negedge clk);rst_n=1;tick();checking=1;
        if (!start_ready||busy||error) $fatal(1,"reset restart");
    endtask
    task automatic submit;
        @(negedge clk);
        if (!start_ready) $fatal(1,"descriptor not ready");
        if (mode==15) start_amount=49;
        if (mode==16) start_address=32'h100e0002;
        if (mode==17) start_address=32'hfffffff0;
        start_valid=1;tick();@(negedge clk);start_valid=0;
    endtask
    task automatic check_memory;
        for (integer i=0;i<1024;i=i+1)
            if (output_mem[i]!==expected_mem[i]) $fatal(1,"output data/hole mismatch index=%0d",i);
    endtask
    task automatic finish_good;
        while (!done&&!error) tick();
        if (error||command_reads!=196||reads!=rows*ao*ai*2||writes!=rows*ao||acks!=rows*ao||groups!=group_count||dones!=1)
            $fatal(1,"raw pipeline failed reads=%0d writes=%0d groups=%0d acks=%0d done=%0d error=%h",reads,writes,groups,acks,dones,error_code);
        repeat(5) begin tick();if (busy||done||acknowledged||error||mem_req_valid||!start_ready) $fatal(1,"post-job state");end
        check_memory();good_jobs=good_jobs+1;
    endtask
    task automatic sticky(input logic [7:0] code);
        if (!error||error_code!==code||done||acknowledged) $fatal(1,"wrong fault code=%h expected=%h",error_code,code);
        checking=0;
        repeat(40) begin
            @(negedge clk);start_valid=1;tick();
            if (!error||error_code!==code||busy||done||acknowledged||start_ready||mem_req_valid||mem_rsp_ready) $fatal(1,"fault not sticky/quiescent");
        end
        check_memory();faults=faults+1;
    endtask
    initial begin
        checking=0;good_jobs=0;faults=0;resets=0;cycles=0;clear_counters();
        if (!$value$plusargs("ROOT=%s",root_path)||!$value$plusargs("ROWS=%d",rows)||!$value$plusargs("AI=%d",ai)||
            !$value$plusargs("AO=%d",ao)||!$value$plusargs("GROUPS=%d",group_count)||!$value$plusargs("MODE=%d",mode)) $fatal(1,"missing arguments");
        if (rows*ai>4096||ao*ai>8192||rows*ao>512||group_count>2048) $fatal(1,"test storage bounds");
        path={root_path,"/commands.hex"};$readmemh(path,commands);
        path={root_path,"/input.hex"};$readmemh(path,input_mem,0,rows*ai-1);
        path={root_path,"/weight.hex"};$readmemh(path,weight_mem,0,ao*ai-1);
        path={root_path,"/outputs.hex"};$readmemh(path,output_words,0,rows*ao-1);
        path={root_path,"/groups.hex"};$readmemh(path,group_words,0,group_count-1);
        for (integer i=0;i<1024;i=i+1) begin output_mem[i]=16'ha55a;expected_mem[i]=16'ha55a;end
        reset_all();
        if (mode==7) commands[0]=64'hdead000000001234;
        if (mode==8) commands[0]=commands[48];
        if (mode==18) commands[45]=commands[46];
        begin
            submit();
            if (mode==9||mode==19) begin
                if (mode==19) begin while (command_reads<20&&!error) tick();end
                else begin while (dut.core.pipeline.group_stage.state!=2&&!error) tick();end
                if (error||writes!=0) $fatal(1,"reset setup");
                reset_all();resets=resets+1;repeat(140) begin tick();if (error||done||acknowledged||busy||mem_req_valid) $fatal(1,"stale arithmetic after reset");end
                submit();finish_good();
            end else if (mode==0||mode==10) begin
                finish_good();
                if (mode==10) begin clear_counters();submit();finish_good();end
            end else begin
                while (!error&&!done) tick();
                if (done) $fatal(1,"faulted job completed");
                sticky(mode==3||mode==4||mode==21 ? 8'd8 : mode==11||mode==14 ? 8'd6 :
                       mode==7 ? 8'd1 : mode==8||mode==18 ? 8'd3 :
                       mode>=15&&mode<=17 ? 8'd7 : 8'd5);
            end
        end
        $display("PASS DMA NVDLA CMAC mode=%0d good_jobs=%0d faults=%0d resets=%0d reads=%0d writes=%0d groups=%0d acks=%0d cycles=%0d seed=3588ca16",mode,good_jobs,faults,resets,reads,writes,groups,acks,cycles);
        $finish;
    end
    initial begin #30000000;$fatal(1,"raw pipeline simulation timeout");end
endmodule
