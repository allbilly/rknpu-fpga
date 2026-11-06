// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact whole-BO replay of fp16_max_k2s2_c3_tail_h2w2.
module tb_ppu_pool_max2x2s2_c3_tail_h2w2;
    localparam int unsigned BO_BYTES = 4096;
    localparam int unsigned ATOM_BYTES = 16;
    localparam int unsigned INPUT_BEATS = 4;
    localparam int unsigned VALUE_BYTES = 16;
    localparam int unsigned PHYSICAL_LANES = 8;
    localparam int unsigned LOGICAL_CHANNELS = 3;

    logic clk;
    initial clk = 0;
    always #5 clk = ~clk;

    logic rst_n = 0;
    logic in_valid = 0;
    wire in_ready;
    logic [127:0] in_atom = 0;
    wire out_valid;
    logic out_ready;
    wire [127:0] out_atom;
    wire out_last;

    logic [7:0] in_bo [0:BO_BYTES-1];
    logic [7:0] out_init [0:BO_BYTES-1];
    logic [7:0] device_out [0:BO_BYTES-1];
    logic [7:0] observed [0:BO_BYTES-1];
    logic [127:0] captured_atom;
    logic captured_last;

    integer in_fd, init_fd, device_fd, observed_fd;
    integer input_beats;
    integer output_beats;
    integer output_stall_cycles;
    integer cycles;
    integer byte_mismatches;
    integer lane_mismatches;
    integer i, byte_idx, lane;
    integer stall_mode = 0;
    logic [31:0] seed = 32'h3588;
    logic [31:0] lfsr;
    logic force_first_stall;
    logic stalled;
    logic [127:0] held_atom;
    logic held_last;
    logic [15:0] observed_lane;
    logic [15:0] device_lane;
    string in_path, init_path, device_path, observed_path, case_name;

    rk_ppu_pool_max2x2s2_c3_tail_h2w2 dut (
        .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready),
        .in_atom(in_atom), .out_valid(out_valid), .out_ready(out_ready),
        .out_atom(out_atom), .out_last(out_last)
    );

    always @(negedge clk) begin
        lfsr <= {lfsr[30:0], lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
        if (stall_mode == 0) begin
            out_ready <= 1'b1;
        end else if (out_valid && !force_first_stall) begin
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
            if (cycles > 1000000) $fatal(1, "PPU C3 tail testbench timeout");
            if (out_valid && !out_ready)
                output_stall_cycles <= output_stall_cycles + 1;
            if (stalled && (!out_valid || out_atom !== held_atom || out_last !== held_last))
                $fatal(1, "Output changed under backpressure");
            stalled <= out_valid && !out_ready;
            held_atom <= out_atom;
            held_last <= out_last;
            if (out_valid && out_ready) begin
                if (output_beats != 0) $fatal(1, "More than one output atom");
                captured_atom <= out_atom;
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
        byte_mismatches = 0;
        lane_mismatches = 0;
        stalled = 0;
        held_atom = 0;
        held_last = 0;
        captured_atom = 0;
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
        if (captured_last !== 1'b1) $fatal(1, "Single output must assert out_last");
        if ((stall_mode == 0 && output_stall_cycles != 0) ||
            (stall_mode == 1 && output_stall_cycles == 0))
            $fatal(1, "Unexpected output stall coverage: %0d", output_stall_cycles);

        // A second 2x2 input surface is not accepted before reset.
        @(negedge clk);
        in_atom = {128{1'b1}};
        in_valid = 1;
        repeat (3) begin
            @(posedge clk);
            if (in_ready !== 1'b0) $fatal(1, "post-frame input was accepted");
        end
        @(negedge clk);
        in_valid = 0;

        for (byte_idx = 0; byte_idx < VALUE_BYTES; byte_idx = byte_idx + 1)
            observed[byte_idx] = captured_atom[byte_idx*8 +: 8];
        for (i = VALUE_BYTES; i < BO_BYTES; i = i + 1)
            if (observed[i] !== out_init[i]) $fatal(1, "output tail modified at byte %0d", i);

        for (i = 0; i < BO_BYTES; i = i + 1) begin
            if (observed[i] !== device_out[i]) begin
                if (byte_mismatches == 0)
                    $display("FAIL first byte mismatch offset=%0d observed=%02h device=%02h",
                             i, observed[i], device_out[i]);
                byte_mismatches = byte_mismatches + 1;
            end
        end
        for (lane = 0; lane < PHYSICAL_LANES; lane = lane + 1) begin
            observed_lane = {observed[lane*2+1], observed[lane*2]};
            device_lane = {device_out[lane*2+1], device_out[lane*2]};
            if (observed_lane !== device_lane) begin
                if (lane_mismatches == 0)
                    $display("FAIL first output lane=%0d observed=%04h device=%04h",
                             lane, observed_lane, device_lane);
                lane_mismatches = lane_mismatches + 1;
            end
        end
        // The source's three logical channels are followed by five -99 lanes.
        for (lane = LOGICAL_CHANNELS; lane < PHYSICAL_LANES; lane = lane + 1)
            if ({observed[lane*2+1], observed[lane*2]} !== 16'hd630)
                $fatal(1, "C3 physical tail lane %0d is not FP16 -99", lane);

        observed_fd = $fopen(observed_path, "wb");
        if (observed_fd == 0) $fatal(1, "Could not open observed BO output");
        for (i = 0; i < BO_BYTES; i = i + 1) $fwrite(observed_fd, "%c", observed[i]);
        $fclose(observed_fd);
        if (byte_mismatches != 0 || lane_mismatches != 0)
            $fatal(1, "PPU C3 tail BO mismatch bytes=%0d lanes=%0d",
                   byte_mismatches, lane_mismatches);

        $display("PASS ppu_max2x2s2_c3_tail_h2w2 case=%0s input_beats=%0d output_atoms=%0d logical_channels=%0d physical_lanes=%0d tail_lanes=%0d value_bytes=%0d buffer_bytes=%0d byte_mismatches=%0d lane_mismatches=%0d cycles=%0d stall=%0d stall_cycles=%0d seed=%08h",
                 case_name, input_beats, output_beats, LOGICAL_CHANNELS,
                 PHYSICAL_LANES, PHYSICAL_LANES-LOGICAL_CHANNELS, VALUE_BYTES,
                 BO_BYTES, byte_mismatches, lane_mismatches, cycles,
                 stall_mode, output_stall_cycles, seed);
        $finish;
    end

    initial begin
        #10000000;
        $fatal(1, "PPU C3 tail testbench deadline");
    end
endmodule
