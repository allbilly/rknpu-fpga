// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Capture-bounded spatial front. Geometry, kernel size, real channels,
// packed-lane width, kernel count and the number of C1 planes are elaboration
// parameters rather than literal capture tables. It loads the original packed
// operands into local storage, then emits one kh-major CMAC frame per kernel
// tap and output pixel. This is still a bounded spatial schedule, not full
// NVDLA CBUF/CSC behavior.
//
// Weight storage is a **single-read-port RAM**, and each frame is assembled
// over several cycles into a register. An earlier form read the whole packed
// weight BO combinationally at many indices in one cycle to build the
// 8192-bit `frame_weight` bus per kernel lane. That is a many-port array: it
// cannot map to block RAM, so Vivado dissolved it into flip-flops, and a C16
// geometry needs 73,728 bits, which exceeds the dissolve limit and fails
// `synth_design`. Reading one halfword per cycle from a proper RAM keeps the
// storage in block RAM and removes the mux tree entirely.
//
// The frame cadence is unchanged: one frame per (output atom, kernel tap),
// with `frame_first`/`frame_last` and a tag stable across all taps of an atom.
// Only the number of cycles used to build a frame changes.
module rk_conv_3x3_valid_c4_front #(
    // Spatial execution geometry. The local pixel window uses fixed 3x3 taps.
    parameter int unsigned INPUT_H = 9,
    parameter int unsigned INPUT_W = 9,
    parameter int unsigned OUTPUT_H = 7,
    parameter int unsigned OUTPUT_W = 7,
    parameter int unsigned STRIDE = 1,
    // Kernel extent. The default 3x3 preserves the original captured profiles.
    parameter int unsigned KH = 3,
    parameter int unsigned KW = 3,
    // Real convolution dimensions. INPUT_CHANNELS real channels are packed
    // into ceil(C/PACK_C2) C1 planes; KERNELS must fit the C32/K16 frame.
    parameter int unsigned INPUT_CHANNELS = 4,
    parameter int unsigned KERNELS = 4,
    // Output-channel blocking for the two-task OC16/OC32 captures. Each block
    // is KERNELS consecutive output channels; C1_BLOCKS blocks are emitted per
    // output pixel and write OUT_BLOCK_STRIDE atoms apart in the BO.
    parameter int unsigned C1_BLOCKS = 1,
    parameter int unsigned OUT_BLOCK_STRIDE = 0,
    // Weight chunk layout for the conv-simple captures: the BO stores
    // [oc_chunk][tap][oc_lane][align_c], so one chunk holds 16 output-channel
    // lanes per tap. CHUNK_LANES is that lane count.
    parameter int unsigned CHUNK_LANES = 0,
    // NVDLA-aligned input-channel count in the weight BO (align_c), and the
    // packed C2 lanes per feature pixel (8 lanes = 16 bytes).
    parameter int unsigned ALIGN_C = 16,
    parameter int unsigned PACK_C2 = 8,
    // Depthwise execution: each kernel k reduces only input channel k, so the
    // per-kernel mask is a single diagonal bit and the weight image is the
    // donor's depthwise_spatial_major [ky][kx][C2] layout.
    parameter bit DEPTHWISE = 1'b0,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         config_valid,
    output logic         config_ready,
    input  logic [31:0]  config_input_base,
    input  logic [31:0]  config_weight_base,
    input  logic [31:0]  config_output_base,
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
    output logic [511:0] frame_data,
    output logic [8191:0] frame_weight,
    output logic [31:0]  frame_data_mask,
    output logic [511:0] frame_weight_mask,
    output logic [31:0]  frame_output_address,
    output logic         frame_first,
    output logic         frame_last,
    output logic         frame_last_output
);
    // Kernel taps are derived from the requested window rather than fixed at 9.
    localparam int unsigned TAPS = KH * KW;
    localparam int unsigned PIXEL_BYTES = PACK_C2 * 2;
    localparam int unsigned INPUT_PIXELS = INPUT_H * INPUT_W;
    localparam int unsigned PLANE_BYTES = INPUT_PIXELS * PIXEL_BYTES;
    localparam int unsigned PLANES = (INPUT_CHANNELS + PACK_C2 - 1) / PACK_C2;
    localparam int unsigned LAST_PLANE_LANES = INPUT_CHANNELS - (PLANES-1)*PACK_C2;
    // Depthwise packs one lane per channel into [ky][kx][c2_out]; c2_out
    // is ALIGN_C, not the C2 atom width. Using PACK_C2 here aliased the
    // next tap whenever KERNELS exceeded one 16-byte atom.
    // Weight halfwords per tap. Three BO layouts are supported, each derived
    // from a captured packing function rather than guessed:
    //   depthwise   [ky][kx][C2]                     -> ALIGN_C lanes
    //   chunked     [oc_chunk][ky][kx][oc_lane][aC]  -> CHUNK_LANES*aC lanes
    //   capture     [ky][kx][oc_lane][aC]            -> KERNELS*aC lanes
    localparam int unsigned CHUNKS = (CHUNK_LANES != 0) ?
        ((C1_BLOCKS * KERNELS + CHUNK_LANES - 1) / CHUNK_LANES) : 1;
    localparam int unsigned WEIGHT_LANES = DEPTHWISE ? ALIGN_C :
        (CHUNK_LANES != 0) ? CHUNK_LANES * ALIGN_C : KERNELS * ALIGN_C;
    localparam int unsigned WEIGHT_HALFWORDS = TAPS * WEIGHT_LANES * CHUNKS;
    // Halfwords consumed to build one frame's weight bus. The BO stores them
    // contiguously per (chunk, tap) group, so one sequential walk covers every
    // real channel of every kernel lane of that tap.
    localparam int unsigned FRAME_WEIGHT_HALFWORDS = DEPTHWISE ? KERNELS :
                                                     KERNELS * INPUT_CHANNELS;
    // The frame_data bus is filled the same way: one real channel per cycle.
    localparam int unsigned FRAME_DATA_LANES = INPUT_CHANNELS;
    localparam int unsigned ASSEMBLE_CYCLES =
        FRAME_WEIGHT_HALFWORDS + FRAME_DATA_LANES;
    localparam int unsigned BLOCK_STRIDE = (OUT_BLOCK_STRIDE != 0) ?
        OUT_BLOCK_STRIDE : OUTPUT_H * OUTPUT_W;
    localparam int unsigned TOTAL_ATOMS = BLOCK_STRIDE * C1_BLOCKS;
    // Counter widths are derived from the geometry instead of fixed at 7 bits;
    // an 11x28 depthwise plane has 308 pixels and 234 output atoms.
    localparam int unsigned PIXEL_BITS = $clog2(INPUT_H*INPUT_W + 1);
    // The input window RAM is indexed by pixel*32 + lane, so its address
    // needs one more dimension than the pixel counter.
    localparam int unsigned INPUT_WORD_BITS = PIXEL_BITS + 5;
    // The atom counter spans all C1 blocks, not just one block's pixels.
    localparam int unsigned ATOM_BITS = $clog2(TOTAL_ATOMS + 1);
    localparam int unsigned WEIGHT_BITS = $clog2(WEIGHT_HALFWORDS + 1);
    localparam int unsigned ASSEMBLE_BITS = $clog2(ASSEMBLE_CYCLES + 1);
    localparam logic [31:0] REAL_MASK = (32'd1 << INPUT_CHANNELS) - 32'd1;

    typedef enum logic [3:0] {
        IDLE, WEIGHT_REQ, WEIGHT_WAIT, INPUT_REQ, INPUT_WAIT,
        ASSEMBLE, EMIT, FINISHED, FAULT
    } state_t;
    state_t state;
    logic [31:0] input_base, output_base;
    logic [WEIGHT_BITS-1:0] weight_index;
    logic [PIXEL_BITS-1:0] pixel_index;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [1:0] plane_index;
    logic [2:0] channel_index;
    logic [ATOM_BITS-1:0] output_atom;
    logic [5:0] tap_index;
    logic [31:0] stalled_cycles;
    logic [7:0] saved_code, normalized_cancel;
    logic response_status_bad, response_data_bad;
    // Feature window in a single-port RAM: PIXELS * 32 lanes hold C32 in four
    // C2=8 planes, and smaller channel counts use a prefix. The previous form
    // was a many-port array read at up to 32 indices in one cycle to build the
    // 512-bit frame_data bus, so it could not map to RAM and dissolved into
    // flip-flops, which is both the largest LUT consumer and the longest
    // combinational path in the image.
    logic [15:0] input_store [0:INPUT_H*INPUT_W*32-1];
    logic input_write_en;
    logic [INPUT_WORD_BITS-1:0] input_waddr;
    logic input_read_en;
    logic [INPUT_WORD_BITS-1:0] input_raddr;
    logic [15:0] input_rdata_q;
    // Single-read-port weight RAM. The write port is used only while loading
    // the BO; the read port only while assembling a frame. Both are
    // synchronous, which is what lets synthesis keep this in block RAM.
    logic [15:0] weight_store [0:WEIGHT_HALFWORDS-1];
    logic weight_write_en;
    logic [WEIGHT_BITS-1:0] weight_waddr;
    logic weight_read_en;
    logic [WEIGHT_BITS-1:0] weight_raddr;
    logic [15:0] weight_rdata_q;
    // Registered frame weight bus, filled one halfword per cycle.
    logic [8191:0] frame_weight_q;
    logic [511:0] frame_data_q;
    logic [ASSEMBLE_BITS-1:0] assemble_index;
    logic [31:0] weight_group_base_q;
    logic [PIXEL_BITS-1:0] frame_pixel_q;

    // Pure function of (output atom, tap): first halfword of the contiguous
    // group this frame reads. Derived from the captured BO layouts, never a
    // literal table. Kept as a function so the frame address is recomputed
    // from the registers rather than patched incrementally.
    function automatic logic [PIXEL_BITS-1:0] frame_pixel_for(
        input logic [31:0] atom, input logic [31:0] tap);
        integer y, x, ty, tx;
        begin
            y = (atom % BLOCK_STRIDE) / OUTPUT_W;
            x = (atom % BLOCK_STRIDE) % OUTPUT_W;
            ty = tap / KW;
            tx = tap % KW;
            frame_pixel_for =
                PIXEL_BITS'((y * STRIDE + ty) * INPUT_W + x * STRIDE + tx);
        end
    endfunction

    function automatic logic [31:0] weight_group_address(
        input logic [31:0] atom, input logic [31:0] tap);
        integer lanes, lane_base_f, chunk_f;
        begin
            lanes = atom / BLOCK_STRIDE;
            lane_base_f = lanes * KERNELS;
            chunk_f = (CHUNK_LANES != 0) ? (lane_base_f / CHUNK_LANES) : 0;
            if (DEPTHWISE)
                weight_group_address = tap * ALIGN_C;
            else
                weight_group_address =
                    chunk_f * TAPS * WEIGHT_LANES + tap * WEIGHT_LANES +
                    (lane_base_f - chunk_f * CHUNK_LANES) * ALIGN_C;
        end
    endfunction
    integer output_y, output_x, tap_y, tap_x, input_pixel;
    integer kernel_lane, input_lane;

    initial begin
        if (TIMEOUT_CYCLES == 0)
            $fatal(1, "spatial conv front timeout must be positive");
        if (KH < 1 || KW < 1 || KH > 5 || KW > 5)
            $fatal(1, "spatial conv front supports kernels from 1x1 to 5x5");
        if (INPUT_H < KH || INPUT_W < KW || OUTPUT_H < 1 || OUTPUT_W < 1)
            $fatal(1, "spatial conv front geometry is too small");
        if (INPUT_H != (OUTPUT_H - 1) * STRIDE + KH ||
            INPUT_W != (OUTPUT_W - 1) * STRIDE + KW)
            $fatal(1, "spatial conv front geometry does not match KH/KW/stride");
        if (INPUT_CHANNELS < 1 || INPUT_CHANNELS > 32)
            $fatal(1, "spatial conv front supports one to 32 real channels");
        if (KERNELS < 1 || KERNELS > 16)
            $fatal(1, "spatial conv front supports one to sixteen real kernels");
        if (C1_BLOCKS < 1 || C1_BLOCKS * KERNELS > 32)
            $fatal(1, "spatial conv front output blocking exceeds 32 channels");
        if (CHUNK_LANES != 0 && (CHUNK_LANES % 8) != 0)
            $fatal(1, "chunked weight lanes must be a multiple of eight");
        if (ALIGN_C < INPUT_CHANNELS || ALIGN_C > 32)
            $fatal(1, "spatial conv front align_c must cover real channels");
        if (DEPTHWISE && KERNELS != INPUT_CHANNELS)
            $fatal(1, "depthwise execution needs one kernel per real channel");
        if (DEPTHWISE && KERNELS > ALIGN_C)
            $fatal(1, "depthwise kernel count must fit one aligned weight group");
        if (PACK_C2 != 4 && PACK_C2 != 8)
            $fatal(1, "spatial conv front consumes C2=4 or C2=8 packed planes");
        if (TOTAL_ATOMS > 4096)
            $fatal(1, "spatial conv front output atom index is too large");
        if (FRAME_WEIGHT_HALFWORDS > ALIGN_C * KERNELS)
            $fatal(1, "frame weight walk exceeds one tap group");
        if (FRAME_WEIGHT_HALFWORDS == 0)
            $fatal(1, "frame weight walk must visit at least one halfword");
        if (INPUT_WORD_BITS > 32)
            $fatal(1, "input window address does not fit 32 bits");
    end

    // Write port. No reset: the whole array is written by the weight phase
    // before any read, and a reset on a RAM array prevents block RAM inference.
    assign weight_write_en = rst_n && state == WEIGHT_WAIT;
    assign weight_waddr = weight_index;
    always_ff @(posedge clk) begin
        if (weight_write_en && mem_rsp_valid)
            weight_store[weight_waddr] <= mem_rsp_rdata;
    end
    // Input window RAM: one write port (load phase) and one read port
    // (assemble phase), plus a registered pixel pointer for the emitted frame.
    assign input_write_en = rst_n && state == INPUT_WAIT && mem_rsp_valid;
    wire [31:0] input_waddr_w = (32'(pixel_index) * 32'd32) +
                                (32'(plane_index) * 32'(PACK_C2)) +
                                32'(channel_index);
    assign input_waddr = input_waddr_w[INPUT_WORD_BITS-1:0];
    always_ff @(posedge clk) begin
        if (input_write_en)
            input_store[input_waddr] <= mem_rsp_rdata;
    end
    assign input_read_en = rst_n && state == ASSEMBLE &&
                           (32'(assemble_index) >= FRAME_WEIGHT_HALFWORDS) &&
                           (32'(assemble_index) < ASSEMBLE_CYCLES);
    wire [31:0] input_raddr_w = (32'(frame_pixel_q) * 32'd32) +
                                (32'(assemble_index) - 32'(FRAME_WEIGHT_HALFWORDS));
    assign input_raddr = input_raddr_w[INPUT_WORD_BITS-1:0];
    always_ff @(posedge clk) begin
        if (input_read_en)
            input_rdata_q <= input_store[input_raddr];
    end

    // Read port: combinational address off the stable group base, registered
    // data out. One halfword per cycle.
    // Address of the halfword the walk is currently on. Real channels only,
    // so the stride over the BO's align_c lanes is explicit.
    wire [31:0] assemble_slot = 32'(assemble_index);
    wire [31:0] weight_read_address_w = DEPTHWISE ?
        ({22'd0, weight_group_base_q[WEIGHT_BITS-1:0]} +
         32'(assemble_index)) :
        ({22'd0, weight_group_base_q[WEIGHT_BITS-1:0]} +
         32'(assemble_slot / 32'(INPUT_CHANNELS)) * 32'(ALIGN_C) +
         32'(assemble_slot % 32'(INPUT_CHANNELS)));
    assign weight_raddr = weight_read_address_w[WEIGHT_BITS-1:0];
    assign weight_read_en = rst_n && state == ASSEMBLE &&
                            (32'(assemble_index) < FRAME_WEIGHT_HALFWORDS);
    always_ff @(posedge clk) begin
        if (weight_read_en)
            weight_rdata_q <= weight_store[weight_raddr];
    end

    // Sequential walk of one tap group. The BO stores, per (chunk, tap),
    // `KERNELS*ALIGN_C` contiguous halfwords in [oc_lane][align_c] order, so
    // one counter covers the whole frame.
    always @* begin
        case (cancel_code)
            1,2,3,4,5,6,7,8: normalized_cancel = cancel_code;
            default: normalized_cancel = 6;
        endcase
        response_status_bad = mem_rsp_error;
        response_data_bad = 1'b0;
`ifndef SYNTHESIS
        if (mem_rsp_error !== 1'b0) response_status_bad = 1'b1;
        if ((^mem_rsp_rdata) === 1'bx) response_data_bad = 1'b1;
`endif

        output_y = 32'(output_atom % BLOCK_STRIDE) / OUTPUT_W;
        output_x = 32'(output_atom % BLOCK_STRIDE) % OUTPUT_W;
        tap_y = 32'(tap_index) / KW;
        tap_x = 32'(tap_index) % KW;
        input_pixel = (output_y * STRIDE + tap_y) * INPUT_W +
                      output_x * STRIDE + tap_x;

        frame_data_mask = REAL_MASK;
        frame_weight_mask = '0;
        for (kernel_lane = 0; kernel_lane < KERNELS; kernel_lane = kernel_lane + 1) begin
            if (DEPTHWISE)
                // One diagonal lane per kernel: only channel==kernel takes part.
                frame_weight_mask[kernel_lane*32 +: 32] = 32'd1 << kernel_lane;
            else
                // Only the real aligned-channel lanes take part. Padded lanes
                // in the captured BO stay masked off rather than becoming data.
                frame_weight_mask[kernel_lane*32 +: 32] = REAL_MASK;
        end
        // DPU output atoms are 16-byte aligned: 8 packed FP16 lanes per atom.
        // Atom addresses are 16-byte aligned and block-major: C1 block b
        // starts BLOCK_STRIDE atoms after block b-1.
        frame_output_address = output_base +
                               ({{(32-ATOM_BITS){1'b0}}, output_atom} << 4);
        frame_first = tap_index == 6'd0;
        frame_last = tap_index == 6'(TAPS - 1);
        // CACC requires a stable tag over all nine tap frames. Mark every
        // frame belonging to the final output atom; frame_last separately
        // identifies the final reduction tap.
        frame_last_output = 32'(output_atom) == TOTAL_ATOMS-1;
    end

    assign frame_weight = frame_weight_q;
    assign frame_data = frame_data_q;

    assign config_ready = rst_n && !error && state == IDLE;
    assign busy = rst_n && !error && state != IDLE && state != FINISHED;
    assign error = rst_n && (state == FAULT || cancel);
    assign error_code = !rst_n ? 8'd0 : state == FAULT ? saved_code :
                        cancel ? normalized_cancel : 8'd0;
    assign mem_req_valid = rst_n && !error &&
                           (state == WEIGHT_REQ || state == INPUT_REQ);
    assign mem_rsp_ready = rst_n && !error &&
                           (state == WEIGHT_WAIT || state == INPUT_WAIT);
    assign frame_valid = rst_n && !error && state == EMIT;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            input_base <= 0;
            output_base <= 0;
            weight_index <= 0;
            pixel_index <= 0;
            plane_index <= 0;
            channel_index <= 0;
            output_atom <= 0;
            tap_index <= 0;
            stalled_cycles <= 0;
            saved_code <= 0;
            mem_req_addr <= 0;
            assemble_index <= 0;
            frame_weight_q <= '0;
        end else if (!error) begin
            if ((state != WEIGHT_REQ && state != WEIGHT_WAIT &&
                 state != INPUT_REQ && state != INPUT_WAIT) ||
                (mem_req_valid && mem_req_ready) ||
                (mem_rsp_valid && mem_rsp_ready))
                stalled_cycles <= 0;
            else stalled_cycles <= stalled_cycles + 1'b1;

            case (state)
                IDLE: if (config_valid && config_ready) begin
                    input_base <= config_input_base;
                    output_base <= config_output_base;
                    weight_index <= 0;
                    pixel_index <= 0;
                    plane_index <= 0;
                    channel_index <= 0;
                    output_atom <= 0;
                    tap_index <= 0;
                    mem_req_addr <= config_weight_base;
                    state <= WEIGHT_REQ;
                end
                WEIGHT_REQ: if (mem_req_ready) state <= WEIGHT_WAIT;
                INPUT_REQ: if (mem_req_ready) state <= INPUT_WAIT;
                WEIGHT_WAIT, INPUT_WAIT: if (mem_rsp_valid && mem_rsp_ready) begin
                    if (response_status_bad) begin
                        saved_code <= 5;
                        state <= FAULT;
                    end else if (response_data_bad) begin
                        saved_code <= 6;
                        state <= FAULT;
                    end else if (state == WEIGHT_WAIT) begin
                        if (32'(weight_index) == WEIGHT_HALFWORDS-1) begin
                            pixel_index <= 0;
                            plane_index <= 0;
                            channel_index <= 0;
                            mem_req_addr <= input_base;
                            state <= INPUT_REQ;
                        end else begin
                            weight_index <= weight_index + 1'b1;
                            mem_req_addr <= mem_req_addr + 32'd2;
                            state <= WEIGHT_REQ;
                        end
                    end else begin
                        // The input write port already committed this halfword
                        // through `input_write_en`/`input_waddr`; this branch
                        // only advances the address walk.
                        if (32'(channel_index) == ((32'(plane_index) == PLANES-1) ?
                                                   LAST_PLANE_LANES-1 : PACK_C2-1)) begin
                            channel_index <= 0;
                            if (32'(plane_index) == PLANES-1) begin
                                plane_index <= 0;
                                if (32'(pixel_index) == INPUT_H*INPUT_W-1) begin
                                    output_atom <= 0;
                                    tap_index <= 0;
                                    assemble_index <= 0;
                                    // First group of the first atom is tap 0 of
                                    // block 0; derive it, do not assume zero.
                                    weight_group_base_q <=
                                        weight_group_address(32'd0, 32'd0);
                                    frame_pixel_q <=
                                        frame_pixel_for(32'd0, 32'd0);
                                    frame_weight_q <= '0;
                                    frame_data_q <= '0;
                                    state <= ASSEMBLE;
                                end else begin
                                    pixel_index <= pixel_index + 1'b1;
                                    mem_req_addr <= input_base +
                                        (32'(pixel_index) + 32'd1) * PIXEL_BYTES;
                                    state <= INPUT_REQ;
                                end
                            end else begin
                                plane_index <= plane_index + 1'b1;
                                mem_req_addr <= input_base +
                                    32'(plane_index + 1'b1) * PLANE_BYTES +
                                    32'(pixel_index) * PIXEL_BYTES;
                                state <= INPUT_REQ;
                            end
                        end else begin
                            channel_index <= channel_index + 1'b1;
                            mem_req_addr <= mem_req_addr + 32'd2;
                            state <= INPUT_REQ;
                        end
                    end
                end
                ASSEMBLE: begin
                    // One halfword issued per cycle; the previous one has
                    // arrived by this edge and is placed into the frame bus.
                    integer slot, lane_of_slot, channel_of_slot;
                    if (32'(assemble_index) > 0 &&
                        32'(assemble_index) <= FRAME_WEIGHT_HALFWORDS) begin
                        slot = int'(assemble_index) - 1;
                        if (DEPTHWISE) begin
                            // [ky][kx][C2]: lane `kernel` inside that tap.
                            frame_weight_q[(slot*32 + slot)*16 +: 16]
                                <= weight_rdata_q;
                        end else begin
                            // The walk covers only the real channels of each
                            // kernel lane; padded BO lanes stay masked and
                            // zero on the bus.
                            lane_of_slot = slot / int'(INPUT_CHANNELS);
                            channel_of_slot = slot % int'(INPUT_CHANNELS);
                            frame_weight_q[(lane_of_slot*32 + channel_of_slot)*16
                                           +: 16] <= weight_rdata_q;
                        end
                    end
                    if (32'(assemble_index) > FRAME_WEIGHT_HALFWORDS)
                        frame_data_q[(32'(assemble_index) -
                                      FRAME_WEIGHT_HALFWORDS - 1)*16 +: 16]
                            <= input_rdata_q;
                    if (32'(assemble_index) == ASSEMBLE_CYCLES) begin
                        assemble_index <= 0;
                        state <= EMIT;
                    end else assemble_index <= assemble_index + 1'b1;
                end
                EMIT: if (frame_valid && frame_ready) begin
                    if (tap_index == 6'(TAPS - 1)) begin
                        if (32'(output_atom) == TOTAL_ATOMS-1) state <= FINISHED;
                        else begin
                            output_atom <= output_atom + 1'b1;
                            tap_index <= 0;
                            assemble_index <= 0;
                            // Recompute the group base from the *next* atom and
                            // tap 0. Deriving it beats patching an incremental
                            // offset, which is where the chunk arithmetic would
                            // drift.
                            weight_group_base_q <= weight_group_address(
                                32'(output_atom) + 32'd1, 32'd0);
                            frame_pixel_q <= frame_pixel_for(
                                                 32'(output_atom) + 32'd1,
                                                 32'd0);
                            frame_weight_q <= '0;
                            frame_data_q <= '0;
                            state <= ASSEMBLE;
                        end
                    end else begin
                        tap_index <= tap_index + 1'b1;
                        assemble_index <= 0;
                        weight_group_base_q <= weight_group_address(
                            32'(output_atom), 32'(tap_index) + 32'd1);
                        frame_pixel_q <= frame_pixel_for(32'(output_atom),
                                                         32'(tap_index) + 32'd1);
                        frame_weight_q <= '0;
                        frame_data_q <= '0;
                        state <= ASSEMBLE;
                    end
                end
                FINISHED: begin end
                default: begin
                    saved_code <= 6;
                    state <= FAULT;
                end
            endcase

            if ((state == WEIGHT_REQ || state == WEIGHT_WAIT ||
                 state == INPUT_REQ || state == INPUT_WAIT) &&
                !(mem_req_valid && mem_req_ready) &&
                !(mem_rsp_valid && mem_rsp_ready) &&
                stalled_cycles >= TIMEOUT_CYCLES - 1) begin
                saved_code <= 8;
                state <= FAULT;
            end
        end
    end
endmodule
