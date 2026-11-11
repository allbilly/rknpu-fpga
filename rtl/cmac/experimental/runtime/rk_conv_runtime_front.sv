// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Generalized runtime-configured spatial front (EXPERIMENTAL prototype).
//
// Same frame contract as `rk_conv_3x3_valid_c4_front`: one kh-major CMAC frame
// per (output atom, kernel tap), assembled into the 8704-bit frame bus over
// `frame_weight_halfwords + input_channels` cycles, with the tag fields the
// CACC requires (atom address, first/last/last_output, real-lane masks).
//
// Everything the production front takes as an elaboration parameter is a
// runtime input decoded by `rk_conv_runtime_decode`: spatial geometry, stride,
// depthwise mode, real channels and packing, output-channel blocking, the three
// captured weight BO layouts (kh-major / depthwise-spatial / 16-OC chunks) and
// the FP16-atom output address walk. Operand storage is sized for the capture
// corpus maxima (320 input pixels, 4608 weight halfwords) in single-port RAMs.
// The emit walk uses counters and precomputed deltas; there is no runtime
// division. Bounded spatial schedule, not a full NVDLA CBUF/CSC model.
module rk_conv_runtime_front #(
    // Corpus-verified lanes: max 16 channel lanes (C16 jobs) and 16 kernel
    // lanes, provided by the additive experimental cell/array copies.
    parameter int unsigned ATOMIC_C = 16,
    parameter int unsigned ATOMIC_K = 16
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         cfg_valid,
    output logic         cfg_ready,
    input  logic [5:0]   cfg_input_h,
    input  logic [5:0]   cfg_input_w,
    input  logic [5:0]   cfg_output_h,
    input  logic [5:0]   cfg_output_w,
    input  logic [2:0]   cfg_kernel_h,
    input  logic [2:0]   cfg_kernel_w,
    input  logic [2:0]   cfg_stride,
    input  logic         cfg_depthwise,
    input  logic [5:0]   cfg_input_channels,
    input  logic [3:0]   cfg_pack_c2,
    input  logic [2:0]   cfg_planes,
    input  logic [3:0]   cfg_kernels,
    input  logic [2:0]   cfg_c1_blocks,
    input  logic [1:0]   cfg_weight_mode,
    input  logic [5:0]   cfg_align_c,
    input  logic [31:0]  cfg_input_base,
    input  logic [31:0]  cfg_weight_base,
    input  logic [31:0]  cfg_output_base,
    input  logic [9:0]   cfg_frame_weight_halfwords,
    input  logic [12:0]  cfg_weight_halfwords,
    input  logic [9:0]   cfg_weight_lanes,
    input  logic [4:0]   cfg_pixel_bytes,
    input  logic [12:0]  cfg_plane_bytes,
    input  logic [12:0]  cfg_block_bytes,
    input  logic [14:0]  cfg_chunk_stride_bytes,
    input  logic [31:0]  cfg_real_mask,
    input  logic         cancel,
    input  logic [7:0]   cancel_code,
    output logic         busy,
    output logic         error,
    output logic [7:0]   error_code,
    output logic         mem_req_valid,
    input  logic         mem_req_ready,
    output logic [31:0]  mem_req_addr,
    input  logic         mem_rsp_valid,
    output logic         mem_rsp_ready,
    input  logic [15:0]  mem_rsp_rdata,
    input  logic         mem_rsp_error,
    output logic         frame_valid,
    input  logic         frame_ready,
    output logic [ATOMIC_C*16-1:0] frame_data,
    output logic [ATOMIC_K*ATOMIC_C*16-1:0] frame_weight,
    output logic [ATOMIC_C-1:0] frame_data_mask,
    output logic [ATOMIC_K*ATOMIC_C-1:0] frame_weight_mask,
    output logic [31:0]  frame_output_address,
    output logic         frame_first,
    output logic         frame_last,
    output logic         frame_last_output
);
    localparam int unsigned MAX_INPUT_PIXELS = 320;
    localparam int unsigned MAX_WEIGHT_HALFWORDS = 4608;
    localparam int unsigned INPUT_WORD_BITS = 15;
    localparam int unsigned WEIGHT_BITS = 13;
    localparam int unsigned TIMEOUT_CYCLES = 65536;

    typedef enum logic [3:0] {
        IDLE, WEIGHT_REQ, WEIGHT_WAIT, INPUT_REQ, INPUT_WAIT,
        ASSEMBLE, EMIT, FINISHED, FAULT
    } state_t;
    state_t state_q;
    logic started_q;

    // Operand storage: simulation keeps the plain arrays (accepted receipts
    // bind the simulation path); synthesis uses the explicit SDP-BRAM mapping
    // below, because Vivado 2026.1 cannot infer block RAM for the plain-array
    // pattern in this prototype. Geometry is identical (16-bit, 10240 / 4608
    // entries) and the read path is the same registered read.
`ifndef SYNTHESIS
    logic [15:0] input_store [0:MAX_INPUT_PIXELS*32-1];
    logic [15:0] weight_store [0:MAX_WEIGHT_HALFWORDS-1];
`endif
    logic [ATOMIC_K*ATOMIC_C*16-1:0] frame_weight_q;
    logic [ATOMIC_C*16-1:0] frame_data_q;

    // Load walk.
    logic [WEIGHT_BITS-1:0] w_idx_q;
    logic [8:0]  i_pix_q;
    logic [2:0]  i_plane_q;
    logic [3:0]  i_chan_q;
    logic [31:0] load_addr_q;
    logic [31:0] i_pix_off_q;

    // Emit walk.
    logic [2:0]  e_block_q;
    logic [5:0]  e_bx_q, e_by_q;
    logic [2:0]  e_tx_q, e_ty_q;
    logic [8:0]  a_index_q;
    logic [10:0] w_lane_q;
    logic [5:0]  w_ch_q;
    logic [10:0] p_lane_q;
    logic [5:0]  p_ch_q, c_issue_q, p_c_q;
    logic [15:0] e_p0_q, e_row_off_q;
    logic [15:0] e_lane_base_q;
    logic [15:0] e_block_hw_q;     // weight-store halfword base of the block
    logic [15:0] e_group_hw_q;     // weight-store halfword base of the tap
    logic [12:0] w_raddr_q;
    logic [INPUT_WORD_BITS-1:0] i_raddr_q;
    logic [31:0] e_out_addr_q;
    logic        weight_read_en, input_read_en;
    logic [15:0] weight_rdata_q, input_rdata_q;

    logic [31:0] stalled_q;
    logic [7:0]  saved_code_q, normalized_cancel_q;
    logic        response_status_bad, response_data_bad;
    logic [15:0] row_step_q;        // stride * IW
    logic [5:0]  last_lane_q;

    // ------------------------------------------------------------------
    // Config-derived helpers.
    // ------------------------------------------------------------------
    // Real lanes in the current input plane (the last plane may be partial).
    logic [5:0] plane_lanes;
    assign plane_lanes = (cfg_pack_c2 == 4'd8) ?
                         (({3'd0, cfg_planes} - 6'd1) << 3) :
                         (({3'd0, cfg_planes} - 6'd1) << 2);
    assign last_lane_q = (i_plane_q == (cfg_planes - 3'd1)) ?
                         (cfg_input_channels - plane_lanes) : cfg_pack_c2;

    logic [INPUT_WORD_BITS-1:0] load_word;

`ifdef SYNTHESIS
    // Explicit simple-dual-port BRAM mapping (see rk_runtime_sdp_bram.sv).
    // Write ports mirror the array assignments exactly; read ports are the
    // existing registered reads. No scheduling/gating/arithmetic change.
    rk_runtime_sdp_bram #(
        .DATA_W(16), .ADDR_W(15), .DEPTH(MAX_INPUT_PIXELS*32)
    ) input_mem (
        .clk(clk),
        .we(rst_n && !error && state_q == INPUT_WAIT && mem_rsp_valid &&
            mem_rsp_ready && !response_status_bad && !response_data_bad),
        .waddr(load_word[14:0]), .wdata(mem_rsp_rdata),
        .re(input_read_en), .raddr(i_raddr_q[14:0]), .rdata(input_rdata_q));
    rk_runtime_sdp_bram #(
        .DATA_W(16), .ADDR_W(13), .DEPTH(8192)
    ) weight_mem (
        .clk(clk),
        .we(rst_n && !error && state_q == WEIGHT_WAIT && mem_rsp_valid &&
            mem_rsp_ready && !response_status_bad && !response_data_bad),
        .waddr(w_idx_q), .wdata(mem_rsp_rdata),
        .re(weight_read_en), .raddr(w_raddr_q), .rdata(weight_rdata_q));
`endif
    always @* begin
        if (cfg_pack_c2 == 4'd8)
            load_word = (i_pix_q << 5) + (i_plane_q << 3) + i_chan_q;
        else
            load_word = (i_pix_q << 5) + (i_plane_q << 2) + i_chan_q;
    end

    logic [15:0] frame_pixel;
    assign frame_pixel = e_p0_q + e_row_off_q + {13'd0, e_tx_q};

    always @* begin
        frame_data_mask = cfg_real_mask[ATOMIC_C-1:0];
        frame_weight_mask = '0;
        for (int k = 0; k < ATOMIC_K; k = k + 1) begin
            if (k < cfg_kernels) begin
                if (cfg_depthwise)
                    frame_weight_mask[k*ATOMIC_C +: ATOMIC_C] =
                        {{(ATOMIC_C-1){1'b0}}, 1'b1} << k;
                else
                    frame_weight_mask[k*ATOMIC_C +: ATOMIC_C] =
                        cfg_real_mask[ATOMIC_C-1:0];
            end
        end
        frame_output_address = e_out_addr_q;
        frame_first = (e_tx_q == 3'd0) && (e_ty_q == 3'd0);
        frame_last = (e_tx_q == (cfg_kernel_w - 3'd1)) &&
                     (e_ty_q == (cfg_kernel_h - 3'd1));
        frame_last_output = (e_block_q == (cfg_c1_blocks - 3'd1)) &&
                            (e_by_q == (cfg_output_h - 6'd1)) &&
                            (e_bx_q == (cfg_output_w - 6'd1));
    end
    assign frame_weight = frame_weight_q;
    assign frame_data = frame_data_q;

    // ------------------------------------------------------------------
    // Memory read ports.
    // ------------------------------------------------------------------
    assign weight_read_en = rst_n && !error && state_q == ASSEMBLE &&
                            ({3'd0, a_index_q} <
                             {2'd0, cfg_frame_weight_halfwords});
`ifndef SYNTHESIS
    always @(posedge clk) begin
        if (weight_read_en) weight_rdata_q <= weight_store[w_raddr_q];
    end
`endif
    assign input_read_en = rst_n && !error && state_q == ASSEMBLE &&
                           ({3'd0, a_index_q} >=
                            {2'd0, cfg_frame_weight_halfwords}) &&
                           ({3'd0, a_index_q} <
                            ({2'd0, cfg_frame_weight_halfwords} +
                             {6'd0, cfg_input_channels}));
`ifndef SYNTHESIS
    always @(posedge clk) begin
        if (input_read_en) input_rdata_q <= input_store[i_raddr_q];
    end
`endif

    // ------------------------------------------------------------------
    // Status.
    // ------------------------------------------------------------------
    assign cfg_ready = rst_n && !error && state_q == IDLE && !started_q;
    assign busy = rst_n && !error && state_q != IDLE && state_q != FINISHED;
    assign error = rst_n && (state_q == FAULT || cancel);
    assign error_code = !rst_n ? 8'd0 : state_q == FAULT ? saved_code_q :
                        cancel ? normalized_cancel_q : 8'd0;
    assign mem_req_valid = rst_n && !error &&
                           (state_q == WEIGHT_REQ || state_q == INPUT_REQ);
    assign mem_rsp_ready = rst_n && !error &&
                           (state_q == WEIGHT_WAIT || state_q == INPUT_WAIT);
    assign frame_valid = rst_n && !error && state_q == EMIT;

    always @* begin
        case (cancel_code)
            1, 2, 3, 4, 5, 6, 7, 8: normalized_cancel_q = cancel_code;
            default: normalized_cancel_q = 8'd6;
        endcase
        response_status_bad = mem_rsp_error;
        response_data_bad = 1'b0;
`ifndef SYNTHESIS
        if (mem_rsp_error !== 1'b0) response_status_bad = 1'b1;
        if ((^mem_rsp_rdata) === 1'bx) response_data_bad = 1'b1;
`endif
    end

    // ------------------------------------------------------------------
    // Next-frame walk (combinational).
    // ------------------------------------------------------------------
    logic [2:0]  n_block, n_tx, n_ty;
    logic [5:0]  n_bx, n_by;
    logic [15:0] n_p0, n_row_off, n_lane_base, n_block_hw, n_group_hw;
    logic [31:0] n_out_addr;
    logic        frame_accept, final_frame;
    logic [9:0]  next_pixel_w;
    assign frame_accept = frame_valid && frame_ready;
    // The next frame's pixel includes the tap-column offset too: the
    // adopted front recomputes frame_pixel_for(atom, tap_next) directly.
    assign next_pixel_w = n_p0[9:0] + n_row_off[9:0] + n_tx;

    always @* begin
        n_block = e_block_q;
        n_bx = e_bx_q;
        n_by = e_by_q;
        n_tx = e_tx_q;
        n_ty = e_ty_q;
        n_p0 = e_p0_q;
        n_row_off = e_row_off_q;
        n_lane_base = e_lane_base_q;
        n_block_hw = e_block_hw_q;
        n_group_hw = e_group_hw_q;
        n_out_addr = e_out_addr_q;
        final_frame = 1'b0;
        if (e_tx_q < (cfg_kernel_w - 3'd1)) begin
            n_tx = e_tx_q + 3'd1;
            n_group_hw = e_group_hw_q + {6'd0, cfg_weight_lanes};
        end else if (e_ty_q < (cfg_kernel_h - 3'd1)) begin
            n_tx = 3'd0;
            n_ty = e_ty_q + 3'd1;
            n_row_off = e_row_off_q + {10'd0, cfg_input_w};
            n_group_hw = e_group_hw_q + {6'd0, cfg_weight_lanes};
        end else begin
            n_tx = 3'd0;
            n_ty = 3'd0;
            n_row_off = 16'd0;
            n_group_hw = e_block_hw_q;
            if (e_bx_q < (cfg_output_w - 6'd1)) begin
                n_bx = e_bx_q + 6'd1;
                n_p0 = e_p0_q + {13'd0, cfg_stride};
                n_out_addr = e_out_addr_q + 32'd16;
            end else if (e_by_q < (cfg_output_h - 6'd1)) begin
                n_bx = 6'd0;
                n_by = e_by_q + 6'd1;
                n_p0 = e_p0_q + row_step_q -
                       ((cfg_output_w - 6'd1) * {3'd0, cfg_stride});
                n_out_addr = e_out_addr_q + 32'd16;
            end else if (e_block_q < (cfg_c1_blocks - 3'd1)) begin
                n_block = e_block_q + 3'd1;
                n_bx = 6'd0;
                n_by = 6'd0;
                n_p0 = 16'd0;
                n_lane_base = e_lane_base_q + {12'd0, cfg_kernels};
                if (cfg_weight_mode == 2'd2)
                    n_block_hw = (n_lane_base >> 4) *
                                     (cfg_chunk_stride_bytes >> 1) +
                                 (n_lane_base & 16'd15) *
                                     {10'd0, cfg_align_c};
                else
                    n_block_hw = 16'd0;
                n_group_hw = n_block_hw;
                n_out_addr = cfg_output_base +
                             ({19'd0, n_block} * cfg_block_bytes);
            end
        end
        // Adopted-front completion: FINISHED only after the last tap of the
        // last output atom (its `tap_index==TAPS-1 && output_atom==TOTAL_ATOMS-1`).
        // Using the next counters alone was true for every tap of the last atom.
        final_frame = (e_tx_q == (cfg_kernel_w - 3'd1)) &&
                      (e_ty_q == (cfg_kernel_h - 3'd1)) &&
                      (e_block_q == (cfg_c1_blocks - 3'd1)) &&
                      (e_by_q == (cfg_output_h - 6'd1)) &&
                      (e_bx_q == (cfg_output_w - 6'd1));
    end

    // ------------------------------------------------------------------
    // Sequential schedule.
    // ------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= IDLE;
            started_q <= 1'b0;
            w_idx_q <= '0;
            i_pix_q <= '0;
            i_plane_q <= '0;
            i_chan_q <= '0;
            load_addr_q <= '0;
            i_pix_off_q <= '0;
            e_block_q <= '0; e_bx_q <= '0; e_by_q <= '0;
            e_tx_q <= '0; e_ty_q <= '0;
            a_index_q <= '0; w_lane_q <= '0; w_ch_q <= '0;
            p_lane_q <= '0; p_ch_q <= '0; c_issue_q <= '0; p_c_q <= '0;
            e_p0_q <= '0; e_row_off_q <= '0; e_lane_base_q <= '0;
            e_block_hw_q <= '0; e_group_hw_q <= '0;
            w_raddr_q <= '0; i_raddr_q <= '0; e_out_addr_q <= '0;
            stalled_q <= '0; saved_code_q <= '0;
            frame_weight_q <= '0; frame_data_q <= '0;
            mem_req_addr <= '0;
            row_step_q <= '0;
        end else if (!error) begin
            if ((state_q != WEIGHT_REQ && state_q != WEIGHT_WAIT &&
                 state_q != INPUT_REQ && state_q != INPUT_WAIT) ||
                (mem_req_valid && mem_req_ready) ||
                (mem_rsp_valid && mem_rsp_ready))
                stalled_q <= '0;
            else
                stalled_q <= stalled_q + 32'd1;

            case (state_q)
                IDLE: if (cfg_valid && cfg_ready) begin
                    started_q <= 1'b1;
                    w_idx_q <= '0;
                    i_pix_q <= '0;
                    i_plane_q <= '0;
                    i_chan_q <= '0;
                    load_addr_q <= cfg_weight_base;
                    mem_req_addr <= cfg_weight_base;
                    i_pix_off_q <= '0;
                    row_step_q <= ({10'd0, cfg_stride} * {10'd0, cfg_input_w});
                    state_q <= WEIGHT_REQ;
                end
                WEIGHT_REQ: if (mem_req_ready) state_q <= WEIGHT_WAIT;
                WEIGHT_WAIT: if (mem_rsp_valid && mem_rsp_ready) begin
                    if (response_status_bad) begin
                        saved_code_q <= 8'd5;
                        state_q <= FAULT;
                    end else if (response_data_bad) begin
                        saved_code_q <= 8'd6;
                        state_q <= FAULT;
                    end else begin
`ifndef SYNTHESIS
                        weight_store[w_idx_q] <= mem_rsp_rdata;
`endif
                        if (w_idx_q == (cfg_weight_halfwords - 13'd1)) begin
                            i_pix_q <= '0;
                            i_plane_q <= '0;
                            i_chan_q <= '0;
                            i_pix_off_q <= '0;
                            load_addr_q <= cfg_input_base;
                            mem_req_addr <= cfg_input_base;
                            state_q <= INPUT_REQ;
                        end else begin
                            w_idx_q <= w_idx_q + 13'd1;
                            load_addr_q <= load_addr_q + 32'd2;
                            mem_req_addr <= load_addr_q + 32'd2;
                            state_q <= WEIGHT_REQ;
                        end
                    end
                end
                INPUT_REQ: if (mem_req_ready) state_q <= INPUT_WAIT;
                INPUT_WAIT: if (mem_rsp_valid && mem_rsp_ready) begin
                    if (response_status_bad) begin
                        saved_code_q <= 8'd5;
                        state_q <= FAULT;
                    end else if (response_data_bad) begin
                        saved_code_q <= 8'd6;
                        state_q <= FAULT;
                    end else begin
`ifndef SYNTHESIS
                        input_store[load_word] <= mem_rsp_rdata;
`endif
                        if (i_chan_q == (last_lane_q[3:0] - 4'd1)) begin
                            i_chan_q <= '0;
                            if (i_plane_q == (cfg_planes - 3'd1)) begin
                                i_plane_q <= '0;
                                if (i_pix_q == ((cfg_input_h *
                                                 cfg_input_w) - 9'd1)) begin
                                    e_block_q <= '0; e_bx_q <= '0;
                                    e_by_q <= '0; e_tx_q <= '0; e_ty_q <= '0;
                                    e_p0_q <= '0; e_row_off_q <= '0;
                                    e_lane_base_q <= '0;
                                    e_block_hw_q <= '0;
                                    e_group_hw_q <= '0;
                                    e_out_addr_q <= cfg_output_base;
                                    a_index_q <= '0;
                                    w_lane_q <= '0; w_ch_q <= '0;
                                    p_lane_q <= '0; p_ch_q <= '0;
                                    c_issue_q <= '0; p_c_q <= '0;
                                    w_raddr_q <= '0; i_raddr_q <= '0;
                                    frame_weight_q <= '0;
                                    frame_data_q <= '0;
                                    state_q <= ASSEMBLE;
                                end else begin
                                    i_pix_q <= i_pix_q + 9'd1;
                                    i_pix_off_q <= i_pix_off_q +
                                                   {27'd0, cfg_pixel_bytes};
                                    load_addr_q <= cfg_input_base +
                                                   i_pix_off_q +
                                                   {27'd0, cfg_pixel_bytes};
                                    mem_req_addr <= cfg_input_base +
                                                   i_pix_off_q +
                                                   {27'd0, cfg_pixel_bytes};
                                    state_q <= INPUT_REQ;
                                end
                            end else begin
                                i_plane_q <= i_plane_q + 3'd1;
                                load_addr_q <= load_addr_q +
                                    ({19'd0, cfg_plane_bytes} -
                                     (({26'd0, last_lane_q} - 32'd1) << 1));
                                mem_req_addr <= load_addr_q +
                                    ({19'd0, cfg_plane_bytes} -
                                     (({26'd0, last_lane_q} - 32'd1) << 1));
                                state_q <= INPUT_REQ;
                            end
                        end else begin
                            i_chan_q <= i_chan_q + 4'd1;
                            load_addr_q <= load_addr_q + 32'd2;
                            mem_req_addr <= load_addr_q + 32'd2;
                            state_q <= INPUT_REQ;
                        end
                    end
                end
                ASSEMBLE: begin
                    // Place the halfword that was issued last cycle.
                    if (a_index_q > 9'd0 &&
                        ({3'd0, a_index_q} <= {2'd0, cfg_frame_weight_halfwords})) begin
                        if (cfg_depthwise)
                            frame_weight_q[(p_lane_q*ATOMIC_C + p_lane_q)*16 +: 16]
                                <= weight_rdata_q;
                        else
                            frame_weight_q[(p_lane_q*ATOMIC_C + p_ch_q)*16 +: 16]
                                <= weight_rdata_q;
                    end
                    if (({3'd0, a_index_q} > {2'd0, cfg_frame_weight_halfwords}) &&
                        ({3'd0, a_index_q} <=
                         ({2'd0, cfg_frame_weight_halfwords} +
                          {6'd0, cfg_input_channels})))
                        frame_data_q[p_c_q*16 +: 16] <= input_rdata_q;
                    // Issue the next operand read and advance its walk.
                    if ({3'd0, a_index_q} < {2'd0, cfg_frame_weight_halfwords}) begin
                        p_lane_q <= w_lane_q;
                        p_ch_q <= w_ch_q;
                        if (cfg_depthwise) begin
                            w_lane_q <= w_lane_q + 11'd1;
                            w_ch_q <= '0;
                            w_raddr_q <= w_raddr_q + 13'd1;
                        end else if ((w_ch_q + 6'd1) ==
                                     cfg_input_channels) begin
                            w_lane_q <= w_lane_q + 11'd1;
                            w_ch_q <= '0;
                            w_raddr_q <= w_raddr_q +
                                ({7'd0, cfg_align_c} -
                                 {7'd0, cfg_input_channels} + 13'd1);
                        end else begin
                            w_ch_q <= w_ch_q + 6'd1;
                            w_raddr_q <= w_raddr_q + 13'd1;
                        end
                    end else if ({3'd0, a_index_q} <
                                 ({2'd0, cfg_frame_weight_halfwords} +
                                  {6'd0, cfg_input_channels})) begin
                        // The read port is driven from the registered
                        // address, so prepare the *next* channel's address.
                        i_raddr_q <= {frame_pixel[9:0], 5'd0} +
                                     {9'd0, c_issue_q} + 15'd1;
                        p_c_q <= c_issue_q;
                        c_issue_q <= c_issue_q + 6'd1;
                    end
                    if ({3'd0, a_index_q} ==
                        ({2'd0, cfg_frame_weight_halfwords} +
                         {6'd0, cfg_input_channels})) begin
                        a_index_q <= '0;
                        w_lane_q <= '0;
                        w_ch_q <= '0;
                        p_lane_q <= '0;
                        p_ch_q <= '0;
                        c_issue_q <= '0;
                        p_c_q <= '0;
                        w_raddr_q <= n_group_hw[12:0];
                        i_raddr_q <= {next_pixel_w, 5'd0};
                        // The assembled frame must stay on the bus through
                        // EMIT; the adopted front clears the buses only after
                        // the frame is accepted (EMIT branch), not here.
                        state_q <= EMIT;
                    end else begin
                        a_index_q <= a_index_q + 9'd1;
                    end
                end
                EMIT: if (frame_accept) begin
                    e_block_q <= n_block;
                    e_bx_q <= n_bx;
                    e_by_q <= n_by;
                    e_tx_q <= n_tx;
                    e_ty_q <= n_ty;
                    e_p0_q <= n_p0;
                    e_row_off_q <= n_row_off;
                    e_lane_base_q <= n_lane_base;
                    e_block_hw_q <= n_block_hw;
                    e_group_hw_q <= n_group_hw;
                    e_out_addr_q <= n_out_addr;
                    a_index_q <= '0;
                    w_lane_q <= '0;
                    w_ch_q <= '0;
                    p_lane_q <= '0;
                    p_ch_q <= '0;
                    c_issue_q <= '0;
                    p_c_q <= '0;
                    w_raddr_q <= n_group_hw[12:0];
                    i_raddr_q <= {next_pixel_w, 5'd0};
                    frame_weight_q <= '0;
                    frame_data_q <= '0;
                    if (final_frame) state_q <= FINISHED;
                    else state_q <= ASSEMBLE;
                end
                FINISHED: begin end
                default: begin
                    saved_code_q <= 8'd6;
                    state_q <= FAULT;
                end
            endcase

            if ((state_q == WEIGHT_REQ || state_q == WEIGHT_WAIT ||
                 state_q == INPUT_REQ || state_q == INPUT_WAIT) &&
                !(mem_req_valid && mem_req_ready) &&
                !(mem_rsp_valid && mem_rsp_ready) &&
                stalled_q >= TIMEOUT_CYCLES - 1) begin
                saved_code_q <= 8'd8;
                state_q <= FAULT;
            end
        end
    end
endmodule
