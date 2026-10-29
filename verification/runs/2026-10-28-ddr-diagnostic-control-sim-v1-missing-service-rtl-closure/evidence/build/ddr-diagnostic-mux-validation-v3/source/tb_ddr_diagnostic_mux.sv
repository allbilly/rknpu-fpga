`timescale 1ns/1ps
module tb_ddr_diagnostic_mux #(
  parameter int unsigned ADDR_WIDTH=31,
  parameter int unsigned DATA_WIDTH=512,
  parameter int unsigned ID_WIDTH=4
);
  logic joint_rst_n, diagnostic_selected;
  logic [1:0][ID_WIDTH-1:0] s_awid,s_arid;
  logic [1:0][ADDR_WIDTH-1:0] s_awaddr,s_araddr;
  logic [1:0][7:0] s_awlen,s_arlen;
  logic [1:0][2:0] s_awsize,s_arsize,s_awprot,s_arprot;
  logic [1:0][1:0] s_awburst,s_arburst;
  logic [1:0] s_awlock,s_arlock,s_awvalid,s_wlast,s_wvalid,s_bready,s_arvalid,s_rready;
  logic [1:0][3:0] s_awcache,s_arcache,s_awqos,s_arqos;
  logic [1:0][DATA_WIDTH-1:0] s_wdata;
  logic [1:0][DATA_WIDTH/8-1:0] s_wstrb;
  wire [1:0] s_awready,s_wready,s_bvalid,s_arready,s_rlast,s_rvalid;
  wire [1:0][ID_WIDTH-1:0] s_bid,s_rid;
  wire [1:0][1:0] s_bresp,s_rresp;
  wire [1:0][DATA_WIDTH-1:0] s_rdata;

  wire [ID_WIDTH-1:0] m_awid,m_arid,m_bid,m_rid;
  wire [ADDR_WIDTH-1:0] m_awaddr,m_araddr;
  wire [7:0] m_awlen,m_arlen;
  wire [2:0] m_awsize,m_arsize,m_awprot,m_arprot;
  wire [1:0] m_awburst,m_arburst,m_bresp,m_rresp;
  wire m_awlock,m_arlock,m_awvalid,m_wlast,m_wvalid,m_bready,m_arvalid,m_rready,m_rlast,m_rvalid;
  wire [3:0] m_awcache,m_arcache,m_awqos,m_arqos;
  wire [DATA_WIDTH-1:0] m_wdata,m_rdata;
  wire [DATA_WIDTH/8-1:0] m_wstrb;
  wire m_bvalid,m_awready,m_wready,m_arready;
  logic [ID_WIDTH-1:0] ctrl_bid,ctrl_rid;
  logic [1:0] ctrl_bresp,ctrl_rresp;
  logic [DATA_WIDTH-1:0] ctrl_rdata;
  logic ctrl_bvalid,ctrl_rvalid,ctrl_rlast,ctrl_awready,ctrl_wready,ctrl_arready;
  logic [31:0] rng;
  integer checks;

  rk_ddr_diagnostic_mux #(.ADDR_WIDTH(ADDR_WIDTH),.DATA_WIDTH(DATA_WIDTH),.ID_WIDTH(ID_WIDTH)) dut (
    .joint_rst_n,.diagnostic_selected,
    .s_axi_awid(s_awid),.s_axi_arid(s_arid),.s_axi_awaddr(s_awaddr),.s_axi_araddr(s_araddr),
    .s_axi_awlen(s_awlen),.s_axi_arlen(s_arlen),.s_axi_awsize(s_awsize),.s_axi_arsize(s_arsize),
    .s_axi_awburst(s_awburst),.s_axi_arburst(s_arburst),.s_axi_awlock(s_awlock),.s_axi_arlock(s_arlock),
    .s_axi_awcache(s_awcache),.s_axi_arcache(s_arcache),.s_axi_awprot(s_awprot),.s_axi_arprot(s_arprot),
    .s_axi_awqos(s_awqos),.s_axi_arqos(s_arqos),.s_axi_awvalid(s_awvalid),.s_axi_awready(s_awready),
    .s_axi_wdata(s_wdata),.s_axi_wstrb(s_wstrb),.s_axi_wlast(s_wlast),.s_axi_wvalid(s_wvalid),.s_axi_wready(s_wready),
    .s_axi_bid(s_bid),.s_axi_bresp(s_bresp),.s_axi_bvalid(s_bvalid),.s_axi_bready(s_bready),
    .s_axi_arvalid(s_arvalid),.s_axi_arready(s_arready),.s_axi_rid(s_rid),.s_axi_rdata(s_rdata),
    .s_axi_rresp(s_rresp),.s_axi_rlast(s_rlast),.s_axi_rvalid(s_rvalid),.s_axi_rready(s_rready),
    .m_axi_awid(m_awid),.m_axi_arid(m_arid),.m_axi_awaddr(m_awaddr),.m_axi_araddr(m_araddr),
    .m_axi_awlen(m_awlen),.m_axi_arlen(m_arlen),.m_axi_awsize(m_awsize),.m_axi_arsize(m_arsize),
    .m_axi_awburst(m_awburst),.m_axi_arburst(m_arburst),.m_axi_awlock(m_awlock),.m_axi_arlock(m_arlock),
    .m_axi_awcache(m_awcache),.m_axi_arcache(m_arcache),.m_axi_awprot(m_awprot),.m_axi_arprot(m_arprot),
    .m_axi_awqos(m_awqos),.m_axi_arqos(m_arqos),.m_axi_awvalid(m_awvalid),.m_axi_awready(m_awready),
    .m_axi_wdata(m_wdata),.m_axi_wstrb(m_wstrb),.m_axi_wlast(m_wlast),.m_axi_wvalid(m_wvalid),.m_axi_wready(m_wready),
    .m_axi_bid(m_bid),.m_axi_bresp(m_bresp),.m_axi_bvalid(m_bvalid),.m_axi_bready(m_bready),
    .m_axi_arvalid(m_arvalid),.m_axi_arready(m_arready),.m_axi_rid(m_rid),.m_axi_rdata(m_rdata),
    .m_axi_rresp(m_rresp),.m_axi_rlast(m_rlast),.m_axi_rvalid(m_rvalid),.m_axi_rready(m_rready)
  );
  assign m_bid=ctrl_bid; assign m_bresp=ctrl_bresp; assign m_bvalid=ctrl_bvalid;
  assign m_rid=ctrl_rid; assign m_rdata=ctrl_rdata; assign m_rresp=ctrl_rresp;
  assign m_rlast=ctrl_rlast; assign m_rvalid=ctrl_rvalid;
  assign m_awready=ctrl_awready; assign m_wready=ctrl_wready; assign m_arready=ctrl_arready;

  function automatic [31:0] next_rand;
    begin rng=rng*32'd1664525+32'd1013904223; next_rand=rng; end
  endfunction
  task automatic ck(input logic ok,input string msg);
    begin checks=checks+1; if(ok!==1'b1) $fatal(1,"CHECK %s",msg); end
  endtask
  task automatic check_outputs(input integer sel,input string phase);
    integer other;
    begin
      other=1-sel;
      ck(m_awid===s_awid[sel],{phase," AWID"}); ck(m_awaddr===s_awaddr[sel],{phase," AWADDR"});
      ck(m_awlen===s_awlen[sel],{phase," AWLEN"}); ck(m_awsize===s_awsize[sel],{phase," AWSIZE"});
      ck(m_awburst===s_awburst[sel],{phase," AWBURST"}); ck(m_awlock===s_awlock[sel],{phase," AWLOCK"});
      ck(m_awcache===s_awcache[sel],{phase," AWCACHE"}); ck(m_awprot===s_awprot[sel],{phase," AWPROT"}); ck(m_awqos===s_awqos[sel],{phase," AWQOS"});
      ck(m_arid===s_arid[sel],{phase," ARID"}); ck(m_araddr===s_araddr[sel],{phase," ARADDR"});
      ck(m_arlen===s_arlen[sel],{phase," ARLEN"}); ck(m_arsize===s_arsize[sel],{phase," ARSIZE"});
      ck(m_arburst===s_arburst[sel],{phase," ARBURST"}); ck(m_arlock===s_arlock[sel],{phase," ARLOCK"});
      ck(m_arcache===s_arcache[sel],{phase," ARCACHE"}); ck(m_arprot===s_arprot[sel],{phase," ARPROT"}); ck(m_arqos===s_arqos[sel],{phase," ARQOS"});
      ck(m_wdata===s_wdata[sel],{phase," WDATA"}); ck(m_wstrb===s_wstrb[sel],{phase," WSTRB"}); ck(m_wlast===s_wlast[sel],{phase," WLAST"});
      ck(m_awvalid===s_awvalid[sel],{phase," AWVALID"}); ck(m_wvalid===s_wvalid[sel],{phase," WVALID"}); ck(m_arvalid===s_arvalid[sel],{phase," ARVALID"});
      ck(s_awready[sel]===m_awready && s_awready[other]===0,{phase," AWREADY selection"});
      ck(s_wready[sel]===m_wready && s_wready[other]===0,{phase," WREADY selection"});
      ck(s_arready[sel]===m_arready && s_arready[other]===0,{phase," ARREADY selection"});
      ck(m_bready===s_bready[sel],{phase," BREADY route"}); ck(m_rready===s_rready[sel],{phase," RREADY route"});
      ck(s_bvalid[sel]===m_bvalid && s_bvalid[other]===0,{phase," BVALID selection"});
      ck(s_rvalid[sel]===m_rvalid && s_rvalid[other]===0,{phase," RVALID selection"});
      // AXI response payloads are broadcast; only the selected VALID qualifies them.
      ck(s_bid[0]===m_bid && s_bid[1]===m_bid,{phase," BID broadcast"});
      ck(s_bresp[0]===m_bresp && s_bresp[1]===m_bresp,{phase," BRESP broadcast"});
      ck(s_rid[0]===m_rid && s_rid[1]===m_rid,{phase," RID broadcast"});
      ck(s_rdata[0]===m_rdata && s_rdata[1]===m_rdata,{phase," RDATA broadcast"});
      ck(s_rresp[0]===m_rresp && s_rresp[1]===m_rresp,{phase," RRESP broadcast"});
      ck(s_rlast[0]===m_rlast && s_rlast[1]===m_rlast,{phase," RLAST broadcast"});
    end
  endtask
  task automatic drive_random(input integer sel);
    integer k; logic [31:0] rand_word;
    begin
      diagnostic_selected=sel;
      for(k=0;k<2;k=k+1) begin
        s_awid[k]=next_rand(); s_arid[k]=next_rand(); s_awaddr[k]=next_rand(); s_araddr[k]=next_rand();
        s_awlen[k]=next_rand(); s_arlen[k]=next_rand(); s_awsize[k]=next_rand(); s_arsize[k]=next_rand();
        s_awburst[k]=next_rand(); s_arburst[k]=next_rand(); s_awlock[k]=next_rand(); s_arlock[k]=next_rand();
        s_awcache[k]=next_rand(); s_arcache[k]=next_rand(); s_awprot[k]=next_rand(); s_arprot[k]=next_rand();
        s_awqos[k]=next_rand(); s_arqos[k]=next_rand(); s_wlast[k]=next_rand();
      end
      // Icarus requires a constant first index when a variable part-select is used.
      for(integer b=0;b<DATA_WIDTH/32;b=b+1) begin s_wdata[0][b*32 +:32]=next_rand(); s_wdata[1][b*32 +:32]=next_rand(); end
      for(integer b=0;b<DATA_WIDTH/8;b=b+1) begin rand_word=next_rand(); s_wstrb[0][b]=rand_word[0]; rand_word=next_rand(); s_wstrb[1][b]=rand_word[0]; end
      // Both masters request simultaneously; only selected READY may pass.
      s_awvalid=2'b11; s_wvalid=2'b11; s_arvalid=2'b11;
      ctrl_awready=0; ctrl_wready=0; ctrl_arready=0;
      ctrl_bid=next_rand(); ctrl_bresp=next_rand(); ctrl_bvalid=1;
      ctrl_rid=next_rand(); ctrl_rresp=next_rand(); ctrl_rlast=next_rand(); ctrl_rvalid=1;
      for(integer b=0;b<DATA_WIDTH/32;b=b+1) ctrl_rdata[b*32 +:32]=next_rand();
      s_bready=sel ? 2'b01 : 2'b10; s_rready=sel ? 2'b01 : 2'b10;
      #1; check_outputs(sel,"stall-start");
      repeat(2) begin #1; check_outputs(sel,"held-stall"); end
      s_bready[sel]=1; s_rready[sel]=1;
      #1; check_outputs(sel,"response-accept");
      ctrl_bvalid=0; ctrl_rvalid=0;
      #1; check_outputs(sel,"response-retired");
      // Leave VALID asserted until the corresponding selected READY is high.
      ctrl_awready=1; ctrl_wready=1; ctrl_arready=1;
      #1; check_outputs(sel,"accept");
      s_awvalid[sel]=0; s_wvalid[sel]=0; s_arvalid[sel]=0;
      ctrl_bvalid=0; ctrl_rvalid=0;
      #1; check_outputs(sel,"after-accept");
      s_awvalid=0; s_wvalid=0; s_arvalid=0; s_bready=0; s_rready=0;
    end
  endtask

  integer sel,iter;
  logic simulated_fault,simulated_done;
  initial begin
    rng=32'h00003588; checks=0;
    joint_rst_n=0; diagnostic_selected=0; s_awid='0; s_arid='0; s_awaddr='0; s_araddr='0;
    s_awlen='0; s_arlen='0; s_awsize='0; s_arsize='0; s_awburst='0; s_arburst='0; s_awlock='0; s_arlock='0;
    s_awcache='0; s_arcache='0; s_awprot='0; s_arprot='0; s_awqos='0; s_arqos='0; s_awvalid=0; s_wdata='0; s_wstrb='0; s_wlast=0; s_wvalid=0; s_bready=0;
    s_arvalid=0; s_rready=0; ctrl_bid=0; ctrl_bresp=0; ctrl_bvalid=0; ctrl_rid=0; ctrl_rdata='0; ctrl_rresp=0; ctrl_rlast=0; ctrl_rvalid=0;
    ctrl_awready=0; ctrl_wready=0; ctrl_arready=0; simulated_fault=0; simulated_done=0;
    #1; ck(m_awvalid===0 && m_wvalid===0 && m_arvalid===0 && m_bready===0 && m_rready===0,"joint reset gates master handshakes");
    ck(s_awready===0 && s_wready===0 && s_arready===0 && s_bvalid===0 && s_rvalid===0,"joint reset gates slave handshakes");
    joint_rst_n=1;
    // Seeded random fields exercise the complete forwarding bundle for each documented interface shape and selection.
    for(sel=0;sel<2;sel=sel+1) begin
      diagnostic_selected=sel; #1;
      for(iter=0;iter<48;iter=iter+1) drive_random(sel);
      // External completion/fault flags do not alter this leaf; caller holds selection stable through both.
      diagnostic_selected=sel; simulated_fault=1; simulated_done=0;
      s_awvalid[sel]=1; s_wvalid[sel]=1; s_arvalid[sel]=1; ctrl_awready=0; ctrl_wready=0; ctrl_arready=0;
      ctrl_bvalid=1; ctrl_rvalid=1; s_bready='1; s_rready='1; #1;
      ck(simulated_fault===1 && diagnostic_selected===sel,"external fault retains selected owner"); check_outputs(sel,"selected-fault-held");
      simulated_fault=0; simulated_done=1; #1; ck(simulated_done===1 && diagnostic_selected===sel,"external done retains selected owner"); check_outputs(sel,"selected-done-held");
      // Selection changes only after every request and response is idle (ownership gate is external).
      s_awvalid=0; s_wvalid=0; s_arvalid=0; ctrl_bvalid=0; ctrl_rvalid=0; s_bready=0; s_rready=0; simulated_done=0;
      #1; diagnostic_selected=1-sel; #1; ck(diagnostic_selected===1-sel,"idle selector change supplied by owner");
    end
    // Reset gates only handshakes; selected payloads and broadcast return payloads remain combinationally intact.
    diagnostic_selected=1; drive_random(1); s_awvalid=2'b11; s_wvalid=2'b11; s_arvalid=2'b11;
    ctrl_awready=1; ctrl_wready=1; ctrl_arready=1; ctrl_bvalid=1; ctrl_rvalid=1;
    begin
      logic [ID_WIDTH-1:0] old_awid; logic [ADDR_WIDTH-1:0] old_araddr; logic [DATA_WIDTH-1:0] old_wdata,old_rdata;
      old_awid=m_awid; old_araddr=m_araddr; old_wdata=m_wdata; old_rdata=m_rdata;
      joint_rst_n=0; #1;
      ck(m_awid===old_awid && m_araddr===old_araddr && m_wdata===old_wdata && m_rdata===old_rdata,"reset preserves selected payloads");
      ck(m_awvalid===0 && m_wvalid===0 && m_arvalid===0 && m_bready===0 && m_rready===0,"reset gates all master handshakes");
      ck(s_awready===0 && s_wready===0 && s_arready===0 && s_bvalid===0 && s_rvalid===0,"reset gates all slave handshakes");
    end
    $display("PASS diagnostic_mux checks=%0d addr=%0d data=%0d id=%0d seed=3588",checks,ADDR_WIDTH,DATA_WIDTH,ID_WIDTH);
    $finish;
  end
endmodule
