`timescale 1ns/1ps
// Independently check the fixed sparse aperture on both ports, including gaps.
module tb_demo_memory;
    localparam logic [31:0] BASE = 32'h10001000;
    logic clk, rst_n = 0;
    initial clk = 0;
    always #5 clk = ~clk;
    logic req_valid = 0, req_ready, req_write = 0;
    logic [31:0] req_addr = BASE;
    logic [15:0] req_wdata = 0, rsp_rdata;
    logic rsp_valid, rsp_ready = 0, rsp_error;
    logic host_valid = 0, host_ready, host_write = 0;
    logic [31:0] host_addr = BASE;
    logic [15:0] host_wdata = 0, host_rdata;
    logic host_rsp_valid, host_rsp_ready = 0, host_error;
    integer transactions = 0;
    rk_demo_memory dut (.*);

    task automatic transfer(input bit host_port, wr, input logic [31:0] addr,
                            input logic [15:0] data, input bit expect_error,
                            input logic [15:0] expected);
        logic [15:0] held_data;
        begin
            @(negedge clk);
            if (host_port) begin
                host_valid = 1; host_write = wr; host_addr = addr; host_wdata = data;
                if (host_ready !== 1'b1) $fatal(1, "host not ready for request");
            end else begin
                req_valid = 1; req_write = wr; req_addr = addr; req_wdata = data;
                if (req_ready !== 1'b1) $fatal(1, "core port not ready for request");
            end
            @(negedge clk);
            if (host_port) begin
                host_valid = 0;
                if (host_rsp_valid !== 1'b1 || host_error !== expect_error)
                    $fatal(1, "host response/error @%08h", addr);
                held_data = host_rdata;
            end else begin
                req_valid = 0;
                if (rsp_valid !== 1'b1 || rsp_error !== expect_error)
                    $fatal(1, "core response/error @%08h", addr);
                held_data = rsp_rdata;
            end
            if (!wr && !expect_error && held_data !== expected)
                $fatal(1, "read @%08h got %04h expected %04h", addr, held_data, expected);
            // A new request must not overwrite an unacknowledged response.
            // Unknown data on a write/error response is allowed, but must be stable.
            repeat (4) begin
                if (host_port) begin
                    host_valid = 1; host_addr = BASE + 4;
                    if (host_ready !== 1'b0 || host_rsp_valid !== 1'b1 ||
                        host_rdata !== held_data || host_error !== expect_error)
                        $fatal(1, "host response changed under backpressure");
                end else begin
                    req_valid = 1; req_addr = BASE + 4;
                    if (req_ready !== 1'b0 || rsp_valid !== 1'b1 ||
                        rsp_rdata !== held_data || rsp_error !== expect_error)
                        $fatal(1, "core response changed under backpressure");
                end
                @(negedge clk);
            end
            req_valid = 0; host_valid = 0;
            if (host_port) host_rsp_ready = 1;
            else rsp_ready = 1;
            @(negedge clk);
            if (host_port ? host_rsp_valid !== 1'b0 : rsp_valid !== 1'b0)
                $fatal(1, "response was not consumed");
            host_rsp_ready = 0; rsp_ready = 0;
            transactions = transactions + 1;
        end
    endtask

    logic [31:0] bases [0:5];
    initial begin
        bases[0]=32'h10001000; bases[1]=32'h10020000; bases[2]=32'h10040000;
        bases[3]=32'h10060000; bases[4]=32'h10061000; bases[5]=32'h100e0000;
        repeat (3) @(negedge clk);
        if (rsp_valid !== 1'b0 || host_rsp_valid !== 1'b0) $fatal(1, "reset response");
        rst_n=1;
        for (integer i=0; i<6; i=i+1) begin
            transfer(1,1,bases[i],16'(16'h1000+i),0,0);
            transfer(0,1,bases[i]+(i==5 ? 510 : 30),16'(16'h2000+i),0,0);
        end
        for (integer port_id=0; port_id<2; port_id=port_id+1) begin
            for (integer i=0; i<6; i=i+1) begin
                transfer(1'(port_id),1,bases[i]-2,16'hbad1,1,0);
                transfer(1'(port_id),1,bases[i]+1,16'hbad2,1,0);
                transfer(1'(port_id),1,bases[i]+(i==5 ? 512 : 32),16'hbad3,1,0);
            end
            transfer(1'(port_id),1,32'h00000000,16'hbad4,1,0);
            transfer(1'(port_id),1,32'hffffffff,16'hbad5,1,0);
            transfer(1'(port_id),1,32'h100f0000,16'hbad6,1,0);
            for (integer i=0; i<6; i=i+1) begin
                transfer(1'(port_id),0,bases[i],0,0,16'(16'h1000+i));
                transfer(1'(port_id),0,bases[i]+(i==5 ? 510 : 30),0,0,16'(16'h2000+i));
            end
        end
        // Two reads accepted on adjacent cycles while retiring the prior reply.
        @(negedge clk);
        req_valid = 1; req_write = 0; req_addr = BASE; rsp_ready = 1;
        @(negedge clk);
        if (rsp_valid !== 1'b1 || rsp_error !== 1'b0 || rsp_rdata !== 16'h1000)
            $fatal(1, "first pipelined response");
        req_addr = 32'h100e01fe;
        @(negedge clk);
        if (rsp_valid !== 1'b1 || rsp_error !== 1'b0 || rsp_rdata !== 16'h2005)
            $fatal(1, "second pipelined response");
        req_valid = 0;
        @(negedge clk);
        if (rsp_valid !== 1'b0) $fatal(1, "extra pipelined response");
        rsp_ready = 0;
        // Reset cancels both stalled replies but leaves the storage untouched.
        req_valid = 1; req_addr = BASE;
        host_valid = 1; host_write = 0; host_addr = 32'h100e01fe;
        @(negedge clk);
        if (rsp_valid !== 1'b1 || host_rsp_valid !== 1'b1) $fatal(1, "missing pending replies");
        req_valid = 0; host_valid = 0; rst_n = 0;
        @(negedge clk);
        if (rsp_valid !== 1'b0 || host_rsp_valid !== 1'b0) $fatal(1, "stale reply after reset");
        rst_n = 1;
        transfer(0, 0, BASE, 0, 0, 16'h1000);
        transfer(1, 0, 32'h100e01fe, 0, 0, 16'h2005);
        $display("PASS sparse demo BRAM: %0d checked transfers, adjacent requests, dual-port reset", transactions);
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "BRAM test timeout");
    end
endmodule
