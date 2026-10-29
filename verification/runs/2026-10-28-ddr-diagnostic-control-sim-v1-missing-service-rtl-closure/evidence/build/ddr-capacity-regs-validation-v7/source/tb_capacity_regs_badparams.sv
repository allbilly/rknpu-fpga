`timescale 1ns/1ps
module tb_capacity_regs_badparams #(parameter logic [30:0] BAD_BASE=0, parameter logic [31:0] BAD_SPAN=32'h80000000);
  logic clk;
  initial clk=0;
  always #5 clk=~clk;
  wire awready,wready,bvalid,arready,rvalid,request_valid;
  wire [1:0] bresp,rresp;
  wire [31:0] rdata,request_seed;
  rk_ddr_capacity_regs #(.BASE_ADDR(BAD_BASE),.SPAN_BYTES(BAD_SPAN)) dut (
    .clk,.joint_rst_n(1'b0),.s_axil_awaddr('0),.s_axil_awprot('0),.s_axil_awvalid(1'b0),.s_axil_awready(awready),
    .s_axil_wdata('0),.s_axil_wstrb('0),.s_axil_wvalid(1'b0),.s_axil_wready(wready),.s_axil_bresp(bresp),.s_axil_bvalid(bvalid),.s_axil_bready(1'b0),
    .s_axil_araddr('0),.s_axil_arprot('0),.s_axil_arvalid(1'b0),.s_axil_arready(arready),.s_axil_rdata(rdata),.s_axil_rresp(rresp),.s_axil_rvalid(rvalid),.s_axil_rready(1'b0),
    .request_valid,.request_ready(1'b0),.request_seed,.handoff_allowed(1'b0),.owner_busy(1'b0),.owner_done(1'b0),.owner_fault(1'b0),.diagnostic_selected(1'b0),
    .completed_writes('0),.completed_reads('0),.fault_codes('0),.fault_sources('0),.mismatch_address('0),.last_completed_write_address('0),.mismatch_expected('0),.mismatch_actual('0));
  initial begin #2; $display("BAD_PARAMETER_TEST_FAILED_TO_FATAL %b%b%b%b%b%b%b%b %08x %08x",awready,wready,bvalid,arready,rvalid,bresp,rresp,request_valid,rdata,request_seed); $finish; end
endmodule
