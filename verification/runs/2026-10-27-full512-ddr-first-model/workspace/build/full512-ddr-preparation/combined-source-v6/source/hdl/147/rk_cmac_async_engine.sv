// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Raw CMAC descriptor UI->SYS; unchanged halfword traffic SYS->UI.
// Terminal core status is not DDR retirement/ECC proof or host ACK.
// Both crossing resets belong to one coordinated whole-transaction epoch.
module rk_cmac_async_engine #(
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter int unsigned JOB_SYNC_STAGES = 3,
    parameter int unsigned MEMORY_SYNC_STAGES = 3,
    parameter int unsigned PERMIT_SYNC_STAGES = 3
) (
    input wire ui_clk, ui_rst_n, ui_admission_enable, ui_rearm_permit,
    input wire ui_start_valid,
    output wire ui_start_ready,
    input wire [31:0] ui_start_address, ui_start_amount,
    output wire ui_result_valid, ui_result_error,
    output wire [7:0] ui_result_code,
    output wire [31:0] ui_result_tasks,
    input wire ui_result_ready,
    output wire ui_fault,
    input wire core_clk, core_rst_n,
    output wire ui_mem_req_valid, ui_mem_req_write,
    output wire [31:0] ui_mem_req_addr,
    output wire [15:0] ui_mem_req_wdata,
    input wire ui_mem_req_ready, ui_mem_rsp_valid,
    input wire [15:0] ui_mem_rsp_rdata,
    input wire ui_mem_rsp_error,
    output wire ui_mem_rsp_ready
);
    localparam integer PERMIT_STAGES = PERMIT_SYNC_STAGES < 3 ? 3 : PERMIT_SYNC_STAGES;
    logic permit_registered;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [PERMIT_STAGES-1:0] permit_sync;
    wire crossing_start_valid, crossing_start_ready, crossing_result_ready;
    wire [31:0] crossing_address, crossing_amount;
    wire job_ui_protocol_fault, job_core_protocol_fault;
    wire memory_ui_protocol_fault, memory_core_protocol_fault;
    wire dma_start_ready, dma_busy, dma_done, dma_error;
    wire [7:0] dma_error_code;
    wire [31:0] dma_completed_tasks, unused_rearm_count;
    wire mem_req_valid, mem_req_ready, mem_req_write;
    wire mem_rsp_valid, mem_rsp_ready, mem_rsp_error;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata, mem_rsp_rdata;
    logic core_active, terminal_pending, terminal_error, ui_failure_seen;
    logic dma_rst_n, memory_pending;
    logic [7:0] terminal_code;
    logic [31:0] terminal_tasks;
    wire core_permitted = permit_sync[PERMIT_STAGES-1] === 1'b1 &&
                          !job_core_protocol_fault && !memory_core_protocol_fault;
    wire slot_free = !core_active && !terminal_pending;
    wire dma_start_valid = crossing_start_valid && slot_free && core_permitted;
    // A descriptor already accepted in UI cannot be withdrawn if permission
    // is revoked before SYS sees it. Retire it explicitly without a DMA start.
    assign crossing_start_ready = slot_free && (!core_permitted || dma_start_ready);

    initial begin
        if (PERMIT_SYNC_STAGES < 3)
            $fatal(1, "CMAC permit crossing requires at least three stages");
    end
    // Register the actual UI health/admission level before its clean level
    // synchronizer. This is not a cancellation/reset path or memory-ready flag.
    always_ff @(posedge ui_clk or negedge ui_rst_n) begin
        if (!ui_rst_n) permit_registered <= 0;
        else permit_registered <= ui_rearm_permit === 1'b1;
    end
    always_ff @(posedge core_clk or negedge core_rst_n) begin
        if (!core_rst_n) begin permit_sync <= 0; dma_rst_n <= 0; end
        else begin
            permit_sync <= {permit_sync[PERMIT_STAGES-2:0],permit_registered};
            dma_rst_n <= 1;
        end
    end
    assign ui_fault = ui_rst_n && (ui_failure_seen || job_ui_protocol_fault ||
        memory_ui_protocol_fault || (ui_result_valid && ui_result_error));
    always_ff @(posedge ui_clk or negedge ui_rst_n) begin
        if (!ui_rst_n) ui_failure_seen <= 0;
        else if (job_ui_protocol_fault || memory_ui_protocol_fault ||
                 (ui_result_valid && ui_result_error)) ui_failure_seen <= 1;
    end

    rk_async_job_port #(.SYNC_STAGES(JOB_SYNC_STAGES)) job_crossing (
        .s_clk(ui_clk), .s_rst_n(ui_rst_n),
        .s_admission_enable(ui_admission_enable && ui_rearm_permit === 1'b1 && !ui_fault),
        .s_start_valid(ui_start_valid), .s_start_ready(ui_start_ready),
        .s_start_address(ui_start_address), .s_start_amount(ui_start_amount),
        .s_result_valid(ui_result_valid), .s_result_error(ui_result_error),
        .s_result_code(ui_result_code), .s_result_tasks(ui_result_tasks), .s_result_ready(ui_result_ready),
        .s_protocol_fault(job_ui_protocol_fault), .d_clk(core_clk), .d_rst_n(core_rst_n),
        .d_start_valid(crossing_start_valid), .d_start_ready(crossing_start_ready),
        .d_start_address(crossing_address), .d_start_amount(crossing_amount),
        .d_result_valid(terminal_pending), .d_result_error(terminal_error),
        .d_result_code(terminal_code), .d_result_tasks(terminal_tasks), .d_result_ready(crossing_result_ready),
        .d_protocol_fault(job_core_protocol_fault)
    );
    always_ff @(posedge core_clk or negedge core_rst_n) begin
        if (!core_rst_n) begin
            core_active <= 0; terminal_pending <= 0; terminal_error <= 0;
            terminal_code <= 0; terminal_tasks <= 0; memory_pending <= 0;
        end else begin
            if (mem_req_valid && mem_req_ready) memory_pending <= 1;
            if (mem_rsp_valid && mem_rsp_ready) memory_pending <= 0;
            if (crossing_start_valid && crossing_start_ready) begin
                if (core_permitted) core_active <= 1;
                else begin
                    terminal_pending <= 1; terminal_error <= 1;
                    terminal_code <= 5; terminal_tasks <= 0;
                end
            end
            if (core_active && (dma_done || dma_error)) begin
                core_active <= 0; terminal_pending <= 1;
                terminal_error <= dma_error;
                terminal_code <= dma_error ? dma_error_code : 8'b0;
                terminal_tasks <= dma_completed_tasks;
            end
            if (terminal_pending && crossing_result_ready) terminal_pending <= 0;
        end
    end
    // Rearm only the successful numerical child after the crossing is drained.
    // DDR ownership, ECC/fence state and the job/memory crossings are never
    // reset here. A later UI health fault still invalidates the containing job.
    rk_cmac_success_rearm #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) engine (
        .clk(core_clk), .rst_n(dma_rst_n), .start_valid(dma_start_valid), .start_ready(dma_start_ready),
        .start_address(crossing_address), .start_amount(crossing_amount),
        .rearm_allowed(core_permitted), .memory_pending(memory_pending || mem_rsp_valid),
        .busy(dma_busy), .done(dma_done), .error(dma_error), .error_code(dma_error_code),
        .completed_tasks(dma_completed_tasks), .rearm_count(unused_rearm_count),
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr, .mem_req_wdata,
        .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata, .mem_rsp_error
    );
    rk_async_mem_port #(.SYNC_STAGES(MEMORY_SYNC_STAGES)) memory_crossing (
        .s_clk(core_clk), .s_rst_n(core_rst_n), .s_admission_enable(core_active && dma_busy),
        .s_mem_req_valid(mem_req_valid), .s_mem_req_ready(mem_req_ready), .s_mem_req_write(mem_req_write),
        .s_mem_req_addr(mem_req_addr), .s_mem_req_wdata(mem_req_wdata),
        .s_mem_rsp_valid(mem_rsp_valid), .s_mem_rsp_ready(mem_rsp_ready),
        .s_mem_rsp_rdata(mem_rsp_rdata), .s_mem_rsp_error(mem_rsp_error),
        .s_protocol_fault(memory_core_protocol_fault), .d_clk(ui_clk), .d_rst_n(ui_rst_n),
        .d_mem_req_valid(ui_mem_req_valid), .d_mem_req_ready(ui_mem_req_ready),
        .d_mem_req_write(ui_mem_req_write), .d_mem_req_addr(ui_mem_req_addr), .d_mem_req_wdata(ui_mem_req_wdata),
        .d_mem_rsp_valid(ui_mem_rsp_valid), .d_mem_rsp_ready(ui_mem_rsp_ready),
        .d_mem_rsp_rdata(ui_mem_rsp_rdata), .d_mem_rsp_error(ui_mem_rsp_error),
        .d_protocol_fault(memory_ui_protocol_fault)
    );
endmodule
