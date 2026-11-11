// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One frozen `conv-simple` capture through the raw 52-QWORD endpoint, the
// parameterised spatial front, the donor CMAC/CACC arithmetic and the FP16
// output atom writer.
//
// Every geometry element is an elaboration parameter derived from the capture's
// packing function, never from a runtime command field. The profile id selects
// the exact register template.
module rk_conv_simple_core #(
    parameter int unsigned PROFILE = 0,
    // Spatial geometry: input H/W, kernel H/W, stride.
    parameter int unsigned INPUT_H = 8,
    parameter int unsigned INPUT_W = 8,
    parameter int unsigned KH = 3,
    parameter int unsigned KW = 3,
    parameter int unsigned STRIDE = 1,
    // Real channel counts and packing.
    parameter int unsigned INPUT_CHANNELS = 4,
    parameter int unsigned KERNELS = 8,
    parameter int unsigned C1_BLOCKS = 2,
    parameter int unsigned ALIGN_C = 8,
    parameter int unsigned PACK_C2 = 4,
    // conv-simple weight BOs pack 16 output lanes per tap (`[oc_chunk]...`).
    parameter int unsigned CHUNK_LANES = 16,
    // Output format of the captured profile. FP16 profiles use the 8-lane
    // atom writer; the FP32 profile needs the NCHW transposing stage because
    // its captured BO is the logical [C][H][W] tensor.
    parameter bit OUTPUT_FP16 = 1'b1,
    parameter int unsigned TIMEOUT_CYCLES = 65536
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
    // Observation ports for an enclosing descriptor wrapper: the operand
    // placement the strict profile published, and the BO byte sizes it
    // enforces. They are read-only from outside; nothing here can widen the
    // accepted geometry.
    output logic [31:0]  config_input_base,
    output logic [31:0]  config_weight_base,
    output logic [31:0]  config_output_base,
    output logic [31:0]  input_bytes,
    output logic [31:0]  weight_bytes,
    output logic [31:0]  output_bytes
);
    localparam int unsigned OUTPUT_H = INPUT_H - KH + 1;
    localparam int unsigned OUTPUT_W = INPUT_W - KW + 1;
    localparam int unsigned OUTPUT_PIXELS = OUTPUT_H * OUTPUT_W;

    logic config_valid, config_ready, profile_busy, profile_error;
    logic [31:0] input_base, weight_base, output_base;
    logic [31:0] profile_input_bytes, profile_weight_bytes, profile_output_bytes;
    assign config_input_base = input_base;
    assign config_weight_base = weight_base;
    assign config_output_base = output_base;
    assign input_bytes = profile_input_bytes;
    assign weight_bytes = profile_weight_bytes;
    assign output_bytes = profile_output_bytes;
    logic front_busy, front_error, frame_valid, frame_ready;
    logic [7:0] profile_code, front_code, arithmetic_code, atom_code, arbiter_code;
    logic [511:0] frame_data;
    logic [8191:0] frame_weight;
    logic [31:0] frame_data_mask;
    logic [511:0] frame_weight_mask;
    logic [31:0] frame_output_address;
    logic frame_first, frame_last, frame_last_output;
    logic staged_valid, staged_ready;
    logic [511:0] staged_data, staged_weight_mask;
    logic [8191:0] staged_weight;
    logic [31:0] staged_data_mask, staged_address;
    logic staged_first, staged_last, staged_last_output;
    logic arithmetic_ready, arithmetic_valid, arithmetic_busy, arithmetic_error;
    logic atom_ready, atom_busy, atom_error, atom_ack, atom_frame_done, atom_done;
    logic [511:0] arithmetic_values;
    logic [32:0] arithmetic_tag;
    logic arbiter_busy, arbiter_error;
    logic read_req, read_req_ready, read_rsp, read_rsp_ready, read_rsp_error;
    logic write_req, write_req_ready, write_rsp, write_rsp_ready, write_rsp_error;
    logic write_req_write;
    logic [31:0] read_address, write_address;
    logic [15:0] read_data, write_data;
    logic fault;
    logic [7:0] saved_code;
    logic write_violation;
    logic child_cancel;
    logic profile_ready;
    // The arbiter is the only memory master; every module-level memory port is
    // driven from these internal nets exactly once.
    logic arbiter_req_valid, arbiter_rsp_ready;
    logic arbiter_req_write;
    logic [31:0] arbiter_req_addr;
    logic [15:0] arbiter_req_wdata;

    assign child_cancel = fault || profile_error;
    assign write_violation = write_req && !write_req_write;
    assign error = rst_n && (fault || profile_error || front_error ||
                             arithmetic_error || atom_error || arbiter_error ||
                             write_violation);
    assign error_code = !rst_n ? 8'd0 : fault ? saved_code :
                        profile_error ? profile_code : front_error ? front_code :
                        arithmetic_error ? arithmetic_code : atom_error ? atom_code :
                        arbiter_error ? arbiter_code : write_violation ? 8'd6 : 8'd0;
    assign cmd_ready = profile_ready && !error;
    assign busy = rst_n && !error &&
                  (profile_busy || front_busy || arithmetic_busy ||
                   atom_busy || arbiter_busy);
    assign acknowledged = atom_ack && !error;
    assign frame_done = atom_frame_done && !error;
    assign done = atom_done && !error;
    assign frame_ready = staged_ready && !error;
    assign mem_req_valid = arbiter_req_valid && !error;
    assign mem_req_write = arbiter_req_write;
    assign mem_req_addr = arbiter_req_addr;
    assign mem_req_wdata = arbiter_req_wdata;
    assign mem_rsp_ready = arbiter_rsp_ready && !error;

    rk_conv_simple_profile #(.PROFILE(PROFILE)) profile (
        .clk, .rst_n,
        .cmd_valid(cmd_valid && !error), .cmd_ready(profile_ready),
        .cmd_data, .cmd_last,
        .config_valid, .config_ready(config_ready && !error),
        .config_input_base(input_base), .config_weight_base(weight_base),
        .config_output_base(output_base),
        .input_bytes(profile_input_bytes), .weight_bytes(profile_weight_bytes),
        .output_bytes(profile_output_bytes),
        .busy(profile_busy), .error(profile_error), .error_code(profile_code));

    rk_conv_3x3_valid_c4_front #(
        .INPUT_H(INPUT_H), .INPUT_W(INPUT_W),
        .OUTPUT_H(OUTPUT_H), .OUTPUT_W(OUTPUT_W), .STRIDE(STRIDE),
        .KH(KH), .KW(KW),
        .INPUT_CHANNELS(INPUT_CHANNELS), .KERNELS(KERNELS),
        .C1_BLOCKS(C1_BLOCKS), .OUT_BLOCK_STRIDE(OUTPUT_PIXELS),
        .ALIGN_C(ALIGN_C), .PACK_C2(PACK_C2), .CHUNK_LANES(CHUNK_LANES),
        .DEPTHWISE(1'b0), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) front (
        .clk, .rst_n, .config_valid(config_valid && !error), .config_ready,
        .config_input_base(input_base), .config_weight_base(weight_base),
        .config_output_base(output_base), .cancel(child_cancel),
        .cancel_code(fault ? saved_code : profile_code), .busy(front_busy),
        .error(front_error), .error_code(front_code),
        .mem_req_valid(read_req), .mem_req_ready(read_req_ready && !error),
        .mem_req_addr(read_address),
        .mem_rsp_valid(read_rsp && !error), .mem_rsp_ready(read_rsp_ready),
        .mem_rsp_rdata(read_data), .mem_rsp_error(read_rsp_error),
        .frame_valid, .frame_ready, .frame_data, .frame_weight,
        .frame_data_mask, .frame_weight_mask, .frame_output_address,
        .frame_first, .frame_last, .frame_last_output);

    // One register stage between the frame source and the CMAC cells. The
    // operand bus is 8704 bits with a sixteen-lane fanout; without a stage on
    // the boundary the route alone overran the 20 ns period on the six-page
    // image. The stage preserves the frame fields and tag exactly.
    rk_frame_stage stage (
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

    rk_cmac_cacc_fp16_array #(.ATOMIC_C(32), .ATOMIC_K(16), .TAG_WIDTH(33))
    arithmetic (
        .clk, .rst_n, .in_valid(staged_valid && !error), .in_ready(arithmetic_ready),
        .in_data(staged_data), .in_weight(staged_weight),
        .in_data_mask(staged_data_mask), .in_weight_mask(staged_weight_mask),
        .in_first(staged_first), .in_last(staged_last),
        .in_tag({staged_address, staged_last_output}),
        .out_valid(arithmetic_valid), .out_ready(atom_ready && !error),
        .out_values(arithmetic_values), .out_tag(arithmetic_tag),
        .cancel(child_cancel), .cancel_code(fault ? saved_code : profile_code),
        .busy(arithmetic_busy), .error(arithmetic_error),
        .error_code(arithmetic_code));

    generate
        if (OUTPUT_FP16) begin : g_fp16_output
            // The captured atom is OC0..OC7 of the C32/K16 frame; lanes
            // OC8..OC15 are zero-padded and must not be written. Slice them
            // here so the width is an explicit contract, not an implicit
            // port truncation.
            rk_conv_output_atom #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES),
                                  .ATOMIC_K(8)) output_stage (
                .clk, .rst_n,
                .in_valid(arithmetic_valid && !error), .in_ready(atom_ready),
                .in_values(arithmetic_values[255:0]), .in_address(arithmetic_tag[32:1]),
                .in_last(arithmetic_tag[0]), .cancel(child_cancel),
                .cancel_code(fault ? saved_code : profile_code), .busy(atom_busy),
                .acknowledged(atom_ack), .frame_done(atom_frame_done),
                .done(atom_done), .error(atom_error), .error_code(atom_code),
                .mem_req_valid(write_req),
                .mem_req_ready(write_req_ready && !error),
                .mem_req_write(write_req_write), .mem_req_addr(write_address),
                .mem_req_wdata(write_data), .mem_rsp_valid(write_rsp && !error),
                .mem_rsp_ready(write_rsp_ready), .mem_rsp_error(write_rsp_error));
        end else begin : g_fp32_output
            // The FP32 capture's surface is [c1][pixel][c2=4], but the front
            // emits one frame per (block, pixel) carrying KERNELS consecutive
            // channels. `rk_conv_output_c1c2_fp32` maps each value into its
            // plane/slot without touching it. This mapping was verified
            // against the frozen capture before the module was written.
            rk_conv_output_c1c2_fp32 #(
                .LANES(KERNELS), .BLOCKS(C1_BLOCKS), .C2(PACK_C2),
                .HEIGHT(OUTPUT_H), .WIDTH(OUTPUT_W),
                .ATOM_STRIDE_BYTES(16),
                .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
            ) output_stage (
                .clk, .rst_n,
                .in_valid(arithmetic_valid && !error), .in_ready(atom_ready),
                .in_values(arithmetic_values[KERNELS*32-1:0]),
                .in_address(arithmetic_tag[32:1]),
                .in_last(arithmetic_tag[0]), .cancel(child_cancel),
                .cancel_code(fault ? saved_code : profile_code), .busy(atom_busy),
                .acknowledged(atom_ack), .frame_done(atom_frame_done),
                .done(atom_done), .error(atom_error), .error_code(atom_code),
                .mem_req_valid(write_req),
                .mem_req_ready(write_req_ready && !error),
                .mem_req_write(write_req_write), .mem_req_addr(write_address),
                .mem_req_wdata(write_data), .mem_rsp_valid(write_rsp && !error),
                .mem_rsp_ready(write_rsp_ready), .mem_rsp_error(write_rsp_error));
        end
    endgenerate

    rk_cmac_rw_arbiter arbiter (
        .clk, .rst_n, .cancel(child_cancel),
        .cancel_code(fault ? saved_code : profile_code),
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
        .mem_rsp_valid(mem_rsp_valid && !error), .mem_rsp_ready(arbiter_rsp_ready),
        .mem_rsp_data(mem_rsp_rdata), .mem_rsp_error,
        .busy(arbiter_busy), .error(arbiter_error), .error_code(arbiter_code));

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fault <= 1'b0;
            saved_code <= 8'd0;
        end else if (!fault && error) begin
            fault <= 1'b1;
            saved_code <= error_code;
        end
    end
endmodule
