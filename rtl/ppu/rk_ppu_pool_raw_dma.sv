// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Source/capture-bounded C3/C8 PPU command/DMA engine for the K8 UI memory request path.
//
// start_amount is the exact raw command QWORD count (26 or 28 for the distinct
// supported profiles). The engine fetches those QWORDs unchanged through the
// serialized 16-bit UI memory interface and validates them with a separate
// strict raw profile. C3 reads 64 bytes and writes 16; valid-C8 MAX, C8 minimum
// and C8 average read 256 bytes; padded-negative C8 reads 64 bytes. The C8
// surfaces buffer their complete results before output writes. Traffic is
// single-outstanding; there is no command rewrite, CPU arithmetic, or BO repair.
module rk_ppu_pool_raw_dma #(
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
    localparam logic [32:0] COMMAND_26_BYTES = 33'd208;
    localparam logic [32:0] COMMAND_28_BYTES = 33'd224;
    localparam logic [32:0] C3_INPUT_BYTES = 33'd64;
    localparam logic [32:0] C3_OUTPUT_BYTES = 33'd16;
    localparam logic [32:0] C8_INPUT_BYTES = 33'd256;
    localparam logic [32:0] GLOBAL_INPUT_BYTES = 33'd4096;
    localparam logic [32:0] GLOBAL_AVG_INPUT_BYTES = 33'd240;
    localparam logic [32:0] C8_OUTPUT_BYTES = 33'd144;
    localparam logic [32:0] PAD1_INPUT_BYTES = 33'd64;
    localparam logic [32:0] INDEX_OUTPUT_SPAN_BYTES = 33'd48;

    typedef enum logic [4:0] {
        ST_IDLE,
        ST_COMMAND_REQUEST,
        ST_COMMAND_RESPONSE,
        ST_GATE,
        ST_PROFILE,
        ST_INPUT_REQUEST,
        ST_INPUT_RESPONSE,
        ST_INPUT_SEND,
        ST_POOL_WAIT,
        ST_OUTPUT_REQUEST,
        ST_OUTPUT_RESPONSE,
        ST_OUTPUT_RELEASE,
        ST_C8_INPUT_REQUEST,
        ST_C8_INPUT_RESPONSE,
        ST_C8_INPUT_SEND,
        ST_C8_COLLECT,
        ST_C8_OUTPUT_REQUEST,
        ST_C8_OUTPUT_RESPONSE,
        ST_FINISH,
        ST_FAILED
    } state_t;

    state_t state_q;
    logic [31:0] command_address_q;
    logic [32:0] command_end_q;
    logic [5:0] command_qwords_q;
    logic [4:0] fetch_qword_q;
    logic [1:0] fetch_halfword_q;
    logic [47:0] fetch_word_lo_q;
    logic [63:0] command_qword [0:27];
    logic [4:0] gate_qword_q;
    logic [11:0] input_halfword_q;
    logic [7:0] input_atom_q;
    logic [127:0] input_atom_data_q;
    logic [6:0] output_halfword_q;
    logic [3:0] c8_output_count_q;
    logic [127:0] c8_output_atoms [0:8];
    logic [31:0] wait_cycles_q;
    logic request_pending_q;
    logic outstanding_q;
    logic pool_leaf_rst_n_q;
    logic profile_gate_rst_n_q;
    logic c8_selected_q;
    logic pad1_selected_q;
    logic min_selected_q;
    logic avg_selected_q;
    logic index_selected_q;
    logic global_selected_q;
    logic global_avg_selected_q;
    logic [127:0] index_value_atom_q;
    logic [127:0] index_index_atom_q;
    logic mem_req_write_q;
    logic [31:0] mem_req_addr_q;
    logic [15:0] mem_req_wdata_q;
    logic [7:0] error_code_q;

    wire request_fire = mem_req_valid && mem_req_ready;
    wire response_fire = mem_rsp_valid && mem_rsp_ready;
    wire waiting_memory = state_q == ST_COMMAND_RESPONSE ||
                         state_q == ST_INPUT_RESPONSE ||
                         state_q == ST_OUTPUT_RESPONSE ||
                         state_q == ST_C8_INPUT_RESPONSE ||
                         state_q == ST_C8_OUTPUT_RESPONSE;
    wire [32:0] aperture_end = {1'b0, BASE} + BYTES;
    wire [32:0] start_command_bytes = start_amount == 32'd28 ? COMMAND_28_BYTES :
        start_amount == 32'd26 ? COMMAND_26_BYTES : 33'd0;
    wire [32:0] start_command_end = {1'b0, start_address} + start_command_bytes;
    wire [31:0] c3_source_base, c3_destination_base;
    wire [31:0] c8_source_base, c8_destination_base;
    wire [31:0] pad1_source_base, pad1_destination_base;
    wire [31:0] min_source_base, min_destination_base;
    wire [31:0] avg_source_base, avg_destination_base;
    wire [31:0] index_source_base, index_destination_base;
    wire [31:0] global_source_base, global_destination_base;
    wire [31:0] global_avg_source_base, global_avg_destination_base;
    wire buffered_selected = c8_selected_q || pad1_selected_q || min_selected_q ||
                             avg_selected_q || index_selected_q || global_selected_q ||
                             global_avg_selected_q;
    wire [31:0] profile_source_base = c8_selected_q ? c8_source_base :
        pad1_selected_q ? pad1_source_base :
        min_selected_q ? min_source_base :
        avg_selected_q ? avg_source_base :
        index_selected_q ? index_source_base :
        global_avg_selected_q ? global_avg_source_base :
        global_selected_q ? global_source_base : c3_source_base;
    wire [31:0] profile_destination_base = c8_selected_q ? c8_destination_base :
        pad1_selected_q ? pad1_destination_base :
        min_selected_q ? min_destination_base :
        avg_selected_q ? avg_destination_base :
        index_selected_q ? index_destination_base :
        global_avg_selected_q ? global_avg_destination_base :
        global_selected_q ? global_destination_base : c3_destination_base;
    wire [31:0] c3_input_bytes, c3_output_bytes;
    wire [31:0] c8_input_bytes, c8_output_bytes;
    wire [31:0] pad1_input_bytes, pad1_output_bytes;
    wire [31:0] min_input_bytes, min_output_bytes;
    wire [31:0] avg_input_bytes, avg_output_bytes;
    wire [31:0] index_input_bytes, index_output_bytes;
    wire [31:0] global_input_bytes, global_output_bytes;
    wire [31:0] global_avg_input_bytes, global_avg_output_bytes;
    wire [31:0] profile_input_bytes = c8_selected_q ? c8_input_bytes :
        pad1_selected_q ? pad1_input_bytes :
        min_selected_q ? min_input_bytes :
        avg_selected_q ? avg_input_bytes :
        index_selected_q ? index_input_bytes :
        global_avg_selected_q ? global_avg_input_bytes :
        global_selected_q ? global_input_bytes : c3_input_bytes;
    wire [31:0] profile_output_bytes = c8_selected_q ? c8_output_bytes :
        pad1_selected_q ? pad1_output_bytes :
        min_selected_q ? min_output_bytes :
        avg_selected_q ? avg_output_bytes :
        index_selected_q ? index_output_bytes :
        global_avg_selected_q ? global_avg_output_bytes :
        global_selected_q ? global_output_bytes : c3_output_bytes;
    wire [31:0] c8_output_write_offset = index_selected_q ?
        (output_halfword_q < 7'd8 ? {24'd0, output_halfword_q, 1'b0} :
         32'd32 + {24'd0, (output_halfword_q - 7'd8), 1'b0}) :
        {24'd0, output_halfword_q, 1'b0};
    wire [15:0] c8_output_write_data = index_selected_q ?
        (output_halfword_q < 7'd8 ?
         index_value_atom_q[output_halfword_q[2:0]*16 +: 16] :
         index_index_atom_q[(output_halfword_q - 7'd8)*16 +: 16]) :
        c8_output_atoms[output_halfword_q[6:3]][output_halfword_q[2:0]*16 +: 16];
    wire [32:0] source_end = {1'b0, profile_source_base} +
        (global_avg_selected_q ? GLOBAL_AVG_INPUT_BYTES :
         global_selected_q ? GLOBAL_INPUT_BYTES :
         ((c8_selected_q || min_selected_q || avg_selected_q) ? C8_INPUT_BYTES :
          pad1_selected_q ? PAD1_INPUT_BYTES : C3_INPUT_BYTES));
    wire [32:0] destination_end = {1'b0, profile_destination_base} +
        (index_selected_q ? INDEX_OUTPUT_SPAN_BYTES :
          (global_avg_selected_q || global_selected_q) ? 33'd16 :
         buffered_selected ? C8_OUTPUT_BYTES : C3_OUTPUT_BYTES);
    wire gate_valid, gate_ready, gate_last;
    wire gate_profile_valid, gate_error, gate_busy;
    wire c3_gate_ready, c3_gate_profile_valid, c3_gate_error, c3_gate_busy;
    wire c8_gate_ready, c8_gate_profile_valid, c8_gate_error, c8_gate_busy;
    wire pad1_gate_ready, pad1_gate_profile_valid, pad1_gate_error, pad1_gate_busy;
    wire min_gate_ready, min_gate_profile_valid, min_gate_error, min_gate_busy;
    wire avg_gate_ready, avg_gate_profile_valid, avg_gate_error, avg_gate_busy;
    wire [3:0] gate_error_code;
    wire [3:0] c3_gate_error_code;
    wire [3:0] c8_gate_error_code;
    wire [3:0] pad1_gate_error_code;
    wire [3:0] min_gate_error_code;
    wire [3:0] avg_gate_error_code;
    wire index_gate_ready, index_gate_profile_valid, index_gate_error, index_gate_busy;
    wire [3:0] index_gate_error_code;
    wire global_gate_ready, global_gate_profile_valid, global_gate_error, global_gate_busy;
    wire [3:0] global_gate_error_code;
    wire global_avg_gate_ready, global_avg_gate_profile_valid;
    wire global_avg_gate_error, global_avg_gate_busy;
    wire [3:0] global_avg_gate_error_code;
    wire [12:0] unused_rdma_width, unused_rdma_height, unused_rdma_channels;
    wire [31:0] unused_rdma_line_stride, unused_rdma_surface_stride;
    wire [1:0] unused_rdma_format;
    wire [12:0] unused_ppu_in_width, unused_ppu_in_height, unused_ppu_in_channels;
    wire [12:0] unused_ppu_out_width, unused_ppu_out_height, unused_ppu_out_channels;
    wire [3:0] unused_kernel_width, unused_kernel_height;
    wire [3:0] unused_stride_width, unused_stride_height;
    wire [14:0] unused_padding_cfg;
    wire [1:0] unused_pool_method;
    wire unused_ppu_flying, unused_index_en;
    wire [2:0] unused_use_cnt;
    wire [31:0] unused_data_format, unused_output_stride;
    wire [3:0] unused_burst_len;
    wire pool_in_ready, pool_out_valid, pool_out_last;
    wire [127:0] pool_out_atom;
    wire pool_out_ready;
    wire c3_pool_in_ready, c3_pool_out_valid, c3_pool_out_last, c3_pool_out_ready;
    wire [127:0] c3_pool_out_atom;
    wire c8_pool_in_ready, c8_pool_out_valid, c8_pool_out_last, c8_pool_out_ready;
    wire [127:0] c8_pool_out_atom;
    wire pad1_pool_in_ready, pad1_pool_out_valid, pad1_pool_out_last, pad1_pool_out_ready;
    wire [127:0] pad1_pool_out_atom;
    wire min_pool_in_ready, min_pool_out_valid, min_pool_out_last, min_pool_out_ready;
    wire [127:0] min_pool_out_atom;
    wire avg_pool_in_ready, avg_pool_out_valid, avg_pool_out_last, avg_pool_out_ready;
    wire [127:0] avg_pool_out_atom;
    wire index_pool_in_ready, index_pool_out_valid, index_pool_out_last;
    wire index_pool_out_ready;
    wire [127:0] index_pool_value_atom, index_pool_index_atom;
    wire [7:0] index_pool_unique;
    wire global_pool_in_ready, global_pool_out_valid, global_pool_out_last;
    wire global_pool_out_ready;
    wire [127:0] global_pool_out_atom;
    wire global_avg_pool_in_ready, global_avg_pool_out_valid, global_avg_pool_out_last;
    wire global_avg_pool_out_ready;
    wire [127:0] global_avg_pool_out_atom;
    wire c8_capture_state = state_q == ST_C8_INPUT_REQUEST ||
                            state_q == ST_C8_INPUT_RESPONSE ||
                            state_q == ST_C8_INPUT_SEND ||
                            state_q == ST_C8_COLLECT;
    logic bad_c8_input, bad_pad1_input, bad_min_input, bad_avg_input;
    logic bad_index_input, bad_global_input, bad_global_avg_input, bad_c8_output;
    wire pool_leaf_rst_n = rst_n && pool_leaf_rst_n_q;
    logic bad_status, bad_read_data;

    function automatic logic in_aperture(
        input logic [31:0] address,
        input logic [32:0] exclusive_end
    );
        in_aperture = ({1'b0, address} >= {1'b0, BASE}) &&
                      (exclusive_end <= aperture_end) &&
                      (exclusive_end > {1'b0, address});
    endfunction

    function automatic logic ranges_overlap(
        input logic [31:0] a,
        input logic [32:0] a_end,
        input logic [31:0] b,
        input logic [32:0] b_end
    );
        ranges_overlap = ({1'b0, a} < b_end) && ({1'b0, b} < a_end);
    endfunction

    task automatic fail(input logic [7:0] code);
        begin
            state_q <= ST_FAILED;
            error_code_q <= code;
            pool_leaf_rst_n_q <= 1'b0;
            profile_gate_rst_n_q <= 1'b0;
            // Preserve held requests/outstanding responses for coordinated reset.
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

    always_comb begin
        bad_status = mem_rsp_error;
        bad_read_data = 1'b0;
        bad_c8_input = 1'b0;
        bad_pad1_input = 1'b0;
        bad_min_input = 1'b0;
        bad_avg_input = 1'b0;
        bad_index_input = 1'b0;
        bad_global_input = 1'b0;
        bad_global_avg_input = 1'b0;
        bad_c8_output = 1'b0;
`ifndef SYNTHESIS
        if (mem_rsp_error !== 1'b0)
            bad_status = 1'b1;
        if ((^mem_rsp_rdata) === 1'bx)
            bad_read_data = 1'b1;
        if ((^mem_rsp_rdata) === 1'bx)
            bad_c8_input = 1'b1;
        if ((^mem_rsp_rdata) === 1'bx)
            bad_index_input = 1'b1;
        if ((^mem_rsp_rdata) === 1'bx)
            bad_global_input = 1'b1;
        if ((^pool_out_atom) === 1'bx)
            bad_c8_output = 1'b1;
`endif
        if (mem_rsp_rdata[14:10] == 5'h1f ||
            (mem_rsp_rdata[14:10] == 5'd0 &&
             ((mem_rsp_rdata[9:0] != 10'd0) || mem_rsp_rdata[15])))
            bad_c8_input = 1'b1;
        // The captured padded case admits finite-negative normal FP16 input.
        // Its -infinity padding is generated by the fixed leaf, not read from BO.
        if (!mem_rsp_rdata[15] || mem_rsp_rdata[14:10] == 5'd0 ||
            mem_rsp_rdata[14:10] == 5'h1f)
            bad_pad1_input = 1'b1;
        // The pinned minimum capture contains finite normals plus one +0.
        // Reject negative zero, subnormals, infinities and NaNs explicitly.
        if (mem_rsp_rdata[14:10] == 5'h1f || mem_rsp_rdata == 16'h8000 ||
            (mem_rsp_rdata[14:10] == 5'd0 && mem_rsp_rdata[9:0] != 10'd0))
            bad_min_input = 1'b1;
        // The index capture admits finite normals and +0 only. The output
        // is published only when the leaf confirms one unique maximum/lane.
        if (mem_rsp_rdata[14:10] == 5'h1f || mem_rsp_rdata == 16'h8000 ||
            (mem_rsp_rdata[14:10] == 5'd0 && mem_rsp_rdata[9:0] != 10'd0))
            bad_index_input = 1'b1;
        // The source-emitted probe spans [0, 2047] as FP16. Admit only +0 and
        // positive normals within that range; the fixed case does not establish
        // a broader signed/special-value policy.
        if (mem_rsp_rdata[15] || mem_rsp_rdata[14:10] == 5'h1f ||
            (mem_rsp_rdata[14:10] == 5'd0 && mem_rsp_rdata[9:0] != 10'd0) ||
            mem_rsp_rdata > 16'h67ff)
            bad_global_input = 1'b1;
        // The captured H3/W5 source spans +0 through +14.875. This fixed
        // candidate admits only nonnegative finite values in that interval.
        if (mem_rsp_rdata[15] || mem_rsp_rdata[14:10] == 5'h1f ||
            (mem_rsp_rdata[14:10] == 5'd0 && mem_rsp_rdata[9:0] != 10'd0) ||
            mem_rsp_rdata > 16'h4b70)
            bad_global_avg_input = 1'b1;
        // The average leaf is admitted only for the captured finite-normal
        // range [-4, 11.875] plus +0. Reject exceptional encodings, subnormals,
        // negative zero, and values outside that source-backed interval.
        if (mem_rsp_rdata[14:10] == 5'h1f || mem_rsp_rdata == 16'h8000 ||
            (mem_rsp_rdata[14:10] == 5'd0 && mem_rsp_rdata[9:0] != 10'd0) ||
            (mem_rsp_rdata[15] && mem_rsp_rdata[14:0] > 15'h4400) ||
            (!mem_rsp_rdata[15] && mem_rsp_rdata > 16'h49f0))
            bad_avg_input = 1'b1;
        if ((index_selected_q &&
             (c8_output_count_q != 4'd0 || pool_out_last !== 1'b1 ||
              index_pool_unique !== 8'hff ||
              (^index_pool_index_atom) === 1'bx)) ||
            (global_selected_q &&
             (c8_output_count_q != 4'd0 || global_pool_out_last !== 1'b1)) ||
            (global_avg_selected_q &&
             (c8_output_count_q != 4'd0 || global_avg_pool_out_last !== 1'b1)) ||
            (!index_selected_q && !global_selected_q && !global_avg_selected_q &&
             (c8_output_count_q > 4'd8 ||
              pool_out_last !== (c8_output_count_q == 4'd8))))
            bad_c8_output = 1'b1;
    end

    assign start_ready = rst_n && state_q == ST_IDLE &&
                         !request_pending_q && !outstanding_q;
    assign idle_quiet = state_q == ST_IDLE && !request_pending_q && !outstanding_q;
    assign quiescent = idle_quiet && !start_valid;
    assign busy = rst_n && state_q != ST_IDLE && state_q != ST_FAILED;
    assign done = rst_n && state_q == ST_FINISH;
    assign error = rst_n && state_q == ST_FAILED;
    assign error_code = error ? error_code_q : 8'd0;
    assign mem_req_valid = rst_n && request_pending_q;
    assign mem_req_write = mem_req_write_q;
    assign mem_req_addr = mem_req_addr_q;
    assign mem_req_wdata = mem_req_wdata_q;
    assign mem_rsp_ready = rst_n && (outstanding_q || state_q == ST_FAILED);

    assign gate_valid = rst_n && state_q == ST_GATE;
    assign gate_last = gate_qword_q == ((avg_selected_q || global_avg_selected_q) ? 5'd27 : 5'd25);
    assign gate_ready = c8_selected_q ? c8_gate_ready :
        pad1_selected_q ? pad1_gate_ready :
        min_selected_q ? min_gate_ready :
        avg_selected_q ? avg_gate_ready :
        index_selected_q ? index_gate_ready :
        global_avg_selected_q ? global_avg_gate_ready :
        global_selected_q ? global_gate_ready : c3_gate_ready;
    assign gate_profile_valid = c8_selected_q ? c8_gate_profile_valid :
        pad1_selected_q ? pad1_gate_profile_valid :
        min_selected_q ? min_gate_profile_valid :
        avg_selected_q ? avg_gate_profile_valid :
        index_selected_q ? index_gate_profile_valid :
        global_avg_selected_q ? global_avg_gate_profile_valid :
        global_selected_q ? global_gate_profile_valid : c3_gate_profile_valid;
    assign gate_error = c8_selected_q ? c8_gate_error :
        pad1_selected_q ? pad1_gate_error :
        min_selected_q ? min_gate_error :
        avg_selected_q ? avg_gate_error :
        index_selected_q ? index_gate_error :
        global_avg_selected_q ? global_avg_gate_error :
        global_selected_q ? global_gate_error : c3_gate_error;
    assign gate_error_code = c8_selected_q ? c8_gate_error_code :
        pad1_selected_q ? pad1_gate_error_code :
        min_selected_q ? min_gate_error_code :
        avg_selected_q ? avg_gate_error_code :
        index_selected_q ? index_gate_error_code :
        global_avg_selected_q ? global_avg_gate_error_code :
        global_selected_q ? global_gate_error_code : c3_gate_error_code;
    assign gate_busy = c8_selected_q ? c8_gate_busy :
        pad1_selected_q ? pad1_gate_busy :
        min_selected_q ? min_gate_busy :
        avg_selected_q ? avg_gate_busy :
        index_selected_q ? index_gate_busy :
        global_avg_selected_q ? global_avg_gate_busy :
        global_selected_q ? global_gate_busy : c3_gate_busy;
    assign pool_in_ready = c8_selected_q ? c8_pool_in_ready :
        pad1_selected_q ? pad1_pool_in_ready :
        min_selected_q ? min_pool_in_ready :
        avg_selected_q ? avg_pool_in_ready :
        index_selected_q ? index_pool_in_ready :
        global_avg_selected_q ? global_avg_pool_in_ready :
        global_selected_q ? global_pool_in_ready : c3_pool_in_ready;
    assign pool_out_valid = c8_selected_q ? c8_pool_out_valid :
        pad1_selected_q ? pad1_pool_out_valid :
        min_selected_q ? min_pool_out_valid :
        avg_selected_q ? avg_pool_out_valid :
        index_selected_q ? index_pool_out_valid :
        global_avg_selected_q ? global_avg_pool_out_valid :
        global_selected_q ? global_pool_out_valid : c3_pool_out_valid;
    assign pool_out_last = c8_selected_q ? c8_pool_out_last :
        pad1_selected_q ? pad1_pool_out_last :
        min_selected_q ? min_pool_out_last :
        avg_selected_q ? avg_pool_out_last :
        index_selected_q ? index_pool_out_last :
        global_avg_selected_q ? global_avg_pool_out_last :
        global_selected_q ? global_pool_out_last : c3_pool_out_last;
    assign pool_out_atom = c8_selected_q ? c8_pool_out_atom :
        pad1_selected_q ? pad1_pool_out_atom :
        min_selected_q ? min_pool_out_atom :
        avg_selected_q ? avg_pool_out_atom :
        index_selected_q ? index_pool_value_atom :
        global_avg_selected_q ? global_avg_pool_out_atom :
        global_selected_q ? global_pool_out_atom : c3_pool_out_atom;
    assign pool_out_ready = c8_selected_q ? c8_pool_out_ready :
        pad1_selected_q ? pad1_pool_out_ready :
        min_selected_q ? min_pool_out_ready :
        avg_selected_q ? avg_pool_out_ready :
        index_selected_q ? index_pool_out_ready :
        global_avg_selected_q ? global_avg_pool_out_ready :
        global_selected_q ? global_pool_out_ready : c3_pool_out_ready;
    assign c3_pool_out_ready = rst_n && !buffered_selected && state_q == ST_OUTPUT_RELEASE;
    assign c8_pool_out_ready = rst_n && c8_selected_q && c8_capture_state &&
                               c8_output_count_q < 4'd9;
    assign pad1_pool_out_ready = rst_n && pad1_selected_q && c8_capture_state &&
                                 c8_output_count_q < 4'd9;
    assign min_pool_out_ready = rst_n && min_selected_q && c8_capture_state &&
                                c8_output_count_q < 4'd9;
    assign avg_pool_out_ready = rst_n && avg_selected_q && c8_capture_state &&
                                c8_output_count_q < 4'd9;
    assign index_pool_out_ready = rst_n && index_selected_q && c8_capture_state &&
                                  c8_output_count_q == 4'd0;
    assign global_pool_out_ready = rst_n && global_selected_q && c8_capture_state &&
                                   c8_output_count_q == 4'd0;
    assign global_avg_pool_out_ready = rst_n && global_avg_selected_q && c8_capture_state &&
                                       c8_output_count_q == 4'd0;

    rk_ppu_pool_c3_raw_profile profile_gate (
        .clk, .rst_n(profile_gate_rst_n_q && rst_n),
        .cmd_valid(gate_valid && !buffered_selected), .cmd_ready(c3_gate_ready),
        .cmd_data(command_qword[gate_qword_q]), .cmd_last(gate_last),
        .profile_valid(c3_gate_profile_valid),
        .profile_ready(state_q == ST_PROFILE && !buffered_selected),
        .rdma_src_base(c3_source_base), .ppu_dst_base(c3_destination_base),
        .rdma_input_width_m1(unused_rdma_width),
        .rdma_input_height_m1(unused_rdma_height),
        .rdma_input_channels_m1(unused_rdma_channels),
        .rdma_line_stride_bytes(unused_rdma_line_stride),
        .rdma_surface_stride_bytes(unused_rdma_surface_stride),
        .rdma_format(unused_rdma_format),
        .ppu_input_width_m1(unused_ppu_in_width),
        .ppu_input_height_m1(unused_ppu_in_height),
        .ppu_input_channels_m1(unused_ppu_in_channels),
        .ppu_output_width_m1(unused_ppu_out_width),
        .ppu_output_height_m1(unused_ppu_out_height),
        .ppu_output_channels_m1(unused_ppu_out_channels),
        .kernel_width_m1(unused_kernel_width),
        .kernel_height_m1(unused_kernel_height),
        .stride_width_m1(unused_stride_width),
        .stride_height_m1(unused_stride_height),
        .padding_cfg(unused_padding_cfg), .pool_method(unused_pool_method),
        .ppu_flying(unused_ppu_flying), .index_en(unused_index_en),
        .use_cnt(unused_use_cnt), .output_data_format(unused_data_format),
        .output_surface_stride_bytes(unused_output_stride),
        .output_burst_len(unused_burst_len),
        .rdma_transfer_bytes(c3_input_bytes),
        .output_write_bytes(c3_output_bytes),
        .busy(c3_gate_busy), .error(c3_gate_error), .error_code(c3_gate_error_code)
    );

    rk_ppu_pool_c8_raw_profile c8_profile_gate (
        .clk, .rst_n(profile_gate_rst_n_q && rst_n),
        .cmd_valid(gate_valid && c8_selected_q), .cmd_ready(c8_gate_ready),
        .cmd_data(command_qword[gate_qword_q]), .cmd_last(gate_last),
        .profile_valid(c8_gate_profile_valid),
        .profile_ready(state_q == ST_PROFILE && c8_selected_q),
        .rdma_src_base(c8_source_base), .ppu_dst_base(c8_destination_base),
        .rdma_transfer_bytes(c8_input_bytes), .output_write_bytes(c8_output_bytes),
        .busy(c8_gate_busy), .error(c8_gate_error), .error_code(c8_gate_error_code)
    );

    rk_ppu_pool_pad1_raw_profile pad1_profile_gate (
        .clk, .rst_n(profile_gate_rst_n_q && rst_n),
        .cmd_valid(gate_valid && pad1_selected_q), .cmd_ready(pad1_gate_ready),
        .cmd_data(command_qword[gate_qword_q]), .cmd_last(gate_last),
        .profile_valid(pad1_gate_profile_valid),
        .profile_ready(state_q == ST_PROFILE && pad1_selected_q),
        .rdma_src_base(pad1_source_base), .ppu_dst_base(pad1_destination_base),
        .rdma_transfer_bytes(pad1_input_bytes), .output_write_bytes(pad1_output_bytes),
        .busy(pad1_gate_busy), .error(pad1_gate_error),
        .error_code(pad1_gate_error_code)
    );

    rk_ppu_pool_min_raw_profile min_profile_gate (
        .clk, .rst_n(profile_gate_rst_n_q && rst_n),
        .cmd_valid(gate_valid && min_selected_q), .cmd_ready(min_gate_ready),
        .cmd_data(command_qword[gate_qword_q]), .cmd_last(gate_last),
        .profile_valid(min_gate_profile_valid),
        .profile_ready(state_q == ST_PROFILE && min_selected_q),
        .rdma_src_base(min_source_base), .ppu_dst_base(min_destination_base),
        .rdma_transfer_bytes(min_input_bytes), .output_write_bytes(min_output_bytes),
        .busy(min_gate_busy), .error(min_gate_error),
        .error_code(min_gate_error_code)
    );

    rk_ppu_pool_avg_raw_profile avg_profile_gate (
        .clk, .rst_n(profile_gate_rst_n_q && rst_n),
        .cmd_valid(gate_valid && avg_selected_q), .cmd_ready(avg_gate_ready),
        .cmd_data(command_qword[gate_qword_q]), .cmd_last(gate_last),
        .profile_valid(avg_gate_profile_valid),
        .profile_ready(state_q == ST_PROFILE && avg_selected_q),
        .rdma_src_base(avg_source_base), .ppu_dst_base(avg_destination_base),
        .rdma_transfer_bytes(avg_input_bytes), .output_write_bytes(avg_output_bytes),
        .busy(avg_gate_busy), .error(avg_gate_error),
        .error_code(avg_gate_error_code)
    );

    rk_ppu_pool_index_raw_profile index_profile_gate (
        .clk, .rst_n(profile_gate_rst_n_q && rst_n),
        .cmd_valid(gate_valid && index_selected_q), .cmd_ready(index_gate_ready),
        .cmd_data(command_qword[gate_qword_q]), .cmd_last(gate_last),
        .profile_valid(index_gate_profile_valid),
        .profile_ready(state_q == ST_PROFILE && index_selected_q),
        .rdma_src_base(index_source_base), .ppu_dst_base(index_destination_base),
        .rdma_transfer_bytes(index_input_bytes), .output_write_bytes(index_output_bytes),
        .busy(index_gate_busy), .error(index_gate_error),
        .error_code(index_gate_error_code)
    );

    rk_ppu_pool_global_raw_profile global_profile_gate (
        .clk, .rst_n(profile_gate_rst_n_q && rst_n),
        .cmd_valid(gate_valid && global_selected_q), .cmd_ready(global_gate_ready),
        .cmd_data(command_qword[gate_qword_q]), .cmd_last(gate_last),
        .profile_valid(global_gate_profile_valid),
        .profile_ready(state_q == ST_PROFILE && global_selected_q),
        .rdma_src_base(global_source_base), .ppu_dst_base(global_destination_base),
        .rdma_transfer_bytes(global_input_bytes), .output_write_bytes(global_output_bytes),
        .busy(global_gate_busy), .error(global_gate_error),
        .error_code(global_gate_error_code)
    );

    rk_ppu_pool_global_avg_raw_profile global_avg_profile_gate (
        .clk, .rst_n(profile_gate_rst_n_q && rst_n),
        .cmd_valid(gate_valid && global_avg_selected_q), .cmd_ready(global_avg_gate_ready),
        .cmd_data(command_qword[gate_qword_q]), .cmd_last(gate_last),
        .profile_valid(global_avg_gate_profile_valid),
        .profile_ready(state_q == ST_PROFILE && global_avg_selected_q),
        .rdma_src_base(global_avg_source_base), .ppu_dst_base(global_avg_destination_base),
        .rdma_transfer_bytes(global_avg_input_bytes),
        .output_write_bytes(global_avg_output_bytes),
        .busy(global_avg_gate_busy), .error(global_avg_gate_error),
        .error_code(global_avg_gate_error_code)
    );

    rk_ppu_pool_max2x2s2_c3_tail_h2w2 pool_leaf (
        .clk, .rst_n(pool_leaf_rst_n),
        .in_valid(!buffered_selected && state_q == ST_INPUT_SEND), .in_ready(c3_pool_in_ready),
        .in_atom(input_atom_data_q),
        .out_valid(c3_pool_out_valid), .out_ready(c3_pool_out_ready),
        .out_atom(c3_pool_out_atom), .out_last(c3_pool_out_last)
    );

    rk_ppu_pool_max2x2s1_c8 #(.IN_H(4), .IN_W(4)) c8_pool_leaf (
        .clk, .rst_n(pool_leaf_rst_n),
        .in_valid(c8_selected_q && state_q == ST_C8_INPUT_SEND),
        .in_ready(c8_pool_in_ready), .in_atom(input_atom_data_q),
        .out_valid(c8_pool_out_valid), .out_ready(c8_pool_out_ready),
        .out_atom(c8_pool_out_atom), .out_last(c8_pool_out_last)
    );

    rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2 pad1_pool_leaf (
        .clk, .rst_n(pool_leaf_rst_n),
        .in_valid(pad1_selected_q && state_q == ST_C8_INPUT_SEND),
        .in_ready(pad1_pool_in_ready), .in_atom(input_atom_data_q),
        .out_valid(pad1_pool_out_valid), .out_ready(pad1_pool_out_ready),
        .out_atom(pad1_pool_out_atom), .out_last(pad1_pool_out_last)
    );

    rk_ppu_pool_min2x2s1_fp16_capture min_pool_leaf (
        .clk, .rst_n(pool_leaf_rst_n),
        .in_valid(min_selected_q && state_q == ST_C8_INPUT_SEND),
        .in_ready(min_pool_in_ready), .in_atom(input_atom_data_q),
        .out_valid(min_pool_out_valid), .out_ready(min_pool_out_ready),
        .out_atom(min_pool_out_atom), .out_last(min_pool_out_last)
    );

    rk_ppu_pool_avg2x2s1_fp16_capture avg_pool_leaf (
        .clk, .rst_n(pool_leaf_rst_n),
        .in_valid(avg_selected_q && state_q == ST_C8_INPUT_SEND),
        .in_ready(avg_pool_in_ready), .in_atom(input_atom_data_q),
        .out_valid(avg_pool_out_valid), .out_ready(avg_pool_out_ready),
        .out_atom(avg_pool_out_atom), .out_last(avg_pool_out_last)
    );

    rk_ppu_pool_max2x2s2_index_c8_h2w2 index_pool_leaf (
        .clk, .rst_n(pool_leaf_rst_n),
        .in_valid(index_selected_q && state_q == ST_C8_INPUT_SEND),
        .in_ready(index_pool_in_ready), .in_atom(input_atom_data_q),
        .out_valid(index_pool_out_valid), .out_ready(index_pool_out_ready),
        .out_value_atom(index_pool_value_atom), .out_index_atom(index_pool_index_atom),
        .out_unique(index_pool_unique), .out_last(index_pool_out_last)
    );

    rk_ppu_pool_max16x16s16_c8 global_pool_leaf (
        .clk, .rst_n(pool_leaf_rst_n),
        .in_valid(global_selected_q && state_q == ST_C8_INPUT_SEND),
        .in_ready(global_pool_in_ready), .in_atom(input_atom_data_q),
        .out_valid(global_pool_out_valid), .out_ready(global_pool_out_ready),
        .out_atom(global_pool_out_atom), .out_last(global_pool_out_last)
    );

    rk_ppu_pool_avg_global3x5_c8_fp16_capture global_avg_pool_leaf (
        .clk, .rst_n(pool_leaf_rst_n),
        .in_valid(global_avg_selected_q && state_q == ST_C8_INPUT_SEND),
        .in_ready(global_avg_pool_in_ready), .in_atom(input_atom_data_q),
        .out_valid(global_avg_pool_out_valid), .out_ready(global_avg_pool_out_ready),
        .out_atom(global_avg_pool_out_atom), .out_last(global_avg_pool_out_last)
    );

    initial begin
        if (BYTES == 0 || aperture_end > 33'h100000000 ||
            TIMEOUT_CYCLES == 0)
            $fatal(1, "Invalid PPU DMA aperture/timeout");
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state_q <= ST_IDLE;
            command_address_q <= 32'd0;
            command_end_q <= 33'd0;
            command_qwords_q <= 6'd0;
            fetch_qword_q <= 5'd0;
            fetch_halfword_q <= 2'd0;
            fetch_word_lo_q <= 48'd0;
            gate_qword_q <= 5'd0;
            input_halfword_q <= 12'd0;
            input_atom_q <= 8'd0;
            input_atom_data_q <= 128'd0;
            output_halfword_q <= 7'd0;
            c8_output_count_q <= 4'd0;
            wait_cycles_q <= 32'd0;
            request_pending_q <= 1'b0;
            outstanding_q <= 1'b0;
            pool_leaf_rst_n_q <= 1'b0;
            profile_gate_rst_n_q <= 1'b0;
            c8_selected_q <= 1'b0;
            pad1_selected_q <= 1'b0;
            min_selected_q <= 1'b0;
            avg_selected_q <= 1'b0;
            index_selected_q <= 1'b0;
            global_selected_q <= 1'b0;
            global_avg_selected_q <= 1'b0;
            index_value_atom_q <= 128'd0;
            index_index_atom_q <= 128'd0;
            mem_req_write_q <= 1'b0;
            mem_req_addr_q <= 32'd0;
            mem_req_wdata_q <= 16'd0;
            error_code_q <= 8'd0;
        end else begin
            if (request_fire) begin
                request_pending_q <= 1'b0;
                outstanding_q <= 1'b1;
            end
            if (response_fire)
                outstanding_q <= 1'b0;

            if (state_q != ST_FAILED) begin
                if (mem_rsp_valid && !outstanding_q) begin
                    fail(8'd7);
                end else if (response_fire &&
                             (bad_status ||
                              (state_q != ST_OUTPUT_RESPONSE &&
                               state_q != ST_C8_OUTPUT_RESPONSE && bad_read_data))) begin
                    fail(bad_status ? 8'd5 : 8'd6);
                end else if (response_fire && c8_selected_q &&
                             state_q == ST_C8_INPUT_RESPONSE && bad_c8_input) begin
                    fail(8'd6);
                end else if (response_fire && pad1_selected_q &&
                             state_q == ST_C8_INPUT_RESPONSE && bad_pad1_input) begin
                    fail(8'd6);
                end else if (response_fire && min_selected_q &&
                             state_q == ST_C8_INPUT_RESPONSE && bad_min_input) begin
                    fail(8'd6);
                end else if (response_fire && avg_selected_q &&
                             state_q == ST_C8_INPUT_RESPONSE && bad_avg_input) begin
                    fail(8'd6);
                end else if (response_fire && index_selected_q &&
                             state_q == ST_C8_INPUT_RESPONSE && bad_index_input) begin
                    fail(8'd6);
                end else if (response_fire && global_selected_q &&
                             state_q == ST_C8_INPUT_RESPONSE && bad_global_input) begin
                    fail(8'd6);
                end else if (response_fire && global_avg_selected_q &&
                             state_q == ST_C8_INPUT_RESPONSE && bad_global_avg_input) begin
                    fail(8'd6);
                end else if (buffered_selected && pool_out_valid &&
                             pool_out_ready && bad_c8_output) begin
                    fail(8'd6);
                end else if (waiting_memory && !request_fire && !response_fire &&
                             wait_cycles_q == TIMEOUT_CYCLES - 1) begin
                    fail(8'd8);
                end else begin
                    if (buffered_selected && pool_out_valid && pool_out_ready) begin
                        if (index_selected_q) begin
                            index_value_atom_q <= index_pool_value_atom;
                            index_index_atom_q <= index_pool_index_atom;
                        end else begin
                            c8_output_atoms[c8_output_count_q] <= pool_out_atom;
                        end
                        c8_output_count_q <= c8_output_count_q + 1'b1;
                    end
                    if (!waiting_memory || request_fire || response_fire)
                        wait_cycles_q <= 32'd0;
                    else
                        wait_cycles_q <= wait_cycles_q + 1'b1;

                    case (state_q)
                        ST_IDLE: begin
                            if (start_valid && start_ready) begin
                                // The captured leaf is single-frame. Keep it
                                // reset throughout command fetch/profile gate;
                                // each accepted descriptor therefore starts a
                                // fresh frame even after an earlier ACK.
                                pool_leaf_rst_n_q <= 1'b0;
                                profile_gate_rst_n_q <= 1'b0;
                                c8_selected_q <= 1'b0;
                                pad1_selected_q <= 1'b0;
                                min_selected_q <= 1'b0;
                                 avg_selected_q <= 1'b0;
                                 index_selected_q <= 1'b0;
                                 global_selected_q <= 1'b0;
                                 global_avg_selected_q <= 1'b0;
                                 c8_output_count_q <= 4'd0;
                                if (start_amount != 32'd26 && start_amount != 32'd28) begin
                                    fail(8'd1);
                                end else if (start_address[2:0] != 3'b000 ||
                                             !in_aperture(start_address, start_command_end)) begin
                                    fail(8'd3);
                                end else begin
                                    command_address_q <= start_address;
                                    command_end_q <= start_command_end;
                                    command_qwords_q <= start_amount[5:0];
                                    fetch_qword_q <= 5'd0;
                                    fetch_halfword_q <= 2'd0;
                                    state_q <= ST_COMMAND_REQUEST;
                                end
                            end
                        end

                        ST_COMMAND_REQUEST: begin
                            issue_request(
                                1'b0,
                                command_address_q + {24'd0, fetch_qword_q, 3'b000} +
                                    {29'd0, fetch_halfword_q, 1'b0},
                                16'd0
                            );
                            state_q <= ST_COMMAND_RESPONSE;
                        end

                        ST_COMMAND_RESPONSE: begin
                            if (response_fire) begin
                                if (fetch_halfword_q == 2'd3) begin
                                    command_qword[fetch_qword_q] <=
                                        {mem_rsp_rdata, fetch_word_lo_q};
                                    if (fetch_qword_q == command_qwords_q[4:0] - 5'd1) begin
                                         if (command_qwords_q == 6'd28 &&
                                            command_qword[8] == 64'h4001000000106024) begin
                                            c8_selected_q <= 1'b0;
                                            pad1_selected_q <= 1'b0;
                                            min_selected_q <= 1'b0;
                                             global_avg_selected_q <=
                                                 command_qword[3] == 64'h4001000000026010;
                                             avg_selected_q <=
                                                 command_qword[3] != 64'h4001000000026010;
                                             index_selected_q <= 1'b0;
                                             global_selected_q <= 1'b0;
                                            gate_qword_q <= 5'd0;
                                            profile_gate_rst_n_q <= 1'b1;
                                            state_q <= ST_GATE;
                                        end else if (command_qwords_q == 6'd26 &&
                                            command_qword[2][63:48] == 16'h4001 &&
                                            command_qword[2][15:0] == 16'h600c &&
                                            command_qword[2][47:16] == 32'h00000001) begin
                                            c8_selected_q <= 1'b0;
                                            min_selected_q <= 1'b0;
                                            avg_selected_q <= 1'b0;
                                            index_selected_q <=
                                                command_qword[8] == 64'h4001400000116024;
                                            global_selected_q <= 1'b0;
                                            pad1_selected_q <=
                                                command_qword[8] == 64'h4001000000116024 &&
                                                command_qword[5][63:48] == 16'h4001 &&
                                                command_qword[5][15:0] == 16'h6018 &&
                                                command_qword[5][47:16] == 32'h00000002;
                                            gate_qword_q <= 5'd0;
                                            // QWORD 2 also identifies C3. The exact
                                            // output-width QWORD 5 separates padded C8.
                                            profile_gate_rst_n_q <= 1'b1;
                                            state_q <= ST_GATE;
                                        end else if (command_qwords_q == 6'd26 &&
                                                     command_qword[2][63:48] == 16'h4001 &&
                                                     command_qword[2][15:0] == 16'h600c &&
                                                     command_qword[2][47:16] == 32'h00000003) begin
                                            min_selected_q <=
                                                command_qword[8] == 64'h4001000000126024;
                                            c8_selected_q <=
                                                command_qword[8] != 64'h4001000000126024;
                                            pad1_selected_q <= 1'b0;
                                             avg_selected_q <= 1'b0;
                                             index_selected_q <= 1'b0;
                                             global_selected_q <= 1'b0;
                                            gate_qword_q <= 5'd0;
                                             profile_gate_rst_n_q <= 1'b1;
                                             state_q <= ST_GATE;
                                        end else if (command_qwords_q == 6'd26 &&
                                                     command_qword[2][63:48] == 16'h4001 &&
                                                     command_qword[2][15:0] == 16'h600c &&
                                                     command_qword[2][47:16] == 32'h0000000f) begin
                                            c8_selected_q <= 1'b0;
                                            pad1_selected_q <= 1'b0;
                                            min_selected_q <= 1'b0;
                                            avg_selected_q <= 1'b0;
                                            index_selected_q <= 1'b0;
                                            global_selected_q <= 1'b1;
                                            gate_qword_q <= 5'd0;
                                            profile_gate_rst_n_q <= 1'b1;
                                            state_q <= ST_GATE;
                                        end else begin
                                            fail(8'd2);
                                        end
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
                        end

                        ST_GATE: begin
                            if (gate_error)
                                fail({4'd0, gate_error_code});
                            else if (gate_valid && gate_ready) begin
                                        if (gate_qword_q == ((avg_selected_q || global_avg_selected_q) ? 5'd27 : 5'd25))
                                    state_q <= ST_PROFILE;
                                else
                                    gate_qword_q <= gate_qword_q + 1'b1;
                            end
                        end

                        ST_PROFILE: begin
                            if (gate_error) begin
                                fail({4'd0, gate_error_code});
                            end else if (gate_profile_valid && !gate_busy) begin
                                fail(8'd6);
                            end else if (gate_profile_valid) begin
                                if ((c8_selected_q &&
                                     (profile_input_bytes != 32'd256 ||
                                      profile_output_bytes != 32'd144)) ||
                                    (pad1_selected_q &&
                                     (profile_input_bytes != 32'd64 ||
                                      profile_output_bytes != 32'd144)) ||
                                    (min_selected_q &&
                                     (profile_input_bytes != 32'd256 ||
                                      profile_output_bytes != 32'd144)) ||
                                    (avg_selected_q &&
                                     (profile_input_bytes != 32'd256 ||
                                      profile_output_bytes != 32'd144)) ||
                                    (global_avg_selected_q &&
                                     (profile_input_bytes != 32'd240 ||
                                      profile_output_bytes != 32'd16)) ||
                                    (index_selected_q &&
                                     (profile_input_bytes != 32'd64 ||
                                      profile_output_bytes != 32'd48)) ||
                                    (global_selected_q &&
                                     (profile_input_bytes != 32'd4096 ||
                                      profile_output_bytes != 32'd16)) ||
                                    (!buffered_selected &&
                                     (profile_input_bytes != 32'd64 ||
                                      profile_output_bytes != 32'd16)) ||
                                    !in_aperture(profile_source_base, source_end) ||
                                    !in_aperture(profile_destination_base, destination_end) ||
                                    ranges_overlap(command_address_q, command_end_q,
                                                   profile_source_base, source_end) ||
                                    ranges_overlap(command_address_q, command_end_q,
                                                   profile_destination_base, destination_end) ||
                                    ranges_overlap(profile_source_base, source_end,
                                                   profile_destination_base, destination_end)) begin
                                    fail(8'd3);
                                 end else begin
                                     pool_leaf_rst_n_q <= 1'b1;
                                     input_halfword_q <= 12'd0;
                                     input_atom_q <= 8'd0;
                                    if (buffered_selected) begin
                                        c8_output_count_q <= 4'd0;
                                        state_q <= ST_C8_INPUT_REQUEST;
                                    end else begin
                                        state_q <= ST_INPUT_REQUEST;
                                    end
                                end
                            end
                        end

                        ST_INPUT_REQUEST: begin
                            issue_request(
                                1'b0,
                                 profile_source_base + {19'd0, input_halfword_q, 1'b0},
                                16'd0
                            );
                            state_q <= ST_INPUT_RESPONSE;
                        end

                        ST_INPUT_RESPONSE: begin
                            if (response_fire) begin
                                input_atom_data_q[input_halfword_q[2:0]*16 +: 16] <= mem_rsp_rdata;
                                if (input_halfword_q[2:0] == 3'd7) begin
                                    state_q <= ST_INPUT_SEND;
                                end else begin
                                    input_halfword_q <= input_halfword_q + 1'b1;
                                    state_q <= ST_INPUT_REQUEST;
                                end
                            end
                        end

                        ST_INPUT_SEND: begin
                            if (pool_in_ready) begin
                                if (input_atom_q == 8'd3) begin
                                    state_q <= ST_POOL_WAIT;
                                end else begin
                                    input_atom_q <= input_atom_q + 1'b1;
                                    input_halfword_q <= input_halfword_q + 1'b1;
                                    state_q <= ST_INPUT_REQUEST;
                                end
                            end
                        end

                        ST_POOL_WAIT: begin
                            if (pool_out_valid) begin
                                if (pool_out_last !== 1'b1 || (^pool_out_atom) === 1'bx)
                                    fail(8'd6);
                                else begin
                                    output_halfword_q <= 7'd0;
                                    state_q <= ST_OUTPUT_REQUEST;
                                end
                            end
                        end

                        ST_OUTPUT_REQUEST: begin
                            issue_request(
                                1'b1,
                                profile_destination_base + {24'd0, output_halfword_q, 1'b0},
                                pool_out_atom[output_halfword_q*16 +: 16]
                            );
                            state_q <= ST_OUTPUT_RESPONSE;
                        end

                        ST_OUTPUT_RESPONSE: begin
                            if (response_fire) begin
                                if (output_halfword_q == 7'd7)
                                    state_q <= ST_OUTPUT_RELEASE;
                                else begin
                                    output_halfword_q <= output_halfword_q + 1'b1;
                                    state_q <= ST_OUTPUT_REQUEST;
                                end
                            end
                        end

                        ST_OUTPUT_RELEASE: begin
                            if (pool_out_valid && pool_out_ready)
                                state_q <= ST_FINISH;
                        end

                        ST_C8_INPUT_REQUEST: begin
                            issue_request(
                                1'b0,
                                 profile_source_base + {19'd0, input_halfword_q, 1'b0},
                                16'd0
                            );
                            state_q <= ST_C8_INPUT_RESPONSE;
                        end

                        ST_C8_INPUT_RESPONSE: begin
                            if (response_fire) begin
                                input_atom_data_q[input_halfword_q[2:0]*16 +: 16] <= mem_rsp_rdata;
                                if (input_halfword_q[2:0] == 3'd7)
                                    state_q <= ST_C8_INPUT_SEND;
                                else begin
                                    input_halfword_q <= input_halfword_q + 1'b1;
                                    state_q <= ST_C8_INPUT_REQUEST;
                                end
                            end
                        end

                        ST_C8_INPUT_SEND: begin
                            if (pool_in_ready) begin
                                 if (global_selected_q && input_atom_q == 8'd255)
                                     state_q <= ST_C8_COLLECT;
                                 else if (global_avg_selected_q && input_atom_q == 8'd14)
                                     state_q <= ST_C8_COLLECT;
                                 else if (((pad1_selected_q || index_selected_q) &&
                                      input_atom_q == 8'd3) ||
                                     ((c8_selected_q || min_selected_q || avg_selected_q) &&
                                      input_atom_q == 8'd15))
                                    state_q <= ST_C8_COLLECT;
                                else begin
                                    input_atom_q <= input_atom_q + 1'b1;
                                    input_halfword_q <= input_halfword_q + 1'b1;
                                    state_q <= ST_C8_INPUT_REQUEST;
                                end
                            end
                        end

                        ST_C8_COLLECT: begin
                            // Buffered profiles defer writes until their full
                            // supported input frame and output atom are captured.
                                 if (((index_selected_q || global_selected_q || global_avg_selected_q) &&
                                  c8_output_count_q == 4'd1) ||
                                (!index_selected_q && !global_selected_q && !global_avg_selected_q &&
                                 c8_output_count_q == 4'd9)) begin
                                output_halfword_q <= 7'd0;
                                state_q <= ST_C8_OUTPUT_REQUEST;
                            end
                        end

                        ST_C8_OUTPUT_REQUEST: begin
                            issue_request(
                                1'b1,
                                profile_destination_base + c8_output_write_offset,
                                c8_output_write_data
                            );
                            state_q <= ST_C8_OUTPUT_RESPONSE;
                        end

                        ST_C8_OUTPUT_RESPONSE: begin
                            if (response_fire) begin
                                 if ((index_selected_q && output_halfword_q == 7'd15) ||
                                     ((global_selected_q || global_avg_selected_q) &&
                                      output_halfword_q == 7'd7) ||
                                     (!index_selected_q && !global_selected_q &&
                                      !global_avg_selected_q && output_halfword_q == 7'd71))
                                    state_q <= ST_FINISH;
                                else begin
                                    output_halfword_q <= output_halfword_q + 1'b1;
                                    state_q <= ST_C8_OUTPUT_REQUEST;
                                end
                            end
                        end

                        ST_FINISH: begin
                            if (result_ready) begin
                                pool_leaf_rst_n_q <= 1'b0;
                                state_q <= ST_IDLE;
                            end
                        end

                        default: fail(8'd7);
                    endcase
                end
            end
        end
    end
endmodule
