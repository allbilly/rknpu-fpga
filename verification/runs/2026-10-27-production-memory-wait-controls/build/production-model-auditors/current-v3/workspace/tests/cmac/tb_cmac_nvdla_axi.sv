`timescale 1ns/1ps
module tb_cmac_nvdla_axi;
    localparam logic [31:0] BASE=32'h10000000;
    localparam integer WORDS=524288;
    logic clk;
    initial clk=0;
    always #5 clk=~clk;
    logic rst_n=0, memory_ready=0, irq;
    `include "tests/axil_host.svh"
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
    rk_cmac_nvdla_axi #(.TIMEOUT_CYCLES(128)) dut(.*);

    logic [15:0] memory [0:WORDS-1];
    `include "tests/memory_check.svh"
    logic [31:0] lfsr;
    logic have_aw, have_w, have_ar;
    logic [30:0] saved_aw, saved_ar;
    logic [511:0] saved_data;
    logic [63:0] saved_strobe;
    integer aw_count, w_count, ar_count, b_count, r_count, write_delay, read_delay;
    integer fault_mode=0,expected_writes;
    logic held_aw, held_w, held_ar;
    logic [30:0] old_aw, old_ar;
    logic [575:0] old_w;
    assign m_axi_awready=rst_n && !have_aw && !m_axi_bvalid && lfsr[0];
    assign m_axi_wready=rst_n && !have_w && !m_axi_bvalid && lfsr[1];
    assign m_axi_arready=rst_n && !have_ar && !m_axi_rvalid && lfsr[2] && fault_mode!=3;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lfsr<=32'h3588c510;
            have_aw<=0; have_w<=0; have_ar<=0; saved_aw<=0; saved_ar<=0; saved_data<=0; saved_strobe<=0;
            m_axi_bid<=0; m_axi_bresp<=0; m_axi_bvalid<=0;
            m_axi_rid<=0; m_axi_rresp<=0; m_axi_rlast<=1; m_axi_rdata<=0; m_axi_rvalid<=0;
            aw_count<=0; w_count<=0; ar_count<=0; b_count<=0; r_count<=0; write_delay<=0; read_delay<=0;
            held_aw<=0; held_w<=0; held_ar<=0; old_aw<=0; old_ar<=0; old_w<=0;
        end else begin
            lfsr<={lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
            if (m_axi_awid!=0 || m_axi_arid!=0 || m_axi_awlen!=0 || m_axi_arlen!=0 ||
                m_axi_awsize!=6 || m_axi_arsize!=6 || m_axi_awburst!=1 || m_axi_arburst!=1 ||
                m_axi_awlock || m_axi_arlock || m_axi_awcache!=0 || m_axi_arcache!=0 ||
                m_axi_awprot!=0 || m_axi_arprot!=0 || m_axi_awqos!=0 || m_axi_arqos!=0 || !m_axi_wlast)
                $fatal(1,"unsupported AXI attributes");
            if (held_aw && (!m_axi_awvalid || m_axi_awaddr!==old_aw)) $fatal(1,"unstable AW");
            if (held_ar && (!m_axi_arvalid || m_axi_araddr!==old_ar)) $fatal(1,"unstable AR");
            if (held_w && (!m_axi_wvalid || {m_axi_wdata,m_axi_wstrb}!==old_w)) $fatal(1,"unstable W");
            held_aw<=m_axi_awvalid && !m_axi_awready; old_aw<=m_axi_awaddr;
            held_ar<=m_axi_arvalid && !m_axi_arready; old_ar<=m_axi_araddr;
            held_w<=m_axi_wvalid && !m_axi_wready; old_w<={m_axi_wdata,m_axi_wstrb};
            if (m_axi_awvalid && m_axi_awready) begin
                if (m_axi_awaddr[5:0]!=0) $fatal(1,"unaligned AW");
                have_aw<=1; saved_aw<=m_axi_awaddr; aw_count<=aw_count+1; write_delay<=3+int'(lfsr[5:3]);
            end
            if (m_axi_wvalid && m_axi_wready) begin
                if ($countones(m_axi_wstrb)!=2) $fatal(1,"wrong write mask");
                have_w<=1; saved_data<=m_axi_wdata; saved_strobe<=m_axi_wstrb; w_count<=w_count+1;
            end
            if (m_axi_arvalid && m_axi_arready) begin
                if (m_axi_araddr[5:0]!=0) $fatal(1,"unaligned AR");
                have_ar<=1; saved_ar<=m_axi_araddr; ar_count<=ar_count+1; read_delay<=2+int'(lfsr[8:6]);
            end
            if (have_aw && have_w && fault_mode!=5 && !(fault_mode==9 && w_count==18)) begin
                if (write_delay!=0) write_delay<=write_delay-1;
                else begin
                    have_aw<=0; have_w<=0; m_axi_bvalid<=1;
                    m_axi_bresp<=(fault_mode==4 || (fault_mode==6 && w_count==expected_writes)) ? 2'b10 : 2'b00;
                    if (32'(saved_aw)<BASE || 32'(saved_aw)>=BASE+2*WORDS) m_axi_bresp<=3;
                    else for (integer i=0; i<64; i=i+1)
                        if (saved_strobe[i]) memory[((32'(saved_aw)-BASE)>>1)+i/2][8*(i%2) +: 8]<=saved_data[8*i +: 8];
                end
            end
            if (have_ar && fault_mode!=2) begin
                if (read_delay!=0) read_delay<=read_delay-1;
                else begin
                    have_ar<=0; m_axi_rvalid<=1; m_axi_rresp<=fault_mode==1 ? 2'b10 : 2'b00;
                    if (32'(saved_ar)<BASE || 32'(saved_ar)>=BASE+2*WORDS) begin m_axi_rresp<=3; m_axi_rdata<=0; end
                    else for (integer i=0; i<32; i=i+1) m_axi_rdata[16*i +: 16]<=memory[((32'(saved_ar)-BASE)>>1)+i];
                end
            end
            if (m_axi_bvalid && m_axi_bready) begin m_axi_bvalid<=0; b_count<=b_count+1; end
            if (m_axi_rvalid && m_axi_rready) begin m_axi_rvalid<=0; r_count<=r_count+1; end
        end
    end
    task automatic reset_all;
        @(negedge clk); rst_n=0; memory_ready=0; host_idle();
        repeat(4) @(negedge clk);
        if (irq || m_axi_awvalid || m_axi_wvalid || m_axi_arvalid || m_axi_bready || m_axi_rready ||
            s_axil_bvalid || s_axil_rvalid) $fatal(1,"activity during joint reset");
        rst_n=1; host_expect(8,0);
    endtask
    task automatic stage(input logic [31:0] address, input logic [31:0] amount, input logic [31:0] tag);
        host_write(32'h10,address,0,1); host_write(32'h14,amount,0,2); host_write(32'h18,tag);
    endtask
    string prefix, output_path;
    logic [31:0] start_address, start_amount, status, tag;
    logic [15:0] reset_scratch, reset_output;
    integer expected_tasks, expected_transactions, expected_error, repeats, polls, requested_fault, expected_checks;
    initial begin
        if (!$value$plusargs("WRITES=%d",expected_writes)) $fatal(1,"missing write count");
        if (!$value$plusargs("CASE=%s",prefix) || !$value$plusargs("START=%h",start_address) ||
            !$value$plusargs("AMOUNT=%d",start_amount) || !$value$plusargs("NTASKS=%d",expected_tasks) ||
            !$value$plusargs("NTRANS=%d",expected_transactions) || !$value$plusargs("OUTPUT=%s",output_path) ||
            !$value$plusargs("NCHECKS=%d",expected_checks))
            $fatal(1,"missing host replay metadata");
        if (!$value$plusargs("FAULT=%d",fault_mode)) fault_mode=0;
        requested_fault=fault_mode;
        if (!$value$plusargs("REPEATS=%d",repeats)) repeats=1;
        for (integer i=0; i<WORDS; i=i+1) memory[i]=16'ha55a;
        $readmemh({prefix,"/input.hex"},memory);
        if (fault_mode==8) memory[((start_address-BASE)>>1)+3]=16'hffff;
        reset_all();
        host_expect(0,32'h524b434d); host_expect(4,32'h00010000);
        if (fault_mode==9) begin
            stage(start_address,start_amount,32'hab07);
            memory_ready=1; host_write(32'h0c,1);
            wait(have_aw && have_w && w_count==18);
            if (b_count!=17 || irq) $fatal(1,"reset test did not reach partial CMAC output");
            reset_scratch=memory[(32'h10040000-BASE)>>1];
            reset_output=memory[(32'h10040042-BASE)>>1];
            reset_all(); fault_mode=0;
            if (memory[(32'h10040000-BASE)>>1]!==reset_scratch || memory[(32'h10040042-BASE)>>1]!==reset_output)
                $fatal(1,"joint reset rolled back completed memory writes");
            // RAM is intentionally not reloaded: partial writes must not be rolled back.
        end
        expected_error=0;
        case (fault_mode)
            1,4,6,10: expected_error=5;
            2,3,5: expected_error=8;
            7: expected_error=7;
            8: expected_error=1;
            default: begin end
        endcase
        for (integer job=0; job<repeats; job=job+1) begin
            tag=32'h35880000+32'(job);
            stage((start_address+(fault_mode==7 ? 32'd8 : 32'd0)) |
                  (fault_mode==10 ? 32'h80000000 : 32'b0),start_amount,tag);
            if (job==0) begin
                host_expect(8,32'h700); host_write(32'h0c,1,2);
                if (aw_count!=0 || ar_count!=0 || w_count!=0 || irq) $fatal(1,"job launched before memory admission");
                memory_ready=1;
            end
            host_expect(8,32'h711);
            host_write(32'h0c,1);
            host_write(32'h10,32'hbad0bad0,2); host_write(32'h0c,1,2); host_write(32'h0c,2,2);
            status=0; polls=0;
            while (!status[2] && polls<100000) begin host_read(8,status); polls=polls+1; end
            if (!status[2] || !irq || status[1] || status[3]!=(expected_error!=0)) $fatal(1,"bad completion status %08h",status);
            host_expect(32'h1c,tag); host_expect(32'h24,32'(expected_error));
            host_expect(32'h20,expected_error==0 ? 32'(expected_tasks) : 32'd0);
            repeat(5) @(negedge clk);
            if (!irq) $fatal(1,"IRQ was a pulse instead of a held result");
            if (expected_error!=0) begin
                host_write(32'h0c,2,2); host_write(32'h18,0,2); host_expect(32'h24,32'(expected_error));
                if (fault_mode==3 && !m_axi_arvalid) $fatal(1,"core timeout cancelled AXI AR");
                if (((fault_mode==7 || fault_mode==10) && ar_count!=0) || (fault_mode==8 && (ar_count!=4 || aw_count!=0)))
                    $fatal(1,"descriptor/raw-register rejection did not occur at its proper boundary");
                reset_all();
            end else begin
                if (have_aw || have_w || have_ar || m_axi_bvalid || m_axi_rvalid ||
                    aw_count!=w_count || b_count!=w_count || r_count!=ar_count ||
                    ar_count+aw_count!=(job+1)*expected_transactions) $fatal(1,"premature completion or duplicated memory traffic");
                host_write(32'h10,0,2); host_write(32'h0c,1,2);
                host_write(32'h0c,2);
                host_expect(8,32'h10); host_expect(32'h10,0); host_expect(32'h14,0); host_expect(32'h18,0);
                if (irq) $fatal(1,"ACK did not release result");
            end
        end
        if (expected_error==0) begin
            verify_memory({prefix,"/check.txt"},output_path,expected_checks);
        end
        $display("PASS CMAC host_axi %s repeats=%0d fault_mode=%0d error=%0d status/tag/task/IRQ and memory checks",prefix,repeats,requested_fault,expected_error);
        $finish;
    end
    initial begin #30000000; $fatal(1,"host AXI global timeout"); end
endmodule
