// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Whole-BO replay of the captured signed-integer Q16 average profiles and the
// 1x1 C32 identity profile.
//
// MODE selects the capture at elaboration through DUT_CASE; each case has its
// own area, element width and lane count.
module tb_ppu_pool_int_avg #(
    parameter integer CASE_ID = 0,
    parameter integer ELEM_W = 8,
    parameter integer LANES = 16,
    parameter integer KH = 2,
    parameter integer KW = 2
);
    localparam int unsigned ATOMS = KH * KW;
    localparam int unsigned BO_BYTES = 4096;
    // The C32 INT8 1x1 case carries two 16-byte atoms per pixel (32 lanes
    // need 32 bytes); every average case carries one atom per pixel. So the
    // input atom count is ATOMS for the averages and 2 for the C32 identity.
    localparam int unsigned IN_ATOMS = (CASE_ID == 4) ? 2 : ATOMS;
    localparam int unsigned OUT_ATOMS = (CASE_ID == 4) ? 2 : 1;

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

    // Observation is taken through a single named instance per case; the
    // generate labels are stripped so hierarchical references stay simple.
    generate
      if (1) begin : g
        case (CASE_ID)
            0: rk_ppu_pool_avg_q16_i8_c16_k2s2 dut (
                   .clk, .rst_n, .in_valid, .in_ready, .in_atom,
                   .out_valid, .out_ready, .out_atom, .out_last);
            1: rk_ppu_pool_avg_q16_i8_c16_k3x3 dut (
                   .clk, .rst_n, .in_valid, .in_ready, .in_atom,
                   .out_valid, .out_ready, .out_atom, .out_last);
            2: rk_ppu_pool_avg_q16_i16_c8_k2s2 dut (
                   .clk, .rst_n, .in_valid, .in_ready, .in_atom,
                   .out_valid, .out_ready, .out_atom, .out_last);
            3: rk_ppu_pool_avg_q16_i16_c8_k3x3 dut (
                   .clk, .rst_n, .in_valid, .in_ready, .in_atom,
                   .out_valid, .out_ready, .out_atom, .out_last);
            4: rk_ppu_pool_max_k1s1_i8_c32 dut (
                   .clk, .rst_n, .in_valid, .in_ready, .in_atom,
                   .out_valid, .out_ready, .out_atom, .out_last);
            default: initial $fatal(1, "unsupported case id");
        endcase
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

        // Drive from the inactive edge so each atom is accepted exactly once:
        // assert after loading in_atom, then release at the next negedge. The
        // leaf accepts one atom per rising edge while in_valid and in_ready
        // are both high, so asserting before the data is loaded would
        // accumulate a zero atom and shift every later lane by one pixel.
        for (beat = 0; beat < IN_ATOMS; beat = beat + 1) begin
            @(negedge clk);
            if (!in_ready) $fatal(1, "leaf stalled before input beat %0d", beat);
            in_atom = atom_bytes(beat);
            in_valid = 1;
            tick();

        end
        @(negedge clk);
        in_valid = 0;

        // Divider latency is bounded; wait for the first output atom.
        for (byte_index = 0; byte_index < 400 && !out_valid; byte_index = byte_index + 1)
            tick();
        if (!out_valid) $fatal(1, "leaf did not emit an output atom");
        // The average leaves hold LANES*ELEM_W = 128 bits of channels, which is
        // exactly ONE 16-byte output atom. The C32 identity profile holds two
        // atoms because 32 INT8 lanes need 32 bytes. OUT_ATOMS says which.
        out_ready = 1;
        for (beat = 0; beat < OUT_ATOMS; beat = beat + 1) begin
            for (byte_index = 0; byte_index < 16; byte_index = byte_index + 1)
                observed[beat * 16 + byte_index] = out_atom[byte_index*8 +: 8];
            @(negedge clk);
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
        $display("PASS PPU_INT_AVG case=%0d elem=%0d lanes=%0d area=%0d bo_bytes=%0d",
                 CASE_ID, ELEM_W, LANES, ATOMS, BO_BYTES);
        $finish;
    end

    initial begin
        #2000000;
        $fatal(1, "signed-integer average replay watchdog");
    end
endmodule
