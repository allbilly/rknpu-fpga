`timescale 1ns/1ps
module tb_pcie_dma_decerr;
`ifdef VERILATOR_NATIVE
  localparam integer FOUR_STATE=0;
`else
  localparam integer FOUR_STATE=1;
`endif
  logic clk, rst_n=0;
  initial begin clk=0; forever #5 clk=~clk; end
  wire protocol_fault,awready,wready,bvalid,arready,rvalid,rlast;
  wire [3:0] bid,rid;
  wire [1:0] bresp,rresp;
  wire [127:0] rdata;
  logic [3:0] awid=0,arid=0;
  logic [63:0] awaddr=0,araddr=0;
  logic [7:0] awlen=0,arlen=0;
  logic [2:0] awsize=0,arsize=0,awprot=0,arprot=0;
  logic [1:0] awburst=1,arburst=1;
  logic awvalid=0,awlock=0,arvalid=0,arlock=0;
  logic [3:0] awcache=0,arcache=0;
  logic [127:0] wdata=0;
  logic [15:0] wstrb=0;
  logic wlast=0,wvalid=0,bready=0,rready=0;
  rk_pcie_dma_decerr dut(.*,
    .s_axi_awready(awready),.s_axi_wready(wready),.s_axi_bid(bid),.s_axi_bresp(bresp),.s_axi_bvalid(bvalid),
    .s_axi_arready(arready),.s_axi_rid(rid),.s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rlast(rlast),.s_axi_rvalid(rvalid),
    .s_axi_awid(awid),.s_axi_awaddr(awaddr),.s_axi_awlen(awlen),.s_axi_awsize(awsize),.s_axi_awburst(awburst),
    .s_axi_awprot(awprot),.s_axi_awvalid(awvalid),.s_axi_awlock(awlock),.s_axi_awcache(awcache),
    .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wlast(wlast),.s_axi_wvalid(wvalid),.s_axi_bready(bready),
    .s_axi_arid(arid),.s_axi_araddr(araddr),.s_axi_arlen(arlen),.s_axi_arsize(arsize),.s_axi_arburst(arburst),
    .s_axi_arprot(arprot),.s_axi_arvalid(arvalid),.s_axi_arlock(arlock),.s_axi_arcache(arcache),.s_axi_rready(rready));

  integer check_count;
  task automatic check(input logic cond,input string msg);
    begin
      check_count=check_count+1;
      if(cond!==1'b1) $fatal(1,"CHECK_FAIL %s",msg);
    end
  endtask
  task automatic tick;
    @(posedge clk); #1;
  endtask
  task automatic reset_leaf;
    @(negedge clk); rst_n=0; awvalid=0; wvalid=0; arvalid=0; bready=0; rready=0;
    awid=0; awlen=0; arid=0; arlen=0;
    #1; check(protocol_fault===0 && bvalid===0 && rvalid===0 && awready===0 && arready===0,"reset clears outputs/fault");
    repeat(2) tick();
    @(negedge clk); rst_n=1;
    tick();
    check(protocol_fault===0 && awready===1 && arready===1,"reset release ready");
  endtask
  task automatic send_aw(input [3:0] id,input [63:0] addr,input [7:0] len);
    integer n; logic accepted;
    begin
      @(negedge clk); awid=id; awaddr=addr; awlen=len; awsize=3'b101; awburst=2'b10;
      awprot=3'b111; awlock=1; awcache=4'hf; awvalid=1;
      n=0; accepted=0;
      while(!accepted)begin @(posedge clk); accepted=(awready===1); #1; n=n+1; if(n>20)$fatal(1,"AW handshake timeout"); end
      @(negedge clk); awvalid=0;
    end
  endtask
  task automatic send_ar(input [3:0] id,input [63:0] addr,input [7:0] len);
    integer n; logic accepted;
    begin
      @(negedge clk); arid=id; araddr=addr; arlen=len; arsize=3'b001; arburst=2'b00;
      arprot=3'b101; arlock=0; arcache=4'h3; arvalid=1;
      n=0; accepted=0;
      while(!accepted)begin @(posedge clk); accepted=(arready===1); #1; n=n+1; if(n>20)$fatal(1,"AR handshake timeout"); end
      @(negedge clk); arvalid=0;
    end
  endtask
  task automatic send_w(input [7:0] len,input integer first_index,input integer last_index);
    integer i,n; logic accepted;
    begin
      for(i=first_index;i<=last_index;i=i+1)begin
        if(!(first_index==0 && i==0 && wvalid===1)) begin
          @(negedge clk); wvalid=1; wlast=(i==int'(len)); wdata={4{32'h87654321^i}}; wstrb=16'hffff^(16'(i));
        end
        n=0; accepted=0;
        while(!accepted)begin @(posedge clk); accepted=(wready===1); #1; n=n+1; if(n>20)$fatal(1,"W handshake timeout beat=%0d",i); end
      end
      @(negedge clk); wvalid=0;
    end
  endtask
  task automatic accept_b(input [3:0] id);
    begin
      #1; check(bvalid===1 && bresp===2'b11 && bid===id,"B DECERR/id");
      repeat(3)begin tick(); check(bvalid===1 && bresp===2'b11 && bid===id,"held B stability"); end
      @(negedge clk); bready=1; tick();
      @(negedge clk); bready=0; #1; check(bvalid===0,"B consumed");
    end
  endtask
  task automatic write_burst(input [7:0] len,input [3:0] id,input [63:0] addr,input integer order);
    integer i,n; logic accepted;
    begin
      if(order==0)begin send_aw(id,addr,len); send_w(len,0,int'(len)); end
      else begin
        @(negedge clk); wvalid=1; wlast=(len==0); wdata=128'h00112233445566778899aabbccddeeff; wstrb=16'ha55a;
        repeat(2)begin tick(); check(wready===0,"W waits before AW"); end
        if(order==1)begin send_aw(id,addr,len); i=1; end
        else begin
          @(negedge clk); awid=id; awaddr=addr; awlen=len; awsize=3'b111; awburst=2'b11;
          awprot=0; awlock=0; awcache=0; awvalid=1;
          @(posedge clk); check(awready===1 && wready===0,"simultaneous AW/W accepts address first"); #1;
          @(negedge clk); awvalid=0; i=1;
        end
        n=0; accepted=0;
        while(!accepted)begin @(posedge clk); accepted=(wready===1); #1; n=n+1; if(n>20)$fatal(1,"held first W timeout"); end
        for(i=1;i<=len;i=i+1)begin
          @(negedge clk); wlast=(i==int'(len)); wdata={4{32'habc00000+i}}; wstrb=16'hf0f0;
          @(posedge clk); check(wready===1,"W burst drains"); #1;
        end
        @(negedge clk); wvalid=0;
      end
      accept_b(id);
      check(protocol_fault===0,"valid write leaves fault clear");
    end
  endtask
  task automatic read_burst(input [7:0] len,input [3:0] id,input [63:0] addr,input logic stall_first,input logic stall_last);
    integer i,n;
    begin
      send_ar(id,addr,len);
      @(negedge clk); rready=0;
      for(i=0;i<=len;i=i+1)begin
        n=0;
        do begin tick(); n=n+1; if(n>20)$fatal(1,"RVALID timeout beat=%0d",i); end while(rvalid!==1);
        check(rid===id && rdata===128'b0 && rresp===2'b11 && rlast===(i==int'(len)),"R beat identity/data/DECERR/LAST");
        if((i==0 && stall_first)||(i==int'(len) && stall_last))begin
          repeat(3)begin tick(); check(rvalid===1 && rid===id && rdata===0 && rresp===3 && rlast===(i==int'(len)),"held R stability"); end
        end
        @(negedge clk); rready=1; tick();
        @(negedge clk); rready=0;
      end
      #1; check(rvalid===0 && protocol_fault===0,"read burst completes cleanly");
    end
  endtask
  task automatic protocol_fault_reset;
    begin
      reset_leaf();
      send_aw(4'hc,64'hffff_ffff_ffff_ffff,8'd2);
      @(negedge clk); wvalid=1; wlast=0; wdata=128'h1; wstrb=16'hffff; tick();
      check(wready===1,"partial burst accepted");
      reset_leaf(); check(wready===0 && protocol_fault===0,"reset abandons partial burst");
      send_ar(4'hd,64'h8000_0000_0000_0001,8'd2);
      #1; check(rvalid===1,"read response held before reset");
      reset_leaf(); check(rvalid===0 && rlast===0,"reset clears held read response");
      send_aw(4'ha,64'hffff_ffff_ffff_ffff,0);
      @(negedge clk); wvalid=1; wlast=1; tick(); @(negedge clk); wvalid=0;
      #1; check(bvalid===1 && bid===4'ha && bresp===3,"B response held before reset");
      reset_leaf(); check(bvalid===0,"reset clears held B response");
      write_burst(0,4'h3,64'h0123_4567_89ab_cdef,0);
      read_burst(0,4'h4,64'hfedc_ba98_7654_3210,1,1);
    end
  endtask
  task automatic wlast_early_case;
    begin
      reset_leaf(); send_aw(4'h6,64'h0000_0000_0000_1000,8'd2);
      @(negedge clk); wvalid=1; wlast=1; wdata=1; wstrb=16'hffff; tick();
      check(protocol_fault===1 && wready===1,"early WLAST faults but keeps accepted burst drainable");
      check(awready===0 && arready===0,"fault blocks new addresses");
      @(negedge clk); wlast=0; tick(); check(wready===1,"drain middle beat after fault");
      @(negedge clk); wlast=1; tick(); @(negedge clk); wvalid=0;
      accept_b(4'h6); check(protocol_fault===1 && awready===0 && arready===0,"fault sticky after early-WLAST response");
    end
  endtask
  task automatic wlast_missing_case(input [7:0] len,input [3:0] id);
    integer i;
    begin
      reset_leaf(); send_aw(id,64'h0000_1000_0000_0000,len);
      for(i=0;i<=len;i=i+1)begin
        @(negedge clk); wvalid=1; wlast=0;
        @(posedge clk); check(wready===1,"missing-WLAST accepted beat drains"); #1;
      end
      @(negedge clk); wvalid=0;
      check(protocol_fault===1,"missing final WLAST faults");
      @(negedge clk); wvalid=1; wlast=1;
      repeat(2)begin tick(); check(wready===0 && bvalid===1 && bid===id && bresp===3,
        "late WLAST cannot be accepted after the declared final beat"); end
      @(negedge clk); wvalid=0;
      accept_b(id); check(awready===0 && arready===0,"missing-WLAST fault blocks addresses");
    end
  endtask
  task automatic fault_while_read_pending;
    integer i;
    begin
      reset_leaf(); send_ar(4'hc,64'hffff_0000_0000_0000,8'd1);
      #1; check(rvalid===1 && rid===4'hc && rlast===0 && rresp===3 && rdata===0,
        "accepted read response held before unrelated write fault");
      send_aw(4'hd,64'h8000_0000_0000_0001,0);
      @(negedge clk); wvalid=1; wlast=0; wdata=128'hfedcba9876543210; wstrb=16'h1234;
      @(posedge clk); check(wready===1,"faulting write beat accepted"); #1;
      check(protocol_fault===1 && bvalid===1 && bid===4'hd && bresp===3 &&
            rvalid===1 && rid===4'hc && rlast===0 && rresp===3 && rdata===0,
        "write protocol fault retains read and write error responses");
      check(awready===0 && arready===0,"fault blocks new addresses while responses are pending");
      @(negedge clk); wvalid=0; rready=1;
      for(i=0;i<2;i=i+1)begin
        @(posedge clk); check(rvalid===1 && rid===4'hc && rresp===3 && rdata===0 && rlast===(i==1),
          "accepted read burst drains after protocol fault"); #1;
      end
      @(negedge clk); rready=0;
      check(rvalid===0 && protocol_fault===1 && bvalid===1,"read drains without clearing sticky fault or B response");
      accept_b(4'hd); check(protocol_fault===1 && awready===0 && arready===0,
        "fault remains sticky after both accepted channels drain");
    end
  endtask
  task automatic concurrent_rw;
    integer i;
    begin
      reset_leaf();
      @(negedge clk); awid=4'h2; awaddr=64'h8000_0000_0000_0000; awlen=2; awvalid=1;
      arid=4'he; araddr=64'hffff_0000_0000_0000; arlen=2; arvalid=1; rready=1;
      @(posedge clk); check(awready===1 && arready===1,"concurrent AW/AR accepted"); #1;
      @(negedge clk); awvalid=0; arvalid=0; wvalid=1; wlast=0; wstrb=16'h0; wdata=0;
      for(i=0;i<3;i=i+1)begin
        @(posedge clk); check(rvalid===1 && rid===4'he && rresp===3 && rdata===0 && rlast===(i==2),"concurrent read beat"); #1;
        if(i<2)begin @(negedge clk); wlast=(i==1); end
      end
      @(negedge clk); wvalid=0; rready=0;
      accept_b(4'h2); check(protocol_fault===0,"concurrent channels complete");
    end
  endtask
`ifndef VERILATOR_NATIVE
  task automatic unknown_address_tests;
    begin
      reset_leaf(); @(negedge clk); awvalid=1; awid=4'bx001; awlen=0; tick();
      check(protocol_fault===1 && bvalid===0 && awready===0,"unknown AWID faults without response");
      reset_leaf(); @(negedge clk); awvalid=1; awid=4'bz001; awlen=0; tick();
      check(protocol_fault===1 && bvalid===0 && awready===0,"Z AWID faults without response");
      reset_leaf(); @(negedge clk); awvalid=1; awid=4'h1; awlen=8'bz0000000; tick();
      check(protocol_fault===1 && bvalid===0 && awready===0,"unknown AWLEN faults without response");
      reset_leaf(); @(negedge clk); awvalid=1; awid=4'h1; awlen=8'bx0000000; tick();
      check(protocol_fault===1 && bvalid===0 && awready===0,"X AWLEN faults without response");
      reset_leaf(); @(negedge clk); arvalid=1; arid=4'bz101; arlen=0; tick();
      check(protocol_fault===1 && rvalid===0 && arready===0,"unknown ARID faults without response");
      reset_leaf(); @(negedge clk); arvalid=1; arid=4'bx101; arlen=0; tick();
      check(protocol_fault===1 && rvalid===0 && arready===0,"X ARID faults without response");
      reset_leaf(); @(negedge clk); arvalid=1; arid=4'h2; arlen=8'bx0000000; tick();
      check(protocol_fault===1 && rvalid===0 && arready===0,"unknown ARLEN faults without response");
      reset_leaf(); @(negedge clk); arvalid=1; arid=4'h2; arlen=8'bz0000000; tick();
      check(protocol_fault===1 && rvalid===0 && arready===0,"Z ARLEN faults without response");
      reset_leaf(); @(negedge clk); awvalid=1'bx; awid=0; awlen=0; tick();
      check(protocol_fault===1 && bvalid===0,"X AWVALID faults without response");
      reset_leaf(); @(negedge clk); awvalid=1'bz; awid=0; awlen=0; tick();
      check(protocol_fault===1 && bvalid===0,"Z AWVALID faults without response");
      reset_leaf(); @(negedge clk); wvalid=1'bx; tick(); check(protocol_fault===1 && bvalid===0,"X WVALID faults");
      reset_leaf(); @(negedge clk); wvalid=1'bz; tick(); check(protocol_fault===1 && bvalid===0,"Z WVALID faults");
      reset_leaf(); send_aw(4'hb,64'h0,0); @(negedge clk); wvalid=1'bx; wlast=1; tick();
      check(protocol_fault===1 && wready===1 && bvalid===0,"unknown WVALID faults but does not consume accepted beat");
      @(negedge clk); wvalid=1; wlast=1; @(posedge clk); check(wready===1,"known WVALID drains after unknown"); #1;
      @(negedge clk); wvalid=0; accept_b(4'hb); check(protocol_fault===1,"unknown WVALID fault remains sticky after drain");
      reset_leaf(); @(negedge clk); arvalid=1'bx; arid=0; arlen=0; tick();
      check(protocol_fault===1 && rvalid===0,"X ARVALID faults without response");
      reset_leaf(); @(negedge clk); arvalid=1'bz; arid=0; arlen=0; tick();
      check(protocol_fault===1 && rvalid===0,"Z ARVALID faults without response");
    end
  endtask
`endif
  initial begin
    check_count=0;
    reset_leaf();
    // Length encodings 0,1,254,255 represent 1,2,255,256 beats.
    write_burst(0,4'h1,64'h0,0);
    write_burst(1,4'h2,64'hffff_ffff_ffff_ffff,1);
    write_burst(254,4'h3,64'h8000_0000_0000_0001,2);
    write_burst(255,4'h4,64'h0000_0000_0000_0003,0);
    read_burst(0,4'h5,64'h0,1,1);
    read_burst(1,4'h6,64'hffff_ffff_ffff_ffff,0,1);
    read_burst(254,4'h7,64'h8000_0000_0000_0001,1,0);
    read_burst(255,4'h8,64'h0000_0000_0000_0003,0,1);
    concurrent_rw();
    wlast_early_case();
    wlast_missing_case(0,4'h7);
    wlast_missing_case(1,4'h9);
    fault_while_read_pending();
    protocol_fault_reset();
`ifndef VERILATOR_NATIVE
    unknown_address_tests();
`endif
    $display("PASS_PCIE_DMA_DECERR_NATIVE four_state=%0d",FOUR_STATE);
    $display("CHECK_COUNT_PCIE_DMA_DECERR checks=%0d",check_count);
    $finish;
  end
endmodule
