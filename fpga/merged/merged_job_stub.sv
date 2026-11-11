// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Page-ABI model for the Image-A runtime conv page (S1 scaffolding, NOT an
// engine and NOT a replacement for the real page).
//
// This is a `rk_job_control`-compatible AXI4-Lite page model used while conveng's
// runtime engine is still gated on its parameterised equivalence rerun. It
// implements the exact register ABI the real `rk_conv_runtime_axi` page will
// expose, so the replay/ABI benches and negative controls can be written and
// proven now; only the wrapper file/hashes need pinning when the engine lands.
//
// Registers (rk_job_control compatible):
//   0x00 DEVICE_ID      RO  0x524b4356 "RKCV"
//   0x04 ABI_VERSION    RO  0x00010000
//   0x08 STATUS         RO  {21'b0, fields_valid[3], 1'b0, busy, error,
//                            memory_ready, result_error, result_valid, active,
//                            can_submit}
//   0x0c COMMAND        WO  1 = submit, 2 = acknowledge/clear result
//   0x10 START_ADDRESS  RW  command BO base, 16-byte aligned, inside the window
//   0x14 START_AMOUNT   RW  command QWORD count (scaffold: 1..4096; the real
//                            page will accept exactly 52 or 54)
//   0x18 JOB_TAG        RW
//   0x1c RESULT_TAG     RO
//   0x20 RESULT_TASKS   RO  1 on modeled success, 0 on modeled error
//   0x24 RESULT_CODE    RO  0 OK, 2 missing fields, 4 unaligned address,
//                            6 address/amount out of range
//
// The model performs no memory access and produces no output BO: a modeled
// submit completes after DONE_CYCLES with RESULT_TASKS=1 so the transport, the
// register ABI, the submit/ack ordering and the error paths can be exercised.
// TODO(S1): replace this instance with `rk_conv_runtime_axi` (real engine,
// co-signed ABI) once conveng's parameterised rerun is green; keep this file as
// the ABI reference model for the replay harness.
module merged_job_stub #(
    parameter logic [31:0] DEVICE_ID = 32'h524b_4356,
    parameter logic [31:0] ABI_VERSION = 32'h00010000,
    parameter logic [31:0] WINDOW_BASE = 32'h0000_0000,
    parameter int unsigned WINDOW_BYTES = 65536,
    parameter int unsigned ALIGN_BYTES = 16,
    parameter int unsigned AMOUNT_MIN = 1,
    parameter int unsigned AMOUNT_MAX = 4096,
    parameter int unsigned DONE_CYCLES = 8
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        memory_ready,
    // AXI4-Lite slave
    input  logic [31:0] s_axil_awaddr,
    input  logic [2:0]  s_axil_awprot,
    input  logic        s_axil_awvalid,
    output logic        s_axil_awready,
    input  logic [31:0] s_axil_wdata,
    input  logic [3:0]  s_axil_wstrb,
    input  logic        s_axil_wvalid,
    output logic        s_axil_wready,
    output logic [1:0]  s_axil_bresp,
    output logic        s_axil_bvalid,
    input  logic        s_axil_bready,
    input  logic [31:0] s_axil_araddr,
    input  logic [2:0]  s_axil_arprot,
    input  logic        s_axil_arvalid,
    output logic        s_axil_arready,
    output logic [31:0] s_axil_rdata,
    output logic [1:0]  s_axil_rresp,
    output logic        s_axil_rvalid,
    input  logic        s_axil_rready,
    // Status lines the image uses for LEDs/arbitration.
    output logic        busy,
    output logic        irq
);
    localparam logic [11:0] REG_ID = 12'h000, REG_ABI = 12'h004, REG_STATUS = 12'h008,
                            REG_COMMAND = 12'h00c, REG_START_ADDRESS = 12'h010,
                            REG_START_AMOUNT = 12'h014, REG_JOB_TAG = 12'h018,
                            REG_RESULT_TAG = 12'h01c, REG_RESULT_TASKS = 12'h020,
                            REG_RESULT_CODE = 12'h024;
    localparam logic [2:0] CMD_SUBMIT = 3'd1, CMD_ACK = 3'd2;

    logic aw_pending_q, w_pending_q, bvalid_q, rvalid_q;
    logic [31:0] write_address_q, write_data_q, read_address_q, read_data_q;
    logic [31:0] start_address_q, start_amount_q, job_tag_q;
    logic [31:0] result_tag_q, result_tasks_q;
    logic [7:0] result_code_q;
    logic active_q, result_valid_q, error_q, result_error_q;
    logic [7:0] wait_q;
    logic [3:0] fields_valid_q;

    wire [31:0] waddr = write_address_q;
    wire [31:0] raddr = read_address_q;
    wire fields_ok = &fields_valid_q[2:0];
    wire can_submit = rst_n && !active_q && !result_valid_q && !error_q &&
                      !busy && fields_ok && memory_ready;
    wire [31:0] status_word = {21'b0, fields_valid_q[2:0], 1'b0, busy, error_q,
                                memory_ready, result_error_q, result_valid_q,
                                active_q, can_submit};
    wire start_aligned = (start_address_q % ALIGN_BYTES) == 0;
    wire start_in_window = (start_address_q >= WINDOW_BASE) &&
                           ((start_address_q - WINDOW_BASE) < WINDOW_BYTES);
    wire amount_ok = (start_amount_q >= AMOUNT_MIN) && (start_amount_q <= AMOUNT_MAX);

    assign busy = active_q;
    assign irq = result_valid_q;
    assign s_axil_awready = rst_n && !aw_pending_q && !bvalid_q;
    assign s_axil_wready = rst_n && !w_pending_q && !bvalid_q;
    assign s_axil_arready = rst_n && !rvalid_q;
    assign s_axil_bvalid = rst_n && bvalid_q;
    assign s_axil_bresp = 2'b00;
    assign s_axil_rvalid = rst_n && rvalid_q;
    assign s_axil_rresp = 2'b00;
    assign s_axil_rdata = read_data_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            aw_pending_q <= 1'b0;
            w_pending_q <= 1'b0;
            bvalid_q <= 1'b0;
            rvalid_q <= 1'b0;
            write_address_q <= 32'd0;
            write_data_q <= 32'd0;
            read_address_q <= 32'd0;
            read_data_q <= 32'd0;
            start_address_q <= 32'd0;
            start_amount_q <= 32'd0;
            job_tag_q <= 32'd0;
            result_tag_q <= 32'd0;
            result_tasks_q <= 32'd0;
            result_code_q <= 8'd0;
            active_q <= 1'b0;
            result_valid_q <= 1'b0;
            error_q <= 1'b0;
            result_error_q <= 1'b0;
            wait_q <= 8'd0;
            fields_valid_q <= 4'b0000;
        end else begin
            if (s_axil_bvalid && s_axil_bready) bvalid_q <= 1'b0;
            if (s_axil_rvalid && s_axil_rready) rvalid_q <= 1'b0;
            if (s_axil_awvalid && s_axil_awready) begin
                aw_pending_q <= 1'b1;
                write_address_q <= s_axil_awaddr;
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_pending_q <= 1'b1;
                write_data_q <= s_axil_wdata;
            end
            // Modeled job lifecycle: submit -> busy for DONE_CYCLES -> result.
            if (active_q) begin
                wait_q <= wait_q + 8'd1;
                if (wait_q == 8'(DONE_CYCLES - 1)) begin
                    active_q <= 1'b0;
                    result_valid_q <= 1'b1;
                    result_tasks_q <= 32'd1;
                    result_tag_q <= job_tag_q;
                    result_code_q <= 8'd0;
                    result_error_q <= 1'b0;
                end
            end
            if (aw_pending_q && w_pending_q && !bvalid_q) begin
                aw_pending_q <= 1'b0;
                w_pending_q <= 1'b0;
                bvalid_q <= 1'b1;
                case (waddr[11:0])
                    REG_COMMAND: begin
                        case (write_data_q[2:0])
                            CMD_SUBMIT: begin
                                if (can_submit && start_aligned &&
                                    start_in_window && amount_ok) begin
                                    // Accepted: modeled one-task job.
                                    active_q <= 1'b1;
                                    wait_q <= 8'd0;
                                    error_q <= 1'b0;
                                    result_error_q <= 1'b0;
                                    result_code_q <= 8'd0;
                                end else if (!result_valid_q && !active_q) begin
                                    // Rejected submission: report an explicit code
                                    // (2 missing fields, 4 unaligned, 6 range).
                                    // While a job/result is pending the command is
                                    // ignored instead (mirrors the real page's
                                    // non-writable state) so a host cannot destroy
                                    // a pending result by polling-submitting.
                                    error_q <= 1'b1;
                                    result_error_q <= 1'b1;
                                    result_tasks_q <= 32'd0;
                                    result_code_q <= !fields_ok ? 8'd2 :
                                                     !start_aligned ? 8'd4 :
                                                     !(start_in_window && amount_ok) ? 8'd6 : 8'd2;
                                end
                            end
                            CMD_ACK: begin
                                result_valid_q <= 1'b0;
                                result_error_q <= 1'b0;
                                error_q <= 1'b0;
                            end
                            default: begin end
                        endcase
                    end
                    REG_START_ADDRESS: begin
                        start_address_q <= write_data_q;
                        fields_valid_q[0] <= 1'b1;
                    end
                    REG_START_AMOUNT: begin
                        start_amount_q <= write_data_q;
                        fields_valid_q[1] <= 1'b1;
                    end
                    REG_JOB_TAG: begin
                        job_tag_q <= write_data_q;
                        fields_valid_q[2] <= 1'b1;
                    end
                    default: begin end
                endcase
            end
            if (s_axil_arvalid && s_axil_arready) begin
                rvalid_q <= 1'b1;
                read_address_q <= s_axil_araddr;
                read_data_q <= 32'h0000_0000;
                case (s_axil_araddr[11:0])
                    REG_ID: read_data_q <= DEVICE_ID;
                    REG_ABI: read_data_q <= ABI_VERSION;
                    REG_STATUS: read_data_q <= status_word;
                    REG_START_ADDRESS: read_data_q <= start_address_q;
                    REG_START_AMOUNT: read_data_q <= start_amount_q;
                    REG_JOB_TAG: read_data_q <= job_tag_q;
                    REG_RESULT_TAG: read_data_q <= result_tag_q;
                    REG_RESULT_TASKS: read_data_q <= result_tasks_q;
                    REG_RESULT_CODE: read_data_q <= {24'd0, result_code_q};
                    default: read_data_q <= 32'h0000_0000;
                endcase
            end
        end
    end
endmodule
