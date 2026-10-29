`timescale 1ns/1ps
module tb_jtag_backend;
    logic clk;
    initial clk=0;
    always #10 clk=~clk;
    logic rst_n=0, req_valid=0, req_ready, rsp_valid, fault, memory_busy;
    logic [603:0] req=0;
    logic [511:0] rsp_data;
    logic [7:0] rsp_status;
    logic [15:0] rsp_seq;
    logic memory_available=1;
    logic [31:0] s_axil_awaddr,s_axil_wdata,s_axil_araddr,s_axil_rdata=0;
    logic [2:0] s_axil_awprot,s_axil_arprot;
    logic [3:0] s_axil_wstrb;
    logic s_axil_awvalid,s_axil_awready=0,s_axil_wvalid,s_axil_wready=0;
    logic s_axil_bvalid=0,s_axil_bready,s_axil_arvalid,s_axil_arready=0,s_axil_rvalid=0,s_axil_rready;
    logic [1:0] s_axil_bresp=0,s_axil_rresp=0;
    logic host_valid,host_ready=0,host_write,host_rsp_valid=0,host_rsp_ready,host_error=0;
    logic [31:0] host_addr;
    logic [15:0] host_wdata,host_rdata=0;
    logic [15:0] sequence_id=0;
    logic [511:0] pattern;
    integer replies;
    rk_jtag_backend #(.BYTES(256),.TIMEOUT_CYCLES(8)) dut(.*);

    logic held_aw,held_w,held_ar,held_mem;
    initial begin replies=0;held_aw=0;held_w=0;held_ar=0;held_mem=0;end
    logic [31:0] prev_aw,prev_ar;
    logic [35:0] prev_w;
    logic [48:0] prev_mem;
    always @(posedge clk) begin
        if (rst_n) begin
            if (held_aw && (!s_axil_awvalid || s_axil_awaddr!==prev_aw)) $fatal(1,"AW changed while stalled");
            if (held_w && (!s_axil_wvalid || {s_axil_wstrb,s_axil_wdata}!==prev_w)) $fatal(1,"W changed while stalled");
            if (held_ar && (!s_axil_arvalid || s_axil_araddr!==prev_ar)) $fatal(1,"AR changed while stalled");
            if (held_mem && (!host_valid || {host_write,host_addr,host_wdata}!==prev_mem)) $fatal(1,"RAM request changed while stalled");
            if (s_axil_awprot!==0 || s_axil_arprot!==0) $fatal(1,"AXIL protection changed");
            if (s_axil_bvalid && !s_axil_bready) $fatal(1,"test supplied B when backend not receiving");
            if (s_axil_rvalid && !s_axil_rready) $fatal(1,"test supplied R when backend not receiving");
            if (rsp_valid) replies<=replies+1;
        end
        held_aw<=rst_n && s_axil_awvalid && !s_axil_awready; prev_aw<=s_axil_awaddr;
        held_w<=rst_n && s_axil_wvalid && !s_axil_wready; prev_w<={s_axil_wstrb,s_axil_wdata};
        held_ar<=rst_n && s_axil_arvalid && !s_axil_arready; prev_ar<=s_axil_araddr;
        held_mem<=rst_n && host_valid && !host_ready; prev_mem<={host_write,host_addr,host_wdata};
    end
    task automatic reset_all;
        @(negedge clk); rst_n=0; req_valid=0;
        s_axil_awready=0;s_axil_wready=0;s_axil_arready=0;s_axil_bvalid=0;s_axil_rvalid=0;
        host_ready=0;host_rsp_valid=0;host_error=0;
        repeat(3) @(negedge clk);
        if (rsp_valid || s_axil_awvalid || s_axil_wvalid || s_axil_arvalid || host_valid) $fatal(1,"activity during reset");
        rst_n=1; @(negedge clk);
        if (!req_ready || fault) $fatal(1,"reset did not clear quarantine");
    endtask
    task automatic send(input logic [7:0] op,input logic [31:0] addr,
                        input logic [511:0] data=0,input logic [3:0] strobes=15);
        if (!req_ready) $fatal(1,"unexpected request refusal");
        sequence_id=sequence_id+1;
        req={32'h4f54504a,sequence_id,op,strobes,addr,data};req_valid=1;
        @(negedge clk);req_valid=0;
    endtask
    task automatic expect_rsp(input logic [7:0] status,input logic [511:0] data=0);
        integer cycles;
        cycles=0;
        while (!rsp_valid && cycles<20) begin @(negedge clk);cycles=cycles+1;end
        if (!rsp_valid || rsp_status!==status || rsp_data!==data || rsp_seq!==sequence_id)
            $fatal(1,"response mismatch seq=%h status=%h expected=%h data=%h",rsp_seq,rsp_status,status,rsp_data);
        @(negedge clk);
        if (rsp_valid) $fatal(1,"response was not a pulse");
    endtask
    task automatic read_reg(input logic [1:0] response);
        send(1,32'h24);
        repeat(3) @(negedge clk);
        if (!s_axil_arvalid || s_axil_araddr!==32'h24 || req_ready) $fatal(1,"read not pending");
        s_axil_arready=1;@(negedge clk);s_axil_arready=0;
        repeat(2) @(negedge clk);
        s_axil_rvalid=1;s_axil_rdata=32'h524b4557;s_axil_rresp=response;
        @(negedge clk);s_axil_rvalid=0;
        expect_rsp({6'b0,response},response==0 ? 512'h524b4557 : 512'b0);
    endtask
    task automatic write_reg(input bit w_first,input logic [1:0] response);
        send(2,32'h18,512'h3588);
        repeat(2) @(negedge clk);
        if (!s_axil_awvalid || !s_axil_wvalid || s_axil_awaddr!==32'h18 || s_axil_wdata!==32'h3588 || s_axil_wstrb!==15)
            $fatal(1,"wrong write payload");
        if (w_first) s_axil_wready=1;else s_axil_awready=1;
        @(negedge clk);s_axil_wready=0;s_axil_awready=0;
        repeat(3) @(negedge clk);
        if (w_first) s_axil_awready=1;else s_axil_wready=1;
        @(negedge clk);s_axil_wready=0;s_axil_awready=0;
        repeat(2) @(negedge clk);s_axil_bvalid=1;s_axil_bresp=response;
        @(negedge clk);s_axil_bvalid=0;
        expect_rsp({6'b0,response});
    endtask
    task automatic line_transfer(input bit writing,input integer fail_at=-1);
        send(writing ? 8'd4 : 8'd3,32'h10000040,writing ? pattern : 512'b0);
        for (integer i=0;i<(fail_at<0 ? 32 : fail_at+1);i=i+1) begin
            if (!memory_busy || !host_valid || host_write!==writing || host_addr!==32'h10000040+32'(2*i)) $fatal(1,"bad RAM word/address");
            if (writing && host_wdata!==pattern[16*i +:16]) $fatal(1,"wrong little-endian word");
            repeat(1+i%3) @(negedge clk);
            host_ready=1;@(negedge clk);host_ready=0;
            if (host_valid || !host_rsp_ready || rsp_valid) $fatal(1,"early RAM completion");
            repeat(1+i%2) @(negedge clk);
            host_rsp_valid=1;host_rdata=pattern[16*i +:16];host_error=i==fail_at;
            @(negedge clk);host_rsp_valid=0;host_error=0;
            if (i==fail_at) begin
                expect_rsp(2);
                if (host_valid) $fatal(1,"RAM continued after error");
            end
        end
        if (fail_at<0) expect_rsp(0,writing ? 512'b0 : pattern);
        if (memory_busy) $fatal(1,"memory ownership retained after response");
    endtask
    initial begin
        for (integer i=0;i<32;i=i+1) pattern[16*i +:16]=16'h3588 ^ 16'(i*1237);
        reset_all();
        send(8'hff,0);expect_rsp(5);
        send(1,2);expect_rsp(4);
        send(3,32'h10000002);expect_rsp(4);
        send(3,32'h90000000);expect_rsp(6);
        send(4,32'h10000100,pattern);expect_rsp(6);
        send(3,32'h0fffffc0);expect_rsp(6);
        send(1,0,512'd1);expect_rsp(5);
        send(2,0,512'h100000000);expect_rsp(5);
        send(3,32'h10000000,0,0);expect_rsp(5);
        memory_available=0;send(4,32'h10000000,pattern);expect_rsp(2);memory_available=1;
        if (host_valid || s_axil_awvalid || s_axil_arvalid) $fatal(1,"invalid request had bus side effects");
        read_reg(0);read_reg(2);read_reg(3);
        write_reg(0,0);write_reg(1,2);write_reg(0,3);
        line_transfer(1);line_transfer(0);line_transfer(1,7);line_transfer(0,13);
        // Timeout does not withdraw AR; no later request/duplicate response.
        send(1,0);expect_rsp(8'h80);
        if (!fault || req_ready || !s_axil_arvalid) $fatal(1,"timeout did not quarantine outstanding AR");
        repeat(3) @(negedge clk);
        s_axil_arready=1;@(negedge clk);s_axil_arready=0;
        s_axil_rvalid=1;s_axil_rresp=0;@(negedge clk);s_axil_rvalid=0;
        repeat(3) @(negedge clk);if (rsp_valid || req_ready) $fatal(1,"late response escaped quarantine");
        reset_all();
        // Timeout after AW only must retain W until eventual acceptance.
        send(2,16,512'h1234);s_axil_awready=1;@(negedge clk);s_axil_awready=0;
        expect_rsp(8'h80);if (!fault || !s_axil_wvalid) $fatal(1,"timeout withdrew W");
        s_axil_wready=1;@(negedge clk);s_axil_wready=0;
        s_axil_bvalid=1;@(negedge clk);s_axil_bvalid=0;
        reset_all();
        send(4,32'h10000000,pattern);expect_rsp(8'h80);
        if (!fault || !host_valid) $fatal(1,"timeout withdrew RAM request");
        host_ready=1;@(negedge clk);host_ready=0;host_rsp_valid=1;
        @(negedge clk);host_rsp_valid=0;reset_all();
        send(3,32'h10000000);host_ready=1;@(negedge clk);host_ready=0;
        expect_rsp(8'h80);if (!fault || !host_rsp_ready) $fatal(1,"RAM response timeout did not drain");
        reset_all();
        // Invalid early B and AXI-Lite EXOKAY fail as protocol errors.
        send(2,0);s_axil_bvalid=1;s_axil_bresp=0;@(negedge clk);s_axil_bvalid=0;
        expect_rsp(7);if (!fault) $fatal(1,"early B did not quarantine");reset_all();
        send(1,0);s_axil_arready=1;@(negedge clk);s_axil_arready=0;
        s_axil_rvalid=1;s_axil_rresp=1;@(negedge clk);s_axil_rvalid=0;
        expect_rsp(7);if (!fault) $fatal(1,"EXOKAY did not quarantine");reset_all();
        // A response cannot precede the clock edge that accepts the request.
        // Otherwise stale B/R could masquerade as a new zero-latency response.
        send(2,0);s_axil_awready=1;s_axil_wready=1;s_axil_bvalid=1;s_axil_bresp=0;
        @(negedge clk);s_axil_awready=0;s_axil_wready=0;s_axil_bvalid=0;
        expect_rsp(7);if (!fault) $fatal(1,"same-edge AW/W/B did not quarantine");reset_all();
        send(1,0);s_axil_arready=1;s_axil_rvalid=1;s_axil_rresp=0;s_axil_rdata=32'hbad0bad0;
        @(negedge clk);s_axil_arready=0;s_axil_rvalid=0;
        expect_rsp(7);if (!fault) $fatal(1,"same-edge AR/R did not quarantine");reset_all();
        if (replies!=28) $fatal(1,"coverage count mismatch %0d",replies);
        $display("PASS jtag_backend 28 replies; independent AXIL channels, 32-word endian lines, rejection, stalls, timeout quarantine and joint reset");
        $finish;
    end
    initial begin #1000000;$fatal(1,"backend test timeout");end
endmodule
