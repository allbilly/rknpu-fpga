// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Successful standalone CMAC ownership: run, observe drained memory, reset
// only the owned CMAC engine, then publish completion. A fault never rearms.
// Shared RAM/mailbox/job-control resets remain exclusively global.
module rk_cmac_success_rearm #(
    parameter int unsigned TIMEOUT_CYCLES=65536
) (
    input wire clk,rst_n,start_valid,
    output wire start_ready,
    input wire [31:0] start_address,start_amount,
    input wire rearm_allowed,memory_pending,
    output wire busy,done,error,
    output wire [7:0] error_code,
    output logic [31:0] completed_tasks,rearm_count,
    output wire mem_req_valid,
    input wire mem_req_ready,
    output wire mem_req_write,
    output wire [31:0] mem_req_addr,
    output wire [15:0] mem_req_wdata,
    input wire mem_rsp_valid,
    output wire mem_rsp_ready,
    input wire [15:0] mem_rsp_rdata,
    input wire mem_rsp_error
);
    typedef enum logic [2:0] {IDLE,RUN,DRAIN,RESET_ENGINE,RELEASE_ENGINE,FINISH,FAILED} state_t;
    state_t state;
    logic [31:0] wait_cycles;
    logic [1:0] stable_cycles;
    logic [7:0] saved_code;
    logic child_release;
    wire child_ready,child_busy,child_done,child_error;
    wire unused_acknowledged,unused_frame_done;
    wire [7:0] child_code;
    wire child_req,child_rsp_ready;
    logic allowed;
    always @* begin
        allowed=0;
        case(rearm_allowed)1'b1:allowed=1;default:allowed=0;endcase
    end
    // Only a dedicated registered release FF drives local reset. Decoding
    // state directly could transiently hit RESET_ENGINE on a multi-bit FSM
    // transition, asserting reset before the drain guard had authorized it.
    wire child_rst_n=rst_n&&child_release;
    wire drained=!memory_pending&&!mem_rsp_valid&&!child_req&&!child_busy;
    assign start_ready=rst_n&&state==IDLE&&child_ready&&allowed&&!child_error;
    assign busy=rst_n&&state!=IDLE&&state!=FAILED;
    assign done=rst_n&&state==FINISH&&!error;
    assign error=rst_n&&(state==FAILED||child_error);
    assign error_code=!rst_n ? 8'd0 : state==FAILED ? saved_code : child_code;
    // No accepted request or response is discarded by success reset: these
    // channels are only quiescent when RESET_ENGINE becomes reachable.
    assign mem_req_valid=rst_n&&child_req;
    assign mem_rsp_ready=rst_n&&child_rsp_ready;
    rk_cmac_array_dma #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) engine(
        .clk,.rst_n(child_rst_n),.start_valid(start_valid&&state==IDLE&&allowed),
        .start_ready(child_ready),.start_address,.start_amount,.busy(child_busy),.done(child_done),
        .acknowledged(unused_acknowledged),.frame_done(unused_frame_done),.error(child_error),.error_code(child_code),
        .mem_req_valid(child_req),.mem_req_ready,.mem_req_write,.mem_req_addr,.mem_req_wdata,
        .mem_rsp_valid,.mem_rsp_ready(child_rsp_ready),.mem_rsp_rdata,.mem_rsp_error);
    initial if(TIMEOUT_CYCLES==0)$fatal(1,"Invalid CMAC rearm timeout");
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;wait_cycles<=0;stable_cycles<=0;saved_code<=0;
            completed_tasks<=0;rearm_count<=0;child_release<=1;
        end else if(state!=FAILED)begin
            if(child_error)begin state<=FAILED;saved_code<=child_code;end
            else case(state)
                IDLE:if(start_valid&&start_ready)begin
                    state<=RUN;completed_tasks<=0;stable_cycles<=0;wait_cycles<=0;
                end
                RUN:if(child_done)begin
                    if(!allowed)begin state<=FAILED;saved_code<=6;end
                    else begin completed_tasks<=1;state<=DRAIN;stable_cycles<=0;wait_cycles<=0;end
                end
                DRAIN:begin
                    if(!allowed)begin state<=FAILED;saved_code<=6;end
                    else if(drained)begin
                        if(stable_cycles==1)begin
                            state<=RESET_ENGINE;stable_cycles<=0;child_release<=0;
                        end
                        else stable_cycles<=stable_cycles+1'b1;
                    end else stable_cycles<=0;
                    if(wait_cycles==TIMEOUT_CYCLES-1)begin state<=FAILED;saved_code<=8;end
                    else wait_cycles<=wait_cycles+1'b1;
                end
                RESET_ENGINE:begin
                    if(!allowed||memory_pending||mem_rsp_valid||child_req)begin state<=FAILED;saved_code<=6;end
                    else if(stable_cycles==1)begin
                        state<=RELEASE_ENGINE;stable_cycles<=0;wait_cycles<=0;
                        rearm_count<=rearm_count+1'b1;child_release<=1;
                    end else stable_cycles<=stable_cycles+1'b1;
                end
                RELEASE_ENGINE:begin
                    if(!allowed||memory_pending||mem_rsp_valid||child_req)begin state<=FAILED;saved_code<=6;end
                    else if(child_ready&&stable_cycles==1)begin state<=FINISH;stable_cycles<=0;end
                    else if(child_ready)stable_cycles<=stable_cycles+1'b1;
                    else stable_cycles<=0;
                    if(wait_cycles==TIMEOUT_CYCLES-1)begin state<=FAILED;saved_code<=8;end
                    else wait_cycles<=wait_cycles+1'b1;
                end
                FINISH:state<=IDLE;
                default:begin state<=FAILED;saved_code<=6;end
            endcase
        end
    end
endmodule
