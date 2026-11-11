// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Replays only the exact captured 26-QWORD MAX+INDEX command profile.
module tb_ppu_pool_index_raw_profile;
    localparam int unsigned COMMAND_BYTES = 26 * 8;
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
    integer command_fd, mode = 0, expected_error = 0, accepted = 0;
    integer i, b;
    logic [63:0] word;
    logic word_last;
    string command_path;

    rk_ppu_pool_index_raw_profile dut (
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
            if (cmd_ready !== 1'b1) $fatal(1, "command was not ready");
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
        if (mode < 0 || mode > 10) $fatal(1, "invalid MODE");
        command_fd = $fopen(command_path, "rb");
        if (command_fd == 0) $fatal(1, "cannot open patched command");
        if ($fread(command_bytes, command_fd) != COMMAND_BYTES)
            $fatal(1, "command size is not 26 QWORDs");
        $fclose(command_fd);

        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        begin : SEND_STREAM
            for (i = 0; i < 26; i = i + 1) begin
                word = 64'b0;
                for (b = 0; b < 8; b = b + 1)
                    word[b*8 +: 8] = command_bytes[i*8+b];
                word_last = (i == 25);
                case (mode)
                    1: if (i == 9) word[47:16] = word[47:16] ^ 32'h1;
                    2: if (i == 13) word[47:16] = word[47:16] | 32'h1;
                    3: if (i == 2) word[63:48] = 16'h4002;
                    4: if (i == 5) word_last = 1'b1;
                    5: if (i == 20) word[47:16] = 32'h00002000;
                    6: if (i == 20) word[47:16] = 32'hfffffff0;
                    7: if (i == 25) word_last = 1'b0;
                    8: if (i == 13) word[47:16] = 32'hfffffff0;
                    9: if (i == 20) word[47:16] = 32'hxxxxxxxx;
                    10: if (i == 14) word[47:16] = 32'h00000011;
                    default: begin end
                endcase
                send_word(word, word_last);
                if (expected_error != 0 && error) disable SEND_STREAM;
            end
        end

        if (expected_error != 0) begin
            if (error !== 1'b1 || error_code !== expected_error[3:0])
                $fatal(1, "mode %0d error=%b code=%0d expected=%0d",
                       mode, error, error_code, expected_error);
            if (profile_valid !== 1'b0 || busy !== 1'b0)
                $fatal(1, "rejected command published profile or stayed busy");
            $display("PASS ppu_index_raw_profile mode=%0d rejected_code=%0d words=%0d profile=0",
                     mode, error_code, accepted);
        end else begin
            if (accepted != 26 || error !== 1'b0 || error_code !== 4'd0 ||
                profile_valid !== 1'b1 || busy !== 1'b1)
                $fatal(1, "captured stream rejected words=%0d error=%b code=%0d profile=%b",
                       accepted, error, error_code, profile_valid);
            if (rdma_src_base !== 32'h00001000 || ppu_dst_base !== 32'h00002000 ||
                rdma_transfer_bytes !== 32'd64 || output_write_bytes !== 32'd48)
                $fatal(1, "index profile geometry/base mismatch");
            repeat (3) begin
                @(posedge clk);
                if (profile_valid !== 1'b1 || !busy || cmd_ready)
                    $fatal(1, "profile backpressure contract failed");
            end
            @(negedge clk);
            profile_ready = 1'b1;
            @(posedge clk);
            #1;
            if (profile_valid !== 1'b0 || busy !== 1'b0 || cmd_ready !== 1'b0)
                $fatal(1, "profile did not retire");
            $display("PASS ppu_index_raw_profile mode=0 accepted_words=26 src=%08h dst=%08h input_bytes=64 output_span_bytes=48 profile_stall_cycles=3",
                     rdma_src_base, ppu_dst_base);
        end
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1, "MAX+INDEX raw profile timeout");
    end
endmodule
