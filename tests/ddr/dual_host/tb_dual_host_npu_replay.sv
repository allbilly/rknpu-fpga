// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Public-source actual NPU dual-host EW replay with an independent AXI RAM/ECC model.
// The model is not MIG/PHY; PCIe IP/CDC and hardware execution remain outside this test.
module tb_dual_host_npu_replay;
  localparam logic [31:0] BASE=32'h10000000;
  localparam logic [32:0] BYTES=33'd1048576;
  logic sys_clk,c0_ui_clk,c1_ui_clk;
  initial begin sys_clk=0;c0_ui_clk=0;c1_ui_clk=0;end
  always #10 sys_clk=~sys_clk;
  always #3.75 c0_ui_clk=~c0_ui_clk;
  always #4.25 c1_ui_clk=~c1_ui_clk;
  logic cfg_reset,reset_req_valid;
  wire reset_req_ready,mig_sys_rst_n,sys_clients_rst_n,c0_clients_rst_n,c1_clients_rst_n;
  wire c0_aresetn,c1_aresetn,sequence_busy,sequence_complete,admission_blocked,sequence_fault;
  wire [7:0] sequence_fault_code;
  logic c0_ui_clk_sync_rst,c1_ui_clk_sync_rst,c0_trained;
  logic lose_calibration=0;
  // An external loss override changes the actual input before the next launch
  // edge; it never forces DUT state or merely queues a later model update.
  wire c0_init_calib_complete=c0_trained&&!lose_calibration;
  integer bringup0,bringup1;
  always @(posedge c0_ui_clk) begin
    if(!mig_sys_rst_n)begin bringup0<=0;c0_ui_clk_sync_rst<=1;c0_trained<=0;end
    else begin
      if(bringup0<40)bringup0<=bringup0+1;
      if(bringup0>=12)c0_ui_clk_sync_rst<=0;
      if(bringup0>=24)c0_trained<=1;
    end
  end
  always @(posedge c1_ui_clk) begin
    if(!mig_sys_rst_n)begin bringup1<=0;c1_ui_clk_sync_rst<=1;end
    else begin
      if(bringup1<40)bringup1<=bringup1+1;
      if(bringup1>=15)c1_ui_clk_sync_rst<=0;
    end
  end
  logic req_valid=0;
  wire req_ready,rsp_valid,irq,fault,init_complete,init_active,memory_ready;
  wire job_owned,job_active,job_retired;
  logic [603:0] req=0;
  wire [511:0] rsp_data;
  wire [7:0] rsp_status,fault_code;
  wire [15:0] rsp_seq;
  wire [3:0] m_axi_awid,m_axi_arid,m_axi_bid,m_axi_rid;
  wire [30:0] m_axi_awaddr,m_axi_araddr;
  wire [7:0] m_axi_awlen,m_axi_arlen;
  wire [2:0] m_axi_awsize,m_axi_arsize,m_axi_awprot,m_axi_arprot;
  wire [1:0] m_axi_awburst,m_axi_arburst,m_axi_bresp,m_axi_rresp;
  wire m_axi_awlock,m_axi_arlock,m_axi_awvalid,m_axi_awready,m_axi_wlast,m_axi_wvalid,m_axi_wready;
  wire m_axi_bvalid,m_axi_bready,m_axi_arvalid,m_axi_arready,m_axi_rlast,m_axi_rvalid,m_axi_rready;
  wire [3:0] m_axi_awcache,m_axi_arcache,m_axi_awqos,m_axi_arqos;
  wire [511:0] m_axi_wdata,m_axi_rdata;
  wire [63:0] m_axi_wstrb;
  wire [31:0] m_axi_ctrl_awaddr,m_axi_ctrl_wdata,m_axi_ctrl_araddr,m_axi_ctrl_rdata;
  wire m_axi_ctrl_awvalid,m_axi_ctrl_awready,m_axi_ctrl_wvalid,m_axi_ctrl_wready;
  wire m_axi_ctrl_bvalid,m_axi_ctrl_bready,m_axi_ctrl_arvalid,m_axi_ctrl_arready;
  wire m_axi_ctrl_rvalid,m_axi_ctrl_rready,c0_interrupt;
  wire model_ctrl_arready,model_ctrl_rvalid,model_ctrl_arvalid,model_ctrl_rready;
  logic stall_ctrl=0;
  assign m_axi_ctrl_arready=model_ctrl_arready&&!stall_ctrl;
  assign m_axi_ctrl_rvalid=model_ctrl_rvalid&&!stall_ctrl;
  assign model_ctrl_arvalid=m_axi_ctrl_arvalid&&!stall_ctrl;
  assign model_ctrl_rready=m_axi_ctrl_rready&&!stall_ctrl;
  wire [1:0] m_axi_ctrl_bresp,m_axi_ctrl_rresp;
  logic jtag_link_healthy=1'b1,pcie_link_healthy=1'b1;
  wire [1:0] transport_owner;
  wire [31:0] transport_lease_epoch;
  wire transport_release_ready,pcie_irq,pcie_protocol_fault,pcie_epoch_fault,owner_protocol_fault;
  wire [7:0] owner_failure_code;
  logic [31:0] pcie_axil_awaddr=0,pcie_axil_wdata=0,pcie_axil_araddr=0;
  logic [2:0] pcie_axil_awprot=0,pcie_axil_arprot=0;
  logic [3:0] pcie_axil_wstrb=0;
  logic pcie_axil_awvalid=0,pcie_axil_wvalid=0,pcie_axil_bready=0;
  logic pcie_axil_arvalid=0,pcie_axil_rready=0;
  wire pcie_axil_awready,pcie_axil_wready;
  wire [1:0] pcie_axil_bresp,pcie_axil_rresp;
  wire pcie_axil_bvalid,pcie_axil_arready,pcie_axil_rvalid;
  wire [31:0] pcie_axil_rdata;
  rk_dual_host_ddr #(.BASE(BASE),.BYTES(BYTES),.TIMEOUT_CYCLES(2048),.MAX_TASKS(4),
    .RESET_WAIT_TIMEOUT_CYCLES(1024)) dut(.*);
  // The actual capacity ECC monitor contract supplies only status=0, onoff=1, IRQ mask=3.
  always @(posedge c0_ui_clk) begin
    if (dut.backend.capacity.bist.monitor.snapshot_valid === 1'b1 &&
        (dut.backend.capacity.bist.monitor.snapshot_status !== 32'h0 ||
         dut.backend.capacity.bist.monitor.snapshot_onoff !== 32'h1 ||
         dut.backend.capacity.bist.monitor.snapshot_irq_mask !== 32'h3))
      $fatal(1,"Retirement ECC snapshot tuple differs from the accepted monitor contract");
  end
  // External candidate invariant: without a live block, core_error must be exactly clear.
  always @(posedge c0_ui_clk) begin
    if (dut.backend.rst_n === 1'b1 && dut.backend.live_block === 1'b0 && dut.backend.core_error !== 1'b0)
      $fatal(1,"core_error asserted while reset is released and live_block is clear");
  end

  logic inj_ue_next_rmw=0,hold_phy_write_full=0,drop_read_return=0;
  wire [31:0] write_commit_count,read_return_count,pending_writes;
  wire inj_ue_fired;
  rk_mig_logic_model #(.BASE(BASE),.BYTES(1048576)) memory_model (
    .clk(c0_ui_clk),.rst(c0_ui_clk_sync_rst),.aresetn(c0_aresetn),
    .calib_complete(c0_init_calib_complete),.interrupt(c0_interrupt),
    .m_axi_ctrl_arready(model_ctrl_arready),.m_axi_ctrl_rvalid(model_ctrl_rvalid),
    .m_axi_ctrl_arvalid(model_ctrl_arvalid),.m_axi_ctrl_rready(model_ctrl_rready),.*
  );

  integer commands,init_aw,init_w,job_aw,retired_count,dma_launches,fabric_claims;
  integer data_ar_count,read64_packets,read64_axi_reads;
  logic old_irq;
  logic [30:0] final_job_aw,final_job_ar;
  logic [31:0] csr_base=0;
  wire [31:0] selected_identity=32'h524b4144;
  logic [15:0] sequence_id;
  logic inj_seen;
  logic [511:0] value,upload_line,expected_line;
  logic [31:0] address,start_address,start_amount,tag;
  integer upload_count,expected_tasks;
  integer fd,observed,polls,uploaded_nonzero,submissions;
  integer prior_dma_launches;
  string vector_dir,out_dir,prefix,output_path;
  `include "strict_line_image.svh"
  always @(posedge c0_ui_clk) begin
    if(!c0_clients_rst_n)begin
      init_aw<=0;init_w<=0;job_aw<=0;retired_count<=0;
      old_irq<=0;inj_seen<=0;final_job_aw<=0;final_job_ar<=0;
      dma_launches<=0;fabric_claims<=0;
      data_ar_count<=0;
    end else begin
      if(m_axi_arvalid&&m_axi_arready)data_ar_count<=data_ar_count+1;
      old_irq<=irq;
      if(inj_ue_fired)inj_seen<=1;
      if(dut.backend.dma_start_valid&&dut.backend.dma_start_ready)dma_launches<=dma_launches+1;
      if(dut.backend.job_begin&&dut.backend.job_begin_ready)fabric_claims<=fabric_claims+1;
      if(init_active&&m_axi_awvalid&&m_axi_awready)begin
        if({1'b0,m_axi_awaddr}!==BASE+32'(init_aw*64))$fatal(1,"Initialization address sequence");
        init_aw<=init_aw+1;
      end
      if(init_active&&m_axi_wvalid&&m_axi_wready)begin
        if(m_axi_wdata!==0||m_axi_wstrb!==64'hffffffffffffffff||m_axi_wlast!==1)
          $fatal(1,"Initialization must write complete zero/ECC beats");
        init_w<=init_w+1;
      end
      if(job_active&&m_axi_awvalid&&m_axi_awready)begin
        final_job_aw<=m_axi_awaddr;job_aw<=job_aw+1;
      end
      if(job_active&&m_axi_arvalid&&m_axi_arready)final_job_ar<=m_axi_araddr;
      if(job_retired)begin
        if(pending_writes!==0||final_job_ar!==final_job_aw||job_aw==0)
          $fatal(1,"Job retired before actual writes/exact-address fence");
        retired_count<=retired_count+1;
      end
      if(irq&&!old_irq&&!fault&&pending_writes!==0)$fatal(1,"Successful IRQ while PHY writes pending");
    end
  end

  task automatic command(input logic[7:0]op,input logic[31:0]address,input logic[511:0]data,
    output logic[511:0]result,input logic[7:0]status=0,input logic[3:0]strobes=15);
    integer guard,reads_before;
    guard=0;while(!req_ready)begin @(negedge c0_ui_clk);guard=guard+1;if(guard>5000)$fatal(1,"Frame admission stalled");end
    reads_before=data_ar_count;
    @(negedge c0_ui_clk);sequence_id=sequence_id==16'hffff ? 16'd1 : sequence_id+1;
    req={32'h4f54504a,sequence_id,op,strobes,address,data};req_valid=1;
    @(negedge c0_ui_clk);req_valid=0;req='0;guard=0;
    while(!rsp_valid)begin @(negedge c0_ui_clk);guard=guard+1;if(guard>20000)$fatal(1,"Frame response stalled op%0d",op);end
    if(rsp_seq!==sequence_id||rsp_status!==status)$fatal(1,"Frame error op%0d status%h expected%h",op,rsp_status,status);
    if(op==3&&status==0)begin
      if(data_ar_count-reads_before!=1)$fatal(1,"READ64 must use exactly one physical AXI read, got%0d",data_ar_count-reads_before);
      read64_packets=read64_packets+1;read64_axi_reads=read64_axi_reads+data_ar_count-reads_before;
    end
    result=rsp_data;if(status!=0&&result!==0)$fatal(1,"Error leaked payload");
    commands=commands+1;@(negedge c0_ui_clk);
  endtask

  function automatic bit job_status_has_error(input logic [511:0] snapshot);
    job_status_has_error=snapshot[3]!==1'b0||snapshot[5]!==1'b0||snapshot[7]!==1'b0||
                          snapshot[511:11]!==501'd0||(^snapshot)===1'bx;
  endfunction
  task automatic pcie_axil_write(input logic [31:0] off,input logic [31:0] data);
    integer guard;
    begin
      guard=0; @(negedge c0_ui_clk); pcie_axil_awaddr=off;pcie_axil_awprot=0;pcie_axil_awvalid=1;
      pcie_axil_wdata=data;pcie_axil_wstrb=4'hf;pcie_axil_wvalid=1;pcie_axil_bready=1;
      while(!(pcie_axil_awready&&pcie_axil_wready)) begin @(negedge c0_ui_clk);guard=guard+1;if(guard>100)$fatal(1,"PCIe AXI write admission timeout");end
      @(negedge c0_ui_clk);pcie_axil_awvalid=0;pcie_axil_wvalid=0;
      while(!pcie_axil_bvalid) begin @(negedge c0_ui_clk);guard=guard+1;if(guard>200)$fatal(1,"PCIe AXI B timeout");end
      if(pcie_axil_bresp!==0)$fatal(1,"PCIe AXI write response %b at %h",pcie_axil_bresp,off);
      @(negedge c0_ui_clk);pcie_axil_bready=0;
    end
  endtask
  task automatic pcie_axil_read(input logic [31:0] off,output logic [31:0] data);
    integer guard;
    begin
      guard=0;@(negedge c0_ui_clk);pcie_axil_araddr=off;pcie_axil_arprot=0;pcie_axil_arvalid=1;pcie_axil_rready=1;
      while(!pcie_axil_arready)begin @(negedge c0_ui_clk);guard=guard+1;if(guard>100)$fatal(1,"PCIe AXI AR timeout");end
      @(negedge c0_ui_clk);pcie_axil_arvalid=0;
      while(!pcie_axil_rvalid)begin @(negedge c0_ui_clk);guard=guard+1;if(guard>200)$fatal(1,"PCIe AXI R timeout");end
      if(pcie_axil_rresp!==0)$fatal(1,"PCIe AXI read response %b at %h",pcie_axil_rresp,off);
      data=pcie_axil_rdata;@(negedge c0_ui_clk);pcie_axil_rready=0;
    end
  endtask

  logic [15:0] pcie_sequence=16'h7000;
  logic [639:0] pcie_packet,pcie_reply;
  task automatic pcie_command(input logic [7:0] op,input logic [31:0] off,
      input logic [511:0] data,input logic [7:0] expected_status,output logic [511:0] result);
    logic [31:0] word,status_word;
    integer guard,reads_before;
    begin
      reads_before=data_ar_count;
      pcie_sequence=pcie_sequence+1'b1;
      pcie_packet={36'd0,32'h4f54504a,pcie_sequence,op,4'hf,off,data};
      for(integer k=0;k<20;k++)pcie_axil_write(32'h40+32'(4*k),pcie_packet[k*32 +:32]);
      pcie_axil_write(32'h0c,32'd1);
      guard=0;status_word=0;
      while(!status_word[2])begin
        pcie_axil_read(32'h08,status_word);guard=guard+1;
        if(status_word[3])$fatal(1,"PCIe mailbox protocol fault during op%0d",op);
        if(guard>20000)$fatal(1,"PCIe packet response timeout op%0d",op);
      end
      for(integer k=0;k<20;k++)begin
        pcie_axil_read(32'h100+32'(4*k),word);pcie_reply[k*32 +:32]=word;
      end
      if(pcie_reply[639:568]!==72'd0 || pcie_reply[567:536]!==32'h4f54504a ||
          pcie_reply[535:520]!==pcie_sequence || pcie_reply[519:512]!==expected_status)
        $fatal(1,"PCIe response mismatch seq=%h reserved=%h magic=%h seqgot=%h status=%h",pcie_sequence,
          pcie_reply[639:568],pcie_reply[567:536],pcie_reply[535:520],pcie_reply[519:512]);
      if(op==3 && expected_status==0)begin
        if(data_ar_count-reads_before!=1)$fatal(1,"PCIe READ64 must use exactly one physical AXI read");
        read64_packets=read64_packets+1;read64_axi_reads=read64_axi_reads+data_ar_count-reads_before;
      end
      result=pcie_reply[511:0];
      if(expected_status!=0 && result!==0)$fatal(1,"PCIe error response leaked payload");
      pcie_axil_write(32'h0c,32'd2);
    end
  endtask
  task automatic check_memory_pcie;
    logic [31:0] previous_address,line_address;
    logic [511:0] line_expected,line_result;
    integer line_fd,observed_fd;
    begin
      ddr_image_open({prefix,"/expected.txt"},upload_count,line_fd);
      observed_fd=$fopen(output_path,"w");if(observed_fd==0)$fatal(1,"PCIe readback output unavailable");
      previous_address=0;
      for(integer line=0;line<upload_count;line++)begin
        ddr_image_read(line_fd,line,previous_address,line_address,line_expected);previous_address=line_address;
        pcie_command(3,line_address,512'd0,0,line_result);
        if(line_result!==line_expected)$fatal(1,"PCIe-owned DDR BO mismatch at %h",line_address);
        $fdisplay(observed_fd,"%08h %0128h",line_address,line_result);
      end
      ddr_image_finish(line_fd);$fclose(observed_fd);
    end
  endtask
  task automatic await_transport_release(input logic [1:0] expected_owner);
    integer guard;
    begin
      guard=0;
      while(!transport_release_ready)begin
        @(negedge c0_ui_clk);guard=guard+1;
        if(transport_owner!==expected_owner)$fatal(1,"Transport owner changed while waiting for hardware release witness");
        if(guard>2048)$fatal(1,"Hardware release witness did not settle within bounded UI wait");
      end
      if(transport_owner!==expected_owner)$fatal(1,"Transport owner changed before witnessed release");
    end
  endtask
  task automatic replay_ew_sub9_from_pcie;
    logic [511:0] got;
    integer guard;
    begin
      prefix=vector_dir;
      output_path=$sformatf("%s/pcie-ew-sub9-observed.txt",out_dir);
      upload_count=1600;
      pcie_command(2,32'h60c,512'd1,0,got);
      if(transport_owner!==2'd2 || transport_lease_epoch!==32'd2)$fatal(1,"PCIe lease epoch/owner mismatch");
      pcie_command(2,32'h10,512'h00000000100e0000,0,got);
      pcie_command(2,32'h14,512'd35,0,got);
      pcie_command(2,32'h18,512'h35882003,0,got);
      pcie_command(2,32'h00c,512'd1,0,got);
      submissions=submissions+1;
      if(!job_active)$fatal(1,"EW job completed before nonowner in-flight controls");
      prior_dma_launches=dma_launches;
      // These must be denied by the owner mux without reaching or cancelling the live NPU job.
      command(4,BASE,512'h1,value,2);
      command(2,32'h50c,512'd1,value,2);
      command(2,32'h00c,512'd2,value,2);
      if(dma_launches!=prior_dma_launches || !job_active)$fatal(1,"nonowner controls altered live backend job");
      guard=0;got=0;
      while(!got[2])begin
        pcie_command(1,32'h08,512'd0,0,got);guard=guard+1;
        if(job_status_has_error(got)||fault)$fatal(1,"PCIe replay status/fault failure");
        if(guard>100000)$fatal(1,"PCIe EW replay poll timeout");
      end
      if(!irq || !pcie_irq || transport_release_ready)$fatal(1,"Held-result release witness must remain low before NPU ACK");
      pcie_command(2,32'h60c,512'd2,2,got);
      if(transport_owner!==2'd2)$fatal(1,"Held PCIe result release changed owner");
      pcie_command(1,32'h1c,512'd0,0,got);if(got[31:0]!==32'h35882003)$fatal(1,"PCIe result tag mismatch");
      pcie_command(1,32'h20,512'd0,0,got);if(got[31:0]!==2)$fatal(1,"PCIe task count mismatch");
      pcie_command(1,32'h24,512'd0,0,got);if(got[31:0]!==0)$fatal(1,"PCIe error status mismatch");
      check_memory_pcie();
      pcie_command(2,32'h00c,512'd2,0,got);
      guard=0;
      while(!transport_release_ready)begin
        @(negedge c0_ui_clk);guard=guard+1;
        if(transport_owner!==2'd2)$fatal(1,"Outer PCIe packet ACK unexpectedly released global owner");
        if(guard>2048)$fatal(1,"Hardware release witness did not settle within bounded UI wait");
      end
      if(transport_owner!==2'd2)$fatal(1,"Outer PCIe packet ACK unexpectedly released global owner");
      pcie_command(2,32'h60c,512'd2,0,got);
      if(transport_owner!==0)$fatal(1,"PCIe lease did not release");
      $display("DUAL_HOST_PCIE_EW_SUB9_PASS jobs=1 tasks=2 bo_lines=1600 ack_after_complete_readback=1 outer_packet_ack_kept_owner=1");$fflush();
    end
  endtask
  task automatic register_command(input logic[7:0]op,input logic[31:0]offset,
    input logic[511:0]data,output logic[511:0]result,input logic[7:0]status=0,
    input logic[3:0]strobes=15);
    command(op,offset<32'h100 ? csr_base+offset : offset,data,result,status,strobes);
  endtask
  task automatic report_boot_state(input string phase);
    $display("DDR_BOOT phase=%s time=%0t sys_reset=%b mig_sys_rst_n=%b sys_clients_rst_n=%b c0_clients_rst_n=%b c1_clients_rst_n=%b c0_ui_sync_rst=%b c1_ui_sync_rst=%b c0_trained=%b seq_busy=%b seq_complete=%b seq_fault=%b seq_fault_code=%02h admission_blocked=%b req_ready=%b fault=%b fault_code=%02h init_active=%b init_complete=%b memory_ready=%b init_aw=%0d init_w=%0d commits=%0d pending=%0d",
      phase,$time,cfg_reset,mig_sys_rst_n,sys_clients_rst_n,c0_clients_rst_n,c1_clients_rst_n,
      c0_ui_clk_sync_rst,c1_ui_clk_sync_rst,c0_trained,sequence_busy,sequence_complete,
      sequence_fault,sequence_fault_code,admission_blocked,req_ready,fault,fault_code,
      init_active,init_complete,memory_ready,init_aw,init_w,write_commit_count,pending_writes);
    $fflush();
  endtask
  // Optional progress independent of the main stimulus coroutine: distinguish
  // slow advancing simulation from a frame wait or initialization fault.
  bit boot_tick_enabled;
  integer boot_tick_cycles;
  initial boot_tick_cycles=0;
  initial boot_tick_enabled=$test$plusargs("DDR_BOOT_TICK");
  always @(posedge c0_ui_clk) begin
    if(!c0_clients_rst_n)boot_tick_cycles<=0;
    else if(boot_tick_enabled)begin
      boot_tick_cycles<=boot_tick_cycles+1;
      if((boot_tick_cycles%1024)==0)begin
        report_boot_state("independent_ui_tick");
        $display("DDR_BUS tick=%0d req_valid=%b rsp_valid=%b rsp_status=%02h ctrl_AW=%b/%b ctrl_W=%b/%b ctrl_B=%b/%b ctrl_AR=%b/%b ctrl_R=%b/%b mem_AW=%b/%b mem_W=%b/%b mem_B=%b/%b mem_AR=%b/%b mem_R=%b/%b",
          boot_tick_cycles,req_valid,rsp_valid,rsp_status,m_axi_ctrl_awvalid,m_axi_ctrl_awready,
          m_axi_ctrl_wvalid,m_axi_ctrl_wready,m_axi_ctrl_bvalid,m_axi_ctrl_bready,
          m_axi_ctrl_arvalid,m_axi_ctrl_arready,m_axi_ctrl_rvalid,m_axi_ctrl_rready,
          m_axi_awvalid,m_axi_awready,m_axi_wvalid,m_axi_wready,m_axi_bvalid,m_axi_bready,
          m_axi_arvalid,m_axi_arready,m_axi_rvalid,m_axi_rready);
        $fflush();
      end
    end
  end
  task automatic expect_reg(input logic[31:0]off,input logic[31:0]expected);
    register_command(1,off,0,value);if(value!=={480'b0,expected})$fatal(1,"Register%h got%h expected%h",off,value,expected);
  endtask
  task automatic check_memory;
    logic [31:0] previous_address;
    ddr_image_open({prefix,"/expected.txt"},upload_count,fd);observed=$fopen(output_path,"w");
    if(observed==0)$fatal(1,"Readback output unavailable");
    previous_address=0;
    for(integer line=0;line<upload_count;line=line+1)begin
      ddr_image_read(fd,line,previous_address,address,expected_line);previous_address=address;
      command(3,address,0,value);
      if(value!==expected_line)$fatal(1,"DDR BO mismatch at%h got%h expected%h",address,value,expected_line);
      $fdisplay(observed,"%08h %0128h",address,value);
    end
    ddr_image_finish(fd);$fclose(observed);
  endtask
  task automatic await_initialization;
    polls=0;
    while(!init_complete&&!fault)begin
      @(negedge c0_ui_clk);polls=polls+1;
      if(polls%100000==0)report_boot_state("initializing");
      if(polls>2000000)$fatal(1,"Init timeout");
    end
    if(fault||!memory_ready||c0_aresetn!==1'b1||c1_aresetn!==1'b1||
       init_aw!=16384||init_w!=16384||write_commit_count!=16384||pending_writes!=0)
      $fatal(1,"Incomplete hardware initialization aw%0d w%0d committed%0d",init_aw,init_w,write_commit_count);
  endtask
  task automatic upload_images;
    logic [31:0] previous_address;
    ddr_image_open({prefix,"/upload.txt"},upload_count,fd);uploaded_nonzero=0;previous_address=0;
    for(integer line=0;line<upload_count;line=line+1)begin
      ddr_image_read(fd,line,previous_address,address,upload_line);previous_address=address;
      // Hardware already zeroed every line. Omit redundant zero copies while
      // preserving every raw BO byte, including complete padding/readback.
      if(upload_line!==0)begin command(4,address,upload_line,value);uploaded_nonzero=uploaded_nonzero+1;end
    end
    ddr_image_finish(fd);
  endtask
  task automatic run_case(input string case_dir,input string observed_path,input logic [31:0] case_start,
      input logic [31:0] case_amount,input integer case_tasks,input integer case_lines,
      input logic [31:0] case_csr_base,input logic [31:0] case_tag);
    begin
      prefix=case_dir;output_path=observed_path;start_address=case_start;start_amount=case_amount;
      expected_tasks=case_tasks;upload_count=case_lines;csr_base=case_csr_base;
      $display("CASE_CSR_SELECT base=%08h selected_identity=%08h",csr_base,selected_identity);$fflush();
      expect_reg(0,case_csr_base==32'h100 ? 32'h524b4344 : 32'h524b4144);expect_reg(4,32'h00010000);
      upload_images();
      register_command(2,32'h10,{480'b0,start_address},value);
      if(transport_release_ready)$fatal(1,"Address-only descriptor staging did not block release");
      command(2,32'h60c,512'd2,value,2);
      register_command(2,32'h14,{480'b0,start_amount},value);
      register_command(2,32'h18,{480'b0,case_tag},value);
      register_command(2,32'h0c,512'd1,value);submissions=submissions+1;
      polls=0;value=0;
      while(!value[2])begin
        register_command(1,8,0,value);polls=polls+1;
        if(job_status_has_error(value)||fault)$fatal(1,"normal job poll error status=%h fault=%b",value,fault);
        if(polls>100000)$fatal(1,"normal result timeout");
      end
      if(value[1]||value[3]||!irq||fault)$fatal(1,"normal job result/fault mismatch %h",value);
      expect_reg(32'h1c,case_tag);expect_reg(32'h20,32'(case_tasks));expect_reg(32'h24,0);
      if(retired_count!=submissions||pending_writes!=0)$fatal(1,"normal job did not retire");
      check_memory();
      command(2,32'h60c,512'd2,value,2);
      if(transport_owner!==2'd1)$fatal(1,"Held result release changed JTAG owner");
      register_command(2,32'h0c,512'd2,value);
      polls=0;while(job_owned||!memory_ready)begin @(negedge c0_ui_clk);polls=polls+1;if(polls>1000)$fatal(1,"ACK did not release normal owner");end
      $display("NORMAL_CASE_PASS csr_base=%08h lines=%0d tasks=%0d read64=%0d axi_reads=%0d",csr_base,upload_count,expected_tasks,read64_packets,read64_axi_reads);$fflush();
    end
  endtask
  initial begin : replay
    if(!$value$plusargs("VECTORS=%s",vector_dir) || vector_dir.len()==0)
      $fatal(1,"Required +VECTORS=<dir>");
    if(!$value$plusargs("OUT=%s",out_dir) || out_dir.len()==0)
      $fatal(1,"Required +OUT=<freshdir>");
    cfg_reset=1;reset_req_valid=0;c0_ui_clk_sync_rst=1;c1_ui_clk_sync_rst=1;c0_trained=0;
    commands=0;sequence_id=16'hfffe;submissions=0;
    read64_packets=0;read64_axi_reads=0;csr_base=0;
    repeat(5)@(negedge sys_clk);cfg_reset=0;report_boot_state("reset_deasserted");
    polls=0;while(req_ready!==1'b1)begin @(negedge c0_ui_clk);polls=polls+1;if(polls>10000)$fatal(1,"first req_ready timeout");end
    report_boot_state("first_req_ready");
    if(init_complete || transport_release_ready)$fatal(1,"Expected boot-time uninitialized backend");
    command(2,32'h60c,512'd1,value,2);
    if(transport_owner!==0 || transport_lease_epoch!==0)$fatal(1,"Early denied acquire changed lease");
    command(3,BASE,0,value,2);
    await_initialization();
    await_transport_release(2'd0);
    command(2,32'h60c,512'd1,value);
    if(transport_owner!==2'd1 || transport_lease_epoch!==32'd1)
      $fatal(1,"JTAG source did not acquire first hardware lease");
    command(1,0,0,value);if(value!=={480'b0,32'h524b4144})$fatal(1,"RKAD identity");
    command(1,4,0,value);if(value!=={480'b0,32'h00010000})$fatal(1,"RKAD ABI");
    command(1,32'h100,0,value);if(value!=={480'b0,32'h524b4344})$fatal(1,"RKCD identity");
    command(1,32'h104,0,value);if(value!=={480'b0,32'h00010000})$fatal(1,"RKCD ABI");
    command(1,32'h200,0,value);if(value!=={480'b0,32'h524b4d54})$fatal(1,"RKMT identity");
    command(1,32'h204,0,value);if(value!=={480'b0,32'h00010000})$fatal(1,"RKMT ABI");
    command(3,BASE,0,value);if(value!==0)$fatal(1,"Initialized first line nonzero");
    command(3,BASE+32'h000fffc0,0,value);if(value!==0)$fatal(1,"initial last line nonzero");
    value=512'h0123456789abcdef00112233445566778899aabbccddeeffcafebabedeadbeef;
    command(4,BASE+32'h000fffc0,value,upload_line);command(3,BASE+32'h000fffc0,0,expected_line);
    if(expected_line!==value)$fatal(1,"raw host memory R/W mismatch");
    command(4,BASE+32'h000fffc0,0,upload_line);
    run_case(vector_dir,$sformatf("%s/jtag-ew-sub9-observed.txt",out_dir),
      32'h100e0000,35,2,1600,0,32'h35882002);
    await_transport_release(2'd1);
    command(2,32'h60c,512'd2,value);
    if(transport_owner!==0)$fatal(1,"JTAG global lease did not release");
    $display("DUAL_HOST_JTAG_EW_SUB9_PASS jobs=1 tasks=2 bo_lines=1600 ack_after_complete_readback=1");$fflush();
    replay_ew_sub9_from_pcie();
    if(pcie_protocol_fault || pcie_epoch_fault || owner_protocol_fault || owner_failure_code!=0)
      $fatal(1,"Unexpected frontend ownership/protocol fault");
    if(read64_packets!=3203 || read64_axi_reads!=3203)
      $fatal(1,"Expected 3203 exact physical READ64 operations packets=%0d axi_reads=%0d",read64_packets,read64_axi_reads);
    if(retired_count!=2 || submissions!=2 || dma_launches!=2 || fabric_claims!=2)
      $fatal(1,"Final job/task retirement counters mismatch jobs=%0d retired=%0d dma=%0d fabric=%0d",submissions,retired_count,dma_launches,fabric_claims);
    if(transport_owner!==0 || transport_lease_epoch!==2)
      $fatal(1,"Final ownership/epoch mismatch owner=%0d epoch=%0d",transport_owner,transport_lease_epoch);
    $display("DUAL_HOST_NPU_REPLAY_PASS jobs=2 tasks=4 bo_images=2 bo_bytes=204800 physical_read64=3203 lease_epoch=2 owner=0");$fflush();
    $finish;
  end
  initial begin repeat(100000000)@(posedge c0_ui_clk);$fatal(1,"Joined DDR watchdog");end
endmodule
