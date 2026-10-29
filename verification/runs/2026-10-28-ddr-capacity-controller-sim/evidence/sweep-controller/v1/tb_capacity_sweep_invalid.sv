`timescale 1ns/1ps
module tb_capacity_sweep_invalid #(
  parameter logic [30:0] TEST_BASE=0,
  parameter logic [31:0] TEST_SPAN=256,
  parameter integer TEST_TIMEOUT=20
);
  logic clk=0;always #5 clk=~clk;
  logic [30:0] line_address,retire_last_write_address,mismatch_address;
  logic [511:0] line_wdata,mismatch_expected,mismatch_actual;
  logic [31:0] completed_writes,completed_reads;
  logic [7:0] fault_code;
  logic start_ready,busy,done,fault,trial,line_valid,line_write,line_rsp_ready;
  logic retire_valid,retire_rsp_ready;
  rk_ddr_capacity_sweep #(.BASE_ADDR(TEST_BASE),.SPAN_BYTES(TEST_SPAN),.TIMEOUT_CYCLES(TEST_TIMEOUT)) dut(
    .clk(clk),.joint_rst_n(1'b0),.start_valid(1'b0),.start_ready(start_ready),.seed(32'b0),
    .initialization_complete(1'b1),.calibration_complete(1'b1),.ecc_monitor_healthy(1'b1),.owner_exclusive(1'b1),
    .busy(busy),.done(done),.fault(fault),.fault_code(fault_code),.trial(trial),
    .completed_writes(completed_writes),.completed_reads(completed_reads),.mismatch_address(mismatch_address),
    .mismatch_expected(mismatch_expected),.mismatch_actual(mismatch_actual),.line_valid(line_valid),.line_ready(1'b0),
    .line_write(line_write),.line_address(line_address),.line_wdata(line_wdata),.line_rsp_valid(1'b0),
    .line_rsp_ready(line_rsp_ready),.line_rsp_error(1'b0),.line_rdata(512'b0),.retire_valid(retire_valid),
    .retire_ready(1'b0),.retire_last_write_address(retire_last_write_address),.retire_rsp_valid(1'b0),
    .retire_rsp_ready(retire_rsp_ready),.retire_rsp_ok(1'b1),.retire_ecc_status(32'b0),
    .retire_ecc_onoff(32'd1),.retire_ecc_irq_mask(32'd3));
  initial begin #2;$display("FAIL_SWEEP_INVALID_PARAMETER_ACCEPTED");$fatal(1);end
endmodule
