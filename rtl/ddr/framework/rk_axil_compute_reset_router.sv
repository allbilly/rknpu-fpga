// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Private management/control router. Slave0 is the unchanged normal EW/CMAC
// control bank; slave1 is the RKRS compute-reset bank. Only full addresses
// 0x00000500..0x000005ff route to slave1. All others reach the existing normal
// decoder unchanged, retaining its unsupported-address failures.
// AR is transparent until its handshake, preserving the selected leaf's
// AR-time snapshot. W may precede AW and is buffered without altering bits.
// Address/protection stay captured through B/R for the existing normal bank
// decoder, which observes its address until the response handshake.
// One write and one independent read may be outstanding. No fault/status
// input cancels VALID or a held response; only whole-domain reset cancels.
module rk_axil_compute_reset_router (
    input logic clk, joint_rst_n,
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
    input logic s_axil_rready,

    output logic [1:0][31:0] m_axil_awaddr,
    output logic [1:0][2:0] m_axil_awprot,
    output logic [1:0] m_axil_awvalid,
    input logic [1:0] m_axil_awready,
    output logic [1:0][31:0] m_axil_wdata,
    output logic [1:0][3:0] m_axil_wstrb,
    output logic [1:0] m_axil_wvalid,
    input logic [1:0] m_axil_wready,
    input logic [1:0][1:0] m_axil_bresp,
    input logic [1:0] m_axil_bvalid,
    output logic [1:0] m_axil_bready,
    output logic [1:0][31:0] m_axil_araddr,
    output logic [1:0][2:0] m_axil_arprot,
    output logic [1:0] m_axil_arvalid,
    input logic [1:0] m_axil_arready,
    input logic [1:0][31:0] m_axil_rdata,
    input logic [1:0][1:0] m_axil_rresp,
    input logic [1:0] m_axil_rvalid,
    output logic [1:0] m_axil_rready
);
    logic aw_target, ar_target, write_target, read_target;
    logic aw_sent, w_sent, w_buffered, read_pending;
    logic [31:0] captured_wdata, captured_awaddr, captured_araddr;
    logic [2:0] captured_awprot, captured_arprot;
    logic [3:0] captured_wstrb;
    assign aw_target=s_axil_awaddr[31:8]===24'h000005;
    assign ar_target=s_axil_araddr[31:8]===24'h000005;
    assign m_axil_awaddr={2{aw_sent ? captured_awaddr : s_axil_awaddr}};
    assign m_axil_awprot={2{aw_sent ? captured_awprot : s_axil_awprot}};
    assign m_axil_wdata={2{captured_wdata}};
    assign m_axil_wstrb={2{captured_wstrb}};
    assign m_axil_araddr={2{read_pending ? captured_araddr : s_axil_araddr}};
    assign m_axil_arprot={2{read_pending ? captured_arprot : s_axil_arprot}};
    assign s_axil_wready=joint_rst_n && !w_buffered && !w_sent;
    always_comb begin
        m_axil_awvalid=0; m_axil_wvalid=0; m_axil_bready=0;
        m_axil_arvalid=0; m_axil_rready=0;
        s_axil_awready=0; s_axil_bvalid=0; s_axil_bresp=0;
        s_axil_arready=0; s_axil_rvalid=0; s_axil_rdata=0; s_axil_rresp=0;
        if (joint_rst_n) begin
            if (!aw_sent) begin
                m_axil_awvalid[aw_target]=s_axil_awvalid;
                s_axil_awready=m_axil_awready[aw_target];
            end
            if (aw_sent && w_buffered && !w_sent)
                m_axil_wvalid[write_target]=1;
            if (aw_sent && w_sent) begin
                s_axil_bvalid=m_axil_bvalid[write_target];
                s_axil_bresp=m_axil_bresp[write_target];
                m_axil_bready[write_target]=s_axil_bready;
            end
            if (!read_pending) begin
                m_axil_arvalid[ar_target]=s_axil_arvalid;
                s_axil_arready=m_axil_arready[ar_target];
            end else begin
                s_axil_rvalid=m_axil_rvalid[read_target];
                s_axil_rdata=m_axil_rdata[read_target];
                s_axil_rresp=m_axil_rresp[read_target];
                m_axil_rready[read_target]=s_axil_rready;
            end
        end
    end
    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            write_target<=0; read_target<=0; aw_sent<=0; w_sent<=0;
            w_buffered<=0; read_pending<=0; captured_wdata<=0; captured_wstrb<=0;
            captured_awaddr<=0; captured_araddr<=0; captured_awprot<=0; captured_arprot<=0;
        end else begin
            if (s_axil_awvalid && s_axil_awready) begin aw_sent<=1; write_target<=aw_target;
                captured_awaddr<=s_axil_awaddr; captured_awprot<=s_axil_awprot; end
            if (s_axil_wvalid && s_axil_wready) begin
                captured_wdata<=s_axil_wdata; captured_wstrb<=s_axil_wstrb; w_buffered<=1;
            end
            if (aw_sent && w_buffered && m_axil_wvalid[write_target] && m_axil_wready[write_target]) begin
                w_sent<=1; w_buffered<=0;
            end
            if (s_axil_bvalid && s_axil_bready) begin aw_sent<=0; w_sent<=0; end
            if (s_axil_arvalid && s_axil_arready) begin read_pending<=1; read_target<=ar_target;
                captured_araddr<=s_axil_araddr; captured_arprot<=s_axil_arprot; end
            if (s_axil_rvalid && s_axil_rready) read_pending<=0;
        end
    end
endmodule
