`timescale 1ns/1ps
module tb_capacity_sweep_full_elab;
  function automatic logic [511:0] expected_zero_pattern;
    integer lane;
    logic [31:0] salt;
    begin
      for(lane=0;lane<16;lane=lane+1)begin
        salt=lane*32'h9e3779b9;
        expected_zero_pattern[lane*32 +:32]=salt;
      end
    end
  endfunction
  logic clk;initial clk=0;always #5 clk=~clk;
  logic rst_n=0;
  logic start_valid=0;
  logic [31:0] seed=0;
  logic line_ready=0,line_rsp_valid=0,line_rsp_error=0;
  logic [511:0] line_rdata='0;
  logic retire_ready=0,retire_rsp_valid=0,retire_rsp_ok=1;
  logic [31:0] retire_ecc_status=0,retire_ecc_onoff=1,retire_ecc_irq_mask=3;
  logic start_ready,busy,done,fault,trial,line_valid,line_write,line_rsp_ready;
  logic retire_valid,retire_rsp_ready;
  logic [7:0] fault_code;
  logic [31:0] completed_writes,completed_reads;
  logic [30:0] mismatch_address,line_address,retire_last_write_address;
  logic [511:0] mismatch_expected,mismatch_actual,line_wdata;
  rk_ddr_capacity_sweep dut(.clk(clk),.joint_rst_n(rst_n),.start_valid(start_valid),
    .start_ready(start_ready),.seed(seed),.initialization_complete(1'b1),.calibration_complete(1'b1),
    .ecc_monitor_healthy(1'b1),.owner_exclusive(1'b1),.busy(busy),.done(done),.fault(fault),
    .fault_code(fault_code),.trial(trial),.completed_writes(completed_writes),.completed_reads(completed_reads),
    .mismatch_address(mismatch_address),.mismatch_expected(mismatch_expected),.mismatch_actual(mismatch_actual),
    .line_valid(line_valid),.line_ready(line_ready),.line_write(line_write),.line_address(line_address),
    .line_wdata(line_wdata),.line_rsp_valid(line_rsp_valid),.line_rsp_ready(line_rsp_ready),
    .line_rsp_error(line_rsp_error),.line_rdata(line_rdata),.retire_valid(retire_valid),
    .retire_ready(retire_ready),.retire_last_write_address(retire_last_write_address),
    .retire_rsp_valid(retire_rsp_valid),.retire_rsp_ready(retire_rsp_ready),.retire_rsp_ok(retire_rsp_ok),
    .retire_ecc_status(retire_ecc_status),.retire_ecc_onoff(retire_ecc_onoff),.retire_ecc_irq_mask(retire_ecc_irq_mask));
  initial begin
    #20;rst_n=1;#1;
    if(dut.LAST_ADDR!==31'h7fffffc0 || start_ready!==1'b1 || line_address!==0 || fault!==0 ||
       busy!==1'b0 || done!==1'b0 || completed_writes!==0 || completed_reads!==0 ||
       line_valid!==1'b0 || line_write!==1'b1 || line_wdata!==expected_zero_pattern() || line_rsp_ready!==1'b0 ||
       retire_valid!==1'b0 || retire_rsp_ready!==1'b0 || retire_last_write_address!==0 ||
       fault_code!==0 || trial!==1'b0 || mismatch_address!==0 || mismatch_expected!==512'b0 || mismatch_actual!==512'b0)
      $fatal(1,"full-window parameter/boundary elaboration mismatch");
    $display("PASS_SWEEP_FULL_WINDOW_ELAB_ONLY last=%08x no_span_iteration=1",dut.LAST_ADDR);
    $finish;
  end
endmodule
