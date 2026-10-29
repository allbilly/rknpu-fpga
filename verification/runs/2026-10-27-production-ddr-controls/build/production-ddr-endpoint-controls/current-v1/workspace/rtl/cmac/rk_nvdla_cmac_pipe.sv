// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Internal numerical pipeline. The enclosing engine supplies decoded raw
// operand groups; this is not an alternate host tensor-operation interface.
module rk_nvdla_cmac_pipe #(parameter int unsigned TIMEOUT_CYCLES=65536) (
    input logic clk,rst_n,in_valid,
    output logic in_ready,
    input logic [1023:0] in_data,in_weight,
    input logic [31:0] in_address,
    input logic in_first,in_last,in_last_output,
    input logic cancel,
    input logic [7:0] cancel_code,
    output logic busy,acknowledged,done,error,
    output logic [7:0] error_code,
    output logic mem_req_valid,
    input logic mem_req_ready,
    output logic mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input logic mem_rsp_valid,
    output logic mem_rsp_ready,
    input logic mem_rsp_error
);
    logic group_ready,group_valid,group_busy,group_error;
    logic accum_ready,accum_valid,accum_busy,accum_error;
    logic tail_ready,tail_busy,tail_error,tail_ack,tail_done,tail_req,tail_rsp;
    logic [43:0] group_value;
    logic [34:0] group_tag;
    logic [31:0] accum_value;
    logic [32:0] accum_tag;
    logic [7:0] group_code,accum_code,tail_code,saved_code,normalized_cancel;
    logic fault,active,closing,child_cancel;
    always @* begin
        case (cancel_code)
            1,2,3,4,5,6,7,8:normalized_cancel=cancel_code;
            default:normalized_cancel=6;
        endcase
    end
    // Cancellation distribution is acyclic: children see only the external
    // cancel or registered root fault. Aggregate errors gate every seam now.
    assign child_cancel=cancel||fault;
    assign error=rst_n&&(fault||cancel||group_error||accum_error||tail_error);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : cancel ? normalized_cancel :
                      group_error ? group_code : accum_error ? accum_code : tail_error ? tail_code : 8'd0;
    assign in_ready=group_ready&&!error&&!closing;
    assign busy=rst_n&&!error&&((active&&!tail_done)||group_busy||accum_busy||tail_busy);
    assign acknowledged=tail_ack&&!error;
    assign done=tail_done&&!error;
    assign mem_req_valid=tail_req&&!error;
    assign mem_rsp_ready=tail_rsp&&!error;
    rk_nvdla_cmac_group group_stage(
        .clk,.rst_n,.in_valid(in_valid&&!error&&!closing),.in_ready(group_ready),.in_data,.in_weight,
        .in_tag({in_address,in_last_output,in_first,in_last}),
        .out_valid(group_valid),.out_ready(accum_ready&&!error),.out_group(group_value),.out_tag(group_tag),
        .cancel(child_cancel),.cancel_code(fault ? saved_code : normalized_cancel),
        .busy(group_busy),.error(group_error),.error_code(group_code));
    rk_nvdla_cacc accumulator(
        .clk,.rst_n,.in_valid(group_valid&&!error),.in_ready(accum_ready),.in_group(group_value),
        .in_first(group_tag[1]),.in_last(group_tag[0]),.in_tag(group_tag[34:2]),
        .out_valid(accum_valid),.out_ready(tail_ready&&!error),.out_value(accum_value),.out_tag(accum_tag),
        .cancel(child_cancel),.cancel_code(fault ? saved_code : normalized_cancel),
        .busy(accum_busy),.error(accum_error),.error_code(accum_code));
    rk_cmac_output_nvdla #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) output_tail(
        .clk,.rst_n,.in_valid(accum_valid&&!error),.in_ready(tail_ready),
        .in_value(accum_value),.in_address(accum_tag[32:1]),.in_last(accum_tag[0]),
        .cancel(child_cancel),.cancel_code(fault ? saved_code : normalized_cancel),
        .busy(tail_busy),.acknowledged(tail_ack),.done(tail_done),.error(tail_error),.error_code(tail_code),
        .mem_req_valid(tail_req),.mem_req_ready(mem_req_ready&&!error),.mem_req_write,.mem_req_addr,.mem_req_wdata,
        .mem_rsp_valid(mem_rsp_valid&&!error),.mem_rsp_ready(tail_rsp),.mem_rsp_error);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin fault<=0;saved_code<=0;active<=0;closing<=0;end
        else begin
            if (!fault&&error) begin fault<=1;saved_code<=error_code;end
            if (!error) begin
                if (tail_done) begin active<=0;closing<=0;end
                if (in_valid&&in_ready) begin
                    active<=1;
                    if (in_last&&in_last_output) closing<=1;
                end
            end
        end
    end
endmodule
