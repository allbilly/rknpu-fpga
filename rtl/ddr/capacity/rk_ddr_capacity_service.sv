// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Rendered by compose_service.py. Private UI-domain subsystem, not a board top.
// Normal inputs are the unchanged raw-command fabric and ECC monitor masters.
// The caller supplies true internal fabric/host/job/readback quiescence and
// must allow previously owned readback/ACK to drain while blocking new work.
// Management AXI-Lite is separately decoded; no RK register interpretation,
// JTAG transport, controller PHY, PCIe, clock crossing or reset coordinator here.
// Both controllers and every full512 product remain obligations of the parent.
module rk_ddr_capacity_service #(
    parameter logic [30:0] BASE_ADDR=0,
    parameter logic [31:0] SPAN_BYTES=32'h80000000,
    parameter int unsigned TIMEOUT_CYCLES=65536
) (
    input logic clk, joint_rst_n, initialization_complete, calibration_complete, mig_interrupt,
    input logic normal_monitor_healthy, normal_monitor_fault,
    input logic normal_fabric_quiet, normal_job_owned, normal_host_busy, normal_engine_pending, normal_pending_response,
    output logic normal_admission_enable, normal_selected, diagnostic_selected, owner_busy, owner_done, owner_fault,
    input logic [3:0] n_axi_awid,
    input logic [30:0] n_axi_awaddr,
    input logic [7:0] n_axi_awlen,
    input logic [2:0] n_axi_awsize,
    input logic [1:0] n_axi_awburst,
    input logic n_axi_awlock,
    input logic [3:0] n_axi_awcache,
    input logic [2:0] n_axi_awprot,
    input logic [3:0] n_axi_awqos,
    input logic n_axi_awvalid,
    output logic n_axi_awready,
    input logic [3:0] n_axi_arid,
    input logic [30:0] n_axi_araddr,
    input logic [7:0] n_axi_arlen,
    input logic [2:0] n_axi_arsize,
    input logic [1:0] n_axi_arburst,
    input logic n_axi_arlock,
    input logic [3:0] n_axi_arcache,
    input logic [2:0] n_axi_arprot,
    input logic [3:0] n_axi_arqos,
    input logic n_axi_arvalid,
    output logic n_axi_arready,
    input logic [511:0] n_axi_wdata,
    input logic [63:0] n_axi_wstrb,
    input logic n_axi_wlast,
    input logic n_axi_wvalid,
    output logic n_axi_wready,
    output logic [3:0] n_axi_bid,
    output logic [1:0] n_axi_bresp,
    output logic n_axi_bvalid,
    input logic n_axi_bready,
    output logic [3:0] n_axi_rid,
    output logic [511:0] n_axi_rdata,
    output logic [1:0] n_axi_rresp,
    output logic n_axi_rlast,
    output logic n_axi_rvalid,
    input logic n_axi_rready,
    output logic [3:0] m_axi_awid,
    output logic [30:0] m_axi_awaddr,
    output logic [7:0] m_axi_awlen,
    output logic [2:0] m_axi_awsize,
    output logic [1:0] m_axi_awburst,
    output logic m_axi_awlock,
    output logic [3:0] m_axi_awcache,
    output logic [2:0] m_axi_awprot,
    output logic [3:0] m_axi_awqos,
    output logic m_axi_awvalid,
    input logic m_axi_awready,
    output logic [3:0] m_axi_arid,
    output logic [30:0] m_axi_araddr,
    output logic [7:0] m_axi_arlen,
    output logic [2:0] m_axi_arsize,
    output logic [1:0] m_axi_arburst,
    output logic m_axi_arlock,
    output logic [3:0] m_axi_arcache,
    output logic [2:0] m_axi_arprot,
    output logic [3:0] m_axi_arqos,
    output logic m_axi_arvalid,
    input logic m_axi_arready,
    output logic [511:0] m_axi_wdata,
    output logic [63:0] m_axi_wstrb,
    output logic m_axi_wlast,
    output logic m_axi_wvalid,
    input logic m_axi_wready,
    input logic [3:0] m_axi_bid,
    input logic [1:0] m_axi_bresp,
    input logic m_axi_bvalid,
    output logic m_axi_bready,
    input logic [3:0] m_axi_rid,
    input logic [511:0] m_axi_rdata,
    input logic [1:0] m_axi_rresp,
    input logic m_axi_rlast,
    input logic m_axi_rvalid,
    output logic m_axi_rready,
    input logic [31:0] n_ctrl_awaddr,
    input logic n_ctrl_awvalid,
    output logic n_ctrl_awready,
    input logic [31:0] n_ctrl_wdata,
    input logic n_ctrl_wvalid,
    output logic n_ctrl_wready,
    output logic [1:0] n_ctrl_bresp,
    output logic n_ctrl_bvalid,
    input logic n_ctrl_bready,
    input logic [31:0] n_ctrl_araddr,
    input logic n_ctrl_arvalid,
    output logic n_ctrl_arready,
    output logic [31:0] n_ctrl_rdata,
    output logic [1:0] n_ctrl_rresp,
    output logic n_ctrl_rvalid,
    input logic n_ctrl_rready,
    output logic [31:0] m_axi_ctrl_awaddr,
    output logic m_axi_ctrl_awvalid,
    input logic m_axi_ctrl_awready,
    output logic [31:0] m_axi_ctrl_wdata,
    output logic m_axi_ctrl_wvalid,
    input logic m_axi_ctrl_wready,
    input logic [1:0] m_axi_ctrl_bresp,
    input logic m_axi_ctrl_bvalid,
    output logic m_axi_ctrl_bready,
    output logic [31:0] m_axi_ctrl_araddr,
    output logic m_axi_ctrl_arvalid,
    input logic m_axi_ctrl_arready,
    input logic [31:0] m_axi_ctrl_rdata,
    input logic [1:0] m_axi_ctrl_rresp,
    input logic m_axi_ctrl_rvalid,
    output logic m_axi_ctrl_rready,
    input logic [31:0] s_axil_awaddr,
    input logic [2:0] s_axil_awprot,
    input logic s_axil_awvalid,
    output logic s_axil_awready,
    input logic [31:0] s_axil_wdata,
    input logic [3:0] s_axil_wstrb,
    input logic s_axil_wvalid,
    output logic s_axil_wready,
    output logic [1:0] s_axil_bresp,
    output logic s_axil_bvalid,
    input logic s_axil_bready,
    input logic [31:0] s_axil_araddr,
    input logic [2:0] s_axil_arprot,
    input logic s_axil_arvalid,
    output logic s_axil_arready,
    output logic [31:0] s_axil_rdata,
    output logic [1:0] s_axil_rresp,
    output logic s_axil_rvalid,
    input logic s_axil_rready
);
    logic [3:0] d_axi_awid;
    logic [1:0][3:0] mem_awid;
    logic [30:0] d_axi_awaddr;
    logic [1:0][30:0] mem_awaddr;
    logic [7:0] d_axi_awlen;
    logic [1:0][7:0] mem_awlen;
    logic [2:0] d_axi_awsize;
    logic [1:0][2:0] mem_awsize;
    logic [1:0] d_axi_awburst;
    logic [1:0][1:0] mem_awburst;
    logic d_axi_awlock;
    logic [1:0]mem_awlock;
    logic [3:0] d_axi_awcache;
    logic [1:0][3:0] mem_awcache;
    logic [2:0] d_axi_awprot;
    logic [1:0][2:0] mem_awprot;
    logic [3:0] d_axi_awqos;
    logic [1:0][3:0] mem_awqos;
    logic d_axi_awvalid;
    logic [1:0]mem_awvalid;
    logic d_axi_awready;
    logic [1:0]mem_awready;
    logic [3:0] d_axi_arid;
    logic [1:0][3:0] mem_arid;
    logic [30:0] d_axi_araddr;
    logic [1:0][30:0] mem_araddr;
    logic [7:0] d_axi_arlen;
    logic [1:0][7:0] mem_arlen;
    logic [2:0] d_axi_arsize;
    logic [1:0][2:0] mem_arsize;
    logic [1:0] d_axi_arburst;
    logic [1:0][1:0] mem_arburst;
    logic d_axi_arlock;
    logic [1:0]mem_arlock;
    logic [3:0] d_axi_arcache;
    logic [1:0][3:0] mem_arcache;
    logic [2:0] d_axi_arprot;
    logic [1:0][2:0] mem_arprot;
    logic [3:0] d_axi_arqos;
    logic [1:0][3:0] mem_arqos;
    logic d_axi_arvalid;
    logic [1:0]mem_arvalid;
    logic d_axi_arready;
    logic [1:0]mem_arready;
    logic [511:0] d_axi_wdata;
    logic [1:0][511:0] mem_wdata;
    logic [63:0] d_axi_wstrb;
    logic [1:0][63:0] mem_wstrb;
    logic d_axi_wlast;
    logic [1:0]mem_wlast;
    logic d_axi_wvalid;
    logic [1:0]mem_wvalid;
    logic d_axi_wready;
    logic [1:0]mem_wready;
    logic [3:0] d_axi_bid;
    logic [1:0][3:0] mem_bid;
    logic [1:0] d_axi_bresp;
    logic [1:0][1:0] mem_bresp;
    logic d_axi_bvalid;
    logic [1:0]mem_bvalid;
    logic d_axi_bready;
    logic [1:0]mem_bready;
    logic [3:0] d_axi_rid;
    logic [1:0][3:0] mem_rid;
    logic [511:0] d_axi_rdata;
    logic [1:0][511:0] mem_rdata;
    logic [1:0] d_axi_rresp;
    logic [1:0][1:0] mem_rresp;
    logic d_axi_rlast;
    logic [1:0]mem_rlast;
    logic d_axi_rvalid;
    logic [1:0]mem_rvalid;
    logic d_axi_rready;
    logic [1:0]mem_rready;
    logic [31:0] d_ctrl_awaddr;
    logic d_ctrl_awvalid;
    logic d_ctrl_awready;
    logic [31:0] d_ctrl_wdata;
    logic d_ctrl_wvalid;
    logic d_ctrl_wready;
    logic [1:0] d_ctrl_bresp;
    logic d_ctrl_bvalid;
    logic d_ctrl_bready;
    logic [31:0] d_ctrl_araddr;
    logic d_ctrl_arvalid;
    logic d_ctrl_arready;
    logic [31:0] d_ctrl_rdata;
    logic [1:0] d_ctrl_rresp;
    logic d_ctrl_rvalid;
    logic d_ctrl_rready;
    logic [1:0]ctrl_awid;
    logic unused_ctrl_awid;
    logic [1:0][31:0] ctrl_awaddr;
    logic [1:0][7:0] ctrl_awlen;
    logic [7:0] unused_ctrl_awlen;
    logic [1:0][2:0] ctrl_awsize;
    logic [2:0] unused_ctrl_awsize;
    logic [1:0][1:0] ctrl_awburst;
    logic [1:0] unused_ctrl_awburst;
    logic [1:0]ctrl_awlock;
    logic unused_ctrl_awlock;
    logic [1:0][3:0] ctrl_awcache;
    logic [3:0] unused_ctrl_awcache;
    logic [1:0][2:0] ctrl_awprot;
    logic [2:0] unused_ctrl_awprot;
    logic [1:0][3:0] ctrl_awqos;
    logic [3:0] unused_ctrl_awqos;
    logic [1:0]ctrl_awvalid;
    logic [1:0]ctrl_awready;
    logic [1:0]ctrl_arid;
    logic unused_ctrl_arid;
    logic [1:0][31:0] ctrl_araddr;
    logic [1:0][7:0] ctrl_arlen;
    logic [7:0] unused_ctrl_arlen;
    logic [1:0][2:0] ctrl_arsize;
    logic [2:0] unused_ctrl_arsize;
    logic [1:0][1:0] ctrl_arburst;
    logic [1:0] unused_ctrl_arburst;
    logic [1:0]ctrl_arlock;
    logic unused_ctrl_arlock;
    logic [1:0][3:0] ctrl_arcache;
    logic [3:0] unused_ctrl_arcache;
    logic [1:0][2:0] ctrl_arprot;
    logic [2:0] unused_ctrl_arprot;
    logic [1:0][3:0] ctrl_arqos;
    logic [3:0] unused_ctrl_arqos;
    logic [1:0]ctrl_arvalid;
    logic [1:0]ctrl_arready;
    logic [1:0][31:0] ctrl_wdata;
    logic [1:0][3:0] ctrl_wstrb;
    logic [3:0] unused_ctrl_wstrb;
    logic [1:0]ctrl_wlast;
    logic unused_ctrl_wlast;
    logic [1:0]ctrl_wvalid;
    logic [1:0]ctrl_wready;
    logic [1:0]unused_return_ctrl_bid;
    logic unused_ctrl_bid;
    logic [1:0][1:0] ctrl_bresp;
    logic [1:0]ctrl_bvalid;
    logic [1:0]ctrl_bready;
    logic [1:0]unused_return_ctrl_rid;
    logic unused_ctrl_rid;
    logic [1:0][31:0] ctrl_rdata;
    logic [1:0][1:0] ctrl_rresp;
    logic [1:0]unused_return_ctrl_rlast;
    logic unused_ctrl_rlast;
    logic [1:0]ctrl_rvalid;
    logic [1:0]ctrl_rready;
    logic request_valid, request_ready, diagnostic_reset_n, diagnostic_exclusive;
    logic diagnostic_start_valid, diagnostic_start_ready, diagnostic_monitor_healthy;
    logic unused_bist_busy, bist_done, bist_fault, unused_bist_trial, handoff_allowed, normal_unrouted_request;
    logic [31:0] request_seed, diagnostic_seed, completed_writes, completed_reads;
    logic [31:0] unused_accepted_aw_count, unused_accepted_w_count, unused_accepted_b_count;
    logic [30:0] mismatch_address, last_completed_write_address;
    logic [511:0] mismatch_expected, mismatch_actual;
    logic [2:0] bist_fault_sources;
    logic [7:0] owner_fault_code, sweep_fault_code, adapter_fault_code, monitor_fault_code;
    // Normal data/ECC payloads and attributes pass unchanged; no fault gates.
    assign mem_awid[0]=n_axi_awid;
    assign mem_awid[1]=d_axi_awid;
    assign mem_awaddr[0]=n_axi_awaddr;
    assign mem_awaddr[1]=d_axi_awaddr;
    assign mem_awlen[0]=n_axi_awlen;
    assign mem_awlen[1]=d_axi_awlen;
    assign mem_awsize[0]=n_axi_awsize;
    assign mem_awsize[1]=d_axi_awsize;
    assign mem_awburst[0]=n_axi_awburst;
    assign mem_awburst[1]=d_axi_awburst;
    assign mem_awlock[0]=n_axi_awlock;
    assign mem_awlock[1]=d_axi_awlock;
    assign mem_awcache[0]=n_axi_awcache;
    assign mem_awcache[1]=d_axi_awcache;
    assign mem_awprot[0]=n_axi_awprot;
    assign mem_awprot[1]=d_axi_awprot;
    assign mem_awqos[0]=n_axi_awqos;
    assign mem_awqos[1]=d_axi_awqos;
    assign mem_awvalid[0]=n_axi_awvalid;
    assign mem_awvalid[1]=d_axi_awvalid;
    assign n_axi_awready=mem_awready[0];
    assign d_axi_awready=mem_awready[1];
    assign mem_arid[0]=n_axi_arid;
    assign mem_arid[1]=d_axi_arid;
    assign mem_araddr[0]=n_axi_araddr;
    assign mem_araddr[1]=d_axi_araddr;
    assign mem_arlen[0]=n_axi_arlen;
    assign mem_arlen[1]=d_axi_arlen;
    assign mem_arsize[0]=n_axi_arsize;
    assign mem_arsize[1]=d_axi_arsize;
    assign mem_arburst[0]=n_axi_arburst;
    assign mem_arburst[1]=d_axi_arburst;
    assign mem_arlock[0]=n_axi_arlock;
    assign mem_arlock[1]=d_axi_arlock;
    assign mem_arcache[0]=n_axi_arcache;
    assign mem_arcache[1]=d_axi_arcache;
    assign mem_arprot[0]=n_axi_arprot;
    assign mem_arprot[1]=d_axi_arprot;
    assign mem_arqos[0]=n_axi_arqos;
    assign mem_arqos[1]=d_axi_arqos;
    assign mem_arvalid[0]=n_axi_arvalid;
    assign mem_arvalid[1]=d_axi_arvalid;
    assign n_axi_arready=mem_arready[0];
    assign d_axi_arready=mem_arready[1];
    assign mem_wdata[0]=n_axi_wdata;
    assign mem_wdata[1]=d_axi_wdata;
    assign mem_wstrb[0]=n_axi_wstrb;
    assign mem_wstrb[1]=d_axi_wstrb;
    assign mem_wlast[0]=n_axi_wlast;
    assign mem_wlast[1]=d_axi_wlast;
    assign mem_wvalid[0]=n_axi_wvalid;
    assign mem_wvalid[1]=d_axi_wvalid;
    assign n_axi_wready=mem_wready[0];
    assign d_axi_wready=mem_wready[1];
    assign n_axi_bid=mem_bid[0];
    assign d_axi_bid=mem_bid[1];
    assign n_axi_bresp=mem_bresp[0];
    assign d_axi_bresp=mem_bresp[1];
    assign n_axi_bvalid=mem_bvalid[0];
    assign d_axi_bvalid=mem_bvalid[1];
    assign mem_bready[0]=n_axi_bready;
    assign mem_bready[1]=d_axi_bready;
    assign n_axi_rid=mem_rid[0];
    assign d_axi_rid=mem_rid[1];
    assign n_axi_rdata=mem_rdata[0];
    assign d_axi_rdata=mem_rdata[1];
    assign n_axi_rresp=mem_rresp[0];
    assign d_axi_rresp=mem_rresp[1];
    assign n_axi_rlast=mem_rlast[0];
    assign d_axi_rlast=mem_rlast[1];
    assign n_axi_rvalid=mem_rvalid[0];
    assign d_axi_rvalid=mem_rvalid[1];
    assign mem_rready[0]=n_axi_rready;
    assign mem_rready[1]=d_axi_rready;
    assign ctrl_awid={2{1'b0}};
    assign ctrl_awaddr[0]=n_ctrl_awaddr;
    assign ctrl_awaddr[1]=d_ctrl_awaddr;
    assign ctrl_awlen={2{8'b0}};
    assign ctrl_awsize={2{3'd2}};
    assign ctrl_awburst={2{2'b01}};
    assign ctrl_awlock={2{1'b0}};
    assign ctrl_awcache={2{4'b0}};
    assign ctrl_awprot={2{3'b0}};
    assign ctrl_awqos={2{4'b0}};
    assign ctrl_awvalid[0]=n_ctrl_awvalid;
    assign ctrl_awvalid[1]=d_ctrl_awvalid;
    assign n_ctrl_awready=ctrl_awready[0];
    assign d_ctrl_awready=ctrl_awready[1];
    assign ctrl_arid={2{1'b0}};
    assign ctrl_araddr[0]=n_ctrl_araddr;
    assign ctrl_araddr[1]=d_ctrl_araddr;
    assign ctrl_arlen={2{8'b0}};
    assign ctrl_arsize={2{3'd2}};
    assign ctrl_arburst={2{2'b01}};
    assign ctrl_arlock={2{1'b0}};
    assign ctrl_arcache={2{4'b0}};
    assign ctrl_arprot={2{3'b0}};
    assign ctrl_arqos={2{4'b0}};
    assign ctrl_arvalid[0]=n_ctrl_arvalid;
    assign ctrl_arvalid[1]=d_ctrl_arvalid;
    assign n_ctrl_arready=ctrl_arready[0];
    assign d_ctrl_arready=ctrl_arready[1];
    assign ctrl_wdata[0]=n_ctrl_wdata;
    assign ctrl_wdata[1]=d_ctrl_wdata;
    assign ctrl_wstrb={2{4'hf}};
    assign ctrl_wlast={2{1'b1}};
    assign ctrl_wvalid[0]=n_ctrl_wvalid;
    assign ctrl_wvalid[1]=d_ctrl_wvalid;
    assign n_ctrl_wready=ctrl_wready[0];
    assign d_ctrl_wready=ctrl_wready[1];
    assign n_ctrl_bresp=ctrl_bresp[0];
    assign d_ctrl_bresp=ctrl_bresp[1];
    assign n_ctrl_bvalid=ctrl_bvalid[0];
    assign d_ctrl_bvalid=ctrl_bvalid[1];
    assign ctrl_bready[0]=n_ctrl_bready;
    assign ctrl_bready[1]=d_ctrl_bready;
    assign n_ctrl_rdata=ctrl_rdata[0];
    assign d_ctrl_rdata=ctrl_rdata[1];
    assign n_ctrl_rresp=ctrl_rresp[0];
    assign d_ctrl_rresp=ctrl_rresp[1];
    assign n_ctrl_rvalid=ctrl_rvalid[0];
    assign d_ctrl_rvalid=ctrl_rvalid[1];
    assign ctrl_rready[0]=n_ctrl_rready;
    assign ctrl_rready[1]=d_ctrl_rready;
    assign unused_ctrl_bid=1'b0;
    assign unused_ctrl_rid=1'b0;
    assign unused_ctrl_rlast=1'b1;
    assign normal_unrouted_request=diagnostic_selected && (n_axi_awvalid || n_axi_wvalid ||
        n_axi_arvalid || n_ctrl_awvalid || n_ctrl_wvalid || n_ctrl_arvalid);
    assign handoff_allowed=initialization_complete===1'b1 && calibration_complete===1'b1 &&
        normal_monitor_healthy===1'b1 && normal_monitor_fault===1'b0 && normal_fabric_quiet===1'b1 &&
        normal_job_owned===1'b0 && normal_host_busy===1'b0 && normal_engine_pending===1'b0 && normal_pending_response===1'b0;
    rk_ddr_diagnostic_mux memory_mux (
        .joint_rst_n(joint_rst_n),
        .diagnostic_selected(diagnostic_selected),
        .s_axi_awid(mem_awid),
        .s_axi_awaddr(mem_awaddr),
        .s_axi_awlen(mem_awlen),
        .s_axi_awsize(mem_awsize),
        .s_axi_awburst(mem_awburst),
        .s_axi_awlock(mem_awlock),
        .s_axi_awcache(mem_awcache),
        .s_axi_awprot(mem_awprot),
        .s_axi_awqos(mem_awqos),
        .s_axi_awvalid(mem_awvalid),
        .s_axi_awready(mem_awready),
        .s_axi_arid(mem_arid),
        .s_axi_araddr(mem_araddr),
        .s_axi_arlen(mem_arlen),
        .s_axi_arsize(mem_arsize),
        .s_axi_arburst(mem_arburst),
        .s_axi_arlock(mem_arlock),
        .s_axi_arcache(mem_arcache),
        .s_axi_arprot(mem_arprot),
        .s_axi_arqos(mem_arqos),
        .s_axi_arvalid(mem_arvalid),
        .s_axi_arready(mem_arready),
        .s_axi_wdata(mem_wdata),
        .s_axi_wstrb(mem_wstrb),
        .s_axi_wlast(mem_wlast),
        .s_axi_wvalid(mem_wvalid),
        .s_axi_wready(mem_wready),
        .s_axi_bid(mem_bid),
        .s_axi_bresp(mem_bresp),
        .s_axi_bvalid(mem_bvalid),
        .s_axi_bready(mem_bready),
        .s_axi_rid(mem_rid),
        .s_axi_rdata(mem_rdata),
        .s_axi_rresp(mem_rresp),
        .s_axi_rlast(mem_rlast),
        .s_axi_rvalid(mem_rvalid),
        .s_axi_rready(mem_rready),
        .m_axi_awid(m_axi_awid),
        .m_axi_awaddr(m_axi_awaddr),
        .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst),
        .m_axi_awlock(m_axi_awlock),
        .m_axi_awcache(m_axi_awcache),
        .m_axi_awprot(m_axi_awprot),
        .m_axi_awqos(m_axi_awqos),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_awready(m_axi_awready),
        .m_axi_arid(m_axi_arid),
        .m_axi_araddr(m_axi_araddr),
        .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst),
        .m_axi_arlock(m_axi_arlock),
        .m_axi_arcache(m_axi_arcache),
        .m_axi_arprot(m_axi_arprot),
        .m_axi_arqos(m_axi_arqos),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready),
        .m_axi_wdata(m_axi_wdata),
        .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_wvalid(m_axi_wvalid),
        .m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid),
        .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid),
        .m_axi_bready(m_axi_bready),
        .m_axi_rid(m_axi_rid),
        .m_axi_rdata(m_axi_rdata),
        .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rready(m_axi_rready)
    );

    rk_ddr_diagnostic_mux #(.ADDR_WIDTH(32),.DATA_WIDTH(32),.ID_WIDTH(1)) control_mux (
        .joint_rst_n(joint_rst_n),
        .diagnostic_selected(diagnostic_selected),
        .s_axi_awid(ctrl_awid),
        .s_axi_awaddr(ctrl_awaddr),
        .s_axi_awlen(ctrl_awlen),
        .s_axi_awsize(ctrl_awsize),
        .s_axi_awburst(ctrl_awburst),
        .s_axi_awlock(ctrl_awlock),
        .s_axi_awcache(ctrl_awcache),
        .s_axi_awprot(ctrl_awprot),
        .s_axi_awqos(ctrl_awqos),
        .s_axi_awvalid(ctrl_awvalid),
        .s_axi_awready(ctrl_awready),
        .s_axi_arid(ctrl_arid),
        .s_axi_araddr(ctrl_araddr),
        .s_axi_arlen(ctrl_arlen),
        .s_axi_arsize(ctrl_arsize),
        .s_axi_arburst(ctrl_arburst),
        .s_axi_arlock(ctrl_arlock),
        .s_axi_arcache(ctrl_arcache),
        .s_axi_arprot(ctrl_arprot),
        .s_axi_arqos(ctrl_arqos),
        .s_axi_arvalid(ctrl_arvalid),
        .s_axi_arready(ctrl_arready),
        .s_axi_wdata(ctrl_wdata),
        .s_axi_wstrb(ctrl_wstrb),
        .s_axi_wlast(ctrl_wlast),
        .s_axi_wvalid(ctrl_wvalid),
        .s_axi_wready(ctrl_wready),
        .s_axi_bid(unused_return_ctrl_bid),
        .s_axi_bresp(ctrl_bresp),
        .s_axi_bvalid(ctrl_bvalid),
        .s_axi_bready(ctrl_bready),
        .s_axi_rid(unused_return_ctrl_rid),
        .s_axi_rdata(ctrl_rdata),
        .s_axi_rresp(ctrl_rresp),
        .s_axi_rlast(unused_return_ctrl_rlast),
        .s_axi_rvalid(ctrl_rvalid),
        .s_axi_rready(ctrl_rready),
        .m_axi_awid(unused_ctrl_awid),
        .m_axi_awaddr(m_axi_ctrl_awaddr),
        .m_axi_awlen(unused_ctrl_awlen),
        .m_axi_awsize(unused_ctrl_awsize),
        .m_axi_awburst(unused_ctrl_awburst),
        .m_axi_awlock(unused_ctrl_awlock),
        .m_axi_awcache(unused_ctrl_awcache),
        .m_axi_awprot(unused_ctrl_awprot),
        .m_axi_awqos(unused_ctrl_awqos),
        .m_axi_awvalid(m_axi_ctrl_awvalid),
        .m_axi_awready(m_axi_ctrl_awready),
        .m_axi_arid(unused_ctrl_arid),
        .m_axi_araddr(m_axi_ctrl_araddr),
        .m_axi_arlen(unused_ctrl_arlen),
        .m_axi_arsize(unused_ctrl_arsize),
        .m_axi_arburst(unused_ctrl_arburst),
        .m_axi_arlock(unused_ctrl_arlock),
        .m_axi_arcache(unused_ctrl_arcache),
        .m_axi_arprot(unused_ctrl_arprot),
        .m_axi_arqos(unused_ctrl_arqos),
        .m_axi_arvalid(m_axi_ctrl_arvalid),
        .m_axi_arready(m_axi_ctrl_arready),
        .m_axi_wdata(m_axi_ctrl_wdata),
        .m_axi_wstrb(unused_ctrl_wstrb),
        .m_axi_wlast(unused_ctrl_wlast),
        .m_axi_wvalid(m_axi_ctrl_wvalid),
        .m_axi_wready(m_axi_ctrl_wready),
        .m_axi_bid(unused_ctrl_bid),
        .m_axi_bresp(m_axi_ctrl_bresp),
        .m_axi_bvalid(m_axi_ctrl_bvalid),
        .m_axi_bready(m_axi_ctrl_bready),
        .m_axi_rid(unused_ctrl_rid),
        .m_axi_rdata(m_axi_ctrl_rdata),
        .m_axi_rresp(m_axi_ctrl_rresp),
        .m_axi_rlast(unused_ctrl_rlast),
        .m_axi_rvalid(m_axi_ctrl_rvalid),
        .m_axi_rready(m_axi_ctrl_rready)
    );

    rk_ddr_capacity_owner #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) owner (
        .clk(clk),
        .joint_rst_n(joint_rst_n),
        .request_valid(request_valid),
        .request_ready(request_ready),
        .request_seed(request_seed),
        .initialization_complete(initialization_complete),
        .calibration_complete(calibration_complete),
        .platform_monitor_healthy(normal_monitor_healthy),
        .platform_monitor_fault(normal_monitor_fault),
        .normal_fabric_quiet(normal_fabric_quiet),
        .normal_job_owned(normal_job_owned),
        .normal_host_busy(normal_host_busy),
        .normal_engine_pending(normal_engine_pending),
        .normal_pending_response(normal_pending_response),
        .normal_unrouted_request(normal_unrouted_request),
        .normal_admission_enable(normal_admission_enable),
        .normal_selected(normal_selected),
        .diagnostic_selected(diagnostic_selected),
        .diagnostic_reset_n(diagnostic_reset_n),
        .diagnostic_exclusive(diagnostic_exclusive),
        .diagnostic_start_valid(diagnostic_start_valid),
        .diagnostic_start_ready(diagnostic_start_ready),
        .diagnostic_seed(diagnostic_seed),
        .diagnostic_monitor_healthy(diagnostic_monitor_healthy),
        .diagnostic_done(bist_done),
        .diagnostic_fault(bist_fault),
        .busy(owner_busy),
        .done(owner_done),
        .fault(owner_fault),
        .fault_code(owner_fault_code),
        .bus_awvalid({m_axi_ctrl_awvalid,m_axi_awvalid}),
        .bus_awready({m_axi_ctrl_awready,m_axi_awready}),
        .bus_wvalid({m_axi_ctrl_wvalid,m_axi_wvalid}),
        .bus_wready({m_axi_ctrl_wready,m_axi_wready}),
        .bus_bvalid({m_axi_ctrl_bvalid,m_axi_bvalid}),
        .bus_bready({m_axi_ctrl_bready,m_axi_bready}),
        .bus_arvalid({m_axi_ctrl_arvalid,m_axi_arvalid}),
        .bus_arready({m_axi_ctrl_arready,m_axi_arready}),
        .bus_rvalid({m_axi_ctrl_rvalid,m_axi_rvalid}),
        .bus_rready({m_axi_ctrl_rready,m_axi_rready}),
        .bus_b_ok({(m_axi_ctrl_bresp===2'b00),(m_axi_bid===4'b0 && m_axi_bresp===2'b00)}),
        .bus_r_ok({(m_axi_ctrl_rresp===2'b00),(m_axi_rid===4'b0 && m_axi_rresp===2'b00 && m_axi_rlast===1'b1)})
    );

    rk_ddr_capacity_bist #(.BASE_ADDR(BASE_ADDR),.SPAN_BYTES(SPAN_BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) bist (
        .clk(clk),
        .joint_rst_n(diagnostic_reset_n),
        .initialization_complete(initialization_complete),
        .calibration_complete(calibration_complete),
        .owner_exclusive(diagnostic_exclusive),
        .mig_interrupt(mig_interrupt),
        .start_valid(diagnostic_start_valid),
        .start_ready(diagnostic_start_ready),
        .seed(diagnostic_seed),
        .busy(unused_bist_busy),
        .done(bist_done),
        .fault(bist_fault),
        .trial(unused_bist_trial),
        .fault_sources(bist_fault_sources),
        .monitor_healthy(diagnostic_monitor_healthy),
        .sweep_fault_code(sweep_fault_code),
        .adapter_fault_code(adapter_fault_code),
        .monitor_fault_code(monitor_fault_code),
        .completed_writes(completed_writes),
        .completed_reads(completed_reads),
        .accepted_aw_count(unused_accepted_aw_count),
        .accepted_w_count(unused_accepted_w_count),
        .accepted_b_count(unused_accepted_b_count),
        .mismatch_address(mismatch_address),
        .last_completed_write_address(last_completed_write_address),
        .mismatch_expected(mismatch_expected),
        .mismatch_actual(mismatch_actual),
        .m_axi_awid(d_axi_awid),
        .m_axi_awaddr(d_axi_awaddr),
        .m_axi_awlen(d_axi_awlen),
        .m_axi_awsize(d_axi_awsize),
        .m_axi_awburst(d_axi_awburst),
        .m_axi_awlock(d_axi_awlock),
        .m_axi_awcache(d_axi_awcache),
        .m_axi_awprot(d_axi_awprot),
        .m_axi_awqos(d_axi_awqos),
        .m_axi_awvalid(d_axi_awvalid),
        .m_axi_awready(d_axi_awready),
        .m_axi_arid(d_axi_arid),
        .m_axi_araddr(d_axi_araddr),
        .m_axi_arlen(d_axi_arlen),
        .m_axi_arsize(d_axi_arsize),
        .m_axi_arburst(d_axi_arburst),
        .m_axi_arlock(d_axi_arlock),
        .m_axi_arcache(d_axi_arcache),
        .m_axi_arprot(d_axi_arprot),
        .m_axi_arqos(d_axi_arqos),
        .m_axi_arvalid(d_axi_arvalid),
        .m_axi_arready(d_axi_arready),
        .m_axi_wdata(d_axi_wdata),
        .m_axi_wstrb(d_axi_wstrb),
        .m_axi_wlast(d_axi_wlast),
        .m_axi_wvalid(d_axi_wvalid),
        .m_axi_wready(d_axi_wready),
        .m_axi_bid(d_axi_bid),
        .m_axi_bresp(d_axi_bresp),
        .m_axi_bvalid(d_axi_bvalid),
        .m_axi_bready(d_axi_bready),
        .m_axi_rid(d_axi_rid),
        .m_axi_rdata(d_axi_rdata),
        .m_axi_rresp(d_axi_rresp),
        .m_axi_rlast(d_axi_rlast),
        .m_axi_rvalid(d_axi_rvalid),
        .m_axi_rready(d_axi_rready),
        .m_axi_ctrl_awaddr(d_ctrl_awaddr),
        .m_axi_ctrl_awvalid(d_ctrl_awvalid),
        .m_axi_ctrl_awready(d_ctrl_awready),
        .m_axi_ctrl_wdata(d_ctrl_wdata),
        .m_axi_ctrl_wvalid(d_ctrl_wvalid),
        .m_axi_ctrl_wready(d_ctrl_wready),
        .m_axi_ctrl_bresp(d_ctrl_bresp),
        .m_axi_ctrl_bvalid(d_ctrl_bvalid),
        .m_axi_ctrl_bready(d_ctrl_bready),
        .m_axi_ctrl_araddr(d_ctrl_araddr),
        .m_axi_ctrl_arvalid(d_ctrl_arvalid),
        .m_axi_ctrl_arready(d_ctrl_arready),
        .m_axi_ctrl_rdata(d_ctrl_rdata),
        .m_axi_ctrl_rresp(d_ctrl_rresp),
        .m_axi_ctrl_rvalid(d_ctrl_rvalid),
        .m_axi_ctrl_rready(d_ctrl_rready)
    );

    rk_ddr_capacity_regs #(.BASE_ADDR(BASE_ADDR),.SPAN_BYTES(SPAN_BYTES)) registers (
        .clk(clk),
        .joint_rst_n(joint_rst_n),
        .s_axil_awaddr(s_axil_awaddr),
        .s_axil_awprot(s_axil_awprot),
        .s_axil_awvalid(s_axil_awvalid),
        .s_axil_awready(s_axil_awready),
        .s_axil_wdata(s_axil_wdata),
        .s_axil_wstrb(s_axil_wstrb),
        .s_axil_wvalid(s_axil_wvalid),
        .s_axil_wready(s_axil_wready),
        .s_axil_bresp(s_axil_bresp),
        .s_axil_bvalid(s_axil_bvalid),
        .s_axil_bready(s_axil_bready),
        .s_axil_araddr(s_axil_araddr),
        .s_axil_arprot(s_axil_arprot),
        .s_axil_arvalid(s_axil_arvalid),
        .s_axil_arready(s_axil_arready),
        .s_axil_rdata(s_axil_rdata),
        .s_axil_rresp(s_axil_rresp),
        .s_axil_rvalid(s_axil_rvalid),
        .s_axil_rready(s_axil_rready),
        .request_valid(request_valid),
        .request_ready(request_ready),
        .request_seed(request_seed),
        .handoff_allowed(handoff_allowed),
        .owner_busy(owner_busy),
        .owner_done(owner_done),
        .diagnostic_selected(diagnostic_selected),
        .completed_writes(completed_writes),
        .completed_reads(completed_reads),
        .mismatch_address(mismatch_address),
        .last_completed_write_address(last_completed_write_address),
        .mismatch_expected(mismatch_expected),
        .mismatch_actual(mismatch_actual),
        .owner_fault(owner_fault || bist_fault),
        .fault_sources(bist_fault_sources),
        .fault_codes({owner_fault_code,sweep_fault_code,adapter_fault_code,monitor_fault_code})
    );

endmodule
