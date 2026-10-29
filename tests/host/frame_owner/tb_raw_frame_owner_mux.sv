`timescale 1ns/1ps
module tb_raw_frame_owner_mux;
  logic clk, rst_n=0, release_ready=0;
  logic [1:0] link_healthy=2'b11, s_req_valid=0;
  wire [1:0] s_req_ready;
  logic [1:0][603:0] s_req=0;
  wire [1:0] s_rsp_valid;
  wire [1:0][511:0] s_rsp_data;
  wire [1:0][7:0] s_rsp_status;
  wire [1:0][15:0] s_rsp_seq;
  wire m_req_valid;
  logic m_req_ready=0;
  wire [603:0] m_req;
  logic m_rsp_valid=0;
  logic [511:0] m_rsp_data=0;
  logic [7:0] m_rsp_status=0;
  logic [15:0] m_rsp_seq=0;
  wire [1:0] owner;
  wire [31:0] lease_epoch;
  wire failed;
  wire [7:0] failure_code;
  integer checks=0;
  localparam logic [31:0] MAGIC=32'h4f54504a;
  rk_raw_frame_owner_mux dut(.*);
  always #5 clk=~clk;

  function automatic [603:0] frame(input logic [15:0] seq,input logic [7:0] op,
      input logic [31:0] addr,input logic [511:0] data,input logic [3:0] strb);
    frame={MAGIC,seq,op,strb,addr,data};
  endfunction
  task automatic check(input logic cond,input string label);
    begin checks=checks+1; if(cond!==1'b1) $fatal(1,"FAIL %s",label); end
  endtask
  task automatic tick;
    begin @(posedge clk); #1; end
  endtask
  task automatic reset_all;
    begin @(negedge clk); rst_n=0; s_req_valid=0; m_rsp_valid=0; m_req_ready=0;
      link_healthy=2'b11; release_ready=0; repeat(2) tick();
      @(negedge clk); rst_n=1; tick(); end
  endtask
  task automatic send(input integer src,input logic [603:0] req);
    begin @(negedge clk); s_req[src]=req; s_req_valid[src]=1;
      #1; check(s_req_ready[src],"source ready"); tick();
      @(negedge clk); s_req_valid[src]=0; end
  endtask
  task automatic response(input integer src,input logic [15:0] seq,
      input logic [7:0] status,input logic [511:0] data);
    begin @(negedge clk); m_rsp_seq=seq; m_rsp_status=status; m_rsp_data=data; m_rsp_valid=1;
      tick(); check(s_rsp_valid[src],"response delivered to source");
      check(s_rsp_seq[src]==seq,"response sequence"); check(s_rsp_status[src]==status,"response status");
      check(s_rsp_data[src]==data,"response payload");
      check(s_rsp_valid[1-src]==0,"response not broadcast to other source");
      @(negedge clk); m_rsp_valid=0; end
  endtask
  task automatic mgmt(input integer src,input logic [15:0] seq,input logic [7:0] op,
      input logic [31:0] addr,input logic [511:0] data,input logic [7:0] exp_status,
      input logic [511:0] exp_data);
    begin send(src,frame(seq,op,addr,data,4'hf));
      check(s_rsp_valid[src],"management response valid"); check(s_rsp_seq[src]==seq,"management sequence");
      if(s_rsp_status[src]!==exp_status) $display("MGMT status seq=%0d got=%0d exp=%0d failed=%0d owner=%0d",seq,s_rsp_status[src],exp_status,failed,owner); check(s_rsp_status[src]==exp_status,"management status");
      check(s_rsp_data[src]==exp_data,"management data"); end
  endtask
  task automatic acquire(input integer src,input logic [15:0] seq);
    logic [511:0] d;
    begin d=0; d[31:0]=1; mgmt(src,seq,2,32'h60c,d,0,0); end
  endtask
  task automatic release_owner(input integer src,input logic [15:0] seq);
    logic [511:0] d;
    begin d=0; d[31:0]=2; mgmt(src,seq,2,32'h60c,d,0,0); end
  endtask
  task automatic backend(input integer src,input logic [15:0] seq);
    begin send(src,frame(seq,8'h40,32'h12345678,512'hfeed0123456789ab,4'hf));
      check(m_req_valid,"owner backend request offered"); check(m_req==s_req[src],"request exact forwarding"); end
  endtask

  logic [511:0] d;
  logic [603:0] saved;
  integer i;
  initial begin
    clk=0;
    reset_all();
    mgmt(0,1,1,32'h600,0,0,512'h524b484f);
    mgmt(1,2,1,32'h604,0,0,512'h00010000);
    mgmt(0,3,1,32'h608,0,0,0);
    mgmt(1,4,1,32'h614,0,0,512'd2);
    mgmt(0,5,1,32'h61c,0,0,512'd3);
    mgmt(1,6,1,32'h610,0,0,0);
    mgmt(0,7,1,32'h618,0,0,0);
    d=0; d[31:0]=1; mgmt(0,8,2,32'h60c,d,2,0);
    release_ready=1'bx; mgmt(0,81,2,32'h60c,d,2,0);
    release_ready=1; acquire(0,9); check(owner==1&&lease_epoch==1,"JTAG claim epoch");
    mgmt(0,10,2,32'h60c,d,2,0);
    d[31:0]=2; release_ready=1'bx; mgmt(0,82,2,32'h60c,d,2,0);
    release_ready=0; mgmt(0,83,2,32'h60c,d,2,0); release_ready=1;
    d[31:0]=2; mgmt(1,11,2,32'h60c,d,2,0);
    mgmt(0,12,2,32'h60c,d,0,0); check(owner==0,"owner release");
    acquire(1,13); check(owner==2&&lease_epoch==2,"PCIe claim epoch");
    mgmt(0,14,1,32'h614,0,0,512'd1);

    // Denied nonowner and no-owner raw traffic never reaches backend.
    send(0,frame(20,8'h40,32'h100,0,4'hf));
    check(s_rsp_valid[0]&&s_rsp_status[0]==2&&!m_req_valid,"nonowner rejected");
    send(0,frame(201,1,32'h100,0,4'hf)); check(s_rsp_status[0]==2&&!m_req_valid,"nonowner raw read rejected");
    send(0,frame(202,2,32'h100,0,4'hf)); check(s_rsp_status[0]==2&&!m_req_valid,"nonowner raw write rejected");
    release_owner(1,21);
    send(1,frame(22,8'h40,32'h100,0,4'hf)); check(s_rsp_status[1]==2&&!m_req_valid,"no-owner rejected");
    send(1,frame(203,1,32'h100,0,4'hf)); check(s_rsp_status[1]==2&&!m_req_valid,"no-owner raw read rejected");
    send(1,frame(204,2,32'h100,0,4'hf)); check(s_rsp_status[1]==2&&!m_req_valid,"no-owner raw write rejected");
    acquire(0,23);
    for(i=0;i<5;i=i+1) begin
      send(1,frame(16'(24+i),8'(8'h41+i),32'(32'h200+i),512'(i+1),4'hf));
      check(s_rsp_valid[1]&&s_rsp_status[1]==2&&!m_req_valid,"nonowner opcode class denied");
    end
    // Backpressure retains all 604 bits; changing unaccepted source pins is harmless.
    backend(0,40); saved=m_req; check(!s_req_ready[0]&&!s_req_ready[1],"single outstanding blocks next frame");
    @(negedge clk); s_req[0]=~s_req[0]; s_req[1]=~s_req[1]; repeat(3) begin tick(); check(m_req_valid&&m_req==saved,"offered frame stable"); end
    // release cannot be accepted while the backend response is outstanding.
    d=0; d[31:0]=2; @(negedge clk); s_req[0]=frame(41,2,32'h60c,d,4'hf); s_req_valid=1;
    #1; check(!s_req_ready[0],"release blocked while offered"); s_req_valid=0;
    @(negedge clk); m_req_ready=1; tick(); check(!m_req_valid,"request accepted once");
    @(negedge clk); m_req_ready=0; s_req[0]=frame(41,2,32'h60c,512'd2,4'hf); s_req_valid=1;
    #1; check(!s_req_ready[0],"release blocked while waiting for response"); s_req_valid=0;
    m_rsp_seq=40; m_rsp_data=512'h1234; m_rsp_status=0; m_rsp_valid=1;
    tick(); check(s_rsp_valid[0]&&s_rsp_data[0]==512'h1234&&s_rsp_seq[0]==40,"backend response routing");
    @(negedge clk); m_rsp_valid=0; release_owner(0,42); check(owner==0,"release after response");
    acquire(1,43); check(lease_epoch==4,"next owner epoch increments"); release_owner(1,44); acquire(0,59);

    // Malformed management fields and aliases fail locally; raw unknown opcodes pass through.
    d=0; mgmt(0,45,1,32'h600,512'd1,2,0);
    send(0,frame(46,1,32'h600,0,4'h0)); check(s_rsp_status[0]==2,"bad management strobe rejected");
    send(0,frame(47,2,32'h600,0,4'hf)); check(s_rsp_status[0]==3,"readonly register write DECERR");
    mgmt(0,48,1,32'h601,0,3,0);
    mgmt(0,49,1,32'h620,0,3,0);
    d=0; d[31:0]=3; mgmt(0,56,2,32'h60c,d,2,0);
    d=0; d[32]=1; mgmt(0,58,2,32'h60c,d,2,0);
    send(0,frame(56,8'hff,32'habcdef01,512'h99887766,4'h5));
    check(m_req_valid&&m_req==s_req[0],"unknown raw opcode forwarded unchanged");
    @(negedge clk); m_req_ready=1; tick(); @(negedge clk); m_req_ready=0;
    m_rsp_seq=56;m_rsp_status=8'h02;m_rsp_data=0;m_rsp_valid=1;tick();
    check(s_rsp_valid[0]&&s_rsp_status[0]==2&&s_rsp_data[0]==0,"backend error response passed through");
    @(negedge clk);m_rsp_valid=0;
    // A response on the acceptance edge must complete exactly once.
    send(0,frame(57,8'h42,32'h88776655,512'h123456,4'hf));
    @(negedge clk);m_req_ready=1;m_rsp_valid=1;m_rsp_seq=57;m_rsp_status=0;m_rsp_data=512'h7654321;
    tick();check(s_rsp_valid[0]&&s_rsp_seq[0]==57&&s_rsp_data[0]==512'h7654321,"zero-latency accept and response");
    @(negedge clk);m_req_ready=0;m_rsp_valid=0;

    release_owner(0,60);
    // Atomic same-edge management contenders: one winner, other sees occupied state.
    @(negedge clk); s_req[0]=frame(50,2,32'h60c,{{480'd0,32'd1}},4'hf);
    s_req[1]=frame(51,2,32'h60c,{{480'd0,32'd1}},4'hf); s_req_valid=2'b11;
    #1; check($onehot(s_req_ready),"simultaneous claim one winner");
    i=s_req_ready[0]?0:1; tick(); @(negedge clk); s_req_valid=0;
    check(owner==(i==0?1:2),"atomic winner owns lease");
    check(s_rsp_valid[i],"claim winner response");
    // Losing contender is serviced next and rejected as occupied.
    mgmt(1-i,52,2,32'h60c,{{480'd0,32'd1}},2,0);
    release_owner(i,53); acquire(0,54);

    // Protocol fault classes are sticky and management diagnostics stay readable.
    backend(0,60); link_healthy[0]=0; tick(); check(failed&&failure_code==1&&!m_req_valid,"link loss fault1 blocks offer");
    mgmt(1,61,1,32'h618,0,0,512'd1); d=0;d[31:0]=2;mgmt(1,62,2,32'h60c,d,2,0);
    reset_all(); release_ready=1; acquire(0,63); @(negedge clk); m_rsp_valid=1;m_rsp_seq=0;m_rsp_data=0;m_rsp_status=0;
    tick();check(failed&&failure_code==2,"unsolicited response fault2");
    check(!m_req_valid&&$onehot(s_req_ready),"fault permits management-only arbitration");
    reset_all(); release_ready=1; acquire(0,64); backend(0,65); m_req_ready=1;tick(); @(negedge clk);m_req_ready=0;
    m_rsp_valid=1;m_rsp_seq=66;m_rsp_data=0;m_rsp_status=0;tick();check(failed&&failure_code==3,"wrong sequence fault3");
    reset_all(); release_ready=1; acquire(0,67); backend(0,68);m_req_ready=1;tick();@(negedge clk);m_req_ready=0;
    m_rsp_valid=1;m_rsp_seq=68;m_rsp_data=512'h1;m_rsp_status=8'h02;tick();check(failed&&failure_code==4,"error payload fault4");
    reset_all(); release_ready=1; acquire(0,69); backend(0,70);m_req_ready=1;tick();@(negedge clk);m_req_ready=0;
    rst_n=0;m_rsp_valid=0;repeat(2)tick();@(negedge clk);rst_n=1;tick();
    m_rsp_valid=1;m_rsp_seq=70;m_rsp_data=0;m_rsp_status=0;tick();
    check(failed&&failure_code==2,"late old response detected unsolicited");
    reset_all(); check(owner==0&&lease_epoch==0&&!failed&&failure_code==0,"joint reset clears state");
    $display("PASS_RAW_FRAME_OWNER_MUX checks=%0d",checks); $finish;
  end
endmodule
