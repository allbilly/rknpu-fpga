// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One physical ordinary-RAM read per host READ64, unpacked into halfwords.
// DMA and writes always use the unchanged legacy adapter; no CPU path.
module rk_axi_mem_read_snapshot (
    input logic clk, rst_n,
    input logic host_read_scope, request_is_host, invalidate_snapshot,
    input logic [15:0] host_read_epoch,
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

    typedef enum logic [1:0] {IDLE, FORWARD, SNAPSHOT_RESPONSE, FAULT} state_t;
    state_t state;
    logic legacy_req_valid,legacy_req_ready,legacy_rsp_valid,legacy_rsp_ready,legacy_rsp_error;
    logic [15:0] legacy_rsp_rdata;
    logic snapshot_valid,forward_host_read,snapshot_error;
    logic [511:0] snapshot_data;
    logic [24:0] snapshot_line,forward_line;
    logic [15:0] snapshot_epoch,forward_epoch,snapshot_word;
    logic snapshot_hit;
    wire accept=mem_req_valid&&mem_req_ready;

    // Unknown controls/address comparisons cannot select buffered data.
    always @* begin
        snapshot_hit=0;
        if(snapshot_valid===1'b1 && host_read_scope===1'b1 && request_is_host===1'b1 &&
           invalidate_snapshot===1'b0 && mem_req_write===1'b0 &&
           mem_req_addr[31]===1'b0 && mem_req_addr[0]===1'b0 &&
           snapshot_line==mem_req_addr[30:6] && snapshot_epoch==host_read_epoch &&
           legacy_req_ready===1'b1 && m_axi_rvalid===1'b0 && m_axi_bvalid===1'b0)
            snapshot_hit=1;
    end
    assign mem_req_ready=rst_n && state==IDLE && legacy_req_ready;
    assign legacy_req_valid=state==IDLE && mem_req_valid && !snapshot_hit;
    assign legacy_rsp_ready=state==FORWARD && mem_rsp_ready;
    assign mem_rsp_valid=rst_n && ((state==FORWARD && legacy_rsp_valid) || state==SNAPSHOT_RESPONSE);
    assign mem_rsp_rdata=state==SNAPSHOT_RESPONSE?snapshot_word:legacy_rsp_rdata;
    assign mem_rsp_error=state==SNAPSHOT_RESPONSE?snapshot_error:legacy_rsp_error;

    // The original adapter retains all DMA/write/error/AXI handshakes.
    rk_axi_mem legacy (
        .mem_req_valid(legacy_req_valid),.mem_req_ready(legacy_req_ready),
        .mem_rsp_valid(legacy_rsp_valid),.mem_rsp_ready(legacy_rsp_ready),
        .mem_rsp_rdata(legacy_rsp_rdata),.mem_rsp_error(legacy_rsp_error),.*
    );

    always_ff @(posedge clk) begin
        if(!rst_n)begin
            state<=IDLE;snapshot_valid<=0;snapshot_line<=0;snapshot_epoch<=0;
            forward_line<=0;forward_epoch<=0;forward_host_read<=0;
            snapshot_word<=0;snapshot_error<=0;
            // snapshot_data is deliberately not reset; validity guards it.
        end else begin
            if(host_read_scope!==1'b1 || invalidate_snapshot!==1'b0 ||
               host_read_epoch!=snapshot_epoch ||
               ((m_axi_rvalid||m_axi_bvalid)&&state!=FORWARD))snapshot_valid<=0;
            if(state==FORWARD && forward_host_read && host_read_scope===1'b1 &&
               invalidate_snapshot===1'b0 && host_read_epoch==forward_epoch &&
               m_axi_rvalid && m_axi_rready && m_axi_rid===4'b0 &&
               m_axi_rresp===2'b0 && m_axi_rlast===1'b1 && m_axi_bvalid===1'b0)begin
                snapshot_data<=m_axi_rdata;snapshot_line<=forward_line;
                snapshot_epoch<=forward_epoch;snapshot_valid<=1;
            end
            case(state)
                IDLE:if(accept)begin
                    if(snapshot_hit)begin
                        snapshot_word<=snapshot_data[16*mem_req_addr[5:1]+:16];
                        snapshot_error<=0;state<=SNAPSHOT_RESPONSE;
                    end else begin
                        snapshot_valid<=0;
                        forward_host_read<=host_read_scope===1'b1 && request_is_host===1'b1 &&
                            mem_req_write===1'b0 && mem_req_addr[31]===1'b0 && mem_req_addr[0]===1'b0;
                        forward_line<=mem_req_addr[30:6];forward_epoch<=host_read_epoch;
                        state<=FORWARD;
                    end
                end
                FORWARD:if(legacy_rsp_valid&&mem_rsp_ready)begin
                    if(legacy_rsp_error)snapshot_valid<=0;
                    state<=IDLE;
                end
                SNAPSHOT_RESPONSE:if(mem_rsp_ready)begin
                    if(snapshot_error)state<=FAULT;else state<=IDLE;
                end
                FAULT:begin end
                default:begin snapshot_valid<=0;snapshot_error<=1;state<=SNAPSHOT_RESPONSE;end
            endcase
        end
    end
endmodule
