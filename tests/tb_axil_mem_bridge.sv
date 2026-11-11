// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Unit test for rk_axil_mem_bridge: one 32-bit AXI access becomes two halfword
// memory transactions, and every illegal access is an explicit error.
module tb_axil_mem_bridge;
    localparam logic [31:0] BASE = 32'h00000000;
    localparam int unsigned MEM_BYTES = 256;

    logic clk = 0;
    always #5 clk = ~clk;

    logic rst_n = 0, host_enable = 1;
    wire busy;
    `include "tests/axil_host.svh"

    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_req_ready, mem_rsp_valid, mem_rsp_error;
    logic [15:0] mem_rsp_rdata;

    logic [15:0] storage [0:MEM_BYTES/2-1];
    logic pending;
    logic [15:0] pending_data;
    integer responses;

    rk_axil_mem_bridge #(.BASE(BASE), .BYTES(MEM_BYTES)) dut (
        .clk, .rst_n, .host_enable, .busy,
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready,
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata,
        .mem_rsp_error
    );

    // Memory model: one-cycle latency, no backpressure.
    assign mem_req_ready = rst_n && !pending;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            pending <= 1'b0;
            mem_rsp_valid <= 1'b0;
            mem_rsp_error <= 1'b0;
            mem_rsp_rdata <= 16'd0;
            responses <= 0;
        end else begin
            if (mem_req_valid && mem_req_ready) begin
                pending <= 1'b1;
                pending_data <= storage[mem_req_addr[7:1]];
                if (mem_req_write) storage[mem_req_addr[7:1]] <= mem_req_wdata;
            end
            if (pending && !mem_rsp_valid) begin
                pending <= 1'b0;
                mem_rsp_valid <= 1'b1;
                mem_rsp_rdata <= pending_data;
                mem_rsp_error <= 1'b0;
                responses <= responses + 1;
            end
            if (mem_rsp_valid && mem_rsp_ready) begin
                mem_rsp_valid <= 1'b0;
                mem_rsp_error <= 1'b0;
            end
        end
    end

    integer i;
    logic [31:0] value;

    initial begin
        for (i = 0; i < MEM_BYTES / 2; i = i + 1) storage[i] = 16'h0;
        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        // 1. Write 32 bits to offset 0x40 and read it back.
        host_write(32'h40, 32'hdead_beef);
        host_read(32'h40, value);
        if (value !== 32'hdead_beef)
            $fatal(1, "round trip got %08x", value);
        if (responses != 4)
            $fatal(1, "expected 4 halfword transactions, saw %0d", responses);

        // 2. Partial strobe must be rejected and must not touch memory.
        host_write(32'h44, 32'h1234_5678, 2'b10, 0, 4'b0011);
        host_read(32'h44, value);
        if (value !== 32'h0) $fatal(1, "partial write reached memory: %08x", value);

        // 3. Unaligned address must be rejected.
        host_read(32'h42, value, 2'b10);
        host_write(32'h42, 32'hffff_ffff, 2'b10);

        // 4. Out-of-range address must be rejected.
        host_read(32'h100, value, 2'b10);
        host_write(32'h100, 32'hffff_ffff, 2'b10);

        // 5. Protected access must be rejected.
        host_read(32'h40, value, 2'b10, 3'b001);
        host_write(32'h40, 32'h0, 2'b10, 0, 4'hf, 3'b001);

        // 6. W before AW must still work (the shared host tasks exercise this).
        host_write(32'h48, 32'h0bad_f00d, 0, 2);
        host_read(32'h48, value);
        if (value !== 32'h0bad_f00d)
            $fatal(1, "W-before-AW round trip got %08x", value);

        // 7. AW before W must still work.
        host_write(32'h4c, 32'hc0de_1234, 0, 1);
        host_read(32'h4c, value);
        if (value !== 32'hc0de_1234)
            $fatal(1, "AW-before-W round trip got %08x", value);

        // 8. With host_enable low the bridge must withdraw ready and stall.
        host_enable = 0;
        @(negedge clk); s_axil_araddr = 32'h40; s_axil_arvalid = 1;
        repeat (10) begin
            @(negedge clk);
            if (s_axil_arready !== 1'b0)
                $fatal(1, "arready high while disabled");
            if (s_axil_rvalid !== 1'b0)
                $fatal(1, "rvalid high while disabled");
        end
        s_axil_arvalid = 0;
        host_enable = 1;
        @(negedge clk);

        $display("PASS AXI_MEM_BRIDGE responses=%0d", responses);
        $finish;
    end

    initial begin
        #200000;
        $fatal(1, "bridge watchdog");
    end
endmodule
