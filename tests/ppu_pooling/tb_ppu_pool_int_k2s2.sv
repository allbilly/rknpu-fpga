// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Whole-BO replay of the captured signed-integer 2x2/stride-2 pooling cases
// against the shared parameterized reducer.
//
// The bench is parameterized by element width, lane count and method so the
// four captured profiles share one replay body:
//   ELEM_W=8,  LANES=16, METHOD=0  int8_max_k2s2_valid_c16_h2w2
//   ELEM_W=8,  LANES=16, METHOD=1  int8_min_k2s2_valid_c16_h2w2
//   ELEM_W=16, LANES=8,  METHOD=0  int16_max_k2s2_valid_c8_h2w2
//   ELEM_W=16, LANES=8,  METHOD=1  int16_min_k2s2_valid_c8_h2w2
//
// It reads the frozen input BO, the initialized output BO and the device
// output BO, drives the four captured input atoms, writes the single output
// atom, then compares the complete 4096-byte output BO byte by byte.
module tb_ppu_pool_int_k2s2 #(
    parameter integer ELEM_W = 8,
    parameter integer LANES = 16,
    parameter integer METHOD = 0
);
    localparam int unsigned BO_BYTES = 4096;
    localparam int unsigned ATOM_BYTES = 16;
    localparam int unsigned INPUT_BEATS = 4;
    localparam int unsigned VALUE_BYTES = 16;

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
        if (ELEM_W == 8 && LANES == 16 && METHOD == 0) begin : g_i8_max
            rk_ppu_pool_max_k2s2_i8_c16_h2w2 dut (
                .clk, .rst_n, .in_valid, .in_ready, .in_atom,
                .out_valid, .out_ready, .out_atom, .out_last
            );
        end else if (ELEM_W == 8 && LANES == 16) begin : g_i8_min
            rk_ppu_pool_min_k2s2_i8_c16_h2w2 dut (
                .clk, .rst_n, .in_valid, .in_ready, .in_atom,
                .out_valid, .out_ready, .out_atom, .out_last
            );
        end else if (ELEM_W == 16 && LANES == 8 && METHOD == 0) begin : g_i16_max
            rk_ppu_pool_max_k2s2_i16_c8_h2w2 dut (
                .clk, .rst_n, .in_valid, .in_ready, .in_atom,
                .out_valid, .out_ready, .out_atom, .out_last
            );
        end else if (ELEM_W == 16 && LANES == 8) begin : g_i16_min
            rk_ppu_pool_min_k2s2_i16_c8_h2w2 dut (
                .clk, .rst_n, .in_valid, .in_ready, .in_atom,
                .out_valid, .out_ready, .out_atom, .out_last
            );
        end else begin : g_unsupported
            initial $fatal(1, "unsupported integer pooling replay geometry");
        end
    endgenerate

    task automatic tick;
        begin @(posedge clk); #2; end
    endtask

    function automatic logic [127:0] atom_bytes(input integer index);
        integer offset;
        begin
            offset = index * ATOM_BYTES;
            for (integer lane = 0; lane < ATOM_BYTES; lane = lane + 1)
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

        for (beat = 0; beat < INPUT_BEATS; beat = beat + 1) begin
            @(negedge clk);
            if (!in_ready) $fatal(1, "leaf stalled before input beat %0d", beat);
            in_atom = atom_bytes(beat);
            in_valid = 1;
            tick();
        end
        @(negedge clk);
        in_valid = 0;

        repeat (4) tick();
        if (!out_valid) $fatal(1, "leaf did not emit an output atom");
        if (out_last !== 1'b1) $fatal(1, "out_last must assert on the only atom");
        for (byte_index = 0; byte_index < VALUE_BYTES; byte_index = byte_index + 1)
            observed[byte_index] = out_atom[byte_index*8 +: 8];

        out_ready = 1;
        tick();
        @(negedge clk);
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
        $display("PASS PPU_INT_K2S2 elem=%0d lanes=%0d method=%0d beats=%0d bo_bytes=%0d",
                 ELEM_W, LANES, METHOD, INPUT_BEATS, BO_BYTES);
        $finish;
    end

    initial begin
        #2000000;
        $fatal(1, "signed-integer k2s2 replay watchdog");
    end
endmodule
