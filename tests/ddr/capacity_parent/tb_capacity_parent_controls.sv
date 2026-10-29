// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Published CAP_parent-v2 diagnostic router with the actual EW/CMAC register
// banks behind slave0 and the published RKMT bank behind slave1. This is a
// control-path simulation only; no DDR model, capacity proof or hardware call.
module tb_capacity_parent_controls;
  logic clk; initial clk=0; always #5 clk=~clk;
  logic joint_rst_n;
  logic [31:0] s_awaddr,s_wdata,s_araddr;
  logic [2:0] s_awprot,s_arprot;
  logic s_awvalid,s_wvalid,s_bready,s_arvalid,s_rready;
  logic [3:0] s_wstrb;
  wire s_awready,s_wready,s_bvalid,s_arready,s_rvalid;
  wire [1:0] s_bresp,s_rresp;
  wire [31:0] s_rdata;
  wire [1:0][31:0] m_awaddr,m_wdata,m_araddr,m_rdata;
  wire [1:0][2:0] m_awprot,m_arprot;
  wire [1:0][3:0] m_wstrb;
  wire [1:0] m_awvalid,m_awready,m_wvalid,m_wready,m_bvalid,m_bready;
  wire [1:0][1:0] m_bresp,m_rresp;
  wire [1:0] m_arvalid,m_arready,m_rvalid,m_rready;

  rk_axil_diagnostic_router router(
    .clk,.joint_rst_n,
    .s_axil_awaddr(s_awaddr),.s_axil_awprot(s_awprot),.s_axil_awvalid(s_awvalid),.s_axil_awready(s_awready),
    .s_axil_wdata(s_wdata),.s_axil_wstrb(s_wstrb),.s_axil_wvalid(s_wvalid),.s_axil_wready(s_wready),
    .s_axil_bresp(s_bresp),.s_axil_bvalid(s_bvalid),.s_axil_bready(s_bready),
    .s_axil_araddr(s_araddr),.s_axil_arprot(s_arprot),.s_axil_arvalid(s_arvalid),.s_axil_arready(s_arready),
    .s_axil_rdata(s_rdata),.s_axil_rresp(s_rresp),.s_axil_rvalid(s_rvalid),.s_axil_rready(s_rready),
    .m_axil_awaddr(m_awaddr),.m_axil_awprot(m_awprot),.m_axil_awvalid(m_awvalid),.m_axil_awready(m_awready),
    .m_axil_wdata(m_wdata),.m_axil_wstrb(m_wstrb),.m_axil_wvalid(m_wvalid),.m_axil_wready(m_wready),
    .m_axil_bresp(m_bresp),.m_axil_bvalid(m_bvalid),.m_axil_bready(m_bready),
    .m_axil_araddr(m_araddr),.m_axil_arprot(m_arprot),.m_axil_arvalid(m_arvalid),.m_axil_arready(m_arready),
    .m_axil_rdata(m_rdata),.m_axil_rresp(m_rresp),.m_axil_rvalid(m_rvalid),.m_axil_rready(m_rready));

  logic memory_ready,ew_ready,cmac_ready,core_busy,core_done,core_error;
  wire core_write_block=core_busy||core_error;
  logic [7:0] core_error_code;
  logic [31:0] core_completed_tasks;
  wire irq,scheduler_fault,control_owned,control_owner_cmac,core_start_valid,core_start_cmac;
  wire [31:0] core_start_address,core_start_amount;
  logic saw_ew_start,saw_cmac_start;
  logic [31:0] observed_start_address,observed_start_amount;
  logic observed_start_cmac;
  integer reads,writes;

  rk_dual_job_control_admission normal_banks(
    .clk,.rst_n(joint_rst_n),.memory_ready,
    .s_axil_awaddr(m_awaddr[0]),.s_axil_awprot(m_awprot[0]),.s_axil_awvalid(m_awvalid[0]),.s_axil_awready(m_awready[0]),
    .s_axil_wdata(m_wdata[0]),.s_axil_wstrb(m_wstrb[0]),.s_axil_wvalid(m_wvalid[0]),.s_axil_wready(m_wready[0]),
    .s_axil_bresp(m_bresp[0]),.s_axil_bvalid(m_bvalid[0]),.s_axil_bready(m_bready[0]),
    .s_axil_araddr(m_araddr[0]),.s_axil_arprot(m_arprot[0]),.s_axil_arvalid(m_arvalid[0]),.s_axil_arready(m_arready[0]),
    .s_axil_rdata(m_rdata[0]),.s_axil_rresp(m_rresp[0]),.s_axil_rvalid(m_rvalid[0]),.s_axil_rready(m_rready[0]),
    .irq,.scheduler_fault,.control_owned,.control_owner_cmac,.core_start_valid,.core_start_cmac,
    .core_start_address,.core_start_amount,.core_ew_start_ready(ew_ready),.core_cmac_start_ready(cmac_ready),
    .core_busy,.core_done,.core_error,.core_write_block,.core_error_code,.core_completed_tasks);

  wire rkmt_request_valid;
  wire [31:0] rkmt_seed;
  logic [30:0] rkmt_mismatch_address,rkmt_last_write;
  logic [511:0] rkmt_expected,rkmt_actual;
  logic rkmt_request_ready;
  rk_ddr_capacity_regs #(.BASE_ADDR(31'h10000000),.SPAN_BYTES(32'h00100000)) diag_regs(
    .clk,.joint_rst_n,
    .s_axil_awaddr(m_awaddr[1]),.s_axil_awprot(m_awprot[1]),.s_axil_awvalid(m_awvalid[1]),.s_axil_awready(m_awready[1]),
    .s_axil_wdata(m_wdata[1]),.s_axil_wstrb(m_wstrb[1]),.s_axil_wvalid(m_wvalid[1]),.s_axil_wready(m_wready[1]),
    .s_axil_bresp(m_bresp[1]),.s_axil_bvalid(m_bvalid[1]),.s_axil_bready(m_bready[1]),
    .s_axil_araddr(m_araddr[1]),.s_axil_arprot(m_arprot[1]),.s_axil_arvalid(m_arvalid[1]),.s_axil_arready(m_arready[1]),
    .s_axil_rdata(m_rdata[1]),.s_axil_rresp(m_rresp[1]),.s_axil_rvalid(m_rvalid[1]),.s_axil_rready(m_rready[1]),
    .request_valid(rkmt_request_valid),.request_ready(rkmt_request_ready),.request_seed(rkmt_seed),
    .handoff_allowed(1'b1),.owner_busy(1'b0),.owner_done(1'b0),.owner_fault(1'b0),.diagnostic_selected(1'b0),
    .completed_writes(32'b0),.completed_reads(32'b0),.fault_codes(32'b0),.fault_sources(3'b0),
    .mismatch_address(rkmt_mismatch_address),.last_completed_write_address(rkmt_last_write),
    .mismatch_expected(rkmt_expected),.mismatch_actual(rkmt_actual));

  always @(posedge clk) begin
    if(!joint_rst_n)begin saw_ew_start<=0;saw_cmac_start<=0;observed_start_address<=0;observed_start_amount<=0;observed_start_cmac<=0;end
    else if(core_start_valid&&((core_start_cmac&&cmac_ready)||(!core_start_cmac&&ew_ready)))begin
      observed_start_address<=core_start_address;observed_start_amount<=core_start_amount;observed_start_cmac<=core_start_cmac;
      if(core_start_cmac)saw_cmac_start<=1;else saw_ew_start<=1;
    end
  end

  task automatic fail(input string message); $display("FAIL_CAPACITY_PARENT %s",message); $fatal(1); endtask
  task automatic reset_dut;
    begin
      @(negedge clk);joint_rst_n=0;s_awaddr=0;s_awprot=0;s_awvalid=0;s_wdata=0;s_wstrb=0;s_wvalid=0;s_bready=0;
      s_araddr=0;s_arprot=0;s_arvalid=0;s_rready=0;memory_ready=1;ew_ready=1;cmac_ready=1;
      core_busy=0;core_done=0;core_error=0;core_error_code=0;core_completed_tasks=0;rkmt_request_ready=0;
      rkmt_mismatch_address=0;rkmt_last_write=0;rkmt_expected=0;rkmt_actual=0;reads=0;writes=0;
      repeat(2)@(posedge clk);@(negedge clk);joint_rst_n=1;
    end
  endtask

  task automatic read_csr(input logic [31:0] address,input logic [2:0] prot,input logic [1:0] expected_resp,input logic [31:0] expected_data,input bit change_frontend);
    integer guard;logic [31:0] changed;
    begin
      changed=~address;@(negedge clk);s_araddr=address;s_arprot=prot;s_arvalid=1;s_rready=0;#1;
      if(s_arready!==1)fail($sformatf("AR not admitted at %08x",address));
      if(m_arvalid!==2'b01&&m_arvalid!==2'b10)fail("AR did not select exactly one child");
      @(posedge clk);#1;@(negedge clk);s_arvalid=0;
      if(change_frontend)begin s_araddr=changed;s_arprot=~prot;end
      guard=0;while(!s_rvalid)begin @(negedge clk);guard=guard+1;if(guard>20)fail("R response timeout");end
      repeat(2)begin @(posedge clk);#1;if(s_rvalid!==1||s_rresp!==expected_resp||s_rdata!==expected_data)
        fail($sformatf("R changed/misrouted address=%08x got resp=%b data=%08x expected resp=%b data=%08x",address,s_rresp,s_rdata,expected_resp,expected_data));end
      @(negedge clk);s_rready=1;@(posedge clk);#1;@(negedge clk);s_rready=0;reads=reads+1;
    end
  endtask

  task automatic write_csr(input logic [31:0] address,input logic [2:0] prot,input logic [31:0] data,input logic [3:0] strb,input logic [1:0] expected_resp,input bit mutate_frontend);
    integer guard;logic [31:0] changed;
    begin
      changed=~address;@(negedge clk);s_awaddr=address;s_awprot=prot;s_awvalid=1;s_bready=0;#1;
      if(s_awready!==1)fail($sformatf("AW not admitted at %08x",address));
      if(m_awvalid!==2'b01&&m_awvalid!==2'b10)fail("AW did not select exactly one child");
      @(posedge clk);#1;@(negedge clk);s_awvalid=0;
      if(mutate_frontend)begin s_awaddr=changed;s_awprot=~prot;end
      s_wdata=data;s_wstrb=strb;s_wvalid=1;#1;if(s_wready!==1)fail("W not accepted");
      @(posedge clk);#1;@(negedge clk);s_wvalid=0;s_wdata=~data;s_wstrb=~strb;
      guard=0;while(!s_bvalid)begin @(negedge clk);guard=guard+1;if(guard>20)fail("B response timeout");end
      repeat(2)begin @(posedge clk);#1;if(s_bvalid!==1||s_bresp!==expected_resp)
        fail($sformatf("B changed/misrouted address=%08x got=%b expected=%b",address,s_bresp,expected_resp));end
      @(negedge clk);s_bready=1;@(posedge clk);#1;@(negedge clk);s_bready=0;writes=writes+1;
    end
  endtask

  task automatic run_job(input bit cmac,input logic [31:0] address,input logic [31:0] amount,input logic [31:0] tag);
    logic [31:0] base;integer guard;
    begin
      base=cmac?32'h100:32'h0;
      write_csr(base+32'h10,0,address,4'hf,0,1);
      write_csr(base+32'h14,0,amount,4'hf,0,1);
      write_csr(base+32'h18,0,tag,4'hf,0,1);
      if(cmac)write_csr(base+32'h10,3'b001,32'hbad0bad0,4'hf,2,1);
      else write_csr(32'h14,0,amount^32'h1,4'h3,2,1);
      read_csr(base+32'h10,0,0,address,1);
      read_csr(base+32'h14,0,0,amount,1);
      read_csr(base+32'h18,0,0,tag,1);
      write_csr(base+32'h0c,0,1,4'hf,0,1);
      guard=0;while(!((cmac&&saw_cmac_start)||(!cmac&&saw_ew_start)))begin @(negedge clk);guard=guard+1;if(guard>30)fail("normal descriptor did not reach selected core");end
      if(observed_start_cmac!==cmac||observed_start_address!==address||observed_start_amount!==amount)
        fail($sformatf("normal descriptor wrong cmac=%0d address=%08x amount=%0d",observed_start_cmac,observed_start_address,observed_start_amount));
      if(control_owner_cmac!==cmac||scheduler_fault)fail("selected normal owner bank or scheduler fault is wrong");
      core_completed_tasks=cmac?1:2;@(negedge clk);core_done=1;@(posedge clk);#1;@(negedge clk);core_done=0;
      if(!irq||!control_owned||control_owner_cmac!==cmac)fail("actual result did not remain owned through readback/ACK");
      read_csr(base+32'h1c,0,0,tag,1);read_csr(base+32'h20,0,0,cmac?1:2,1);read_csr(base+32'h24,0,0,0,1);
      write_csr(base+32'h0c,0,2,4'hf,0,1);
      guard=0;while(control_owned)begin @(negedge clk);guard=guard+1;if(guard>20)fail("normal bank owner did not release after result ACK");end
      if(cmac)saw_cmac_start=0;else saw_ew_start=0;
    end
  endtask

  initial begin
    reset_dut();
    if(rkmt_request_valid!==0||rkmt_seed!==32'h3588c350||rkmt_mismatch_address!==0||rkmt_last_write!==0||rkmt_expected!==0||rkmt_actual!==0)
      fail("published RKMT bank reset snapshot/default seed mismatch");
    read_csr(0,0,0,32'h524b4144,1);read_csr(4,0,0,32'h00010000,1);
    read_csr(32'h100,0,0,32'h524b4344,1);read_csr(32'h104,0,0,32'h00010000,1);
    read_csr(32'h200,0,0,32'h524b4d54,1);read_csr(32'h204,0,0,32'h00010000,1);
    // The router must preserve the full address through the actual normal leaf;
    // high aliases route to EW unchanged and retain its explicit DECERR.
    read_csr(32'h00010200,0,2'b11,0,1);read_csr(32'h01000200,0,2'b11,0,1);
    read_csr(32'h01000000,0,2'b11,0,1);read_csr(0,3'b001,2'b10,0,1);
    write_csr(32'h01000010,0,32'h12345678,4'hf,2'b11,1);
    run_job(0,32'h10001000,35,32'h35880001);
    run_job(1,32'h100e0000,45,32'h35880002);
    $display("PASS_CAPACITY_PARENT_CONTROLS reads=%0d writes=%0d actual_normal_banks=EW+CMAC RKMT=public_decoder scopes=control_only",reads,writes);$finish;
  end
  initial begin repeat(20000)@(posedge clk);fail("watchdog");end
endmodule
