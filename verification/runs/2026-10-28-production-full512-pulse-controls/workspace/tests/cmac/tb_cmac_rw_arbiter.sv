// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_rw_arbiter;
    logic clk,rst_n=0,cancel=0;
    logic [7:0] cancel_code=0;
    logic read_req_valid=0,write_req_valid=0,read_rsp_ready=0,write_rsp_ready=0;
    wire read_req_ready,write_req_ready,read_rsp_valid,write_rsp_valid,read_rsp_error,write_rsp_error;
    logic [31:0] read_req_addr=32'h1000,write_req_addr=32'h2000;
    logic [15:0] write_req_data=16'habcd;
    wire [15:0] read_rsp_data;
    wire mem_req_valid,mem_req_write,mem_rsp_ready,busy,error;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_data;
    wire [7:0] error_code;
    logic mem_req_ready=0,mem_rsp_valid=0,mem_rsp_error=0;
    logic [15:0] mem_rsp_data=16'hbeef;
    integer transfers=0,cancels=0,reads=0,writes=0;
    initial clk=0;
    always #5 clk=~clk;
    rk_cmac_rw_arbiter dut(.*);
    task automatic tick;@(posedge clk);#1;endtask
    task automatic reset_all;
        @(negedge clk);rst_n=0;cancel=1;cancel_code=4;read_req_valid=0;write_req_valid=0;
        read_rsp_ready=0;write_rsp_ready=0;mem_req_ready=0;mem_rsp_valid=0;mem_rsp_error=0;
        read_req_addr=32'h1000;write_req_addr=32'h2000;write_req_data=16'habcd;
        repeat(3) begin tick();if(error||busy||mem_req_valid||mem_rsp_ready||read_req_ready||write_req_ready||read_rsp_valid||write_rsp_valid||error_code!==0) $fatal(1,"reset dominance");end
        @(negedge clk);rst_n=1;cancel=0;cancel_code=0;tick();if(error||busy) $fatal(1,"stale arbiter state");
    endtask
    task automatic wait_request(input logic write_owner);
        begin: wait_req
            for(integer age=0;age<4;age=age+1) begin tick();if(mem_req_valid) disable wait_req;end
            $fatal(1,"missing arbiter request");
        end
        if(mem_req_write!==write_owner||mem_req_addr!==(write_owner ? 32'h2000 : 32'h1000)||mem_req_data!==(write_owner ? 16'habcd : 16'd0)||!busy||error) $fatal(1,"owner/request mismatch");
    endtask
    task automatic accept_request(input logic write_owner);
        repeat(3) begin
            tick();if(!mem_req_valid||mem_req_write!==write_owner||mem_req_addr!==(write_owner ? 32'h2000 : 32'h1000)||read_req_ready||write_req_ready) $fatal(1,"stalled request switched owners");
        end
        @(negedge clk);mem_req_ready=1;#1;
        if(read_req_ready!==!write_owner||write_req_ready!==write_owner) $fatal(1,"ready routed to wrong client");
        tick();if(mem_req_valid||!busy||error) $fatal(1,"request handoff");
        @(negedge clk);mem_req_ready=0;
    endtask
    task automatic respond(input logic write_owner,input logic response_error);
        @(negedge clk);mem_rsp_valid=1;mem_rsp_error=response_error;read_rsp_ready=0;write_rsp_ready=0;
        repeat(4) begin
            tick();if(read_rsp_valid!==!write_owner||write_rsp_valid!==write_owner||mem_rsp_ready||!busy||error) $fatal(1,"response routing/backpressure");
            if(write_owner ? write_rsp_error!==response_error : (read_rsp_error!==response_error||read_rsp_data!==16'hbeef)) $fatal(1,"response payload/error changed");
        end
        @(negedge clk);read_rsp_ready=1;write_rsp_ready=1;#1;if(!mem_rsp_ready) $fatal(1,"response readiness");
        tick();if(busy||error||read_rsp_valid||write_rsp_valid) $fatal(1,"response did not retire");
        @(negedge clk);mem_rsp_valid=0;mem_rsp_error=0;read_rsp_ready=0;write_rsp_ready=0;
        transfers=transfers+1;if(write_owner) writes=writes+1;else reads=reads+1;
    endtask
    task automatic sticky;
        repeat(8) begin
            @(negedge clk);cancel=0;read_req_valid=1;write_req_valid=1;mem_req_ready=1;read_rsp_ready=1;write_rsp_ready=1;tick();
            if(!error||busy||mem_req_valid||mem_rsp_ready||read_req_ready||write_req_ready||read_rsp_valid||write_rsp_valid) $fatal(1,"arbiter fault escaped");
        end
    endtask
    initial begin
        reset_all();@(negedge clk);read_req_valid=1;write_req_valid=1;
        for(integer i=0;i<32;i=i+1) begin wait_request(i[0]);accept_request(i[0]);respond(i[0],i[1]);end
        // A read arriving behind an already exposed write cannot change the
        // request under external backpressure or steal its eventual response.
        reset_all();@(negedge clk);write_req_valid=1;wait_request(1);
        @(negedge clk);read_req_valid=1;accept_request(1);respond(1,0);
        for(integer phase=0;phase<3;phase=phase+1) begin
            reset_all();
            if(phase!=0) begin @(negedge clk);read_req_valid=1;wait_request(0);end
            if(phase==2) accept_request(0);
            @(negedge clk);cancel=1;cancel_code=2;tick();if(error_code!==2) $fatal(1,"cancel code");sticky();cancels=cancels+1;
            reset_all();@(negedge clk);read_req_valid=1;wait_request(0);accept_request(0);respond(0,0);
        end
        reset_all();@(negedge clk);mem_rsp_valid=1;tick();
        if(!error||error_code!==6||mem_rsp_ready) $fatal(1,"unsolicited response accepted");sticky();
        $display("PASS CMAC read/write arbiter transfers=%0d reads=%0d writes=%0d fair_pairs=16 locked_write=1 cancels=%0d unsolicited_faults=1",transfers,reads,writes,cancels);
        $finish;
    end
    initial begin #100000;$fatal(1,"arbiter watchdog");end
endmodule
