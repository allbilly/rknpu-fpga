// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Reset sequencing for a NEW owned SYS50/UI0/UI1 boundary, not the original
// MicroBlaze/XDMA/USER2 platform. Every client must remain transaction-passive
// while admission_blocked: this signal blocks NEW admission, never AXI valids.
// Branches release before their acknowledgments return; completion proves only
// this sequence, not draining, allocation initialization, clock liveness or jobs.
// Assert cfg_reset at bootstrap; its deassertion MUST be SYS-clock synchronous
// (e.g. the existing SYS startup register), not an asynchronous R28 pin. Each
// UI branch independently conditions reset release. Physical mapping is pending.
module rk_mig_reset_coordinator #(
    parameter int unsigned SYS_HOLD_CYCLES = 64,
    parameter int unsigned UI_FRESH_CYCLES = 4,
    parameter int unsigned SYNC_STAGES = 3,
    parameter int unsigned WAIT_TIMEOUT_CYCLES = 65536
) (
    input logic sys_clk, cfg_reset,
    input logic reset_req_valid,
    output logic reset_req_ready,
    input logic c0_ui_clk, c1_ui_clk,
    input logic c0_ui_clk_sync_rst, c1_ui_clk_sync_rst,
    output logic mig_sys_rst_n, sys_clients_rst_n,
    output logic c0_clients_rst_n, c1_clients_rst_n,
    output logic c0_aresetn, c1_aresetn,
    output logic sequence_busy, sequence_complete, admission_blocked,
    output logic sequence_fault,
    output logic [7:0] sequence_fault_code
);
    localparam integer STAGES = SYNC_STAGES < 2 ? 2 : SYNC_STAGES;
    typedef enum logic [2:0] {HOLD, QUALIFY, RELEASE, COMPLETE, FAULT} state_t;
    state_t state;
    logic [31:0] hold_cycles, wait_cycles;
    logic release_permit, release_started;
    logic [1:0] assertion_seen, low_seen;
    logic c0_fresh, c1_fresh;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] reset0_sync, reset1_sync;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] fresh0_sync, fresh1_sync;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] release0_sync, release1_sync;
    logic [STAGES-1:0] sys_release_pipe;
    logic fault_now;
    logic [7:0] fault_now_code;
    wire restart = reset_req_ready && reset_req_valid === 1'b1;
    wire epoch_assert = cfg_reset | ~mig_sys_rst_n;
    wire both_fresh = fresh0_sync[STAGES-1] === 1'b1 && fresh1_sync[STAGES-1] === 1'b1;
    wire branches_released = sys_clients_rst_n && release0_sync[STAGES-1] === 1'b1 &&
                              release1_sync[STAGES-1] === 1'b1;

    initial begin
        if (SYS_HOLD_CYCLES == 0 || UI_FRESH_CYCLES == 0 || SYNC_STAGES < 2 || WAIT_TIMEOUT_CYCLES == 0)
            $fatal(1,"Reset coordinator requires positive counts and at least two synchronizer stages");
    end

    assign c0_aresetn = c0_clients_rst_n;
    assign c1_aresetn = c1_clients_rst_n;
    assign reset_req_ready = cfg_reset === 1'b0 && (state == COMPLETE || state == FAULT);
    assign sequence_busy = cfg_reset !== 1'b0 || restart || (state != COMPLETE && state != FAULT);
    assign sequence_complete = cfg_reset === 1'b0 && state == COMPLETE && !sequence_fault && !fault_now && !restart;
    assign admission_blocked = !sequence_complete;

    // A level witness crosses each way. No pulse/counter bus crosses domains.
    for (genvar domain=0;domain<2;domain=domain+1) begin: ui_domain
        wire clk = domain == 0 ? c0_ui_clk : c1_ui_clk;
        wire ui_reset = domain == 0 ? c0_ui_clk_sync_rst : c1_ui_clk_sync_rst;
        (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-2:0] reset_pipe;
        (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic local_rst_n;
        (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] assertion_sync, permit_sync;
        logic [31:0] fresh_cycles;
        logic fresh, clients_rst_n;
        if (domain == 0) begin: channel0
            assign c0_fresh = fresh;
            assign c0_clients_rst_n = clients_rst_n;
        end else begin: channel1
            assign c1_fresh = fresh;
            assign c1_clients_rst_n = clients_rst_n;
        end
        // Only this bridge sees the raw SYS-domain reset. Functional reset
        // pins assert without a clock and deassert after local clock edges.
        always_ff @(posedge clk or posedge epoch_assert) begin
            if (epoch_assert) begin reset_pipe <= 0; local_rst_n <= 0; end
            else begin
                reset_pipe <= (reset_pipe << 1) | {{(STAGES-2){1'b0}},1'b1};
                local_rst_n <= reset_pipe[STAGES-2];
            end
        end
        // Revocation must erase a partially received permit even if this
        // clock is stopped. Only eligibility is cleared: released functional
        // resets and fresh-edge state remain untouched until an explicit epoch.
        always_ff @(posedge clk or negedge local_rst_n or negedge release_permit) begin
            if (!local_rst_n || !release_permit) permit_sync <= 0;
            else permit_sync <= {permit_sync[STAGES-2:0],1'b1};
        end
        always_ff @(posedge clk or negedge local_rst_n) begin
            if (!local_rst_n) begin
                assertion_sync <= 0; fresh_cycles <= 0; fresh <= 0; clients_rst_n <= 0;
            end else begin
                assertion_sync <= {assertion_sync[STAGES-2:0],assertion_seen[domain]};
                if (ui_reset !== 1'b0 || assertion_sync[STAGES-1] !== 1'b1) begin
                    fresh_cycles <= 0; fresh <= 0;
                end else if (!fresh) begin
                    if (fresh_cycles >= UI_FRESH_CYCLES-1) fresh <= 1;
                    else fresh_cycles <= fresh_cycles+1;
                end
                // Once released, no health event can assert this reset. Only
                // an explicit whole-boundary epoch may cancel transactions.
                if (!clients_rst_n && permit_sync[STAGES-1] === 1'b1 && fresh && ui_reset === 1'b0)
                    clients_rst_n <= 1;
            end
        end
    end

    always @* begin
        fault_now_code = 0;
        if (state == QUALIFY || state == RELEASE || state == COMPLETE) begin
            // Unknown rejection is a four-state control check, not metastability detection.
            if (reset0_sync[STAGES-1] !== 1'b0 && reset0_sync[STAGES-1] !== 1'b1) fault_now_code = 8'd5;
            else if (reset1_sync[STAGES-1] !== 1'b0 && reset1_sync[STAGES-1] !== 1'b1) fault_now_code = 8'd6;
            else if (low_seen[0] && reset0_sync[STAGES-1]) fault_now_code = 8'd3;
            else if (low_seen[1] && reset1_sync[STAGES-1]) fault_now_code = 8'd4;
            else if (state == QUALIFY && !both_fresh && wait_cycles >= WAIT_TIMEOUT_CYCLES-1) fault_now_code = 8'd1;
            else if (state == RELEASE && !branches_released && wait_cycles >= WAIT_TIMEOUT_CYCLES-1) fault_now_code = 8'd2;
        end
        fault_now = fault_now_code != 0;
    end

    always_ff @(posedge sys_clk or posedge cfg_reset) begin
        if (cfg_reset) begin
            state <= HOLD; hold_cycles <= 0; wait_cycles <= 0;
            mig_sys_rst_n <= 0; sys_clients_rst_n <= 0;
            release_permit <= 0; release_started <= 0; sys_release_pipe <= 0;
            assertion_seen <= 0; low_seen <= 0;
            reset0_sync <= 0; reset1_sync <= 0; fresh0_sync <= 0; fresh1_sync <= 0;
            release0_sync <= 0; release1_sync <= 0;
            sequence_fault <= 0; sequence_fault_code <= 0;
        end else if (restart) begin
            state <= HOLD; hold_cycles <= 0; wait_cycles <= 0;
            mig_sys_rst_n <= 0; sys_clients_rst_n <= 0;
            release_permit <= 0; release_started <= 0; sys_release_pipe <= 0;
            assertion_seen <= 0; low_seen <= 0;
            reset0_sync <= 0; reset1_sync <= 0; fresh0_sync <= 0; fresh1_sync <= 0;
            release0_sync <= 0; release1_sync <= 0;
            sequence_fault <= 0; sequence_fault_code <= 0;
        end else begin
            reset0_sync <= {reset0_sync[STAGES-2:0],c0_ui_clk_sync_rst};
            reset1_sync <= {reset1_sync[STAGES-2:0],c1_ui_clk_sync_rst};
            fresh0_sync <= {fresh0_sync[STAGES-2:0],c0_fresh};
            fresh1_sync <= {fresh1_sync[STAGES-2:0],c1_fresh};
            release0_sync <= {release0_sync[STAGES-2:0],c0_clients_rst_n};
            release1_sync <= {release1_sync[STAGES-2:0],c1_clients_rst_n};
            if (reset0_sync[STAGES-1] === 1'b1) assertion_seen[0] <= 1;
            if (reset1_sync[STAGES-1] === 1'b1) assertion_seen[1] <= 1;
            if (mig_sys_rst_n && assertion_seen[0] && reset0_sync[STAGES-1] === 1'b0) low_seen[0] <= 1;
            if (mig_sys_rst_n && assertion_seen[1] && reset1_sync[STAGES-1] === 1'b0) low_seen[1] <= 1;

            if (fault_now && !sequence_fault) begin
                sequence_fault <= 1; sequence_fault_code <= fault_now_code;
                state <= FAULT; release_permit <= 0;
                // Once release was published, a client may already be active.
                // Never assert any reset as a health response in that epoch.
                if (!release_started) begin mig_sys_rst_n <= 0; sys_clients_rst_n <= 0; end
            end else if (!sequence_fault) begin
                case (state)
                    HOLD: begin
                        if (hold_cycles >= SYS_HOLD_CYCLES-1) begin
                            mig_sys_rst_n <= 1; state <= QUALIFY; wait_cycles <= 0;
                        end else hold_cycles <= hold_cycles+1;
                    end
                    QUALIFY: begin
                        if (both_fresh) begin
                            release_permit <= 1; release_started <= 1;
                            state <= RELEASE; wait_cycles <= 0;
                        end else wait_cycles <= wait_cycles+1;
                    end
                    RELEASE: begin
                        sys_release_pipe <= {sys_release_pipe[STAGES-2:0],1'b1};
                        if (sys_release_pipe[STAGES-1]) sys_clients_rst_n <= 1;
                        if (branches_released) state <= COMPLETE;
                        else wait_cycles <= wait_cycles+1;
                    end
                    COMPLETE: begin end
                    FAULT: begin end
                    default: begin
                        sequence_fault <= 1; sequence_fault_code <= 8'd7;
                        release_permit <= 0; state <= FAULT;
                    end
                endcase
            end
        end
    end
endmodule
