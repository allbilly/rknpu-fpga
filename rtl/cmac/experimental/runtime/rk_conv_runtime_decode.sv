// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Runtime decoder for one captured RK3588 CNA convolution task.
//
// EXPERIMENTAL prototype (rtl/cmac/experimental/runtime/). Not instantiated by
// the adopted image. It consumes the raw final command QWORDs unchanged and
// derives the convolution geometry and configuration from the register fields
// instead of comparing the stream against a per-capture constant table.
//
// Strictness / fail-closed policy (see docs/CONV_RUNTIME_ENGINE.md):
//   * exactly two canonical word sequences are accepted: the 54-word
//     conv_new_clean.py family (CNA body prefixed by the three DPU-RDMA clear
//     words) and the 52-word conv_simple.py family (CNA body, four PC-tail
//     words, one trailing zero padding word);
//   * every word's (target, offset) must be the next canonical field and the
//     terminal boundary must match; the 52-word family's padding word must be
//     zero;
//   * every value is validated against the pinned donor's own formulas: the
//     fields this engine consumes are decoded, and the redundant geometry /
//     BO-size / schedule fields are re-derived from the primary fields and
//     compared. A mismatch faults; nothing is corrected or widened;
//   * buffers must be 16-byte aligned, inside the 32-bit space and pairwise
//     non-overlapping using the derived byte sizes;
//   * self-consistent geometry outside the capture-bounded engine limits is
//     refused with the unsupported code;
//   * one job per configuration; a second stream is fault 7.
//
// Error codes: 1 non-canonical/unknown field, 2 unsupported or inconsistent
// value/derived geometry, 3 framing (cmd_last/length/family), 4 buffer
// range/alignment/overlap, 7 second stream.
module rk_conv_runtime_decode (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        cmd_valid,
    output logic        cmd_ready,
    input  logic [63:0] cmd_data,
    input  logic        cmd_last,
    output logic        config_valid,
    input  logic        config_ready,
    // Decoded convolution geometry.
    output logic [5:0]  cfg_input_h,
    output logic [5:0]  cfg_input_w,
    output logic [5:0]  cfg_output_h,
    output logic [5:0]  cfg_output_w,
    output logic [2:0]  cfg_kernel_h,
    output logic [2:0]  cfg_kernel_w,
    output logic [2:0]  cfg_stride,
    output logic        cfg_depthwise,
    output logic [5:0]  cfg_input_channels,
    output logic [5:0]  cfg_input_align,
    output logic [3:0]  cfg_pack_c2,
    output logic [2:0]  cfg_planes,
    output logic [5:0]  cfg_output_channels,
    output logic [3:0]  cfg_kernels,
    output logic [2:0]  cfg_c1_blocks,
    // 0 = kh-major [ky][kx][OC][align_c]; 1 = depthwise [ky][kx][C2];
    // 2 = chunked [oc_chunk][ky][kx][16 OC lanes][align_c].
    output logic [1:0]  cfg_weight_mode,
    output logic [4:0]  cfg_chunk_lanes,
    output logic [5:0]  cfg_align_c,
    output logic        cfg_output_fp16,
    output logic [3:0]  cfg_output_atom_lanes,
    // Buffers (bases come from the three relocated address words).
    output logic [31:0] cfg_input_base,
    output logic [31:0] cfg_weight_base,
    output logic [31:0] cfg_output_base,
    output logic [31:0] cfg_input_bytes,
    output logic [31:0] cfg_weight_bytes,
    output logic [31:0] cfg_output_bytes,
    // Derived loop constants for the generalized front.
    output logic [7:0]  cfg_taps,
    output logic [9:0]  cfg_frame_weight_halfwords,
    output logic [12:0] cfg_weight_halfwords,
    output logic [9:0]  cfg_weight_lanes,
    output logic [8:0]  cfg_block_stride,
    output logic [9:0]  cfg_total_atoms,
    output logic [11:0] cfg_plane_words,
    output logic [4:0]  cfg_pixel_bytes,
    output logic [12:0] cfg_plane_bytes,
    output logic [12:0] cfg_block_bytes,
    output logic [14:0] cfg_chunk_stride_bytes,
    output logic [14:0] cfg_block_plane_bytes,
    output logic [31:0] cfg_real_mask,
    output logic        busy,
    output logic        error,
    output logic [7:0]  error_code
);
    // Capture-bounded engine limits (corpus maxima with explicit headroom).
    localparam int unsigned MAX_INPUT_PIXELS = 320;
    localparam int unsigned MAX_WEIGHT_HALFWORDS = 4608;
    localparam int unsigned MAX_KERNEL = 5;
    localparam int unsigned MAX_CHANNELS = 32;
    localparam int unsigned MAX_STRIDE = 2;
    localparam int unsigned MAX_OUTPUT_BLOCKS = 4;
    localparam int unsigned BODY_WORDS = 50;

    localparam logic [15:0] T_DPU = 16'h1001;
    localparam logic [15:0] T_CNA = 16'h0201;
    localparam logic [15:0] T_CORE = 16'h0801;
    localparam logic [15:0] T_RDMA = 16'h2001;
    localparam logic [15:0] T_PC = 16'h0081;
    localparam logic [15:0] T_PC_REG = 16'h0101;
    localparam logic [15:0] T_VERSION = 16'h0041;

    typedef enum logic [2:0] {
        STREAM, DERIVE, CHECK, VALIDATED, LOCKED, FAULT
    } state_t;
    state_t state_q;

    logic [5:0]  word_index_q;
    logic        family54_q;
    logic [7:0]  saved_code_q;
    logic [31:0] r_word [0:BODY_WORDS-1];

    // ------------------------------------------------------------------
    // Canonical sequence check.
    // ------------------------------------------------------------------
    function automatic logic [31:0] canonical_tag(input logic [5:0] body);
        begin
            case (body)
                6'd0:  canonical_tag = {T_CNA, 16'h100c};
                6'd1:  canonical_tag = {T_CNA, 16'h1010};
                6'd2:  canonical_tag = {T_CNA, 16'h1014};
                6'd3:  canonical_tag = {T_CNA, 16'h1020};
                6'd4:  canonical_tag = {T_CNA, 16'h1024};
                6'd5:  canonical_tag = {T_CNA, 16'h1028};
                6'd6:  canonical_tag = {T_CNA, 16'h102c};
                6'd7:  canonical_tag = {T_CNA, 16'h1030};
                6'd8:  canonical_tag = {T_CNA, 16'h1034};
                6'd9:  canonical_tag = {T_CNA, 16'h1038};
                6'd10: canonical_tag = {T_CNA, 16'h1040};
                6'd11: canonical_tag = {T_CNA, 16'h1044};
                6'd12: canonical_tag = {T_CNA, 16'h104c};
                6'd13: canonical_tag = {T_CNA, 16'h1050};
                6'd14: canonical_tag = {T_CNA, 16'h1054};
                6'd15: canonical_tag = {T_CNA, 16'h1058};
                6'd16: canonical_tag = {T_CNA, 16'h105c};
                6'd17: canonical_tag = {T_CNA, 16'h1070};
                6'd18: canonical_tag = {T_CNA, 16'h1078};
                6'd19: canonical_tag = {T_CNA, 16'h107c};
                6'd20: canonical_tag = {T_CNA, 16'h1080};
                6'd21: canonical_tag = {T_CNA, 16'h1084};
                6'd22: canonical_tag = {T_CNA, 16'h1088};
                6'd23: canonical_tag = {T_CNA, 16'h1110};
                6'd24: canonical_tag = {T_CNA, 16'h1180};
                6'd25: canonical_tag = {T_CORE, 16'h3010};
                6'd26: canonical_tag = {T_CORE, 16'h3014};
                6'd27: canonical_tag = {T_CORE, 16'h3018};
                6'd28: canonical_tag = {T_CORE, 16'h3030};
                6'd29: canonical_tag = {T_DPU, 16'h400c};
                6'd30: canonical_tag = {T_DPU, 16'h4010};
                6'd31: canonical_tag = {T_DPU, 16'h4020};
                6'd32: canonical_tag = {T_DPU, 16'h4024};
                6'd33: canonical_tag = {T_DPU, 16'h4030};
                6'd34: canonical_tag = {T_DPU, 16'h4034};
                6'd35: canonical_tag = {T_DPU, 16'h4038};
                6'd36: canonical_tag = {T_DPU, 16'h403c};
                6'd37: canonical_tag = {T_DPU, 16'h4040};
                6'd38: canonical_tag = {T_DPU, 16'h4050};
                6'd39: canonical_tag = {T_DPU, 16'h4058};
                6'd40: canonical_tag = {T_DPU, 16'h405c};
                6'd41: canonical_tag = {T_DPU, 16'h4060};
                6'd42: canonical_tag = {T_DPU, 16'h4070};
                6'd43: canonical_tag = {T_DPU, 16'h4078};
                6'd44: canonical_tag = {T_DPU, 16'h4084};
                6'd45: canonical_tag = {T_DPU, 16'h40c0};
                6'd46: canonical_tag = {T_PC_REG, 16'h0010};
                6'd47: canonical_tag = {T_PC_REG, 16'h0014};
                6'd48: canonical_tag = {T_VERSION, 16'h0000};
                6'd49: canonical_tag = {T_PC, 16'h0008};
                default: canonical_tag = 32'h0;
            endcase
        end
    endfunction

    logic        word1_is_rdma;
    logic        frame_ok;
    logic [31:0] body_now;
    logic [31:0] exp_tag;
    logic [7:0]  recv_code;

    assign word1_is_rdma = (cmd_data[63:48] == T_RDMA) &&
                           (cmd_data[15:0] == 16'h5004);
    // The family is decided by word 1; the body index uses the registered
    // family from word 2 onwards and the immediate family decision at word 1.
    assign body_now = (word_index_q == 6'd0) ? 32'd0 :
                      (family54_q ? (32'(word_index_q) - 32'd4) :
                                    (32'(word_index_q) - 32'd1));

    always @* begin
        exp_tag = 32'h0;
        recv_code = 8'd0;
        frame_ok = 1'b1;
        // A four-state command word is not a valid capture replay: an X/Z tag,
        // address or value must never be silently interpreted.
        if ((^cmd_data) === 1'bx) recv_code = 8'd2;
        if (word_index_q == 6'd0) begin
            exp_tag = {T_DPU, 16'h4004};
            if ({cmd_data[63:48], cmd_data[15:0]} != exp_tag) recv_code = 8'd1;
            else if (cmd_last) recv_code = 8'd3;
            else if (cmd_data[47:16] != 32'h0000000e) recv_code = 8'd2;
        end else if (word_index_q == 6'd1) begin
            exp_tag = word1_is_rdma ? {T_RDMA, 16'h5004} : {T_CNA, 16'h100c};
            if ({cmd_data[63:48], cmd_data[15:0]} != exp_tag) recv_code = 8'd1;
            else if (cmd_last) recv_code = 8'd3;
            else if (word1_is_rdma && cmd_data[47:16] != 32'h0) recv_code = 8'd2;
        end else if (family54_q && word_index_q == 6'd2) begin
            exp_tag = {T_RDMA, 16'h5034};
            if ({cmd_data[63:48], cmd_data[15:0]} != exp_tag) recv_code = 8'd1;
            else if (cmd_last) recv_code = 8'd3;
            else if (cmd_data[47:16] != 32'h0) recv_code = 8'd2;
        end else if (family54_q && word_index_q == 6'd3) begin
            exp_tag = {T_RDMA, 16'h5044};
            if ({cmd_data[63:48], cmd_data[15:0]} != exp_tag) recv_code = 8'd1;
            else if (cmd_last) recv_code = 8'd3;
            else if (cmd_data[47:16] != 32'h0) recv_code = 8'd2;
        end else if (!family54_q && word_index_q == 6'd51) begin
            // Documented trailing zero padding word of the 52-word family.
            if ({cmd_data[63:48], cmd_data[15:0]} != 32'h0) recv_code = 8'd1;
            else if (cmd_last) recv_code = 8'd3;
            else if (cmd_data[47:16] != 32'h0) recv_code = 8'd2;
        end else begin
            exp_tag = canonical_tag(body_now[5:0]);
            if (body_now[5:0] > 6'd49) recv_code = 8'd1;
            else if ({cmd_data[63:48], cmd_data[15:0]} != exp_tag)
                recv_code = 8'd1;
            else if (cmd_last !=
                     (word_index_q == (family54_q ? 6'd53 : 6'd50)))
                recv_code = 8'd3;
            else begin
                case (body_now[5:0])
                    6'd13, 6'd14, 6'd15, 6'd16:
                        frame_ok = (cmd_data[47:16] == 32'h00010000);
                    6'd18: frame_ok = (cmd_data[47:16] == 32'h000f000f);
                    6'd35: frame_ok = (cmd_data[47:16] == 32'h0);
                    6'd37, 6'd41: frame_ok =
                        (cmd_data[47:16] == 32'h00000053);
                    6'd42: frame_ok = (cmd_data[47:16] == 32'h00000383);
                    6'd43: frame_ok = (cmd_data[47:16] == 32'h00000001);
                    6'd46, 6'd47, 6'd48:
                        frame_ok = (cmd_data[47:16] == 32'h0);
                    6'd49: frame_ok = (cmd_data[47:16] == 32'h0000000d);
                    default: frame_ok = 1'b1;
                endcase
                if (!frame_ok) recv_code = 8'd2;
            end
        end
    end

    assign cmd_ready = rst_n && !error && (state_q == STREAM ||
                                           state_q == LOCKED);
    assign config_valid = rst_n && !error && state_q == VALIDATED;
    assign busy = rst_n && !error && !(state_q == STREAM && word_index_q == 6'd0) &&
                  state_q != LOCKED && state_q != FAULT;
    assign error = rst_n && state_q == FAULT;
    assign error_code = !rst_n ? 8'd0 : error ? saved_code_q : 8'd0;

    logic word_fire;
    assign word_fire = rst_n && !error && state_q == STREAM && cmd_valid &&
                       cmd_ready;
    logic fam54_now;
    logic storage_slot;
    logic [5:0] store_index;
    assign fam54_now = (word_index_q == 6'd1) ? word1_is_rdma : family54_q;
    assign storage_slot = fam54_now ? (word_index_q >= 6'd4) :
                                      (word_index_q >= 6'd1);
    assign store_index = body_now[5:0];
    logic store_en;
    assign store_en = word_fire && (recv_code == 8'd0) && storage_slot &&
                      (word_index_q != 6'd0) &&
                      (body_now[5:0] < 6'd50);

    // ------------------------------------------------------------------
    // Validation / derivation (combinational, sampled once in CHECK).
    // ------------------------------------------------------------------
    logic [31:0] w_conv1, w_conv2, w_conv3, w_ds0, w_ds1, w_ds2, w_ds3;
    logic [31:0] w_ws0, w_ws1, w_ws2, w_cbuf0, w_cbuf1, w_cvt0, w_cvt5;
    logic [31:0] w_in_base, w_dma1, w_dma2, w_fcds0, w_fcds1, w_w_base;
    logic [31:0] w_misc, w_out0, w_out1, w_feat, w_fmt, w_out_base;
    logic [31:0] w_surf, w_cube_w, w_cube_h, w_cube_c, w_bsow, w_wdma0;
    logic [31:0] w_wdma1, w_outcvt, w_surface_add;

    assign w_conv1 = r_word[0];
    assign w_conv2 = r_word[1];
    assign w_conv3 = r_word[2];
    assign w_ds0 = r_word[3];
    assign w_ds1 = r_word[4];
    assign w_ds2 = r_word[5];
    assign w_ds3 = r_word[6];
    assign w_ws0 = r_word[7];
    assign w_ws1 = r_word[8];
    assign w_ws2 = r_word[9];
    assign w_cbuf0 = r_word[10];
    assign w_cbuf1 = r_word[11];
    assign w_cvt0 = r_word[12];
    assign w_cvt5 = r_word[24];
    assign w_in_base = r_word[17];
    assign w_dma1 = r_word[19];
    assign w_dma2 = r_word[20];
    assign w_fcds0 = r_word[21];
    assign w_fcds1 = r_word[22];
    assign w_w_base = r_word[23];
    assign w_misc = r_word[25];
    assign w_out0 = r_word[26];
    assign w_out1 = r_word[27];
    assign w_feat = r_word[29];
    assign w_fmt = r_word[30];
    assign w_out_base = r_word[31];
    assign w_surf = r_word[32];
    assign w_cube_w = r_word[33];
    assign w_cube_h = r_word[34];
    assign w_cube_c = r_word[36];
    assign w_bsow = r_word[38];
    assign w_wdma0 = r_word[39];
    assign w_wdma1 = r_word[40];
    assign w_outcvt = r_word[44];
    assign w_surface_add = r_word[45];

    logic [5:0]  d_ih, d_iw, d_ow, d_oh, d_ic, d_ic_align, d_align_c;
    logic [5:0]  d_oc, d_align_out;
    logic [2:0]  d_kh, d_kw, d_stride_x, d_stride_y, d_planes;
    logic [2:0]  d_alloc_planes;
    logic [3:0]  d_pack_c2;
    logic [3:0]  d_kernels;
    logic [2:0]  d_c1_blocks;
    logic        d_dw, d_spatial, d_nhwc, d_fp16;
    logic [2:0]  d_out_precision;
    logic [31:0] d_taps, d_pixels, d_atoms_calc, d_per_kernel, d_weight_lanes;
    logic [31:0] d_chunks, d_weight_hw, d_weight_bytes, d_frame_weight;
    logic [31:0] d_planes_up, d_input_bytes, d_block_stride, d_total_atoms;
    logic [31:0] d_chunk_stride_hw, d_pixel_bytes, d_plane_bytes;
    logic [31:0] d_block_bytes, d_chunk_stride_bytes, d_block_plane_bytes;
    logic [31:0] d_out_bytes, d_grains, d_line, d_surf, d_row_entries;
    logic [31:0] d_entries, d_bank_product, d_bank, d_align16;
    logic [31:0] d_plane_words;
    logic [31:0] d_align_expected, d_ows, d_real_mask;

    always @* begin : derive
        d_ih = w_ds0[15:0];
        d_ic_align = w_ds1[15:0];
        d_align_c = w_ds1[15:0];
        d_ic = w_ds1[31:16] + 6'd1;
        d_iw = w_fcds0[31:16];
        d_ow = w_ds2[15:0];
        d_oh = w_out0[31:16] + 6'd1;
        d_kw = w_ws2[31:24];
        d_kh = w_ws2[23:16];
        d_stride_x = w_conv3[2:0];
        d_stride_y = w_conv3[5:3];
        d_dw = (w_conv1[1:0] == 2'b11);
        d_out_precision = w_fmt[31:29];
        d_fp16 = (d_out_precision == 3'd2);
        d_spatial = (d_kh != 3'd1) || (d_kw != 3'd1);
        d_oc = d_dw ? d_ic : w_ws2[15:0];
        d_kernels = (d_oc > 6'd8) ? 4'd8 : d_oc[3:0];
        d_c1_blocks = (d_oc > 6'd8) ? ((d_oc + 6'd7) >> 3) : 3'd1;
        if (family54_q) begin
            d_nhwc = 1'b0;
            d_pack_c2 = 4'd8;
        end else if (d_ic > 6'd1 && d_ic <= 6'd4 &&
                     w_cvt5 == ((32'd1 << d_ic) - 32'd1)) begin
            d_nhwc = 1'b1;
            d_pack_c2 = {1'b0, d_ic[2:0]};
        end else begin
            d_nhwc = 1'b0;
            d_pack_c2 = {1'b0, w_cvt5[2:0]} + 4'd1;
        end
        // One C1 plane per PACK_C2 real/alignment channel slots; the NHWC
        // pack is a single interleaved plane. ceil(max(IC, align_c)/C2).
        // The front loads only real channels: one plane per PACK_C2 real
        // channels (the production front's PLANES = ceil(IC/PACK_C2)). The BO
        // allocation may hold extra aligned planes; that only affects the
        // derived input BO byte size below, not the operand walk.
        d_planes_up = (d_ic > d_ic_align) ? {26'd0, d_ic} :
                                           {26'd0, d_ic_align};
        if (d_nhwc)
            d_alloc_planes = 3'd1;
        else if (d_pack_c2 == 4'd8)
            d_alloc_planes = (d_planes_up[5:0] + 6'd7) >> 3;
        else
            d_alloc_planes = (d_planes_up[5:0] + 6'd3) >> 2;
        if (d_pack_c2 == 4'd8)
            d_planes = ({26'd0, d_ic} + 32'd7) >> 3;
        else
            d_planes = ({26'd0, d_ic} + 32'd3) >> 2;
        d_align16 = ({26'd0, d_oc} + 32'd15) & 32'hfffffff0;
        d_align_expected = family54_q ?
                           ((d_align16 < 32'd32) ? 32'd32 : d_align16) :
                           ((d_align16 < 32'd16) ? 32'd16 : d_align16);
        d_align_out = w_out1[5:0] + 6'd1;
        d_taps = {26'd0, d_kh} * {26'd0, d_kw};
        d_pixels = {26'd0, d_ih} * {26'd0, d_iw};
        d_atoms_calc = {26'd0, d_oh} * {26'd0, d_ow};
        d_per_kernel = d_taps * {26'd0, d_align_c} * 32'd2;
        d_weight_lanes = d_dw ? {26'd0, d_align_c} :
                         family54_q ?
                         ({26'd0, d_kernels} * {26'd0, d_align_c}) :
                         (32'd16 * {26'd0, d_align_c});
        d_chunks = (family54_q || d_dw) ? 32'd1 :
                   (({26'd0, d_oc} + 32'd15) >> 4);
        d_weight_hw = d_taps * d_weight_lanes * d_chunks;
        d_weight_bytes = d_weight_hw * 32'd2;
        d_frame_weight = d_dw ? {28'd0, d_kernels} :
                               ({28'd0, d_kernels} * {26'd0, d_ic});
        d_input_bytes = d_alloc_planes * d_pixels * {26'd0, d_pack_c2} * 32'd2;
        d_block_stride = d_atoms_calc;
        d_total_atoms = d_atoms_calc * {29'd0, d_c1_blocks};
        d_chunk_stride_hw = d_taps * d_weight_lanes;
        d_pixel_bytes = {26'd0, d_pack_c2} * 32'd2;
        d_plane_words = d_pixels * {26'd0, d_pack_c2};
        d_plane_bytes = d_pixels * d_pixel_bytes;
        d_block_bytes = d_atoms_calc << 4;
        d_chunk_stride_bytes = d_chunk_stride_hw << 1;
        // FP32 output layout: one 16-byte atom per (output plane, output
        // pixel); a block advances one plane group of C2=4 channels.
        d_block_plane_bytes = ({29'd0, d_kernels} >> 2) *
                              (d_atoms_calc << 4);
        d_out_bytes = d_fp16 ? (w_surf * ({26'd0, d_align_out} >> 3))
                             : (d_atoms_calc * {26'd0, d_oc} * 32'd4);
        if (d_dw) begin
            if (({26'd0, d_ih} + {26'd0, d_kh}) > 32'd13) d_grains = 32'd13;
            else d_grains = {26'd0, d_ih} + {26'd0, d_kh};
        end else if (family54_q && !d_spatial) begin
            if (({26'd0, d_ih} + {26'd0, d_kh}) < 32'd52) d_grains = 32'd52;
            else d_grains = {26'd0, d_ih} + {26'd0, d_kh};
        end else begin
            d_grains = {26'd0, d_ih} + {26'd0, d_kh};
        end
        d_line = d_nhwc ? w_ds0[31:16] : (w_ds0[31:16] * 32'd4);
        d_surf = d_nhwc ? (w_ds0[31:16] * ({26'd0, d_ih} - 32'd1))
                        : (d_ih > 6'd4 ?
                           (w_ds0[31:16] * ({26'd0, d_ih} - 32'd4)) : 32'd0);
        d_row_entries = ((w_ds0[31:16] * {26'd0, d_align_c}) + 32'd31) >> 5;
        d_entries = (d_align_c >= 6'd16 || d_dw) ? d_row_entries :
                    (d_row_entries * {26'd0, d_ih} * 32'd4);
        d_bank_product = (w_ds0[31:16] * d_grains * {26'd0, d_align_c}) << 1;
        d_bank = (d_bank_product + 32'd32767) >> 15;
        if (d_bank < 32'd1) d_bank = 32'd1;
        if (d_bank > 32'd11) d_bank = 32'd11;
        if (d_spatial && (d_nhwc || d_dw)) d_bank = 32'd11;
        if (family54_q) d_ows = d_spatial ? (((d_atoms_calc + 32'd3) >> 2) << 2)
                                          : d_atoms_calc;
        else d_ows = (!d_spatial && d_atoms_calc < 32'd4) ? d_atoms_calc
                                                          : (((d_atoms_calc + 32'd3) >> 2) << 2);
        d_real_mask = (d_ic >= 6'd32) ? 32'hffffffff : ((32'd1 << d_ic) - 32'd1);
    end

    logic [7:0]  check_code;
    logic [31:0] chk_in_end, chk_w_end, chk_out_end;
    logic        chk_overlap;
    always @* begin : validate
        check_code = 8'd0;
        chk_in_end = 32'd0;
        chk_w_end = 32'd0;
        chk_out_end = 32'd0;
        chk_overlap = 1'b0;
        // --- control words (exact donor values) ---
        if (family54_q) begin
            if (w_conv1 != 32'h0000_0120 && w_conv1 != 32'h0000_0123)
                check_code = 8'd2;
        end else if (d_dw) begin
            if (w_conv1 != 32'h0000_0123) check_code = 8'd2;
        end else if (d_nhwc) begin
            if (w_conv1 != (32'h6000_0000 |
                            ((32'd7 + {26'd0, d_ic}) << 12) |
                            32'h0000_0120))
                check_code = 8'd2;
        end else if (w_conv1 != 32'h0000_0120) begin
            check_code = 8'd2;
        end
        // --- channel/geometry range gates ---
        if (check_code == 8'd0) begin
            if (d_kh == 3'd0 || d_kw == 3'd0 ||
                d_kh > 3'(MAX_KERNEL) || d_kw > 3'(MAX_KERNEL))
                check_code = 8'd2;
            else if (d_ic == 6'd0 || d_ic > 6'(MAX_CHANNELS) ||
                     d_ic_align < d_ic || d_ic_align > 6'(MAX_CHANNELS))
                check_code = 8'd2;
            else if (d_pack_c2 != 4'd4 && d_pack_c2 != 4'd8)
                check_code = 8'd2;
            else if (d_oc == 6'd0 || d_oc > 6'(MAX_CHANNELS))
                check_code = 8'd2;
            else if (d_c1_blocks > 3'(MAX_OUTPUT_BLOCKS))
                check_code = 8'd2;
            else if (d_dw && d_oc != d_ic)
                check_code = 8'd2;
            else if (d_stride_x != d_stride_y || d_stride_x == 3'd0 ||
                     d_stride_x > 3'(MAX_STRIDE))
                check_code = 8'd2;
            else if (d_dw && d_kh != d_kw)
                check_code = 8'd2;
            else if (d_dw && w_ws2[15:0] != 32'h1)
                check_code = 8'd2;
            else if (w_conv3[15:6] != 0)
                check_code = 8'd2;
            else if (d_ih < d_kh || d_iw < d_kw)
                check_code = 8'd2;
            else if (d_ih != (d_oh - 6'd1) * {3'd0, d_stride_y} + d_kh ||
                     d_iw != (d_ow - 6'd1) * {3'd0, d_stride_x} + d_kw)
                check_code = 8'd2;
            else if (d_pixels > 32'(MAX_INPUT_PIXELS))
                check_code = 8'd2;
            else if (d_weight_hw > 32'(MAX_WEIGHT_HALFWORDS))
                check_code = 8'd2;
            else if (!d_fp16 && (d_pack_c2 != 4'd4 ||
                                 (d_kernels[1:0] != 2'b00)))
                check_code = 8'd2;
        end
        // --- redundant geometry cross-checks ---
        if (check_code == 8'd0) begin
            if (w_ds0[31:16] < {26'd0, d_iw}) check_code = 8'd2;
            else if (w_fcds0[15:0] != {26'd0, d_ih}) check_code = 8'd2;
            else if (w_fcds1 != {26'd0, d_ic_align}) check_code = 8'd2;
            else if (d_atoms_calc != w_ds3) check_code = 8'd2;
            else if (w_out0[15:0] + 32'd1 != {26'd0, d_ow} ||
                     w_cube_w + 32'd1 != {26'd0, d_ow}) check_code = 8'd2;
            else if (w_cube_h + 32'd1 != {26'd0, d_oh}) check_code = 8'd2;
            else if (w_cube_c[15:0] != w_out1[15:0] ||
                     w_wdma0 != w_out1) check_code = 8'd2;
            else if (w_cube_c[31:16] + 32'd1 != {26'd0, d_oc}) check_code = 8'd2;
            else if (w_wdma1[31:16] + 32'd1 != {26'd0, d_oh} ||
                     w_wdma1[15:0] + 32'd1 != {26'd0, d_ow}) check_code = 8'd2;
            else if (d_align_out != d_align_expected[5:0]) check_code = 8'd2;
            else if (w_misc[9:8] != 2'd2 || w_misc[1] != d_dw ||
                     w_misc[0] != d_spatial || w_misc[31:10] != 0 ||
                     w_misc[7:2] != 0) check_code = 8'd2;
            else if (w_feat[4:3] != (d_dw ? 2'b11 : 2'b00) ||
                     w_feat[2:1] != 2'b10 || w_feat[0] != 1'b0 ||
                     w_feat[9:5] != 5'd15 || w_feat[31:10] != 0)
                check_code = 8'd2;
            else if (d_out_precision != 3'd2 && d_out_precision != 3'd5)
                check_code = 8'd2;
            else if (w_fmt != (({29'd0, d_out_precision} << 29) |
                               (32'd2 << 26) | 32'd2)) check_code = 8'd2;
        end
        // --- channel packing / schedule cross-checks ---
        if (check_code == 8'd0) begin
            if (family54_q) begin
                if (w_cvt0 != 32'h1) check_code = 8'd2;
                else if (!d_dw && w_cvt5 != 32'h0) check_code = 8'd2;
                else if (d_dw && w_cvt5 != 32'h7) check_code = 8'd2;
            end else begin
                if (w_cvt0 != (d_spatial ? 32'h0b : 32'h01))
                    check_code = 8'd2;
                else if (d_nhwc &&
                         w_cvt5 != ((32'd1 << d_ic) - 32'd1))
                    check_code = 8'd2;
                else if (!d_nhwc && w_cvt5 != ({29'd0, d_pack_c2} - 32'd1))
                    check_code = 8'd2;
            end
        end
        if (check_code == 8'd0) begin
            if (w_conv2[31:4] != d_grains || w_conv2[3:0] != 0)
                check_code = 8'd2;
            else if (w_cbuf1 != d_entries) check_code = 8'd2;
            else if (w_dma1 != d_line || w_dma2 != d_surf) check_code = 8'd2;
            else if (w_surf[31:4] != d_ows[27:0] || w_surf[3:0] != 0)
                check_code = 8'd2;
            else if (w_surface_add != (d_ows * 32'd32)) check_code = 8'd2;
            else if (w_cbuf0[31:14] != 0 ||
                     ({1'b0, w_cbuf0[3:0]} + {1'b0, w_cbuf0[7:4]}) != 5'd12 ||
                     w_cbuf0[3:0] == 4'd0 || w_cbuf0[3:0] > 4'd11 ||
                     w_cbuf0[7:4] == 4'd0 || w_cbuf0[7:4] > 4'd11 ||
                     w_cbuf0[13] != 1'b0 ||
                     (w_cbuf0[3:0] != d_bank[3:0] && w_cbuf0[3:0] != 4'd11))
                check_code = 8'd2;
        end
        // --- weight BO sizes ---
        if (check_code == 8'd0) begin
            if (d_dw) begin
                if (w_ws0 != d_per_kernel || w_ws1 != d_per_kernel)
                    check_code = 8'd2;
            end else begin
                if (w_ws1 != d_per_kernel || w_ws0 != d_weight_bytes)
                    check_code = 8'd2;
            end
            if (check_code == 8'd0 &&
                d_frame_weight > ({26'd0, d_kernels} * {26'd0, d_align_c}))
                check_code = 8'd2;
        end
        // --- output BO size / conversion ---
        if (check_code == 8'd0) begin
            if (d_out_bytes == 0) check_code = 8'd2;
            else if (w_outcvt != (d_fp16 ? 32'h0001_0001 : 32'h0))
                check_code = 8'd2;
            else if (w_bsow != (((d_dw || !d_fp16) ? 32'd3 : 32'd1) * 32'd292 +
                                32'd2))
                check_code = 8'd2;
        end
        // --- buffer gate ---
        if (check_code == 8'd0) begin
            chk_in_end = w_in_base + d_input_bytes;
            chk_w_end = w_w_base + d_weight_bytes;
            chk_out_end = w_out_base + d_out_bytes;
            if (w_in_base[3:0] != 0 || w_w_base[3:0] != 0 ||
                w_out_base[3:0] != 0) check_code = 8'd4;
            else if (chk_in_end < w_in_base || chk_w_end < w_w_base ||
                     chk_out_end < w_out_base) check_code = 8'd4;
            else begin
                chk_overlap =
                    ((w_in_base < chk_w_end) && (w_w_base < chk_in_end)) ||
                    ((w_in_base < chk_out_end) && (w_out_base < chk_in_end)) ||
                    ((w_w_base < chk_out_end) && (w_out_base < chk_w_end));
                if (chk_overlap) check_code = 8'd4;
            end
        end
    end

    // ------------------------------------------------------------------
    // Sequential control.
    // ------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= STREAM;
            word_index_q <= 6'd0;
            family54_q <= 1'b0;
            saved_code_q <= 8'd0;
            cfg_input_h <= '0; cfg_input_w <= '0;
            cfg_output_h <= '0; cfg_output_w <= '0;
            cfg_kernel_h <= '0; cfg_kernel_w <= '0; cfg_stride <= '0;
            cfg_depthwise <= 1'b0; cfg_input_channels <= '0;
            cfg_input_align <= '0; cfg_pack_c2 <= '0; cfg_planes <= '0;
            cfg_output_channels <= '0; cfg_kernels <= '0; cfg_c1_blocks <= '0;
            cfg_weight_mode <= '0; cfg_chunk_lanes <= '0; cfg_align_c <= '0;
            cfg_output_fp16 <= 1'b0; cfg_output_atom_lanes <= '0;
            cfg_input_base <= '0; cfg_weight_base <= '0; cfg_output_base <= '0;
            cfg_input_bytes <= '0; cfg_weight_bytes <= '0;
            cfg_output_bytes <= '0; cfg_taps <= '0;
            cfg_frame_weight_halfwords <= '0; cfg_weight_halfwords <= '0;
            cfg_weight_lanes <= '0; cfg_block_stride <= '0;
            cfg_total_atoms <= '0; cfg_plane_words <= '0;
            cfg_pixel_bytes <= '0; cfg_plane_bytes <= '0;
            cfg_block_bytes <= '0; cfg_chunk_stride_bytes <= '0;
            cfg_block_plane_bytes <= '0; cfg_real_mask <= '0;
        end else begin
            case (state_q)
                STREAM: if (word_fire) begin
                    if (recv_code != 8'd0) begin
                        saved_code_q <= recv_code;
                        state_q <= FAULT;
                    end else begin
                        if (store_en) r_word[store_index] <= cmd_data[47:16];
                        if (word_index_q == 6'd1)
                            family54_q <= word1_is_rdma;
                        if ((word_index_q == 6'd53 && family54_q) ||
                            (word_index_q == 6'd51 && !family54_q))
                            state_q <= DERIVE;
                        else
                            word_index_q <= word_index_q + 6'd1;
                    end
                end
                DERIVE: state_q <= CHECK;
                CHECK: begin
                    if (check_code != 8'd0) begin
                        saved_code_q <= check_code;
                        state_q <= FAULT;
                    end else begin
                        cfg_input_h <= d_ih;
                        cfg_input_w <= d_iw;
                        cfg_output_h <= d_oh;
                        cfg_output_w <= d_ow;
                        cfg_kernel_h <= d_kh;
                        cfg_kernel_w <= d_kw;
                        cfg_stride <= d_stride_x;
                        cfg_depthwise <= d_dw;
                        cfg_input_channels <= d_ic;
                        cfg_input_align <= d_ic_align;
                        cfg_pack_c2 <= d_pack_c2;
                        cfg_planes <= d_planes;
                        cfg_output_channels <= d_oc;
                        cfg_kernels <= d_kernels;
                        cfg_c1_blocks <= d_c1_blocks;
                        cfg_weight_mode <= d_dw ? 2'd1 :
                                           (family54_q ? 2'd0 : 2'd2);
                        cfg_chunk_lanes <= (family54_q || d_dw) ? 5'd0 : 5'd16;
                        cfg_align_c <= d_align_c;
                        cfg_output_fp16 <= d_fp16;
                        cfg_output_atom_lanes <= d_fp16 ? 4'd8 : 4'd4;
                        cfg_input_base <= w_in_base;
                        cfg_weight_base <= w_w_base;
                        cfg_output_base <= w_out_base;
                        cfg_input_bytes <= d_input_bytes;
                        cfg_weight_bytes <= d_weight_bytes;
                        cfg_output_bytes <= d_out_bytes;
                        cfg_taps <= d_taps[7:0];
                        cfg_frame_weight_halfwords <= d_frame_weight[9:0];
                        cfg_weight_halfwords <= d_weight_hw[12:0];
                        cfg_weight_lanes <= d_weight_lanes[9:0];
                        cfg_block_stride <= d_block_stride[8:0];
                        cfg_total_atoms <= d_total_atoms[9:0];
                        cfg_plane_words <= d_plane_words[11:0];
                        cfg_pixel_bytes <= d_pixel_bytes[4:0];
                        cfg_plane_bytes <= d_plane_bytes[12:0];
                        cfg_block_bytes <= d_block_bytes[12:0];
                        cfg_chunk_stride_bytes <= d_chunk_stride_bytes[14:0];
                        cfg_block_plane_bytes <= d_block_plane_bytes[14:0];
                        cfg_real_mask <= d_real_mask;
                        state_q <= VALIDATED;
                    end
                end
                VALIDATED: if (config_ready) state_q <= LOCKED;
                LOCKED: if (cmd_valid) begin
                    saved_code_q <= 8'd7;
                    state_q <= FAULT;
                end
                default: begin
                    saved_code_q <= 8'd6;
                    state_q <= FAULT;
                end
            endcase
        end
    end
endmodule
