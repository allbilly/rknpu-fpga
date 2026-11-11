// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact captured FP16 3x3/stride-2, padded-1, C8 H4W4 maximum profile
// (fp16_max_k3x3_pad1_c8_h4w4 capture).
//
// The capture pads with FP16 -infinity (PPU_PADDING_VALUE_1_CFG = 0xfc00), so
// every padded tap loses the maximum comparison. Out-of-window taps therefore
// contribute -infinity; they are never replaced by zero or a neighbour.
//
// A 3x3 window at stride 2 over a 4x4 surface padded by 1 on each side yields a
// 2x2 output; each output pixel is one 8-lane atom, so four atoms come out.
//
// Verified against the frozen device BO in pure Python before this file was
// written: for each output pixel and channel the maximum over the 3x3 window
// with out-of-range taps at -infinity reproduces all 32 captured values.
//
// Special values: the capture contains no NaN and no +/-0 pair, so no policy
// beyond the captured -inf pad is invented. A NaN input is an explicit fault.
module rk_ppu_pool_max3x3s2_pad1_c8_h4w4 (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         in_valid,
    output logic         in_ready,
    input  logic [127:0] in_atom,
    output logic         out_valid,
    input  logic         out_ready,
    output logic [127:0] out_atom,
    output logic         out_last
);
    localparam int unsigned C = 8;
    localparam int unsigned H = 4;
    localparam int unsigned W = 4;
    localparam int unsigned IN_ATOMS = H * W;      // 16
    localparam int unsigned OUT_ATOMS = 4;         // 2x2 output pixels
    localparam logic [15:0] NEG_INF = 16'hfc00;

    logic [127:0] pixel_q [0:IN_ATOMS-1];
    logic [127:0] result_q [0:3];
    logic [4:0] beat_q;
    logic loaded_q;                // all 16 pixels captured
    logic [2:0] out_beat_q;
    logic [127:0] out_atom_q;
    logic out_valid_q, out_last_q;

    function automatic logic [15:0] fp16_max2(input logic [15:0] a,
                                              input logic [15:0] b);
        begin
            if ((a[14:10] == 5'h1f && a[9:0] != 10'd0) ||
                (b[14:10] == 5'h1f && b[9:0] != 10'd0))
                fp16_max2 = 16'hxxxx;                 // NaN: explicit fault
            else if (a[15] != b[15])
                fp16_max2 = a[15] ? b : a;             // negative loses
            else if (!a[15])
                fp16_max2 = (a[14:0] >= b[14:0]) ? a : b;
            else
                fp16_max2 = (a[14:0] <= b[14:0]) ? a : b;
        end
    endfunction

    // Evaluated in a separate cycle after `loaded_q` is set, so every pixel
    // read here is already committed in `pixel_q`.
    function automatic logic [127:0] window_max(input integer oy,
                                                input integer ox);
        logic [127:0] result;
        logic [15:0] candidate;
        integer y, x;
        begin
            result = '0;
            for (integer lane = 0; lane < C; lane = lane + 1) begin
                candidate = NEG_INF;
                for (integer ky = 0; ky < 3; ky = ky + 1) begin
                    for (integer kx = 0; kx < 3; kx = kx + 1) begin
                        y = oy * 2 - 1 + ky;
                        x = ox * 2 - 1 + kx;
                        if (y >= 0 && y < H && x >= 0 && x < W)
                            candidate = fp16_max2(
                                candidate, pixel_q[y*W + x][lane*16 +: 16]);
                    end
                end
                result[lane*16 +: 16] = candidate;
            end
            window_max = result;
        end
    endfunction

    assign in_ready  = rst_n && !loaded_q;
    assign out_valid = out_valid_q;
    assign out_atom  = out_atom_q;
    assign out_last  = out_last_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            beat_q <= 5'd0;
            loaded_q <= 1'b0;
            out_beat_q <= 3'd0;
            out_atom_q <= 128'b0;
            out_valid_q <= 1'b0;
            out_last_q <= 1'b0;
            for (integer i = 0; i < OUT_ATOMS; i = i + 1)
                result_q[i] <= 128'b0;
        end else begin
            if (out_valid_q && out_ready) begin
                if (out_beat_q == 3'(OUT_ATOMS - 1)) begin
                    out_valid_q <= 1'b0;
                    out_last_q <= 1'b0;
                end else begin
                    out_atom_q <= result_q[out_beat_q[1:0] + 2'd1];
                    out_last_q <= (out_beat_q + 3'd1 == 3'(OUT_ATOMS - 1));
                    out_beat_q <= out_beat_q + 3'd1;
                end
            end

            if (in_valid && in_ready) begin
                pixel_q[beat_q[3:0]] <= in_atom;
                beat_q <= beat_q + 5'd1;
                if (beat_q == 5'(IN_ATOMS - 1))
                    loaded_q <= 1'b1;
            end

            // One cycle later every pixel is committed: evaluate the windows
            // and present the first output atom.
            if (loaded_q && !out_valid_q && out_beat_q == 3'd0) begin
                result_q[0] <= window_max(0, 0);
                result_q[1] <= window_max(0, 1);
                result_q[2] <= window_max(1, 0);
                result_q[3] <= window_max(1, 1);
                out_atom_q <= window_max(0, 0);
                out_valid_q <= 1'b1;
                out_last_q <= 1'b0;
            end
        end
    end
endmodule
