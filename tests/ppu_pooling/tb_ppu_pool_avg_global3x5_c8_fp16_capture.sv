// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Whole-BO replay of the pinned global-average capture through its leaf.
module tb_ppu_pool_avg_global3x5_c8_fp16_capture;
    localparam int unsigned BO_BYTES = 4096;
    localparam int unsigned INPUT_ATOMS = 15;

    logic clk;
    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end
    logic rst_n = 1'b0;
    logic in_valid = 1'b0;
    wire in_ready;
    logic [127:0] in_atom = 128'd0;
    wire out_valid;
    logic out_ready = 1'b0;
    wire [127:0] out_atom;
    wire out_last;

    logic [7:0] in_bo [0:BO_BYTES-1];
    logic [7:0] output_init [0:BO_BYTES-1];
    logic [7:0] source_expected [0:BO_BYTES-1];
    logic [7:0] device_out [0:BO_BYTES-1];
    logic [7:0] observed [0:BO_BYTES-1];
    logic [127:0] captured_atom;
    logic captured_last;
    integer in_fd, init_fd, expected_fd, device_fd, observed_fd;
    integer atom_index, byte_index, input_beats, output_beats, cycles;
    integer tail_mismatches, value_byte_mismatches, whole_bo_mismatches;
    string in_path, init_path, expected_path, device_path, observed_path;

    rk_ppu_pool_avg_global3x5_c8_fp16_capture dut (
        .clk, .rst_n, .in_valid, .in_ready, .in_atom,
        .out_valid, .out_ready, .out_atom, .out_last
    );

    always @(posedge clk) begin
        if (rst_n) begin
            cycles <= cycles + 1;
            if (cycles > 10000) $fatal(1, "global-average leaf timeout");
            if (out_valid && out_ready) begin
                captured_atom <= out_atom;
                captured_last <= out_last;
                output_beats <= output_beats + 1;
            end
        end
    end

    initial begin
        if (!$value$plusargs("IN_BIN=%s", in_path) ||
            !$value$plusargs("OUT_INIT_BIN=%s", init_path) ||
            !$value$plusargs("EXPECTED_BIN=%s", expected_path) ||
            !$value$plusargs("DEVICE_OUT_BIN=%s", device_path) ||
            !$value$plusargs("OBSERVED_BIN=%s", observed_path))
            $fatal(1, "missing global-average fixture paths");
        in_fd = $fopen(in_path, "rb");
        init_fd = $fopen(init_path, "rb");
        expected_fd = $fopen(expected_path, "rb");
        device_fd = $fopen(device_path, "rb");
        if (in_fd == 0 || init_fd == 0 || expected_fd == 0 || device_fd == 0)
            $fatal(1, "cannot open global-average fixtures");
        if ($fread(in_bo, in_fd) != BO_BYTES ||
            $fread(output_init, init_fd) != BO_BYTES ||
            $fread(source_expected, expected_fd) != BO_BYTES ||
            $fread(device_out, device_fd) != BO_BYTES)
            $fatal(1, "global-average fixture is not a complete 4096-byte BO");
        $fclose(in_fd);
        $fclose(init_fd);
        $fclose(expected_fd);
        $fclose(device_fd);

        for (byte_index = 0; byte_index < BO_BYTES; byte_index = byte_index + 1) begin
            if (source_expected[byte_index] !== device_out[byte_index])
                $fatal(1, "source/device fixture mismatch at byte %0d", byte_index);
            observed[byte_index] = output_init[byte_index];
        end
        input_beats = 0;
        output_beats = 0;
        cycles = 0;
        tail_mismatches = 0;
        value_byte_mismatches = 0;
        whole_bo_mismatches = 0;
        captured_atom = 128'd0;
        captured_last = 1'b0;

        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        for (atom_index = 0; atom_index < INPUT_ATOMS; atom_index = atom_index + 1) begin
            @(negedge clk);
            for (byte_index = 0; byte_index < 16; byte_index = byte_index + 1)
                in_atom[byte_index*8 +: 8] = in_bo[atom_index*16 + byte_index];
            in_valid = 1'b1;
            do @(posedge clk); while (!in_ready);
            input_beats = input_beats + 1;
        end
        @(negedge clk);
        in_valid = 1'b0;
        wait (out_valid === 1'b1);
        repeat (3) begin
            @(negedge clk);
            if (out_valid !== 1'b1 || out_last !== 1'b1 ||
                (^out_atom) === 1'bx)
                $fatal(1, "global-average output did not remain valid under backpressure");
        end
        @(negedge clk);
        out_ready = 1'b1;
        @(posedge clk);
        @(negedge clk);
        out_ready = 1'b0;
        in_valid = 1'b1;
        #1;
        if (in_ready !== 1'b0)
            $fatal(1, "leaf accepted an extra atom after the one-frame capture");
        in_valid = 1'b0;
        repeat (2) @(negedge clk);

        if (input_beats != INPUT_ATOMS || output_beats != 1 || captured_last !== 1'b1)
            $fatal(1, "global-average framing mismatch input=%0d output=%0d last=%b",
                   input_beats, output_beats, captured_last);
        for (byte_index = 0; byte_index < 16; byte_index = byte_index + 1)
            observed[byte_index] = captured_atom[byte_index*8 +: 8];
        for (byte_index = 16; byte_index < BO_BYTES; byte_index = byte_index + 1)
            if (observed[byte_index] !== output_init[byte_index])
                tail_mismatches = tail_mismatches + 1;
        for (byte_index = 0; byte_index < BO_BYTES; byte_index = byte_index + 1) begin
            if (observed[byte_index] !== device_out[byte_index]) begin
                whole_bo_mismatches = whole_bo_mismatches + 1;
                if (byte_index < 16) value_byte_mismatches = value_byte_mismatches + 1;
            end
        end
        observed_fd = $fopen(observed_path, "wb");
        if (observed_fd == 0) $fatal(1, "cannot write observed BO");
        for (byte_index = 0; byte_index < BO_BYTES; byte_index = byte_index + 1)
            $fwrite(observed_fd, "%c", observed[byte_index]);
        $fclose(observed_fd);
        if (tail_mismatches != 0 || whole_bo_mismatches != 0)
            $fatal(1, "global-average full BO mismatch value_bytes=%0d tail_bytes=%0d total=%0d",
                   value_byte_mismatches, tail_mismatches, whole_bo_mismatches);
        $display("PASS ppu_avg_global3x5_c8_fp16_capture input_atoms=%0d output_atoms=%0d value_bytes=16 full_bo_bytes=4096 value_byte_mismatches=%0d tail_mismatches=%0d cycles=%0d seed=0x72667555",
                 input_beats, output_beats, value_byte_mismatches, tail_mismatches, cycles);
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1, "global-average leaf deadline");
    end
endmodule
