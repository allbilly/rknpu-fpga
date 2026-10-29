// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Standalone maintenance-control protocol test. No tensor, MIG/PHY, transport,
// TAP or board shell is instantiated; external reset witnesses are controlled here.
module tb_whole_reset_control;
  localparam logic [63:0] TEST_TIMEOUT=64'd64;
  localparam integer TEST_STABLE_SAMPLES=2;
  localparam logic [31:0] MAGIC=32'h4f54504a;
  localparam logic [31:0] START_KEY=32'h53545254;
  localparam logic [31:0] CANCEL_KEY=32'h43414e43;
  localparam logic [31:0] ACK_KEY=32'h41434b21;
`ifdef __ICARUS__
  localparam integer X_TESTS=1;
`else
  localparam integer X_TESTS=0;
`endif
  logic sys_clk,power_rst_n;
  always #5 sys_clk=~sys_clk;
  logic req_valid=0;
  wire req_ready;
  logic [603:0] req=0;
  wire rsp_valid;
  wire [511:0] rsp_data;
  wire [7:0] rsp_status;
  wire [15:0] rsp_seq;
  wire quiesce_request,reset_request;
  logic quiesce_ack=0,quiescent=0,reset_ready=1,reset_asserted=0;
  logic reset_complete=1,reset_fault=0;
  logic [7:0] reset_fault_code=0;
  logic platform_ready=1;
  integer checks=0,reset_request_edges;
  logic [15:0] seq=0;
  rk_whole_reset_control #(.TIMEOUT_CYCLES(TEST_TIMEOUT),.STABLE_SAMPLES(TEST_STABLE_SAMPLES)) dut(
    .sys_clk(sys_clk),.power_rst_n(power_rst_n),.req_valid(req_valid),.req_ready(req_ready),.req(req),
    .rsp_valid(rsp_valid),.rsp_data(rsp_data),.rsp_status(rsp_status),.rsp_seq(rsp_seq),
    .quiesce_request(quiesce_request),.quiesce_ack(quiesce_ack),.quiescent(quiescent),
    .reset_request(reset_request),.reset_ready(reset_ready),.reset_asserted(reset_asserted),
    .reset_complete(reset_complete),.reset_fault(reset_fault),.reset_fault_code(reset_fault_code),
    .platform_ready(platform_ready));
  always @(posedge sys_clk) begin
    if(reset_request===1'b1)reset_request_edges<=reset_request_edges+1;
  end
  task automatic check(input logic ok,input string label);
    begin
      checks=checks+1;
      if(ok!==1'b1)$fatal(1,"CHECK_FAILED %s checks=%0d",label,checks);
    end
  endtask
  task automatic tick(input integer count);
    begin repeat(count)begin @(posedge sys_clk);#1;end end
  endtask
  task automatic next_seq(output logic [15:0] value);
    begin seq=seq+16'd1;value=seq;end
  endtask
  task automatic send_frame(input logic [7:0] op,input logic [31:0] addr,
      input logic [511:0] data,input logic [3:0] strobes,input logic [31:0] magic,
      input logic [7:0] wanted_status,input logic [511:0] wanted_data,input string label);
    logic [15:0] frame_seq;
    begin
      next_seq(frame_seq);
      @(negedge sys_clk);
      check(req_ready===1'b1,label);
      req={magic,frame_seq,op,strobes,addr,data};req_valid=1;
      @(posedge sys_clk);#1;
      check(rsp_valid===1'b1,label);
      check(rsp_seq===frame_seq,label);
      check(rsp_status===wanted_status,label);
      check(rsp_data===wanted_data,label);
      @(negedge sys_clk);req_valid=0;req='0;
      @(posedge sys_clk);#1;
    end
  endtask
  task automatic read32(input logic [31:0] addr,input logic [31:0] expected,input string label);
    begin send_frame(8'd1,addr,512'd0,4'hf,MAGIC,8'd0,{480'd0,expected},label);end
  endtask
  task automatic write32(input logic [31:0] addr,input logic [31:0] value,
                         input logic [7:0] expected_status,input string label);
    begin send_frame(8'd2,addr,{480'd0,value},4'hf,MAGIC,expected_status,512'd0,label);end
  endtask
  task automatic start_request(input logic [7:0] expected_status);
    begin write32(32'h0c,START_KEY,expected_status,"START");end
  endtask
  task automatic cancel_request(input logic [7:0] expected_status);
    begin write32(32'h0c,CANCEL_KEY,expected_status,"CANCEL");end
  endtask
  task automatic ack_result(input logic [7:0] expected_status);
    begin write32(32'h0c,ACK_KEY,expected_status,"ACK");end
  endtask
  task automatic wait_for_state(input logic [2:0] state_value,input integer max_cycles,input string label);
    integer n;
    begin
      n=0;
      while(dut.state!==state_value&&n<max_cycles)begin tick(1);n=n+1;end
      check(dut.state===state_value,label);
    end
  endtask
  task automatic wait_reset_request(input integer max_cycles);
    integer n;
    begin
      n=0;
      while(reset_request!==1'b1&&n<max_cycles)begin tick(1);n=n+1;end
      check(reset_request===1'b1,"reset request reached coordinator");
    end
  endtask
  task automatic finish_reset_success;
    integer before_count;
    begin
      before_count=reset_request_edges;
      start_request(8'd0);
      check(quiesce_request===1'b1&&reset_request===1'b0,"success scenario START enters drain phase");
      quiesce_ack=1;quiescent=1;reset_ready=1;
      tick(1);
      check(reset_request===1'b1,"quiescence sample reaches request threshold");
      check(reset_request_edges==before_count,"reset is not accepted early");
      tick(1);
      check(dut.state===3'd2,"coordinator request advances to WAIT_ASSERT");
      check(reset_request_edges==before_count+1,"exactly one coordinator reset request edge");
      check(dut.reset_sent===1'b1,"request fire is recorded");
      reset_ready=0;reset_asserted=0;reset_complete=1;platform_ready=1;
      tick(4);
      check(dut.state===3'd2&&dut.assertion_seen===1'b0&&dut.success_epoch==0,
            "stale COMPLETE/READY cannot acknowledge without assertion and low witnesses");
      reset_asserted=1;reset_complete=0;platform_ready=0;
      tick(1);
      check(dut.state===3'd3&&dut.assertion_seen===1'b1,"fresh asserted and low reset witnesses accepted");
      reset_asserted=0;reset_complete=1;platform_ready=0;
      tick(1);
      check(dut.state===3'd4,"fresh completion enters WAIT_READY");
      platform_ready=1;
      tick(1);
      check(dut.state===3'd4&&dut.success_epoch==0,"first READY sample is not enough");
      tick(1);
      check(dut.state===3'd5&&dut.success_epoch==1,"second fresh READY sample completes epoch");
      read32(32'h08,32'h00000bf4,"success status held result");
      read32(32'h14,32'd1,"success epoch increment once");
      read32(32'h18,32'd0,"success error clear");
      read32(32'h20,32'd4,"success phase");
      check(quiesce_request===1'b1,"success result retains drain barrier until ACK");
      reset_fault=1;reset_fault_code=8'd1;tick(1);
      read32(32'h18,32'd0,"late fault leaves successful result code cached");
      read32(32'h14,32'd1,"late fault leaves completed epoch cached");
      ack_result(8'd0);
      check(dut.state===3'd0&&quiesce_request===1'b0,"ACK releases control barrier only");
      check(reset_request_edges==before_count+1&&reset_request===1'b0,"ACK does not initiate another reset");
      reset_fault=0;reset_fault_code=0;
      quiesce_ack=0;quiescent=0;reset_ready=1;reset_asserted=0;reset_complete=0;platform_ready=1;
    end
  endtask
  task automatic finish_cancelled_request;
    integer before_count;
    begin
      before_count=reset_request_edges;
      start_request(8'd0);
      check(quiesce_request===1'b1&&reset_request===1'b0,"START closes admission before reset request");
      cancel_request(8'd0);
      check(dut.state===3'd5&&dut.reset_sent===1'b0&&dut.saved_error==8'd2,
            "pre-fire CANCEL returns interrupted result without request");
      check(quiesce_request===1'b0&&reset_request_edges==before_count,"pre-fire CANCEL makes no reset request");
      start_request(8'd2);
      check(dut.state===3'd5&&quiesce_request===1'b0,
            "held CANCEL result blocks a new START until ACK");
      ack_result(8'd0);
      check(dut.state===3'd0&&reset_request_edges==before_count,"ACK after pre-fire CANCEL is not reset");
    end
  endtask
  task automatic cancel_on_exact_fire_edge;
    logic [15:0] frame_seq;
    integer before_count;
    begin
      before_count=reset_request_edges;
      start_request(8'd0);quiesce_ack=1;quiescent=1;
      tick(1);check(reset_request===1'b1,"exact-fire setup reaches reset-request window");
      next_seq(frame_seq);
      @(negedge sys_clk);req={MAGIC,frame_seq,8'd2,4'hf,32'h0c,{480'd0,CANCEL_KEY}};req_valid=1;
      #1;check(reset_request===1'b0,"same-edge CANCEL wins before external reset fire");
      @(posedge sys_clk);#1;
      check(rsp_valid===1'b1&&rsp_seq===frame_seq&&rsp_status===0&&rsp_data===0,
            "same-edge CANCEL receives accepted response");
      check(dut.state===3'd5&&dut.reset_sent===1'b0&&reset_request_edges==before_count,
            "same-edge CANCEL prevents coordinator request");
      @(negedge sys_clk);req_valid=0;req='0;@(posedge sys_clk);#1;
      start_request(8'd2);
      ack_result(8'd0);quiesce_ack=0;quiescent=0;
      check(dut.state===3'd0&&reset_request_edges==before_count,"same-edge CANCEL result ACK does not reset");
    end
  endtask
  task automatic after_fire_timeout_and_ack_rules;
    integer before_count;
    logic [31:0] before_epoch;
    begin
      before_count=reset_request_edges;
      before_epoch=dut.success_epoch;
      reset_complete=1;platform_ready=1;reset_asserted=0;
      start_request(8'd0);quiesce_ack=1;quiescent=1;reset_ready=1;
      wait_reset_request(6);tick(1);
      check(dut.state===3'd2&&dut.reset_sent===1'b1&&reset_request_edges==before_count+1,
            "post-fire timeout case records exactly one reset request");
      // COMPLETE/READY retained from before this operation cannot prove a
      // newly issued reset, especially when no assertion was ever observed.
      reset_ready=0;reset_asserted=0;reset_complete=1;platform_ready=1;
      tick(80);
      check(dut.state===3'd5&&dut.saved_error==8'd1&&dut.saved_phase==3'd2&&
            dut.reset_sent===1'b1&&quiesce_request===1'b1,
            "post-fire timeout retains request barrier and reports WAIT_ASSERT timeout");
      cancel_request(8'd2);
      ack_result(8'd2);
      check(quiesce_request===1'b1&&reset_request_edges==before_count+1,
            "post-fire failure cannot CANCEL or ACK from stale COMPLETE/READY");
      check(dut.success_epoch===before_epoch&&dut.saved_error==8'd1&&dut.saved_phase==3'd2,
            "stale terminal levels retain the original failed result");
      reset_asserted=1;reset_complete=0;platform_ready=0;tick(1);
      check(quiesce_request===1'b1&&dut.success_epoch===before_epoch,
            "fresh assertion and low witnesses do not upgrade the held failure");
      reset_asserted=0;reset_complete=1;platform_ready=0;tick(1);
      platform_ready=1;tick(TEST_STABLE_SAMPLES);
      check(dut.state===3'd5&&dut.saved_error==8'd1&&dut.success_epoch===before_epoch,
            "fresh completion and READY permit release without changing failure or epoch");
      ack_result(8'd0);
      check(dut.state===3'd0&&dut.saved_error==8'd1&&dut.success_epoch===before_epoch&&
            reset_request_edges==before_count+1,
            "freshly completed reset ACK releases the same failed result exactly once");
      quiesce_ack=0;quiescent=0;reset_ready=1;reset_asserted=0;reset_complete=0;platform_ready=0;
    end
  endtask
  task automatic stale_fault_requires_fresh_terminal_fault;
    integer before_count;
    logic [31:0] before_epoch;
    begin
      before_count=reset_request_edges;
      before_epoch=dut.success_epoch;
      reset_fault=1;reset_fault_code=8'd2;
      start_request(8'd0);quiesce_ack=1;quiescent=1;reset_ready=1;
      wait_reset_request(6);tick(1);
      reset_ready=0;reset_asserted=0;reset_complete=0;platform_ready=0;tick(80);
      check(dut.state===3'd5&&dut.saved_error==8'd1&&dut.saved_phase==3'd2&&
            dut.saved_sequence_code==0&&
            dut.reset_sent===1'b1&&reset_request_edges==before_count+1,
            "preexisting high fault does not replace timeout with a fresh terminal fault");
      ack_result(8'd2);
      check(quiesce_request===1'b1&&dut.success_epoch===before_epoch,
            "preexisting high fault cannot qualify terminal ACK");
      reset_fault=0;reset_fault_code=0;tick(1);
      reset_fault=1;reset_fault_code=8'd3;tick(1);
      reset_fault=1;reset_fault_code=8'd0;tick(1);
      ack_result(8'd2);
      check(quiesce_request===1'b1&&dut.saved_error==8'd1,
            "zero code cannot reuse a previously valid high fault witness");
      reset_fault=1;reset_fault_code=8'd8;tick(1);
      ack_result(8'd2);
      check(quiesce_request===1'b1&&dut.saved_error==8'd1,
            "unsupported code cannot reuse a previously valid high fault witness");
`ifdef __ICARUS__
      reset_fault=1;reset_fault_code=8'hxx;tick(1);
      ack_result(8'd2);
      check(quiesce_request===1'b1&&dut.saved_error==8'd1,
            "unknown code cannot reuse a previously valid high fault witness");
`endif
      reset_fault=0;reset_fault_code=0;tick(1);
      reset_fault=1;reset_fault_code=8'd0;tick(1);
      ack_result(8'd2);
      check(quiesce_request===1'b1&&dut.saved_error==8'd1,
            "zero code cannot reuse terminal witness after fault cleared");
      reset_fault=0;reset_fault_code=0;tick(1);
      reset_fault=1;reset_fault_code=8'd8;tick(1);
      ack_result(8'd2);
      check(quiesce_request===1'b1&&dut.saved_error==8'd1,
            "unsupported code cannot reuse terminal witness after fault cleared");
`ifdef __ICARUS__
      reset_fault=0;reset_fault_code=0;tick(1);
      reset_fault=1;reset_fault_code=8'hxx;tick(1);
      ack_result(8'd2);
      check(quiesce_request===1'b1&&dut.saved_error==8'd1,
            "unknown code cannot reuse terminal witness after fault cleared");
`endif
      reset_fault=0;reset_fault_code=0;tick(1);
      reset_fault=1;reset_fault_code=8'd3;tick(1);
      ack_result(8'd0);
      check(dut.state===3'd0&&dut.saved_error==8'd1&&dut.saved_sequence_code==0&&
            dut.success_epoch===before_epoch&&reset_request_edges==before_count+1,
            "fresh fault after observed low unlocks ACK without rewriting held result");
      reset_fault=0;reset_fault_code=0;quiesce_ack=0;quiescent=0;reset_ready=1;
      reset_complete=0;platform_ready=0;
    end
  endtask
  task automatic reset_fault_during_active;
    integer before_count;
    begin
      before_count=reset_request_edges;
      start_request(8'd0);quiesce_ack=1;quiescent=1;
      wait_reset_request(6);tick(1);
      reset_ready=0;reset_asserted=0;reset_complete=0;platform_ready=0;
      reset_fault_code=8'd2;reset_fault=1;tick(1);
      check(dut.state===3'd5&&dut.saved_error==8'd3&&dut.saved_sequence_code==8'd2&&
            dut.reset_sent===1'b1,"actual coordinator fault terminates issued reset");
      ack_result(8'd0);
      check(dut.state===3'd0&&reset_request_edges==before_count+1,"fault ACK does not issue reset again");
      reset_fault=0;reset_fault_code=0;quiesce_ack=0;quiescent=0;reset_ready=1;
      reset_complete=0;platform_ready=0;
    end
  endtask
  task automatic prefire_timeout_and_ack;
    integer before_count;
    begin
      before_count=reset_request_edges;
      start_request(8'd0);check(quiesce_request===1'b1&&reset_request===1'b0,"prefire timeout barrier asserted");
      tick(80);
      check(dut.state===3'd5&&dut.saved_error==8'd1&&dut.saved_phase==3'd1&&
            dut.reset_sent===1'b0&&quiesce_request===1'b1,"prefire timeout retains barrier without reset request");
      start_request(8'd2);cancel_request(8'd2);
      ack_result(8'd0);
      check(dut.state===3'd0&&quiesce_request===1'b0&&reset_request_edges==before_count,
            "pre-fire timeout may be ACKed without requesting reset");
    end
  endtask
  task automatic unknown_active_witness;
    begin
      start_request(8'd0);quiesce_ack=1;quiescent=1'bx;tick(1);
      check(dut.state===3'd5&&dut.saved_error==8'd7&&dut.saved_phase==3'd1&&
            dut.reset_sent===1'b0&&reset_request===1'b0,"unknown active witness fails closed pre-fire");
      quiescent=0;quiesce_ack=0;
      read32(32'h18,32'd7,"unknown witness saved error");
      read32(32'h20,32'd1,"unknown witness source phase");
      ack_result(8'd0);
      check(dut.state===3'd0,"unknown-witness result ACK returns idle");
    end
  endtask
  task automatic expect_rejected_keys;
    integer before_count;
    begin
      before_count=reset_request_edges;
      send_frame(8'd1,32'h00,0,4'hf,32'h0,8'd5,0,"bad magic");
      send_frame(8'd3,32'h00,0,4'hf,MAGIC,8'd5,0,"unsupported op");
      send_frame(8'd2,32'h0c,{480'd0,START_KEY},4'h7,MAGIC,8'd5,0,"bad strobe");
      send_frame(8'd1,32'h00,{480'd0,32'd1},4'hf,MAGIC,8'd5,0,"read payload reserved");
      send_frame(8'd2,32'h0c,{479'd0,1'b1,START_KEY},4'hf,MAGIC,8'd5,0,"write payload reserved");
      send_frame(8'd1,32'h02,0,4'hf,MAGIC,8'd4,0,"unaligned read");
      send_frame(8'd2,32'h0c,{480'd0,32'h12345678},4'hf,MAGIC,8'd2,0,"invalid key");
      send_frame(8'd1,32'h40,0,4'hf,MAGIC,8'd2,0,"unsupported register read");
      write32(32'h00,32'd0,8'd2,"write read-only identity");
      check(reset_request_edges==before_count&&dut.state===3'd0,"rejected frames have no reset side effect");
      $display("PASS_WHOLE_RESET_SCENARIO name=frame_validation");
    end
  endtask
  task automatic start_invariant_tests;
    begin
      reset_ready=0;start_request(8'd2);reset_ready=1;
      quiesce_ack=1;start_request(8'd2);quiesce_ack=0;
      quiescent=1;start_request(8'd2);quiescent=0;
`ifdef __ICARUS__
      reset_ready=1'bx;start_request(8'd2);reset_ready=1;
`endif
      force dut.attempts=32'hffffffff;start_request(8'd2);release dut.attempts;
      force dut.success_epoch=32'hffffffff;start_request(8'd2);release dut.success_epoch;
      @(negedge sys_clk);power_rst_n=0;req_valid=0;req=0;
      tick(2);@(negedge sys_clk);power_rst_n=1;tick(2);
      read32(32'h10,32'd0,"power reset clears overflowed attempt fixture");
      read32(32'h14,32'd0,"power reset clears overflowed epoch fixture");
      check(dut.state===3'd0&&dut.quiesce_request===1'b0,"invalid readiness/ownership/overflow START cannot mutate state");
      $display("PASS_WHOLE_RESET_SCENARIO name=start_admission_invariants");
    end
  endtask
  task automatic raw_unknown_frame;
    logic [15:0] frame_seq;
    begin
      next_seq(frame_seq);@(negedge sys_clk);
      req={MAGIC,frame_seq,8'd1,4'hf,32'h00,512'd0};req[500]=1'bx;req_valid=1;
      @(posedge sys_clk);#1;
      check(rsp_valid===1'b1&&rsp_status===8'd5&&rsp_data===0&&rsp_seq===frame_seq,
            "unknown raw frame fields are rejected");
      @(negedge sys_clk);req_valid=0;req='0;@(posedge sys_clk);#1;
    end
  endtask
  initial begin
    sys_clk=0;power_rst_n=0;reset_request_edges=0;
    req_valid=0;req=0;quiesce_ack=0;quiescent=0;reset_ready=1;reset_asserted=0;
    reset_complete=1;reset_fault=0;reset_fault_code=0;platform_ready=1;seq=0;
    repeat(3)@(posedge sys_clk);@(negedge sys_clk);power_rst_n=1;tick(2);
    read32(32'h00,32'h524b5052,"identity");
    read32(32'h04,32'h00010000,"ABI");
    read32(32'h10,32'd0,"start attempts");read32(32'h14,32'd0,"success epoch");
    read32(32'h18,32'd0,"saved error");read32(32'h1c,32'h00010001,"reset control ABI");
    read32(32'h28,32'd64,"timeout low");read32(32'h2c,32'd0,"timeout high");
    expect_rejected_keys();start_invariant_tests();
`ifdef __ICARUS__
    raw_unknown_frame();unknown_active_witness();
    $display("PASS_WHOLE_RESET_SCENARIO name=unknown_active_witness_4state");
`endif
    finish_cancelled_request();$display("PASS_WHOLE_RESET_SCENARIO name=cancel_before_fire");
    cancel_on_exact_fire_edge();$display("PASS_WHOLE_RESET_SCENARIO name=cancel_wins_exact_fire_edge");
    finish_reset_success();$display("PASS_WHOLE_RESET_SCENARIO name=fresh_reset_assert_complete_ready_ack");
    prefire_timeout_and_ack();$display("PASS_WHOLE_RESET_SCENARIO name=timeout_before_reset_fire_ack");
    after_fire_timeout_and_ack_rules();$display("PASS_WHOLE_RESET_SCENARIO name=timeout_after_fire_waits_for_terminal_reset");
    reset_fault_during_active();$display("PASS_WHOLE_RESET_SCENARIO name=reset_fault_ack_after_fire");
    stale_fault_requires_fresh_terminal_fault();
    $display("PASS_WHOLE_RESET_SCENARIO name=stale_fault_requires_fresh_terminal_fault");
    reset_fault=1;reset_fault_code=1;tick(4);
    check(reset_request===1'b0&&dut.state===3'd0,"health inputs do not autonomously request reset; DUT has no TAP signal");
    reset_fault=0;reset_fault_code=0;
    $display("PASS_RK_WHOLE_RESET_CONTROL checks=%0d reset_fires=%0d x_tests=%0d scope=control_only_nonphysical",
      checks,reset_request_edges,X_TESTS);
    $finish;
  end
  initial begin repeat(10000)@(posedge sys_clk);$fatal(1,"whole-reset control watchdog");end
endmodule
