// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exclusive C0 memory owner beneath unchanged raw-QWORD computation. The full
// configured span is initialized by full-strobe hardware writes, then fenced.
// HOST writes retire individually; JOB writes retire at an actual-history seal.
// Actual MC variant/profile and whole-domain reset/CDC obligations are external;
// this source component does not establish physical DDR or RK equivalence.
module rk_ddr_memory_fabric_snapshot #(
    parameter logic [31:0] BASE = 0,
    parameter logic [32:0] BYTES = 33'h080000000,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, joint_rst_n, sequence_ready, calib_complete,
    input logic monitor_healthy, monitor_fault,
    input logic [7:0] monitor_fault_code,
    input logic host_session_busy,
    input logic host_read_scope,
    input logic [15:0] host_read_epoch,
    input logic host_valid,
    output logic host_ready,
    input logic host_write,
    input logic [31:0] host_addr,
    input logic [15:0] host_wdata,
    output logic host_rsp_valid,
    input logic host_rsp_ready,
    output logic [15:0] host_rdata,
    output logic host_error,
    input logic engine_req_valid,
    output logic engine_req_ready,
    input logic engine_req_write,
    input logic [31:0] engine_req_addr,
    input logic [15:0] engine_req_wdata,
    output logic engine_rsp_valid,
    input logic engine_rsp_ready,
    output logic [15:0] engine_rsp_rdata,
    output logic engine_rsp_error,
    input logic job_begin,
    output logic job_begin_ready,
    input logic job_seal, job_abort, job_release,
    output logic init_complete, init_active, memory_ready,
    output logic job_owned, job_active, job_retired,
    output logic fault,
    output logic [7:0] fault_code,
    output logic monitor_check_valid,
    input logic monitor_check_ready,
    input logic monitor_snapshot_valid,
    output logic monitor_snapshot_ready,
    input logic [31:0] monitor_snapshot_status, monitor_snapshot_onoff, monitor_snapshot_irq_mask,
    output logic [3:0] m_axi_awid, m_axi_arid,
    output logic [30:0] m_axi_awaddr, m_axi_araddr,
    output logic [7:0] m_axi_awlen, m_axi_arlen,
    output logic [2:0] m_axi_awsize, m_axi_arsize,
    output logic [1:0] m_axi_awburst, m_axi_arburst,
    output logic m_axi_awlock, m_axi_arlock,
    output logic [3:0] m_axi_awcache, m_axi_arcache,
    output logic [2:0] m_axi_awprot, m_axi_arprot,
    output logic [3:0] m_axi_awqos, m_axi_arqos,
    output logic m_axi_awvalid,
    input logic m_axi_awready,
    output logic [511:0] m_axi_wdata,
    output logic [63:0] m_axi_wstrb,
    output logic m_axi_wlast, m_axi_wvalid,
    input logic m_axi_wready,
    input logic [3:0] m_axi_bid,
    input logic [1:0] m_axi_bresp,
    input logic m_axi_bvalid,
    output logic m_axi_bready,
    output logic m_axi_arvalid,
    input logic m_axi_arready,
    input logic [3:0] m_axi_rid,
    input logic [511:0] m_axi_rdata,
    input logic [1:0] m_axi_rresp,
    input logic m_axi_rlast, m_axi_rvalid,
    output logic m_axi_rready
);
    localparam logic [32:0] END_ADDRESS = {1'b0,BASE}+BYTES;
    typedef enum logic [3:0] {WAIT_START, INITIALIZE, FENCE_START, FENCE_WAIT,
                              HOST, JOB, RESULT, QUARANTINE} state_t;
    typedef enum logic [1:0] {BUS_NONE, BUS_INIT, BUS_ADAPTER, BUS_FENCE} bus_t;
    typedef enum logic [1:0] {FENCE_INIT, FENCE_HOST, FENCE_JOB} fence_t;
    typedef enum logic [1:0] {NO_REQUEST, HOST_REQUEST, ENGINE_REQUEST} requester_t;
    state_t state;
    bus_t bus_owner;
    fence_t fence_reason;
    requester_t requester;
    logic service_active, latched_fault, monitor_gap_pending, seal_seen, release_seen;
    logic [7:0] saved_fault_code, cause_now;
    logic fault_now, monitor_gap, health_good, retire_pulse;
    logic [31:0] stalled_cycles;
    logic timeout_enabled, progress;
    logic init_aw_pending, init_w_pending, init_outstanding;
    logic [31:0] init_address;
    logic [30:0] init_bus_address;
    logic relay_pending, adapter_waiting, request_live, response_sent, request_write;
    logic [31:0] request_address;
    logic [15:0] request_data;
    logic request_accept, host_accept, engine_accept, bad_request;
    logic aw_seen, w_seen, read_seen, record_epoch;
    logic [31:0] active_aw_address, last_completed_aw;
    logic [31:0] aw_count, w_count, b_count, ar_count, r_count;
    logic producer_quiet, writes_finished, protocol_bad, controls_bad;
    logic aw_take, w_take, b_take, ar_take, r_take;
    logic fence_request_pending, fence_ready, unused_fence_result_valid, fence_result_ready, fence_done;
    logic fence_fault;
    logic [7:0] fence_fault_code;
    logic fence_sealed, host_below_base, engine_below_base;
    logic host_response_pending, engine_response_pending;

    logic a_req_ready, a_rsp_valid, a_rsp_ready, a_rsp_error;
    logic [15:0] a_rsp_data;
    logic [3:0] a_awid, a_arid, a_awcache, a_arcache, a_awqos, a_arqos;
    logic [30:0] a_awaddr, a_araddr;
    logic [7:0] a_awlen, a_arlen;
    logic [2:0] a_awsize, a_arsize, a_awprot, a_arprot;
    logic [1:0] a_awburst, a_arburst;
    logic a_awlock, a_arlock, a_awvalid, a_awready, a_wlast, a_wvalid, a_wready;
    logic a_bvalid, a_bready, a_arvalid, a_arready, a_rlast, a_rvalid, a_rready;
    logic [511:0] a_wdata;
    logic [63:0] a_wstrb;
    logic [3:0] f_arid, f_arcache, f_arqos;
    logic [30:0] f_araddr;
    logic [7:0] f_arlen;
    logic [2:0] f_arsize, f_arprot;
    logic [1:0] f_arburst;
    logic f_arlock, f_arvalid, f_arready, f_rvalid, f_rready;

    initial begin
        if ((^BASE) === 1'bx || (^BYTES) === 1'bx || BASE[31] || BASE[5:0] != 0 ||
                BYTES < 64 || BYTES > 33'h080000000 || BYTES[5:0] != 0 ||
                END_ADDRESS > 33'h080000000 || TIMEOUT_CYCLES == 0)
            $fatal(1,"DDR fabric needs aligned nonempty C0 span and positive timeout");
    end

    rk_axi_mem_read_snapshot adapter (
        .host_read_scope(host_read_scope),.host_read_epoch(host_read_epoch),
        .request_is_host(requester==HOST_REQUEST),
        .invalidate_snapshot(!health_good||fault||!init_complete||aw_take),
        .clk(clk),.rst_n(joint_rst_n),.mem_req_valid(relay_pending),.mem_req_ready(a_req_ready),
        .mem_req_write(request_write),.mem_req_addr(request_address),.mem_req_wdata(request_data),
        .mem_rsp_valid(a_rsp_valid),.mem_rsp_ready(a_rsp_ready),.mem_rsp_rdata(a_rsp_data),.mem_rsp_error(a_rsp_error),
        .m_axi_awid(a_awid),.m_axi_arid(a_arid),.m_axi_awaddr(a_awaddr),.m_axi_araddr(a_araddr),
        .m_axi_awlen(a_awlen),.m_axi_arlen(a_arlen),.m_axi_awsize(a_awsize),.m_axi_arsize(a_arsize),
        .m_axi_awburst(a_awburst),.m_axi_arburst(a_arburst),.m_axi_awlock(a_awlock),.m_axi_arlock(a_arlock),
        .m_axi_awcache(a_awcache),.m_axi_arcache(a_arcache),.m_axi_awprot(a_awprot),.m_axi_arprot(a_arprot),
        .m_axi_awqos(a_awqos),.m_axi_arqos(a_arqos),.m_axi_awvalid(a_awvalid),.m_axi_awready(a_awready),
        .m_axi_wdata(a_wdata),.m_axi_wstrb(a_wstrb),.m_axi_wlast(a_wlast),.m_axi_wvalid(a_wvalid),.m_axi_wready(a_wready),
        .m_axi_bid(m_axi_bid),.m_axi_bresp(m_axi_bresp),.m_axi_bvalid(a_bvalid),.m_axi_bready(a_bready),
        .m_axi_arvalid(a_arvalid),.m_axi_arready(a_arready),.m_axi_rid(m_axi_rid),.m_axi_rdata(m_axi_rdata),
        .m_axi_rresp(m_axi_rresp),.m_axi_rlast(a_rlast),.m_axi_rvalid(a_rvalid),.m_axi_rready(a_rready)
    );
    assign a_rsp_ready = joint_rst_n && (adapter_waiting || latched_fault);
    assign a_awready = bus_owner == BUS_ADAPTER && m_axi_awready;
    assign a_wready = bus_owner == BUS_ADAPTER && m_axi_wready;
    assign a_bvalid = bus_owner == BUS_ADAPTER && m_axi_bvalid;
    assign a_arready = bus_owner == BUS_ADAPTER && m_axi_arready;
    assign a_rvalid = bus_owner == BUS_ADAPTER && m_axi_rvalid;
    assign a_rlast = m_axi_rlast;

    assign producer_quiet = !relay_pending && !adapter_waiting && !init_aw_pending &&
        !init_w_pending && !init_outstanding && !aw_seen && !w_seen && ar_count == r_count;
    assign writes_finished = producer_quiet && aw_count != 0 && aw_count == w_count && aw_count == b_count;
    assign fence_sealed = bus_owner == BUS_FENCE;
    assign fence_result_ready = joint_rst_n && (state == FENCE_WAIT || latched_fault);
    rk_mig_write_fence #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) fence (
        .clk(clk),.joint_rst_n(joint_rst_n),.fence_valid(fence_request_pending),.fence_ready(fence_ready),
        .final_write_address(last_completed_aw),.epoch_has_write(b_count != 0),
        .epoch_sealed(fence_sealed),.writes_complete(writes_finished),.upstream_quiescent(producer_quiet),
        .owner_exclusive(fence_sealed),.calib_complete(calib_complete),.monitor_healthy(monitor_healthy),
        .monitor_fault(monitor_fault),.fence_result_valid(unused_fence_result_valid),.fence_result_ready(fence_result_ready),
        .fence_done(fence_done),.fault(fence_fault),.fault_code(fence_fault_code),
        .m_axi_arid(f_arid),.m_axi_araddr(f_araddr),.m_axi_arlen(f_arlen),.m_axi_arsize(f_arsize),
        .m_axi_arburst(f_arburst),.m_axi_arlock(f_arlock),.m_axi_arcache(f_arcache),.m_axi_arprot(f_arprot),
        .m_axi_arqos(f_arqos),.m_axi_arvalid(f_arvalid),.m_axi_arready(f_arready),.m_axi_rid(m_axi_rid),
        .m_axi_rresp(m_axi_rresp),.m_axi_rlast(m_axi_rlast),.m_axi_rvalid(f_rvalid),.m_axi_rready(f_rready),
        .monitor_check_valid(monitor_check_valid),.monitor_check_ready(monitor_check_ready),
        .monitor_snapshot_valid(monitor_snapshot_valid),.monitor_snapshot_ready(monitor_snapshot_ready),
        .monitor_snapshot_status(monitor_snapshot_status),.monitor_snapshot_onoff(monitor_snapshot_onoff),
        .monitor_snapshot_irq_mask(monitor_snapshot_irq_mask)
    );
    assign f_arready = bus_owner == BUS_FENCE && m_axi_arready;
    assign f_rvalid = bus_owner == BUS_FENCE && m_axi_rvalid;
    if(BASE==0)begin: zero_base
        assign host_below_base=0;
        assign engine_below_base=0;
    end else begin: nonzero_base
        assign host_below_base={1'b0,host_addr}<{1'b0,BASE};
        assign engine_below_base={1'b0,engine_req_addr}<{1'b0,BASE};
    end
    assign host_rsp_valid=joint_rst_n&&host_response_pending;
    assign engine_rsp_valid=joint_rst_n&&engine_response_pending;
    assign init_bus_address=init_address[30:0];

    always_comb begin
        m_axi_awid=0;m_axi_awaddr=init_bus_address;m_axi_awlen=0;m_axi_awsize=6;m_axi_awburst=1;
        m_axi_awlock=0;m_axi_awcache=0;m_axi_awprot=0;m_axi_awqos=0;m_axi_awvalid=0;
        m_axi_wdata=0;m_axi_wstrb=64'hffff_ffff_ffff_ffff;m_axi_wlast=1;m_axi_wvalid=0;m_axi_bready=0;
        m_axi_arid=0;m_axi_araddr=0;m_axi_arlen=0;m_axi_arsize=6;m_axi_arburst=1;
        m_axi_arlock=0;m_axi_arcache=0;m_axi_arprot=0;m_axi_arqos=0;m_axi_arvalid=0;m_axi_rready=0;
        case(bus_owner)
            BUS_INIT: begin
                m_axi_awvalid=joint_rst_n&&init_aw_pending;m_axi_wvalid=joint_rst_n&&init_w_pending;
                m_axi_bready=joint_rst_n&&init_outstanding&&!init_aw_pending&&!init_w_pending;
            end
            BUS_ADAPTER: begin
                m_axi_awid=a_awid;m_axi_awaddr=a_awaddr;m_axi_awlen=a_awlen;m_axi_awsize=a_awsize;
                m_axi_awburst=a_awburst;m_axi_awlock=a_awlock;m_axi_awcache=a_awcache;
                m_axi_awprot=a_awprot;m_axi_awqos=a_awqos;m_axi_awvalid=a_awvalid;
                m_axi_wdata=a_wdata;m_axi_wstrb=a_wstrb;m_axi_wlast=a_wlast;m_axi_wvalid=a_wvalid;
                m_axi_bready=a_bready;m_axi_arid=a_arid;m_axi_araddr=a_araddr;m_axi_arlen=a_arlen;
                m_axi_arsize=a_arsize;m_axi_arburst=a_arburst;m_axi_arlock=a_arlock;
                m_axi_arcache=a_arcache;m_axi_arprot=a_arprot;m_axi_arqos=a_arqos;
                m_axi_arvalid=a_arvalid;m_axi_rready=a_rready;
            end
            BUS_FENCE: begin
                m_axi_arid=f_arid;m_axi_araddr=f_araddr;m_axi_arlen=f_arlen;m_axi_arsize=f_arsize;
                m_axi_arburst=f_arburst;m_axi_arlock=f_arlock;m_axi_arcache=f_arcache;
                m_axi_arprot=f_arprot;m_axi_arqos=f_arqos;m_axi_arvalid=f_arvalid;m_axi_rready=f_rready;
            end
            default: begin end
        endcase
        // Quarantine drains external responses even if the old adapter cannot
        // attribute an invalid/late beat. Its asserted request paths stay owned.
        if(latched_fault&&joint_rst_n)begin m_axi_bready=1;m_axi_rready=1;end
    end
    assign aw_take=m_axi_awvalid&&m_axi_awready;
    assign w_take=m_axi_wvalid&&m_axi_wready;
    assign b_take=m_axi_bvalid&&m_axi_bready;
    assign ar_take=m_axi_arvalid&&m_axi_arready;
    assign r_take=m_axi_rvalid&&m_axi_rready;

    assign health_good=sequence_ready===1'b1&&calib_complete===1'b1&&
        monitor_healthy===1'b1&&monitor_fault===1'b0;
    assign monitor_gap=service_active&&sequence_ready===1'b1&&calib_complete===1'b1&&
        monitor_healthy!==1'b1&&monitor_fault===1'b0;
    assign fault=latched_fault||fault_now;
    assign fault_code=(latched_fault&&saved_fault_code!=0)?saved_fault_code:cause_now;
    assign memory_ready=joint_rst_n&&init_complete&&health_good&&!fault&&
        host_session_busy===1'b0&&!(request_live&&requester==HOST_REQUEST)&&!host_rsp_valid;
    assign init_active=joint_rst_n&&!init_complete&&!fault;
    assign job_begin_ready=memory_ready&&state==HOST&&!request_live&&!relay_pending&&!adapter_waiting&&
        !engine_rsp_valid&&host_valid===1'b0;
    assign host_ready=joint_rst_n&&init_complete&&health_good&&!fault&&
        (state==HOST||state==RESULT)&&!request_live&&!relay_pending&&!adapter_waiting&&
        !host_rsp_valid&&!engine_rsp_valid&&!(job_begin&&job_begin_ready);
    assign engine_req_ready=joint_rst_n&&state==JOB&&job_owned&&health_good&&!fault&&
        !request_live&&!relay_pending&&!adapter_waiting&&!engine_rsp_valid&&!host_rsp_valid;
    assign host_accept=host_valid&&host_ready;
    assign engine_accept=engine_req_valid&&engine_req_ready;
    assign request_accept=host_accept||engine_accept;
    assign bad_request=host_accept?((^host_addr)===1'bx||host_addr[0]!==1'b0||host_addr[31]!==1'b0||
        host_below_base||({1'b0,host_addr}+33'd2)>END_ADDRESS||
        (host_write!==1'b0&&host_write!==1'b1)||(host_write&&(^host_wdata)===1'bx)||
        (state==RESULT&&host_write!==1'b0)):
        ((^engine_req_addr)===1'bx||engine_req_addr[0]!==1'b0||engine_req_addr[31]!==1'b0||
        engine_below_base||({1'b0,engine_req_addr}+33'd2)>END_ADDRESS||
        (engine_req_write!==1'b0&&engine_req_write!==1'b1)||
        (engine_req_write&&(^engine_req_wdata)===1'bx));
    assign job_retired=joint_rst_n&&retire_pulse&&health_good&&!fault;

    always_comb begin
        protocol_bad=0;
        if(service_active)begin
            if(m_axi_bvalid!==1'b0&&(m_axi_bvalid!==1'b1||!aw_seen||!w_seen||
                m_axi_bid!==0||m_axi_bresp!==0))protocol_bad=1;
            if(m_axi_rvalid!==1'b0&&(m_axi_rvalid!==1'b1||!read_seen||
                m_axi_rid!==0||m_axi_rresp!==0||m_axi_rlast!==1'b1))protocol_bad=1;
            if(aw_take&&(aw_seen||read_seen||aw_count==32'hffff_ffff))protocol_bad=1;
            if(w_take&&(w_seen||read_seen||w_count==32'hffff_ffff))protocol_bad=1;
            if(ar_take&&(read_seen||aw_seen||w_seen||ar_count==32'hffff_ffff))protocol_bad=1;
            if(a_rsp_valid&&a_rsp_ready&&(a_rsp_error!==1'b0||
                (!request_write&&(^a_rsp_data)===1'bx)))protocol_bad=1;
        end
        controls_bad=0;
        if(service_active)begin
            if((job_begin!==1'b0&&job_begin!==1'b1)||(job_abort!==1'b0&&job_abort!==1'b1)||
                (job_seal!==1'b0&&job_seal!==1'b1)||(job_release!==1'b0&&job_release!==1'b1))controls_bad=1;
            if(job_seal&&!seal_seen&&(state!=JOB||!job_owned||request_live||relay_pending||adapter_waiting||
                engine_rsp_valid||host_rsp_valid||engine_req_valid!==1'b0||!writes_finished||read_seen))controls_bad=1;
            if(job_release&&!release_seen&&(state!=RESULT||!job_owned||request_live||relay_pending||adapter_waiting||
                host_rsp_valid||host_session_busy!==1'b0||host_valid!==1'b0))controls_bad=1;
        end
        progress=aw_take||w_take||b_take||ar_take||r_take||
            (relay_pending&&a_req_ready)||(a_rsp_valid&&a_rsp_ready)||
            (fence_request_pending&&fence_ready)||(monitor_check_valid&&monitor_check_ready)||
            (monitor_snapshot_valid&&monitor_snapshot_ready);
        timeout_enabled=init_outstanding||relay_pending||adapter_waiting||fence_request_pending;
        cause_now=0;fault_now=0;
        if(monitor_fault!==1'b0)begin
            fault_now=1;cause_now=(monitor_fault===1'b1&&monitor_fault_code===8'd3)?8'd8:8'd5;
        end else if(service_active&&(sequence_ready!==1'b1||calib_complete!==1'b1))begin
            fault_now=1;cause_now=8'd5;
        end else if(monitor_gap||monitor_gap_pending)begin
            fault_now=1;cause_now=monitor_gap_pending?8'd5:8'd0;
        end else if(job_abort!==1'b0)begin fault_now=1;cause_now=8'd5;
        end else if(protocol_bad||controls_bad)begin fault_now=1;cause_now=8'd5;
        end else if(timeout_enabled&&!progress&&stalled_cycles>=TIMEOUT_CYCLES-1)begin
            fault_now=1;cause_now=8'd8;
        end else if(fence_fault)begin fault_now=1;cause_now=fence_fault_code==6?8'd8:8'd5;end
    end

    always_ff @(posedge clk) begin
        if(!joint_rst_n)begin
            state<=WAIT_START;bus_owner<=BUS_NONE;fence_reason<=FENCE_INIT;requester<=NO_REQUEST;
            service_active<=0;latched_fault<=0;monitor_gap_pending<=0;seal_seen<=0;release_seen<=0;
            saved_fault_code<=0;stalled_cycles<=0;
            init_aw_pending<=0;init_w_pending<=0;init_outstanding<=0;init_address<=BASE;
            relay_pending<=0;adapter_waiting<=0;request_live<=0;response_sent<=0;request_write<=0;
            request_address<=0;request_data<=0;record_epoch<=0;aw_seen<=0;w_seen<=0;read_seen<=0;
            active_aw_address<=0;last_completed_aw<=0;aw_count<=0;w_count<=0;b_count<=0;ar_count<=0;r_count<=0;
            fence_request_pending<=0;init_complete<=0;job_owned<=0;job_active<=0;retire_pulse<=0;
            host_response_pending<=0;host_rdata<=0;host_error<=0;
            engine_response_pending<=0;engine_rsp_rdata<=0;engine_rsp_error<=0;
        end else begin
            retire_pulse<=0;
            if(job_seal===1'b0)seal_seen<=0;
            if(job_release===1'b0)release_seen<=0;
            if(!timeout_enabled||progress)stalled_cycles<=0;
            else if(stalled_cycles<TIMEOUT_CYCLES-1)stalled_cycles<=stalled_cycles+1;
            if(aw_take)begin aw_seen<=1;active_aw_address<={1'b0,m_axi_awaddr};if(record_epoch&&bus_owner!=BUS_FENCE)aw_count<=aw_count+1;end
            if(w_take)begin w_seen<=1;if(record_epoch&&bus_owner!=BUS_FENCE)w_count<=w_count+1;end
            if(b_take&&aw_seen&&w_seen)begin
                aw_seen<=0;w_seen<=0;
                if(record_epoch&&bus_owner!=BUS_FENCE)begin b_count<=b_count+1;last_completed_aw<=active_aw_address;end
            end
            if(ar_take)begin read_seen<=1;if(record_epoch&&bus_owner!=BUS_FENCE)ar_count<=ar_count+1;end
            if(r_take&&read_seen&&m_axi_rlast===1'b1)begin
                read_seen<=0;if(record_epoch&&bus_owner!=BUS_FENCE)r_count<=r_count+1;
            end
            if(bus_owner==BUS_INIT)begin
                if(aw_take)init_aw_pending<=0;
                if(w_take)init_w_pending<=0;
                if(b_take&&aw_seen&&w_seen)init_outstanding<=0;
            end
            if(relay_pending&&a_req_ready)begin relay_pending<=0;adapter_waiting<=1;end
            if(a_rsp_valid&&a_rsp_ready)adapter_waiting<=0;
            if(fence_request_pending&&fence_ready)fence_request_pending<=0;
            if(host_rsp_valid&&host_rsp_ready)begin host_response_pending<=0;request_live<=0;response_sent<=0;end
            if(engine_rsp_valid&&engine_rsp_ready)begin engine_response_pending<=0;request_live<=0;response_sent<=0;end

            if(fault_now&&!latched_fault)begin
                latched_fault<=1;saved_fault_code<=cause_now;monitor_gap_pending<=monitor_gap&&cause_now==0;
                state<=QUARANTINE;init_complete<=0;
            end else if(latched_fault&&saved_fault_code==0&&cause_now!=0)begin
                saved_fault_code<=cause_now;monitor_gap_pending<=0;
            end
            // An error response does not claim that late side effects retired.
            // Existing held responses are never overwritten by a later fault.
            if(fault&&fault_code!=0&&request_live&&!response_sent)begin
                if(requester==HOST_REQUEST)begin host_response_pending<=1;host_error<=1;host_rdata<=0;end
                else if(requester==ENGINE_REQUEST)begin engine_response_pending<=1;engine_rsp_error<=1;engine_rsp_rdata<=0;end
                response_sent<=1;
            end

            if(!fault)begin
                if(request_accept)begin
                    if(host_accept)requester<=HOST_REQUEST;else requester<=ENGINE_REQUEST;
                    request_live<=1;response_sent<=0;
                    request_write<=host_accept?host_write:engine_req_write;
                    request_address<=host_accept?host_addr:engine_req_addr;
                    request_data<=host_accept?host_wdata:engine_req_wdata;
                    if(bad_request)begin
                        if(host_accept)begin host_response_pending<=1;host_error<=1;host_rdata<=0;end
                        else begin engine_response_pending<=1;engine_rsp_error<=1;engine_rsp_rdata<=0;end
                        response_sent<=1;
                    end else begin
                        relay_pending<=1;bus_owner<=BUS_ADAPTER;
                        if(host_accept&&host_write)begin
                            record_epoch<=1;aw_count<=0;w_count<=0;b_count<=0;ar_count<=0;r_count<=0;last_completed_aw<=0;
                        end
                    end
                end
                if(a_rsp_valid&&a_rsp_ready&&adapter_waiting)begin
                    if(requester==HOST_REQUEST&&request_write)begin
                        state<=FENCE_START;fence_reason<=FENCE_HOST;bus_owner<=BUS_FENCE;fence_request_pending<=1;
                    end else begin
                        if(requester==HOST_REQUEST)begin host_response_pending<=1;host_error<=0;host_rdata<=a_rsp_data;end
                        else begin engine_response_pending<=1;engine_rsp_error<=0;engine_rsp_rdata<=a_rsp_data;end
                        response_sent<=1;bus_owner<=BUS_NONE;
                    end
                end
                case(state)
                    WAIT_START: if(health_good)begin
                        service_active<=1;init_address<=BASE;init_aw_pending<=1;init_w_pending<=1;init_outstanding<=1;
                        record_epoch<=1;aw_count<=0;w_count<=0;b_count<=0;ar_count<=0;r_count<=0;
                        state<=INITIALIZE;bus_owner<=BUS_INIT;
                    end
                    INITIALIZE: if(b_take&&aw_seen&&w_seen)begin
                        if(({1'b0,init_address}+33'd64)==END_ADDRESS)begin
                            bus_owner<=BUS_FENCE;fence_reason<=FENCE_INIT;fence_request_pending<=1;state<=FENCE_START;
                        end else begin
                            init_address<=init_address+64;init_aw_pending<=1;init_w_pending<=1;init_outstanding<=1;
                        end
                    end
                    FENCE_START: if(fence_request_pending&&fence_ready)state<=FENCE_WAIT;
                    FENCE_WAIT: if(fence_done)begin
                        bus_owner<=BUS_NONE;record_epoch<=0;
                        case(fence_reason)
                            FENCE_INIT:begin init_complete<=1;state<=HOST;end
                            FENCE_HOST:begin
                                host_response_pending<=1;host_error<=0;host_rdata<=0;response_sent<=1;
                                if(job_owned)state<=RESULT;else state<=HOST;
                            end
                            FENCE_JOB:begin retire_pulse<=1;job_active<=0;state<=RESULT;end
                            default:begin end
                        endcase
                    end
                    HOST:if(job_begin&&job_begin_ready)begin
                        job_owned<=1;job_active<=1;state<=JOB;record_epoch<=1;
                        aw_count<=0;w_count<=0;b_count<=0;ar_count<=0;r_count<=0;last_completed_aw<=0;
                    end
                    JOB:if(job_seal&&!seal_seen)begin
                        seal_seen<=1;
                        state<=FENCE_START;fence_reason<=FENCE_JOB;bus_owner<=BUS_FENCE;fence_request_pending<=1;
                    end
                    RESULT:if(job_release&&!release_seen)begin release_seen<=1;job_owned<=0;state<=HOST;end
                    QUARANTINE:begin end
                    default:begin end
                endcase
            end
        end
    end
endmodule
