// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Whole-BO replay for the three newly-added captured leaves:
//   CASE_ID 0: fp16_max_k3s2_pad1_c8_h4w4   (4 input atoms -> 2 output atoms)
//   CASE_ID 1: fp16_avg_k2s1_pad1_use_cnt0_c8_h1w1  (1 input atom -> 2 atoms)
//   CASE_ID 2: fp16_avg_k2s1_pad1_use_cnt7_c8_h1w1  (same leaf)
//
// The bench drives the captured input atoms and compares the complete
// 4096-byte output BO against the frozen device bytes.
module tb_ppu_pool_pad_tail #(
    parameter integer CASE_ID = 0
);
    localparam int unsigned BO_BYTES = 4096;
    // CASE 0 emits four 8-lane atoms (2x2 output pixels); the padded 1x1
    // averages emit four atoms as well.
    localparam int unsigned IN_ATOMS = (CASE_ID == 0) ? 16 : 1;
    localparam int unsigned OUT_ATOMS = 4;

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

    integer beat, byte_index, errors;
    string fixture;

    generate
        if (CASE_ID == 0) begin : g_max
            rk_ppu_pool_max3x3s2_pad1_c8_h4w4 dut (
                .clk, .rst_n, .in_valid, .in_ready, .in_atom,
                .out_valid, .out_ready, .out_atom, .out_last);
        end else begin : g_avg
            rk_ppu_pool_avg2x2s1_pad1_c8_h1w1 dut (
                .clk, .rst_n, .in_valid, .in_ready, .in_atom,
                .out_valid, .out_ready, .out_atom, .out_last);
        end
    endgenerate

    task automatic tick;
        begin @(posedge clk); #2; end
    endtask

    function automatic logic [127:0] atom_bytes(input integer index);
        integer offset;
        begin
            offset = index * 16;
            for (integer lane = 0; lane < 16; lane = lane + 1)
                atom_bytes[lane*8 +: 8] = in_bo[offset + lane];
        end
    endfunction

    initial begin
        if (!$value$plusargs("FIXTURE=%s", fixture))
            $fatal(1, "missing FIXTURE argument");
        $readmemh({fixture, "/in.hex"}, in_bo);
        $readmemh({fixture, "/out_init.hex"}, out_init);
        $readmemh({fixture, "/device.hex"}, device_out);
        for (byte_index = 0; byte_index < BO_BYTES; byte_index = byte_index + 1)
            observed[byte_index] = out_init[byte_index];

        @(negedge clk);
        rst_n = 1;
        repeat (2) tick();

        for (beat = 0; beat < IN_ATOMS; beat = beat + 1) begin
            @(negedge clk);
            if (!in_ready) $fatal(1, "leaf stalled before atom %0d", beat);
            in_atom = atom_bytes(beat);
            in_valid = 1;
            tick();
        end
        @(negedge clk);
        in_valid = 0;

        out_ready = 1;
        for (beat = 0; beat < OUT_ATOMS; beat = beat + 1) begin
            for (byte_index = 0; byte_index < 300 && !out_valid;
                 byte_index = byte_index + 1)
                tick();
            if (!out_valid) $fatal(1, "leaf did not emit output atom %0d", beat);
            for (byte_index = 0; byte_index < 16; byte_index = byte_index + 1)
                observed[beat * 16 + byte_index] = out_atom[byte_index*8 +: 8];
            tick();
        end
        out_ready = 0;

        errors = 0;
        for (byte_index = 0; byte_index < BO_BYTES; byte_index = byte_index + 1) begin
            if (observed[byte_index] !== device_out[byte_index]) begin
                errors = errors + 1;
                if (errors <= 6)
                    $display("MISMATCH byte %0d observed=%02x device=%02x",
                             byte_index, observed[byte_index], device_out[byte_index]);
            end
        end
        if (errors != 0)
            $fatal(1, "whole-BO mismatch: %0d of %0d bytes", errors, BO_BYTES);
        $display("PASS PPU_POOL_PAD_TAIL case=%0d in_atoms=%0d out_atoms=%0d bo_bytes=%0d",
                 CASE_ID, IN_ATOMS, OUT_ATOMS, BO_BYTES);
        $finish;
    end

    initial begin
        #2000000;
        $fatal(1, "padded tail replay watchdog");
    end
endmodule
