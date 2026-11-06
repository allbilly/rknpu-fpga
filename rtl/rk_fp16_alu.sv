// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Original, synthesis-oriented scalar binary16 ADD/SUB/MUL/MAX/FDIV implementation.
// Policy: round-to-nearest-even, gradual underflow, RK-captured NaN 7c01.
// MAX uses IEEE maximum ordering, including +0 over -0. Captured RK behavior
// also gives +0 for exact ADD/SUB cancellation and a SUB-only infinity quirk:
// same-sign infinities return +inf, opposite-sign infinities return NaN.
// FDIV reproduces the candidate RK3588 three-guard-bit quotient contract:
// exact finite quotient truncated three bits below the destination quantum,
// then ties-to-even. Special results use sign(a); finite results use sign(a)^sign(b).
// The wide exact adder favors reviewability over Fmax/area. No real/shortreal,
// DPI, vendor IP, or host arithmetic is present in the hardware datapath.
module rk_fp16_alu (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        in_valid,
    output logic        in_ready,
    input  logic [2:0]  in_op, // 0 ADD, 1 SUB, 2 MUL, 3 MAX, 4 FDIV; 5..7 invalid
    input  logic [15:0] in_a,
    input  logic [15:0] in_b,
    output logic        out_valid,
    input  logic        out_ready,
    output logic [15:0] out_data
);
    typedef enum logic [1:0] {IDLE, DIV, PACK} state_t;
    state_t state;

    logic [24:0] div_num;
    logic [23:0] div_den, div_rem;
    logic [24:0] div_trial;
    logic [13:0] div_quot;
    logic div_ge;
    logic [3:0] div_bit;
    logic signed [8:0] div_e;
    logic div_sign;
    logic [24:0] fdiv_start_num;
    logic [23:0] fdiv_start_den;
    logic signed [8:0] fdiv_start_e;
    logic [15:0] fdiv_special_data;
    logic fdiv_is_special;

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

    function automatic integer msb10(input logic [9:0] x);
        integer i;
        begin
            msb10 = 0;
            for (i = 0; i < 10; i = i + 1)
                if (x[i]) msb10 = i;
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

    // Three-guard-bit finite quotient packing. d = floor(8 * quotient/ulp).
    function automatic logic [15:0] pack_fdiv(
        input logic sign_bit, input logic signed [8:0] e_in, input logic [13:0] d
    );
        logic signed [8:0] exponent;
        logic [11:0] n;
        logic [4:0] exp_field;
        begin
            exponent = e_in;
            n = {1'b0, d[13:3]};
            if ((d[2:0] > 3'd4) || ((d[2:0] == 3'd4) && n[0])) n = n + 1'b1;
            if (n == 12'd2048) begin
                n = 12'd1024;
                exponent = exponent + 1'b1;
            end
            if ((n == 12'd1024) && (exponent < -14)) exponent = -14;
            exp_field = 5'(exponent + 15);
            if (exponent < -14) pack_fdiv = {sign_bit, 5'h00, n[9:0]};
            else if (exponent > 15) pack_fdiv = {sign_bit, 5'h1f, 10'b0};
            else pack_fdiv = {sign_bit, exp_field, n[9:0]};
        end
    endfunction

    function automatic logic [15:0] calculate(
        input logic [15:0] a, b, input logic [2:0] op
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
            if (na || nb || op > 4) calculate = 16'h7c01;
            else if (op == 3) begin
                if (sa != sb) calculate = sa ? b : a;
                else if (!sa) calculate = ({a[14:0]} >= {b[14:0]}) ? a : b;
                else calculate = ({a[14:0]} <= {b[14:0]}) ? a : b;
            end else if (op == 2) begin
                if ((ia && zb) || (ib && za)) calculate = 16'h7c01;
                else if (ia || ib) calculate = {sa ^ sb, 5'h1f, 10'b0};
                else calculate = pack_half(sa ^ sb, {42'b0, product}, ea + eb - 50);
            end else begin
                if (ia && ib) begin
                    if (op == 1) calculate = (sa != sb) ? 16'h7c00 : 16'h7c01;
                    else calculate = (sa == sb) ? {sa, 5'h1f, 10'b0} : 16'h7c01;
                end else if (ia) calculate = {sa, 5'h1f, 10'b0};
                else if (ib) calculate = {sb, 5'h1f, 10'b0};
                else if (magnitude == 0) calculate = 16'b0;
                else calculate = pack_half(neg, {22'b0, magnitude}, -24);
            end
        end
    endfunction

    // Unpack finite nonzero operands and prepare the long-division operands.
    always_comb begin : fdiv_unpack
        logic [10:0] ua, ub;
        logic [9:0] fa, fb;
        logic [24:0] num;
        logic [23:0] den;
        integer ea, eb, p, k, e_i, ue, shift;
        ua = 0; ub = 0; fa = 0; fb = 0; num = 0; den = 0;
        ea = 0; eb = 0; p = 0; k = 0; e_i = 0; ue = 0; shift = 0;
        fa = in_a[9:0];
        fb = in_b[9:0];
        if (in_a[14:10] != 5'd0) begin
            ua = {1'b1, fa};
            ea = int'(in_a[14:10]) - 15;
        end else begin
            p = msb10(fa);
            k = 10 - p;
            ua = {1'b0, fa} << k;
            ea = -14 - k;
        end
        if (in_b[14:10] != 5'd0) begin
            ub = {1'b1, fb};
            eb = int'(in_b[14:10]) - 15;
        end else begin
            p = msb10(fb);
            k = 10 - p;
            ub = {1'b0, fb} << k;
            eb = -14 - k;
        end
        if (ua >= ub) begin
            e_i = ea - eb;
            num = {{14{1'b0}}, ua};
        end else begin
            e_i = ea - eb - 1;
            num = {{13{1'b0}}, ua, 1'b0};
        end
        den = {{13{1'b0}}, ub};
        ue = (e_i >= -14) ? (e_i - 10) : -24;
        shift = e_i - ue + 3;
        if (shift >= 0) num = num << shift;
        else den = den << (-shift);
        fdiv_start_num = num;
        fdiv_start_den = den;
        fdiv_start_e = 9'(e_i);
    end

    // Captured special-value precedence and the special-path sign(a) rule.
    always_comb begin : fdiv_classify
        logic a_nan, b_nan, a_inf, b_inf, a_zero, b_zero;
        a_nan = (&in_a[14:10]) && (|in_a[9:0]);
        b_nan = (&in_b[14:10]) && (|in_b[9:0]);
        a_inf = (&in_a[14:10]) && !(|in_a[9:0]);
        b_inf = (&in_b[14:10]) && !(|in_b[9:0]);
        a_zero = !(|in_a[14:0]);
        b_zero = !(|in_b[14:0]);
        fdiv_special_data = 16'h0000;
        if (a_nan || b_nan) fdiv_special_data = 16'h7c01;
        else if ((in_a == 16'h0000) && (in_b == 16'h0000)) fdiv_special_data = 16'h7c01;
        else if (b_zero) fdiv_special_data = {in_a[15], 5'h1f, 10'b0};
        else if (a_zero) fdiv_special_data = {in_a[15], 5'h00, 10'b0};
        else if (a_inf) fdiv_special_data = {in_a[15], 5'h1f, 10'b0};
        else if (b_inf) fdiv_special_data = {in_a[15], 5'h00, 10'b0};
        fdiv_is_special = a_nan || b_nan ||
            ((in_a == 16'h0000) && (in_b == 16'h0000)) ||
            b_zero || a_zero || a_inf || b_inf;
    end

    assign div_trial = {div_rem, div_num[{1'b0, div_bit}]};
    assign div_ge = div_trial >= {1'b0, div_den};

    assign in_ready = (state == IDLE) && (!out_valid || out_ready);

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state <= IDLE;
            out_valid <= 0;
            out_data <= 0;
            div_num <= 0; div_den <= 0; div_rem <= 0; div_quot <= 0;
            div_bit <= 0; div_e <= 0; div_sign <= 0;
        end else if (state == IDLE) begin
            if (in_valid && in_ready) begin
                if (in_op == 3'd4) begin
                    if (fdiv_is_special) begin
                        out_valid <= 1'b1;
                        out_data <= fdiv_special_data;
                    end else begin
                        out_valid <= 1'b0;
                        div_num <= fdiv_start_num;
                        div_den <= fdiv_start_den;
                        div_e <= fdiv_start_e;
                        div_sign <= in_a[15] ^ in_b[15];
                        // N = H*2^14 + L. Quotient < 2^14 implies H < den, so
                        // start the 14-bit long division with remainder H.
                        div_rem <= {13'b0, fdiv_start_num[24:14]};
                        div_quot <= 0;
                        div_bit <= 4'd13;
                        state <= DIV;
                    end
                end else begin
                    out_valid <= 1'b1;
                    out_data <= calculate(in_a, in_b, in_op);
                end
            end else if (out_valid && out_ready) begin
                out_valid <= 1'b0;
            end
        end else if (state == DIV) begin
            div_rem <= div_ge ? (div_trial[23:0] - div_den) : div_trial[23:0];
            div_quot[div_bit] <= div_ge;
            if (div_bit == 0) state <= PACK;
            else div_bit <= div_bit - 1'b1;
        end else begin
            state <= IDLE;
            out_valid <= 1'b1;
            out_data <= pack_fdiv(div_sign, div_e, div_quot);
        end
    end
endmodule
