// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Runtime-configurable FP32 output placement for the captured conv-simple
// FP32 profile (EXPERIMENTAL prototype).
//
// The captured FP32 surface is `[c1][pixel][c2=4]` 32-bit words (measured, not
// assumed; see docs/CONV_SIMPLE_FIXTURES.md): one 16-byte atom per
// (output-channel plane, pixel), four FP32 slots per atom. A CACC frame
// carries `LANES` consecutive output channels of one output-channel block, so
//   channel = block*LANES + lane
//   plane   = channel / 4
//   slot    = channel % 4
//   address = base + plane*PIXELS*16 + pixel*16 + slot*4
// and the value itself is passed to `rk_cmac_fp32_writer` unchanged.
//
// Runtime inputs replace the elaboration parameters of the production
// `rk_conv_output_c1c2_fp32` stage. This is a transport/placement stage only:
// it never converts, rounds or repairs a value.
module rk_conv_runtime_fp32_output (
    input  logic         clk,
    input  logic         rst_n,
    // Runtime configuration (stable while the job runs).
    input  logic [3:0]   cfg_lanes,     // output channels carried per frame
    input  logic [2:0]   cfg_blocks,    // output-channel blocks
    input  logic [9:0]   cfg_pixels,    // output atoms per block
    input  logic         in_valid,
    output logic         in_ready,
    input  logic [255:0] in_values,     // up to 8 x 32-bit CACC groups
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
    typedef enum logic [1:0] {IDLE, EMIT, ACK} state_t;
    state_t state_q;

    logic [255:0] values_q;
    logic [31:0]  base_q;
    logic         base_valid_q;
    logic [3:0]   lane_q;
    logic [2:0]   block_q;
    logic [9:0]   pixel_q;
    logic         last_frame_q;
    logic [7:0]   saved_code_q;
    logic         fault_q;
    logic         done_q, frame_done_q;
    logic         writer_started_q;
    logic [31:0]  plane_byte_q, pixel_byte_q, frame_byte_q;
    logic [31:0]  lane_addr;
    logic [31:0]  expect_addr;

    assign lane_addr = base_q + plane_byte_q + pixel_byte_q +
                       (({28'd0, lane_q} >> 2) * (cfg_pixels * 32'd16)) +
                       (({28'd0, lane_q} & 32'd3) * 32'd4);
    assign expect_addr = base_valid_q ? (base_q + frame_byte_q) : in_address;

    logic writer_ready, writer_busy, writer_ack, writer_done, writer_error;
    logic writer_req_valid, writer_rsp_ready;
    logic [7:0] writer_code;
    wire writer_valid = rst_n && !fault_q && state_q == EMIT && !writer_busy;
    wire [31:0] writer_value = values_q[lane_q*32 +: 32];
    wire writer_last = (lane_q == (cfg_lanes - 4'd1)) && last_frame_q;

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

    rk_cmac_fp32_writer #(.TIMEOUT_CYCLES(65536)) writer (
        .clk, .rst_n,
        .result_valid(writer_valid), .result_ready(writer_ready),
        .result_address(lane_addr), .result_value(writer_value),
        .result_last(writer_last),
        .busy(writer_busy), .acknowledged(writer_ack), .done(writer_done),
        .error(writer_error), .error_code(writer_code),
        .mem_req_valid(writer_req_valid), .mem_req_ready(mem_req_ready),
        .mem_req_write(mem_req_write), .mem_req_addr(mem_req_addr),
        .mem_req_wdata(mem_req_wdata),
        .mem_rsp_valid(mem_rsp_valid), .mem_rsp_ready(writer_rsp_ready),
        .mem_rsp_error(mem_rsp_error));

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= IDLE;
            values_q <= '0;
            base_q <= '0;
            base_valid_q <= 1'b0;
            lane_q <= '0;
            block_q <= '0;
            pixel_q <= '0;
            last_frame_q <= 1'b0;
            saved_code_q <= '0;
            fault_q <= 1'b0;
            done_q <= 1'b0;
            frame_done_q <= 1'b0;
            writer_started_q <= 1'b0;
            plane_byte_q <= '0;
            pixel_byte_q <= '0;
            frame_byte_q <= '0;
        end else if (!fault_q) begin
            done_q <= 1'b0;
            frame_done_q <= 1'b0;
            if (writer_busy) writer_started_q <= 1'b1;
            if (cancel) begin
                fault_q <= 1'b1;
                saved_code_q <= (cancel_code >= 1 && cancel_code <= 8) ?
                                 cancel_code : 8'd6;
            end else case (state_q)
                IDLE: if (in_valid && in_ready) begin
                    if (!base_valid_q) begin
                        base_q <= in_address;
                        base_valid_q <= 1'b1;
                        frame_byte_q <= 32'd0;
                        plane_byte_q <= 32'd0;
                        pixel_byte_q <= 32'd0;
                    end else if (in_address != expect_addr) begin
                        fault_q <= 1'b1;
                        saved_code_q <= 8'd4;
                    end
                    if (pixel_q == (cfg_pixels - 10'd1)) begin
                        if (in_last != (block_q == (cfg_blocks - 3'd1))) begin
                            fault_q <= 1'b1;
                            saved_code_q <= 8'd3;
                        end
                    end else if (in_last) begin
                        fault_q <= 1'b1;
                        saved_code_q <= 8'd3;
                    end
                    values_q <= in_values;
                    last_frame_q <= in_last;
                    lane_q <= '0;
                    writer_started_q <= 1'b0;
                    state_q <= EMIT;
                end
                EMIT: if (writer_valid && writer_ready) state_q <= ACK;
                ACK: begin
                    if (writer_started_q && !writer_busy) begin
                        frame_done_q <= 1'b1;
                        writer_started_q <= 1'b0;
                        if (writer_last != writer_done) begin
                            fault_q <= 1'b1;
                            saved_code_q <= 8'd6;
                        end else if (lane_q != (cfg_lanes - 4'd1)) begin
                            lane_q <= lane_q + 4'd1;
                            state_q <= EMIT;
                        end else begin
                            lane_q <= '0;
                            frame_byte_q <= frame_byte_q + 32'd16;
                            if (pixel_q == (cfg_pixels - 10'd1)) begin
                                pixel_q <= '0;
                                pixel_byte_q <= 32'd0;
                                block_q <= block_q + 3'd1;
                                plane_byte_q <= plane_byte_q +
                                    (({29'd0, cfg_lanes} >> 2) *
                                     (cfg_pixels * 32'd16));
                            end else begin
                                pixel_q <= pixel_q + 10'd1;
                                pixel_byte_q <= pixel_byte_q + 32'd16;
                            end
                            if (last_frame_q) begin
                                done_q <= 1'b1;
                                base_valid_q <= 1'b0;
                                state_q <= IDLE;
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
