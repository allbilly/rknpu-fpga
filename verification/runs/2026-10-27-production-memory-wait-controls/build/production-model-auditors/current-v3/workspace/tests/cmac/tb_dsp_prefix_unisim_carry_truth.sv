// SPDX-License-Identifier: MIT
// Vendor-model truth-table control. Not equivalence to Yosys four-state carry.
`timescale 1ns/1ps
module tb_dsp_prefix_unisim_carry_truth;
    logic ci = 0, cyinit = 0;
    logic [3:0] di = 0, s = 0;
    wire [3:0] co, sum;
    CARRY4 actual(.CI(ci), .CYINIT(cyinit), .DI(di), .S(s), .CO(co), .O(sum));
    integer binary_count = 0, four_count = 0, differences = 0, negative = 0;
    integer first_difference = -1;

    function automatic logic decode(input integer digit);
        case (digit)
            0: decode = 1'b0;
            1: decode = 1'b1;
            2: decode = 1'bx;
            default: decode = 1'bz;
        endcase
    endfunction
    function automatic logic truth_and(input logic left, right);
        if (left === 1'b0 || right === 1'b0) truth_and = 1'b0;
        else if (left === 1'b1 && right === 1'b1) truth_and = 1'b1;
        else truth_and = 1'bx;
    endfunction
    function automatic logic truth_or(input logic left, right);
        if (left === 1'b1 || right === 1'b1) truth_or = 1'b1;
        else if (left === 1'b0 && right === 1'b0) truth_or = 1'b0;
        else truth_or = 1'bx;
    endfunction
    function automatic logic truth_not(input logic value);
        if (value === 1'b0) truth_not = 1'b1;
        else if (value === 1'b1) truth_not = 1'b0;
        else truth_not = 1'bx;
    endfunction
    function automatic logic truth_xor(input logic left, right);
        if ((left === 1'b0 || left === 1'b1) && (right === 1'b0 || right === 1'b1))
            truth_xor = (left !== right);
        else truth_xor = 1'bx;
    endfunction
    function automatic logic yosys_mux(input logic choose, left, right);
        if (choose === 1'b1) yosys_mux = left;
        else if (choose === 1'b0) yosys_mux = right;
        else if (left === right) yosys_mux = left;
        else yosys_mux = 1'bx;
    endfunction
    task automatic check_case(input logic is_binary);
        logic vendor_carry, yosys_carry;
        logic [3:0] vendor_co, vendor_sum, yosys_co, yosys_sum;
        integer bit_index;
        begin
            // Pinned UNISIM explicitly gives unconnected Z carry inputs 0.
            vendor_carry = truth_or(ci === 1'bz ? 1'b0 : ci,
                                    cyinit === 1'bz ? 1'b0 : cyinit);
            yosys_carry = truth_or(ci, cyinit);
            for (bit_index = 0; bit_index < 4; bit_index = bit_index + 1) begin
                vendor_sum[bit_index] = truth_xor(s[bit_index], vendor_carry);
                vendor_carry = truth_or(truth_and(s[bit_index], vendor_carry),
                                        truth_and(truth_not(s[bit_index]), di[bit_index]));
                vendor_co[bit_index] = vendor_carry;
                yosys_sum[bit_index] = truth_xor(s[bit_index], yosys_carry);
                yosys_carry = yosys_mux(s[bit_index], yosys_carry, di[bit_index]);
                yosys_co[bit_index] = yosys_carry;
            end
            if (negative != 0 && binary_count == 0) vendor_co = vendor_co ^ 4'b1;
            #1;
            if (co !== vendor_co || sum !== vendor_sum)
                $fatal(1, "vendor CARRY mismatch case=%0d got=%h/%h expected=%h/%h",
                    binary_count + four_count, co, sum, vendor_co, vendor_sum);
            if (co !== yosys_co || sum !== yosys_sum) begin
                if (is_binary) $fatal(1, "Binary Yosys/vendor carry disagreement");
                if (first_difference == -1) first_difference = four_count;
                differences = differences + 1;
            end
        end
    endtask
    integer n, q, digit;
    initial begin
        if ($value$plusargs("NEGATIVE=%d", negative)) begin end
        wait(glbl.GSR === 1'b0); #1;
        for (n = 0; n < 1024; n = n + 1) begin
            {s, di, cyinit, ci} = 10'(n);
            check_case(1'b1); binary_count = binary_count + 1;
        end
        for (n = 0; n < 1048576; n = n + 1) begin
            q = n; ci = decode(q%4); q = q/4;
            cyinit = decode(q%4); q = q/4;
            for (digit = 0; digit < 4; digit = digit + 1) begin
                di[digit] = decode(q%4); q = q/4;
            end
            for (digit = 0; digit < 4; digit = digit + 1) begin
                s[digit] = decode(q%4); q = q/4;
            end
            check_case(1'b0); four_count = four_count + 1;
        end
        if (binary_count != 1024 || four_count != 1048576 || differences <= 0 || first_difference < 0)
            $fatal(1, "Incomplete vendor carry corpus or missing explicit four-state difference");
        $display("PASS pinned UNISIM CARRY truth binary=%0d four_state=%0d yosys_four_state_differences=%0d first_difference=%0d; not Yosys four-state equivalence or FPGA acceptance",
            binary_count, four_count, differences, first_difference);
        $finish;
    end
endmodule
