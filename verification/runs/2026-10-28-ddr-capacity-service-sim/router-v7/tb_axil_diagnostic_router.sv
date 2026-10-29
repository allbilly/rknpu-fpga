`timescale 1ns/1ps
module tb_axil_diagnostic_router;
  logic clk;initial clk=0;always #5 clk=~clk;
  logic joint_rst_n;
  logic [31:0] s_awaddr,s_wdata,s_araddr;logic [2:0] s_awprot,s_arprot;
  logic s_awvalid,s_awready,s_wvalid,s_wready,s_bvalid,s_bready,s_arvalid,s_arready,s_rvalid,s_rready;
  logic [3:0] s_wstrb;logic [1:0] s_bresp,s_rresp;logic [31:0] s_rdata;
  logic [1:0][2:0] child_awprot_bus,child_arprot_bus;
  logic [1:0][31:0] child_awaddr,child_araddr,child_wdata,child_rdata;
  logic [1:0][3:0] child_wstrb;
  logic [1:0] child_awready,child_wready,child_bvalid;
  logic [1:0][1:0] child_bresp,child_rresp;
  logic [1:0] child_arready,child_rvalid;
  logic [1:0] child_awvalid,child_wvalid,child_bready;
  logic [1:0] child_arvalid,child_rready;
  integer transactions;

  rk_axil_diagnostic_router dut(
    .clk(clk),.joint_rst_n(joint_rst_n),.s_axil_awaddr(s_awaddr),.s_axil_awprot(s_awprot),
    .s_axil_awvalid(s_awvalid),.s_axil_awready(s_awready),.s_axil_wdata(s_wdata),.s_axil_wstrb(s_wstrb),
    .s_axil_wvalid(s_wvalid),.s_axil_wready(s_wready),.s_axil_bresp(s_bresp),.s_axil_bvalid(s_bvalid),.s_axil_bready(s_bready),
    .s_axil_araddr(s_araddr),.s_axil_arprot(s_arprot),.s_axil_arvalid(s_arvalid),.s_axil_arready(s_arready),
    .s_axil_rdata(s_rdata),.s_axil_rresp(s_rresp),.s_axil_rvalid(s_rvalid),.s_axil_rready(s_rready),
    .m_axil_awaddr(child_awaddr),.m_axil_awprot(child_awprot_bus),.m_axil_awvalid(child_awvalid),.m_axil_awready(child_awready),
    .m_axil_wdata(child_wdata),.m_axil_wstrb(child_wstrb),.m_axil_wvalid(child_wvalid),.m_axil_wready(child_wready),
    .m_axil_bresp(child_bresp),.m_axil_bvalid(child_bvalid),.m_axil_bready(child_bready),
    .m_axil_araddr(child_araddr),.m_axil_arprot(child_arprot_bus),.m_axil_arvalid(child_arvalid),.m_axil_arready(child_arready),
    .m_axil_rdata(child_rdata),.m_axil_rresp(child_rresp),.m_axil_rvalid(child_rvalid),.m_axil_rready(child_rready));

  function automatic logic route_diag(input logic [31:0] address);
    route_diag=(address>=32'h00000200)&&(address<=32'h000002ff);
  endfunction
  function automatic logic [31:0] random_next(input logic [31:0] x);
    logic [31:0] y;begin y=x;y=y^(y<<13);y=y^(y>>17);y=y^(y<<5);random_next=y;end
  endfunction
  function automatic logic [31:0] tag_data(input logic [31:0] addr,input logic [2:0] prot,input integer lane);
    tag_data=(lane==0?32'ha5000000:32'hd1000000)^addr^{29'b0,prot};
  endfunction
  task automatic fail(input string msg);$display("FAIL_AXIL_ROUTER %s",msg);$fatal(1);endtask
  task automatic reset_router;
    begin
      @(negedge clk);joint_rst_n=0;s_awaddr=0;s_awprot=0;s_awvalid=0;s_wdata=0;s_wstrb=0;s_wvalid=0;
      s_bready=0;s_araddr=0;s_arprot=0;s_arvalid=0;s_rready=0;
      child_awready=0;child_wready=0;child_bvalid=0;child_bresp=0;child_arready=0;child_rvalid=0;child_rresp=0;child_rdata=0;
      repeat(2)@(posedge clk);@(negedge clk);joint_rst_n=1;#1;
      if(s_awready!==0||s_wready!==1||s_bvalid!==0||s_arready!==0||s_rvalid!==0||child_awvalid!==0||child_wvalid!==0||
         child_bready!==0||child_arvalid!==0||child_rready!==0)fail("reset did not clear channels/gate VALID");
    end
  endtask

  task automatic write_transaction(input logic [31:0] addr,input logic [2:0] prot,input logic [31:0] data,
       input logic [3:0] strb,input logic [1:0] response,input logic w_before_aw);
    logic [1:0] target,other;
    logic [31:0] captured_data,changed_aw;
    logic [3:0] captured_strb;
    integer sel;
    begin
      sel=route_diag(addr)?1:0;target=(2'b01<<sel);other=2'b11^target;
      captured_data=data;captured_strb=strb;changed_aw=~addr;
      if(w_before_aw)begin
        @(negedge clk);s_wdata=data;s_wstrb=strb;s_wvalid=1;#1;
        if(s_wready!==1)fail("W-before-AW was not buffered/accepted");
        @(posedge clk);#1;@(negedge clk);s_wvalid=0;s_wdata=~data;s_wstrb=~strb;
        if(child_wvalid!==0)fail("buffered W escaped before AW target known");
      end
      @(negedge clk);s_awaddr=addr;s_awprot=prot;s_awvalid=1;
      child_awready=other;#1;
      if(child_awvalid!==target || child_awaddr[sel]!==addr || child_awprot_bus[sel]!==prot)
        fail($sformatf("AW full-address/protection decode mismatch addr=%08x sel=%0d target=%b valid=%b child_addr0=%08x child_addr1=%08x prot=%b child_prot0=%b child_prot1=%b",
          addr,sel,target,child_awvalid,child_awaddr[0],child_awaddr[1],prot,child_awprot_bus[0],child_awprot_bus[1]));
      if(child_awvalid[1-sel]!==0 || s_awready!==0)fail("AW selected/unselected READY/VALID isolation mismatch");
      repeat(2)begin @(posedge clk);#1;if(child_awvalid!==target||child_awaddr[sel]!==addr||child_awprot_bus[sel]!==prot||s_awready!==0)
        fail("AW payload changed while selected child stalled");end
      @(negedge clk);child_awready=2'b11;#1;
      if(s_awready!==1 || child_awvalid!==target)fail("AW selected handshake not passed through");
      @(posedge clk);#1;@(negedge clk);s_awvalid=0;s_awaddr=changed_aw;s_awprot=~prot;child_awready=0;
      if(!w_before_aw)begin
        if(child_wvalid!==0)fail("child WVALID before parent W accepted");
        s_wdata=data;s_wstrb=strb;s_wvalid=1;#1;
        if(s_wready!==1)fail("AW-before-W upstream W not accepted");
        @(posedge clk);#1;@(negedge clk);s_wvalid=0;s_wdata=~data;s_wstrb=~strb;
      end
      #1;if(child_wvalid!==target || child_wdata[sel]!==captured_data || child_wstrb[sel]!==captured_strb)
        fail("buffered child W payload/lane mismatch");
      if(child_wvalid[1-sel]!==0)fail("unselected child saw WVALID");
      child_wready=other;#1;
      repeat(2)begin @(posedge clk);#1;#1;if(child_wvalid!==target || child_wdata[sel]!==captured_data || child_wstrb[sel]!==captured_strb)
        fail("child W payload changed under READY stall");end
      @(negedge clk);child_wready=2'b11;@(posedge clk);#1;@(negedge clk);child_wready=0;
      if(child_bready!==0)fail("BREADY asserted before parent BREADY");
      child_bresp[sel]=response;child_bvalid=target;s_bready=0;#1;
      repeat(2)begin @(posedge clk);#1;
        if(s_bvalid!==1 || s_bresp!==response || child_bready!==0 || child_bready[1-sel]!==0)
          fail("B response target/payload/backpressure routing mismatch");
      end
      s_awaddr=changed_aw;s_awvalid=0;
      @(negedge clk);s_bready=1;#1;
      if(child_bready!==target || s_bvalid!==1 || s_bresp!==response)fail("B selected lane did not receive READY");
      @(posedge clk);#1;@(negedge clk);s_bready=0;child_bvalid=0;
      transactions=transactions+1;
    end
  endtask

  task automatic read_transaction(input logic [31:0] addr,input logic [2:0] prot,input logic [1:0] response);
    logic [1:0] target,other;logic [31:0] changed_addr,expected_data;integer sel;
    begin
      sel=route_diag(addr)?1:0;target=(2'b01<<sel);other=2'b11^target;changed_addr=~addr;
      @(negedge clk);s_araddr=addr;s_arprot=prot;s_arvalid=1;child_arready=other;#1;
      if(child_arvalid!==target || child_araddr[sel]!==addr || child_arprot_bus[sel]!==prot || s_arready!==0)
        fail("AR decode/transparent child selection mismatch");
      repeat(2)begin @(posedge clk);#1;if(child_arvalid!==target || child_araddr[sel]!==addr || child_arprot_bus[sel]!==prot || s_arready!==0)
        fail("AR payload changed while selected child stalled");end
      @(negedge clk);child_arready=2'b11;#1;
      if(s_arready!==1||child_arvalid!==target)fail("parent/child AR handshake was not same-edge");
      @(posedge clk);#1;@(negedge clk);s_arvalid=0;s_araddr=changed_addr;s_arprot=~prot;child_arready=0;
      expected_data=tag_data(addr,prot,sel);child_rdata[sel]=expected_data;child_rresp[sel]=response;child_rvalid=target;s_rready=0;#1;
      repeat(2)begin @(posedge clk);#1;
        if(s_rvalid!==1 || s_rdata!==expected_data || s_rresp!==response || child_rready!==0 || child_rready[1-sel]!==0)
          fail("R snapshot target/data/RESP/backpressure mismatch after frontend address changed");
      end
      @(negedge clk);s_rready=1;#1;
      if(child_rready!==target || s_rvalid!==1)fail("R selected lane did not receive READY");
      @(posedge clk);#1;@(negedge clk);s_rready=0;child_rvalid=0;
      transactions=transactions+1;
    end
  endtask

  task automatic simultaneous_different_targets;
    logic [1:0] awtarget,artarget;
    logic [31:0] rtag;
    begin
      awtarget=2'b10;artarget=2'b01;rtag=tag_data(32'h100,3'b101,0);
      @(negedge clk);s_awaddr=32'h200;s_awprot=3'b011;s_awvalid=1;s_araddr=32'h100;s_arprot=3'b101;s_arvalid=1;
      child_awready=awtarget;child_arready=artarget;#1;
      if(child_awvalid!==awtarget || child_arvalid!==artarget || s_awready!==1 || s_arready!==1)
        fail("independent read/write different-target admission failed");
      @(posedge clk);#1;@(negedge clk);s_awvalid=0;s_arvalid=0;child_awready=0;child_arready=0;
      s_wdata=32'h12345678;s_wstrb=4'b0101;s_wvalid=1;
      if(s_wready!==1)fail("simultaneous test W not accepted");@(posedge clk);#1;@(negedge clk);s_wvalid=0;
      child_wready=awtarget;if(child_wvalid!==awtarget||child_wdata[1]!==32'h12345678||child_wstrb[1]!==4'b0101)
        fail("simultaneous test W target/data mismatch");
      @(posedge clk);#1;@(negedge clk);child_wready=0;
      child_bresp[1]=2'b11;child_bvalid=awtarget;child_rdata[0]=rtag;child_rresp[0]=2'b10;child_rvalid=artarget;
      s_bready=0;s_rready=0;#1;repeat(2)begin @(posedge clk);#1;
        if(s_bvalid!==1||s_bresp!==2'b11||child_bready!==0||s_rvalid!==1||s_rdata!==rtag||s_rresp!==2'b10||child_rready!==0)
          fail("simultaneous independent responses were misrouted");end
      @(negedge clk);s_rready=1;#1;if(child_rready!==artarget||child_bready!==0)fail("independent RREADY isolation failure");
      @(posedge clk);#1;@(negedge clk);s_rready=0;child_rvalid=0;s_bready=1;#1;
      if(child_bready!==awtarget)fail("independent BREADY selected lane failure");
      @(posedge clk);#1;@(negedge clk);s_bready=0;child_bvalid=0;
      transactions=transactions+2;
    end
  endtask

  task automatic no_zero_bubble_reissue;
    logic [1:0] oldtarget,newtarget;
    begin
      oldtarget=2'b10;newtarget=2'b01;
      @(negedge clk);s_awaddr=32'h200;s_awprot=3'b001;s_awvalid=1;child_awready=3;
      @(posedge clk);#1;@(negedge clk);s_awvalid=0;child_awready=0;
      s_wdata=32'h89abcdef;s_wstrb=4'hf;s_wvalid=1;@(posedge clk);#1;@(negedge clk);s_wvalid=0;
      child_wready=3;@(posedge clk);#1;@(negedge clk);child_wready=0;
      child_bresp[1]=2'b01;child_bvalid=oldtarget;s_bready=0;
      s_awaddr=32'h100;s_awprot=3'b110;s_awvalid=1;child_awready=3;
      repeat(2)begin @(posedge clk);#1;
        if(s_awready!==0||child_awvalid!==0||s_bvalid!==1||s_bresp!==2'b01||child_bready!==0)
          fail("new AW reissued while prior B still outstanding");
      end
      @(negedge clk);s_bready=1;@(posedge clk);#1;@(negedge clk);s_bready=0;child_bvalid=0;
      #1;if(s_awready!==1||child_awvalid!==newtarget)fail("held next AW not accepted after B completion bubble");
      @(posedge clk);#1;@(negedge clk);s_awvalid=0;child_awready=0;
      joint_rst_n=0;@(posedge clk);#1;@(negedge clk);child_bvalid=0;child_wready=0;child_awready=0;joint_rst_n=1;
      #1;if(s_awready!==0||s_bvalid!==0||child_awvalid!==0||child_wvalid!==0)
        fail("joint reset did not clear pending router state");
      transactions=transactions+1;
    end
  endtask

  task automatic random_suite;
    logic [31:0] state,address,data;logic [2:0] prot;logic [3:0] strb;logic [1:0] response;integer i;
    begin
      state=32'h3588b157;
      // Explicit route-boundary addresses, malformed alignment passed unchanged to child.
      read_transaction(32'h00000200,3'b001,2'b00);write_transaction(32'h000002ff,3'b101,32'h01020304,4'b0011,2'b01,0);
      read_transaction(32'h000001ff,3'b010,2'b10);write_transaction(32'h00000300,3'b111,32'h11223344,4'b1100,2'b11,1);
      read_transaction(32'h00010200,3'b100,2'b01);write_transaction(32'hffff0200,3'b011,32'h55667788,4'b0101,2'b00,0);
      read_transaction(32'h00000201,3'b110,2'b11);write_transaction(32'h000002fe,3'b001,32'h99aabbcc,4'b1010,2'b10,1);
      read_transaction(32'h000002ff,3'b111,2'b00);read_transaction(32'h00000300,3'b000,2'b01);
      // All four response codes pass from each route; values are route-tagged.
      for(i=0;i<4;i=i+1)begin
        write_transaction(i[0]?32'h200:32'h100,3'(i),32'hc0010000+i,4'(i),2'(i),i[0]);
        read_transaction(i[0]?32'h2ff:32'hff,3'(i),2'(i));
      end
      // Deterministic full-address/data/protection/strobe random cases, never a seeded DUT expectation.
      for(i=0;i<24;i=i+1)begin
        state=random_next(state);address=state;state=random_next(state);data=state;state=random_next(state);
        prot=state[2:0];strb=state[3:0];response=state[1:0];
        write_transaction(address,prot,data,strb,response,state[4]);
        state=random_next(state);address=state;state=random_next(state);prot=state[2:0];response=state[1:0];
        read_transaction(address,prot,response);
      end
    end
  endtask

  initial begin : test
    joint_rst_n=0;s_awaddr=0;s_awprot=0;s_awvalid=0;s_wdata=0;s_wstrb=0;s_wvalid=0;s_bready=0;
    s_araddr=0;s_arprot=0;s_arvalid=0;s_rready=0;child_awready=0;child_wready=0;child_bvalid=0;child_bresp=0;
    child_arready=0;child_rvalid=0;child_rresp=0;child_rdata=0;transactions=0;
    reset_router();
    write_transaction(32'h00000200,3'b101,32'h12345678,4'b0101,2'b00,0); // AW before W
    write_transaction(32'h00000100,3'b010,32'h89abcdef,4'b1010,2'b01,1); // W before AW
    read_transaction(32'h00000200,3'b110,2'b10);read_transaction(32'h00010200,3'b011,2'b11);
    simultaneous_different_targets();no_zero_bubble_reissue();random_suite();
    $display("PASS_AXIL_DIAGNOSTIC_ROUTER transactions=%0d full_address_decode=PASS",transactions);
    $finish;
  end
endmodule
