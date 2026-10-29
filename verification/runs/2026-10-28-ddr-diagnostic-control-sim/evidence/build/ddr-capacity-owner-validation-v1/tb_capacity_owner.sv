`timescale 1ns/1ps
module tb_capacity_owner #(
  parameter integer QUIET_CYCLES=2,
  parameter integer TIMEOUT_CYCLES=8
);
  logic clk;initial clk=0;always #5 clk=~clk;
  logic joint_rst_n,request_valid,request_ready;logic [31:0] request_seed;
  logic initialization_complete,calibration_complete,platform_monitor_healthy,platform_monitor_fault;
  logic normal_fabric_quiet,normal_job_owned,normal_host_busy,normal_engine_pending,normal_pending_response,normal_unrouted_request;
  logic normal_admission_enable,normal_selected,diagnostic_selected,diagnostic_reset_n,diagnostic_exclusive;
  logic diagnostic_start_valid,diagnostic_start_ready;logic [31:0] diagnostic_seed;
  logic diagnostic_monitor_healthy,diagnostic_done,diagnostic_fault;
  logic busy,done,fault;logic [7:0] fault_code;
  logic [1:0] bus_awvalid,bus_awready,bus_wvalid,bus_wready,bus_bvalid,bus_bready,bus_b_ok;
  logic [1:0] bus_arvalid,bus_arready,bus_rvalid,bus_rready,bus_r_ok;

  rk_ddr_capacity_owner #(.QUIET_CYCLES(QUIET_CYCLES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) dut(.*);

  task automatic fail(input string message);
    $display("FAIL_OWNER %s",message);$fatal(1);
  endtask
  task automatic reset_owner;
    begin
      @(negedge clk);joint_rst_n=0;request_valid=0;request_seed=0;
      initialization_complete=1;calibration_complete=1;platform_monitor_healthy=1;platform_monitor_fault=0;
      normal_fabric_quiet=1;normal_job_owned=0;normal_host_busy=0;normal_engine_pending=0;
      normal_pending_response=0;normal_unrouted_request=0;
      diagnostic_start_ready=0;diagnostic_monitor_healthy=0;diagnostic_done=0;diagnostic_fault=0;
      bus_awvalid=0;bus_awready=0;bus_wvalid=0;bus_wready=0;bus_bvalid=0;bus_bready=0;bus_b_ok=0;
      bus_arvalid=0;bus_arready=0;bus_rvalid=0;bus_rready=0;bus_r_ok=0;
      repeat(2)@(posedge clk);@(negedge clk);joint_rst_n=1;#1;
      if(request_ready!==1 || normal_selected!==1 || diagnostic_selected!==0 || diagnostic_reset_n!==0 ||
         diagnostic_exclusive!==0 || normal_admission_enable!==1 || fault!==0 || done!==0)
        fail("joint reset did not restore normal ownership safely");
    end
  endtask
  task automatic pulse_request(input logic [31:0] seed_value);
    begin
      @(negedge clk);request_seed=seed_value;request_valid=1;
      if(request_ready!==1)fail("request not ready in normal owner state");
      if(normal_admission_enable!==0)fail("new normal admission was not blocked while request valid");
      @(posedge clk);#1;
      if(request_ready!==0 || normal_selected!==1 || diagnostic_selected!==0)
        fail("ownership changed before quiet drain");
      @(negedge clk);request_valid=0;request_seed=~seed_value;
      if(normal_admission_enable!==0)fail("normal admission re-enabled during quiesce");
    end
  endtask
  task automatic lane_aw(input logic [1:0] valid_value,input logic [1:0] ready_value);
    begin @(negedge clk);bus_awvalid=valid_value;bus_awready=ready_value;@(posedge clk);#1;@(negedge clk);bus_awvalid=0;bus_awready=0;end
  endtask
  task automatic lane_w(input logic [1:0] valid_value,input logic [1:0] ready_value);
    begin @(negedge clk);bus_wvalid=valid_value;bus_wready=ready_value;@(posedge clk);#1;@(negedge clk);bus_wvalid=0;bus_wready=0;end
  endtask
  task automatic lane_b(input logic [1:0] valid_value,input logic [1:0] ready_value,input logic [1:0] ok_value);
    begin @(negedge clk);bus_bvalid=valid_value;bus_bready=ready_value;bus_b_ok=ok_value;@(posedge clk);#1;@(negedge clk);bus_bvalid=0;bus_bready=0;bus_b_ok=0;end
  endtask
  task automatic lane_ar(input logic [1:0] valid_value,input logic [1:0] ready_value);
    begin @(negedge clk);bus_arvalid=valid_value;bus_arready=ready_value;@(posedge clk);#1;@(negedge clk);bus_arvalid=0;bus_arready=0;end
  endtask
  task automatic lane_r(input logic [1:0] valid_value,input logic [1:0] ready_value,input logic [1:0] ok_value);
    begin @(negedge clk);bus_rvalid=valid_value;bus_rready=ready_value;bus_r_ok=ok_value;@(posedge clk);#1;@(negedge clk);bus_rvalid=0;bus_rready=0;bus_r_ok=0;end
  endtask
  task automatic wait_diag_selected;
    integer n;begin n=0;while(!diagnostic_selected&&n<20)begin @(posedge clk);#1;n=n+1;end
      if(diagnostic_selected!==1)fail("diagnostic ownership did not follow quiet interval");end
  endtask
  task automatic wait_fault(input logic [7:0] expected_code);
    integer n;begin n=0;while(!fault&&n<40)begin @(posedge clk);#1;n=n+1;end
      if(fault!==1 || fault_code!==expected_code)fail($sformatf("fault=%b code=%0d expected=%0d",fault,fault_code,expected_code));end
  endtask
  task automatic check_quarantine_sticky;
    begin
      if(diagnostic_selected!==1 || normal_selected!==0 || diagnostic_reset_n!==1 || diagnostic_exclusive!==1 ||
         done!==0 || normal_admission_enable!==0)
        fail("fault changed or released sticky diagnostic ownership");
    end
  endtask
  task automatic trigger_invalid_seed;
    begin
      reset_owner();@(negedge clk);request_seed=32'hxxxxxxxx;request_valid=1;
      @(posedge clk);#1;request_valid=0;wait_fault(1);
      if(normal_selected!==1 || diagnostic_selected!==0 || diagnostic_start_valid!==0)
        fail("invalid start seed changed selector or launched diagnostic");
    end
  endtask
  task automatic trigger_health_start_fault(input integer which);
    begin
      reset_owner();
      case(which)
        0:initialization_complete=0;
        1:calibration_complete=0;
        2:platform_monitor_healthy=0;
        3:platform_monitor_fault=1;
        default:fail("bad health selector");
      endcase
      pulse_request(32'h3588c350);wait_fault(1);
      if(normal_selected!==1 || diagnostic_selected!==0)fail("preownership health fault changed selector");
    end
  endtask
  task automatic prepare_diag_owner;
    begin reset_owner();pulse_request(32'h3588c350);normal_fabric_quiet=1;wait_diag_selected();end
  endtask

  initial begin : test
    integer i,n;
    joint_rst_n=0;request_valid=0;request_seed=0;initialization_complete=1;calibration_complete=1;
    platform_monitor_healthy=1;platform_monitor_fault=0;normal_fabric_quiet=1;normal_job_owned=0;normal_host_busy=0;
    normal_engine_pending=0;normal_pending_response=0;normal_unrouted_request=0;diagnostic_start_ready=0;
    diagnostic_monitor_healthy=0;diagnostic_done=0;diagnostic_fault=0;
    bus_awvalid=0;bus_awready=0;bus_wvalid=0;bus_wready=0;bus_bvalid=0;bus_bready=0;bus_b_ok=0;
    bus_arvalid=0;bus_arready=0;bus_rvalid=0;bus_rready=0;bus_r_ok=0;

    // Two lanes perform concurrent, independent writes and reads while normal remains selected.
    reset_owner();normal_fabric_quiet=0;normal_job_owned=1;normal_host_busy=1;normal_engine_pending=1;normal_pending_response=1;
    lane_aw(2'b01,2'b01);lane_w(2'b10,2'b10);lane_w(2'b01,2'b01);lane_aw(2'b10,2'b10);
    lane_b(2'b11,2'b11,2'b11);lane_ar(2'b11,2'b11);pulse_request(32'h3588c350);
    repeat(3)begin @(posedge clk);#1;if(normal_selected!==1 || diagnostic_selected!==0)fail("normal owner changed before drain");end
    lane_r(2'b11,2'b11,2'b11);
    normal_job_owned=0;normal_host_busy=0;normal_engine_pending=0;normal_pending_response=0;normal_fabric_quiet=1;
    @(posedge clk);#1;if(diagnostic_selected!==0)fail("diagnostic selected after only one quiet sample");
    // A new, stalled normal request interrupts the quiet streak and must be observed.
    @(negedge clk);bus_awvalid=2'b01;bus_awready=2'b00;@(posedge clk);#1;@(negedge clk);bus_awvalid=0;
    if(diagnostic_selected!==0)fail("diagnostic selected through a nonquiet valid");
    @(posedge clk);#1;if(diagnostic_selected!==0)fail("diagnostic did not restart two-cycle quiet count");
    @(posedge clk);#1;if(diagnostic_selected!==1 || normal_selected!==0 || !diagnostic_exclusive || !diagnostic_reset_n)
      fail("two consecutive quiet samples did not latch diagnostic owner");
    if(diagnostic_seed!==32'h3588c350)fail("request seed was not captured");
    if(diagnostic_start_valid!==0)fail("start offered before diagnostic monitor healthy");
    diagnostic_monitor_healthy=1;
    @(posedge clk);#1;if(diagnostic_start_valid!==1 || diagnostic_seed!==32'h3588c350)fail("held start handshake missing/captured seed changed");
    repeat(3)begin @(posedge clk);#1;if(diagnostic_start_valid!==1 || diagnostic_seed!==32'h3588c350)fail("start valid/seed not held across READY stall");end
    diagnostic_start_ready=1;@(posedge clk);#1;diagnostic_start_ready=0;
    if(diagnostic_start_valid!==0 || !busy)fail("start handshake did not enter RUN");
    // There is intentionally no global timeout in RUN.
    repeat(TIMEOUT_CYCLES*3)begin @(posedge clk);#1;if(fault || done || !diagnostic_selected)fail("RUN incorrectly timed out or relinquished owner");end
    diagnostic_done=1;@(posedge clk);#1;
    if(done!==1 || fault!==0 || normal_selected!==0 || diagnostic_selected!==1 || !diagnostic_reset_n || !diagnostic_exclusive)
      fail("diagnostic completion released ownership or failed done gating");
    $display("PASS_OWNER_QUIET_DRAIN_HELD_START_STICKY_DONE");

    // Timed quiesce, monitor wait, and launch failures are distinct fault 3 paths.
    reset_owner();normal_job_owned=1;pulse_request(32'h3588c350);repeat(TIMEOUT_CYCLES+3)@(posedge clk);#1;wait_fault(3);
    if(normal_selected!==1 || diagnostic_selected!==0)fail("quiesce timeout changed selector");
    prepare_diag_owner();repeat(TIMEOUT_CYCLES+3)@(posedge clk);#1;wait_fault(3);check_quarantine_sticky();
    prepare_diag_owner();diagnostic_monitor_healthy=1;repeat(2)@(posedge clk);#1;
    if(diagnostic_start_valid!==1)fail("launch-timeout setup did not assert start");
    repeat(TIMEOUT_CYCLES+3)@(posedge clk);#1;wait_fault(3);check_quarantine_sticky();
    if(diagnostic_start_valid!==1 || diagnostic_seed!==32'h3588c350)fail("fault withdrew held start/seed");
    diagnostic_start_ready=1;@(posedge clk);#1;diagnostic_start_ready=0;
    if(diagnostic_start_valid!==0 || !fault)fail("held start did not late-drain after timeout");
    $display("PASS_OWNER_BOUNDED_PRE_RUN_TIMEOUTS");

    // Code 1 health and code 4 logical ownership failures.
    for(i=0;i<4;i=i+1)trigger_health_start_fault(i);
    prepare_diag_owner();diagnostic_monitor_healthy=1;@(posedge clk);#1;normal_job_owned=1;@(posedge clk);#1;wait_fault(4);check_quarantine_sticky();
    prepare_diag_owner();diagnostic_monitor_healthy=1;@(posedge clk);#1;normal_unrouted_request=1;@(posedge clk);#1;wait_fault(4);check_quarantine_sticky();
    $display("PASS_OWNER_HEALTH_AND_LOGICAL_QUIET_FAULTS");

    // Code 5 diagnostic fault, unhealthy monitor/RUN, early done, and done with physical work pending.
    prepare_diag_owner();diagnostic_fault=1;@(posedge clk);#1;wait_fault(5);check_quarantine_sticky();
    prepare_diag_owner();diagnostic_done=1;@(posedge clk);#1;wait_fault(5);check_quarantine_sticky();
    prepare_diag_owner();diagnostic_monitor_healthy=1;@(posedge clk);#1;diagnostic_start_ready=1;@(posedge clk);#1;diagnostic_start_ready=0;
    diagnostic_monitor_healthy=0;@(posedge clk);#1;wait_fault(5);check_quarantine_sticky();
    prepare_diag_owner();diagnostic_monitor_healthy=1;@(posedge clk);#1;diagnostic_start_ready=1;@(posedge clk);#1;diagnostic_start_ready=0;
    bus_awvalid=2'b01;bus_awready=0;diagnostic_done=1;@(posedge clk);#1;wait_fault(5);check_quarantine_sticky();
    prepare_diag_owner();diagnostic_monitor_healthy=1;@(posedge clk);#1;diagnostic_start_ready=1;@(posedge clk);#1;diagnostic_start_ready=0;
    @(negedge clk);diagnostic_done=1;platform_monitor_healthy=0;@(posedge clk);#1;wait_fault(1);
    if(done!==0 || fault_code!==1)fail("same-edge health loss did not take precedence over done");check_quarantine_sticky();
    $display("PASS_OWNER_DIAGNOSTIC_FAULT_PRIORITY");

    // Duplicate/premature/unsolicited handshakes and failed response witnesses fault 2.
    reset_owner();lane_aw(2'b01,2'b01);lane_aw(2'b01,2'b01);wait_fault(2);
    if(aw_seen[0]!==1)fail("duplicate AW fault did not retain pending write");
    lane_w(2'b01,2'b01);lane_b(2'b01,2'b01,2'b01);
    if(aw_seen[0]!==0 || w_seen[0]!==0 || diagnostic_selected!==0 || normal_selected!==1 || !fault)
      fail("late B did not drain quarantined write while selector remained normal");
    reset_owner();lane_w(2'b10,2'b10);lane_w(2'b10,2'b10);wait_fault(2);
    reset_owner();lane_ar(2'b01,2'b01);lane_ar(2'b01,2'b01);wait_fault(2);lane_r(2'b01,2'b01,2'b01);
    reset_owner();lane_b(2'b01,2'b01,2'b01);wait_fault(2);
    reset_owner();lane_r(2'b10,2'b10,2'b10);wait_fault(2);
    reset_owner();lane_aw(2'b01,2'b01);lane_b(2'b01,2'b01,2'b01);wait_fault(2); // B before W
    reset_owner();lane_aw(2'b01,2'b01);lane_w(2'b01,2'b01);lane_b(2'b01,2'b01,2'b00);wait_fault(2);
    reset_owner();lane_ar(2'b01,2'b01);lane_r(2'b01,2'b01,2'b00);wait_fault(2);
    reset_owner();
    @(negedge clk);bus_awvalid=2'b01;bus_awready=2'b01;bus_arvalid=2'b01;bus_arready=2'b01;
    @(posedge clk);#1;wait_fault(2);
    $display("PASS_OWNER_PROTOCOL_FAULTS_AND_LATE_DRAIN");

    // Four-state-only invalid request seed and bus-valid observations are rejected.
`ifndef VERILATOR
    reset_owner();@(negedge clk);request_valid=1;request_seed=32'hxxxxxxxx;@(posedge clk);#1;wait_fault(1);
    reset_owner();@(negedge clk);bus_awvalid=2'bx0;@(posedge clk);#1;wait_fault(2);
    reset_owner();@(negedge clk);bus_bvalid=2'bx0;@(posedge clk);#1;wait_fault(2);
    $display("PASS_OWNER_UNKNOWN_INPUTS_FOUR_STATE");
`else
    $display("PASS_OWNER_UNKNOWN_INPUTS=NOT_APPLICABLE_TWO_STATE");
`endif

    // Only whole-domain reset returns selection and admission to NORMAL.
    reset_owner();
    $display("PASS_OWNER_LEAF_CASES=PASS");$finish;
  end
endmodule
