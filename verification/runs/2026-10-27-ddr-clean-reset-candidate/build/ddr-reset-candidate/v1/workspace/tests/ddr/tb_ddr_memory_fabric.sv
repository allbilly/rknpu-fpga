// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Independent AXI RAM/check-receipt model only. The FULL_SPAN branch validates
// every default-span write without allocating a 2-GiB simulation array. Neither
// branch simulates the MIG PHY, ECC encoding or controller ordering premise.
module tb_ddr_memory_fabric #(
    parameter bit FULL_SPAN = 0,
    parameter logic [31:0] DUT_BASE = 32'h10000000,
    parameter logic [32:0] DUT_BYTES = 256,
    parameter int unsigned DUT_TIMEOUT_CYCLES = 32
);
    localparam logic [31:0] MODEL_BASE = FULL_SPAN?32'b0:DUT_BASE;
    localparam logic [32:0] MODEL_BYTES = FULL_SPAN?33'h080000000:DUT_BYTES;
    logic clk;
    initial clk=0;
    always #5 clk=~clk;
    logic joint_rst_n,sequence_ready,calib_complete,monitor_healthy,monitor_fault,host_session_busy;
    logic [7:0] monitor_fault_code;
    logic host_valid,host_write,host_rsp_ready;
    logic [31:0] host_addr;
    logic [15:0] host_wdata;
    wire host_ready,host_rsp_valid,host_error;
    wire [15:0] host_rdata;
    logic engine_req_valid,engine_req_write,engine_rsp_ready;
    logic [31:0] engine_req_addr;
    logic [15:0] engine_req_wdata;
    wire engine_req_ready,engine_rsp_valid,engine_rsp_error;
    wire [15:0] engine_rsp_rdata;
    logic job_begin,job_seal,job_abort,job_release;
    wire job_begin_ready,init_complete,init_active,memory_ready,job_owned,job_active,job_retired,fault;
    wire [7:0] fault_code;
    wire monitor_check_valid,monitor_snapshot_ready;
    wire monitor_check_ready,monitor_snapshot_valid;
    logic [31:0] monitor_snapshot_status,monitor_snapshot_onoff,monitor_snapshot_irq_mask;
    wire [3:0] m_axi_awid,m_axi_arid,m_axi_awcache,m_axi_arcache,m_axi_awqos,m_axi_arqos;
    wire [30:0] m_axi_awaddr,m_axi_araddr;
    wire [7:0] m_axi_awlen,m_axi_arlen;
    wire [2:0] m_axi_awsize,m_axi_arsize,m_axi_awprot,m_axi_arprot;
    wire [1:0] m_axi_awburst,m_axi_arburst;
    wire m_axi_awlock,m_axi_arlock,m_axi_awvalid,m_axi_wlast,m_axi_wvalid,m_axi_bready,m_axi_arvalid,m_axi_rready;
    wire [511:0] m_axi_wdata;
    wire [63:0] m_axi_wstrb;
    wire m_axi_awready,m_axi_wready,m_axi_bvalid,m_axi_arready,m_axi_rlast,m_axi_rvalid;
    logic [3:0] m_axi_bid,m_axi_rid;
    logic [1:0] m_axi_bresp,m_axi_rresp;
    wire [511:0] m_axi_rdata;
    if(FULL_SPAN)begin: full_default
        rk_ddr_memory_fabric #(.TIMEOUT_CYCLES(DUT_TIMEOUT_CYCLES)) dut(.*);
    end else begin: small_profile
        rk_ddr_memory_fabric #(.BASE(DUT_BASE),.BYTES(DUT_BYTES),.TIMEOUT_CYCLES(DUT_TIMEOUT_CYCLES)) dut(.*);
    end

    logic allow_aw,allow_w,allow_b,allow_ar,allow_r,allow_check,allow_snapshot;
    logic inject_b,inject_r,force_not_last;
    logic aw_saved,w_saved,bvalid,ar_saved,rvalid,check_saved,snapshot_valid;
    logic [30:0] saved_awaddr,saved_araddr;
    logic [511:0] saved_wdata,read_data;
    logic [63:0] saved_wstrb;
    logic [7:0] bytes[0:255];
    logic init_walking,expect_fence_address;
    logic [30:0] last_acknowledged_aw;
    integer aw_count,w_count,b_count,ar_count,r_count,check_count,retired_count,cases;
    logic prior_aw_stall,prior_w_stall,prior_ar_stall;
    logic [30:0] prior_awaddr,prior_araddr;
    logic [511:0] prior_wdata;
    logic [63:0] prior_wstrb;
    assign m_axi_awready=joint_rst_n&&allow_aw&&!aw_saved&&!bvalid;
    assign m_axi_wready=joint_rst_n&&allow_w&&!w_saved&&!bvalid;
    assign m_axi_bvalid=bvalid||inject_b;
    assign m_axi_arready=joint_rst_n&&allow_ar&&!ar_saved&&!rvalid;
    assign m_axi_rvalid=rvalid||inject_r;
    assign m_axi_rlast=!force_not_last;
    assign m_axi_rdata=read_data;
    assign monitor_check_ready=joint_rst_n&&allow_check&&!check_saved&&!snapshot_valid;
    assign monitor_snapshot_valid=snapshot_valid;

    always @(posedge clk)begin
        if(!joint_rst_n)begin
            aw_saved<=0;w_saved<=0;bvalid<=0;ar_saved<=0;rvalid<=0;check_saved<=0;snapshot_valid<=0;
            saved_awaddr<=0;saved_araddr<=0;saved_wdata<=0;saved_wstrb<=0;read_data<=0;
            aw_count<=0;w_count<=0;b_count<=0;ar_count<=0;r_count<=0;check_count<=0;retired_count<=0;
            prior_aw_stall<=0;prior_w_stall<=0;prior_ar_stall<=0;
            prior_awaddr<=0;prior_araddr<=0;prior_wdata<=0;prior_wstrb<=0;init_walking<=1;last_acknowledged_aw<=0;
        end else begin
            if(prior_aw_stall&&(!m_axi_awvalid||m_axi_awaddr!==prior_awaddr))$fatal(1,"AW withdrawn/changed");
            if(prior_w_stall&&(!m_axi_wvalid||m_axi_wdata!==prior_wdata||m_axi_wstrb!==prior_wstrb))$fatal(1,"W withdrawn/changed");
            if(prior_ar_stall&&(!m_axi_arvalid||m_axi_araddr!==prior_araddr))$fatal(1,"AR withdrawn/changed");
            prior_aw_stall<=m_axi_awvalid&&!m_axi_awready;prior_w_stall<=m_axi_wvalid&&!m_axi_wready;
            prior_ar_stall<=m_axi_arvalid&&!m_axi_arready;
            prior_awaddr<=m_axi_awaddr;prior_araddr<=m_axi_araddr;prior_wdata<=m_axi_wdata;prior_wstrb<=m_axi_wstrb;
            if(m_axi_awvalid&&m_axi_awready)begin
                if(m_axi_awid!==0||m_axi_awlen!==0||m_axi_awsize!==6||m_axi_awburst!==1||
                    m_axi_awlock!==0||m_axi_awcache!==0||m_axi_awprot!==0||m_axi_awqos!==0)
                    $fatal(1,"Noncanonical write fields");
                if(init_walking&&m_axi_awaddr!==31'(MODEL_BASE+32'(aw_count)*64))$fatal(1,"Init range/order changed");
                aw_saved<=1;saved_awaddr<=m_axi_awaddr;aw_count<=aw_count+1;
                if(FULL_SPAN&&((aw_count+1)%1048576)==0)begin
                    $display("PROGRESS default_c0_init_lines=%0d",aw_count+1);
                    $fflush();
                end
            end
            if(m_axi_wvalid&&m_axi_wready)begin
                if(m_axi_wlast!==1)$fatal(1,"Missing write-last");
                if(init_walking&&(m_axi_wdata!==0||m_axi_wstrb!==64'hffff_ffff_ffff_ffff))
                    $fatal(1,"Initialization used data fixups or partial ECC writes");
                w_saved<=1;saved_wdata<=m_axi_wdata;saved_wstrb<=m_axi_wstrb;w_count<=w_count+1;
            end
            if(aw_saved&&w_saved&&allow_b&&!bvalid)begin
                if(!FULL_SPAN)for(integer n=0;n<64;n=n+1)begin
                    if(saved_wstrb[n])bytes[32'(saved_awaddr)-MODEL_BASE+32'(n)]<=saved_wdata[8*n+:8];
                end
                aw_saved<=0;w_saved<=0;bvalid<=1;
            end
            if(bvalid&&m_axi_bready)begin bvalid<=0;b_count<=b_count+1;last_acknowledged_aw<=saved_awaddr;end
            if(m_axi_arvalid&&m_axi_arready)begin
                if(m_axi_arid!==0||m_axi_arlen!==0||m_axi_arsize!==6||m_axi_arburst!==1||
                    m_axi_arlock!==0||m_axi_arcache!==0||m_axi_arprot!==0||m_axi_arqos!==0)
                    $fatal(1,"Noncanonical read fields");
                if(init_walking)begin
                    if({2'b0,m_axi_araddr}!==({1'b0,MODEL_BASE}+MODEL_BYTES-64)||
                        aw_count!=32'(MODEL_BYTES>>6)||b_count!=32'(MODEL_BYTES>>6))
                        $fatal(1,"Initialization fence not based on actual final AW/B");
                    init_walking<=0;
                end else if(expect_fence_address&&m_axi_araddr!==last_acknowledged_aw)
                    $fatal(1,"Fence did not use the actually acknowledged final AW address");
                ar_saved<=1;saved_araddr<=m_axi_araddr;ar_count<=ar_count+1;
            end
            if(ar_saved&&allow_r&&!rvalid)begin
                if(FULL_SPAN)read_data<=0;
                else for(integer n=0;n<64;n=n+1)read_data[8*n+:8]<=bytes[32'(saved_araddr)-MODEL_BASE+32'(n)];
                ar_saved<=0;rvalid<=1;
            end
            if(rvalid&&m_axi_rready)begin rvalid<=0;r_count<=r_count+1;end
            if(monitor_check_valid&&monitor_check_ready)begin check_saved<=1;check_count<=check_count+1;end
            if(check_saved&&allow_snapshot&&!snapshot_valid)begin check_saved<=0;snapshot_valid<=1;end
            if(snapshot_valid&&monitor_snapshot_ready)snapshot_valid<=0;
            if(job_retired)retired_count<=retired_count+1;
        end
    end
    task automatic tick;
        @(posedge clk);#1;
    endtask
    task automatic reset_case;
        @(negedge clk);joint_rst_n=0;sequence_ready=0;calib_complete=0;monitor_healthy=0;monitor_fault=0;monitor_fault_code=0;
        host_session_busy=0;host_valid=0;host_write=0;host_addr=MODEL_BASE;host_wdata=0;host_rsp_ready=0;
        engine_req_valid=0;engine_req_write=0;engine_req_addr=MODEL_BASE;engine_req_wdata=0;engine_rsp_ready=0;
        job_begin=0;job_seal=0;job_abort=0;job_release=0;
        expect_fence_address=0;
        allow_aw=1;allow_w=1;allow_b=1;allow_ar=1;allow_r=1;allow_check=1;allow_snapshot=1;
        inject_b=0;inject_r=0;force_not_last=0;m_axi_bid=0;m_axi_bresp=0;m_axi_rid=0;m_axi_rresp=0;
        monitor_snapshot_status=0;monitor_snapshot_onoff=1;monitor_snapshot_irq_mask=3;
        if(!FULL_SPAN)for(integer i=0;i<256;i=i+1)bytes[i]=8'ha5;
        repeat(3)tick();@(negedge clk);joint_rst_n=1;repeat(3)tick();
        if(init_complete||!init_active||memory_ready||host_ready||engine_req_ready||fault||m_axi_awvalid||m_axi_wvalid||m_axi_arvalid)
            $fatal(1,"Initialization admission before qualification");
    endtask
    task automatic start_init;
        @(negedge clk);sequence_ready=1;calib_complete=1;monitor_healthy=1;
    endtask
    task automatic await_init;
        integer n;
        n=0;while(!init_complete&&!fault&&n<500)begin tick();n=n+1;end
        if(!init_complete||fault||!memory_ready||!job_begin_ready||aw_count!=32'(MODEL_BYTES>>6)||
            b_count!=aw_count||ar_count!=1||r_count!=1||check_count!=1)
            $fatal(1,"Initialization did not finish exact span/fence code=%0d",fault_code);
        if(!FULL_SPAN)for(integer i=0;i<256;i=i+1)if(bytes[i]!==0)$fatal(1,"Byte not initialized");
    endtask
    task automatic boot;
        reset_case();start_init();await_init();
    endtask
    task automatic host_request(input logic wr,input logic[31:0] addr,input logic[15:0] data);
        integer n;
        @(negedge clk);host_write=wr;host_addr=addr;host_wdata=data;host_valid=1;n=0;
        expect_fence_address=wr;
        while(!host_ready&&!fault&&n<100)begin tick();n=n+1;end
        if(!host_ready||fault)$fatal(1,"HOST admission failed");
        tick();@(negedge clk);host_valid=0;
    endtask
    task automatic host_response(input logic error_expected,input logic[15:0] data,input bit check_data);
        integer n;
        n=0;while(!host_rsp_valid&&!fault&&n<200)begin tick();n=n+1;end
        if(!host_rsp_valid||host_error!==error_expected||(check_data&&host_rdata!==data))
            $fatal(1,"HOST response mismatch err=%b data=%h code=%0d",host_error,host_rdata,fault_code);
        @(negedge clk);host_rsp_ready=1;tick();@(negedge clk);host_rsp_ready=0;
        expect_fence_address=0;
    endtask
    task automatic begin_job;
        @(negedge clk);#1;
        if(!job_begin_ready)$fatal(1,"Job not ready");
        job_begin=1;tick();@(negedge clk);job_begin=0;
        if(!job_owned||!job_active||host_ready)$fatal(1,"Job ownership not captured");
    endtask
    task automatic engine_request(input logic wr,input logic[31:0] addr,input logic[15:0] data);
        @(negedge clk);engine_req_write=wr;engine_req_addr=addr;engine_req_wdata=data;engine_req_valid=1;
        if(!engine_req_ready)$fatal(1,"Engine not ready");
        tick();@(negedge clk);engine_req_valid=0;
    endtask
    task automatic engine_response(input logic error_expected,input logic[15:0] data,input bit check_data);
        integer n;
        n=0;while(!engine_rsp_valid&&!fault&&n<100)begin tick();n=n+1;end
        if(!engine_rsp_valid||engine_rsp_error!==error_expected||(check_data&&engine_rsp_rdata!==data))
            $fatal(1,"Engine response mismatch");
        @(negedge clk);engine_rsp_ready=1;tick();@(negedge clk);engine_rsp_ready=0;
    endtask
    task automatic seal_job;
        @(negedge clk);expect_fence_address=1;job_seal=1;tick();@(negedge clk);job_seal=0;
    endtask
    task automatic await_retired;
        integer n;
        n=0;while(job_active&&!fault&&n<100)begin tick();n=n+1;end
        if(job_retired)tick();
        if(fault||job_active||!job_owned||retired_count!=1)$fatal(1,"Job did not retire once");
        expect_fence_address=0;
    endtask
    task automatic expect_fault(input logic[7:0] code);
        integer n;
        tick();
        n=0;while((!fault||fault_code==0)&&n<150)begin tick();n=n+1;end
        if(!fault||fault_code!==code||memory_ready||host_ready||engine_req_ready||job_retired)
            $fatal(1,"Fault mismatch case%0d want%0d got%0d aw=%0d ar=%0d check=%0d",cases,code,fault_code,aw_count,ar_count,check_count);
        cases=cases+1;
    endtask
    integer before_aw,before_ar,before_check;
    logic [15:0] held_data;
    initial begin
        cases=0;joint_rst_n=0;
        reset_case();start_init();
        if(FULL_SPAN)begin
            wait(init_complete||fault);#1;
            if(fault||aw_count!=33554432||w_count!=33554432||b_count!=33554432||
                ar_count!=1||r_count!=1||check_count!=1||!memory_ready)
                $fatal(1,"Default full-span stream mismatch code=%0d",fault_code);
            $display("PASS ddr_memory_fabric default_span_bytes=2147483648 lines=33554432 last=7fffffc0 full_strobes=1 init_fences=1 no_DDR_contents_or_physical_proof");
            $finish;
        end
        await_init();cases=cases+1;
        host_request(1,MODEL_BASE+2,16'h1234);host_response(0,0,0);
        if(bytes[0]!==0||bytes[1]!==0||bytes[2]!==8'h34||bytes[3]!==8'h12||bytes[4]!==0||
            check_count!=2||ar_count!=2)$fatal(1,"Masked HOST write lacked fence or damaged neighbor");
        host_request(0,MODEL_BASE+2,0);host_response(0,16'h1234,1);cases=cases+1;

        @(negedge clk);allow_snapshot=0;
        host_request(1,MODEL_BASE+66,16'h5678);wait(check_saved);repeat(4)tick();
        if(host_rsp_valid||memory_ready||job_begin_ready)$fatal(1,"HOST B acknowledged before fence/ECC");
        @(negedge clk);allow_snapshot=1;host_response(0,0,0);cases=cases+1;

        before_aw=aw_count;before_ar=ar_count;
        host_request(1,MODEL_BASE+256,16'h5678);host_response(1,0,0);
        host_request(0,MODEL_BASE+1,0);host_response(1,0,0);
        if(fault||aw_count!=before_aw||ar_count!=before_ar)$fatal(1,"Local error poisoned bus/memory");cases=cases+1;

        @(negedge clk);host_session_busy=1;repeat(3)tick();
        if(memory_ready||job_begin_ready)$fatal(1,"Midpacket job admission");
        @(negedge clk);host_session_busy=0;begin_job();
        engine_request(0,MODEL_BASE+2,0);engine_response(0,16'h1234,1);
        engine_request(1,MODEL_BASE+64,16'hbeef);engine_response(0,0,0);
        before_check=check_count;@(negedge clk);allow_snapshot=0;seal_job();repeat(8)tick();
        if(!job_active||!job_owned||job_retired||retired_count!=0)$fatal(1,"B became job retirement");
        @(negedge clk);allow_snapshot=1;await_retired();
        if(check_count!=before_check+1||!job_owned||job_begin_ready)$fatal(1,"Job fence/RESULT ownership");
        host_request(0,MODEL_BASE+64,0);host_response(0,16'hbeef,1);
        before_aw=aw_count;host_request(1,MODEL_BASE+64,16'hcccc);host_response(1,0,0);
        if(fault||aw_count!=before_aw||!job_owned)$fatal(1,"RESULT write not read-only");
        @(negedge clk);job_release=1;tick();@(negedge clk);job_release=0;
        if(job_owned||!job_begin_ready)$fatal(1,"Successful release did not free ownership");cases=cases+1;

        boot();host_request(0,MODEL_BASE,0);wait(host_rsp_valid);held_data=host_rdata;
        repeat(8)begin tick();if(!host_rsp_valid||host_error||host_rdata!==held_data||job_begin_ready)$fatal(1,"Held HOST response changed/admitted job");end
        host_response(0,0,1);cases=cases+1;

        boot();host_request(0,MODEL_BASE,0);wait(host_rsp_valid);held_data=host_rdata;
        @(negedge clk);monitor_healthy=0;monitor_fault=1;monitor_fault_code=1;expect_fault(5);
        repeat(5)begin tick();if(!host_rsp_valid||host_error||host_rdata!==held_data)$fatal(1,"Fault overwrote held successful response");end

        reset_case();allow_w=0;start_init();wait(aw_count==1);repeat(3)tick();
        if(m_axi_awvalid||!m_axi_wvalid)$fatal(1,"Init AW-first pending handshake lost");
        @(negedge clk);allow_w=1;await_init();cases=cases+1;
        reset_case();allow_aw=0;start_init();wait(w_count==1);repeat(3)tick();
        if(!m_axi_awvalid||m_axi_wvalid)$fatal(1,"Init W-first pending handshake lost");
        @(negedge clk);allow_aw=1;await_init();cases=cases+1;

        boot();begin_job();engine_request(1,MODEL_BASE+256,16'habcd);engine_response(1,0,0);
        @(negedge clk);job_abort=1;expect_fault(5);

        reset_case();allow_aw=0;start_init();expect_fault(8);
        if(!m_axi_awvalid)$fatal(1,"Init timeout cancelled AW");
        @(negedge clk);allow_aw=1;repeat(8)tick();if(init_complete)$fatal(1,"Faulted init completed");

        boot();begin_job();@(negedge clk);allow_r=0;
        engine_request(0,MODEL_BASE,0);wait(ar_saved);@(negedge clk);job_abort=1;expect_fault(5);
        @(negedge clk);allow_r=1;repeat(12)tick();
        if(rvalid||!engine_rsp_valid||!engine_rsp_error)$fatal(1,"Late adapter response not drained after abort");

        boot();begin_job();@(negedge clk);allow_r=0;
        engine_request(0,MODEL_BASE,0);wait(ar_saved);
        @(negedge clk);monitor_healthy=0;#1;
        if(!fault||fault_code!==0||engine_rsp_valid)$fatal(1,"Monitor pending cause not reserved");
        tick();@(negedge clk);monitor_fault=1;monitor_fault_code=3;
        expect_fault(8);if(!engine_rsp_valid)tick();
        if(!engine_rsp_valid||!engine_rsp_error)$fatal(1,"Classified timeout did not fail pending engine request");
        @(negedge clk);allow_r=1;repeat(12)tick();
        if(rvalid)$fatal(1,"Timeout late R not drained");

        boot();begin_job();engine_request(1,MODEL_BASE,16'h4321);engine_response(0,0,0);
        @(negedge clk);allow_ar=0;seal_job();wait(m_axi_arvalid);
        @(negedge clk);calib_complete=0;expect_fault(5);
        if(!m_axi_arvalid)$fatal(1,"Fence fault cancelled AR");
        @(negedge clk);allow_ar=1;repeat(10)tick();if(job_retired||retired_count!=0)$fatal(1,"Faulted fence retired");

        boot();begin_job();seal_job();expect_fault(5);
        boot();@(negedge clk);inject_b=1;expect_fault(5);@(negedge clk);inject_b=0;
        boot();begin_job();@(negedge clk);m_axi_rresp=2;
        engine_request(0,MODEL_BASE,0);expect_fault(5);
        boot();@(negedge clk);monitor_snapshot_status=1;
        host_request(1,MODEL_BASE,16'h7777);expect_fault(5);
        boot();@(negedge clk);allow_snapshot=0;
        host_request(1,MODEL_BASE,16'h8888);expect_fault(8);

`ifndef VERILATOR
        boot();host_request(0,32'hx,0);host_response(1,0,0);if(fault)$fatal(1,"Unknown local address poisoned fabric");cases=cases+1;
        boot();begin_job();@(negedge clk);m_axi_rid=4'bx;
        engine_request(0,MODEL_BASE,0);expect_fault(5);
`endif
        $display("PASS ddr_memory_fabric cases=%0d window_bytes=256 scope=independent_owned_fabric_only",cases);
        $finish;
    end
    initial begin
        if(!FULL_SPAN)begin repeat(15000)tick();$fatal(1,"Fabric bench watchdog");end
    end
endmodule
