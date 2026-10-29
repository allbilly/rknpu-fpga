// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_pcie_jtag_frame_frontend;
  logic clk,rst_n=1,release_ready=0,jtag_link_healthy=1,pcie_link_healthy=0;
  initial clk=0;
  always #5 clk=~clk;
  logic [31:0] awaddr=0,wdata=0,araddr=0;
  logic [2:0] awprot=0,arprot=0;
  logic awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
  logic [3:0] wstrb=4'hf;
  wire awready,wready,bvalid,arready,rvalid;
  wire [1:0] bresp,rresp;
  wire [31:0] rdata;
  logic jtag_req_valid=0; wire jtag_req_ready,jtag_rsp_valid;
  logic [603:0] jtag_req=0; wire [511:0] jtag_rsp_data;
  wire [7:0] jtag_rsp_status; wire [15:0] jtag_rsp_seq;
  wire m_req_valid; logic m_req_ready=0; wire [603:0] m_req;
  logic m_rsp_valid=0; logic [511:0] m_rsp_data=0;
  logic [7:0] m_rsp_status=0; logic [15:0] m_rsp_seq=0;
  wire [1:0] owner; wire [31:0] lease_epoch;
  wire pcie_irq,pcie_protocol_fault,pcie_epoch_fault,owner_protocol_fault; wire [7:0] owner_failure_code;
  integer checks=0, i;
  logic [639:0] raw_frame;
  logic [639:0] expected_rsp;
  logic [511:0] backend_data;
  logic [31:0] rd;
  rk_pcie_jtag_frame_frontend dut(.*,
    .s_axil_awaddr(awaddr),.s_axil_awprot(awprot),.s_axil_awvalid(awvalid),.s_axil_awready(awready),
    .s_axil_wdata(wdata),.s_axil_wstrb(wstrb),.s_axil_wvalid(wvalid),.s_axil_wready(wready),
    .s_axil_bresp(bresp),.s_axil_bvalid(bvalid),.s_axil_bready(bready),
    .s_axil_araddr(araddr),.s_axil_arprot(arprot),.s_axil_arvalid(arvalid),.s_axil_arready(arready),
    .s_axil_rdata(rdata),.s_axil_rresp(rresp),.s_axil_rvalid(rvalid),.s_axil_rready(rready));
  task automatic ck(input logic c,input string s); begin checks++; if(c!==1'b1)$fatal(1,"FAIL %s t=%0t owner=%0d pcie_fault=%b owner_fault=%b",s,$time,owner,pcie_protocol_fault,owner_protocol_fault); end endtask
  task automatic tick; begin @(posedge clk); #1; end endtask
  task automatic reset_all; begin
    @(negedge clk);rst_n=0;awvalid=0;wvalid=0;bready=0;arvalid=0;rready=0;jtag_req_valid=0;m_req_ready=0;m_rsp_valid=0;
    jtag_link_healthy=1;pcie_link_healthy=1;release_ready=0;repeat(2)tick();
    @(negedge clk);rst_n=1;tick();ck(owner==0&&lease_epoch==0&&!pcie_irq&&!pcie_protocol_fault&&!pcie_epoch_fault&&!owner_protocol_fault,"joint reset clears composition");
  end endtask
  task automatic reset_startup_down; begin
    @(negedge clk);rst_n=0;awvalid=0;wvalid=0;bready=0;arvalid=0;rready=0;
    jtag_req_valid=0;m_req_ready=0;m_rsp_valid=0;jtag_link_healthy=1;pcie_link_healthy=0;release_ready=0;
    repeat(2)tick();@(negedge clk);rst_n=1;tick();
    ck(owner==0&&lease_epoch==0&&!pcie_epoch_fault&&!pcie_protocol_fault&&!owner_protocol_fault,
       "joint reset with absent PCIe link starts clean unowned epoch");
    ck(!dut.pcie_epoch_ready&&!dut.pcie_seen_up,"startup link absence remains unarmed and unseen");
  end endtask
  task automatic axwrite(input logic [31:0] a,input logic [31:0] d); integer n; begin
    @(negedge clk);awaddr=a;wdata=d;awvalid=1;wvalid=1;
    n=0;while(!(awready&&wready)&&n<40)begin @(negedge clk);n++;end
    ck(awready&&wready,"AXI AW/W accepted");@(posedge clk);#1;@(negedge clk);awvalid=0;wvalid=0;bready=0;
    n=0;while(!bvalid&&n<40)begin tick();n++;end ck(bvalid&&bresp==0,"AXI B success");
    repeat(2)begin tick();ck(bvalid&&bresp==0,"AXI B response held under backpressure");end
    @(negedge clk);bready=1;tick();@(negedge clk);bready=0;
  end endtask
  task automatic axwrite_error(input logic [31:0] a,input logic [31:0] d,input logic [1:0] expected); integer n; begin
    @(negedge clk);awaddr=a;wdata=d;awvalid=1;wvalid=1;n=0;
    while(!(awready&&wready)&&n<40)begin @(negedge clk);n++;end
    ck(awready&&wready,"AXI AW/W accepted while PCIe admission is disabled");@(posedge clk);#1;@(negedge clk);awvalid=0;wvalid=0;bready=0;
    n=0;while(!bvalid&&n<40)begin tick();n++;end
    ck(bvalid&&bresp===expected,"disabled PCIe write returns explicit SLVERR");
    repeat(2)begin tick();ck(bvalid&&bresp===expected,"disabled-write B response held");end
    @(negedge clk);bready=1;tick();@(negedge clk);bready=0;
  end endtask
  task automatic axread(input logic [31:0] a,output logic [31:0] d); integer n; begin
    @(negedge clk);araddr=a;arvalid=1;rready=0;while(!arready)@(negedge clk);@(posedge clk);#1;
    @(negedge clk);arvalid=0;n=0;while(!rvalid&&n<40)begin tick();n++;end
    ck(rvalid&&rresp==0,"AXI R success");d=rdata;
    repeat(2)begin tick();ck(rvalid&&rresp==0&&rdata==d,"AXI R response held under backpressure");end
    @(negedge clk);rready=1;tick();@(negedge clk);rready=0;
  end endtask
  task automatic axread_error(input logic [31:0] a,input logic [1:0] expected); integer n; begin
    @(negedge clk);araddr=a;arvalid=1;rready=0;n=0;
    while(!arready&&n<40)begin @(negedge clk);n++;end
    ck(arready,"AXI AR accepted while PCIe admission is disabled");@(posedge clk);#1;@(negedge clk);arvalid=0;
    n=0;while(!rvalid&&n<40)begin tick();n++;end
    ck(rvalid&&rresp===expected&&rdata===0,"disabled PCIe read returns SLVERR and zero data");
    repeat(2)begin tick();ck(rvalid&&rresp===expected&&rdata===0,"disabled-read R response held");end
    @(negedge clk);rready=1;tick();@(negedge clk);rready=0;
  end endtask
  task automatic pcie_aw_half(input logic [31:0] a); integer n; begin
    @(negedge clk);awaddr=a;awvalid=1;wvalid=0;n=0;
    while(!awready&&n<40)begin @(negedge clk);n++;end
    ck(awready,"PCIe AW-only half accepted while source admission is down");tick();@(negedge clk);awvalid=0;
  end endtask
  task automatic pcie_w_half(input logic [31:0] d); integer n; begin
    @(negedge clk);wdata=d;wvalid=1;wstrb=4'hf;n=0;
    while(!wready&&n<40)begin @(negedge clk);n++;end
    ck(wready,"PCIe W-only half accepted while source admission is down");tick();@(negedge clk);wvalid=0;
  end endtask
  task automatic pcie_w_complete_aw(input logic [31:0] d); integer n; begin
    pcie_w_half(d);n=0;while(!bvalid&&n<40)begin tick();n++;end
    ck(bvalid&&bresp===2,"AW half disqualified before startup re-arm returns SLVERR");
    repeat(2)begin tick();ck(bvalid&&bresp===2,"startup pair error B response held");end
    @(negedge clk);bready=1;tick();@(negedge clk);bready=0;
  end endtask
  task automatic startup_half_reject(input logic aw_first); begin
    reset_startup_down();
    axwrite_error(32'h40,32'h0a0b0c0d,2);axread_error(0,2);
    ck(dut.pcie_packets.staged===20'd0&&!dut.pcie_packets.aw_pending&&!dut.pcie_packets.w_pending,
       "disabled complete write/read do not stage or retain halves");
    if(aw_first)begin
      pcie_aw_half(32'h40);
      ck(dut.pcie_packets.aw_pending&&!dut.pcie_packets.aw_allowed&&!dut.pcie_packets.w_pending,
         "pre-up AW half remembered as disqualified");
    end else begin
      pcie_w_half(32'h10203040);
      ck(dut.pcie_packets.w_pending&&!dut.pcie_packets.w_allowed&&!dut.pcie_packets.aw_pending,
         "pre-up W half remembered as disqualified");
    end
    pcie_link_healthy=1;repeat(4)tick();
    ck(dut.pcie_epoch_ready&&dut.pcie_seen_up&&!pcie_epoch_fault,
       "four fresh high samples arm PCIe after startup absence");
    if(aw_first)pcie_w_complete_aw(32'h55667788);else aw_reject_pending_w(32'h40);
    ck(dut.pcie_packets.staged===20'd0&&!dut.pcie_packets.aw_pending&&!dut.pcie_packets.w_pending&&
       !dut.pcie_req_valid&&!m_req_valid&&owner==0&&lease_epoch==0,
       "drained startup-disqualified pair has no staged data, claim or backend frame");
  end endtask
  function automatic [603:0] frame(input logic [15:0] seq,input logic [7:0] op,input logic [31:0] addr,input logic [511:0] data);
    frame={32'h4f54504a,seq,op,4'hf,addr,data};
  endfunction
  task automatic jsend(input logic [603:0] q); begin
    @(negedge clk);jtag_req=q;jtag_req_valid=1;#1;if(!jtag_req_ready)$display("JSEND seq=%h mvalid=%b mready=%b off=%b wait=%b ownerhealthy=%b pcie_req=%b",q[571:556],m_req_valid,m_req_ready,dut.sessions.offered,dut.sessions.waiting,dut.sessions.owner_healthy,dut.pcie_req_valid);ck(jtag_req_ready,"JTAG source handshake ready");tick();@(negedge clk);jtag_req_valid=0;
  end endtask
  task automatic jmgmt(input logic [15:0] seq,input logic [7:0] op,input logic [31:0] addr,input logic [511:0] data,input logic [7:0] status,input logic [511:0] value);
    begin jsend(frame(seq,op,addr,data));if(!(jtag_rsp_valid&&jtag_rsp_seq==seq&&jtag_rsp_status==status&&jtag_rsp_data==value))$display("JMGMT seq=%h gotvalid=%b gotseq=%h status=%h data=%h expected status=%h data=%h",seq,jtag_rsp_valid,jtag_rsp_seq,jtag_rsp_status,jtag_rsp_data,status,value);ck(jtag_rsp_valid&&jtag_rsp_seq==seq&&jtag_rsp_status==status&&jtag_rsp_data==value,"JTAG management result");end
  endtask
  task automatic owner_action(input logic [15:0] seq,input logic [31:0] value,input logic [7:0] status); logic [511:0] d; begin d=0;d[31:0]=value;jmgmt(seq,2,32'h60c,d,status,0);end endtask
  task automatic stage_pcie; begin for(integer k=0;k<20;k++)axwrite(32'h40+4*k,raw_frame[k*32 +:32]);end endtask
  task automatic aw_reject_pending_w(input logic [31:0] a); integer n; begin
    @(negedge clk);awaddr=a;awvalid=1;wvalid=0;n=0;
    while(!awready&&n<40)begin @(negedge clk);n++;end
    ck(awready,"AW completes preserved W-only packet write");tick();@(negedge clk);awvalid=0;
    n=0;while(!bvalid&&n<40)begin tick();n++;end ck(bvalid&&bresp===2,"W-only half captured while down is rejected after recovery");
    repeat(2)begin tick();ck(bvalid&&bresp===2,"rejected partial-write B response held");end
    @(negedge clk);bready=1;tick();@(negedge clk);bready=0;
  end endtask
  task automatic pcie_start; begin axwrite(32'hc,1);ck(m_req_valid&&m_req==raw_frame[603:0],"PCIe packet forwarded exact raw request");end endtask
  task automatic backend_accept; begin m_req_ready=1;tick();@(negedge clk);m_req_ready=0;ck(!m_req_valid,"backend accepted once");end endtask
  task automatic backend_reply(input logic [15:0] seq,input logic [7:0] status,input logic [511:0] d); begin
    @(negedge clk);m_rsp_seq=seq;m_rsp_status=status;m_rsp_data=d;m_rsp_valid=1;tick();@(negedge clk);m_rsp_valid=0;
  end endtask
  task automatic claim_pcie(input logic [15:0] seq); begin
    raw_frame={36'd0,frame(seq,2,32'h60c,{{480'd0,32'd1}})};stage_pcie();axwrite(32'hc,1);
    ck(owner==2,"PCIe claim accepted through BAR frame");
    expected_rsp={72'd0,32'h4f54504a,seq,8'd0,512'd0};
    for(integer k=0;k<20;k++)begin axread(32'h100+4*k,rd);ck(rd==expected_rsp[k*32 +:32],"PCIe claim response word");end
    axwrite(32'hc,2);
  end endtask
  initial begin
    raw_frame=0;raw_frame[603:572]=32'h4f54504a;raw_frame[571:556]=16'hcafe;raw_frame[555:548]=8'h42;raw_frame[547:544]=4'hf;
    for(i=0;i<16;i++)backend_data[i*32 +:32]=32'h81000000+i*32'h01010101;
    // Neither AXI half accepted before the first healthy PCIe epoch may be
    // paired later into a valid write after link arming.
    startup_half_reject(1);startup_half_reject(0);
    release_ready=1;
    raw_frame={36'd0,frame(16'hee00,2,32'h60c,{{480'd0,32'd1}})};
    claim_pcie(16'hee00);ck(owner==2&&lease_epoch==1&&!pcie_epoch_fault,
                            "clean transaction works after startup-disqualified halves are drained");
    reset_all();repeat(4)tick();
    raw_frame=0;raw_frame[603:572]=32'h4f54504a;raw_frame[571:556]=16'hcafe;
    raw_frame[555:548]=8'h42;raw_frame[547:544]=4'hf;
    jmgmt(1,1,32'h600,0,0,512'h524b484f);
    jmgmt(2,1,32'h608,0,0,0);jmgmt(3,1,32'h614,0,0,512'd1);
    // PCIe startup must establish four consecutive healthy UI samples before
    // any packet source can claim the shared backend.
    repeat(5)tick();ck(dut.pcie_epoch_ready&&!pcie_epoch_fault&&!pcie_irq&&owner==0,
                       "PCIe epoch arms after fresh healthy samples with no owner");
    // Preserve a W-only packet write through link loss/recovery. The guard
    // faults the source, but must not reset the AXI mailbox's partial state.
    raw_frame={36'd0,frame(16'he100,2,32'h60c,{{480'd0,32'd1}})};
    @(negedge clk);wdata=raw_frame[31:0];wvalid=1;wstrb=4'hf;
    while(!wready)@(negedge clk);tick();@(negedge clk);wvalid=0;
    ck(dut.pcie_packets.w_pending&& !dut.pcie_packets.aw_pending,"W-only packet half retained before link loss");
    pcie_link_healthy=0;tick();ck(pcie_epoch_fault&&pcie_irq&&owner==0&&!owner_protocol_fault,
                                   "unowned PCIe loss latches epoch fault and IRQ");
    pcie_link_healthy=1;repeat(6)tick();
    ck(pcie_epoch_fault&&pcie_irq&&owner==0&&!owner_protocol_fault&&
       dut.pcie_packets.w_pending&&!dut.pcie_packets.failed,
       "PCIe recovery neither clears epoch fault nor resets partial mailbox state");
    aw_reject_pending_w(32'h40);
    ck(dut.pcie_packets.staged===20'd0&&!dut.pcie_packets.aw_pending&&!dut.pcie_packets.w_pending,
       "link-loss pairing error leaves packet staging unchanged");
    for(i=0;i<20;i++)axwrite_error(32'h40+4*i,raw_frame[i*32 +:32],2);
    axwrite_error(32'hc,1,2);
    ck(!dut.pcie_req_valid&&!m_req_valid&&owner==0&&lease_epoch==0&&
       dut.pcie_packets.staged===20'd0&&pcie_epoch_fault&&!owner_protocol_fault,
       "recovered but faulted PCIe writes cannot stage, claim or forward a packet");
    // The unhealthy PCIe peer cannot seize the lane, while independent JTAG
    // continues to claim and use the backend without an owner fault.
    release_ready=1;owner_action(16'he101,1,0);
    ck(owner==1&&pcie_epoch_fault&&!owner_protocol_fault,
       "JTAG can acquire with the PCIe epoch fault sticky and no owner fault");
    jsend(frame(16'he102,1,32'h100,512'd0));
    ck(m_req_valid&&owner==1,"JTAG backend read forwards during the PCIe epoch fault");
    backend_accept();backend_reply(16'he102,0,512'h1234);
    ck(jtag_rsp_valid&&jtag_rsp_seq==16'he102&&jtag_rsp_status==0&&owner==1&&
       pcie_epoch_fault&&!owner_protocol_fault,
       "JTAG receives its response while PCIe fault remains isolated");
    owner_action(16'he103,2,0);ck(owner==0&&pcie_epoch_fault&&!owner_protocol_fault,
                                   "JTAG release does not clear PCIe epoch fault");
    reset_all();
    ck(dut.pcie_packets.staged===20'd0&&!dut.pcie_packets.aw_pending&&!dut.pcie_packets.w_pending&&
       !dut.pcie_packets.waiting&&!pcie_epoch_fault&&!pcie_irq&&owner==0,
       "joint reset clears epoch fault and partial packet state");
    release_ready=1;repeat(4)tick();claim_pcie(16'he104);
    ck(owner==2&&lease_epoch==1&&!pcie_epoch_fault,
       "PCIe can acquire only in a fresh jointly reset epoch");
    reset_all();
    raw_frame=0;raw_frame[603:572]=32'h4f54504a;raw_frame[571:556]=16'hcafe;
    raw_frame[555:548]=8'h42;raw_frame[547:544]=4'hf;
    // Release witness blocks both transports; ownership epoch changes only after healthy quiescence.
    owner_action(4,1,2);ck(owner==0&&lease_epoch==0,"acquire denied without backend release witness");
    release_ready=1;owner_action(5,1,0);ck(owner==1&&lease_epoch==1,"JTAG acquires epoch one");
    stage_pcie();axwrite(32'hc,1);ck(!m_req_valid,"PCIe payload blocked by JTAG owner");
    // The mux returns a local SLVERR packet response; drain all words before ACK.
    expected_rsp={72'd0,32'h4f54504a,16'hcafe,8'd2,512'd0};
    for(i=0;i<20;i++)begin axread(32'h100+4*i,rd);ck(rd==expected_rsp[i*32 +:32],"blocked PCIe packet contains local SLVERR only");end
    axwrite(32'hc,2);ck(owner==1,"packet ACK does not release JTAG lease");
    rd=0;jmgmt(6,1,32'h614,0,0,512'd1);
    // Raw JTAG request crosses as one unchanged backend frame and response stays with JTAG.
    jsend(frame(16'h101,8'h43,32'h11223344,512'hfedcba9876543210));
    ck(m_req_valid&&m_req==frame(16'h101,8'h43,32'h11223344,512'hfedcba9876543210),"JTAG request exact backend frame");
    backend_accept();backend_reply(16'h101,0,512'h0123456789abcdef);
    ck(jtag_rsp_valid&&jtag_rsp_seq==16'h101&&jtag_rsp_data==512'h0123456789abcdef,"JTAG receives correlated backend response");
    // PCIe cannot release another source's owner; a low witness refuses JTAG release too.
    // The earlier PCIe payload was rejected without a backend handshake; that
    // also proves PCIe cannot use the backend lane to alter JTAG ownership.
    release_ready=0;owner_action(8,2,2);ck(owner==1,"release denied with low backend witness");
    release_ready=1;owner_action(9,2,0);ck(owner==0,"JTAG release after healthy quiet");
    raw_frame={36'd0,frame(16'hca11,2,32'h60c,{{480'd0,32'd1}})};stage_pcie();axwrite(32'hc,1);
    ck(!m_req_valid&&owner==2&&lease_epoch==2,"PCIe management acquire uses source identity and epoch");
    expected_rsp={72'd0,32'h4f54504a,16'hca11,8'd0,512'd0};
    for(i=0;i<20;i++)begin axread(32'h100+4*i,rd);ck(rd==expected_rsp[i*32 +:32],"PCIe acquire response DWORD");end
    axwrite(32'hc,2);ck(owner==2,"PCIe packet ACK retains global owner");
    raw_frame=0;raw_frame[603:572]=32'h4f54504a;raw_frame[571:556]=16'hcafe;raw_frame[555:548]=8'h42;raw_frame[547:544]=4'hf;
    stage_pcie();pcie_start();
    // Backend backpressure retains the complete request; management queries remain available.
    repeat(3)begin tick();ck(m_req_valid&&m_req==raw_frame[603:0],"PCIe raw frame stable under backend stall");end
    backend_accept();backend_reply(16'hcafe,0,backend_data);tick();ck(pcie_irq,"held PCIe response raises IRQ");
    expected_rsp={72'd0,32'h4f54504a,16'hcafe,8'd0,backend_data};
    for(i=0;i<20;i++)begin axread(32'h100+4*i,rd);ck(rd==expected_rsp[i*32 +:32],"PCIe response DWORD endian/header/payload");end
    ck(!jtag_rsp_valid,"PCIe response never leaks to JTAG");
    axwrite(32'hc,2);ck(owner==2&&lease_epoch==2,"outer packet ACK retains global owner");
    jsend(frame(16'h102,8'h43,32'h11223344,512'd0));ck(jtag_rsp_valid&&jtag_rsp_status==2&&!m_req_valid,"JTAG raw request denied while PCIe owns backend");
    jsend(frame(16'h103,2,32'h50c,512'd1));ck(jtag_rsp_valid&&jtag_rsp_status==2&&owner==2&&!m_req_valid,"JTAG reset CSR 0x50c denied while PCIe owns backend");
    jsend(frame(16'h104,2,32'h00c,512'd1));ck(jtag_rsp_valid&&jtag_rsp_status==2&&owner==2&&!m_req_valid,"JTAG NPU ACK 0x00c denied while PCIe owns backend");
    release_ready=0;raw_frame={36'd0,frame(16'hcaff,2,32'h60c,{{480'd0,32'd2}})};stage_pcie();axwrite(32'hc,1);
    ck(owner==2&&lease_epoch==2,"release denied while backend quiet witness low");
    expected_rsp={72'd0,32'h4f54504a,16'hcaff,8'd2,512'd0};
    for(i=0;i<20;i++)begin axread(32'h100+4*i,rd);ck(rd==expected_rsp[i*32 +:32],"release refusal packet DWORD");end
    axwrite(32'hc,2);release_ready=1;
    raw_frame={36'd0,frame(16'hcb00,2,32'h60c,{{480'd0,32'd2}})};stage_pcie();axwrite(32'hc,1);
    ck(owner==0&&lease_epoch==2,"PCIe release only after packet ACK and quiet witness");
    expected_rsp={72'd0,32'h4f54504a,16'hcb00,8'd0,512'd0};
    for(i=0;i<20;i++)begin axread(32'h100+4*i,rd);ck(rd==expected_rsp[i*32 +:32],"release success packet DWORD");end
    axwrite(32'hc,2);
    // PCIe lease loss faults the mux; the healthy raw JTAG peer can still query diagnostics.
    raw_frame={36'd0,frame(16'hcc00,2,32'h60c,{{480'd0,32'd1}})};stage_pcie();axwrite(32'hc,1);
    ck(owner==2&&lease_epoch==3,"PCIe acquires before link-loss scenario");
    expected_rsp={72'd0,32'h4f54504a,16'hcc00,8'd0,512'd0};
    for(i=0;i<20;i++)begin axread(32'h100+4*i,rd);ck(rd==expected_rsp[i*32 +:32],"PCIe acquire response before link loss");end
    axwrite(32'hc,2);pcie_link_healthy=0;tick();
    ck(owner_protocol_fault&&owner_failure_code==1&&pcie_epoch_fault&&pcie_irq&&!m_req_valid,"PCIe owner link loss faults both retained owner and source epoch");
    pcie_link_healthy=1;repeat(5)tick();
    ck(owner==2&&owner_protocol_fault&&pcie_epoch_fault&&pcie_irq&&!m_req_valid,
       "link recovery cannot heal an owned PCIe lease or either sticky fault");
    jmgmt(18,1,32'h618,0,0,512'd1);
    // PCIe link disappears with a raw payload offered but not accepted by the backend.
    reset_all();repeat(4)tick();release_ready=1;claim_pcie(16'hcd00);
    raw_frame=0;raw_frame[603:572]=32'h4f54504a;raw_frame[571:556]=16'hcd01;raw_frame[555:548]=8'h42;raw_frame[547:544]=4'hf;
    stage_pcie();pcie_start();ck(m_req_valid&&!m_req_ready,"PCIe backend request is offered and stalled");
    pcie_link_healthy=0;tick();ck(!m_req_valid&&owner_protocol_fault&&owner_failure_code==1&&pcie_epoch_fault&&!pcie_protocol_fault,"offered request is cut off on PCIe link loss");
    repeat(3)begin tick();ck(!m_req_valid&&!jtag_rsp_valid,"stalled request never leaks or gets a response after link loss");end
    ck(dut.pcie_packets.waiting&&owner==2&&owner_protocol_fault&&pcie_epoch_fault,
       "PCIe mailbox/lease remains pending and faulted");
    axread_error(32'h8,2);
    jmgmt(16'hcd02,1,32'h618,0,0,512'd1);
    pcie_link_healthy=1;repeat(5)tick();
    ck(owner==2&&owner_protocol_fault&&pcie_epoch_fault&&pcie_irq&&!m_req_valid,
       "link recovery does not heal the offered-request owner lease or epoch fault");
    reset_all();
    // PCIe link disappears after backend acceptance; a late backend reply is quarantined.
    release_ready=1;repeat(4)tick();claim_pcie(16'hce00);
    raw_frame=0;raw_frame[603:572]=32'h4f54504a;raw_frame[571:556]=16'hce01;raw_frame[555:548]=8'h42;raw_frame[547:544]=4'hf;
    stage_pcie();pcie_start();backend_accept();
    pcie_link_healthy=0;tick();ck(owner_protocol_fault&&owner_failure_code==1&&pcie_epoch_fault&&!pcie_protocol_fault,"accepted request faults on PCIe link loss");
    backend_reply(16'hce01,0,backend_data);tick();
    ck(owner_protocol_fault&&pcie_irq&&!pcie_protocol_fault&&!jtag_rsp_valid,"late backend reply does not become PCIe success or JTAG response");
    ck(dut.pcie_packets.waiting&&owner==2&&owner_protocol_fault&&pcie_epoch_fault,
       "accepted PCIe mailbox/lease remains pending and faulted");
    axread_error(32'h8,2);
    pcie_link_healthy=1;repeat(5)tick();
    ck(owner==2&&owner_protocol_fault&&pcie_epoch_fault&&pcie_irq&&!m_req_valid&&!jtag_rsp_valid,
       "link recovery does not heal accepted PCIe lease or admit its late response");
    reset_all();
    release_ready=1;owner_action(19,1,0);ck(owner==1,"joint recovery permits fresh claim");
    // Wrong backend sequence faults the owner mux; the packet endpoint is not given a false response.
    owner_action(20,2,0);owner_action(21,1,0);ck(owner==1,"JTAG reacquires after joint reset");
    jsend(frame(16'hcafe,8'h42,32'h12345678,0));ck(m_req_valid,"JTAG backend request offered before injected response fault");backend_accept();backend_reply(16'hcaff,0,0);
    ck(owner_protocol_fault&&owner_failure_code==3&&pcie_irq,"backend wrong sequence creates sticky owner fault");
    ck(!m_req_valid,"owner fault blocks backend traffic");
    reset_all();
    $display("PASS_PCIE_JTAG_FRAME_FRONTEND checks=%0d",checks);$finish;
  end
endmodule
