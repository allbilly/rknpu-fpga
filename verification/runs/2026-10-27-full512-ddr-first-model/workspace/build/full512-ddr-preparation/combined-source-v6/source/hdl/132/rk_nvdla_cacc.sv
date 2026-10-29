// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Ordered FP44-group reduction. Internal interface, not a raw command port.
// Arithmetic is unmodified NVIDIA CACC; only one group is issued at a time.
module rk_nvdla_cacc #(parameter int unsigned TAG_WIDTH=33) (
    input logic clk,rst_n,in_valid,
    output logic in_ready,
    input logic [43:0] in_group,
    input logic in_first,in_last,
    input logic [TAG_WIDTH-1:0] in_tag,
    output logic out_valid,
    input logic out_ready,
    output logic [31:0] out_value,
    output logic [TAG_WIDTH-1:0] out_tag,
    input logic cancel,
    input logic [7:0] cancel_code,
    output logic busy,error,
    output logic [7:0] error_code
);
    logic active,pending,pending_last,held_valid,fault;
    logic [7:0] saved_code,cancel_normalized;
    logic [47:0] partial,donor_partial;
    logic [31:0] donor_final;
    logic donor_pv,donor_fv,legal,accept,issue;
    logic [TAG_WIDTH-1:0] saved_tag;
    initial begin if (TAG_WIDTH==0) $fatal(1,"TAG_WIDTH must be positive");end
    always @* begin
        case (cancel_code)
            1,2,3,4,5,6,7,8:cancel_normalized=cancel_code;
            default:cancel_normalized=6;
        endcase
        legal=1;
`ifndef SYNTHESIS
        // X/Z are simulator states, not electrical detectors. Keep these
        // rejection checks in four-state tests without synthesizing X literals.
        if ((^in_group)===1'bx || (^in_tag)===1'bx) legal=0;
        if ((in_first!==1'b0 && in_first!==1'b1) || (in_last!==1'b0 && in_last!==1'b1)) legal=0;
`endif
        if (in_first!=!active || (active && in_tag!=saved_tag)) legal=0;
        if (in_group[43:38]==6'h3f) begin
            if (in_group[36:27]==0) legal=0;
        end else if (in_group[37:35]!=3'b000 && in_group[37:35]!=3'b111) legal=0;
    end
    assign error=rst_n && (fault || cancel);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : cancel ? cancel_normalized : 8'd0;
    assign in_ready=rst_n && !error && !pending && !held_valid;
    assign accept=in_valid && in_ready;
    assign issue=accept && legal;
    assign out_valid=rst_n && !error && held_valid;
    assign out_tag=saved_tag;
    assign busy=rst_n && !error && (active || pending || held_valid);
    NV_NVDLA_CACC_CALC_fp_48b donor(
        .nvdla_core_clk(clk),.nvdla_core_rstn(rst_n),.in_data(in_group),
        .in_op(partial),.in_op_valid(active),.in_sel(in_last),.in_valid(issue),
        .out_partial_data(donor_partial),.out_partial_valid(donor_pv),
        .out_final_data(donor_final),.out_final_valid(donor_fv));
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active<=0;pending<=0;pending_last<=0;held_valid<=0;fault<=0;saved_code<=0;
            partial<=0;saved_tag<=0;out_value<=0;
        end else begin
            if (!fault && cancel) begin fault<=1;saved_code<=cancel_normalized;end
            if (!error) begin
                if (accept && !legal) begin fault<=1;saved_code<=6;end
                if (issue) begin
                    active<=1;pending<=1;pending_last<=in_last;
                    if (in_first) saved_tag<=in_tag;
                end
                if (donor_pv || donor_fv) begin
                    if (!pending || (donor_pv && donor_fv) || donor_fv!=pending_last) begin
                        fault<=1;saved_code<=6;
                    end else begin
                        pending<=0;
                        if (donor_fv) begin out_value<=donor_final;held_valid<=1;end
                        else partial<=donor_partial;
                    end
                end
                if (out_valid && out_ready) begin held_valid<=0;active<=0;partial<=0;end
            end
        end
    end
endmodule
