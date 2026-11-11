// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Output re-layout for the captured FP32 conv-simple case
// (`conv_simple_fp16_1x1_c4_h8_w8_oc16`).
//
// Why this module exists. That capture's output surface is
//   [c1][pixel][c2],  c2 = 4 FP32 words (16 bytes) per atom
// i.e. one 16-byte atom per (output-channel plane, pixel). The spatial front
// instead emits one frame per pixel *per block*, and each frame carries
// `LANES` consecutive channels. With `C2 = 4`, every frame therefore spans
// exactly two planes, and each of its `LANES` values belongs to a different
// 4-byte slot inside one of two 16-byte atoms:
//
//   channel = block*LANES + lane
//   plane   = channel / C2
//   slot    = channel % C2
//   address = base + plane*H*W*4 + pixel*16 + slot*4
//
// This was verified against the frozen capture before the module was written:
// that mapping reproduces all 1024 FP32 words of the device BO to within
// 2.4e-7 (FP32 accumulation order), and both NHWC and plain NCHW layouts
// disagree by whole values. So this is a pure addressing/ordering stage —
// never arithmetic, never a data fixup.
//
// The base is captured from the first frame and every later frame must follow
// the same 16-byte atom stride; a mismatch is an explicit fault rather than a
// silently misplaced tensor.
module rk_conv_output_c1c2_fp32 #(
    parameter int unsigned LANES = 8,            // channels carried per frame
    parameter int unsigned BLOCKS = 2,           // output-channel blocks
    parameter int unsigned C2 = 4,               // FP32 words per 16-byte atom
    parameter int unsigned HEIGHT = 8,
    parameter int unsigned WIDTH = 8,
    // Address distance between consecutive per-pixel frames.
    parameter int unsigned ATOM_STRIDE_BYTES = 16,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         in_valid,
    output logic         in_ready,
    input  logic [LANES*32-1:0] in_values,
    input  logic [31:0]  in_address,
    input  logic         in_last,
    input  logic         cancel,
    input  logic [7:0]   cancel_code,
    output logic         busy,
    output logic         acknowledged,
    output logic         frame_done,
    output logic         done,
    output logic         error,
    output logic [7:0]   error_code,
    output logic         mem_req_valid,
    input  logic         mem_req_ready,
    output logic         mem_req_write,
    output logic [31:0]  mem_req_addr,
    output logic [15:0]  mem_req_wdata,
    input  logic         mem_rsp_valid,
    output logic         mem_rsp_ready,
    input  logic         mem_rsp_error
);
    localparam int unsigned PIXELS = HEIGHT * WIDTH;
    // Each c1 plane holds PIXELS*C2 words; that is the stride between planes.
    localparam int unsigned PLANE_BYTES = PIXELS * C2 * 4;
    localparam int unsigned VALUE_W = LANES * 32;

    typedef enum logic [1:0] {IDLE, EMIT, ACK} state_t;
    state_t state_q;

    logic [VALUE_W-1:0] values_q;
    logic [31:0] base_q;
    logic base_valid_q;
    logic [31:0] lane_q;
    logic [31:0] block_q;      // output-channel block of the buffered frame
    logic [31:0] pixel_q;      // pixel index of the buffered frame
    logic last_frame_q;
    logic [7:0] saved_code_q;
    logic fault_q;
    logic done_q, frame_done_q;
    // A value is complete when the writer has started and returned to idle:
    // `acknowledged` pulses once per halfword, so it cannot drive the walk.
    logic writer_started_q;

    wire [31:0] channel_index = block_q * LANES + lane_q;
    wire [31:0] plane_index = channel_index / C2;
    wire [31:0] slot_index = channel_index % C2;
    wire [31:0] lane_address = base_q +
                               plane_index * 32'(PLANE_BYTES) +
                               pixel_q * 32'(ATOM_STRIDE_BYTES) +
                               slot_index * 32'd4;

    logic writer_ready, writer_busy, writer_ack, writer_done, writer_error;
    logic writer_req_valid, writer_rsp_ready;
    logic [7:0] writer_code;
    wire writer_valid = rst_n && !fault_q && state_q == EMIT && !writer_busy;
    wire [31:0] writer_value = values_q[lane_q*32 +: 32];

    assign in_ready = rst_n && !fault_q && !cancel && state_q == IDLE;
    assign busy = rst_n && !fault_q && state_q != IDLE;
    assign acknowledged = writer_ack && !fault_q;
    assign frame_done = frame_done_q;
    assign done = done_q;
    assign mem_req_valid = writer_req_valid && !fault_q;
    assign mem_rsp_ready = writer_rsp_ready && !fault_q;
    assign error = rst_n && (fault_q || writer_error);
    assign error_code = !rst_n ? 8'd0 : fault_q ? saved_code_q :
                        writer_error ? writer_code : 8'd0;

    initial begin
        if (LANES == 0 || LANES > 32)
            $fatal(1, "C1C2 FP32 writer supports one to 32 channels per frame");
        if (C2 != 4)
            $fatal(1, "C1C2 FP32 writer expects four words per 16-byte atom");
        if (LANES % C2 != 0)
            $fatal(1, "each frame must span whole C2 atoms");
        if (PIXELS == 0)
            $fatal(1, "C1C2 FP32 writer needs at least one pixel");
        if (ATOM_STRIDE_BYTES != 16)
            $fatal(1, "C1C2 FP32 writer expects a 16-byte per-pixel atom");
    end

    rk_cmac_fp32_writer #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) writer (
        .clk, .rst_n,
        .result_valid(writer_valid), .result_ready(writer_ready),
        .result_address(lane_address), .result_value(writer_value),
        .result_last(lane_q == LANES-1 && last_frame_q),
        .busy(writer_busy), .acknowledged(writer_ack), .done(writer_done),
        .error(writer_error), .error_code(writer_code),
        .mem_req_valid(writer_req_valid), .mem_req_ready(mem_req_ready),
        .mem_req_write(mem_req_write), .mem_req_addr(mem_req_addr),
        .mem_req_wdata(mem_req_wdata),
        .mem_rsp_valid(mem_rsp_valid), .mem_rsp_ready(writer_rsp_ready),
        .mem_rsp_error(mem_rsp_error)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= IDLE;
            values_q <= '0;
            base_q <= 32'd0;
            base_valid_q <= 1'b0;
            lane_q <= 32'd0;
            block_q <= 32'd0;
            pixel_q <= 32'd0;
            last_frame_q <= 1'b0;
            saved_code_q <= 8'd0;
            fault_q <= 1'b0;
            done_q <= 1'b0;
            frame_done_q <= 1'b0;
            writer_started_q <= 1'b0;
        end else if (!fault_q) begin
            done_q <= 1'b0;
            frame_done_q <= 1'b0;
            if (writer_busy)
                writer_started_q <= 1'b1;
            if (cancel) begin
                fault_q <= 1'b1;
                saved_code_q <= (cancel_code >= 1 && cancel_code <= 8) ?
                                 cancel_code : 8'd6;
            end else case (state_q)
                IDLE: begin
                    if (in_valid && in_ready) begin
                        if (!base_valid_q) begin
                            // The first frame defines the surface base.
                            base_q <= in_address;
                            base_valid_q <= 1'b1;
                        end else if (in_address < base_q ||
                                     ((in_address - base_q) % ATOM_STRIDE_BYTES) != 0) begin
                            fault_q <= 1'b1;
                            saved_code_q <= 8'd4;
                        end else if ((in_address - base_q) / ATOM_STRIDE_BYTES >=
                                     BLOCKS * PIXELS) begin
                            fault_q <= 1'b1;
                            saved_code_q <= 8'd3;
                        end
                        values_q <= in_values;
                        // The front packs atoms as block*PIXELS + pixel.
                        block_q <= ((in_address - (base_valid_q ? base_q : in_address))
                                    / ATOM_STRIDE_BYTES) / PIXELS;
                        pixel_q <= ((in_address - (base_valid_q ? base_q : in_address))
                                    / ATOM_STRIDE_BYTES) % PIXELS;
                        lane_q <= 32'd0;
                        last_frame_q <= in_last;
                        writer_started_q <= 1'b0;
                        state_q <= EMIT;
                    end
                end
                EMIT: if (writer_valid && writer_ready)
                    state_q <= ACK;
                ACK: begin
                    if (writer_started_q && !writer_busy) begin
                        frame_done_q <= 1'b1;
                        writer_started_q <= 1'b0;
                        if ((lane_q == LANES-1 && last_frame_q) != writer_done) begin
                            // The walk and the writer must agree on the final value.
                            fault_q <= 1'b1;
                            saved_code_q <= 8'd6;
                        end else if (lane_q != LANES-1) begin
                            lane_q <= lane_q + 32'd1;
                            state_q <= EMIT;
                        end else begin
                            lane_q <= 32'd0;
                            if (last_frame_q) begin
                                state_q <= IDLE;
                                base_valid_q <= 1'b0;
                                done_q <= 1'b1;
                            end else begin
                                state_q <= IDLE;
                            end
                        end
                    end
                end
                default: begin
                    fault_q <= 1'b1;
                    saved_code_q <= 8'd6;
                end
            endcase
            if (writer_error) begin
                fault_q <= 1'b1;
                saved_code_q <= writer_code;
            end
        end
    end
endmodule
