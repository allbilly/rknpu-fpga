// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Internal C32/K16 arithmetic-to-memory path. The future raw-command CSC
// supplies physical operand frames and output atom addresses; this module
// deliberately has no alternate host/tensor execution interface.
module rk_cmac_array_datapath #(parameter int unsigned TIMEOUT_CYCLES=65536) (
    input wire clk,rst_n,in_valid,
    output wire in_ready,
    input wire [511:0] in_data,
    input wire [8191:0] in_weight,
    input wire [31:0] in_data_mask,
    input wire [511:0] in_weight_mask,
    input wire in_first,in_last,in_last_frame,
    input wire [31:0] in_output_address,
    input wire cancel,
    input wire [7:0] cancel_code,
    output wire busy,acknowledged,frame_done,done,error,
    output wire [7:0] error_code,
    output wire mem_req_valid,
    input wire mem_req_ready,
    output wire mem_req_write,
    output wire [31:0] mem_req_addr,
    output wire [15:0] mem_req_wdata,
    input wire mem_rsp_valid,
    output wire mem_rsp_ready,
    input wire mem_rsp_error
);
    wire arithmetic_ready,arithmetic_valid,arithmetic_busy,arithmetic_error;
    wire writer_ready,writer_busy,writer_ack,writer_frame_done,writer_done,writer_error,writer_req,writer_rsp;
    wire [511:0] result_values;
    wire [32:0] result_tag;
    wire [7:0] arithmetic_code,writer_code;
    logic active,closing,fault;
    logic [7:0] saved_code,normalized_cancel;
    wire child_cancel=cancel||fault;
    always @* begin
        case(cancel_code)
            1,2,3,4,5,6,7,8:normalized_cancel=cancel_code;
            default:normalized_cancel=6;
        endcase
    end
    assign error=rst_n&&(fault||cancel||arithmetic_error||writer_error);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : cancel ? normalized_cancel :
                      arithmetic_error ? arithmetic_code : writer_error ? writer_code : 8'd0;
    assign in_ready=arithmetic_ready&&!error&&!closing;
    assign busy=rst_n&&!error&&((active&&!writer_done)||arithmetic_busy||writer_busy);
    assign acknowledged=writer_ack&&!error;
    assign frame_done=writer_frame_done&&!error;
    assign done=writer_done&&!error;
    assign mem_req_valid=writer_req&&!error;
    assign mem_rsp_ready=writer_rsp&&!error;
    rk_cmac_cacc_fp16_array arithmetic(
        .clk,.rst_n,.in_valid(in_valid&&!error&&!closing),.in_ready(arithmetic_ready),
        .in_data,.in_weight,.in_data_mask,.in_weight_mask,.in_first,.in_last,
        .in_tag({in_output_address,in_last_frame}),.out_valid(arithmetic_valid),
        .out_ready(writer_ready&&!error),.out_values(result_values),.out_tag(result_tag),
        .cancel(child_cancel),.cancel_code(fault ? saved_code : normalized_cancel),
        .busy(arithmetic_busy),.error(arithmetic_error),.error_code(arithmetic_code));
    rk_cmac_frame_output #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) writer(
        .clk,.rst_n,.in_valid(arithmetic_valid&&!error),.in_ready(writer_ready),
        .in_values(result_values),.in_address(result_tag[32:1]),.in_last(result_tag[0]),
        .cancel(child_cancel),.cancel_code(fault ? saved_code : normalized_cancel),
        .busy(writer_busy),.acknowledged(writer_ack),.frame_done(writer_frame_done),.done(writer_done),
        .error(writer_error),.error_code(writer_code),
        .mem_req_valid(writer_req),.mem_req_ready(mem_req_ready&&!error),.mem_req_write,.mem_req_addr,.mem_req_wdata,
        .mem_rsp_valid(mem_rsp_valid&&!error),.mem_rsp_ready(writer_rsp),.mem_rsp_error);
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin active<=0;closing<=0;fault<=0;saved_code<=0;end
        else begin
            if(!fault&&error) begin fault<=1;saved_code<=error_code;end
            if(!error) begin
                if(writer_done) begin active<=0;closing<=0;end
                if(in_valid&&in_ready) begin active<=1;if(in_last&&in_last_frame) closing<=1;end
            end
        end
    end
endmodule
