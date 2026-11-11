// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Host-drivable AXI-Lite endpoint around the captured signed-INT8 pooling job.
//
// Same transport page layout as rk_conv_simple_axi, with a distinct identity:
//
//   0x00  DEVICE_ID      RO  0x524b5050 ("RKPP": captured raw PPU jobs)
//   0x04  ABI_VERSION    RO  0x00010000
//   0x08  STATUS         RO  [0] can_submit, [1] active, [2] result_valid,
//                            [3] result_error, [4] memory_ready,
//                            [5] engine error, [6] engine busy,
//                            [10:8] descriptor fields valid
//   0x0c  COMMAND        WO  1 = submit, 2 = acknowledge result
//   0x10  START_ADDRESS  RW  command BO base
//   0x14  START_AMOUNT   RW  raw QWORD count (26 for these captures)
//   0x18  JOB_TAG        RW
//   0x1c  RESULT_TAG     RO
//   0x20  RESULT_TASKS   RO
//   0x24  RESULT_CODE    RO
//
// A faulted result holds the slot until the platform resets the endpoint,
// matching rk_job_control and the CMAC page.
module rk_ppu_pool_axi #(
    parameter logic [31:0] BASE = 32'h10000000,
    parameter logic [32:0] BYTES = 33'd1048576,
    parameter int unsigned WORDS = 26,
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter logic [31:0] DEVICE_ID = 32'h524b5050,
    parameter bit MINIMUM = 1'b0
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        memory_ready,
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
    output logic        irq,
    output logic        busy,
    output logic        mem_req_valid,
    input  logic        mem_req_ready,
    output logic        mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input  logic        mem_rsp_valid,
    output logic        mem_rsp_ready,
    input  logic [15:0] mem_rsp_rdata,
    input  logic        mem_rsp_error
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
    logic writable, can_submit, engine_busy, engine_error;
    logic [31:0] status_word;

    logic engine_start_valid, engine_start_ready, engine_done;
    logic [7:0] engine_error_code;

    assign writable = !active && !launch_pending && !result_valid &&
                      !engine_error && !engine_busy;
    assign can_submit = writable && (&fields_valid) && memory_ready &&
                        engine_start_ready;
    assign status_word = {21'b0, fields_valid, 1'b0, engine_busy, engine_error,
                          memory_ready, result_error, result_valid, active,
                          can_submit};
    assign engine_start_valid = rst_n && launch_pending;
    assign irq = rst_n && result_valid;
    assign busy = rst_n && (active || launch_pending);
    assign s_axil_awready = rst_n && !have_aw && !bvalid;
    assign s_axil_wready = rst_n && !have_w && !bvalid;
    assign s_axil_arready = rst_n && !rvalid;
    assign s_axil_bvalid = rst_n && bvalid;
    assign s_axil_rvalid = rst_n && rvalid;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            have_aw <= 1'b0; have_w <= 1'b0; bvalid <= 1'b0; rvalid <= 1'b0;
            write_address <= 32'd0; write_data <= 32'd0;
            write_prot <= 3'd0; write_strobe <= 4'd0;
            s_axil_bresp <= 2'd0; s_axil_rresp <= 2'd0; s_axil_rdata <= 32'd0;
            command_address <= 32'd0; command_amount <= 32'd0; job_tag <= 32'd0;
            fields_valid <= 3'd0;
            launch_pending <= 1'b0; active <= 1'b0;
            result_valid <= 1'b0; result_error <= 1'b0;
            result_tag <= 32'd0; result_tasks <= 32'd0; result_code <= 8'd0;
        end else begin
            if (s_axil_bvalid && s_axil_bready) bvalid <= 1'b0;
            if (s_axil_rvalid && s_axil_rready) rvalid <= 1'b0;

            if (s_axil_awvalid && s_axil_awready) begin
                have_aw <= 1'b1;
                write_address <= s_axil_awaddr;
                write_prot <= s_axil_awprot;
            end
            if (s_axil_wvalid && s_axil_wready) begin
                have_w <= 1'b1;
                write_data <= s_axil_wdata;
                write_strobe <= s_axil_wstrb;
            end

            if (have_aw && have_w && !bvalid) begin
                have_aw <= 1'b0; have_w <= 1'b0; bvalid <= 1'b1;
                s_axil_bresp <= 2'b00;
                if (write_prot != 3'd0 || write_strobe != 4'hf)
                    s_axil_bresp <= 2'b10;
                else case (write_address)
                    32'h0c: begin
                        if (write_data == 32'd1 && can_submit) begin
                            active <= 1'b1; launch_pending <= 1'b1;
                            result_tag <= 32'd0; result_tasks <= 32'd0;
                            result_code <= 8'd0; result_error <= 1'b0;
                        end else if (write_data == 32'd2 && result_valid &&
                                     !result_error && !active && !engine_error &&
                                     !engine_busy) begin
                            result_valid <= 1'b0; fields_valid <= 3'd0;
                            command_address <= 32'd0; command_amount <= 32'd0;
                            job_tag <= 32'd0;
                        end else s_axil_bresp <= 2'b10;
                    end
                    32'h10: if (writable) begin
                        command_address <= write_data; fields_valid[0] <= 1'b1;
                    end else s_axil_bresp <= 2'b10;
                    32'h14: if (writable) begin
                        command_amount <= write_data; fields_valid[1] <= 1'b1;
                    end else s_axil_bresp <= 2'b10;
                    32'h18: if (writable) begin
                        job_tag <= write_data; fields_valid[2] <= 1'b1;
                    end else s_axil_bresp <= 2'b10;
                    32'h00, 32'h04, 32'h08, 32'h1c, 32'h20, 32'h24:
                        s_axil_bresp <= 2'b10;
                    default: s_axil_bresp <= 2'b11;
                endcase
            end

            if (s_axil_arvalid && s_axil_arready) begin
                rvalid <= 1'b1; s_axil_rresp <= 2'b00; s_axil_rdata <= 32'd0;
                if (s_axil_arprot != 3'd0) s_axil_rresp <= 2'b10;
                else case (s_axil_araddr)
                    32'h00: s_axil_rdata <= DEVICE_ID;
                    32'h04: s_axil_rdata <= 32'h00010000;
                    32'h08: s_axil_rdata <= status_word;
                    32'h0c: s_axil_rresp <= 2'b10;
                    32'h10: s_axil_rdata <= command_address;
                    32'h14: s_axil_rdata <= command_amount;
                    32'h18: s_axil_rdata <= job_tag;
                    32'h1c: s_axil_rdata <= result_tag;
                    32'h20: s_axil_rdata <= result_tasks;
                    32'h24: s_axil_rdata <= {24'd0, result_code};
                    default: s_axil_rresp <= 2'b11;
                endcase
            end

            if (engine_start_valid && engine_start_ready)
                launch_pending <= 1'b0;
            if (active && !launch_pending && (engine_error || engine_done)) begin
                active <= 1'b0; result_valid <= 1'b1;
                result_error <= engine_error;
                result_tag <= job_tag;
                result_tasks <= engine_error ? 32'd0 : 32'd1;
                result_code <= engine_error ? engine_error_code : 8'd0;
            end
        end
    end

    rk_ppu_pool_i8_k2s2_dma #(
        .BASE(BASE), .BYTES(BYTES), .MINIMUM(MINIMUM),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) engine (
        .clk, .rst_n,
        .start_valid(engine_start_valid), .start_ready(engine_start_ready),
        .start_address(command_address), .start_amount(command_amount),
        .quiescent(), .idle_quiet(),
        .busy(engine_busy), .done(engine_done),
        .error(engine_error), .error_code(engine_error_code),
        .result_ready(1'b1),
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata,
        .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata, .mem_rsp_error);

    initial begin
        if (TIMEOUT_CYCLES == 0)
            $fatal(1, "pooling endpoint timeout must be positive");
        if (WORDS != 26)
            $fatal(1, "captured INT8 descriptors are exactly 26 QWORDs");
    end
endmodule
