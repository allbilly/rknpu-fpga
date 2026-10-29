`timescale 1ns/1ps
module tb_ddr_diagnostic_mux_badparams #(
  parameter int unsigned BAD_ADDR_WIDTH=31,
  parameter int unsigned BAD_DATA_WIDTH=512,
  parameter int unsigned BAD_ID_WIDTH=4
);
  logic joint_rst_n,diagnostic_selected;
  logic [1:0][BAD_ID_WIDTH-1:0] s_axi_awid,s_axi_arid;
  logic [1:0][BAD_ADDR_WIDTH-1:0] s_axi_awaddr,s_axi_araddr;
  logic [1:0][7:0] s_axi_awlen,s_axi_arlen;
  logic [1:0][2:0] s_axi_awsize,s_axi_arsize,s_axi_awprot,s_axi_arprot;
  logic [1:0][1:0] s_axi_awburst,s_axi_arburst;
  logic [1:0] s_axi_awlock,s_axi_arlock,s_axi_awvalid,s_axi_wlast,s_axi_wvalid,s_axi_bready,s_axi_arvalid,s_axi_rready;
  logic [1:0][3:0] s_axi_awcache,s_axi_arcache,s_axi_awqos,s_axi_arqos;
  logic [1:0][BAD_DATA_WIDTH-1:0] s_axi_wdata;
  logic [1:0][BAD_DATA_WIDTH/8-1:0] s_axi_wstrb;
  wire [1:0] s_axi_awready,s_axi_wready,s_axi_bvalid,s_axi_arready,s_axi_rlast,s_axi_rvalid;
  wire [1:0][BAD_ID_WIDTH-1:0] s_axi_bid,s_axi_rid;
  wire [1:0][1:0] s_axi_bresp,s_axi_rresp;
  wire [1:0][BAD_DATA_WIDTH-1:0] s_axi_rdata;
  wire [BAD_ID_WIDTH-1:0] m_axi_awid,m_axi_arid;
  wire [BAD_ADDR_WIDTH-1:0] m_axi_awaddr,m_axi_araddr;
  wire [7:0] m_axi_awlen,m_axi_arlen;
  wire [2:0] m_axi_awsize,m_axi_arsize,m_axi_awprot,m_axi_arprot;
  wire [1:0] m_axi_awburst,m_axi_arburst;
  wire m_axi_awlock,m_axi_arlock,m_axi_awvalid,m_axi_wlast,m_axi_wvalid,m_axi_bready,m_axi_arvalid,m_axi_rready;
  wire [3:0] m_axi_awcache,m_axi_arcache,m_axi_awqos,m_axi_arqos;
  wire [BAD_DATA_WIDTH-1:0] m_axi_wdata;
  wire [BAD_DATA_WIDTH/8-1:0] m_axi_wstrb;
  logic m_axi_awready,m_axi_wready,m_axi_bvalid,m_axi_arready,m_axi_rvalid;
  logic [BAD_ID_WIDTH-1:0] m_axi_bid,m_axi_rid;
  logic [1:0] m_axi_bresp,m_axi_rresp;
  logic [BAD_DATA_WIDTH-1:0] m_axi_rdata;
  logic m_axi_rlast;
  wire output_sink = ^{s_axi_awready,s_axi_wready,s_axi_bvalid,s_axi_arready,s_axi_rlast,s_axi_rvalid,
    s_axi_bid,s_axi_rid,s_axi_bresp,s_axi_rresp,s_axi_rdata,m_axi_awid,m_axi_arid,
    m_axi_awaddr,m_axi_araddr,m_axi_awlen,m_axi_arlen,m_axi_awsize,m_axi_arsize,m_axi_awprot,m_axi_arprot,
    m_axi_awburst,m_axi_arburst,m_axi_awlock,m_axi_arlock,m_axi_awvalid,m_axi_wdata,m_axi_wstrb,m_axi_wlast,m_axi_wvalid,
    m_axi_bready,m_axi_arvalid,m_axi_rready,m_axi_awcache,m_axi_arcache,m_axi_awqos,m_axi_arqos};
  rk_ddr_diagnostic_mux #(.ADDR_WIDTH(BAD_ADDR_WIDTH),.DATA_WIDTH(BAD_DATA_WIDTH),.ID_WIDTH(BAD_ID_WIDTH)) dut (
    .joint_rst_n,.diagnostic_selected,
    .s_axi_awid,.s_axi_arid,.s_axi_awaddr,.s_axi_araddr,.s_axi_awlen,.s_axi_arlen,.s_axi_awsize,.s_axi_arsize,
    .s_axi_awburst,.s_axi_arburst,.s_axi_awlock,.s_axi_arlock,.s_axi_awcache,.s_axi_arcache,.s_axi_awprot,.s_axi_arprot,
    .s_axi_awqos,.s_axi_arqos,.s_axi_awvalid,.s_axi_awready,.s_axi_wdata,.s_axi_wstrb,.s_axi_wlast,.s_axi_wvalid,.s_axi_wready,
    .s_axi_bid,.s_axi_bresp,.s_axi_bvalid,.s_axi_bready,.s_axi_arvalid,.s_axi_arready,.s_axi_rid,.s_axi_rdata,
    .s_axi_rresp,.s_axi_rlast,.s_axi_rvalid,.s_axi_rready,
    .m_axi_awid,.m_axi_arid,.m_axi_awaddr,.m_axi_araddr,.m_axi_awlen,.m_axi_arlen,.m_axi_awsize,.m_axi_arsize,
    .m_axi_awburst,.m_axi_arburst,.m_axi_awlock,.m_axi_arlock,.m_axi_awcache,.m_axi_arcache,.m_axi_awprot,.m_axi_arprot,
    .m_axi_awqos,.m_axi_awvalid,.m_axi_awready,.m_axi_wdata,.m_axi_wstrb,.m_axi_wlast,.m_axi_wvalid,.m_axi_wready,
    .m_axi_bid,.m_axi_bresp,.m_axi_bvalid,.m_axi_bready,.m_axi_arvalid,.m_axi_arready,
    .m_axi_rid,.m_axi_rdata,.m_axi_rresp,.m_axi_rlast,.m_axi_rvalid,.m_axi_rready
  );
  initial begin
    joint_rst_n=0; diagnostic_selected=0;
    s_axi_awid='0;s_axi_arid='0;s_axi_awaddr='0;s_axi_araddr='0;s_axi_awlen='0;s_axi_arlen='0;s_axi_awsize='0;s_axi_arsize='0;
    s_axi_awburst='0;s_axi_arburst='0;s_axi_awlock='0;s_axi_arlock='0;s_axi_awcache='0;s_axi_arcache='0;s_axi_awprot='0;s_axi_arprot='0;
    s_axi_awqos='0;s_axi_arqos='0;s_axi_awvalid='0;s_axi_wdata='0;s_axi_wstrb='0;s_axi_wlast='0;s_axi_wvalid='0;s_axi_bready='0;
    s_axi_arvalid='0;s_axi_rready='0;m_axi_awready=0;m_axi_wready=0;m_axi_bvalid=0;m_axi_arready=0;m_axi_rvalid=0;
    m_axi_bid='0;m_axi_bresp='0;m_axi_rid='0;m_axi_rdata='0;m_axi_rresp='0;m_axi_rlast=0;
    #2; $display("BAD_PARAMETER_TEST_FAILED_TO_FATAL %b",output_sink); $finish;
  end
endmodule
