// SPDX-License-Identifier: MIT
`timescale 1ps/1ps
// Actual archived MC, including bank/rank scheduling and ECC/RMW logic.
// The external PHY model returns data only for observed issued read columns.
// It does not choose or generate the controller's command ordering.
module tb_mig_fence_order;
  // Blocking assignments are intentional in this simulation-only event ledger.
  /* verilator lint_off BLKSEQ */
  logic clk;
  always #3750 clk=~clk;
  logic rst,init_calib_complete,command_valid;
  logic [2:0] cmd,bank;
  logic [4:0] data_buf_addr;
  logic [9:0] col;
  logic [14:0] row;
  logic phy_rddata_valid,phy_mc_ctl_full,phy_mc_cmd_full,phy_mc_data_full;
  logic [575:0] phy_rd_data;
  integer mode;
  wire [63:0] user_write_mask=mode>=6 ? 64'b0 : 64'hffff_ffff_ffff_fffc;
  wire accept,accept_ns;
  // use_addr is the MC's already-admitted UI pulse, not a held VALID input.
  // Match ui_cmd's gating so periodic-read reservation cannot consume a held
  // test request through accept_internal while accept is low.
  wire use_addr=command_valid&&accept;
  wire [511:0] rd_data;
  wire [4:0] rd_data_addr,wr_data_addr;
  wire rd_data_en,rd_data_end,rd_data_offset,wr_data_en,wr_data_offset;
  wire [7:0] ecc_single,ecc_multiple;
  wire [28:0] ecc_err_addr;
  wire [575:0] mc_wrdata;
  wire [71:0] mc_wrdata_mask;
  wire [59:0] mc_address;
  wire [11:0] mc_bank;
  wire [3:0] mc_ras_n,mc_cas_n,mc_we_n,mc_cs_n,mc_cke,mc_aux_out0,mc_aux_out1;
  wire [1:0] mc_odt,mc_cas_slot,mc_rank_cnt,bank_mach_next;
  wire [5:0] mc_data_offset,mc_data_offset_1,mc_data_offset_2;
  wire [2:0] mc_cmd;
  wire mc_read_idle,mc_ref_zq_wip,app_sr_active,app_ref_ack,app_zq_ack;
  wire mc_reset_n,mc_wrdata_en,mc_cmd_wren,mc_ctl_wren;
  // Full MC port binding is retained; these PHY-facing outputs are not claimed
  // as a physical-memory or drain oracle by this ordering bench.
  wire unused_controller_outputs = ^{accept_ns,rd_data,wr_data_addr,wr_data_en,wr_data_offset,
    ecc_err_addr,mc_wrdata,mc_wrdata_mask,mc_address,mc_bank,mc_ras_n,mc_cas_n,mc_we_n,
    mc_cs_n,mc_cke,mc_aux_out0,mc_aux_out1,mc_odt,mc_cas_slot,mc_rank_cnt,bank_mach_next,
    mc_data_offset,mc_data_offset_1,mc_data_offset_2,mc_cmd,mc_read_idle,mc_ref_zq_wip,
    app_sr_active,app_ref_ack,app_zq_ack,mc_reset_n,mc_wrdata_en,mc_cmd_wren,mc_ctl_wren};

  mig_7series_v4_2_mc #(
/* verilator lint_off INCABSPATH */
`include `RK_MIG_MC_PARAMS_HEADER
/* verilator lint_on INCABSPATH */
  ) dut (
    .clk(clk),.rst(rst),.slot_0_present(8'h1),.slot_1_present(8'h0),
    .cmd(cmd),.data_buf_addr(data_buf_addr),.hi_priority(1'b0),.size(1'b1),
    .bank(bank),.col(col),.rank(1'b0),.row(row),.use_addr(use_addr),
    .wr_data(512'b0),.wr_data_mask(user_write_mask),
    .accept(accept),.accept_ns(accept_ns),.bank_mach_next(bank_mach_next),
    .rd_data(rd_data),.rd_data_addr(rd_data_addr),.rd_data_en(rd_data_en),
    .rd_data_end(rd_data_end),.rd_data_offset(rd_data_offset),
    .wr_data_addr(wr_data_addr),.wr_data_en(wr_data_en),.wr_data_offset(wr_data_offset),
    .mc_read_idle(mc_read_idle),.mc_ref_zq_wip(mc_ref_zq_wip),
    .correct_en(1'b1),.raw_not_ecc(8'b0),.fi_xor_we(9'b0),.fi_xor_wrdata(72'b0),
    .ecc_err_addr(ecc_err_addr),.ecc_single(ecc_single),.ecc_multiple(ecc_multiple),
    .app_periodic_rd_req(1'b0),.app_ref_req(1'b0),.app_zq_req(1'b0),.app_sr_req(1'b0),
    .app_sr_active(app_sr_active),.app_ref_ack(app_ref_ack),.app_zq_ack(app_zq_ack),
    .mc_ras_n(mc_ras_n),.mc_cas_n(mc_cas_n),.mc_we_n(mc_we_n),.mc_address(mc_address),
    .mc_bank(mc_bank),.mc_cs_n(mc_cs_n),.mc_odt(mc_odt),.mc_cke(mc_cke),
    .mc_reset_n(mc_reset_n),.mc_wrdata(mc_wrdata),.mc_wrdata_mask(mc_wrdata_mask),
    .mc_wrdata_en(mc_wrdata_en),.mc_cmd_wren(mc_cmd_wren),.mc_ctl_wren(mc_ctl_wren),
    .mc_cmd(mc_cmd),.mc_data_offset(mc_data_offset),.mc_data_offset_1(mc_data_offset_1),
    .mc_data_offset_2(mc_data_offset_2),.mc_cas_slot(mc_cas_slot),
    .mc_aux_out0(mc_aux_out0),.mc_aux_out1(mc_aux_out1),.mc_rank_cnt(mc_rank_cnt),
    .phy_mc_ctl_full(phy_mc_ctl_full),.phy_mc_cmd_full(phy_mc_cmd_full),
    .phy_mc_data_full(phy_mc_data_full),.phy_rd_data(phy_rd_data),
    .phy_rddata_valid(phy_rddata_valid),.init_calib_complete(init_calib_complete),
    .calib_rd_data_offset(6'b0),.calib_rd_data_offset_1(6'b0),.calib_rd_data_offset_2(6'b0)
  );

  integer cycle,qhead,qtail;
  integer due[0:127],qtag[0:127];
  logic qrmw[0:127],qperiodic[0:127];
  integer accepted,read_columns,write_columns,returned,normal_returns;
  integer write_cycle[0:31],rmw_return_cycle[0:31],normal_return_cycle[0:31];
  logic accepted_tag[0:31],read_issued[0:31],write_issued[0:31];
  logic [2:0] expected_bank[0:31];
  logic [14:0] expected_row[0:31];
  logic [9:0] expected_col[0:31];
  logic [2:0] expected_op[0:31];
  integer expected_write_tag,ue_cycles,ce_cycles;
  integer zero_write_beats;
  integer zero_write_cycle[0:1];
  integer returned_tag;
  logic returned_rmw,returned_periodic;
  integer i;

  // The FIFO models the PHY's ordered read returns; latency is intentionally
  // varied. Neither write-issue order nor fence eligibility comes from it.
  always @(negedge clk) begin
    phy_rddata_valid=0;phy_rd_data=0;returned_tag=-1;returned_rmw=0;returned_periodic=0;
    if (!rst && qhead<qtail && cycle>=due[qhead]) begin
      phy_rddata_valid=1;returned_tag=qtag[qhead];returned_rmw=qrmw[qhead];
      returned_periodic=qperiodic[qhead];
      if (mode==5 && qrmw[qhead] && qtag[qhead]==2) phy_rd_data=576'h3;
      qhead=qhead+1;
    end
  end

  always @(posedge clk) begin
    cycle=cycle+1;
    if (!rst) begin
      if (phy_rddata_valid) begin
        if(!returned_periodic)returned=returned+1;
        if (returned_tag<0) $fatal(1,"Unsolicited model PHY return");
        if (returned_rmw && !returned_periodic) rmw_return_cycle[returned_tag]=cycle;
        $display("TRACE PHY cycle=%0d tag=%0d rmw=%0d periodic=%0d",cycle,returned_tag,returned_rmw,returned_periodic);
      end
      if(dut.sent_col && dut.col_rd_wr)begin
        if(qtail>=128)$fatal(1,"PHY model queue overflow");
        qtag[qtail]=int'(dut.col_data_buf_addr);qrmw[qtail]=dut.col_rmw;
        qperiodic[qtail]=dut.col_periodic_rd;
        due[qtail]=cycle+((!dut.col_periodic_rd&&dut.col_rmw&&dut.col_data_buf_addr==2)?80:8);
        qtail=qtail+1;
      end
      if (dut.sent_col && !dut.col_periodic_rd) begin
        if (!accepted_tag[dut.col_data_buf_addr]) $fatal(1,"Column without accepted request");
        if (dut.col_ba!==expected_bank[dut.col_data_buf_addr] ||
            dut.col_row!==expected_row[dut.col_data_buf_addr] ||
            dut.col_a[9:0]!==expected_col[dut.col_data_buf_addr])
          $fatal(1,"Column address/tag mismatch tag=%0d",dut.col_data_buf_addr);
        $display("TRACE COLUMN cycle=%0d tag=%0d bank=%0d row=%0d col=%0d read=%0d rmw=%0d",
          cycle,dut.col_data_buf_addr,dut.col_ba,dut.col_row,dut.col_a,dut.col_rd_wr,dut.col_rmw);
        if (dut.col_rd_wr) begin
          if(dut.col_data_buf_addr<3 && expected_op[dut.col_data_buf_addr]!==3'b011)
            $fatal(1,"Full-beat WRITE unexpectedly issued an RMW read");
          if (read_issued[dut.col_data_buf_addr]) $fatal(1,"Duplicate read column");
          read_issued[dut.col_data_buf_addr]=1;read_columns=read_columns+1;
          if (dut.col_data_buf_addr==3 && mode!=1 && mode!=7 && !write_issued[2])
            $fatal(1,"Same-final-address read issued before final write");
          if (dut.col_data_buf_addr==3 && mode==6 && zero_write_beats!=2)
            $fatal(1,"Full-write fence read issued before both encoded data beats");
        end else begin
          if (write_issued[dut.col_data_buf_addr] || int'(dut.col_data_buf_addr)!=expected_write_tag)
            $fatal(1,"NORM writes reordered/duplicated tag=%0d expected=%0d",dut.col_data_buf_addr,expected_write_tag);
          if (expected_op[dut.col_data_buf_addr]==3'b011 && rmw_return_cycle[dut.col_data_buf_addr]==0)
            $fatal(1,"RMW write before its PHY return");
          if (expected_op[dut.col_data_buf_addr]==3'b000 && read_issued[dut.col_data_buf_addr])
            $fatal(1,"Full-beat WRITE depended on a prior RMW read");
          write_issued[dut.col_data_buf_addr]=1;write_cycle[dut.col_data_buf_addr]=cycle;
          write_columns=write_columns+1;expected_write_tag=expected_write_tag+1;
        end
      end
      if (rd_data_en) begin
        if ((rd_data_addr!=3 && rd_data_addr!=4) || !read_issued[rd_data_addr])
          $fatal(1,"Unexpected native read response tag=%0d",rd_data_addr);
        if (normal_return_cycle[rd_data_addr]!=0) $fatal(1,"Duplicate native return");
        normal_return_cycle[rd_data_addr]=cycle;normal_returns=normal_returns+1;
        if (!rd_data_end || rd_data_offset!==0) $fatal(1,"Unexpected native response framing");
        if (rd_data_addr==3 && mode!=1 && mode!=7 && (!write_issued[1] || !write_issued[2])) $fatal(1,"Fence response preceded writes");
        $display("TRACE RESPONSE cycle=%0d tag=%0d",cycle,rd_data_addr);
      end
      if (|ecc_multiple) ue_cycles=ue_cycles+1;
      if (|ecc_single) ce_cycles=ce_cycles+1;
      if(mode>=6 && mc_wrdata_en)begin
        if(mc_wrdata!==576'b0 || mc_wrdata_mask!==72'b0)
          $fatal(1,"Full zero write did not emit all data/ECC bytes without masking");
        if(zero_write_beats>=2 || write_cycle[zero_write_beats+1]==0 ||
           cycle<=write_cycle[zero_write_beats+1])
          $fatal(1,"Encoded data beat did not follow its ordered WRITE column");
        zero_write_cycle[zero_write_beats]=cycle;
        zero_write_beats=zero_write_beats+1;
        $display("TRACE FULL_WRITE_DATA cycle=%0d data=0 mask=0",cycle);
      end
    end
  end

  task automatic tick;
    @(posedge clk);#101;
  endtask
  task automatic issue(input logic [2:0] op,input logic [2:0] b,
                       input logic [14:0] r,input logic [9:0] c,input logic [4:0] tag);
    integer guard;
    @(negedge clk);cmd=op;bank=b;row=r;col=c;data_buf_addr=tag;command_valid=0;
    // MC compare registers see the same stable look-ahead fields as the UI.
    repeat(2)tick();@(negedge clk);command_valid=1;guard=0;
    do begin
      @(posedge clk);guard=guard+1;
      if(guard>1000)$fatal(1,"Native request not accepted");
    end while(!accept);
    if(accepted_tag[tag])$fatal(1,"Duplicate accepted tag");
    accepted_tag[tag]=1;expected_bank[tag]=b;expected_row[tag]=r;expected_col[tag]=c;expected_op[tag]=op;
    accepted=accepted+1;
    $display("TRACE ACCEPT cycle=%0d tag=%0d bank=%0d row=%0d col=%0d op=%0d",cycle,tag,b,r,c,op);
    @(negedge clk);command_valid=0;
  endtask

  integer guard;
  initial begin
    clk=0;rst=1;init_calib_complete=0;command_valid=0;cmd=0;bank=0;
    data_buf_addr=0;col=0;row=0;phy_rddata_valid=0;phy_rd_data=0;
    phy_mc_ctl_full=0;phy_mc_cmd_full=0;phy_mc_data_full=0;
    mode=0;cycle=0;qhead=0;qtail=0;accepted=0;read_columns=0;write_columns=0;
    returned=0;normal_returns=0;expected_write_tag=1;ue_cycles=0;ce_cycles=0;
    zero_write_beats=0;
    zero_write_cycle[0]=0;zero_write_cycle[1]=0;
    returned_tag=-1;returned_rmw=0;returned_periodic=0;
    if (!$value$plusargs("MODE=%d",mode)) mode=0;
    if(mode<0||mode>7)$fatal(1,"Unsupported mode");
    for(i=0;i<32;i=i+1)begin
      write_cycle[i]=0;rmw_return_cycle[i]=0;normal_return_cycle[i]=0;
      accepted_tag[i]=0;read_issued[i]=0;write_issued[i]=0;
      expected_bank[i]=0;expected_row[i]=0;expected_col[i]=0;expected_op[i]=0;
    end
    repeat(30)tick();@(negedge clk);rst=0;
    repeat(10)tick();if(accept!==0)$fatal(1,"Uncalibrated MC accepts work");
    @(negedge clk);init_calib_complete=1;repeat(5)tick();
    // A completed read leaves an unrelated bank open. It is outside the write
    // epoch and must finish before either epoch write is presented.
    issue(3'b001,3'd2,15'd0,10'd8,5'd4);
    guard=0;
    while(normal_return_cycle[4]==0&&guard<1000)begin tick();guard=guard+1;end
    if(normal_return_cycle[4]==0)$fatal(1,"Priming read failed");
    // Hold only the PHY write-data path. Read columns/returns remain possible;
    // the DUT, not the PHY model, must enforce the same-bank dependency.
    if(mode==1||mode==4||mode==7)phy_mc_data_full=1;
    issue(mode>=6?3'b000:3'b011,mode==2||mode==3?3'd1:3'd0,15'd0,10'd0,5'd1);
    issue(mode>=6?3'b000:3'b011,3'd1,mode==2?15'd1:15'd0,mode==3?10'd0:10'd8,5'd2);
    issue(3'b001,mode==1||mode==7?3'd2:3'd1,mode==2?15'd1:15'd0,mode==3?10'd0:10'd8,5'd3);
    if(mode==1||mode==7)begin
      guard=0;
      while(normal_returns==1&&guard<1000)begin tick();guard=guard+1;end
      if(normal_returns!=2||write_columns!=0)$fatal(1,"Unrelated-bank read did not bypass PHY-stalled writes");
      @(negedge clk);phy_mc_data_full=0;
    end
    if(mode==4)begin
      repeat(160)tick();
      if(write_columns!=0||normal_returns!=1||rmw_return_cycle[1]==0||rmw_return_cycle[2]==0)
        $fatal(1,"Same-bank fence bypassed pending writes or RMW reads did not run");
      @(negedge clk);phy_mc_data_full=0;
    end
    guard=0;
    while((normal_returns!=2||write_columns!=2||(mode>=6&&zero_write_beats!=2))&&guard<2000)begin tick();guard=guard+1;end
    if(normal_returns!=2||write_columns!=2||accepted!=4||read_columns!=(mode>=6?2:4)||returned!=(mode>=6?2:4))
      $fatal(1,"Incomplete ordering corpus accepted=%0d rdcols=%0d wrcols=%0d returns=%0d native=%0d",accepted,read_columns,write_columns,returned,normal_returns);
    if((mode==1||mode==7) && normal_return_cycle[3]>=write_cycle[2])$fatal(1,"Unrelated-bank negative control did not bypass final write");
    if(mode!=1 && mode!=7 && normal_return_cycle[3]<=write_cycle[2])$fatal(1,"Same-address fence did not follow final write");
    if(mode>=6 && (zero_write_beats!=2||rmw_return_cycle[1]!=0||rmw_return_cycle[2]!=0))
      $fatal(1,"Full-beat WRITE data/RMW inventory differs");
    if(mode==6 && zero_write_cycle[1]>=normal_return_cycle[3])$fatal(1,"Full data beat completed after fence");
    if(mode==7 && normal_return_cycle[3]>=zero_write_cycle[0])$fatal(1,"Full-write negative control did not precede data");
    if(mode==5)begin if(ue_cycles!=1||ce_cycles!=0)$fatal(1,"Injected RMW UE pulse count differs");end
    else if(ue_cycles!=0||ce_cycles!=0)$fatal(1,"Unexpected ECC status");
    $display("PASS mig_fence_order mode=%0d accepted=%0d read_columns=%0d write_columns=%0d phy_returns=%0d native_returns=%0d w1=%0d w2=%0d rmw2=%0d fence=%0d ue=%0d scope=actual_MC_modeled_PHY_only",
      mode,accepted,read_columns,write_columns,returned,normal_returns,write_cycle[1],write_cycle[2],rmw_return_cycle[2],normal_return_cycle[3],ue_cycles);
    $finish;
  end
  initial begin repeat(5000)tick();$fatal(1,"Actual MC ordering watchdog");end
  /* verilator lint_on BLKSEQ */
endmodule
