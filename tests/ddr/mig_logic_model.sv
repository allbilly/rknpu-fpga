// SPDX-License-Identifier: MIT
`timescale 1ps/1ps
// Simulation composition of actual archived logical MIG modules. The explicit
// PHY boundary stores encoded beats; there is no tensor arithmetic or PHY/pad
// model, and RAM is not cleared by reset. Only recognized periodic reads may
// return zero outside the modeled allocation.
/* verilator lint_off DECLFILENAME */
module rk_mig_logic_model #(
  parameter logic [31:0] BASE=32'h10000000,
  parameter int unsigned BYTES=1048576,
  parameter int unsigned READ_LATENCY_CYCLES=8,
  parameter int unsigned QUEUE_DEPTH=64
)(
  input logic clk,rst,aresetn,calib_complete,
  input logic [3:0] m_axi_awid,
  input logic [30:0] m_axi_awaddr,
  input logic [7:0] m_axi_awlen,
  input logic [2:0] m_axi_awsize,
  input logic [1:0] m_axi_awburst,
  input logic m_axi_awlock,
  input logic [3:0] m_axi_awcache,
  input logic [2:0] m_axi_awprot,
  input logic [3:0] m_axi_awqos,
  input logic m_axi_awvalid,
  output wire m_axi_awready,
  input logic [511:0] m_axi_wdata,
  input logic [63:0] m_axi_wstrb,
  input logic m_axi_wlast,m_axi_wvalid,
  output wire m_axi_wready,
  output wire [3:0] m_axi_bid,
  output wire [1:0] m_axi_bresp,
  output wire m_axi_bvalid,
  input logic m_axi_bready,
  input logic [3:0] m_axi_arid,
  input logic [30:0] m_axi_araddr,
  input logic [7:0] m_axi_arlen,
  input logic [2:0] m_axi_arsize,
  input logic [1:0] m_axi_arburst,
  input logic m_axi_arlock,
  input logic [3:0] m_axi_arcache,
  input logic [2:0] m_axi_arprot,
  input logic [3:0] m_axi_arqos,
  input logic m_axi_arvalid,
  output wire m_axi_arready,
  output wire [511:0] m_axi_rdata,
  output wire [3:0] m_axi_rid,
  output wire [1:0] m_axi_rresp,
  output wire m_axi_rlast,m_axi_rvalid,
  input logic m_axi_rready,
  input logic [31:0] m_axi_ctrl_awaddr,m_axi_ctrl_wdata,m_axi_ctrl_araddr,
  input logic m_axi_ctrl_awvalid,m_axi_ctrl_wvalid,m_axi_ctrl_bready,
  input logic m_axi_ctrl_arvalid,m_axi_ctrl_rready,
  output wire m_axi_ctrl_awready,m_axi_ctrl_wready,m_axi_ctrl_bvalid,
  output wire [1:0] m_axi_ctrl_bresp,
  output wire m_axi_ctrl_arready,m_axi_ctrl_rvalid,
  output wire [31:0] m_axi_ctrl_rdata,
  output wire [1:0] m_axi_ctrl_rresp,
  output wire interrupt,
  input logic inj_ue_next_rmw,hold_phy_write_full,drop_read_return,
  output logic inj_ue_fired,
  output logic [31:0] write_commit_count,read_return_count,pending_writes
);
/* verilator lint_on DECLFILENAME */
  /* verilator lint_off BLKSEQ */
  localparam int unsigned LINES=BYTES/64;
  wire [28:0] app_addr;
  wire [2:0] app_cmd;
  wire app_en,app_hi_pri,app_sz,app_rdy,app_wdf_wren,app_wdf_end,app_wdf_rdy;
  wire [511:0] app_wdf_data,app_rd_data;
  wire [63:0] app_wdf_mask;
  wire app_rd_valid,app_rd_end;
  wire [7:0] app_ecc_multiple,app_ecc_single,raw_not_ecc;
  wire correct_en,app_correct_en;
  logic calib_r;
  wire [2:0] native_cmd,native_bank;
  wire [9:0] native_col;
  wire [14:0] native_row;
  wire native_rank,native_use_addr,native_size,native_hi_priority;
  wire [4:0] data_buf_addr,rd_data_addr,wr_data_addr;
  wire [511:0] wr_data,rd_data;
  wire [63:0] wr_data_mask;
  wire accept,accept_ns,rd_data_en,rd_data_end,rd_data_offset,wr_data_en,wr_data_offset;
  wire [7:0] ecc_single,ecc_multiple;
  wire [28:0] ecc_err_addr;
  wire [8:0] fi_xor_we;
  wire [71:0] fi_xor_wrdata;
  logic [575:0] phy_rd_data,phy_rd_data_d;
  logic phy_rddata_valid;
  wire [575:0] mc_wrdata;
  wire [71:0] mc_wrdata_mask;
  wire mc_wrdata_en;
  wire sr_req,ref_req,zq_req,sr_active,ref_ack,zq_ack;
  wire unused_app_sr_active,unused_app_ref_ack,unused_app_zq_ack;
  wire [1:0] unused_bank_mach_next,unused_mc_odt,unused_mc_cas_slot,unused_mc_rank_cnt;
  wire unused_mc_read_idle,unused_mc_ref_zq_wip,unused_mc_reset_n,unused_mc_cmd_wren,unused_mc_ctl_wren;
  wire [3:0] unused_mc_ras_n,unused_mc_cas_n,unused_mc_we_n,unused_mc_cs_n,unused_mc_cke;
  wire [3:0] unused_mc_aux_out0,unused_mc_aux_out1;
  wire [59:0] unused_mc_address;
  wire [11:0] unused_mc_bank;
  wire [2:0] unused_mc_cmd;
  wire [5:0] unused_mc_data_offset,unused_mc_data_offset_1,unused_mc_data_offset_2;

  // Match the original memory-top calibration and raw-DFI registration seam.
  always @(posedge clk) begin
    calib_r<=calib_complete;
    phy_rd_data_d<=#100 phy_rd_data;
  end

  mig_7series_v4_2_axi_mc #(
/* verilator lint_off INCABSPATH */
`include `RK_MIG_LOGIC_AXI_PARAMS_HEADER
/* verilator lint_on INCABSPATH */
  ) axi (
    .aclk(clk),.aresetn(aresetn),
    .s_axi_awid(m_axi_awid),.s_axi_awaddr(m_axi_awaddr),.s_axi_awlen(m_axi_awlen),
    .s_axi_awsize(m_axi_awsize),.s_axi_awburst(m_axi_awburst),.s_axi_awlock(m_axi_awlock),
    .s_axi_awcache(m_axi_awcache),.s_axi_awprot(m_axi_awprot),.s_axi_awqos(m_axi_awqos),
    .s_axi_awvalid(m_axi_awvalid),.s_axi_awready(m_axi_awready),
    .s_axi_wdata(m_axi_wdata),.s_axi_wstrb(m_axi_wstrb),.s_axi_wlast(m_axi_wlast),
    .s_axi_wvalid(m_axi_wvalid),.s_axi_wready(m_axi_wready),
    .s_axi_bid(m_axi_bid),.s_axi_bresp(m_axi_bresp),.s_axi_bvalid(m_axi_bvalid),.s_axi_bready(m_axi_bready),
    .s_axi_arid(m_axi_arid),.s_axi_araddr(m_axi_araddr),.s_axi_arlen(m_axi_arlen),
    .s_axi_arsize(m_axi_arsize),.s_axi_arburst(m_axi_arburst),.s_axi_arlock(m_axi_arlock),
    .s_axi_arcache(m_axi_arcache),.s_axi_arprot(m_axi_arprot),.s_axi_arqos(m_axi_arqos),
    .s_axi_arvalid(m_axi_arvalid),.s_axi_arready(m_axi_arready),
    .s_axi_rid(m_axi_rid),.s_axi_rdata(m_axi_rdata),.s_axi_rresp(m_axi_rresp),
    .s_axi_rlast(m_axi_rlast),.s_axi_rvalid(m_axi_rvalid),.s_axi_rready(m_axi_rready),
    .mc_app_en(app_en),.mc_app_cmd(app_cmd),.mc_app_sz(app_sz),.mc_app_addr(app_addr),
    .mc_app_hi_pri(app_hi_pri),.mc_app_rdy(app_rdy),.mc_init_complete(calib_r),
    .mc_app_wdf_wren(app_wdf_wren),.mc_app_wdf_mask(app_wdf_mask),.mc_app_wdf_data(app_wdf_data),
    .mc_app_wdf_end(app_wdf_end),.mc_app_wdf_rdy(app_wdf_rdy),
    .mc_app_rd_valid(app_rd_valid),.mc_app_rd_data(app_rd_data),.mc_app_rd_end(app_rd_end),
    .mc_app_ecc_multiple_err(app_ecc_multiple)
  );

  mig_7series_v4_2_ui_top #(
/* verilator lint_off INCABSPATH */
`include `RK_MIG_LOGIC_UI_PARAMS_HEADER
/* verilator lint_on INCABSPATH */
  ) ui (
    .clk(clk),.rst(rst),.accept(accept),.accept_ns(accept_ns),
    .app_addr(app_addr),.app_cmd(app_cmd),.app_en(app_en),.app_hi_pri(app_hi_pri),.app_sz(app_sz),
    .app_wdf_data(app_wdf_data),.app_wdf_mask(app_wdf_mask),.app_wdf_end(app_wdf_end),
    .app_wdf_wren(app_wdf_wren),.app_wdf_rdy(app_wdf_rdy),.app_rdy(app_rdy),
    .app_rd_data(app_rd_data),.app_rd_data_valid(app_rd_valid),.app_rd_data_end(app_rd_end),
    .app_ecc_multiple_err(app_ecc_multiple),.app_ecc_single_err(app_ecc_single),
    .app_correct_en(app_correct_en),.app_raw_not_ecc(8'b0),
    .cmd(native_cmd),.bank(native_bank),.col(native_col),.row(native_row),.rank(native_rank),
    .use_addr(native_use_addr),.size(native_size),.hi_priority(native_hi_priority),.data_buf_addr(data_buf_addr),
    .wr_data(wr_data),.wr_data_mask(wr_data_mask),.raw_not_ecc(raw_not_ecc),.correct_en(correct_en),
    .wr_data_addr(wr_data_addr),.wr_data_en(wr_data_en),.wr_data_offset(wr_data_offset),
    .rd_data(rd_data),.rd_data_addr(rd_data_addr),.rd_data_en(rd_data_en),
    .rd_data_end(rd_data_end),.rd_data_offset(rd_data_offset),.ecc_multiple(ecc_multiple),.ecc_single(ecc_single),
    .app_sr_req(1'b0),.sr_req(sr_req),.sr_active(sr_active),.app_sr_active(unused_app_sr_active),
    .app_ref_req(1'b0),.ref_req(ref_req),.ref_ack(ref_ack),.app_ref_ack(unused_app_ref_ack),
    .app_zq_req(1'b0),.zq_req(zq_req),.zq_ack(zq_ack),.app_zq_ack(unused_app_zq_ack)
  );

  mig_7series_v4_2_mc #(
/* verilator lint_off INCABSPATH */
`include `RK_MIG_LOGIC_MC_PARAMS_HEADER
/* verilator lint_on INCABSPATH */
  ) mc (
    .clk(clk),.rst(rst),.slot_0_present(8'h1),.slot_1_present(8'h0),
    .cmd(native_cmd),.data_buf_addr(data_buf_addr),.hi_priority(native_hi_priority),.size(native_size),
    .bank(native_bank),.col(native_col),.rank(native_rank),.row(native_row),.use_addr(native_use_addr),
    .wr_data(wr_data),.wr_data_mask(wr_data_mask),.accept(accept),.accept_ns(accept_ns),
    .bank_mach_next(unused_bank_mach_next),.rd_data(rd_data),.rd_data_addr(rd_data_addr),
    .rd_data_en(rd_data_en),.rd_data_end(rd_data_end),.rd_data_offset(rd_data_offset),
    .wr_data_addr(wr_data_addr),.wr_data_en(wr_data_en),.wr_data_offset(wr_data_offset),
    .mc_read_idle(unused_mc_read_idle),.mc_ref_zq_wip(unused_mc_ref_zq_wip),
    .correct_en(correct_en),.raw_not_ecc(raw_not_ecc),.fi_xor_we(fi_xor_we),.fi_xor_wrdata(fi_xor_wrdata),
    .ecc_err_addr(ecc_err_addr),.ecc_single(ecc_single),.ecc_multiple(ecc_multiple),
    .app_periodic_rd_req(1'b0),.app_ref_req(ref_req),.app_zq_req(zq_req),.app_sr_req(sr_req),
    .app_sr_active(sr_active),.app_ref_ack(ref_ack),.app_zq_ack(zq_ack),
    .mc_ras_n(unused_mc_ras_n),.mc_cas_n(unused_mc_cas_n),.mc_we_n(unused_mc_we_n),
    .mc_address(unused_mc_address),.mc_bank(unused_mc_bank),.mc_cs_n(unused_mc_cs_n),
    .mc_odt(unused_mc_odt),.mc_cke(unused_mc_cke),.mc_reset_n(unused_mc_reset_n),
    .mc_wrdata(mc_wrdata),.mc_wrdata_mask(mc_wrdata_mask),.mc_wrdata_en(mc_wrdata_en),
    .mc_cmd_wren(unused_mc_cmd_wren),.mc_ctl_wren(unused_mc_ctl_wren),.mc_cmd(unused_mc_cmd),
    .mc_data_offset(unused_mc_data_offset),.mc_data_offset_1(unused_mc_data_offset_1),
    .mc_data_offset_2(unused_mc_data_offset_2),.mc_cas_slot(unused_mc_cas_slot),
    .mc_aux_out0(unused_mc_aux_out0),.mc_aux_out1(unused_mc_aux_out1),.mc_rank_cnt(unused_mc_rank_cnt),
    .phy_mc_ctl_full(1'b0),.phy_mc_cmd_full(1'b0),.phy_mc_data_full(hold_phy_write_full),
    .phy_rd_data(phy_rd_data),.phy_rddata_valid(phy_rddata_valid),.init_calib_complete(calib_complete),
    .calib_rd_data_offset(6'b0),.calib_rd_data_offset_1(6'b0),.calib_rd_data_offset_2(6'b0)
  );

  mig_7series_v4_2_axi_ctrl_top #(
/* verilator lint_off INCABSPATH */
`include `RK_MIG_LOGIC_CTRL_PARAMS_HEADER
/* verilator lint_on INCABSPATH */
  ) control (
    .aclk(clk),.aresetn(aresetn),
    .s_axi_awvalid(m_axi_ctrl_awvalid),.s_axi_awready(m_axi_ctrl_awready),.s_axi_awaddr(m_axi_ctrl_awaddr),
    .s_axi_wvalid(m_axi_ctrl_wvalid),.s_axi_wready(m_axi_ctrl_wready),.s_axi_wdata(m_axi_ctrl_wdata),
    .s_axi_bvalid(m_axi_ctrl_bvalid),.s_axi_bready(m_axi_ctrl_bready),.s_axi_bresp(m_axi_ctrl_bresp),
    .s_axi_arvalid(m_axi_ctrl_arvalid),.s_axi_arready(m_axi_ctrl_arready),.s_axi_araddr(m_axi_ctrl_araddr),
    .s_axi_rvalid(m_axi_ctrl_rvalid),.s_axi_rready(m_axi_ctrl_rready),.s_axi_rdata(m_axi_ctrl_rdata),.s_axi_rresp(m_axi_ctrl_rresp),
    .interrupt(interrupt),.init_complete(calib_r),.ecc_single(ecc_single),.ecc_multiple(ecc_multiple),
    .ecc_err_addr(ecc_err_addr),.app_correct_en(app_correct_en),.dfi_rddata(phy_rd_data_d),
    .fi_xor_we(fi_xor_we),.fi_xor_wrdata(fi_xor_wrdata)
  );

  logic [575:0] memory[0:LINES-1];
  logic [31:0] write_address_queue[0:QUEUE_DEPTH-1];
  logic [575:0] write_data_queue[0:QUEUE_DEPTH-1],read_data_queue[0:QUEUE_DEPTH-1];
  integer read_due[0:QUEUE_DEPTH-1];
  logic read_periodic[0:QUEUE_DEPTH-1],read_rmw[0:QUEUE_DEPTH-1];
  integer wa_head,wa_tail,wd_head,wd_tail,rd_head,rd_tail,cycle;
  logic offered_periodic,ue_pending,ue_request_seen;
  logic [31:0] column_byte_address;
  integer index,slot;

  function automatic logic in_window(input logic [31:0] address);
    in_window=({1'b0,address}>={1'b0,BASE})&&({1'b0,address}+33'd64<={1'b0,BASE}+33'(BYTES));
  endfunction

  initial begin
    if(BYTES==0||BYTES%64!=0||BASE[5:0]!=0||BASE[31]||
       ({1'b0,BASE}+33'(BYTES)>33'h080000000)||QUEUE_DEPTH<8||READ_LATENCY_CYCLES==0)
      $fatal(1,"Invalid logical MIG model geometry/latency");
    // Nonzero power-up contents, exactly once. No reset-side RAM clearing.
    for(integer line=0;line<LINES;line=line+1)memory[line]='1;
    wa_head=0;wa_tail=0;wd_head=0;wd_tail=0;rd_head=0;rd_tail=0;cycle=0;
    phy_rddata_valid=0;phy_rd_data=0;offered_periodic=0;ue_pending=0;ue_request_seen=0;
    inj_ue_fired=0;write_commit_count=0;read_return_count=0;pending_writes=0;
  end

  // Encoded data and addresses arrive on the REAL MC output streams. Pair them
  // in issue order. A read does not wait in this model for older writes: a
  // same-bank violation is an error, never repaired by model-side ordering.
  always @(posedge clk) begin
    if(rst)begin
      wa_head=0;wa_tail=0;wd_head=0;wd_tail=0;rd_head=0;rd_tail=0;cycle=0;
      phy_rddata_valid<=0;phy_rd_data<=0;offered_periodic<=0;
      ue_pending=0;ue_request_seen=inj_ue_next_rmw;inj_ue_fired<=0;
      write_commit_count=0;read_return_count=0;pending_writes=0;
    end else begin
      cycle=cycle+1;inj_ue_fired<=0;
      if(inj_ue_next_rmw&&!ue_request_seen)ue_pending=1;
      ue_request_seen=inj_ue_next_rmw;
      if(m_axi_awvalid&&m_axi_awready)begin
        if(m_axi_awid!==0||m_axi_awlen!==0||m_axi_awsize!==6||m_axi_awburst!==1||
           m_axi_awlock!==0||m_axi_awcache!==0||m_axi_awprot!==0||m_axi_awqos!==0||m_axi_awaddr[5:0]!==0||
           (^m_axi_awaddr===1'bx))
          $fatal(1,"Logical MIG model accepts only the bounded single-beat AXI write profile");
        pending_writes=pending_writes+1;
      end
      if(m_axi_wvalid&&m_axi_wready&&(m_axi_wlast!==1'b1||(^m_axi_wstrb===1'bx)||(^m_axi_wdata===1'bx)))
        $fatal(1,"Logical MIG WLAST/data/strobes invalid");
      if(m_axi_arvalid&&m_axi_arready)begin
        if(m_axi_arid!==0||m_axi_arlen!==0||m_axi_arsize!==6||m_axi_arburst!==1||
           m_axi_arlock!==0||m_axi_arcache!==0||m_axi_arprot!==0||m_axi_arqos!==0||m_axi_araddr[5:0]!==0||
           (^m_axi_araddr===1'bx))
          $fatal(1,"Logical MIG model accepts only the bounded single-beat AXI read profile");
      end
      if(phy_rddata_valid)begin
        if(rd_head>=rd_tail)$fatal(1,"Unsolicited modeled PHY return");
        rd_head=rd_head+1;
        if(!offered_periodic)read_return_count=read_return_count+1;
      end
      if(mc_wrdata_en)begin
        if(wd_tail-wd_head>=QUEUE_DEPTH)$fatal(1,"Encoded write-data queue overflow");
        if(mc_wrdata_mask!==72'b0)$fatal(1,"Unexpected physical byte masking with selected ECC profile");
        write_data_queue[wd_tail%QUEUE_DEPTH]=mc_wrdata;wd_tail=wd_tail+1;
      end
      column_byte_address={1'b0,mc.col_ba,mc.col_row,mc.col_a[9:3],6'b0};
      if(mc.sent_col&&!mc.col_rd_wr)begin
        if(mc.col_periodic_rd!==1'b0||mc.col_ra!==1'b0||mc.col_a[2:0]!==0||in_window(column_byte_address)!==1'b1)
          $fatal(1,"User WRITE outside logical MIG window/alignment");
        if(wa_tail-wa_head>=QUEUE_DEPTH)$fatal(1,"Write-column queue overflow");
        write_address_queue[wa_tail%QUEUE_DEPTH]=column_byte_address;wa_tail=wa_tail+1;
      end
      if(wa_head<wa_tail&&wd_head<wd_tail)begin
        index=int'((write_address_queue[wa_head%QUEUE_DEPTH]-BASE)>>6);
        if(index<0||index>=LINES)$fatal(1,"Encoded write index outside allocated DRAM model");
        memory[index]=write_data_queue[wd_head%QUEUE_DEPTH];
        wa_head=wa_head+1;wd_head=wd_head+1;write_commit_count=write_commit_count+1;
        if(pending_writes==0)$fatal(1,"Encoded commit without accepted AXI write");
        pending_writes=pending_writes-1;
      end
      if(mc.sent_col&&mc.col_rd_wr)begin
        if(rd_tail-rd_head>=QUEUE_DEPTH)$fatal(1,"PHY read-return queue overflow");
        if(mc.col_ra!==1'b0||mc.col_a[2:0]!==0)$fatal(1,"Unsupported MC read rank/alignment");
        for(integer pending=wa_head;pending<wa_tail;pending=pending+1)
          if(write_address_queue[pending%QUEUE_DEPTH][30:28]==column_byte_address[30:28])
            $fatal(1,"Actual MC READ bypassed older same-bank encoded WRITE data");
        slot=rd_tail%QUEUE_DEPTH;
        if(slot<0||slot>=QUEUE_DEPTH)$fatal(1,"PHY read queue index outside allocation");
        if(in_window(column_byte_address))begin
          index=int'((column_byte_address-BASE)>>6);
          if(index<0||index>=LINES)$fatal(1,"Encoded read index outside allocated DRAM model");
          read_data_queue[slot]=memory[index];
        end else if(mc.col_periodic_rd)read_data_queue[slot]=0;
        else $fatal(1,"User READ outside logical MIG storage window");
        read_periodic[slot]=mc.col_periodic_rd;read_rmw[slot]=mc.col_rmw;
        read_due[slot]=cycle+int'(READ_LATENCY_CYCLES);rd_tail=rd_tail+1;
      end
      phy_rddata_valid<=0;phy_rd_data<=0;offered_periodic<=0;
      if(!drop_read_return&&rd_head<rd_tail&&cycle>=read_due[rd_head%QUEUE_DEPTH])begin
        slot=rd_head%QUEUE_DEPTH;
        if(slot<0||slot>=QUEUE_DEPTH)$fatal(1,"PHY return queue index outside allocation");
        phy_rddata_valid<=1;offered_periodic<=read_periodic[slot];
        if(ue_pending&&read_rmw[slot]&&!read_periodic[slot])begin
          phy_rd_data<=read_data_queue[slot]^576'h3;ue_pending=0;inj_ue_fired<=1;
        end else phy_rd_data<=read_data_queue[slot];
      end
    end
  end
  wire unused_app_single = ^app_ecc_single;
  /* verilator lint_on BLKSEQ */
endmodule
