// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Minimal explicit-failure AXI4-Lite slave for unmapped addresses.
//
// A host access to an address this image does not decode must complete with
// SLVERR, not stall forever and not silently alias another page. This slave
// accepts one AW/W pair and one AR at a time and always answers SLVERR.
//
// It deliberately has no registers, no side effects and no write data storage:
// the only observable behaviour is the error response.
module rk_axil_error_slave (
    input  logic        clk,
    input  logic        rst_n,
    input  logic [31:0] s_axil_awaddr,
    input  logic [2:0]  s_axil_awprot,
    input  logic        s_axil_awvalid,
    output logic        s_axil_awready,
    input  logic [31:0] s_axil_wdata,
    input  logic [3:0]  s_axil_wstrb,
    input  logic        s_axil_wvalid,
    output logic        s_axil_wready,
    output logic [1:0]  s_axil_bresp,
    output logic        s_axil_bvalid,
    input  logic        s_axil_bready,
    input  logic [31:0] s_axil_araddr,
    input  logic [2:0]  s_axil_arprot,
    input  logic        s_axil_arvalid,
    output logic        s_axil_arready,
    output logic [31:0] s_axil_rdata,
    output logic [1:0]  s_axil_rresp,
    output logic        s_axil_rvalid,
    input  logic        s_axil_rready
);
    logic aw_pending_q, w_pending_q, bvalid_q, rvalid_q;

    assign s_axil_awready = rst_n && !aw_pending_q && !bvalid_q;
    assign s_axil_wready = rst_n && !w_pending_q && !bvalid_q;
    assign s_axil_arready = rst_n && !rvalid_q;
    assign s_axil_bvalid = rst_n && bvalid_q;
    assign s_axil_rvalid = rst_n && rvalid_q;
    assign s_axil_bresp = 2'b10;   // SLVERR: the address is not implemented
    assign s_axil_rresp = 2'b10;
    assign s_axil_rdata = 32'd0;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            aw_pending_q <= 1'b0;
            w_pending_q <= 1'b0;
            bvalid_q <= 1'b0;
            rvalid_q <= 1'b0;
        end else begin
            if (s_axil_bvalid && s_axil_bready) bvalid_q <= 1'b0;
            if (s_axil_rvalid && s_axil_rready) rvalid_q <= 1'b0;
            if (s_axil_awvalid && s_axil_awready) aw_pending_q <= 1'b1;
            if (s_axil_wvalid && s_axil_wready) w_pending_q <= 1'b1;
            if (aw_pending_q && w_pending_q && !bvalid_q) begin
                aw_pending_q <= 1'b0;
                w_pending_q <= 1'b0;
                bvalid_q <= 1'b1;
            end
            if (s_axil_arvalid && s_axil_arready) rvalid_q <= 1'b1;
        end
    end

    // The addresses and write data are intentionally unused: nothing is mapped
    // here, and an error response is the only correct outcome.
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused = &{1'b1, s_axil_awaddr, s_axil_awprot, s_axil_wdata,
                    s_axil_wstrb, s_axil_araddr, s_axil_arprot};
    /* verilator lint_on UNUSEDSIGNAL */
endmodule
