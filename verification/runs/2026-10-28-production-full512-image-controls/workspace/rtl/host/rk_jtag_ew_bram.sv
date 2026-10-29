// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Host-controlled BRAM profile. Raw final command BO bytes feed the existing DMA.
// No tensor interface, software arithmetic, DDR or PCIe is present here.
module rk_jtag_ew_bram #(
    parameter int unsigned BYTES = 1048576,
    parameter logic [31:0] BASE = 32'h10000000,
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter int unsigned MAX_TASKS = 4095
) (
    input logic clk, rst_n,
    input logic req_valid,
    output logic req_ready,
    input logic [603:0] req,
    output logic rsp_valid,
    output logic [511:0] rsp_data,
    output logic [7:0] rsp_status,
    output logic [15:0] rsp_seq,
    output logic irq, fault
);
    logic [31:0] s_axil_awaddr, s_axil_wdata, s_axil_araddr, s_axil_rdata;
    logic [2:0] s_axil_awprot, s_axil_arprot;
    logic [3:0] s_axil_wstrb;
    logic [1:0] s_axil_bresp, s_axil_rresp;
    logic s_axil_awvalid, s_axil_awready, s_axil_wvalid, s_axil_wready;
    logic s_axil_bvalid, s_axil_bready, s_axil_arvalid, s_axil_arready, s_axil_rvalid, s_axil_rready;
    logic core_start_valid, core_start_ready, core_busy, core_done, core_error;
    logic [31:0] core_start_address, core_start_amount, core_completed_tasks;
    logic [7:0] core_error_code;
    logic unused_task_done;
    logic mem_req_valid, mem_req_ready, mem_req_write, mem_rsp_valid, mem_rsp_ready, mem_rsp_error;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_req_wdata, mem_rsp_rdata;
    logic host_valid, host_ready, host_write, host_rsp_valid, host_rsp_ready, host_error;
    logic [31:0] host_addr;
    logic [15:0] host_wdata, host_rdata;
    logic backend_fault, memory_busy;
    wire memory_available = !(core_start_valid || core_busy || core_error);
    wire memory_ready = rst_n && !memory_busy;
    assign fault = backend_fault || core_error;

    rk_jtag_backend #(.BYTES(BYTES), .BASE(BASE), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)) backend (
        .fault(backend_fault), .*
    );
    rk_job_control control(.*);
    rk_ew_dma #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES), .MAX_TASKS(MAX_TASKS)) engine (
        .clk, .rst_n, .start_valid(core_start_valid), .start_ready(core_start_ready),
        .start_address(core_start_address), .start_amount(core_start_amount), .busy(core_busy),
        .done(core_done), .task_done(unused_task_done), .completed_tasks(core_completed_tasks),
        .error(core_error), .error_code(core_error_code),
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr, .mem_req_wdata,
        .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata, .mem_rsp_error
    );
    rk_bram #(.BYTES(BYTES), .BASE(BASE)) memory (
        .clk, .rst_n, .req_valid(mem_req_valid), .req_ready(mem_req_ready),
        .req_write(mem_req_write), .req_addr(mem_req_addr), .req_wdata(mem_req_wdata),
        .rsp_valid(mem_rsp_valid), .rsp_ready(mem_rsp_ready), .rsp_rdata(mem_rsp_rdata),
        .rsp_error(mem_rsp_error), .host_valid, .host_ready, .host_write, .host_addr, .host_wdata,
        .host_rsp_valid, .host_rsp_ready, .host_rdata, .host_error
    );
endmodule
