// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Tag/handshake adapter ONLY. Arithmetic is the unmodified NVIDIA donor.
// One in-flight value; tags never pass through floating-point arithmetic.
// Reset must also reset downstream ownership/transport at the enclosing job.
module rk_nvdla_fp32_to_fp16 #(
    parameter int unsigned TAG_WIDTH=97
) (
    input logic clk,rst_n,
    input logic in_valid,
    output logic in_ready,
    input logic [31:0] in_value,
    input logic [TAG_WIDTH-1:0] in_tag,
    output logic out_valid,
    input logic out_ready,
    output logic [15:0] out_value,
    output logic [TAG_WIDTH-1:0] out_tag
);
    logic pending,donor_in_ready,donor_out_valid;
    logic [TAG_WIDTH-1:0] saved_tag;
    initial begin
        if (TAG_WIDTH==0) $fatal(1,"TAG_WIDTH must be positive");
    end
    assign in_ready=rst_n && !pending && donor_in_ready;
    assign out_valid=rst_n && pending && donor_out_valid;
    assign out_tag=saved_tag;
    HLS_fp32_to_fp16 donor(
        .nvdla_core_clk(clk),.nvdla_core_rstn(rst_n),
        .chn_a_rsc_z(in_value),.chn_a_rsc_vz(rst_n && !pending && in_valid),.chn_a_rsc_lz(donor_in_ready),
        .chn_o_rsc_z(out_value),.chn_o_rsc_vz(rst_n && pending && out_ready),.chn_o_rsc_lz(donor_out_valid));
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin pending<=0;saved_tag<=0;end
        else begin
            if (in_valid && in_ready) begin pending<=1;saved_tag<=in_tag;end
            else if (out_valid && out_ready) pending<=0;
        end
    end
endmodule
