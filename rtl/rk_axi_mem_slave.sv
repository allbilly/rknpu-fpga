// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Strict AXI4 memory slave -> halfword memory port.
//
// Why this exists. `rk_cmac_nvdla_axi` speaks AXI4 on its memory master through
// `rk_cmac_axi_mem`: one 512-bit beat per access, `awlen=0`, `awsize=6`,
// `awburst=INCR`. Its address convention is:
//
//   * the AXI address is the **64-byte-aligned beat base**, not the byte
//     address of the datum;
//   * the datum's halfword is selected by the 2-bit lane strobe in `wstrb`
//     (writes) or by the adapter's own `mem_req_addr[5:1]` out of the returned
//     512-bit beat (reads).
//
// The board images expose a plain halfword BRAM port. Nothing in this tree
// bridged those two conventions, which is why the GEMM endpoint could not be
// put into an image.
//
// This adapter does exactly that, and nothing else:
//
//   * write: take the single full lane strobe, write that halfword at
//     `base + 2*lane`;
//   * read: fetch all 32 halfwords of the beat from `base`, assemble 512 bits,
//     and let the requesting adapter pick its lane;
//   * reject any other shape with SLVERR instead of guessing at a byte mask;
//   * never reorder, buffer or merge transactions.
//
// It is a transport leaf. It performs no arithmetic and makes no numerical
// decision.
module rk_axi_mem_slave #(
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    // Legal memory span. Any beat outside it is an error response.
    parameter logic [31:0] BASE = 32'h0000_0000,
    parameter logic [32:0] BYTES = 33'd32768
) (
    input  logic         clk,
    input  logic         rst_n,
    // Halfword memory port (this leaf drives it as a master).
    output logic         mem_req_valid,
    input  logic         mem_req_ready,
    output logic         mem_req_write,
    output logic [31:0]  mem_req_addr,
    output logic [15:0]  mem_req_wdata,
    input  logic         mem_rsp_valid,
    output logic         mem_rsp_ready,
    input  logic [15:0]  mem_rsp_rdata,
    input  logic         mem_rsp_error,
    // AXI4 slave: write-address channel.
    input  logic [3:0]   s_axi_awid,
    input  logic [30:0]  s_axi_awaddr,
    input  logic [7:0]   s_axi_awlen,
    input  logic [2:0]   s_axi_awsize,
    input  logic [1:0]   s_axi_awburst,
    input  logic         s_axi_awlock,
    input  logic [3:0]   s_axi_awcache,
    input  logic [2:0]   s_axi_awprot,
    input  logic [3:0]   s_axi_awqos,
    input  logic         s_axi_awvalid,
    output logic         s_axi_awready,
    // AXI4 slave: write-data channel.
    input  logic [511:0] s_axi_wdata,
    input  logic [63:0]  s_axi_wstrb,
    input  logic         s_axi_wlast,
    input  logic         s_axi_wvalid,
    output logic         s_axi_wready,
    // AXI4 slave: write-response channel.
    output logic [3:0]   s_axi_bid,
    output logic [1:0]   s_axi_bresp,
    output logic         s_axi_bvalid,
    input  logic         s_axi_bready,
    // AXI4 slave: read-address channel.
    input  logic [3:0]   s_axi_arid,
    input  logic [30:0]  s_axi_araddr,
    input  logic [7:0]   s_axi_arlen,
    input  logic [2:0]   s_axi_arsize,
    input  logic [1:0]   s_axi_arburst,
    input  logic         s_axi_arlock,
    input  logic [3:0]   s_axi_arcache,
    input  logic [2:0]   s_axi_arprot,
    input  logic [3:0]   s_axi_arqos,
    input  logic         s_axi_arvalid,
    output logic         s_axi_arready,
    // AXI4 slave: read-data channel.
    output logic [3:0]   s_axi_rid,
    output logic [511:0] s_axi_rdata,
    output logic [1:0]   s_axi_rresp,
    output logic         s_axi_rlast,
    output logic         s_axi_rvalid,
    input  logic         s_axi_rready
);
    localparam int unsigned BEAT_BYTES = 64;
    localparam int unsigned BEAT_HALFWORDS = BEAT_BYTES / 2;

    typedef enum logic [2:0] {
        IDLE, WRITE_MEM, WRITE_RESP, READ_MEM, READ_RESP
    } state_t;
    state_t state_q;

    logic have_aw_q, have_w_q;
    logic [30:0] awaddr_q, araddr_q;
    logic [511:0] wdata_q;
    logic [63:0] wstrb_q;
    logic aw_shape_ok_q;
    logic write_error_q, read_error_q;
    logic [31:0] stalled_q;
    // Exactly one outstanding halfword transaction. A new request is issued
    // only after the previous response has been consumed, so a memory that
    // keeps `req_ready` high while a response is in flight cannot double-fetch.
    logic issue_pending_q;

    // Single-lane decode of the latched W strobe.
    logic write_shape_ok;
    logic [4:0] write_lane_q;
    logic [4:0] fetch_index_q;
    logic [511:0] read_beat_q;

    // The only legal write strobe is exactly one full halfword lane. A partial
    // lane, two lanes, or none is malformed and gets SLVERR. Kept as one
    // explicit loop rather than a function with an output argument, which not
    // every simulator elaborates.
    always_comb begin
        integer i;
        integer count;
        logic [4:0] lane;
        count = 0;
        lane = 5'd0;
        for (i = 0; i < 32; i = i + 1) begin
            if (wstrb_q[2*i +: 2] == 2'b11) begin
                lane = i[4:0];
                count = count + 1;
            end else if (wstrb_q[2*i +: 2] != 2'b00) begin
                count = count + 2;   // partial lane: always malformed
            end
        end
        write_lane_q = lane;
        write_shape_ok = count == 1;
    end

    function automatic logic attributes_ok(
        input logic [7:0] len, input logic [2:0] size,
        input logic [1:0] burst, input logic lock
    );
        attributes_ok = (len == 8'd0) && (size == 3'd6) && (burst == 2'b01) &&
                        !lock;
    endfunction

    // A beat is legal when it is 64-byte aligned and its whole 64 bytes lie
    // inside the aperture.
    function automatic logic beat_legal(input logic [31:0] address);
        beat_legal = ((address % BEAT_BYTES) == 0) && (address >= BASE) &&
                     ({1'b0, address} + 33'(BEAT_BYTES) <=
                      {1'b0, BASE} + BYTES);
    endfunction

    wire [31:0] write_beat = {1'b0, awaddr_q};
    wire [31:0] read_beat  = {1'b0, araddr_q};
    wire [31:0] write_address = write_beat + 32'(write_lane_q) * 32'd2;
    wire [31:0] read_address = read_beat +
                              32'(fetch_index_q) * 32'd2;
    wire [15:0] write_halfword = wdata_q[16*write_lane_q +: 16];

    assign s_axi_awready = rst_n && state_q == IDLE && !have_aw_q;
    assign s_axi_wready  = rst_n && state_q == IDLE && !have_w_q;
    assign s_axi_arready = rst_n && state_q == IDLE && !have_aw_q && !have_w_q;
    assign s_axi_bvalid  = rst_n && state_q == WRITE_RESP;
    assign s_axi_rvalid  = rst_n && state_q == READ_RESP;
    assign s_axi_bid     = 4'd0;
    assign s_axi_rid     = 4'd0;
    assign s_axi_rdata   = read_beat_q;
    assign s_axi_rlast   = 1'b1;
    assign s_axi_bresp   = write_error_q ? 2'b10 : 2'b00;
    assign s_axi_rresp   = read_error_q ? 2'b10 : 2'b00;

    assign mem_req_valid = rst_n && !issue_pending_q &&
                           ((state_q == WRITE_MEM) || (state_q == READ_MEM));
    assign mem_req_write = state_q == WRITE_MEM;
    assign mem_req_addr  = state_q == WRITE_MEM ? write_address : read_address;
    assign mem_req_wdata = write_halfword;
    assign mem_rsp_ready = rst_n && ((state_q == WRITE_MEM) ||
                                     (state_q == READ_MEM));

    initial begin
        if (TIMEOUT_CYCLES == 0)
            $fatal(1, "AXI memory slave timeout must be positive");
        if (BYTES < BEAT_BYTES || BYTES % BEAT_BYTES != 0)
            $fatal(1, "AXI memory slave aperture must be a positive multiple of 64 bytes");
        if (BASE % BEAT_BYTES != 0)
            $fatal(1, "AXI memory slave base must be 64-byte aligned");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= IDLE;
            have_aw_q <= 1'b0;
            have_w_q <= 1'b0;
            awaddr_q <= 31'd0;
            araddr_q <= 31'd0;
            wdata_q <= 512'd0;
            wstrb_q <= 64'd0;
            aw_shape_ok_q <= 1'b0;
            write_error_q <= 1'b0;
            read_error_q <= 1'b0;
            fetch_index_q <= 5'd0;
            read_beat_q <= 512'd0;
            issue_pending_q <= 1'b0;
            stalled_q <= 32'd0;
        end else begin
            if (mem_rsp_valid || (mem_req_valid && mem_req_ready) ||
                (s_axi_bvalid && s_axi_bready) || (s_axi_rvalid && s_axi_rready))
                stalled_q <= 32'd0;
            else if (state_q != IDLE)
                stalled_q <= stalled_q + 1'b1;

            case (state_q)
                IDLE: begin
                    if (s_axi_awvalid && s_axi_awready) begin
                        have_aw_q <= 1'b1;
                        awaddr_q <= s_axi_awaddr;
                        aw_shape_ok_q <= attributes_ok(s_axi_awlen, s_axi_awsize,
                                                       s_axi_awburst, s_axi_awlock) &&
                                         s_axi_awid == 4'd0;
                    end
                    if (s_axi_wvalid && s_axi_wready) begin
                        have_w_q <= 1'b1;
                        wdata_q <= s_axi_wdata;
                        wstrb_q <= s_axi_wstrb;
                    end
                    if (s_axi_arvalid && s_axi_arready) begin
                        araddr_q <= s_axi_araddr;
                        if (!attributes_ok(s_axi_arlen, s_axi_arsize,
                                           s_axi_arburst, s_axi_arlock) ||
                            !beat_legal({1'b0, s_axi_araddr}) ||
                            s_axi_arid != 4'd0) begin
                            read_error_q <= 1'b1;
                            state_q <= READ_RESP;
                        end else begin
                            read_error_q <= 1'b0;
                            fetch_index_q <= 5'd0;
                            read_beat_q <= 512'd0;
                            issue_pending_q <= 1'b0;
                            state_q <= READ_MEM;
                        end
                    end
                    if (have_aw_q && have_w_q) begin
                        // The write shape was captured on the AW/W beats; the
                        // live bus may already describe the next transfer.
                        if (!s_axi_wlast || !beat_legal(write_beat) ||
                            !aw_shape_ok_q || !write_shape_ok) begin
                            write_error_q <= 1'b1;
                            state_q <= WRITE_RESP;
                        end else begin
                            write_error_q <= 1'b0;
                            issue_pending_q <= 1'b0;
                            state_q <= WRITE_MEM;
                        end
                        have_aw_q <= 1'b0;
                        have_w_q <= 1'b0;
                    end
                end

                WRITE_MEM: begin
                    if (mem_req_valid && mem_req_ready) issue_pending_q <= 1'b1;
                    if (issue_pending_q && mem_rsp_valid) begin
                        issue_pending_q <= 1'b0;
                        write_error_q <= mem_rsp_error;
                        state_q <= WRITE_RESP;
                    end
                end

                WRITE_RESP: if (s_axi_bready) state_q <= IDLE;

                READ_MEM: begin
                    if (mem_req_valid && mem_req_ready) issue_pending_q <= 1'b1;
                    if (issue_pending_q && mem_rsp_valid) begin
                        issue_pending_q <= 1'b0;
                        if (mem_rsp_error || ((^mem_rsp_rdata) === 1'bx)) begin
                            read_error_q <= 1'b1;
                            state_q <= READ_RESP;
                        end else begin
                            read_beat_q[16*fetch_index_q +: 16] <= mem_rsp_rdata;
                            if (fetch_index_q == BEAT_HALFWORDS - 1) begin
                                fetch_index_q <= 5'd0;
                                state_q <= READ_RESP;
                            end else begin
                                fetch_index_q <= fetch_index_q + 1'b1;
                            end
                        end
                    end
                end

                READ_RESP: if (s_axi_rready) state_q <= IDLE;

                default: state_q <= IDLE;
            endcase

            if (state_q != IDLE && stalled_q >= TIMEOUT_CYCLES - 1) begin
                // A stalled memory port is a fault: the platform resets this
                // leaf together with the engine and the memory.
                write_error_q <= 1'b1;
                read_error_q <= 1'b1;
                state_q <= IDLE;
            end
        end
    end
endmodule
