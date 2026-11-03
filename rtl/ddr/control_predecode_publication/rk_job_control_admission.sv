// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// FPGA transport registers, not Rockchip NPU registers. One job/result slot.
// The platform must reset the control, engine and downstream AXI domain together.
module rk_job_control_admission #(
    parameter logic [31:0] DEVICE_ID = 32'h524b4557,
    parameter logic [31:0] ABI_VERSION = 32'h00010000
) (
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
    output wire descriptor_empty,
    output logic core_start_valid,
    input logic core_start_ready,
    output logic [31:0] core_start_address, core_start_amount,
    input logic core_busy, core_done, core_error,
    input logic core_write_block,
    input logic new_admission_block,
    input logic [7:0] core_error_code,
    input logic [31:0] core_completed_tasks
);
    logic have_aw, have_w, bvalid, rvalid;
    logic [31:0] write_address, write_data;
    logic [2:0] write_prot;
    logic [3:0] write_strobe;
    // Logical descriptor fields remain zero until written and after ACK.
    // Raw writes only touch the unpublished bank; accepted writes publish
    // through one selector per field. ACK clears the original validity flags.
    logic [95:0] descriptor_payload_bank0,descriptor_payload_bank1;
    logic [2:0] descriptor_payload_select;
    logic [2:0] fields_valid;
    wire [31:0] command_address=fields_valid[0] ?
        (descriptor_payload_select[0] ? descriptor_payload_bank1[31:0] : descriptor_payload_bank0[31:0]) : 32'd0;
    wire [31:0] command_amount=fields_valid[1] ?
        (descriptor_payload_select[1] ? descriptor_payload_bank1[63:32] : descriptor_payload_bank0[63:32]) : 32'd0;
    wire [31:0] job_tag=fields_valid[2] ?
        (descriptor_payload_select[2] ? descriptor_payload_bank1[95:64] : descriptor_payload_bank0[95:64]) : 32'd0;
    logic launch_pending, active, result_valid;
    logic result_error_payload;
    logic [7:0] result_code_payload;
    wire result_error = result_valid ? result_error_payload : 1'b0;
    wire [7:0] result_code = result_valid ?
        (result_error_payload ? result_code_payload : 8'b0) : 8'b0;
    logic [31:0] result_tag, result_tasks;
    logic writable, can_submit, status_can_submit;
    logic [31:0] status_word;

    // Match the procedural write guard exactly, including its four-state
    // fall-through behavior. SUBMIT readiness never controls descriptor data.
    wire descriptor_write_commit=have_aw&&have_w&&!bvalid;
    wire descriptor_payload_admitted=((write_prot!=0||write_strobe!=4'hf)!==1'b1);
    wire descriptor_write_accept=descriptor_write_commit&&descriptor_payload_admitted&&writable;
    wire descriptor_ack_accept=descriptor_write_commit&&descriptor_payload_admitted&&
        (write_address==32'h0c)&&(write_data==32'd2)&&result_valid&&!result_error&&
        !active&&!core_write_block;

    assign descriptor_empty = rst_n && fields_valid===3'b000;
    assign writable = !active && !launch_pending && !result_valid && !core_write_block &&
        new_admission_block===1'b0;
    // Keep the original four-state status expression; only procedural
    // admission guards use the independently proven parent block predicate.
    assign status_can_submit = !active && !launch_pending && !result_valid &&
        !core_error && !core_busy && (&fields_valid) && memory_ready && core_start_ready &&
        new_admission_block===1'b0;
    assign can_submit = writable && (&fields_valid) && memory_ready && core_start_ready;
    assign status_word = {21'b0, fields_valid, 1'b0, core_busy, core_error,
                          memory_ready, result_error, result_valid, active, status_can_submit};
    assign core_start_valid = rst_n && launch_pending;
    assign core_start_address = command_address;
    assign core_start_amount = command_amount;
    assign irq = rst_n && result_valid;
    assign s_axil_awready = rst_n && !have_aw && !bvalid;
    assign s_axil_wready = rst_n && !have_w && !bvalid;
    assign s_axil_arready = rst_n && !rvalid;
    assign s_axil_bvalid = rst_n && bvalid;
    assign s_axil_rvalid = rst_n && rvalid;

    // Private payloads are sampled locally while active. The original known
    // result-valid publication exposes only the completion edge's snapshot.
    // Preserve the original procedural X/Z reset fall-through, without resets
    // or live completion-error enables on these nine private payload bits.
    always_ff @(posedge clk) begin
        if (!rst_n) begin end
        else if (active) begin
            result_error_payload <= core_error;
            result_code_payload <= core_error_code;
        end
    end

    // Same-cycle private capture and publication retain the original write
    // timing. Strobes/protection/busy/fault gates qualify publication only;
    // rejected raw writes cannot alter any logical descriptor field.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            descriptor_payload_bank0<=0;descriptor_payload_bank1<=0;descriptor_payload_select<=0;
        end else begin
            if(descriptor_write_commit&&write_address==32'h10)begin
                if(descriptor_payload_select[0])descriptor_payload_bank0[31:0]<=write_data;
                else descriptor_payload_bank1[31:0]<=write_data;
            end
            if(descriptor_write_accept&&write_address==32'h10)
                descriptor_payload_select[0]<=!descriptor_payload_select[0];
            if(descriptor_write_commit&&write_address==32'h14)begin
                if(descriptor_payload_select[1])descriptor_payload_bank0[63:32]<=write_data;
                else descriptor_payload_bank1[63:32]<=write_data;
            end
            if(descriptor_write_accept&&write_address==32'h14)
                descriptor_payload_select[1]<=!descriptor_payload_select[1];
            if(descriptor_write_commit&&write_address==32'h18)begin
                if(descriptor_payload_select[2])descriptor_payload_bank0[95:64]<=write_data;
                else descriptor_payload_bank1[95:64]<=write_data;
            end
            if(descriptor_write_accept&&write_address==32'h18)
                descriptor_payload_select[2]<=!descriptor_payload_select[2];
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            have_aw <= 0; have_w <= 0; bvalid <= 0; rvalid <= 0;
            write_address <= 0; write_data <= 0; write_prot <= 0; write_strobe <= 0;
            s_axil_bresp <= 0; s_axil_rresp <= 0; s_axil_rdata <= 0;
            fields_valid <= 0;
            launch_pending <= 0; active <= 0; result_valid <= 0;
            result_tag <= 0; result_tasks <= 0;
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
                            // Result-free states already hold zero code/error:
                            // reset initializes them; successful ACK preserves
                            // zero, and error results cannot be ACKed/submitted.
                        end else if (write_data == 2 && result_valid && !result_error &&
                                     !active && !core_write_block) begin
                            result_valid <= 0;
                        end else s_axil_bresp <= 2'b10;
                    end
                    32'h10: if (writable) begin end
                            else s_axil_bresp <= 2'b10;
                    32'h14: if (writable) begin end
                            else s_axil_bresp <= 2'b10;
                    32'h18: if (writable) begin end
                            else s_axil_bresp <= 2'b10;
                    32'h00, 32'h04, 32'h08, 32'h1c, 32'h20, 32'h24: s_axil_bresp <= 2'b10;
                    default: s_axil_bresp <= 2'b11;
                endcase
            end
            if (descriptor_ack_accept) begin
                fields_valid <= 0;
            end else begin
                if (descriptor_write_accept && write_address==32'h10) begin
                    fields_valid[0] <= 1;
                end
                if (descriptor_write_accept && write_address==32'h14) begin
                    fields_valid[1] <= 1;
                end
                if (descriptor_write_accept && write_address==32'h18) begin
                    fields_valid[2] <= 1;
                end
            end
            // Read snapshots precede a simultaneous register write/event update.
            if (s_axil_arvalid && s_axil_arready) begin
                rvalid <= 1; s_axil_rresp <= 2'b00; s_axil_rdata <= 0;
                if (s_axil_arprot != 0) s_axil_rresp <= 2'b10;
                else case (s_axil_araddr)
                    32'h00: s_axil_rdata <= DEVICE_ID; // RKEW by default
                    32'h04: s_axil_rdata <= ABI_VERSION;
                    32'h08: s_axil_rdata <= status_word;
                    32'h0c: s_axil_rresp <= 2'b10;
                    32'h10: s_axil_rdata <= command_address;
                    32'h14: s_axil_rdata <= command_amount;
                    32'h18: s_axil_rdata <= job_tag;
                    32'h1c: s_axil_rdata <= active ? 32'b0 : result_tag;
                    32'h20: s_axil_rdata <= active ? 32'b0 : result_tasks;
                    32'h24: s_axil_rdata <= {24'b0, result_code};
                    default: s_axil_rresp <= 2'b11;
                endcase
            end
            // Only the registered active bit enables these 64 metadata FFs.
            // Reads stay zero throughout active, including a completion edge;
            // the last active edge captures exactly the original completion
            // payload. ACK keeps the held snapshot; no live-input read mux.
            if (active) begin
                result_tag <= job_tag; result_tasks <= core_completed_tasks;
            end
            if (core_start_valid && core_start_ready) launch_pending <= 0;
            if (active && !launch_pending && (core_error || core_done)) begin
                active <= 0; result_valid <= 1;
                // Result metadata was sampled on this same edge while active.
                // The same active edge captures raw private error/code payloads.
            end
        end
    end
endmodule
