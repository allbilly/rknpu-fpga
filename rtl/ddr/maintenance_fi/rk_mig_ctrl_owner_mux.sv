// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Source-specific, one-outstanding AXI-Lite control ownership. Index 0 is the
// ordinary strict ECC monitor; index 1 is the FI service. This is not a generic
// pipelined AXI interconnect. Owner changes only at an empty transaction boundary.
module rk_mig_ctrl_owner_mux (
    input logic clk, joint_rst_n,
    input logic fi_owner_request, fi_take_safe, normal_yield_ready,
    input logic fi_busy, fi_release_safe,
    output logic fi_owner_granted, normal_owner_granted, port_idle,
    output logic fault,
    output logic [7:0] fault_code,
    input logic [1:0][31:0] s_awaddr, s_wdata, s_araddr,
    input logic [1:0] s_awvalid, s_wvalid, s_bready, s_arvalid, s_rready,
    output logic [1:0] s_awready, s_wready, s_bvalid, s_arready, s_rvalid,
    output logic [1:0][1:0] s_bresp, s_rresp,
    output logic [1:0][31:0] s_rdata,
    output logic [31:0] m_awaddr, m_wdata, m_araddr,
    output logic m_awvalid, m_wvalid, m_bready, m_arvalid, m_rready,
    input logic m_awready, m_wready, m_bvalid, m_arready, m_rvalid,
    input logic [1:0] m_bresp, m_rresp,
    input logic [31:0] m_rdata
);
    logic owner_fi, aw_seen, w_seen, r_seen;
    logic aw_take, w_take, b_take, ar_take, r_take;
    logic [7:0] cause;

    assign fi_owner_granted = joint_rst_n && owner_fi;
    assign normal_owner_granted = joint_rst_n && !owner_fi;
    assign m_awaddr = s_awaddr[owner_fi];
    assign m_wdata = s_wdata[owner_fi];
    assign m_araddr = s_araddr[owner_fi];
    // A fault retains the mux/grant and never withdraws an accepted owner's
    // outstanding VALID/payload. Admission of fresh work is the caller's duty.
    assign m_awvalid = joint_rst_n && s_awvalid[owner_fi];
    assign m_wvalid = joint_rst_n && s_wvalid[owner_fi];
    assign m_bready = joint_rst_n && s_bready[owner_fi];
    assign m_arvalid = joint_rst_n && s_arvalid[owner_fi];
    assign m_rready = joint_rst_n && s_rready[owner_fi];
    assign aw_take = m_awvalid && m_awready;
    assign w_take = m_wvalid && m_wready;
    assign b_take = m_bvalid && m_bready;
    assign ar_take = m_arvalid && m_arready;
    assign r_take = m_rvalid && m_rready;
    assign port_idle = joint_rst_n && !aw_seen && !w_seen && !r_seen &&
                       s_awvalid[owner_fi] === 1'b0 && s_wvalid[owner_fi] === 1'b0 &&
                       s_arvalid[owner_fi] === 1'b0 && m_bvalid === 1'b0 && m_rvalid === 1'b0;

    always_comb begin
        s_awready = 0; s_wready = 0; s_bvalid = 0;
        s_arready = 0; s_rvalid = 0;
        s_bresp = 0; s_rresp = 0; s_rdata = 0;
        if (joint_rst_n) begin
            s_awready[owner_fi] = m_awready;
            s_wready[owner_fi] = m_wready;
            s_bvalid[owner_fi] = m_bvalid;
            s_bresp[owner_fi] = m_bresp;
            s_arready[owner_fi] = m_arready;
            s_rvalid[owner_fi] = m_rvalid;
            s_rresp[owner_fi] = m_rresp;
            s_rdata[owner_fi] = m_rdata;
        end
        cause = 0;
        if ((fi_owner_request !== 1'b0 && fi_owner_request !== 1'b1) ||
            (m_awvalid !== 1'b0 && m_awvalid !== 1'b1) ||
            (m_wvalid !== 1'b0 && m_wvalid !== 1'b1) ||
            (m_arvalid !== 1'b0 && m_arvalid !== 1'b1)) cause = 8'd1;
        else if ((aw_take && (aw_seen || r_seen)) || (w_take && (w_seen || r_seen)) ||
                 (m_bvalid !== 1'b0 && (m_bvalid !== 1'b1 || !aw_seen || !w_seen || r_seen))) cause = 8'd2;
        else if ((ar_take && (r_seen || aw_seen || w_seen || aw_take || w_take)) ||
                 (m_rvalid !== 1'b0 && (m_rvalid !== 1'b1 || !r_seen || aw_seen || w_seen))) cause = 8'd3;
        else if ((m_bvalid === 1'b1 && m_bresp !== 2'b00) ||
                 (m_rvalid === 1'b1 && m_rresp !== 2'b00)) cause = 8'd4;
    end

    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            owner_fi <= 1; aw_seen <= 0; w_seen <= 0; r_seen <= 0;
            fault <= 0; fault_code <= 0;
        end else begin
            if (aw_take) aw_seen <= 1;
            if (w_take) w_seen <= 1;
            if (b_take) begin aw_seen <= 0; w_seen <= 0; end
            if (ar_take) r_seen <= 1;
            if (r_take) r_seen <= 0;
            if (!fault && cause != 0) begin fault <= 1; fault_code <= cause; end
            if (!fault && cause == 0 && port_idle) begin
                if (owner_fi) begin
                    if (fi_owner_request === 1'b0 && fi_busy === 1'b0 && fi_release_safe === 1'b1)
                        owner_fi <= 0;
                end else if (fi_owner_request === 1'b1 && fi_take_safe === 1'b1 && normal_yield_ready === 1'b1)
                    owner_fi <= 1;
            end
        end
    end
endmodule
