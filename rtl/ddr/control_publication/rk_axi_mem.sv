// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One halfword request -> one full-width AXI beat. Intended for ordinary RAM,
// never side-effecting MMIO. Reset with the engine AND downstream AXI fabric.
module rk_axi_mem (
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
    // Keep request permission on single-bit publication, not every private
    // state/address/data FF enable. Logical state/payload remain the original
    // values on every clock, including while AXI VALID is low.
    (* fsm_encoding = "none" *) state_t phase_payload;
    logic transaction_active;
    wire [2:0] state=transaction_active ? phase_payload : IDLE;
    logic [51:0] request_payload[0:1];
    logic request_select;
    wire [51:0] published_request=request_payload[request_select];
    wire [30:0] address=published_request[51:21];
    wire [4:0] lane=published_request[20:16];
    wire [15:0] write_data=published_request[15:0];
    logic [15:0] response_data_payload;
    logic response_data_live;
    assign mem_rsp_rdata=response_data_live ? response_data_payload : 16'd0;
    state_t idle_phase;
    always_comb begin
        if(mem_req_addr[31]||mem_req_addr[0]) idle_phase=RESPONSE;
        else if(mem_req_write) idle_phase=WRITE;
        else idle_phase=READ_ADDR;
    end
    always_ff @(posedge clk)begin
        if(!rst_n)begin
            request_payload[0]<=0;request_payload[1]<=0;request_select<=0;
        end else if(!transaction_active)begin
            // Use the original procedural-if truth convention for X/Z.
            if(mem_req_addr[31]||mem_req_addr[0])begin end
            else begin
                request_payload[!request_select]<={mem_req_addr[30:6],6'b0,mem_req_addr[5:1],mem_req_wdata};
                if(mem_req_valid)request_select<=!request_select;
            end
        end
    end
    always_ff @(posedge clk)begin
        if(!rst_n)begin response_data_payload<=0;response_data_live<=0;end
        else if(!transaction_active&&mem_req_valid) response_data_live<=0;
        else if(transaction_active&&phase_payload==READ_DATA&&m_axi_rvalid)begin
            response_data_payload<=m_axi_rdata[16*lane+:16];response_data_live<=1;
        end
    end
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
    always_ff @(posedge clk) begin
        if(!rst_n)begin
            transaction_active<=0;phase_payload<=IDLE;
            aw_pending<=0;w_pending<=0;mem_rsp_error<=0;
        end else if(!transaction_active)begin
            phase_payload<=idle_phase;
            if(mem_req_valid)begin
                transaction_active<=1;
                if(mem_req_addr[31]||mem_req_addr[0])mem_rsp_error<=1;
                else begin
                    mem_rsp_error<=0;
                    if(mem_req_write)begin aw_pending<=1;w_pending<=1;end
                end
            end
        end else case(phase_payload)
            WRITE:begin
                if(m_axi_awready)aw_pending<=0;
                if(m_axi_wready)w_pending<=0;
                if((!aw_pending||m_axi_awready)&&(!w_pending||m_axi_wready))phase_payload<=WRITE_ACK;
            end
            WRITE_ACK:if(m_axi_bvalid)begin
                mem_rsp_error<=m_axi_bresp!=0||m_axi_bid!=0;phase_payload<=RESPONSE;
            end
            READ_ADDR:if(m_axi_arready)phase_payload<=READ_DATA;
            READ_DATA:if(m_axi_rvalid)begin
                mem_rsp_error<=m_axi_rresp!=0||m_axi_rid!=0||!m_axi_rlast;phase_payload<=RESPONSE;
            end
            RESPONSE:if(mem_rsp_ready)begin
                if(mem_rsp_error)phase_payload<=FAULT;
                else begin transaction_active<=0;phase_payload<=IDLE;end
            end
            FAULT:begin end
            default:begin mem_rsp_error<=1;phase_payload<=RESPONSE;end
        endcase
    end
endmodule
