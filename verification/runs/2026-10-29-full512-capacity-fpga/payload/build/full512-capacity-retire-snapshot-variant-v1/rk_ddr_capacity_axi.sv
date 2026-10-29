// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Diagnostic-only exclusive owner of a 512-bit MIG AXI port. No RK command API.
// This adapter must replace, never run alongside, the ordinary memory fabric.
// The platform supplies qualified controller ordering, exclusive ownership,
// calibration/initialization and an audited whole-transaction-domain reset.
// AXI B alone is not a retirement witness: each sealed pass uses the existing
// exact-final-write-address read/ECC fence. No physical capacity claim here.
module rk_ddr_capacity_axi #(
    parameter logic [30:0] BASE_ADDR = 0,
    parameter logic [31:0] SPAN_BYTES = 32'h80000000,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, joint_rst_n,
    input logic initialization_complete, calibration_complete, owner_exclusive,
    input logic monitor_healthy, monitor_fault,
    output logic fault,
    output logic [7:0] fault_code,
    output logic [31:0] accepted_aw_count, accepted_w_count, accepted_b_count,
    output logic [30:0] last_completed_write_address,

    input logic line_valid,
    output logic line_ready,
    input logic line_write,
    input logic [30:0] line_address,
    input logic [511:0] line_wdata,
    output logic line_rsp_valid,
    input logic line_rsp_ready,
    output logic line_rsp_error,
    output logic [511:0] line_rdata,
    input logic retire_valid,
    output logic retire_ready,
    input logic [30:0] retire_last_write_address,
    output logic retire_rsp_valid,
    input logic retire_rsp_ready,
    output logic retire_rsp_ok,
    output logic [31:0] retire_ecc_status, retire_ecc_onoff, retire_ecc_irq_mask,

    output logic monitor_check_valid,
    input logic monitor_check_ready,
    input logic monitor_snapshot_valid,
    output logic monitor_snapshot_ready,
    input logic [31:0] monitor_snapshot_status, monitor_snapshot_onoff, monitor_snapshot_irq_mask,

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
    output logic m_axi_rready
);
    localparam logic [32:0] END_ADDR = {2'b0,BASE_ADDR}+{1'b0,SPAN_BYTES};
    // Capacity-parent specialization: the actual strict ECC monitor publishes
    // only the validated tuple status=0/onoff=1/IRQmask=3. Keep every fence
    // validation/fault check; compress only its accepted receipt storage.
    // This source is not a replacement for an arbitrary-snapshot adapter.
    logic retire_ecc_accepted;
    assign retire_ecc_status = 32'b0;
    assign retire_ecc_onoff = {31'b0, retire_ecc_accepted};
    assign retire_ecc_irq_mask = {30'b0, {2{retire_ecc_accepted}}};
    logic service_active, write_active, read_active, retire_active;
    logic aw_pending, w_pending, ar_pending, aw_seen, w_seen;
    logic [30:0] captured_address;
    logic [511:0] captured_data;
    logic line_accept, retire_accept, aw_take, w_take, b_complete, r_complete;
    logic quiet, health_good, fault_now, invalid_request, below_base, timeout_active, progress;
    logic [7:0] current_fault;
    logic [31:0] wait_cycles;
    logic fence_pending, fence_ready, fence_result_valid, fence_result_ready;
    logic fence_done, fence_fault;
    logic [7:0] fence_fault_code;
    logic [3:0] f_arid, f_arcache, f_arqos;
    logic [30:0] f_araddr;
    logic [7:0] f_arlen;
    logic [2:0] f_arsize, f_arprot;
    logic [1:0] f_arburst;
    logic f_arlock, f_arvalid, f_rready;

    initial begin
        if ((^BASE_ADDR) === 1'bx || (^SPAN_BYTES) === 1'bx ||
            BASE_ADDR[5:0] != 0 || SPAN_BYTES < 64 || SPAN_BYTES[5:0] != 0 ||
            END_ADDR > 33'h080000000 || TIMEOUT_CYCLES == 0)
            $fatal(1,"Capacity AXI adapter needs aligned nonempty31-bit span and positive timeout");
    end
    assign health_good = initialization_complete === 1'b1 && calibration_complete === 1'b1 &&
        owner_exclusive === 1'b1 && monitor_healthy === 1'b1 && monitor_fault === 1'b0;
    assign quiet = !write_active && !read_active && !aw_pending && !w_pending && !ar_pending &&
        !aw_seen && !w_seen && !line_rsp_valid;
    // Mutual exclusion is checked before launching either accepted operation.
    assign line_ready = joint_rst_n && !fault && health_good && quiet &&
        !retire_active && !retire_rsp_valid;
    assign retire_ready = line_ready;
    assign line_accept = line_valid && line_ready;
    assign retire_accept = retire_valid && retire_ready;
    if (BASE_ADDR==0) begin: zero_base
        assign below_base=0;
    end else begin: nonzero_base
        assign below_base={2'b0,line_address} < {2'b0,BASE_ADDR};
    end
    assign invalid_request = line_accept && ((^line_address) === 1'bx ||
        line_address[5:0] !== 0 || below_base ||
        ({2'b0,line_address}+33'd64) > END_ADDR ||
        (line_write !== 1'b0 && line_write !== 1'b1) ||
        (line_write && (^line_wdata) === 1'bx));

    assign m_axi_awid=0; assign m_axi_awaddr=captured_address;
    assign m_axi_awlen=0; assign m_axi_awsize=6; assign m_axi_awburst=1;
    assign m_axi_awlock=0; assign m_axi_awcache=0; assign m_axi_awprot=0; assign m_axi_awqos=0;
    assign m_axi_awvalid=joint_rst_n && aw_pending;
    assign m_axi_wdata=captured_data; assign m_axi_wstrb='1;
    assign m_axi_wlast=1; assign m_axi_wvalid=joint_rst_n && w_pending;
    assign m_axi_bready=joint_rst_n && ((write_active && !aw_pending && !w_pending) || fault);
    assign aw_take=m_axi_awvalid && m_axi_awready;
    assign w_take=m_axi_wvalid && m_axi_wready;
    assign b_complete=m_axi_bvalid && m_axi_bready && write_active && !aw_pending && !w_pending;

    assign m_axi_arid=retire_active ? f_arid : 4'b0;
    assign m_axi_araddr=retire_active ? f_araddr : captured_address;
    assign m_axi_arlen=retire_active ? f_arlen : 8'b0;
    assign m_axi_arsize=retire_active ? f_arsize : 3'd6;
    assign m_axi_arburst=retire_active ? f_arburst : 2'b01;
    assign m_axi_arlock=retire_active && f_arlock;
    assign m_axi_arcache=retire_active ? f_arcache : 4'b0;
    assign m_axi_arprot=retire_active ? f_arprot : 3'b0;
    assign m_axi_arqos=retire_active ? f_arqos : 4'b0;
    assign m_axi_arvalid=joint_rst_n && (retire_active ? f_arvalid : ar_pending);
    assign m_axi_rready=joint_rst_n && (fault ||
        (retire_active ? f_rready : (read_active && !ar_pending)));
    assign r_complete=m_axi_rvalid && m_axi_rready && read_active && !ar_pending;

    assign fence_result_ready=joint_rst_n && retire_active && !retire_rsp_valid;
    rk_mig_write_fence #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) fence (
        .clk(clk),.joint_rst_n(joint_rst_n),.fence_valid(fence_pending),.fence_ready(fence_ready),
        .final_write_address({1'b0,last_completed_write_address}),
        .epoch_has_write(accepted_b_count != 0),.epoch_sealed(retire_active),
        .writes_complete(quiet && accepted_aw_count==accepted_w_count && accepted_aw_count==accepted_b_count),
        .upstream_quiescent(quiet),.owner_exclusive(owner_exclusive),
        .calib_complete(calibration_complete),.monitor_healthy(monitor_healthy),.monitor_fault(monitor_fault),
        .fence_result_valid(fence_result_valid),.fence_result_ready(fence_result_ready),
        .fence_done(fence_done),.fault(fence_fault),.fault_code(fence_fault_code),
        .m_axi_arid(f_arid),.m_axi_araddr(f_araddr),.m_axi_arlen(f_arlen),.m_axi_arsize(f_arsize),
        .m_axi_arburst(f_arburst),.m_axi_arlock(f_arlock),.m_axi_arcache(f_arcache),
        .m_axi_arprot(f_arprot),.m_axi_arqos(f_arqos),.m_axi_arvalid(f_arvalid),
        .m_axi_arready(m_axi_arready && retire_active),.m_axi_rid(m_axi_rid),
        .m_axi_rresp(m_axi_rresp),.m_axi_rlast(m_axi_rlast),
        .m_axi_rvalid(m_axi_rvalid && retire_active),.m_axi_rready(f_rready),
        .monitor_check_valid(monitor_check_valid),.monitor_check_ready(monitor_check_ready),
        .monitor_snapshot_valid(monitor_snapshot_valid),.monitor_snapshot_ready(monitor_snapshot_ready),
        .monitor_snapshot_status(monitor_snapshot_status),.monitor_snapshot_onoff(monitor_snapshot_onoff),
        .monitor_snapshot_irq_mask(monitor_snapshot_irq_mask)
    );
    assign timeout_active=write_active || read_active || fence_pending;
    assign progress=aw_take || w_take || b_complete || (m_axi_arvalid && m_axi_arready) ||
        r_complete || (fence_pending && fence_ready);
    always_comb begin
        current_fault=0;
        if ((service_active || line_accept || retire_accept) && !health_good) current_fault=1;
        else if (line_accept && retire_accept) current_fault=2;
        else if (invalid_request) current_fault=1;
        else if (retire_accept && (accepted_b_count==0 ||
            accepted_aw_count!=accepted_b_count || accepted_w_count!=accepted_b_count ||
            retire_last_write_address !== last_completed_write_address)) current_fault=4;
        else if (m_axi_bvalid !== 1'b0 && (m_axi_bvalid !== 1'b1 || !write_active ||
            aw_pending || w_pending || !aw_seen || !w_seen)) current_fault=2;
        else if (b_complete && (m_axi_bid !== 0 || m_axi_bresp !== 0)) current_fault=3;
        else if (!retire_active && m_axi_rvalid !== 1'b0 &&
            (m_axi_rvalid !== 1'b1 || !read_active || ar_pending)) current_fault=2;
        else if (r_complete && (m_axi_rid !== 0 || m_axi_rresp !== 0 ||
            m_axi_rlast !== 1'b1 || (^m_axi_rdata) === 1'bx)) current_fault=3;
        else if (!retire_active && monitor_snapshot_valid !== 1'b0) current_fault=4;
        else if (fence_fault) current_fault=fence_fault_code==6 ? 8'd5 : 8'd4;
        else if ((aw_take && accepted_aw_count==32'hffffffff) ||
            (w_take && accepted_w_count==32'hffffffff) ||
            (b_complete && accepted_b_count==32'hffffffff)) current_fault=2;
        else if (timeout_active && !progress && wait_cycles>=TIMEOUT_CYCLES-1) current_fault=5;
        fault_now=current_fault!=0;
    end
    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            service_active<=0; write_active<=0; read_active<=0; retire_active<=0;
            aw_pending<=0; w_pending<=0; ar_pending<=0; aw_seen<=0; w_seen<=0;
            captured_address<=0; captured_data<=0; wait_cycles<=0; fence_pending<=0;
            accepted_aw_count<=0; accepted_w_count<=0; accepted_b_count<=0;
            last_completed_write_address<=0; fault<=0; fault_code<=0;
            line_rsp_valid<=0; line_rsp_error<=0; line_rdata<=0;
            retire_rsp_valid<=0; retire_rsp_ok<=0;
            retire_ecc_accepted<=0;
        end else begin
            // All handshakes still drain in quarantine; no pending VALID is withdrawn.
            if (aw_take) begin aw_pending<=0; aw_seen<=1; accepted_aw_count<=accepted_aw_count+1'b1; end
            if (w_take) begin w_pending<=0; w_seen<=1; accepted_w_count<=accepted_w_count+1'b1; end
            if (m_axi_arvalid && m_axi_arready && !retire_active) ar_pending<=0;
            if (b_complete) begin write_active<=0; aw_seen<=0; w_seen<=0; end
            if (r_complete && m_axi_rlast === 1'b1) read_active<=0;
            if (fence_pending && fence_ready) fence_pending<=0;
            if (line_rsp_valid && line_rsp_ready) line_rsp_valid<=0;
            if (retire_rsp_valid && retire_rsp_ready) begin retire_rsp_valid<=0; retire_active<=0; end
            if (progress || !timeout_active) wait_cycles<=0;
            else if (wait_cycles<TIMEOUT_CYCLES) wait_cycles<=wait_cycles+1'b1;
            if (!fault && fault_now) begin fault<=1; fault_code<=current_fault; end
            if (!fault && !fault_now) begin
                if (line_accept) begin
                    service_active<=1; captured_address<=line_address; captured_data<=line_wdata;
                    if (line_write) begin write_active<=1; aw_pending<=1; w_pending<=1; end
                    else begin read_active<=1; ar_pending<=1; end
                end
                if (b_complete) begin
                    accepted_b_count<=accepted_b_count+1'b1;
                    last_completed_write_address<=captured_address;
                    line_rsp_valid<=1; line_rsp_error<=0; line_rdata<=0;
                end
                if (r_complete) begin line_rsp_valid<=1; line_rsp_error<=0; line_rdata<=m_axi_rdata; end
                if (retire_accept) begin service_active<=1; retire_active<=1; fence_pending<=1; end
                if (monitor_snapshot_valid && monitor_snapshot_ready &&
                    monitor_snapshot_status === 32'b0 && monitor_snapshot_onoff === 32'h1 &&
                    monitor_snapshot_irq_mask === 32'h3) retire_ecc_accepted<=1;
                if (fence_done && fence_result_valid) begin retire_rsp_valid<=1; retire_rsp_ok<=1; end
            end
        end
    end
endmodule
