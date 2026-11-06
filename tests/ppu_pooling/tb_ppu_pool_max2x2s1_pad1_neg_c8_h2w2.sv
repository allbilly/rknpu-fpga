// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Full output-BO replay of the captured RK3588 padded negative MAX case.
module tb_ppu_pool_max2x2s1_pad1_neg_c8_h2w2;
    localparam int unsigned BO_BYTES = 4096;
    localparam int unsigned ATOM_BYTES = 16;
    localparam int unsigned IN_H = 2;
    localparam int unsigned IN_W = 2;
    localparam int unsigned OUT_H = 3;
    localparam int unsigned OUT_W = 3;
    localparam int unsigned IN_LINE_STRIDE = IN_W * ATOM_BYTES;
    localparam int unsigned OUT_LINE_STRIDE = OUT_W * ATOM_BYTES;
    localparam int unsigned INPUT_BEATS = IN_H * IN_W;
    localparam int unsigned OUTPUT_ATOMS = OUT_H * OUT_W;
    localparam int unsigned VALUE_BYTES = OUTPUT_ATOMS * ATOM_BYTES;
    localparam int unsigned VALUE_LANES = VALUE_BYTES / 2;

    logic clk;
    initial clk = 1'b0;
    always #5 clk = ~clk;

    logic rst_n = 1'b0;
    logic in_valid = 1'b0;
    wire in_ready;
    logic [127:0] in_atom = 128'b0;
    wire out_valid;
    logic out_ready;
    wire [127:0] out_atom;
    wire out_last;

    logic [7:0] in_bo [0:BO_BYTES-1];
    logic [7:0] out_init [0:BO_BYTES-1];
    logic [7:0] device_out [0:BO_BYTES-1];
    logic [7:0] observed [0:BO_BYTES-1];
    logic [127:0] captured [0:OUTPUT_ATOMS-1];
    logic captured_last [0:OUTPUT_ATOMS-1];

    integer in_fd, init_fd, device_fd, observed_fd;
    integer input_beats, output_beats, cycles, stall_cycles;
    integer mismatches, lane_mismatches;
    integer i, row_idx, col_idx, byte_idx, beat, lane;
    integer stall_mode = 0;
    logic [31:0] seed = 32'h3588;
    logic [31:0] lfsr;
    logic stalled;
    logic [127:0] held_atom;
    logic held_last;
    logic [15:0] observed_lane, device_lane;
    logic accepted;
    string in_path, init_path, device_path, observed_path, case_name;

    rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2 dut (
        .clk(clk),
        .rst_n(rst_n),
        .in_valid(in_valid),
        .in_ready(in_ready),
        .in_atom(in_atom),
        .out_valid(out_valid),
        .out_ready(out_ready),
        .out_atom(out_atom),
        .out_last(out_last)
    );

    // Mode 0 is always-ready. Mode 1 applies deterministic output stalls.
    always @(negedge clk) begin
        lfsr <= {lfsr[30:0], lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
        if (stall_mode == 0)
            out_ready <= 1'b1;
        else
            out_ready <= lfsr[0] || lfsr[5];
    end

    always @(posedge clk) begin
        if (rst_n) begin
            cycles <= cycles + 1;
            if (cycles > 1000000) $fatal(1, "PPU padded MAX testbench timeout");
            if (stalled && (!out_valid || out_atom !== held_atom || out_last !== held_last))
                $fatal(1, "Output changed under backpressure at beat %0d", output_beats);
            stalled <= out_valid && !out_ready;
            held_atom <= out_atom;
            held_last <= out_last;
            if (out_valid && !out_ready)
                stall_cycles <= stall_cycles + 1;
            if (out_valid && out_ready) begin
                if (output_beats >= OUTPUT_ATOMS)
                    $fatal(1, "More than nine output atoms");
                captured[output_beats] <= out_atom;
                captured_last[output_beats] <= out_last;
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
        input_beats = 0;
        output_beats = 0;
        cycles = 0;
        stall_cycles = 0;
        mismatches = 0;
        lane_mismatches = 0;
        stalled = 1'b0;
        held_atom = 128'b0;
        held_last = 1'b0;

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

        for (i = 0; i < BO_BYTES; i = i + 1)
            observed[i] = out_init[i];

        repeat (4) @(negedge clk);
        rst_n = 1'b1;

        // The captured input has 2x2 atoms, row-major, at 32-byte line stride.
        for (row_idx = 0; row_idx < IN_H; row_idx = row_idx + 1) begin
            for (col_idx = 0; col_idx < IN_W; col_idx = col_idx + 1) begin
                @(negedge clk);
                in_atom = 128'b0;
                for (byte_idx = 0; byte_idx < ATOM_BYTES; byte_idx = byte_idx + 1)
                    in_atom[byte_idx*8 +: 8] =
                        in_bo[row_idx*IN_LINE_STRIDE + col_idx*ATOM_BYTES + byte_idx];
                in_valid = 1'b1;
                do begin
                    @(posedge clk);
                    accepted = in_ready;
                end while (!accepted);
                input_beats = input_beats + 1;
            end
        end
        @(negedge clk);
        in_valid = 1'b0;

        wait (output_beats == OUTPUT_ATOMS);
        repeat (3) @(negedge clk);
        if (output_beats != OUTPUT_ATOMS)
            $fatal(1, "Wrong output atom count: got %0d expected %0d", output_beats, OUTPUT_ATOMS);
        if (input_beats != INPUT_BEATS)
            $fatal(1, "Wrong input atom count: got %0d expected %0d", input_beats, INPUT_BEATS);
        if ((stall_mode == 0) && (stall_cycles != 0))
            $fatal(1, "Always-ready run unexpectedly stalled");
        if ((stall_mode == 1) && (stall_cycles == 0))
            $fatal(1, "Backpressure run did not exercise a stall");

        for (beat = 0; beat < OUTPUT_ATOMS; beat = beat + 1) begin
            if (captured_last[beat] !== (beat == OUTPUT_ATOMS-1))
                $fatal(1, "out_last wrong at output atom %0d", beat);
        end

        for (row_idx = 0; row_idx < OUT_H; row_idx = row_idx + 1) begin
            for (col_idx = 0; col_idx < OUT_W; col_idx = col_idx + 1) begin
                beat = row_idx*OUT_W + col_idx;
                for (byte_idx = 0; byte_idx < ATOM_BYTES; byte_idx = byte_idx + 1)
                    observed[row_idx*OUT_LINE_STRIDE + col_idx*ATOM_BYTES + byte_idx] =
                        captured[beat][byte_idx*8 +: 8];
            end
        end

        for (i = 0; i < BO_BYTES; i = i + 1) begin
            if (observed[i] !== device_out[i]) begin
                if (mismatches == 0)
                    $display("FAIL first byte mismatch offset=%0d observed=%02h device=%02h",
                             i, observed[i], device_out[i]);
                mismatches = mismatches + 1;
            end
        end
        for (lane = 0; lane < VALUE_LANES; lane = lane + 1) begin
            observed_lane = {observed[lane*2+1], observed[lane*2]};
            device_lane = {device_out[lane*2+1], device_out[lane*2]};
            if (observed_lane !== device_lane) begin
                if (lane_mismatches == 0)
                    $display("FAIL first lane mismatch lane=%0d observed=%04h device=%04h",
                             lane, observed_lane, device_lane);
                lane_mismatches = lane_mismatches + 1;
            end
        end

        // The capture's value surface is 144 bytes; all remaining initialized
        // BO bytes must be untouched by this standalone value-only leaf.
        for (i = VALUE_BYTES; i < BO_BYTES; i = i + 1) begin
            if (observed[i] !== out_init[i])
                $fatal(1, "Output tail changed at byte %0d", i);
        end

        observed_fd = $fopen(observed_path, "wb");
        if (observed_fd == 0) $fatal(1, "Could not open observed BO output");
        for (i = 0; i < BO_BYTES; i = i + 1)
            $fwrite(observed_fd, "%c", observed[i]);
        $fclose(observed_fd);

        if (mismatches != 0 || lane_mismatches != 0)
            $fatal(1, "PPU padded MAX whole-BO mismatch: bytes=%0d lanes=%0d",
                   mismatches, lane_mismatches);

        $display("PASS ppu_max2x2s1_pad1_neg_c8_h2w2 case=%0s input_beats=%0d output_atoms=%0d value_bytes=%0d lanes=%0d buffer_bytes=%0d mismatches=%0d lane_mismatches=%0d cycles=%0d stall=%0d stall_cycles=%0d seed=%08h",
                 case_name, input_beats, output_beats, VALUE_BYTES, VALUE_LANES,
                 BO_BYTES, mismatches, lane_mismatches, cycles, stall_mode,
                 stall_cycles, seed);
        $finish;
    end

    initial begin
        #10000000;
        $fatal(1, "PPU padded MAX testbench deadline");
    end
endmodule
