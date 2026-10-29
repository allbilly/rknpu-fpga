// SPDX-License-Identifier: MIT
// Diagnostic model control only: not a CMAC, raw board or FPGA test.
`timescale 1ns/1ps
module tb_dsp_prefix_primitive_model_control;
    localparam logic [47:0] BIAS = 48'h000055550000;
    logic [29:0] a = 0;
    logic [17:0] b = 0;
    wire [47:0] product;
    DSP48E1 #(
        .ACASCREG(0), .ADREG(0), .ALUMODEREG(0), .AREG(0), .A_INPUT("DIRECT"),
        .BCASCREG(0), .BREG(0), .B_INPUT("DIRECT"), .CARRYINREG(0),
        .CARRYINSELREG(0), .CREG(0), .DREG(0), .INMODEREG(0), .MREG(0),
        .OPMODEREG(0), .PREG(0), .USE_DPORT("FALSE"),
        .USE_MULT("MULTIPLY"), .USE_SIMD("ONE48")
    ) actual_dsp(
        .A(a), .ACIN(30'b0), .ALUMODE(4'b0), .B(b), .BCIN(18'b0),
        .C(BIAS), .CARRYIN(1'b0), .CARRYINSEL(3'b0), .D(25'b0),
        .INMODE(5'b0), .OPMODE(7'b0110101), .P(product), .PCIN(48'b0)
    );
    logic ci = 0, cyinit = 0;
    logic [3:0] di = 0, s = 0;
    wire [3:0] co, sum;
    CARRY4 actual_carry(.CI(ci), .CYINIT(cyinit), .DI(di), .S(s), .CO(co), .O(sum));
    integer dsp_count = 0, carry_binary = 0, carry_four_state = 0;
    integer neg_dsp = 0, neg_carry = 0;
    logic [31:0] rng = 32'h35883216;
    logic [24:0] edge_a [0:7];
    logic [17:0] edge_b [0:7];

    task automatic check_dsp(input logic [24:0] lhs, input logic [17:0] rhs);
        logic signed [63:0] exact;
        logic [47:0] expected;
        begin
            a = {5'b0, lhs}; b = rhs;
            exact = $signed(lhs) * $signed(rhs);
            exact = exact + 64'sh0000000055550000;
            expected = exact[47:0];
            if (neg_dsp != 0 && dsp_count == 0) expected = expected ^ 48'b1;
            #1;
            if (product !== expected)
                $fatal(1, "primitive DSP mismatch case=%0d got=%h expected=%h", dsp_count, product, expected);
            dsp_count = dsp_count + 1;
        end
    endtask

    function automatic logic decode_four_state(input integer digit);
        case (digit)
            0: decode_four_state = 1'b0;
            1: decode_four_state = 1'b1;
            2: decode_four_state = 1'bx;
            default: decode_four_state = 1'bz;
        endcase
    endfunction

    // Independent four-state truth table, not the library's chained ternaries.
    function automatic logic merge_mux(input logic choose, left, right);
        if (choose === 1'b1) merge_mux = left;
        else if (choose === 1'b0) merge_mux = right;
        else if (left === right) merge_mux = left;
        else merge_mux = 1'bx;
    endfunction

    task automatic check_carry;
        logic carry;
        logic [3:0] expected_co, expected_sum;
        integer bit_index;
        begin
            if (ci === 1'b1 || cyinit === 1'b1) carry = 1'b1;
            else if (ci === 1'b0 && cyinit === 1'b0) carry = 1'b0;
            else carry = 1'bx;
            for (bit_index = 0; bit_index < 4; bit_index = bit_index + 1) begin
                if ((s[bit_index] === 1'b0 || s[bit_index] === 1'b1) &&
                    (carry === 1'b0 || carry === 1'b1))
                    expected_sum[bit_index] = (s[bit_index] !== carry);
                else expected_sum[bit_index] = 1'bx;
                carry = merge_mux(s[bit_index], carry, di[bit_index]);
                expected_co[bit_index] = carry;
            end
            if (neg_carry != 0 && carry_binary == 0) expected_co = expected_co ^ 4'b1;
            #1;
            if (co !== expected_co || sum !== expected_sum)
                $fatal(1, "primitive CARRY mismatch case=%0d got=%h/%h expected=%h/%h",
                    carry_binary + carry_four_state, co, sum, expected_co, expected_sum);
        end
    endtask

    integer i, j, n, q, digit;
    logic [24:0] random_a;
    initial begin
        if ($value$plusargs("NEG_DSP=%d", neg_dsp)) begin end
        if ($value$plusargs("NEG_CARRY=%d", neg_carry)) begin end
        edge_a[0]=0; edge_a[1]=1; edge_a[2]=2047; edge_a[3]=2048;
        edge_a[4]=25'h1ffffff; edge_a[5]=25'h1fffffe;
        edge_a[6]=25'h0ffffff; edge_a[7]=25'h1000000;
        edge_b[0]=0; edge_b[1]=1; edge_b[2]=2047; edge_b[3]=2048;
        edge_b[4]=18'h3ffff; edge_b[5]=18'h3fffe;
        edge_b[6]=18'h1ffff; edge_b[7]=18'h20000;
        for (i=0; i<8; i=i+1) for (j=0; j<8; j=j+1) check_dsp(edge_a[i], edge_b[j]);
        for (i=0; i<2048; i=i+1) for (j=0; j<2048; j=j+1)
            check_dsp(25'(i), 18'(j));
        for (n=0; n<65536; n=n+1) begin
            rng = rng ^ (rng << 13); rng = rng ^ (rng >> 17); rng = rng ^ (rng << 5);
            random_a = rng[24:0];
            rng = rng ^ (rng << 13); rng = rng ^ (rng >> 17); rng = rng ^ (rng << 5);
            check_dsp(random_a, rng[17:0]);
        end
        for (n=0; n<1024; n=n+1) begin
            {s, di, cyinit, ci} = 10'(n);
            check_carry(); carry_binary = carry_binary + 1;
        end
`ifndef VERILATOR
        for (n=0; n<1048576; n=n+1) begin
            q=n; ci=decode_four_state(q%4); q=q/4;
            cyinit=decode_four_state(q%4); q=q/4;
            for (digit=0; digit<4; digit=digit+1) begin
                di[digit]=decode_four_state(q%4); q=q/4;
            end
            for (digit=0; digit<4; digit=digit+1) begin
                s[digit]=decode_four_state(q%4); q=q/4;
            end
            check_carry(); carry_four_state = carry_four_state + 1;
        end
`endif
        if (dsp_count != 4259904 || carry_binary != 1024) $fatal(1,"Incomplete primitive control corpus");
`ifdef VERILATOR
        if (carry_four_state != 0) $fatal(1,"Two-state run cannot claim four-state coverage");
`else
        if (carry_four_state != 1048576) $fatal(1,"Incomplete four-state primitive corpus");
`endif
        $display("PASS actual mapped prefix primitive model control dsp=%0d carry_binary=%0d carry_four_state=%0d seed=35883216; not full-array or FPGA acceptance",
            dsp_count, carry_binary, carry_four_state);
        $finish;
    end
endmodule
