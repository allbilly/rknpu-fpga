// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Fast decoder-only unit bench for the runtime conv decoder prototype.
//
// Feeds the raw command QWORDs of one captured task (only the three documented
// value32 DMA-address relocations applied) and prints the decoded configuration
// in a machine-readable line. The Python driver
// `tests/conv/runtime/run_decode_unit.py` compares that line against the golden
// decoder model for every case; this keeps decoder debugging to a ~2 s compile
// instead of a full convolution replay.
module tb_runtime_decode_unit;
    localparam int unsigned MAX_WORDS = 54;

    logic clk = 1'b0;
    always #5 clk = ~clk;

    logic        rst_n = 1'b0;
    logic        cmd_valid = 1'b0;
    logic [63:0] cmd_data = 64'd0;
    logic        cmd_last = 1'b0;
    wire         cmd_ready;
    wire         config_valid, busy, error;
    wire [7:0]   error_code;
    wire [5:0]   cfg_input_h, cfg_input_w, cfg_output_h, cfg_output_w;
    wire [2:0]   cfg_kernel_h, cfg_kernel_w, cfg_stride, cfg_planes;
    wire         cfg_depthwise;
    wire [5:0]   cfg_input_channels, cfg_input_align, cfg_output_channels;
    wire [5:0]   cfg_align_c;
    wire [3:0]   cfg_pack_c2, cfg_kernels, cfg_output_atom_lanes;
    wire [2:0]   cfg_c1_blocks;
    wire [1:0]   cfg_weight_mode;
    wire [4:0]   cfg_chunk_lanes;
    wire         cfg_output_fp16;
    wire [31:0]  cfg_input_base, cfg_weight_base, cfg_output_base;
    wire [31:0]  cfg_input_bytes, cfg_weight_bytes, cfg_output_bytes;
    wire [7:0]   cfg_taps;
    wire [9:0]   cfg_frame_weight_halfwords;
    wire [12:0] cfg_weight_halfwords;
    wire [9:0]  cfg_weight_lanes;
    wire [8:0]  cfg_block_stride;
    wire [9:0]  cfg_total_atoms;
    wire [11:0] cfg_plane_words;
    wire [4:0]  cfg_pixel_bytes;
    wire [12:0] cfg_plane_bytes, cfg_block_bytes;
    wire [14:0] cfg_chunk_stride_bytes, cfg_block_plane_bytes;
    wire [31:0] cfg_real_mask;

    logic [63:0] commands [0:MAX_WORDS-1];
    integer num_cmd;
    integer i;
    integer j;
    integer got_config;
    string fixture;

    rk_conv_runtime_decode dut (
        .clk, .rst_n,
        .cmd_valid, .cmd_ready, .cmd_data, .cmd_last,
        .config_valid, .config_ready(1'b1),
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
        .cfg_real_mask, .busy, .error, .error_code);

    initial begin
        if (!$value$plusargs("FIXTURE=%s", fixture))
            $fatal(1, "missing +FIXTURE=<fixture hex dir>");
        if (!$value$plusargs("NUM_CMD=%d", num_cmd))
            $fatal(1, "missing +NUM_CMD");
        for (i = 0; i < MAX_WORDS; i = i + 1) commands[i] = 64'd0;
        $readmemh({fixture, "/commands.hex"}, commands);

        @(negedge clk);
        rst_n = 1'b0;
        repeat (4) begin @(posedge clk); #1; end
        @(negedge clk);
        rst_n = 1'b1;
        repeat (2) begin @(posedge clk); #1; end
        if (!cmd_ready) $fatal(1, "decoder not ready after reset");

        for (i = 0; i < num_cmd; i = i + 1) begin
            @(negedge clk);
            cmd_data = commands[i];
            cmd_last = (i == (num_cmd == 52 ? 50 : 53));
            cmd_valid = 1'b1;
            while (!cmd_ready && !error) @(posedge clk);
            @(posedge clk);
            @(negedge clk);
            cmd_valid = 1'b0;
            if (error) begin
                $display("DECODE_ERROR code=%0d word_index=%0d",
                         error_code, dut.word_index_q);
                $finish;
            end
        end

        got_config = 0;
        for (j = 0; j < 40 && !got_config && !error; j = j + 1) begin
            @(posedge clk); #1;
            if (config_valid) got_config = 1;
        end
        if (!got_config && error) begin
            $display("DECODE_ERROR code=%0d word_index=%0d",
                     error_code, dut.word_index_q);
        end else if (!got_config) begin
            $display("DECODE_ERROR code=255 word_index=%0d", dut.word_index_q);
        end else begin
            $display({"DECODE_OK ih=%0d iw=%0d oh=%0d ow=%0d kh=%0d kw=%0d ",
                      "stride=%0d dw=%0d ic=%0d ical=%0d pack=%0d planes=%0d ",
                      "oc=%0d kernels=%0d blocks=%0d wmode=%0d align=%0d ",
                      "fp16=%0d in_base=%0d w_base=%0d out_base=%0d ",
                      "in_bytes=%0d w_bytes=%0d out_bytes=%0d taps=%0d ",
                      "frame_w=%0d w_hw=%0d w_lanes=%0d block_stride=%0d ",
                      "total_atoms=%0d plane_words=%0d pixel_bytes=%0d ",
                      "plane_bytes=%0d block_bytes=%0d chunk_bytes=%0d ",
                      "block_plane_bytes=%0d real_mask=%0d"},
                     cfg_input_h, cfg_input_w, cfg_output_h, cfg_output_w,
                     cfg_kernel_h, cfg_kernel_w, cfg_stride, cfg_depthwise,
                     cfg_input_channels, cfg_input_align, cfg_pack_c2,
                     cfg_planes, cfg_output_channels, cfg_kernels,
                     cfg_c1_blocks, cfg_weight_mode, cfg_align_c,
                     cfg_output_fp16, cfg_input_base, cfg_weight_base,
                     cfg_output_base, cfg_input_bytes, cfg_weight_bytes,
                     cfg_output_bytes, cfg_taps, cfg_frame_weight_halfwords,
                     cfg_weight_halfwords, cfg_weight_lanes,
                     cfg_block_stride, cfg_total_atoms, cfg_plane_words,
                     cfg_pixel_bytes, cfg_plane_bytes, cfg_block_bytes,
                     cfg_chunk_stride_bytes, cfg_block_plane_bytes,
                     cfg_real_mask);
        end
        $finish;
    end
endmodule
