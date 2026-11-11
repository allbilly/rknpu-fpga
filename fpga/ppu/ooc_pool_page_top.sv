// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// LAB-ONLY out-of-context wrapper for one pooling-corpus page.
//
// Used by tools/ppu/ooc_pool_fit.py to measure the per-page synthesis cost of
// `rk_ppu_pool_corpus_axi` on a heat-marginal host where a whole-image synth
// times out the thermal guard. It is NOT part of the image source list and is
// never built into a bitstream.
module ooc_pool_page_top #(
    parameter int unsigned CASE = 0
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        memory_ready,
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
    output wire        irq,
    output wire        busy,
    output wire        mem_req_valid,
    input  wire        mem_req_ready,
    output wire        mem_req_write,
    output wire [31:0] mem_req_addr,
    output wire [15:0] mem_req_wdata,
    input  wire        mem_rsp_valid,
    output wire        mem_rsp_ready,
    input  wire [15:0] mem_rsp_rdata,
    input  wire        mem_rsp_error
);
    rk_ppu_pool_corpus_axi #(
        .CASE(CASE), .BASE(32'h0000_0000), .BYTES(33'd32768),
        .TIMEOUT_CYCLES(65536)
    ) page (
        .clk, .rst_n, .memory_ready,
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready,
        .irq, .busy,
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata,
        .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata, .mem_rsp_error
    );
endmodule
