// SPDX-License-Identifier: MIT
// Unconstrained binary inputs. Compare compensated lane sum/tag, not the two
// separate carry-save row encodings. Does not prove X/reset/full-array behavior.
module cmac_lane_dsp_miter (
    input wire [15:0] op_a, op_b,
    input wire [3:0] exp_sft,
    input wire pair_nz,
    output wire [31:0] reference_lane, actual_lane,
    output wire [7:0] reference_tag, actual_tag,
    output wire [39:0] difference,
    output wire mismatch
);
    wire [31:0] row_a, row_b;
    reg [31:0] compensation;
    rk_cmac_fp16_rows reference_rows (
        .op_a(op_a), .op_b(op_b), .exp_sft(exp_sft), .pair_nz(pair_nz),
        .res_a(row_a), .res_b(row_b), .res_tag(reference_tag)
    );
    always @* begin
        case(reference_tag)
            8'hf0: compensation = 32'haaab0000;
            8'h78: compensation = 32'hfaaab000;
            8'h3c: compensation = 32'hffaaab00;
            8'h1e: compensation = 32'hfffaaab0;
            8'h0f: compensation = 32'hffffaaab;
            8'h07: compensation = 32'hfffffaab;
            8'h03: compensation = 32'hffffffab;
            8'h01: compensation = 32'hfffffffb;
            default: compensation = 32'd0;
        endcase
    end
    assign reference_lane = row_a + row_b + compensation;
    rk_cmac_fp16_lane_dsp candidate (
        .op_a(op_a), .op_b(op_b), .exp_sft(exp_sft), .pair_nz(pair_nz),
        .lane_sum(actual_lane), .res_tag(actual_tag)
    );
    assign difference = {reference_lane ^ actual_lane, reference_tag ^ actual_tag};
    assign mismatch = |difference;
endmodule
