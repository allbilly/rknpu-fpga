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
    logic capacity_selected, capacity_busy, unused_capacity_done;
    logic capacity_session_seen, capacity_fault_active;
    logic fabric_diagnostic_quiet;
    localparam integer STAGES = SYNC_STAGES < 3 ? 3 : SYNC_STAGES;
    wire clk = c0_ui_clk;
    wire rst_n = c0_clients_rst_n;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] sequence_sync;
    logic sequence_complete_registered;
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
    wire [1:0] core_start_kind;
    wire ew_dma_start_ready,cmac_dma_start_ready,layout_dma_start_ready;
    wire control_scheduler_fault,control_owned,control_quiet;
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

    wire compute_reset_request,compute_reset_request_ready,compute_reset_result,compute_reset_error,compute_reset_ack;
    wire compute_reset_blocked,unused_compute_core_blocked,compute_ui_rst_n,compute_core_rst_n;
    logic compute_admission_hold;
    wire [7:0] compute_reset_code;
    wire [31:0] compute_reset_epoch;
    wire engine_ui_quiet,engine_core_quiet,engine_core_ready,engine_ui_ready;
    wire reset_healthy=sequence_ready_ui0&&init_complete&&!live_block&&monitor_healthy===1'b1&&
        c0_init_calib_complete===1'b1&&capacity_normal_selected&&!capacity_selected&&!capacity_busy;
    wire reset_quiet=control_quiet&&fabric_diagnostic_quiet&&engine_ui_quiet&&
        !core_start_valid&&!dma_inflight&&!async_result_valid&&!engine_req_valid&&!engine_rsp_valid&&
        !host_valid&&!host_rsp_valid&&!backend_memory_busy&&!job_owned&&!job_active&&!epoch_started&&!irq&&
        capacity_normal_admission&&!capacity_selected&&!capacity_busy&&
        !m_axi_awvalid&&!m_axi_wvalid&&!m_axi_bvalid&&!m_axi_arvalid&&!m_axi_rvalid&&
        !m_axi_ctrl_awvalid&&!m_axi_ctrl_wvalid&&!m_axi_ctrl_bvalid&&!m_axi_ctrl_arvalid&&!m_axi_ctrl_rvalid;
    logic health_published,core_ready_published;
    // Registered ownership avoids feeding live fabric health back through
    // admission/READY into its own protocol checker. Release only after the
    // sequencer's post-ACK core-idle handshake has completed.
    always_ff @(posedge clk)begin
        if(!rst_n)compute_admission_hold<=0;
        else if(compute_reset_request&&compute_reset_request_ready)compute_admission_hold<=1;
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
        .ui_restart_ready(engine_ui_ready&&ui_core_ready_sync[STAGES-1]),
        .request_valid(compute_reset_request),.request_ready(compute_reset_request_ready),
        .admission_blocked(compute_reset_blocked),.result_valid(compute_reset_result),.result_error(compute_reset_error),
        .error_code(compute_reset_code),.result_ready(compute_reset_ack),.reset_epoch(compute_reset_epoch),
        .ui_compute_rst_n(compute_ui_rst_n),.core_clk(sys_clk),.core_rst_n(sys_engine_rst_n),
        .core_healthy(core_health_sync[STAGES-1]),.core_quiet(engine_core_quiet),
        .core_admission_blocked(unused_compute_core_blocked),.core_compute_rst_n(compute_core_rst_n)
    );

    logic [31:0] read_address;
    logic read_fault;
    logic [7:0] read_fault_code;
    wire monitor_early_fault = monitor_seen && monitor_healthy !== 1'b1 && monitor_fault === 1'b0;
    wire fabric_cause_pending = fabric_fault === 1'b1 && fabric_fault_code === 8'b0;
    wire sequence_lost = sequence_seen && (!sequence_ready_ui0 || c0_ui_clk_sync_rst !== 1'b0);
    wire external_block = first_fault_valid || monitor_cause_pending || dma_error !== 1'b0 ||
        monitor_fault !== 1'b0 || monitor_early_fault || engine_crossing_fault !== 1'b0 ||
        backend_fault !== 1'b0 || control_scheduler_fault !== 1'b0 || sequence_lost || capacity_fault_active !== 1'b0 || compute_reset_error !== 1'b0;
    wire live_block = external_block || fabric_fault !== 1'b0;
    wire control_start_accept = core_start_valid && core_start_ready;
    wire dma_start_accept = dma_start_valid && dma_start_ready;
    // No client starts before the synchronized reset barrier. Once enabled,
    // register diagnostics remain accessible after a later health fault.
    wire backend_enabled = sequence_seen || sequence_ready_ui0;
    assign req_ready = backend_enabled && backend_req_ready;

    initial begin
        if (SYNC_STAGES < 3) $fatal(1,"Async DDR endpoint requires at least three CDC stages");
        if (BYTES < 33'd64 || (BYTES & (BYTES-33'd1)) != 0 || BASE[5:0] != 0 ||
            ({1'b0,BASE}+BYTES) > 33'h080000000 || TIMEOUT_CYCLES == 0)
            $fatal(1,"DDR endpoint needs an aligned power-of-two C0 window and positive timeout");
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
            else known_cause_code = fabric_fault === 1'b1 && fabric_fault_code === 8'd8 ? 8'd8 : 8'd5;
        end else if (dma_error !== 1'b0) begin
            known_cause = 1; known_cause_code = dma_error_code;
        end else if (monitor_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = monitor_fault_code === 8'd3 ? 8'd8 : 8'd5;
        end else if (monitor_early_fault || fabric_cause_pending) begin
            reserve_monitor_cause = 1;
        end else if (engine_crossing_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = 8'd5;
        end else if (control_scheduler_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = 8'd6;
        end else if (backend_fault !== 1'b0) begin
            // The backend is an abort source for the fabric. Preserve its
            // original timeout before the fabric's derived generic abort E5.
            known_cause = 1; known_cause_code = rsp_status === 8'h80 ? 8'd8 : 8'd5;
        end else if (capacity_fault_active !== 1'b0) begin
            known_cause = 1; known_cause_code = 8'd5;
        end else if (compute_reset_error !== 1'b0) begin
            known_cause = 1; known_cause_code = compute_reset_code;
        end else if (fabric_fault !== 1'b0) begin
            known_cause = 1; known_cause_code = fabric_fault_code === 8'd8 ? 8'd8 : 8'd5;
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
    assign memory_ready = fabric_memory_ready && sequence_ready_ui0 && !live_block && capacity_normal_admission && !compute_admission_hold;

    // A faulted queued descriptor is acknowledged to the logical controller,
    // without starting DMA/fabric work. This releases its launch_pending state.
    assign core_start_ready = live_block || (!compute_admission_hold && capacity_normal_admission && dma_start_ready && job_begin_ready);
    assign dma_start_valid = core_start_valid && job_begin_ready && !external_block && capacity_normal_admission && !compute_admission_hold;
    assign job_begin = core_start_valid && dma_start_ready && !external_block && capacity_normal_admission && !compute_admission_hold;
    assign job_seal = dma_done && !external_block;
    // Do not feed the fabric's own combinational fault back into its abort.
    assign job_abort = external_block;
    assign job_release = rst_n && irq_previous && !irq;
    // Packet admission is distinct from fabric memory_ready (which excludes
    // this backend's already-active host session to block mid-packet SUBMIT).
    assign memory_available = init_complete && sequence_ready_ui0 && !live_block && !compute_admission_hold && capacity_normal_selected &&
        (capacity_normal_admission || ((job_owned || control_owned) && irq && epoch_retired && req[555:548] === 8'd3)) &&
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
        .fault(backend_fault),.memory_busy(backend_memory_busy),.*
    );
    rk_layout_job_control control (
        .core_write_block(live_block || dma_busy || job_active || compute_admission_hold),
        .s_axil_rdata(control_rdata),.scheduler_fault(control_scheduler_fault),
        .control_owned,.control_owner_kind,.core_start_kind,.control_quiet(control_quiet),
        .core_ew_start_ready(live_block || (!compute_admission_hold && capacity_normal_admission && ew_dma_start_ready && job_begin_ready)),
        .core_cmac_start_ready(live_block || (!compute_admission_hold && capacity_normal_admission && cmac_dma_start_ready && job_begin_ready)),
        .core_layout_start_ready(live_block || (!compute_admission_hold && capacity_normal_admission && layout_dma_start_ready && job_begin_ready)),
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
        // The fabric rejects new jobs/memory and success on its own immediate
        // fault. Do not feed that combinational fault through the child READY
        // and job_begin back into the fabric's protocol checker. Its cause is
        // captured by first_fault_valid on the next UI edge, revoking this
        // numerical-child permit through the registered cross-clock path.
        .ui_rearm_permit(sequence_ready_ui0 && init_complete && !external_block &&
                         monitor_healthy === 1'b1 && c0_init_calib_complete === 1'b1),
        .ui_clk(clk),.ui_rst_n(compute_ui_rst_n),.ui_admission_enable(!external_block && sequence_ready_ui0 && !compute_admission_hold),
        .ui_quiet(engine_ui_quiet),.core_quiet(engine_core_quiet),.core_restart_ready(engine_core_ready),.ui_restart_ready(engine_ui_ready),
        .ui_start_valid(dma_start_valid),.ui_start_ready(dma_start_ready),
        .ui_start_address(core_start_address),.ui_start_amount(core_start_amount),
        .ui_result_valid(async_result_valid),.ui_result_error(async_result_error),
        .ui_result_code(async_result_code),.ui_result_tasks(async_result_tasks),.ui_result_ready(1'b1),
        .ui_fault(engine_crossing_fault),.core_clk(sys_clk),.core_rst_n(compute_core_rst_n),
        .ui_mem_req_valid(engine_req_valid),.ui_mem_req_ready(engine_req_ready),.ui_mem_req_write(engine_req_write),
        .ui_mem_req_addr(engine_req_addr),.ui_mem_req_wdata(engine_req_wdata),.ui_mem_rsp_valid(engine_rsp_valid),
        .ui_mem_rsp_ready(engine_rsp_ready),.ui_mem_rsp_rdata(engine_rsp_rdata),.ui_mem_rsp_error(engine_rsp_error)
    );
    rk_mig_ecc_monitor #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) monitor (
        .clk,.joint_rst_n(rst_n),.calib_complete(monitor_calib),.mig_interrupt(c0_interrupt),
        .check_valid(monitor_check_valid),.check_ready(monitor_check_ready),
        .snapshot_valid(monitor_snapshot_valid),.snapshot_ready(monitor_snapshot_ready),
        .snapshot_status(monitor_snapshot_status),.snapshot_onoff(monitor_snapshot_onoff),
        .snapshot_irq_mask(monitor_snapshot_irq_mask),.monitor_healthy,
        .fault(monitor_fault),.fault_code(monitor_fault_code),
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
        .m_axi_ctrl_rready(n_ctrl_rready),.*
    );
    rk_ddr_memory_fabric_snapshot_capacity #(.BASE(BASE),.BYTES(BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) memory (
        .clk,.joint_rst_n(rst_n),.sequence_ready(sequence_ready_ui0),.calib_complete(c0_init_calib_complete),
        .host_session_busy(backend_memory_busy),.memory_ready(fabric_memory_ready),
        // The accepted packet is identified by latched backend state/sequence.
        // memory_available is admission-only and may inspect the next req.
        .host_read_scope(backend_memory_busy&&!host_write&&!live_block),.host_read_epoch(rsp_seq),
        .fault(fabric_fault),.fault_code(fabric_fault_code),.diagnostic_quiescent(fabric_diagnostic_quiet),
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
        .s_axil_awaddr(s_axil_awaddr),.m_axil_awaddr(reset_routes_awaddr),
        .s_axil_awprot(s_axil_awprot),.m_axil_awprot(reset_routes_awprot),
        .s_axil_awvalid(s_axil_awvalid),.m_axil_awvalid(reset_routes_awvalid),
        .s_axil_awready(s_axil_awready),.m_axil_awready(reset_routes_awready),
        .s_axil_wdata(s_axil_wdata),.m_axil_wdata(reset_routes_wdata),
        .s_axil_wstrb(s_axil_wstrb),.m_axil_wstrb(reset_routes_wstrb),
        .s_axil_wvalid(s_axil_wvalid),.m_axil_wvalid(reset_routes_wvalid),
        .s_axil_wready(s_axil_wready),.m_axil_wready(reset_routes_wready),
        .s_axil_bresp(s_axil_bresp),.m_axil_bresp(reset_routes_bresp),
        .s_axil_bvalid(s_axil_bvalid),.m_axil_bvalid(reset_routes_bvalid),
        .s_axil_bready(s_axil_bready),.m_axil_bready(reset_routes_bready),
        .s_axil_araddr(s_axil_araddr),.m_axil_araddr(reset_routes_araddr),
        .s_axil_arprot(s_axil_arprot),.m_axil_arprot(reset_routes_arprot),
        .s_axil_arvalid(s_axil_arvalid),.m_axil_arvalid(reset_routes_arvalid),
        .s_axil_arready(s_axil_arready),.m_axil_arready(reset_routes_arready),
        .s_axil_rdata(s_axil_rdata),.m_axil_rdata(reset_routes_rdata),
        .s_axil_rresp(s_axil_rresp),.m_axil_rresp(reset_routes_rresp),
        .s_axil_rvalid(s_axil_rvalid),.m_axil_rvalid(reset_routes_rvalid),
        .s_axil_rready(s_axil_rready),.m_axil_rready(reset_routes_rready)
    );
    rk_compute_reset_regs reset_registers (
        .clk,.rst_n,.healthy(reset_healthy),.quiescent(reset_quiet),.reset_blocked(compute_reset_blocked||compute_admission_hold),
        .reset_request_valid(compute_reset_request),.reset_request_ready(compute_reset_request_ready),
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
        .normal_monitor_fault(monitor_fault),
        .normal_fabric_quiet(fabric_diagnostic_quiet),
        .normal_job_owned(control_owned || job_owned || epoch_started || irq || compute_admission_hold),
        .normal_host_busy(backend_memory_busy),
        .normal_engine_pending(core_start_valid || dma_inflight || engine_req_valid || async_result_valid),
        .normal_pending_response(host_rsp_valid || engine_rsp_valid || normal_axil_bvalid || normal_axil_rvalid),
        .normal_admission_enable(capacity_normal_admission),
        .normal_selected(capacity_normal_selected),
        .diagnostic_selected(capacity_selected),
        .owner_busy(capacity_busy),
        .owner_done(unused_capacity_done),
        .owner_fault(capacity_owner_fault),
        .n_axi_awid(n_axi_awid),
        .n_axi_awaddr(n_axi_awaddr),
        .n_axi_awlen(n_axi_awlen),
        .n_axi_awsize(n_axi_awsize),
        .n_axi_awburst(n_axi_awburst),
        .n_axi_awlock(n_axi_awlock),
        .n_axi_awcache(n_axi_awcache),
        .n_axi_awprot(n_axi_awprot),
        .n_axi_awqos(n_axi_awqos),
        .n_axi_awvalid(n_axi_awvalid),
        .n_axi_awready(n_axi_awready),
        .n_axi_arid(n_axi_arid),
        .n_axi_araddr(n_axi_araddr),
        .n_axi_arlen(n_axi_arlen),
        .n_axi_arsize(n_axi_arsize),
        .n_axi_arburst(n_axi_arburst),
        .n_axi_arlock(n_axi_arlock),
        .n_axi_arcache(n_axi_arcache),
        .n_axi_arprot(n_axi_arprot),
        .n_axi_arqos(n_axi_arqos),
        .n_axi_arvalid(n_axi_arvalid),
        .n_axi_arready(n_axi_arready),
        .n_axi_wdata(n_axi_wdata),
        .n_axi_wstrb(n_axi_wstrb),
        .n_axi_wlast(n_axi_wlast),
        .n_axi_wvalid(n_axi_wvalid),
        .n_axi_wready(n_axi_wready),
        .n_axi_bid(n_axi_bid),
        .n_axi_bresp(n_axi_bresp),
        .n_axi_bvalid(n_axi_bvalid),
        .n_axi_bready(n_axi_bready),
        .n_axi_rid(n_axi_rid),
        .n_axi_rdata(n_axi_rdata),
        .n_axi_rresp(n_axi_rresp),
        .n_axi_rlast(n_axi_rlast),
        .n_axi_rvalid(n_axi_rvalid),
        .n_axi_rready(n_axi_rready),
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

endmodule
