// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Original, synthesis-oriented scalar binary16 ADD/SUB/MUL implementation.
// Policy: round-to-nearest-even, gradual underflow, canonical quiet NaN 7e00.
// This policy is not asserted to match every RK3588 special-value quirk.
// The wide exact adder favors reviewability over Fmax/area. No real/shortreal,
// DPI, vendor IP, or host arithmetic is present in the hardware datapath.
module rk_fp16_alu (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        in_valid,
    output logic        in_ready,
    input  logic [1:0]  in_op, // 0 ADD, 1 SUB, 2 MUL; 3 is invalid
    input  logic [15:0] in_a,
    input  logic [15:0] in_b,
    output logic        out_valid,
    input  logic        out_ready,
    output logic [15:0] out_data
);
    function automatic logic [63:0] rshift_rne(
        input logic [63:0] x, input integer shift
    );
        logic [63:0] q, rem_bits, halfway;
        begin
            q = 0; rem_bits = 0; halfway = 0;
            if (shift <= 0) rshift_rne = x << (-shift);
            else if (shift >= 64) rshift_rne = 0;
            else begin
                q = x >> shift;
                rem_bits = x & ((64'd1 << shift) - 1);
                halfway = 64'd1 << (shift - 1);
                rshift_rne = q + {63'b0, ((rem_bits > halfway) ||
                    ((rem_bits == halfway) && q[0]))};
            end
        end
    endfunction

    // Exact positive integer n times 2**scale, rounded once to binary16.
    function automatic logic [15:0] pack_half(
        input logic sign_bit, input logic [63:0] n, input integer scale
    );
        integer p, i, exponent;
        logic [63:0] q;
        logic [4:0] exp_field;
        begin
            p = 0; q = 0; exponent = 0; exp_field = 0;
            for (i = 0; i < 64; i = i + 1)
                if (n[i]) p = i;
            exponent = p + scale;
            if (n == 0) pack_half = {sign_bit, 15'b0};
            else if (exponent < -14) begin
                q = rshift_rne(n, -scale - 24);
                // q==1024 naturally encodes the smallest normal number.
                pack_half = {sign_bit, 15'b0} | {5'b0, q[10:0]};
            end else begin
                q = rshift_rne(n, p - 10);
                if (q == 2048) begin
                    q = q >> 1;
                    exponent = exponent + 1;
                end
                exp_field = 5'(exponent + 15);
                if (exponent > 15) pack_half = {sign_bit, 5'h1f, 10'b0};
                else pack_half = {sign_bit, exp_field, q[9:0]};
            end
        end
    endfunction

    function automatic logic [15:0] calculate(
        input logic [15:0] a, b, input logic [1:0] op
    );
        logic sa, sb, na, nb, ia, ib, za, zb, neg;
        logic [10:0] ma, mb;
        logic [21:0] product;
        logic [39:0] ua, ub;
        logic signed [41:0] va, vb, total;
        logic [41:0] magnitude;
        integer ea, eb;
        begin
            sa = a[15]; sb = b[15] ^ (op == 1);
            na = (&a[14:10]) && (|a[9:0]);
            nb = (&b[14:10]) && (|b[9:0]);
            ia = (&a[14:10]) && !(|a[9:0]);
            ib = (&b[14:10]) && !(|b[9:0]);
            za = !(|a[14:0]); zb = !(|b[14:0]);
            ea = (a[14:10] == 0) ? 1 : int'(a[14:10]);
            eb = (b[14:10] == 0) ? 1 : int'(b[14:10]);
            ma = {(|a[14:10]), a[9:0]};
            mb = {(|b[14:10]), b[9:0]};
            product = ma * mb;
            ua = {29'b0, ma} << (ea - 1);
            ub = {29'b0, mb} << (eb - 1);
            va = sa ? -$signed({2'b0, ua}) : $signed({2'b0, ua});
            vb = sb ? -$signed({2'b0, ub}) : $signed({2'b0, ub});
            total = va + vb;
            neg = total[41];
            magnitude = neg ? $unsigned(-total) : $unsigned(total);
            if (na || nb || op == 3) calculate = 16'h7e00;
            else if (op == 2) begin
                if ((ia && zb) || (ib && za)) calculate = 16'h7e00;
                else if (ia || ib) calculate = {sa ^ sb, 5'h1f, 10'b0};
                else calculate = pack_half(sa ^ sb, {42'b0, product}, ea + eb - 50);
            end else begin
                if (ia && ib && (sa != sb)) calculate = 16'h7e00;
                else if (ia) calculate = {sa, 5'h1f, 10'b0};
                else if (ib) calculate = {sb, 5'h1f, 10'b0};
                else if (magnitude == 0)
                    calculate = {(sa && sb), 15'b0};
                else calculate = pack_half(neg, {22'b0, magnitude}, -24);
            end
        end
    endfunction

    assign in_ready = !out_valid || out_ready;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 0;
            out_data <= 0;
        end else if (in_ready) begin
            out_valid <= in_valid;
            if (in_valid) out_data <= calculate(in_a, in_b, in_op);
        end
    end
endmodule
