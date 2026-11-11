// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Strict descriptor-to-raw-command wrapper for one pinned 3x3 C4 profile.
// start_amount counts the exact 54 raw QWORDs in the captured job. Each QWORD
// is fetched as four unchanged little-endian halfwords, then passed unchanged
// to the raw-stream core with the original task-end boundary as sideband.
module rk_conv_3x3_c4_dma #(
    parameter int unsigned PROFILE = 0, // 0=valid, 1=stride2, 2=explicit-zero-frame
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        start_valid,
    output logic        start_ready,
    input  logic [31:0] start_address,
    input  logic [31:0] start_amount,
    output logic        busy,
    output logic        done,
    output logic        acknowledged,
    output logic        frame_done,
    output logic        error,
    output logic [7:0]  error_code,
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
    localparam int unsigned PROFILE_VALID = 0;
    localparam int unsigned PROFILE_STRIDE2 = 1;
    localparam int unsigned PROFILE_PAD1_ZERO_FRAME = 2;
    localparam logic [32:0] INPUT_BYTES = PROFILE == PROFILE_VALID ? 33'd2592 : 33'd3872;
    localparam logic [32:0] WEIGHT_BYTES = 33'd1152;
    localparam logic [32:0] OUTPUT_BYTES = PROFILE == PROFILE_VALID ? 33'd3328 :
                                           PROFILE == PROFILE_STRIDE2 ? 33'd1792 : 33'd5376;

    typedef enum logic [2:0] {
        IDLE, CHECK, FETCH_REQ, FETCH_WAIT, SEND, RUN, REARM, FAILED
    } state_t;
    state_t state;
    logic [31:0] command_base, command_amount, input_base, weight_base, output_base;
    logic [32:0] command_end, input_end, weight_end, output_end;
    logic [5:0] word_index;
    logic [1:0] halfword_index;
    logic [63:0] command_word;
    logic [31:0] stalled_cycles;
    logic [1:0] rearm_cycles;
    logic fault, core_busy, core_done, core_error, core_cmd_ready;
    logic core_acknowledged, core_frame_done, core_req_valid, core_req_write;
    logic core_rsp_ready, fetch_bad_status, fetch_bad_data, core_cmd_valid;
    logic [7:0] saved_code, core_error_code;
    logic [31:0] core_req_addr;
    logic [15:0] core_req_data;
    logic ranges_disjoint, tail_is_exact, rearm_done;
    logic core_rst_n;

    initial begin
        if (TIMEOUT_CYCLES == 0)
            $fatal(1, "convolution command DMA timeout must be positive");
        if (PROFILE > PROFILE_PAD1_ZERO_FRAME)
            $fatal(1, "unsupported strict 3x3 C4 DMA profile");
    end

    assign command_end = {1'b0, command_base} + 33'd432;
    assign input_end = {1'b0, input_base} + INPUT_BYTES;
    assign weight_end = {1'b0, weight_base} + WEIGHT_BYTES;
    assign output_end = {1'b0, output_base} + OUTPUT_BYTES;

    function automatic logic overlaps(
        input logic [31:0] a_base,
        input logic [32:0] a_end,
        input logic [31:0] b_base,
        input logic [32:0] b_end
    );
        overlaps = ({1'b0, a_base} < b_end) && ({1'b0, b_base} < a_end);
    endfunction

    always @* begin
        ranges_disjoint = command_end <= 33'h100000000 &&
            !overlaps(command_base, command_end, input_base, input_end) &&
            !overlaps(command_base, command_end, weight_base, weight_end) &&
            !overlaps(command_base, command_end, output_base, output_end);
        // Let the raw profile preserve its exact rejection priority for a bad
        // terminal QWORD. Only pre-reject the final command when that word is
        // otherwise the pinned tail and the command/operand BOs overlap.
        tail_is_exact = word_index == 6'd53 &&
            command_word[63:48] === 16'h0081 &&
            command_word[15:0] === 16'h0008 &&
            command_word[47:16] === 32'h0000000d;
        fetch_bad_status = mem_rsp_error;
        fetch_bad_data = 1'b0;
`ifndef SYNTHESIS
        if (mem_rsp_error !== 1'b0) fetch_bad_status = 1'b1;
        if ((^mem_rsp_rdata) === 1'bx) fetch_bad_data = 1'b1;
`endif
    end

    assign error = rst_n && (fault || core_error);
    assign error_code = !rst_n ? 8'd0 : fault ? saved_code : core_error_code;
    // The strict core profile latches its task boundary, so a second descriptor
    // requires a reset pulse before the next raw stream. This wrapper owns that
    // reset: it holds the core in reset through REARM, fires done to the caller
    // at the end of the completed RUN, and only then releases start_ready.
    assign core_rst_n = rst_n && state != REARM;
    assign start_ready = rst_n && !error && state == IDLE && !core_busy && rearm_done;
    assign busy = rst_n && !error && state != IDLE && state != FAILED;
    assign done = rst_n && !error && state == RUN && core_done;
    assign acknowledged = rst_n && !error && state == RUN && core_acknowledged;
    assign frame_done = rst_n && !error && state == RUN && core_frame_done;
    assign core_cmd_valid = rst_n && !error && state == SEND &&
                            !(tail_is_exact && !ranges_disjoint);

    always @* begin
        mem_req_valid = 1'b0;
        mem_req_write = 1'b0;
        mem_req_addr = 32'd0;
        mem_req_wdata = 16'd0;
        mem_rsp_ready = 1'b0;
        if (rst_n && !error) begin
            case (state)
                FETCH_REQ: begin
                    mem_req_valid = 1'b1;
                    mem_req_addr = command_base + {23'd0, word_index, 3'b000} +
                                   {29'd0, halfword_index, 1'b0};
                end
                FETCH_WAIT: mem_rsp_ready = 1'b1;
                RUN: begin
                    mem_req_valid = core_req_valid;
                    mem_req_write = core_req_write;
                    mem_req_addr = core_req_addr;
                    mem_req_wdata = core_req_data;
                    mem_rsp_ready = core_rsp_ready;
                end
                default: begin end
            endcase
        end
    end

    // One exact-profile core instance. The profile selectors are elaboration
    // parameters on the shared core, so the descriptor wrapper does not carry
    // three near-duplicate instantiations that only differ by wrapper name.
    rk_conv_3x3_valid_c4_core #(
        .STRIDE2(PROFILE == PROFILE_STRIDE2),
        .PAD1_ZERO_FRAME(PROFILE == PROFILE_PAD1_ZERO_FRAME),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) core (
        .clk, .rst_n(core_rst_n), .cmd_valid(core_cmd_valid), .cmd_ready(core_cmd_ready),
        .cmd_data(command_word), .cmd_last(word_index == 6'd53),
        .busy(core_busy), .acknowledged(core_acknowledged),
        .frame_done(core_frame_done), .done(core_done), .error(core_error),
        .error_code(core_error_code), .mem_req_valid(core_req_valid),
        .mem_req_ready(mem_req_ready && state == RUN && !error),
        .mem_req_write(core_req_write), .mem_req_addr(core_req_addr),
        .mem_req_wdata(core_req_data),
        .mem_rsp_valid(mem_rsp_valid && state == RUN && !error),
        .mem_rsp_ready(core_rsp_ready), .mem_rsp_rdata(mem_rsp_rdata),
        .mem_rsp_error(mem_rsp_error));

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            command_base <= 0;
            command_amount <= 0;
            input_base <= 0;
            weight_base <= 0;
            output_base <= 0;
            word_index <= 0;
            halfword_index <= 0;
            command_word <= 0;
            stalled_cycles <= 0;
            rearm_cycles <= 0;
            rearm_done <= 1'b1;
            fault <= 0;
            saved_code <= 0;
        end else if (!fault) begin
            if (core_error) begin
                fault <= 1'b1;
                saved_code <= core_error_code;
                state <= FAILED;
            end else begin
                if ((state != FETCH_REQ && state != FETCH_WAIT) ||
                    (mem_req_valid && mem_req_ready) ||
                    (mem_rsp_valid && mem_rsp_ready))
                    stalled_cycles <= 0;
                else
                    stalled_cycles <= stalled_cycles + 1'b1;

                case (state)
                    IDLE: if (start_valid && start_ready) begin
                        command_base <= start_address;
                        command_amount <= start_amount;
                        rearm_done <= 1'b0;
                        state <= CHECK;
                    end
                    CHECK: begin
                        if (command_amount != 32'd54 || command_base[2:0] != 3'b000 ||
                            command_end > 33'h100000000) begin
                            fault <= 1'b1;
                            saved_code <= 7;
                            state <= FAILED;
                        end else begin
                            word_index <= 0;
                            halfword_index <= 0;
                            command_word <= 0;
                            input_base <= 0;
                            weight_base <= 0;
                            output_base <= 0;
                            state <= FETCH_REQ;
                        end
                    end
                    FETCH_REQ: if (mem_req_valid && mem_req_ready)
                        state <= FETCH_WAIT;
                    FETCH_WAIT: if (mem_rsp_valid && mem_rsp_ready) begin
                        if (fetch_bad_status || fetch_bad_data) begin
                            fault <= 1'b1;
                            saved_code <= fetch_bad_status ? 8'd5 : 8'd6;
                            state <= FAILED;
                        end else begin
                            command_word[16*halfword_index +: 16] <= mem_rsp_rdata;
                            if (halfword_index == 2'd3)
                                state <= SEND;
                            else begin
                                halfword_index <= halfword_index + 1'b1;
                                state <= FETCH_REQ;
                            end
                        end
                    end
                    SEND: begin
                        if (tail_is_exact && !ranges_disjoint) begin
                            fault <= 1'b1;
                            saved_code <= 4;
                            state <= FAILED;
                        end else if (core_cmd_valid && core_cmd_ready) begin
                            case (word_index)
                                21: input_base <= command_word[47:16];
                                27: weight_base <= command_word[47:16];
                                35: output_base <= command_word[47:16];
                                default: begin end
                            endcase
                            if (word_index == 6'd53) begin
                                state <= RUN;
                            end else begin
                                word_index <= word_index + 1'b1;
                                halfword_index <= 0;
                                state <= FETCH_REQ;
                            end
                        end
                    end
                    // The strict profile locks after one terminal QWORD. Hold the
                    // core in reset in REARM so the next descriptor starts from
                    // the same exact STREAM state, then release the wrapper.
                    RUN: if (core_done) begin
                        state <= REARM;
                        rearm_cycles <= 2'd0;
                    end
                    REARM: begin
                        rearm_cycles <= rearm_cycles + 1'b1;
                        if (rearm_cycles == 2'd2) begin
                            rearm_done <= 1'b1;
                            state <= IDLE;
                        end
                    end
                    FAILED: begin end
                    default: begin
                        fault <= 1'b1;
                        saved_code <= 7;
                        state <= FAILED;
                    end
                endcase

                if ((state == FETCH_REQ || state == FETCH_WAIT) &&
                    !(mem_req_valid && mem_req_ready) &&
                    !(mem_rsp_valid && mem_rsp_ready) &&
                    stalled_cycles >= TIMEOUT_CYCLES - 1) begin
                    fault <= 1'b1;
                    saved_code <= 8;
                    state <= FAILED;
                end
            end
        end
    end
endmodule
