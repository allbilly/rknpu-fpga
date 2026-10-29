// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Candidate C32/K16 parallel raw-command endpoint; not the legacy C64 core.
// Single-clock internal endpoint. Joint asynchronous reset assertion;
// platform must synchronize reset deassertion. No PCIe, CDC, MIG or ECC.
module rk_cmac_array_axi #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, rst_n, memory_ready,
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
    output logic irq,
    output logic [3:0] m_axi_awid, m_axi_arid,
    output logic [30:0] m_axi_awaddr, m_axi_araddr,
    output logic [7:0] m_axi_awlen, m_axi_arlen,
    output logic [2:0] m_axi_awsize, m_axi_arsize,
    output logic [1:0] m_axi_awburst, m_axi_arburst,
    output logic m_axi_awlock, m_axi_arlock,
    output logic [3:0] m_axi_awcache, m_axi_arcache,
    output logic [2:0] m_axi_awprot, m_axi_arprot,
    output logic [3:0] m_axi_awqos, m_axi_arqos,
    output logic m_axi_awvalid,
    input logic m_axi_awready,
    output logic [511:0] m_axi_wdata,
    output logic [63:0] m_axi_wstrb,
    output logic m_axi_wlast, m_axi_wvalid,
    input logic m_axi_wready,
    input logic [3:0] m_axi_bid,
    input logic [1:0] m_axi_bresp,
    input logic m_axi_bvalid,
    output logic m_axi_bready,
    output logic m_axi_arvalid,
    input logic m_axi_arready,
    input logic [3:0] m_axi_rid,
    input logic [511:0] m_axi_rdata,
    input logic [1:0] m_axi_rresp,
    input logic m_axi_rlast, m_axi_rvalid,
    output logic m_axi_rready
);
    logic core_start_valid, core_start_ready, core_busy, core_done, core_error;
    logic [31:0] core_start_address, core_start_amount, core_completed_tasks;
    logic [7:0] core_error_code;
    logic unused_acknowledged,unused_frame_done;
    logic mem_req_valid, mem_req_ready, mem_req_write, mem_rsp_valid, mem_rsp_ready, mem_rsp_error;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_req_wdata, mem_rsp_rdata;

    // The controller samples this count only on done/error. One terminal task.
    assign core_completed_tasks = core_done && !core_error ? 32'd1 : 32'd0;
    rk_cmac_job_control control(.*);
    rk_cmac_array_dma #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) engine (
        .clk(clk), .rst_n(rst_n), .start_valid(core_start_valid), .start_ready(core_start_ready),
        .start_address(core_start_address), .start_amount(core_start_amount), .busy(core_busy),
        .done(core_done), .acknowledged(unused_acknowledged), .error(core_error),
        .frame_done(unused_frame_done), .error_code(core_error_code),
        .mem_req_valid(mem_req_valid), .mem_req_ready(mem_req_ready), .mem_req_write(mem_req_write),
        .mem_req_addr(mem_req_addr), .mem_req_wdata(mem_req_wdata), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rsp_rdata(mem_rsp_rdata), .mem_rsp_error(mem_rsp_error)
    );
    rk_cmac_axi_mem memory_adapter(.*);
endmodule
