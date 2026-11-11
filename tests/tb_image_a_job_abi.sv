// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Image-A runtime-page ABI bench (S1 replay scaffolding).
//
// Drives the exact register contract the real `rk_conv_runtime_axi` page will
// expose (currently served by the `merged_job_stub` ABI reference model) through
// the reviewed USER2 mailbox -> AXI bridge -> Image-A decode path:
//
//   ID/ABI read, START_ADDRESS/START_AMOUNT/JOB_TAG write, STATUS can_submit,
//   COMMAND submit -> modeled result (RESULT_TAG/RESULT_TASKS/RESULT_CODE),
//   COMMAND ack -> re-arm, and the scaffold negative controls:
//     * unaligned START_ADDRESS      -> RESULT_CODE=4, RESULT_TASKS=0
//     * START_ADDRESS outside window -> RESULT_CODE=6, RESULT_TASKS=0
//     * START_AMOUNT==0 / oversized  -> RESULT_CODE=6, RESULT_TASKS=0
//     * a second COMMAND=submit while a result is pending -> refused (no new job)
//     * a valid job after each acknowledged error still works (ack re-arms)
//
// The engine-level negative controls (unsupported geometry, second stream
// without reset, overlapping buffers) are listed in the replay plan and are
// exercised by the S1 family replay once the real page is pinned.
//
// Simulation-only glue: tests/merged/merged_primitive_stubs.sv + the shared
// tests/host/mailbox_scan.svh driver. Run from the repo root:
//   iverilog -g2012 -Itests -o /tmp/abi.vvp -s tb_image_a_job_abi \
//       tests/merged/merged_primitive_stubs.sv <profile sources> \
//       tests/tb_image_a_job_abi.sv
//   vvp /tmp/abi.vvp
module tb_image_a_job_abi;
    localparam logic [31:0] PAGE = 32'h0001_0000;
    localparam logic [31:0] REG_ID = 32'h0;
    localparam logic [31:0] REG_ABI = 32'h4;
    localparam logic [31:0] REG_STATUS = 32'h8;
    localparam logic [31:0] REG_COMMAND = 32'hc;
    localparam logic [31:0] REG_START_ADDRESS = 32'h10;
    localparam logic [31:0] REG_START_AMOUNT = 32'h14;
    localparam logic [31:0] REG_JOB_TAG = 32'h18;
    localparam logic [31:0] REG_RESULT_TAG = 32'h1c;
    localparam logic [31:0] REG_RESULT_TASKS = 32'h20;
    localparam logic [31:0] REG_RESULT_CODE = 32'h24;
    localparam logic [31:0] ID_RKCV = 32'h524b_4356;
    localparam logic [31:0] ABI = 32'h0001_0000;
    // STATUS bit positions (rk_job_control layout).
    localparam integer ST_CAN_SUBMIT = 0, ST_ACTIVE = 1, ST_RESULT_VALID = 2,
                       ST_MEMORY_READY = 4;
    localparam logic [2:0] CMD_SUBMIT = 3'd1, CMD_ACK = 3'd2;

    logic clk = 0;
    always #10 clk = ~clk;
    wire [2:0] leds;
    ypcb_merged_top #(.LED_ACTIVE_LOW(1'b0)) dut (
        .SYS_CLK(clk), .led_3bits_tri_o(leds)
    );

    logic tck = 0, capture = 0, shift = 0, update = 0, sel = 0, tdi = 0;
    wire tdo = dut.u_bscan.TDO;
    initial begin
        force dut.u_bscan.TCK = tck;
        force dut.u_bscan.CAPTURE = capture;
        force dut.u_bscan.SHIFT = shift;
        force dut.u_bscan.UPDATE = update;
        force dut.u_bscan.SEL = sel;
        force dut.u_bscan.TDI = tdi;
    end

    `include "host/mailbox_scan.svh"

    logic [15:0] sequence_q = 16'h0;
    integer frames = 0, checks = 0;
    logic [31:0] value;

    task automatic command(input logic [7:0] opcode, input logic [31:0] address,
                           input logic [511:0] data, input logic [3:0] strobes,
                           output logic [511:0] result,
                           input logic [7:0] status_expected = 0);
        logic [639:0] packet, received;
        integer polls;
        begin
            sequence_q = sequence_q + 1;
            packet = {36'b0, 32'h4f54504a, sequence_q, opcode, strobes,
                      address, data};
            scan_frame(packet, received);
            polls = 0;
            while ((received[567:536] != 32'h4f54504a ||
                    received[535:520] != sequence_q) && polls < 8) begin
                scan_frame(0, received);
                polls = polls + 1;
            end
            if (received[567:536] != 32'h4f54504a ||
                received[535:520] != sequence_q ||
                received[519:512] != status_expected)
                $fatal(1, "IMAGE_A_ABI frame %0d op=%0d status=%02x expected=%02x",
                       sequence_q, opcode, received[519:512], status_expected);
            result = received[511:0];
            frames = frames + 1;
            checks = checks + 1;
        end
    endtask

    task automatic write_word(input logic [31:0] offset, input logic [31:0] data);
        logic [511:0] unused;
        command(8'd2, PAGE + offset, {480'h0, data}, 4'hf, unused);
    endtask

    task automatic read_word(input logic [31:0] offset, output logic [31:0] data);
        logic [511:0] value512;
        command(8'd1, PAGE + offset, 512'h0, 4'hf, value512);
        data = value512[31:0];
    endtask

    task automatic expect_reg(input logic [31:0] offset, input logic [31:0] expected,
                              input string label);
        read_word(offset, value);
        if (value !== expected)
            $fatal(1, "IMAGE_A_ABI %s: reg %02x got=%08x expected=%08x",
                   label, offset, value, expected);
        checks = checks + 1;
    endtask

    task automatic expect_status_bit(input integer bit_index, input logic expected,
                                     input string label);
        read_word(REG_STATUS, value);
        if (value[bit_index] !== expected)
            $fatal(1, "IMAGE_A_ABI %s: STATUS bit%0d got=%b status=%08x",
                   label, bit_index, value[bit_index], value);
        checks = checks + 1;
    endtask

    task automatic program_job(input logic [31:0] address, input logic [31:0] amount,
                               input logic [31:0] tag);
        write_word(REG_START_ADDRESS, address);
        write_word(REG_START_AMOUNT, amount);
        write_word(REG_JOB_TAG, tag);
    endtask

    task automatic run_job(input logic [31:0] address, input logic [31:0] amount,
                           input logic [31:0] tag, input logic [31:0] expect_tasks);
        program_job(address, amount, tag);
        expect_status_bit(ST_CAN_SUBMIT, 1'b1, "can_submit after programming");
        write_word(REG_COMMAND, 32'(CMD_SUBMIT));
        // One mailbox frame takes ~107 us of simulated time, which is longer
        // than the modeled job's DONE_CYCLES; the next read may already see the
        // result. Accept either "active" or "result valid" here.
        read_word(REG_STATUS, value);
        if ((value[ST_ACTIVE] | value[ST_RESULT_VALID]) !== 1'b1)
            $fatal(1, "IMAGE_A_ABI submit did not take effect status=%08x", value);
        checks = checks + 1;
        for (integer poll = 0; poll < 4; poll = poll + 1) begin
            read_word(REG_STATUS, value);
            if (value[ST_RESULT_VALID] === 1'b1) break;
        end
        if (value[ST_RESULT_VALID] !== 1'b1)
            $fatal(1, "IMAGE_A_ABI modeled job did not complete status=%08x", value);
        checks = checks + 1;
        expect_reg(REG_RESULT_TASKS, expect_tasks, "result tasks");
        expect_reg(REG_RESULT_TAG, tag, "result tag");
        expect_reg(REG_RESULT_CODE, 32'h0, "result code ok");
        write_word(REG_COMMAND, 32'(CMD_ACK));
        expect_status_bit(ST_RESULT_VALID, 1'b0, "result cleared by ack");
    endtask

    task automatic expect_error(input logic [31:0] address, input logic [31:0] amount,
                                input logic [31:0] code, input string label);
        program_job(address, amount, 32'hc0de_0000);
        write_word(REG_COMMAND, 32'(CMD_SUBMIT));
        expect_reg(REG_RESULT_TASKS, 32'h0, label);
        expect_reg(REG_RESULT_CODE, code, label);
        expect_status_bit(ST_RESULT_VALID, 1'b0, label);
        write_word(REG_COMMAND, 32'(CMD_ACK));
        expect_status_bit(ST_ACTIVE, 1'b0, label);
    endtask

    initial begin : TEST
        repeat (200) @(posedge clk);

        // ---- identity + reset state -------------------------------------
        expect_reg(REG_ID, ID_RKCV, "device identity");
        expect_reg(REG_ABI, ABI, "abi version");
        // The real S1 page is IDLE with no result pending at reset, so it CAN
        // accept a submit (STATUS[0] = 1). The previous expectation (bit0=0) was
        // the ABI reference stub's "result already pending" initialisation, not
        // the real page's contract.
        expect_status_bit(ST_CAN_SUBMIT, 1'b1, "reset can submit");
        expect_status_bit(ST_RESULT_VALID, 1'b0, "reset no result");
        expect_status_bit(ST_MEMORY_READY, 1'b1, "memory ready idle");

        // ---- positive job: tag/lifecycle/ack/re-arm ----------------------
        run_job(32'h0000_0100, 32'd52, 32'h1234_5678, 32'd1);
        run_job(32'h0000_0200, 32'd54, 32'h89ab_cdef, 32'd1);

        // ---- negative: second submit while a result is pending ----------
        program_job(32'h0000_0300, 32'd52, 32'h0bad_f00d);
        write_word(REG_COMMAND, 32'(CMD_SUBMIT));
        read_word(REG_STATUS, value);
        if (value[ST_ACTIVE] !== 1'b0 || value[ST_RESULT_VALID] !== 1'b1)
            $fatal(1, "IMAGE_A_ABI pending job did not complete status=%08x", value);
        // A submit command while the result slot is occupied must be refused:
        // can_submit is low, and the pending result must not change.
        expect_status_bit(ST_CAN_SUBMIT, 1'b0, "cannot submit while result pending");
        write_word(REG_COMMAND, 32'(CMD_SUBMIT));
        expect_reg(REG_RESULT_TASKS, 32'd1, "pending result not replaced");
        expect_reg(REG_RESULT_TAG, 32'h0bad_f00d, "pending tag not replaced");
        write_word(REG_COMMAND, 32'(CMD_ACK));
        expect_status_bit(ST_RESULT_VALID, 1'b0, "ack clears modeled result");

        // ---- negative controls (each acknowledged, then re-armed) --------
        expect_error(32'h0000_0002, 32'd52, 32'h4, "unaligned START_ADDRESS");
        expect_error(32'h0001_0000, 32'd52, 32'h6, "START_ADDRESS outside window");
        expect_error(32'h0000_0100, 32'd0, 32'h6, "zero START_AMOUNT");
        expect_error(32'h0000_0100, 32'd4097, 32'h6, "oversized START_AMOUNT");

        // ---- a valid job still runs after the acknowledged errors --------
        run_job(32'h0000_0400, 32'd52, 32'h5a5a_5a5a, 32'd1);

        $display("PASS YPCB_IMAGE_A_JOB_ABI frames=%0d checks=%0d", frames, checks);
        $finish;
    end

    initial begin
        #60_000_000;
        $fatal(1, "IMAGE_A_ABI timeout after %0d checks", checks);
    end
endmodule
