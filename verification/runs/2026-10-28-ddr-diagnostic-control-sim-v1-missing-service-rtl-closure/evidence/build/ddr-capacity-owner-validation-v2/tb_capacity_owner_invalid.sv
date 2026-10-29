`timescale 1ns/1ps
module tb_capacity_owner_invalid #(
  parameter integer QUIET_CYCLES=2,
  parameter integer TIMEOUT_CYCLES=8
);
  logic clk;initial clk=0;always #5 clk=~clk;
  logic request_ready,normal_admission_enable,normal_selected,diagnostic_selected,diagnostic_reset_n,diagnostic_exclusive;
  logic diagnostic_start_valid;logic [31:0] diagnostic_seed;
  logic busy,done,fault;logic [7:0] fault_code;
  rk_ddr_capacity_owner #(.QUIET_CYCLES(QUIET_CYCLES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) dut(
    .clk(clk),.joint_rst_n(1'b0),.request_valid(1'b0),.request_ready(request_ready),.request_seed(32'b0),
    .initialization_complete(1'b1),.calibration_complete(1'b1),.platform_monitor_healthy(1'b1),
    .platform_monitor_fault(1'b0),.normal_fabric_quiet(1'b1),.normal_job_owned(1'b0),.normal_host_busy(1'b0),
    .normal_engine_pending(1'b0),.normal_pending_response(1'b0),.normal_unrouted_request(1'b0),
    .normal_admission_enable(normal_admission_enable),.normal_selected(normal_selected),
    .diagnostic_selected(diagnostic_selected),.diagnostic_reset_n(diagnostic_reset_n),
    .diagnostic_exclusive(diagnostic_exclusive),.diagnostic_start_valid(diagnostic_start_valid),
    .diagnostic_start_ready(1'b0),.diagnostic_seed(diagnostic_seed),.diagnostic_monitor_healthy(1'b0),
    .diagnostic_done(1'b0),.diagnostic_fault(1'b0),.busy(busy),.done(done),.fault(fault),.fault_code(fault_code),
    .bus_awvalid(2'b0),.bus_awready(2'b0),.bus_wvalid(2'b0),.bus_wready(2'b0),
    .bus_bvalid(2'b0),.bus_bready(2'b0),.bus_b_ok(2'b0),.bus_arvalid(2'b0),.bus_arready(2'b0),
    .bus_rvalid(2'b0),.bus_rready(2'b0),.bus_r_ok(2'b0));
  initial begin
    #1;
    if(request_ready||normal_admission_enable||normal_selected||diagnostic_selected||diagnostic_reset_n||
       diagnostic_exclusive||diagnostic_start_valid||diagnostic_seed!=0||busy||done||fault||fault_code!=0)
      $display("FAIL_INVALID_OWNER_PARAMETER_OUTPUTS_UNEXPECTED");
    $display("FAIL_OWNER_INVALID_PARAMETER_ACCEPTED");$fatal(1);
  end
endmodule
