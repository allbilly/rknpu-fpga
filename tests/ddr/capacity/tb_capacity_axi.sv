`timescale 1ns/1ps
module tb_capacity_axi #(
  parameter logic [30:0] BASE_ADDR=0,
  parameter logic [31:0] SPAN_BYTES=256,
  parameter integer TIMEOUT_CYCLES=32
);
  localparam integer LINES=SPAN_BYTES/64;
  logic clk;initial clk=0;always #5 clk=~clk;
  logic joint_rst_n,calibration_complete,initialization_complete,owner_exclusive,mig_interrupt;
  logic monitor_healthy,monitor_fault;logic [7:0] monitor_fault_code;
  logic sw_start_valid,sw_start_ready;logic [31:0] sw_seed;
  logic sw_busy,sw_done,sw_fault;logic [7:0] sw_fault_code;logic sw_trial;
  logic [31:0] sw_completed_writes,sw_completed_reads;logic [30:0] sw_mismatch_address;
  logic [511:0] sw_mismatch_expected,sw_mismatch_actual;
  logic sw_line_valid,sw_line_ready,sw_line_write,sw_line_rsp_valid,sw_line_rsp_ready,sw_line_rsp_error;
  logic [30:0] sw_line_address;logic [511:0] sw_line_wdata,sw_line_rdata;
  logic sw_retire_valid,sw_retire_ready,sw_retire_rsp_valid,sw_retire_rsp_ready,sw_retire_rsp_ok;
  logic [30:0] sw_retire_last_address;logic [31:0] sw_retire_status,sw_retire_onoff,sw_retire_mask;

  logic direct_mode,manual_line_valid,manual_line_ready,manual_line_write,manual_line_rsp_ready;
  logic [30:0] manual_line_address;logic [511:0] manual_line_wdata;
  logic manual_retire_valid,manual_retire_ready,manual_retire_rsp_ready;logic [30:0] manual_retire_last_address;
  logic adapter_line_valid,adapter_line_ready,adapter_line_write,adapter_line_rsp_valid,adapter_line_rsp_ready,adapter_line_rsp_error;
  logic [30:0] adapter_line_address;logic [511:0] adapter_line_wdata,adapter_line_rdata;
  logic adapter_retire_valid,adapter_retire_ready,adapter_retire_rsp_valid,adapter_retire_rsp_ready,adapter_retire_rsp_ok;
  logic [30:0] adapter_retire_last_address;logic [31:0] adapter_retire_status,adapter_retire_onoff,adapter_retire_mask;
  logic adapter_fault;logic [7:0] adapter_fault_code;logic [31:0] aw_count,w_count,b_count;logic [30:0] last_write_address;
  logic monitor_check_valid,monitor_check_ready,monitor_snapshot_valid,monitor_snapshot_ready;
  logic [31:0] monitor_snapshot_status,monitor_snapshot_onoff,monitor_snapshot_mask;

  logic [3:0] awid,arid;logic [30:0] awaddr,araddr;logic [7:0] awlen,arlen;
  logic [2:0] awsize,arsize;logic [1:0] awburst,arburst;logic awlock,arlock;
  logic [3:0] awcache,arcache,awqos,arqos;logic [2:0] awprot,arprot;
  logic awvalid,awready;logic [511:0] wdata;logic [63:0] wstrb;logic wlast,wvalid,wready;
  logic [3:0] bid,rid;logic [1:0] bresp,rresp;logic bvalid,bready;
  logic arvalid,arready,rlast,rvalid,rready;logic [511:0] rdata;

  logic ctrl_awvalid,ctrl_awready;logic [31:0] ctrl_awaddr,ctrl_wdata;
  logic ctrl_wvalid,ctrl_wready;logic [1:0] ctrl_bresp;logic ctrl_bvalid,ctrl_bready;
  logic [31:0] ctrl_araddr,ctrl_rdata;logic ctrl_arvalid,ctrl_arready;
  logic [1:0] ctrl_rresp;logic ctrl_rvalid,ctrl_rready;
  logic [31:0] ctrl_mask_reg,ctrl_onoff_reg,ctrl_status_reg,ctrl_read_address;

  logic [511:0] memory[0:15];
  logic aw_seen,w_seen,b_pending,r_pending,ctrl_aw_seen,ctrl_w_seen,ctrl_b_pending,ctrl_r_pending;
  logic [30:0] saved_awaddr,read_address;logic [511:0] saved_wdata,read_payload;
  logic [31:0] write_index,aw_wait,w_wait,ar_wait,b_delay,r_delay,ctrl_aw_wait,ctrl_w_wait,ctrl_ar_wait,ctrl_b_delay,ctrl_r_delay;
  logic [31:0] saved_ctrl_awaddr,saved_ctrl_wdata;
  logic [31:0] line_rsp_stall_counter,retire_rsp_stall_counter;
  logic [511:0] line_rsp_hold_data;
  integer model_b_completions,model_r_completions,write_order_aw_first,write_order_w_first;
  logic [31:0] test_seed;
  logic [30:0] golden_address;logic [31:0] golden_seed;logic golden_trial,golden_valid;
  logic [511:0] golden_data,golden_expected;string golden_path;integer golden_fd,golden_scanned,golden_rows,golden_trial_i;
  integer snapshot_count,retire_ar_count,read_line_count,expected_line_seq,fence_response_count;
  logic [30:0] model_last_b_address;
  logic stall_aw_forever,stall_w_forever,stall_ar_forever,inject_b,inject_r;
  logic bad_bid,bad_bresp;logic [2:0] read_fault_mode;logic fence_read_fault_only,alias_mode;
  logic bad_ctrl_status,bad_ctrl_onoff,bad_ctrl_mask;

  rk_ddr_capacity_sweep #(.BASE_ADDR(BASE_ADDR),.SPAN_BYTES(SPAN_BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) sweep(
    .clk(clk),.joint_rst_n(joint_rst_n),.start_valid(sw_start_valid),.start_ready(sw_start_ready),.seed(sw_seed),
    .initialization_complete(initialization_complete),.calibration_complete(calibration_complete),
    .ecc_monitor_healthy(monitor_healthy),.owner_exclusive(owner_exclusive),.busy(sw_busy),.done(sw_done),
    .fault(sw_fault),.fault_code(sw_fault_code),.trial(sw_trial),.completed_writes(sw_completed_writes),
    .completed_reads(sw_completed_reads),.mismatch_address(sw_mismatch_address),
    .mismatch_expected(sw_mismatch_expected),.mismatch_actual(sw_mismatch_actual),
    .line_valid(sw_line_valid),.line_ready(sw_line_ready),.line_write(sw_line_write),.line_address(sw_line_address),
    .line_wdata(sw_line_wdata),.line_rsp_valid(sw_line_rsp_valid),.line_rsp_ready(sw_line_rsp_ready),
    .line_rsp_error(sw_line_rsp_error),.line_rdata(sw_line_rdata),.retire_valid(sw_retire_valid),
    .retire_ready(sw_retire_ready),.retire_last_write_address(sw_retire_last_address),
    .retire_rsp_valid(sw_retire_rsp_valid),.retire_rsp_ready(sw_retire_rsp_ready),.retire_rsp_ok(sw_retire_rsp_ok),
    .retire_ecc_status(sw_retire_status),.retire_ecc_onoff(sw_retire_onoff),.retire_ecc_irq_mask(sw_retire_mask));
  rk_ddr_capacity_pattern public_pattern_check(.address(golden_address),.seed(golden_seed),.trial(golden_trial),
    .valid(golden_valid),.data(golden_data));

  assign adapter_line_valid=direct_mode ? manual_line_valid : sw_line_valid;
  assign adapter_line_write=direct_mode ? manual_line_write : sw_line_write;
  assign adapter_line_address=direct_mode ? manual_line_address : sw_line_address;
  assign adapter_line_wdata=direct_mode ? manual_line_wdata : sw_line_wdata;
  assign sw_line_ready=direct_mode ? 1'b0 : adapter_line_ready;
  assign manual_line_ready=direct_mode ? adapter_line_ready : 1'b0;
  assign adapter_line_rsp_ready=direct_mode ? manual_line_rsp_ready : sw_line_rsp_ready;
  assign sw_line_rsp_valid=adapter_line_rsp_valid;assign sw_line_rsp_error=adapter_line_rsp_error;assign sw_line_rdata=adapter_line_rdata;
  assign adapter_retire_valid=direct_mode ? manual_retire_valid : sw_retire_valid;
  assign adapter_retire_last_address=direct_mode ? manual_retire_last_address : sw_retire_last_address;
  assign sw_retire_ready=direct_mode ? 1'b0 : adapter_retire_ready;
  assign manual_retire_ready=direct_mode ? adapter_retire_ready : 1'b0;
  assign adapter_retire_rsp_ready=direct_mode ? manual_retire_rsp_ready : sw_retire_rsp_ready;
  assign sw_retire_rsp_valid=adapter_retire_rsp_valid;assign sw_retire_rsp_ok=adapter_retire_rsp_ok;
  assign sw_retire_status=adapter_retire_status;assign sw_retire_onoff=adapter_retire_onoff;assign sw_retire_mask=adapter_retire_mask;

  rk_ddr_capacity_axi #(.BASE_ADDR(BASE_ADDR),.SPAN_BYTES(SPAN_BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) adapter(
    .clk(clk),.joint_rst_n(joint_rst_n),.initialization_complete(initialization_complete),
    .calibration_complete(calibration_complete),.owner_exclusive(owner_exclusive),
    .monitor_healthy(monitor_healthy),.monitor_fault(monitor_fault),.fault(adapter_fault),.fault_code(adapter_fault_code),
    .accepted_aw_count(aw_count),.accepted_w_count(w_count),.accepted_b_count(b_count),
    .last_completed_write_address(last_write_address),.line_valid(adapter_line_valid),.line_ready(adapter_line_ready),
    .line_write(adapter_line_write),.line_address(adapter_line_address),.line_wdata(adapter_line_wdata),
    .line_rsp_valid(adapter_line_rsp_valid),.line_rsp_ready(adapter_line_rsp_ready),
    .line_rsp_error(adapter_line_rsp_error),.line_rdata(adapter_line_rdata),
    .retire_valid(adapter_retire_valid),.retire_ready(adapter_retire_ready),
    .retire_last_write_address(adapter_retire_last_address),.retire_rsp_valid(adapter_retire_rsp_valid),
    .retire_rsp_ready(adapter_retire_rsp_ready),.retire_rsp_ok(adapter_retire_rsp_ok),
    .retire_ecc_status(adapter_retire_status),.retire_ecc_onoff(adapter_retire_onoff),.retire_ecc_irq_mask(adapter_retire_mask),
    .monitor_check_valid(monitor_check_valid),.monitor_check_ready(monitor_check_ready),
    .monitor_snapshot_valid(monitor_snapshot_valid),.monitor_snapshot_ready(monitor_snapshot_ready),
    .monitor_snapshot_status(monitor_snapshot_status),.monitor_snapshot_onoff(monitor_snapshot_onoff),
    .monitor_snapshot_irq_mask(monitor_snapshot_mask),
    .m_axi_awid(awid),.m_axi_arid(arid),.m_axi_awaddr(awaddr),.m_axi_araddr(araddr),
    .m_axi_awlen(awlen),.m_axi_arlen(arlen),.m_axi_awsize(awsize),.m_axi_arsize(arsize),
    .m_axi_awburst(awburst),.m_axi_arburst(arburst),.m_axi_awlock(awlock),.m_axi_arlock(arlock),
    .m_axi_awcache(awcache),.m_axi_arcache(arcache),.m_axi_awprot(awprot),.m_axi_arprot(arprot),
    .m_axi_awqos(awqos),.m_axi_arqos(arqos),.m_axi_awvalid(awvalid),.m_axi_awready(awready),
    .m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),.m_axi_wvalid(wvalid),.m_axi_wready(wready),
    .m_axi_bid(bid),.m_axi_bresp(bresp),.m_axi_bvalid(bvalid),.m_axi_bready(bready),
    .m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_rid(rid),.m_axi_rdata(rdata),
    .m_axi_rresp(rresp),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready));

  rk_mig_ecc_monitor #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) ecc_monitor(
    .clk(clk),.joint_rst_n(joint_rst_n),.calib_complete(calibration_complete),.mig_interrupt(mig_interrupt),
    .check_valid(monitor_check_valid),.check_ready(monitor_check_ready),.snapshot_valid(monitor_snapshot_valid),
    .snapshot_ready(monitor_snapshot_ready),.snapshot_status(monitor_snapshot_status),
    .snapshot_onoff(monitor_snapshot_onoff),.snapshot_irq_mask(monitor_snapshot_mask),
    .monitor_healthy(monitor_healthy),.fault(monitor_fault),.fault_code(monitor_fault_code),
    .m_axi_ctrl_awaddr(ctrl_awaddr),.m_axi_ctrl_awvalid(ctrl_awvalid),.m_axi_ctrl_awready(ctrl_awready),
    .m_axi_ctrl_wdata(ctrl_wdata),.m_axi_ctrl_wvalid(ctrl_wvalid),.m_axi_ctrl_wready(ctrl_wready),
    .m_axi_ctrl_bresp(ctrl_bresp),.m_axi_ctrl_bvalid(ctrl_bvalid),.m_axi_ctrl_bready(ctrl_bready),
    .m_axi_ctrl_araddr(ctrl_araddr),.m_axi_ctrl_arvalid(ctrl_arvalid),.m_axi_ctrl_arready(ctrl_arready),
    .m_axi_ctrl_rdata(ctrl_rdata),.m_axi_ctrl_rresp(ctrl_rresp),.m_axi_ctrl_rvalid(ctrl_rvalid),.m_axi_ctrl_rready(ctrl_rready));

  assign awready=joint_rst_n && !stall_aw_forever && awvalid && aw_wait>=((write_index[0])?3:1);
  assign wready=joint_rst_n && !stall_w_forever && wvalid && w_wait>=((write_index[0])?1:3);
  assign bid=bad_bid?4'd1:4'd0;assign bresp=bad_bresp?2'b10:2'b00;
  assign bvalid=joint_rst_n && (inject_b || (b_pending && b_delay==0));
  assign arready=joint_rst_n && !stall_ar_forever && arvalid && ar_wait>=2;
  assign rid=((read_fault_mode==1) && (!fence_read_fault_only || adapter.retire_active))?4'd1:4'd0;
  assign rresp=((read_fault_mode==2) && (!fence_read_fault_only || adapter.retire_active))?2'b10:2'b00;
  assign rlast=((read_fault_mode==3) && (!fence_read_fault_only || adapter.retire_active))?1'b0:1'b1;
  assign rdata=inject_r?512'b0:(read_payload ^ ((read_fault_mode==4)?(512'b1<<13):512'b0));
  assign rvalid=joint_rst_n && (inject_r || (r_pending && r_delay==0));

  function automatic integer memory_slot(input logic [30:0] address);
    integer line_index;begin line_index=(address-BASE_ADDR)>>6;memory_slot=alias_mode?(line_index>>1):line_index;end
  endfunction
  function automatic logic outside_span(input logic [30:0] address);
    logic [32:0] a,b,e;
    begin
      a={2'b0,address};b={2'b0,BASE_ADDR};e=b+{1'b0,SPAN_BYTES};
      if(BASE_ADDR==0)outside_span=(a+33'd64)>e;
      else outside_span=(a<b)||((a+33'd64)>e);
    end
  endfunction
  function automatic logic [511:0] sw_pattern(input logic [30:0] address,input logic [31:0] seed_value,input logic trial_value);
    integer lane;logic [31:0] line_index,salt;begin
      if(address[5:0]!=0)line_index=0;else line_index={7'b0,address[30:6]};
      for(lane=0;lane<16;lane=lane+1)begin salt=lane*32'h9e3779b9;sw_pattern[lane*32 +:32]=line_index^seed_value^salt^{32{trial_value}};end
    end
  endfunction
  always_comb begin
    ctrl_awready=joint_rst_n && ctrl_awvalid && ctrl_aw_wait>=1;ctrl_wready=joint_rst_n && ctrl_wvalid && ctrl_w_wait>=3;
    ctrl_bresp=0;ctrl_bvalid=joint_rst_n && ctrl_b_pending && ctrl_b_delay==0;
    ctrl_arready=joint_rst_n && ctrl_arvalid && ctrl_ar_wait>=2;ctrl_rresp=0;ctrl_rvalid=joint_rst_n && ctrl_r_pending && ctrl_r_delay==0;
    case(ctrl_read_address)
      32'h4:ctrl_rdata=bad_ctrl_mask?0:ctrl_mask_reg;
      32'h8:ctrl_rdata=bad_ctrl_onoff?0:ctrl_onoff_reg;
      32'h0:ctrl_rdata=bad_ctrl_status?1:ctrl_status_reg;
      default:ctrl_rdata=32'hxxxxxxxx;
    endcase
  end

  always_ff @(posedge clk) begin
    if(!joint_rst_n)begin
      aw_seen<=0;w_seen<=0;b_pending<=0;b_delay<=0;write_index<=0;aw_wait<=0;w_wait<=0;
      ar_wait<=0;r_pending<=0;r_delay<=0;saved_awaddr<=0;saved_wdata<=0;read_address<=0;read_payload<=0;
      ctrl_aw_seen<=0;ctrl_w_seen<=0;ctrl_b_pending<=0;ctrl_b_delay<=0;ctrl_r_pending<=0;ctrl_r_delay<=0;
      saved_ctrl_awaddr<=0;saved_ctrl_wdata<=0;ctrl_read_address<=0;ctrl_aw_wait<=0;ctrl_w_wait<=0;ctrl_ar_wait<=0;
      ctrl_mask_reg<=0;ctrl_onoff_reg<=1;ctrl_status_reg<=0;
      model_b_completions<=0;model_r_completions<=0;write_order_aw_first<=0;write_order_w_first<=0;model_last_b_address<=0;
      line_rsp_stall_counter<=0;retire_rsp_stall_counter<=0;
      snapshot_count<=0;retire_ar_count<=0;read_line_count<=0;expected_line_seq<=0;fence_response_count<=0;
      line_rsp_hold_data<=0;
      for(integer k=0;k<16;k=k+1)memory[k]<=0;
    end else begin
      if(awvalid && !awready)aw_wait<=aw_wait+1;else aw_wait<=0;
      if(wvalid && !wready)w_wait<=w_wait+1;else w_wait<=0;
      if(arvalid && !arready)ar_wait<=ar_wait+1;else ar_wait<=0;
      if(ctrl_awvalid && !ctrl_awready)ctrl_aw_wait<=ctrl_aw_wait+1;else ctrl_aw_wait<=0;
      if(ctrl_wvalid && !ctrl_wready)ctrl_w_wait<=ctrl_w_wait+1;else ctrl_w_wait<=0;
      if(ctrl_arvalid && !ctrl_arready)ctrl_ar_wait<=ctrl_ar_wait+1;else ctrl_ar_wait<=0;
      if(awvalid && awready)begin
        if(awlen!=0 || awsize!=6 || awburst!=1 || awlock!=0 || awid!=0 || awcache!=0 || awprot!=0 || awqos!=0)$fatal(1,"bad single-beat AXI AW fields");
        if(aw_seen)$fatal(1,"second AW before B completion");saved_awaddr<=awaddr;aw_seen<=1;
        if(!w_seen)write_order_aw_first<=write_order_aw_first+1;
      end
      if(wvalid && wready)begin
        if(wlast!==1 || wstrb!==64'hffffffffffffffff)$fatal(1,"bad AXI WLAST/WSTRB");
        if(w_seen)$fatal(1,"second W before B completion");saved_wdata<=wdata;w_seen<=1;
        if(!aw_seen)write_order_w_first<=write_order_w_first+1;
      end
      if(!b_pending && ((aw_seen || (awvalid&&awready)) && (w_seen || (wvalid&&wready))))begin b_pending<=1;b_delay<=2;end
      else if(b_pending && b_delay!=0)b_delay<=b_delay-1;
      if(bvalid && bready)begin
        if(!inject_b && (!aw_seen || !w_seen))$fatal(1,"B before AW/W completion");
        if(!bad_bid && !bad_bresp && !inject_b)begin memory[memory_slot(saved_awaddr)]<=saved_wdata;model_last_b_address<=saved_awaddr;end
        b_pending<=0;aw_seen<=0;w_seen<=0;write_index<=write_index+1;model_b_completions<=model_b_completions+1;
      end
      if(arvalid && arready)begin
        if(arlen!=0 || arsize!=6 || arburst!=1 || arlock!=0 || arid!=0 || arcache!=0 || arprot!=0 || arqos!=0)$fatal(1,"bad AXI AR fields");
        if(r_pending)$fatal(1,"second AR before R completion");
        if(outside_span(araddr))$fatal(1,"AR outside configured span");
        read_address<=araddr;read_payload<=memory[memory_slot(araddr)];r_pending<=1;r_delay<=2;
        if(adapter.retire_active)begin
          retire_ar_count<=retire_ar_count+1;
          if(araddr!==last_write_address || last_write_address!==model_last_b_address)$fatal(1,"fence AR differs from final completed B AW address");
          if(direct_mode)begin
            if(b_count==0)$fatal(1,"direct fence AR without a successful B response");
          end else if((retire_ar_count<2 && b_count!=LINES)||(retire_ar_count>=2 && b_count!=2*LINES))
            $fatal(1,"fence AR before write pass B responses");
        end else read_line_count<=read_line_count+1;
      end else if(r_pending && r_delay!=0)r_delay<=r_delay-1;
      if(rvalid && rready)begin
        if(outside_span(read_address))$fatal(1,"R response outside accepted AR range");
        r_pending<=0;model_r_completions<=model_r_completions+1;
      end
      if(ctrl_awvalid && ctrl_awready)begin saved_ctrl_awaddr<=ctrl_awaddr;ctrl_aw_seen<=1;end
      if(ctrl_wvalid && ctrl_wready)begin saved_ctrl_wdata<=ctrl_wdata;ctrl_w_seen<=1;end
      if(!ctrl_b_pending && ((ctrl_aw_seen || (ctrl_awvalid&&ctrl_awready)) && (ctrl_w_seen || (ctrl_wvalid&&ctrl_wready))))begin ctrl_b_pending<=1;ctrl_b_delay<=2;end
      else if(ctrl_b_pending && ctrl_b_delay!=0)ctrl_b_delay<=ctrl_b_delay-1;
      if(ctrl_bvalid && ctrl_bready)begin
        if(!ctrl_aw_seen || !ctrl_w_seen)$fatal(1,"ECC monitor B before control AW/W");
        if(saved_ctrl_awaddr==4)ctrl_mask_reg<=saved_ctrl_wdata;ctrl_b_pending<=0;ctrl_aw_seen<=0;ctrl_w_seen<=0;
      end
      if(ctrl_arvalid && ctrl_arready)begin ctrl_read_address<=ctrl_araddr;ctrl_r_pending<=1;ctrl_r_delay<=2;end
      else if(ctrl_r_pending && ctrl_r_delay!=0)ctrl_r_delay<=ctrl_r_delay-1;
      if(ctrl_rvalid && ctrl_rready)ctrl_r_pending<=0;
      if(monitor_check_valid && monitor_check_ready)snapshot_count<=snapshot_count+1;
      if(direct_mode && adapter_line_rsp_valid && !manual_line_rsp_ready)begin
        if(line_rsp_stall_counter==0)line_rsp_hold_data<=adapter_line_rdata;
        else if(adapter_line_rdata!==line_rsp_hold_data)$fatal(1,"line response changed under backpressure");
        line_rsp_stall_counter<=line_rsp_stall_counter+1;
      end else line_rsp_stall_counter<=0;
      if(direct_mode && adapter_retire_rsp_valid && !manual_retire_rsp_ready)retire_rsp_stall_counter<=retire_rsp_stall_counter+1;
      else retire_rsp_stall_counter<=0;
      if(!direct_mode && adapter_line_valid && adapter_line_ready)begin
        integer phase,position,line_index;logic expected_write,expected_trial;logic [30:0] expected_address;
        phase=expected_line_seq/LINES;position=expected_line_seq%LINES;expected_trial=(phase>=2);expected_write=((phase%2)==0);
        if(expected_write && expected_trial)line_index=LINES-1-position;else line_index=position;
        expected_address=BASE_ADDR+31'(line_index*64);
        if(expected_line_seq>=4*LINES || adapter_line_write!==expected_write || sweep.trial!==expected_trial ||
          adapter_line_address!==expected_address || adapter_line_wdata!==sw_pattern(expected_address,test_seed,expected_trial))
          $fatal(1,"integrated sweep line mismatch seq=%0d phase=%0d pos=%0d got_addr=%08x exp_addr=%08x got_write=%b exp_write=%b got_trial=%b exp_trial=%b seed=%08x got_data=%h exp_data=%h",
            expected_line_seq,phase,position,adapter_line_address,expected_address,adapter_line_write,expected_write,sweep.trial,expected_trial,test_seed,adapter_line_wdata,sw_pattern(expected_address,test_seed,expected_trial));
        if(!expected_write && fence_response_count!==(expected_trial?3:1))$fatal(1,"read before write-pass ECC fence");
        expected_line_seq<=expected_line_seq+1;
      end
      if(!direct_mode && adapter_retire_valid && adapter_retire_ready)begin
        logic [30:0] expected_last;expected_last=(fence_response_count<2)?BASE_ADDR+31'((LINES-1)*64):BASE_ADDR;
        if(adapter_retire_last_address!==expected_last || adapter_retire_last_address!==last_write_address)
          $fatal(1,"retire address differs from final successful AW/B");
      end
      if(adapter_retire_rsp_valid && adapter_retire_rsp_ready && !adapter_retire_rsp_ok)$fatal(1,"failed fence reported success");
      if(!direct_mode && adapter_retire_rsp_valid && adapter_retire_rsp_ready)fence_response_count<=fence_response_count+1;
    end
  end

  task automatic fail(input string msg);$display("FAIL_AXI %s",msg);$fatal(1);endtask
  task automatic check_public_software_goldens;
    begin
      if(!$value$plusargs("GOLDENS=%s",golden_path))fail("missing public-software golden fixture");
      golden_fd=$fopen(golden_path,"r");if(golden_fd==0)fail("cannot open public-software golden fixture");golden_rows=0;
      while(!$feof(golden_fd))begin
        golden_scanned=$fscanf(golden_fd,"%h %h %d %h\n",golden_address,golden_seed,golden_trial_i,golden_expected);
        if(golden_scanned==-1)begin end
        else if(golden_scanned!=4)fail("malformed public-software golden row");
        else begin
          if(golden_trial_i!=0&&golden_trial_i!=1)fail("public golden trial must be 0/1");
          golden_trial=(golden_trial_i==1);#1;
          if(golden_valid!==1'b1||golden_data!==golden_expected)
            fail($sformatf("public software nonzero golden mismatch addr=%h seed=%h trial=%0d",golden_address,golden_seed,golden_trial));
          golden_rows=golden_rows+1;
        end
      end
      $fclose(golden_fd);if(golden_rows!=18)fail("wrong public-software golden count");
      $display("PASS_PUBLIC_PATTERN_GOLDENS rows=%0d base=00001000 software_oracle=tools/ddr/capacity_pattern.py",golden_rows);
    end
  endtask
  task automatic reset_system;
    begin
      @(negedge clk);joint_rst_n=0;sw_start_valid=0;sw_seed=0;direct_mode=0;manual_line_valid=0;manual_line_write=0;
      manual_line_address=0;manual_line_wdata=0;manual_line_rsp_ready=1;manual_retire_valid=0;manual_retire_last_address=0;
      manual_retire_rsp_ready=1;calibration_complete=1;initialization_complete=1;owner_exclusive=1;mig_interrupt=0;
      stall_aw_forever=0;stall_w_forever=0;stall_ar_forever=0;inject_b=0;inject_r=0;bad_bid=0;bad_bresp=0;
      read_fault_mode=0;fence_read_fault_only=0;alias_mode=0;bad_ctrl_status=0;bad_ctrl_onoff=0;bad_ctrl_mask=0;
      repeat(3)@(posedge clk);@(negedge clk);joint_rst_n=1;
    end
  endtask
  task automatic wait_monitor_ready;
    integer n;begin n=0;while(!monitor_healthy && !monitor_fault && n<400)begin @(posedge clk);#1;n=n+1;end
      if(!monitor_healthy)fail($sformatf("ECC monitor init/fault code=%0d",monitor_fault_code));end
  endtask
  task automatic wait_adapter_fault(input logic [7:0] expected);
    integer n;begin n=0;while(!adapter_fault && n<120)begin @(posedge clk);#1;n=n+1;end
      if(adapter_fault!==1 || adapter_fault_code!==expected)fail($sformatf("adapter fault %b/%0d expected %0d",adapter_fault,adapter_fault_code,expected));end
  endtask
  task automatic pulse_sweep_start_expect_fault(input logic [7:0] expected);
    begin
      @(negedge clk);sw_seed=32'h3588c350;sw_start_valid=1;
      if(sw_start_ready!==1'b1)fail("sweep start gate did not expose terminal health failure");
      @(posedge clk);#1;@(negedge clk);sw_start_valid=0;
      repeat(2)@(posedge clk);#1;
      if(sw_fault!==1 || sw_fault_code!==expected || sw_busy!==0 || sw_done!==0 || sw_line_valid!==0)
        fail($sformatf("sweep health failure got %b/%0d expected %0d",sw_fault,sw_fault_code,expected));
    end
  endtask
  task automatic wait_monitor_fault(input logic [7:0] expected);
    integer n;begin n=0;while(!monitor_fault && n<500)begin @(posedge clk);#1;n=n+1;end
      if(monitor_fault!==1 || monitor_fault_code!==expected)
        fail($sformatf("ECC monitor fault %b/%0d expected %0d",monitor_fault,monitor_fault_code,expected));end
  endtask
  task automatic run_sweep(input logic [31:0] seed_value);
    integer n;begin test_seed=seed_value;sw_seed=seed_value;@(negedge clk);sw_start_valid=1;
      if(sw_start_ready!==1)fail("sweep not ready after ECC monitor");@(posedge clk);#1;@(negedge clk);sw_start_valid=0;
      n=0;while(!sw_done && !sw_fault && n<5000)begin @(posedge clk);#1;n=n+1;end
      if(sw_fault)fail($sformatf("sweep fault %0d",sw_fault_code));if(!sw_done)fail("sweep timeout");
      if(sw_trial!==1'b1 || sw_mismatch_address!==0 || sw_mismatch_expected!==0 || sw_mismatch_actual!==0)fail("unexpected sweep mismatch outputs");
      if(sw_completed_writes!==2*LINES || sw_completed_reads!==2*LINES || expected_line_seq!==4*LINES ||
        fence_response_count!==4 || retire_ar_count!==4 || read_line_count!==2*LINES ||
        aw_count!==2*LINES || w_count!==2*LINES || b_count!==2*LINES ||
        snapshot_count!==4 || model_b_completions!==2*LINES || model_r_completions!==2*LINES+4)
        fail("integrated sweep counters/fences/ECC snapshots differ");
      if(write_order_aw_first==0 || write_order_w_first==0)fail("AW-before-W and W-before-AW both not observed");
    end endtask
  task automatic manual_line(input logic wr, input logic [30:0] addr, input logic [511:0] data,
      input logic [7:0] expected_fault_code, input logic hold_response);
    integer n;
    logic [511:0] saved;
    begin
      @(negedge clk); direct_mode=1; manual_line_write=wr; manual_line_address=addr; manual_line_wdata=data;
      manual_line_valid=1; manual_line_rsp_ready=hold_response ? 1'b0 : 1'b1; n=0;
      while(!manual_line_ready && n<100) begin @(posedge clk); #1; n=n+1; end
      if(!manual_line_ready) fail("manual line not accepted");
      @(posedge clk); #1; @(negedge clk); manual_line_valid=0;
      if(expected_fault_code!=0) begin
        wait_adapter_fault(expected_fault_code);
      end else begin
        n=0; while(!adapter_line_rsp_valid && !adapter_fault && n<150) begin @(posedge clk); #1; n=n+1; end
        if(adapter_fault || !adapter_line_rsp_valid) fail("manual line response absent/faulted");
        if(!wr && adapter_line_rdata!==memory[memory_slot(addr)]) fail("line readback differs from AXI memory model");
        if(hold_response) begin
          saved=adapter_line_rdata;
          repeat(3) begin @(posedge clk); #1; if(!adapter_line_rsp_valid || adapter_line_rdata!==saved) fail("line RSP unstable under backpressure"); end
          if(line_rsp_stall_counter<3) fail("line response backpressure was not exercised");
          @(negedge clk); manual_line_rsp_ready=1;
        end
        @(posedge clk); #1; @(negedge clk); manual_line_rsp_ready=1;
      end
    end
  endtask

  task automatic manual_retire(input logic [30:0] addr, input logic [7:0] expected_fault_code,
      input logic hold_response);
    integer n;
    logic [31:0] saved_status,saved_onoff,saved_mask;
    begin
      @(negedge clk); manual_retire_last_address=addr; manual_retire_valid=1;
      manual_retire_rsp_ready=hold_response ? 1'b0 : 1'b1; n=0;
      while(!manual_retire_ready && n<100) begin @(posedge clk); #1; n=n+1; end
      if(!manual_retire_ready) fail("manual retire not accepted");
      @(posedge clk); #1; @(negedge clk); manual_retire_valid=0;
      if(expected_fault_code!=0) begin
        wait_adapter_fault(expected_fault_code);
      end else begin
        n=0; while(!adapter_retire_rsp_valid && !adapter_fault && n<300) begin @(posedge clk); #1; n=n+1; end
        if(adapter_fault || !adapter_retire_rsp_valid || !adapter_retire_rsp_ok) fail("fence response absent/failed");
        if(hold_response) begin
          saved_status=adapter_retire_status; saved_onoff=adapter_retire_onoff; saved_mask=adapter_retire_mask;
          repeat(3) begin @(posedge clk); #1;
            if(!adapter_retire_rsp_valid || adapter_retire_status!==saved_status ||
               adapter_retire_onoff!==saved_onoff || adapter_retire_mask!==saved_mask)
              fail("retire ECC snapshot unstable under backpressure");
          end
          if(retire_rsp_stall_counter<3) fail("retire response backpressure was not exercised");
          @(negedge clk); manual_retire_rsp_ready=1;
        end
        @(posedge clk); #1; @(negedge clk); manual_retire_rsp_ready=1;
      end
    end
  endtask

  initial begin : test
    logic [511:0] payload;integer k;
    joint_rst_n=0;calibration_complete=1;initialization_complete=1;owner_exclusive=1;mig_interrupt=0;
    sw_start_valid=0;sw_seed=0;direct_mode=0;manual_line_valid=0;manual_line_write=0;manual_line_address=0;manual_line_wdata=0;
    manual_line_rsp_ready=1;manual_retire_valid=0;manual_retire_last_address=0;manual_retire_rsp_ready=1;
    stall_aw_forever=0;stall_w_forever=0;stall_ar_forever=0;inject_b=0;inject_r=0;bad_bid=0;bad_bresp=0;
    read_fault_mode=0;fence_read_fault_only=0;alias_mode=0;bad_ctrl_status=0;bad_ctrl_onoff=0;bad_ctrl_mask=0;
    check_public_software_goldens();
    reset_system();wait_monitor_ready();run_sweep(32'h3588c350);
    $display("PASS_AXI_INTEGRATED span=%0d base=%h writes=%0d reads=%0d fences=4",SPAN_BYTES,BASE_ADDR,b_count,model_r_completions);
    if($test$plusargs("FAULTS"))begin
      reset_system();wait_monitor_ready();direct_mode=1;payload=sw_pattern(BASE_ADDR,32'h3588c350,1'b0);
      manual_line(1'b1,BASE_ADDR,payload,0,1'b1);manual_retire(BASE_ADDR,0,1'b1);
      if(snapshot_count!=1 || adapter_retire_status!==0 || adapter_retire_onoff!==1 || adapter_retire_mask!==3)
        fail("real ECC monitor retirement snapshot invalid");

      // Invalid request fields fault before any AXI traffic.
      reset_system();wait_monitor_ready();direct_mode=1;manual_line(1'b1,BASE_ADDR+31'd1,payload,1,1'b0);
      if(aw_count!=0 || b_count!=0)$fatal(1,"unaligned line reached AXI");
      reset_system();wait_monitor_ready();direct_mode=1;manual_line(1'b1,31'(BASE_ADDR+SPAN_BYTES),payload,1,1'b0);
      if(aw_count!=0 || b_count!=0)$fatal(1,"out-of-range line reached AXI");
      if(BASE_ADDR!=0)begin reset_system();wait_monitor_ready();direct_mode=1;manual_line(1'b0,BASE_ADDR-31'd64,'0,1,1'b0);end
`ifndef VERILATOR
      reset_system();wait_monitor_ready();direct_mode=1;manual_line(1'b1,{25'h0,6'bx00000},payload,1,1'b0);
      reset_system();wait_monitor_ready();direct_mode=1;manual_line(1'bx,BASE_ADDR,payload,1,1'b0);
      reset_system();wait_monitor_ready();direct_mode=1;
      manual_line(1'b1,BASE_ADDR,512'hxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx,1,1'b0);
      $display("PASS_AXI_UNKNOWN_FIELDS_FOUR_STATE");
`else
      $display("PASS_AXI_UNKNOWN_FIELDS=NOT_APPLICABLE_TWO_STATE");
`endif

      // Retirement requires writes and the exact last acknowledged AW; simultaneous channels reject.
      reset_system();wait_monitor_ready();direct_mode=1;manual_retire(BASE_ADDR,4,1'b0);
      reset_system();wait_monitor_ready();direct_mode=1;manual_line(1'b1,BASE_ADDR,payload,0,1'b0);
      manual_retire(BASE_ADDR+31'd64,4,1'b0);
      reset_system();wait_monitor_ready();direct_mode=1;
      @(negedge clk);manual_line_valid=1;manual_retire_valid=1;manual_line_write=1;
      manual_line_address=BASE_ADDR;manual_line_wdata=payload;manual_retire_last_address=BASE_ADDR;
      @(posedge clk);#1;@(negedge clk);manual_line_valid=0;manual_retire_valid=0;wait_adapter_fault(2);

      // Actual B/R payload IDs, response codes, RLAST, and read-fence response checks.
      reset_system();wait_monitor_ready();direct_mode=1;bad_bid=1;manual_line(1'b1,BASE_ADDR,payload,3,1'b0);
      reset_system();wait_monitor_ready();direct_mode=1;bad_bresp=1;manual_line(1'b1,BASE_ADDR,payload,3,1'b0);
      reset_system();wait_monitor_ready();direct_mode=1;read_fault_mode=1;manual_line(1'b0,BASE_ADDR,'0,3,1'b0);
      reset_system();wait_monitor_ready();direct_mode=1;read_fault_mode=2;manual_line(1'b0,BASE_ADDR,'0,3,1'b0);
      reset_system();wait_monitor_ready();direct_mode=1;read_fault_mode=3;manual_line(1'b0,BASE_ADDR,'0,3,1'b0);
      for(k=1;k<=3;k=k+1)begin
        reset_system();wait_monitor_ready();direct_mode=1;manual_line(1'b1,BASE_ADDR,payload,0,1'b0);
        fence_read_fault_only=1;read_fault_mode=3'(k);manual_retire(BASE_ADDR,4,1'b0);
      end
      reset_system();wait_monitor_ready();direct_mode=1;@(negedge clk);inject_b=1;
      @(posedge clk);#1;@(negedge clk);inject_b=0;wait_adapter_fault(2);
      reset_system();wait_monitor_ready();direct_mode=1;@(negedge clk);inject_r=1;
      @(posedge clk);#1;@(negedge clk);inject_r=0;wait_adapter_fault(2);
      // Responses offered while their address/data request is still pending are premature, not completions.
      reset_system();wait_monitor_ready();direct_mode=1;stall_aw_forever=1;stall_w_forever=1;
      @(negedge clk);manual_line_valid=1;manual_line_write=1;manual_line_address=BASE_ADDR;manual_line_wdata=payload;
      while(!manual_line_ready)@(posedge clk);@(posedge clk);#1;@(negedge clk);manual_line_valid=0;inject_b=1;
      @(posedge clk);#1;@(negedge clk);inject_b=0;wait_adapter_fault(2);
      if(!awvalid||!wvalid)$fatal(1,"premature B cancelled pending AW/W");stall_aw_forever=0;stall_w_forever=0;
      k=0;while(model_b_completions<1&&k<100)begin @(posedge clk);#1;k=k+1;end
      if(model_b_completions<1||adapter_line_rsp_valid||!adapter_fault)$fatal(1,"premature B quarantine failed to drain");
      reset_system();wait_monitor_ready();direct_mode=1;stall_ar_forever=1;
      @(negedge clk);manual_line_valid=1;manual_line_write=0;manual_line_address=BASE_ADDR;manual_line_wdata='0;
      while(!manual_line_ready)@(posedge clk);@(posedge clk);#1;@(negedge clk);manual_line_valid=0;inject_r=1;
      @(posedge clk);#1;@(negedge clk);inject_r=0;wait_adapter_fault(2);
      if(!arvalid)$fatal(1,"premature R cancelled pending AR");stall_ar_forever=0;
      k=0;while(model_r_completions<1&&k<100)begin @(posedge clk);#1;k=k+1;end
      if(model_r_completions<1||adapter_line_rsp_valid||!adapter_fault)$fatal(1,"premature R quarantine failed to drain");
      $display("PASS_AXI_PREMATURE_RESPONSES");

      // The actual control monitor owns ECC initialization/status; platform health gates the producer.
      reset_system();bad_ctrl_mask=1;wait_monitor_fault(6);pulse_sweep_start_expect_fault(1);
      reset_system();bad_ctrl_onoff=1;wait_monitor_fault(7);pulse_sweep_start_expect_fault(1);
      reset_system();bad_ctrl_status=1;wait_monitor_fault(8);pulse_sweep_start_expect_fault(1);
      reset_system();mig_interrupt=1;wait_monitor_fault(1);pulse_sweep_start_expect_fault(1);
      reset_system();wait_monitor_ready();initialization_complete=0;pulse_sweep_start_expect_fault(1);
      reset_system();calibration_complete=0;repeat(2)@(posedge clk);pulse_sweep_start_expect_fault(1);
      reset_system();wait_monitor_ready();owner_exclusive=0;pulse_sweep_start_expect_fault(1);

      // Pending AW/W/AR requests survive timeout, then late responses drain without a success response.
      reset_system();wait_monitor_ready();direct_mode=1;stall_aw_forever=1;manual_line(1'b1,BASE_ADDR,payload,5,1'b0);
      if(!awvalid)$fatal(1,"timed-out AW was withdrawn");stall_aw_forever=0;
      k=0;while(model_b_completions<1 && k<100)begin @(posedge clk);#1;k=k+1;end
      if(model_b_completions<1 || adapter_line_rsp_valid || !adapter_fault || adapter_line_ready)$fatal(1,"late AW/B drain failed");
      reset_system();wait_monitor_ready();direct_mode=1;stall_w_forever=1;manual_line(1'b1,BASE_ADDR,payload,5,1'b0);
      if(!wvalid)$fatal(1,"timed-out W was withdrawn");stall_w_forever=0;
      k=0;while(model_b_completions<1 && k<100)begin @(posedge clk);#1;k=k+1;end
      if(model_b_completions<1 || adapter_line_rsp_valid || !adapter_fault)$fatal(1,"late W/B drain failed");
      reset_system();wait_monitor_ready();direct_mode=1;stall_ar_forever=1;manual_line(1'b0,BASE_ADDR,'0,5,1'b0);
      if(!arvalid)$fatal(1,"timed-out AR was withdrawn");stall_ar_forever=0;
      k=0;while(model_r_completions<1 && k<100)begin @(posedge clk);#1;k=k+1;end
      if(model_r_completions<1 || adapter_line_rsp_valid || !adapter_fault)$fatal(1,"late AR/R drain failed");
      reset_system();wait_monitor_ready();direct_mode=1;manual_line(1'b1,BASE_ADDR,payload,0,1'b0);
      stall_ar_forever=1;manual_retire(BASE_ADDR,5,1'b0);
      if(!arvalid)$fatal(1,"timed-out fence AR was withdrawn");stall_ar_forever=0;
      k=0;while(model_r_completions<1 && k<100)begin @(posedge clk);#1;k=k+1;end
      if(model_r_completions<1 || adapter_retire_rsp_valid || !adapter_fault)$fatal(1,"late fence R drain failed");

      // A fresh monitor/ECC error on the last pass prevents the success marker.
      reset_system();wait_monitor_ready();test_seed=32'h3588c350;sw_seed=test_seed;
      @(negedge clk);sw_start_valid=1;@(posedge clk);#1;@(negedge clk);sw_start_valid=0;
      k=0;while(!sw_fault && !sw_done && k<5000)begin
        @(negedge clk);if(sw_completed_reads==2*LINES && fence_response_count==3)bad_ctrl_status=1;
        @(posedge clk);#1;k=k+1;
      end
      if(!sw_fault || sw_fault_code!=1 || sw_done)$fatal(1,"final ECC health failure did not prevent done");
      reset_system();wait_monitor_ready();run_sweep(32'hffffffff);
      $display("PASS_AXI_FAULT_DIRECTED");
    end
    $display("PASS_AXI_TESTBENCH scope=adapter_contract_only physical=NOT_QUALIFIED");$finish;
  end
endmodule
