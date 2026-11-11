// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Autonomous board self-test for one captured conv-simple task.
//
// On reset release it:
//   1. loads the frozen 512-byte packed input BO and 2,304-byte packed weight
//      BO from the generated ROM into a BRAM aperture,
//   2. clears the 1,152-byte output BO (the capture's initial content is
//      unset, so the whole window is defined before comparison),
//   3. replays the captured 52-QWORD command stream from ROM into the raw
//      endpoint, one word per accepted handshake,
//   4. waits for completion and reads back the complete output BO, comparing
//      every halfword with the captured device bytes.
//
// The command stream is fed from ROM rather than BRAM so the conv engine stays
// the only memory master for operand traffic. Every operand and expected byte
// is ROM content taken from the pinned fixture. `pass`/`fail` are sticky.
module rk_conv_simple_self_test #(
    parameter logic [31:0] BASE = 32'h10000000,
    parameter int unsigned BRAM_BYTES = 32768,
    parameter int unsigned TIMEOUT_CYCLES = 4096,
    parameter int unsigned WATCHDOG_CYCLES = 4_000_000
) (
    input  logic clk,
    input  logic rst_n,
    output logic pass,
    output logic fail,
    output logic [7:0] error_code
);
    localparam int unsigned COMMAND_WORDS = 52;
    localparam int unsigned COMMAND_LAST = COMMAND_WORDS - 2;  // PC trigger
    localparam int unsigned INPUT_HALFWORDS = 256;
    localparam int unsigned WEIGHT_HALFWORDS = 1152;
    localparam int unsigned OUTPUT_HALFWORDS = 576;

    typedef enum logic [3:0] {
        ST_INIT_INPUT, ST_INIT_WEIGHT, ST_INIT_OUTPUT,
        ST_SEND, ST_RUN, ST_CHECK, ST_PASS, ST_FAIL
    } state_t;
    state_t state_q;

    logic [5:0]   command_index;
    logic [63:0]  command_data;
    logic [7:0]   input_index;
    logic [15:0]  input_data;
    logic [10:0]  weight_index;
    logic [15:0]  weight_data;
    logic [9:0]   expected_index;
    logic [15:0]  expected_data;
    logic [31:0]  command_base, input_base, weight_base, output_base, start_amount;

    rk_conv_simple_demo_rom rom (
        .command_index, .command_data, .input_index, .input_data,
        .weight_index, .weight_data, .expected_index, .expected_data,
        .command_base, .input_base, .weight_base, .output_base, .start_amount
    );

    logic [11:0] init_index_q;
    logic [11:0] check_index_q;
    logic [5:0]  send_index_q;
    logic [31:0] watchdog_q;
    logic error_q;
    logic [7:0] error_code_q;

    wire cmd_valid, cmd_ready, busy, acknowledged, frame_done, done, error;
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

    assign cmd_valid = state_q == ST_SEND && cmd_ready;
    wire cmd_last = send_index_q == 6'(COMMAND_LAST);

    rk_conv_simple_core #(
        .PROFILE(0), .INPUT_H(8), .INPUT_W(8), .KH(3), .KW(3), .STRIDE(1),
        .INPUT_CHANNELS(4), .KERNELS(8), .C1_BLOCKS(2), .ALIGN_C(8),
        .PACK_C2(4), .CHUNK_LANES(16), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) engine (
        .clk, .rst_n,
        .cmd_valid, .cmd_ready, .cmd_data(command_data), .cmd_last,
        .busy, .acknowledged, .frame_done, .done,
        .error, .error_code(engine_error_code),
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

    // The command index comes from the send counter; the operand indices come
    // from the loader counter. They are never live at the same time.
    assign command_index = send_index_q;
    assign input_index = init_index_q[7:0];
    assign weight_index = init_index_q[10:0];
    assign expected_index = check_index_q[9:0];

    always_comb begin
        host_valid = 1'b0;
        host_write = 1'b0;
        host_addr = 32'd0;
        host_wdata = 16'd0;
        host_rsp_ready = 1'b1;
        case (state_q)
            ST_INIT_INPUT: begin
                host_valid = 1'b1;
                host_write = 1'b1;
                host_addr = 32'(input_base + {20'd0, init_index_q[7:0], 1'b0});
                host_wdata = input_data;
            end
            ST_INIT_WEIGHT: begin
                host_valid = 1'b1;
                host_write = 1'b1;
                host_addr = 32'(weight_base + {20'd0, init_index_q[10:0], 1'b0});
                host_wdata = weight_data;
            end
            ST_INIT_OUTPUT: begin
                host_valid = 1'b1;
                host_write = 1'b1;
                host_addr = 32'(output_base + {20'd0, init_index_q[9:0], 1'b0});
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

    // The captured output BO is fully defined, so the checker compares every
    // halfword against the captured bytes with no zero-fill allowance.
    assign pass = state_q == ST_PASS;
    assign fail = state_q == ST_FAIL;
    assign error_code = error_q ? error_code_q : 8'd0;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state_q <= ST_INIT_INPUT;
            init_index_q <= 12'd0;
            check_index_q <= 12'd0;
            send_index_q <= 6'd0;
            watchdog_q <= 32'd0;
            error_q <= 1'b0;
            error_code_q <= 8'd0;
        end else begin
            if (state_q != ST_PASS && state_q != ST_FAIL)
                watchdog_q <= watchdog_q + 1'b1;

            if (state_q == ST_INIT_INPUT || state_q == ST_INIT_WEIGHT ||
                state_q == ST_INIT_OUTPUT) begin
                if (host_rsp_valid && host_error) begin
                    state_q <= ST_FAIL;
                    error_q <= 1'b1;
                    error_code_q <= 8'h53;
                end else if (host_valid && host_ready) begin
                    if (state_q == ST_INIT_INPUT &&
                        init_index_q[7:0] == 8'(INPUT_HALFWORDS - 1)) begin
                        init_index_q <= 12'd0;
                        state_q <= ST_INIT_WEIGHT;
                    end else if (state_q == ST_INIT_WEIGHT &&
                                 init_index_q[10:0] == 11'(WEIGHT_HALFWORDS - 1)) begin
                        init_index_q <= 12'd0;
                        state_q <= ST_INIT_OUTPUT;
                    end else if (state_q == ST_INIT_OUTPUT &&
                                 init_index_q[9:0] == 10'(OUTPUT_HALFWORDS - 1)) begin
                        init_index_q <= 12'd0;
                        send_index_q <= 6'd0;
                        state_q <= ST_SEND;
                    end else begin
                        init_index_q <= init_index_q + 1'b1;
                    end
                end
            end

            // One accepted descriptor word per cycle; `cmd_ready` stays high
            // until the profile leaves its collect state, so this cannot skip
            // or duplicate a captured field.
            if (state_q == ST_SEND && cmd_ready) begin
                if (send_index_q == 6'(COMMAND_WORDS - 1)) begin
                    state_q <= ST_RUN;
                end else begin
                    send_index_q <= send_index_q + 1'b1;
                end
            end

            if (state_q == ST_SEND && error) begin
                state_q <= ST_FAIL;
                error_q <= 1'b1;
                error_code_q <= engine_error_code;
            end

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
                end else if (host_rdata !== expected_data) begin
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
