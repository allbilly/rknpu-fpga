// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Source preparation: raw UI-domain descriptor -> SYS-domain EW DMA, with
// halfword memory back in UI. No command/arithmetic/layout interpretation here.
// UI result is terminal core status, not a DDR fence or successful host ACK.
// Both resets must be one audited core/crossing/memory-owner transaction epoch.
module rk_ew_async_engine #(
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter int unsigned MAX_TASKS = 4095,
    parameter int unsigned JOB_SYNC_STAGES = 3,
    parameter int unsigned MEMORY_SYNC_STAGES = 3
) (
    input wire ui_clk, ui_rst_n, ui_admission_enable,
    input wire ui_start_valid,
    output wire ui_start_ready,
    input wire [31:0] ui_start_address, ui_start_amount,
    output wire ui_result_valid, ui_result_error,
    output wire [7:0] ui_result_code,
    output wire [31:0] ui_result_tasks,
    input wire ui_result_ready,
    output wire ui_fault,ui_quiet,core_quiet,core_restart_ready,
    input wire core_clk, core_rst_n,
    output wire ui_mem_req_valid, ui_mem_req_write,
    output wire [31:0] ui_mem_req_addr,
    output wire [15:0] ui_mem_req_wdata,
    input wire ui_mem_req_ready, ui_mem_rsp_valid,
    input wire [15:0] ui_mem_rsp_rdata,
    input wire ui_mem_rsp_error,
    output wire ui_mem_rsp_ready
);
    wire crossing_start_valid,crossing_start_ready,crossing_result_ready;
    wire [31:0] crossing_address,crossing_amount;
    wire job_ui_protocol_fault,memory_ui_protocol_fault;
    wire unused_job_core_protocol_fault,unused_memory_core_protocol_fault;
    wire dma_start_ready,unused_dma_busy,dma_done,unused_task_done,dma_error;
    wire [7:0] dma_error_code;
    wire [31:0] dma_completed_tasks;
    wire mem_req_valid,mem_req_ready,mem_req_write,mem_rsp_valid,mem_rsp_ready,mem_rsp_error;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata,mem_rsp_rdata;
    logic core_active,terminal_pending,terminal_error,ui_failure_seen;
    logic dma_rst_n;
    logic [7:0] terminal_code;
    logic [31:0] terminal_tasks;
    wire dma_start_valid=crossing_start_valid&&!core_active&&!terminal_pending;
    assign crossing_start_ready=dma_start_ready&&!core_active&&!terminal_pending;
    // The crossing halves assert reset asynchronously. The unchanged EW DMA
    // uses a synchronous functional reset: retain it through the first fresh
    // core edge after release, including when the core clock was stopped.
    always_ff @(posedge core_clk or negedge core_rst_n) begin
        if(!core_rst_n)dma_rst_n<=0;
        else dma_rst_n<=1;
    end
    // A consumed error never reopens admission. A later protocol fault must
    // also invalidate a pending success in the containing UI retirement owner.
    assign ui_fault=ui_rst_n&&(ui_failure_seen||job_ui_protocol_fault||memory_ui_protocol_fault||
                              (ui_result_valid&&ui_result_error));
    always_ff @(posedge ui_clk or negedge ui_rst_n) begin
        if(!ui_rst_n)ui_failure_seen<=0;
        else if(job_ui_protocol_fault||memory_ui_protocol_fault||(ui_result_valid&&ui_result_error))
            ui_failure_seen<=1;
    end

    wire job_ui_quiet,job_core_quiet,memory_ui_quiet,memory_core_quiet;
    assign ui_quiet=job_ui_quiet&&memory_ui_quiet&&!ui_fault&&!ui_mem_req_valid&&!ui_mem_rsp_valid;
    assign core_quiet=job_core_quiet&&memory_core_quiet&&!core_active&&!terminal_pending&&
        !mem_req_valid&&!mem_rsp_valid&&!dma_error&&!unused_dma_busy&&!unused_job_core_protocol_fault&&!unused_memory_core_protocol_fault;
    assign core_restart_ready=core_quiet&&dma_start_ready&&dma_rst_n;
    rk_async_job_port #(.SYNC_STAGES(JOB_SYNC_STAGES)) job_crossing (
        .s_quiet(job_ui_quiet),.d_quiet(job_core_quiet),
        .s_clk(ui_clk),.s_rst_n(ui_rst_n),.s_admission_enable(ui_admission_enable&&!ui_fault),
        .s_start_valid(ui_start_valid),.s_start_ready(ui_start_ready),
        .s_start_address(ui_start_address),.s_start_amount(ui_start_amount),
        .s_result_valid(ui_result_valid),.s_result_error(ui_result_error),
        .s_result_code(ui_result_code),.s_result_tasks(ui_result_tasks),.s_result_ready(ui_result_ready),
        .s_protocol_fault(job_ui_protocol_fault),.d_clk(core_clk),.d_rst_n(core_rst_n),
        .d_start_valid(crossing_start_valid),.d_start_ready(crossing_start_ready),
        .d_start_address(crossing_address),.d_start_amount(crossing_amount),
        .d_result_valid(terminal_pending),.d_result_error(terminal_error),
        .d_result_code(terminal_code),.d_result_tasks(terminal_tasks),.d_result_ready(crossing_result_ready),
        .d_protocol_fault(unused_job_core_protocol_fault)
    );
    // Convert the unchanged DMA's one-cycle done or sticky error into exactly
    // one held result per accepted start. A sticky DMA error is not replayed as
    // unsolicited replies, and consuming its result does not reset the core.
    always_ff @(posedge core_clk or negedge core_rst_n) begin
        if(!core_rst_n) begin
            core_active<=0;terminal_pending<=0;terminal_error<=0;terminal_code<=0;terminal_tasks<=0;
        end else begin
            if(dma_start_valid&&dma_start_ready)core_active<=1;
            if(core_active&&(dma_done||dma_error)) begin
                core_active<=0;terminal_pending<=1;
                terminal_error<=dma_error;terminal_code<=dma_error?dma_error_code:8'b0;
                terminal_tasks<=dma_completed_tasks;
            end
            if(terminal_pending&&crossing_result_ready)terminal_pending<=0;
        end
    end
    rk_ew_dma #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES),.MAX_TASKS(MAX_TASKS)) engine (
        .clk(core_clk),.rst_n(dma_rst_n),.start_valid(dma_start_valid),.start_ready(dma_start_ready),
        .start_address(crossing_address),.start_amount(crossing_amount),.busy(unused_dma_busy),
        .done(dma_done),.task_done(unused_task_done),.error(dma_error),.error_code(dma_error_code),
        .completed_tasks(dma_completed_tasks),.mem_req_valid,.mem_req_ready,.mem_req_write,
        .mem_req_addr,.mem_req_wdata,.mem_rsp_valid,.mem_rsp_ready,.mem_rsp_rdata,.mem_rsp_error
    );
    rk_async_mem_port #(.SYNC_STAGES(MEMORY_SYNC_STAGES)) memory_crossing (
        .s_quiet(memory_core_quiet),.d_quiet(memory_ui_quiet),
        .s_clk(core_clk),.s_rst_n(core_rst_n),.s_admission_enable(core_active),
        .s_mem_req_valid(mem_req_valid),.s_mem_req_ready(mem_req_ready),.s_mem_req_write(mem_req_write),
        .s_mem_req_addr(mem_req_addr),.s_mem_req_wdata(mem_req_wdata),.s_mem_rsp_valid(mem_rsp_valid),
        .s_mem_rsp_ready(mem_rsp_ready),.s_mem_rsp_rdata(mem_rsp_rdata),.s_mem_rsp_error(mem_rsp_error),
        .s_protocol_fault(unused_memory_core_protocol_fault),.d_clk(ui_clk),.d_rst_n(ui_rst_n),
        .d_mem_req_valid(ui_mem_req_valid),.d_mem_req_ready(ui_mem_req_ready),.d_mem_req_write(ui_mem_req_write),
        .d_mem_req_addr(ui_mem_req_addr),.d_mem_req_wdata(ui_mem_req_wdata),.d_mem_rsp_valid(ui_mem_rsp_valid),
        .d_mem_rsp_ready(ui_mem_rsp_ready),.d_mem_rsp_rdata(ui_mem_rsp_rdata),.d_mem_rsp_error(ui_mem_rsp_error),
        .d_protocol_fault(memory_ui_protocol_fault)
    );
endmodule
