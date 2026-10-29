// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// FPGA transport registers, not Rockchip NPU registers. One job/result slot.
// The platform must reset the control, engine and downstream AXI domain together.
module rk_job_control (
    input logic clk, rst_n, memory_ready,
    input logic [31:0] s_axil_awaddr,
    input logic [2:0] s_axil_awprot,
    input logic s_axil_awvalid,
    output logic s_axil_awready,
    input logic [31:0] s_axil_wdata,
    input logic [3:0] s_axil_wstrb,
    input logic s_axil_wvalid,
    output logic s_axil_wready,
    output logic [1:0] s_axil_bresp,
    output logic s_axil_bvalid,
    input logic s_axil_bready,
    input logic [31:0] s_axil_araddr,
    input logic [2:0] s_axil_arprot,
    input logic s_axil_arvalid,
    output logic s_axil_arready,
    output logic [31:0] s_axil_rdata,
    output logic [1:0] s_axil_rresp,
    output logic s_axil_rvalid,
    input logic s_axil_rready,
    output logic irq,
    output logic core_start_valid,
    input logic core_start_ready,
    output logic [31:0] core_start_address, core_start_amount,
    input logic core_busy, core_done, core_error,
    input logic [7:0] core_error_code,
    input logic [31:0] core_completed_tasks
);
    logic have_aw, have_w, bvalid, rvalid;
    logic [31:0] write_address, write_data;
    logic [2:0] write_prot;
    logic [3:0] write_strobe;
    logic [31:0] command_address, command_amount, job_tag;
    logic [2:0] fields_valid;
    logic launch_pending, active, result_valid, result_error;
    logic [31:0] result_tag, result_tasks;
    logic [7:0] result_code;
    logic writable, can_submit;
    logic [31:0] status_word;

    assign writable = !active && !launch_pending && !result_valid && !core_error && !core_busy;
    assign can_submit = writable && (&fields_valid) && memory_ready && core_start_ready;
    assign status_word = {21'b0, fields_valid, 1'b0, core_busy, core_error,
                          memory_ready, result_error, result_valid, active, can_submit};
    assign core_start_valid = rst_n && launch_pending;
    assign core_start_address = command_address;
    assign core_start_amount = command_amount;
    assign irq = rst_n && result_valid;
    assign s_axil_awready = rst_n && !have_aw && !bvalid;
    assign s_axil_wready = rst_n && !have_w && !bvalid;
    assign s_axil_arready = rst_n && !rvalid;
    assign s_axil_bvalid = rst_n && bvalid;
    assign s_axil_rvalid = rst_n && rvalid;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            have_aw <= 0; have_w <= 0; bvalid <= 0; rvalid <= 0;
            write_address <= 0; write_data <= 0; write_prot <= 0; write_strobe <= 0;
            s_axil_bresp <= 0; s_axil_rresp <= 0; s_axil_rdata <= 0;
            command_address <= 0; command_amount <= 0; job_tag <= 0; fields_valid <= 0;
            launch_pending <= 0; active <= 0; result_valid <= 0; result_error <= 0;
            result_tag <= 0; result_tasks <= 0; result_code <= 0;
        end else begin
            if (s_axil_bvalid && s_axil_bready) bvalid <= 0;
            if (s_axil_rvalid && s_axil_rready) rvalid <= 0;
            if (s_axil_awvalid && s_axil_awready) begin
                have_aw <= 1; write_address <= s_axil_awaddr; write_prot <= s_axil_awprot;
            end
            if (s_axil_wvalid && s_axil_wready) begin
                have_w <= 1; write_data <= s_axil_wdata; write_strobe <= s_axil_wstrb;
            end
            if (have_aw && have_w && !bvalid) begin
                have_aw <= 0; have_w <= 0; bvalid <= 1; s_axil_bresp <= 2'b00;
                if (write_prot != 0 || write_strobe != 4'hf) s_axil_bresp <= 2'b10;
                else case (write_address)
                    32'h0c: begin
                        if (write_data == 1 && can_submit) begin
                            active <= 1; launch_pending <= 1;
                            result_tag <= 0; result_tasks <= 0; result_code <= 0; result_error <= 0;
                        end else if (write_data == 2 && result_valid && !result_error &&
                                     !active && !core_error && !core_busy) begin
                            result_valid <= 0; fields_valid <= 0;
                            command_address <= 0; command_amount <= 0; job_tag <= 0;
                        end else s_axil_bresp <= 2'b10;
                    end
                    32'h10: if (writable) begin command_address <= write_data; fields_valid[0] <= 1; end
                            else s_axil_bresp <= 2'b10;
                    32'h14: if (writable) begin command_amount <= write_data; fields_valid[1] <= 1; end
                            else s_axil_bresp <= 2'b10;
                    32'h18: if (writable) begin job_tag <= write_data; fields_valid[2] <= 1; end
                            else s_axil_bresp <= 2'b10;
                    32'h00, 32'h04, 32'h08, 32'h1c, 32'h20, 32'h24: s_axil_bresp <= 2'b10;
                    default: s_axil_bresp <= 2'b11;
                endcase
            end
            // Read snapshots precede a simultaneous register write/event update.
            if (s_axil_arvalid && s_axil_arready) begin
                rvalid <= 1; s_axil_rresp <= 2'b00; s_axil_rdata <= 0;
                if (s_axil_arprot != 0) s_axil_rresp <= 2'b10;
                else case (s_axil_araddr)
                    32'h00: s_axil_rdata <= 32'h524b4557; // RKEW
                    32'h04: s_axil_rdata <= 32'h00010000;
                    32'h08: s_axil_rdata <= status_word;
                    32'h0c: s_axil_rresp <= 2'b10;
                    32'h10: s_axil_rdata <= command_address;
                    32'h14: s_axil_rdata <= command_amount;
                    32'h18: s_axil_rdata <= job_tag;
                    32'h1c: s_axil_rdata <= result_tag;
                    32'h20: s_axil_rdata <= result_tasks;
                    32'h24: s_axil_rdata <= {24'b0, result_code};
                    default: s_axil_rresp <= 2'b11;
                endcase
            end
            if (core_start_valid && core_start_ready) launch_pending <= 0;
            if (active && !launch_pending && (core_error || core_done)) begin
                active <= 0; result_valid <= 1; result_error <= core_error;
                result_tag <= job_tag; result_tasks <= core_completed_tasks;
                result_code <= core_error ? core_error_code : 8'b0;
            end
        end
    end
endmodule
