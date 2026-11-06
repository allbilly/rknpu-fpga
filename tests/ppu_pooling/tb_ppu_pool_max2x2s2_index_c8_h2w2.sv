// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact whole-BO replay of the one captured FP16 MAX+INDEX case.
module tb_ppu_pool_max2x2s2_index_c8_h2w2;
    localparam int unsigned BO_BYTES = 4096;
    localparam int unsigned ATOM_BYTES = 16;
    localparam int unsigned INPUT_BEATS = 4;
    localparam int unsigned VALUE_OFFSET = 0;
    localparam int unsigned VALUE_BYTES = 16;
    localparam int unsigned GAP_OFFSET = 16;
    localparam int unsigned INDEX_OFFSET = 32;
    localparam int unsigned INDEX_BYTES = 16;
    localparam int unsigned LOGICAL_BYTES = 48;

    logic clk;
    initial clk = 0;
    always #5 clk = ~clk;

    logic rst_n = 0;
    logic in_valid = 0;
    wire in_ready;
    logic [127:0] in_atom = 0;
    wire out_valid;
    logic out_ready;
    wire [127:0] out_value_atom;
    wire [127:0] out_index_atom;
    wire out_last;

    logic [7:0] in_bo [0:BO_BYTES-1];
    logic [7:0] out_init [0:BO_BYTES-1];
    logic [7:0] device_out [0:BO_BYTES-1];
    logic [7:0] observed [0:BO_BYTES-1];
    logic [127:0] captured_value;
    logic [127:0] captured_index;
    logic captured_last;

    integer in_fd, init_fd, device_fd, observed_fd;
    integer input_beats;
    integer output_beats;
    integer output_stall_cycles;
    integer cycles;
    integer mismatches;
    integer value_mismatches;
    integer index_mismatches;
    integer i, byte_idx, lane;
    integer stall_mode = 0;
    logic [31:0] seed = 32'h3588;
    logic [31:0] lfsr;
    logic force_first_stall;
    logic stalled;
    logic [127:0] held_value;
    logic [127:0] held_index;
    logic held_last;
    string in_path, init_path, device_path, observed_path, case_name;

    rk_ppu_pool_max2x2s2_index_c8_h2w2 dut (
        .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready),
        .in_atom(in_atom), .out_valid(out_valid), .out_ready(out_ready),
        .out_value_atom(out_value_atom), .out_index_atom(out_index_atom),
        .out_last(out_last)
    );

    always @(negedge clk) begin
        lfsr <= {lfsr[30:0], lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
        if (stall_mode == 0) begin
            out_ready <= 1'b1;
        end else if (out_valid && !force_first_stall) begin
            // Force a real, reproducible output stall for this one-result frame.
            out_ready <= 1'b0;
            force_first_stall <= 1'b1;
        end else if (force_first_stall) begin
            out_ready <= 1'b1;
        end else begin
            out_ready <= lfsr[0] || lfsr[5];
        end
    end

    always @(posedge clk) begin
        if (rst_n) begin
            cycles <= cycles + 1;
            if (cycles > 1000000) $fatal(1, "PPU MAX+INDEX testbench timeout");
            if (out_valid && !out_ready)
                output_stall_cycles <= output_stall_cycles + 1;
            if (stalled && (!out_valid || out_value_atom !== held_value ||
                            out_index_atom !== held_index || out_last !== held_last))
                $fatal(1, "Paired output changed under backpressure");
            stalled <= out_valid && !out_ready;
            held_value <= out_value_atom;
            held_index <= out_index_atom;
            held_last <= out_last;
            if (out_valid && out_ready) begin
                if (output_beats != 0) $fatal(1, "More than one output atom pair");
                captured_value <= out_value_atom;
                captured_index <= out_index_atom;
                captured_last <= out_last;
                output_beats <= output_beats + 1;
            end
        end
    end

    initial begin
        if (!$value$plusargs("IN_BIN=%s", in_path)) $fatal(1, "missing +IN_BIN");
        if (!$value$plusargs("OUT_INIT_BIN=%s", init_path)) $fatal(1, "missing +OUT_INIT_BIN");
        if (!$value$plusargs("DEVICE_OUT_BIN=%s", device_path)) $fatal(1, "missing +DEVICE_OUT_BIN");
        if (!$value$plusargs("OBSERVED_BIN=%s", observed_path)) $fatal(1, "missing +OBSERVED_BIN");
        if (!$value$plusargs("STALL=%d", stall_mode)) stall_mode = 0;
        if (!$value$plusargs("SEED=%d", seed)) seed = 32'h3588;
        if (!$value$plusargs("CASE=%s", case_name)) case_name = "unnamed";
        if (stall_mode < 0 || stall_mode > 1) $fatal(1, "STALL must be 0 or 1");
        lfsr = seed;
        force_first_stall = 0;
        out_ready = 0;
        input_beats = 0;
        output_beats = 0;
        output_stall_cycles = 0;
        cycles = 0;
        mismatches = 0;
        value_mismatches = 0;
        index_mismatches = 0;
        stalled = 0;
        held_value = 0;
        held_index = 0;
        held_last = 0;
        captured_value = 0;
        captured_index = 0;
        captured_last = 0;

        in_fd = $fopen(in_path, "rb");
        init_fd = $fopen(init_path, "rb");
        device_fd = $fopen(device_path, "rb");
        if (in_fd == 0 || init_fd == 0 || device_fd == 0)
            $fatal(1, "Could not open captured BO fixture");
        if ($fread(in_bo, in_fd) != BO_BYTES) $fatal(1, "Short input BO read");
        if ($fread(out_init, init_fd) != BO_BYTES) $fatal(1, "Short output-init BO read");
        if ($fread(device_out, device_fd) != BO_BYTES) $fatal(1, "Short device-output BO read");
        $fclose(in_fd);
        $fclose(init_fd);
        $fclose(device_fd);
        for (i = 0; i < BO_BYTES; i = i + 1) observed[i] = out_init[i];

        repeat (4) @(negedge clk);
        rst_n = 1;
        for (i = 0; i < INPUT_BEATS; i = i + 1) begin
            @(negedge clk);
            in_atom = 128'b0;
            for (byte_idx = 0; byte_idx < ATOM_BYTES; byte_idx = byte_idx + 1)
                in_atom[byte_idx*8 +: 8] = in_bo[i*ATOM_BYTES + byte_idx];
            in_valid = 1;
            do @(posedge clk); while (!in_ready);
            input_beats = input_beats + 1;
        end
        @(negedge clk);
        in_valid = 0;

        wait (output_beats == 1);
        if (input_beats != INPUT_BEATS) $fatal(1, "Wrong input atom count");
        if (captured_last !== 1'b1) $fatal(1, "Single result must assert out_last");
        if ((stall_mode == 0 && output_stall_cycles != 0) ||
            (stall_mode == 1 && output_stall_cycles == 0))
            $fatal(1, "Unexpected output stall coverage: %0d", output_stall_cycles);

        // The one-frame candidate must reject a new input until reset.
        @(negedge clk);
        in_atom = {128{1'b1}};
        in_valid = 1;
        repeat (3) begin
            @(posedge clk);
            if (in_ready !== 1'b0) $fatal(1, "post-frame input was accepted");
        end
        @(negedge clk);
        in_valid = 0;

        // Values occupy bytes 0..15. INDEX_EN's captured index surface starts
        // at byte 32; bytes 16..31 are an untouched gap.
        for (byte_idx = 0; byte_idx < VALUE_BYTES; byte_idx = byte_idx + 1)
            observed[VALUE_OFFSET + byte_idx] = captured_value[byte_idx*8 +: 8];
        for (byte_idx = 0; byte_idx < INDEX_BYTES; byte_idx = byte_idx + 1)
            observed[INDEX_OFFSET + byte_idx] = captured_index[byte_idx*8 +: 8];
        for (i = GAP_OFFSET; i < INDEX_OFFSET; i = i + 1)
            if (observed[i] !== out_init[i]) $fatal(1, "INDEX_EN value/index gap was modified");
        for (i = LOGICAL_BYTES; i < BO_BYTES; i = i + 1)
            if (observed[i] !== out_init[i]) $fatal(1, "output tail was modified at byte %0d", i);

        for (i = 0; i < BO_BYTES; i = i + 1) begin
            if (observed[i] !== device_out[i]) begin
                if (mismatches == 0)
                    $display("FAIL first byte mismatch offset=%0d observed=%02h device=%02h",
                             i, observed[i], device_out[i]);
                mismatches = mismatches + 1;
            end
        end
        for (lane = 0; lane < 8; lane = lane + 1) begin
            for (byte_idx = 0; byte_idx < 2; byte_idx = byte_idx + 1) begin
                if (observed[VALUE_OFFSET + lane*2 + byte_idx] !==
                    device_out[VALUE_OFFSET + lane*2 + byte_idx])
                    value_mismatches = value_mismatches + 1;
                if (observed[INDEX_OFFSET + lane*2 + byte_idx] !==
                    device_out[INDEX_OFFSET + lane*2 + byte_idx])
                    index_mismatches = index_mismatches + 1;
            end
        end

        observed_fd = $fopen(observed_path, "wb");
        if (observed_fd == 0) $fatal(1, "Could not open observed BO output");
        for (i = 0; i < BO_BYTES; i = i + 1) $fwrite(observed_fd, "%c", observed[i]);
        $fclose(observed_fd);
        if (mismatches != 0 || value_mismatches != 0 || index_mismatches != 0)
            $fatal(1, "PPU MAX+INDEX BO mismatch bytes=%0d values=%0d indices=%0d",
                   mismatches, value_mismatches, index_mismatches);

        $display("PASS ppu_max2x2s2_index_c8_h2w2 case=%0s input_beats=%0d output_pairs=%0d value_bytes=%0d index_offset=%0d index_bytes=%0d logical_bytes=%0d buffer_bytes=%0d mismatches=%0d value_mismatches=%0d index_mismatches=%0d cycles=%0d stall=%0d stall_cycles=%0d seed=%08h",
                 case_name, input_beats, output_beats, VALUE_BYTES, INDEX_OFFSET,
                 INDEX_BYTES, LOGICAL_BYTES, BO_BYTES, mismatches, value_mismatches,
                 index_mismatches, cycles, stall_mode, output_stall_cycles, seed);
        $finish;
    end

    initial begin
        #10000000;
        $fatal(1, "PPU MAX+INDEX testbench deadline");
    end
endmodule
