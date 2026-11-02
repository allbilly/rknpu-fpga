// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Candidate only: actual XDMA and asynchronous AXI-Lite converter.
// Common epoch resets master and converter together. Link/PERST invalidates
// health without resetting retained NPU/frontend ownership. Polling-only:
// usr_irq_req is zero and no MSI notification service is offered.
module rk_pcie_control_plane (
    input wire pcie_refclk,pcie_perst_n,c0_ui_clk,common_epoch_rst_n,ui_epoch_rst_n,
    input wire [7:0] pci_exp_rxp,pci_exp_rxn,
    output wire [7:0] pci_exp_txp,pci_exp_txn,
    output wire pcie_source_healthy,pcie_clock_alive,
    output wire pcie_axi_clk,pcie_axi_aresetn,pcie_link_up,
    output wire dma_protocol_fault,
    output wire [31 : 0] pcie_axil_awaddr,
    output wire [2 : 0] pcie_axil_awprot,
    output wire pcie_axil_awvalid,
    input wire pcie_axil_awready,
    output wire [31 : 0] pcie_axil_wdata,
    output wire [3 : 0] pcie_axil_wstrb,
    output wire pcie_axil_wvalid,
    input wire pcie_axil_wready,
    input wire pcie_axil_bvalid,
    input wire [1 : 0] pcie_axil_bresp,
    output wire pcie_axil_bready,
    output wire [31 : 0] pcie_axil_araddr,
    output wire [2 : 0] pcie_axil_arprot,
    output wire pcie_axil_arvalid,
    input wire pcie_axil_arready,
    input wire [31 : 0] pcie_axil_rdata,
    input wire [1 : 0] pcie_axil_rresp,
    input wire pcie_axil_rvalid,
    output wire pcie_axil_rready
);
    wire m_axi_awready;
    wire m_axi_wready;
    wire [3 : 0] m_axi_bid;
    wire [1 : 0] m_axi_bresp;
    wire m_axi_bvalid;
    wire m_axi_arready;
    wire [3 : 0] m_axi_rid;
    wire [127 : 0] m_axi_rdata;
    wire [1 : 0] m_axi_rresp;
    wire m_axi_rlast;
    wire m_axi_rvalid;
    wire [3 : 0] m_axi_awid;
    wire [63 : 0] m_axi_awaddr;
    wire [7 : 0] m_axi_awlen;
    wire [2 : 0] m_axi_awsize;
    wire [1 : 0] m_axi_awburst;
    wire [2 : 0] m_axi_awprot;
    wire m_axi_awvalid;
    wire m_axi_awlock;
    wire [3 : 0] m_axi_awcache;
    wire [127 : 0] m_axi_wdata;
    wire [15 : 0] m_axi_wstrb;
    wire m_axi_wlast;
    wire m_axi_wvalid;
    wire m_axi_bready;
    wire [3 : 0] m_axi_arid;
    wire [63 : 0] m_axi_araddr;
    wire [7 : 0] m_axi_arlen;
    wire [2 : 0] m_axi_arsize;
    wire [1 : 0] m_axi_arburst;
    wire [2 : 0] m_axi_arprot;
    wire m_axi_arvalid;
    wire m_axi_arlock;
    wire [3 : 0] m_axi_arcache;
    wire m_axi_rready;
    wire [31 : 0] m_axil_awaddr;
    wire [2 : 0] m_axil_awprot;
    wire m_axil_awvalid;
    wire m_axil_awready;
    wire [31 : 0] m_axil_wdata;
    wire [3 : 0] m_axil_wstrb;
    wire m_axil_wvalid;
    wire m_axil_wready;
    wire m_axil_bvalid;
    wire [1 : 0] m_axil_bresp;
    wire m_axil_bready;
    wire [31 : 0] m_axil_araddr;
    wire [2 : 0] m_axil_arprot;
    wire m_axil_arvalid;
    wire m_axil_arready;
    wire [31 : 0] m_axil_rdata;
    wire [1 : 0] m_axil_rresp;
    wire m_axil_rvalid;
    wire m_axil_rready;
    wire bridge_s_ready,bridge_m_ready,qualified_source;
    wire [0:0] usr_irq_ack_unused;
    wire msi_enable_unused,cfg_mgmt_done_unused;
    wire [2:0] msi_vector_width_unused;
    wire [31:0] cfg_mgmt_data_unused;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] s_ready_ui;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] dma_fault_ui;
    always @(posedge c0_ui_clk or negedge ui_epoch_rst_n)begin
        if(!ui_epoch_rst_n)begin s_ready_ui<=0;dma_fault_ui<=0;end
        else begin
            s_ready_ui<={s_ready_ui[1:0],bridge_s_ready};
            dma_fault_ui<={dma_fault_ui[1:0],dma_protocol_fault};
        end
    end
    assign pcie_source_healthy=qualified_source&&(dma_fault_ui[2]===1'b0);
    rk_pcie_source_health health (
        .ui_clk(c0_ui_clk),.pcie_clk(pcie_axi_clk),.joint_reset_n(common_epoch_rst_n),
        .pcie_link_up(pcie_link_up&&pcie_perst_n),.pcie_axi_aresetn(pcie_axi_aresetn),
        .bridge_ready_ui(bridge_m_ready&&s_ready_ui[2]),
        .source_healthy(qualified_source),.clock_alive(pcie_clock_alive)
    );
    xdma_probe xdma (
        .sys_clk(pcie_refclk),
        .sys_rst_n(common_epoch_rst_n&&pcie_perst_n),
        .user_lnk_up(pcie_link_up),
        .pci_exp_txp(pci_exp_txp),
        .pci_exp_txn(pci_exp_txn),
        .pci_exp_rxp(pci_exp_rxp),
        .pci_exp_rxn(pci_exp_rxn),
        .axi_aclk(pcie_axi_clk),
        .axi_aresetn(pcie_axi_aresetn),
        .usr_irq_req(1'b0),
        .usr_irq_ack(usr_irq_ack_unused),
        .msi_enable(msi_enable_unused),
        .msi_vector_width(msi_vector_width_unused),
        .m_axi_awready(m_axi_awready),
        .m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid),
        .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid),
        .m_axi_arready(m_axi_arready),
        .m_axi_rid(m_axi_rid),
        .m_axi_rdata(m_axi_rdata),
        .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_rvalid(m_axi_rvalid),
        .m_axi_awid(m_axi_awid),
        .m_axi_awaddr(m_axi_awaddr),
        .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst),
        .m_axi_awprot(m_axi_awprot),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_awlock(m_axi_awlock),
        .m_axi_awcache(m_axi_awcache),
        .m_axi_wdata(m_axi_wdata),
        .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_wvalid(m_axi_wvalid),
        .m_axi_bready(m_axi_bready),
        .m_axi_arid(m_axi_arid),
        .m_axi_araddr(m_axi_araddr),
        .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst),
        .m_axi_arprot(m_axi_arprot),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arlock(m_axi_arlock),
        .m_axi_arcache(m_axi_arcache),
        .m_axi_rready(m_axi_rready),
        .m_axil_awaddr(m_axil_awaddr),
        .m_axil_awprot(m_axil_awprot),
        .m_axil_awvalid(m_axil_awvalid),
        .m_axil_awready(m_axil_awready),
        .m_axil_wdata(m_axil_wdata),
        .m_axil_wstrb(m_axil_wstrb),
        .m_axil_wvalid(m_axil_wvalid),
        .m_axil_wready(m_axil_wready),
        .m_axil_bvalid(m_axil_bvalid),
        .m_axil_bresp(m_axil_bresp),
        .m_axil_bready(m_axil_bready),
        .m_axil_araddr(m_axil_araddr),
        .m_axil_arprot(m_axil_arprot),
        .m_axil_arvalid(m_axil_arvalid),
        .m_axil_arready(m_axil_arready),
        .m_axil_rdata(m_axil_rdata),
        .m_axil_rresp(m_axil_rresp),
        .m_axil_rvalid(m_axil_rvalid),
        .m_axil_rready(m_axil_rready),
        .cfg_mgmt_addr(19'd0),
        .cfg_mgmt_write(1'b0),
        .cfg_mgmt_write_data(32'd0),
        .cfg_mgmt_byte_enable(4'd0),
        .cfg_mgmt_read(1'b0),
        .cfg_mgmt_read_data(cfg_mgmt_data_unused),
        .cfg_mgmt_read_write_done(cfg_mgmt_done_unused),
        .cfg_mgmt_type1_cfg_reg_access(1'b0)
    );
    rk_pcie_axil_crossing crossing (
        .pcie_clk(pcie_axi_clk),.c0_ui_clk(c0_ui_clk),.common_epoch_rst_n(common_epoch_rst_n),
        .s_ready(bridge_s_ready),.m_ready(bridge_m_ready),
        .s_axil_awaddr(m_axil_awaddr),
        .m_axil_awaddr(pcie_axil_awaddr),
        .s_axil_awprot(m_axil_awprot),
        .m_axil_awprot(pcie_axil_awprot),
        .s_axil_awvalid(m_axil_awvalid),
        .m_axil_awvalid(pcie_axil_awvalid),
        .s_axil_awready(m_axil_awready),
        .m_axil_awready(pcie_axil_awready),
        .s_axil_wdata(m_axil_wdata),
        .m_axil_wdata(pcie_axil_wdata),
        .s_axil_wstrb(m_axil_wstrb),
        .m_axil_wstrb(pcie_axil_wstrb),
        .s_axil_wvalid(m_axil_wvalid),
        .m_axil_wvalid(pcie_axil_wvalid),
        .s_axil_wready(m_axil_wready),
        .m_axil_wready(pcie_axil_wready),
        .s_axil_bvalid(m_axil_bvalid),
        .m_axil_bvalid(pcie_axil_bvalid),
        .s_axil_bresp(m_axil_bresp),
        .m_axil_bresp(pcie_axil_bresp),
        .s_axil_bready(m_axil_bready),
        .m_axil_bready(pcie_axil_bready),
        .s_axil_araddr(m_axil_araddr),
        .m_axil_araddr(pcie_axil_araddr),
        .s_axil_arprot(m_axil_arprot),
        .m_axil_arprot(pcie_axil_arprot),
        .s_axil_arvalid(m_axil_arvalid),
        .m_axil_arvalid(pcie_axil_arvalid),
        .s_axil_arready(m_axil_arready),
        .m_axil_arready(pcie_axil_arready),
        .s_axil_rdata(m_axil_rdata),
        .m_axil_rdata(pcie_axil_rdata),
        .s_axil_rresp(m_axil_rresp),
        .m_axil_rresp(pcie_axil_rresp),
        .s_axil_rvalid(m_axil_rvalid),
        .m_axil_rvalid(pcie_axil_rvalid),
        .s_axil_rready(m_axil_rready),
        .m_axil_rready(pcie_axil_rready)
    );
    rk_pcie_dma_decerr rejected_dma (
        .clk(pcie_axi_clk),.rst_n(pcie_axi_aresetn),.protocol_fault(dma_protocol_fault),
        .s_axi_awready(m_axi_awready),
        .s_axi_wready(m_axi_wready),
        .s_axi_bid(m_axi_bid),
        .s_axi_bresp(m_axi_bresp),
        .s_axi_bvalid(m_axi_bvalid),
        .s_axi_arready(m_axi_arready),
        .s_axi_rid(m_axi_rid),
        .s_axi_rdata(m_axi_rdata),
        .s_axi_rresp(m_axi_rresp),
        .s_axi_rlast(m_axi_rlast),
        .s_axi_rvalid(m_axi_rvalid),
        .s_axi_awid(m_axi_awid),
        .s_axi_awaddr(m_axi_awaddr),
        .s_axi_awlen(m_axi_awlen),
        .s_axi_awsize(m_axi_awsize),
        .s_axi_awburst(m_axi_awburst),
        .s_axi_awprot(m_axi_awprot),
        .s_axi_awvalid(m_axi_awvalid),
        .s_axi_awlock(m_axi_awlock),
        .s_axi_awcache(m_axi_awcache),
        .s_axi_wdata(m_axi_wdata),
        .s_axi_wstrb(m_axi_wstrb),
        .s_axi_wlast(m_axi_wlast),
        .s_axi_wvalid(m_axi_wvalid),
        .s_axi_bready(m_axi_bready),
        .s_axi_arid(m_axi_arid),
        .s_axi_araddr(m_axi_araddr),
        .s_axi_arlen(m_axi_arlen),
        .s_axi_arsize(m_axi_arsize),
        .s_axi_arburst(m_axi_arburst),
        .s_axi_arprot(m_axi_arprot),
        .s_axi_arvalid(m_axi_arvalid),
        .s_axi_arlock(m_axi_arlock),
        .s_axi_arcache(m_axi_arcache),
        .s_axi_rready(m_axi_rready)
    );
endmodule
