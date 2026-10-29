// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Preparation candidate only. Reset the drained compute/crossing island;
// DDR/controller/fabric/ECC/job-control reset pins must NEVER use these outputs.
// The parent must derive exact quiet/ready witnesses and gate new admission.
module rk_quiescent_compute_reset #(
    parameter integer SYNC_STAGES=3,
    parameter integer HOLD_CYCLES=4,
    parameter integer FRESH_CYCLES=4,
    parameter integer TIMEOUT_CYCLES=65536
) (
    input wire ui_clk,ui_rst_n,ui_healthy,ui_quiet,ui_restart_ready,
    input wire request_valid,
    output wire request_ready,admission_blocked,result_valid,result_error,
    output wire [7:0] error_code,
    input wire result_ready,
    output logic [31:0] reset_epoch,
    output wire ui_compute_rst_n,
    input wire core_clk,core_rst_n,core_healthy,core_quiet,
    output wire core_admission_blocked,core_compute_rst_n
);
    typedef enum logic [2:0] {U_IDLE,U_QUIET,U_HOLD,U_RELEASE,U_DONE,U_FAILED} u_state_t;
    typedef enum logic [2:0] {C_IDLE,C_QUIET,C_HOLD,C_FRESH,C_DONE,C_FAILED} c_state_t;
    u_state_t us;
    c_state_t cs;
    logic block_level,reset_level,ui_release,core_release;
    logic quiet_level,held_level,released_level,idle_level,core_fault;
    logic [7:0] saved_code;
    logic [31:0] ui_wait,core_wait,ui_stable,core_stable;
    logic reset_started;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [SYNC_STAGES-1:0] block_sync,reset_sync;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [SYNC_STAGES-1:0] quiet_sync,held_sync,released_sync,idle_sync,fault_sync;
    wire block_seen=block_sync[SYNC_STAGES-1];
    wire reset_seen=reset_sync[SYNC_STAGES-1];
    assign request_ready=ui_rst_n&&us==U_IDLE&&ui_healthy===1'b1&&idle_sync[SYNC_STAGES-1]&&
        !held_sync[SYNC_STAGES-1]&&!released_sync[SYNC_STAGES-1]&&!fault_sync[SYNC_STAGES-1];
    assign admission_blocked=ui_rst_n&&(us!=U_IDLE||!request_ready);
    assign core_admission_blocked=core_rst_n&&(block_seen||cs!=C_IDLE||core_fault);
    assign ui_compute_rst_n=ui_rst_n&&ui_release;
    // One registered UI authorization asserts BOTH empty compute islands
    // asynchronously. Otherwise clearing UI toggle state can reach CORE
    // synchronizers before CORE reset and look like a new request epoch.
    // Deassertion remains CORE-clocked: ui_release rises only after CORE has
    // latched core_release low and acknowledged four fresh reset edges.
    assign core_compute_rst_n=core_rst_n&&ui_release&&core_release;
    assign result_valid=ui_rst_n&&(us==U_DONE||us==U_FAILED);
    assign result_error=ui_rst_n&&us==U_FAILED;
    assign error_code=result_error ? saved_code : 8'd0;
    initial if(SYNC_STAGES<3||HOLD_CYCLES<2||FRESH_CYCLES<2||TIMEOUT_CYCLES<1)
        $fatal(1,"Invalid quiescent-reset timing contract");
    always @(posedge ui_clk or negedge ui_rst_n)begin
        if(!ui_rst_n)begin quiet_sync<=0;held_sync<=0;released_sync<=0;idle_sync<=0;fault_sync<=0;end
        else begin
            quiet_sync<={quiet_sync[SYNC_STAGES-2:0],quiet_level};
            held_sync<={held_sync[SYNC_STAGES-2:0],held_level};
            released_sync<={released_sync[SYNC_STAGES-2:0],released_level};
            idle_sync<={idle_sync[SYNC_STAGES-2:0],idle_level};
            fault_sync<={fault_sync[SYNC_STAGES-2:0],core_fault};
        end
    end
    always @(posedge core_clk or negedge core_rst_n)begin
        if(!core_rst_n)begin block_sync<=0;reset_sync<=0;end
        else begin
            block_sync<={block_sync[SYNC_STAGES-2:0],block_level};
            reset_sync<={reset_sync[SYNC_STAGES-2:0],reset_level};
        end
    end
    task automatic ui_fail(input logic [7:0] code);
        us<=U_FAILED;saved_code<=code;block_level<=1;
        // Before reset authorization, leave all owned compute channels alive.
        // Once reset has begun, fail closed until the global joint reset.
        if(reset_started)begin ui_release<=0;reset_level<=1;end
    endtask
    always @(posedge ui_clk or negedge ui_rst_n)begin
        if(!ui_rst_n)begin
            us<=U_IDLE;block_level<=0;reset_level<=0;ui_release<=1;
            saved_code<=0;ui_wait<=0;ui_stable<=0;reset_epoch<=0;reset_started<=0;
        end else if(us!=U_FAILED)begin
            if(us!=U_IDLE&&ui_healthy!==1'b1)ui_fail(5);
            else if(fault_sync[SYNC_STAGES-1])ui_fail(5);
            else if(us!=U_IDLE&&us!=U_DONE&&ui_wait==TIMEOUT_CYCLES-1)ui_fail(8);
            else begin
                if(us==U_IDLE||us==U_DONE)ui_wait<=0;
                else ui_wait<=ui_wait+1'b1;
                case(us)
                    U_IDLE:if(request_valid&&request_ready)begin
                        if(reset_epoch==32'hffffffff)ui_fail(6);
                        else begin us<=U_QUIET;block_level<=1;ui_wait<=0;ui_stable<=0;reset_started<=0;end
                    end
                    U_QUIET:begin
                        if(ui_quiet===1'b1&&quiet_sync[SYNC_STAGES-1])begin
                            if(ui_stable==1)begin
                                ui_release<=0;reset_level<=1;reset_started<=1;
                                us<=U_HOLD;ui_wait<=0;ui_stable<=0;
                            end else ui_stable<=ui_stable+1'b1;
                        end else ui_stable<=0;
                    end
                    U_HOLD:begin
                        if(ui_quiet!==1'b1)ui_fail(6);
                        else begin
                            if(ui_stable<HOLD_CYCLES)ui_stable<=ui_stable+1'b1;
                            if(ui_stable>=HOLD_CYCLES-1&&held_sync[SYNC_STAGES-1])begin
                                ui_release<=1;reset_level<=0;us<=U_RELEASE;ui_wait<=0;ui_stable<=0;
                            end
                        end
                    end
                    U_RELEASE:begin
                        if(ui_quiet!==1'b1)ui_fail(6);
                        else if(released_sync[SYNC_STAGES-1]&&ui_restart_ready===1'b1)begin
                            reset_epoch<=reset_epoch+1'b1;us<=U_DONE;ui_wait<=0;
                        end
                    end
                    U_DONE:if(result_ready)begin
                        us<=U_IDLE;block_level<=0;reset_started<=0;ui_stable<=0;
                    end
                    default:ui_fail(6);
                endcase
            end
        end
    end
    task automatic core_fail;
        cs<=C_FAILED;core_fault<=1;idle_level<=0;
        if(cs==C_HOLD||cs==C_FRESH||cs==C_DONE)core_release<=0;
    endtask
    always @(posedge core_clk or negedge core_rst_n)begin
        if(!core_rst_n)begin
            cs<=C_IDLE;core_release<=1;quiet_level<=0;held_level<=0;released_level<=0;
            idle_level<=0;core_fault<=0;core_wait<=0;core_stable<=0;
        end else if(cs!=C_FAILED)begin
            if(cs!=C_IDLE&&core_healthy!==1'b1)core_fail();
            else if(cs!=C_IDLE&&cs!=C_DONE&&core_wait==TIMEOUT_CYCLES-1)core_fail();
            else begin
                if(cs==C_IDLE||cs==C_DONE)core_wait<=0;
                else core_wait<=core_wait+1'b1;
                case(cs)
                    C_IDLE:begin
                        idle_level<=core_healthy===1'b1;
                        if(block_seen)begin cs<=C_QUIET;idle_level<=0;core_stable<=0;core_wait<=0;end
                    end
                    C_QUIET:begin
                        if(!block_seen)core_fail();
                        else if(core_quiet===1'b1)begin
                            if(core_stable>=1)quiet_level<=1;
                            else core_stable<=core_stable+1'b1;
                            if(reset_seen)begin
                                if(!quiet_level)core_fail();
                                else begin core_release<=0;cs<=C_HOLD;core_stable<=0;core_wait<=0;end
                            end
                        end else begin
                            quiet_level<=0;core_stable<=0;
                            if(reset_seen)core_fail();
                        end
                    end
                    C_HOLD:begin
                        if(core_quiet!==1'b1||!block_seen)core_fail();
                        else if(!reset_seen)begin
                            if(!held_level)core_fail();
                            else begin core_release<=1;cs<=C_FRESH;core_stable<=0;core_wait<=0;end
                        end else begin
                            if(core_stable>=HOLD_CYCLES-1)held_level<=1;
                            else core_stable<=core_stable+1'b1;
                        end
                    end
                    C_FRESH:begin
                        if(core_quiet!==1'b1||reset_seen||!block_seen)core_fail();
                        else if(core_stable>=FRESH_CYCLES-1)begin released_level<=1;cs<=C_DONE;end
                        else core_stable<=core_stable+1'b1;
                    end
                    C_DONE:begin
                        if(reset_seen||core_quiet!==1'b1)core_fail();
                        else if(!block_seen)begin
                            quiet_level<=0;held_level<=0;released_level<=0;idle_level<=1;cs<=C_IDLE;
                        end
                    end
                    default:core_fail();
                endcase
            end
        end
    end
endmodule
