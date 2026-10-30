// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// UNSELECTED integration candidate. No board/CDC/timing qualification.
// power_rst_n is configuration-only and shared with the SYS controller.
// UI gate/handshake state MUST survive the whole-transaction client reset.
module rk_whole_reset_ui_bridge #(
    parameter integer SYNC_STAGES = 3,
    parameter integer UI_FRESH_CYCLES = 4
) (
    input wire sys_clk, ui_clk, power_rst_n,
    input wire sys_quiesce_request,
    input wire coordinator_ready,
    output wire controller_reset_ready,
    output wire sys_quiesce_ack, sys_quiescent, sys_platform_ready,
    output wire ui_admission_block,
    input wire ui_drained, ui_platform_ready,
    // Actual client-epoch reset; invalidates readiness, never gate/owner state.
    input wire ui_clients_rst_n,
    output wire bridge_fault
);
    localparam integer STAGES=SYNC_STAGES<3?3:SYNC_STAGES;
    localparam integer FRESH=UI_FRESH_CYCLES<1?1:UI_FRESH_CYCLES;
    typedef enum logic [2:0] {BOOT_HIGH,RETURN_LOW,IDLE,WAIT_HIGH,ACTIVE,FAULT} state_t;
    state_t state;
    logic retained_request;
    logic ui_quiet_published,ui_ready_published;
    logic [31:0] ui_fresh_count;
    logic ui_fresh;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [STAGES-1:0] request_sync;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [STAGES-1:0] ack_sync,quiet_sync;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [STAGES-1:0] ready_sync;
    // A return-to-zero handshake is completed even after early CANCEL. Merely
    // sampling ACK=0 before an old request reaches UI is not a fresh boundary.
    assign ui_admission_block=request_sync[STAGES-1];
    assign bridge_fault=state===FAULT;
    assign controller_reset_ready=(coordinator_ready===1'b1)&&
        (((state===IDLE)&&(sys_quiesce_request===1'b0))||
         ((state===ACTIVE)&&(sys_quiesce_request===1'b1)&&(ack_sync[STAGES-1]===1'b1)));
    assign sys_quiesce_ack=(state===ACTIVE)&&(sys_quiesce_request===1'b1)&&ack_sync[STAGES-1];
    assign sys_quiescent=sys_quiesce_ack&&quiet_sync[STAGES-1];
    assign sys_platform_ready=ready_sync[STAGES-1];

    initial begin
        if((^SYNC_STAGES)===1'bx||SYNC_STAGES<3||SYNC_STAGES>16||
           (^UI_FRESH_CYCLES)===1'bx||UI_FRESH_CYCLES<1||UI_FRESH_CYCLES>65536)
            $fatal(1,"Invalid whole-reset UI bridge synchronization/freshness");
    end

    // Retained admission gate only. ui_clients_rst_n must not reset this path:
    // an asserted request must block new frames through stopped/reset UI clocks.
    always @(posedge ui_clk or negedge power_rst_n)begin
        if(!power_rst_n)begin request_sync<=0;ui_quiet_published<=0;end
        else begin
            request_sync<={request_sync[STAGES-2:0],retained_request};
            ui_quiet_published<=ui_admission_block?ui_drained:1'b0;
        end
    end
    always @(posedge sys_clk or negedge power_rst_n)begin
        if(!power_rst_n)begin ack_sync<=0;quiet_sync<=0;end
        else begin
            ack_sync<={ack_sync[STAGES-2:0],ui_admission_block};
            quiet_sync<={quiet_sync[STAGES-2:0],ui_quiet_published};
        end
    end

    // Immediate invalidation survives a stopped UI clock. Deassertion only
    // enables local edge counting; data cannot publish until fresh UI edges.
    wire ready_rst_n=power_rst_n&&ui_clients_rst_n;
    // Asynchronous assertion invalidates both domains even with a stopped UI
    // clock. Each domain releases its own readiness registers on local edges.
    // Split the output stage from the shift vector. The local reset output
    // is not itself synchronous shift data; only its preceding stages are.
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [STAGES-2:0] ready_ui_pipe,ready_sys_pipe;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic ready_ui_rst_n,ready_sys_rst_n;
    always @(posedge ui_clk or negedge ready_rst_n)begin
        if(!ready_rst_n)begin ready_ui_pipe<=0;ready_ui_rst_n<=0;end
        else begin
            ready_ui_pipe<={ready_ui_pipe[STAGES-3:0],1'b1};
            ready_ui_rst_n<=ready_ui_pipe[STAGES-2];
        end
    end
    always @(posedge sys_clk or negedge ready_rst_n)begin
        if(!ready_rst_n)begin ready_sys_pipe<=0;ready_sys_rst_n<=0;end
        else begin
            ready_sys_pipe<={ready_sys_pipe[STAGES-3:0],1'b1};
            ready_sys_rst_n<=ready_sys_pipe[STAGES-2];
        end
    end

    always @(posedge ui_clk or negedge ready_ui_rst_n)begin
        if(!ready_ui_rst_n)begin ui_ready_published<=0;ui_fresh_count<=0;ui_fresh<=0;end
        else begin
            if(!ui_fresh)begin
                if(({1'b0,ui_fresh_count}+33'd1)>={1'b0,32'(FRESH)})ui_fresh<=1;
                else ui_fresh_count<=ui_fresh_count+1'b1;
            end
            ui_ready_published<=ui_fresh?ui_platform_ready:1'b0;
        end
    end
    always @(posedge sys_clk or negedge ready_sys_rst_n)begin
        if(!ready_sys_rst_n)ready_sync<=0;
        else ready_sync<={ready_sync[STAGES-2:0],ui_ready_published};
    end

    always @(posedge sys_clk or negedge power_rst_n)begin
        if(!power_rst_n)begin state<=BOOT_HIGH;retained_request<=1;end
        else case(state)
            BOOT_HIGH:if(ack_sync[STAGES-1]===1'b1)begin
                retained_request<=0;state<=RETURN_LOW;
            end
            RETURN_LOW:if(ack_sync[STAGES-1]===1'b0)state<=IDLE;
            IDLE:if(sys_quiesce_request===1'b1)begin retained_request<=1;state<=WAIT_HIGH;end
            WAIT_HIGH:if(ack_sync[STAGES-1]===1'b1)begin
                if(sys_quiesce_request===1'b0)begin retained_request<=0;state<=RETURN_LOW;end
                else if(sys_quiesce_request===1'b1)state<=ACTIVE;
            end
            ACTIVE:begin
                if(sys_quiesce_request===1'b0)begin retained_request<=0;state<=RETURN_LOW;end
                else if(ack_sync[STAGES-1]!==1'b1)begin state<=FAULT;retained_request<=1;end
            end
            FAULT:begin retained_request<=1;end
            default:begin state<=FAULT;retained_request<=1;end
        endcase
    end
endmodule
