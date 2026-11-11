// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Unit bench for rk_jtag_axil_bridge: mailbox frames become AXI4-Lite.
//
// The AXI slave here is a tiny memory with an error window, so every status
// path (OK / frame / alignment / downstream / timeout) is exercised.
module tb_jtag_axil_bridge;
    localparam logic [31:0] MAGIC = 32'h4f54504a;
    localparam int unsigned TIMEOUT_CYCLES = 64;
    localparam int unsigned MEM_WORDS = 64;

    logic clk = 0;
    always #10 clk = ~clk;

    logic rst_n = 0;
    logic req_valid = 0, req_ready, rsp_valid, fault;
    logic [603:0] req = 0;
    logic [511:0] rsp_data;
    logic [7:0] rsp_status;
    logic [15:0] rsp_seq;
    logic [15:0] sequence_q;

    logic [31:0] s_axil_awaddr, s_axil_wdata, s_axil_araddr, s_axil_rdata;
    logic [2:0] s_axil_awprot, s_axil_arprot;
    logic [3:0] s_axil_wstrb;
    logic [1:0] s_axil_bresp, s_axil_rresp;
    logic s_axil_awvalid, s_axil_awready, s_axil_wvalid, s_axil_wready;
    logic s_axil_bvalid, s_axil_bready, s_axil_arvalid, s_axil_arready;
    logic s_axil_rvalid, s_axil_rready;

    logic [31:0] memory [0:MEM_WORDS-1];
    logic aw_pending, w_pending, ar_pending, bvalid, rvalid;
    logic [31:0] aw_address, w_data, ar_address;
    logic [1:0] bresp, rresp;
    logic [31:0] rdata;
    integer stall_count;

    rk_jtag_axil_bridge #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) dut (
        .clk, .rst_n,
        .req_valid, .req_ready, .req,
        .rsp_valid, .rsp_data, .rsp_status, .rsp_seq, .fault,
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready
    );

    // AXI slave: one outstanding transaction, optional stalls, an error window.
    assign s_axil_awready = rst_n && !aw_pending && !bvalid && (stall_count == 0);
    assign s_axil_wready = rst_n && !w_pending && !bvalid && (stall_count == 0);
    assign s_axil_arready = rst_n && !ar_pending && !rvalid && (stall_count == 0);
    assign s_axil_bvalid = bvalid;
    assign s_axil_rvalid = rvalid;
    assign s_axil_bresp = bresp;
    assign s_axil_rresp = rresp;
    assign s_axil_rdata = rdata;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            aw_pending <= 0; w_pending <= 0; ar_pending <= 0;
            bvalid <= 0; rvalid <= 0; bresp <= 0; rresp <= 0;
            stall_count <= 0;
        end else begin
            if (stall_count > 0) stall_count <= stall_count - 1;
            if (s_axil_awvalid && s_axil_awready) begin
                aw_pending <= 1; aw_address <= s_axil_awaddr;
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_pending <= 1; w_data <= s_axil_wdata;
            end
            if (aw_pending && w_pending && !bvalid) begin
                aw_pending <= 0; w_pending <= 0; bvalid <= 1;
                // Address 0x100 and above is an error window.
                if (aw_address >= 32'h100) begin
                    bresp <= 2'b10;
                end else begin
                    bresp <= 2'b00;
                    memory[aw_address[7:2]] <= w_data;
                end
            end
            if (bvalid && s_axil_bready) bvalid <= 0;
            if (s_axil_arvalid && s_axil_arready) begin
                ar_pending <= 1; ar_address <= s_axil_araddr;
            end
            if (ar_pending && !rvalid) begin
                ar_pending <= 0; rvalid <= 1;
                if (ar_address >= 32'h100) begin
                    rresp <= 2'b10; rdata <= 32'hdead_beef;
                end else begin
                    rresp <= 2'b00; rdata <= memory[ar_address[7:2]];
                end
            end
            if (rvalid && s_axil_rready) rvalid <= 0;
        end
    end

    task automatic send(input logic [7:0] opcode, input logic [31:0] address,
                        input logic [511:0] data, input logic [3:0] strobes);
        begin
            if (!req_ready) $fatal(1, "request refused");
            sequence_q = sequence_q + 1;
            // Block ops take exactly 64 bytes, so their address must be 64-byte
            // aligned; register ops are word aligned.
            req = {MAGIC, sequence_q, opcode, strobes, address, data};
            req_valid = 1;
            @(negedge clk);
            req_valid = 0;
        end
    endtask

    task automatic expect_response(input logic [7:0] status,
                                   input logic [511:0] data);
        integer cycles;
        begin
            cycles = 0;
            while (!rsp_valid && cycles < 4000) begin
                @(negedge clk);
                cycles = cycles + 1;
            end
            if (!rsp_valid) $fatal(1, "no response for sequence %0d", sequence_q);
            if (rsp_status !== status || rsp_data !== data || rsp_seq !== sequence_q)
                $fatal(1, "response mismatch seq=%0d status=%02x expected=%02x",
                       rsp_seq, rsp_status, status);
            @(negedge clk);
            if (rsp_valid) $fatal(1, "response was not a pulse");
        end
    endtask

    integer i;
    logic [511:0] pattern;

    initial begin
        for (i = 0; i < MEM_WORDS; i = i + 1) memory[i] = 32'h0;
        sequence_q = 0;
        repeat (4) @(negedge clk);
        rst_n = 1;
        repeat (2) @(negedge clk);

        // 1. Register write then register read.
        send(8'd2, 32'h0000_0040, 512'hdead_beef, 4'hf);
        expect_response(8'd0, 512'h0);
        send(8'd1, 32'h0000_0040, 512'h0, 4'hf);
        expect_response(8'd0, {480'h0, 32'hdead_beef});

        // 2. Block write 16 words, then block read them back.
        pattern = 512'h0;
        for (i = 0; i < 16; i = i + 1)
            pattern[i*32 +: 32] = 32'h1111_0000 + 32'(i);
        send(8'd4, 32'h0000_0040, pattern, 4'hf);
        expect_response(8'd0, 512'h0);
        // Read a different 64-byte block so the returned words must be fetched.
        send(8'd3, 32'h0000_0000, 512'h0, 4'hf);
        expect_response(8'd0, 512'h0);

        // 3. Misaligned block address -> status 4, no AXI traffic.
        send(8'd3, 32'h0000_0022, 512'h0, 4'hf);
        expect_response(8'd4, 512'h0);

        // 4. Misaligned register address -> status 4.
        send(8'd1, 32'h0000_0043, 512'h0, 4'hf);
        expect_response(8'd4, 512'h0);

        // 5. Bad magic -> status 5.
        sequence_q = sequence_q + 1;
        req = {32'h0, sequence_q, 8'd1, 4'hf, 32'h0, 512'h0};
        req_valid = 1; @(negedge clk); req_valid = 0;
        expect_response(8'd5, 512'h0);

        // 6. Downstream error on a register read -> status 7 and quarantine.
        send(8'd1, 32'h0000_0100, 512'h0, 4'hf);
        expect_response(8'd7, 512'h0);
        if (!fault) $fatal(1, "downstream error did not quarantine");
        if (req_ready) $fatal(1, "quarantined bridge accepted a request");

        // 7. Joint reset clears quarantine; then a timeout quarantines too.
        @(negedge clk); rst_n = 0;
        repeat (3) @(negedge clk); rst_n = 1;
        repeat (2) @(negedge clk);
        if (fault || !req_ready) $fatal(1, "reset did not clear quarantine");
        stall_count = TIMEOUT_CYCLES + 8;
        send(8'd1, 32'h0000_0000, 512'h0, 4'hf);
        expect_response(8'h80, 512'h0);
        if (!fault) $fatal(1, "timeout did not quarantine");

        $display("PASS JTAG_AXIL_BRIDGE sequences=%0d", sequence_q);
        $finish;
    end

    initial begin
        #4000000;
        $fatal(1, "JTAG AXI bridge watchdog");
    end
endmodule
