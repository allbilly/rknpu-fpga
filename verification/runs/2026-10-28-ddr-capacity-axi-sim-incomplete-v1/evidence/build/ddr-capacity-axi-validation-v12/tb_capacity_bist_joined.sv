`timescale 1ns/1ps
module tb_capacity_bist_joined #(
  parameter logic [30:0] BASE_ADDR=0,
  parameter logic [31:0] SPAN_BYTES=256,
  parameter integer TIMEOUT_CYCLES=32
);
  localparam integer LINES=SPAN_BYTES/64;
  logic clk;initial clk=0;always #5 clk=~clk;
  logic joint_rst_n,initialization_complete,calibration_complete,owner_exclusive,mig_interrupt,start_valid;
  logic [31:0] seed;logic start_ready,busy,done,fault,trial,monitor_healthy;
  logic [2:0] fault_sources;logic [7:0] sweep_fault_code,adapter_fault_code,monitor_fault_code;
  logic [31:0] completed_writes,completed_reads,accepted_aw_count,accepted_w_count,accepted_b_count;
  logic [30:0] mismatch_address,last_completed_write_address;logic [511:0] mismatch_expected,mismatch_actual;
  logic [3:0] awid,arid;logic [30:0] awaddr,araddr;logic [7:0] awlen,arlen;
  logic [2:0] awsize,arsize;logic [1:0] awburst,arburst;logic awlock,arlock;
  logic [3:0] awcache,arcache,awqos,arqos;logic [2:0] awprot,arprot;
  logic awvalid,awready;logic [511:0] wdata;logic [63:0] wstrb;logic wlast,wvalid,wready;
  logic [3:0] bid,rid;logic [1:0] bresp,rresp;logic bvalid,bready,arvalid,arready,rlast,rvalid,rready;logic [511:0] rdata;
  logic [31:0] ctrl_awaddr,ctrl_wdata,ctrl_araddr,ctrl_rdata;logic ctrl_awvalid,ctrl_awready,ctrl_wvalid,ctrl_wready;
  logic [1:0] ctrl_bresp,ctrl_rresp;logic ctrl_bvalid,ctrl_bready,ctrl_arvalid,ctrl_arready,ctrl_rvalid,ctrl_rready;
  logic [511:0] memory[0:15];logic aw_seen,w_seen,b_pending,r_pending;
  logic [30:0] saved_awaddr,read_address;logic [511:0] saved_wdata;
  logic [31:0] mask_reg,onoff_reg,status_reg,ctrl_saved_addr,ctrl_saved_data,ctrl_read_address;
  logic ctrl_aw_seen,ctrl_w_seen,ctrl_b_pending,ctrl_r_pending;
  integer fence_reads,line_reads,snapshot_checks;
  logic [31:0] expected_seed;
  logic [30:0] golden_address;logic [31:0] golden_seed;logic golden_trial,golden_valid;
  logic [511:0] golden_data,golden_expected;string golden_path;integer golden_fd,golden_scanned,golden_rows,golden_trial_i;

  rk_ddr_capacity_bist #(.BASE_ADDR(BASE_ADDR),.SPAN_BYTES(SPAN_BYTES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) dut(
    .clk(clk),.joint_rst_n(joint_rst_n),.initialization_complete(initialization_complete),
    .calibration_complete(calibration_complete),.owner_exclusive(owner_exclusive),.mig_interrupt(mig_interrupt),
    .start_valid(start_valid),.start_ready(start_ready),.seed(seed),.busy(busy),.done(done),.fault(fault),.trial(trial),
    .fault_sources(fault_sources),.sweep_fault_code(sweep_fault_code),.adapter_fault_code(adapter_fault_code),
    .monitor_fault_code(monitor_fault_code),.completed_writes(completed_writes),.completed_reads(completed_reads),
    .accepted_aw_count(accepted_aw_count),.accepted_w_count(accepted_w_count),.accepted_b_count(accepted_b_count),
    .mismatch_address(mismatch_address),.last_completed_write_address(last_completed_write_address),
    .mismatch_expected(mismatch_expected),.mismatch_actual(mismatch_actual),.monitor_healthy(monitor_healthy),
    .m_axi_awid(awid),.m_axi_arid(arid),.m_axi_awaddr(awaddr),.m_axi_araddr(araddr),.m_axi_awlen(awlen),.m_axi_arlen(arlen),
    .m_axi_awsize(awsize),.m_axi_arsize(arsize),.m_axi_awburst(awburst),.m_axi_arburst(arburst),
    .m_axi_awlock(awlock),.m_axi_arlock(arlock),.m_axi_awcache(awcache),.m_axi_arcache(arcache),
    .m_axi_awprot(awprot),.m_axi_arprot(arprot),.m_axi_awqos(awqos),.m_axi_arqos(arqos),
    .m_axi_awvalid(awvalid),.m_axi_awready(awready),.m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),
    .m_axi_wvalid(wvalid),.m_axi_wready(wready),.m_axi_bid(bid),.m_axi_bresp(bresp),.m_axi_bvalid(bvalid),
    .m_axi_bready(bready),.m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_rid(rid),.m_axi_rdata(rdata),
    .m_axi_rresp(rresp),.m_axi_rlast(rlast),.m_axi_rvalid(rvalid),.m_axi_rready(rready),
    .m_axi_ctrl_awaddr(ctrl_awaddr),.m_axi_ctrl_awvalid(ctrl_awvalid),.m_axi_ctrl_awready(ctrl_awready),
    .m_axi_ctrl_wdata(ctrl_wdata),.m_axi_ctrl_wvalid(ctrl_wvalid),.m_axi_ctrl_wready(ctrl_wready),
    .m_axi_ctrl_bresp(ctrl_bresp),.m_axi_ctrl_bvalid(ctrl_bvalid),.m_axi_ctrl_bready(ctrl_bready),
    .m_axi_ctrl_araddr(ctrl_araddr),.m_axi_ctrl_arvalid(ctrl_arvalid),.m_axi_ctrl_arready(ctrl_arready),
    .m_axi_ctrl_rdata(ctrl_rdata),.m_axi_ctrl_rresp(ctrl_rresp),.m_axi_ctrl_rvalid(ctrl_rvalid),.m_axi_ctrl_rready(ctrl_rready));
  rk_ddr_capacity_pattern public_pattern_check(.address(golden_address),.seed(golden_seed),.trial(golden_trial),
    .valid(golden_valid),.data(golden_data));

  assign awready=joint_rst_n;assign wready=joint_rst_n;assign bid=0;assign bresp=0;assign bvalid=joint_rst_n&&b_pending;
  assign arready=joint_rst_n;assign rid=0;assign rresp=0;assign rlast=1;assign rvalid=joint_rst_n&&r_pending;
  assign ctrl_awready=joint_rst_n;assign ctrl_wready=joint_rst_n;assign ctrl_bresp=0;assign ctrl_bvalid=joint_rst_n&&ctrl_b_pending;
  assign ctrl_arready=joint_rst_n;assign ctrl_rresp=0;assign ctrl_rvalid=joint_rst_n&&ctrl_r_pending;
  function automatic integer slot(input logic [30:0] address);slot=(address-BASE_ADDR)>>6;endfunction
  function automatic logic [511:0] independent_pattern(input logic [30:0] address,input logic [31:0] seed_value,input logic trial_value);
    integer lane;logic [31:0] index,salt;begin index=address[30:6];
      for(lane=0;lane<16;lane=lane+1)begin salt=lane*32'h9e3779b9;independent_pattern[lane*32 +:32]=index^seed_value^salt^{32{trial_value}};end
    end
  endfunction
  always_comb begin
    case(ctrl_read_address)
      32'h4:ctrl_rdata=mask_reg;
      32'h8:ctrl_rdata=onoff_reg;
      32'h0:ctrl_rdata=status_reg;
      default:ctrl_rdata=32'hxxxxxxxx;
    endcase
    rdata=r_pending?memory[slot(read_address)]:512'b0;
  end
  always_ff @(posedge clk)begin
    if(!joint_rst_n)begin
      aw_seen<=0;w_seen<=0;b_pending<=0;r_pending<=0;saved_awaddr<=0;saved_wdata<=0;read_address<=0;
      mask_reg<=0;onoff_reg<=1;status_reg<=0;ctrl_aw_seen<=0;ctrl_w_seen<=0;ctrl_b_pending<=0;ctrl_r_pending<=0;
      ctrl_saved_addr<=0;ctrl_saved_data<=0;ctrl_read_address<=0;fence_reads<=0;line_reads<=0;snapshot_checks<=0;
      for(integer i=0;i<16;i=i+1)memory[i]<=0;
    end else begin
      if(awvalid&&awready)begin
        if(awid!=0||awlen!=0||awsize!=6||awburst!=1||awlock!=0||awcache!=0||awprot!=0||awqos!=0)$fatal(1,"bad joined AW");
        saved_awaddr<=awaddr;aw_seen<=1;
      end
      if(wvalid&&wready)begin
        if(wlast!==1||wstrb!==64'hffffffffffffffff)$fatal(1,"bad joined W");
        if(accepted_aw_count<LINES)begin
          if(awaddr!==BASE_ADDR+31'(accepted_aw_count*64)||wdata!==independent_pattern(awaddr,expected_seed,1'b0))$fatal(1,"trial0 expected order/data mismatch");
        end else if(accepted_aw_count<2*LINES)begin
          if(awaddr!==BASE_ADDR+31'((2*LINES-1-accepted_aw_count)*64)||wdata!==independent_pattern(awaddr,expected_seed,1'b1))$fatal(1,"trial1 expected order/data mismatch");
        end
        saved_wdata<=wdata;w_seen<=1;
      end
      if((aw_seen||(awvalid&&awready))&&(w_seen||(wvalid&&wready))&&!b_pending)b_pending<=1;
      if(bvalid&&bready)begin if(!aw_seen||!w_seen)$fatal(1,"B before AW/W");memory[slot(saved_awaddr)]<=saved_wdata;aw_seen<=0;w_seen<=0;b_pending<=0;end
      if(arvalid&&arready)begin
        if(arid!=0||arlen!=0||arsize!=6||arburst!=1||arlock!=0||arcache!=0||arprot!=0||arqos!=0)$fatal(1,"bad joined AR");
        if(araddr<BASE_ADDR||({1'b0,araddr}+32'd64)>{1'b0,BASE_ADDR}+{1'b0,SPAN_BYTES})$fatal(1,"joined AR out of range");
        read_address<=araddr;r_pending<=1;
        if(dut.adapter.retire_active)begin
          fence_reads<=fence_reads+1;
          if(araddr!==last_completed_write_address)$fatal(1,"joined fence address is not final successful write");
          if((fence_reads<2&&accepted_b_count!=LINES)||(fence_reads>=2&&accepted_b_count!=2*LINES))$fatal(1,"joined fence before write responses");
        end else begin
          line_reads<=line_reads+1;
          if((!trial&&fence_reads!=1)||(trial&&fence_reads!=3))$fatal(1,"joined line read before write-pass fence");
        end
      end
      if(rvalid&&rready)r_pending<=0;
      if(ctrl_awvalid&&ctrl_awready)begin if(ctrl_awaddr!=4)$fatal(1,"unexpected ECC control AW");ctrl_saved_addr<=ctrl_awaddr;ctrl_aw_seen<=1;end
      if(ctrl_wvalid&&ctrl_wready)begin if(ctrl_wdata!=3)$fatal(1,"unexpected ECC control W");ctrl_saved_data<=ctrl_wdata;ctrl_w_seen<=1;end
      if((ctrl_aw_seen||(ctrl_awvalid&&ctrl_awready))&&(ctrl_w_seen||(ctrl_wvalid&&ctrl_wready))&&!ctrl_b_pending)ctrl_b_pending<=1;
      if(ctrl_bvalid&&ctrl_bready)begin if(!ctrl_aw_seen||!ctrl_w_seen)$fatal(1,"control B before AW/W");if(ctrl_saved_addr==4)mask_reg<=ctrl_saved_data;ctrl_aw_seen<=0;ctrl_w_seen<=0;ctrl_b_pending<=0;end
      if(ctrl_arvalid&&ctrl_arready)begin ctrl_read_address<=ctrl_araddr;ctrl_r_pending<=1;end
      if(ctrl_rvalid&&ctrl_rready)ctrl_r_pending<=0;
      if(dut.monitor_check_valid&&dut.monitor_check_ready)snapshot_checks<=snapshot_checks+1;
    end
  end
  task automatic fail(input string msg);$display("FAIL_JOINED_AXI %s",msg);$fatal(1);endtask
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
          if(golden_valid!==1'b1 || golden_data!==golden_expected)
            fail($sformatf("public software nonzero golden mismatch addr=%h seed=%h trial=%0d",golden_address,golden_seed,golden_trial));
          golden_rows=golden_rows+1;
        end
      end
      $fclose(golden_fd);if(golden_rows!=18)fail("wrong public-software golden count");
      $display("PASS_PUBLIC_PATTERN_GOLDENS rows=%0d base=00001000 software_oracle=tools/ddr/capacity_pattern.py",golden_rows);
    end
  endtask
  initial begin
    joint_rst_n=0;initialization_complete=1;calibration_complete=1;owner_exclusive=1;mig_interrupt=0;start_valid=0;seed=32'h3588c350;expected_seed=seed;
    check_public_software_goldens();
    repeat(3)@(posedge clk);@(negedge clk);joint_rst_n=1;
    begin integer n;n=0;while(!monitor_healthy&&n<500)begin @(posedge clk);#1;n=n+1;end if(!monitor_healthy)fail("actual monitor did not initialize");end
    @(negedge clk);start_valid=1;@(posedge clk);#1;@(negedge clk);start_valid=0;
    begin integer n;n=0;while(!done&&!fault&&n<5000)begin @(posedge clk);#1;n=n+1;end if(fault||!done)fail($sformatf("joined BIST failed source=%b sweep=%0d adapter=%0d monitor=%0d",fault_sources,sweep_fault_code,adapter_fault_code,monitor_fault_code));end
    if(completed_writes!=2*LINES||completed_reads!=2*LINES||accepted_aw_count!=2*LINES||accepted_w_count!=2*LINES||
       accepted_b_count!=2*LINES||fence_reads!=4||line_reads!=2*LINES||snapshot_checks!=4||last_completed_write_address!==BASE_ADDR||
       fault_sources!==0||busy!==0||mismatch_address!==0||mismatch_expected!==0||mismatch_actual!==0)
      fail("joined wrapper final counts/fences/status incorrect");
    $display("PASS_JOINED_BIST span=%0d base=%h writes=%0d reads=%0d fences=%0d snapshots=%0d",SPAN_BYTES,BASE_ADDR,accepted_b_count,line_reads,fence_reads,snapshot_checks);$finish;
  end
endmodule
