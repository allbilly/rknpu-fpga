// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Joined raw-command EW endpoint for the separately qualified C0 source variant.
// Frames, AXI memory and ECC control are all in c0_ui_clk. This is NOT a BSCAN,
// TCK CDC, PCIe or physical-board shell. SYS reset owns both MIG UI domains.
// Transport identity RKED distinguishes this candidate from legacy RKEW.
// No command words, numerical data or layouts are repaired by this composite.
module rk_jtag_ew_ddr #(
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
    localparam integer STAGES = SYNC_STAGES < 2 ? 2 : SYNC_STAGES;
    wire clk = c0_ui_clk;
    wire rst_n = c0_clients_rst_n;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] sequence_sync;
    wire sequence_ready_ui0 = sequence_sync[STAGES-1] === 1'b1;
    wire monitor_calib = sequence_ready_ui0 && c0_init_calib_complete === 1'b1;
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
    logic [31:0] core_start_address, core_start_amount, core_completed_tasks;
    logic [7:0] core_error_code;
    logic dma_start_valid, dma_start_ready, dma_busy, dma_done, dma_error, unused_task_done;
    logic [31:0] dma_completed_tasks;
    logic [7:0] dma_error_code;
    logic engine_req_valid, engine_req_ready, engine_req_write, engine_rsp_valid, engine_rsp_ready, engine_rsp_error;
    logic [31:0] engine_req_addr;
    logic [15:0] engine_req_wdata, engine_rsp_rdata;
    logic host_valid, host_ready, host_write, host_rsp_valid, host_rsp_ready, host_error;
    logic [31:0] host_addr;
    logic [15:0] host_wdata, host_rdata;
    logic backend_fault, backend_memory_busy, memory_available;
    logic backend_req_ready;
    logic fabric_fault, fabric_memory_ready;
    logic [7:0] fabric_fault_code;
    logic job_begin, job_begin_ready, job_seal, job_abort, job_release;
    logic epoch_started, epoch_retired, irq_previous;
    logic first_fault_valid, monitor_cause_pending;
    logic [7:0] first_fault_code, known_cause_code;
    logic known_cause, reserve_monitor_cause;
    logic [31:0] read_address;
    logic read_fault;
    logic [7:0] read_fault_code;
    wire monitor_early_fault = monitor_seen && monitor_healthy !== 1'b1 && monitor_fault === 1'b0;
    wire fabric_cause_pending = fabric_fault === 1'b1 && fabric_fault_code === 8'b0;
    wire sequence_lost = sequence_seen && (!sequence_ready_ui0 || c0_ui_clk_sync_rst !== 1'b0);
    wire external_block = first_fault_valid || monitor_cause_pending || dma_error !== 1'b0 ||
        monitor_fault !== 1'b0 || monitor_early_fault || backend_fault !== 1'b0 || sequence_lost;
    wire live_block = external_block || fabric_fault !== 1'b0;
    wire control_start_accept = core_start_valid && core_start_ready;
    wire dma_start_accept = dma_start_valid && dma_start_ready;
    // No client starts before the synchronized reset barrier. Once enabled,
    // register diagnostics remain accessible after a later health fault.
    wire backend_enabled = sequence_seen || sequence_ready_ui0;
    assign req_ready = backend_enabled && backend_req_ready;

    initial begin
        if (BYTES < 33'd64 || (BYTES & (BYTES-33'd1)) != 0 || BASE[5:0] != 0 ||
            ({1'b0,BASE}+BYTES) > 33'h080000000 || TIMEOUT_CYCLES == 0)
            $fatal(1,"DDR endpoint needs an aligned power-of-two C0 window and positive timeout");
    end

    rk_mig_reset_coordinator #(.SYS_HOLD_CYCLES(SYS_HOLD_CYCLES),.UI_FRESH_CYCLES(UI_FRESH_CYCLES),
        .SYNC_STAGES(SYNC_STAGES),.WAIT_TIMEOUT_CYCLES(RESET_WAIT_TIMEOUT_CYCLES)) reset_owner (.*);
    // The reset coordinator supplies fresh UI clocks with this reset held low
    // before release, as required by the unchanged synchronous-reset clients.
    always_ff @(posedge clk) begin
        if (!rst_n) sequence_sync <= 0;
        else sequence_sync <= {sequence_sync[STAGES-2:0],sequence_complete};
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
            else known_cause_code = fabric_fault === 1'b1 && fabric_fault_code === 8'd8 ? 8'd8 : 8'd5;
        end else if (dma_error !== 1'b0) begin
            known_cause = 1; known_cause_code = dma_error_code;
        end else if (monitor_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = monitor_fault_code === 8'd3 ? 8'd8 : 8'd5;
        end else if (monitor_early_fault || fabric_cause_pending) begin
            reserve_monitor_cause = 1;
        end else if (backend_fault !== 1'b0) begin
            // The backend is an abort source for the fabric. Preserve its
            // original timeout before the fabric's derived generic abort E5.
            known_cause = 1; known_cause_code = rsp_status === 8'h80 ? 8'd8 : 8'd5;
        end else if (fabric_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = fabric_fault_code === 8'd8 ? 8'd8 : 8'd5;
        end else if (sequence_lost) begin
            known_cause = 1; known_cause_code = 8'd5;
        end
    end
    assign fault = rst_n && live_block;
    assign fault_code = !rst_n ? 8'b0 : first_fault_valid ? first_fault_code : known_cause ? known_cause_code : 8'b0;
    assign core_error = first_fault_valid || known_cause;
    assign core_error_code = first_fault_valid ? first_fault_code : known_cause_code;
    assign core_busy = dma_busy || job_active || (live_block && !core_error);
    assign core_done = epoch_started && job_retired && !live_block;
    assign core_completed_tasks = epoch_started ? dma_completed_tasks : 32'b0;
    assign memory_ready = fabric_memory_ready && sequence_ready_ui0 && !live_block;

    // A faulted queued descriptor is acknowledged to the logical controller,
    // without starting DMA/fabric work. This releases its launch_pending state.
    assign core_start_ready = live_block || (dma_start_ready && job_begin_ready);
    assign dma_start_valid = core_start_valid && job_begin_ready && !external_block;
    assign job_begin = core_start_valid && dma_start_ready && !external_block;
    assign job_seal = dma_done && !external_block;
    // Do not feed the fabric's own combinational fault back into its abort.
    assign job_abort = external_block;
    assign job_release = rst_n && irq_previous && !irq;
    // Packet admission is distinct from fabric memory_ready (which excludes
    // this backend's already-active host session to block mid-packet SUBMIT).
    assign memory_available = init_complete && sequence_ready_ui0 && !live_block &&
        monitor_healthy === 1'b1 && c0_init_calib_complete === 1'b1 &&
        !core_start_valid && !dma_busy && !job_active &&
        (!job_owned || (irq && epoch_retired && req[555:548] === 8'd3));

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
            if (s_axil_arvalid && s_axil_arready) begin
                read_address <= s_axil_araddr; read_fault <= live_block; read_fault_code <= fault_code;
            end
        end
    end
    // Preserve the controller's AR-time snapshot, including under backpressure.
    // An old successful result becomes logically failed on a NEW read after a
    // platform fault. Pending classification reports error with code0 in RKED.
    always_comb begin
        s_axil_rdata = control_rdata;
        if (s_axil_rresp == 2'b00) begin
            case (read_address)
                32'h00: s_axil_rdata = 32'h524b4544; // RKED, ABI1.0 at unchanged0x04.
                32'h08: if (read_fault) begin
                    s_axil_rdata[0] = 0; s_axil_rdata[4] = 0; s_axil_rdata[5] = 1;
                    if (control_rdata[2]) s_axil_rdata[3] = 1;
                end
                32'h24: if (read_fault) s_axil_rdata = {24'b0,read_fault_code};
                default: begin end
            endcase
        end
    end

    rk_jtag_backend #(.BASE(BASE),.BYTES(BYTES[31:0]),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) backend (
        .req_valid(req_valid && backend_enabled),.req_ready(backend_req_ready),
        .fault(backend_fault),.memory_busy(backend_memory_busy),.*
    );
    rk_job_control control (.s_axil_rdata(control_rdata),.*);
    rk_ew_dma #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES),.MAX_TASKS(MAX_TASKS)) engine (
        .clk,.rst_n,.start_valid(dma_start_valid),.start_ready(dma_start_ready),
        .start_address(core_start_address),.start_amount(core_start_amount),
        .busy(dma_busy),.done(dma_done),.task_done(unused_task_done),.error(dma_error),
        .error_code(dma_error_code),.completed_tasks(dma_completed_tasks),
        .mem_req_valid(engine_req_valid),.mem_req_ready(engine_req_ready),.mem_req_write(engine_req_write),
        .mem_req_addr(engine_req_addr),.mem_req_wdata(engine_req_wdata),.mem_rsp_valid(engine_rsp_valid),
        .mem_rsp_ready(engine_rsp_ready),.mem_rsp_rdata(engine_rsp_rdata),.mem_rsp_error(engine_rsp_error)
    );
    rk_mig_ecc_monitor #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) monitor (
        .clk,.joint_rst_n(rst_n),.calib_complete(monitor_calib),.mig_interrupt(c0_interrupt),
        .check_valid(monitor_check_valid),.check_ready(monitor_check_ready),
        .snapshot_valid(monitor_snapshot_valid),.snapshot_ready(monitor_snapshot_ready),
        .snapshot_status(monitor_snapshot_status),.snapshot_onoff(monitor_snapshot_onoff),
        .snapshot_irq_mask(monitor_snapshot_irq_mask),.monitor_healthy,
        .fault(monitor_fault),.fault_code(monitor_fault_code),.*
    );
    rk_ddr_memory_fabric #(.BASE(BASE),.BYTES(BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) memory (
        .clk,.joint_rst_n(rst_n),.sequence_ready(sequence_ready_ui0),.calib_complete(c0_init_calib_complete),
        .host_session_busy(backend_memory_busy),.memory_ready(fabric_memory_ready),
        .fault(fabric_fault),.fault_code(fabric_fault_code),.*
    );
endmodule
