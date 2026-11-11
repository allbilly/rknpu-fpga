// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Unit bench for rk_axi_mem_slave: the AXI4 -> halfword bridge.
//
// It drives exactly the access shape `rk_cmac_axi_mem` emits:
//
//   * `awlen=0`, `awsize=6`, `awburst=INCR`
//   * `awaddr` is the 64-byte-aligned beat base
//   * the halfword to write is selected by a single 2-bit strobe lane
//   * a read returns the whole 512-bit beat from `araddr`
//
// Checks:
//   1. write lands in the right halfword of the right word;
//   2. a read returns 32 halfwords and the datum is in the requested beat;
//   3. an address outside the aperture is SLVERR, with no memory access;
//   4. a malformed write (partial lane) is SLVERR, with no memory access;
//   5. a malformed read (multi-beat, or byte-sized) is SLVERR, no access.
module tb_axi_mem_slave;
    localparam logic [31:0] BASE = 32'h0000_0000;
    localparam int unsigned BYTES = 32768;
    localparam int unsigned BEAT_BYTES = 64;

    logic clk = 0;
    always #5 clk = ~clk;

    logic rst_n = 0;

    logic [3:0] s_axi_awid = 0;
    logic [30:0] s_axi_awaddr = 0;
    logic [7:0] s_axi_awlen = 0;
    logic [2:0] s_axi_awsize = 6;
    logic [1:0] s_axi_awburst = 1;
    logic s_axi_awlock = 0;
    logic [3:0] s_axi_awcache = 0;
    logic [2:0] s_axi_awprot = 0;
    logic [3:0] s_axi_awqos = 0;
    logic s_axi_awvalid = 0;
    wire s_axi_awready;
    logic [511:0] s_axi_wdata = 0;
    logic [63:0] s_axi_wstrb = 0;
    logic s_axi_wlast = 1;
    logic s_axi_wvalid = 0;
    wire s_axi_wready;
    wire [3:0] s_axi_bid;
    wire [1:0] s_axi_bresp;
    wire s_axi_bvalid;
    logic s_axi_bready = 0;
    logic [3:0] s_axi_arid = 0;
    logic [30:0] s_axi_araddr = 0;
    logic [7:0] s_axi_arlen = 0;
    logic [2:0] s_axi_arsize = 6;
    logic [1:0] s_axi_arburst = 1;
    logic s_axi_arlock = 0;
    logic [3:0] s_axi_arcache = 0;
    logic [2:0] s_axi_arprot = 0;
    logic [3:0] s_axi_arqos = 0;
    logic s_axi_arvalid = 0;
    wire s_axi_arready;
    wire [3:0] s_axi_rid;
    wire [511:0] s_axi_rdata;
    wire [1:0] s_axi_rresp;
    wire s_axi_rlast;
    wire s_axi_rvalid;
    logic s_axi_rready = 0;

    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_req_ready, mem_rsp_valid, mem_rsp_error;
    logic [15:0] mem_rsp_rdata;

    logic [15:0] memory [0:BYTES/2-1];
    integer accesses;
    integer writes_seen;

    assign mem_req_ready = rst_n && !mem_rsp_valid;

    rk_axi_mem_slave #(
        .TIMEOUT_CYCLES(256), .BASE(BASE), .BYTES(33'(BYTES))
    ) dut (
        .clk, .rst_n,
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata,
        .mem_rsp_error,
        .s_axi_awid, .s_axi_awaddr, .s_axi_awlen, .s_axi_awsize,
        .s_axi_awburst, .s_axi_awlock, .s_axi_awcache, .s_axi_awprot,
        .s_axi_awqos, .s_axi_awvalid, .s_axi_awready,
        .s_axi_wdata, .s_axi_wstrb, .s_axi_wlast, .s_axi_wvalid,
        .s_axi_wready,
        .s_axi_bid, .s_axi_bresp, .s_axi_bvalid, .s_axi_bready,
        .s_axi_arid, .s_axi_araddr, .s_axi_arlen, .s_axi_arsize,
        .s_axi_arburst, .s_axi_arlock, .s_axi_arcache, .s_axi_arprot,
        .s_axi_arqos, .s_axi_arvalid, .s_axi_arready,
        .s_axi_rid, .s_axi_rdata, .s_axi_rresp, .s_axi_rlast,
        .s_axi_rvalid, .s_axi_rready
    );

    // Memory model: one outstanding halfword, one-cycle response, and an
    // explicit counter so a malformed request that never reaches memory is
    // detectable.
    logic pending;
    logic [31:0] pending_addr;
    logic [15:0] pending_data;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            pending <= 1'b0;
            mem_rsp_valid <= 1'b0;
            mem_rsp_error <= 1'b0;
            pending_addr <= 32'd0;
            pending_data <= 16'd0;
            accesses <= 0;
            writes_seen <= 0;
        end else begin
            if (mem_req_valid && mem_req_ready) begin
                pending <= 1'b1;
                pending_addr <= mem_req_addr;
                pending_data <= memory[mem_req_addr >> 1];
                accesses <= accesses + 1;
                if (mem_req_write) begin
                    memory[mem_req_addr >> 1] <= mem_req_wdata;
                    writes_seen <= writes_seen + 1;
                end
            end
            if (pending && !mem_rsp_valid) begin
                pending <= 1'b0;
                mem_rsp_valid <= 1'b1;
                mem_rsp_error <= (pending_addr < BASE) ||
                                 (pending_addr + 1 >= BASE + BYTES) ||
                                 pending_addr[0];
                mem_rsp_rdata <= pending_data;
            end
            if (mem_rsp_valid && mem_rsp_ready) begin
                mem_rsp_valid <= 1'b0;
                mem_rsp_error <= 1'b0;
            end
        end
    end

    task automatic axi_write(input logic [30:0] beat, input logic [4:0] lane,
                             input logic [15:0] value, input logic [63:0] strobe,
                             input logic [7:0] len, input logic [2:0] size,
                             input logic [1:0] burst, output logic [1:0] resp);
        begin
            @(negedge clk);
            s_axi_awaddr = beat; s_axi_awlen = len; s_axi_awsize = size;
            s_axi_awburst = burst; s_axi_awvalid = 1;
            s_axi_wdata = 512'd0; s_axi_wdata[16*lane +: 16] = value;
            s_axi_wstrb = strobe; s_axi_wlast = 1; s_axi_wvalid = 1;
            do @(posedge clk); while (!s_axi_awready || !s_axi_wready);
            @(negedge clk);
            s_axi_awvalid = 0; s_axi_wvalid = 0;
            s_axi_bready = 1;
            do @(posedge clk); while (!s_axi_bvalid);
            resp = s_axi_bresp;
            @(negedge clk);
            s_axi_bready = 0;
        end
    endtask

    task automatic axi_read(input logic [30:0] beat, input logic [7:0] len,
                            input logic [2:0] size, input logic [1:0] burst,
                            output logic [1:0] resp, output logic [511:0] data);
        begin
            @(negedge clk);
            s_axi_araddr = beat; s_axi_arlen = len; s_axi_arsize = size;
            s_axi_arburst = burst; s_axi_arvalid = 1;
            do @(posedge clk); while (!s_axi_arready);
            @(negedge clk);
            s_axi_arvalid = 0;
            s_axi_rready = 1;
            do @(posedge clk); while (!s_axi_rvalid);
            resp = s_axi_rresp;
            data = s_axi_rdata;
            @(negedge clk);
            s_axi_rready = 0;
        end
    endtask

    integer i, access_before;
    logic [1:0] resp;
    logic [511:0] beat_data;

    initial begin
        for (i = 0; i < BYTES/2; i = i + 1) memory[i] = 16'd0;
        repeat (4) @(negedge clk);
        rst_n = 1;
        repeat (2) @(negedge clk);

        // 1. Write halfword lane 3 of beat 0x0100 -> address 0x0106.
        resp = 0;
        axi_write(31'h0000_0100, 5'd3, 16'hbeef, 64'h0000_0000_0000_00c0,
                  8'd0, 3'd6, 2'b01, resp);
        if (resp != 2'b00) $fatal(1, "legal write got SLVERR");
        if (memory[32'h0083] !== 16'hbeef)
            $fatal(1, "halfword write landed wrong: %04x", memory[32'h0083]);
        if (memory[32'h0082] !== 16'h0000 || memory[32'h0084] !== 16'h0000)
            $fatal(1, "halfword write touched a neighbour");

        // 2. Read beat 0x0100 back: 32 halfwords fetched, the written lane
        //    visible at bits [63:48].
        access_before = accesses;
        resp = 0;
        beat_data = 0;
        axi_read(31'h0000_0100, 8'd0, 3'd6, 2'b01, resp, beat_data);
        if (resp != 2'b00) $fatal(1, "legal read got SLVERR");
        if (accesses != access_before + 32)
            $fatal(1, "legal read fetched %0d halfwords, expected 32",
                   accesses - access_before);
        if (beat_data[48 +: 16] !== 16'hbeef)
            $fatal(1, "read beat lost the written halfword: %04x",
                   beat_data[48 +: 16]);

        // 3. Out-of-aperture beat: SLVERR, no memory access.
        access_before = accesses;
        resp = 0;
        axi_write(31'h0000_8000, 5'd0, 16'h1234, 64'h0000_0000_0000_0003,
                  8'd0, 3'd6, 2'b01, resp);
        if (resp != 2'b10) $fatal(1, "out-of-aperture write not SLVERR (%b)", resp);
        if (accesses != access_before) $fatal(1, "out-of-aperture write reached memory");
        access_before = accesses;
        resp = 0;
        beat_data = 0;
        axi_read(31'h0000_8000, 8'd0, 3'd6, 2'b01, resp, beat_data);
        if (resp != 2'b10) $fatal(1, "out-of-aperture read not SLVERR (%b)", resp);
        if (accesses != access_before) $fatal(1, "out-of-aperture read reached memory");

        // 4. Partial-lane write: SLVERR, no memory access.
        access_before = accesses;
        resp = 0;
        axi_write(31'h0000_0100, 5'd0, 16'h5678, 64'h0000_0000_0000_0001,
                  8'd0, 3'd6, 2'b01, resp);
        if (resp != 2'b10) $fatal(1, "partial-lane write not SLVERR (%b)", resp);
        if (accesses != access_before) $fatal(1, "partial-lane write reached memory");

        // 5. Multi-beat read and byte-sized read: SLVERR, no access.
        access_before = accesses;
        resp = 0;
        beat_data = 0;
        axi_read(31'h0000_0100, 8'd1, 3'd6, 2'b01, resp, beat_data);
        if (resp != 2'b10) $fatal(1, "multi-beat read not SLVERR (%b)", resp);
        if (accesses != access_before) $fatal(1, "multi-beat read reached memory");
        access_before = accesses;
        resp = 0;
        beat_data = 0;
        axi_read(31'h0000_0100, 8'd0, 3'd0, 2'b01, resp, beat_data);
        if (resp != 2'b10) $fatal(1, "byte-sized read not SLVERR (%b)", resp);
        if (accesses != access_before) $fatal(1, "byte-sized read reached memory");

        // 6. Last beat of the aperture is still legal, and a misaligned beat
        //    base is not.
        resp = 0;
        axi_write(31'h0000_7fc0, 5'd31, 16'hcafe, 64'hc000_0000_0000_0000,
                  8'd0, 3'd6, 2'b01, resp);
        if (resp != 2'b00) $fatal(1, "last aperture beat rejected");
        if (memory[32'h3fff] !== 16'hcafe) $fatal(1, "last halfword not written");
        access_before = accesses;
        resp = 0;
        axi_write(31'h0000_7f00, 5'd0, 16'hdead, 64'h0000_0000_0000_0003,
                  8'd0, 3'd6, 2'b01, resp);
        if (resp != 2'b00) $fatal(1, "aligned in-aperture beat rejected");
        access_before = accesses;
        resp = 0;
        axi_write(31'h0000_7e02, 5'd0, 16'hdead, 64'h0000_0000_0000_0003,
                  8'd0, 3'd6, 2'b01, resp);
        if (resp != 2'b10) $fatal(1, "misaligned beat base was accepted (%b)", resp);
        if (accesses != access_before) $fatal(1, "misaligned beat base reached memory");

        $display("PASS AXI_MEM_SLAVE accesses=%0d writes=%0d", accesses, writes_seen);
        $finish;
    end

    initial begin
        #400000;
        $fatal(1, "AXI memory slave watchdog");
    end
endmodule
