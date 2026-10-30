// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Private control-only composition. No host ABI, data-memory master, expected
// CE/UE reader, DDR initializer or job-admission proof is provided here.
module rk_mig_fi_control_service #(
    parameter int unsigned GUARD_TIMEOUT_CYCLES = 65536,
    parameter int unsigned BOOT_TIMEOUT_CYCLES = 262144,
    parameter int unsigned MONITOR_TIMEOUT_CYCLES = 65536
) (
    input logic clk, joint_rst_n, sequence_ready, calib_complete, mig_interrupt,
    // This quiet input must work BEFORE initialization; do not wire a signal
    // that itself requires initialization_complete, or bootstrap deadlocks.
    input logic normal_memory_quiescent, diagnostic_memory_quiescent,
    // Runtime acquisition additionally requires completed initialization and
    // all ordinary jobs/host sessions/fences to be retired by the parent.
    input logic normal_diag_admission_ready,
    input logic diagnostic_owner_request,
    output logic diagnostic_owner_granted,
    output logic normal_owner_granted,
    input logic diagnostic_req_valid, diagnostic_req_write,
    output logic diagnostic_req_ready,
    input logic [31:0] diagnostic_req_address, diagnostic_req_data,
    input logic [3:0] diagnostic_req_strobe,
    input logic [2:0] diagnostic_req_protection,
    output logic diagnostic_rsp_valid,
    input logic diagnostic_rsp_ready,
    output logic [1:0] diagnostic_rsp_response,
    input logic check_valid,
    output logic check_ready, snapshot_valid,
    input logic snapshot_ready,
    output logic [31:0] snapshot_status, snapshot_onoff, snapshot_irq_mask,
    output logic monitor_healthy, monitor_fault,
    output logic [7:0] monitor_fault_code,
    output logic startup_complete, initialization_permit, normal_admission_permit,
    output logic control_fault, recovery_required, injection_dirty,control_transaction_idle,
    output logic boot_fault, arbiter_fault, guard_quarantine,
    output logic [7:0] boot_fault_code, arbiter_fault_code, guard_fault_code,
    output logic [71:0] observed_mask,
    output logic [8:0] known_bytes,
    output logic mask_disarmed,
    output logic fi_read_address_ready,
    output logic unexpected_read_valid,
    output logic [1:0] unexpected_read_response,
    output logic [31:0] unexpected_read_data,
    output logic [31:0] m_axi_ctrl_awaddr, m_axi_ctrl_wdata, m_axi_ctrl_araddr,
    output logic m_axi_ctrl_awvalid, m_axi_ctrl_wvalid, m_axi_ctrl_bready,
    output logic m_axi_ctrl_arvalid, m_axi_ctrl_rready,
    input logic m_axi_ctrl_awready, m_axi_ctrl_wready, m_axi_ctrl_bvalid,
    input logic m_axi_ctrl_arready, m_axi_ctrl_rvalid,
    input logic [1:0] m_axi_ctrl_bresp, m_axi_ctrl_rresp,
    input logic [31:0] m_axi_ctrl_rdata,
    input logic [8:0] fi_xor_we,
    input logic [71:0] fi_xor_wrdata,
    input logic memory_write_clear
);
    logic [1:0][31:0] s_awaddr, s_wdata, s_araddr, s_rdata;
    logic [1:0] s_awvalid, s_wvalid, s_bready, s_arvalid, s_rready;
    logic [1:0] s_awready, s_wready, s_bvalid, s_arready, s_rvalid;
    logic [1:0][1:0] s_bresp, s_rresp;
    logic fi_granted, normal_granted, port_idle;
    logic boot_owner, boot_req_valid, boot_rsp_ready;
    logic [31:0] boot_req_address;
    logic guard_ready, guard_rsp_valid, guard_busy;
    logic [1:0] guard_rsp_response;
    logic guard_req_valid, guard_req_write, guard_rsp_ready;
    logic [31:0] guard_req_address, guard_req_data;
    logic [3:0] guard_req_strobe;
    logic [2:0] guard_req_protection;
    logic monitor_started, monitor_calib, monitor_check_valid, monitor_check_ready;
    logic traffic_violation, epoch_violation, dirty_now;
    logic fi_request, take_safe, release_safe, normal_yield;

    assign control_transaction_idle = !boot_owner && !guard_busy && !diagnostic_rsp_valid && port_idle;
    assign control_fault = boot_fault || arbiter_fault || guard_quarantine || traffic_violation || epoch_violation;
    assign recovery_required = injection_dirty || control_fault || monitor_fault;
    assign diagnostic_owner_granted = startup_complete && monitor_started && fi_granted;
    assign normal_owner_granted = normal_granted;
    // Ignore runtime acquisition until the bootstrap has relinquished the
    // port once; otherwise an early request could hold FI and deadlock init.
    assign fi_request = boot_owner || (monitor_started && diagnostic_owner_request);
    assign take_safe = startup_complete && sequence_ready === 1'b1 && normal_diag_admission_ready === 1'b1 &&
                       normal_memory_quiescent === 1'b1 && !control_fault && monitor_healthy;
    assign release_safe = startup_complete && mask_disarmed && diagnostic_memory_quiescent === 1'b1 &&
                          !control_fault && !monitor_fault && !injection_dirty;
    assign normal_yield = monitor_check_ready && check_valid === 1'b0;

    // An early diagnostic request must not stop the initialization needed to
    // make runtime acquisition possible. Only NEW ordinary admission uses it.
    assign initialization_permit = joint_rst_n && startup_complete && normal_granted &&
                                   sequence_ready === 1'b1 && calib_complete === 1'b1 &&
                                   !control_fault && !injection_dirty && mask_disarmed && monitor_healthy;
    assign normal_admission_permit = initialization_permit && diagnostic_owner_request === 1'b0;

    // Hold initial monitor setup until the bootstrap has fully handed over.
    // Once started, never hide physical calibration or IRQ loss during FI.
    assign monitor_calib = calib_complete && startup_complete && (monitor_started || normal_granted);
    assign monitor_check_valid = check_valid && normal_granted && startup_complete && !control_fault;
    assign check_ready = monitor_check_ready && normal_granted && startup_complete && !control_fault;
    assign unexpected_read_valid = s_rvalid[1];
    assign fi_read_address_ready = s_arready[1];
    assign unexpected_read_response = s_rresp[1];
    assign unexpected_read_data = s_rdata[1];

    assign guard_req_valid = boot_owner ? boot_req_valid : diagnostic_req_valid && startup_complete && monitor_started && !control_fault;
    assign guard_req_write = boot_owner ? 1'b1 : diagnostic_req_write;
    assign guard_req_address = boot_owner ? boot_req_address : diagnostic_req_address;
    assign guard_req_data = boot_owner ? 32'b0 : diagnostic_req_data;
    assign guard_req_strobe = boot_owner ? 4'hf : diagnostic_req_strobe;
    assign guard_req_protection = boot_owner ? 3'b0 : diagnostic_req_protection;
    assign guard_rsp_ready = boot_owner ? boot_rsp_ready : diagnostic_rsp_ready;
    assign diagnostic_req_ready = !boot_owner && startup_complete && monitor_started && !control_fault && guard_ready;
    assign diagnostic_rsp_valid = !boot_owner && startup_complete && monitor_started && guard_rsp_valid;
    assign diagnostic_rsp_response = guard_rsp_response;

    always_comb begin
        dirty_now = 0;
        for (int byte_index = 0; byte_index < 9; byte_index = byte_index + 1)
            if (fi_xor_we[byte_index] !== 1'b0 && fi_xor_wrdata[byte_index*8+:8] !== 8'b0) dirty_now = 1;
    end
    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            monitor_started <= 0; injection_dirty <= 0;
            traffic_violation <= 0; epoch_violation <= 0;
        end else begin
            if (startup_complete && normal_granted) monitor_started <= 1;
            if (startup_complete && dirty_now) injection_dirty <= 1;
            if (startup_complete && fi_granted && normal_memory_quiescent !== 1'b1) traffic_violation <= 1;
            if (startup_complete && sequence_ready !== 1'b1) epoch_violation <= 1;
        end
    end

    rk_mig_ctrl_owner_mux owner (
        .clk, .joint_rst_n, .fi_owner_request(fi_request), .fi_take_safe(take_safe),
        .normal_yield_ready(normal_yield), .fi_busy(guard_busy), .fi_release_safe(release_safe),
        .fi_owner_granted(fi_granted), .normal_owner_granted(normal_granted), .port_idle,
        .fault(arbiter_fault), .fault_code(arbiter_fault_code),
        .s_awaddr, .s_wdata, .s_araddr, .s_awvalid, .s_wvalid, .s_bready, .s_arvalid, .s_rready,
        .s_awready, .s_wready, .s_bvalid, .s_bresp, .s_arready, .s_rvalid, .s_rresp, .s_rdata,
        .m_awaddr(m_axi_ctrl_awaddr), .m_wdata(m_axi_ctrl_wdata), .m_araddr(m_axi_ctrl_araddr),
        .m_awvalid(m_axi_ctrl_awvalid), .m_wvalid(m_axi_ctrl_wvalid), .m_bready(m_axi_ctrl_bready),
        .m_arvalid(m_axi_ctrl_arvalid), .m_rready(m_axi_ctrl_rready),
        .m_awready(m_axi_ctrl_awready), .m_wready(m_axi_ctrl_wready), .m_bvalid(m_axi_ctrl_bvalid),
        .m_bresp(m_axi_ctrl_bresp), .m_arready(m_axi_ctrl_arready), .m_rvalid(m_axi_ctrl_rvalid),
        .m_rresp(m_axi_ctrl_rresp), .m_rdata(m_axi_ctrl_rdata)
    );
    rk_mig_fi_startup_disarm #(.TIMEOUT_CYCLES(BOOT_TIMEOUT_CYCLES)) startup (
        .clk, .joint_rst_n, .sequence_ready, .calib_complete,
        .memory_quiescent(normal_memory_quiescent && diagnostic_memory_quiescent),
        .fi_owner_granted(fi_granted), .port_idle,
        .guard_ready, .guard_rsp_valid, .guard_rsp_response, .guard_busy,
        .guard_quarantine, .guard_mask_disarmed(mask_disarmed), .arbiter_fault,
        .owner_request(boot_owner), .req_valid(boot_req_valid), .req_address(boot_req_address),
        .rsp_ready(boot_rsp_ready), .startup_complete, .fault(boot_fault), .fault_code(boot_fault_code)
    );
    rk_mig_fi_write_guard #(.TIMEOUT_CYCLES(GUARD_TIMEOUT_CYCLES)) guard (
        .clk, .joint_rst_n, .diagnostic_owned(fi_granted && !control_fault && sequence_ready === 1'b1),
        .memory_quiescent(normal_memory_quiescent && diagnostic_memory_quiescent), .calib_complete,
        .req_valid(guard_req_valid), .req_ready(guard_ready), .req_write(guard_req_write),
        .req_address(guard_req_address), .req_data(guard_req_data),
        .req_strobe(guard_req_strobe), .req_protection(guard_req_protection),
        .rsp_valid(guard_rsp_valid), .rsp_ready(guard_rsp_ready), .rsp_response(guard_rsp_response),
        .busy(guard_busy), .quarantine(guard_quarantine), .fault_code(guard_fault_code),
        .observed_mask, .known_bytes, .mask_disarmed,
        .m_axi_ctrl_awaddr(s_awaddr[1]), .m_axi_ctrl_awvalid(s_awvalid[1]), .m_axi_ctrl_awready(s_awready[1]),
        .m_axi_ctrl_wdata(s_wdata[1]), .m_axi_ctrl_wvalid(s_wvalid[1]), .m_axi_ctrl_wready(s_wready[1]),
        .m_axi_ctrl_bresp(s_bresp[1]), .m_axi_ctrl_bvalid(s_bvalid[1]), .m_axi_ctrl_bready(s_bready[1]),
        .fi_xor_we, .fi_xor_wrdata, .memory_write_clear
    );
    assign s_araddr[1] = 0;
    assign s_arvalid[1] = 0;
    assign s_rready[1] = 0;

    rk_mig_ecc_monitor #(.TIMEOUT_CYCLES(MONITOR_TIMEOUT_CYCLES)) monitor (
        .clk, .joint_rst_n, .calib_complete(monitor_calib), .mig_interrupt,
        .check_valid(monitor_check_valid), .check_ready(monitor_check_ready),
        .snapshot_valid, .snapshot_ready, .snapshot_status, .snapshot_onoff, .snapshot_irq_mask,
        .monitor_healthy, .fault(monitor_fault), .fault_code(monitor_fault_code),
        .m_axi_ctrl_awaddr(s_awaddr[0]), .m_axi_ctrl_awvalid(s_awvalid[0]), .m_axi_ctrl_awready(s_awready[0]),
        .m_axi_ctrl_wdata(s_wdata[0]), .m_axi_ctrl_wvalid(s_wvalid[0]), .m_axi_ctrl_wready(s_wready[0]),
        .m_axi_ctrl_bresp(s_bresp[0]), .m_axi_ctrl_bvalid(s_bvalid[0]), .m_axi_ctrl_bready(s_bready[0]),
        .m_axi_ctrl_araddr(s_araddr[0]), .m_axi_ctrl_arvalid(s_arvalid[0]), .m_axi_ctrl_arready(s_arready[0]),
        .m_axi_ctrl_rdata(s_rdata[0]), .m_axi_ctrl_rresp(s_rresp[0]), .m_axi_ctrl_rvalid(s_rvalid[0]),
        .m_axi_ctrl_rready(s_rready[0])
    );
endmodule
