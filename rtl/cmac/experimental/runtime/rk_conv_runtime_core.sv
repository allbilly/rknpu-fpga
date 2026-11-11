// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One runtime-decoded conv engine (EXPERIMENTAL prototype).
//
// Same external endpoint contract as the adopted per-profile conv cores: the
// raw command QWORD stream is the execution boundary, the operand/output
// memory port is halfword-serialized and read/write arbitrated, and the
// arithmetic is the unchanged donor `rk_cmac_cacc_fp16_array` behind the
// unchanged `rk_frame_stage` register slice.
//
// What changes is where the geometry comes from: `rk_conv_runtime_decode`
// derives it from the unchanged register fields (see docs/CONV_RUNTIME_ENGINE.md),
// `rk_conv_runtime_front` generates the same frame sequence from runtime
// counters, and one of two output stages is selected from the decoded output
// precision (FP16 atom writer or FP32 [c1][pixel][c2] placement). There is no
// CPU arithmetic, no operand repack and no output repair.
module rk_conv_runtime_core #(
    // Corpus-verified geometry: max 16 channel lanes (C16 jobs) and 16 kernel
    // lanes. This uses the ADDITIVE experimental cell/array copies (C=16
    // capable); the FINAL-frozen cell/array/cacc files are untouched.
    parameter int unsigned ATOMIC_C = 16,
    parameter int unsigned ATOMIC_K = 16
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        cmd_valid,
    output logic        cmd_ready,
    input  logic [63:0] cmd_data,
    input  logic        cmd_last,
    output logic        busy,
    output logic        acknowledged,
    output logic        frame_done,
    output logic        done,
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
    input  logic        mem_rsp_error,
    // Observation ports for the enclosing harness (read-only).
    output logic [31:0] config_input_base,
    output logic [31:0] config_weight_base,
    output logic [31:0] config_output_base,
    output logic [31:0] input_bytes,
    output logic [31:0] weight_bytes,
    output logic [31:0] output_bytes,
    output logic [8:0]  obs_total_atoms,
    output logic [7:0]  obs_taps,
    output logic        obs_output_fp16
);
    localparam int unsigned TIMEOUT_CYCLES = 65536;

    // ---- decoder output ---------------------------------------------------
    logic        decode_valid, decode_ready, decode_busy, decode_error;
    logic [7:0]  decode_code;
    logic [5:0]  cfg_input_h, cfg_input_w, cfg_output_h, cfg_output_w;
    logic [2:0]  cfg_kernel_h, cfg_kernel_w, cfg_stride, cfg_planes;
    logic        cfg_depthwise;
    logic [5:0]  cfg_input_channels, cfg_input_align, cfg_output_channels;
    logic [5:0]  cfg_align_c;
    logic [3:0]  cfg_pack_c2, cfg_kernels, cfg_output_atom_lanes;
    logic [2:0]  cfg_c1_blocks;
    logic [1:0]  cfg_weight_mode;
    logic [4:0]  cfg_chunk_lanes;
    logic        cfg_output_fp16;
    logic [31:0] cfg_input_base, cfg_weight_base, cfg_output_base;
    logic [31:0] cfg_input_bytes, cfg_weight_bytes, cfg_output_bytes;
    logic [7:0]  cfg_taps;
    logic [9:0]  cfg_frame_weight_halfwords;
    logic [12:0] cfg_weight_halfwords;
    logic [9:0]  cfg_weight_lanes;
    logic [8:0]  cfg_block_stride;
    logic [9:0]  cfg_total_atoms;
    logic [11:0] cfg_plane_words;
    logic [4:0]  cfg_pixel_bytes;
    logic [12:0] cfg_plane_bytes, cfg_block_bytes;
    logic [14:0] cfg_chunk_stride_bytes, cfg_block_plane_bytes;
    logic [31:0] cfg_real_mask;

    // ---- front / stage / arithmetic --------------------------------------
    logic        front_cfg_ready, front_busy, front_error;
    logic [7:0]  front_code;
    logic        frame_valid, frame_ready;
    logic [ATOMIC_C*16-1:0] frame_data;
    logic [ATOMIC_K*ATOMIC_C*16-1:0] frame_weight;
    logic [ATOMIC_C-1:0] frame_data_mask;
    logic [31:0] frame_output_address;
    logic [ATOMIC_K*ATOMIC_C-1:0] frame_weight_mask;
    logic        frame_first, frame_last, frame_last_output;
    logic        staged_valid, staged_ready;
    // Widths track the elaboration-time ATOMIC_C/ATOMIC_K (16x16 for the
    // corpus-verified construction). Hard-coded 512/8192/32/32 widths produced
    // Icarus port-width warnings (and silently truncated the upper lanes).
    logic [ATOMIC_C*16-1:0] staged_data;
    logic [ATOMIC_K*ATOMIC_C*16-1:0] staged_weight;
    logic [ATOMIC_C-1:0] staged_data_mask;
    logic [ATOMIC_K*ATOMIC_C-1:0] staged_weight_mask;
    logic [31:0] staged_address;
    logic        staged_first, staged_last, staged_last_output;
    logic        arithmetic_ready, arithmetic_valid, arithmetic_busy;
    logic        arithmetic_error;
    logic [ATOMIC_K*32-1:0] arithmetic_values;
    logic [32:0]  arithmetic_tag;
    logic [7:0]   arithmetic_code;

    // ---- output stages ----------------------------------------------------
    logic        atom_ack_fp16, atom_frame_done_fp16, atom_done_fp16;
    logic        atom_busy_fp16, atom_error_fp16;
    logic [7:0]  atom_code_fp16;
    logic        atom_ready_fp16;
    logic        atom_ack_fp32, atom_frame_done_fp32, atom_done_fp32;
    logic        atom_busy_fp32, atom_error_fp32;
    logic [7:0]  atom_code_fp32;
    logic        atom_ready_fp32;
    logic        atom_ready, atom_ack, atom_frame_done, atom_done;
    logic        atom_error;
    logic [7:0]  atom_code;

    // ---- memory arbitration ----------------------------------------------
    logic        read_req, read_req_ready, read_rsp, read_rsp_ready;
    logic        read_rsp_error;
    logic [31:0] read_address;
    logic [15:0] read_data;
    logic        write_req, write_req_ready, write_rsp, write_rsp_ready;
    logic        write_rsp_error;
    logic        write_req_write;
    logic [31:0] write_address;
    logic [15:0] write_data;
    logic        arbiter_busy, arbiter_error, arbiter_req_valid, arbiter_rsp_ready;
    logic        arbiter_req_write;
    logic [31:0] arbiter_req_addr;
    logic [15:0] arbiter_req_wdata;
    logic [7:0]  arbiter_code;
    logic        fault;
    logic [7:0]  saved_code;
    logic        write_violation, child_cancel;

    // ---- per-stage write ports -------------------------------------------
    logic fp16_wreq_valid, fp16_wreq_ready, fp16_wreq_write;
    logic [31:0] fp16_wreq_addr;
    logic [15:0] fp16_wreq_wdata;
    logic fp16_wrsp_valid, fp16_wrsp_ready, fp16_wrsp_error;
    logic fp32_wreq_valid, fp32_wreq_ready, fp32_wreq_write;
    logic [31:0] fp32_wreq_addr;
    logic [15:0] fp32_wreq_wdata;
    logic fp32_wrsp_valid, fp32_wrsp_ready, fp32_wrsp_error;

    wire use_fp16 = cfg_output_fp16;
    wire fp16_in_valid = arithmetic_valid && !error && use_fp16;
    wire fp32_in_valid = arithmetic_valid && !error && !use_fp16;
    wire [ATOMIC_K*32-1:0] cacc_values = arithmetic_values;
    wire [31:0] atom_tag_address = arithmetic_tag[32:1];
    wire fp16_in_last = arithmetic_tag[0];

    assign config_input_base = cfg_input_base;
    assign config_weight_base = cfg_weight_base;
    assign config_output_base = cfg_output_base;
    assign input_bytes = cfg_input_bytes;
    assign weight_bytes = cfg_weight_bytes;
    assign output_bytes = cfg_output_bytes;
    assign obs_total_atoms = cfg_total_atoms[8:0];
    assign obs_taps = cfg_taps;
    assign obs_output_fp16 = cfg_output_fp16;

    // ---- decoder ----------------------------------------------------------
    rk_conv_runtime_decode decoder (
        .clk, .rst_n,
        .cmd_valid(cmd_valid && !error), .cmd_ready(decode_ready),
        .cmd_data, .cmd_last,
        .config_valid(decode_valid), .config_ready(front_cfg_ready),
        .cfg_input_h, .cfg_input_w, .cfg_output_h, .cfg_output_w,
        .cfg_kernel_h, .cfg_kernel_w, .cfg_stride, .cfg_depthwise,
        .cfg_input_channels, .cfg_input_align, .cfg_pack_c2, .cfg_planes,
        .cfg_output_channels, .cfg_kernels, .cfg_c1_blocks,
        .cfg_weight_mode, .cfg_chunk_lanes, .cfg_align_c,
        .cfg_output_fp16, .cfg_output_atom_lanes,
        .cfg_input_base, .cfg_weight_base, .cfg_output_base,
        .cfg_input_bytes, .cfg_weight_bytes, .cfg_output_bytes,
        .cfg_taps, .cfg_frame_weight_halfwords, .cfg_weight_halfwords,
        .cfg_weight_lanes, .cfg_block_stride, .cfg_total_atoms,
        .cfg_plane_words, .cfg_pixel_bytes, .cfg_plane_bytes,
        .cfg_block_bytes, .cfg_chunk_stride_bytes, .cfg_block_plane_bytes,
        .cfg_real_mask,
        .busy(decode_busy), .error(decode_error), .error_code(decode_code));

    // ---- generalized front ------------------------------------------------
    rk_conv_runtime_front front (
        .clk, .rst_n,
        .cfg_valid(decode_valid), .cfg_ready(front_cfg_ready),
        .cfg_input_h, .cfg_input_w, .cfg_output_h, .cfg_output_w,
        .cfg_kernel_h, .cfg_kernel_w, .cfg_stride, .cfg_depthwise,
        .cfg_input_channels, .cfg_pack_c2, .cfg_planes, .cfg_kernels,
        .cfg_c1_blocks, .cfg_weight_mode, .cfg_align_c,
        .cfg_input_base, .cfg_weight_base, .cfg_output_base,
        .cfg_frame_weight_halfwords, .cfg_weight_halfwords,
        .cfg_weight_lanes, .cfg_pixel_bytes, .cfg_plane_bytes,
        .cfg_block_bytes, .cfg_chunk_stride_bytes, .cfg_real_mask,
        .cancel(child_cancel), .cancel_code(fault ? saved_code : decode_code),
        .busy(front_busy), .error(front_error), .error_code(front_code),
        .mem_req_valid(read_req), .mem_req_ready(read_req_ready && !error),
        .mem_req_addr(read_address),
        .mem_rsp_valid(read_rsp && !error), .mem_rsp_ready(read_rsp_ready),
        .mem_rsp_rdata(read_data), .mem_rsp_error(read_rsp_error),
        .frame_valid, .frame_ready, .frame_data, .frame_weight,
        .frame_data_mask, .frame_weight_mask, .frame_output_address,
        .frame_first, .frame_last, .frame_last_output);

    // ---- frame stage + unchanged CMAC/CACC array -------------------------
    rk_runtime_frame_stage #(.ATOMIC_C(ATOMIC_C), .ATOMIC_K(ATOMIC_K)) stage (
        .clk, .rst_n, .cancel(child_cancel),
        .in_valid(frame_valid && !error), .in_ready(staged_ready),
        .in_data(frame_data), .in_weight(frame_weight),
        .in_data_mask(frame_data_mask), .in_weight_mask(frame_weight_mask),
        .in_address(frame_output_address), .in_first(frame_first),
        .in_last(frame_last), .in_last_output(frame_last_output),
        .out_valid(staged_valid), .out_ready(arithmetic_ready),
        .out_data(staged_data), .out_weight(staged_weight),
        .out_data_mask(staged_data_mask), .out_weight_mask(staged_weight_mask),
        .out_address(staged_address), .out_first(staged_first),
        .out_last(staged_last), .out_last_output(staged_last_output));

    rk_runtime_cacc_fp16_array #(.ATOMIC_C(ATOMIC_C), .ATOMIC_K(ATOMIC_K), .TAG_WIDTH(33))
    arithmetic (
        .clk, .rst_n,
        .in_valid(staged_valid && !error), .in_ready(arithmetic_ready),
        .in_data(staged_data), .in_weight(staged_weight),
        .in_data_mask(staged_data_mask), .in_weight_mask(staged_weight_mask),
        .in_first(staged_first), .in_last(staged_last),
        .in_tag({staged_address, staged_last_output}),
        .out_valid(arithmetic_valid), .out_ready(atom_ready && !error),
        .out_values(arithmetic_values), .out_tag(arithmetic_tag),
        .cancel(child_cancel), .cancel_code(fault ? saved_code : decode_code),
        .busy(arithmetic_busy), .error(arithmetic_error),
        .error_code(arithmetic_code));

    // ---- FP16 atom output -------------------------------------------------
    rk_conv_output_atom #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES), .ATOMIC_K(8))
    output_fp16 (
        .clk, .rst_n,
        .in_valid(fp16_in_valid), .in_ready(atom_ready_fp16),
        .in_values(cacc_values[255:0]), .in_address(atom_tag_address),
        .in_last(fp16_in_last), .cancel(child_cancel),
        .cancel_code(fault ? saved_code : decode_code),
        .busy(atom_busy_fp16), .acknowledged(atom_ack_fp16),
        .frame_done(atom_frame_done_fp16), .done(atom_done_fp16),
        .error(atom_error_fp16), .error_code(atom_code_fp16),
        .mem_req_valid(fp16_wreq_valid), .mem_req_ready(fp16_wreq_ready),
        .mem_req_write(fp16_wreq_write), .mem_req_addr(fp16_wreq_addr),
        .mem_req_wdata(fp16_wreq_wdata),
        .mem_rsp_valid(fp16_wrsp_valid), .mem_rsp_ready(fp16_wrsp_ready),
        .mem_rsp_error(fp16_wrsp_error));

    // ---- FP32 [c1][pixel][c2] output -------------------------------------
    rk_conv_runtime_fp32_output output_fp32 (
        .clk, .rst_n,
        .cfg_lanes(cfg_kernels), .cfg_blocks(cfg_c1_blocks),
        .cfg_pixels({1'b0, cfg_block_stride}),
        .in_valid(fp32_in_valid), .in_ready(atom_ready_fp32),
        .in_values(cacc_values[255:0]), .in_address(atom_tag_address),
        .in_last(fp16_in_last), .cancel(child_cancel),
        .cancel_code(fault ? saved_code : decode_code),
        .busy(atom_busy_fp32), .acknowledged(atom_ack_fp32),
        .frame_done(atom_frame_done_fp32), .done(atom_done_fp32),
        .error(atom_error_fp32), .error_code(atom_code_fp32),
        .mem_req_valid(fp32_wreq_valid), .mem_req_ready(fp32_wreq_ready),
        .mem_req_write(fp32_wreq_write), .mem_req_addr(fp32_wreq_addr),
        .mem_req_wdata(fp32_wreq_wdata),
        .mem_rsp_valid(fp32_wrsp_valid), .mem_rsp_ready(fp32_wrsp_ready),
        .mem_rsp_error(fp32_wrsp_error));

    // ---- selected output stage -------------------------------------------
    assign atom_ready = use_fp16 ? atom_ready_fp16 : atom_ready_fp32;
    assign atom_ack = use_fp16 ? atom_ack_fp16 : atom_ack_fp32;
    assign atom_frame_done = use_fp16 ? atom_frame_done_fp16 :
                                        atom_frame_done_fp32;
    assign atom_done = use_fp16 ? atom_done_fp16 : atom_done_fp32;
    assign atom_error = use_fp16 ? atom_error_fp16 : atom_error_fp32;
    assign atom_code = use_fp16 ? atom_code_fp16 : atom_code_fp32;

    assign write_req = use_fp16 ? fp16_wreq_valid : fp32_wreq_valid;
    assign fp16_wreq_ready = write_req_ready && use_fp16;
    assign fp32_wreq_ready = write_req_ready && !use_fp16;
    assign write_req_write = use_fp16 ? fp16_wreq_write : fp32_wreq_write;
    assign write_address = use_fp16 ? fp16_wreq_addr : fp32_wreq_addr;
    assign write_data = use_fp16 ? fp16_wreq_wdata : fp32_wreq_wdata;
    assign fp16_wrsp_valid = write_rsp && use_fp16;
    assign fp32_wrsp_valid = write_rsp && !use_fp16;
    assign fp16_wrsp_error = write_rsp_error;
    assign fp32_wrsp_error = write_rsp_error;
    assign write_rsp_ready = use_fp16 ? fp16_wrsp_ready : fp32_wrsp_ready;

    // ---- errors -----------------------------------------------------------
    assign child_cancel = fault || decode_error;
    assign write_violation = write_req && !write_req_write;
    assign error = rst_n && (fault || decode_error || front_error ||
                             arithmetic_error || atom_error ||
                             arbiter_error || write_violation);
    assign error_code = !rst_n ? 8'd0 : fault ? saved_code :
                        decode_error ? decode_code :
                        front_error ? front_code :
                        arithmetic_error ? arithmetic_code :
                        atom_error ? atom_code :
                        arbiter_error ? arbiter_code :
                        write_violation ? 8'd6 : 8'd0;
    assign cmd_ready = decode_ready && !error;
    assign busy = rst_n && !error &&
                  (decode_busy || front_busy || arithmetic_busy ||
                   atom_busy_fp16 || atom_busy_fp32 || arbiter_busy);
    assign acknowledged = atom_ack && !error;
    assign frame_done = atom_frame_done && !error;
    assign done = atom_done && !error;
    assign frame_ready = staged_ready && !error;
    assign mem_req_valid = arbiter_req_valid && !error;
    assign mem_req_write = arbiter_req_write;
    assign mem_req_addr = arbiter_req_addr;
    assign mem_req_wdata = arbiter_req_wdata;
    assign mem_rsp_ready = arbiter_rsp_ready && !error;

    rk_cmac_rw_arbiter arbiter (
        .clk, .rst_n, .cancel(child_cancel),
        .cancel_code(fault ? saved_code : decode_code),
        .read_req_valid(read_req && !error), .read_req_ready,
        .read_req_addr(read_address),
        .read_rsp_valid(read_rsp), .read_rsp_ready(read_rsp_ready && !error),
        .read_rsp_data(read_data), .read_rsp_error(read_rsp_error),
        .write_req_valid(write_req && !error), .write_req_ready,
        .write_req_addr(write_address), .write_req_data(write_data),
        .write_rsp_valid(write_rsp), .write_rsp_ready(write_rsp_ready && !error),
        .write_rsp_error(write_rsp_error),
        .mem_req_valid(arbiter_req_valid), .mem_req_ready(mem_req_ready && !error),
        .mem_req_write(arbiter_req_write), .mem_req_addr(arbiter_req_addr),
        .mem_req_data(arbiter_req_wdata),
        .mem_rsp_valid(mem_rsp_valid && !error),
        .mem_rsp_ready(arbiter_rsp_ready),
        .mem_rsp_data(mem_rsp_rdata), .mem_rsp_error,
        .busy(arbiter_busy), .error(arbiter_error), .error_code(arbiter_code));

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fault <= 1'b0;
            saved_code <= 8'd0;
        end else if (!fault && error) begin
            fault <= 1'b1;
            saved_code <= error_code;
        end
    end
endmodule
