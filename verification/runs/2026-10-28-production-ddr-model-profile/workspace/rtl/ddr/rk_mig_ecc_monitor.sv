// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exclusive owner of the source-bound MIG channel-0 ECC AXI-Lite control port.
// This monitors configuration/status only: it proves neither memory retirement
// nor initialized allocations, and monitor_healthy is NOT job admission.
// joint_rst_n requires the platform's audited whole-transaction-domain reset;
// calibration loss and c0_aresetn alone do not establish that contract.
module rk_mig_ecc_monitor #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, joint_rst_n, calib_complete, mig_interrupt,
    input logic check_valid,
    output logic check_ready,
    output logic snapshot_valid,
    input logic snapshot_ready,
    output logic [31:0] snapshot_status, snapshot_onoff, snapshot_irq_mask,
    output logic monitor_healthy, fault,
    output logic [7:0] fault_code,
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
    typedef enum logic [2:0] {WAIT_CALIB, WRITE_MASK, READ_MASK, READ_ONOFF,
                              READ_STATUS, READY, RESULT, QUARANTINE} state_t;
    typedef enum logic [1:0] {NONE, WRITE, READ} transaction_t;
    state_t state;
    transaction_t transaction;
    logic aw_pending, w_pending, ar_pending, service_active, healthy;
    logic checking;
    logic [31:0] cycles, captured_mask, captured_onoff;
    logic b_complete, r_complete, fault_now;
    logic [7:0] current_fault_code;

    initial begin
        if (TIMEOUT_CYCLES == 0) $fatal(1, "ECC monitor timeout must be positive");
    end

    assign m_axi_ctrl_awaddr = 32'h4;
    assign m_axi_ctrl_wdata = 32'h3;
    // Faults never withdraw transactions. Only the platform joint reset can.
    assign m_axi_ctrl_awvalid = joint_rst_n && aw_pending;
    assign m_axi_ctrl_wvalid = joint_rst_n && w_pending;
    assign m_axi_ctrl_arvalid = joint_rst_n && ar_pending;
    assign m_axi_ctrl_bready = joint_rst_n && (transaction == WRITE || fault);
    // The archived control slave reads live register data: consume immediately.
    assign m_axi_ctrl_rready = joint_rst_n && (transaction == READ || fault);
    assign b_complete = m_axi_ctrl_bvalid && m_axi_ctrl_bready &&
                        transaction == WRITE && !aw_pending && !w_pending;
    assign r_complete = m_axi_ctrl_rvalid && m_axi_ctrl_rready &&
                        transaction == READ && !ar_pending;
    assign monitor_healthy = joint_rst_n && healthy && !fault && !fault_now;
    assign check_ready = monitor_healthy && state == READY && !snapshot_valid;

    always_comb begin
        current_fault_code = 0;
        // In four-state simulation an unresolved IRQ is not evidence of health.
        // This rejection does not model or detect physical metastability.
        if (mig_interrupt !== 1'b0) current_fault_code = 8'd1;
        else if (service_active && calib_complete !== 1'b1) current_fault_code = 8'd2;
        else if ((m_axi_ctrl_bvalid && (transaction != WRITE || aw_pending || w_pending)) ||
                 (m_axi_ctrl_rvalid && (transaction != READ || ar_pending))) current_fault_code = 8'd5;
        else if ((b_complete && m_axi_ctrl_bresp !== 2'b00) ||
                 (r_complete && m_axi_ctrl_rresp !== 2'b00)) current_fault_code = 8'd4;
        else if (r_complete && state == READ_MASK && m_axi_ctrl_rdata !== 32'h3) current_fault_code = 8'd6;
        else if (r_complete && state == READ_ONOFF && m_axi_ctrl_rdata !== 32'h1) current_fault_code = 8'd7;
        else if (r_complete && state == READ_STATUS && m_axi_ctrl_rdata !== 32'h0) current_fault_code = 8'd8;
        else if (transaction != NONE && !b_complete && !r_complete &&
                 cycles >= TIMEOUT_CYCLES-1) current_fault_code = 8'd3;
        fault_now = current_fault_code != 0;
    end

    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            state <= WAIT_CALIB; transaction <= NONE;
            aw_pending <= 0; w_pending <= 0; ar_pending <= 0;
            service_active <= 0; healthy <= 0; checking <= 0; cycles <= 0;
            m_axi_ctrl_araddr <= 0; captured_mask <= 0; captured_onoff <= 0;
            snapshot_valid <= 0; snapshot_status <= 0; snapshot_onoff <= 0; snapshot_irq_mask <= 0;
            fault <= 0; fault_code <= 0;
        end else begin
            if (m_axi_ctrl_awvalid && m_axi_ctrl_awready) aw_pending <= 0;
            if (m_axi_ctrl_wvalid && m_axi_ctrl_wready) w_pending <= 0;
            if (m_axi_ctrl_arvalid && m_axi_ctrl_arready) ar_pending <= 0;
            if (transaction == NONE || b_complete || r_complete) cycles <= 0;
            else if (cycles < TIMEOUT_CYCLES-1) cycles <= cycles+1;
            if (b_complete || r_complete) transaction <= NONE;
            if (snapshot_valid && snapshot_ready) snapshot_valid <= 0;

            if (!fault && fault_now) begin
                fault <= 1; fault_code <= current_fault_code;
                healthy <= 0; state <= QUARANTINE;
            end
            // Transaction handshake bookkeeping above remains active forever
            // in quarantine. No fresh command or response snapshot is invented.
            if (!fault && !fault_now) begin
                case (state)
                    WAIT_CALIB: if (calib_complete) begin
                        service_active <= 1; checking <= 0;
                        aw_pending <= 1; w_pending <= 1; transaction <= WRITE; state <= WRITE_MASK;
                    end
                    WRITE_MASK: if (b_complete) begin
                        m_axi_ctrl_araddr <= 32'h4; ar_pending <= 1;
                        transaction <= READ; state <= READ_MASK;
                    end
                    READ_MASK: if (r_complete) begin
                        captured_mask <= m_axi_ctrl_rdata;
                        m_axi_ctrl_araddr <= 32'h8; ar_pending <= 1;
                        transaction <= READ; state <= READ_ONOFF;
                    end
                    READ_ONOFF: if (r_complete) begin
                        captured_onoff <= m_axi_ctrl_rdata;
                        m_axi_ctrl_araddr <= 0; ar_pending <= 1;
                        transaction <= READ; state <= READ_STATUS;
                    end
                    READ_STATUS: if (r_complete) begin
                        healthy <= 1;
                        if (checking) begin
                            snapshot_irq_mask <= captured_mask; snapshot_onoff <= captured_onoff;
                            snapshot_status <= m_axi_ctrl_rdata; snapshot_valid <= 1; state <= RESULT;
                        end else state <= READY;
                    end
                    READY: if (check_valid && check_ready) begin
                        checking <= 1; m_axi_ctrl_araddr <= 32'h4; ar_pending <= 1;
                        transaction <= READ; state <= READ_MASK;
                    end
                    RESULT: if (snapshot_valid && snapshot_ready) state <= READY;
                    QUARANTINE: begin end
                    default: begin fault <= 1; fault_code <= 8'd5; healthy <= 0; state <= QUARANTINE; end
                endcase
            end
        end
    end
endmodule
