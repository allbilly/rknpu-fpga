// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// UNQUALIFIED joined EW/full512 CMAC DDR candidate. Its own validation is required.
// Frames, memory ownership and ECC control stay in c0_ui_clk; the unchanged
// raw EW DMA runs in SYS50 through separately tested descriptor/memory CDC.
// This is not a BSCAN, PCIe or physical-board shell. All reset branches belong
// to the coordinated whole-transaction epoch. Identity RKAD distinguishes
// terminal-only task snapshots and the two-clock contract from RKED/RKEW.
// No command words, numerical data or layouts are repaired by this composite.
module rk_jtag_dual_ddr_async #(
    parameter logic [31:0] BASE = 0,
    parameter logic [32:0] BYTES = 33'h080000000,
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter int unsigned MAX_TASKS = 4095,
    parameter int unsigned SYS_HOLD_CYCLES = 64,
    parameter int unsigned UI_FRESH_CYCLES = 4,
    parameter int unsigned SYNC_STAGES = 3,
    parameter int unsigned RESET_WAIT_TIMEOUT_CYCLES = 65536
) (
    input logic sys_clk, cfg_reset, reset_req_valid,
    output logic reset_req_ready,
    input logic c0_ui_clk, c1_ui_clk, c0_ui_clk_sync_rst, c1_ui_clk_sync_rst,
    // Actual selected C1 UI/MC observations, not the raw app UI vectors.
    input logic fi_mc_ecc_valid,fi_mc_read_data_valid,
    input logic [7:0] fi_mc_single,fi_mc_multiple,
    input logic [28:0] fi_mc_ecc_address,
    input logic [8:0] fi_we_witness,
    input logic [71:0] fi_data_witness,
    input logic fi_clear_witness,
    input logic c0_init_calib_complete, c0_interrupt,
    output logic mig_sys_rst_n, sys_clients_rst_n, c0_clients_rst_n, c1_clients_rst_n,
    output logic c0_aresetn, c1_aresetn,
    output logic sequence_busy, sequence_complete, admission_blocked, sequence_fault,
    output logic [7:0] sequence_fault_code,
    input logic req_valid,
    output logic req_ready,
    input logic [603:0] req,
    output logic rsp_valid,
    output logic [511:0] rsp_data,
    output logic [7:0] rsp_status,
    output logic [15:0] rsp_seq,
    output logic irq, fault,
    output wire transport_release_ready,
    output logic [7:0] fault_code,
    output logic init_complete, init_active, memory_ready, job_owned, job_active, job_retired,
    output logic maintenance_drained,maintenance_platform_ready,
    output wire maintenance_endpoint_epoch_ready,

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
    // The management bank is the sole internal diagnostic request source.
    logic fi_owner_request,fi_owner_granted,fi_recovery_required,fi_startup_complete,fi_control_fault;
    logic fi_ctrl_req_valid,fi_ctrl_req_write,fi_ctrl_req_ready,fi_ctrl_rsp_valid,fi_ctrl_rsp_ready;
    logic [31:0] fi_ctrl_req_address,fi_ctrl_req_data;
    logic [3:0] fi_ctrl_req_strobe;
    logic [2:0] fi_ctrl_req_protection;
    logic [1:0] fi_ctrl_rsp_response;
    logic fi_line_req_valid,fi_line_req_write,fi_line_req_ready,fi_line_rsp_valid,fi_line_rsp_ready,fi_line_rsp_matched;
    logic [31:0] fi_line_req_address;
    logic [511:0] fi_line_req_data,fi_line_rsp_data;
    logic [1:0] fi_line_expected_response,fi_line_rsp_response;
    logic fi_management_fault,fi_management_transaction_quiet;
    logic [7:0] fi_management_fault_code;
    logic [31:0] fi_legacy_axil_awaddr,fi_register_axil_awaddr;
    logic [1:0] [31:0] fi_route_axil_awaddr;
    logic [2:0] fi_legacy_axil_awprot,fi_register_axil_awprot;
    logic [1:0] [2:0] fi_route_axil_awprot;
    logic fi_legacy_axil_awvalid,fi_register_axil_awvalid;
    logic [1:0] fi_route_axil_awvalid;
    logic fi_legacy_axil_awready,fi_register_axil_awready;
    logic [1:0] fi_route_axil_awready;
    logic [31:0] fi_legacy_axil_wdata,fi_register_axil_wdata;
    logic [1:0] [31:0] fi_route_axil_wdata;
    logic [3:0] fi_legacy_axil_wstrb,fi_register_axil_wstrb;
    logic [1:0] [3:0] fi_route_axil_wstrb;
    logic fi_legacy_axil_wvalid,fi_register_axil_wvalid;
    logic [1:0] fi_route_axil_wvalid;
    logic fi_legacy_axil_wready,fi_register_axil_wready;
    logic [1:0] fi_route_axil_wready;
    logic [1:0] fi_legacy_axil_bresp,fi_register_axil_bresp;
    logic [1:0] [1:0] fi_route_axil_bresp;
    logic fi_legacy_axil_bvalid,fi_register_axil_bvalid;
    logic [1:0] fi_route_axil_bvalid;
    logic fi_legacy_axil_bready,fi_register_axil_bready;
    logic [1:0] fi_route_axil_bready;
    logic [31:0] fi_legacy_axil_araddr,fi_register_axil_araddr;
    logic [1:0] [31:0] fi_route_axil_araddr;
    logic [2:0] fi_legacy_axil_arprot,fi_register_axil_arprot;
    logic [1:0] [2:0] fi_route_axil_arprot;
    logic fi_legacy_axil_arvalid,fi_register_axil_arvalid;
    logic [1:0] fi_route_axil_arvalid;
    logic fi_legacy_axil_arready,fi_register_axil_arready;
    logic [1:0] fi_route_axil_arready;
    logic [31:0] fi_legacy_axil_rdata,fi_register_axil_rdata;
    logic [1:0] [31:0] fi_route_axil_rdata;
    logic [1:0] fi_legacy_axil_rresp,fi_register_axil_rresp;
    logic [1:0] [1:0] fi_route_axil_rresp;
    logic fi_legacy_axil_rvalid,fi_register_axil_rvalid;
    logic [1:0] fi_route_axil_rvalid;
    logic fi_legacy_axil_rready,fi_register_axil_rready;
    logic [1:0] fi_route_axil_rready;
    // Capacity diagnostics share the real fabric/controller paths.
    logic [3:0] n_axi_awid;
    logic [30:0] n_axi_awaddr;
    logic [7:0] n_axi_awlen;
    logic [2:0] n_axi_awsize;
    logic [1:0] n_axi_awburst;
    logic n_axi_awlock;
    logic [3:0] n_axi_awcache;
    logic [2:0] n_axi_awprot;
    logic [3:0] n_axi_awqos;
    logic n_axi_awvalid;
    logic n_axi_awready;
    logic [3:0] n_axi_arid;
    logic [30:0] n_axi_araddr;
    logic [7:0] n_axi_arlen;
    logic [2:0] n_axi_arsize;
    logic [1:0] n_axi_arburst;
    logic n_axi_arlock;
    logic [3:0] n_axi_arcache;
    logic [2:0] n_axi_arprot;
    logic [3:0] n_axi_arqos;
    logic n_axi_arvalid;
    logic n_axi_arready;
    logic [511:0] n_axi_wdata;
    logic [63:0] n_axi_wstrb;
    logic n_axi_wlast;
    logic n_axi_wvalid;
    logic n_axi_wready;
    logic [3:0] n_axi_bid;
    logic [1:0] n_axi_bresp;
    logic n_axi_bvalid;
    logic n_axi_bready;
    logic [3:0] n_axi_rid;
    logic [511:0] n_axi_rdata;
    logic [1:0] n_axi_rresp;
    logic n_axi_rlast;
    logic n_axi_rvalid;
    logic n_axi_rready;
    logic fi_normal_admission,fi_initialization_permit,fi_normal_owner,fi_ctrl_idle;
    logic fi_control_recovery,fi_line_recovery,fi_line_quiet,fi_line_fault,fi_fabric_quiet;
    logic fi_injection_dirty;
    logic [7:0] fi_line_fault_code;
    logic unused_fi_boot_fault,unused_fi_arbiter_fault,unused_fi_guard_fault;
    logic [7:0] unused_fi_boot_code,unused_fi_arbiter_code,unused_fi_guard_code;
    logic [71:0] unused_fi_mask;
    logic [8:0] unused_fi_known_bytes;
    logic unused_fi_disarmed,unused_fi_arready,unused_fi_rvalid;
    logic [1:0] unused_fi_rresp;
    logic [31:0] unused_fi_rdata;
    wire fi_request_pending=fi_owner_request||fi_line_recovery;
    assign fi_recovery_required=fi_control_recovery||fi_line_recovery||fi_line_fault;
    logic [3:0] fi_bus_awid,fi_merged_axi_awid;
    logic [1:0] [3:0] fi_mux_awid;
    logic [30:0] fi_bus_awaddr,fi_merged_axi_awaddr;
    logic [1:0] [30:0] fi_mux_awaddr;
    logic [7:0] fi_bus_awlen,fi_merged_axi_awlen;
    logic [1:0] [7:0] fi_mux_awlen;
    logic [2:0] fi_bus_awsize,fi_merged_axi_awsize;
    logic [1:0] [2:0] fi_mux_awsize;
    logic [1:0] fi_bus_awburst,fi_merged_axi_awburst;
    logic [1:0] [1:0] fi_mux_awburst;
    logic fi_bus_awlock,fi_merged_axi_awlock;
    logic [1:0] fi_mux_awlock;
    logic [3:0] fi_bus_awcache,fi_merged_axi_awcache;
    logic [1:0] [3:0] fi_mux_awcache;
    logic [2:0] fi_bus_awprot,fi_merged_axi_awprot;
    logic [1:0] [2:0] fi_mux_awprot;
    logic [3:0] fi_bus_awqos,fi_merged_axi_awqos;
    logic [1:0] [3:0] fi_mux_awqos;
    logic fi_bus_awvalid,fi_merged_axi_awvalid;
    logic [1:0] fi_mux_awvalid;
    logic fi_bus_awready,fi_merged_axi_awready;
    logic [1:0] fi_mux_awready;
    logic [3:0] fi_bus_arid,fi_merged_axi_arid;
    logic [1:0] [3:0] fi_mux_arid;
    logic [30:0] fi_bus_araddr,fi_merged_axi_araddr;
    logic [1:0] [30:0] fi_mux_araddr;
    logic [7:0] fi_bus_arlen,fi_merged_axi_arlen;
    logic [1:0] [7:0] fi_mux_arlen;
    logic [2:0] fi_bus_arsize,fi_merged_axi_arsize;
    logic [1:0] [2:0] fi_mux_arsize;
    logic [1:0] fi_bus_arburst,fi_merged_axi_arburst;
    logic [1:0] [1:0] fi_mux_arburst;
    logic fi_bus_arlock,fi_merged_axi_arlock;
    logic [1:0] fi_mux_arlock;
    logic [3:0] fi_bus_arcache,fi_merged_axi_arcache;
    logic [1:0] [3:0] fi_mux_arcache;
    logic [2:0] fi_bus_arprot,fi_merged_axi_arprot;
    logic [1:0] [2:0] fi_mux_arprot;
    logic [3:0] fi_bus_arqos,fi_merged_axi_arqos;
    logic [1:0] [3:0] fi_mux_arqos;
    logic fi_bus_arvalid,fi_merged_axi_arvalid;
    logic [1:0] fi_mux_arvalid;
    logic fi_bus_arready,fi_merged_axi_arready;
    logic [1:0] fi_mux_arready;
    logic [511:0] fi_bus_wdata,fi_merged_axi_wdata;
    logic [1:0] [511:0] fi_mux_wdata;
    logic [63:0] fi_bus_wstrb,fi_merged_axi_wstrb;
    logic [1:0] [63:0] fi_mux_wstrb;
    logic fi_bus_wlast,fi_merged_axi_wlast;
    logic [1:0] fi_mux_wlast;
    logic fi_bus_wvalid,fi_merged_axi_wvalid;
    logic [1:0] fi_mux_wvalid;
    logic fi_bus_wready,fi_merged_axi_wready;
    logic [1:0] fi_mux_wready;
    logic [3:0] fi_bus_bid,fi_merged_axi_bid;
    logic [1:0] [3:0] fi_mux_bid;
    logic [1:0] fi_bus_bresp,fi_merged_axi_bresp;
    logic [1:0] [1:0] fi_mux_bresp;
    logic fi_bus_bvalid,fi_merged_axi_bvalid;
    logic [1:0] fi_mux_bvalid;
    logic fi_bus_bready,fi_merged_axi_bready;
    logic [1:0] fi_mux_bready;
    logic [3:0] fi_bus_rid,fi_merged_axi_rid;
    logic [1:0] [3:0] fi_mux_rid;
    logic [511:0] fi_bus_rdata,fi_merged_axi_rdata;
    logic [1:0] [511:0] fi_mux_rdata;
    logic [1:0] fi_bus_rresp,fi_merged_axi_rresp;
    logic [1:0] [1:0] fi_mux_rresp;
    logic fi_bus_rlast,fi_merged_axi_rlast;
    logic [1:0] fi_mux_rlast;
    logic fi_bus_rvalid,fi_merged_axi_rvalid;
    logic [1:0] fi_mux_rvalid;
    logic fi_bus_rready,fi_merged_axi_rready;
    logic [1:0] fi_mux_rready;
    logic [31:0] n_ctrl_awaddr;
    logic n_ctrl_awvalid;
    logic n_ctrl_awready;
    logic [31:0] n_ctrl_wdata;
    logic n_ctrl_wvalid;
    logic n_ctrl_wready;
    logic [1:0] n_ctrl_bresp;
    logic n_ctrl_bvalid;
    logic n_ctrl_bready;
    logic [31:0] n_ctrl_araddr;
    logic n_ctrl_arvalid;
    logic n_ctrl_arready;
    logic [31:0] n_ctrl_rdata;
    logic [1:0] n_ctrl_rresp;
    logic n_ctrl_rvalid;
    logic n_ctrl_rready;
    logic [31:0] normal_axil_awaddr, diagnostic_axil_awaddr;
    logic [1:0][31:0] routed_axil_awaddr;
    logic [2:0] normal_axil_awprot, diagnostic_axil_awprot;
    logic [1:0][2:0] routed_axil_awprot;
    logic normal_axil_awvalid, diagnostic_axil_awvalid;
    logic [1:0]routed_axil_awvalid;
    logic normal_axil_awready, diagnostic_axil_awready;
    logic [1:0]routed_axil_awready;
    logic [31:0] normal_axil_wdata, diagnostic_axil_wdata;
    logic [1:0][31:0] routed_axil_wdata;
    logic [3:0] normal_axil_wstrb, diagnostic_axil_wstrb;
    logic [1:0][3:0] routed_axil_wstrb;
    logic normal_axil_wvalid, diagnostic_axil_wvalid;
    logic [1:0]routed_axil_wvalid;
    logic normal_axil_wready, diagnostic_axil_wready;
    logic [1:0]routed_axil_wready;
    logic [1:0] normal_axil_bresp, diagnostic_axil_bresp;
    logic [1:0][1:0] routed_axil_bresp;
    logic normal_axil_bvalid, diagnostic_axil_bvalid;
    logic [1:0]routed_axil_bvalid;
    logic normal_axil_bready, diagnostic_axil_bready;
    logic [1:0]routed_axil_bready;
    logic [31:0] normal_axil_araddr, diagnostic_axil_araddr;
    logic [1:0][31:0] routed_axil_araddr;
    logic [2:0] normal_axil_arprot, diagnostic_axil_arprot;
    logic [1:0][2:0] routed_axil_arprot;
    logic normal_axil_arvalid, diagnostic_axil_arvalid;
    logic [1:0]routed_axil_arvalid;
    logic normal_axil_arready, diagnostic_axil_arready;
    logic [1:0]routed_axil_arready;
    logic [31:0] normal_axil_rdata, diagnostic_axil_rdata;
    logic [1:0][31:0] routed_axil_rdata;
    logic [1:0] normal_axil_rresp, diagnostic_axil_rresp;
    logic [1:0][1:0] routed_axil_rresp;
    logic normal_axil_rvalid, diagnostic_axil_rvalid;
    logic [1:0]routed_axil_rvalid;
    logic normal_axil_rready, diagnostic_axil_rready;
    logic [1:0]routed_axil_rready;
    logic capacity_normal_admission, capacity_normal_selected, capacity_owner_fault;
    logic capacity_selected, capacity_busy, capacity_owner_done;
    logic capacity_session_seen, capacity_fault_active;
    logic fabric_diagnostic_quiet;
    localparam integer STAGES = SYNC_STAGES < 3 ? 3 : SYNC_STAGES;
    wire clk = c0_ui_clk;
    wire rst_n = c0_clients_rst_n;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] sequence_sync;
    logic sequence_complete_registered;
    wire sequence_ready_ui0 = sequence_sync[STAGES-1] === 1'b1;
    logic sequence_seen, monitor_seen;
    logic monitor_healthy, monitor_fault;
    logic [7:0] monitor_fault_code;
    logic monitor_check_valid, monitor_check_ready, monitor_snapshot_valid, monitor_snapshot_ready;
    logic [31:0] monitor_snapshot_status, monitor_snapshot_onoff, monitor_snapshot_irq_mask;

    logic [31:0] s_axil_awaddr, s_axil_wdata, s_axil_araddr, s_axil_rdata, control_rdata;
    logic [2:0] s_axil_awprot, s_axil_arprot;
    logic [3:0] s_axil_wstrb;
    logic [1:0] s_axil_bresp, s_axil_rresp;
    logic s_axil_awvalid, s_axil_awready, s_axil_wvalid, s_axil_wready;
    logic s_axil_bvalid, s_axil_bready, s_axil_arvalid, s_axil_arready, s_axil_rvalid, s_axil_rready;
    logic core_start_valid, core_start_ready, core_busy, core_done, core_error;
    wire [1:0] core_start_kind;
    wire ew_dma_start_ready,cmac_dma_start_ready,layout_dma_start_ready;
    wire ew_dma_start_slot_ready,cmac_dma_start_slot_ready,layout_dma_start_slot_ready,dma_start_slot_ready;
    wire control_scheduler_fault,control_owned,control_quiet,control_session_quiet;
    wire [1:0] control_owner_kind;
    logic [31:0] core_start_address, core_start_amount, core_completed_tasks;
    logic [7:0] core_error_code;
    logic dma_start_valid, dma_start_ready, dma_busy, dma_done, dma_error;
    logic async_result_valid, async_result_error, engine_crossing_fault;
    logic [7:0] async_result_code;
    logic [31:0] async_result_tasks;
    logic dma_inflight, dma_error_latched;
    logic [7:0] dma_code_latched;
    logic [31:0] dma_tasks_latched;
    logic ui_engine_rst_n, sys_engine_rst_n;
    logic [31:0] dma_completed_tasks;
    logic [7:0] dma_error_code;
    logic engine_req_valid, engine_req_ready, engine_req_write, engine_rsp_valid, engine_rsp_ready, engine_rsp_error;
    logic [31:0] engine_req_addr;
    logic [15:0] engine_req_wdata, engine_rsp_rdata;
    logic host_valid, host_ready, host_write, host_rsp_valid, host_rsp_ready, host_error;
    logic host_pending_ready;
    logic [31:0] host_addr;
    logic [15:0] host_wdata, host_rdata;
    logic backend_fault, backend_memory_busy, memory_available;
    logic backend_req_ready;
    logic fabric_fault, fabric_memory_ready;
    wire fabric_fault_without_parent_abort;
    wire fabric_fault_without_parent_abort_or_monitor_gap;
    wire fabric_memory_ready_without_fault, job_begin_ready_without_fault;
    logic [7:0] fabric_fault_code;
    logic job_begin, job_begin_ready, job_seal, job_abort, job_release;
    logic epoch_started, epoch_retired, irq_previous;
    logic first_fault_valid, monitor_cause_pending;
    logic [7:0] first_fault_code, known_cause_code;
    logic known_cause, reserve_monitor_cause;

    wire compute_reset_request,compute_reset_request_ready,compute_reset_result,compute_reset_error,compute_reset_ack;
    wire compute_reset_blocked,unused_compute_core_blocked,compute_ui_rst_n,compute_core_rst_n;
    wire compute_maintenance_quiet;
    wire compute_request_ready_without_health,compute_maintenance_quiet_without_request,reset_request_intent;
    logic compute_admission_hold;
    wire [7:0] compute_reset_code;
    wire [31:0] compute_reset_epoch;
    wire engine_ui_quiet,engine_ui_idle_quiet,engine_ui_quiet_fast;
    wire engine_core_quiet,engine_core_ready,engine_ui_ready,engine_ui_idle_ready,engine_ui_ready_fast;
    assign engine_ui_quiet_fast=engine_ui_idle_quiet&&!core_start_valid;
    assign engine_ui_ready_fast=engine_ui_idle_ready&&!core_start_valid;
    wire reset_healthy=sequence_ready_ui0&&init_complete&&!live_block&&monitor_healthy===1'b1&&
        c0_init_calib_complete===1'b1&&capacity_normal_selected&&!capacity_selected&&!capacity_busy;
    wire reset_quiet=control_quiet&&fabric_diagnostic_quiet&&engine_ui_quiet_fast&&
        !dma_inflight&&!async_result_valid&&!engine_req_valid&&!engine_rsp_valid&&
        !host_valid&&!host_rsp_valid&&!backend_memory_busy&&!job_owned&&!job_active&&!epoch_started&&!irq&&
        capacity_normal_admission&&!capacity_selected&&!capacity_busy&&
        !m_axi_awvalid&&!m_axi_wvalid&&!m_axi_bvalid&&!m_axi_arvalid&&!m_axi_rvalid&&
        !m_axi_ctrl_awvalid&&!m_axi_ctrl_wvalid&&!m_axi_ctrl_bvalid&&!m_axi_ctrl_arvalid&&!m_axi_ctrl_rvalid;
    // Under known READY, the sequencer is live and IDLE: its blocked/result
    // outputs are zero. Avoid feeding READY back through blocked into the CSR
    // request and then back into the sequencer's quiet/ownership decisions.
    wire compute_reset_request_qualified=reset_request_intent&&
        (reset_healthy===1'b1)&&(reset_quiet===1'b1)&&
        (compute_request_ready_without_health===1'b1)&&(compute_admission_hold===1'b0);
`ifdef ASSERT_ON
    always @(posedge clk)begin
        if(compute_reset_request_qualified!==compute_reset_request)
            $fatal(1,"Qualified compute reset request differs from original CSR request");
    end
`endif
    // Transport handoff additionally requires empty real descriptors and no
    // held/reset transaction. This output does not change compute reset quiet.
    // request_ready_without_health already contains UI reset and the IDLE
    // state predicate. Preserve four-state behavior while removing the
    // duplicate healthy -> request_ready -> admission_blocked feedback.
    wire transport_reset_ready=(reset_healthy&&!ui_engine_rst_n)||
        ((reset_healthy===1'b1)&&compute_request_ready_without_health);
    assign transport_release_ready=transport_reset_ready&&reset_quiet&&control_session_quiet&&
        !compute_admission_hold&&!compute_reset_result&&!compute_reset_error&&
        req_ready&&!req_valid&&!rsp_valid;
`ifdef ASSERT_ON
    always @(posedge clk)begin
        if(transport_release_ready!==(reset_healthy&&reset_quiet&&control_session_quiet&&
            !compute_admission_hold&&!compute_reset_blocked&&!compute_reset_result&&!compute_reset_error&&
            req_ready&&!req_valid&&!rsp_valid))
            $fatal(1,"Transport release cofactor changes four-state readiness");
    end
`endif
    logic health_published,core_ready_published;
    // Registered ownership avoids feeding live fabric health back through
    // admission/READY into its own protocol checker. Release only after the
    // sequencer's post-ACK core-idle handshake has completed.
    always_ff @(posedge clk)begin
        if(!rst_n)compute_admission_hold<=0;
        else if(compute_reset_request_qualified&&compute_reset_request_ready)compute_admission_hold<=1;
        else if(compute_reset_error)compute_admission_hold<=1;
        else if(compute_reset_request_ready&&!compute_reset_blocked&&!compute_reset_result)compute_admission_hold<=0;
    end
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [STAGES-1:0] core_health_sync,ui_core_ready_sync;
    always_ff @(posedge clk or negedge ui_engine_rst_n)begin
        if(!ui_engine_rst_n)begin health_published<=0;ui_core_ready_sync<=0;end
        else begin health_published<=reset_healthy;ui_core_ready_sync<={ui_core_ready_sync[STAGES-2:0],core_ready_published};end
    end
    always_ff @(posedge sys_clk or negedge sys_engine_rst_n)begin
        if(!sys_engine_rst_n)begin core_health_sync<=0;core_ready_published<=0;end
        else begin core_health_sync<={core_health_sync[STAGES-2:0],health_published};core_ready_published<=engine_core_ready;end
    end
    rk_quiescent_compute_reset #(.SYNC_STAGES(STAGES),.HOLD_CYCLES(4),.FRESH_CYCLES(4),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)) compute_reset (
        .ui_clk(clk),.ui_rst_n(ui_engine_rst_n),.ui_healthy(reset_healthy),.ui_quiet(reset_quiet),
        .ui_restart_ready(engine_ui_ready_fast&&ui_core_ready_sync[STAGES-1]),
        .request_valid(compute_reset_request_qualified),.request_ready(compute_reset_request_ready),
        .request_ready_without_health(compute_request_ready_without_health),
        .admission_blocked(compute_reset_blocked),.result_valid(compute_reset_result),.result_error(compute_reset_error),
        .error_code(compute_reset_code),.result_ready(compute_reset_ack),.reset_epoch(compute_reset_epoch),
        .ui_compute_rst_n(compute_ui_rst_n),.maintenance_transaction_quiet(compute_maintenance_quiet),
        .maintenance_quiet_without_request(compute_maintenance_quiet_without_request),.core_clk(sys_clk),.core_rst_n(sys_engine_rst_n),
        .core_healthy(core_health_sync[STAGES-1]),.core_quiet(engine_core_quiet),
        .core_admission_blocked(unused_compute_core_blocked),.core_compute_rst_n(compute_core_rst_n)
    );

    logic [31:0] read_address;
    logic read_fault;
    logic [7:0] read_fault_code;
    wire monitor_early_fault = monitor_seen && monitor_healthy !== 1'b1 && monitor_fault === 1'b0;
    wire fabric_cause_pending_hint;
    wire fabric_is_timeout;
    wire fabric_cause_pending_decoded = fabric_fault === 1'b1 && fabric_fault_code === 8'b0;
    wire fabric_cause_pending = fabric_cause_pending_hint;
    wire sequence_lost = sequence_seen && (!sequence_ready_ui0 || c0_ui_clk_sync_rst !== 1'b0);
    wire external_block = first_fault_valid || monitor_cause_pending || dma_error !== 1'b0 ||
        monitor_fault !== 1'b0 || monitor_early_fault || engine_crossing_fault !== 1'b0 ||
        backend_fault !== 1'b0 || control_scheduler_fault !== 1'b0 || sequence_lost || capacity_fault_active !== 1'b0 || compute_reset_error !== 1'b0 ||
        fi_control_fault !== 1'b0 || fi_line_fault !== 1'b0 || fi_management_fault !== 1'b0;
    // The fabric already includes this abort in its public fault. OR the
    // parent term directly with the other-fault cofactor instead of sending
    // it through that child OR network a second time. Unknown abort still
    // blocks exactly as the original fabric job_abort!==0 event does.
    // Shared-reset invariant: service_active implies monitor_seen. The fabric
    // sets service_active only after known-good monitor health; this parent
    // records that same health on the same edge and keeps it until joint reset.
    // Thus any current fabric gap already blocks through monitor_early_fault.
    wire fabric_parent_fault = fabric_fault_without_parent_abort_or_monitor_gap;
    wire live_block = (external_block!==1'b0)||(fabric_parent_fault!==1'b0);
`ifdef ASSERT_ON
    always_ff @(posedge clk)begin
        if(rst_n===1'b1&&memory.service_active===1'b1&&monitor_seen!==1'b1)
            $fatal(1,"Active fabric requires the shared-reset monitor-seen invariant");
        if(rst_n===1'b1&&live_block!==(external_block||(fabric_fault!==1'b0)))
            $fatal(1,"Parent live block differs from original full fabric fault");
    end
`endif
    wire compute_ui_admission = !external_block && sequence_ready_ui0 && !compute_admission_hold && fi_normal_admission;
    wire control_start_accept = core_start_valid && core_start_ready;
    wire dma_start_accept = dma_start_valid && compute_ui_admission && dma_start_slot_ready;
    // No client starts before the synchronized reset barrier. Once enabled,
    // register diagnostics remain accessible after a later health fault.
    wire backend_enabled = sequence_seen || sequence_ready_ui0;
    assign maintenance_endpoint_epoch_ready=backend_enabled;
    assign req_ready = backend_enabled && backend_req_ready;

    initial begin
        if (SYNC_STAGES < 3) $fatal(1,"Async DDR endpoint requires at least three CDC stages");
        if (BYTES < 33'd64 || (BYTES & (BYTES-33'd1)) != 0 || BASE[5:0] != 0 ||
            ({1'b0,BASE}+BYTES) > 33'h080000000 || TIMEOUT_CYCLES == 0)
            $fatal(1,"DDR endpoint needs an aligned power-of-two C0 window and positive timeout");
    end

    // Occupancy witness: ordinary health is not evidence of drainage.
    // Backend protocol quarantine and unfinished compute reset remain excluded
    // because their retained obligations are not proven idle; see CONTRACT.md.
    // Accepted raw frames must separately drain through the retained frame gate.
    wire maintenance_drained_now = rst_n && !init_active && fi_fabric_quiet &&
        control_session_quiet&&compute_maintenance_quiet&&engine_ui_quiet_fast&&
        fi_line_quiet && fi_ctrl_idle && fi_management_transaction_quiet &&
        backend_enabled && backend_req_ready && !backend_memory_busy &&
        !control_owned && !job_owned && !job_active && !epoch_started && !irq &&
        !core_start_valid && !core_busy && !dma_inflight && !async_result_valid &&
        !host_valid && !host_rsp_valid && !engine_req_valid && !engine_rsp_valid &&
        // Capacity retains diagnostic selection after RESULT until whole reset.
        // Its real owner_done is fail-closed on fault/health loss or any pending
        // physical AXI transaction. Only that completed owner may cross reset;
        // RUN, launch, partial AW/W and held B/R remain blocked.
        (capacity_selected===1'b0 ||
         (capacity_selected===1'b1 && capacity_owner_done===1'b1)) &&
        capacity_busy===1'b0 &&
        !fi_ctrl_req_valid && !fi_ctrl_rsp_valid && !fi_line_req_valid && !fi_line_rsp_valid &&
        !s_axil_awvalid && !s_axil_wvalid && !s_axil_bvalid && !s_axil_arvalid && !s_axil_rvalid &&
        !m_axi_awvalid && !m_axi_wvalid && !m_axi_bvalid && !m_axi_arvalid && !m_axi_rvalid &&
        !m_axi_ctrl_awvalid && !m_axi_ctrl_wvalid && !m_axi_ctrl_bvalid &&
        !m_axi_ctrl_arvalid && !m_axi_ctrl_rvalid;
    // Registered witnesses do not create a new combinational admission loop.
    always_ff @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin maintenance_drained<=0;maintenance_platform_ready<=0;end
        else begin
            maintenance_drained<=maintenance_drained_now;
            maintenance_platform_ready<=memory_ready && init_complete && !init_active &&
                fi_startup_complete && unused_fi_disarmed && unused_fi_known_bytes==9'h1ff &&
                unused_fi_mask==72'd0;
        end
    end

    rk_mig_reset_coordinator #(.SYS_HOLD_CYCLES(SYS_HOLD_CYCLES),.UI_FRESH_CYCLES(UI_FRESH_CYCLES),
        .SYNC_STAGES(SYNC_STAGES),.WAIT_TIMEOUT_CYCLES(RESET_WAIT_TIMEOUT_CYCLES)) reset_owner (.*);
    // The reset coordinator supplies fresh UI clocks with this reset held low
    // before release, as required by the unchanged synchronous-reset clients.
    // Publish one registered SYS level to the UI admission synchronizer.
    // The public local barrier keeps its immediate SYS-domain fault/request
    // gating; remote visibility includes this one additional SYS edge.
    always_ff @(posedge sys_clk or posedge cfg_reset) begin
        if (cfg_reset) sequence_complete_registered <= 0;
        else sequence_complete_registered <= sequence_complete;
    end
    always_ff @(posedge clk) begin
        if (!rst_n) sequence_sync <= 0;
        else sequence_sync <= {sequence_sync[STAGES-2:0],sequence_complete_registered};
    end

    // Reserve an earlier monitor failure before its registered cause is known.
    // Live loss blocks admission/done/ACK immediately; code0 means pending, not
    // success. A later relay error must not replace the monitor's timeout E8.
    always_comb begin
        known_cause = 0; known_cause_code = 0; reserve_monitor_cause = 0;
        if (monitor_cause_pending) begin
            known_cause = 1;
            if (monitor_fault !== 1'b0)
                known_cause_code = monitor_fault_code === 8'd3 ? 8'd8 : 8'd5;
            else known_cause_code = fabric_fault === 1'b1 && fabric_is_timeout ? 8'd8 : 8'd5;
        end else if (dma_error !== 1'b0) begin
            known_cause = 1; known_cause_code = dma_error_code;
        end else if (monitor_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = monitor_fault_code === 8'd3 ? 8'd8 : 8'd5;
        // Reset-reachable fabric invariants make every public pending cause
        // an early monitor loss already observed by this parent. Keep this
        // branch local instead of traversing derived abort/classification.
        end else if (monitor_early_fault) begin
            reserve_monitor_cause = 1;
        end else if (engine_crossing_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = 8'd5;
        end else if (control_scheduler_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = 8'd6;
        end else if (backend_fault !== 1'b0) begin
            // The backend is an abort source for the fabric. Preserve its
            // original timeout before the fabric's derived generic abort E5.
            known_cause = 1; known_cause_code = rsp_status === 8'h80 ? 8'd8 : 8'd5;
        end else if (fi_management_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = fi_management_fault_code === 8'd1 ? 8'd8 : 8'd5;
        end else if (fi_control_fault !== 1'b0 || fi_line_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = fi_line_fault_code === 8'd4 ? 8'd8 : 8'd5;
        end else if (capacity_fault_active !== 1'b0) begin
            known_cause = 1; known_cause_code = 8'd5;
        end else if (compute_reset_error !== 1'b0) begin
            known_cause = 1; known_cause_code = compute_reset_code;
        end else if (fabric_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = fabric_is_timeout ? 8'd8 : 8'd5;
        end else if (sequence_lost) begin
            known_cause = 1; known_cause_code = 8'd5;
        end
    end
    assign fault = rst_n && live_block;
    assign fault_code = !rst_n ? 8'b0 : first_fault_valid ? first_fault_code : known_cause ? known_cause_code : 8'b0;
    // Platform faults block admission/success/ACK immediately, but a launched
    // core still owns its terminal task snapshot. Wait for that snapshot
    // before publishing an error result; never replace an unknown partial
    // count with zero. A stopped core remains pending until drain/joint reset.
    assign core_error = (first_fault_valid || known_cause) &&
                        (!epoch_started || !dma_inflight || async_result_valid);
    assign core_error_code = first_fault_valid ? first_fault_code : known_cause_code;
    assign core_busy = dma_busy || job_active || (live_block && !core_error);
    assign core_done = epoch_started && job_retired && !live_block;
    assign core_completed_tasks = epoch_started ? dma_completed_tasks : 32'b0;
    assign memory_ready = fabric_memory_ready_without_fault && sequence_ready_ui0 && !live_block && capacity_normal_admission && !compute_admission_hold && fi_normal_admission;

    // A faulted queued descriptor is acknowledged to the logical controller,
    // without starting DMA/fabric work. This releases its launch_pending state.
    assign core_start_ready = live_block || (!compute_admission_hold && capacity_normal_admission && compute_ui_admission && dma_start_slot_ready && job_begin_ready_without_fault);
    assign dma_start_valid = core_start_valid && job_begin_ready && !external_block && capacity_normal_admission && !compute_admission_hold;
    assign job_begin = core_start_valid && compute_ui_admission && dma_start_slot_ready && !external_block && capacity_normal_admission && !compute_admission_hold;
    assign job_seal = dma_done && !external_block;
    // Do not feed the fabric's own combinational fault back into its abort.
    assign job_abort = external_block;
    assign job_release = rst_n && irq_previous && !irq;
    // Packet admission is distinct from fabric memory_ready (which excludes
    // this backend's already-active host session to block mid-packet SUBMIT).
    assign memory_available = init_complete && sequence_ready_ui0 && !live_block && !compute_admission_hold && capacity_normal_selected &&
        (capacity_normal_admission || ((job_owned || control_owned) && irq && epoch_retired && req[555:548] === 8'd3)) &&
        (fi_normal_admission || ((job_owned || control_owned) && irq && epoch_retired && req[555:548] === 8'd3)) &&
        monitor_healthy === 1'b1 && c0_init_calib_complete === 1'b1 &&
        !core_start_valid && !dma_busy && !job_active &&
        (!job_owned || (irq && epoch_retired && req[555:548] === 8'd3)) &&
        (!control_owned || (control_owner_kind === core_start_kind && irq &&
                            epoch_retired && req[555:548] === 8'd3));

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            first_fault_valid <= 0; first_fault_code <= 0; monitor_cause_pending <= 0;
            sequence_seen <= 0; monitor_seen <= 0; epoch_started <= 0; epoch_retired <= 0; irq_previous <= 0;
            read_address <= 0; read_fault <= 0; read_fault_code <= 0;
        end else begin
            if (sequence_ready_ui0) sequence_seen <= 1;
            if (monitor_healthy === 1'b1) monitor_seen <= 1;
            if (!first_fault_valid) begin
                if (known_cause) begin
                    first_fault_valid <= 1; first_fault_code <= known_cause_code; monitor_cause_pending <= 0;
                end else if (reserve_monitor_cause) monitor_cause_pending <= 1;
            end
            irq_previous <= irq;
            if (control_start_accept) begin
                epoch_started <= dma_start_accept; epoch_retired <= 0;
            end else if (job_release) begin
                epoch_started <= 0; epoch_retired <= 0;
            end
            if (job_retired) epoch_retired <= 1;
            if (normal_axil_arvalid && normal_axil_arready) begin
                read_address <= normal_axil_araddr; read_fault <= live_block; read_fault_code <= fault_code;
            end
        end
    end
    // Preserve the controller's AR-time snapshot, including under backpressure.
    // An old successful result becomes logically failed on a NEW read after a
    // platform fault. Pending classification reports error with code0 in RKAD.
    always_comb begin
        normal_axil_rdata = control_rdata;
        if (normal_axil_rresp == 2'b00) begin
            case (read_address)
                32'h08,32'h108,32'h408: if (read_fault) begin
                    normal_axil_rdata[0] = 0; normal_axil_rdata[4] = 0; normal_axil_rdata[5] = 1;
                    if (control_rdata[2]) normal_axil_rdata[3] = 1;
                end
                32'h24,32'h124,32'h424: if (read_fault) normal_axil_rdata = {24'b0,read_fault_code};
                default: begin end
            endcase
        end
    end

    rk_jtag_backend #(.BASE(BASE),.BYTES(BYTES[31:0]),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) backend (
        .req_valid(req_valid && backend_enabled),.req_ready(backend_req_ready),
        .host_ready(host_pending_ready),
        .fault(backend_fault),.memory_busy(backend_memory_busy),.*
    );
    rk_layout_job_control control (
        .core_write_block(live_block || dma_busy || job_active || compute_admission_hold),
        .new_admission_block(fi_request_pending||!fi_normal_owner),
        .s_axil_rdata(control_rdata),.scheduler_fault(control_scheduler_fault),
        .control_owned,.control_owner_kind,.core_start_kind,.control_quiet(control_quiet),.session_quiet(control_session_quiet),
        .core_ew_start_ready(live_block || (!compute_admission_hold && capacity_normal_admission && compute_ui_admission && ew_dma_start_slot_ready && job_begin_ready_without_fault)),
        .core_cmac_start_ready(live_block || (!compute_admission_hold && capacity_normal_admission && compute_ui_admission && cmac_dma_start_slot_ready && job_begin_ready_without_fault)),
        .core_layout_start_ready(live_block || (!compute_admission_hold && capacity_normal_admission && compute_ui_admission && layout_dma_start_slot_ready && job_begin_ready_without_fault)),
        .s_axil_awaddr(normal_axil_awaddr),
        .s_axil_awprot(normal_axil_awprot),
        .s_axil_awvalid(normal_axil_awvalid),
        .s_axil_awready(normal_axil_awready),
        .s_axil_wdata(normal_axil_wdata),
        .s_axil_wstrb(normal_axil_wstrb),
        .s_axil_wvalid(normal_axil_wvalid),
        .s_axil_wready(normal_axil_wready),
        .s_axil_bresp(normal_axil_bresp),
        .s_axil_bvalid(normal_axil_bvalid),
        .s_axil_bready(normal_axil_bready),
        .s_axil_araddr(normal_axil_araddr),
        .s_axil_arprot(normal_axil_arprot),
        .s_axil_arvalid(normal_axil_arvalid),
        .s_axil_arready(normal_axil_arready),
        .s_axil_rresp(normal_axil_rresp),
        .s_axil_rvalid(normal_axil_rvalid),
        .s_axil_rready(normal_axil_rready),.*);
    // The coordinator holds each raw reset through fresh local edges and
    // supplies the admission barrier. Dedicated registered copies feed only
    // asynchronous crossing reset pins; the original UI clients remain on
    // their unchanged synchronous reset. No tap reset or health event drives
    // these registers, and no local copy can recover a failed transaction.
    always_ff @(posedge clk) ui_engine_rst_n <= c0_clients_rst_n;
    always_ff @(posedge sys_clk) sys_engine_rst_n <= sys_clients_rst_n;
    assign dma_busy = dma_inflight;
    assign dma_done = async_result_valid && !async_result_error;
    assign dma_error = dma_error_latched || (async_result_valid && async_result_error);
    assign dma_error_code = dma_error_latched ? dma_code_latched : async_result_code;
    assign dma_completed_tasks = async_result_valid ? async_result_tasks : dma_tasks_latched;
    // Forward terminal task count on the same UI edge as an error, before its
    // local snapshot registers update. Queued failures without a DMA start
    // retain the prior DMA snapshot; epoch_started still masks it from results.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            dma_inflight <= 0; dma_error_latched <= 0; dma_code_latched <= 0; dma_tasks_latched <= 0;
        end else begin
            if (dma_start_accept) begin dma_inflight <= 1; dma_tasks_latched <= 0; end
            if (async_result_valid) begin
                dma_inflight <= 0; dma_tasks_latched <= async_result_tasks;
                if (async_result_error) begin dma_error_latched <= 1; dma_code_latched <= async_result_code; end
            end
        end
    end
    rk_layout_compute_dispatch #(.BASE(BASE),.BYTES(BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES),.MAX_TASKS(MAX_TASKS),
        .SYNC_STAGES(SYNC_STAGES)) engine (
        .ui_start_offer(core_start_valid),.ui_start_kind(core_start_kind),.ui_ew_start_ready(ew_dma_start_ready),
        .ui_cmac_start_ready(cmac_dma_start_ready),.ui_layout_start_ready(layout_dma_start_ready),
        .ui_ew_start_slot_ready(ew_dma_start_slot_ready),.ui_cmac_start_slot_ready(cmac_dma_start_slot_ready),
        .ui_layout_start_slot_ready(layout_dma_start_slot_ready),
        // The fabric rejects new jobs/memory and success on its own immediate
        // fault. Do not feed that combinational fault through the child READY
        // and job_begin back into the fabric's protocol checker. Its cause is
        // captured by first_fault_valid on the next UI edge, revoking this
        // numerical-child permit through the registered cross-clock path.
        .ui_rearm_permit(sequence_ready_ui0 && init_complete && !external_block &&
                         monitor_healthy === 1'b1 && c0_init_calib_complete === 1'b1),
        .ui_clk(clk),.ui_rst_n(compute_ui_rst_n),.ui_admission_enable(compute_ui_admission),
        .ui_quiet(engine_ui_quiet),.ui_idle_quiet(engine_ui_idle_quiet),
        .core_quiet(engine_core_quiet),.core_restart_ready(engine_core_ready),
        .ui_restart_ready(engine_ui_ready),.ui_idle_restart_ready(engine_ui_idle_ready),
        .ui_start_valid(dma_start_valid),.ui_start_ready(dma_start_ready),.ui_start_slot_ready(dma_start_slot_ready),
        .ui_start_address(core_start_address),.ui_start_amount(core_start_amount),
        .ui_result_valid(async_result_valid),.ui_result_error(async_result_error),
        .ui_result_code(async_result_code),.ui_result_tasks(async_result_tasks),.ui_result_ready(1'b1),
        .ui_fault(engine_crossing_fault),.core_clk(sys_clk),.core_rst_n(compute_core_rst_n),
        .ui_mem_req_valid(engine_req_valid),.ui_mem_req_ready(engine_req_ready),.ui_mem_req_write(engine_req_write),
        .ui_mem_req_addr(engine_req_addr),.ui_mem_req_wdata(engine_req_wdata),.ui_mem_rsp_valid(engine_rsp_valid),
        .ui_mem_rsp_ready(engine_rsp_ready),.ui_mem_rsp_rdata(engine_rsp_rdata),.ui_mem_rsp_error(engine_rsp_error)
    );
`ifdef ASSERT_ON
    always_ff @(posedge clk) begin
        if(compute_ui_rst_n===1'b1) begin
            if(dma_start_ready !== (compute_ui_admission && dma_start_slot_ready))
                $fatal(1,"readiness factor identity failed: dispatcher");
            if(ew_dma_start_ready !== (compute_ui_admission && ew_dma_start_slot_ready))
                $fatal(1,"readiness factor identity failed: EW slot");
            if(cmac_dma_start_ready !== (compute_ui_admission && cmac_dma_start_slot_ready))
                $fatal(1,"readiness factor identity failed: CMAC slot");
            if(layout_dma_start_ready !== (compute_ui_admission && layout_dma_start_slot_ready))
                $fatal(1,"readiness factor identity failed: layout slot");
            if(engine_ui_quiet !== (engine_ui_idle_quiet && !core_start_valid && !dma_start_valid))
                $fatal(1,"quiet factor identity failed: parent engine quiet");
            if(engine_ui_quiet_fast !== engine_ui_quiet)
                $fatal(1,"quiet fast-factor identity failed: parent engine quiet");
            if(engine_ui_ready !== (engine_ui_idle_ready && !core_start_valid && !dma_start_valid))
                $fatal(1,"quiet factor identity failed: parent restart ready");
            if(engine_ui_ready_fast !== engine_ui_ready)
                $fatal(1,"quiet fast-factor identity failed: parent restart ready");
            if((monitor_early_fault || fabric_cause_pending) !== monitor_early_fault)
                $fatal(1,"Reset-reachable pending cause was not an early monitor loss");
            if(fabric_cause_pending_hint !== fabric_cause_pending_decoded)
                $fatal(1,"fault-cause zero tag identity failed: parent fabric");
        end
    end
`endif
    rk_mig_fi_control_service #(.GUARD_TIMEOUT_CYCLES(TIMEOUT_CYCLES),
        .BOOT_TIMEOUT_CYCLES(TIMEOUT_CYCLES),.MONITOR_TIMEOUT_CYCLES(TIMEOUT_CYCLES)) monitor (
        .clk,.joint_rst_n(rst_n),.sequence_ready(sequence_ready_ui0&&!fi_line_fault),
        .calib_complete(c0_init_calib_complete),.mig_interrupt(c0_interrupt),
        .normal_memory_quiescent(fi_fabric_quiet),.diagnostic_memory_quiescent(fi_line_quiet),
        .normal_diag_admission_ready(capacity_normal_admission&&capacity_normal_selected&&fabric_diagnostic_quiet&&
            control_session_quiet&&compute_maintenance_quiet&&
            !control_owned&&!job_owned&&!epoch_started&&!irq&&!backend_memory_busy&&
            !core_start_valid&&!dma_inflight&&!engine_req_valid&&!async_result_valid&&
            !host_rsp_valid&&!engine_rsp_valid&&!normal_axil_awvalid&&!normal_axil_wvalid&&
            !normal_axil_bvalid&&!normal_axil_arvalid&&!normal_axil_rvalid),
        .diagnostic_owner_request(fi_request_pending),.diagnostic_owner_granted(fi_owner_granted),
        .normal_owner_granted(fi_normal_owner),
        .diagnostic_req_valid(fi_ctrl_req_valid),.diagnostic_req_write(fi_ctrl_req_write),
        .diagnostic_req_ready(fi_ctrl_req_ready),.diagnostic_req_address(fi_ctrl_req_address),
        .diagnostic_req_data(fi_ctrl_req_data),.diagnostic_req_strobe(fi_ctrl_req_strobe),
        .diagnostic_req_protection(fi_ctrl_req_protection),.diagnostic_rsp_valid(fi_ctrl_rsp_valid),
        .diagnostic_rsp_ready(fi_ctrl_rsp_ready),.diagnostic_rsp_response(fi_ctrl_rsp_response),
        .check_valid(monitor_check_valid),.check_ready(monitor_check_ready),
        .snapshot_valid(monitor_snapshot_valid),.snapshot_ready(monitor_snapshot_ready),
        .snapshot_status(monitor_snapshot_status),.snapshot_onoff(monitor_snapshot_onoff),
        .snapshot_irq_mask(monitor_snapshot_irq_mask),.monitor_healthy,.monitor_fault,.monitor_fault_code,
        .startup_complete(fi_startup_complete),.initialization_permit(fi_initialization_permit),
        .normal_admission_permit(fi_normal_admission),.control_fault(fi_control_fault),
        .recovery_required(fi_control_recovery),.injection_dirty(fi_injection_dirty),
        .control_transaction_idle(fi_ctrl_idle),.boot_fault(unused_fi_boot_fault),
        .arbiter_fault(unused_fi_arbiter_fault),.guard_quarantine(unused_fi_guard_fault),
        .boot_fault_code(unused_fi_boot_code),.arbiter_fault_code(unused_fi_arbiter_code),
        .guard_fault_code(unused_fi_guard_code),.observed_mask(unused_fi_mask),
        .known_bytes(unused_fi_known_bytes),.mask_disarmed(unused_fi_disarmed),
        .fi_read_address_ready(unused_fi_arready),.unexpected_read_valid(unused_fi_rvalid),
        .unexpected_read_response(unused_fi_rresp),.unexpected_read_data(unused_fi_rdata),
        .fi_xor_we(fi_we_witness),.fi_xor_wrdata(fi_data_witness),.memory_write_clear(fi_clear_witness),
        .m_axi_ctrl_awaddr(n_ctrl_awaddr),
        .m_axi_ctrl_awvalid(n_ctrl_awvalid),
        .m_axi_ctrl_awready(n_ctrl_awready),
        .m_axi_ctrl_wdata(n_ctrl_wdata),
        .m_axi_ctrl_wvalid(n_ctrl_wvalid),
        .m_axi_ctrl_wready(n_ctrl_wready),
        .m_axi_ctrl_bresp(n_ctrl_bresp),
        .m_axi_ctrl_bvalid(n_ctrl_bvalid),
        .m_axi_ctrl_bready(n_ctrl_bready),
        .m_axi_ctrl_araddr(n_ctrl_araddr),
        .m_axi_ctrl_arvalid(n_ctrl_arvalid),
        .m_axi_ctrl_arready(n_ctrl_arready),
        .m_axi_ctrl_rdata(n_ctrl_rdata),
        .m_axi_ctrl_rresp(n_ctrl_rresp),
        .m_axi_ctrl_rvalid(n_ctrl_rvalid),
        .m_axi_ctrl_rready(n_ctrl_rready)
    );
    rk_ddr_memory_fabric_snapshot_capacity #(.BASE(BASE),.BYTES(BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES),.PARENT_SCOPE_COFACTOR(1'b1)) memory (
        .host_pending_ready(host_pending_ready),
        .clk,.joint_rst_n(rst_n),.sequence_ready(sequence_ready_ui0),.calib_complete(c0_init_calib_complete),
        .host_session_busy(backend_memory_busy),.memory_ready(fabric_memory_ready),
        .initialization_enable(fi_initialization_permit),.preinitialization_quiescent(fi_fabric_quiet),
        .job_seal_intent(dma_done && 1'b1),
        .fault_without_parent_abort(fabric_fault_without_parent_abort),
        .fault_without_parent_abort_or_monitor_gap(fabric_fault_without_parent_abort_or_monitor_gap),
        .memory_ready_without_fault(fabric_memory_ready_without_fault),
        .job_begin_ready_without_fault(job_begin_ready_without_fault),
        // The accepted packet is identified by latched backend state/sequence.
        // memory_available is admission-only and may inspect the next req.
        // The child reconstructs the original abort/fault-qualified scope.
        // Snapshot-hit selection uses bare B only behind invalidate===0.
        .host_read_scope(backend_memory_busy&&!host_write),.host_read_epoch(rsp_seq),
        .fault(fabric_fault),.fault_code(fabric_fault_code),.fault_cause_pending(fabric_cause_pending_hint),.fault_is_timeout(fabric_is_timeout),
        .diagnostic_quiescent(fabric_diagnostic_quiet),
        .m_axi_awid(n_axi_awid),
        .m_axi_awaddr(n_axi_awaddr),
        .m_axi_awlen(n_axi_awlen),
        .m_axi_awsize(n_axi_awsize),
        .m_axi_awburst(n_axi_awburst),
        .m_axi_awlock(n_axi_awlock),
        .m_axi_awcache(n_axi_awcache),
        .m_axi_awprot(n_axi_awprot),
        .m_axi_awqos(n_axi_awqos),
        .m_axi_awvalid(n_axi_awvalid),
        .m_axi_awready(n_axi_awready),
        .m_axi_arid(n_axi_arid),
        .m_axi_araddr(n_axi_araddr),
        .m_axi_arlen(n_axi_arlen),
        .m_axi_arsize(n_axi_arsize),
        .m_axi_arburst(n_axi_arburst),
        .m_axi_arlock(n_axi_arlock),
        .m_axi_arcache(n_axi_arcache),
        .m_axi_arprot(n_axi_arprot),
        .m_axi_arqos(n_axi_arqos),
        .m_axi_arvalid(n_axi_arvalid),
        .m_axi_arready(n_axi_arready),
        .m_axi_wdata(n_axi_wdata),
        .m_axi_wstrb(n_axi_wstrb),
        .m_axi_wlast(n_axi_wlast),
        .m_axi_wvalid(n_axi_wvalid),
        .m_axi_wready(n_axi_wready),
        .m_axi_bid(n_axi_bid),
        .m_axi_bresp(n_axi_bresp),
        .m_axi_bvalid(n_axi_bvalid),
        .m_axi_bready(n_axi_bready),
        .m_axi_rid(n_axi_rid),
        .m_axi_rdata(n_axi_rdata),
        .m_axi_rresp(n_axi_rresp),
        .m_axi_rlast(n_axi_rlast),
        .m_axi_rvalid(n_axi_rvalid),
        .m_axi_rready(n_axi_rready),.*
    );
    // Preserve the original normal-path first-fault classification. The
    // diagnostic observer may notice the same bad response, but contributes
    // a parent failure only after a diagnostic session has actually begun.
    always_ff @(posedge clk) begin
        if (!rst_n) capacity_session_seen<=0;
        else if (capacity_busy || capacity_selected) capacity_session_seen<=1;
    end
    assign capacity_fault_active=capacity_owner_fault && capacity_session_seen;
    // Management mux preserves full addresses and held B/R-bank selection.
    assign normal_axil_awaddr=routed_axil_awaddr[0];
    assign diagnostic_axil_awaddr=routed_axil_awaddr[1];
    assign normal_axil_awprot=routed_axil_awprot[0];
    assign diagnostic_axil_awprot=routed_axil_awprot[1];
    assign normal_axil_awvalid=routed_axil_awvalid[0];
    assign diagnostic_axil_awvalid=routed_axil_awvalid[1];
    assign routed_axil_awready[0]=normal_axil_awready;
    assign routed_axil_awready[1]=diagnostic_axil_awready;
    assign normal_axil_wdata=routed_axil_wdata[0];
    assign diagnostic_axil_wdata=routed_axil_wdata[1];
    assign normal_axil_wstrb=routed_axil_wstrb[0];
    assign diagnostic_axil_wstrb=routed_axil_wstrb[1];
    assign normal_axil_wvalid=routed_axil_wvalid[0];
    assign diagnostic_axil_wvalid=routed_axil_wvalid[1];
    assign routed_axil_wready[0]=normal_axil_wready;
    assign routed_axil_wready[1]=diagnostic_axil_wready;
    assign routed_axil_bresp[0]=normal_axil_bresp;
    assign routed_axil_bresp[1]=diagnostic_axil_bresp;
    assign routed_axil_bvalid[0]=normal_axil_bvalid;
    assign routed_axil_bvalid[1]=diagnostic_axil_bvalid;
    assign normal_axil_bready=routed_axil_bready[0];
    assign diagnostic_axil_bready=routed_axil_bready[1];
    assign normal_axil_araddr=routed_axil_araddr[0];
    assign diagnostic_axil_araddr=routed_axil_araddr[1];
    assign normal_axil_arprot=routed_axil_arprot[0];
    assign diagnostic_axil_arprot=routed_axil_arprot[1];
    assign normal_axil_arvalid=routed_axil_arvalid[0];
    assign diagnostic_axil_arvalid=routed_axil_arvalid[1];
    assign routed_axil_arready[0]=normal_axil_arready;
    assign routed_axil_arready[1]=diagnostic_axil_arready;
    assign routed_axil_rdata[0]=normal_axil_rdata;
    assign routed_axil_rdata[1]=diagnostic_axil_rdata;
    assign routed_axil_rresp[0]=normal_axil_rresp;
    assign routed_axil_rresp[1]=diagnostic_axil_rresp;
    assign routed_axil_rvalid[0]=normal_axil_rvalid;
    assign routed_axil_rvalid[1]=diagnostic_axil_rvalid;
    assign normal_axil_rready=routed_axil_rready[0];
    assign diagnostic_axil_rready=routed_axil_rready[1];
    wire [31:0] dispatch_axil_awaddr,reset_axil_awaddr;
    wire [1:0][31:0] reset_routes_awaddr;
    wire [2:0] dispatch_axil_awprot,reset_axil_awprot;
    wire [1:0][2:0] reset_routes_awprot;
    wire dispatch_axil_awvalid,reset_axil_awvalid;
    wire [1:0] reset_routes_awvalid;
    wire dispatch_axil_awready,reset_axil_awready;
    wire [1:0] reset_routes_awready;
    wire [31:0] dispatch_axil_wdata,reset_axil_wdata;
    wire [1:0][31:0] reset_routes_wdata;
    wire [3:0] dispatch_axil_wstrb,reset_axil_wstrb;
    wire [1:0][3:0] reset_routes_wstrb;
    wire dispatch_axil_wvalid,reset_axil_wvalid;
    wire [1:0] reset_routes_wvalid;
    wire dispatch_axil_wready,reset_axil_wready;
    wire [1:0] reset_routes_wready;
    wire [1:0] dispatch_axil_bresp,reset_axil_bresp;
    wire [1:0][1:0] reset_routes_bresp;
    wire dispatch_axil_bvalid,reset_axil_bvalid;
    wire [1:0] reset_routes_bvalid;
    wire dispatch_axil_bready,reset_axil_bready;
    wire [1:0] reset_routes_bready;
    wire [31:0] dispatch_axil_araddr,reset_axil_araddr;
    wire [1:0][31:0] reset_routes_araddr;
    wire [2:0] dispatch_axil_arprot,reset_axil_arprot;
    wire [1:0][2:0] reset_routes_arprot;
    wire dispatch_axil_arvalid,reset_axil_arvalid;
    wire [1:0] reset_routes_arvalid;
    wire dispatch_axil_arready,reset_axil_arready;
    wire [1:0] reset_routes_arready;
    wire [31:0] dispatch_axil_rdata,reset_axil_rdata;
    wire [1:0][31:0] reset_routes_rdata;
    wire [1:0] dispatch_axil_rresp,reset_axil_rresp;
    wire [1:0][1:0] reset_routes_rresp;
    wire dispatch_axil_rvalid,reset_axil_rvalid;
    wire [1:0] reset_routes_rvalid;
    wire dispatch_axil_rready,reset_axil_rready;
    wire [1:0] reset_routes_rready;
    assign dispatch_axil_awaddr=reset_routes_awaddr[0];
    assign reset_axil_awaddr=reset_routes_awaddr[1];
    assign dispatch_axil_awprot=reset_routes_awprot[0];
    assign reset_axil_awprot=reset_routes_awprot[1];
    assign dispatch_axil_awvalid=reset_routes_awvalid[0];
    assign reset_axil_awvalid=reset_routes_awvalid[1];
    assign reset_routes_awready[0]=dispatch_axil_awready;
    assign reset_routes_awready[1]=reset_axil_awready;
    assign dispatch_axil_wdata=reset_routes_wdata[0];
    assign reset_axil_wdata=reset_routes_wdata[1];
    assign dispatch_axil_wstrb=reset_routes_wstrb[0];
    assign reset_axil_wstrb=reset_routes_wstrb[1];
    assign dispatch_axil_wvalid=reset_routes_wvalid[0];
    assign reset_axil_wvalid=reset_routes_wvalid[1];
    assign reset_routes_wready[0]=dispatch_axil_wready;
    assign reset_routes_wready[1]=reset_axil_wready;
    assign reset_routes_bresp[0]=dispatch_axil_bresp;
    assign reset_routes_bresp[1]=reset_axil_bresp;
    assign reset_routes_bvalid[0]=dispatch_axil_bvalid;
    assign reset_routes_bvalid[1]=reset_axil_bvalid;
    assign dispatch_axil_bready=reset_routes_bready[0];
    assign reset_axil_bready=reset_routes_bready[1];
    assign dispatch_axil_araddr=reset_routes_araddr[0];
    assign reset_axil_araddr=reset_routes_araddr[1];
    assign dispatch_axil_arprot=reset_routes_arprot[0];
    assign reset_axil_arprot=reset_routes_arprot[1];
    assign dispatch_axil_arvalid=reset_routes_arvalid[0];
    assign reset_axil_arvalid=reset_routes_arvalid[1];
    assign reset_routes_arready[0]=dispatch_axil_arready;
    assign reset_routes_arready[1]=reset_axil_arready;
    assign reset_routes_rdata[0]=dispatch_axil_rdata;
    assign reset_routes_rdata[1]=reset_axil_rdata;
    assign reset_routes_rresp[0]=dispatch_axil_rresp;
    assign reset_routes_rresp[1]=reset_axil_rresp;
    assign reset_routes_rvalid[0]=dispatch_axil_rvalid;
    assign reset_routes_rvalid[1]=reset_axil_rvalid;
    assign dispatch_axil_rready=reset_routes_rready[0];
    assign reset_axil_rready=reset_routes_rready[1];
    rk_axil_compute_reset_router reset_router (
        .clk,.joint_rst_n(rst_n),
        .s_axil_awaddr(fi_legacy_axil_awaddr),.m_axil_awaddr(reset_routes_awaddr),
        .s_axil_awprot(fi_legacy_axil_awprot),.m_axil_awprot(reset_routes_awprot),
        .s_axil_awvalid(fi_legacy_axil_awvalid),.m_axil_awvalid(reset_routes_awvalid),
        .s_axil_awready(fi_legacy_axil_awready),.m_axil_awready(reset_routes_awready),
        .s_axil_wdata(fi_legacy_axil_wdata),.m_axil_wdata(reset_routes_wdata),
        .s_axil_wstrb(fi_legacy_axil_wstrb),.m_axil_wstrb(reset_routes_wstrb),
        .s_axil_wvalid(fi_legacy_axil_wvalid),.m_axil_wvalid(reset_routes_wvalid),
        .s_axil_wready(fi_legacy_axil_wready),.m_axil_wready(reset_routes_wready),
        .s_axil_bresp(fi_legacy_axil_bresp),.m_axil_bresp(reset_routes_bresp),
        .s_axil_bvalid(fi_legacy_axil_bvalid),.m_axil_bvalid(reset_routes_bvalid),
        .s_axil_bready(fi_legacy_axil_bready),.m_axil_bready(reset_routes_bready),
        .s_axil_araddr(fi_legacy_axil_araddr),.m_axil_araddr(reset_routes_araddr),
        .s_axil_arprot(fi_legacy_axil_arprot),.m_axil_arprot(reset_routes_arprot),
        .s_axil_arvalid(fi_legacy_axil_arvalid),.m_axil_arvalid(reset_routes_arvalid),
        .s_axil_arready(fi_legacy_axil_arready),.m_axil_arready(reset_routes_arready),
        .s_axil_rdata(fi_legacy_axil_rdata),.m_axil_rdata(reset_routes_rdata),
        .s_axil_rresp(fi_legacy_axil_rresp),.m_axil_rresp(reset_routes_rresp),
        .s_axil_rvalid(fi_legacy_axil_rvalid),.m_axil_rvalid(reset_routes_rvalid),
        .s_axil_rready(fi_legacy_axil_rready),.m_axil_rready(reset_routes_rready)
    );
    rk_compute_reset_regs reset_registers (
        .clk,.rst_n,.healthy(reset_healthy),.quiescent(reset_quiet),.reset_blocked(compute_reset_blocked||compute_admission_hold),
        .reset_request_valid(compute_reset_request),.reset_request_ready(compute_reset_request_ready),
        .reset_request_intent(reset_request_intent),
        .reset_result_valid(compute_reset_result),.reset_result_error(compute_reset_error),.reset_error_code(compute_reset_code),
        .reset_epoch(compute_reset_epoch),.reset_result_ready(compute_reset_ack),
        .s_axil_awaddr(reset_axil_awaddr),
        .s_axil_awprot(reset_axil_awprot),
        .s_axil_awvalid(reset_axil_awvalid),
        .s_axil_awready(reset_axil_awready),
        .s_axil_wdata(reset_axil_wdata),
        .s_axil_wstrb(reset_axil_wstrb),
        .s_axil_wvalid(reset_axil_wvalid),
        .s_axil_wready(reset_axil_wready),
        .s_axil_bresp(reset_axil_bresp),
        .s_axil_bvalid(reset_axil_bvalid),
        .s_axil_bready(reset_axil_bready),
        .s_axil_araddr(reset_axil_araddr),
        .s_axil_arprot(reset_axil_arprot),
        .s_axil_arvalid(reset_axil_arvalid),
        .s_axil_arready(reset_axil_arready),
        .s_axil_rdata(reset_axil_rdata),
        .s_axil_rresp(reset_axil_rresp),
        .s_axil_rvalid(reset_axil_rvalid),
        .s_axil_rready(reset_axil_rready)
    );
    rk_axil_diagnostic_router diagnostic_router (
        .clk(clk),
        .joint_rst_n(rst_n),
        .s_axil_awaddr(dispatch_axil_awaddr),
        .s_axil_awprot(dispatch_axil_awprot),
        .s_axil_awvalid(dispatch_axil_awvalid),
        .s_axil_awready(dispatch_axil_awready),
        .s_axil_wdata(dispatch_axil_wdata),
        .s_axil_wstrb(dispatch_axil_wstrb),
        .s_axil_wvalid(dispatch_axil_wvalid),
        .s_axil_wready(dispatch_axil_wready),
        .s_axil_bresp(dispatch_axil_bresp),
        .s_axil_bvalid(dispatch_axil_bvalid),
        .s_axil_bready(dispatch_axil_bready),
        .s_axil_araddr(dispatch_axil_araddr),
        .s_axil_arprot(dispatch_axil_arprot),
        .s_axil_arvalid(dispatch_axil_arvalid),
        .s_axil_arready(dispatch_axil_arready),
        .s_axil_rdata(dispatch_axil_rdata),
        .s_axil_rresp(dispatch_axil_rresp),
        .s_axil_rvalid(dispatch_axil_rvalid),
        .s_axil_rready(dispatch_axil_rready),
        .m_axil_awaddr(routed_axil_awaddr),
        .m_axil_awprot(routed_axil_awprot),
        .m_axil_awvalid(routed_axil_awvalid),
        .m_axil_awready(routed_axil_awready),
        .m_axil_wdata(routed_axil_wdata),
        .m_axil_wstrb(routed_axil_wstrb),
        .m_axil_wvalid(routed_axil_wvalid),
        .m_axil_wready(routed_axil_wready),
        .m_axil_bresp(routed_axil_bresp),
        .m_axil_bvalid(routed_axil_bvalid),
        .m_axil_bready(routed_axil_bready),
        .m_axil_araddr(routed_axil_araddr),
        .m_axil_arprot(routed_axil_arprot),
        .m_axil_arvalid(routed_axil_arvalid),
        .m_axil_arready(routed_axil_arready),
        .m_axil_rdata(routed_axil_rdata),
        .m_axil_rresp(routed_axil_rresp),
        .m_axil_rvalid(routed_axil_rvalid),
        .m_axil_rready(routed_axil_rready)
    );

    rk_ddr_capacity_service #(.BASE_ADDR(BASE[30:0]),.SPAN_BYTES(BYTES[31:0]),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) capacity (
        .clk(clk),
        .joint_rst_n(rst_n),
        .initialization_complete(init_complete && sequence_ready_ui0),
        .calibration_complete(c0_init_calib_complete),
        .mig_interrupt(c0_interrupt),
        .normal_monitor_healthy(monitor_healthy),
        .normal_monitor_fault(monitor_fault),.other_diagnostic_pending(fi_request_pending||fi_owner_granted),
        .normal_fabric_quiet(fabric_diagnostic_quiet),
        .normal_job_owned(control_owned || job_owned || epoch_started || irq || compute_admission_hold),
        .normal_host_busy(backend_memory_busy),
        .normal_engine_pending(core_start_valid || dma_inflight || engine_req_valid || async_result_valid),
        .normal_pending_response(host_rsp_valid || engine_rsp_valid || normal_axil_bvalid || normal_axil_rvalid),
        .normal_admission_enable(capacity_normal_admission),
        .normal_selected(capacity_normal_selected),
        .diagnostic_selected(capacity_selected),
        .owner_busy(capacity_busy),
        .owner_done(capacity_owner_done),
        .owner_fault(capacity_owner_fault),
        .n_axi_awid(fi_merged_axi_awid),
        .n_axi_awaddr(fi_merged_axi_awaddr),
        .n_axi_awlen(fi_merged_axi_awlen),
        .n_axi_awsize(fi_merged_axi_awsize),
        .n_axi_awburst(fi_merged_axi_awburst),
        .n_axi_awlock(fi_merged_axi_awlock),
        .n_axi_awcache(fi_merged_axi_awcache),
        .n_axi_awprot(fi_merged_axi_awprot),
        .n_axi_awqos(fi_merged_axi_awqos),
        .n_axi_awvalid(fi_merged_axi_awvalid),
        .n_axi_awready(fi_merged_axi_awready),
        .n_axi_arid(fi_merged_axi_arid),
        .n_axi_araddr(fi_merged_axi_araddr),
        .n_axi_arlen(fi_merged_axi_arlen),
        .n_axi_arsize(fi_merged_axi_arsize),
        .n_axi_arburst(fi_merged_axi_arburst),
        .n_axi_arlock(fi_merged_axi_arlock),
        .n_axi_arcache(fi_merged_axi_arcache),
        .n_axi_arprot(fi_merged_axi_arprot),
        .n_axi_arqos(fi_merged_axi_arqos),
        .n_axi_arvalid(fi_merged_axi_arvalid),
        .n_axi_arready(fi_merged_axi_arready),
        .n_axi_wdata(fi_merged_axi_wdata),
        .n_axi_wstrb(fi_merged_axi_wstrb),
        .n_axi_wlast(fi_merged_axi_wlast),
        .n_axi_wvalid(fi_merged_axi_wvalid),
        .n_axi_wready(fi_merged_axi_wready),
        .n_axi_bid(fi_merged_axi_bid),
        .n_axi_bresp(fi_merged_axi_bresp),
        .n_axi_bvalid(fi_merged_axi_bvalid),
        .n_axi_bready(fi_merged_axi_bready),
        .n_axi_rid(fi_merged_axi_rid),
        .n_axi_rdata(fi_merged_axi_rdata),
        .n_axi_rresp(fi_merged_axi_rresp),
        .n_axi_rlast(fi_merged_axi_rlast),
        .n_axi_rvalid(fi_merged_axi_rvalid),
        .n_axi_rready(fi_merged_axi_rready),
        .m_axi_awid(m_axi_awid),
        .m_axi_awaddr(m_axi_awaddr),
        .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize),
        .m_axi_awburst(m_axi_awburst),
        .m_axi_awlock(m_axi_awlock),
        .m_axi_awcache(m_axi_awcache),
        .m_axi_awprot(m_axi_awprot),
        .m_axi_awqos(m_axi_awqos),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_awready(m_axi_awready),
        .m_axi_arid(m_axi_arid),
        .m_axi_araddr(m_axi_araddr),
        .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize),
        .m_axi_arburst(m_axi_arburst),
        .m_axi_arlock(m_axi_arlock),
        .m_axi_arcache(m_axi_arcache),
        .m_axi_arprot(m_axi_arprot),
        .m_axi_arqos(m_axi_arqos),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_arready(m_axi_arready),
        .m_axi_wdata(m_axi_wdata),
        .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_wvalid(m_axi_wvalid),
        .m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid),
        .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid),
        .m_axi_bready(m_axi_bready),
        .m_axi_rid(m_axi_rid),
        .m_axi_rdata(m_axi_rdata),
        .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rready(m_axi_rready),
        .n_ctrl_awaddr(n_ctrl_awaddr),
        .n_ctrl_awvalid(n_ctrl_awvalid),
        .n_ctrl_awready(n_ctrl_awready),
        .n_ctrl_wdata(n_ctrl_wdata),
        .n_ctrl_wvalid(n_ctrl_wvalid),
        .n_ctrl_wready(n_ctrl_wready),
        .n_ctrl_bresp(n_ctrl_bresp),
        .n_ctrl_bvalid(n_ctrl_bvalid),
        .n_ctrl_bready(n_ctrl_bready),
        .n_ctrl_araddr(n_ctrl_araddr),
        .n_ctrl_arvalid(n_ctrl_arvalid),
        .n_ctrl_arready(n_ctrl_arready),
        .n_ctrl_rdata(n_ctrl_rdata),
        .n_ctrl_rresp(n_ctrl_rresp),
        .n_ctrl_rvalid(n_ctrl_rvalid),
        .n_ctrl_rready(n_ctrl_rready),
        .m_axi_ctrl_awaddr(m_axi_ctrl_awaddr),
        .m_axi_ctrl_awvalid(m_axi_ctrl_awvalid),
        .m_axi_ctrl_awready(m_axi_ctrl_awready),
        .m_axi_ctrl_wdata(m_axi_ctrl_wdata),
        .m_axi_ctrl_wvalid(m_axi_ctrl_wvalid),
        .m_axi_ctrl_wready(m_axi_ctrl_wready),
        .m_axi_ctrl_bresp(m_axi_ctrl_bresp),
        .m_axi_ctrl_bvalid(m_axi_ctrl_bvalid),
        .m_axi_ctrl_bready(m_axi_ctrl_bready),
        .m_axi_ctrl_araddr(m_axi_ctrl_araddr),
        .m_axi_ctrl_arvalid(m_axi_ctrl_arvalid),
        .m_axi_ctrl_arready(m_axi_ctrl_arready),
        .m_axi_ctrl_rdata(m_axi_ctrl_rdata),
        .m_axi_ctrl_rresp(m_axi_ctrl_rresp),
        .m_axi_ctrl_rvalid(m_axi_ctrl_rvalid),
        .m_axi_ctrl_rready(m_axi_ctrl_rready),
        .s_axil_awaddr(diagnostic_axil_awaddr),
        .s_axil_awprot(diagnostic_axil_awprot),
        .s_axil_awvalid(diagnostic_axil_awvalid),
        .s_axil_awready(diagnostic_axil_awready),
        .s_axil_wdata(diagnostic_axil_wdata),
        .s_axil_wstrb(diagnostic_axil_wstrb),
        .s_axil_wvalid(diagnostic_axil_wvalid),
        .s_axil_wready(diagnostic_axil_wready),
        .s_axil_bresp(diagnostic_axil_bresp),
        .s_axil_bvalid(diagnostic_axil_bvalid),
        .s_axil_bready(diagnostic_axil_bready),
        .s_axil_araddr(diagnostic_axil_araddr),
        .s_axil_arprot(diagnostic_axil_arprot),
        .s_axil_arvalid(diagnostic_axil_arvalid),
        .s_axil_arready(diagnostic_axil_arready),
        .s_axil_rdata(diagnostic_axil_rdata),
        .s_axil_rresp(diagnostic_axil_rresp),
        .s_axil_rvalid(diagnostic_axil_rvalid),
        .s_axil_rready(diagnostic_axil_rready)
    );

    assign fi_mux_awid[0]=n_axi_awid;
    assign fi_mux_awid[1]=fi_bus_awid;
    assign fi_mux_awaddr[0]=n_axi_awaddr;
    assign fi_mux_awaddr[1]=fi_bus_awaddr;
    assign fi_mux_awlen[0]=n_axi_awlen;
    assign fi_mux_awlen[1]=fi_bus_awlen;
    assign fi_mux_awsize[0]=n_axi_awsize;
    assign fi_mux_awsize[1]=fi_bus_awsize;
    assign fi_mux_awburst[0]=n_axi_awburst;
    assign fi_mux_awburst[1]=fi_bus_awburst;
    assign fi_mux_awlock[0]=n_axi_awlock;
    assign fi_mux_awlock[1]=fi_bus_awlock;
    assign fi_mux_awcache[0]=n_axi_awcache;
    assign fi_mux_awcache[1]=fi_bus_awcache;
    assign fi_mux_awprot[0]=n_axi_awprot;
    assign fi_mux_awprot[1]=fi_bus_awprot;
    assign fi_mux_awqos[0]=n_axi_awqos;
    assign fi_mux_awqos[1]=fi_bus_awqos;
    assign fi_mux_awvalid[0]=n_axi_awvalid;
    assign fi_mux_awvalid[1]=fi_bus_awvalid;
    assign n_axi_awready=fi_mux_awready[0];
    assign fi_bus_awready=fi_mux_awready[1];
    assign fi_mux_arid[0]=n_axi_arid;
    assign fi_mux_arid[1]=fi_bus_arid;
    assign fi_mux_araddr[0]=n_axi_araddr;
    assign fi_mux_araddr[1]=fi_bus_araddr;
    assign fi_mux_arlen[0]=n_axi_arlen;
    assign fi_mux_arlen[1]=fi_bus_arlen;
    assign fi_mux_arsize[0]=n_axi_arsize;
    assign fi_mux_arsize[1]=fi_bus_arsize;
    assign fi_mux_arburst[0]=n_axi_arburst;
    assign fi_mux_arburst[1]=fi_bus_arburst;
    assign fi_mux_arlock[0]=n_axi_arlock;
    assign fi_mux_arlock[1]=fi_bus_arlock;
    assign fi_mux_arcache[0]=n_axi_arcache;
    assign fi_mux_arcache[1]=fi_bus_arcache;
    assign fi_mux_arprot[0]=n_axi_arprot;
    assign fi_mux_arprot[1]=fi_bus_arprot;
    assign fi_mux_arqos[0]=n_axi_arqos;
    assign fi_mux_arqos[1]=fi_bus_arqos;
    assign fi_mux_arvalid[0]=n_axi_arvalid;
    assign fi_mux_arvalid[1]=fi_bus_arvalid;
    assign n_axi_arready=fi_mux_arready[0];
    assign fi_bus_arready=fi_mux_arready[1];
    assign fi_mux_wdata[0]=n_axi_wdata;
    assign fi_mux_wdata[1]=fi_bus_wdata;
    assign fi_mux_wstrb[0]=n_axi_wstrb;
    assign fi_mux_wstrb[1]=fi_bus_wstrb;
    assign fi_mux_wlast[0]=n_axi_wlast;
    assign fi_mux_wlast[1]=fi_bus_wlast;
    assign fi_mux_wvalid[0]=n_axi_wvalid;
    assign fi_mux_wvalid[1]=fi_bus_wvalid;
    assign n_axi_wready=fi_mux_wready[0];
    assign fi_bus_wready=fi_mux_wready[1];
    assign n_axi_bid=fi_mux_bid[0];
    assign fi_bus_bid=fi_mux_bid[1];
    assign n_axi_bresp=fi_mux_bresp[0];
    assign fi_bus_bresp=fi_mux_bresp[1];
    assign n_axi_bvalid=fi_mux_bvalid[0];
    assign fi_bus_bvalid=fi_mux_bvalid[1];
    assign fi_mux_bready[0]=n_axi_bready;
    assign fi_mux_bready[1]=fi_bus_bready;
    assign n_axi_rid=fi_mux_rid[0];
    assign fi_bus_rid=fi_mux_rid[1];
    assign n_axi_rdata=fi_mux_rdata[0];
    assign fi_bus_rdata=fi_mux_rdata[1];
    assign n_axi_rresp=fi_mux_rresp[0];
    assign fi_bus_rresp=fi_mux_rresp[1];
    assign n_axi_rlast=fi_mux_rlast[0];
    assign fi_bus_rlast=fi_mux_rlast[1];
    assign n_axi_rvalid=fi_mux_rvalid[0];
    assign fi_bus_rvalid=fi_mux_rvalid[1];
    assign fi_mux_rready[0]=n_axi_rready;
    assign fi_mux_rready[1]=fi_bus_rready;
    rk_ddr_diagnostic_mux fi_data_mux (.joint_rst_n(rst_n),.diagnostic_selected(fi_owner_granted),
        .s_axi_awid(fi_mux_awid),.m_axi_awid(fi_merged_axi_awid),
        .s_axi_awaddr(fi_mux_awaddr),.m_axi_awaddr(fi_merged_axi_awaddr),
        .s_axi_awlen(fi_mux_awlen),.m_axi_awlen(fi_merged_axi_awlen),
        .s_axi_awsize(fi_mux_awsize),.m_axi_awsize(fi_merged_axi_awsize),
        .s_axi_awburst(fi_mux_awburst),.m_axi_awburst(fi_merged_axi_awburst),
        .s_axi_awlock(fi_mux_awlock),.m_axi_awlock(fi_merged_axi_awlock),
        .s_axi_awcache(fi_mux_awcache),.m_axi_awcache(fi_merged_axi_awcache),
        .s_axi_awprot(fi_mux_awprot),.m_axi_awprot(fi_merged_axi_awprot),
        .s_axi_awqos(fi_mux_awqos),.m_axi_awqos(fi_merged_axi_awqos),
        .s_axi_awvalid(fi_mux_awvalid),.m_axi_awvalid(fi_merged_axi_awvalid),
        .s_axi_awready(fi_mux_awready),.m_axi_awready(fi_merged_axi_awready),
        .s_axi_arid(fi_mux_arid),.m_axi_arid(fi_merged_axi_arid),
        .s_axi_araddr(fi_mux_araddr),.m_axi_araddr(fi_merged_axi_araddr),
        .s_axi_arlen(fi_mux_arlen),.m_axi_arlen(fi_merged_axi_arlen),
        .s_axi_arsize(fi_mux_arsize),.m_axi_arsize(fi_merged_axi_arsize),
        .s_axi_arburst(fi_mux_arburst),.m_axi_arburst(fi_merged_axi_arburst),
        .s_axi_arlock(fi_mux_arlock),.m_axi_arlock(fi_merged_axi_arlock),
        .s_axi_arcache(fi_mux_arcache),.m_axi_arcache(fi_merged_axi_arcache),
        .s_axi_arprot(fi_mux_arprot),.m_axi_arprot(fi_merged_axi_arprot),
        .s_axi_arqos(fi_mux_arqos),.m_axi_arqos(fi_merged_axi_arqos),
        .s_axi_arvalid(fi_mux_arvalid),.m_axi_arvalid(fi_merged_axi_arvalid),
        .s_axi_arready(fi_mux_arready),.m_axi_arready(fi_merged_axi_arready),
        .s_axi_wdata(fi_mux_wdata),.m_axi_wdata(fi_merged_axi_wdata),
        .s_axi_wstrb(fi_mux_wstrb),.m_axi_wstrb(fi_merged_axi_wstrb),
        .s_axi_wlast(fi_mux_wlast),.m_axi_wlast(fi_merged_axi_wlast),
        .s_axi_wvalid(fi_mux_wvalid),.m_axi_wvalid(fi_merged_axi_wvalid),
        .s_axi_wready(fi_mux_wready),.m_axi_wready(fi_merged_axi_wready),
        .s_axi_bid(fi_mux_bid),.m_axi_bid(fi_merged_axi_bid),
        .s_axi_bresp(fi_mux_bresp),.m_axi_bresp(fi_merged_axi_bresp),
        .s_axi_bvalid(fi_mux_bvalid),.m_axi_bvalid(fi_merged_axi_bvalid),
        .s_axi_bready(fi_mux_bready),.m_axi_bready(fi_merged_axi_bready),
        .s_axi_rid(fi_mux_rid),.m_axi_rid(fi_merged_axi_rid),
        .s_axi_rdata(fi_mux_rdata),.m_axi_rdata(fi_merged_axi_rdata),
        .s_axi_rresp(fi_mux_rresp),.m_axi_rresp(fi_merged_axi_rresp),
        .s_axi_rlast(fi_mux_rlast),.m_axi_rlast(fi_merged_axi_rlast),
        .s_axi_rvalid(fi_mux_rvalid),.m_axi_rvalid(fi_merged_axi_rvalid),
        .s_axi_rready(fi_mux_rready),.m_axi_rready(fi_merged_axi_rready));
    rk_mig_fi_line_access #(.BASE(BASE),.BYTES(BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) fi_lines (
        .clk,.joint_rst_n(rst_n),.diagnostic_owned(fi_owner_granted),
        .sequence_ready(sequence_ready_ui0),.calib_complete(c0_init_calib_complete),
        .request_enable(fi_ctrl_idle&&fi_ctrl_req_valid===1'b0),
        .req_valid(fi_line_req_valid),.req_ready(fi_line_req_ready),.req_write(fi_line_req_write),
        .req_address(fi_line_req_address),.req_data(fi_line_req_data),.req_expected_response(fi_line_expected_response),
        .rsp_valid(fi_line_rsp_valid),.rsp_ready(fi_line_rsp_ready),.rsp_data(fi_line_rsp_data),
        .rsp_response(fi_line_rsp_response),.rsp_matched(fi_line_rsp_matched),
        .quiet(fi_line_quiet),.recovery_required(fi_line_recovery),.fault(fi_line_fault),.fault_code(fi_line_fault_code),
        .m_axi_awid(fi_bus_awid),
        .m_axi_awaddr(fi_bus_awaddr),
        .m_axi_awlen(fi_bus_awlen),
        .m_axi_awsize(fi_bus_awsize),
        .m_axi_awburst(fi_bus_awburst),
        .m_axi_awlock(fi_bus_awlock),
        .m_axi_awcache(fi_bus_awcache),
        .m_axi_awprot(fi_bus_awprot),
        .m_axi_awqos(fi_bus_awqos),
        .m_axi_awvalid(fi_bus_awvalid),
        .m_axi_awready(fi_bus_awready),
        .m_axi_arid(fi_bus_arid),
        .m_axi_araddr(fi_bus_araddr),
        .m_axi_arlen(fi_bus_arlen),
        .m_axi_arsize(fi_bus_arsize),
        .m_axi_arburst(fi_bus_arburst),
        .m_axi_arlock(fi_bus_arlock),
        .m_axi_arcache(fi_bus_arcache),
        .m_axi_arprot(fi_bus_arprot),
        .m_axi_arqos(fi_bus_arqos),
        .m_axi_arvalid(fi_bus_arvalid),
        .m_axi_arready(fi_bus_arready),
        .m_axi_wdata(fi_bus_wdata),
        .m_axi_wstrb(fi_bus_wstrb),
        .m_axi_wlast(fi_bus_wlast),
        .m_axi_wvalid(fi_bus_wvalid),
        .m_axi_wready(fi_bus_wready),
        .m_axi_bid(fi_bus_bid),
        .m_axi_bresp(fi_bus_bresp),
        .m_axi_bvalid(fi_bus_bvalid),
        .m_axi_bready(fi_bus_bready),
        .m_axi_rid(fi_bus_rid),
        .m_axi_rdata(fi_bus_rdata),
        .m_axi_rresp(fi_bus_rresp),
        .m_axi_rlast(fi_bus_rlast),
        .m_axi_rvalid(fi_bus_rvalid),
        .m_axi_rready(fi_bus_rready));
    wire unused_fi_status=fi_injection_dirty;
    assign fi_legacy_axil_awaddr=fi_route_axil_awaddr[0];
    assign fi_register_axil_awaddr=fi_route_axil_awaddr[1];
    assign fi_legacy_axil_awprot=fi_route_axil_awprot[0];
    assign fi_register_axil_awprot=fi_route_axil_awprot[1];
    assign fi_legacy_axil_awvalid=fi_route_axil_awvalid[0];
    assign fi_register_axil_awvalid=fi_route_axil_awvalid[1];
    assign fi_route_axil_awready[0]=fi_legacy_axil_awready;
    assign fi_route_axil_awready[1]=fi_register_axil_awready;
    assign fi_legacy_axil_wdata=fi_route_axil_wdata[0];
    assign fi_register_axil_wdata=fi_route_axil_wdata[1];
    assign fi_legacy_axil_wstrb=fi_route_axil_wstrb[0];
    assign fi_register_axil_wstrb=fi_route_axil_wstrb[1];
    assign fi_legacy_axil_wvalid=fi_route_axil_wvalid[0];
    assign fi_register_axil_wvalid=fi_route_axil_wvalid[1];
    assign fi_route_axil_wready[0]=fi_legacy_axil_wready;
    assign fi_route_axil_wready[1]=fi_register_axil_wready;
    assign fi_route_axil_bresp[0]=fi_legacy_axil_bresp;
    assign fi_route_axil_bresp[1]=fi_register_axil_bresp;
    assign fi_route_axil_bvalid[0]=fi_legacy_axil_bvalid;
    assign fi_route_axil_bvalid[1]=fi_register_axil_bvalid;
    assign fi_legacy_axil_bready=fi_route_axil_bready[0];
    assign fi_register_axil_bready=fi_route_axil_bready[1];
    assign fi_legacy_axil_araddr=fi_route_axil_araddr[0];
    assign fi_register_axil_araddr=fi_route_axil_araddr[1];
    assign fi_legacy_axil_arprot=fi_route_axil_arprot[0];
    assign fi_register_axil_arprot=fi_route_axil_arprot[1];
    assign fi_legacy_axil_arvalid=fi_route_axil_arvalid[0];
    assign fi_register_axil_arvalid=fi_route_axil_arvalid[1];
    assign fi_route_axil_arready[0]=fi_legacy_axil_arready;
    assign fi_route_axil_arready[1]=fi_register_axil_arready;
    assign fi_route_axil_rdata[0]=fi_legacy_axil_rdata;
    assign fi_route_axil_rdata[1]=fi_register_axil_rdata;
    assign fi_route_axil_rresp[0]=fi_legacy_axil_rresp;
    assign fi_route_axil_rresp[1]=fi_register_axil_rresp;
    assign fi_route_axil_rvalid[0]=fi_legacy_axil_rvalid;
    assign fi_route_axil_rvalid[1]=fi_register_axil_rvalid;
    assign fi_legacy_axil_rready=fi_route_axil_rready[0];
    assign fi_register_axil_rready=fi_route_axil_rready[1];
    rk_axil_diagnostic_router #(.DIAGNOSTIC_PAGE(24'h000003)) fi_management_router (
        .clk(clk),.joint_rst_n(rst_n),
        .s_axil_awaddr(s_axil_awaddr),.m_axil_awaddr(fi_route_axil_awaddr),
        .s_axil_awprot(s_axil_awprot),.m_axil_awprot(fi_route_axil_awprot),
        .s_axil_awvalid(s_axil_awvalid),.m_axil_awvalid(fi_route_axil_awvalid),
        .s_axil_awready(s_axil_awready),.m_axil_awready(fi_route_axil_awready),
        .s_axil_wdata(s_axil_wdata),.m_axil_wdata(fi_route_axil_wdata),
        .s_axil_wstrb(s_axil_wstrb),.m_axil_wstrb(fi_route_axil_wstrb),
        .s_axil_wvalid(s_axil_wvalid),.m_axil_wvalid(fi_route_axil_wvalid),
        .s_axil_wready(s_axil_wready),.m_axil_wready(fi_route_axil_wready),
        .s_axil_bresp(s_axil_bresp),.m_axil_bresp(fi_route_axil_bresp),
        .s_axil_bvalid(s_axil_bvalid),.m_axil_bvalid(fi_route_axil_bvalid),
        .s_axil_bready(s_axil_bready),.m_axil_bready(fi_route_axil_bready),
        .s_axil_araddr(s_axil_araddr),.m_axil_araddr(fi_route_axil_araddr),
        .s_axil_arprot(s_axil_arprot),.m_axil_arprot(fi_route_axil_arprot),
        .s_axil_arvalid(s_axil_arvalid),.m_axil_arvalid(fi_route_axil_arvalid),
        .s_axil_arready(s_axil_arready),.m_axil_arready(fi_route_axil_arready),
        .s_axil_rdata(s_axil_rdata),.m_axil_rdata(fi_route_axil_rdata),
        .s_axil_rresp(s_axil_rresp),.m_axil_rresp(fi_route_axil_rresp),
        .s_axil_rvalid(s_axil_rvalid),.m_axil_rvalid(fi_route_axil_rvalid),
        .s_axil_rready(s_axil_rready),.m_axil_rready(fi_route_axil_rready));
    // CLAIM's existing normal-admission factors imply reset_healthy=1.
    // Project that known health out of the request/READY/blocked feedback.
    // Keep the original full quiet witness on whole-reset and owner-grant paths.
    wire fi_claim_base = fi_normal_admission&&capacity_normal_admission&&capacity_normal_selected&&
            control_session_quiet&&
            fabric_diagnostic_quiet&&!live_block&&!control_owned&&!job_owned&&!epoch_started&&!irq&&
            !backend_memory_busy&&!core_start_valid&&!dma_inflight&&!engine_req_valid&&!async_result_valid&&
            !host_rsp_valid&&!engine_rsp_valid&&!normal_axil_awvalid&&!normal_axil_wvalid&&
            !normal_axil_bvalid&&!normal_axil_arvalid&&!normal_axil_rvalid;
    wire reset_quiet_under_fi_base = control_quiet&&engine_ui_quiet_fast&&
        !host_valid&&!job_active&&
        !m_axi_awvalid&&!m_axi_wvalid&&!m_axi_bvalid&&!m_axi_arvalid&&!m_axi_rvalid&&
        !m_axi_ctrl_awvalid&&!m_axi_ctrl_wvalid&&!m_axi_ctrl_bvalid&&!m_axi_ctrl_arvalid&&!m_axi_ctrl_rvalid;
    wire reset_request_assuming_health = reset_request_intent&&
        (reset_quiet_under_fi_base===1'b1)&&(compute_request_ready_without_health===1'b1)&&
        (compute_admission_hold===1'b0);
    wire compute_quiet_under_fi_base = compute_maintenance_quiet_without_request&&
        (reset_request_assuming_health===1'b0);
`ifdef ASSERT_ON
    always @(posedge clk)if(rst_n===1'b1)begin
        if(fi_claim_base===1'b1)begin
            if(reset_healthy!==1'b1||reset_quiet!==reset_quiet_under_fi_base)
                $fatal(1,"FI CLAIM cofactor precondition differs");
        end
        if(((fi_claim_base&&compute_maintenance_quiet)===1'b1)!==
           ((fi_claim_base&&compute_quiet_under_fi_base)===1'b1))
            $fatal(1,"FI CLAIM known-health cofactor changes acceptance");
    end
`endif
    rk_mig_fi_management_regs #(.BASE(BASE),.BYTES(BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) fi_management (
        .clk(clk),.joint_rst_n(rst_n),
        .claim_eligible(fi_claim_base&&compute_quiet_under_fi_base),
        .startup_complete(fi_startup_complete),.memory_initialized(init_complete),
        .parent_fault(fault),.control_fault(fi_control_fault),.recovery_required(fi_recovery_required),
        .owner_granted(fi_owner_granted),.owner_request(fi_owner_request),
        .local_fault(fi_management_fault),.local_fault_code(fi_management_fault_code),
        .transaction_quiet(fi_management_transaction_quiet),
        .observed_mask(unused_fi_mask),.known_mask_bytes(unused_fi_known_bytes),.mask_disarmed(unused_fi_disarmed),
        .mc_ecc_valid(fi_mc_ecc_valid),.mc_read_data_valid(fi_mc_read_data_valid),
        .mc_single(fi_mc_single),.mc_multiple(fi_mc_multiple),.mc_ecc_address(fi_mc_ecc_address),.fi_clear(fi_clear_witness),
        .ctrl_req_valid(fi_ctrl_req_valid),.ctrl_req_write(fi_ctrl_req_write),.ctrl_req_ready(fi_ctrl_req_ready),
        .ctrl_req_address(fi_ctrl_req_address),.ctrl_req_data(fi_ctrl_req_data),
        .ctrl_req_strobe(fi_ctrl_req_strobe),.ctrl_req_protection(fi_ctrl_req_protection),
        .ctrl_rsp_valid(fi_ctrl_rsp_valid),.ctrl_rsp_ready(fi_ctrl_rsp_ready),.ctrl_rsp_response(fi_ctrl_rsp_response),
        .line_req_valid(fi_line_req_valid),.line_req_write(fi_line_req_write),.line_req_ready(fi_line_req_ready),
        .line_req_address(fi_line_req_address),.line_req_data(fi_line_req_data),.line_expected_response(fi_line_expected_response),
        .line_rsp_valid(fi_line_rsp_valid),.line_rsp_ready(fi_line_rsp_ready),.line_rsp_matched(fi_line_rsp_matched),
        .line_rsp_data(fi_line_rsp_data),.line_rsp_response(fi_line_rsp_response),
        .s_axil_awaddr(fi_register_axil_awaddr),
        .s_axil_awprot(fi_register_axil_awprot),
        .s_axil_awvalid(fi_register_axil_awvalid),
        .s_axil_awready(fi_register_axil_awready),
        .s_axil_wdata(fi_register_axil_wdata),
        .s_axil_wstrb(fi_register_axil_wstrb),
        .s_axil_wvalid(fi_register_axil_wvalid),
        .s_axil_wready(fi_register_axil_wready),
        .s_axil_bresp(fi_register_axil_bresp),
        .s_axil_bvalid(fi_register_axil_bvalid),
        .s_axil_bready(fi_register_axil_bready),
        .s_axil_araddr(fi_register_axil_araddr),
        .s_axil_arprot(fi_register_axil_arprot),
        .s_axil_arvalid(fi_register_axil_arvalid),
        .s_axil_arready(fi_register_axil_arready),
        .s_axil_rdata(fi_register_axil_rdata),
        .s_axil_rresp(fi_register_axil_rresp),
        .s_axil_rvalid(fi_register_axil_rvalid),
        .s_axil_rready(fi_register_axil_rready));
endmodule
