// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One retained UI clock: PCIe BAR-path mailbox + raw JTAG source + ownership.
// External PCIe/CDC/link-reset integration must preserve this transaction epoch.
module rk_pcie_jtag_frame_frontend (
    input wire clk,rst_n,release_ready,jtag_link_healthy,pcie_link_healthy,
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
    output wire [7:0] owner_failure_code
);
    wire pcie_req_valid,pcie_req_ready,mailbox_irq;
    wire [603:0] pcie_req;
    wire [1:0] requests_valid,requests_ready,responses_valid;
    wire [1:0][603:0] requests;
    wire [1:0][511:0] responses_data;
    wire [1:0][7:0] responses_status;
    wire [1:0][15:0] responses_seq;
    wire pcie_epoch_ready,pcie_seen_up;
    rk_transport_epoch_guard pcie_epoch (
        .clk(clk),.rst_n(rst_n),.up(pcie_link_healthy),.ready(pcie_epoch_ready),
        .failed(pcie_epoch_fault),.seen_up(pcie_seen_up)
    );
    wire [1:0] health={pcie_epoch_ready&&pcie_seen_up&&!pcie_protocol_fault,jtag_link_healthy};
    assign requests_valid={pcie_req_valid,jtag_req_valid};
    assign requests={pcie_req,jtag_req};
    assign jtag_req_ready=requests_ready[0];
    assign pcie_req_ready=requests_ready[1];
    assign jtag_rsp_valid=responses_valid[0];
    assign jtag_rsp_data=responses_data[0];
    assign jtag_rsp_status=responses_status[0];
    assign jtag_rsp_seq=responses_seq[0];
    assign pcie_irq=mailbox_irq||owner_protocol_fault||pcie_epoch_fault;
    rk_axil_frame_mailbox pcie_packets (
        .admission_enable(pcie_epoch_ready&&pcie_seen_up),
        .req_valid(pcie_req_valid),.req_ready(pcie_req_ready),.req(pcie_req),
        .rsp_valid(responses_valid[1]),.rsp_data(responses_data[1]),
        .rsp_status(responses_status[1]),.rsp_seq(responses_seq[1]),
        .irq(mailbox_irq),.protocol_fault(pcie_protocol_fault),.*
    );
    rk_raw_frame_owner_mux sessions (
        .link_healthy(health),.s_req_valid(requests_valid),.s_req_ready(requests_ready),.s_req(requests),
        .s_rsp_valid(responses_valid),.s_rsp_data(responses_data),
        .s_rsp_status(responses_status),.s_rsp_seq(responses_seq),
        .failed(owner_protocol_fault),.failure_code(owner_failure_code),.*
    );
endmodule
