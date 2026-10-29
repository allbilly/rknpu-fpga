`timescale 1ns/1ps
module tb_session_quiet;
  logic clk; always #5 clk=~clk;
  logic rst_n=0, memory_ready=1;
  logic [31:0] awaddr=0,wdata=0,araddr=0;
  logic [2:0] awprot=0,arprot=0;
  logic [3:0] wstrb=4'hf;
  logic awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
  wire awready,wready,bvalid,arready,rvalid;
  wire [1:0] bresp,rresp; wire [31:0] rdata;
  wire irq,scheduler_fault,control_owned,control_quiet,session_quiet;
  wire [1:0] control_owner_kind;
  wire core_start_valid; wire [1:0] core_start_kind;
  wire [31:0] core_start_address,core_start_amount;
  logic ew_ready=1,cmac_ready=1,layout_ready=1;
  logic core_busy=0,core_done=0,core_error=0,core_write_block=0;
  logic [7:0] core_error_code=0; logic [31:0] core_completed_tasks=0;
  wire ref_awready,ref_wready,ref_bvalid,ref_arready,ref_rvalid;
  wire [1:0] ref_bresp,ref_rresp; wire [31:0] ref_rdata;
  wire ref_irq,ref_fault,ref_owned,ref_quiet,ref_start_valid; wire [1:0] ref_owner,ref_kind;
  wire [31:0] ref_start_address,ref_start_amount;
  rk_layout_job_control_reference refdut(
    .clk,.rst_n,.memory_ready,.s_axil_awaddr(awaddr),.s_axil_wdata(wdata),.s_axil_araddr(araddr),
    .s_axil_awprot(awprot),.s_axil_arprot(arprot),.s_axil_wstrb(wstrb),
    .s_axil_awvalid(awvalid),.s_axil_wvalid(wvalid),.s_axil_bready(bready),
    .s_axil_arvalid(arvalid),.s_axil_rready(rready),.s_axil_awready(ref_awready),.s_axil_wready(ref_wready),
    .s_axil_bvalid(ref_bvalid),.s_axil_arready(ref_arready),.s_axil_rvalid(ref_rvalid),.s_axil_bresp(ref_bresp),
    .s_axil_rresp(ref_rresp),.s_axil_rdata(ref_rdata),.irq(ref_irq),.scheduler_fault(ref_fault),.control_owned(ref_owned),
    .control_quiet(ref_quiet),.control_owner_kind(ref_owner),.core_start_valid(ref_start_valid),.core_start_kind(ref_kind),
    .core_start_address(ref_start_address),.core_start_amount(ref_start_amount),.core_ew_start_ready(ew_ready),
    .core_cmac_start_ready(cmac_ready),.core_layout_start_ready(layout_ready),.core_busy,.core_done,.core_error,
    .core_write_block,.core_error_code,.core_completed_tasks);
  always @(negedge clk) if(rst_n) begin
    if({awready,wready,bvalid,bresp,arready,rvalid,rresp,rdata,irq,scheduler_fault,control_owned,control_owner_kind,
        core_start_valid,core_start_kind,core_start_address,core_start_amount,control_quiet} !==
       {ref_awready,ref_wready,ref_bvalid,ref_bresp,ref_arready,ref_rvalid,ref_rresp,ref_rdata,ref_irq,ref_fault,
        ref_owned,ref_owner,ref_start_valid,ref_kind,ref_start_address,ref_start_amount,ref_quiet}) begin
      $display("REFERENCE_OUTPUT_MISMATCH at %0t",$time);$fatal(1);
    end
  end
  integer checks,start_count; reg [1:0] last_kind; reg [31:0] last_start_addr,last_start_amount;
  always @(posedge clk) if(core_start_valid && (core_start_kind==0?ew_ready:core_start_kind==1?cmac_ready:layout_ready)) begin start_count<=start_count+1;last_kind<=core_start_kind;last_start_addr<=core_start_address;last_start_amount<=core_start_amount;end
  rk_layout_job_control dut(
    .clk,.rst_n,.memory_ready,.s_axil_awaddr(awaddr),.s_axil_wdata(wdata),.s_axil_araddr(araddr),
    .s_axil_awprot(awprot),.s_axil_arprot(arprot),.s_axil_wstrb(wstrb),
    .s_axil_awvalid(awvalid),.s_axil_wvalid(wvalid),.s_axil_bready(bready),
    .s_axil_arvalid(arvalid),.s_axil_rready(rready),.s_axil_awready(awready),.s_axil_wready(wready),
    .s_axil_bvalid(bvalid),.s_axil_arready(arready),.s_axil_rvalid(rvalid),.s_axil_bresp(bresp),
    .s_axil_rresp(rresp),.s_axil_rdata(rdata),.irq,.scheduler_fault,.control_owned,
    .control_quiet,.session_quiet,.control_owner_kind,.core_start_valid,.core_start_kind,
    .core_start_address,.core_start_amount,.core_ew_start_ready(ew_ready),
    .core_cmac_start_ready(cmac_ready),.core_layout_start_ready(layout_ready),.core_busy,
    .core_done,.core_error,.core_write_block,.core_error_code,.core_completed_tasks);

  task automatic tick; begin @(posedge clk); #1; end endtask
  task automatic must(input bit ok,input [8*100-1:0] msg); begin checks=checks+1; if(!ok)begin $display("FAIL %0s",msg);$fatal(1);end end endtask
  task automatic reset_all; begin
    awvalid=0;wvalid=0;bready=0;arvalid=0;rready=0;rst_n=0;tick();tick();rst_n=1;tick();
    must(session_quiet,"global reset returns idle session quiet");must(!scheduler_fault,"reset leaves no scheduler fault");must(!control_owned && control_owner_kind==0,"reset clears controller owner");must(dut.bank_descriptor_empty===3'b111,"reset descriptor-empty bits reflect zero fields");
  end endtask
  task automatic write_reg(input [31:0] a,input [31:0] d,input [1:0] expected,input bit hold_b);
    bit ah,wh,ah_now,wh_now; integer n;
    begin
      awaddr=a;wdata=d;awvalid=1;wvalid=1;bready=0;ah=0;wh=0;n=0;
      while((!ah||!wh)&&n<20)begin
        @(posedge clk);
        ah_now=awvalid&&awready;wh_now=wvalid&&wready;
        #1;
        if(ah_now)begin awvalid=0;ah=1;end
        if(wh_now)begin wvalid=0;wh=1;end
        n=n+1;
      end
      n=0;while(!bvalid&&n<20)begin @(posedge clk);#1;n=n+1;end
      if(!bvalid)begin $display("missing B %08x",a);$fatal(1);end
      if(bresp!==expected)begin $display("B resp %b expected %b addr %08x",bresp,expected,a);$fatal(1);end
      if(hold_b)begin must(!control_quiet,"held B blocks quiet");tick();must(bvalid,"B remains held");end
      bready=1;tick();bready=0;#1;
    end
  endtask
  task automatic stage(input [31:0] base,input [31:0] av,input [31:0] amount,input [31:0] tag);
    begin write_reg(base+32'h10,av,0,0);write_reg(base+32'h14,amount,0,0);write_reg(base+32'h18,tag,0,0);end
  endtask
  task automatic read_reg(input [31:0] a,input [31:0] expected);
    begin araddr=a;arvalid=1;rready=0;@(posedge clk);if(!arready)$fatal(1,"AR not ready");#1;arvalid=0;#1;
      if(!rvalid||rresp!==0||rdata!==expected)begin $display("read %08x got %08x resp%0d",a,rdata,rresp);$fatal(1);end
      rready=1;tick();rready=0;
    end
  endtask
  task automatic start_job(input [31:0] base,input [31:0] a,input [31:0] n,input [31:0] tag);
    integer before_starts; begin reset_all;stage(base,a,n,tag);must(!session_quiet,"fully staged descriptor blocks session");
      before_starts=start_count;write_reg(base+12,1,0,0);must(control_owned,"raw START obtains owner");
      must(start_count==before_starts+1,"raw START handoff observed");
      must(last_kind === ((base==32'h00000000) ? 2'd0 : (base==32'h00000100) ? 2'd1 : 2'd2),"START routed to selected bank");
      must(last_start_addr==a && last_start_amount==n,"start descriptor matches staged raw words");
      core_done=1;core_busy=0;core_completed_tasks=32'h1234;tick();core_done=0;
      must(irq,"successful terminal result raises IRQ");
      read_reg(base+32'h1c,tag);read_reg(base+32'h20,32'h1234);
      write_reg(base+12,2,0,0);tick();tick();
      must(!irq,"successful ACK clears IRQ");must(!control_owned,"successful ACK releases controller owner");
      must(session_quiet,"successful ACK clears all descriptors and allows session quiet");
    end
  endtask
  integer k;
  reg [31:0] pages[0:2];
  initial begin
    clk=0;checks=0;start_count=0;pages[0]=0;pages[1]=32'h100;pages[2]=32'h400;
    reset_all;
    // A held R response is outstanding even with an empty descriptor.
    araddr=0;arvalid=1;rready=0;@(posedge clk);if(!arready)$fatal(1,"held-R AR not ready");#1;arvalid=0;#1;
    must(rvalid,"read response is offered");must(!control_quiet,"held R blocks quiet");tick();must(rvalid,"R remains held under backpressure");
    rready=1;tick();rready=0;must(control_quiet && session_quiet,"drained R restores empty-session quiet");
    // AW-only and W-only transfer halves are outstanding session state.
    awaddr=32'h10;awvalid=1;@(posedge clk);#1;awvalid=0;tick();must(!control_quiet,"accepted partial AW blocks quiet");
    wdata=32'h1000;wvalid=1;@(posedge clk);#1;wvalid=0;tick();must(bvalid,"partial AW completes when W arrives");must(!control_quiet,"held response blocks quiet");
    bready=1;tick();bready=0;must(!session_quiet,"partial descriptor blocks session after response");
    reset_all;
    wdata=32'h1000;wvalid=1;@(posedge clk);#1;wvalid=0;tick();must(!control_quiet,"accepted partial W blocks quiet");
    awaddr=32'h10;awvalid=1;@(posedge clk);#1;awvalid=0;tick();must(bvalid,"partial W completes when AW arrives");bready=1;tick();bready=0;
    must(!session_quiet,"W-first descriptor remains staged");reset_all;
    // Every bank contributes all three descriptor bits to the session witness.
    for(k=0;k<3;k=k+1)begin
      write_reg(pages[k]+32'h10,32'h1000+k,0,0);must(dut.bank_descriptor_empty[k]===1'b0,"any staged field makes its bank nonempty");must(!session_quiet,"address-only descriptor blocks session");
      write_reg(pages[k]+32'h14,32'h20,0,0);must(!session_quiet,"address+amount descriptor blocks session");
      write_reg(pages[k]+32'h18,32'h55+k,0,0);must(!session_quiet,"fully staged descriptor blocks session");
      must(!control_owned&&!core_busy,"descriptor staging does not claim engine");
      write_reg(pages[k]+12,2,2,0);must(!session_quiet,"ACK before result rejected and descriptor retained");
      read_reg(pages[k]+32'h10,32'h1000+k);read_reg(pages[k]+32'h14,32'h20);read_reg(pages[k]+32'h18,32'h55+k);
      // Bad/readonly/alias requests must not mutate any staged fields.
      awprot=1;write_reg(pages[k]+32'h10,32'hdeadbeef,2,0);awprot=0;
      write_reg(pages[k]+32'h30,32'hdeadbeef,3,0);
      if(k==1)write_reg(32'h210,32'hdeadbeef,3,0);
      if(k==2)write_reg(32'h310,32'hdeadbeef,3,0);
      read_reg(pages[k]+32'h10,32'h1000+k);read_reg(pages[k]+32'h14,32'h20);read_reg(pages[k]+32'h18,32'h55+k);
      // reset between cases: global reset is the only operation that discards staged fields.
      reset_all;
    end
    // The busy input does not mask staged fields; global reset clears them.
    stage(0,32'h111,32'h22,32'h33);core_busy=1;tick();must(!session_quiet,"engine busy does not mask staged fields");
    core_busy=0;reset_all;
    // The start-ready stall preserves the launch and keeps session held.
    stage(32'h100,32'habc,32'h40,32'h66);cmac_ready=0;k=start_count;write_reg(32'h10c,1,2,0); // START rejected while core not ready
    must(!core_start_valid && start_count==k,"stalled START has no core handoff");must(!session_quiet,"stalled start cannot make staged session quiet");cmac_ready=1;
    // Successful paths for each address bank.
    for(k=0;k<3;k=k+1)start_job(pages[k],32'h1000+k,32'h20,32'h80+k);
    // Error completion cannot ACK or release a session with a result held.
    stage(32'h400,32'h234,32'h10,32'h99);write_reg(32'h40c,1,0,0);tick();
    core_error=1;core_error_code=8'h5a;tick();core_error=0;must(irq,"error result IRQ held");
    write_reg(32'h40c,2,2,0);must(!session_quiet,"error result ACK denied and quiescence remains false");
    read_reg(32'h410,32'h234);read_reg(32'h414,32'h10);read_reg(32'h418,32'h99);
    reset_all;
    $display("PASS checks=%0d simulator=%0s",checks,"Icarus/Verilator");$finish;
  end
endmodule
