// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Actual archived ECC control RTL only. Raw ECC inputs model qualified events;
// no DDR PHY, RMW transaction, memory contents or retirement is simulated.
module tb_mig_ecc_vendor;
  logic clk;
  initial clk=0;
  always #3.75 clk=~clk;
  logic joint_rst_n=0,calib_complete=0,init_complete=0,use_monitor=0;
  logic check_valid=0,snapshot_ready=0;
  wire check_ready,snapshot_valid,monitor_healthy,fault;
  wire [7:0] fault_code;
  wire [31:0] snapshot_status,snapshot_onoff,snapshot_irq_mask;
  wire [31:0] m_axi_ctrl_awaddr,m_axi_ctrl_wdata,m_axi_ctrl_araddr;
  wire m_axi_ctrl_awvalid,m_axi_ctrl_wvalid,m_axi_ctrl_bready,m_axi_ctrl_arvalid,m_axi_ctrl_rready;
  wire m_axi_ctrl_awready,m_axi_ctrl_wready,m_axi_ctrl_bvalid,m_axi_ctrl_arready,m_axi_ctrl_rvalid;
  wire [1:0] m_axi_ctrl_bresp,m_axi_ctrl_rresp;
  wire [31:0] m_axi_ctrl_rdata;
  wire mig_interrupt;
  rk_mig_ecc_monitor #(.TIMEOUT_CYCLES(128)) monitor(.*);

  logic [7:0] ecc_single=0,ecc_multiple=0;
  logic [28:0] ecc_err_addr=0;
  logic [575:0] dfi_rddata=0;
  wire app_correct_en;
  wire [8:0] fi_xor_we;
  wire [71:0] fi_xor_wrdata;
  logic [31:0] host_awaddr=0,host_wdata=0,host_araddr=0;
  logic host_awvalid=0,host_wvalid=0,host_bready=0,host_arvalid=0,host_rready=0;
  wire awready,wready,bvalid,arready,rvalid,interrupt;
  wire [1:0] bresp,rresp;
  wire [31:0] rdata;
  wire [31:0] awaddr=use_monitor?m_axi_ctrl_awaddr:host_awaddr;
  wire [31:0] wdata=use_monitor?m_axi_ctrl_wdata:host_wdata;
  wire [31:0] araddr=use_monitor?m_axi_ctrl_araddr:host_araddr;
  wire awvalid=use_monitor?m_axi_ctrl_awvalid:host_awvalid;
  wire wvalid=use_monitor?m_axi_ctrl_wvalid:host_wvalid;
  wire bready=use_monitor?m_axi_ctrl_bready:host_bready;
  wire arvalid=use_monitor?m_axi_ctrl_arvalid:host_arvalid;
  wire rready=use_monitor?m_axi_ctrl_rready:host_rready;
  assign m_axi_ctrl_awready=use_monitor&&awready;
  assign m_axi_ctrl_wready=use_monitor&&wready;
  assign m_axi_ctrl_bvalid=use_monitor&&bvalid;
  assign m_axi_ctrl_bresp=bresp;
  assign m_axi_ctrl_arready=use_monitor&&arready;
  assign m_axi_ctrl_rvalid=use_monitor&&rvalid;
  assign m_axi_ctrl_rresp=rresp;
  assign m_axi_ctrl_rdata=rdata;
  assign mig_interrupt=use_monitor&&interrupt;

  mig_7series_v4_2_axi_ctrl_top #(
// The absolute per-run header binds provenance and prevents include shadowing.
/* verilator lint_off INCABSPATH */
`include `RK_MIG_ECC_PARAMS_HEADER
/* verilator lint_on INCABSPATH */
  ) control (
    .aclk(clk),.aresetn(joint_rst_n),
    .s_axi_awvalid(awvalid),.s_axi_awready(awready),.s_axi_awaddr(awaddr),
    .s_axi_wvalid(wvalid),.s_axi_wready(wready),.s_axi_wdata(wdata),
    .s_axi_bvalid(bvalid),.s_axi_bready(bready),.s_axi_bresp(bresp),
    .s_axi_arvalid(arvalid),.s_axi_arready(arready),.s_axi_araddr(araddr),
    .s_axi_rvalid(rvalid),.s_axi_rready(rready),.s_axi_rdata(rdata),.s_axi_rresp(rresp),
    .interrupt(interrupt),.init_complete(init_complete),.ecc_single(ecc_single),
    .ecc_multiple(ecc_multiple),.ecc_err_addr(ecc_err_addr),.app_correct_en(app_correct_en),
    .dfi_rddata(dfi_rddata),.fi_xor_we(fi_xor_we),.fi_xor_wrdata(fi_xor_wrdata)
  );

  integer scenarios,monitor_writes,reads;
  always @(posedge clk) if(!joint_rst_n) begin
    monitor_writes<=0;reads<=0;
  end else if(use_monitor) begin
    if(awvalid&&awready) begin
      if(awaddr!==32'h4) $fatal(1,"Monitor writes a register other than IRQ enable");
      monitor_writes<=monitor_writes+1;
    end
    if(wvalid&&wready&&wdata!==32'h3) $fatal(1,"Wrong monitor IRQ mask");
    if(arvalid&&arready) reads<=reads+1;
    if(rvalid&&!rready) $fatal(1,"Monitor backpressures live vendor RDATA");
  end
  task automatic tick;
    @(posedge clk); #0.1;
  endtask
  task automatic reset_pair;
    @(negedge clk);
    joint_rst_n=0;calib_complete=0;init_complete=0;use_monitor=0;
    check_valid=0;snapshot_ready=0;ecc_single=0;ecc_multiple=0;
    host_awvalid=0;host_wvalid=0;host_bready=0;host_arvalid=0;host_rready=0;
    repeat(3)tick();
    @(negedge clk);joint_rst_n=1;
    repeat(2)tick();
    scenarios=scenarios+1;
  endtask
  task automatic host_write(input logic[31:0] address,input logic[31:0] data);
    integer guard;
    logic aw_hit,w_hit;
    @(negedge clk);host_awaddr=address;host_wdata=data;host_awvalid=1;host_wvalid=1;host_bready=1;
    guard=0;
    while(host_awvalid||host_wvalid) begin
      @(posedge clk);
      aw_hit=awready&&host_awvalid;w_hit=wready&&host_wvalid;
      @(negedge clk);
      if(aw_hit)host_awvalid=0;
      if(w_hit)host_wvalid=0;
      guard=guard+1;if(guard>100)$fatal(1,"Vendor write request stalled");
    end
    while(!bvalid)begin tick();guard=guard+1;if(guard>100)$fatal(1,"Vendor B stalled");end
    if(bresp!==0)$fatal(1,"Vendor write error");
    tick();@(negedge clk);host_bready=0;
  endtask
  task automatic host_read(input logic[31:0] address,output logic[31:0] data);
    integer guard;
    @(negedge clk);host_araddr=address;host_arvalid=1;host_rready=1;guard=0;
    do begin @(posedge clk);guard=guard+1;if(guard>100)$fatal(1,"Vendor AR stalled");end while(!arready);
    @(negedge clk);host_arvalid=0;
    while(!rvalid)begin tick();guard=guard+1;if(guard>100)$fatal(1,"Vendor R stalled");end
    if(rresp!==0)$fatal(1,"Vendor read error");
    data=rdata;tick();@(negedge clk);host_rready=0;
  endtask
  task automatic start_monitor;
    integer guard;
    @(negedge clk);use_monitor=1;init_complete=1;calib_complete=1;
    guard=0;
    while(!monitor_healthy&&!fault)begin tick();guard=guard+1;if(guard>100)$fatal(1,"Monitor startup stalled");end
    if(fault)$fatal(1,"Monitor startup fault %0d",fault_code);
    if(monitor_writes!=1||reads!=3||app_correct_en!==1)$fatal(1,"Startup did not verify real control registers");
    // Vendor reg_bank latches write data even when the injection write-enable
    // is zero. Only the enable qualifies this payload; IRQ writes can change it.
    if(fi_xor_we!==0)$fatal(1,"Fault injection write enables active, payload=%h",fi_xor_wrdata);
  endtask
  task automatic snapshot;
    integer guard;
    @(negedge clk);check_valid=1;guard=0;
    do begin @(posedge clk);guard=guard+1;if(guard>100)$fatal(1,"Check admission stalled");end while(!check_ready);
    @(negedge clk);check_valid=0;
    while(!snapshot_valid&&!fault)begin tick();guard=guard+1;if(guard>100)$fatal(1,"Snapshot stalled");end
    if(fault||snapshot_status!==0||snapshot_onoff!==1||snapshot_irq_mask!==3)$fatal(1,"Bad vendor snapshot");
  endtask
  task automatic expect_fault(input logic[7:0] code);
    integer guard;
    guard=0;while(!fault)begin tick();guard=guard+1;if(guard>100)$fatal(1,"Expected vendor fault absent");end
    if(fault_code!==code||monitor_healthy)$fatal(1,"Wrong vendor fault %0d expected %0d",fault_code,code);
    repeat(12)tick();
    if(check_ready||monitor_healthy||!fault)$fatal(1,"Fault silently recovered");
  endtask
  logic[31:0] data;
  logic[95:0] held;
  integer kind,lane;
  initial begin
    scenarios=0;
    reset_pair();init_complete=1;
    host_read(8,data);if(data!==1)$fatal(1,"Incorrect archived ECC reset value");
    host_read(4,data);if(data!==0)$fatal(1,"Incorrect archived IRQ reset value");
    host_read(0,data);if(data!==0)$fatal(1,"Incorrect archived status reset value");
    @(negedge clk);ecc_multiple=8'h80;tick();@(negedge clk);ecc_multiple=0;
    repeat(3)tick();host_read(0,data);if(data!==1)$fatal(1,"Raw UE not sticky at bit0");
    if(interrupt)$fatal(1,"Disabled IRQ asserted");
    host_write(4,3);repeat(3)tick();if(!interrupt)$fatal(1,"IRQ mask not active");

    reset_pair();use_monitor=1;
    repeat(10)tick();if(monitor_writes!=0||reads!=0||monitor_healthy||fault)$fatal(1,"Uncalibrated access");
    start_monitor();snapshot();held={snapshot_status,snapshot_onoff,snapshot_irq_mask};
    repeat(7)begin tick();if(!snapshot_valid||{snapshot_status,snapshot_onoff,snapshot_irq_mask}!==held)$fatal(1,"Snapshot not stable");end
    @(negedge clk);snapshot_ready=1;tick();@(negedge clk);snapshot_ready=0;
    snapshot();
    @(negedge clk);ecc_multiple=1;tick();@(negedge clk);ecc_multiple=0;
    expect_fault(1);
    if(!snapshot_valid||{snapshot_status,snapshot_onoff,snapshot_irq_mask}!==held)$fatal(1,"Fault changed held pre-event snapshot");
    @(negedge clk);snapshot_ready=1;tick();@(negedge clk);snapshot_ready=0;
    if(!fault)$fatal(1,"Snapshot ACK cleared quarantine");

    for(kind=0;kind<2;kind=kind+1)for(lane=0;lane<8;lane=lane+1)begin
      reset_pair();start_monitor();
      @(negedge clk);if(kind==0)ecc_multiple=8'(1<<lane);else ecc_single=8'(1<<lane);
      tick();@(negedge clk);ecc_multiple=0;ecc_single=0;
      expect_fault(1);
    end

    reset_pair();init_complete=1;host_write(8,0);
    @(negedge clk);use_monitor=1;calib_complete=1;
    expect_fault(7);

    reset_pair();init_complete=1;
    @(negedge clk);ecc_multiple=1;tick();@(negedge clk);ecc_multiple=0;
    @(negedge clk);use_monitor=1;calib_complete=1;
    expect_fault(1);

    reset_pair();start_monitor();@(negedge clk);calib_complete=0;init_complete=0;
    expect_fault(2);@(negedge clk);calib_complete=1;init_complete=1;
    repeat(12)tick();if(!fault||monitor_healthy)$fatal(1,"Calibration return recovered quarantine");
    if(scenarios!=21)$fatal(1,"Vendor scenario inventory %0d",scenarios);
    $display("PASS mig_ecc_vendor scenarios=21 raw_event_vectors=16 held_snapshots=2 no_MIG_memory_or_retirement_proof");
    $finish;
  end
  initial begin repeat(20000)tick();$fatal(1,"Vendor monitor bench watchdog");end
endmodule
