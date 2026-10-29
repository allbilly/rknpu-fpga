// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_array_front;
    logic clk,rst_n=0,cmd_valid=0,downstream_busy=0,cancel=0;
    wire cmd_ready,busy,stream_done,error;
    logic [63:0] cmd_data=0;
    logic [7:0] cancel_code=0;
    wire [7:0] error_code;
    wire mem_req_valid,mem_req_ready,mem_rsp_valid,mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_rsp_rdata;
    wire mem_rsp_error,frame_valid,frame_ready;
    wire [511:0] frame_data,frame_weight_mask;
    wire [8191:0] frame_weight;
    wire [31:0] frame_data_mask,frame_output_address,frame_row,frame_oc,frame_ic;
    wire frame_first,frame_last,frame_last_output;
    logic [63:0] commands[0:48];
    logic [15:0] input_mem[0:4095],weight_mem[0:8191];
    logic [8834:0] expected[0:127],held_frame;
    wire [8834:0] frame_bits={frame_data,frame_weight,frame_output_address,frame_row,frame_oc,frame_ic,frame_first,frame_last,frame_last_output};
    logic [31:0] rng,held_address;
    logic checking=0,pending,response_error,request_stalled=0,frame_stalled=0;
    logic [15:0] response_data;
    integer rows=0,ai=0,ao=0,total_frames=0,frames=0,frame_reads=0,requests=0,stream_pulses=0,final_stalls=0;
    integer slave_count,response_delay,request_wait=0,response_wait=0;
    integer mode=0,fault_at=0,good_runs=0,fault_runs=0,reset_runs=0,cancel_runs=0,total_frames_checked=0,profile_faults=0;
    string source_path,front_path,path;
    initial clk=0;
    always #5 clk=~clk;
    rk_cmac_array_front #(.TIMEOUT_CYCLES(32)) dut(.*);
    assign mem_req_ready=rst_n&&!pending&&rng[2:0]!=0&&!(mode==2&&slave_count+1==fault_at);
    assign mem_rsp_valid=rst_n&&pending&&response_delay==0&&!(mode==3&&slave_count==fault_at);
    assign mem_rsp_rdata=response_data;
    assign mem_rsp_error=response_error;
    assign frame_ready=rst_n&&rng[5:3]!=0&&!(frame_last&&frame_last_output&&final_stalls<40);
    function automatic [15:0] read_half(input logic [31:0] address);
        if(address>=32'h10010000&&address<32'h10010000+32'(rows*ai*2)&&address[0]==0)
            return input_mem[(address-32'h10010000)>>1];
        if(address>=32'h10020000&&address<32'h10020000+32'(ao*ai*2)&&address[0]==0)
            return weight_mem[(address-32'h10020000)>>1];
        $fatal(1,"unmapped array read %h",address);return 0;
    endfunction
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin pending<=0;slave_count<=0;response_delay<=0;response_data<=0;response_error<=0;rng<=32'h3588af16;end
        else begin
            rng<=rng*32'd1664525+32'd1013904223;
            if(mem_req_valid&&mem_req_ready) begin
                if(pending) $fatal(1,"multiple reads outstanding");
                pending<=1;slave_count<=slave_count+1;response_data<=read_half(mem_req_addr);response_delay<=int'(rng[8:6]);
                response_error<=mode==1&&slave_count+1==fault_at;
`ifndef VERILATOR
                if(mode==4&&slave_count+1==fault_at) response_error<=1'bx;
                if(mode==5&&slave_count+1==fault_at) response_data<=16'bx;
`endif
            end
            if(pending) begin
                if(response_delay>0) response_delay<=response_delay-1;
                else if(mem_rsp_valid&&mem_rsp_ready) pending<=0;
            end
        end
    end
    task automatic tick;
        logic req_fire,frame_fire,last_fire,pre_req,pre_req_ready,pre_rsp,pre_rsp_ready,pre_frame,pre_frame_ready;
        logic [31:0] address,wanted,row,oc,ic;
        logic [8834:0] actual;
        @(posedge clk);
        pre_req=mem_req_valid;pre_req_ready=mem_req_ready;pre_rsp=mem_rsp_valid;pre_rsp_ready=mem_rsp_ready;
        pre_frame=frame_valid;pre_frame_ready=frame_ready;address=mem_req_addr;actual=frame_bits;
        req_fire=pre_req&&pre_req_ready;frame_fire=pre_frame&&pre_frame_ready;last_fire=frame_fire&&frame_last&&frame_last_output;
        #1;
        if(checking&&rst_n) begin
            if(request_stalled&&!error&&(pre_req!==1||address!==held_address)) $fatal(1,"read request changed under stall");
            if(frame_stalled&&!error&&(pre_frame!==1||actual!==held_frame)) $fatal(1,"frame changed under stall");
            request_stalled=pre_req&&!pre_req_ready&&!error;held_address=address;
            frame_stalled=pre_frame&&!pre_frame_ready&&!error;held_frame=actual;
            if(req_fire) begin
                if(frames>=total_frames||frame_reads>=544) $fatal(1,"extra frame read");
                row=expected[frames][98:67];oc=expected[frames][66:35];ic=expected[frames][34:3];
                wanted=frame_reads<32 ? 32'h10010000+(row*32'(ai)+ic+32'(frame_reads))*2 :
                       32'h10020000+oc*32'(ai)*2+ic*32+32'((frame_reads-32)*2);
                if(address!==wanted) $fatal(1,"read address frame=%0d read=%0d got=%h expected=%h",frames,frame_reads,address,wanted);
                requests=requests+1;frame_reads=frame_reads+1;
            end
            if(pre_frame) begin
                if(frames>=total_frames||frame_reads!=544||actual!==expected[frames]||frame_data_mask!=='1||frame_weight_mask!=='1)
                    $fatal(1,"frame/metadata/mask mismatch at %0d reads=%0d",frames,frame_reads);
                if(!pre_frame_ready&&actual[1:0]==2'b11) final_stalls=final_stalls+1;
            end
            if(frame_fire) begin frames=frames+1;total_frames_checked=total_frames_checked+1;frame_reads=0;end
            if(stream_done!==last_fire) $fatal(1,"stream_done is not final frame handshake");
            if(stream_done) stream_pulses=stream_pulses+1;
            if((pre_req||pre_rsp_ready||pre_frame)&&!last_fire&&!error&&!busy) $fatal(1,"lost frame ownership");
            if(pre_req&&!pre_req_ready) request_wait=request_wait+1;else request_wait=0;
            if(pre_rsp_ready&&!pre_rsp) response_wait=response_wait+1;else response_wait=0;
            if(error&&error_code==8&&request_wait!=32&&response_wait!=32) $fatal(1,"memory timeout not exactly 32 stalled cycles");
        end
    endtask
    task automatic reset_all;
        checking=0;@(negedge clk);rst_n=0;cmd_valid=0;cmd_data=0;downstream_busy=0;cancel=1;cancel_code=4;
        repeat(3) tick();
        if(mem_req_valid||mem_rsp_ready||frame_valid||error||stream_done||busy||cmd_ready||error_code!==0) $fatal(1,"reset dominance");
        frames=0;frame_reads=0;requests=0;stream_pulses=0;final_stalls=0;request_stalled=0;frame_stalled=0;request_wait=0;response_wait=0;
        @(negedge clk);rst_n=1;cancel=0;cancel_code=0;tick();checking=1;
    endtask
    task automatic open_case(input string name,input integer m,in_channels,out_channels);
        rows=m;ai=in_channels;ao=out_channels;total_frames=rows*(ai/32)*(ao/16);
        if(total_frames>128) $fatal(1,"fixture too large");
        path={source_path,"/",name,"/commands.hex"};$readmemh(path,commands);
        path={source_path,"/",name,"/input.hex"};$readmemh(path,input_mem,0,rows*ai-1);
        path={source_path,"/",name,"/weight.hex"};$readmemh(path,weight_mem,0,ao*ai-1);
        path={front_path,"/",name,"/frames.hex"};$readmemh(path,expected,0,total_frames-1);
    endtask
    task automatic submit;
        for(integer word=0;word<49;word=word+1) begin
            @(negedge clk);cmd_valid=1;cmd_data=commands[word];if(!cmd_ready) $fatal(1,"command blocked %0d",word);tick();
        end
        @(negedge clk);cmd_valid=0;downstream_busy=1;
    endtask
    task automatic good(input string name,input integer m,in_channels,out_channels);
        mode=0;fault_at=0;reset_all();open_case(name,m,in_channels,out_channels);submit();
        while(stream_pulses==0&&!error) tick();
        if(error||frames!=total_frames||requests!=total_frames*544||stream_pulses!=1||final_stalls<40) $fatal(1,"good array front failed frames=%0d reads=%0d code=%0d",frames,requests,error_code);
        repeat(4) begin tick();if(cmd_ready||!busy||mem_req_valid||frame_valid||stream_done) $fatal(1,"downstream ownership lost");end
        @(negedge clk);downstream_busy=0;tick();if(!cmd_ready||busy) $fatal(1,"downstream release");
        good_runs=good_runs+1;
    endtask
    task automatic sticky(input logic [7:0] code);
        if(!error||error_code!==code) $fatal(1,"wrong array fault got=%0d expected=%0d",error_code,code);
        checking=0;
        repeat(8) begin
            @(negedge clk);cancel=0;cmd_valid=1;cmd_data=commands[0];tick();
            if(!error||error_code!==code||cmd_ready||mem_req_valid||mem_rsp_ready||frame_valid||stream_done||busy) $fatal(1,"array fault escaped");
        end
        @(negedge clk);cmd_valid=0;
    endtask
    task automatic fault(input integer how,at_request,input logic [7:0] code);
        mode=how;fault_at=at_request;reset_all();open_case("m2_n17_k31",2,32,32);submit();
        while(!error&&stream_pulses==0) tick();
        if(stream_pulses!=0||frames!=(at_request-1)/544) $fatal(1,"fault emitted extra frame");
        sticky(code);fault_runs=fault_runs+1;
    endtask
    initial begin
        if(!$value$plusargs("SOURCE=%s",source_path)||!$value$plusargs("FRONT=%s",front_path)) $fatal(1,"missing fixture roots");
        good("m1_n8_k7",8,32,32);good("m1_n8_k8",8,32,32);good("m1_n8_k9",8,32,32);
        good("m2_n17_k31",2,32,32);good("m2_n17_k32",2,32,32);good("m2_n17_k33",2,64,32);good("m2_n17_k65",2,96,32);
        fault(1,1,5);fault(1,32,5);fault(1,33,5);fault(1,544,5);fault(1,545,5);fault(1,2176,5);
        fault(2,1,8);fault(2,33,8);fault(3,1,8);fault(3,33,8);
`ifndef VERILATOR
        fault(4,1,5);fault(4,33,5);fault(5,1,6);fault(5,33,6);
`endif
        for(integer phase=0;phase<5;phase=phase+1) begin
            mode=0;fault_at=0;reset_all();open_case("m2_n17_k31",2,32,32);submit();
            begin: wait_phase
                forever begin
                    tick();
                    if(frames>=1&&((phase==0&&mem_req_valid&&frame_reads==0)||(phase==1&&mem_rsp_ready&&frame_reads==1)||
                       (phase==2&&mem_req_valid&&frame_reads==32)||(phase==3&&mem_rsp_ready&&frame_reads==33)||
                       (phase==4&&frame_valid&&!frame_ready))) disable wait_phase;
                end
            end
            if(stream_pulses!=0) $fatal(1,"reset prefix completed");
            reset_runs=reset_runs+1;good("m2_n17_k31",2,32,32);
        end
        for(integer phase=0;phase<3;phase=phase+1) begin
            mode=0;fault_at=0;reset_all();open_case("m2_n17_k31",2,32,32);submit();
            if(phase!=0) begin
                begin: wait_cancel_phase
                    forever begin tick();if(phase==1 ? mem_rsp_ready : frame_valid) disable wait_cancel_phase;end
                end
            end
            @(negedge clk);cancel=1;cancel_code=2;tick();sticky(2);cancel_runs=cancel_runs+1;
        end
        mode=0;reset_all();open_case("m2_n17_k31",2,32,32);
        @(negedge clk);cmd_valid=1;cmd_data=commands[0]^(64'd1<<16);tick();sticky(2);profile_faults=profile_faults+1;
        if(requests!=0) $fatal(1,"bad profile touched memory");
        good("m2_n17_k31",2,32,32);
        @(negedge clk);cmd_valid=1;cmd_data=commands[48];tick();sticky(3);profile_faults=profile_faults+1;
        reset_all();@(negedge clk);cmd_valid=1;cmd_data=64'hffff00000000ffff;tick();sticky(1);profile_faults=profile_faults+1;
        if(requests!=0) $fatal(1,"unknown field touched memory");
        $display("PASS raw C32 K16 array front good_runs=%0d fault_runs=%0d reset_phases=%0d cancels=%0d profile_faults=%0d checked_frames=%0d seed=3588af16",good_runs,fault_runs,reset_runs,cancel_runs,profile_faults,total_frames_checked);
        $finish;
    end
    initial begin #30000000;$fatal(1,"array front watchdog");end
endmodule
