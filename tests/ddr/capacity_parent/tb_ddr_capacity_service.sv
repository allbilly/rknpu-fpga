`timescale 1ns/1ps
module tb_ddr_capacity_service #(parameter logic [30:0] TB_BASE=0, parameter logic [31:0] TB_SPAN=32'd256);
  logic clk;
  logic joint_rst_n;
  logic initialization_complete;
  logic calibration_complete;
  logic mig_interrupt;
  logic normal_monitor_healthy;
  logic normal_monitor_fault;
  logic normal_fabric_quiet;
  logic normal_job_owned;
  logic normal_host_busy;
  logic normal_engine_pending;
  logic normal_pending_response;
  wire normal_admission_enable;
  wire normal_selected;
  wire diagnostic_selected;
  wire owner_busy;
  wire owner_done;
  wire owner_fault;
  logic [3:0] n_axi_awid;
  logic [30:0] n_axi_awaddr;
  logic [7:0] n_axi_awlen;
  logic [2:0] n_axi_awsize;
  logic [1:0] n_axi_awburst;
  logic n_axi_awlock;
  logic [3:0] n_axi_awcache;
  logic [2:0] n_axi_awprot;
  logic [3:0] n_axi_awqos;
  logic n_axi_awvalid;
  wire n_axi_awready;
  logic [3:0] n_axi_arid;
  logic [30:0] n_axi_araddr;
  logic [7:0] n_axi_arlen;
  logic [2:0] n_axi_arsize;
  logic [1:0] n_axi_arburst;
  logic n_axi_arlock;
  logic [3:0] n_axi_arcache;
  logic [2:0] n_axi_arprot;
  logic [3:0] n_axi_arqos;
  logic n_axi_arvalid;
  wire n_axi_arready;
  logic [511:0] n_axi_wdata;
  logic [63:0] n_axi_wstrb;
  logic n_axi_wlast;
  logic n_axi_wvalid;
  wire n_axi_wready;
  wire [3:0] n_axi_bid;
  wire [1:0] n_axi_bresp;
  wire n_axi_bvalid;
  logic n_axi_bready;
  wire [3:0] n_axi_rid;
  wire [511:0] n_axi_rdata;
  wire [1:0] n_axi_rresp;
  wire n_axi_rlast;
  wire n_axi_rvalid;
  logic n_axi_rready;
  wire [3:0] m_axi_awid;
  wire [30:0] m_axi_awaddr;
  wire [7:0] m_axi_awlen;
  wire [2:0] m_axi_awsize;
  wire [1:0] m_axi_awburst;
  wire m_axi_awlock;
  wire [3:0] m_axi_awcache;
  wire [2:0] m_axi_awprot;
  wire [3:0] m_axi_awqos;
  wire m_axi_awvalid;
  logic m_axi_awready;
  wire [3:0] m_axi_arid;
  wire [30:0] m_axi_araddr;
  wire [7:0] m_axi_arlen;
  wire [2:0] m_axi_arsize;
  wire [1:0] m_axi_arburst;
  wire m_axi_arlock;
  wire [3:0] m_axi_arcache;
  wire [2:0] m_axi_arprot;
  wire [3:0] m_axi_arqos;
  wire m_axi_arvalid;
  logic m_axi_arready;
  wire [511:0] m_axi_wdata;
  wire [63:0] m_axi_wstrb;
  wire m_axi_wlast;
  wire m_axi_wvalid;
  logic m_axi_wready;
  logic [3:0] m_axi_bid;
  logic [1:0] m_axi_bresp;
  logic m_axi_bvalid;
  wire m_axi_bready;
  logic [3:0] m_axi_rid;
  logic [511:0] m_axi_rdata;
  logic [1:0] m_axi_rresp;
  logic m_axi_rlast;
  logic m_axi_rvalid;
  wire m_axi_rready;
  logic [31:0] n_ctrl_awaddr;
  logic n_ctrl_awvalid;
  wire n_ctrl_awready;
  logic [31:0] n_ctrl_wdata;
  logic n_ctrl_wvalid;
  wire n_ctrl_wready;
  wire [1:0] n_ctrl_bresp;
  wire n_ctrl_bvalid;
  logic n_ctrl_bready;
  logic [31:0] n_ctrl_araddr;
  logic n_ctrl_arvalid;
  wire n_ctrl_arready;
  wire [31:0] n_ctrl_rdata;
  wire [1:0] n_ctrl_rresp;
  wire n_ctrl_rvalid;
  logic n_ctrl_rready;
  wire [31:0] m_axi_ctrl_awaddr;
  wire m_axi_ctrl_awvalid;
  logic m_axi_ctrl_awready;
  wire [31:0] m_axi_ctrl_wdata;
  wire m_axi_ctrl_wvalid;
  logic m_axi_ctrl_wready;
  logic [1:0] m_axi_ctrl_bresp;
  logic m_axi_ctrl_bvalid;
  wire m_axi_ctrl_bready;
  wire [31:0] m_axi_ctrl_araddr;
  wire m_axi_ctrl_arvalid;
  logic m_axi_ctrl_arready;
  logic [31:0] m_axi_ctrl_rdata;
  logic [1:0] m_axi_ctrl_rresp;
  logic m_axi_ctrl_rvalid;
  wire m_axi_ctrl_rready;
  logic [31:0] s_axil_awaddr;
  logic [2:0] s_axil_awprot;
  logic s_axil_awvalid;
  wire s_axil_awready;
  logic [31:0] s_axil_wdata;
  logic [3:0] s_axil_wstrb;
  logic s_axil_wvalid;
  wire s_axil_wready;
  wire [1:0] s_axil_bresp;
  wire s_axil_bvalid;
  logic s_axil_bready;
  logic [31:0] s_axil_araddr;
  logic [2:0] s_axil_arprot;
  logic s_axil_arvalid;
  wire s_axil_arready;
  wire [31:0] s_axil_rdata;
  wire [1:0] s_axil_rresp;
  wire s_axil_rvalid;
  logic s_axil_rready;

  localparam integer LINE_COUNT=TB_SPAN/64;
  rk_ddr_capacity_service #(.BASE_ADDR(TB_BASE),.SPAN_BYTES(TB_SPAN),.TIMEOUT_CYCLES(256)) dut (.*);
  localparam integer RAM_LINES=128;
  logic [511:0] ram[0:RAM_LINES-1];
  logic ram_aw_seen,ram_w_seen,ram_write_active,ram_ar_pending;
  logic [6:0] ram_awaddr_index,ram_araddr_index;
  logic [3:0] ram_awid_hold,ram_arid_hold;
  logic [511:0] ram_wdata_hold;
  integer ram_b_delay,ram_r_delay;
  logic corrupt_enable,corruption_fired;
  integer diag_mem_writes,diag_mem_reads,diag_fence_reads;
  integer success_diag_writes,success_diag_reads,success_diag_fences;
  logic ctrl_aw_seen,ctrl_w_seen,ctrl_write_active,ctrl_ar_pending;
  logic [31:0] ctrl_awaddr_hold,ctrl_wdata_hold,ctrl_araddr_hold,ecc_mask;
  integer ctrl_b_delay,ctrl_r_delay;
  integer diag_ctrl_mask_reads,diag_ctrl_onoff_reads,diag_ctrl_status_reads,diag_ctrl_writes;
  wire ram_aw_take=m_axi_awvalid&&m_axi_awready;
  wire ram_w_take=m_axi_wvalid&&m_axi_wready;
  wire ram_ar_take=m_axi_arvalid&&m_axi_arready;
  wire ctrl_aw_take=m_axi_ctrl_awvalid&&m_axi_ctrl_awready;
  wire ctrl_w_take=m_axi_ctrl_wvalid&&m_axi_ctrl_wready;
  wire ctrl_ar_take=m_axi_ctrl_arvalid&&m_axi_ctrl_arready;

  function automatic logic address_in_test_window(input logic [30:0] address);
    logic [32:0] offset;
    begin
      offset={2'b0,address}-{2'b0,TB_BASE};
      address_in_test_window=((^address)!==1'bx)&&(address[5:0]===6'b0)&&
          (offset[32]===1'b0)&&((offset+33'd64)<={1'b0,TB_SPAN});
    end
  endfunction
  function automatic logic [6:0] ram_index(input logic [6:0] line_index);
    ram_index=line_index;
  endfunction
  function automatic [511:0] expected_pattern(input logic [30:0] addr,input logic [31:0] seed,input logic trial);
    reg [511:0] value;
    begin
      if(addr[5:0]!==0) value='x;
      else for(integer lane=0;lane<16;lane=lane+1)
        value[lane*32 +:32]={7'b0,addr[30:6]}^seed^(32'(lane*32'h9e3779b9))^{32{trial}};
      expected_pattern=value;
    end
  endfunction
  initial begin
    for(integer ri=0;ri<RAM_LINES;ri=ri+1) ram[ri]='0;

  end
  always_comb begin
    m_axi_awready=joint_rst_n&&!ram_aw_seen&&!ram_write_active&&!m_axi_bvalid;
    m_axi_wready=joint_rst_n&&!ram_w_seen&&!ram_write_active&&!m_axi_bvalid;
    m_axi_arready=joint_rst_n&&!ram_ar_pending&&!m_axi_rvalid;
    m_axi_ctrl_awready=joint_rst_n&&!ctrl_aw_seen&&!ctrl_write_active&&!m_axi_ctrl_bvalid;
    m_axi_ctrl_wready=joint_rst_n&&!ctrl_w_seen&&!ctrl_write_active&&!m_axi_ctrl_bvalid;
    m_axi_ctrl_arready=joint_rst_n&&!ctrl_ar_pending&&!m_axi_ctrl_rvalid;
  end
  always_ff @(posedge clk) begin
    if(!joint_rst_n) begin
      ram_aw_seen<=0;ram_w_seen<=0;ram_write_active<=0;ram_ar_pending<=0;
      ram_awaddr_index<=0;ram_wdata_hold<=0;ram_araddr_index<=0;ram_awid_hold<=0;ram_arid_hold<=0;ram_b_delay<=0;ram_r_delay<=0;
      m_axi_bvalid<=0;m_axi_bid<=0;m_axi_bresp<=0;m_axi_rvalid<=0;m_axi_rid<=0;m_axi_rresp<=0;m_axi_rlast<=1;m_axi_rdata<=0;
      ctrl_aw_seen<=0;ctrl_w_seen<=0;ctrl_write_active<=0;ctrl_ar_pending<=0;
      ctrl_awaddr_hold<=0;ctrl_wdata_hold<=0;ctrl_araddr_hold<=0;ctrl_b_delay<=0;ctrl_r_delay<=0;ecc_mask<=0;
      m_axi_ctrl_bvalid<=0;m_axi_ctrl_bresp<=0;m_axi_ctrl_rvalid<=0;m_axi_ctrl_rdata<=0;m_axi_ctrl_rresp<=0;
      diag_mem_writes<=0;diag_mem_reads<=0;diag_fence_reads<=0;
      diag_ctrl_mask_reads<=0;diag_ctrl_onoff_reads<=0;diag_ctrl_status_reads<=0;diag_ctrl_writes<=0;
      corruption_fired<=0;
    end else begin
      if(ram_aw_take) begin ram_aw_seen<=1;ram_awaddr_index<=m_axi_awaddr[12:6];ram_awid_hold<=m_axi_awid; end
      if(ram_w_take) begin ram_w_seen<=1;ram_wdata_hold<=m_axi_wdata; end
      if(!ram_write_active&&(ram_aw_seen||ram_aw_take)&&(ram_w_seen||ram_w_take)) begin
        if(diagnostic_selected && (!address_in_test_window(m_axi_awaddr) ||
           m_axi_awid!==0 || m_axi_awlen!==0 || m_axi_awsize!==6 || m_axi_awburst!==1 ||
           m_axi_awlock!==0 || m_axi_awcache!==0 || m_axi_awprot!==0 || m_axi_awqos!==0 || m_axi_wstrb!=='1 || m_axi_wlast!==1))
          $fatal(1,"diagnostic memory AXI write attributes changed");
        ram[(ram_aw_take?m_axi_awaddr[12:6]:ram_awaddr_index)]<=ram_w_take?m_axi_wdata:ram_wdata_hold;
        if(diagnostic_selected) diag_mem_writes<=diag_mem_writes+1;
        ram_aw_seen<=0;ram_w_seen<=0;ram_write_active<=1;ram_b_delay<=2;
      end
      if(ram_write_active) begin
        if(ram_b_delay>0) ram_b_delay<=ram_b_delay-1;
        else begin m_axi_bvalid<=1;m_axi_bid<=ram_awid_hold;m_axi_bresp<=0;ram_write_active<=0; end
      end
      if(m_axi_bvalid&&m_axi_bready) m_axi_bvalid<=0;
      if(ram_ar_take) begin
        if(diagnostic_selected && (!address_in_test_window(m_axi_araddr) ||
           m_axi_arid!==0 || m_axi_arlen!==0 || m_axi_arsize!==6 || m_axi_arburst!==1 ||
           m_axi_arlock!==0 || m_axi_arcache!==0 || m_axi_arprot!==0 || m_axi_arqos!==0))
          $fatal(1,"diagnostic memory AXI read attributes changed");
        ram_ar_pending<=1;ram_araddr_index<=m_axi_araddr[12:6];ram_arid_hold<=m_axi_arid;ram_r_delay<=2;
        if(diagnostic_selected) begin
          if(dut.bist.adapter.retire_active) diag_fence_reads<=diag_fence_reads+1;
          else diag_mem_reads<=diag_mem_reads+1;
        end
      end
      if(ram_ar_pending) begin
        if(ram_r_delay>0) ram_r_delay<=ram_r_delay-1;
        else begin
          m_axi_rdata<=ram[ram_araddr_index];
          if(corrupt_enable && diagnostic_selected && !dut.bist.adapter.retire_active && !corruption_fired) begin
            m_axi_rdata<=ram[ram_araddr_index]^512'h1;corruption_fired<=1;
          end
          m_axi_rid<=ram_arid_hold;m_axi_rresp<=0;m_axi_rlast<=1;m_axi_rvalid<=1;ram_ar_pending<=0;
        end
      end
      if(m_axi_rvalid&&m_axi_rready) m_axi_rvalid<=0;

      if(ctrl_aw_take) begin ctrl_aw_seen<=1;ctrl_awaddr_hold<=m_axi_ctrl_awaddr; end
      if(ctrl_w_take) begin ctrl_w_seen<=1;ctrl_wdata_hold<=m_axi_ctrl_wdata; end
      if(!ctrl_write_active&&(ctrl_aw_seen||ctrl_aw_take)&&(ctrl_w_seen||ctrl_w_take)) begin
        if(diagnostic_selected && ((ctrl_aw_take?m_axi_ctrl_awaddr:ctrl_awaddr_hold)!=32'h4 ||
           (ctrl_w_take?m_axi_ctrl_wdata:ctrl_wdata_hold)!=32'h3)) $fatal(1,"diagnostic ECC control write changed");
        if((ctrl_aw_take?m_axi_ctrl_awaddr:ctrl_awaddr_hold)==32'h4) ecc_mask<=ctrl_w_take?m_axi_ctrl_wdata:ctrl_wdata_hold;
        if(diagnostic_selected) diag_ctrl_writes<=diag_ctrl_writes+1;
        ctrl_aw_seen<=0;ctrl_w_seen<=0;ctrl_write_active<=1;ctrl_b_delay<=2;
      end
      if(ctrl_write_active) begin
        if(ctrl_b_delay>0) ctrl_b_delay<=ctrl_b_delay-1;
        else begin m_axi_ctrl_bresp<=0;m_axi_ctrl_bvalid<=1;ctrl_write_active<=0; end
      end
      if(m_axi_ctrl_bvalid&&m_axi_ctrl_bready) m_axi_ctrl_bvalid<=0;
      if(ctrl_ar_take) begin
        ctrl_ar_pending<=1;ctrl_araddr_hold<=m_axi_ctrl_araddr;ctrl_r_delay<=2;
        if(diagnostic_selected) begin
          case(m_axi_ctrl_araddr)
            32'h4: diag_ctrl_mask_reads<=diag_ctrl_mask_reads+1;
            32'h8: diag_ctrl_onoff_reads<=diag_ctrl_onoff_reads+1;
            32'h0: diag_ctrl_status_reads<=diag_ctrl_status_reads+1;
            default: $fatal(1,"unexpected diagnostic ECC read address %08x",m_axi_ctrl_araddr);
          endcase
        end
      end
      if(ctrl_ar_pending) begin
        if(ctrl_r_delay>0) ctrl_r_delay<=ctrl_r_delay-1;
        else begin
          case(ctrl_araddr_hold)
            32'h4: m_axi_ctrl_rdata<=ecc_mask;
            32'h8: m_axi_ctrl_rdata<=32'h1;
            32'h0: m_axi_ctrl_rdata<=32'h0;
            default: m_axi_ctrl_rdata<=32'h0;
          endcase
          m_axi_ctrl_rresp<=0;m_axi_ctrl_rvalid<=1;ctrl_ar_pending<=0;
        end
      end
      if(m_axi_ctrl_rvalid&&m_axi_ctrl_rready) m_axi_ctrl_rvalid<=0;
      if(diagnostic_selected && (m_axi_ctrl_awvalid && m_axi_ctrl_awaddr!==4 || m_axi_ctrl_wvalid && m_axi_ctrl_wdata!==3))
        $fatal(1,"diagnostic ECC control AXI payload changed");
    end
  end
  always @(posedge clk) begin
    if(joint_rst_n && diagnostic_selected) begin
      if(n_axi_awready||n_axi_wready||n_axi_arready||n_axi_bvalid||n_axi_rvalid||n_ctrl_awready||n_ctrl_wready||n_ctrl_arready||n_ctrl_bvalid||n_ctrl_rvalid)
        $fatal(1,"normal-channel handshake leakage during diagnostic ownership");
    end
  end
  task automatic ck(input logic ok,input string msg);
    begin if(ok!==1'b1) $fatal(1,"CHECK %s",msg); end
  endtask
  task automatic step;
    begin @(posedge clk); #1; end
  endtask
  task automatic wait_owner_done;
    integer n;
    begin
      n=0;
      while(!owner_done&&!owner_fault&&n<5000) begin step();n=n+1;end
      if(owner_fault) $fatal(1,"OWNER_FAULT code=%02x sweep=%02x adapter=%02x monitor=%02x sources=%b",dut.owner_fault_code,dut.sweep_fault_code,dut.adapter_fault_code,dut.monitor_fault_code,dut.bist_fault_sources);
      if(!owner_done) $fatal(1,"OWNER_DONE timeout");
    end
  endtask
  task automatic wait_diagnostic_selected;
    integer n;
    begin n=0; while(!diagnostic_selected&&n<500) begin step();n=n+1;end
      if(!diagnostic_selected) $fatal(1,"DIAGNOSTIC_SELECT timeout");
      n=0;while(dut.diagnostic_monitor_healthy!==1'b1&&n<500) begin step();n=n+1;end
      if(dut.diagnostic_monitor_healthy!==1'b1) $fatal(1,"ECC monitor startup timeout");
    end
  endtask
  task automatic csr_write(input logic [31:0] addr,input logic [31:0] data,input logic [1:0] exp_resp);
    logic awtaken,wtaken;integer n;
    begin
      @(negedge clk);s_axil_awaddr=addr;s_axil_awprot=0;s_axil_awvalid=1;s_axil_wdata=data;s_axil_wstrb=4'hf;s_axil_wvalid=1;s_axil_bready=0;
      n=0;awtaken=0;wtaken=0;
      while(!(awtaken&&wtaken)&&n<50) begin @(posedge clk);awtaken=awtaken||s_axil_awready;wtaken=wtaken||s_axil_wready;#1;n=n+1;end
      if(!(awtaken&&wtaken)) $fatal(1,"CSR AW/W timeout addr=%08x",addr);
      @(negedge clk);s_axil_awvalid=0;s_axil_wvalid=0;
      n=0;while(!s_axil_bvalid&&n<50) begin step();n=n+1;end
      if(!s_axil_bvalid||s_axil_bresp!==exp_resp) $fatal(1,"CSR write response addr=%08x resp=%b expected=%b ownerfault=%b ownercode=%02x ownerstate=%0d busy=%b selected=%b aw_seen=%b w_seen=%b read_seen=%b busB=%b/%b/%b busR=%b/%b/%b held=%b/%b",addr,s_axil_bresp,exp_resp,owner_fault,dut.owner_fault_code,dut.owner.state,owner_busy,diagnostic_selected,dut.owner.aw_seen,dut.owner.w_seen,dut.owner.read_seen,m_axi_bvalid,m_axi_bid,m_axi_bresp,m_axi_rvalid,m_axi_rid,m_axi_rresp,dut.registers.aw_held,dut.registers.w_held);
      @(negedge clk);s_axil_bready=1;step();@(negedge clk);s_axil_bready=0;
    end
  endtask
  task automatic csr_read(input logic [31:0] addr,input logic [1:0] exp_resp,input logic [31:0] exp_data);
    logic taken;integer n;
    begin
      @(negedge clk);s_axil_araddr=addr;s_axil_arprot=0;s_axil_arvalid=1;s_axil_rready=0;
      n=0;taken=0;while(!taken&&n<50)begin @(posedge clk);taken=s_axil_arready;#1;n=n+1;end
      if(!taken)$fatal(1,"CSR AR timeout addr=%08x",addr);
      @(negedge clk);s_axil_arvalid=0;
      n=0;while(!s_axil_rvalid&&n<50)begin step();n=n+1;end
      if(!s_axil_rvalid||s_axil_rresp!==exp_resp||(exp_resp==0&&s_axil_rdata!==exp_data))
        $fatal(1,"CSR read addr=%08x data=%08x resp=%b expected=%08x/%b",addr,s_axil_rdata,s_axil_rresp,exp_data,exp_resp);
      repeat(2)begin step();ck(s_axil_rvalid&&s_axil_rresp===exp_resp,"CSR R stable under backpressure");end
      @(negedge clk);s_axil_rready=1;step();@(negedge clk);s_axil_rready=0;
    end
  endtask
  task automatic normal_write(input logic [30:0] addr,input logic [511:0] data,input logic hold_b);
    logic at,wt;integer n;
    begin
      @(negedge clk);n_axi_awid=4'h0;n_axi_awaddr=addr;n_axi_awlen=0;n_axi_awsize=6;n_axi_awburst=1;n_axi_awlock=0;n_axi_awcache=4'hf;n_axi_awprot=3'h2;n_axi_awqos=4'h5;n_axi_awvalid=1;
      n_axi_wdata=data;n_axi_wstrb=64'hffffffffffffffff;n_axi_wlast=1;n_axi_wvalid=1;n_axi_bready=0;
      n=0;at=0;wt=0;while(!(at&&wt)&&n<50)begin @(posedge clk);at=at||n_axi_awready;wt=wt||n_axi_wready;#1;n=n+1;end
      if(!(at&&wt))$fatal(1,"normal memory AW/W timeout");
      @(negedge clk);n_axi_awvalid=0;n_axi_wvalid=0;
      n=0;while(!n_axi_bvalid&&n<50)begin step();n=n+1;end
      if(!n_axi_bvalid||n_axi_bid!==4'h0||n_axi_bresp!==0)$fatal(1,"normal memory B timeout/payload mismatch valid=%b id=%h resp=%b mvalid=%b mid=%h mresp=%b",n_axi_bvalid,n_axi_bid,n_axi_bresp,m_axi_bvalid,m_axi_bid,m_axi_bresp);
      if(!hold_b)begin @(negedge clk);n_axi_bready=1;step();@(negedge clk);n_axi_bready=0;end
    end
  endtask
  task automatic normal_read(input logic [30:0] addr,input logic hold_r,input logic [511:0] exp_data);
    logic taken;integer n;
    begin
      @(negedge clk);n_axi_arid=4'h0;n_axi_araddr=addr;n_axi_arlen=0;n_axi_arsize=6;n_axi_arburst=1;n_axi_arlock=1;n_axi_arcache=4'h9;n_axi_arprot=3'h3;n_axi_arqos=4'ha;n_axi_arvalid=1;n_axi_rready=0;
      n=0;taken=0;while(!taken&&n<50)begin @(posedge clk);taken=n_axi_arready;#1;n=n+1;end
      if(!taken)$fatal(1,"normal memory AR timeout");
      @(negedge clk);n_axi_arvalid=0;
      n=0;while(!n_axi_rvalid&&n<50)begin step();n=n+1;end
      if(!n_axi_rvalid)$fatal(1,"normal memory R timeout");
      if(!hold_r)begin if(n_axi_rid!==4'h0||n_axi_rresp!==0||n_axi_rlast!==1||n_axi_rdata!==exp_data)$fatal(1,"normal memory read mismatch addr=%08x id=%h resp=%b last=%b actual=%0128x expected=%0128x",addr,n_axi_rid,n_axi_rresp,n_axi_rlast,n_axi_rdata,exp_data);
        @(negedge clk);n_axi_rready=1;step();@(negedge clk);n_axi_rready=0;end
    end
  endtask
  task automatic normal_ctrl_write(input logic [31:0] addr,input logic [31:0] data);
    logic at,wt;integer n;
    begin
      @(negedge clk);n_ctrl_awaddr=addr;n_ctrl_awvalid=1;n_ctrl_wdata=data;n_ctrl_wvalid=1;n_ctrl_bready=0;
      n=0;at=0;wt=0;while(!(at&&wt)&&n<50)begin @(posedge clk);at=at||n_ctrl_awready;wt=wt||n_ctrl_wready;#1;n=n+1;end
      if(!(at&&wt))$fatal(1,"normal ctrl AW/W timeout");@(negedge clk);n_ctrl_awvalid=0;n_ctrl_wvalid=0;
      n=0;while(!n_ctrl_bvalid&&n<50)begin step();n=n+1;end if(!n_ctrl_bvalid||n_ctrl_bresp!==0)$fatal(1,"normal ctrl B failed");
      @(negedge clk);n_ctrl_bready=1;step();@(negedge clk);n_ctrl_bready=0;
    end
  endtask
  task automatic normal_ctrl_read(input logic [31:0] addr,input logic [31:0] exp_data);
    logic taken;integer n;
    begin
      @(negedge clk);n_ctrl_araddr=addr;n_ctrl_arvalid=1;n_ctrl_rready=0;
      n=0;taken=0;while(!taken&&n<50)begin @(posedge clk);taken=n_ctrl_arready;#1;n=n+1;end if(!taken)$fatal(1,"normal ctrl AR timeout");
      @(negedge clk);n_ctrl_arvalid=0;n=0;while(!n_ctrl_rvalid&&n<50)begin step();n=n+1;end
      if(!n_ctrl_rvalid||n_ctrl_rresp!==0||n_ctrl_rdata!==exp_data)$fatal(1,"normal ctrl R mismatch");
      @(negedge clk);n_ctrl_rready=1;step();@(negedge clk);n_ctrl_rready=0;
    end
  endtask
  task automatic normal_ctrl_read_pending(input logic [31:0] addr);
    logic taken;integer n;
    begin
      @(negedge clk);n_ctrl_araddr=addr;n_ctrl_arvalid=1;n_ctrl_rready=0;
      n=0;taken=0;while(!taken&&n<50)begin @(posedge clk);taken=n_ctrl_arready;#1;n=n+1;end
      if(!taken)$fatal(1,"normal ctrl pending AR timeout");
      @(negedge clk);n_ctrl_arvalid=0;n=0;while(!n_ctrl_rvalid&&n<50)begin step();n=n+1;end
      if(!n_ctrl_rvalid||n_ctrl_rresp!==0||n_ctrl_rdata!==32'h1)$fatal(1,"normal ctrl pending R payload");
    end
  endtask
  task automatic check_success(input logic [31:0] seed);
    integer i;logic [30:0] a;
    begin
      csr_read(32'h208,0,32'h68);
      csr_read(32'h220,0,2*LINE_COUNT);csr_read(32'h224,0,2*LINE_COUNT);
      csr_read(32'h228,0,0);csr_read(32'h22c,0,0);
      csr_read(32'h230,0,0);csr_read(32'h234,0,{1'b0,TB_BASE});
      for(i=0;i<16;i=i+1)begin csr_read(32'h240+i*4,0,0);csr_read(32'h280+i*4,0,0);end
      ck(owner_done&&!owner_fault&&diagnostic_selected&&!normal_selected,"successful diagnostic ownership state");
      ck(diag_mem_writes==2*LINE_COUNT&&diag_mem_reads==2*LINE_COUNT&&diag_fence_reads==4,"two BIST passes and four retirement fences");
      success_diag_writes=diag_mem_writes;success_diag_reads=diag_mem_reads;success_diag_fences=diag_fence_reads;
      ck(diag_ctrl_mask_reads==5&&diag_ctrl_onoff_reads==5&&diag_ctrl_status_reads==5,"startup and four ECC snapshots");
      ck(diag_ctrl_writes==1,"ECC monitor initialization mask write");
      for(i=0;i<LINE_COUNT;i=i+1)begin a=TB_BASE+31'(i*64);ck(ram[ram_index(a[12:6])]===expected_pattern(a,seed,1'b1),"complete 512-bit RAM line matches final pass");end
    end
  endtask
  task automatic start_and_drain_normal;
    begin
      normal_write(TB_BASE+31'd64,512'h123456789abcdef00123456789abcdef,1);
      normal_ctrl_read_pending(32'h8);
      ck(n_axi_bvalid&&n_ctrl_rvalid,"normal memory B and independent CTRL R outstanding before ownership request");
      csr_write(32'h210,32'h3588c350,0);csr_write(32'h20c,1,0);
      repeat(5)begin step();ck(!diagnostic_selected&&n_axi_bvalid&&n_ctrl_rvalid,"owner waits for physical B/R drain despite logical quiet witness");end
      @(negedge clk);n_axi_bready=1;n_ctrl_rready=1;
      step();ck(!n_axi_bvalid&&!n_ctrl_rvalid,"normal memory B and CTRL R drained");@(negedge clk);n_axi_bready=0;n_ctrl_rready=0;
      wait_diagnostic_selected();
    end
  endtask
  task automatic reset_transaction_domain;
    begin
      @(negedge clk);joint_rst_n=0;n_axi_awvalid=0;n_axi_wvalid=0;n_axi_arvalid=0;n_axi_bready=0;n_axi_rready=0;
      n_ctrl_awvalid=0;n_ctrl_wvalid=0;n_ctrl_arvalid=0;n_ctrl_bready=0;n_ctrl_rready=0;
      step();@(negedge clk);joint_rst_n=1;step();
    end
  endtask

  logic [511:0] ram_snapshot[0:127];
  logic [511:0] success_line;
  logic [31:0] seed_one,seed_two;
  integer i,cycles,health_wait;
  initial begin clk=0; end
  always #5 clk=~clk;
  always @(posedge clk) begin
    if(joint_rst_n) begin cycles<=cycles+1; if(cycles>20000)$fatal(1,"global watchdog"); end
    if(joint_rst_n && diagnostic_selected) begin
      ck(!normal_admission_enable,"normal admission closed during diag");
    end
  end
  task automatic wait_owner_fault;
    integer n;
    begin n=0;while(!owner_fault&&!owner_done&&n<5000)begin step();n=n+1;end
      if(!owner_fault)$fatal(1,"expected owner fault, got done=%b",owner_done);
    end
  endtask
  task automatic check_memory_pattern(input logic [31:0] seed,input logic trial);
    logic [30:0] a;integer j;
    begin for(j=0;j<LINE_COUNT;j=j+1)begin a=TB_BASE+31'(j*64);ck(ram[ram_index(a[12:6])]===expected_pattern(a,seed,trial),"all stored RAM bytes match generated pattern");end end
  endtask
  initial begin
    cycles=0;success_diag_writes=0;success_diag_reads=0;success_diag_fences=0;
    corrupt_enable=0;
    joint_rst_n='0;
    initialization_complete='0;
    calibration_complete='0;
    mig_interrupt='0;
    normal_monitor_healthy='0;
    normal_monitor_fault='0;
    normal_fabric_quiet='0;
    normal_job_owned='0;
    normal_host_busy='0;
    normal_engine_pending='0;
    normal_pending_response='0;
    n_axi_awid='0;
    n_axi_awaddr='0;
    n_axi_awlen='0;
    n_axi_awsize='0;
    n_axi_awburst='0;
    n_axi_awlock='0;
    n_axi_awcache='0;
    n_axi_awprot='0;
    n_axi_awqos='0;
    n_axi_awvalid='0;
    n_axi_arid='0;
    n_axi_araddr='0;
    n_axi_arlen='0;
    n_axi_arsize='0;
    n_axi_arburst='0;
    n_axi_arlock='0;
    n_axi_arcache='0;
    n_axi_arprot='0;
    n_axi_arqos='0;
    n_axi_arvalid='0;
    n_axi_wdata='0;
    n_axi_wstrb='0;
    n_axi_wlast='0;
    n_axi_wvalid='0;
    n_axi_bready='0;
    n_axi_rready='0;
    n_ctrl_awaddr='0;
    n_ctrl_awvalid='0;
    n_ctrl_wdata='0;
    n_ctrl_wvalid='0;
    n_ctrl_bready='0;
    n_ctrl_araddr='0;
    n_ctrl_arvalid='0;
    n_ctrl_rready='0;
    s_axil_awaddr='0;
    s_axil_awprot='0;
    s_axil_awvalid='0;
    s_axil_wdata='0;
    s_axil_wstrb='0;
    s_axil_wvalid='0;
    s_axil_bready='0;
    s_axil_araddr='0;
    s_axil_arprot='0;
    s_axil_arvalid='0;
    s_axil_rready='0;
    for(i=0;i<RAM_LINES;i=i+1) ram_snapshot[i]='0;
    step();
    @(negedge clk);joint_rst_n=1;initialization_complete=1;calibration_complete=1;normal_monitor_healthy=1;
    normal_fabric_quiet=1;normal_job_owned=0;normal_host_busy=0;normal_engine_pending=0;normal_pending_response=0;
    // Normal controller/data and ECC-control traffic works before ownership changes.
    normal_ctrl_write(32'h4,32'h3);normal_ctrl_read(32'h8,32'h1);
    success_line=512'h123456789abcdef00123456789abcdef;
    normal_write(TB_BASE,success_line,0);normal_read(TB_BASE,0,success_line);
    // Handoff is rejected while the normal host still owns an active job.
    normal_job_owned=1;csr_write(32'h210,32'h3588c350,0);csr_write(32'h20c,1,2);
    ck(!diagnostic_selected&&!owner_fault&&!owner_busy,"rejected START leaves normal ownership unchanged");normal_job_owned=0;
    normal_host_busy=1;csr_write(32'h20c,1,2);
    ck(!diagnostic_selected&&!owner_fault&&!owner_busy&&!normal_job_owned,"START rejected while only normal host is busy");normal_host_busy=0;
    // Set both logical quiescence witnesses true while actual normal B and R are still pending.
    start_and_drain_normal();
    ck(diagnostic_selected&&dut.diagnostic_monitor_healthy,"monitor initialization completes before BIST launch");
    wait_owner_done();
    check_success(32'h3588c350);
    for(i=0;i<RAM_LINES;i=i+1)ram_snapshot[i]=ram[i];
    // An unselected normal request remains held, faults ownership, and never reaches the controller.
    @(negedge clk);n_axi_awaddr=TB_BASE+31'd64;n_axi_awid=0;n_axi_awlen=0;n_axi_awsize=6;n_axi_awburst=1;n_axi_awlock=0;
    n_axi_awcache=0;n_axi_awprot=0;n_axi_awqos=0;n_axi_awvalid=1;
    repeat(3)step();
    ck(owner_fault&&diagnostic_selected&&!owner_done,"late unrouted request quarantines owner");
    ck(!n_axi_awready&&!m_axi_awvalid,"late normal AW does not leak to physical AXI");
    csr_read(32'h208,0,32'h70);csr_read(32'h228,0,32'h04000000);csr_read(32'h22c,0,0);
    reset_transaction_domain();
    ck(normal_selected&&!diagnostic_selected&&!owner_fault,"joint reset is required for normal return");
    for(i=0;i<RAM_LINES;i=i+1)ck(ram[i]===ram_snapshot[i],"RAM contents persist across transaction reset");
    normal_read(TB_BASE,0,ram_snapshot[ram_index(TB_BASE[12:6])]);normal_ctrl_read(32'h8,32'h1);
    normal_write(TB_BASE+31'd128,512'h55aa,0);normal_read(TB_BASE+31'd128,0,512'h55aa);
    // Re-arm in a new reset epoch. The model corrupts only a returned BIST read, never stored RAM.
    seed_two=32'habcdef01;corrupt_enable=1;
    csr_write(32'h210,seed_two,0);csr_write(32'h20c,1,0);
    wait_diagnostic_selected();wait_owner_fault();
    ck(corruption_fired&&owner_fault&&diagnostic_selected&&!owner_done,"corrupted raw read faults BIST owner");
    ck(dut.owner_fault_code===8'd5&&dut.sweep_fault_code===8'd4&&dut.adapter_fault_code===0&&dut.monitor_fault_code===0,"expected owner and pattern mismatch fault sources");
    csr_read(32'h208,0,32'h70);csr_read(32'h228,0,32'h05040000);csr_read(32'h22c,0,1);
    csr_read(32'h220,0,LINE_COUNT);csr_read(32'h224,0,0);csr_read(32'h230,0,{1'b0,TB_BASE});
    success_line=expected_pattern(TB_BASE,seed_two,1'b0);
    for(i=0;i<16;i=i+1)begin
      csr_read(32'h240+i*4,0,success_line[i*32 +:32]);
      csr_read(32'h280+i*4,0,(success_line[i*32 +:32]^(i==0?32'h1:32'h0)));
    end
    corrupt_enable=0;

    reset_transaction_domain();
    ck(normal_selected&&!diagnostic_selected&&!owner_fault,"joint reset recovers from memory mismatch fault");
    check_memory_pattern(seed_two,1'b0);
    normal_read(TB_BASE,0,expected_pattern(TB_BASE,seed_two,1'b0));
    // Drop platform health exactly between BIST completion and owner acceptance.
    normal_monitor_healthy=1;seed_one=32'h13572468;csr_write(32'h210,seed_one,0);csr_write(32'h20c,1,0);
    wait_diagnostic_selected();health_wait=0;
    while(dut.bist.done!==1'b1&&!owner_fault&&health_wait<5000)begin step();health_wait=health_wait+1;end
    if(dut.bist.done!==1'b1)$fatal(1,"BIST completion not reached ownerfault=%b ownercode=%02x ownerstate=%0d bistbusy=%b bistdone=%b bistfault=%b sweep=%02x adapter=%02x monitor=%02x monitorhealthy=%b platformhealthy=%b init=%b calib=%b writes=%0d reads=%0d fence=%0d",owner_fault,dut.owner_fault_code,dut.owner.state,dut.unused_bist_busy,dut.bist_done,dut.bist_fault,dut.sweep_fault_code,dut.adapter_fault_code,dut.monitor_fault_code,dut.diagnostic_monitor_healthy,normal_monitor_healthy,initialization_complete,calibration_complete,diag_mem_writes,diag_mem_reads,diag_fence_reads);
    ck(dut.completed_writes===2*LINE_COUNT&&dut.completed_reads===2*LINE_COUNT,"BIST datapath completed before health-edge reject");
    @(negedge clk);normal_monitor_healthy=0;step();
    ck(owner_fault&&diagnostic_selected&&!owner_done&&dut.owner_fault_code===8'd1&&dut.bist.done,"same-edge final health loss rejects owner completion");
    csr_read(32'h208,0,32'h70);csr_read(32'h228,0,32'h01000000);csr_read(32'h22c,0,0);
    reset_transaction_domain();normal_monitor_healthy=1;
    ck(normal_selected&&!diagnostic_selected&&!owner_fault,"joint reset recovers final-health quarantine");
    normal_read(TB_BASE,0,expected_pattern(TB_BASE,seed_one,1'b1));
    $display("PASS capacity_service base=%08x span=%08x lines=%0d diagnostic_writes=%0d diagnostic_reads=%0d fences=%0d",TB_BASE,TB_SPAN,LINE_COUNT,success_diag_writes,success_diag_reads,success_diag_fences);
    $finish;  end
endmodule
