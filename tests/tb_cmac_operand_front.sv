// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_operand_front;
    logic clk, rst_n;
    initial clk=0;
    always #5 clk=~clk;
    logic cmd_valid, cmd_ready, downstream_busy, busy, address_done, stream_done, error;
    logic [63:0] cmd_data;
    logic [7:0] error_code;
    logic mem_req_valid, mem_req_ready, mem_rsp_valid, mem_rsp_ready, mem_rsp_error;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_rsp_rdata;
    logic operand_valid, operand_ready;
    logic [15:0] operand_input, operand_weight;
    logic [31:0] operand_output_address, operand_row, operand_oc, operand_ic;
    logic operand_first, operand_last, operand_last_output;
    rk_cmac_operand_front #(.TIMEOUT_CYCLES(32)) dut(.*);
    string root_path, path;
    logic [63:0] commands [0:48];
    logic [15:0] input_mem [0:4095], weight_mem [0:8191];
    logic [31:0] expect_a, expect_b, expect_d, expect_row, expect_oc, expect_ic;
    logic [15:0] expect_input, expect_weight;
    logic [2:0] expect_flags;
    logic [162:0] stalled_operand;
    logic [31:0] stalled_addr;
    logic operand_stalled, request_stalled;
    wire [162:0] operand_bits={operand_input,operand_weight,operand_output_address,
                              operand_row,operand_oc,operand_ic,operand_first,operand_last,operand_last_output};
    integer rows, ai, ao, total_pairs, expected_fd;
    integer requests, operands, pair_requests, address_pulses, stream_pulses, final_stalls;
    integer total_operands, good_runs, fault_runs, reset_runs, x_runs;
    integer fault_mode, fault_at, slave_count, response_delay, request_wait, response_wait;
    logic checking, slave_pending;
    logic [31:0] rng;
    logic [15:0] response_data;
    logic response_error;

    // Fault modes: 1 bus error, 2 request timeout, 3 response timeout,
    // 4 unknown response status (Icarus only). Output backpressure is not a
    // memory timeout and the final operand is held for 40 cycles to prove it.
    assign mem_req_ready=rst_n && !slave_pending && rng[2:0]!=0 && !(fault_mode==2 && slave_count+1==fault_at);
    assign mem_rsp_valid=rst_n && slave_pending && response_delay==0 && !(fault_mode==3 && slave_count==fault_at);
    assign mem_rsp_rdata=response_data;
    assign mem_rsp_error=response_error;
    assign operand_ready=rst_n && rng[5:3]!=0 && !(operand_last && operand_last_output && final_stalls<40);

    function automatic logic [15:0] read_half(input logic [31:0] address);
        if (address>=32'h10010000 && address<32'h10010000+32'(rows*ai*2) && address[0]==0)
            return input_mem[(address-32'h10010000)>>1];
        if (address>=32'h10020000 && address<32'h10020000+32'(ao*ai*2) && address[0]==0)
            return weight_mem[(address-32'h10020000)>>1];
        $fatal(1,"unmapped/unaligned operand read %h",address);
        return 0;
    endfunction
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            slave_pending<=0; slave_count<=0; response_delay<=0;
            response_data<=0; response_error<=0; rng<=32'h3588ca03;
        end else begin
            rng<=rng*32'd1664525+32'd1013904223;
            if (mem_req_valid && mem_req_ready) begin
                if (slave_pending) $fatal(1,"multiple outstanding requests");
                slave_pending<=1; slave_count<=slave_count+1;
                response_data<=read_half(mem_req_addr); response_delay<=int'({29'b0,rng[8:6]});
                response_error<=fault_mode==1 && slave_count+1==fault_at;
`ifndef VERILATOR
                if (fault_mode==4 && slave_count+1==fault_at) response_error<=1'bx;
`endif
            end
            if (slave_pending) begin
                if (response_delay>0) response_delay<=response_delay-1;
                else if (mem_rsp_valid && mem_rsp_ready) slave_pending<=0;
            end
        end
    end

    task automatic next_expected;
        if ($fscanf(expected_fd,"%h %h %h %h %h %h %h %h %h",expect_a,expect_b,expect_d,
                    expect_row,expect_oc,expect_ic,expect_input,expect_weight,expect_flags)!=9)
            $fatal(1,"missing expected operand %0d",operands);
    endtask
    task automatic tick;
        logic req_fire, op_fire, last_fire, pre_req_valid, pre_req_ready, pre_rsp_ready, pre_rsp_valid;
        logic pre_op_valid, pre_op_ready;
        logic [31:0] req_addr;
        logic [162:0] op_bits;
        @(posedge clk);
        req_fire=mem_req_valid && mem_req_ready;
        op_fire=operand_valid && operand_ready;
        last_fire=op_fire && operand_last && operand_last_output;
        pre_req_valid=mem_req_valid; pre_req_ready=mem_req_ready; req_addr=mem_req_addr;
        pre_rsp_ready=mem_rsp_ready; pre_rsp_valid=mem_rsp_valid;
        pre_op_valid=operand_valid; pre_op_ready=operand_ready; op_bits=operand_bits;
        #1;
        if (checking && rst_n) begin
            if (request_stalled && (pre_req_valid!==1 || req_addr!==stalled_addr)) $fatal(1,"unstable request");
            if (operand_stalled && (pre_op_valid!==1 || op_bits!==stalled_operand)) $fatal(1,"unstable operand/tag");
            request_stalled=pre_req_valid && !pre_req_ready && !error;
            operand_stalled=pre_op_valid && !pre_op_ready;
            stalled_addr=req_addr; stalled_operand=op_bits;
            if (pre_req_valid && !pre_req_ready) request_wait=request_wait+1; else request_wait=0;
            if (pre_rsp_ready && !pre_rsp_valid) response_wait=response_wait+1; else response_wait=0;
            if (req_fire) begin
                if (operands>=total_pairs || pair_requests>=2) $fatal(1,"extra operand request");
                if (req_addr !== (pair_requests==0 ? expect_a : expect_b))
                    $fatal(1,"request order/address operand=%0d phase=%0d got=%h A=%h W=%h",operands,pair_requests,req_addr,expect_a,expect_b);
                requests=requests+1; pair_requests=pair_requests+1;
            end
            if (pre_op_valid && op_bits !== {expect_input,expect_weight,expect_d,expect_row,expect_oc,expect_ic,expect_flags})
                $fatal(1,"operand data/tag mismatch at %0d",operands);
            if (pre_op_valid && !pre_op_ready && expect_flags[1:0]==2'b11) final_stalls=final_stalls+1;
            if (op_fire) begin
                if (pair_requests!=2) $fatal(1,"operand before both reads");
                operands=operands+1; total_operands=total_operands+1; pair_requests=0;
                if (operands<total_pairs) next_expected();
            end
            if (address_done) begin
                address_pulses=address_pulses+1;
                if (!busy || stream_done || operands>=total_pairs) $fatal(1,"address issuance counted as stream completion");
            end
            if (stream_done !== last_fire) $fatal(1,"stream_done not bound to final operand handshake");
            if (stream_done) stream_pulses=stream_pulses+1;
            if ((pre_req_valid || pre_rsp_ready || pre_op_valid) && !last_fire && !error && !busy)
                $fatal(1,"busy dropped while operands remain in flight");
            if (error && error_code==8 && request_wait!=32 && response_wait!=32)
                $fatal(1,"timeout did not occur on exactly 32 stalled memory cycles: req=%0d rsp=%0d",request_wait,response_wait);
        end
    endtask
    task automatic reset_all;
        checking=0;
        @(negedge clk);rst_n=0;cmd_valid=0;cmd_data=0;downstream_busy=0;
        repeat(2) tick();
        if (mem_req_valid!==0 || operand_valid!==0 || error!==0 || stream_done!==0 || busy!==0)
            $fatal(1,"reset state");
        requests=0;operands=0;pair_requests=0;address_pulses=0;stream_pulses=0;final_stalls=0;
        request_stalled=0;operand_stalled=0;request_wait=0;response_wait=0;
        @(negedge clk);rst_n=1;
        tick();checking=1;
    endtask
    task automatic open_case(input string name,input integer m,input integer in_channels,input integer out_channels);
        rows=m;ai=in_channels;ao=out_channels;total_pairs=rows*ai*ao;
        path={root_path,"/",name,"/commands.hex"};$readmemh(path,commands);
        path={root_path,"/",name,"/input.hex"};$readmemh(path,input_mem,0,rows*ai-1);
        path={root_path,"/",name,"/weight.hex"};$readmemh(path,weight_mem,0,ao*ai-1);
        path={root_path,"/",name,"/expected.txt"};expected_fd=$fopen(path,"r");
        if (expected_fd==0) $fatal(1,"opening expected operand file");
        next_expected();
    endtask
    task automatic submit;
        for (integer w=0;w<49;w=w+1) begin
            @(negedge clk);cmd_valid=1;cmd_data=commands[w];
            if (cmd_ready!==1) $fatal(1,"raw command blocked at word %0d",w);
            tick();
        end
        @(negedge clk);cmd_valid=0;downstream_busy=1;
    endtask
    task automatic finish_good;
        while (stream_pulses==0 && !error) tick();
        if (error || operands!=total_pairs || requests!=2*total_pairs || address_pulses!=1 || stream_pulses!=1 || final_stalls<40)
            $fatal(1,"good stream failed operands=%0d requests=%0d err=%b code=%0d",operands,requests,error,error_code);
        repeat(4) begin
            tick();
            if (cmd_ready!==0 || busy!==1 || mem_req_valid!==0 || operand_valid!==0 || stream_done!==0)
                $fatal(1,"downstream ownership lost before final write phase");
        end
        @(negedge clk);downstream_busy=0;
        tick();
        if (cmd_ready!==1 || busy!==0) $fatal(1,"ownership release");
        good_runs=good_runs+1;$fclose(expected_fd);
    endtask
    task automatic good(input string name,input integer m,input integer in_channels,input integer out_channels);
        fault_mode=0;fault_at=0;reset_all();open_case(name,m,in_channels,out_channels);submit();finish_good();
    endtask
    task automatic fault(input integer mode,input integer at_request,input logic [7:0] code);
        fault_mode=mode;fault_at=at_request;reset_all();open_case("m2_n17_k31",2,32,32);submit();
        while (!error && stream_pulses==0) tick();
        if (error!==1 || error_code!==code || stream_pulses!=0 || operands!=(at_request-1)/2)
            $fatal(1,"fault expectation mode=%0d at=%0d code=%0d operands=%0d",mode,at_request,error_code,operands);
        checking=0; // The exact timeout cycle was checked on assertion above.
        repeat(5) begin
            @(negedge clk);cmd_valid=1;cmd_data=commands[0];tick();
            if (cmd_ready!==0 || mem_req_valid!==0 || mem_rsp_ready!==0 || operand_valid!==0 || stream_done!==0 || error_code!==code)
                $fatal(1,"fault not sticky/quiescent");
        end
        @(negedge clk);cmd_valid=0;
        $fclose(expected_fd);fault_runs=fault_runs+1;
    endtask

    initial begin
        rst_n=0;cmd_valid=0;cmd_data=0;downstream_busy=0;checking=0;
        rows=0;ai=0;ao=0;final_stalls=0;fault_mode=0;fault_at=0;
        total_operands=0;good_runs=0;fault_runs=0;reset_runs=0;x_runs=0;
        if (!$value$plusargs("ROOT=%s",root_path)) $fatal(1,"missing ROOT");
        good("m1_n8_k7",8,32,32);good("m1_n8_k8",8,32,32);good("m1_n8_k9",8,32,32);
        good("m2_n17_k31",2,32,32);good("m2_n17_k32",2,32,32);
        good("m2_n17_k33",2,64,32);good("m2_n17_k65",2,96,32);
        fault(1,1,5);fault(1,2,5);fault(1,4096,5);
        fault(2,1,8);fault(2,2,8);fault(3,1,8);fault(3,2,8);
`ifndef VERILATOR
        fault(4,1,5);fault(4,2,5);x_runs=2;
`endif
        // Public-port reset in each reader phase after a prefix was emitted.
        for (integer phase=0;phase<5;phase=phase+1) begin
            fault_mode=0;fault_at=0;reset_all();open_case("m2_n17_k31",2,32,32);submit();
            begin : wait_phase
                forever begin
                    tick();
                    if (operands>=7) begin
                        if ((phase==0 && mem_req_valid && pair_requests==0) ||
                            (phase==1 && mem_rsp_ready && pair_requests==1) ||
                            (phase==2 && mem_req_valid && pair_requests==1) ||
                            (phase==3 && mem_rsp_ready && pair_requests==2) ||
                            (phase==4 && operand_valid && !operand_ready)) disable wait_phase;
                    end
                end
            end
            if (stream_pulses!=0) $fatal(1,"reset prefix unexpectedly completed");
            $fclose(expected_fd);reset_runs=reset_runs+1;
            good("m2_n17_k31",2,32,32); // Joint adapter reset, complete restart.
        end
        // Bad profile and a new trigger cannot inherit the preceding task.
        fault_mode=0;fault_at=0;reset_all();open_case("m2_n17_k31",2,32,32);
        @(negedge clk);cmd_valid=1;cmd_data=commands[0]^(64'd1<<16);tick();
        if (error!==1 || error_code!==2 || requests!=0 || operand_valid!==0) $fatal(1,"invalid profile reached memory");
        $fclose(expected_fd);
        good("m2_n17_k31",2,32,32);
        @(negedge clk);cmd_valid=1;cmd_data=commands[48];tick();
        if (error!==1 || error_code!==3 || mem_req_valid!==0) $fatal(1,"stale profile reuse");
        $display("PASS raw CMAC operand front good_runs=%0d fault_runs=%0d reset_phases=%0d x_runs=%0d checked_operands=%0d seed=3588ca03; no numerical GEMM",good_runs,fault_runs,reset_runs,x_runs,total_operands);
        $finish;
    end
    initial begin #30000000;$fatal(1,"operand front HDL timeout");end
endmodule
