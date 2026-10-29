// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One UI numerical-job slot across the existing raw EW and full512 CMAC
// bridges. Selection stays in UI; each engine has its own descriptor crossing.
// This is not DDR retirement or host ACK. The containing DDR owner must hold
// admission through fence/ECC/readback/ACK after consuming numerical status.
module rk_dual_async_dispatch #(
    parameter int unsigned TIMEOUT_CYCLES=65536,
    parameter int unsigned MAX_TASKS=4095,
    parameter int unsigned SYNC_STAGES=3
) (
    input wire ui_clk,ui_rst_n,ui_admission_enable,ui_rearm_permit,
    input wire ui_start_valid,ui_start_cmac,
    output wire ui_start_ready,ui_ew_start_ready,ui_cmac_start_ready,
    input wire [31:0] ui_start_address,ui_start_amount,
    output wire ui_result_valid,ui_result_error,
    output wire [7:0] ui_result_code,
    output wire [31:0] ui_result_tasks,
    input wire ui_result_ready,
    output wire ui_fault,
    input wire core_clk,core_rst_n,
    output wire ui_mem_req_valid,ui_mem_req_write,
    output wire [31:0] ui_mem_req_addr,
    output wire [15:0] ui_mem_req_wdata,
    input wire ui_mem_req_ready,ui_mem_rsp_valid,
    input wire [15:0] ui_mem_rsp_rdata,
    input wire ui_mem_rsp_error,
    output wire ui_mem_rsp_ready
);
    logic owned,owner_cmac,memory_pending,local_fault;
    wire ew_ready,cm_ready,ew_result,cm_result,ew_error,cm_error,ew_fault,cm_fault;
    wire [7:0] ew_code,cm_code;
    wire [31:0] ew_tasks,cm_tasks;
    wire ew_request,cm_request,ew_write,cm_write,ew_response_ready,cm_response_ready;
    wire [31:0] ew_address,cm_address;
    wire [15:0] ew_data,cm_data;
    wire known_selection=(ui_start_cmac===1'b0)||(ui_start_cmac===1'b1);
    wire slot_free=ui_rst_n&&!owned&&!ui_fault;
    assign ui_ew_start_ready=slot_free&&ew_ready;
    assign ui_cmac_start_ready=slot_free&&cm_ready;
    assign ui_start_ready=known_selection&&(ui_start_cmac ? ui_cmac_start_ready : ui_ew_start_ready);
    assign ui_result_valid=ui_rst_n&&owned&&(owner_cmac ? cm_result : ew_result);
    assign ui_result_error=owned&&(owner_cmac ? cm_error : ew_error);
    assign ui_result_code=owned ? (owner_cmac ? cm_code : ew_code) : 8'b0;
    assign ui_result_tasks=owned ? (owner_cmac ? cm_tasks : ew_tasks) : 32'b0;
    // Never withdraw an owned/offered memory transfer on fault or admission
    // revocation. A failed owner stays selected until the coordinated reset.
    assign ui_mem_req_valid=ui_rst_n&&owned&&(owner_cmac ? cm_request : ew_request);
    assign ui_mem_req_write=owned&&(owner_cmac ? cm_write : ew_write);
    assign ui_mem_req_addr=owned ? (owner_cmac ? cm_address : ew_address) : 32'b0;
    assign ui_mem_req_wdata=owned ? (owner_cmac ? cm_data : ew_data) : 16'b0;
    assign ui_mem_rsp_ready=ui_rst_n&&owned&&(owner_cmac ? cm_response_ready : ew_response_ready);
    wire request_fire=ui_mem_req_valid&&ui_mem_req_ready;
    wire response_fire=ui_mem_rsp_valid&&ui_mem_rsp_ready;
    wire bad_owner=(!owned&&(ew_request||cm_request||ew_result||cm_result))||
        (owned&&(owner_cmac ? (ew_request||ew_result) : (cm_request||cm_result)));
    // An offered second request is already a protocol violation while the
    // first response is pending. Detect it independently of downstream READY:
    // platform faults may revoke READY, so using request_fire here feeds that
    // fault back into admission and creates a combinational cycle in DDR.
    wire bad_memory=(ui_mem_req_valid&&memory_pending&&!response_fire)||
                    (ui_mem_rsp_valid&&!memory_pending);
    wire bad_success=ui_result_valid&&!ui_result_error&&
                     (memory_pending||ui_mem_req_valid||ui_mem_rsp_valid);
    wire bad_selection=ui_start_valid&&!owned&&!known_selection;
    assign ui_fault=ui_rst_n&&(local_fault||ew_fault||cm_fault||
        bad_owner||bad_memory||bad_success||bad_selection);

    always_ff @(posedge ui_clk or negedge ui_rst_n)begin
        if(!ui_rst_n)begin owned<=0;owner_cmac<=0;memory_pending<=0;local_fault<=0;end
        else begin
            if(bad_owner||bad_memory||bad_success||bad_selection)local_fault<=1;
            if(ui_start_valid&&ui_start_ready)begin owned<=1;owner_cmac<=ui_start_cmac;end
            case({request_fire,response_fire})
                2'b10:memory_pending<=1;
                2'b01:memory_pending<=0;
                default:begin end
            endcase
            if(ui_result_valid&&ui_result_ready&&!ui_result_error&&!ui_fault)
                owned<=0;
        end
    end

    rk_ew_async_engine #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES),.MAX_TASKS(MAX_TASKS),
        .JOB_SYNC_STAGES(SYNC_STAGES),.MEMORY_SYNC_STAGES(SYNC_STAGES)) ew (
        .ui_clk,.ui_rst_n,.ui_admission_enable(ui_admission_enable&&!ui_fault),
        .ui_start_valid(ui_start_valid&&!owned&&(ui_start_cmac===1'b0)),.ui_start_ready(ew_ready),
        .ui_start_address,.ui_start_amount,.ui_result_valid(ew_result),.ui_result_error(ew_error),
        .ui_result_code(ew_code),.ui_result_tasks(ew_tasks),
        .ui_result_ready(ui_result_ready&&owned&&!owner_cmac),.ui_fault(ew_fault),
        .core_clk,.core_rst_n,.ui_mem_req_valid(ew_request),
        .ui_mem_req_ready(ui_mem_req_ready&&owned&&!owner_cmac),.ui_mem_req_write(ew_write),
        .ui_mem_req_addr(ew_address),.ui_mem_req_wdata(ew_data),
        .ui_mem_rsp_valid(ui_mem_rsp_valid&&owned&&!owner_cmac),
        .ui_mem_rsp_rdata,.ui_mem_rsp_error,.ui_mem_rsp_ready(ew_response_ready)
    );
    rk_cmac_async_engine #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES),
        .JOB_SYNC_STAGES(SYNC_STAGES),.MEMORY_SYNC_STAGES(SYNC_STAGES),
        .PERMIT_SYNC_STAGES(SYNC_STAGES)) cmac (
        .ui_clk,.ui_rst_n,.ui_admission_enable(ui_admission_enable&&!ui_fault),.ui_rearm_permit,
        .ui_start_valid(ui_start_valid&&!owned&&(ui_start_cmac===1'b1)),.ui_start_ready(cm_ready),
        .ui_start_address,.ui_start_amount,.ui_result_valid(cm_result),.ui_result_error(cm_error),
        .ui_result_code(cm_code),.ui_result_tasks(cm_tasks),
        .ui_result_ready(ui_result_ready&&owned&&owner_cmac),.ui_fault(cm_fault),
        .core_clk,.core_rst_n,.ui_mem_req_valid(cm_request),
        .ui_mem_req_ready(ui_mem_req_ready&&owned&&owner_cmac),.ui_mem_req_write(cm_write),
        .ui_mem_req_addr(cm_address),.ui_mem_req_wdata(cm_data),
        .ui_mem_rsp_valid(ui_mem_rsp_valid&&owned&&owner_cmac),
        .ui_mem_rsp_rdata,.ui_mem_rsp_error,.ui_mem_rsp_ready(cm_response_ready)
    );
endmodule
