// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Feeds the captured (address-patched by the pinned job patch table) raw
// QWORD stream to the strict C3 PPU register/DMA profile gate.
module tb_ppu_pool_c3_raw_profile;
    localparam int unsigned COMMAND_BYTES = 26 * 8;
    logic clk;
    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    logic rst_n = 0;
    logic cmd_valid = 0;
    wire cmd_ready;
    logic [63:0] cmd_data = 0;
    logic cmd_last = 0;
    wire profile_valid;
    logic profile_ready = 0;
    wire [31:0] rdma_src_base, ppu_dst_base;
    wire [12:0] rdma_input_width_m1, rdma_input_height_m1, rdma_input_channels_m1;
    wire [31:0] rdma_line_stride_bytes, rdma_surface_stride_bytes;
    wire [1:0] rdma_format;
    wire [12:0] ppu_input_width_m1, ppu_input_height_m1, ppu_input_channels_m1;
    wire [12:0] ppu_output_width_m1, ppu_output_height_m1, ppu_output_channels_m1;
    wire [3:0] kernel_width_m1, kernel_height_m1, stride_width_m1, stride_height_m1;
    wire [14:0] padding_cfg;
    wire index_en;
    wire [1:0] pool_method;
    wire ppu_flying;
    wire [2:0] use_cnt;
    wire [31:0] output_data_format;
    wire [31:0] output_surface_stride_bytes;
    wire [3:0] output_burst_len;
    wire [31:0] rdma_transfer_bytes, output_write_bytes;
    wire busy, error;
    wire [3:0] error_code;

    logic [7:0] command_bytes [0:COMMAND_BYTES-1];
    integer command_fd;
    integer mode = 0;
    integer expected_error = 0;
    integer accepted = 0;
    integer i, b;
    logic [63:0] word;
    logic word_last;
    logic [31:0] expected_src;
    logic [31:0] expected_dst;
    string command_path;

    rk_ppu_pool_c3_raw_profile dut (
        .clk, .rst_n, .cmd_valid, .cmd_ready, .cmd_data, .cmd_last,
        .profile_valid, .profile_ready, .rdma_src_base, .ppu_dst_base,
        .rdma_input_width_m1, .rdma_input_height_m1, .rdma_input_channels_m1,
        .rdma_line_stride_bytes, .rdma_surface_stride_bytes, .rdma_format,
        .ppu_input_width_m1, .ppu_input_height_m1, .ppu_input_channels_m1,
        .ppu_output_width_m1, .ppu_output_height_m1, .ppu_output_channels_m1,
        .kernel_width_m1, .kernel_height_m1, .stride_width_m1,
        .stride_height_m1, .padding_cfg, .pool_method, .ppu_flying, .index_en,
        .use_cnt, .output_data_format, .output_surface_stride_bytes,
        .output_burst_len, .rdma_transfer_bytes, .output_write_bytes, .busy,
        .error, .error_code
    );

    task automatic send_word(input logic [63:0] data, input logic last_word);
        begin
            @(negedge clk);
            cmd_data = data;
            cmd_last = last_word;
            cmd_valid = 1'b1;
            @(posedge clk);
            if (cmd_ready !== 1'b1) $fatal(1, "command was not ready at transfer");
            accepted = accepted + 1;
            #1;
            @(negedge clk);
            cmd_valid = 1'b0;
            cmd_last = 1'b0;
        end
    endtask

    initial begin
        if (!$value$plusargs("COMMAND_BIN=%s", command_path)) $fatal(1, "missing +COMMAND_BIN");
        if (!$value$plusargs("MODE=%d", mode)) mode = 0;
        if (!$value$plusargs("EXPECT_ERROR=%d", expected_error)) expected_error = 0;
        if (mode < 0 || mode > 10) $fatal(1, "invalid MODE");
        command_fd = $fopen(command_path, "rb");
        if (command_fd == 0) $fatal(1, "cannot open patched command stream");
        if ($fread(command_bytes, command_fd) != COMMAND_BYTES)
            $fatal(1, "raw command stream size is not 26 QWORDs");
        $fclose(command_fd);

        expected_src = 32'h00001000;
        expected_dst = 32'h00002000;
        repeat (4) @(negedge clk);
        rst_n = 1'b1;

        begin : SEND_CAPTURED_STREAM
            for (i = 0; i < 26; i = i + 1) begin
                word = 64'b0;
                for (b = 0; b < 8; b = b + 1)
                    word[b*8 +: 8] = command_bytes[i*8+b];
                word_last = (i == 25);
                case (mode)
                    1: if (i == 8) word[47:16] = word[47:16] ^ 32'h00000001;
                    2: if (i == 13) word[47:16] = word[47:16] | 32'h00000001;
                    3: if (i == 2) word[63:48] = 16'h4002;
                    4: if (i == 3) word_last = 1'b1;
                    5: if (i == 20) word[47:16] = expected_dst;
                    6: if (i == 20) word[47:16] = 32'hfffffff0;
                    7: if (i == 25) word_last = 1'b0;
                    8: if (i == 16) word[47:16] = 32'h00000203;
                    9: if (i == 22) word[47:16] = 32'h00000050;
                    10: if (i == 20) word[47:16] = 32'hxxxxxxxx;
                    default: begin end
                endcase
                send_word(word, word_last);
                if (expected_error != 0 && error) disable SEND_CAPTURED_STREAM;
            end
        end

        if (expected_error != 0) begin
            if (error !== 1'b1 || error_code !== expected_error[3:0])
                $fatal(1, "negative mode %0d error=%b code=%0d expected=%0d",
                       mode, error, error_code, expected_error);
            if (profile_valid !== 1'b0)
                $fatal(1, "invalid raw command stream published a profile");
            if (busy !== 1'b0) $fatal(1, "faulted profile parser remained busy");
            $display("PASS ppu_c3_raw_profile mode=%0d rejected_code=%0d words=%0d profile=0",
                     mode, error_code, accepted);
        end else begin
            if (accepted != 26 || error !== 1'b0 || error_code !== 4'd0 ||
                profile_valid !== 1'b1)
                $fatal(1, "captured raw stream not accepted words=%0d error=%b code=%0d profile=%b",
                       accepted, error, error_code, profile_valid);
            if (rdma_src_base !== expected_src || ppu_dst_base !== expected_dst)
                $fatal(1, "relocated DMA bases mismatch src=%08h dst=%08h",
                       rdma_src_base, ppu_dst_base);
            if (rdma_input_width_m1 !== 1 || rdma_input_height_m1 !== 1 ||
                rdma_input_channels_m1 !== 2 || rdma_line_stride_bytes !== 32 ||
                rdma_surface_stride_bytes !== 64 || rdma_format !== 2)
                $fatal(1, "RDMA shape/stride/format contract mismatch");
            if (ppu_input_width_m1 !== 1 || ppu_input_height_m1 !== 1 ||
                ppu_input_channels_m1 !== 2 || ppu_output_width_m1 !== 0 ||
                ppu_output_height_m1 !== 0 || ppu_output_channels_m1 !== 2)
                $fatal(1, "PPU cube dimensions/channels mismatch");
            if (kernel_width_m1 !== 1 || kernel_height_m1 !== 1 ||
                stride_width_m1 !== 1 || stride_height_m1 !== 1 ||
                padding_cfg !== 0 || pool_method !== 1 || ppu_flying !== 1 ||
                index_en !== 0 || use_cnt !== 0)
                $fatal(1, "PPU max/kernel/stride/padding/index contract mismatch");
            if (output_data_format !== 32'h00000012 ||
                output_surface_stride_bytes !== 16 || output_burst_len !== 3 ||
                rdma_transfer_bytes !== 64 || output_write_bytes !== 16)
                $fatal(1, "PPU output format/stride/burst contract mismatch");

            // Profile payload must stay stable until the downstream start accepts it.
            repeat (3) begin
                @(posedge clk);
                if (profile_valid !== 1'b1 || !busy || cmd_ready)
                    $fatal(1, "profile-valid backpressure contract failed");
                if (rdma_src_base !== expected_src || ppu_dst_base !== expected_dst)
                    $fatal(1, "profile changed under backpressure");
            end
            @(negedge clk);
            profile_ready = 1'b1;
            @(posedge clk);
            #1;
            if (profile_valid !== 1'b0 || busy !== 1'b0 || cmd_ready !== 1'b0)
                $fatal(1, "single task did not retire to done state");
            $display("PASS ppu_c3_raw_profile mode=0 accepted_words=26 src=%08h dst=%08h rdma_line=%0d rdma_surface=%0d output_bytes=16 profile_stall_cycles=3",
                     rdma_src_base, ppu_dst_base, rdma_line_stride_bytes,
                     rdma_surface_stride_bytes);
        end
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1, "raw profile testbench timeout");
    end
endmodule
