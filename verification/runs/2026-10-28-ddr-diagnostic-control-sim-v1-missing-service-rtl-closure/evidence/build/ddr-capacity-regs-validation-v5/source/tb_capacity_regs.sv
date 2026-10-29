`timescale 1ns/1ps
module tb_capacity_regs;
  logic clk, joint_rst_n;
  initial begin clk=0; joint_rst_n=0; end
  always #5 clk=~clk;
  logic [31:0] awaddr, wdata, araddr;
  logic [2:0] awprot, arprot;
  logic awvalid, wvalid, bready, arvalid, rready;
  logic [3:0] wstrb;
  wire awready, wready, bvalid, arready, rvalid;
  wire [1:0] bresp, rresp;
  wire [31:0] rdata;
  wire request_valid;
  logic request_ready, handoff_allowed, owner_busy, owner_done, owner_fault, diagnostic_selected;
  logic [31:0] completed_writes, completed_reads, fault_codes;
  logic [2:0] fault_sources;
  logic [30:0] mismatch_address, last_completed_write_address;
  logic [511:0] mismatch_expected, mismatch_actual;
  wire [31:0] request_seed;
  integer checks;
  logic [31:0] current_araddr;

  rk_ddr_capacity_regs #(.BASE_ADDR(31'd0),.SPAN_BYTES(32'h80000000)) dut (
    .clk,.joint_rst_n,.s_axil_awaddr(awaddr),.s_axil_awprot(awprot),.s_axil_awvalid(awvalid),.s_axil_awready(awready),
    .s_axil_wdata(wdata),.s_axil_wstrb(wstrb),.s_axil_wvalid(wvalid),.s_axil_wready(wready),
    .s_axil_bresp(bresp),.s_axil_bvalid(bvalid),.s_axil_bready(bready),
    .s_axil_araddr(araddr),.s_axil_arprot(arprot),.s_axil_arvalid(arvalid),.s_axil_arready(arready),
    .s_axil_rdata(rdata),.s_axil_rresp(rresp),.s_axil_rvalid(rvalid),.s_axil_rready(rready),
    .request_valid,.request_ready,.request_seed,.handoff_allowed,.owner_busy,.owner_done,.owner_fault,.diagnostic_selected,
    .completed_writes,.completed_reads,.fault_codes,.fault_sources,.mismatch_address,.last_completed_write_address,
    .mismatch_expected,.mismatch_actual
  );

  task automatic ck(input logic ok,input string what);
    begin checks=checks+1; if (ok!==1'b1) $fatal(1,"CHECK %s",what); end
  endtask
  task automatic tick;
    begin @(posedge clk); #1; end
  endtask
  task automatic reset_all;
    begin
      @(negedge clk); joint_rst_n=0; awvalid=0; wvalid=0; bready=0; arvalid=0; rready=0;
      awaddr=0; awprot=0; wdata=0; wstrb=4'hf; araddr=0; arprot=0;
      request_ready=0; handoff_allowed=1; owner_busy=0; owner_done=0; owner_fault=0; diagnostic_selected=0;
      completed_writes=0; completed_reads=0; fault_codes=0; fault_sources=0;
      mismatch_address=0; last_completed_write_address=0; mismatch_expected=0; mismatch_actual=0;
      tick(); @(negedge clk); joint_rst_n=1; tick();
    end
  endtask
  task automatic put_aw(input logic [31:0] a,input logic [2:0] p);
    integer waits; logic accepted;
    begin
      waits=0; @(negedge clk); awaddr=a; awprot=p; awvalid=1;
      do begin @(posedge clk); accepted=awready; #1; waits=waits+1; if(waits>100) $fatal(1,"AW handshake timeout"); end while(!accepted);
      @(negedge clk); awvalid=0;
    end
  endtask
  task automatic put_w(input logic [31:0] d,input logic [3:0] s);
    integer waits; logic accepted;
    begin
      waits=0; @(negedge clk); wdata=d; wstrb=s; wvalid=1;
      do begin @(posedge clk); accepted=wready; #1; waits=waits+1; if(waits>100) $fatal(1,"W handshake timeout"); end while(!accepted);
      @(negedge clk); wvalid=0;
    end
  endtask
  task automatic get_b(input logic [1:0] expected,input integer stall);
    logic [1:0] held; integer waits;
    begin
      bready=0; waits=0; do begin tick(); waits=waits+1; if(waits>100) $fatal(1,"B response timeout"); end while (!bvalid);
      ck(bresp===expected,"B response code"); held=bresp;
      repeat(stall) begin tick(); ck(bvalid===1 && bresp===held,"B stable under backpressure"); end
      @(negedge clk); bready=1; tick(); ck(!bvalid,"B handshake clears response"); @(negedge clk); bready=0;
    end
  endtask
  task automatic wr(input logic [31:0] a,input logic [31:0] d,input logic [3:0] s,input logic [2:0] p,
                    input integer ordering,input logic [1:0] expected);
    begin
      if(ordering==0) begin put_aw(a,p); repeat(2) tick(); put_w(d,s); end
      else if(ordering==1) begin put_w(d,s); repeat(2) tick(); put_aw(a,p); end
      else begin
        @(negedge clk); awaddr=a; awprot=p; wdata=d; wstrb=s; awvalid=1; wvalid=1;
        begin : both_channels
          integer waits; logic aw_taken, w_taken;
          waits=0;
          do begin @(posedge clk); aw_taken=awready; w_taken=wready; #1; waits=waits+1; if(waits>100) $fatal(1,"AW/W handshake timeout"); end while (!(aw_taken&&w_taken));
        end
        @(negedge clk); awvalid=0; wvalid=0;
      end
      get_b(expected,2);
    end
  endtask
  task automatic get_r(input logic [1:0] expected_resp,input logic [31:0] expected_data,input integer stall);
    logic [31:0] held; logic [1:0] heldresp; integer waits;
    begin
      rready=0; waits=0; do begin tick(); waits=waits+1; if(waits>100) $fatal(1,"R response timeout"); end while(!rvalid); ck(rresp===expected_resp,"R response code");
      if(expected_resp===0 && rdata!==expected_data) $fatal(1,"R_DATA addr=%08x expected=%08x actual=%08x",current_araddr,expected_data,rdata); held=rdata; heldresp=rresp;
      repeat(stall) begin tick(); ck(rvalid===1 && rdata===held && rresp===heldresp,"R stable under backpressure"); end
      @(negedge clk); rready=1; tick(); ck(!rvalid,"R handshake clears response"); @(negedge clk); rready=0;
    end
  endtask
  task automatic rd(input logic [31:0] a,input logic [2:0] p,input logic [1:0] resp,input logic [31:0] data);
    integer waits; logic accepted;
    begin
      waits=0; current_araddr=a; @(negedge clk); araddr=a; arprot=p; arvalid=1;
      do begin @(posedge clk); accepted=arready; #1; waits=waits+1; if(waits>100) $fatal(1,"AR handshake timeout"); end while(!accepted);
      @(negedge clk); arvalid=0; get_r(resp,data,2);
    end
  endtask
  task automatic start_held(input logic [31:0] expected_seed);
    begin
      request_ready=1; put_w(32'd1,4'hf); put_aw(32'h20c,0);
      @(posedge clk); #1; ck(bvalid && bresp===0 && request_valid && request_seed===expected_seed,"start commits exactly one held request");
      @(negedge clk); request_ready=0; get_b(0,2);
    end
  endtask

  integer i;
  logic [31:0] old_seed;
  initial begin
    checks=0;
    reset_all();
    rd(32'h200,0,0,32'h524b4d54); rd(32'h204,0,0,32'h00010000);
    rd(32'h208,0,0,32'h00000000); rd(32'h210,0,0,32'h3588c350);
    rd(32'h214,0,0,32'h80000000); rd(32'h218,0,0,0); rd(32'h21c,0,0,32'h00020040);
    rd(32'h220,0,0,0); rd(32'h224,0,0,0); rd(32'h228,0,0,0); rd(32'h22c,0,0,0);
    // W-before-AW, then independently stalled AW/W and a held B response.
    wr(32'h210,32'h12345678,4'hf,0,1,0); rd(32'h210,0,0,32'h12345678);
    // AR capture is an old-state snapshot when it coincides with a seed commit.
    put_aw(32'h210,0); put_w(32'hcafebeef,4'hf); old_seed=32'h12345678;
    araddr=32'h210; current_araddr=32'h210; arprot=0; arvalid=1;
    tick(); ck(bvalid && rvalid,"simultaneous write and read responses"); ck(rresp===0 && rdata===old_seed,"AR sees old seed on simultaneous write");
    @(negedge clk); arvalid=0; get_r(0,old_seed,1); get_b(0,1); rd(32'h210,0,0,32'hcafebeef);

    // Read-only words and malformed writes must not change seed or issue work.
    wr(32'h200,32'h0,4'hf,0,0,2); wr(32'h20c,0,4'hf,0,1,2); wr(32'h20c,2,4'hf,0,0,2);
    wr(32'h210,32'h11111111,4'h7,0,2,2); wr(32'h210,32'h11111111,4'hf,3'b001,0,2);
    wr(32'h211,32'h11111111,4'hf,0,1,2); wr(32'h2c0,32'h11111111,4'hf,0,0,2);
    rd(32'h210,0,0,32'hcafebeef); rd(32'h211,0,2,0); rd(32'h23c,0,2,0); rd(32'h2c0,0,2,0);
    for(i=1;i<8;i=i+1) begin wr(32'h210,32'h11111111,4'hf,i[2:0],i%2,2); rd(32'h210,i[2:0],2,0); end
`ifndef VERILATOR
    wr(32'h210,32'h11111111,4'b1x11,0,2,2); // Unknown byte enable is not a full-word write.
    wr(32'h210,32'h11111111,4'hf,3'b0x0,0,2);
    wr(32'h210,32'h11111111,4'hf,0,1,0); // valid full-word write after X controls
    rd(32'h210,3'b0x0,2,0);
    @(negedge clk); awaddr=32'h210; awprot=0; awvalid=1; tick(); @(negedge clk); awvalid=0;
    @(negedge clk); wdata=32'h0badc0de; wstrb=4'hf; wvalid=1; tick(); @(negedge clk); wvalid=0; get_b(0,1);
    rd(32'h210,0,0,32'h0badc0de);
    wr(32'h210,32'hxxxx_xxxx,4'hf,0,2,2); rd(32'h210,0,0,32'h0badc0de);
    wr(32'h210,32'hcafebeef,4'hf,0,2,0); rd(32'h210,0,0,32'hcafebeef);
    wr(32'hxxxx_xxxx,32'h12345678,4'hf,0,0,2);
    rd(32'hxxxx_xxxx,0,2,0);
`endif

    // Every expected/actual mismatch word is independently addressable and ordered low-word first.
    for(i=0;i<16;i=i+1) begin mismatch_expected[i*32 +:32]=32'h10000000+i; mismatch_actual[i*32 +:32]=32'h20000000+i; end
    mismatch_address=31'h1234560; last_completed_write_address=31'h7654320;
    completed_writes=32'h10203040; completed_reads=32'h50607080;
    fault_codes=32'h000008e5; fault_sources=3'b101;
    rd(32'h220,0,0,32'h10203040); rd(32'h224,0,0,32'h50607080); rd(32'h228,0,0,32'h000008e5);
    rd(32'h22c,0,0,32'h5); rd(32'h230,0,0,32'h01234560); rd(32'h234,0,0,32'h07654320);
    for(i=0;i<16;i=i+1) begin rd(32'h240+i*4,0,0,32'h10000000+i); rd(32'h280+i*4,0,0,32'h20000000+i); end

    // A pending start is refused unless every admission predicate is exact.
    request_ready=0; wr(32'h20c,1,4'hf,0,0,2);
    request_ready=1; handoff_allowed=0; wr(32'h20c,1,4'hf,0,1,2);
    handoff_allowed=1; owner_busy=1; wr(32'h20c,1,4'hf,0,2,2);
    owner_busy=0; owner_fault=1; wr(32'h20c,1,4'hf,0,0,2);
    owner_fault=0; diagnostic_selected=1; wr(32'h20c,1,4'hf,0,1,2);
    diagnostic_selected=0; rd(32'h208,0,0,32'h00000001);
    // Queue AW before a health transition; the W channel is still accepted, but commit rejects.
    put_aw(32'h210,0); owner_busy=1; put_w(32'h01020304,4'hf); get_b(2,1); owner_busy=0;
    rd(32'h210,0,0,32'hcafebeef);

    // One valid start per reset. Hold the request across a fault; its seed remains fixed until handshake.
    start_held(32'hcafebeef); ck(request_valid===1 && request_seed===32'hcafebeef,"start request carries configured seed");
    repeat(3) begin tick(); ck(request_valid && request_seed===32'hcafebeef,"held request stable"); end
    owner_fault=1; ck(request_valid && request_seed===32'hcafebeef,"fault does not cancel owned request");
    wr(32'h210,32'hdeadbeef,4'hf,0,0,2); wr(32'h20c,1,4'hf,0,1,2); wr(32'h20c,0,4'hf,0,0,2);
    owner_busy=1; owner_done=1; completed_writes=16; completed_reads=16; fault_codes=32'h000000e5; fault_sources=3'b010;
    rd(32'h208,0,0,32'h0000005e); rd(32'h228,0,0,32'he5); rd(32'h220,0,0,16); rd(32'h224,0,0,16);
    ck(request_valid && request_seed===32'hcafebeef,"fault status read leaves request stable");
    request_ready=1; tick(); ck(!request_valid,"request handshake retires pending request");
    owner_busy=0; owner_done=0; rd(32'h208,0,0,32'h00000050);

    // Joint reset is the only way to rearm; new epoch permits a new seed/start.
    reset_all(); wr(32'h210,32'h0badc0de,4'hf,0,2,0);
    start_held(32'h0badc0de); ck(request_valid && request_seed===32'h0badc0de,"joint reset rearms single start");
    $display("PASS capacity_regs checks=%0d",checks);
    $finish;
  end
endmodule

module tb_capacity_regs_badparams #(parameter logic [30:0] BAD_BASE=0, parameter logic [31:0] BAD_SPAN=32'h80000000);
  logic clk;
  initial clk=0;
  always #5 clk=~clk;
  wire awready,wready,bvalid,arready,rvalid,request_valid;
  wire [1:0] bresp,rresp;
  wire [31:0] rdata,request_seed;
  rk_ddr_capacity_regs #(.BASE_ADDR(BAD_BASE),.SPAN_BYTES(BAD_SPAN)) dut (
    .clk,.joint_rst_n(1'b0),.s_axil_awaddr('0),.s_axil_awprot('0),.s_axil_awvalid(1'b0),.s_axil_awready(awready),
    .s_axil_wdata('0),.s_axil_wstrb('0),.s_axil_wvalid(1'b0),.s_axil_wready(wready),.s_axil_bresp(bresp),.s_axil_bvalid(bvalid),.s_axil_bready(1'b0),
    .s_axil_araddr('0),.s_axil_arprot('0),.s_axil_arvalid(1'b0),.s_axil_arready(arready),.s_axil_rdata(rdata),.s_axil_rresp(rresp),.s_axil_rvalid(rvalid),.s_axil_rready(1'b0),
    .request_valid,.request_ready(1'b0),.request_seed,.handoff_allowed(1'b0),.owner_busy(1'b0),.owner_done(1'b0),.owner_fault(1'b0),.diagnostic_selected(1'b0),
    .completed_writes('0),.completed_reads('0),.fault_codes('0),.fault_sources('0),.mismatch_address('0),.last_completed_write_address('0),.mismatch_expected('0),.mismatch_actual('0));
  initial begin #2; $display("BAD_PARAMETER_TEST_FAILED_TO_FATAL %b%b%b%b%b%b%b%b",awready,wready,bvalid,arready,rvalid,bresp,rresp,request_valid); $finish; end
endmodule
