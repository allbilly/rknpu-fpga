// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Strict 26-QWORD descriptor path for the two captured signed-INT8 C16 tasks.
//
// The endpoint fetches the raw command QWORDs unchanged through the serialized
// 16-bit memory interface, validates them with a separate strict raw profile,
// then runs the captured signed-INT8 2x2/stride-2 pooling leaf. Traffic is
// single-outstanding. There is no command rewrite, no CPU arithmetic and no
// runtime layout repair.
//
// start_amount is the exact raw command QWORD count and must be 26. The
// profile-published base addresses and their 64-byte input / 16-byte output
// windows are re-checked against the configured aperture, and overlap with the
// command block is rejected before any operand read or output write.
//
// The leaf and profile are held in reset while idle and released only after the
// complete raw command stream has been accepted, so a captured task always
// starts from a defined single-frame state.
module rk_ppu_pool_i8_k2s2_dma #(
    parameter logic [31:0] BASE = 32'h10000000,
    parameter logic [32:0] BYTES = 33'd1048576,
    parameter bit MINIMUM = 1'b0,
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
    localparam logic [32:0] COMMAND_BYTES = 33'd208;  // 26 QWORDs
    localparam logic [32:0] INPUT_BYTES = 33'd64;     // 4 atoms of 16 bytes
    localparam logic [32:0] OUTPUT_BYTES = 33'd16;    // 1 atom

    typedef enum logic [4:0] {
        ST_IDLE,
        ST_COMMAND_REQUEST, ST_COMMAND_RESPONSE,
        ST_GATE, ST_PROFILE,
        ST_INPUT_REQUEST, ST_INPUT_RESPONSE, ST_INPUT_SEND,
        ST_POOL_WAIT,
        ST_OUTPUT_REQUEST, ST_OUTPUT_RESPONSE,
        ST_FINISH, ST_FAILED
    } state_t;
    state_t state_q;

    logic [31:0] command_base_q;
    logic [32:0] command_end_q;
    logic [31:0] source_base_q, destination_base_q;
    logic [4:0]  fetch_qword_q, gate_qword_q;
    logic [1:0]  fetch_halfword_q;
    logic [47:0] fetch_word_lo_q;
    logic [63:0] command_qword [0:25];
    logic [31:0] wait_cycles_q;
    logic [7:0]  error_code_q;

    logic request_pending_q, outstanding_q;
    logic mem_req_write_q;
    logic [31:0] mem_req_addr_q;
    logic [15:0] mem_req_wdata_q;
    wire request_fire = request_pending_q && mem_req_ready;
    wire response_fire = outstanding_q && mem_rsp_valid && mem_rsp_ready;
    wire waiting_memory = request_pending_q || outstanding_q;

    logic profile_rst_n_q;
    logic profile_cmd_ready;
    logic profile_valid, profile_error, profile_busy;
    logic [31:0] profile_src_base, profile_dst_base;
    logic [31:0] profile_input_bytes, profile_output_bytes;
    logic [3:0]  profile_error_code;

    logic leaf_rst_n_q;
    logic leaf_in_valid, leaf_in_ready;
    logic [127:0] leaf_in_atom;
    logic leaf_out_valid, leaf_out_ready, leaf_out_last;
    logic [127:0] leaf_out_atom;

    logic [1:0]  input_beat_q;
    logic [3:0]  input_halfword_q, output_halfword_q;
    logic [127:0] input_atom_q, output_atom_q;

    logic bad_status, bad_read_data;
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
            $fatal(1, "invalid pooling DMA aperture");
        if (TIMEOUT_CYCLES == 0)
            $fatal(1, "pooling DMA timeout must be positive");
    end

    // ---- strict raw profile ----------------------------------------------
    rk_ppu_pool_i8_k2s2_profile #(.MINIMUM(MINIMUM)) profile (
        .clk, .rst_n(rst_n && profile_rst_n_q && state_q != ST_FAILED),
        .cmd_valid(state_q == ST_GATE && profile_cmd_ready), .cmd_ready(profile_cmd_ready),
        .cmd_data(command_qword[gate_qword_q]),
        .cmd_last(gate_qword_q == 5'd25),
        .profile_valid, .profile_ready(state_q == ST_PROFILE),
        .rdma_src_base(profile_src_base), .ppu_dst_base(profile_dst_base),
        .rdma_transfer_bytes(profile_input_bytes),
        .output_write_bytes(profile_output_bytes),
        .busy(profile_busy), .error(profile_error),
        .error_code(profile_error_code)
    );

    // ---- captured signed-INT8 leaf --------------------------------------
    rk_ppu_pool_int_k2s2 #(.ELEM_W(8), .LANES(16),
        .METHOD(MINIMUM ? 1 : 0)) leaf (
        .clk, .rst_n(rst_n && leaf_rst_n_q && state_q != ST_FAILED),
        .in_valid(leaf_in_valid), .in_ready(leaf_in_ready),
        .in_atom(leaf_in_atom),
        .out_valid(leaf_out_valid), .out_ready(leaf_out_ready),
        .out_atom(leaf_out_atom), .out_last(leaf_out_last)
    );

    assign leaf_in_valid = rst_n && state_q == ST_INPUT_SEND;
    assign leaf_in_atom = input_atom_q;
    assign leaf_out_ready = rst_n && state_q == ST_POOL_WAIT;

    // ---- serialized memory master ---------------------------------------
    assign mem_req_valid = rst_n && request_pending_q && state_q != ST_FAILED;
    assign mem_req_write = mem_req_write_q;
    assign mem_req_addr = mem_req_addr_q;
    assign mem_req_wdata = mem_req_wdata_q;
    assign mem_rsp_ready = rst_n &&
        (state_q == ST_COMMAND_RESPONSE ||
         state_q == ST_INPUT_RESPONSE ||
         state_q == ST_OUTPUT_RESPONSE);

    // ---- control ---------------------------------------------------------
    assign error = rst_n && state_q == ST_FAILED;
    assign error_code = !rst_n ? 8'd0 : error ? error_code_q : 8'd0;
    assign start_ready = rst_n && state_q == ST_IDLE && !waiting_memory;
    assign idle_quiet = state_q == ST_IDLE && !waiting_memory;
    assign quiescent = idle_quiet && !start_valid;
    // `done` is a one-cycle completion pulse consumed by the transport control,
    // which latches a result slot; `result_ready` only releases that slot.
    assign done = rst_n && state_q == ST_FINISH && result_ready;
    assign busy = rst_n && state_q != ST_IDLE && state_q != ST_FAILED && !done;

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

    // Synchronous reset: rst_n is already a synchronized deassertion, so an
    // asynchronous edge would add a second, unreviewed reset path.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state_q <= ST_IDLE;
            command_base_q <= 32'd0;
            command_end_q <= 33'd0;
            source_base_q <= 32'd0;
            destination_base_q <= 32'd0;
            fetch_qword_q <= 5'd0;
            fetch_halfword_q <= 2'd0;
            gate_qword_q <= 5'd0;
            fetch_word_lo_q <= 48'd0;
            input_beat_q <= 2'd0;
            input_halfword_q <= 4'd0;
            output_halfword_q <= 4'd0;
            input_atom_q <= 128'd0;
            output_atom_q <= 128'd0;
            wait_cycles_q <= 32'd0;
            request_pending_q <= 1'b0;
            outstanding_q <= 1'b0;
            mem_req_write_q <= 1'b0;
            mem_req_addr_q <= 32'd0;
            mem_req_wdata_q <= 16'd0;
            profile_rst_n_q <= 1'b0;
            leaf_rst_n_q <= 1'b0;
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
                         state_q != ST_OUTPUT_RESPONSE) begin
                fail(8'd6);
            end else if (waiting_memory && !request_fire && !response_fire &&
                         wait_cycles_q >= TIMEOUT_CYCLES - 1) begin
                fail(8'd8);
            end else begin
                if (!waiting_memory || request_fire || response_fire)
                    wait_cycles_q <= 32'd0;
                else
                    wait_cycles_q <= wait_cycles_q + 1'b1;

                case (state_q)
                    ST_IDLE: if (start_valid && start_ready) begin
                        // Hold the captured leaf and raw profile in reset until
                        // a complete command stream has been accepted.
                        profile_rst_n_q <= 1'b0;
                        leaf_rst_n_q <= 1'b0;
                        if (start_amount != 32'd26) begin
                            fail(8'd1);
                        end else if (start_address[2:0] != 3'b000 ||
                                     !in_aperture(start_address,
                                                  {1'b0, start_address} + COMMAND_BYTES)) begin
                            fail(8'd3);
                        end else begin
                            command_base_q <= start_address;
                            command_end_q <= {1'b0, start_address} + COMMAND_BYTES;
                            fetch_qword_q <= 5'd0;
                            fetch_halfword_q <= 2'd0;
                            gate_qword_q <= 5'd0;
                            input_beat_q <= 2'd0;
                            input_halfword_q <= 4'd0;
                            output_halfword_q <= 4'd0;
                            state_q <= ST_COMMAND_REQUEST;
                        end
                    end

                    ST_COMMAND_REQUEST: begin
                        issue_request(1'b0,
                            command_base_q +
                                32'(fetch_qword_q) * 32'd8 +
                                32'(fetch_halfword_q) * 32'd2,
                            16'd0);
                        state_q <= ST_COMMAND_RESPONSE;
                    end

                    ST_COMMAND_RESPONSE: if (response_fire) begin
                        if (fetch_halfword_q == 2'd3) begin
                            command_qword[fetch_qword_q] <=
                                {mem_rsp_rdata, fetch_word_lo_q};
                            if (fetch_qword_q == 5'd25) begin
                                // Release the profile only once the whole
                                // unchanged stream is buffered.
                                profile_rst_n_q <= 1'b1;
                                gate_qword_q <= 5'd0;
                                state_q <= ST_GATE;
                            end else begin
                                fetch_qword_q <= fetch_qword_q + 1'b1;
                                fetch_halfword_q <= 2'd0;
                                state_q <= ST_COMMAND_REQUEST;
                            end
                        end else begin
                            fetch_word_lo_q[16*fetch_halfword_q +: 16] <= mem_rsp_rdata;
                            fetch_halfword_q <= fetch_halfword_q + 1'b1;
                            state_q <= ST_COMMAND_REQUEST;
                        end
                    end

                    // The profile consumes one raw QWORD per accepted
                    // handshake. Advance the gate index only when the profile
                    // actually accepted the QWORD, so a collection stall
                    // cannot skip or duplicate a captured field.
                    ST_GATE: begin
                        if (profile_error) begin
                            fail({4'd0, profile_error_code});
                        end else if (profile_cmd_ready) begin
                            if (gate_qword_q == 5'd25) begin
                                state_q <= ST_PROFILE;
                            end else begin
                                gate_qword_q <= gate_qword_q + 1'b1;
                            end
                        end
                    end

                    ST_PROFILE: begin
                        if (profile_error) begin
                            fail({4'd0, profile_error_code});
                        end else if (profile_valid && !profile_busy) begin
                            // Publish with no collection in flight is never a
                            // legitimate state for this fixed profile.
                            fail(8'd6);
                        end else if (profile_valid) begin
                            source_base_q <= profile_src_base;
                            destination_base_q <= profile_dst_base;
                            if (33'(profile_input_bytes) != INPUT_BYTES ||
                                33'(profile_output_bytes) != OUTPUT_BYTES ||
                                !in_aperture(profile_src_base,
                                             {1'b0, profile_src_base} + INPUT_BYTES) ||
                                !in_aperture(profile_dst_base,
                                             {1'b0, profile_dst_base} + OUTPUT_BYTES) ||
                                ranges_overlap(profile_src_base,
                                               {1'b0, profile_src_base} + INPUT_BYTES,
                                               profile_dst_base,
                                               {1'b0, profile_dst_base} + OUTPUT_BYTES) ||
                                ranges_overlap(command_base_q,
                                               command_end_q,
                                               profile_src_base,
                                               {1'b0, profile_src_base} + INPUT_BYTES) ||
                                ranges_overlap(command_base_q,
                                               command_end_q,
                                               profile_dst_base,
                                               {1'b0, profile_dst_base} + OUTPUT_BYTES)) begin
                                fail(8'd3);
                            end else begin
                                // Both operands are in the aperture and the
                                // command block is disjoint: release the leaf.
                                leaf_rst_n_q <= 1'b1;
                                input_beat_q <= 2'd0;
                                input_halfword_q <= 4'd0;
                                state_q <= ST_INPUT_REQUEST;
                            end
                        end
                    end

                    ST_INPUT_REQUEST: begin
                        issue_request(1'b0,
                            source_base_q +
                                32'(input_beat_q) * 32'd16 +
                                32'(input_halfword_q) * 32'd2,
                            16'd0);
                        state_q <= ST_INPUT_RESPONSE;
                    end

                    ST_INPUT_RESPONSE: if (response_fire) begin
                        input_atom_q[input_halfword_q*16 +: 16] <= mem_rsp_rdata;
                        if (input_halfword_q == 4'd7) begin
                            state_q <= ST_INPUT_SEND;
                        end else begin
                            input_halfword_q <= input_halfword_q + 1'b1;
                            state_q <= ST_INPUT_REQUEST;
                        end
                    end

                    ST_INPUT_SEND: if (leaf_in_ready) begin
                        if (input_beat_q == 2'd3) begin
                            state_q <= ST_POOL_WAIT;
                        end else begin
                            input_beat_q <= input_beat_q + 1'b1;
                            input_halfword_q <= 4'd0;
                            state_q <= ST_INPUT_REQUEST;
                        end
                    end

                    ST_POOL_WAIT: if (leaf_out_valid) begin
                        if (leaf_out_last !== 1'b1) begin
                            fail(8'd6);
                        end else begin
                            output_atom_q <= leaf_out_atom;
                            output_halfword_q <= 4'd0;
                            state_q <= ST_OUTPUT_REQUEST;
                        end
                    end

                    ST_OUTPUT_REQUEST: begin
                        issue_request(1'b1,
                            destination_base_q +
                                32'(output_halfword_q) * 32'd2,
                            output_atom_q[output_halfword_q*16 +: 16]);
                        state_q <= ST_OUTPUT_RESPONSE;
                    end

                    ST_OUTPUT_RESPONSE: if (response_fire) begin
                        if (output_halfword_q == 4'd7) begin
                            state_q <= ST_FINISH;
                        end else begin
                            output_halfword_q <= output_halfword_q + 1'b1;
                            state_q <= ST_OUTPUT_REQUEST;
                        end
                    end

                    ST_FINISH: if (result_ready) begin
                        leaf_rst_n_q <= 1'b0;
                        profile_rst_n_q <= 1'b0;
                        state_q <= ST_IDLE;
                    end

                    default: fail(8'd7);
                endcase
            end
        end
    end
endmodule
