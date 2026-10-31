// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One retained UI clock: PCIe BAR-path mailbox + raw JTAG source + ownership.
// External PCIe/CDC/link-reset integration must preserve this transaction epoch.
module rk_pcie_jtag_maintenance_frontend (
    input wire clk,power_rst_n,rst_n,maintenance_block,backend_drained,
    input wire release_ready,jtag_link_healthy,pcie_link_healthy,
    input wire [31:0] s_axil_awaddr,
    input wire [2:0] s_axil_awprot,
    input wire s_axil_awvalid,
    output wire s_axil_awready,
    input wire [31:0] s_axil_wdata,
    input wire [3:0] s_axil_wstrb,
    input wire s_axil_wvalid,
    output wire s_axil_wready,
    output wire [1:0] s_axil_bresp,
    output wire s_axil_bvalid,
    input wire s_axil_bready,
    input wire [31:0] s_axil_araddr,
    input wire [2:0] s_axil_arprot,
    input wire s_axil_arvalid,
    output wire s_axil_arready,
    output wire [31:0] s_axil_rdata,
    output wire [1:0] s_axil_rresp,
    output wire s_axil_rvalid,
    input wire s_axil_rready,
    input wire jtag_req_valid,
    output wire jtag_req_ready,
    input wire [603:0] jtag_req,
    output wire jtag_rsp_valid,
    output wire [511:0] jtag_rsp_data,
    output wire [7:0] jtag_rsp_status,
    output wire [15:0] jtag_rsp_seq,
    output wire m_req_valid,
    input wire m_req_ready,
    output wire [603:0] m_req,
    input wire m_rsp_valid,
    input wire [511:0] m_rsp_data,
    input wire [7:0] m_rsp_status,
    input wire [15:0] m_rsp_seq,
    output wire [1:0] owner,
    output wire [31:0] lease_epoch,
    output wire pcie_irq,pcie_protocol_fault,pcie_epoch_fault,owner_protocol_fault,
    output wire [7:0] owner_failure_code,
    output wire maintenance_quiet,maintenance_fault
);
    wire packet_req_valid,packet_req_ready,packet_rsp_valid,mailbox_irq;
    wire [603:0] packet_req;
    wire [511:0] packet_rsp_data;
    wire [7:0] packet_rsp_status;
    wire [15:0] packet_rsp_seq;
    wire packet_quiet,sessions_quiet;
    wire pcie_epoch_ready,pcie_seen_up;
    wire packet_admission,axi_sealed,axi_seal_fault;
    wire [1:0] gate_sealed,gate_fault;
    wire [1:0] requests_valid,requests_ready,responses_valid;
    wire [1:0][603:0] requests;
    wire [1:0][511:0] responses_data;
    wire [1:0][7:0] responses_status;
    wire [1:0][15:0] responses_seq;
    wire parent_drained=(packet_quiet===1'b1)&&(sessions_quiet===1'b1)&&
        (backend_drained===1'b1);
    assign maintenance_fault=axi_seal_fault||(|gate_fault);
    assign maintenance_quiet=(power_rst_n===1'b1)&&(maintenance_block===1'b1)&&
        (axi_sealed===1'b1)&&(gate_sealed===2'b11)&&
        (parent_drained===1'b1)&&(maintenance_fault===1'b0);
    assign pcie_irq=mailbox_irq||owner_protocol_fault||pcie_epoch_fault||maintenance_fault;

    wire [31:0] p_awaddr,p_wdata,p_araddr,p_rdata;
    wire [2:0] p_awprot,p_arprot;
    wire [3:0] p_wstrb;
    wire [1:0] p_bresp,p_rresp;
    wire p_awvalid,p_awready,p_wvalid,p_wready,p_bvalid,p_bready;
    wire p_arvalid,p_arready,p_rvalid,p_rready;
    rk_axil_maintenance_seal bus_seal (
        .clk(clk),.power_rst_n(power_rst_n),.ui_clients_rst_n(rst_n),
        .admission_block(maintenance_block),
        .drain_ready(parent_drained&&(&gate_sealed)),
        .packet_admission_enable(packet_admission),.sealed_quiet(axi_sealed),.seal_fault(axi_seal_fault),
        .s_awaddr(s_axil_awaddr),.s_awprot(s_axil_awprot),.s_awvalid(s_axil_awvalid),.s_awready(s_axil_awready),
        .s_wdata(s_axil_wdata),.s_wstrb(s_axil_wstrb),.s_wvalid(s_axil_wvalid),.s_wready(s_axil_wready),
        .s_bresp(s_axil_bresp),.s_bvalid(s_axil_bvalid),.s_bready(s_axil_bready),
        .s_araddr(s_axil_araddr),.s_arprot(s_axil_arprot),.s_arvalid(s_axil_arvalid),.s_arready(s_axil_arready),
        .s_rdata(s_axil_rdata),.s_rresp(s_axil_rresp),.s_rvalid(s_axil_rvalid),.s_rready(s_axil_rready),
        .m_awaddr(p_awaddr),.m_awprot(p_awprot),.m_awvalid(p_awvalid),.m_awready(p_awready),
        .m_wdata(p_wdata),.m_wstrb(p_wstrb),.m_wvalid(p_wvalid),.m_wready(p_wready),
        .m_bresp(p_bresp),.m_bvalid(p_bvalid),.m_bready(p_bready),
        .m_araddr(p_araddr),.m_arprot(p_arprot),.m_arvalid(p_arvalid),.m_arready(p_arready),
        .m_rdata(p_rdata),.m_rresp(p_rresp),.m_rvalid(p_rvalid),.m_rready(p_rready)
    );
    rk_transport_epoch_guard pcie_epoch (
        .clk(clk),.rst_n(rst_n),.up(pcie_link_healthy),.ready(pcie_epoch_ready),
        .failed(pcie_epoch_fault),.seen_up(pcie_seen_up)
    );
    wire [1:0] health={pcie_epoch_ready&&pcie_seen_up&&!pcie_protocol_fault,jtag_link_healthy};
    rk_axil_frame_mailbox_maintenance pcie_packets (
        .clk(clk),.rst_n(rst_n),
        .admission_enable(pcie_epoch_ready&&pcie_seen_up&&packet_admission),
        .s_axil_awaddr(p_awaddr),.s_axil_awprot(p_awprot),.s_axil_awvalid(p_awvalid),.s_axil_awready(p_awready),
        .s_axil_wdata(p_wdata),.s_axil_wstrb(p_wstrb),.s_axil_wvalid(p_wvalid),.s_axil_wready(p_wready),
        .s_axil_bresp(p_bresp),.s_axil_bvalid(p_bvalid),.s_axil_bready(p_bready),
        .s_axil_araddr(p_araddr),.s_axil_arprot(p_arprot),.s_axil_arvalid(p_arvalid),.s_axil_arready(p_arready),
        .s_axil_rdata(p_rdata),.s_axil_rresp(p_rresp),.s_axil_rvalid(p_rvalid),.s_axil_rready(p_rready),
        .req_valid(packet_req_valid),.req_ready(packet_req_ready),.req(packet_req),
        .rsp_valid(packet_rsp_valid),.rsp_data(packet_rsp_data),.rsp_status(packet_rsp_status),.rsp_seq(packet_rsp_seq),
        .irq(mailbox_irq),.protocol_fault(pcie_protocol_fault),.transaction_quiet(packet_quiet)
    );
    rk_whole_reset_frame_gate jtag_gate (
        .ui_clk(clk),.power_rst_n(power_rst_n),.ui_clients_rst_n(rst_n),
        .admission_block(maintenance_block),.parent_drained(parent_drained),
        .s_req_valid(jtag_req_valid),.s_req_ready(jtag_req_ready),.s_req(jtag_req),
        .s_rsp_valid(jtag_rsp_valid),.s_rsp_data(jtag_rsp_data),.s_rsp_status(jtag_rsp_status),.s_rsp_seq(jtag_rsp_seq),
        .m_req_valid(requests_valid[0]),.m_req_ready(requests_ready[0]),.m_req(requests[0]),
        .m_rsp_valid(responses_valid[0]),.m_rsp_data(responses_data[0]),.m_rsp_status(responses_status[0]),.m_rsp_seq(responses_seq[0]),
        .sealed_quiet(gate_sealed[0]),.gate_fault(gate_fault[0])
    );
    rk_whole_reset_frame_gate pcie_gate (
        .ui_clk(clk),.power_rst_n(power_rst_n),.ui_clients_rst_n(rst_n),
        .admission_block(maintenance_block),.parent_drained(parent_drained),
        .s_req_valid(packet_req_valid),.s_req_ready(packet_req_ready),.s_req(packet_req),
        .s_rsp_valid(packet_rsp_valid),.s_rsp_data(packet_rsp_data),.s_rsp_status(packet_rsp_status),.s_rsp_seq(packet_rsp_seq),
        .m_req_valid(requests_valid[1]),.m_req_ready(requests_ready[1]),.m_req(requests[1]),
        .m_rsp_valid(responses_valid[1]),.m_rsp_data(responses_data[1]),.m_rsp_status(responses_status[1]),.m_rsp_seq(responses_seq[1]),
        .sealed_quiet(gate_sealed[1]),.gate_fault(gate_fault[1])
    );
    rk_raw_frame_owner_mux_maintenance sessions (
        .clk(clk),.rst_n(rst_n),.release_ready(release_ready),.link_healthy(health),
        .s_req_valid(requests_valid),.s_req_ready(requests_ready),.s_req(requests),
        .s_rsp_valid(responses_valid),.s_rsp_data(responses_data),.s_rsp_status(responses_status),.s_rsp_seq(responses_seq),
        .m_req_valid(m_req_valid),.m_req_ready(m_req_ready),.m_req(m_req),
        .m_rsp_valid(m_rsp_valid),.m_rsp_data(m_rsp_data),.m_rsp_status(m_rsp_status),.m_rsp_seq(m_rsp_seq),
        .owner(owner),.lease_epoch(lease_epoch),.failed(owner_protocol_fault),.failure_code(owner_failure_code),
        .transaction_quiet(sessions_quiet)
    );
endmodule
