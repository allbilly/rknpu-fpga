`timescale 1ns/1ps
// Native functional bench for the unmodified AMD AXI Clock Converter v2.1
// AXI4-Lite asynchronous mode and the public retained-epoch reset wrapper.
// This is not a substitute for Vivado IP generation, timing/CDC signoff,
// PCIe link logic, or a routed FPGA test.
module tb_actual_converter_reset;
    localparam integer SYNC_STAGES=3;
    localparam integer RESET_EDGES=8;
    localparam integer SETTLE_EDGES=5;
    localparam integer TIMEOUT_CYCLES=2000;

    // The installed AMD glbl is instantiated in this actual top. XPM reset
    // initialization is not treated as finished until its real GSR is low.
    glbl glbl();

    logic epoch_rst_n;
    logic s_clk,m_clk;
    logic s_clock_run,m_clock_run;
    wire s_aresetn,m_aresetn,s_ready,m_ready;
    integer s_aw_hs,s_w_hs,s_ar_hs,s_b_hs,s_r_hs;
    integer m_aw_hs,m_w_hs,m_ar_hs,m_b_hs,m_r_hs;
    initial begin #1000000;$fatal(1,"GLOBAL_TIMEOUT: actual converter/reset functional matrix exceeded 1 ms simulation time");end

    // Unequal stoppable clocks: source period 4.0 ns; master period 7.5 ns.
    // Disabling a domain holds its clock low without generating a new edge.
    always begin
        #2.000;
        if (s_clock_run) s_clk=~s_clk;
        else s_clk=1'b0;
    end
    always begin
        #3.750;
        if (m_clock_run) m_clk=~m_clk;
        else m_clk=1'b0;
    end

    rk_pcie_bridge_reset #(
        .SYNC_STAGES(SYNC_STAGES),.RESET_EDGES(RESET_EDGES),.SETTLE_EDGES(SETTLE_EDGES)
    ) bridge_reset (
        .epoch_rst_n(epoch_rst_n),.s_clk(s_clk),.m_clk(m_clk),
        .s_aresetn(s_aresetn),.m_aresetn(m_aresetn),.s_ready(s_ready),.m_ready(m_ready)
    );

    // TEST BFM command inputs. The actual AXI valid/ready outputs below are
    // owned by one resettable BFM process. These requests are cleared by every
    // joint-reset task before the common epoch assertion.
    logic bfm_aw_request,bfm_w_request,bfm_ar_request;
    logic bfm_bready_request,bfm_rready_request;
    logic [31:0] bfm_awaddr,bfm_wdata,bfm_araddr;
    logic [2:0] bfm_awprot,bfm_arprot;
    logic [3:0] bfm_wstrb;
    logic bfm_aw_done,bfm_w_done,bfm_ar_done;
    logic bfm_aw_active,bfm_w_active,bfm_ar_active;
    logic s_awvalid,s_wvalid,s_arvalid;
    logic s_bready,s_rready;
    logic [31:0] s_awaddr,s_wdata,s_araddr;
    logic [2:0] s_awprot,s_arprot;
    logic [3:0] s_wstrb;

    wire s_awready,s_wready,s_arready,s_bvalid,s_rvalid;
    wire [1:0] s_bresp,s_rresp;
    wire [31:0] s_rdata;
    wire m_awvalid,m_wvalid,m_arvalid,m_bready,m_rready;
    wire [31:0] m_awaddr,m_wdata,m_araddr;
    wire [2:0] m_awprot,m_arprot;
    wire [3:0] m_wstrb;

    // BFM output state is reset asynchronously by the same transaction epoch
    // as the converter. Commands are admitted only once both public domains
    // report ready and vendor GSR has been released.
    always @(posedge s_clk or negedge epoch_rst_n) begin
        if (!epoch_rst_n) begin
            bfm_aw_active<=1'b0;bfm_aw_done<=1'b0;s_awvalid<=1'b0;
            bfm_w_active<=1'b0;bfm_w_done<=1'b0;s_wvalid<=1'b0;
            bfm_ar_active<=1'b0;bfm_ar_done<=1'b0;s_arvalid<=1'b0;
            s_bready<=1'b0;s_rready<=1'b0;
            s_awaddr<=32'b0;s_awprot<=3'b0;s_wdata<=32'b0;s_wstrb<=4'b0;
            s_araddr<=32'b0;s_arprot<=3'b0;
        end else begin
            if (!bfm_aw_request) begin bfm_aw_active<=1'b0;bfm_aw_done<=1'b0;s_awvalid<=1'b0;end
            else if (!bfm_aw_active && !bfm_aw_done && s_ready===1'b1 && m_ready===1'b1 && glbl.GSR===1'b0) begin
                s_awaddr<=bfm_awaddr;s_awprot<=bfm_awprot;s_awvalid<=1'b1;bfm_aw_active<=1'b1;
            end else if (bfm_aw_active && s_awvalid && s_awready) begin
                s_awvalid<=1'b0;bfm_aw_active<=1'b0;bfm_aw_done<=1'b1;
            end

            if (!bfm_w_request) begin bfm_w_active<=1'b0;bfm_w_done<=1'b0;s_wvalid<=1'b0;end
            else if (!bfm_w_active && !bfm_w_done && s_ready===1'b1 && m_ready===1'b1 && glbl.GSR===1'b0) begin
                s_wdata<=bfm_wdata;s_wstrb<=bfm_wstrb;s_wvalid<=1'b1;bfm_w_active<=1'b1;
            end else if (bfm_w_active && s_wvalid && s_wready) begin
                s_wvalid<=1'b0;bfm_w_active<=1'b0;bfm_w_done<=1'b1;
            end

            if (!bfm_ar_request) begin bfm_ar_active<=1'b0;bfm_ar_done<=1'b0;s_arvalid<=1'b0;end
            else if (!bfm_ar_active && !bfm_ar_done && s_ready===1'b1 && m_ready===1'b1 && glbl.GSR===1'b0) begin
                s_araddr<=bfm_araddr;s_arprot<=bfm_arprot;s_arvalid<=1'b1;bfm_ar_active<=1'b1;
            end else if (bfm_ar_active && s_arvalid && s_arready) begin
                s_arvalid<=1'b0;bfm_ar_active<=1'b0;bfm_ar_done<=1'b1;
            end
            s_bready<=(bfm_bready_request && s_ready===1'b1 && m_ready===1'b1 && glbl.GSR===1'b0);
            s_rready<=(bfm_rready_request && s_ready===1'b1 && m_ready===1'b1 && glbl.GSR===1'b0);
        end
    end

    // M-domain TEST AXI4-Lite slave. AW and W are independently captured,
    // responses hold until handshake, and only offset 0 is implemented.
    // retained_word and write_effects are deliberately not reset by epoch_rst_n.
    logic slave_aw_enable,slave_w_enable,slave_ar_enable;
    logic slave_aw_pending,slave_w_pending;
    logic [31:0] slave_awaddr_q,slave_wdata_q;
    logic [2:0] slave_awprot_q;
    logic [3:0] slave_wstrb_q;
    logic slave_bvalid_q,slave_rvalid_q;
    logic [1:0] slave_bresp_q,slave_rresp_q;
    logic [31:0] slave_rdata_q;
    logic [31:0] retained_word;
    integer write_effects;
    wire m_awready,m_wready,m_arready,m_bvalid,m_rvalid;
    wire [1:0] m_bresp,m_rresp;
    wire [31:0] m_rdata;
    assign m_awready=epoch_rst_n && m_ready && slave_aw_enable && !slave_aw_pending && !slave_bvalid_q;
    assign m_wready =epoch_rst_n && m_ready && slave_w_enable  && !slave_w_pending  && !slave_bvalid_q;
    assign m_arready=epoch_rst_n && m_ready && slave_ar_enable && !slave_rvalid_q;
    assign m_bvalid=slave_bvalid_q;assign m_bresp=slave_bresp_q;
    assign m_rvalid=slave_rvalid_q;assign m_rresp=slave_rresp_q;assign m_rdata=slave_rdata_q;
    wire m_aw_fire=m_awvalid && m_awready;
    wire m_w_fire=m_wvalid && m_wready;
    wire m_ar_fire=m_arvalid && m_arready;
    wire [31:0] slave_awaddr_effective=slave_aw_pending ? slave_awaddr_q : m_awaddr;
    wire [2:0] slave_awprot_effective=slave_aw_pending ? slave_awprot_q : m_awprot;
    wire [31:0] slave_wdata_effective=slave_w_pending ? slave_wdata_q : m_wdata;
    wire [3:0] slave_wstrb_effective=slave_w_pending ? slave_wstrb_q : m_wstrb;
    wire slave_write_pair=!slave_bvalid_q && (slave_aw_pending || m_aw_fire) && (slave_w_pending || m_w_fire);

    always @(posedge m_clk or negedge epoch_rst_n) begin
        if (!epoch_rst_n) begin
            slave_aw_pending<=1'b0;slave_w_pending<=1'b0;
            slave_awaddr_q<=32'b0;slave_awprot_q<=3'b0;slave_wdata_q<=32'b0;slave_wstrb_q<=4'b0;
            slave_bvalid_q<=1'b0;slave_bresp_q<=2'b0;slave_rvalid_q<=1'b0;slave_rresp_q<=2'b0;slave_rdata_q<=32'b0;
        end else begin
            if (slave_bvalid_q && m_bready) slave_bvalid_q<=1'b0;
            if (slave_write_pair) begin
                slave_aw_pending<=1'b0;slave_w_pending<=1'b0;slave_bvalid_q<=1'b1;
                if (slave_awaddr_effective!=32'h0000_0000) slave_bresp_q<=2'b11;
                else if (slave_awprot_effective!=3'b000 || slave_wstrb_effective!=4'hF) slave_bresp_q<=2'b10;
                else begin
                    slave_bresp_q<=2'b00;retained_word<=slave_wdata_effective;write_effects<=write_effects+1;
                end
            end else begin
                if (m_aw_fire) begin slave_aw_pending<=1'b1;slave_awaddr_q<=m_awaddr;slave_awprot_q<=m_awprot;end
                if (m_w_fire) begin slave_w_pending<=1'b1;slave_wdata_q<=m_wdata;slave_wstrb_q<=m_wstrb;end
            end
            if (slave_rvalid_q && m_rready) slave_rvalid_q<=1'b0;
            if (m_ar_fire) begin
                slave_rvalid_q<=1'b1;slave_rdata_q<=32'b0;
                if (m_araddr!=32'h0000_0000) slave_rresp_q<=2'b11;
                else if (m_arprot!=3'b000) slave_rresp_q<=2'b10;
                else begin slave_rresp_q<=2'b00;slave_rdata_q<=retained_word;end
            end
        end
    end

    // Independent handshake counters are cumulative across common epochs.
    always @(posedge s_clk or negedge epoch_rst_n) if (epoch_rst_n && glbl.GSR===1'b0) begin
        if (s_awvalid && s_awready) s_aw_hs<=s_aw_hs+1;
        if (s_wvalid && s_wready) s_w_hs<=s_w_hs+1;
        if (s_arvalid && s_arready) s_ar_hs<=s_ar_hs+1;
        if (s_bvalid && s_bready) s_b_hs<=s_b_hs+1;
        if (s_rvalid && s_rready) s_r_hs<=s_r_hs+1;
    end
    always @(posedge m_clk or negedge epoch_rst_n) if (epoch_rst_n && glbl.GSR===1'b0) begin
        if (m_awvalid && m_awready) m_aw_hs<=m_aw_hs+1;
        if (m_wvalid && m_wready) m_w_hs<=m_w_hs+1;
        if (m_arvalid && m_arready) m_ar_hs<=m_ar_hs+1;
        if (m_bvalid && m_bready) m_b_hs<=m_b_hs+1;
        if (m_rvalid && m_rready) m_r_hs<=m_r_hs+1;
    end

    // Per-channel raw payload stability monitors. A held transaction may be
    // discarded only by the declared common epoch reset; reset drops these
    // monitor epochs asynchronously so they do not waive ordinary stall checks.
`define AXIL_HOLD_MON(NAME,CLK,RESETN,VALID,READY,PAYLOAD) \
    logic NAME``_held; logic [$bits(PAYLOAD)-1:0] NAME``_payload; \
    always @(posedge CLK or negedge epoch_rst_n) begin \
        if (!epoch_rst_n || (RESETN)!==1'b1) NAME``_held<=1'b0; \
        else begin \
            if (NAME``_held && ((VALID)!==1'b1 || (PAYLOAD)!==NAME``_payload)) \
                $fatal(1,"AXIL_HOLD_FAIL"); \
            NAME``_held<=((VALID)===1'b1)&&((READY)===1'b0); \
            if ((VALID)===1'b1 && (READY)===1'b0) NAME``_payload<=(PAYLOAD); \
        end \
    end
    `AXIL_HOLD_MON(s_aw,s_clk,s_aresetn,s_awvalid,s_awready,{s_awaddr,s_awprot})
    `AXIL_HOLD_MON(s_w,s_clk,s_aresetn,s_wvalid,s_wready,{s_wdata,s_wstrb})
    `AXIL_HOLD_MON(s_ar,s_clk,s_aresetn,s_arvalid,s_arready,{s_araddr,s_arprot})
    `AXIL_HOLD_MON(s_b,s_clk,s_aresetn,s_bvalid,s_bready,s_bresp)
    `AXIL_HOLD_MON(s_r,s_clk,s_aresetn,s_rvalid,s_rready,{s_rdata,s_rresp})
    `AXIL_HOLD_MON(m_aw,m_clk,m_aresetn,m_awvalid,m_awready,{m_awaddr,m_awprot})
    `AXIL_HOLD_MON(m_w,m_clk,m_aresetn,m_wvalid,m_wready,{m_wdata,m_wstrb})
    `AXIL_HOLD_MON(m_ar,m_clk,m_aresetn,m_arvalid,m_arready,{m_araddr,m_arprot})
    `AXIL_HOLD_MON(m_b,m_clk,m_aresetn,m_bvalid,m_bready,m_bresp)
    `AXIL_HOLD_MON(m_r,m_clk,m_aresetn,m_rvalid,m_rready,{m_rdata,m_rresp})
`undef AXIL_HOLD_MON

    // Unused full-AXI fields are explicitly tied at the converter boundary or
    // captured below as observations. This bench makes no zero-value contract.
    // AXI4-Lite traffic uses only
    // address/protection, data/strobes, valid/ready and the Lite responses.
    wire [0:0] s_bid_unused,s_buser_unused,s_rid_unused,s_ruser_unused;
    wire s_rlast_unused;
    wire [0:0] m_awid_unused,m_wid_unused,m_arid_unused,m_awlock_unused,m_arlock_unused;
    wire [7:0] m_awlen_unused,m_arlen_unused;
    wire [2:0] m_awsize_unused,m_arsize_unused;
    wire [1:0] m_awburst_unused,m_arburst_unused;
    wire [3:0] m_awcache_unused,m_awregion_unused,m_awqos_unused,m_arcache_unused,m_arregion_unused,m_arqos_unused;
    wire [0:0] m_awuser_unused,m_wuser_unused,m_aruser_unused;
    wire m_wlast_unused;

    axi_clock_converter_v2_1_36_axi_clock_converter #(
        .C_FAMILY("kintex7"),.C_AXI_ID_WIDTH(1),.C_AXI_ADDR_WIDTH(32),.C_AXI_DATA_WIDTH(32),
        .C_S_AXI_ACLK_RATIO(1),.C_M_AXI_ACLK_RATIO(1),.C_AXI_IS_ACLK_ASYNC(1),
        .C_AXI_PROTOCOL(2),.C_AXI_SUPPORTS_USER_SIGNALS(0),
        .C_AXI_AWUSER_WIDTH(1),.C_AXI_ARUSER_WIDTH(1),.C_AXI_WUSER_WIDTH(1),
        .C_AXI_RUSER_WIDTH(1),.C_AXI_BUSER_WIDTH(1),
        .C_AXI_SUPPORTS_WRITE(1),.C_AXI_SUPPORTS_READ(1),.C_SYNCHRONIZER_STAGE(3)
    ) dut (
        .s_axi_aclk(s_clk),.s_axi_aresetn(s_aresetn),
        .s_axi_awid(1'b0),.s_axi_awaddr(s_awaddr),.s_axi_awlen(8'b0),.s_axi_awsize(3'b0),
        .s_axi_awburst(2'b0),.s_axi_awlock(1'b0),.s_axi_awcache(4'b0),.s_axi_awprot(s_awprot),
        .s_axi_awregion(4'b0),.s_axi_awqos(4'b0),.s_axi_awuser(1'b0),
        .s_axi_awvalid(s_awvalid),.s_axi_awready(s_awready),
        .s_axi_wid(1'b0),.s_axi_wdata(s_wdata),.s_axi_wstrb(s_wstrb),.s_axi_wlast(1'b0),
        .s_axi_wuser(1'b0),.s_axi_wvalid(s_wvalid),.s_axi_wready(s_wready),
        .s_axi_bid(s_bid_unused),.s_axi_bresp(s_bresp),.s_axi_buser(s_buser_unused),
        .s_axi_bvalid(s_bvalid),.s_axi_bready(s_bready),
        .s_axi_arid(1'b0),.s_axi_araddr(s_araddr),.s_axi_arlen(8'b0),.s_axi_arsize(3'b0),
        .s_axi_arburst(2'b0),.s_axi_arlock(1'b0),.s_axi_arcache(4'b0),.s_axi_arprot(s_arprot),
        .s_axi_arregion(4'b0),.s_axi_arqos(4'b0),.s_axi_aruser(1'b0),
        .s_axi_arvalid(s_arvalid),.s_axi_arready(s_arready),
        .s_axi_rid(s_rid_unused),.s_axi_rdata(s_rdata),.s_axi_rresp(s_rresp),
        .s_axi_rlast(s_rlast_unused),.s_axi_ruser(s_ruser_unused),.s_axi_rvalid(s_rvalid),.s_axi_rready(s_rready),
        .m_axi_aclk(m_clk),.m_axi_aresetn(m_aresetn),
        .m_axi_awid(m_awid_unused),.m_axi_awaddr(m_awaddr),.m_axi_awlen(m_awlen_unused),
        .m_axi_awsize(m_awsize_unused),.m_axi_awburst(m_awburst_unused),.m_axi_awlock(m_awlock_unused),
        .m_axi_awcache(m_awcache_unused),.m_axi_awprot(m_awprot),.m_axi_awregion(m_awregion_unused),
        .m_axi_awqos(m_awqos_unused),.m_axi_awuser(m_awuser_unused),
        .m_axi_awvalid(m_awvalid),.m_axi_awready(m_awready),
        .m_axi_wid(m_wid_unused),.m_axi_wdata(m_wdata),.m_axi_wstrb(m_wstrb),
        .m_axi_wlast(m_wlast_unused),.m_axi_wuser(m_wuser_unused),.m_axi_wvalid(m_wvalid),.m_axi_wready(m_wready),
        .m_axi_bid(1'b0),.m_axi_bresp(m_bresp),.m_axi_buser(1'b0),.m_axi_bvalid(m_bvalid),.m_axi_bready(m_bready),
        .m_axi_arid(m_arid_unused),.m_axi_araddr(m_araddr),.m_axi_arlen(m_arlen_unused),
        .m_axi_arsize(m_arsize_unused),.m_axi_arburst(m_arburst_unused),.m_axi_arlock(m_arlock_unused),
        .m_axi_arcache(m_arcache_unused),.m_axi_arprot(m_arprot),.m_axi_arregion(m_arregion_unused),
        .m_axi_arqos(m_arqos_unused),.m_axi_aruser(m_aruser_unused),
        .m_axi_arvalid(m_arvalid),.m_axi_arready(m_arready),
        .m_axi_rid(1'b0),.m_axi_rdata(m_rdata),.m_axi_rresp(m_rresp),.m_axi_rlast(1'b0),
        .m_axi_ruser(1'b0),.m_axi_rvalid(m_rvalid),.m_axi_rready(m_rready)
    );

    integer check_count;
    integer reset_epochs;
    task automatic check(input logic condition,input string message);
        begin check_count=check_count+1;if(condition!==1'b1)$fatal(1,"CHECK_FAIL %s",message);end
    endtask
    task automatic record_unused_axil_fields(input string stage);
        begin
            // These full-AXI outputs are absent from the selected AXI-Lite
            // interface. Record them, without inventing an all-zero contract.
            $display("UNUSED_FULL_AXI_OBSERVATION stage=%s source=%h master=%h",stage,
                {s_bid_unused,s_buser_unused,s_rid_unused,s_ruser_unused,s_rlast_unused},
                {m_awid_unused,m_awlen_unused,m_awsize_unused,m_awburst_unused,m_awlock_unused,
                 m_awcache_unused,m_awregion_unused,m_awqos_unused,m_awuser_unused,m_wid_unused,
                 m_wlast_unused,m_wuser_unused,m_arid_unused,m_arlen_unused,m_arsize_unused,
                 m_arburst_unused,m_arlock_unused,m_arcache_unused,m_arregion_unused,m_arqos_unused,m_aruser_unused});
        end
    endtask
    task automatic wait_ready_pair(input string label);
        integer i;logic seen;
        begin
            seen=1'b0;
            for(i=0;i<TIMEOUT_CYCLES;i=i+1)begin
                @(posedge s_clk);#1;
                if(s_ready===1'b1 && m_ready===1'b1 && glbl.GSR===1'b0)begin seen=1'b1;i=TIMEOUT_CYCLES;end
            end
            check(seen,{label," both reset domains ready after real GSR release"});
            check(s_aresetn===1'b1 && m_aresetn===1'b1,{label," both converter resets released"});
        end
    endtask
    task automatic stop_s_clock;
        begin s_clock_run=1'b0;wait(s_clk===1'b0);#1;end
    endtask
    task automatic stop_m_clock;
        begin m_clock_run=1'b0;wait(m_clk===1'b0);#1;end
    endtask
    task automatic start_both_clocks;
        begin m_clock_run=1'b1;s_clock_run=1'b1;end
    endtask
    task automatic begin_aw(input logic [31:0] address,input logic [2:0] prot);
        begin
            wait_ready_pair("AW start");@(negedge s_clk);bfm_awaddr=address;bfm_awprot=prot;bfm_aw_request=1'b1;
        end
    endtask
    task automatic finish_aw(input string label);
        integer i;logic done;
        begin
            done=1'b0;
            for(i=0;i<TIMEOUT_CYCLES;i=i+1)begin @(posedge s_clk);#1;if(bfm_aw_done)begin done=1'b1;i=TIMEOUT_CYCLES;end end
            check(done,{label," source AW handshake completed"});@(negedge s_clk);bfm_aw_request=1'b0;
        end
    endtask
    task automatic begin_w(input logic [31:0] data,input logic [3:0] strobe);
        begin
            wait_ready_pair("W start");@(negedge s_clk);bfm_wdata=data;bfm_wstrb=strobe;bfm_w_request=1'b1;
        end
    endtask
    task automatic finish_w(input string label);
        integer i;logic done;
        begin
            done=1'b0;
            for(i=0;i<TIMEOUT_CYCLES;i=i+1)begin @(posedge s_clk);#1;if(bfm_w_done)begin done=1'b1;i=TIMEOUT_CYCLES;end end
            check(done,{label," source W handshake completed"});@(negedge s_clk);bfm_w_request=1'b0;
        end
    endtask
    task automatic begin_ar(input logic [31:0] address,input logic [2:0] prot);
        begin
            wait_ready_pair("AR start");@(negedge s_clk);bfm_araddr=address;bfm_arprot=prot;bfm_ar_request=1'b1;
        end
    endtask
    task automatic finish_ar(input string label);
        integer i;logic done;
        begin
            done=1'b0;
            for(i=0;i<TIMEOUT_CYCLES;i=i+1)begin @(posedge s_clk);#1;if(bfm_ar_done)begin done=1'b1;i=TIMEOUT_CYCLES;end end
            check(done,{label," source AR handshake completed"});@(negedge s_clk);bfm_ar_request=1'b0;
        end
    endtask
    task automatic wait_bvalid(input string label,input logic [1:0] expected);
        integer i;logic seen;
        begin
            seen=1'b0;
            for(i=0;i<TIMEOUT_CYCLES;i=i+1)begin @(posedge s_clk);#1;if(s_bvalid)begin seen=1'b1;i=TIMEOUT_CYCLES;end end
            check(seen,{label," response became visible"});check(s_bresp===expected,{label," exact BRESP"});check(s_bready===1'b0,{label," response held under backpressure"});
        end
    endtask
    task automatic wait_rvalid(input string label,input logic [1:0] expected_resp,input logic [31:0] expected_data);
        integer i;logic seen;
        begin
            seen=1'b0;
            for(i=0;i<TIMEOUT_CYCLES;i=i+1)begin @(posedge s_clk);#1;if(s_rvalid)begin seen=1'b1;i=TIMEOUT_CYCLES;end end
            check(seen,{label," read response became visible"});check(s_rresp===expected_resp,{label," exact RRESP"});
            check(s_rdata===expected_data,{label," exact RDATA"});check(s_rready===1'b0,{label," read held under backpressure"});
        end
    endtask
    task automatic hold_b_stable(input logic [1:0] expected,input integer cycles,input string label);
        integer i;logic [1:0] saved;
        begin
            saved=s_bresp;for(i=0;i<cycles;i=i+1)begin @(posedge s_clk);#1;check(s_bvalid===1'b1&&s_bready===1'b0&&s_bresp===saved&&saved===expected,{label," B payload stable while stalled"});end
        end
    endtask
    task automatic hold_r_stable(input logic [1:0] expected_resp,input logic [31:0] expected_data,input integer cycles,input string label);
        integer i;logic [1:0] resp_saved;logic [31:0] data_saved;
        begin
            resp_saved=s_rresp;data_saved=s_rdata;
            for(i=0;i<cycles;i=i+1)begin @(posedge s_clk);#1;check(s_rvalid===1'b1&&s_rready===1'b0&&s_rresp===resp_saved&&s_rdata===data_saved&&resp_saved===expected_resp&&data_saved===expected_data,{label," R payload stable while stalled"});end
        end
    endtask
    task automatic release_b(input integer expected_s,input integer expected_m,input string label);
        integer i;logic done;
        begin
            @(negedge s_clk);bfm_bready_request=1'b1;done=1'b0;
            for(i=0;i<TIMEOUT_CYCLES;i=i+1)begin @(posedge s_clk);#1;if(s_b_hs>=expected_s && m_b_hs>=expected_m)begin done=1'b1;i=TIMEOUT_CYCLES;end end
            check(done,{label," S and M B handshakes completed"});@(negedge s_clk);bfm_bready_request=1'b0;
        end
    endtask
    task automatic release_r(input integer expected_s,input integer expected_m,input string label);
        integer i;logic done;
        begin
            @(negedge s_clk);bfm_rready_request=1'b1;done=1'b0;
            for(i=0;i<TIMEOUT_CYCLES;i=i+1)begin @(posedge s_clk);#1;if(s_r_hs>=expected_s && m_r_hs>=expected_m)begin done=1'b1;i=TIMEOUT_CYCLES;end end
            check(done,{label," S and M R handshakes completed"});@(negedge s_clk);bfm_rready_request=1'b0;
        end
    endtask
    task automatic write_transaction(input logic [31:0] address,input logic [31:0] data,
        input logic [2:0] prot,input logic [3:0] strobe,input logic aw_first,input integer gap,
        input logic hold_response,input logic [1:0] expected_resp,input logic expect_commit,input string label);
        integer s_aw0,s_w0,m_aw0,m_w0,s_b0,m_b0,effects0,i;
        begin
            s_aw0=s_aw_hs;s_w0=s_w_hs;m_aw0=m_aw_hs;m_w0=m_w_hs;s_b0=s_b_hs;m_b0=m_b_hs;effects0=write_effects;
            if(aw_first)begin
                begin_aw(address,prot);finish_aw(label);
                for(i=0;i<gap;i=i+1)begin @(posedge s_clk);#1;check(write_effects==effects0&&!s_bvalid,{label," no early commit/B before W"});end
                begin_w(data,strobe);finish_w(label);
            end else begin
                begin_w(data,strobe);finish_w(label);
                for(i=0;i<gap;i=i+1)begin @(posedge s_clk);#1;check(write_effects==effects0&&!s_bvalid,{label," no early commit/B before AW"});end
                begin_aw(address,prot);finish_aw(label);
            end
            wait_bvalid(label,expected_resp);hold_b_stable(expected_resp,3,label);
            check(s_aw_hs==s_aw0+1 && m_aw_hs==m_aw0+1 && s_w_hs==s_w0+1 && m_w_hs==m_w0+1,
                 {label," exact independent AW/W channel handshakes"});
            check(write_effects==effects0+(expect_commit?1:0),{label," exact write side-effect count"});
            if(hold_response)begin
                check(s_b_hs==s_b0 && m_b_hs==m_b0,{label," no B handshake while response held"});
            end else release_b(s_b0+1,m_b0+1,label);
        end
    endtask
    task automatic read_transaction(input logic [31:0] address,input logic [2:0] prot,
        input logic [1:0] expected_resp,input logic [31:0] expected_data,input string label);
        integer s_ar0,m_ar0,s_r0,m_r0,effects0;
        begin
            s_ar0=s_ar_hs;m_ar0=m_ar_hs;s_r0=s_r_hs;m_r0=m_r_hs;effects0=write_effects;
            begin_ar(address,prot);finish_ar(label);wait_rvalid(label,expected_resp,expected_data);
            hold_r_stable(expected_resp,expected_data,3,label);
            check(s_ar_hs==s_ar0+1 && m_ar_hs==m_ar0+1,{label," exact AR handshakes"});
            check(s_r_hs==s_r0 && m_r_hs==m_r0,{label," no R handshakes while response held"});
            check(write_effects==effects0,{label," read did not change the retained write count"});
            release_r(s_r0+1,m_r0+1,label);
        end
    endtask
    task automatic expect_no_replay(input logic [31:0] expected_word,input integer expected_writes,input string label);
        integer i;integer writes_before;
        begin
            writes_before=write_effects;
            for(i=0;i<8;i=i+1)begin
                @(posedge s_clk);#1;
                check(!s_bvalid&&!s_rvalid&&!s_awvalid&&!s_wvalid&&!s_arvalid,
                      {label," no stale source response/request after fresh readiness"});
                @(posedge m_clk);#1;
                check(!m_bvalid&&!m_rvalid&&!m_awvalid&&!m_wvalid&&!m_arvalid,
                      {label," no stale master-side response/request after fresh readiness"});
            end
            check(write_effects==expected_writes && write_effects==writes_before && retained_word===expected_word,
                  {label," no stale write commit and retained word/count preserved"});
        end
    endtask
    task automatic common_reset_and_recover(input string label,input logic [31:0] expected_word,input integer expected_writes);
        begin
            check(glbl.GSR===1'b0,{label," vendor startup GSR has already ended"});
            // Clear all external BFM intent before common epoch assertion; the
            // BFM's actual VALID/READY state resets asynchronously from epoch_rst_n.
            bfm_aw_request=1'b0;bfm_w_request=1'b0;bfm_ar_request=1'b0;
            bfm_bready_request=1'b0;bfm_rready_request=1'b0;
            epoch_rst_n=1'b0;reset_epochs=reset_epochs+1;#1;
            slave_aw_enable=1'b1;slave_w_enable=1'b1;slave_ar_enable=1'b1;
            check(glbl.GSR===1'b0,{label," later epoch reset does not reassert vendor GSR"});
            check(s_aresetn===1'b0&&m_aresetn===1'b0&&!s_ready&&!m_ready,{label," common reset asynchronously drops project reset/ready"});
            check(!s_awvalid&&!s_wvalid&&!s_arvalid&&!s_bready&&!s_rready,{label," common reset clears BFM outputs"});
            // Do not assert a synchronous vendor VALID must drop instantly.
            #1;start_both_clocks();epoch_rst_n=1'b1;wait_ready_pair(label);
            check(glbl.GSR===1'b0,{label," vendor GSR remains released across epoch reset"});
            expect_no_replay(expected_word,expected_writes,label);
        end
    endtask
    task automatic fresh_rw_after_reset(input logic [31:0] value,input string label);
        begin
            write_transaction(32'h0,value,3'b0,4'hF,1'b1,2,1'b0,2'b00,1'b1,label);
            check(retained_word===value,{label," fresh write changed retained word"});
            read_transaction(32'h0,3'b0,2'b00,value,label);
        end
    endtask

    initial begin : directed_functional_matrix
        integer i,base_m_aw,base_s_aw,base_s_w,base_m_w,base_s_b,base_m_b,base_s_ar,base_m_ar;
        integer base_s_r,base_m_r,base_effects;
        logic [31:0] saved_word;
        check_count=0;reset_epochs=0;
        s_aw_hs=0;s_w_hs=0;s_ar_hs=0;s_b_hs=0;s_r_hs=0;
        m_aw_hs=0;m_w_hs=0;m_ar_hs=0;m_b_hs=0;m_r_hs=0;
        retained_word=32'hA5C3_5A3C;write_effects=0;
        s_clock_run=1'b0;m_clock_run=1'b1;s_clk=1'b0;m_clk=1'b0;epoch_rst_n=1'b1;
        #1;epoch_rst_n=1'b0;
        bfm_aw_request=0;bfm_w_request=0;bfm_ar_request=0;bfm_bready_request=0;bfm_rready_request=0;
        slave_aw_enable=1'b1;slave_w_enable=1'b1;slave_ar_enable=1'b1;
        // Wait for actual installed glbl GSR before releasing the project epoch.
        wait(glbl.GSR===1'b0);check(glbl.GSR===1'b0,"installed glbl GSR release observed");
        check(epoch_rst_n===1'b0,"project epoch remains held through GSR release");
        epoch_rst_n=1'b1;reset_epochs=1;
        repeat(RESET_EDGES+5)@(posedge m_clk);#1;
        check(!s_ready&&!m_ready&&!s_aresetn&&!m_aresetn,
              "stopped source clock blocks converter release/readiness while master advances");
        s_clock_run=1'b1;wait_ready_pair("initial startup");
        check(glbl.GSR===1'b0,"vendor startup GSR remains released during functional traffic");
        record_unused_axil_fields("initial startup");
        $display("PASS_GLBL_RELEASE_AND_ASYMMETRIC_STARTUP");

        saved_word=retained_word;
        // AW-first with a gap. Hold B while an independent read observes the
        // just-committed word, then release both responses.
        base_m_aw=m_aw_hs;base_s_aw=s_aw_hs;base_s_w=s_w_hs;base_m_w=m_w_hs;
        base_s_b=s_b_hs;base_m_b=m_b_hs;base_effects=write_effects;
        begin_aw(32'h0,3'b0);finish_aw("aw_first_gap");repeat(3)@(posedge s_clk);
        begin_w(32'h1111_2222,4'hF);finish_w("aw_first_gap");wait_bvalid("aw_first_gap",2'b00);
        check(write_effects==base_effects+1&&retained_word==32'h1111_2222,"AW-first commit occurs exactly once");
        read_transaction(32'h0,3'b0,2'b00,32'h1111_2222,"read while B held");
        hold_b_stable(2'b00,2,"read while B held");
        release_b(base_s_b+1,base_m_b+1,"aw_first_gap");
        check(s_aw_hs==base_s_aw+1&&m_aw_hs==base_m_aw+1&&s_w_hs==base_s_w+1&&m_w_hs==base_m_w+1,
              "AW-first source/master handshake counts");
        record_unused_axil_fields("after AW-first");

        // W-first with a separated AW channel proves the slave captures both independently.
        write_transaction(32'h0,32'h3333_4444,3'b0,4'hF,1'b0,4,1'b0,2'b00,1'b1,"w_first_gap");
        read_transaction(32'h0,3'b0,2'b00,32'h3333_4444,"w_first_readback");
        saved_word=retained_word;base_effects=write_effects;
        write_transaction(32'h4,32'hDEAD_BEEF,3'b0,4'hF,1'b1,2,1'b0,2'b11,1'b0,"unsupported_write_address");
        write_transaction(32'h0,32'hDEAD_BEEF,3'b001,4'hF,1'b0,2,1'b0,2'b10,1'b0,"unsupported_awprot");
        write_transaction(32'h0,32'hDEAD_BEEF,3'b0,4'h7,1'b1,2,1'b0,2'b10,1'b0,"unsupported_wstrb");
        check(retained_word==saved_word&&write_effects==base_effects,"write errors leave retained word/count unchanged");
        read_transaction(32'h4,3'b0,2'b11,32'b0,"unsupported_read_address");
        read_transaction(32'h0,3'b001,2'b10,32'b0,"unsupported_arprot");
        check(retained_word==saved_word,"read errors leave retained register unchanged");
        $display("PASS_AXI_LITE_ORDERING_BACKPRESSURE_AND_ERRORS");

        // Reset case 1: require the precise vendor-FSM interval where AW has
        // handshaken at M but the source-side CDC acknowledgement has not yet
        // handshaken at S. If this interval is not observable, fail explicitly.
        base_s_aw=s_aw_hs;base_m_aw=m_aw_hs;saved_word=retained_word;base_effects=write_effects;
        slave_aw_enable=1'b1;begin_aw(32'h0,3'b0);
        begin : wait_accepted_aw_before_source_ack
            logic seen;seen=1'b0;
            for(i=0;i<TIMEOUT_CYCLES;i=i+1)begin @(posedge m_clk);#1;
                if(m_aw_hs==base_m_aw+1)begin seen=1'b1;i=TIMEOUT_CYCLES;end end
            check(seen,"AW reached the actual master-side handshake in reset phase 1");
        end
        check(s_awvalid&&!s_awready,"Reset phase 1 is M-accepted AW before S-side acknowledgement");
        stop_s_clock();common_reset_and_recover("reset_with_AW_offered_to_M",saved_word,base_effects);
        check(s_aw_hs==base_s_aw&&m_aw_hs==base_m_aw+1,
              "phase-1 M AW handshake is retained only in cumulative monitor; no source handshake/replay");
        fresh_rw_after_reset(32'h5555_6666,"fresh_after_AW_partial_reset");
        $display("PASS_RESET_AW_OFFERED_BEFORE_SOURCE_HANDSHAKE");

        // Reset case 2: master accepts AW, then M stops while W is held at S.
        base_s_aw=s_aw_hs;base_m_aw=m_aw_hs;base_s_w=s_w_hs;base_m_w=m_w_hs;
        saved_word=retained_word;base_effects=write_effects;
        slave_aw_enable=1'b1;slave_w_enable=1'b0;begin_aw(32'h0,3'b0);finish_aw("reset_after_master_AW_accept");
        check(s_aw_hs==base_s_aw+1&&m_aw_hs==base_m_aw+1,"accepted AW handshakes on both sides before M stop");
        stop_m_clock();begin_w(32'hCAFE_0002,4'hF);
        begin : wait_held_w
            logic seen;seen=1'b0;
            for(i=0;i<TIMEOUT_CYCLES;i=i+1)begin @(posedge s_clk);#1;if(s_wvalid&&!s_wready)begin seen=1'b1;i=TIMEOUT_CYCLES;end end
            check(seen,"W is offered into S while stopped M prevents destination acceptance");
        end
        common_reset_and_recover("reset_after_AW_then_W_offered",saved_word,base_effects);
        check(s_aw_hs==base_s_aw+1&&m_aw_hs==base_m_aw+1&&s_w_hs==base_s_w&&m_w_hs==base_m_w,
              "AW-only accepted prefix and unaccepted W counts are exact");
        fresh_rw_after_reset(32'h7777_8888,"fresh_after_W_partial_reset");
        $display("PASS_RESET_MASTER_ACCEPTED_AW_WITH_W_OFFERED");

        // Reset case 3: successful write commits, B is held, S stops, then the
        // common epoch clears response state but preserves the committed word.
        saved_word=retained_word;base_effects=write_effects;base_s_b=s_b_hs;base_m_b=m_b_hs;
        write_transaction(32'h0,32'hBEEF_0003,3'b0,4'hF,1'b1,1,1'b1,2'b00,1'b1,"commit_then_hold_B");
        check(retained_word==32'hBEEF_0003&&write_effects==base_effects+1,"B-held write committed exactly once");
        check(s_b_hs==base_s_b&&m_b_hs==base_m_b,"B is not accepted at either side while held");
        stop_s_clock();#20;
        check(s_bvalid&&s_bresp==2'b00&&s_bready==1'b0,"committed B remains held while S clock is stopped");
        common_reset_and_recover("reset_with_B_held",32'hBEEF_0003,base_effects+1);
        check(write_effects==base_effects+1&&retained_word==32'hBEEF_0003,"held-response reset does not replay/erase committed word");
        fresh_rw_after_reset(32'h9999_AAAA,"fresh_after_B_reset");
        $display("PASS_RESET_WITH_COMMITTED_B_HELD");

        // Reset case 4: an accepted read response is held at S, then S stops
        // and a common reset flushes only transaction state, not the register.
        saved_word=retained_word;base_s_ar=s_ar_hs;base_m_ar=m_ar_hs;base_s_r=s_r_hs;base_m_r=m_r_hs;base_effects=write_effects;
        begin_ar(32'h0,3'b0);finish_ar("reset_with_R_held");wait_rvalid("reset_with_R_held",2'b00,saved_word);
        check(s_ar_hs==base_s_ar+1&&m_ar_hs==base_m_ar+1,"read address accepted at both domains");
        check(s_r_hs==base_s_r&&m_r_hs==base_m_r,"R held without any response handshake");
        stop_s_clock();#20;
        check(s_rvalid&&s_rdata==saved_word&&s_rresp==2'b00&&s_rready==1'b0,"read payload remains stable while S clock is stopped");
        common_reset_and_recover("reset_with_R_held",saved_word,base_effects);
        check(write_effects==base_effects&&retained_word==saved_word,"read-response reset preserves register/write count");
        fresh_rw_after_reset(32'hBBBB_CCCC,"fresh_after_R_reset");
        $display("PASS_RESET_WITH_R_HELD");

        // Unused full-AXI fields remain tied/unused with AXI4-Lite mode.
        record_unused_axil_fields("final");
        check(reset_epochs==5,"initial plus four explicit common transaction epochs");
        check(write_effects==7&&retained_word==32'hBBBB_CCCC,"exact retained write-effect/final-word count");
        check({s_aw_hs,m_aw_hs,s_w_hs,m_w_hs,s_b_hs,m_b_hs,s_ar_hs,m_ar_hs,s_r_hs,m_r_hs}==
              {32'd11,32'd12,32'd10,32'd10,32'd9,32'd9,32'd9,32'd9,32'd8,32'd8},
              "exact S/M AXI-Lite handshake totals across five epochs");
        $display("PASS_ACTUAL_CONVERTER_RETAINED_EPOCH_FUNCTIONAL checks=%0d epochs=%0d glbl_gsr_released=1 s_aw=%0d m_aw=%0d s_w=%0d m_w=%0d s_b=%0d m_b=%0d s_ar=%0d m_ar=%0d s_r=%0d m_r=%0d write_effects=%0d source=AMD_axi_clock_converter_v2_1_36_async_axilite scope=functional_native_only",
            check_count,reset_epochs,s_aw_hs,m_aw_hs,s_w_hs,m_w_hs,s_b_hs,m_b_hs,s_ar_hs,m_ar_hs,s_r_hs,m_r_hs,write_effects);
        $finish;
    end

endmodule
