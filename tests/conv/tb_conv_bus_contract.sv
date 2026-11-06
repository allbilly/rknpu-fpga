// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_conv_bus_contract;
    logic clk=0, rst_n=0;
    logic cancel=0;
    logic [7:0] cancel_code=0;
    logic read_req_valid=0, read_rsp_ready=0;
    logic [31:0] read_req_addr=0;
    logic write_req_valid=0, write_rsp_ready=0;
    logic [31:0] write_req_addr=0;
    logic [15:0] write_req_data=0;
    logic mem_req_ready=0, mem_rsp_valid=0, mem_rsp_error=0;
    logic [15:0] mem_rsp_data=0;
    wire read_req_ready, read_rsp_valid, read_rsp_error;
    wire [15:0] read_rsp_data;
    wire write_req_ready, write_rsp_valid, write_rsp_error;
    wire mem_req_valid, mem_req_write, mem_rsp_ready, busy, error;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_data;
    wire [7:0] error_code;

    always #5 clk=~clk;

    rk_cmac_rw_arbiter dut(.*);

    task automatic tick;
        begin @(posedge clk); #1; end
    endtask

    initial begin
        repeat (2) tick();
        @(negedge clk); rst_n=1;

        // Read request must remain stable while the adapter applies backpressure.
        @(negedge clk); read_req_valid=1; read_req_addr=32'h00001000;
        tick();
        if (!mem_req_valid || mem_req_write || mem_req_addr!==32'h00001000)
            $fatal(1,"read request was not presented");
        repeat (3) begin
            tick();
            if (!mem_req_valid || mem_req_write || mem_req_addr!==32'h00001000 ||
                mem_req_ready)
                $fatal(1,"stalled read request changed");
        end
        @(negedge clk); mem_req_ready=1;
        #1 if (!read_req_ready) $fatal(1,"read request was not acknowledged");
        tick();
        if (mem_req_valid) $fatal(1,"read request remained valid after handshake");

        // The adapter must hold response valid and payload while the read
        // client backpressures the arbiter.
        @(negedge clk);
        read_req_valid=0; mem_req_ready=0;
        mem_rsp_valid=1; mem_rsp_data=16'h3c00; mem_rsp_error=0;
        repeat (3) begin
            tick();
            if (!read_rsp_valid || mem_rsp_ready || read_rsp_data!==16'h3c00 ||
                read_rsp_error)
                $fatal(1,"read response backpressure contract failed");
        end
        @(negedge clk); read_rsp_ready=1;
        #1 if (!mem_rsp_ready || !read_rsp_valid)
            $fatal(1,"read response handshake was not presented");
        tick();

        // Repeat the held-response test for a write acknowledgment and preserve
        // the bus error status until the sink accepts it.
        @(negedge clk);
        mem_rsp_valid=0; read_rsp_ready=0;
        write_req_valid=1; write_req_addr=32'h00003020; write_req_data=16'h4000;
        mem_req_ready=0;
        tick();
        if (!mem_req_valid || !mem_req_write || mem_req_addr!==32'h00003020 ||
            mem_req_data!==16'h4000)
            $fatal(1,"write request was not presented");
        repeat (3) begin
            tick();
            if (!mem_req_valid || !mem_req_write || mem_req_addr!==32'h00003020 ||
                mem_req_data!==16'h4000 || mem_req_ready)
                $fatal(1,"stalled write request changed");
        end
        @(negedge clk); mem_req_ready=1;
        #1 if (!write_req_ready) $fatal(1,"write request was not acknowledged");
        tick();
        if (mem_req_valid) $fatal(1,"write request remained valid after handshake");

        @(negedge clk);
        write_req_valid=0; mem_req_ready=0;
        mem_rsp_valid=1; mem_rsp_data=16'h0000; mem_rsp_error=1;
        repeat (3) begin
            tick();
            if (!write_rsp_valid || mem_rsp_ready || !write_rsp_error)
                $fatal(1,"write acknowledgment backpressure/error contract failed");
        end
        @(negedge clk); write_rsp_ready=1;
        #1 if (!mem_rsp_ready || !write_rsp_valid || !write_rsp_error)
            $fatal(1,"write response handshake was not presented");
        tick();

        @(negedge clk); mem_rsp_valid=0;
        tick();
        if (error || busy || mem_req_valid || mem_rsp_ready)
            $fatal(1,"arbiter did not return idle after accepted responses");
        $display("PASS_CONV_BUS_REQUEST_AND_RESPONSE_STABILITY");
        $finish;
    end

    initial begin #100000; $fatal(1,"arbiter contract test watchdog"); end
endmodule
