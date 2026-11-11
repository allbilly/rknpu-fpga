// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Host-drivable page for the FP32 GEMM leaf.
//
// This is `rk_cmac_nvdla_axi` without the redundant AXI round trip: the
// endpoint's job control is identical, the engine is
// `rk_cmac_nvdla_dma(OUTPUT_FP16=0)`, and the memory port stays in the halfword
// form the board images already arbitrate. `rk_cmac_nvdla_axi` keeps its AXI4
// memory master for images that own an AXI interconnect; a BRAM-only image
// should use this page instead of paying for AXI4 -> halfword twice.
//
// Register ABI is the shared `rk_cmac_job_control` layout, so one host driver
// covers the conv page, the pooling page and this one.
//
//  0x00  DEVICE_ID      RO  0x524b434d ("RKCM")
//  0x04  ABI_VERSION    RO  0x00010000
//  0x08  STATUS         RO  see rk_cmac_job_control
//  0x0c  COMMAND        WO  1 = submit, 2 = acknowledge result
//  0x10  START_ADDRESS  RW  command BO base (16-byte aligned)
//  0x14  START_AMOUNT   RW  body QWORD count; must be 45
//  0x18  JOB_TAG        RW  echoed in RESULT_TAG
//  0x1c  RESULT_TAG     RO
//  0x20  RESULT_TASKS   RO  1 on success, 0 on error
//  0x24  RESULT_CODE    RO
//
// The command stream is fetched unchanged from the address the host writes.
module rk_cmac_gemm_axi #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        memory_ready,
    // AXI4-Lite slave (the transport page).
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
    input  logic        s_axil_rready,
    // Result slot full, held until the host acknowledges.
    output logic        irq,
    // True from an accepted submit until the result is acknowledged; the dual
    // endpoint uses it to keep the other pages off the memory port.
    output logic        busy,
    // Serialized halfword memory port, same shape as the other pages.
    output logic        mem_req_valid,
    input  logic        mem_req_ready,
    output logic        mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input  logic        mem_rsp_valid,
    output logic        mem_rsp_ready,
    input  logic [15:0] mem_rsp_rdata,
    input  logic        mem_rsp_error
);
    logic core_start_valid, core_start_ready;
    logic [31:0] core_start_address, core_start_amount, core_completed_tasks;
    logic core_busy, core_done, core_error;
    logic [7:0] core_error_code;

    // The controller samples this count only on done/error. One terminal task.
    assign core_completed_tasks = core_done && !core_error ? 32'd1 : 32'd0;

    rk_cmac_job_control control (
        .clk, .rst_n, .memory_ready,
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready,
        .irq,
        .core_start_valid, .core_start_ready,
        .core_start_address, .core_start_amount,
        .core_busy, .core_done, .core_error,
        .core_error_code, .core_completed_tasks
    );

    rk_cmac_nvdla_dma #(
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES),
        // The frozen GEMM captures are FP32 output and their OUT_CVT_SCALE is
        // 0x0, so this page never converts.
        .OUTPUT_FP16(1'b0)
    ) engine (
        .clk, .rst_n,
        .start_valid(core_start_valid), .start_ready(core_start_ready),
        .start_address(core_start_address), .start_amount(core_start_amount),
        .busy(core_busy), .done(core_done), .acknowledged(),
        .address_done(), .operand_done(),
        .error(core_error), .error_code(core_error_code),
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata,
        .mem_rsp_error
    );

    // `rk_cmac_job_control` exposes the result slot but not an "active" flag,
    // so busy is derived from the engine and the launch handshake.
    assign busy = rst_n && (core_busy || core_start_valid) && !irq;

    initial begin
        if (TIMEOUT_CYCLES == 0)
            $fatal(1, "GEMM page timeout must be positive");
    end
endmodule
