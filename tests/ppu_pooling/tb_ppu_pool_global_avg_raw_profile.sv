// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Strict replay and mutation controls for the 28-QWORD global-average capture.
module tb_ppu_pool_global_avg_raw_profile;
    localparam int unsigned COMMAND_BYTES = 28 * 8;
    logic clk;
    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end
    logic rst_n = 1'b0;
    logic cmd_valid = 1'b0;
    wire cmd_ready;
    logic [63:0] cmd_data = 64'd0;
    logic cmd_last = 1'b0;
    wire profile_valid;
    logic profile_ready = 1'b0;
    wire [31:0] rdma_src_base, ppu_dst_base;
    wire [31:0] rdma_transfer_bytes, output_write_bytes;
    wire busy, error;
    wire [3:0] error_code;

    logic [7:0] command_bytes [0:COMMAND_BYTES-1];
    integer command_fd, mode, expected_error, accepted, i, b;
    logic [63:0] word;
    logic word_last;
    string command_path;

    rk_ppu_pool_global_avg_raw_profile dut (
        .clk, .rst_n, .cmd_valid, .cmd_ready, .cmd_data, .cmd_last,
        .profile_valid, .profile_ready, .rdma_src_base, .ppu_dst_base,
        .rdma_transfer_bytes, .output_write_bytes, .busy, .error, .error_code
    );

    task automatic send_word(input logic [63:0] data, input logic last_word);
        begin
            @(negedge clk);
            cmd_data = data;
            cmd_last = last_word;
            cmd_valid = 1'b1;
            @(posedge clk);
            if (cmd_ready !== 1'b1) $fatal(1, "raw command was not ready");
            accepted = accepted + 1;
            #1;
            @(negedge clk);
            cmd_valid = 1'b0;
            cmd_last = 1'b0;
        end
    endtask

    initial begin
        if (!$value$plusargs("COMMAND_BIN=%s", command_path))
            $fatal(1, "missing +COMMAND_BIN");
        if (!$value$plusargs("MODE=%d", mode)) mode = 0;
        if (!$value$plusargs("EXPECT_ERROR=%d", expected_error)) expected_error = 0;
        if (mode < 0 || mode > 13) $fatal(1, "invalid MODE");
        command_fd = $fopen(command_path, "rb");
        if (command_fd == 0) $fatal(1, "cannot open patched command stream");
        if ($fread(command_bytes, command_fd) != COMMAND_BYTES)
            $fatal(1, "command stream is not 28 QWORDs");
        $fclose(command_fd);
        accepted = 0;
        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        begin : SEND_STREAM
            for (i = 0; i < 28; i = i + 1) begin
                word = 64'd0;
                for (b = 0; b < 8; b = b + 1)
                    word[b*8 +: 8] = command_bytes[i*8+b];
                word_last = (i == 27);
                case (mode)
                    1:  if (i == 9)  word[47:16] = word[47:16] ^ 32'd1;
                    2:  if (i == 10) word[47:16] = word[47:16] ^ 32'd1;
                    3:  if (i == 2)  word[63:48] = 16'h4002;
                    4:  if (i == 6)  word_last = 1'b1;
                    5:  if (i == 15) word[47:16] = 32'h00001000;
                    6:  if (i == 22) word[47:16] = 32'hfffffff0;
                    7:  if (i == 27) word_last = 1'b0;
                    8:  if (i == 11) word[47:16] = word[47:16] ^ 32'd1;
                    9:  if (i == 2)  word[47:16] = 32'd3;
                    10: if (i == 15) word[47:16] = 32'h00002001;
                    11: if (i == 22) word[47:16] = 32'd0;
                    12: if (i == 27) word[47:16] = word[47:16] ^ 32'd1;
                    13: if (i == 24) word[47:16] = word[47:16] ^ 32'd1;
                    default: begin end
                endcase
                send_word(word, word_last);
                if (expected_error != 0 && error) disable SEND_STREAM;
            end
        end
        if (expected_error != 0) begin
            if (error !== 1'b1 || error_code !== expected_error[3:0] ||
                profile_valid !== 1'b0 || busy !== 1'b0)
                $fatal(1, "mode %0d expected error %0d, got error=%b code=%0d",
                       mode, expected_error, error, error_code);
            $display("PASS ppu_global_avg_raw_profile mode=%0d rejected_code=%0d words=%0d",
                     mode, error_code, accepted);
        end else begin
            if (accepted != 28 || error !== 1'b0 || profile_valid !== 1'b1 || busy !== 1'b1)
                $fatal(1, "captured global-average profile rejected");
            if (rdma_src_base !== 32'h00001000 || ppu_dst_base !== 32'h00002000 ||
                rdma_transfer_bytes !== 32'd240 || output_write_bytes !== 32'd16)
                $fatal(1, "global-average profile geometry/base mismatch");
            repeat (3) begin
                @(posedge clk);
                if (!profile_valid || !busy || cmd_ready)
                    $fatal(1, "profile-valid backpressure failed");
            end
            @(negedge clk);
            profile_ready = 1'b1;
            @(posedge clk);
            #1;
            if (profile_valid || busy || cmd_ready)
                $fatal(1, "profile did not retire after acceptance");
            $display("PASS ppu_global_avg_raw_profile mode=0 accepted_words=28 src=%08h dst=%08h input_bytes=240 output_bytes=16 profile_stall_cycles=3",
                     rdma_src_base, ppu_dst_base);
        end
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1, "global-average raw profile timeout");
    end
endmodule
