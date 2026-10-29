// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Private two-master routing leaf. Master0=normal, master1=diagnostic.
// The qualified owner is the ONLY source of diagnostic_selected. It must not
// change selection with held VALID or outstanding traffic and must retain
// selection through done/fault. This mux deliberately has no busy/done/fault
// gate, no implicit reset, no arbitration and no data/attribute repair.
// Use separate instances for memory and ECC-control paths. AXI-Lite wrappers
// tie absent ID/burst/last fields to their explicit single-beat constants.
// Positive fallback port widths allow invalid parameters to reach the explicit
// time-zero fatal without a frontend negative-range crash. Valid profiles keep
// their exact original widths; no invalid profile is accepted.
module rk_ddr_diagnostic_mux #(
    parameter int unsigned ADDR_WIDTH = 31,
    parameter int unsigned DATA_WIDTH = 512,
    parameter int unsigned ID_WIDTH = 4
) (
    input logic joint_rst_n, diagnostic_selected,
    input logic [1:0][(ID_WIDTH>0 ? ID_WIDTH : 1)-1:0] s_axi_awid, s_axi_arid,
    input logic [1:0][(ADDR_WIDTH>0 ? ADDR_WIDTH : 1)-1:0] s_axi_awaddr, s_axi_araddr,
    input logic [1:0][7:0] s_axi_awlen, s_axi_arlen,
    input logic [1:0][2:0] s_axi_awsize, s_axi_arsize,
    input logic [1:0][1:0] s_axi_awburst, s_axi_arburst,
    input logic [1:0] s_axi_awlock, s_axi_arlock,
    input logic [1:0][3:0] s_axi_awcache, s_axi_arcache,
    input logic [1:0][2:0] s_axi_awprot, s_axi_arprot,
    input logic [1:0][3:0] s_axi_awqos, s_axi_arqos,
    input logic [1:0] s_axi_awvalid,
    output logic [1:0] s_axi_awready,
    input logic [1:0][(DATA_WIDTH>=8 ? DATA_WIDTH : 8)-1:0] s_axi_wdata,
    input logic [1:0][(DATA_WIDTH>=8 ? DATA_WIDTH/8 : 1)-1:0] s_axi_wstrb,
    input logic [1:0] s_axi_wlast, s_axi_wvalid,
    output logic [1:0] s_axi_wready,
    output logic [1:0][(ID_WIDTH>0 ? ID_WIDTH : 1)-1:0] s_axi_bid,
    output logic [1:0][1:0] s_axi_bresp,
    output logic [1:0] s_axi_bvalid,
    input logic [1:0] s_axi_bready,
    input logic [1:0] s_axi_arvalid,
    output logic [1:0] s_axi_arready,
    output logic [1:0][(ID_WIDTH>0 ? ID_WIDTH : 1)-1:0] s_axi_rid,
    output logic [1:0][(DATA_WIDTH>=8 ? DATA_WIDTH : 8)-1:0] s_axi_rdata,
    output logic [1:0][1:0] s_axi_rresp,
    output logic [1:0] s_axi_rlast, s_axi_rvalid,
    input logic [1:0] s_axi_rready,

    output logic [(ID_WIDTH>0 ? ID_WIDTH : 1)-1:0] m_axi_awid, m_axi_arid,
    output logic [(ADDR_WIDTH>0 ? ADDR_WIDTH : 1)-1:0] m_axi_awaddr, m_axi_araddr,
    output logic [7:0] m_axi_awlen, m_axi_arlen,
    output logic [2:0] m_axi_awsize, m_axi_arsize,
    output logic [1:0] m_axi_awburst, m_axi_arburst,
    output logic m_axi_awlock, m_axi_arlock,
    output logic [3:0] m_axi_awcache, m_axi_arcache,
    output logic [2:0] m_axi_awprot, m_axi_arprot,
    output logic [3:0] m_axi_awqos, m_axi_arqos,
    output logic m_axi_awvalid,
    input logic m_axi_awready,
    output logic [(DATA_WIDTH>=8 ? DATA_WIDTH : 8)-1:0] m_axi_wdata,
    output logic [(DATA_WIDTH>=8 ? DATA_WIDTH/8 : 1)-1:0] m_axi_wstrb,
    output logic m_axi_wlast, m_axi_wvalid,
    input logic m_axi_wready,
    input logic [(ID_WIDTH>0 ? ID_WIDTH : 1)-1:0] m_axi_bid,
    input logic [1:0] m_axi_bresp,
    input logic m_axi_bvalid,
    output logic m_axi_bready,
    output logic m_axi_arvalid,
    input logic m_axi_arready,
    input logic [(ID_WIDTH>0 ? ID_WIDTH : 1)-1:0] m_axi_rid,
    input logic [(DATA_WIDTH>=8 ? DATA_WIDTH : 8)-1:0] m_axi_rdata,
    input logic [1:0] m_axi_rresp,
    input logic m_axi_rlast, m_axi_rvalid,
    output logic m_axi_rready
);
    initial begin
        if (ADDR_WIDTH<1 || DATA_WIDTH<8 || DATA_WIDTH%8!=0 || ID_WIDTH<1)
            $fatal(1,"Diagnostic mux needs positive address/ID widths and byte-granular data");
    end
    assign m_axi_awid=s_axi_awid[diagnostic_selected];
    assign m_axi_awaddr=s_axi_awaddr[diagnostic_selected];
    assign m_axi_awlen=s_axi_awlen[diagnostic_selected];
    assign m_axi_awsize=s_axi_awsize[diagnostic_selected];
    assign m_axi_awburst=s_axi_awburst[diagnostic_selected];
    assign m_axi_awlock=s_axi_awlock[diagnostic_selected];
    assign m_axi_awcache=s_axi_awcache[diagnostic_selected];
    assign m_axi_awprot=s_axi_awprot[diagnostic_selected];
    assign m_axi_awqos=s_axi_awqos[diagnostic_selected];
    assign m_axi_wdata=s_axi_wdata[diagnostic_selected];
    assign m_axi_wstrb=s_axi_wstrb[diagnostic_selected];
    assign m_axi_wlast=s_axi_wlast[diagnostic_selected];
    assign m_axi_arid=s_axi_arid[diagnostic_selected];
    assign m_axi_araddr=s_axi_araddr[diagnostic_selected];
    assign m_axi_arlen=s_axi_arlen[diagnostic_selected];
    assign m_axi_arsize=s_axi_arsize[diagnostic_selected];
    assign m_axi_arburst=s_axi_arburst[diagnostic_selected];
    assign m_axi_arlock=s_axi_arlock[diagnostic_selected];
    assign m_axi_arcache=s_axi_arcache[diagnostic_selected];
    assign m_axi_arprot=s_axi_arprot[diagnostic_selected];
    assign m_axi_arqos=s_axi_arqos[diagnostic_selected];
    // Response payloads are broadcast; only the selected VALID qualifies them.
    assign s_axi_bid={2{m_axi_bid}};
    assign s_axi_bresp={2{m_axi_bresp}};
    assign s_axi_rid={2{m_axi_rid}};
    assign s_axi_rdata={2{m_axi_rdata}};
    assign s_axi_rresp={2{m_axi_rresp}};
    assign s_axi_rlast={2{m_axi_rlast}};
    always_comb begin
        s_axi_awready=0; s_axi_wready=0; s_axi_arready=0;
        s_axi_bvalid=0; s_axi_rvalid=0;
        m_axi_awvalid=0; m_axi_wvalid=0; m_axi_arvalid=0;
        m_axi_bready=0; m_axi_rready=0;
        if (joint_rst_n) begin
            s_axi_awready[diagnostic_selected]=m_axi_awready;
            s_axi_wready[diagnostic_selected]=m_axi_wready;
            s_axi_arready[diagnostic_selected]=m_axi_arready;
            s_axi_bvalid[diagnostic_selected]=m_axi_bvalid;
            s_axi_rvalid[diagnostic_selected]=m_axi_rvalid;
            m_axi_awvalid=s_axi_awvalid[diagnostic_selected];
            m_axi_wvalid=s_axi_wvalid[diagnostic_selected];
            m_axi_arvalid=s_axi_arvalid[diagnostic_selected];
            m_axi_bready=s_axi_bready[diagnostic_selected];
            m_axi_rready=s_axi_rready[diagnostic_selected];
        end
    end
endmodule
