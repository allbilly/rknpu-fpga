// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Internal CxK FP16 group formation followed by independent per-kernel
// FP48 accumulation and FP32 finalization. Raw-command/CSC integration and
// final FP16 conversion/write acknowledgments belong outside this module.
module rk_cmac_cacc_fp16_array #(
    parameter int unsigned ATOMIC_C=32,ATOMIC_K=16,TAG_WIDTH=33
) (
    input wire clk,rst_n,in_valid,
    output wire in_ready,
    input wire [ATOMIC_C*16-1:0] in_data,
    input wire [ATOMIC_K*ATOMIC_C*16-1:0] in_weight,
    input wire [ATOMIC_C-1:0] in_data_mask,
    input wire [ATOMIC_K*ATOMIC_C-1:0] in_weight_mask,
    input wire in_first,in_last,
    input wire [TAG_WIDTH-1:0] in_tag,
    output wire out_valid,
    input wire out_ready,
    output wire [ATOMIC_K*32-1:0] out_values,
    output wire [TAG_WIDTH-1:0] out_tag,
    input wire cancel,
    input wire [7:0] cancel_code,
    output wire busy,error,
    output wire [7:0] error_code
);
    wire group_ready,group_valid,group_error,bank_ready,bank_valid,bank_busy,bank_error;
    wire [ATOMIC_K*44-1:0] group_values;
    wire [TAG_WIDTH+1:0] group_tag;
    wire [7:0] bank_code;
    logic fault;
    logic [7:0] saved_code,normalized_cancel;
    always @* begin
        case(cancel_code)
            1,2,3,4,5,6,7,8:normalized_cancel=cancel_code;
            default:normalized_cancel=6;
        endcase
    end
    assign error=rst_n&&(fault||cancel||group_error||bank_error);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : cancel ? normalized_cancel :
                      group_error ? 8'd6 : bank_error ? bank_code : 8'd0;
    assign in_ready=group_ready&&!error;
    assign out_valid=bank_valid&&!error;
    assign busy=rst_n&&!error&&(group_valid||bank_busy);
    rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K),.TAG_WIDTH(TAG_WIDTH+2)) cmac(
        .clk,.rst_n,.in_valid(in_valid&&!error),.in_ready(group_ready),
        .in_data,.in_weight,.in_data_mask,.in_weight_mask,.in_tag({in_tag,in_first,in_last}),
        .out_valid(group_valid),.out_ready(bank_ready&&!error),.out_groups(group_values),
        .out_tag(group_tag),.error(group_error));
    rk_cacc_fp16_array #(.ATOMIC_K(ATOMIC_K),.TAG_WIDTH(TAG_WIDTH)) cacc(
        .clk,.rst_n,.in_valid(group_valid&&!error),.in_ready(bank_ready),.in_groups(group_values),
        .in_first(group_tag[1]),.in_last(group_tag[0]),.in_tag(group_tag[TAG_WIDTH+1:2]),
        .out_valid(bank_valid),.out_ready(out_ready&&!error),.out_values,.out_tag,
        .cancel(cancel||fault),.cancel_code(fault ? saved_code : normalized_cancel),
        .busy(bank_busy),.error(bank_error),.error_code(bank_code));
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin fault<=0;saved_code<=0;end
        else if(!fault&&error) begin fault<=1;saved_code<=error_code;end
    end
endmodule
