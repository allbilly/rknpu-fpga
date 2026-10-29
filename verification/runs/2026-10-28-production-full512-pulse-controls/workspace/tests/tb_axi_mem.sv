`timescale 1ns/1ps
module tb_axi_mem;
    localparam logic [31:0] BASE = 32'h10000000;
    localparam integer WORDS = 524288;
    logic clk;
    initial clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, manual = 1;
    logic mem_req_valid, mem_req_ready, mem_req_write, mem_rsp_valid, mem_rsp_ready, mem_rsp_error;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_req_wdata, mem_rsp_rdata;
    logic u_valid = 0, u_write = 0, u_ready = 0;
    logic [31:0] u_addr = 0;
    logic [15:0] u_data = 0;
    logic d_valid, d_write, d_ready;
    logic [31:0] d_addr;
    logic [15:0] d_data;
    logic start_valid = 0, start_ready, busy, done, task_done, error;
    logic [31:0] start_address = 0, start_amount = 0, completed_tasks;
    logic [7:0] error_code;
    logic [3:0] m_axi_awid, m_axi_arid, m_axi_bid, m_axi_rid;
    logic [30:0] m_axi_awaddr, m_axi_araddr;
    logic [7:0] m_axi_awlen, m_axi_arlen;
    logic [2:0] m_axi_awsize, m_axi_arsize, m_axi_awprot, m_axi_arprot;
    logic [1:0] m_axi_awburst, m_axi_arburst, m_axi_bresp, m_axi_rresp;
    logic m_axi_awlock, m_axi_arlock;
    logic [3:0] m_axi_awcache, m_axi_arcache, m_axi_awqos, m_axi_arqos;
    logic m_axi_awvalid, m_axi_awready, m_axi_wlast, m_axi_wvalid, m_axi_wready;
    logic m_axi_bvalid, m_axi_bready, m_axi_arvalid, m_axi_arready;
    logic m_axi_rlast, m_axi_rvalid, m_axi_rready;
    logic [511:0] m_axi_wdata, m_axi_rdata;
    logic [63:0] m_axi_wstrb;
    rk_axi_mem adapter(.*);
    rk_ew_dma #(.TIMEOUT_CYCLES(128), .MAX_TASKS(4)) dma (
        .clk(clk), .rst_n(rst_n), .start_valid(start_valid), .start_ready(start_ready),
        .start_address(start_address), .start_amount(start_amount), .busy(busy), .done(done),
        .task_done(task_done), .error(error), .completed_tasks(completed_tasks), .error_code(error_code),
        .mem_req_valid(d_valid), .mem_req_ready(mem_req_ready && !manual), .mem_req_write(d_write),
        .mem_req_addr(d_addr), .mem_req_wdata(d_data), .mem_rsp_valid(mem_rsp_valid && !manual),
        .mem_rsp_ready(d_ready), .mem_rsp_rdata(mem_rsp_rdata), .mem_rsp_error(mem_rsp_error)
    );
    assign mem_req_valid = manual ? u_valid : d_valid;
    assign mem_req_write = manual ? u_write : d_write;
    assign mem_req_addr = manual ? u_addr : d_addr;
    assign mem_req_wdata = manual ? u_data : d_data;
    assign mem_rsp_ready = manual ? u_ready : d_ready;

    // Independent byte-strobe RAM slave. AW and W may arrive in either order.
    logic [15:0] memory [0:WORDS-1];
    `include "tests/memory_check.svh"
    integer expected_checks;
    logic [31:0] lfsr;
    logic have_aw, have_w, have_ar;
    logic [30:0] saved_aw, saved_ar;
    logic [511:0] saved_w;
    logic [63:0] saved_strb;
    logic stall_aw = 0, stall_w = 0, stall_ar = 0, drop_b = 0, drop_r = 0;
    logic [1:0] response_code = 0;
    logic [3:0] response_id = 0;
    logic response_last = 1;
    integer aw_count, w_count, ar_count, b_count, r_count, requests, writes, jobs, tasks;
    integer write_delay, read_delay;
    integer fault_mode = 0;
    logic held_aw, held_w, held_ar, held_rsp;
    logic [30:0] old_aw, old_ar;
    logic [575:0] old_w;
    logic [16:0] old_rsp;
    assign m_axi_awready = rst_n && !have_aw && !m_axi_bvalid && !stall_aw && lfsr[0];
    assign m_axi_wready = rst_n && !have_w && !m_axi_bvalid && !stall_w && lfsr[3];
    assign m_axi_arready = rst_n && !have_ar && !m_axi_rvalid && !stall_ar && lfsr[5];
    always @(posedge clk) begin
        if (!rst_n) begin
            lfsr <= 32'h3588a512;
            have_aw <= 0; have_w <= 0; have_ar <= 0;
            saved_aw <= 0; saved_ar <= 0; saved_w <= 0; saved_strb <= 0;
            m_axi_bvalid <= 0; m_axi_rvalid <= 0;
            m_axi_bid <= 0; m_axi_rid <= 0; m_axi_bresp <= 0; m_axi_rresp <= 0;
            m_axi_rdata <= 0; m_axi_rlast <= 0;
            aw_count <= 0; w_count <= 0; ar_count <= 0; b_count <= 0; r_count <= 0;
            requests <= 0; writes <= 0; jobs <= 0; tasks <= 0;
            write_delay <= 0; read_delay <= 0;
            held_aw <= 0; held_w <= 0; held_ar <= 0; held_rsp <= 0;
            old_aw <= 0; old_ar <= 0; old_w <= 0; old_rsp <= 0;
        end else begin
            lfsr <= {lfsr[30:0], lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
            if (m_axi_awid != 0 || m_axi_arid != 0 || m_axi_awlen != 0 || m_axi_arlen != 0 ||
                m_axi_awsize != 6 || m_axi_arsize != 6 || m_axi_awburst != 1 || m_axi_arburst != 1 ||
                m_axi_awlock || m_axi_arlock || m_axi_awcache != 0 || m_axi_arcache != 0 ||
                m_axi_awprot != 0 || m_axi_arprot != 0 || m_axi_awqos != 0 || m_axi_arqos != 0 || !m_axi_wlast)
                $fatal(1, "AXI attributes changed or unsupported");
            if (held_aw && (!m_axi_awvalid || m_axi_awaddr !== old_aw)) $fatal(1, "unstable AW");
            if (held_ar && (!m_axi_arvalid || m_axi_araddr !== old_ar)) $fatal(1, "unstable AR");
            if (held_w && (!m_axi_wvalid || {m_axi_wdata,m_axi_wstrb} !== old_w)) $fatal(1, "unstable W");
            if (held_rsp && (!mem_rsp_valid || {mem_rsp_error,mem_rsp_rdata} !== old_rsp)) $fatal(1, "unstable response");
            held_aw <= m_axi_awvalid && !m_axi_awready; old_aw <= m_axi_awaddr;
            held_ar <= m_axi_arvalid && !m_axi_arready; old_ar <= m_axi_araddr;
            held_w <= m_axi_wvalid && !m_axi_wready; old_w <= {m_axi_wdata,m_axi_wstrb};
            held_rsp <= mem_rsp_valid && !mem_rsp_ready; old_rsp <= {mem_rsp_error,mem_rsp_rdata};
            if (mem_req_valid && mem_req_ready) begin
                requests <= requests + 1;
                if (mem_req_write) writes <= writes + 1;
            end
            if (done) begin
                if (busy || error || have_aw || have_w || have_ar || m_axi_bvalid || m_axi_rvalid)
                    $fatal(1, "premature DMA done");
                jobs <= jobs + 1;
            end
            if (task_done) tasks <= tasks + 1;
            if (m_axi_awvalid && m_axi_awready) begin
                if (m_axi_awaddr[5:0] != 0) $fatal(1, "unaligned AW");
                have_aw <= 1; saved_aw <= m_axi_awaddr; aw_count <= aw_count + 1;
                write_delay <= 3 + int'(lfsr[8:6]);
            end
            if (m_axi_wvalid && m_axi_wready) begin
                if ($countones(m_axi_wstrb) != 2) $fatal(1, "write strobe width");
                have_w <= 1; saved_w <= m_axi_wdata; saved_strb <= m_axi_wstrb; w_count <= w_count + 1;
            end
            if (m_axi_arvalid && m_axi_arready) begin
                if (m_axi_araddr[5:0] != 0) $fatal(1, "unaligned AR");
                have_ar <= 1; saved_ar <= m_axi_araddr; ar_count <= ar_count + 1;
                read_delay <= 3 + int'(lfsr[11:9]);
            end
            if (have_aw && have_w && !drop_b) begin
                if (write_delay != 0) write_delay <= write_delay - 1;
                else begin
                    have_aw <= 0; have_w <= 0; m_axi_bvalid <= 1;
                    m_axi_bid <= response_id;
                    m_axi_bresp <= (fault_mode==4 || (fault_mode==6 && w_count==32)) ? 2'b10 : response_code;
                    if ({1'b0,saved_aw} < BASE || {1'b0,saved_aw} >= BASE+2*WORDS) m_axi_bresp <= 3;
                    else for (integer i=0; i<64; i=i+1)
                        if (saved_strb[i]) memory[((32'(saved_aw)-BASE)>>1)+i/2][8*(i%2) +: 8] <= saved_w[8*i +: 8];
                end
            end
            if (have_ar && !drop_r) begin
                if (read_delay != 0) read_delay <= read_delay - 1;
                else begin
                    have_ar <= 0; m_axi_rvalid <= 1;
                    m_axi_rid <= response_id; m_axi_rresp <= response_code; m_axi_rlast <= response_last;
                    if ({1'b0,saved_ar} < BASE || {1'b0,saved_ar} >= BASE+2*WORDS) begin
                        m_axi_rresp <= 3; m_axi_rdata <= 0;
                    end else for (integer i=0; i<32; i=i+1)
                        m_axi_rdata[16*i +: 16] <= memory[((32'(saved_ar)-BASE)>>1)+i];
                end
            end
            if (m_axi_bvalid && m_axi_bready) begin m_axi_bvalid <= 0; b_count <= b_count + 1; end
            if (m_axi_rvalid && m_axi_rready) begin m_axi_rvalid <= 0; r_count <= r_count + 1; end
        end
    end

    task automatic reset_all;
        @(negedge clk); rst_n=0; u_valid=0; u_ready=0; start_valid=0;
        repeat (3) @(negedge clk);
        if (mem_req_ready || mem_rsp_valid || m_axi_awvalid || m_axi_wvalid || m_axi_arvalid || m_axi_rready || m_axi_bready)
            $fatal(1, "traffic during reset");
        rst_n=1;
    endtask
    task automatic request(input logic wr, input logic [31:0] addr, input logic [15:0] data);
        @(negedge clk); u_valid=1; u_write=wr; u_addr=addr; u_data=data;
        do @(posedge clk); while (!mem_req_ready);
        @(negedge clk); u_valid=0;
    endtask
    task automatic response(input logic fault, input logic [15:0] data, input logic check_data);
        wait (mem_rsp_valid);
        repeat (5) begin
            @(negedge clk);
            if (!mem_rsp_valid || mem_req_ready || mem_rsp_error !== fault ||
                (check_data && mem_rsp_rdata !== data)) $fatal(1, "bad local response");
        end
        u_ready=1;
        @(negedge clk); u_ready=0;
        if (fault) begin
            u_valid=1;
            repeat (5) begin
                @(negedge clk);
                if (mem_req_ready || mem_rsp_valid || m_axi_awvalid || m_axi_wvalid || m_axi_arvalid || m_axi_rready || m_axi_bready)
                    $fatal(1, "adapter fault not sticky");
            end
            u_valid=0;
        end
    endtask
    task automatic transfer(input logic wr, input logic [31:0] addr, input logic [15:0] data);
        request(wr,addr,data); response(0,data,!wr);
        if (wr && memory[(addr-BASE)>>1] !== data) $fatal(1,"wrong physical write lane");
    endtask
    string prefix, output_path;
    integer expected_tasks, expected_transactions;
    initial begin
        for (integer i=0; i<WORDS; i=i+1) memory[i]=16'ha55a;
        reset_all();
        if ($value$plusargs("CASE=%s",prefix)) begin
            if (!$value$plusargs("NCHECKS=%d",expected_checks)) $fatal(1,"missing NCHECKS");
            if (!$value$plusargs("START=%h",start_address) || !$value$plusargs("AMOUNT=%d",start_amount) ||
                !$value$plusargs("NTASKS=%d",expected_tasks) || !$value$plusargs("NTRANS=%d",expected_transactions))
                $fatal(1, "missing DMA case metadata");
            if (!$value$plusargs("OUTPUT=%s",output_path)) $fatal(1,"missing OUTPUT");
            if (!$value$plusargs("FAULT=%d",fault_mode)) fault_mode=0;
            $readmemh({prefix,"/input.hex"},memory);
            manual=0;
            if (fault_mode==1) response_code=2;
            if (fault_mode==2) drop_r=1;
            if (fault_mode==3) stall_ar=1;
            if (fault_mode==5) drop_b=1;
            @(negedge clk); start_valid=1;
            do @(posedge clk); while (!start_ready);
            @(negedge clk); start_valid=0;
            wait (jobs==1 || error);
            repeat (3) @(negedge clk);
            if (fault_mode!=0) begin
                if (!error || error_code != ((fault_mode==1 || fault_mode==4 || fault_mode==6) ? 5 : 8) ||
                    completed_tasks!=(fault_mode==6 ? 1 : 0) || jobs!=0)
                    $fatal(1,"DMA AXI fault propagation code=%0d",error_code);
                if (fault_mode==3 && !m_axi_arvalid) $fatal(1,"timeout illegally cancelled AXI AR");
                reset_all();
                if (error || busy || completed_tasks!=0) $fatal(1,"DMA reset failed");
                $display("PASS axi_dma fault=%0d propagated and joint reset",fault_mode);
            end else begin
                if (error || jobs!=1 || tasks!=expected_tasks || completed_tasks!=32'(expected_tasks) || requests!=expected_transactions)
                    $fatal(1,"DMA AXI completion/count mismatch error=%0d jobs=%0d tasks=%0d requests=%0d",error_code,jobs,tasks,requests);
                if (aw_count!=writes || w_count!=writes || b_count!=writes || ar_count!=requests-writes || r_count!=ar_count)
                    $fatal(1,"AXI request/response counts disagree");
                verify_memory({prefix,"/check.txt"},output_path,expected_checks);
                $display("PASS axi_dma %s tasks=%0d requests=%0d writes=%0d full-memory comparison",prefix,tasks,requests,writes);
            end
        end else begin
            // All lanes, adjacent beat and 4 KiB boundaries; untouched bytes survive.
            for (integer i=0; i<96; i=i+1) transfer(1,BASE+32'(2*i),16'(16'h1200+i));
            for (integer i=0; i<96; i=i+1) transfer(0,BASE+32'(2*i),16'(16'h1200+i));
            transfer(1,BASE+4094,16'h1234); transfer(1,BASE+4096,16'h5678);
            transfer(0,BASE+4094,16'h1234); transfer(0,BASE+4096,16'h5678);
            transfer(0,BASE+4092,16'ha55a); transfer(0,BASE+4098,16'ha55a);
            // Explicit AW-before-W, W-before-AW, and delayed B acknowledgment.
            stall_w=1; request(1,BASE+256,16'habcd);
            wait(have_aw); repeat(9) @(negedge clk);
            if (mem_rsp_valid || !m_axi_wvalid || m_axi_awvalid) $fatal(1,"AW-only ordering");
            stall_w=0; response(0,0,0);
            stall_aw=1; request(1,BASE+258,16'hdcba);
            wait(have_w); repeat(9) @(negedge clk);
            if (mem_rsp_valid || !m_axi_awvalid || m_axi_wvalid) $fatal(1,"W-only ordering");
            stall_aw=0; response(0,0,0);
            drop_b=1; request(1,BASE+260,16'h7777);
            wait(have_aw && have_w); repeat(15) @(negedge clk);
            if (mem_rsp_valid || !m_axi_bready) $fatal(1,"write completed before B");
            drop_b=0; response(0,0,0);
            transfer(0,BASE+256,16'habcd); transfer(0,BASE+258,16'hdcba); transfer(0,BASE+260,16'h7777);
            // Full-beat address at the 2 GiB edge is issued without wrapping;
            // this test RAM returns DECERR because the location is not mapped.
            reset_all(); request(0,32'h7ffffffe,0); response(1,0,0);
            if (ar_count!=1 || saved_ar!=31'h7fffffc0) $fatal(1,"top address truncated");
            for (integer i=0; i<4; i=i+1) begin
                reset_all(); request(i[0],i<2 ? BASE+1 : 32'h80000000,0); response(1,0,0);
                if (aw_count!=0 || w_count!=0 || ar_count!=0) $fatal(1,"invalid address reached AXI");
            end
            for (integer wr=0; wr<2; wr=wr+1) begin
                for (integer code=1; code<4; code=code+1) begin
                    reset_all(); response_code=2'(code); request(wr[0],BASE,0); response(1,0,0);
                end
                reset_all(); response_code=0; response_id=4'hf;
                request(wr[0],BASE,0); response(1,0,0); response_id=0;
            end
            reset_all(); response_last=0; request(0,BASE,0); response(1,0,0); response_last=1;
            // Joint reset at each externally pending boundary. RAM is not rolled back.
            for (integer phase=0; phase<6; phase=phase+1) begin
                reset_all();
                stall_aw=(phase==0); stall_w=(phase==1); drop_b=(phase==2);
                stall_ar=(phase==3); drop_r=(phase==4);
                request(phase<3,BASE+512,16'h99aa);
                if (phase==0) wait(have_w);
                if (phase==1) wait(have_aw);
                if (phase==2) wait(have_aw && have_w);
                if (phase==3) wait(m_axi_arvalid);
                if (phase==4) wait(have_ar);
                if (phase==5) wait(mem_rsp_valid);
                repeat(5) @(negedge clk);
                reset_all(); stall_aw=0; stall_w=0; drop_b=0; stall_ar=0; drop_r=0;
                repeat(10) @(negedge clk);
                if (mem_rsp_valid || requests!=0 || aw_count!=0 || w_count!=0 || ar_count!=0) $fatal(1,"stale transaction after reset");
                transfer(1,BASE+514,16'h8899); transfer(0,BASE+514,16'h8899);
            end
            $display("PASS axi_mem lanes, boundaries, strobes, independent channels, backpressure, faults and six reset phases");
        end
        $finish;
    end
    initial begin #5000000; $fatal(1,"AXI bench global timeout"); end
endmodule
