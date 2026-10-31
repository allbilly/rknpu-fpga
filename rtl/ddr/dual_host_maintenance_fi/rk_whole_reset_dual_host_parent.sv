// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Unqualified retained dual-host/SYS maintenance composition. Source interfaces
// only until its own native, mapped, timing and physical gates pass.
module rk_whole_reset_dual_host_parent #(
    parameter logic [31:0] BASE = 0,
    parameter logic [32:0] BYTES = 33'h080000000,
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter int unsigned MAX_TASKS = 4095,
    parameter int unsigned SYS_HOLD_CYCLES = 64,
    parameter int unsigned UI_FRESH_CYCLES = 4,
    parameter int unsigned SYNC_STAGES = 3,
    parameter int unsigned RESET_WAIT_TIMEOUT_CYCLES = 65536,
    parameter logic [63:0] MAINTENANCE_TIMEOUT_CYCLES = 64'd5000000000,
    parameter integer MAINTENANCE_STABLE_SAMPLES = 2
) (
    input logic sys_clk, cfg_reset,
    // Configuration-only reset released by fresh local UI edges. This must
    // never be derived from MIG/client/link/PERST/TAP reset.
    input wire ui_power_rst_n,
    input wire jtag_link_healthy,pcie_link_healthy,
    output wire [1:0] transport_owner,
    output wire [31:0] transport_lease_epoch,
    output wire transport_release_ready,
    output wire pcie_irq,pcie_protocol_fault,pcie_epoch_fault,owner_protocol_fault,
    output wire [7:0] owner_failure_code,
    output wire frontend_epoch_rst_n,
    input wire [31:0] pcie_axil_awaddr,pcie_axil_wdata,pcie_axil_araddr,
    input wire [2:0] pcie_axil_awprot,pcie_axil_arprot,
    input wire [3:0] pcie_axil_wstrb,
    input wire pcie_axil_awvalid,pcie_axil_wvalid,pcie_axil_bready,
    input wire pcie_axil_arvalid,pcie_axil_rready,
    output wire pcie_axil_awready,pcie_axil_wready,pcie_axil_bvalid,
    output wire pcie_axil_arready,pcie_axil_rvalid,
    output wire [1:0] pcie_axil_bresp,pcie_axil_rresp,
    output wire [31:0] pcie_axil_rdata,
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
    output logic [7:0] fault_code,
    output logic init_complete, init_active, memory_ready, job_owned, job_active, job_retired,
    input wire maintenance_req_valid,
    output wire maintenance_req_ready,
    input wire [603:0] maintenance_req,
    output wire maintenance_rsp_valid,
    output wire [511:0] maintenance_rsp_data,
    output wire [7:0] maintenance_rsp_status,
    output wire [15:0] maintenance_rsp_seq,
    output wire maintenance_quiesce_request,maintenance_reset_request,
    output wire maintenance_gate_fault,maintenance_bridge_fault,

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

    wire power_rst_n=~cfg_reset;
    wire coordinator_ready,sys_quiesce_ack,sys_quiescent,sys_platform_ready;
    wire ui_admission_block,parent_drained,parent_initialized,sealed_quiet,endpoint_epoch_ready;
    wire backend_req_valid,backend_req_ready,backend_rsp_valid;
    wire [603:0] backend_req;
    wire [511:0] backend_rsp_data;
    wire [7:0] backend_rsp_status;
    wire [15:0] backend_rsp_seq;
    // The coordinator revokes combinational sequence_complete on restart.
    // Sample its witness before the maintenance controller: direct feedback
    // through failure_now/reset_request would form a combinational cycle.
    logic maintenance_sequence_complete;
    always @(posedge sys_clk or negedge power_rst_n)begin
        if(!power_rst_n)maintenance_sequence_complete<=0;
        else maintenance_sequence_complete<=sequence_complete;
    end

    // Once-only bootstrap admission. The retained bridge's internal boot
    // request must finish before the normal frame gate may return ready for
    // denials. Otherwise the first ordinary ID frame could be denied before
    // the original parent enables its own raw interface.
    localparam integer ENABLE_STAGES=SYNC_STAGES<3?3:SYNC_STAGES;
    logic normal_shell_started;
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [ENABLE_STAGES-1:0] normal_shell_started_sync;
    always @(posedge sys_clk or negedge power_rst_n)begin
        if(!power_rst_n)normal_shell_started<=0;
        else if(reset_req_ready===1'b1&&maintenance_quiesce_request===1'b0&&sequence_complete===1'b1)
            normal_shell_started<=1;
    end
    always @(posedge c0_ui_clk or negedge ui_power_rst_n)begin
        if(!ui_power_rst_n)normal_shell_started_sync<=0;
        else normal_shell_started_sync<={normal_shell_started_sync[ENABLE_STAGES-2:0],normal_shell_started};
    end

    rk_whole_reset_control #(.TIMEOUT_CYCLES(MAINTENANCE_TIMEOUT_CYCLES),
        .STABLE_SAMPLES(MAINTENANCE_STABLE_SAMPLES)) maintenance (
        .sys_clk(sys_clk),.power_rst_n(power_rst_n),
        .req_valid(maintenance_req_valid),.req_ready(maintenance_req_ready),.req(maintenance_req),
        .rsp_valid(maintenance_rsp_valid),.rsp_data(maintenance_rsp_data),
        .rsp_status(maintenance_rsp_status),.rsp_seq(maintenance_rsp_seq),
        .quiesce_request(maintenance_quiesce_request),.quiesce_ack(sys_quiesce_ack),.quiescent(sys_quiescent),
        .reset_request(maintenance_reset_request),.reset_ready(reset_req_ready),
        .reset_asserted(~mig_sys_rst_n),.reset_complete(maintenance_sequence_complete),
        .reset_fault(sequence_fault),.reset_fault_code(sequence_fault_code),
        .platform_ready(sys_platform_ready&&!maintenance_bridge_fault)
    );
    rk_whole_reset_dual_power_ui_bridge #(.SYNC_STAGES(SYNC_STAGES),.UI_FRESH_CYCLES(UI_FRESH_CYCLES)) bridge (
        .sys_clk(sys_clk),.ui_clk(c0_ui_clk),.power_rst_n(power_rst_n),.ui_power_rst_n(ui_power_rst_n),
        .sys_quiesce_request(maintenance_quiesce_request),.coordinator_ready(coordinator_ready),
        .controller_reset_ready(reset_req_ready),.sys_quiesce_ack(sys_quiesce_ack),
        .sys_quiescent(sys_quiescent),.sys_platform_ready(sys_platform_ready),
        .ui_admission_block(ui_admission_block),.ui_drained(sealed_quiet),
        .ui_platform_ready(parent_initialized&&!maintenance_gate_fault&&!pcie_protocol_fault&&
                           !pcie_epoch_fault&&!owner_protocol_fault),
        .ui_clients_rst_n(frontend_epoch_rst_n),.bridge_fault(maintenance_bridge_fault)
    );
    // Runtime reset invalidates the packet/owner epoch only after the retained
    // frontend has sealed and published actual drainage. Release is local to
    // UI; the two frame gates and AXI seal use configuration-only power reset.
    wire frontend_reset_request_n=ui_power_rst_n&&c0_clients_rst_n&&endpoint_epoch_ready&&
        normal_shell_started_sync[ENABLE_STAGES-1];
    (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) logic [ENABLE_STAGES-1:0] frontend_release;
    always @(posedge c0_ui_clk or negedge frontend_reset_request_n)begin
        if(!frontend_reset_request_n)frontend_release<=0;
        else frontend_release<={frontend_release[ENABLE_STAGES-2:0],1'b1};
    end
    assign frontend_epoch_rst_n=frontend_release[ENABLE_STAGES-1];
    wire frontend_irq;
    assign pcie_irq=frontend_irq||((transport_owner===2'd2)&&irq);
    rk_pcie_jtag_maintenance_frontend frontend (
        .clk(c0_ui_clk),.power_rst_n(ui_power_rst_n),.rst_n(frontend_epoch_rst_n),
        .maintenance_block(ui_admission_block),.backend_drained(parent_drained),
        .release_ready(transport_release_ready),
        .jtag_link_healthy(jtag_link_healthy),.pcie_link_healthy(pcie_link_healthy),
        .s_axil_awaddr(pcie_axil_awaddr),.s_axil_awprot(pcie_axil_awprot),
        .s_axil_awvalid(pcie_axil_awvalid),.s_axil_awready(pcie_axil_awready),
        .s_axil_wdata(pcie_axil_wdata),.s_axil_wstrb(pcie_axil_wstrb),
        .s_axil_wvalid(pcie_axil_wvalid),.s_axil_wready(pcie_axil_wready),
        .s_axil_bresp(pcie_axil_bresp),.s_axil_bvalid(pcie_axil_bvalid),.s_axil_bready(pcie_axil_bready),
        .s_axil_araddr(pcie_axil_araddr),.s_axil_arprot(pcie_axil_arprot),
        .s_axil_arvalid(pcie_axil_arvalid),.s_axil_arready(pcie_axil_arready),
        .s_axil_rdata(pcie_axil_rdata),.s_axil_rresp(pcie_axil_rresp),
        .s_axil_rvalid(pcie_axil_rvalid),.s_axil_rready(pcie_axil_rready),
        .jtag_req_valid(req_valid),.jtag_req_ready(req_ready),.jtag_req(req),
        .jtag_rsp_valid(rsp_valid),.jtag_rsp_data(rsp_data),.jtag_rsp_status(rsp_status),.jtag_rsp_seq(rsp_seq),
        .m_req_valid(backend_req_valid),.m_req_ready(backend_req_ready),.m_req(backend_req),
        .m_rsp_valid(backend_rsp_valid),.m_rsp_data(backend_rsp_data),
        .m_rsp_status(backend_rsp_status),.m_rsp_seq(backend_rsp_seq),
        .owner(transport_owner),.lease_epoch(transport_lease_epoch),
        .pcie_irq(frontend_irq),.pcie_protocol_fault(pcie_protocol_fault),
        .pcie_epoch_fault(pcie_epoch_fault),.owner_protocol_fault(owner_protocol_fault),
        .owner_failure_code(owner_failure_code),
        .maintenance_quiet(sealed_quiet),.maintenance_fault(maintenance_gate_fault)
    );
    rk_jtag_dual_ddr_async #(
        .BASE(BASE),.BYTES(BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES),.MAX_TASKS(MAX_TASKS),
        .SYS_HOLD_CYCLES(SYS_HOLD_CYCLES),.UI_FRESH_CYCLES(UI_FRESH_CYCLES),
        .SYNC_STAGES(SYNC_STAGES),.RESET_WAIT_TIMEOUT_CYCLES(RESET_WAIT_TIMEOUT_CYCLES)
    ) backend (
        .reset_req_valid(maintenance_reset_request),.reset_req_ready(coordinator_ready),
        .req_valid(backend_req_valid),.req_ready(backend_req_ready),.req(backend_req),
        .rsp_valid(backend_rsp_valid),.rsp_data(backend_rsp_data),
        .rsp_status(backend_rsp_status),.rsp_seq(backend_rsp_seq),
        .transport_release_ready(transport_release_ready),
        .maintenance_drained(parent_drained),.maintenance_platform_ready(parent_initialized),
        .maintenance_endpoint_epoch_ready(endpoint_epoch_ready),.*
    );
endmodule
