// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Candidate C0/NORM/single-rank readback fence. The caller must exclusively own
// both the routed read channel and ECC-check link, seal the memory epoch, have
// accepted every producer B/R response, and supply that epoch's exact final AW
// address. Its initialized ordinary 64-byte beat remains allocated throughout.
// This leaf does not observe/establish those caller obligations. Its ordering
// premise still requires the separately pinned actual-controller qualification;
// a receipt is not global PHY idle, initialized-memory or job-admission proof.
module rk_mig_write_fence #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, joint_rst_n,
    input logic fence_valid,
    output logic fence_ready,
    input logic [31:0] final_write_address,
    input logic epoch_has_write, epoch_sealed, writes_complete,
    input logic upstream_quiescent, owner_exclusive,
    input logic calib_complete, monitor_healthy, monitor_fault,
    output logic fence_result_valid,
    input logic fence_result_ready,
    output logic fence_done, fault,
    output logic [7:0] fault_code,

    output logic [3:0] m_axi_arid,
    output logic [30:0] m_axi_araddr,
    output logic [7:0] m_axi_arlen,
    output logic [2:0] m_axi_arsize,
    output logic [1:0] m_axi_arburst,
    output logic m_axi_arlock,
    output logic [3:0] m_axi_arcache,
    output logic [2:0] m_axi_arprot,
    output logic [3:0] m_axi_arqos,
    output logic m_axi_arvalid,
    input logic m_axi_arready,
    input logic [3:0] m_axi_rid,
    input logic [1:0] m_axi_rresp,
    input logic m_axi_rlast, m_axi_rvalid,
    output logic m_axi_rready,

    output logic monitor_check_valid,
    input logic monitor_check_ready,
    input logic monitor_snapshot_valid,
    output logic monitor_snapshot_ready,
    input logic [31:0] monitor_snapshot_status,
    input logic [31:0] monitor_snapshot_onoff,
    input logic [31:0] monitor_snapshot_irq_mask
);
    typedef enum logic [2:0] {IDLE, READ_ADDR, READ_DATA, CHECK_REQUEST,
                              CHECK_RESPONSE, RESULT, QUARANTINE} state_t;
    state_t state;
    logic active, ar_pending, read_pending, check_pending, check_accepted;
    logic [30:0] captured_address;
    logic [31:0] cycles;
    logic request_accept, read_complete, snapshot_complete, fault_now, invalid_address;
    logic [7:0] current_fault_code;

    initial begin
        if (TIMEOUT_CYCLES == 0) $fatal(1, "Fence timeout must be positive");
    end

    assign fence_ready = joint_rst_n && state == IDLE && !fault;
    assign request_accept = fence_valid && fence_ready;
    assign m_axi_arid = 0;
    assign m_axi_araddr = captured_address;
    assign m_axi_arlen = 0;
    assign m_axi_arsize = 3'd6;
    assign m_axi_arburst = 2'b01;
    assign m_axi_arlock = 0;
    assign m_axi_arcache = 0;
    assign m_axi_arprot = 0;
    assign m_axi_arqos = 0;
    // Requests survive faults/timeouts. Only the platform joint reset cancels.
    assign m_axi_arvalid = joint_rst_n && ar_pending;
    assign m_axi_rready = joint_rst_n && (read_pending || fault);
    assign monitor_check_valid = joint_rst_n && check_pending;
    assign monitor_snapshot_ready = joint_rst_n && (check_accepted || fault);
    assign read_complete = m_axi_rvalid && m_axi_rready && read_pending && !ar_pending;
    assign snapshot_complete = monitor_snapshot_valid && monitor_snapshot_ready && check_accepted;
    assign invalid_address = (^final_write_address) === 1'bx ||
                             final_write_address[31] !== 1'b0 || final_write_address[5:0] !== 6'b0;
    // A held receipt is stable even if health fails later. The acceptance pulse
    // alone qualifies current conditions, so a same-edge fault beats success.
    assign fence_done = joint_rst_n && fence_result_valid && fence_result_ready && !fault && !fault_now;

    always_comb begin
        current_fault_code = 0;
        if ((active || request_accept) && (calib_complete !== 1'b1 ||
                monitor_healthy !== 1'b1 || monitor_fault !== 1'b0)) current_fault_code = 8'd3;
        else if ((active || request_accept) && (owner_exclusive !== 1'b1 ||
                epoch_sealed !== 1'b1 || writes_complete !== 1'b1 ||
                upstream_quiescent !== 1'b1)) current_fault_code = 8'd1;
        else if (request_accept && epoch_has_write !== 1'b1) current_fault_code = 8'd1;
        else if ((active || request_accept) && m_axi_rvalid !== 1'b0 &&
                (m_axi_rvalid !== 1'b1 || !read_pending || ar_pending)) current_fault_code = 8'd4;
        else if (read_complete && (m_axi_rid !== 4'b0 || m_axi_rresp !== 2'b0 ||
                m_axi_rlast !== 1'b1)) current_fault_code = 8'd4;
        else if ((active || request_accept) && monitor_snapshot_valid !== 1'b0 &&
                (monitor_snapshot_valid !== 1'b1 || !check_accepted)) current_fault_code = 8'd5;
        else if (snapshot_complete && (monitor_snapshot_status !== 32'b0 ||
                monitor_snapshot_onoff !== 32'h1 || monitor_snapshot_irq_mask !== 32'h3))
            current_fault_code = 8'd5;
        else if (request_accept && invalid_address)
            current_fault_code = 8'd2;
        else if ((read_pending || check_pending || check_accepted) &&
                !read_complete && !snapshot_complete && cycles >= TIMEOUT_CYCLES-1)
            current_fault_code = 8'd6;
        fault_now = current_fault_code != 0;
    end

    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            state <= IDLE; active <= 0;
            ar_pending <= 0; read_pending <= 0; check_pending <= 0; check_accepted <= 0;
            captured_address <= 0; cycles <= 0;
            fence_result_valid <= 0; fault <= 0; fault_code <= 0;
        end else begin
            if (m_axi_arvalid && m_axi_arready) ar_pending <= 0;
            // A malformed non-last beat faults but stays drainable until a
            // later known last beat, or until a whole-domain reset is applied.
            if (read_complete && m_axi_rlast === 1'b1) read_pending <= 0;
            if (monitor_check_valid && monitor_check_ready) begin
                check_pending <= 0; check_accepted <= 1;
            end
            if (snapshot_complete) check_accepted <= 0;
            if (fence_result_valid && fence_result_ready) begin
                fence_result_valid <= 0; active <= 0;
            end
            if ((!read_pending && !check_pending && !check_accepted) ||
                    read_complete || snapshot_complete) cycles <= 0;
            else if (cycles < TIMEOUT_CYCLES-1) cycles <= cycles+1;

            if (!fault && fault_now) begin
                fault <= 1; fault_code <= current_fault_code; state <= QUARANTINE;
            end
            // All handshake/drain bookkeeping above also runs in quarantine.
            // A faulted ECC monitor may never accept a held check request;
            // fault is terminal and no drained acknowledgment is invented.
            if (!fault && !fault_now) begin
                case (state)
                    IDLE: if (request_accept) begin
                        captured_address <= final_write_address[30:0]; active <= 1;
                        ar_pending <= 1; read_pending <= 1; cycles <= 0; state <= READ_ADDR;
                    end
                    READ_ADDR: if (m_axi_arvalid && m_axi_arready) state <= READ_DATA;
                    READ_DATA: if (read_complete) begin
                        check_pending <= 1; cycles <= 0; state <= CHECK_REQUEST;
                    end
                    CHECK_REQUEST: if (monitor_check_valid && monitor_check_ready) state <= CHECK_RESPONSE;
                    CHECK_RESPONSE: if (snapshot_complete) begin
                        fence_result_valid <= 1; state <= RESULT;
                    end
                    RESULT: if (fence_result_valid && fence_result_ready) state <= IDLE;
                    QUARANTINE: begin end
                    default: begin fault <= 1; fault_code <= 8'd4; state <= QUARANTINE; end
                endcase
            end
        end
    end
endmodule
