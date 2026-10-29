// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_whole_reset_invalid_v6 #(
  parameter logic [63:0] TIMEOUT_CYCLES=64'd0,
  parameter integer STABLE_SAMPLES=0
);
  logic sys_clk=1'b0;
  logic power_rst_n=1'b1;
  logic req_valid=1'b0;
  logic [603:0] req=604'd0;
  logic quiesce_ack=1'b0,quiescent=1'b0,reset_ready=1'b1;
  logic reset_asserted=1'b0,reset_complete=1'b0,reset_fault=1'b0;
  logic [7:0] reset_fault_code=8'd0;
  logic platform_ready=1'b0;
  wire req_ready,rsp_valid,quiesce_request,reset_request;
  wire [511:0] rsp_data;
  wire [7:0] rsp_status;
  wire [15:0] rsp_seq;

  rk_whole_reset_control #(
    .TIMEOUT_CYCLES(TIMEOUT_CYCLES),
    .STABLE_SAMPLES(STABLE_SAMPLES)
  ) dut (
    .sys_clk(sys_clk),.power_rst_n(power_rst_n),
    .req_valid(req_valid),.req_ready(req_ready),.req(req),
    .rsp_valid(rsp_valid),.rsp_data(rsp_data),.rsp_status(rsp_status),.rsp_seq(rsp_seq),
    .quiesce_request(quiesce_request),.quiesce_ack(quiesce_ack),.quiescent(quiescent),
    .reset_request(reset_request),.reset_ready(reset_ready),.reset_asserted(reset_asserted),
    .reset_complete(reset_complete),.reset_fault(reset_fault),
    .reset_fault_code(reset_fault_code),.platform_ready(platform_ready)
  );

  initial begin
    #1;
    if (req_ready || rsp_valid || quiesce_request || reset_request ||
        (|rsp_data) || (|rsp_status) || (|rsp_seq)) $display("outputs observed");
    $fatal(1,"INVALID_PARAMETER_ACCEPTED");
  end
endmodule
