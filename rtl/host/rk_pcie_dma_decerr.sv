// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Unsupported DMA plane: always DECERR; no DDR/NPU side effects.
module rk_pcie_dma_decerr (
    input wire clk,rst_n,
    output logic protocol_fault,
    output wire s_axi_awready,
    output wire s_axi_wready,
    output logic [3 : 0] s_axi_bid,
    output wire [1 : 0] s_axi_bresp,
    output logic s_axi_bvalid,
    output wire s_axi_arready,
    output logic [3 : 0] s_axi_rid,
    output wire [127 : 0] s_axi_rdata,
    output wire [1 : 0] s_axi_rresp,
    output logic s_axi_rlast,
    output logic s_axi_rvalid,
    input wire [3 : 0] s_axi_awid,
    input wire [63 : 0] s_axi_awaddr,
    input wire [7 : 0] s_axi_awlen,
    input wire [2 : 0] s_axi_awsize,
    input wire [1 : 0] s_axi_awburst,
    input wire [2 : 0] s_axi_awprot,
    input wire s_axi_awvalid,
    input wire s_axi_awlock,
    input wire [3 : 0] s_axi_awcache,
    input wire [127 : 0] s_axi_wdata,
    input wire [15 : 0] s_axi_wstrb,
    input wire s_axi_wlast,
    input wire s_axi_wvalid,
    input wire s_axi_bready,
    input wire [3 : 0] s_axi_arid,
    input wire [63 : 0] s_axi_araddr,
    input wire [7 : 0] s_axi_arlen,
    input wire [2 : 0] s_axi_arsize,
    input wire [1 : 0] s_axi_arburst,
    input wire [2 : 0] s_axi_arprot,
    input wire s_axi_arvalid,
    input wire s_axi_arlock,
    input wire [3 : 0] s_axi_arcache,
    input wire s_axi_rready
);
    logic write_active;
    logic [3:0] write_id;
    logic [8:0] write_left,read_left;
    wire aw_known=(^{s_axi_awid,s_axi_awlen})!==1'bx;
    wire ar_known=(^{s_axi_arid,s_axi_arlen})!==1'bx;
    // Metadata/data are unsupported at every address: a consumed transaction
    // returns an error, never success or a side effect in another address map.
    wire unused_rejected_payload=^{s_axi_awaddr,s_axi_awsize,s_axi_awburst,s_axi_awprot,
        s_axi_awlock,s_axi_awcache,s_axi_wdata,s_axi_wstrb,s_axi_araddr,
        s_axi_arsize,s_axi_arburst,s_axi_arprot,s_axi_arlock,s_axi_arcache};
    assign s_axi_awready=rst_n&&!protocol_fault&&!write_active&&!s_axi_bvalid&&aw_known;
    // A previously accepted burst keeps draining after a protocol fault.
    assign s_axi_wready=rst_n&&write_active&&!s_axi_bvalid;
    assign s_axi_arready=rst_n&&!protocol_fault&&!s_axi_rvalid&&ar_known;
    assign s_axi_bresp=2'b11;
    assign s_axi_rresp=2'b11;
    assign s_axi_rdata=128'b0;

    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            write_active<=0;write_id<=0;write_left<=0;read_left<=0;
            s_axi_bid<=0;s_axi_bvalid<=0;s_axi_rid<=0;
            s_axi_rlast<=0;s_axi_rvalid<=0;protocol_fault<=0;
        end else begin
            if((s_axi_awvalid!==1'b0&&s_axi_awvalid!==1'b1)||
               (s_axi_wvalid!==1'b0&&s_axi_wvalid!==1'b1)||
               (s_axi_arvalid!==1'b0&&s_axi_arvalid!==1'b1)||
               (s_axi_awvalid===1'b1&&!aw_known)||
               (s_axi_arvalid===1'b1&&!ar_known))protocol_fault<=1;
            if(s_axi_bvalid&&s_axi_bready)s_axi_bvalid<=0;
            if(s_axi_awvalid===1'b1&&s_axi_awready)begin
                write_active<=1;write_id<=s_axi_awid;
                write_left<={1'b0,s_axi_awlen}+9'd1;
            end
            if(s_axi_wvalid===1'b1&&s_axi_wready)begin
                if(s_axi_wlast!==(write_left==9'd1))protocol_fault<=1;
                if(write_left==9'd1)begin
                    write_active<=0;write_left<=0;
                    s_axi_bid<=write_id;s_axi_bvalid<=1;
                end else write_left<=write_left-9'd1;
            end
            if(s_axi_arvalid===1'b1&&s_axi_arready)begin
                s_axi_rid<=s_axi_arid;s_axi_rvalid<=1;
                s_axi_rlast<=s_axi_arlen==8'd0;
                read_left<={1'b0,s_axi_arlen}+9'd1;
            end else if(s_axi_rvalid&&s_axi_rready)begin
                if(read_left==9'd1)begin
                    read_left<=0;s_axi_rvalid<=0;s_axi_rlast<=0;
                end else begin
                    read_left<=read_left-9'd1;
                    s_axi_rlast<=read_left==9'd2;
                end
            end
        end
    end
endmodule
