// Private combined PCIe/JTAG and dual-MIG shell wiring candidate.
// Unqualified USER2/UI normal plus USER3/SYS maintenance wiring; not a tested image.
`timescale 1ns/1ps
module ypcb_pcie_whole_reset_top #(parameter bit LED_ACTIVE_LOW=1'b0) (
    input wire SYS_CLK,
    output wire [14:0] c0_ddr3_addr,
    output wire [2:0] c0_ddr3_ba,
    output wire c0_ddr3_cas_n,
    output wire [0:0] c0_ddr3_ck_n,
    output wire [0:0] c0_ddr3_ck_p,
    output wire [0:0] c0_ddr3_cke,
    output wire [0:0] c0_ddr3_cs_n,
    inout wire [71:0] c0_ddr3_dq,
    inout wire [8:0] c0_ddr3_dqs_n,
    inout wire [8:0] c0_ddr3_dqs_p,
    output wire [0:0] c0_ddr3_odt,
    output wire c0_ddr3_ras_n,
    output wire c0_ddr3_reset_n,
    output wire c0_ddr3_we_n,
    input wire c0_sys_clk_n,
    input wire c0_sys_clk_p,
    output wire [14:0] c1_ddr3_addr,
    output wire [2:0] c1_ddr3_ba,
    output wire c1_ddr3_cas_n,
    output wire [0:0] c1_ddr3_ck_n,
    output wire [0:0] c1_ddr3_ck_p,
    output wire [0:0] c1_ddr3_cke,
    output wire [0:0] c1_ddr3_cs_n,
    inout wire [71:0] c1_ddr3_dq,
    inout wire [8:0] c1_ddr3_dqs_n,
    inout wire [8:0] c1_ddr3_dqs_p,
    output wire [0:0] c1_ddr3_odt,
    output wire c1_ddr3_ras_n,
    output wire c1_ddr3_reset_n,
    output wire c1_ddr3_we_n,
    input wire c1_sys_clk_n,
    input wire c1_sys_clk_p,
    output wire [2:0] led_3bits_tri_o,
    input wire pcie_refclk_clk_p,
    input wire pcie_refclk_clk_n,
    input wire pcie_perstn,
    input wire [7:0] pcie_mgt_rxp,
    input wire [7:0] pcie_mgt_rxn,
    output wire [7:0] pcie_mgt_txp,
    output wire [7:0] pcie_mgt_txn
);
    wire sys_clk_ib,sys_clk50,startup_rst_n;
    wire tck,capture,shift,update,sel,tdi,tdo;
    wire mtck,mcapture,mshift,mupdate,msel,mtdi,mtdo;
    wire ui_power_rst_n,frontend_epoch_rst_n;
    wire maintenance_req_valid,maintenance_req_ready,maintenance_rsp_valid;
    wire [603:0] maintenance_req;
    wire [511:0] maintenance_rsp_data;
    wire [7:0] maintenance_rsp_status;
    wire [15:0] maintenance_rsp_seq;
    wire maintenance_quiesce_request,maintenance_reset_request;
    wire maintenance_gate_fault,maintenance_bridge_fault;
    logic [25:0] heartbeat;
    initial heartbeat='0;
    wire admission_blocked;
    wire c0_aresetn;
    wire c0_clients_rst_n;
    wire c1_aresetn;
    wire c1_clients_rst_n;
    wire fault;
    wire [1:0] transport_owner;
    wire [31:0] transport_lease_epoch;
    wire transport_release_ready;
    wire pcie_irq;
    wire pcie_protocol_fault;
    wire pcie_epoch_fault;
    wire owner_protocol_fault;
    wire [7:0] owner_failure_code;
    wire [7:0] fault_code;
    wire frame_clk;
    wire frame_rst_n;
    wire init_active;
    wire init_complete;
    wire irq;
    wire job_active;
    wire job_owned;
    wire job_retired;
    wire memory_ready;
    wire mig_sys_rst_n;
    wire [603:0] req;
    wire req_ready;
    wire req_valid;
    wire reset_req_ready;
    wire [511:0] rsp_data;
    wire [15:0] rsp_seq;
    wire [7:0] rsp_status;
    wire rsp_valid;
    wire sequence_busy;
    wire sequence_complete;
    wire sequence_fault;
    wire [7:0] sequence_fault_code;
    wire sys_clients_rst_n;
    wire [7:0] unused_c0_app_ecc_multiple_err;
    wire [7:0] unused_c0_app_ecc_single_err;
    wire unused_c0_app_ref_ack;
    wire unused_c0_app_sr_active;
    wire unused_c0_app_zq_ack;
    wire [11:0] unused_c0_device_temp;
    wire unused_c0_mmcm_locked;
    wire [7:0] unused_c1_app_ecc_multiple_err;
    wire [7:0] unused_c1_app_ecc_single_err;
    wire unused_c1_app_ref_ack;
    wire unused_c1_app_sr_active;
    wire unused_c1_app_zq_ack;
    wire [11:0] unused_c1_device_temp;
    wire unused_c1_init_calib_complete;
    wire unused_c1_interrupt;
    wire unused_c1_mmcm_locked;
    wire unused_c1_s_axi_arready;
    wire unused_c1_s_axi_awready;
    wire [3:0] unused_c1_s_axi_bid;
    wire [1:0] unused_c1_s_axi_bresp;
    wire unused_c1_s_axi_bvalid;
    wire unused_c1_s_axi_ctrl_arready;
    wire unused_c1_s_axi_ctrl_awready;
    wire [1:0] unused_c1_s_axi_ctrl_bresp;
    wire unused_c1_s_axi_ctrl_bvalid;
    wire [31:0] unused_c1_s_axi_ctrl_rdata;
    wire [1:0] unused_c1_s_axi_ctrl_rresp;
    wire unused_c1_s_axi_ctrl_rvalid;
    wire unused_c1_s_axi_ctrl_wready;
    wire [511:0] unused_c1_s_axi_rdata;
    wire [3:0] unused_c1_s_axi_rid;
    wire unused_c1_s_axi_rlast;
    wire [1:0] unused_c1_s_axi_rresp;
    wire unused_c1_s_axi_rvalid;
    wire unused_c1_s_axi_wready;
    wire pcie_refclk,pcie_refclk_odiv2_unused,pcie_perst_n;
    wire pcie_source_healthy,pcie_clock_alive,pcie_axi_clk,pcie_axi_aresetn,pcie_link_up,dma_protocol_fault;
    wire [31:0] pcie_axil_awaddr;
    wire [2:0] pcie_axil_awprot;
    wire pcie_axil_awvalid;
    wire pcie_axil_awready;
    wire [31:0] pcie_axil_wdata;
    wire [3:0] pcie_axil_wstrb;
    wire pcie_axil_wvalid;
    wire pcie_axil_wready;
    wire [1:0] pcie_axil_bresp;
    wire pcie_axil_bvalid;
    wire pcie_axil_bready;
    wire [31:0] pcie_axil_araddr;
    wire [2:0] pcie_axil_arprot;
    wire pcie_axil_arvalid;
    wire pcie_axil_arready;
    wire [31:0] pcie_axil_rdata;
    wire [1:0] pcie_axil_rresp;
    wire pcie_axil_rvalid;
    wire pcie_axil_rready;
    IBUFDS_GTE2 u_pcie_refclk_buf(
        .I(pcie_refclk_clk_p),.IB(pcie_refclk_clk_n),.CEB(1'b0),
        .O(pcie_refclk),.ODIV2(pcie_refclk_odiv2_unused));
    IBUF u_pcie_perst_buf(.I(pcie_perstn),.O(pcie_perst_n));
    IBUF u_ibuf50(.I(SYS_CLK),.O(sys_clk_ib));
    BUFG u_bufg50(.I(sys_clk_ib),.O(sys_clk50));
    (* DONT_TOUCH="TRUE" *) BSCANE2 #(.JTAG_CHAIN(2)) u_bscan(
        .TCK(tck),.DRCK(),.CAPTURE(capture),.SHIFT(shift),.UPDATE(update),
        .SEL(sel),.TDI(tdi),.TDO(tdo),.RESET(),.RUNTEST(),.TMS());
    (* DONT_TOUCH="TRUE" *) BSCANE2 #(.JTAG_CHAIN(3)) u_maintenance_bscan(
        .TCK(mtck),.DRCK(),.CAPTURE(mcapture),.SHIFT(mshift),.UPDATE(mupdate),
        .SEL(msel),.TDI(mtdi),.TDO(mtdo),.RESET(),.RUNTEST(),.TMS());
    (* KEEP_HIERARCHY="TRUE" *) rk_retained_jtag_mailbox u_mailbox(
        .clk(frame_clk),.tck,.capture,.shift,.update,.sel,.tdi,.tdo,
        .power_rst_n(ui_power_rst_n),
        .req_valid,.req_ready,.req,.rsp_valid,.rsp_data,.rsp_status,.rsp_seq);
    (* KEEP_HIERARCHY="TRUE" *) rk_retained_jtag_mailbox u_maintenance_mailbox(
        .clk(sys_clk50),.tck(mtck),.capture(mcapture),.shift(mshift),.update(mupdate),
        .sel(msel),.tdi(mtdi),.tdo(mtdo),.power_rst_n(startup_rst_n),
        .req_valid(maintenance_req_valid),.req_ready(maintenance_req_ready),.req(maintenance_req),
        .rsp_valid(maintenance_rsp_valid),.rsp_data(maintenance_rsp_data),
        .rsp_status(maintenance_rsp_status),.rsp_seq(maintenance_rsp_seq));
    (* KEEP_HIERARCHY="TRUE" *) rk_pcie_whole_reset_mig_platform platform(
        .admission_blocked(admission_blocked),
        .c0_aresetn(c0_aresetn),
        .c0_clients_rst_n(c0_clients_rst_n),
        .c0_ddr3_addr(c0_ddr3_addr),
        .c0_ddr3_ba(c0_ddr3_ba),
        .c0_ddr3_cas_n(c0_ddr3_cas_n),
        .c0_ddr3_ck_n(c0_ddr3_ck_n),
        .c0_ddr3_ck_p(c0_ddr3_ck_p),
        .c0_ddr3_cke(c0_ddr3_cke),
        .c0_ddr3_cs_n(c0_ddr3_cs_n),
        .c0_ddr3_dq(c0_ddr3_dq),
        .c0_ddr3_dqs_n(c0_ddr3_dqs_n),
        .c0_ddr3_dqs_p(c0_ddr3_dqs_p),
        .c0_ddr3_odt(c0_ddr3_odt),
        .c0_ddr3_ras_n(c0_ddr3_ras_n),
        .c0_ddr3_reset_n(c0_ddr3_reset_n),
        .c0_ddr3_we_n(c0_ddr3_we_n),
        .c0_sys_clk_n(c0_sys_clk_n),
        .c0_sys_clk_p(c0_sys_clk_p),
        .c1_aresetn(c1_aresetn),
        .c1_clients_rst_n(c1_clients_rst_n),
        .c1_ddr3_addr(c1_ddr3_addr),
        .c1_ddr3_ba(c1_ddr3_ba),
        .c1_ddr3_cas_n(c1_ddr3_cas_n),
        .c1_ddr3_ck_n(c1_ddr3_ck_n),
        .c1_ddr3_ck_p(c1_ddr3_ck_p),
        .c1_ddr3_cke(c1_ddr3_cke),
        .c1_ddr3_cs_n(c1_ddr3_cs_n),
        .c1_ddr3_dq(c1_ddr3_dq),
        .c1_ddr3_dqs_n(c1_ddr3_dqs_n),
        .c1_ddr3_dqs_p(c1_ddr3_dqs_p),
        .c1_ddr3_odt(c1_ddr3_odt),
        .c1_ddr3_ras_n(c1_ddr3_ras_n),
        .c1_ddr3_reset_n(c1_ddr3_reset_n),
        .c1_ddr3_we_n(c1_ddr3_we_n),
        .c1_sys_clk_n(c1_sys_clk_n),
        .c1_sys_clk_p(c1_sys_clk_p),
        .cfg_reset(~startup_rst_n),
        .ui_power_rst_n(ui_power_rst_n),
        .frontend_epoch_rst_n(frontend_epoch_rst_n),
        .maintenance_req_valid(maintenance_req_valid),
        .maintenance_req_ready(maintenance_req_ready),
        .maintenance_req(maintenance_req),
        .maintenance_rsp_valid(maintenance_rsp_valid),
        .maintenance_rsp_data(maintenance_rsp_data),
        .maintenance_rsp_status(maintenance_rsp_status),
        .maintenance_rsp_seq(maintenance_rsp_seq),
        .maintenance_quiesce_request(maintenance_quiesce_request),
        .maintenance_reset_request(maintenance_reset_request),
        .maintenance_gate_fault(maintenance_gate_fault),
        .maintenance_bridge_fault(maintenance_bridge_fault),
        .fault(fault),
        .fault_code(fault_code),
        .frame_clk(frame_clk),
        .frame_rst_n(frame_rst_n),
        .init_active(init_active),
        .init_complete(init_complete),
        .irq(irq),
        .job_active(job_active),
        .job_owned(job_owned),
        .job_retired(job_retired),
        .memory_ready(memory_ready),
        .mig_sys_rst_n(mig_sys_rst_n),
        .req(req),
        .req_ready(req_ready),
        .req_valid(req_valid),
        .reset_req_ready(reset_req_ready),
        .rsp_data(rsp_data),
        .rsp_seq(rsp_seq),
        .rsp_status(rsp_status),
        .rsp_valid(rsp_valid),
        .sequence_busy(sequence_busy),
        .sequence_complete(sequence_complete),
        .sequence_fault(sequence_fault),
        .sequence_fault_code(sequence_fault_code),
        .sys_clients_rst_n(sys_clients_rst_n),
        .sys_clk(sys_clk50),
        .unused_c0_app_ecc_multiple_err(unused_c0_app_ecc_multiple_err),
        .unused_c0_app_ecc_single_err(unused_c0_app_ecc_single_err),
        .unused_c0_app_ref_ack(unused_c0_app_ref_ack),
        .unused_c0_app_sr_active(unused_c0_app_sr_active),
        .unused_c0_app_zq_ack(unused_c0_app_zq_ack),
        .unused_c0_device_temp(unused_c0_device_temp),
        .unused_c0_mmcm_locked(unused_c0_mmcm_locked),
        .unused_c1_app_ecc_multiple_err(unused_c1_app_ecc_multiple_err),
        .unused_c1_app_ecc_single_err(unused_c1_app_ecc_single_err),
        .unused_c1_app_ref_ack(unused_c1_app_ref_ack),
        .unused_c1_app_sr_active(unused_c1_app_sr_active),
        .unused_c1_app_zq_ack(unused_c1_app_zq_ack),
        .unused_c1_device_temp(unused_c1_device_temp),
        .unused_c1_init_calib_complete(unused_c1_init_calib_complete),
        .unused_c1_interrupt(unused_c1_interrupt),
        .unused_c1_mmcm_locked(unused_c1_mmcm_locked),
        .unused_c1_s_axi_arready(unused_c1_s_axi_arready),
        .unused_c1_s_axi_awready(unused_c1_s_axi_awready),
        .unused_c1_s_axi_bid(unused_c1_s_axi_bid),
        .unused_c1_s_axi_bresp(unused_c1_s_axi_bresp),
        .unused_c1_s_axi_bvalid(unused_c1_s_axi_bvalid),
        .unused_c1_s_axi_ctrl_arready(unused_c1_s_axi_ctrl_arready),
        .unused_c1_s_axi_ctrl_awready(unused_c1_s_axi_ctrl_awready),
        .unused_c1_s_axi_ctrl_bresp(unused_c1_s_axi_ctrl_bresp),
        .unused_c1_s_axi_ctrl_bvalid(unused_c1_s_axi_ctrl_bvalid),
        .unused_c1_s_axi_ctrl_rdata(unused_c1_s_axi_ctrl_rdata),
        .unused_c1_s_axi_ctrl_rresp(unused_c1_s_axi_ctrl_rresp),
        .unused_c1_s_axi_ctrl_rvalid(unused_c1_s_axi_ctrl_rvalid),
        .unused_c1_s_axi_ctrl_wready(unused_c1_s_axi_ctrl_wready),
        .unused_c1_s_axi_rdata(unused_c1_s_axi_rdata),
        .unused_c1_s_axi_rid(unused_c1_s_axi_rid),
        .unused_c1_s_axi_rlast(unused_c1_s_axi_rlast),
        .unused_c1_s_axi_rresp(unused_c1_s_axi_rresp),
        .unused_c1_s_axi_rvalid(unused_c1_s_axi_rvalid),
        .unused_c1_s_axi_wready(unused_c1_s_axi_wready),
        .pcie_axil_awaddr(pcie_axil_awaddr),
        .pcie_axil_awprot(pcie_axil_awprot),
        .pcie_axil_awvalid(pcie_axil_awvalid),
        .pcie_axil_awready(pcie_axil_awready),
        .pcie_axil_wdata(pcie_axil_wdata),
        .pcie_axil_wstrb(pcie_axil_wstrb),
        .pcie_axil_wvalid(pcie_axil_wvalid),
        .pcie_axil_wready(pcie_axil_wready),
        .pcie_axil_bresp(pcie_axil_bresp),
        .pcie_axil_bvalid(pcie_axil_bvalid),
        .pcie_axil_bready(pcie_axil_bready),
        .pcie_axil_araddr(pcie_axil_araddr),
        .pcie_axil_arprot(pcie_axil_arprot),
        .pcie_axil_arvalid(pcie_axil_arvalid),
        .pcie_axil_arready(pcie_axil_arready),
        .pcie_axil_rdata(pcie_axil_rdata),
        .pcie_axil_rresp(pcie_axil_rresp),
        .pcie_axil_rvalid(pcie_axil_rvalid),
        .pcie_axil_rready(pcie_axil_rready),
        .jtag_link_healthy(1'b1),
        .pcie_link_healthy(pcie_source_healthy),
        .transport_release_ready(transport_release_ready),
        .transport_owner(transport_owner),
        .transport_lease_epoch(transport_lease_epoch),
        .pcie_irq(pcie_irq),
        .pcie_protocol_fault(pcie_protocol_fault),
        .pcie_epoch_fault(pcie_epoch_fault),
        .owner_protocol_fault(owner_protocol_fault),
        .owner_failure_code(owner_failure_code)
    );
    rk_pcie_control_plane pcie_control_plane (
        .pcie_refclk(pcie_refclk),.pcie_perst_n(pcie_perst_n),.c0_ui_clk(frame_clk),
        .common_epoch_rst_n(sys_clients_rst_n),.ui_epoch_rst_n(frontend_epoch_rst_n),
        .pci_exp_rxp(pcie_mgt_rxp),.pci_exp_rxn(pcie_mgt_rxn),
        .pci_exp_txp(pcie_mgt_txp),.pci_exp_txn(pcie_mgt_txn),
        .pcie_source_healthy(pcie_source_healthy),.pcie_clock_alive(pcie_clock_alive),
        .pcie_axi_clk(pcie_axi_clk),.pcie_axi_aresetn(pcie_axi_aresetn),
        .pcie_link_up(pcie_link_up),.dma_protocol_fault(dma_protocol_fault),
        .pcie_axil_awaddr(pcie_axil_awaddr),
        .pcie_axil_awprot(pcie_axil_awprot),
        .pcie_axil_awvalid(pcie_axil_awvalid),
        .pcie_axil_awready(pcie_axil_awready),
        .pcie_axil_wdata(pcie_axil_wdata),
        .pcie_axil_wstrb(pcie_axil_wstrb),
        .pcie_axil_wvalid(pcie_axil_wvalid),
        .pcie_axil_wready(pcie_axil_wready),
        .pcie_axil_bresp(pcie_axil_bresp),
        .pcie_axil_bvalid(pcie_axil_bvalid),
        .pcie_axil_bready(pcie_axil_bready),
        .pcie_axil_araddr(pcie_axil_araddr),
        .pcie_axil_arprot(pcie_axil_arprot),
        .pcie_axil_arvalid(pcie_axil_arvalid),
        .pcie_axil_arready(pcie_axil_arready),
        .pcie_axil_rdata(pcie_axil_rdata),
        .pcie_axil_rresp(pcie_axil_rresp),
        .pcie_axil_rvalid(pcie_axil_rvalid),
        .pcie_axil_rready(pcie_axil_rready)
    );
    always_ff @(posedge sys_clk50) begin
        if(!startup_rst_n) heartbeat<='0; else heartbeat<=heartbeat+1'b1;
    end
    // Init/fault/heartbeat are status, never a workload PASS indicator.
    assign led_3bits_tri_o={heartbeat[25],fault,init_complete}^{3{LED_ACTIVE_LOW}};
endmodule
