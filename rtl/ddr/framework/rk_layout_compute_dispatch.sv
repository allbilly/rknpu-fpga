// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Preparation candidate: unchanged raw EW/CMAC dispatcher plus a UI-domain
// raw layout DMA. One owner through terminal status; parent retains DDR
// fence/ECC/readback/ACK ownership after successful numerical status transfer.
module rk_layout_compute_dispatch #(
    parameter logic [31:0] BASE=32'h10000000,
    parameter logic [32:0] BYTES=33'd1048576,
    parameter integer TIMEOUT_CYCLES=65536,
    parameter integer MAX_TASKS=4095,
    parameter integer SYNC_STAGES=3
) (
    input wire ui_clk,ui_rst_n,ui_admission_enable,ui_rearm_permit,
    input wire ui_start_valid,ui_start_offer,
    input wire [1:0] ui_start_kind,
    output wire ui_start_ready,ui_ew_start_ready,ui_cmac_start_ready,ui_layout_start_ready,
    input wire [31:0] ui_start_address,ui_start_amount,
    output wire ui_result_valid,ui_result_error,
    output wire [7:0] ui_result_code,
    output wire [31:0] ui_result_tasks,
    input wire ui_result_ready,
    output wire ui_fault,ui_quiet,core_quiet,core_restart_ready,ui_restart_ready,
    input wire core_clk,core_rst_n,
    output wire ui_mem_req_valid,ui_mem_req_write,
    output wire [31:0] ui_mem_req_addr,
    output wire [15:0] ui_mem_req_wdata,
    input wire ui_mem_req_ready,ui_mem_rsp_valid,
    input wire [15:0] ui_mem_rsp_rdata,
    input wire ui_mem_rsp_error,
    output wire ui_mem_rsp_ready
);
    logic owned,owner_layout,memory_pending,local_fault,layout_rst_n;
    wire numerical_ui_quiet,numerical_core_quiet,numerical_core_ready,layout_quiet;
    assign ui_quiet=!owned&&!memory_pending&&!ui_fault&&numerical_ui_quiet&&layout_quiet&&
        !ui_start_offer&&!ui_start_valid&&!ui_mem_rsp_valid;
    assign core_quiet=numerical_core_quiet;
    assign core_restart_ready=numerical_core_ready;
    assign ui_restart_ready=ui_quiet&&layout_ready&&layout_rst_n;
    wire dual_ready,ew_ready,cmac_ready,dual_result,dual_error,dual_fault;
    wire [7:0] dual_code;
    wire [31:0] dual_tasks;
    wire dual_request,dual_write,dual_response_ready;
    wire [31:0] dual_address;
    wire [15:0] dual_data;
    wire layout_ready,layout_done,layout_error,unused_layout_busy;
    wire [7:0] layout_code;
    wire layout_request,layout_write,layout_response_ready;
    wire [31:0] layout_address;
    wire [15:0] layout_data;
    wire selection_known=(ui_start_kind===2'd0)||(ui_start_kind===2'd1)||(ui_start_kind===2'd2);
    wire selected_layout=ui_start_kind===2'd2;
    wire slot_free=ui_rst_n&&!owned&&!ui_fault;
    assign ui_ew_start_ready=slot_free&&ew_ready;
    assign ui_cmac_start_ready=slot_free&&cmac_ready;
    assign ui_layout_start_ready=slot_free&&layout_ready&&ui_admission_enable&&ui_rearm_permit===1'b1;
    assign ui_start_ready=selection_known&&(selected_layout ? ui_layout_start_ready : slot_free&&dual_ready);
    assign ui_result_valid=ui_rst_n&&owned&&(owner_layout ? (layout_done||layout_error) : dual_result);
    assign ui_result_error=owned&&(owner_layout ? layout_error : dual_error);
    assign ui_result_code=owned ? (owner_layout ? layout_code : dual_code) : 8'd0;
    assign ui_result_tasks=owned ? (owner_layout ? (layout_done ? 32'd1 : 32'd0) : dual_tasks) : 32'd0;
    assign ui_mem_req_valid=ui_rst_n&&owned&&(owner_layout ? layout_request : dual_request);
    assign ui_mem_req_write=owned&&(owner_layout ? layout_write : dual_write);
    assign ui_mem_req_addr=owned ? (owner_layout ? layout_address : dual_address) : 32'd0;
    assign ui_mem_req_wdata=owned ? (owner_layout ? layout_data : dual_data) : 16'd0;
    assign ui_mem_rsp_ready=ui_rst_n&&owned&&(owner_layout ? layout_response_ready : dual_response_ready);
    wire request_fire=ui_mem_req_valid&&ui_mem_req_ready;
    wire response_fire=ui_mem_rsp_valid&&ui_mem_rsp_ready;
    wire bad_owner=(!owned&&(dual_request||layout_request||dual_result||layout_done||layout_error))||
        (owned&&(owner_layout ? (dual_request||dual_result) : (layout_request||layout_done||layout_error)));
    wire bad_memory=(ui_mem_req_valid&&memory_pending&&!response_fire)||(ui_mem_rsp_valid&&!memory_pending);
    wire bad_success=ui_result_valid&&!ui_result_error&&(memory_pending||ui_mem_req_valid||ui_mem_rsp_valid);
    wire bad_selection=ui_start_offer&&!owned&&!selection_known;
    assign ui_fault=ui_rst_n&&(local_fault||dual_fault||layout_error||bad_owner||bad_memory||bad_success||bad_selection);
    // Asynchronously assert this dedicated release FF and retain the leaf's
    // synchronous functional reset through the first fresh UI edge.
    always @(posedge ui_clk or negedge ui_rst_n)begin
        if(!ui_rst_n)layout_rst_n<=0;
        else layout_rst_n<=1;
    end
    always @(posedge ui_clk or negedge ui_rst_n)begin
        if(!ui_rst_n)begin owned<=0;owner_layout<=0;memory_pending<=0;local_fault<=0;end
        else begin
            if(bad_owner||bad_memory||bad_success||bad_selection)local_fault<=1;
            // Register permission loss; do not feed the parent's live fault
            // back through its own combinational rearm/admission predicate.
            if(owned&&owner_layout&&ui_rearm_permit!==1'b1)local_fault<=1;
            if(ui_start_valid&&ui_start_ready)begin owned<=1;owner_layout<=selected_layout;end
            case({request_fire,response_fire})
                2'b10:memory_pending<=1;
                2'b01:memory_pending<=0;
                default:begin end
            endcase
            if(ui_result_valid&&ui_result_ready&&!ui_result_error&&!ui_fault)owned<=0;
        end
    end
    rk_dual_async_dispatch #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES),.MAX_TASKS(MAX_TASKS),.SYNC_STAGES(SYNC_STAGES)) numerical (
        .ui_quiet(numerical_ui_quiet),.core_quiet(numerical_core_quiet),.core_restart_ready(numerical_core_ready),
        .ui_clk,.ui_rst_n,.ui_admission_enable(ui_admission_enable&&!ui_fault),.ui_rearm_permit,
        .ui_start_valid(ui_start_valid&&!owned&&selection_known&&!selected_layout),.ui_start_cmac(ui_start_kind[0]),
        .ui_start_ready(dual_ready),.ui_ew_start_ready(ew_ready),.ui_cmac_start_ready(cmac_ready),
        .ui_start_address,.ui_start_amount,.ui_result_valid(dual_result),.ui_result_error(dual_error),
        .ui_result_code(dual_code),.ui_result_tasks(dual_tasks),
        .ui_result_ready(ui_result_ready&&owned&&!owner_layout),.ui_fault(dual_fault),
        .core_clk,.core_rst_n,.ui_mem_req_valid(dual_request),
        .ui_mem_req_ready(ui_mem_req_ready&&owned&&!owner_layout),.ui_mem_req_write(dual_write),
        .ui_mem_req_addr(dual_address),.ui_mem_req_wdata(dual_data),
        .ui_mem_rsp_valid(ui_mem_rsp_valid&&owned&&!owner_layout),
        .ui_mem_rsp_rdata,.ui_mem_rsp_error,.ui_mem_rsp_ready(dual_response_ready)
    );
    rk_layout_dma #(.BASE(BASE),.BYTES(BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) layout_engine (
        .quiescent(layout_quiet),
        .clk(ui_clk),.rst_n(layout_rst_n),
        .start_valid(ui_start_valid&&slot_free&&selected_layout&&ui_admission_enable&&ui_rearm_permit===1'b1),
        .start_ready(layout_ready),.start_address(ui_start_address),.start_amount(ui_start_amount),
        .busy(unused_layout_busy),.done(layout_done),.error(layout_error),.error_code(layout_code),
        .result_ready(ui_result_ready&&owned&&owner_layout&&!ui_fault),
        .mem_req_valid(layout_request),.mem_req_ready(ui_mem_req_ready&&owned&&owner_layout),
        .mem_req_write(layout_write),.mem_req_addr(layout_address),.mem_req_wdata(layout_data),
        .mem_rsp_valid(ui_mem_rsp_valid&&owned&&owner_layout),.mem_rsp_ready(layout_response_ready),
        .mem_rsp_rdata(ui_mem_rsp_rdata),.mem_rsp_error(ui_mem_rsp_error)
    );
endmodule
