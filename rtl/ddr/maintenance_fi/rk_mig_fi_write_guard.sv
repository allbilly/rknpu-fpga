// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Private candidate: an internal diagnostic request guard, not an admitted
// host ABI or a controller-port arbiter. The caller must hold diagnostic
// ownership and exclude normal memory/control traffic for the full episode.
// A joint reset covers this guard, control port and every transaction domain;
// it does NOT reset the vendor FI mask, so known_bytes is invalidated.
module rk_mig_fi_write_guard #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic clk, joint_rst_n,
    input  logic diagnostic_owned, memory_quiescent, calib_complete,
    input  logic req_valid,
    output logic req_ready,
    input  logic req_write,
    input  logic [31:0] req_address, req_data,
    input  logic [3:0] req_strobe,
    input  logic [2:0] req_protection,
    output logic rsp_valid,
    input  logic rsp_ready,
    output logic [1:0] rsp_response,
    output logic busy, quarantine,
    output logic [7:0] fault_code,
    output logic [71:0] observed_mask,
    output logic [8:0] known_bytes,
    output logic mask_disarmed,
    output logic [31:0] m_axi_ctrl_awaddr,
    output logic m_axi_ctrl_awvalid,
    input  logic m_axi_ctrl_awready,
    output logic [31:0] m_axi_ctrl_wdata,
    output logic m_axi_ctrl_wvalid,
    input  logic m_axi_ctrl_wready,
    input  logic [1:0] m_axi_ctrl_bresp,
    input  logic m_axi_ctrl_bvalid,
    output logic m_axi_ctrl_bready,
    input  logic [8:0] fi_xor_we,
    input  logic [71:0] fi_xor_wrdata,
    // Exact write-clear input of the actual FI leaf, not an AXI B response or
    // inferred retirement. This observes mask clearing only, not DDR success.
    input  logic memory_write_clear
);
    logic active, aw_pending, w_pending, b_seen, fi_seen;
    logic [31:0] cycles;
    logic [8:0] expected_we;
    logic [71:0] expected_data, expected_bits;
    logic b_complete, witness_match, complete_now, fault_now;
    logic [7:0] current_fault;

    function automatic logic legal_request(
        input logic write_request,
        input logic [31:0] address, data,
        input logic [3:0] strobe,
        input logic [2:0] protection
    );
        logic common_valid;
        begin
            common_valid = write_request === 1'b1 && strobe === 4'hf &&
                           protection === 3'b0 && (^data) !== 1'bx;
            case (address)
                32'h300, 32'h304: legal_request = common_valid;
                32'h380: legal_request = common_valid && data[31:8] === 24'b0;
                default: legal_request = 1'b0;
            endcase
        end
    endfunction

    function automatic logic [8:0] byte_enables(input logic [31:0] address);
        case (address)
            32'h300: byte_enables = 9'h00f;
            32'h304: byte_enables = 9'h0f0;
            32'h380: byte_enables = 9'h100;
            default: byte_enables = 9'b0;
        endcase
    endfunction

    function automatic logic [71:0] payload(input logic [31:0] address, data);
        case (address)
            32'h300: payload = {40'b0, data};
            32'h304: payload = {8'b0, data, 32'b0};
            32'h380: payload = {data[7:0], 64'b0};
            default: payload = 72'b0;
        endcase
    endfunction

    function automatic logic [71:0] payload_bits(input logic [31:0] address);
        case (address)
            32'h300: payload_bits = {40'b0, 32'hffffffff};
            32'h304: payload_bits = {8'b0, 32'hffffffff, 32'b0};
            32'h380: payload_bits = {8'hff, 64'b0};
            default: payload_bits = 72'b0;
        endcase
    endfunction

    initial begin
        if (TIMEOUT_CYCLES == 0) $fatal(1, "FI request timeout must be positive");
    end

    assign req_ready = joint_rst_n && !active && !rsp_valid && !quarantine && !fault_now;
    assign busy = active || rsp_valid || quarantine;
    assign m_axi_ctrl_awvalid = joint_rst_n && aw_pending;
    assign m_axi_ctrl_wvalid = joint_rst_n && w_pending;
    // Faults preserve pending AW/W and consume a late B; only joint reset
    // withdraws an uncertain transaction. Quarantine never admits a new one.
    assign m_axi_ctrl_bready = joint_rst_n && (active || quarantine);
    assign b_complete = active && m_axi_ctrl_bvalid === 1'b1 && m_axi_ctrl_bready &&
                        !aw_pending && !w_pending && !b_seen;
    assign witness_match = active && !aw_pending && !w_pending && !fi_seen &&
                           fi_xor_we === expected_we && expected_we != 0 &&
                           (fi_xor_wrdata & expected_bits) === (expected_data & expected_bits);
    assign complete_now = active && !aw_pending && !w_pending &&
                          (b_seen || (b_complete && m_axi_ctrl_bresp === 2'b00)) &&
                          (fi_seen || witness_match);
    assign mask_disarmed = joint_rst_n && !quarantine &&
                           known_bytes === 9'h1ff && observed_mask === 72'b0;

    always_comb begin
        current_fault = 0;
        if (!quarantine && (active || (rsp_valid && rsp_response === 2'b00)) &&
            (diagnostic_owned !== 1'b1 || memory_quiescent !== 1'b1 || calib_complete !== 1'b1))
            current_fault = 8'd1;
        else if (active && !quarantine) begin
            if (memory_write_clear !== 1'b0)
                current_fault = 8'd6;
            else if (m_axi_ctrl_bvalid && (aw_pending || w_pending || b_seen))
                current_fault = 8'd3;
            else if (b_complete && m_axi_ctrl_bresp !== 2'b00)
                current_fault = 8'd4;
            else if (fi_xor_we !== 9'b0 && !witness_match)
                current_fault = 8'd2;
            else if (cycles >= TIMEOUT_CYCLES-1 && !complete_now)
                current_fault = 8'd5;
        end else if (!quarantine && rsp_valid && rsp_response === 2'b00 && memory_write_clear !== 1'b0)
            current_fault = 8'd6;
        else if (!active && !quarantine && diagnostic_owned === 1'b1 && m_axi_ctrl_bvalid !== 1'b0)
            current_fault = 8'd3;
        else if (!active && !quarantine && fi_xor_we !== 9'b0)
            current_fault = 8'd7;
        fault_now = current_fault != 0;
    end

    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            active <= 0; aw_pending <= 0; w_pending <= 0;
            b_seen <= 0; fi_seen <= 0; cycles <= 0;
            rsp_valid <= 0; rsp_response <= 0;
            quarantine <= 0; fault_code <= 0;
            m_axi_ctrl_awaddr <= 0; m_axi_ctrl_wdata <= 0;
            expected_we <= 0; expected_data <= 0; expected_bits <= 0;
            observed_mask <= 0; known_bytes <= 0;
        end else begin
            if (m_axi_ctrl_awvalid && m_axi_ctrl_awready) aw_pending <= 0;
            if (m_axi_ctrl_wvalid && m_axi_ctrl_wready) w_pending <= 0;
            if (b_complete) b_seen <= 1;
            if (witness_match) fi_seen <= 1;
            if (rsp_valid && rsp_ready) rsp_valid <= 0;
            if (active && !quarantine && cycles < TIMEOUT_CYCLES-1) cycles <= cycles + 1'b1;

            if (memory_write_clear === 1'b1) begin
                observed_mask <= 0;
                known_bytes <= 9'h1ff;
            end else if (witness_match && !fault_now && !quarantine) begin
                for (int byte_index = 0; byte_index < 9; byte_index = byte_index + 1) begin
                    if (expected_we[byte_index]) begin
                        observed_mask[byte_index*8+:8] <= fi_xor_wrdata[byte_index*8+:8];
                        known_bytes[byte_index] <= 1'b1;
                    end
                end
            end

            if (req_valid && req_ready) begin
                if (legal_request(req_write, req_address, req_data, req_strobe, req_protection) &&
                    diagnostic_owned === 1'b1 && memory_quiescent === 1'b1 && calib_complete === 1'b1) begin
                    m_axi_ctrl_awaddr <= req_address;
                    m_axi_ctrl_wdata <= req_data;
                    expected_we <= byte_enables(req_address);
                    expected_data <= payload(req_address, req_data);
                    expected_bits <= payload_bits(req_address);
                    active <= 1; aw_pending <= 1; w_pending <= 1;
                    b_seen <= 0; fi_seen <= 0; cycles <= 0;
                end else begin
                    // Every denied field/read fails before any vendor request.
                    rsp_valid <= 1; rsp_response <= 2'b10;
                end
            end
            if (active && !quarantine && !fault_now && b_seen && fi_seen &&
                !aw_pending && !w_pending) begin
                // fi_seen was sampled at the leaf's update edge. This later
                // edge ensures the mask applied before reporting success.
                active <= 0; rsp_valid <= 1; rsp_response <= 2'b00;
            end
            if (fault_now && !quarantine) begin
                quarantine <= 1; fault_code <= current_fault;
                if (active && !rsp_valid) begin
                    rsp_valid <= 1; rsp_response <= 2'b10;
                end
                if (memory_write_clear !== 1'b1) known_bytes <= 0;
            end
        end
    end
endmodule
