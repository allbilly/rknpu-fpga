// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Autonomous board self-test for the captured signed-INT8 C16 pooling task.
//
// On reset release it:
//   1. loads the frozen 26-QWORD command stream and 64-byte input operand from
//      the generated ROM into the BRAM aperture,
//   2. clears the 4096-byte output BO (the capture's initial output BO is zero),
//   3. launches the strict descriptor endpoint once, and
//   4. reads back the complete 4096-byte output BO and compares the first eight
//      halfwords with the captured device bytes and every remaining halfword
//      with zero.
//
// The command stream and expected bytes are ROM contents taken from the pinned
// fixture; no arithmetic is performed in this harness. `pass`/`fail` are sticky
// so the board LEDs hold the result.
module rk_ppu_pool_self_test #(
    parameter logic [31:0] BASE = 32'h10000000,
    parameter int unsigned BRAM_BYTES = 8192,
    parameter int unsigned TIMEOUT_CYCLES = 2048,
    parameter int unsigned WATCHDOG_CYCLES = 1_000_000
) (
    input  logic clk,
    input  logic rst_n,
    output logic pass,
    output logic fail,
    output logic [7:0] error_code
);
    localparam int unsigned COMMAND_HALFWORDS = 104;
    localparam int unsigned INPUT_HALFWORDS = 32;
    localparam int unsigned EXPECTED_HALFWORDS = 8;
    localparam int unsigned OUTPUT_HALFWORDS = 2048;

    typedef enum logic [3:0] {
        ST_INIT_COMMAND, ST_INIT_INPUT, ST_INIT_OUTPUT,
        ST_START, ST_RUN, ST_CHECK, ST_PASS, ST_FAIL
    } state_t;
    state_t state_q;

    logic [6:0] command_index;
    logic [15:0] command_data;
    logic [4:0] input_index;
    logic [15:0] input_data;
    logic [2:0] expected_index;
    logic [15:0] expected_data;
    logic [31:0] command_base, input_base, output_base, start_amount;

    rk_ppu_pool_demo_rom rom (
        .command_index, .command_data, .input_index, .input_data,
        .expected_index, .expected_data,
        .command_base, .input_base, .output_base, .start_amount
    );

    logic [11:0] init_index_q;
    logic [11:0] check_index_q;
    logic [31:0] watchdog_q;
    logic error_q;
    logic [7:0] error_code_q;

    wire start_valid, start_ready;
    wire [31:0] start_address, start_amount_bus;
    wire done, error;
    /* verilator lint_off UNUSEDSIGNAL */
    wire quiescent, idle_quiet, busy;
    /* verilator lint_on UNUSEDSIGNAL */
    wire [7:0] engine_error_code;
    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    wire mem_req_ready;
    wire mem_rsp_valid, mem_rsp_error;
    wire [15:0] mem_rsp_rdata;

    logic host_valid, host_ready, host_write, host_rsp_valid, host_rsp_ready;
    logic [31:0] host_addr;
    logic [15:0] host_wdata, host_rdata;
    logic host_error;

    assign start_valid = state_q == ST_START;
    assign start_address = command_base;
    assign start_amount_bus = start_amount;

    rk_ppu_pool_i8_k2s2_dma #(
        .BASE(BASE), .BYTES(33'(BRAM_BYTES)), .MINIMUM(1'b0),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) engine (
        .clk, .rst_n,
        .start_valid, .start_ready,
        .start_address, .start_amount(start_amount_bus),
        .quiescent, .idle_quiet,
        .busy, .done, .error, .error_code(engine_error_code),
        .result_ready(1'b1),
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata,
        .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata, .mem_rsp_error
    );

    rk_bram #(.BYTES(BRAM_BYTES), .BASE(BASE)) memory (
        .clk, .rst_n,
        .req_valid(mem_req_valid), .req_ready(mem_req_ready),
        .req_write(mem_req_write), .req_addr(mem_req_addr),
        .req_wdata(mem_req_wdata),
        .rsp_valid(mem_rsp_valid), .rsp_ready(mem_rsp_ready),
        .rsp_rdata(mem_rsp_rdata), .rsp_error(mem_rsp_error),
        .host_valid, .host_ready, .host_write, .host_addr, .host_wdata,
        .host_rsp_valid, .host_rsp_ready, .host_rdata, .host_error
    );

    assign command_index = init_index_q[6:0];
    assign input_index = init_index_q[4:0];
    assign expected_index = check_index_q[2:0];

    // Exactly one of the ROM-driven loads or the readback is selected. A new
    // host request is issued only when the previous response is being consumed,
    // so the loader cannot duplicate or skip an address.
    always_comb begin
        host_valid = 1'b0;
        host_write = 1'b0;
        host_addr = 32'd0;
        host_wdata = 16'd0;
        host_rsp_ready = 1'b1;
        case (state_q)
            ST_INIT_COMMAND: begin
                host_valid = 1'b1;
                host_write = 1'b1;
                host_addr = 32'(command_base + {20'd0, init_index_q, 1'b0});
                host_wdata = command_data;
            end
            ST_INIT_INPUT: begin
                host_valid = 1'b1;
                host_write = 1'b1;
                host_addr = 32'(input_base + {26'd0, init_index_q[4:0], 1'b0});
                host_wdata = input_data;
            end
            ST_INIT_OUTPUT: begin
                host_valid = 1'b1;
                host_write = 1'b1;
                host_addr = 32'(output_base + {20'd0, init_index_q, 1'b0});
                host_wdata = 16'd0;
            end
            ST_CHECK: begin
                host_valid = !host_rsp_valid;
                host_write = 1'b0;
                host_addr = 32'(output_base + {20'd0, check_index_q, 1'b0});
            end
            default: begin end
        endcase
    end

    // Only the first eight halfwords carry captured data; the captured initial
    // output BO and therefore the untouched tail are all zero.
    wire [15:0] expected_halfword =
        (state_q == ST_CHECK && check_index_q < 12'(EXPECTED_HALFWORDS))
        ? expected_data : 16'd0;

    assign pass = state_q == ST_PASS;
    assign fail = state_q == ST_FAIL;
    assign error_code = error_q ? error_code_q : 8'd0;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state_q <= ST_INIT_COMMAND;
            init_index_q <= 12'd0;
            check_index_q <= 12'd0;
            watchdog_q <= 32'd0;
            error_q <= 1'b0;
            error_code_q <= 8'd0;
        end else begin
            if (state_q != ST_PASS && state_q != ST_FAIL)
                watchdog_q <= watchdog_q + 1'b1;

            if (state_q == ST_INIT_COMMAND || state_q == ST_INIT_INPUT ||
                state_q == ST_INIT_OUTPUT) begin
                if (host_rsp_valid && host_error) begin
                    state_q <= ST_FAIL;
                    error_q <= 1'b1;
                    error_code_q <= 8'h53;
                end else if (host_valid && host_ready) begin
                    if (state_q == ST_INIT_COMMAND &&
                        init_index_q == 12'(COMMAND_HALFWORDS - 1)) begin
                        init_index_q <= 12'd0;
                        state_q <= ST_INIT_INPUT;
                    end else if (state_q == ST_INIT_INPUT &&
                                 init_index_q[4:0] == 5'(INPUT_HALFWORDS - 1)) begin
                        init_index_q <= 12'd0;
                        state_q <= ST_INIT_OUTPUT;
                    end else if (state_q == ST_INIT_OUTPUT &&
                                 init_index_q == 12'(OUTPUT_HALFWORDS - 1)) begin
                        init_index_q <= 12'd0;
                        check_index_q <= 12'd0;
                        state_q <= ST_START;
                    end else begin
                        init_index_q <= init_index_q + 1'b1;
                    end
                end
            end

            if (state_q == ST_START && start_ready)
                state_q <= ST_RUN;

            if (state_q == ST_RUN) begin
                if (error) begin
                    state_q <= ST_FAIL;
                    error_q <= 1'b1;
                    error_code_q <= engine_error_code;
                end else if (done) begin
                    check_index_q <= 12'd0;
                    state_q <= ST_CHECK;
                end
            end

            if (state_q == ST_CHECK && host_rsp_valid) begin
                if (host_error) begin
                    state_q <= ST_FAIL;
                    error_q <= 1'b1;
                    error_code_q <= 8'h53;
                end else if (host_rdata !== expected_halfword) begin
                    state_q <= ST_FAIL;
                    error_q <= 1'b1;
                    error_code_q <= 8'h51;
                end else if (check_index_q == 12'(OUTPUT_HALFWORDS - 1)) begin
                    state_q <= ST_PASS;
                end else begin
                    check_index_q <= check_index_q + 1'b1;
                end
            end

            if (state_q != ST_PASS && state_q != ST_FAIL &&
                watchdog_q >= WATCHDOG_CYCLES) begin
                state_q <= ST_FAIL;
                error_q <= 1'b1;
                error_code_q <= 8'h52;
            end
        end
    end
endmodule
