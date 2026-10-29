// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Private diagnostic composition, not a board top or RK execution endpoint.
// A platform must grant exclusive ownership of both AXI interfaces before
// releasing this entire transaction domain from its coordinated reset.
// initialization_complete is a platform admission obligation, never a claim
// that these tests have initialized or qualified the physical address span.
// Both data and control interfaces must remain owned in quarantine until an
// audited whole-domain reset; the normal fabric cannot run beside this block.
module rk_ddr_capacity_bist #(
    parameter logic [30:0] BASE_ADDR = 0,
    parameter logic [31:0] SPAN_BYTES = 32'h80000000,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, joint_rst_n,
    input logic initialization_complete, calibration_complete, owner_exclusive, mig_interrupt,
    input logic start_valid,
    output logic start_ready,
    input logic [31:0] seed,
    output logic busy, done, fault, trial,
    output logic [2:0] fault_sources,
    output logic [7:0] sweep_fault_code, adapter_fault_code, monitor_fault_code,
    output logic [31:0] completed_writes, completed_reads,
    output logic [31:0] accepted_aw_count, accepted_w_count, accepted_b_count,
    output logic [30:0] mismatch_address, last_completed_write_address,
    output logic [511:0] mismatch_expected, mismatch_actual,
    output logic monitor_healthy,

    output logic [3:0] m_axi_awid, m_axi_arid,
    output logic [30:0] m_axi_awaddr, m_axi_araddr,
    output logic [7:0] m_axi_awlen, m_axi_arlen,
    output logic [2:0] m_axi_awsize, m_axi_arsize,
    output logic [1:0] m_axi_awburst, m_axi_arburst,
    output logic m_axi_awlock, m_axi_arlock,
    output logic [3:0] m_axi_awcache, m_axi_arcache,
    output logic [2:0] m_axi_awprot, m_axi_arprot,
    output logic [3:0] m_axi_awqos, m_axi_arqos,
    output logic m_axi_awvalid,
    input logic m_axi_awready,
    output logic [511:0] m_axi_wdata,
    output logic [63:0] m_axi_wstrb,
    output logic m_axi_wlast, m_axi_wvalid,
    input logic m_axi_wready,
    input logic [3:0] m_axi_bid,
    input logic [1:0] m_axi_bresp,
    input logic m_axi_bvalid,
    output logic m_axi_bready,
    output logic m_axi_arvalid,
    input logic m_axi_arready,
    input logic [3:0] m_axi_rid,
    input logic [511:0] m_axi_rdata,
    input logic [1:0] m_axi_rresp,
    input logic m_axi_rlast, m_axi_rvalid,
    output logic m_axi_rready,
    output logic [31:0] m_axi_ctrl_awaddr,
    output logic m_axi_ctrl_awvalid,
    input logic m_axi_ctrl_awready,
    output logic [31:0] m_axi_ctrl_wdata,
    output logic m_axi_ctrl_wvalid,
    input logic m_axi_ctrl_wready,
    input logic [1:0] m_axi_ctrl_bresp,
    input logic m_axi_ctrl_bvalid,
    output logic m_axi_ctrl_bready,
    output logic [31:0] m_axi_ctrl_araddr,
    output logic m_axi_ctrl_arvalid,
    input logic m_axi_ctrl_arready,
    input logic [31:0] m_axi_ctrl_rdata,
    input logic [1:0] m_axi_ctrl_rresp,
    input logic m_axi_ctrl_rvalid,
    output logic m_axi_ctrl_rready
);
    logic sweep_fault, adapter_fault, monitor_fault, sweep_done;
    logic line_valid, line_ready, line_write, line_rsp_valid, line_rsp_ready, line_rsp_error;
    logic [30:0] line_address;
    logic [511:0] line_wdata, line_rdata;
    logic retire_valid, retire_ready, retire_rsp_valid, retire_rsp_ready, retire_rsp_ok;
    logic [30:0] retire_last_write_address;
    logic [31:0] retire_ecc_status, retire_ecc_onoff, retire_ecc_irq_mask;
    logic monitor_check_valid, monitor_check_ready, monitor_snapshot_valid, monitor_snapshot_ready;
    logic [31:0] monitor_snapshot_status, monitor_snapshot_onoff, monitor_snapshot_irq_mask;
    assign fault_sources={monitor_fault,adapter_fault,sweep_fault};
    assign fault=joint_rst_n && (|fault_sources);
    assign done=joint_rst_n && sweep_done && !fault &&
        initialization_complete === 1'b1 && calibration_complete === 1'b1 &&
        owner_exclusive === 1'b1 && monitor_healthy === 1'b1;

    rk_ddr_capacity_sweep #(.BASE_ADDR(BASE_ADDR),.SPAN_BYTES(SPAN_BYTES),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)) sweep (
        .done(sweep_done),.fault(sweep_fault),.fault_code(sweep_fault_code),
        .ecc_monitor_healthy(monitor_healthy && !adapter_fault),.*
    );
    rk_ddr_capacity_axi #(.BASE_ADDR(BASE_ADDR),.SPAN_BYTES(SPAN_BYTES),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)) adapter (
        .fault(adapter_fault),.fault_code(adapter_fault_code),.*
    );
    rk_mig_ecc_monitor #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) monitor (
        .calib_complete(calibration_complete && initialization_complete),
        .fault(monitor_fault),.fault_code(monitor_fault_code),
        .check_valid(monitor_check_valid),.check_ready(monitor_check_ready),
        .snapshot_valid(monitor_snapshot_valid),.snapshot_ready(monitor_snapshot_ready),
        .snapshot_status(monitor_snapshot_status),.snapshot_onoff(monitor_snapshot_onoff),
        .snapshot_irq_mask(monitor_snapshot_irq_mask),.*
    );
endmodule
