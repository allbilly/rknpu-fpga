// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Private ownership-control leaf; no mux, CSR decoder, MIG or board top here.
// Lane0 observes actual shared memory AXI, lane1 actual shared ECC-control AXI.
// Each lane has at most one outstanding read OR write; AW/W may arrive in
// either order. normal_fabric_quiet and normal_pending_response additionally
// bind the fabric's internal relay/adapter/fence and frontend response state.
// These obligations cannot be inferred from AXI idleness alone.
// normal_admission_enable blocks NEW frames/jobs only: accepted producer work
// must retain its selected bus until drained. No VALID is gated by fault.
// The platform mux uses diagnostic_selected, never done or busy. Ownership
// and diagnostic reset release remain latched through failure and completion;
// only audited whole-transaction-domain reset permits return to normal work.
module rk_ddr_capacity_owner #(
    parameter int unsigned QUIET_CYCLES = 2,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, joint_rst_n,
    input logic request_valid,
    output logic request_ready,
    input logic [31:0] request_seed,
    input logic initialization_complete, calibration_complete,
    input logic platform_monitor_healthy, platform_monitor_fault,
    input logic normal_fabric_quiet, normal_job_owned, normal_host_busy,
    input logic normal_engine_pending, normal_pending_response,
    input logic normal_unrouted_request,
    output logic normal_admission_enable, normal_selected, diagnostic_selected,
    output logic diagnostic_reset_n, diagnostic_exclusive,
    output logic diagnostic_start_valid,
    input logic diagnostic_start_ready,
    output logic [31:0] diagnostic_seed,
    input logic diagnostic_monitor_healthy, diagnostic_done, diagnostic_fault,
    output logic busy, done, fault,
    output logic [7:0] fault_code,
    // Observed bus signals must be the exact final mux/controller handshakes.
    input logic [1:0] bus_awvalid, bus_awready, bus_wvalid, bus_wready,
    input logic [1:0] bus_bvalid, bus_bready, bus_b_ok,
    input logic [1:0] bus_arvalid, bus_arready,
    input logic [1:0] bus_rvalid, bus_rready, bus_r_ok
);
    typedef enum logic [2:0] {NORMAL, QUIESCE, WAIT_MONITOR, LAUNCH,
                             RUN, RESULT, QUARANTINE} state_t;
    state_t state;
    logic [1:0] aw_seen, w_seen, read_seen;
    logic [1:0] aw_take, w_take, b_take, ar_take, r_take;
    logic diagnostic_owned, start_pending, accepted_done;
    logic health_good, physical_quiet, logical_quiet, quiet_now;
    logic protocol_bad, invalid_seed, fault_now;
    logic [7:0] current_fault;
    logic [31:0] quiet_count, wait_count;
    logic request_accept, start_accept;

    initial begin
        if (QUIET_CYCLES < 2 || TIMEOUT_CYCLES <= QUIET_CYCLES)
            $fatal(1,"Capacity owner requires at least two quiet cycles and a longer positive timeout");
    end
    assign health_good = initialization_complete === 1'b1 && calibration_complete === 1'b1 &&
        platform_monitor_healthy === 1'b1 && platform_monitor_fault === 1'b0;
    assign request_ready = joint_rst_n && state == NORMAL && !fault;
    assign request_accept = request_valid && request_ready;
    assign normal_admission_enable = joint_rst_n && state == NORMAL && !fault &&
        !fault_now && request_valid === 1'b0 && health_good;
    assign diagnostic_selected = joint_rst_n && diagnostic_owned;
    assign normal_selected = joint_rst_n && !diagnostic_owned;
    assign diagnostic_reset_n = diagnostic_selected;
    assign diagnostic_exclusive = diagnostic_selected;
    assign diagnostic_start_valid = joint_rst_n && start_pending;
    assign start_accept = diagnostic_start_valid && diagnostic_start_ready;
    assign busy = joint_rst_n && state != NORMAL && state != RESULT && state != QUARANTINE;
    assign done = joint_rst_n && accepted_done && !fault && !fault_now && health_good;
    assign aw_take = bus_awvalid & bus_awready;
    assign w_take = bus_wvalid & bus_wready;
    assign b_take = bus_bvalid & bus_bready;
    assign ar_take = bus_arvalid & bus_arready;
    assign r_take = bus_rvalid & bus_rready;
    assign physical_quiet = aw_seen === 0 && w_seen === 0 && read_seen === 0 &&
        bus_awvalid === 0 && bus_wvalid === 0 && bus_bvalid === 0 &&
        bus_arvalid === 0 && bus_rvalid === 0;
    assign logical_quiet = normal_fabric_quiet === 1'b1 && normal_job_owned === 1'b0 &&
        normal_host_busy === 1'b0 && normal_engine_pending === 1'b0 &&
        normal_pending_response === 1'b0 && normal_unrouted_request === 1'b0;
    assign quiet_now = physical_quiet && logical_quiet;
    always_comb begin
        invalid_seed = 0;
`ifndef SYNTHESIS
        if ((^request_seed) === 1'bx) invalid_seed = 1;
`endif
        protocol_bad = 0;
        for (int lane=0; lane<2; lane++) begin
            if ((bus_awvalid[lane] !== 1'b0 && bus_awvalid[lane] !== 1'b1) ||
                (bus_wvalid[lane] !== 1'b0 && bus_wvalid[lane] !== 1'b1) ||
                (bus_arvalid[lane] !== 1'b0 && bus_arvalid[lane] !== 1'b1)) protocol_bad = 1;
            if (aw_take[lane] && (aw_seen[lane] || read_seen[lane])) protocol_bad = 1;
            if (w_take[lane] && (w_seen[lane] || read_seen[lane])) protocol_bad = 1;
            if (ar_take[lane] && (read_seen[lane] || aw_seen[lane] || w_seen[lane] ||
                aw_take[lane] || w_take[lane])) protocol_bad = 1;
            if (bus_bvalid[lane] !== 1'b0 && (bus_bvalid[lane] !== 1'b1 ||
                !aw_seen[lane] || !w_seen[lane] || bus_b_ok[lane] !== 1'b1)) protocol_bad = 1;
            if (bus_rvalid[lane] !== 1'b0 && (bus_rvalid[lane] !== 1'b1 ||
                !read_seen[lane] || bus_r_ok[lane] !== 1'b1)) protocol_bad = 1;
        end
        current_fault = 0;
        if ((state != NORMAL || request_accept) && !health_good) current_fault = 1;
        else if (request_accept && invalid_seed) current_fault = 1;
        else if (protocol_bad) current_fault = 2;
        else if (diagnostic_owned && !logical_quiet) current_fault = 4;
        else if (diagnostic_owned && diagnostic_fault !== 1'b0) current_fault = 5;
        else if ((state == RUN || state == RESULT) && diagnostic_monitor_healthy !== 1'b1)
            current_fault = 5;
        else if (diagnostic_done !== 1'b0 &&
            (diagnostic_done !== 1'b1 || (state != RUN && state != RESULT))) current_fault = 5;
        else if (diagnostic_done === 1'b1 && !physical_quiet) current_fault = 5;
        else if ((state == QUIESCE || state == WAIT_MONITOR || state == LAUNCH) &&
            wait_count >= TIMEOUT_CYCLES-1) current_fault = 3;
        fault_now = current_fault != 0;
    end
    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            state <= NORMAL; aw_seen <= 0; w_seen <= 0; read_seen <= 0;
            diagnostic_owned <= 0; start_pending <= 0; accepted_done <= 0;
            diagnostic_seed <= 0; fault <= 0; fault_code <= 0;
            quiet_count <= 0; wait_count <= 0;
        end else begin
            // Observation and pending-start drainage survive quarantine.
            for (int lane=0; lane<2; lane++) begin
                if (aw_take[lane]) aw_seen[lane] <= 1;
                if (w_take[lane]) w_seen[lane] <= 1;
                if (b_take[lane] && aw_seen[lane] && w_seen[lane]) begin
                    aw_seen[lane] <= 0; w_seen[lane] <= 0;
                end
                if (ar_take[lane]) read_seen[lane] <= 1;
                if (r_take[lane] && read_seen[lane] && bus_r_ok[lane] === 1'b1)
                    read_seen[lane] <= 0;
            end
            if (start_accept) start_pending <= 0;
            if (state != QUIESCE && state != WAIT_MONITOR && state != LAUNCH) wait_count <= 0;
            else if (wait_count < TIMEOUT_CYCLES) wait_count <= wait_count+1'b1;
            if (!fault && fault_now) begin
                fault <= 1; fault_code <= current_fault; accepted_done <= 0; state <= QUARANTINE;
            end
            if (!fault && !fault_now) begin
                case (state)
                    NORMAL: if (request_accept) begin
                        diagnostic_seed <= request_seed; quiet_count <= 0; wait_count <= 0; state <= QUIESCE;
                    end
                    QUIESCE: begin
                        if (!quiet_now) quiet_count <= 0;
                        else if (quiet_count >= QUIET_CYCLES-1) begin
                            diagnostic_owned <= 1; wait_count <= 0; state <= WAIT_MONITOR;
                        end else quiet_count <= quiet_count+1'b1;
                    end
                    WAIT_MONITOR: if (diagnostic_monitor_healthy === 1'b1) begin
                        start_pending <= 1; wait_count <= 0; state <= LAUNCH;
                    end
                    LAUNCH: if (start_accept) begin wait_count <= 0; state <= RUN; end
                    RUN: if (diagnostic_done === 1'b1) begin accepted_done <= 1; state <= RESULT; end
                    RESULT, QUARANTINE: begin end
                    default: begin fault <= 1; fault_code <= 2; state <= QUARANTINE; end
                endcase
            end
        end
    end
endmodule
