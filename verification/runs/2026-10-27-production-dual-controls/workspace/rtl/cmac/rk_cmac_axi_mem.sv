// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Staged CMAC copy of rk_axi_mem with joint asynchronous reset assertion.
// Platform must synchronize reset deassertion to clk.
// One halfword request -> one full-width AXI beat. Intended for ordinary RAM,
// never side-effecting MMIO. Reset with the engine AND downstream AXI fabric.
module rk_cmac_axi_mem (
    input logic clk, rst_n,
    input logic mem_req_valid,
    output logic mem_req_ready,
    input logic mem_req_write,
    input logic [31:0] mem_req_addr,
    input logic [15:0] mem_req_wdata,
    output logic mem_rsp_valid,
    input logic mem_rsp_ready,
    output logic [15:0] mem_rsp_rdata,
    output logic mem_rsp_error,
    output logic [3:0] m_axi_awid, m_axi_arid,
    output logic [30:0] m_axi_awaddr, m_axi_araddr,
    output logic [7:0] m_axi_awlen, m_axi_arlen,
    output logic [2:0] m_axi_awsize, m_axi_arsize,
    output logic [1:0] m_axi_awburst, m_axi_arburst,
    output logic m_axi_awlock, m_axi_arlock,
    output logic [3:0] m_axi_awcache, m_axi_arcache,
    output logic [2:0] m_axi_awprot, m_axi_arprot,
    output logic [3:0] m_axi_awqos, m_axi_arqos,
    output logic m_axi_awvalid,
    input logic m_axi_awready,
    output logic [511:0] m_axi_wdata,
    output logic [63:0] m_axi_wstrb,
    output logic m_axi_wlast, m_axi_wvalid,
    input logic m_axi_wready,
    input logic [3:0] m_axi_bid,
    input logic [1:0] m_axi_bresp,
    input logic m_axi_bvalid,
    output logic m_axi_bready,
    output logic m_axi_arvalid,
    input logic m_axi_arready,
    input logic [3:0] m_axi_rid,
    input logic [511:0] m_axi_rdata,
    input logic [1:0] m_axi_rresp,
    input logic m_axi_rlast, m_axi_rvalid,
    output logic m_axi_rready
);
    typedef enum logic [2:0] {IDLE, WRITE, WRITE_ACK, READ_ADDR, READ_DATA, RESPONSE, FAULT} state_t;
    state_t state;
    logic [30:0] address;
    logic [4:0] lane;
    logic [15:0] write_data;
    logic aw_pending, w_pending;

    assign mem_req_ready = rst_n && state == IDLE;
    assign mem_rsp_valid = rst_n && state == RESPONSE;
    assign m_axi_awid = 0;
    assign m_axi_arid = 0;
    assign m_axi_awaddr = address;
    assign m_axi_araddr = address;
    assign m_axi_awlen = 0;
    assign m_axi_arlen = 0;
    assign m_axi_awsize = 3'd6;
    assign m_axi_arsize = 3'd6;
    assign m_axi_awburst = 2'b01;
    assign m_axi_arburst = 2'b01;
    assign m_axi_awlock = 0;
    assign m_axi_arlock = 0;
    assign m_axi_awcache = 0;
    assign m_axi_arcache = 0;
    assign m_axi_awprot = 0;
    assign m_axi_arprot = 0;
    assign m_axi_awqos = 0;
    assign m_axi_arqos = 0;
    assign m_axi_awvalid = rst_n && state == WRITE && aw_pending;
    assign m_axi_wvalid = rst_n && state == WRITE && w_pending;
    assign m_axi_wlast = 1;
    assign m_axi_bready = rst_n && state == WRITE_ACK;
    assign m_axi_arvalid = rst_n && state == READ_ADDR;
    assign m_axi_rready = rst_n && state == READ_DATA;
    always_comb begin
        m_axi_wdata = 0;
        m_axi_wstrb = 0;
        m_axi_wdata[16*lane +: 16] = write_data;
        m_axi_wstrb[2*lane +: 2] = 2'b11;
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; address <= 0; lane <= 0; write_data <= 0;
            aw_pending <= 0; w_pending <= 0;
            mem_rsp_rdata <= 0; mem_rsp_error <= 0;
        end else case (state)
            IDLE: if (mem_req_valid) begin
                mem_rsp_rdata <= 0;
                // Reject rather than truncate a high or odd device address.
                if (mem_req_addr[31] || mem_req_addr[0]) begin
                    mem_rsp_error <= 1; state <= RESPONSE;
                end else begin
                    address <= {mem_req_addr[30:6], 6'b0};
                    lane <= mem_req_addr[5:1]; write_data <= mem_req_wdata;
                    mem_rsp_error <= 0;
                    if (mem_req_write) begin
                        aw_pending <= 1; w_pending <= 1; state <= WRITE;
                    end else state <= READ_ADDR;
                end
            end
            WRITE: begin
                if (m_axi_awready) aw_pending <= 0;
                if (m_axi_wready) w_pending <= 0;
                if ((!aw_pending || m_axi_awready) && (!w_pending || m_axi_wready)) state <= WRITE_ACK;
            end
            WRITE_ACK: if (m_axi_bvalid) begin
                mem_rsp_error <= m_axi_bresp != 0 || m_axi_bid != 0;
                state <= RESPONSE;
            end
            READ_ADDR: if (m_axi_arready) state <= READ_DATA;
            READ_DATA: if (m_axi_rvalid) begin
                mem_rsp_error <= m_axi_rresp != 0 || m_axi_rid != 0 || !m_axi_rlast;
                mem_rsp_rdata <= m_axi_rdata[16*lane +: 16];
                state <= RESPONSE;
            end
            RESPONSE: if (mem_rsp_ready) begin
                if (mem_rsp_error) state <= FAULT;
                else state <= IDLE;
            end
            FAULT: begin end
            default: begin mem_rsp_error <= 1; state <= RESPONSE; end
        endcase
    end
endmodule
