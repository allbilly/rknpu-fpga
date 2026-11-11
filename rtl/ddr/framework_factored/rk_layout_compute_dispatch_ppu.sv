// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Preparation candidate: unchanged raw EW/CMAC dispatcher plus UI-domain
// raw layout and capture-bounded C3/C8 PPU DMA. One owner through terminal status; parent retains DDR
// fence/ECC/readback/ACK ownership after successful numerical status transfer.
/* verilator lint_off DECLFILENAME */
module rk_layout_compute_dispatch #(
    parameter logic [31:0] BASE=32'h10000000,
    parameter logic [32:0] BYTES=33'd1048576,
    parameter integer ATOMIC_C=32,
    parameter integer ATOMIC_K=16,
    parameter integer TIMEOUT_CYCLES=65536,
    parameter integer MAX_TASKS=4095,
    parameter integer SYNC_STAGES=3
) (
    input wire ui_clk,ui_rst_n,ui_admission_enable,ui_rearm_permit,
    input wire ui_start_valid,ui_start_offer,
    input wire [1:0] ui_start_kind,
    output wire ui_start_ready,ui_start_slot_ready,ui_ew_start_ready,ui_cmac_start_ready,ui_layout_start_ready,
    output wire ui_ew_start_slot_ready,ui_cmac_start_slot_ready,ui_layout_start_slot_ready,
    input wire [31:0] ui_start_address,ui_start_amount,
    output wire ui_result_valid,ui_result_error,
    output wire [7:0] ui_result_code,
    output wire [31:0] ui_result_tasks,
    input wire ui_result_ready,
    output wire ui_fault,ui_quiet,ui_idle_quiet,core_quiet,core_restart_ready,ui_restart_ready,ui_idle_restart_ready,
    input wire core_clk,core_rst_n,
    output wire ui_mem_req_valid,ui_mem_req_write,
    output wire [31:0] ui_mem_req_addr,
    output wire [15:0] ui_mem_req_wdata,
    input wire ui_mem_req_ready,ui_mem_rsp_valid,
    input wire [15:0] ui_mem_rsp_rdata,
    input wire ui_mem_rsp_error,
    output wire ui_mem_rsp_ready
);
    logic owned,owner_layout,owner_ppu,memory_pending,local_fault,layout_rst_n,ppu_rst_n;
    wire numerical_ui_quiet,numerical_ui_idle_quiet,numerical_core_quiet,numerical_core_ready;
    wire layout_quiet,layout_idle_quiet,ppu_quiet,ppu_idle_quiet;
    wire layout_ready,layout_done,layout_error,unused_layout_busy;
    wire ppu_ready,ppu_done,ppu_error,ppu_busy,ppu_idle_conflict;
    wire ui_idle_fault;
    assign ui_quiet=!owned&&!memory_pending&&!ui_fault&&numerical_ui_quiet&&layout_quiet&&ppu_quiet&&
        !ui_start_offer&&!ui_start_valid&&!ui_mem_rsp_valid;
    assign ui_idle_quiet=!owned&&!memory_pending&&!ui_idle_fault&&numerical_ui_idle_quiet&&layout_idle_quiet&&ppu_idle_quiet&&
        !ui_mem_rsp_valid;
    assign core_quiet=numerical_core_quiet;
    assign core_restart_ready=numerical_core_ready;
    assign ui_restart_ready=ui_quiet&&layout_ready&&layout_rst_n&&ppu_ready&&ppu_rst_n;
    assign ui_idle_restart_ready=ui_idle_quiet&&layout_ready&&layout_rst_n&&ppu_ready&&ppu_rst_n;
    wire dual_ready,dual_slot_ready,ew_ready,cmac_ready,ew_slot_ready,cmac_slot_ready,dual_result,dual_error,dual_fault;
    wire [7:0] dual_code;
    wire [31:0] dual_tasks;
    wire dual_request,dual_write,dual_response_ready;
    wire [31:0] dual_address;
    wire [15:0] dual_data;
    wire [7:0] layout_code;
    wire layout_request,layout_write,layout_response_ready;
    wire [31:0] layout_address;
    wire [15:0] layout_data;
    wire [7:0] ppu_code;
    wire ppu_request,ppu_write,ppu_response_ready;
    wire [31:0] ppu_address;
    wire [15:0] ppu_data;
    wire selection_known=(ui_start_kind===2'd0)||(ui_start_kind===2'd1)||
                         (ui_start_kind===2'd2)||(ui_start_kind===2'd3);
    wire selected_layout=ui_start_kind===2'd2;
    wire selected_ppu=ui_start_kind===2'd3;
    wire slot_free=ui_rst_n&&!owned&&!ui_fault;
    assign ui_ew_start_ready=slot_free&&ew_ready;
    assign ui_cmac_start_ready=slot_free&&cmac_ready;
    // Layout and PPU share one owned auxiliary slot and one memory channel.
    assign ui_layout_start_ready=slot_free&&layout_ready&&ppu_ready&&ui_admission_enable&&ui_rearm_permit===1'b1;
    assign ui_ew_start_slot_ready=slot_free&&ew_slot_ready;
    assign ui_cmac_start_slot_ready=slot_free&&cmac_slot_ready;
    assign ui_layout_start_slot_ready=slot_free&&layout_ready&&ppu_ready&&(ui_rearm_permit===1'b1);
    assign ui_start_slot_ready=selection_known&&((selected_layout||selected_ppu) ?
        ui_layout_start_slot_ready : slot_free&&dual_slot_ready);
    assign ui_start_ready=selection_known&&((selected_layout||selected_ppu) ?
        ui_layout_start_ready : slot_free&&dual_ready);
`ifdef ASSERT_ON
    always_ff @(posedge ui_clk) begin
        if(ui_rst_n===1'b1) begin
            if(ui_ew_start_ready !== (ui_admission_enable && ui_ew_start_slot_ready))
                $fatal(1,"readiness factor identity failed: layout EW slot");
            if(ui_cmac_start_ready !== (ui_admission_enable && ui_cmac_start_slot_ready))
                $fatal(1,"readiness factor identity failed: layout CMAC slot");
            if(ui_layout_start_ready !== (ui_admission_enable && ui_layout_start_slot_ready))
                $fatal(1,"readiness factor identity failed: layout slot");
            if(ui_start_ready !== (ui_admission_enable && ui_start_slot_ready))
                $fatal(1,"readiness factor identity failed: layout dispatcher");
            if(ui_quiet !== (ui_idle_quiet && !ui_start_offer && !ui_start_valid))
                $fatal(1,"quiet factor identity failed: layout dispatcher");
            if(ui_restart_ready !== (ui_idle_restart_ready && !ui_start_offer && !ui_start_valid))
                $fatal(1,"quiet factor identity failed: layout restart ready");
            if(ppu_idle_conflict)
                $fatal(1,"C3/C8 PPU DMA busy/quiet contradiction");
        end
    end
`endif
    assign ui_result_valid=ui_rst_n&&owned&&(owner_layout ? (layout_done||layout_error) :
        owner_ppu ? (ppu_done||ppu_error) : dual_result);
    assign ui_result_error=owned&&(owner_layout ? layout_error : owner_ppu ? ppu_error : dual_error);
    assign ui_result_code=owned ? (owner_layout ? layout_code : owner_ppu ? ppu_code : dual_code) : 8'd0;
    assign ui_result_tasks=owned ? (owner_layout ? (layout_done ? 32'd1 : 32'd0) :
        owner_ppu ? (ppu_done ? 32'd1 : 32'd0) : dual_tasks) : 32'd0;
    assign ui_mem_req_valid=ui_rst_n&&owned&&(owner_layout ? layout_request :
        owner_ppu ? ppu_request : dual_request);
    assign ui_mem_req_write=owned&&(owner_layout ? layout_write : owner_ppu ? ppu_write : dual_write);
    assign ui_mem_req_addr=owned ? (owner_layout ? layout_address :
        owner_ppu ? ppu_address : dual_address) : 32'd0;
    assign ui_mem_req_wdata=owned ? (owner_layout ? layout_data :
        owner_ppu ? ppu_data : dual_data) : 16'd0;
    assign ui_mem_rsp_ready=ui_rst_n&&owned&&(owner_layout ? layout_response_ready :
        owner_ppu ? ppu_response_ready : dual_response_ready);
    wire request_fire=ui_mem_req_valid&&ui_mem_req_ready;
    wire response_fire=ui_mem_rsp_valid&&ui_mem_rsp_ready;
    wire bad_owner=(!owned&&(dual_request||layout_request||ppu_request||dual_result||
        layout_done||layout_error||ppu_done||ppu_error))||
        (owned&&(owner_layout ? (dual_request||ppu_request||dual_result||ppu_done||ppu_error) :
        owner_ppu ? (dual_request||layout_request||dual_result||layout_done||layout_error) :
        (layout_request||ppu_request||layout_done||layout_error||ppu_done||ppu_error)));
    wire bad_memory=(ui_mem_req_valid&&memory_pending&&!response_fire)||(ui_mem_rsp_valid&&!memory_pending);
    wire bad_success=ui_result_valid&&!ui_result_error&&(memory_pending||ui_mem_req_valid||ui_mem_rsp_valid);
    wire bad_selection=ui_start_offer&&!owned&&!selection_known;
    assign ppu_idle_conflict=ppu_idle_quiet&&ppu_busy;
    assign ui_fault=ui_rst_n&&(local_fault||dual_fault||layout_error||ppu_error||ppu_idle_conflict||
        bad_owner||bad_memory||bad_success||bad_selection);
    assign ui_idle_fault=ui_rst_n&&(local_fault||dual_fault||layout_error||ppu_error||ppu_idle_conflict||
        bad_owner||bad_memory||bad_success);
    // Asynchronously assert this dedicated release FF and retain the leaf's
    // synchronous functional reset through the first fresh UI edge.
    always @(posedge ui_clk or negedge ui_rst_n)begin
        if(!ui_rst_n)begin layout_rst_n<=0;ppu_rst_n<=0;end
        else begin layout_rst_n<=1;ppu_rst_n<=1;end
    end
    always @(posedge ui_clk or negedge ui_rst_n)begin
        if(!ui_rst_n)begin owned<=0;owner_layout<=0;owner_ppu<=0;memory_pending<=0;local_fault<=0;end
        else begin
            if(bad_owner||bad_memory||bad_success||bad_selection)local_fault<=1;
            // Register permission loss; do not feed the parent's live fault
            // back through its own combinational rearm/admission predicate.
            if(owned&&(owner_layout||owner_ppu)&&ui_rearm_permit!==1'b1)local_fault<=1;
            if(ui_start_valid&&ui_start_ready)begin
                owned<=1;owner_layout<=selected_layout;owner_ppu<=selected_ppu;
            end
            case({request_fire,response_fire})
                2'b10:memory_pending<=1;
                2'b01:memory_pending<=0;
                default:begin end
            endcase
            if(ui_result_valid&&ui_result_ready&&!ui_result_error&&!ui_fault)owned<=0;
        end
    end
    rk_dual_async_dispatch #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES),.MAX_TASKS(MAX_TASKS),.SYNC_STAGES(SYNC_STAGES)) numerical (
        .ui_quiet(numerical_ui_quiet),.ui_idle_quiet(numerical_ui_idle_quiet),.core_quiet(numerical_core_quiet),.core_restart_ready(numerical_core_ready),
        .ui_clk,.ui_rst_n,.ui_admission_enable(ui_admission_enable&&!ui_fault),.ui_rearm_permit,
        .ui_start_valid(ui_start_valid&&!owned&&selection_known&&!selected_layout&&!selected_ppu),.ui_start_cmac(ui_start_kind[0]),
        .ui_start_ready(dual_ready),.ui_start_slot_ready(dual_slot_ready),.ui_ew_start_ready(ew_ready),.ui_cmac_start_ready(cmac_ready),
        .ui_ew_start_slot_ready(ew_slot_ready),.ui_cmac_start_slot_ready(cmac_slot_ready),
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
        .quiescent(layout_quiet),.idle_quiet(layout_idle_quiet),
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
    rk_ppu_pool_raw_dma #(.BASE(BASE),.BYTES(BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) ppu_engine (
        .quiescent(ppu_quiet),.idle_quiet(ppu_idle_quiet),
        .clk(ui_clk),.rst_n(ppu_rst_n),
        .start_valid(ui_start_valid&&slot_free&&selected_ppu&&ui_admission_enable&&ui_rearm_permit===1'b1),
        .start_ready(ppu_ready),.start_address(ui_start_address),.start_amount(ui_start_amount),
        .busy(ppu_busy),.done(ppu_done),.error(ppu_error),.error_code(ppu_code),
        .result_ready(ui_result_ready&&owned&&owner_ppu&&!ui_fault),
        .mem_req_valid(ppu_request),.mem_req_ready(ui_mem_req_ready&&owned&&owner_ppu),
        .mem_req_write(ppu_write),.mem_req_addr(ppu_address),.mem_req_wdata(ppu_data),
        .mem_rsp_valid(ui_mem_rsp_valid&&owned&&owner_ppu),.mem_rsp_ready(ppu_response_ready),
        .mem_rsp_rdata(ui_mem_rsp_rdata),.mem_rsp_error(ui_mem_rsp_error)
    );
endmodule
/* verilator lint_on DECLFILENAME */
