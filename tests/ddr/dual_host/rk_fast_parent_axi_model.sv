// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Independent bounded AXI RAM plus the minimal ECC-control register contract.
// It is a fast parent integration model, not a MIG/PHY model.
module rk_mig_logic_model #(
  parameter logic [31:0] BASE=32'h10000000,
  parameter int unsigned BYTES=1048576
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
  output logic m_axi_awready,
  input logic [511:0] m_axi_wdata,
  input logic [63:0] m_axi_wstrb,
  input logic m_axi_wlast,m_axi_wvalid,
  output logic m_axi_wready,
  output logic [3:0] m_axi_bid,
  output logic [1:0] m_axi_bresp,
  output logic m_axi_bvalid,
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
  output logic m_axi_arready,
  output logic [511:0] m_axi_rdata,
  output logic [3:0] m_axi_rid,
  output logic [1:0] m_axi_rresp,
  output logic m_axi_rlast,m_axi_rvalid,
  input logic m_axi_rready,
  input logic [31:0] m_axi_ctrl_awaddr,m_axi_ctrl_wdata,m_axi_ctrl_araddr,
  input logic m_axi_ctrl_awvalid,m_axi_ctrl_wvalid,m_axi_ctrl_bready,
  input logic m_axi_ctrl_arvalid,m_axi_ctrl_rready,
  output logic m_axi_ctrl_awready,m_axi_ctrl_wready,m_axi_ctrl_bvalid,
  output logic [1:0] m_axi_ctrl_bresp,
  output logic m_axi_ctrl_arready,m_axi_ctrl_rvalid,
  output logic [31:0] m_axi_ctrl_rdata,
  output logic [1:0] m_axi_ctrl_rresp,
  output logic interrupt,
  input logic inj_ue_next_rmw,hold_phy_write_full,drop_read_return,
  output logic inj_ue_fired,
  output logic [31:0] write_commit_count,read_return_count,pending_writes
);
  localparam int unsigned LINES=BYTES/64;
  logic [511:0] ram [0:LINES-1];
  logic aw_seen,w_seen,ctrl_aw_seen,ctrl_w_seen;
  logic [30:0] saved_awaddr;
  logic [511:0] saved_wdata;
  logic [63:0] saved_wstrb;
  logic [31:0] saved_ctrl_awaddr,saved_ctrl_wdata;
  logic [31:0] ecc_irq_mask,ecc_onoff,ecc_status;
  logic [31:0] ctrl_rdata_q;
  logic [30:0] effective_awaddr;
  logic [511:0] effective_wdata;
  logic [63:0] effective_wstrb;
  logic have_aw,have_w;
  assign m_axi_awready=!rst&&!aw_seen&&!m_axi_bvalid;
  assign m_axi_wready=!rst&&!w_seen&&!m_axi_bvalid;
  assign m_axi_bid=0; assign m_axi_bresp=0;
  assign m_axi_arready=!rst&&!m_axi_rvalid;
  assign m_axi_rid=0; assign m_axi_rresp=0; assign m_axi_rlast=1;
  assign m_axi_ctrl_awready=!rst&&!ctrl_aw_seen&&!m_axi_ctrl_bvalid;
  assign m_axi_ctrl_wready=!rst&&!ctrl_w_seen&&!m_axi_ctrl_bvalid;
  assign m_axi_ctrl_bresp=0;
  assign m_axi_ctrl_arready=!rst&&!m_axi_ctrl_rvalid;
  assign m_axi_ctrl_rdata=ctrl_rdata_q;
  assign m_axi_ctrl_rresp=0;
  assign interrupt=0; assign inj_ue_fired=0;
  assign effective_awaddr=aw_seen?saved_awaddr:m_axi_awaddr;
  assign effective_wdata=w_seen?saved_wdata:m_axi_wdata;
  assign effective_wstrb=w_seen?saved_wstrb:m_axi_wstrb;
  assign have_aw=aw_seen||(m_axi_awvalid&&m_axi_awready);
  assign have_w=w_seen||(m_axi_wvalid&&m_axi_wready);
  initial begin
    if(BYTES<64 || BYTES%64!=0) $fatal(1,"fast model requires whole lines");
    ecc_irq_mask=0; ecc_onoff=1; ecc_status=0;
  end
  always_ff @(posedge clk) begin : model_state
    integer index;
    if(rst) begin
      aw_seen<=0; w_seen<=0; saved_awaddr<=0; saved_wdata<=0; saved_wstrb<=0;
      m_axi_bvalid<=0; m_axi_rvalid<=0; m_axi_rdata<=0;
      write_commit_count<=0;read_return_count<=0;pending_writes<=0;
      ctrl_aw_seen<=0;ctrl_w_seen<=0;saved_ctrl_awaddr<=0;saved_ctrl_wdata<=0;
      m_axi_ctrl_bvalid<=0;m_axi_ctrl_rvalid<=0;ctrl_rdata_q<=0;
      // RAM intentionally survives whole-interface reset; parent init writes it.
    end else begin
      if(m_axi_awvalid&&m_axi_awready)begin aw_seen<=1;saved_awaddr<=m_axi_awaddr;end
      if(m_axi_wvalid&&m_axi_wready)begin w_seen<=1;saved_wdata<=m_axi_wdata;saved_wstrb<=m_axi_wstrb;end
      if(have_aw&&have_w&&!m_axi_bvalid)begin
        if(effective_awaddr<BASE || {1'b0,effective_awaddr} >= {1'b0,BASE}+BYTES || effective_awaddr[5:0]!=0)
          $fatal(1,"fast model write out of range %h",effective_awaddr);
        index=(effective_awaddr-BASE)>>6;
        for(integer lane=0;lane<64;lane=lane+1)
          if(effective_wstrb[lane])ram[index][lane*8+:8]<=effective_wdata[lane*8+:8];
        aw_seen<=0;w_seen<=0;m_axi_bvalid<=1;write_commit_count<=write_commit_count+1;
        pending_writes<=pending_writes+1;
      end
      if(m_axi_bvalid&&m_axi_bready)begin m_axi_bvalid<=0;if(pending_writes!=0)pending_writes<=pending_writes-1;end
      if(m_axi_arvalid&&m_axi_arready)begin
        if(m_axi_araddr<BASE || {1'b0,m_axi_araddr}>={1'b0,BASE}+BYTES || m_axi_araddr[5:0]!=0)
          $fatal(1,"fast model read out of range %h",m_axi_araddr);
        index=(m_axi_araddr-BASE)>>6;m_axi_rdata<=ram[index];m_axi_rvalid<=1;
      end
      if(m_axi_rvalid&&m_axi_rready)begin m_axi_rvalid<=0;read_return_count<=read_return_count+1;end
      if(m_axi_ctrl_awvalid&&m_axi_ctrl_awready)begin ctrl_aw_seen<=1;saved_ctrl_awaddr<=m_axi_ctrl_awaddr;end
      if(m_axi_ctrl_wvalid&&m_axi_ctrl_wready)begin ctrl_w_seen<=1;saved_ctrl_wdata<=m_axi_ctrl_wdata;end
      if(ctrl_aw_seen&&ctrl_w_seen&&!m_axi_ctrl_bvalid)begin
        case(saved_ctrl_awaddr)
          32'h4:ecc_irq_mask<=saved_ctrl_wdata;
          32'h8:ecc_onoff<=saved_ctrl_wdata;
          32'h0:ecc_status<=saved_ctrl_wdata;
          default:$fatal(1,"unknown fast ECC control write %h",saved_ctrl_awaddr);
        endcase
        ctrl_aw_seen<=0;ctrl_w_seen<=0;m_axi_ctrl_bvalid<=1;
      end
      if(m_axi_ctrl_bvalid&&m_axi_ctrl_bready)m_axi_ctrl_bvalid<=0;
      if(m_axi_ctrl_arvalid&&m_axi_ctrl_arready)begin
        case(m_axi_ctrl_araddr)
          32'h0:ctrl_rdata_q<=ecc_status;
          32'h4:ctrl_rdata_q<=ecc_irq_mask;
          32'h8:ctrl_rdata_q<=ecc_onoff;
          default:$fatal(1,"unknown fast ECC control read %h",m_axi_ctrl_araddr);
        endcase
        m_axi_ctrl_rvalid<=1;
      end
      if(m_axi_ctrl_rvalid&&m_axi_ctrl_rready)m_axi_ctrl_rvalid<=0;
    end
  end
endmodule
