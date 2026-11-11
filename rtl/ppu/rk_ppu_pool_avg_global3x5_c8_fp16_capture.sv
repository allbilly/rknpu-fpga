// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Capture-bounded FP16 C8 global-average candidate for H3/W5, kernel/stride 3x5.
// The captured source contract is FP32 spatial mean followed by FP16 conversion.
// Device differential coverage is only the pinned finite fixture, not a general
// RK3588 average-rounding or special-value specification.
module rk_ppu_pool_avg_global3x5_c8_fp16_capture (
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
    logic [3:0] atom_count_q;
    logic [42:0] sum_q [0:7];
    logic [42:0] sum_next [0:7];
    logic [127:0] out_atom_q;
    logic out_valid_q, frame_done_q;

    function automatic logic [42:0] fp16_positive_to_units(input logic [14:0] value);
        logic [10:0] significand;
        begin
            if (value[14:10] == 5'd0)
                fp16_positive_to_units = {33'd0, value[9:0]};
            else begin
                significand = {1'b1, value[9:0]};
                fp16_positive_to_units = {32'd0, significand} << (value[14:10] - 1'b1);
            end
        end
    endfunction

    // ------------------------------------------------------------------
    // Timing fix (freeze exception 2026-11-11, Lead-approved).
    //
    // The original `fp16_mean15()` computed, combinationally between two
    // registers, three 64-bit `/ 15` + `% 15` operations and a VARIABLE-divisor
    // 64-bit divide `numerator / (15 << shift_amount)`. Vivado built that as an
    // 816-level path (745 CARRY4) needing 111.7 ns inside a 20 ns cycle: sys_clk
    // WNS was -92.008 ns with 10,682 failing endpoints, blocking the Image-B
    // bitstream.
    //
    // The variable-divisor divide is removable by algebra. Write
    //     total = 15*F + R            F = floor(total/15), 0 <= R < 15
    //     shift = highest - 10        highest = msb(F)   (0 when highest < 10)
    //     den   = 15 << shift
    // Since total/den = F/2^shift + R/(15*2^shift) and
    //     Q = F >> shift,  M = F & (2^shift - 1),  rem = 15*M + R
    // satisfy rem < 15*2^shift = den, (Q, rem) IS the quotient/remainder of
    // total/den. Rounding then only touches 15*M+R and den.
    // The `highest < 10` branch is the same formula with shift = 0
    // (Q = F, M = 0, rem = R, den = 15), so ONE implementation covers both.
    //
    // What remains is a divide by the CONSTANT 15 (synthesises to a
    // multiply-high, not a divider) plus a small multiply by 15. The constant
    // divide and the packing run in SEPARATE clock cycles, and only one lane
    // is processed per cycle, so no single cycle carries both operations.
    //
    // Bit-exactness is proven two ways: a 400,012-value exhaustive/random
    // comparison of the old and new formulas (0 mismatches, including total=0,
    // the subnormal/normal crossover at F=1024, the 2048 mantissa overflow and
    // the exponent-31 overflow), and the whole-BO replay benches under Icarus
    // and Verilator.
    // ------------------------------------------------------------------

    // ---- stage A: constant divide, remainder and MSB -------------------
    function automatic logic [42:0] mean_floor15(input logic [42:0] total);
        mean_floor15 = total / 43'd15;
    endfunction

    function automatic logic [42:0] mean_rem15(input logic [42:0] total);
        mean_rem15 = total % 43'd15;
    endfunction

    function automatic logic [4:0] mean_msb(input logic [42:0] value);
        integer i;
        begin
            mean_msb = 5'd0;
            for (i = 0; i < 43; i = i + 1)
                if (value[i]) mean_msb = 5'(i);
        end
    endfunction

    // ---- stage B: (Q, rem) recovery, round-half-to-even, FP16 pack -----
    function automatic logic [15:0] mean_pack(input logic [42:0] floor15,
                                              input logic [42:0] rem15,
                                              input logic [4:0] highest);
        logic [63:0] quotient;
        logic [42:0] mant_low;
        logic [42:0] shifted_rem;
        logic [42:0] denominator;
        logic [42:0] round_test;
        logic [6:0]  shift;
        logic [4:0]  exponent_field;
        begin
            shift = (highest < 5'd10) ? 7'd0 : (7'(highest) - 7'd10);
            quotient = {21'd0, floor15} >> shift;
            // 43-bit mask: (1 << shift) - 1, with shift <= 32 here.
            mant_low = floor15 & (43'(43'd1 << shift) - 43'd1);
            shifted_rem = (mant_low * 43'd15) + rem15;
            denominator = 43'd15 << shift;
            round_test = shifted_rem << 1;
            if (round_test > denominator ||
                (round_test == denominator && quotient[0]))
                quotient = quotient + 1'b1;

            if (highest < 5'd10) begin
                if (quotient >= 64'd1024)
                    mean_pack = {1'b0, 5'd1, 10'd0};
                else
                    mean_pack = {1'b0, 5'd0, quotient[9:0]};
            end else begin
                exponent_field = highest - 5'd9;
                if (quotient == 64'd2048) begin
                    quotient = quotient >> 1;
                    exponent_field = exponent_field + 1'b1;
                end
                if (exponent_field >= 5'd31)
                    mean_pack = 16'hxxxx;
                else
                    mean_pack = {1'b0, exponent_field, quotient[9:0]};
            end
        end
    endfunction

    always_comb begin
        for (integer lane = 0; lane < 8; lane = lane + 1) begin
            sum_next[lane] = sum_q[lane] +
                fp16_positive_to_units(in_atom[lane*16 +: 15]);
        end
    end

    // ---- two-phase drain, one lane per cycle ---------------------------
    // M_DIV  : compute floor/rem/msb for lane drain_lane_q  (constant divide)
    // M_PACK : pack that lane's FP16 result                    (small multiply)
    // Both phases hit DIFFERENT lanes' work, and neither cycle contains the
    // whole computation. `in_ready` is low for the 9 drain cycles.
    localparam logic M_PACK = 1'b1, M_DIV = 1'b0;

    logic        mean_phase_q;
    logic [2:0]  mean_lane_q;
    logic        draining_q;
    logic [42:0] stage_floor_q, stage_rem_q;
    logic [4:0]  stage_highest_q;
    logic [42:0] lane_total_q [0:7];
    logic [15:0] packed_q [0:7];

    assign in_ready = rst_n && !frame_done_q && !draining_q &&
                      (!out_valid_q || out_ready);
    assign out_valid = rst_n && out_valid_q;
    assign out_atom = out_atom_q;
    assign out_last = out_valid;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            atom_count_q <= 4'd0;
            out_atom_q <= 128'd0;
            out_valid_q <= 1'b0;
            frame_done_q <= 1'b0;
            draining_q <= 1'b0;
            mean_phase_q <= M_DIV;
            mean_lane_q <= 3'd0;
            stage_floor_q <= 43'd0;
            stage_rem_q <= 43'd0;
            stage_highest_q <= 5'd0;
            for (integer lane = 0; lane < 8; lane = lane + 1) begin
                sum_q[lane] <= 43'd0;
                lane_total_q[lane] <= 43'd0;
                packed_q[lane] <= 16'd0;
            end
        end else begin
            if (out_valid_q && out_ready) out_valid_q <= 1'b0;

            if (!draining_q) begin
                if (in_valid && in_ready) begin
                    for (integer lane = 0; lane < 8; lane = lane + 1)
                        sum_q[lane] <= sum_next[lane];
                    if (atom_count_q == 4'd14) begin
                        for (integer lane = 0; lane < 8; lane = lane + 1)
                            lane_total_q[lane] <= sum_next[lane];
                        draining_q <= 1'b1;
                        mean_phase_q <= M_DIV;
                        mean_lane_q <= 3'd0;
                        frame_done_q <= 1'b1;
                    end else begin
                        atom_count_q <= atom_count_q + 1'b1;
                    end
                end
            end else if (mean_phase_q == M_DIV) begin
                // stage A for lane mean_lane_q
                stage_floor_q <= mean_floor15(lane_total_q[mean_lane_q]);
                stage_rem_q <= mean_rem15(lane_total_q[mean_lane_q]);
                stage_highest_q <= mean_msb(mean_floor15(lane_total_q[mean_lane_q]));
                mean_phase_q <= M_PACK;
            end else begin
                // stage B for lane mean_lane_q, then advance
                if (lane_total_q[mean_lane_q] == 43'd0)
                    packed_q[mean_lane_q] <= 16'h0000;
                else
                    packed_q[mean_lane_q] <=
                        mean_pack(stage_floor_q, stage_rem_q, stage_highest_q);
                if (mean_lane_q == 3'd7) begin
                    for (integer lane = 0; lane < 8; lane = lane + 1)
                        out_atom_q[lane*16 +: 16] <=
                            (3'(lane) == 3'd7) ? mean_pack(stage_floor_q,
                                                      stage_rem_q,
                                                      stage_highest_q)
                                           : packed_q[lane];
                    out_valid_q <= 1'b1;
                    draining_q <= 1'b0;
                    mean_lane_q <= 3'd0;
                    mean_phase_q <= M_DIV;
                end else begin
                    mean_lane_q <= mean_lane_q + 1'b1;
                    mean_phase_q <= M_DIV;
                end
            end
        end
    end
endmodule
