// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Unselected source-only adapter for the installed AMD AXI Clock Converter.
// Both sides share one retained transaction epoch. common_epoch_rst_n is not
// PCIe PERST#, XDMA axi_aresetn, or a link-health signal. The physical shell
// must assert the actual XDMA reset from this same common epoch.
// This leaf never gates VALID/READY: transactions already accepted across the
// converter must drain. New-frame admission and link quarantine belong at the
// existing retained frontend/epoch guard. No clock-frequency or CDC signoff
// follows from this wrapper or its native converter model.
module rk_pcie_axil_crossing (
    input  wire pcie_clk,
    input  wire c0_ui_clk,
    input  wire common_epoch_rst_n,
    output wire s_ready,
    output wire m_ready,

    input  wire [31:0] s_axil_awaddr,
    input  wire [2:0]  s_axil_awprot,
    input  wire        s_axil_awvalid,
    output wire        s_axil_awready,
    input  wire [31:0] s_axil_wdata,
    input  wire [3:0]  s_axil_wstrb,
    input  wire        s_axil_wvalid,
    output wire        s_axil_wready,
    output wire [1:0]  s_axil_bresp,
    output wire        s_axil_bvalid,
    input  wire        s_axil_bready,
    input  wire [31:0] s_axil_araddr,
    input  wire [2:0]  s_axil_arprot,
    input  wire        s_axil_arvalid,
    output wire        s_axil_arready,
    output wire [31:0] s_axil_rdata,
    output wire [1:0]  s_axil_rresp,
    output wire        s_axil_rvalid,
    input  wire        s_axil_rready,

    output wire [31:0] m_axil_awaddr,
    output wire [2:0]  m_axil_awprot,
    output wire        m_axil_awvalid,
    input  wire        m_axil_awready,
    output wire [31:0] m_axil_wdata,
    output wire [3:0]  m_axil_wstrb,
    output wire        m_axil_wvalid,
    input  wire        m_axil_wready,
    input  wire [1:0]  m_axil_bresp,
    input  wire        m_axil_bvalid,
    output wire        m_axil_bready,
    output wire [31:0] m_axil_araddr,
    output wire [2:0]  m_axil_arprot,
    output wire        m_axil_arvalid,
    input  wire        m_axil_arready,
    input  wire [31:0] m_axil_rdata,
    input  wire [1:0]  m_axil_rresp,
    input  wire        m_axil_rvalid,
    output wire        m_axil_rready
);
    localparam integer RESET_SYNC_STAGES=3;
    localparam integer RESET_EDGES=8;
    localparam integer SETTLE_EDGES=5;

    wire s_aresetn,m_aresetn;
    rk_pcie_bridge_reset #(
        .SYNC_STAGES(RESET_SYNC_STAGES),
        .RESET_EDGES(RESET_EDGES),
        .SETTLE_EDGES(SETTLE_EDGES)
    ) u_bridge_reset (
        .epoch_rst_n(common_epoch_rst_n),
        .s_clk(pcie_clk),.m_clk(c0_ui_clk),
        .s_aresetn(s_aresetn),.m_aresetn(m_aresetn),
        .s_ready(s_ready),.m_ready(m_ready)
    );

    // AXI4-only fields absent from the Lite interfaces are tied or left
    // unconnected exactly at the selected converter boundary. No Lite channel
    // is qualified by s_ready/m_ready here; admission is upstream and ongoing
    // channel handshakes remain available to complete accepted transactions.
    wire [0:0] s_bid_unused,s_buser_unused,s_rid_unused,s_ruser_unused;
    wire s_rlast_unused;
    wire [0:0] m_awid_unused,m_wid_unused,m_arid_unused,m_awlock_unused,m_arlock_unused;
    wire [7:0] m_awlen_unused,m_arlen_unused;
    wire [2:0] m_awsize_unused,m_arsize_unused;
    wire [1:0] m_awburst_unused,m_arburst_unused;
    wire [3:0] m_awcache_unused,m_awregion_unused,m_awqos_unused,m_arcache_unused,m_arregion_unused,m_arqos_unused;
    wire [0:0] m_awuser_unused,m_wuser_unused,m_aruser_unused;
    wire m_wlast_unused;

    axi_clock_converter_v2_1_36_axi_clock_converter #(
        .C_FAMILY("kintex7"),.C_AXI_ID_WIDTH(1),.C_AXI_ADDR_WIDTH(32),.C_AXI_DATA_WIDTH(32),
        .C_S_AXI_ACLK_RATIO(1),.C_M_AXI_ACLK_RATIO(1),.C_AXI_IS_ACLK_ASYNC(1),
        .C_AXI_PROTOCOL(2),.C_AXI_SUPPORTS_USER_SIGNALS(0),
        .C_AXI_AWUSER_WIDTH(1),.C_AXI_ARUSER_WIDTH(1),.C_AXI_WUSER_WIDTH(1),
        .C_AXI_RUSER_WIDTH(1),.C_AXI_BUSER_WIDTH(1),
        .C_AXI_SUPPORTS_WRITE(1),.C_AXI_SUPPORTS_READ(1),.C_SYNCHRONIZER_STAGE(3)
    ) u_axil_converter (
        .s_axi_aclk(pcie_clk),.s_axi_aresetn(s_aresetn),
        .s_axi_awid(1'b0),.s_axi_awaddr(s_axil_awaddr),.s_axi_awlen(8'b0),.s_axi_awsize(3'b0),
        .s_axi_awburst(2'b0),.s_axi_awlock(1'b0),.s_axi_awcache(4'b0),.s_axi_awprot(s_axil_awprot),
        .s_axi_awregion(4'b0),.s_axi_awqos(4'b0),.s_axi_awuser(1'b0),
        .s_axi_awvalid(s_axil_awvalid),.s_axi_awready(s_axil_awready),
        .s_axi_wid(1'b0),.s_axi_wdata(s_axil_wdata),.s_axi_wstrb(s_axil_wstrb),.s_axi_wlast(1'b0),
        .s_axi_wuser(1'b0),.s_axi_wvalid(s_axil_wvalid),.s_axi_wready(s_axil_wready),
        .s_axi_bid(s_bid_unused),.s_axi_bresp(s_axil_bresp),.s_axi_buser(s_buser_unused),
        .s_axi_bvalid(s_axil_bvalid),.s_axi_bready(s_axil_bready),
        .s_axi_arid(1'b0),.s_axi_araddr(s_axil_araddr),.s_axi_arlen(8'b0),.s_axi_arsize(3'b0),
        .s_axi_arburst(2'b0),.s_axi_arlock(1'b0),.s_axi_arcache(4'b0),.s_axi_arprot(s_axil_arprot),
        .s_axi_arregion(4'b0),.s_axi_arqos(4'b0),.s_axi_aruser(1'b0),
        .s_axi_arvalid(s_axil_arvalid),.s_axi_arready(s_axil_arready),
        .s_axi_rid(s_rid_unused),.s_axi_rdata(s_axil_rdata),.s_axi_rresp(s_axil_rresp),
        .s_axi_rlast(s_rlast_unused),.s_axi_ruser(s_ruser_unused),.s_axi_rvalid(s_axil_rvalid),.s_axi_rready(s_axil_rready),
        .m_axi_aclk(c0_ui_clk),.m_axi_aresetn(m_aresetn),
        .m_axi_awid(m_awid_unused),.m_axi_awaddr(m_axil_awaddr),.m_axi_awlen(m_awlen_unused),
        .m_axi_awsize(m_awsize_unused),.m_axi_awburst(m_awburst_unused),.m_axi_awlock(m_awlock_unused),
        .m_axi_awcache(m_awcache_unused),.m_axi_awprot(m_axil_awprot),.m_axi_awregion(m_awregion_unused),
        .m_axi_awqos(m_awqos_unused),.m_axi_awuser(m_awuser_unused),
        .m_axi_awvalid(m_axil_awvalid),.m_axi_awready(m_axil_awready),
        .m_axi_wid(m_wid_unused),.m_axi_wdata(m_axil_wdata),.m_axi_wstrb(m_axil_wstrb),
        .m_axi_wlast(m_wlast_unused),.m_axi_wuser(m_wuser_unused),.m_axi_wvalid(m_axil_wvalid),.m_axi_wready(m_axil_wready),
        .m_axi_bid(1'b0),.m_axi_bresp(m_axil_bresp),.m_axi_buser(1'b0),.m_axi_bvalid(m_axil_bvalid),.m_axi_bready(m_axil_bready),
        .m_axi_arid(m_arid_unused),.m_axi_araddr(m_axil_araddr),.m_axi_arlen(m_arlen_unused),
        .m_axi_arsize(m_arsize_unused),.m_axi_arburst(m_arburst_unused),.m_axi_arlock(m_arlock_unused),
        .m_axi_arcache(m_arcache_unused),.m_axi_arprot(m_axil_arprot),.m_axi_arregion(m_arregion_unused),
        .m_axi_arqos(m_arqos_unused),.m_axi_aruser(m_aruser_unused),
        .m_axi_arvalid(m_axil_arvalid),.m_axi_arready(m_axil_arready),
        .m_axi_rid(1'b0),.m_axi_rdata(m_axil_rdata),.m_axi_rresp(m_axil_rresp),.m_axi_rlast(1'b0),
        .m_axi_ruser(1'b0),.m_axi_rvalid(m_axil_rvalid),.m_axi_rready(m_axil_rready)
    );
endmodule
