// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// INTERNAL post-accumulation tail. Not a raw command port or a GEMM engine.
// Unmodified NVDLA conversion arithmetic via a one-inflight tag adapter.
// Converts once, retains address/last through the pipeline, then acknowledges
// memory writes. Shared upstream cancellation is sticky until joint reset.
module rk_cmac_output_nvdla #(
    parameter int unsigned TIMEOUT_CYCLES=65536
) (
    input logic clk,rst_n,
    input logic in_valid,
    output logic in_ready,
    input logic [31:0] in_value,in_address,
    input logic in_last,
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
    logic cvt_ready,cvt_valid,writer_ready,writer_busy,writer_ack,writer_done,writer_error;
    logic writer_req_valid,writer_rsp_ready;
    logic [15:0] converted;
    logic [32:0] converted_tag;
    logic [7:0] writer_code,saved_code,normalized_cancel_code;
    logic active,closing,fault_latched,accept,emit;
    logic [1:0] pending;
    // Public errors use the existing 1..8 family. Invalid/unknown upstream
    // fault codes are an internal-contract failure, never success or zero.
    always_comb begin
        case (cancel_code)
            1,2,3,4,5,6,7,8: normalized_cancel_code=cancel_code;
            default: normalized_cancel_code=6;
        endcase
    end
    assign error=rst_n && (fault_latched || writer_error || cancel);
    assign error_code=!rst_n ? 8'd0 : fault_latched ? saved_code : writer_error ? writer_code : cancel ? normalized_cancel_code : 8'd0;
    assign in_ready=!error && !closing && cvt_ready;
    assign accept=in_valid && in_ready;
    assign emit=cvt_valid && writer_ready && !error;
    // active spans input gaps, not only occupied stages. A final accepted
    // input closes this stream until its successful write acknowledgment.
    assign busy=rst_n && !error && ((active && !writer_done) || pending!=0 || writer_busy);
    assign acknowledged=writer_ack && !error;
    assign done=writer_done && !error;
    assign mem_req_valid=writer_req_valid && !error;
    assign mem_rsp_ready=writer_rsp_ready && !error;
    rk_nvdla_fp32_to_fp16 #(.TAG_WIDTH(33)) converter(
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid && !closing && !error),.in_ready(cvt_ready),
        .in_value(in_value),.in_tag({in_address,in_last}),.out_valid(cvt_valid),
        .out_ready(writer_ready && !error),.out_value(converted),.out_tag(converted_tag));
    rk_cmac_writer #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) writer(
        .clk(clk),.rst_n(rst_n),.result_valid(cvt_valid && !error),.result_ready(writer_ready),
        .result_address(converted_tag[32:1]),.result_data(converted),.result_last(converted_tag[0]),
        .busy(writer_busy),.acknowledged(writer_ack),.done(writer_done),.error(writer_error),.error_code(writer_code),
        .mem_req_valid(writer_req_valid),.mem_req_ready(mem_req_ready && !error),.mem_req_write(mem_req_write),
        .mem_req_addr(mem_req_addr),.mem_req_wdata(mem_req_wdata),.mem_rsp_valid(mem_rsp_valid && !error),
        .mem_rsp_ready(writer_rsp_ready),.mem_rsp_error(mem_rsp_error));
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active<=0;closing<=0;pending<=0;fault_latched<=0;saved_code<=0;
        end else begin
            if (!fault_latched && (writer_error || cancel)) begin
                fault_latched<=1;saved_code<=writer_error ? writer_code : normalized_cancel_code;
            end
            if (!error) begin
                case ({accept,emit})
                    2'b10: pending<=pending+1'b1;
                    2'b01: pending<=pending-1'b1;
                    default: begin end
                endcase
                if (writer_done) begin active<=0;closing<=0;end
                if (accept) begin
                    active<=1;
                    if (in_last) closing<=1;
                end
            end
        end
    end
endmodule
