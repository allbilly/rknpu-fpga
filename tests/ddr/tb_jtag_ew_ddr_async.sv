// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Raw public frames -> real EW RTL -> AXI/UI/MC logic with encoded DRAM model.
// Training, pads, clocks and actual FPGA operation are outside this test.
module tb_jtag_ew_ddr_async;
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
  rk_jtag_ew_ddr_async #(.BASE(BASE),.BYTES(BYTES),.TIMEOUT_CYCLES(2048),.MAX_TASKS(4),
    .RESET_WAIT_TIMEOUT_CYCLES(1024)) dut(.*);

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
  logic old_irq,inj_seen;
  logic [30:0] final_job_aw,final_job_ar;
  always @(posedge c0_ui_clk) begin
    if(!c0_clients_rst_n)begin
      init_aw<=0;init_w<=0;job_aw<=0;retired_count<=0;
      old_irq<=0;inj_seen<=0;final_job_aw<=0;final_job_ar<=0;
      dma_launches<=0;fabric_claims<=0;
    end else begin
      old_irq<=irq;
      if(inj_ue_fired)inj_seen<=1;
      if(dut.dma_start_valid&&dut.dma_start_ready)dma_launches<=dma_launches+1;
      if(dut.job_begin&&dut.job_begin_ready)fabric_claims<=fabric_claims+1;
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

  logic [15:0] sequence_id;
  task automatic command(input logic[7:0]op,input logic[31:0]address,input logic[511:0]data,
    output logic[511:0]result,input logic[7:0]status=0,input logic[3:0]strobes=15);
    integer guard;
    guard=0;while(!req_ready)begin @(negedge c0_ui_clk);guard=guard+1;if(guard>5000)$fatal(1,"Frame admission stalled");end
    @(negedge c0_ui_clk);sequence_id=sequence_id==16'hffff ? 16'd1 : sequence_id+1;
    req={32'h4f54504a,sequence_id,op,strobes,address,data};req_valid=1;
    @(negedge c0_ui_clk);req_valid=0;guard=0;
    while(!rsp_valid)begin @(negedge c0_ui_clk);guard=guard+1;if(guard>20000)$fatal(1,"Frame response stalled op%0d",op);end
    if(rsp_seq!==sequence_id||rsp_status!==status)$fatal(1,"Frame error op%0d status%h expected%h",op,rsp_status,status);
    result=rsp_data;if(status!=0&&result!==0)$fatal(1,"Error leaked payload");
    commands=commands+1;@(negedge c0_ui_clk);
  endtask
  logic [511:0] value,upload_line,expected_line;
  logic [31:0] address,start_address,start_amount,tag;
  integer upload_count,expected_tasks,jobs,negative_mode,original_negative;
  integer fd,observed,polls,uploaded_nonzero,submissions,reset_recovery,recovered;
  integer prior_dma_launches,prior_fabric_claims;
  logic expect_error,stop_after_error;
  string prefix,output_path;
/* verilator lint_off INCABSPATH */
`include `RK_DDR_LINE_IMAGE_HEADER
/* verilator lint_on INCABSPATH */
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
    command(1,off,0,value);if(value!=={480'b0,expected})$fatal(1,"Register%h got%h expected%h",off,value,expected);
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
  // All paths meet one completion point; no same-cycle fallthrough after $finish.
  initial begin
    cfg_reset=1;reset_req_valid=0;c0_ui_clk_sync_rst=1;c1_ui_clk_sync_rst=1;
    c0_trained=0;commands=0;sequence_id=16'hfffe;submissions=0;recovered=0;stop_after_error=0;
    if(!$value$plusargs("CASE=%s",prefix)||!$value$plusargs("OUTPUT=%s",output_path)||
       !$value$plusargs("START=%h",start_address)||!$value$plusargs("AMOUNT=%d",start_amount)||
       !$value$plusargs("NTASKS=%d",expected_tasks)||!$value$plusargs("NLINES=%d",upload_count))$fatal(1,"Missing metadata");
    if(!$value$plusargs("JOBS=%d",jobs))jobs=1;
    if(!$value$plusargs("NEGATIVE=%d",negative_mode))negative_mode=0;
    original_negative=negative_mode;
    if(!$value$plusargs("RESET_RECOVERY=%d",reset_recovery))reset_recovery=0;
    repeat(5)@(negedge sys_clk);cfg_reset=0;
    report_boot_state("reset_deasserted");
    polls=0;
    while(req_ready!==1'b1)begin
      @(negedge c0_ui_clk);polls=polls+1;
      if(polls%64==0)report_boot_state("waiting_for_first_req_ready");
      if(polls>=10000)begin
        report_boot_state("first_req_ready_timeout");
        $fatal(1,"First frame admission timeout after %0d C0 UI cycles",polls);
      end
    end
    report_boot_state("first_req_ready");
    expect_reg(0,32'h524b4144);expect_reg(4,32'h00010000);
    command(3,BASE,0,value,2); // Hardware initialization owns memory.
    await_initialization();
    command(3,BASE,0,value);if(value!==0)$fatal(1,"First initialized line notzero");
    command(3,BASE+32'h000fffc0,0,value);if(value!==0)$fatal(1,"Last initialized line notzero");
    command(4,BASE+32'h000fffc0,0,value); // Explicit all-zero host write path.
    command(1,32'h80000000,0,value,3);command(2,0,0,value,2);
    command(3,32'h90000000,0,value,6);command(3,BASE+2,0,value,4);
    if(negative_mode==9)begin
      // The public backend starts its per-word timer before the fabric AR.
      // Its timeout must retain E8 despite the fabric's derived abort E5.
      uploaded_nonzero=0;
      @(negedge c0_ui_clk);drop_read_return=1;
      command(3,BASE,0,value,8'h80);
      repeat(5)@(negedge c0_ui_clk);
      if(!fault||fault_code!==8'd8||irq||job_active||dma_launches!=0||fabric_claims!=0)
        $fatal(1,"HOST timeout lost its first cause or launched a job");
      @(negedge c0_ui_clk);drop_read_return=0;
      repeat(100)@(negedge c0_ui_clk);
      if(!fault||fault_code!==8'd8||req_ready||memory_ready)
        $fatal(1,"HOST timeout quarantine recovered without joint reset");
    end else begin
      upload_images();
      if(negative_mode==1)begin
        command(3,start_address&32'hffffffc0,0,value);
        value[8*(start_address[5:0]+6)+:16]=16'hffff;
        command(4,start_address&32'hffffffc0,value,upload_line);
      end
      for(integer job=0;job<jobs&&!stop_after_error;job=job+1)begin
        expect_error=negative_mode!=0&&(negative_mode!=6||job==jobs-1);
        tag=32'h35880000+32'(job);command(2,32'h10,{480'b0,start_address},value);
        command(2,32'h14,{480'b0,start_amount},value);command(2,32'h18,{480'b0,tag},value);
        prior_dma_launches=dma_launches;prior_fabric_claims=fabric_claims;
        if(negative_mode==6&&expect_error)begin
          if(job==0||expected_tasks<=0||prior_dma_launches==0||dut.dma_completed_tasks!==32'(expected_tasks))
            $fatal(1,"Queued-fault control requires a prior completed nonempty job");
          fork
            begin
              // Read-only observation locates the exact queued-descriptor edge;
              // only the external calibration input is changed, never DUT state.
              wait(dut.core_start_valid===1'b1);
              @(negedge c0_ui_clk);lose_calibration=1;
            end
            command(2,32'h0c,512'd1,value);
          join
        end else command(2,32'h0c,512'd1,value);
        submissions=submissions+1;
        if(negative_mode==2)begin @(negedge c0_ui_clk);inj_ue_next_rmw=1;@(negedge c0_ui_clk);inj_ue_next_rmw=0;end
        if(negative_mode==3)begin @(negedge c0_ui_clk);drop_read_return=1;end
        if(negative_mode==4)begin @(negedge c0_ui_clk);hold_phy_write_full=1;end
        if(negative_mode==5)begin @(negedge c0_ui_clk);lose_calibration=1;end
        if(negative_mode==7)begin @(negedge c0_ui_clk);stall_ctrl=1;end
        if(negative_mode==10)begin
          // Observe an actual SYS-domain task completion, then change only
          // the external calibration input. The UI result must wait for the
          // terminal core snapshot and preserve1, not invent a zero count.
          if(expected_tasks!=2)$fatal(1,"Partial-count control requires the original two-task SUB9");
          polls=0;
          while(dut.engine.engine.completed_tasks!==32'd1)begin
            @(negedge sys_clk);polls=polls+1;
            if(polls>100000)$fatal(1,"First actual task did not complete before fault injection");
          end
          @(negedge c0_ui_clk);lose_calibration=1;
        end
        command(3,BASE+32'h40000,0,value,2);command(4,BASE+32'h40000,0,value,2);
        polls=0;value=0;
        while(!value[2])begin command(1,8,0,value);polls=polls+1;if(polls>100000)$fatal(1,"Job result timeout");end
        if(value[1]||value[3]!=(expect_error&&negative_mode!=8)||!irq)$fatal(1,"Bad job result%h fault%0d code%0d",value,fault,fault_code);
        expect_reg(32'h1c,tag);
        if(negative_mode==8)begin
          @(negedge c0_ui_clk);lose_calibration=1;
          repeat(5)@(negedge c0_ui_clk);
          command(1,8,0,value);
          if(!value[2]||!value[3]||!value[5])$fatal(1,"Late fault left pending result successful");
        end
        if(expect_error)begin
          if(!fault)$fatal(1,"Error not quarantined");
          if(negative_mode==2&&!inj_seen)$fatal(1,"UE injection did not reach a real RMW return");
          expect_reg(32'h24,negative_mode==1?32'd1:((negative_mode==3||negative_mode==4||negative_mode==7)?32'd8:32'd5));
          if(negative_mode==6)begin
            if(dma_launches!=prior_dma_launches||fabric_claims!=prior_fabric_claims||
               dut.dma_completed_tasks!==32'(expected_tasks))
              $fatal(1,"Faulted queued descriptor launched work or erased prior raw task history");
            expect_reg(32'h20,0);
          end
          if(negative_mode==10)begin
            expect_reg(32'h20,32'd1);
            if(dut.dma_completed_tasks!==32'd1)$fatal(1,"Cross-clock terminal snapshot lost the completed task");
            $display("CHECKED partial_task_fault completed=1 ui_code=5");
          end
          command(2,32'h0c,512'd2,value,2);
          @(negedge c0_ui_clk);drop_read_return=0;hold_phy_write_full=0;lose_calibration=0;stall_ctrl=0;
          repeat(100)@(negedge c0_ui_clk);
          if(!fault||memory_ready)$fatal(1,"Health return cleared quarantine");
          command(3,BASE,0,value,2);
          if(reset_recovery!=0&&recovered==0)begin
            @(negedge sys_clk);reset_req_valid=1;
            do @(posedge sys_clk);while(!reset_req_ready);
            @(negedge sys_clk);reset_req_valid=0;
            wait(!init_complete);await_initialization();
            command(3,start_address&32'hffffffc0,0,value);
            if(value!==0)$fatal(1,"Reset epoch did not invalidate and reinitialize old BO data");
            expect_reg(0,32'h524b4144);upload_images();
            negative_mode=0;recovered=1;job=-1;
          end else stop_after_error=1;
        end else begin
          if(fault||retired_count!=job+1||pending_writes!=0)$fatal(1,"Unretired success");
          expect_reg(32'h20,32'(expected_tasks));expect_reg(32'h24,0);
          command(4,BASE+32'h40000,0,value,2);if(fault)$fatal(1,"RESULT write rejection poisoned endpoint");
          check_memory();command(2,32'h0c,512'd2,value);
          polls=0;while(job_owned||!memory_ready)begin @(negedge c0_ui_clk);polls=polls+1;if(polls>100)$fatal(1,"ACK didnotrelease owner");end
        end
      end
    end // Non-HOST-timeout test sequence.
    $display("PASS jtag_ew_ddr_async jobs=%0d negative=%0d recovered=%0d lines=%0d uploaded_nonzero=%0d rawtasks=%0d phy_user_returns=%0d scope=actual_AXI_UI_MC_modeled_PHY",submissions,original_negative,recovered,upload_count,uploaded_nonzero,expected_tasks,read_return_count);
    $finish;
  end
  initial begin repeat(100000000)@(posedge c0_ui_clk);$fatal(1,"Joined DDR watchdog");end
endmodule
