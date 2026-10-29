// SPDX-License-Identifier: MIT
// Binary combinational mapping check. The parent proof separately establishes
// the donor's post-configuration contract; this is not reset/X/timing signoff.
module cmac_fixed_rows_mapped_miter (
    input wire clk, rst_n, pair_nz,
    input wire [15:0] op_a, op_b,
    input wire [3:0] exp_sft,
    output wire [31:0] reference_a, reference_b, mapped_a, mapped_b,
    output wire [7:0] reference_tag, mapped_tag,
    output wire [71:0] difference,
    output wire mismatch
);
    rk_cmac_fp16_rows reference_rows (
        .op_a(op_a), .op_b(op_b), .exp_sft(exp_sft), .pair_nz(pair_nz),
        .res_a(reference_a), .res_b(reference_b), .res_tag(reference_tag)
    );
    fp16_rows_area_top actual_mapped_rows (
        .clk(clk), .rst_n(rst_n), .op_a(op_a), .op_b(op_b),
        .exp_sft(exp_sft), .pair_nz(pair_nz),
        .res_a(mapped_a), .res_b(mapped_b), .res_tag(mapped_tag)
    );
    assign difference = {reference_a ^ mapped_a, reference_b ^ mapped_b,
                         reference_tag ^ mapped_tag};
    assign mismatch = |difference;
endmodule
