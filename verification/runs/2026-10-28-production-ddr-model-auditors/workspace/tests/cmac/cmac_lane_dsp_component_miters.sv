// SPDX-License-Identifier: MIT
// Binary component lemmas only. These are not a composed DSP-lane proof.
// All top-level inputs are unconstrained; no assume cells or cutpoint axioms.
`ifdef RK_COMPONENT_NEGATIVE
`define RK_COMPONENT_FLIP 1
`else
`define RK_COMPONENT_FLIP 0
`endif

module cmac_booth_recoding_lemma (
    input wire [2:0] code,
    input wire sign,
    input wire [14:0] magnitude,
    output wire [31:0] difference,
    output wire mismatch
);
    wire [16:0] selected;
    wire inverted;
    NV_NVDLA_CMAC_CORE_MAC_booth donor (
        .code(code), .is_8bit(1'b0), .sign(sign),
        .src_data({1'b0,magnitude}), .out_data(selected), .out_inv(inverted)
    );
    wire signed [31:0] positive = $signed({17'd0,magnitude});
    reg signed [31:0] digit_product;
    always @* begin
        case(code)
            3'b000,3'b111:digit_product=0;
            3'b001,3'b010:digit_product=positive;
            3'b011:digit_product=positive<<<1;
            3'b100:digit_product=-(positive<<<1);
            3'b101,3'b110:digit_product=-positive;
        endcase
    end
    wire [31:0] expected = 32'h00010000 + (sign ? -digit_product:digit_product);
    wire [31:0] actual = {15'd0,selected} + {31'd0,inverted};
    assign difference = actual ^ expected ^ `RK_COMPONENT_FLIP;
    assign mismatch = |difference;
endmodule

module cmac_tree_5x24_lemma (
    input wire [119:0] words,
    output wire [23:0] difference,
    output wire mismatch
);
    wire [23:0] row_a,row_b;
    NV_DW02_tree #(5,24) donor(.INPUT(words),.OUT0(row_a),.OUT1(row_b));
    wire [23:0] expected = words[0+:24]+words[24+:24]+words[48+:24]+words[72+:24]+words[96+:24];
    assign difference = (row_a+row_b) ^ expected ^ `RK_COMPONENT_FLIP;
    assign mismatch = |difference;
endmodule

module cmac_tree_4x32_lemma (
    input wire [127:0] words,
    output wire [31:0] difference,
    output wire mismatch
);
    wire [31:0] row_a,row_b;
    NV_DW02_tree #(4,32) donor(.INPUT(words),.OUT0(row_a),.OUT1(row_b));
    wire [31:0] expected = words[0+:32]+words[32+:32]+words[64+:32]+words[96+:32];
    assign difference = (row_a+row_b) ^ expected ^ `RK_COMPONENT_FLIP;
    assign mismatch = |difference;
endmodule

module cmac_booth_digits_lemma (
    input wire [14:0] magnitude,
    input wire sign,
    output wire [31:0] difference,
    output wire mismatch
);
    wire [16:0] codes = {1'b0,magnitude,1'b0};
    wire signed [31:0] terms[8];
    for(genvar i=0;i<8;i=i+1) begin: digits
        wire signed [31:0] digit = -$signed({30'd0,codes[2*i+2],1'b0})
            + $signed({31'd0,codes[2*i+1]}) + $signed({31'd0,codes[2*i]});
        assign terms[i] = (sign ? -digit:digit) <<< (2*i);
    end
    wire [31:0] actual = terms[0]+terms[1]+terms[2]+terms[3]+terms[4]+terms[5]+terms[6]+terms[7];
    wire signed [31:0] positive = $signed({17'd0,magnitude});
    wire [31:0] expected = sign ? -positive:positive;
    assign difference = actual ^ expected ^ `RK_COMPONENT_FLIP;
    assign mismatch = |difference;
endmodule

module cmac_discarded_carry_lemma (
    input wire [31:0] row_a,row_b,
    input wire [2:0] shift,
    output wire [31:0] difference,
    output wire mismatch,
    output wire sum_overflow
);
    wire [32:0] full_sum = {1'b0,row_a}+{1'b0,row_b};
    wire [31:0] sum = full_sum[31:0];
    wire [4:0] amount = {shift,2'b00};
    wire [31:0] mask = (32'd1 << amount)-32'd1;
    wire carry = (row_a & mask) > (sum & mask);
    wire [31:0] separately_shifted = (row_a >> amount)+(row_b >> amount);
    wire [31:0] corrected = (sum >> amount)-{31'd0,carry};
    assign sum_overflow = full_sum[32];
    assign difference = separately_shifted ^ corrected ^ `RK_COMPONENT_FLIP;
    // This theorem is conditional, not a proof that the donor sum cannot
    // overflow. That concrete source-bound range/composition gate is missing.
    assign mismatch = !sum_overflow && (|difference);
endmodule

`undef RK_COMPONENT_FLIP
