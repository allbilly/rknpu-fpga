// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Strict 52-QWORD descriptor path for one frozen `conv-simple` capture.
//
// start_amount counts the exact raw QWORDs of the captured job. Each QWORD is
// fetched through the serialized 16-bit memory interface as four unchanged
// little-endian halfwords and handed to `rk_conv_simple_core` in the same
// order. The core owns the strict profile gate and the convolution datapath;
// this wrapper owns the fetch, the aperture/overlap checks and the single-job
// rearm.
//
// The core is held in reset while idle and during REARM because its raw
// profile accepts exactly one stream per reset. Traffic is single-outstanding;
// there is no command rewrite, no CPU arithmetic and no runtime layout repair.
module rk_conv_simple_dma #(
    parameter int unsigned PROFILE = 0,
    // Spatial geometry, forwarded to the core. PROFILE selects the exact raw
    // register template; these parameters describe that template's shape. They
    // are separate because the raw table cannot be interrogated for geometry.
    parameter int unsigned INPUT_H = 8,
    parameter int unsigned INPUT_W = 8,
    parameter int unsigned KH = 3,
    parameter int unsigned KW = 3,
    parameter int unsigned INPUT_CHANNELS = 4,
    parameter int unsigned KERNELS = 8,
    parameter int unsigned C1_BLOCKS = 2,
    parameter int unsigned ALIGN_C = 8,
    parameter int unsigned PACK_C2 = 4,
    parameter int unsigned CHUNK_LANES = 16,
    parameter bit OUTPUT_FP16 = 1'b1,
    parameter logic [31:0] BASE = 32'h10000000,
    parameter logic [32:0] BYTES = 33'd1048576,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        start_valid,
    output logic        start_ready,
    input  logic [31:0] start_address,
    input  logic [31:0] start_amount,
    output logic        quiescent,
    output logic        idle_quiet,
    output logic        busy,
    output logic        done,
    output logic        error,
    output logic [7:0]  error_code,
    input  logic        result_ready,
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
    localparam logic [32:0] APERTURE_END = {1'b0, BASE} + BYTES;
    localparam int unsigned WORDS = 52;
    // 52 QWORDs; the width cast keeps the sum in 33 bits without wrapping.
    localparam logic [32:0] COMMAND_BYTES = 33'(WORDS * 8);
    localparam int unsigned LAST_WORD = WORDS - 2;  // PC trigger precedes padding

    typedef enum logic [2:0] {
        ST_IDLE, ST_FETCH_REQUEST, ST_FETCH_RESPONSE, ST_SEND, ST_RUN,
        ST_REARM, ST_FINISH, ST_FAILED
    } state_t;
    state_t state_q;

    logic [31:0] command_base_q;
    logic [32:0] command_end_q;
    logic [5:0]  word_index_q, send_index_q;
    logic [1:0]  halfword_index_q;
    logic [63:0] command_word_q;
    logic [31:0] wait_cycles_q;
    logic [1:0]  rearm_cycles_q;
    logic [7:0]  error_code_q;

    logic request_pending_q, outstanding_q;
    logic mem_req_write_q;
    logic [31:0] mem_req_addr_q;
    logic [15:0] mem_req_wdata_q;
    wire request_fire = request_pending_q && mem_req_ready;
    wire response_fire = outstanding_q && mem_rsp_valid && mem_rsp_ready;
    wire waiting_memory = request_pending_q || outstanding_q;

    logic core_cmd_ready, core_busy, core_done, core_acknowledged, core_frame_done;
    logic core_error, core_rst_n;
    logic [7:0] core_error_code;
    logic core_req_valid, core_req_write, core_rsp_ready;
    logic [31:0] core_req_addr, config_input_base, config_weight_base, config_output_base;
    logic [31:0] cfg_input_bytes, cfg_weight_bytes, cfg_output_bytes;
    logic [15:0] core_req_data;
    wire core_cmd_valid = rst_n && state_q == ST_SEND && core_cmd_ready;

    logic bad_status, bad_read_data, ranges_bad;
    always @* begin
        bad_status = mem_rsp_error;
        bad_read_data = 1'b0;
`ifndef SYNTHESIS
        if (mem_rsp_error !== 1'b0) bad_status = 1'b1;
        if ((^mem_rsp_rdata) === 1'bx) bad_read_data = 1'b1;
`endif
    end

    initial begin
        if (BYTES == 0 || APERTURE_END > 33'h100000000)
            $fatal(1, "invalid conv DMA aperture");
        if (TIMEOUT_CYCLES == 0)
            $fatal(1, "conv DMA timeout must be positive");
        if (PROFILE > 3)
            $fatal(1, "unsupported conv-simple DMA profile");
    end

    assign core_rst_n = rst_n && state_q != ST_IDLE && state_q != ST_REARM &&
                        state_q != ST_FAILED;
    assign mem_req_valid = rst_n && request_pending_q && state_q != ST_FAILED;
    assign mem_req_write = mem_req_write_q;
    assign mem_req_addr = mem_req_addr_q;
    assign mem_req_wdata = mem_req_wdata_q;
    assign mem_rsp_ready = rst_n &&
        (state_q == ST_FETCH_RESPONSE ||
         (state_q == ST_RUN && core_rsp_ready));

    assign error = rst_n && state_q == ST_FAILED;
    assign error_code = !rst_n ? 8'd0 : error ? error_code_q : 8'd0;
    assign start_ready = rst_n && state_q == ST_IDLE && !waiting_memory;
    assign idle_quiet = state_q == ST_IDLE && !waiting_memory;
    assign quiescent = idle_quiet && !start_valid;
    assign done = rst_n && state_q == ST_FINISH && result_ready;
    assign busy = rst_n && state_q != ST_IDLE && state_q != ST_FINISH &&
                  state_q != ST_FAILED;

    function automatic logic in_aperture(
        input logic [31:0] address,
        input logic [32:0] exclusive_end
    );
        in_aperture = ({1'b0, address} >= {1'b0, BASE}) &&
                      (exclusive_end <= APERTURE_END) &&
                      (exclusive_end > {1'b0, address});
    endfunction

    function automatic logic ranges_overlap(
        input logic [31:0] a_base,
        input logic [32:0] a_end,
        input logic [31:0] b_base,
        input logic [32:0] b_end
    );
        ranges_overlap = ({1'b0, a_base} < b_end) && ({1'b0, b_base} < a_end);
    endfunction

    // The command block must stay disjoint from every operand/output window,
    // otherwise the fetch would consume traffic the convolution later writes.
    always @* begin
        ranges_bad = ranges_overlap(command_base_q, command_end_q,
                                    config_input_base,
                                    {1'b0, config_input_base} + cfg_input_bytes) ||
                     ranges_overlap(command_base_q, command_end_q,
                                    config_weight_base,
                                    {1'b0, config_weight_base} + cfg_weight_bytes) ||
                     ranges_overlap(command_base_q, command_end_q,
                                    config_output_base,
                                    {1'b0, config_output_base} + cfg_output_bytes);
    end

    task automatic fail(input logic [7:0] code);
        begin
            state_q <= ST_FAILED;
            error_code_q <= code;
        end
    endtask

    task automatic issue_request(
        input logic is_write,
        input logic [31:0] address,
        input logic [15:0] write_data
    );
        begin
            request_pending_q <= 1'b1;
            mem_req_write_q <= is_write;
            mem_req_addr_q <= address;
            mem_req_wdata_q <= write_data;
        end
    endtask

    rk_conv_simple_core #(
        .PROFILE(PROFILE),
        .INPUT_H(INPUT_H), .INPUT_W(INPUT_W), .KH(KH), .KW(KW),
        .INPUT_CHANNELS(INPUT_CHANNELS), .KERNELS(KERNELS),
        .C1_BLOCKS(C1_BLOCKS), .ALIGN_C(ALIGN_C), .PACK_C2(PACK_C2),
        .CHUNK_LANES(CHUNK_LANES),
        .OUTPUT_FP16(OUTPUT_FP16),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) core (
        .clk, .rst_n(core_rst_n),
        .cmd_valid(core_cmd_valid), .cmd_ready(core_cmd_ready),
        .cmd_data(command_word_q),
        .cmd_last(send_index_q == 6'(LAST_WORD)),
        .busy(core_busy), .acknowledged(core_acknowledged),
        .frame_done(core_frame_done), .done(core_done),
        .error(core_error), .error_code(core_error_code),
        .mem_req_valid(core_req_valid),
        .mem_req_ready(mem_req_ready && state_q == ST_RUN && !error),
        .mem_req_write(core_req_write), .mem_req_addr(core_req_addr),
        .mem_req_wdata(core_req_data),
        .mem_rsp_valid(mem_rsp_valid && outstanding_q && state_q == ST_RUN &&
                       !error),
        .mem_rsp_ready(core_rsp_ready),
        .mem_rsp_rdata(mem_rsp_rdata), .mem_rsp_error(mem_rsp_error),
        // Observation ports for the wrapper's address checks. They are
        // outputs of the same profile that gates the command stream.
        .config_input_base(config_input_base),
        .config_weight_base(config_weight_base),
        .config_output_base(config_output_base),
        .input_bytes(cfg_input_bytes), .weight_bytes(cfg_weight_bytes),
        .output_bytes(cfg_output_bytes));

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= ST_IDLE;
            command_base_q <= 32'd0;
            command_end_q <= 33'd0;
            word_index_q <= 6'd0;
            send_index_q <= 6'd0;
            halfword_index_q <= 2'd0;
            command_word_q <= 64'd0;
            wait_cycles_q <= 32'd0;
            rearm_cycles_q <= 2'd0;
            request_pending_q <= 1'b0;
            outstanding_q <= 1'b0;
            mem_req_write_q <= 1'b0;
            mem_req_addr_q <= 32'd0;
            mem_req_wdata_q <= 16'd0;
            error_code_q <= 8'd0;
        end else if (state_q != ST_FAILED) begin
            if (request_fire) begin
                request_pending_q <= 1'b0;
                outstanding_q <= 1'b1;
            end
            if (response_fire) outstanding_q <= 1'b0;

            if (mem_rsp_valid && !outstanding_q) begin
                fail(8'd7);
            end else if (response_fire && bad_status) begin
                fail(8'd5);
            end else if (response_fire && bad_read_data &&
                         state_q != ST_RUN) begin
                fail(8'd6);
            end else if (waiting_memory && !request_fire && !response_fire &&
                         wait_cycles_q >= TIMEOUT_CYCLES - 1) begin
                fail(8'd8);
            end else begin
                if (!waiting_memory || request_fire || response_fire)
                    wait_cycles_q <= 32'd0;
                else
                    wait_cycles_q <= wait_cycles_q + 1'b1;

                // In RUN the core owns the bus: its request is issued through
                // the wrapper's single-outstanding path so the fetch and the
                // convolution can never have two masters in flight.
                if (state_q == ST_RUN && core_req_valid &&
                    !request_pending_q && !outstanding_q) begin
                    issue_request(core_req_write, core_req_addr, core_req_data);
                end

                case (state_q)
                    ST_IDLE: if (start_valid && start_ready) begin
                        if (start_amount != 32'(WORDS)) begin
                            fail(8'd1);
                        end else if (start_address[2:0] != 3'b000 ||
                                     !in_aperture(start_address,
                                                  {1'b0, start_address} + COMMAND_BYTES)) begin
                            fail(8'd3);
                        end else begin
                            command_base_q <= start_address;
                            command_end_q <= {1'b0, start_address} + COMMAND_BYTES;
                            word_index_q <= 6'd0;
                            send_index_q <= 6'd0;
                            halfword_index_q <= 2'd0;
                            command_word_q <= 64'd0;
                            state_q <= ST_FETCH_REQUEST;
                        end
                    end

                    ST_FETCH_REQUEST: begin
                        issue_request(1'b0,
                            command_base_q +
                                32'(word_index_q) * 32'd8 +
                                32'(halfword_index_q) * 32'd2,
                            16'd0);
                        state_q <= ST_FETCH_RESPONSE;
                    end

                    ST_FETCH_RESPONSE: if (response_fire) begin
                        if (halfword_index_q == 2'd3) begin
                            // Halfwords 0..2 are already in bits 47:0; the
                            // fourth read is the QWORD's most significant
                            // halfword, so it occupies bits 63:48.
                            command_word_q <= {mem_rsp_rdata,
                                               command_word_q[47:0]};
                            state_q <= ST_SEND;
                        end else begin
                            command_word_q[16*halfword_index_q +: 16] <= mem_rsp_rdata;
                            halfword_index_q <= halfword_index_q + 1'b1;
                            state_q <= ST_FETCH_REQUEST;
                        end
                    end

                    // One accepted word per cycle. Index 51 is the capture's
                    // padding word and is still presented; cmd_last asserts at
                    // index 50 only.
                    ST_SEND: begin
                        if (core_error) begin
                            fail(core_error_code);
                        end else if (core_cmd_valid) begin
                            if (send_index_q == 6'(WORDS - 1)) begin
                                if (ranges_bad || !in_aperture(config_input_base,
                                        {1'b0, config_input_base} + cfg_input_bytes) ||
                                    !in_aperture(config_weight_base,
                                        {1'b0, config_weight_base} + cfg_weight_bytes) ||
                                    !in_aperture(config_output_base,
                                        {1'b0, config_output_base} + cfg_output_bytes))
                                    fail(8'd3);
                                else
                                    state_q <= ST_RUN;
                            end else begin
                                send_index_q <= send_index_q + 1'b1;
                                word_index_q <= word_index_q + 1'b1;
                                halfword_index_q <= 2'd0;
                                command_word_q <= 64'd0;
                                state_q <= ST_FETCH_REQUEST;
                            end
                        end
                    end

                    ST_RUN: begin
                        if (core_error) begin
                            fail(core_error_code);
                        end else if (core_done) begin
                            state_q <= ST_REARM;
                            rearm_cycles_q <= 2'd0;
                        end
                    end

                    ST_REARM: begin
                        rearm_cycles_q <= rearm_cycles_q + 1'b1;
                        if (rearm_cycles_q == 2'd2)
                            state_q <= ST_FINISH;
                    end

                    ST_FINISH: if (result_ready) begin
                        state_q <= ST_IDLE;
                    end

                    default: fail(8'd7);
                endcase
            end
        end
    end
endmodule
