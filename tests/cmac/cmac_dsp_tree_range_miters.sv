// SPDX-License-Identifier: MIT
// Conditional full-integer, not just modular, carry-save identities.
// All words are free binary inputs. No assertion that actual donor operands
// satisfy these bounds, no assume cells and no whole-lane acceptance.
`ifdef RK_COMPONENT_NEGATIVE
`define RK_TREE_RANGE_FLIP 1
`else
`define RK_TREE_RANGE_FLIP 0
`endif

module cmac_tree_5x24_integer_lemma (
    input wire [119:0] words,
    output wire [24:0] difference,
    output wire mismatch,
    output wire sum_overflow
);
    wire [23:0] row_a,row_b;
    NV_DW02_tree #(5,24) donor(.INPUT(words),.OUT0(row_a),.OUT1(row_b));
    wire [26:0] full_sum = {3'd0,words[0+:24]}+{3'd0,words[24+:24]}
        +{3'd0,words[48+:24]}+{3'd0,words[72+:24]}+{3'd0,words[96+:24]};
    wire [24:0] row_sum = {1'b0,row_a}+{1'b0,row_b};
    assign sum_overflow = |full_sum[26:24];
    assign difference = row_sum ^ full_sum[24:0] ^ `RK_TREE_RANGE_FLIP;
    assign mismatch = !sum_overflow && (|difference);
endmodule

module cmac_tree_4x32_integer_lemma (
    input wire [127:0] words,
    output wire [32:0] difference,
    output wire mismatch,
    output wire sum_overflow
);
    wire [31:0] row_a,row_b;
    NV_DW02_tree #(4,32) donor(.INPUT(words),.OUT0(row_a),.OUT1(row_b));
    wire [33:0] full_sum = {2'd0,words[0+:32]}+{2'd0,words[32+:32]}
        +{2'd0,words[64+:32]}+{2'd0,words[96+:32]};
    wire [32:0] row_sum = {1'b0,row_a}+{1'b0,row_b};
    assign sum_overflow = |full_sum[33:32];
    assign difference = row_sum ^ full_sum[32:0] ^ `RK_TREE_RANGE_FLIP;
    assign mismatch = !sum_overflow && (|difference);
endmodule

`undef RK_TREE_RANGE_FLIP
