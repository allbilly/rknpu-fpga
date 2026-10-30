// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Unselected clock/link qualifier. No frontend reset, ownership or recovery.
// The existing retained epoch guard must latch any later loss of this level.
module rk_pcie_source_health #(
    parameter integer SYNC_STAGES=3,
    parameter integer HEARTBEAT_BITS=6,
    parameter integer REQUIRED_TRANSITIONS=2,
    parameter integer TIMEOUT_UI_CYCLES=1024
) (
    input wire ui_clk,pcie_clk,joint_reset_n,
    input wire pcie_link_up,pcie_axi_aresetn,bridge_ready_ui,
    output wire source_healthy,
    output logic clock_alive
);
    localparam integer STAGES=SYNC_STAGES<3?3:SYNC_STAGES;
    localparam integer DIV_W=HEARTBEAT_BITS<2?2:HEARTBEAT_BITS;
    // Sanitize elaboration only; invalid requested values still fatal below.
    localparam integer TRANSITIONS_N=REQUIRED_TRANSITIONS<2?2:REQUIRED_TRANSITIONS;
    localparam integer SEEN_W=$clog2(TRANSITIONS_N+1);
    localparam integer AGE_W=TIMEOUT_UI_CYCLES<2?2:$clog2(TIMEOUT_UI_CYCLES+1);
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [STAGES-2:0] pcie_release_early,ui_release_early;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic pcie_local_rst_n,ui_local_rst_n;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [STAGES-2:0] available_early;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic available_ui;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [STAGES-1:0] heartbeat_sync;
    logic [DIV_W-1:0] heartbeat_count;
    logic heartbeat_last;
    logic [SEEN_W-1:0] transitions;
    logic [AGE_W-1:0] age;
    wire available_reset_n=joint_reset_n&&pcie_link_up&&pcie_axi_aresetn;

    initial begin
        if(SYNC_STAGES<3||SYNC_STAGES>8||HEARTBEAT_BITS<2||HEARTBEAT_BITS>10||
           REQUIRED_TRANSITIONS<2||REQUIRED_TRANSITIONS>64||
           TIMEOUT_UI_CYCLES<8||TIMEOUT_UI_CYCLES>1000000)
            $fatal(1,"Invalid PCIe health synchronization/heartbeat/deadline parameters");
    end
    // Common assertion and separately clock-qualified local release. The last
    // reset stage is scalar so vector bits have no mixed reset/status role.
    always @(posedge pcie_clk or negedge joint_reset_n)begin
        if(joint_reset_n!==1'b1)begin pcie_release_early<=0;pcie_local_rst_n<=0;end
        else begin
            pcie_release_early<={pcie_release_early[STAGES-3:0],1'b1};
            pcie_local_rst_n<=pcie_release_early[STAGES-2];
        end
    end
    always @(posedge ui_clk or negedge joint_reset_n)begin
        if(joint_reset_n!==1'b1)begin ui_release_early<=0;ui_local_rst_n<=0;end
        else begin
            ui_release_early<={ui_release_early[STAGES-3:0],1'b1};
            ui_local_rst_n<=ui_release_early[STAGES-2];
        end
    end
    // A short link/reset loss is retained as at least STAGES low UI samples,
    // even if the PCIe clock has stopped. Link reset never clears the epoch.
    always @(posedge ui_clk or negedge available_reset_n)begin
        if(available_reset_n!==1'b1)begin available_early<=0;available_ui<=0;end
        else begin
            available_early<={available_early[STAGES-3:0],1'b1};
            available_ui<=available_early[STAGES-2];
        end
    end
    always @(posedge pcie_clk or negedge pcie_local_rst_n)begin
        if(!pcie_local_rst_n)heartbeat_count<=0;
        else heartbeat_count<=heartbeat_count+DIV_W'(1);
    end
    always @(posedge ui_clk or negedge ui_local_rst_n)begin
        if(!ui_local_rst_n)begin
            heartbeat_sync<=0;heartbeat_last<=0;transitions<=0;age<=0;clock_alive<=0;
        end else begin
            heartbeat_sync<={heartbeat_sync[STAGES-2:0],heartbeat_count[DIV_W-1]};
            if(heartbeat_sync[STAGES-1]!==1'b0&&heartbeat_sync[STAGES-1]!==1'b1)begin
                heartbeat_last<=0;transitions<=0;age<=0;clock_alive<=0;
            end else if(heartbeat_sync[STAGES-1]!==heartbeat_last)begin
                heartbeat_last<=heartbeat_sync[STAGES-1];age<=0;
                if(transitions<SEEN_W'(TRANSITIONS_N))transitions<=transitions+SEEN_W'(1);
                if(transitions>=SEEN_W'(TRANSITIONS_N-1))clock_alive<=1;
            end else if(age>=AGE_W'(TIMEOUT_UI_CYCLES-1))begin
                age<=AGE_W'(TIMEOUT_UI_CYCLES);transitions<=0;clock_alive<=0;
            end else age<=age+AGE_W'(1);
        end
    end
    // Local reset asserts asynchronously from joint_reset_n and releases only
    // after STAGES UI edges. Keep the published level entirely in the UI
    // domain; a direct SYS term would recreate a combinational CDC fanout.
    assign source_healthy=ui_local_rst_n===1'b1&&
        available_ui===1'b1&&clock_alive===1'b1&&bridge_ready_ui===1'b1;
endmodule
