// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Independent AXI-Lite control-slave model, not MIG or DDR qualification.
module tb_mig_ecc_monitor;
    logic clk;
    initial clk=0;
    always #5 clk=~clk;
    logic joint_rst_n,calib_complete,mig_interrupt,check_valid,snapshot_ready;
    wire check_ready,snapshot_valid,monitor_healthy,fault;
    wire [7:0] fault_code;
    wire [31:0] snapshot_status,snapshot_onoff,snapshot_irq_mask;
    wire [31:0] m_axi_ctrl_awaddr,m_axi_ctrl_wdata,m_axi_ctrl_araddr;
    wire m_axi_ctrl_awvalid,m_axi_ctrl_wvalid,m_axi_ctrl_bready,m_axi_ctrl_arvalid,m_axi_ctrl_rready;
    wire m_axi_ctrl_awready,m_axi_ctrl_wready,m_axi_ctrl_arready,m_axi_ctrl_bvalid,m_axi_ctrl_rvalid;
    logic [1:0] m_axi_ctrl_bresp,m_axi_ctrl_rresp;
    wire [31:0] m_axi_ctrl_rdata;
    logic allow_aw,allow_w,allow_b,allow_ar,allow_r,inject_b,inject_r;
    logic [31:0] mask_value,onoff_value,status_value;
    logic aw_seen,w_seen,read_pending,bvalid,rvalid;
    logic [31:0] saved_aw,saved_w,read_address;
    integer write_count,read_count,ar_count,cases;

    rk_mig_ecc_monitor #(.TIMEOUT_CYCLES(32)) dut(.*);
    assign m_axi_ctrl_awready=joint_rst_n && allow_aw && !aw_seen && !bvalid;
    assign m_axi_ctrl_wready=joint_rst_n && allow_w && !w_seen && !bvalid;
    assign m_axi_ctrl_arready=joint_rst_n && allow_ar && !read_pending && !rvalid;
    assign m_axi_ctrl_bvalid=bvalid || inject_b;
    assign m_axi_ctrl_rvalid=rvalid || inject_r;
    assign m_axi_ctrl_rdata=read_address==4 ? mask_value : read_address==8 ? onoff_value : status_value;
    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            aw_seen<=0;w_seen<=0;read_pending<=0;bvalid<=0;rvalid<=0;
            saved_aw<=0;saved_w<=0;read_address<=0;write_count<=0;read_count<=0;ar_count<=0;
        end else begin
            if (m_axi_ctrl_awvalid && m_axi_ctrl_awready) begin aw_seen<=1;saved_aw<=m_axi_ctrl_awaddr;end
            if (m_axi_ctrl_wvalid && m_axi_ctrl_wready) begin w_seen<=1;saved_w<=m_axi_ctrl_wdata;end
            if (!bvalid && aw_seen && w_seen && allow_b) begin
                if (saved_aw!==32'h4 || saved_w!==32'h3) $fatal(1,"Unexpected control write/clear/repair");
                aw_seen<=0;w_seen<=0;bvalid<=1;write_count<=write_count+1;
            end
            if (bvalid && m_axi_ctrl_bready) bvalid<=0;
            if (m_axi_ctrl_arvalid && m_axi_ctrl_arready) begin
                if (m_axi_ctrl_araddr!==0 && m_axi_ctrl_araddr!==4 && m_axi_ctrl_araddr!==8)
                    $fatal(1,"Unexpected control read");
                read_pending<=1;read_address<=m_axi_ctrl_araddr;ar_count<=ar_count+1;
            end
            if (read_pending && allow_r && !rvalid) begin
                rvalid<=1;read_pending<=0;read_count<=read_count+1;
            end
            if (rvalid && m_axi_ctrl_rready) rvalid<=0;
        end
    end

    task automatic step;
        @(posedge clk); #1;
    endtask
    task automatic reset_case;
        @(negedge clk);
        joint_rst_n=0;calib_complete=0;mig_interrupt=0;check_valid=0;snapshot_ready=0;
        allow_aw=1;allow_w=1;allow_b=1;allow_ar=1;allow_r=1;inject_b=0;inject_r=0;
        mask_value=3;onoff_value=1;status_value=0;m_axi_ctrl_bresp=0;m_axi_ctrl_rresp=0;
        repeat(3) step();
        @(negedge clk);joint_rst_n=1;
        repeat(3) step();
        if (monitor_healthy || fault || snapshot_valid || check_ready || m_axi_ctrl_awvalid || m_axi_ctrl_arvalid)
            $fatal(1,"Reset/calibration admission failure");
    endtask
    task automatic calibrate;
        @(negedge clk);calib_complete=1;step();
    endtask
    task automatic await_healthy;
        integer n;
        n=0;
        while (!monitor_healthy && !fault && n<100) begin step();n=n+1;end
        if (!monitor_healthy || fault || !check_ready || snapshot_valid || write_count!=1 || read_count!=3)
            $fatal(1,"Startup failed code=%0d writes=%0d reads=%0d",fault_code,write_count,read_count);
    endtask
    task automatic healthy_start;
        reset_case();calibrate();await_healthy();
    endtask
    task automatic expect_fault(input logic [7:0] code);
        integer n;
        n=0;
        while (!fault && n<100) begin step();n=n+1;end
        if (!fault || fault_code!==code || monitor_healthy || check_ready)
            $fatal(1,"Expected fault%0d got fault=%0d code=%0d",code,fault,fault_code);
        cases=cases+1;
    endtask
    task automatic request_check;
        if (!check_ready) $fatal(1,"Check not ready");
        @(negedge clk);check_valid=1;step();
        @(negedge clk);check_valid=0;
    endtask
    task automatic await_snapshot;
        integer n;
        n=0;
        while (!snapshot_valid && !fault && n<100) begin step();n=n+1;end
        if (!snapshot_valid || fault || snapshot_status!==0 || snapshot_onoff!==1 || snapshot_irq_mask!==3)
            $fatal(1,"Bad check snapshot");
    endtask
    task automatic ensure_quiet(input integer writes,input integer reads);
        repeat(6) step();
        if (!fault || monitor_healthy || m_axi_ctrl_awvalid || m_axi_ctrl_wvalid || m_axi_ctrl_arvalid ||
            write_count!=writes || read_count!=reads || snapshot_valid)
            $fatal(1,"Quarantine issued work or did not drain");
    endtask

    initial begin
        cases=0;joint_rst_n=0;calib_complete=0;mig_interrupt=0;check_valid=0;snapshot_ready=0;
        allow_aw=0;allow_w=0;allow_b=0;allow_ar=0;allow_r=0;inject_b=0;inject_r=0;
        mask_value=0;onoff_value=0;status_value=0;m_axi_ctrl_bresp=0;m_axi_ctrl_rresp=0;

        // Independent AW/W acceptance in both orders, with fixed payloads.
        reset_case();allow_w=0;calibrate();repeat(3) step();
        if (m_axi_ctrl_awvalid || !m_axi_ctrl_wvalid || m_axi_ctrl_wdata!==3) $fatal(1,"AW-first handshake");
        @(negedge clk);allow_w=1;await_healthy();cases=cases+1;
        reset_case();allow_aw=0;calibrate();repeat(3) step();
        if (!m_axi_ctrl_awvalid || m_axi_ctrl_wvalid || m_axi_ctrl_awaddr!==4) $fatal(1,"W-first handshake");
        @(negedge clk);allow_aw=1;await_healthy();cases=cases+1;

        // Fresh snapshots are stable; no second request while output is held.
        request_check();await_snapshot();
        @(negedge clk);check_valid=1;
        repeat(5) begin
            step();
            if (!snapshot_valid || snapshot_status!==0 || snapshot_onoff!==1 || snapshot_irq_mask!==3 ||
                check_ready || ar_count!=6 || write_count!=1) $fatal(1,"Snapshot/ownership changed");
        end
        @(negedge clk);check_valid=0;snapshot_ready=1;step();
        @(negedge clk);snapshot_ready=0;
        request_check();await_snapshot();
        if (ar_count!=9 || write_count!=1) $fatal(1,"Check did not perform fresh reads");
        cases=cases+1;
        // IRQ must withdraw healthy before the clock edge, preserving a held snapshot.
        @(negedge clk);mig_interrupt=1;#1;
        if (monitor_healthy) $fatal(1,"IRQ health not immediate");
        expect_fault(1);
        @(negedge clk);mig_interrupt=0;status_value=3;
        repeat(4) begin
            step();
            if (!snapshot_valid || snapshot_status!==0 || snapshot_onoff!==1 || snapshot_irq_mask!==3 || fault_code!==1)
                $fatal(1,"Fault changed held snapshot/first cause");
        end
        @(negedge clk);snapshot_ready=1;step();
        @(negedge clk);snapshot_ready=0;ensure_quiet(1,9);

        healthy_start();@(negedge clk);calib_complete=0;#1;
        if (monitor_healthy) $fatal(1,"Calibration loss not immediate");
        expect_fault(2);
        @(negedge clk);calib_complete=1;ensure_quiet(1,3);

        reset_case();mask_value=1;calibrate();expect_fault(6);ensure_quiet(1,1);
        reset_case();onoff_value=0;calibrate();expect_fault(7);ensure_quiet(1,2);
        reset_case();status_value=1;calibrate();expect_fault(8);ensure_quiet(1,3);
        reset_case();status_value=2;calibrate();expect_fault(8);ensure_quiet(1,3);
        reset_case();status_value=3;calibrate();expect_fault(8);ensure_quiet(1,3);
        reset_case();m_axi_ctrl_bresp=2;calibrate();expect_fault(4);ensure_quiet(1,0);
        reset_case();m_axi_ctrl_rresp=2;calibrate();expect_fault(4);ensure_quiet(1,1);

        // Timeouts retain AW, W and AR independently until their real handshake.
        reset_case();allow_aw=0;calibrate();expect_fault(3);
        repeat(4) begin step();if (!m_axi_ctrl_awvalid || m_axi_ctrl_awaddr!==4 || m_axi_ctrl_wvalid) $fatal(1,"AW withdrawn");end
        @(negedge clk);allow_aw=1;repeat(8) step();ensure_quiet(1,0);
        reset_case();allow_w=0;calibrate();expect_fault(3);
        repeat(4) begin step();if (!m_axi_ctrl_wvalid || m_axi_ctrl_wdata!==3 || m_axi_ctrl_awvalid) $fatal(1,"W withdrawn");end
        @(negedge clk);allow_w=1;repeat(8) step();ensure_quiet(1,0);
        reset_case();allow_ar=0;calibrate();expect_fault(3);
        repeat(4) begin step();if (!m_axi_ctrl_arvalid || m_axi_ctrl_araddr!==4 || !m_axi_ctrl_rready) $fatal(1,"AR withdrawn");end
        @(negedge clk);allow_ar=1;repeat(8) step();ensure_quiet(1,1);
        reset_case();allow_b=0;calibrate();expect_fault(3);
        if (!m_axi_ctrl_bready || m_axi_ctrl_awvalid || m_axi_ctrl_wvalid) $fatal(1,"B drain failure");
        @(negedge clk);allow_b=1;repeat(8) step();ensure_quiet(1,0);
        reset_case();allow_r=0;calibrate();expect_fault(3);
        if (!m_axi_ctrl_rready || m_axi_ctrl_arvalid) $fatal(1,"R drain failure");
        @(negedge clk);allow_r=1;repeat(8) step();ensure_quiet(1,1);

        healthy_start();@(negedge clk);inject_b=1;expect_fault(5);
        @(negedge clk);inject_b=0;ensure_quiet(1,3);
        healthy_start();@(negedge clk);inject_r=1;expect_fault(5);
        @(negedge clk);inject_r=0;ensure_quiet(1,3);
        reset_case();allow_ar=0;calibrate();
        while (!m_axi_ctrl_arvalid) step();
        @(negedge clk);inject_r=1;expect_fault(5);
        if (!m_axi_ctrl_arvalid) $fatal(1,"Premature R cancelled AR");
        @(negedge clk);inject_r=0;allow_ar=1;repeat(8) step();ensure_quiet(1,1);

        // IRQ on the final status-read edge wins over snapshot publication.
        healthy_start();request_check();
        while (!(rvalid && read_address==0)) step();
        @(negedge clk);mig_interrupt=1;expect_fault(1);
        if (snapshot_valid) $fatal(1,"False snapshot on simultaneous IRQ");
        @(negedge clk);mig_interrupt=0;ensure_quiet(1,6);

        // Calibration loss while the startup transaction is still outstanding.
        reset_case();allow_aw=0;calibrate();@(negedge clk);calib_complete=0;expect_fault(2);
        if (!m_axi_ctrl_awvalid) $fatal(1,"Calibration loss cancelled AW");
        @(negedge clk);allow_aw=1;repeat(8) step();ensure_quiet(1,0);

        // Joint reset is the only recovery; no status clear or ECC repair write.
        healthy_start();cases=cases+1;
`ifdef __ICARUS__
        // Four-state admission controls are separate from physical behavior.
        healthy_start();@(negedge clk);mig_interrupt=1'bx;#1;
        if (monitor_healthy!==0 || check_ready!==0) $fatal(1,"Unknown IRQ admitted health");
        expect_fault(1);
        healthy_start();@(negedge clk);mig_interrupt=1'bz;#1;
        if (monitor_healthy!==0 || check_ready!==0) $fatal(1,"Undriven IRQ admitted health");
        expect_fault(1);
        healthy_start();@(negedge clk);calib_complete=1'bx;#1;
        if (monitor_healthy!==0 || check_ready!==0) $fatal(1,"Unknown calibration retained health");
        expect_fault(2);
        healthy_start();@(negedge clk);calib_complete=1'bz;#1;
        if (monitor_healthy!==0 || check_ready!==0) $fatal(1,"Undriven calibration retained health");
        expect_fault(2);
        reset_case();@(negedge clk);calib_complete=1'bx;
        repeat(4) begin
            step();
            if (monitor_healthy!==0 || check_ready!==0 || fault!==0 || m_axi_ctrl_awvalid!==0 || m_axi_ctrl_arvalid!==0)
                $fatal(1,"Unknown startup calibration admitted service");
        end
        cases=cases+1;calibrate();await_healthy();
        reset_case();@(negedge clk);calib_complete=1'bz;
        repeat(4) begin
            step();
            if (monitor_healthy!==0 || check_ready!==0 || fault!==0 || m_axi_ctrl_awvalid!==0 || m_axi_ctrl_arvalid!==0)
                $fatal(1,"Undriven startup calibration admitted service");
        end
        cases=cases+1;calibrate();await_healthy();
`endif
        $display("PASS mig_ecc_monitor cases=%0d scope=independent_control_slave_only",cases);
        $finish;
    end
    initial begin
        repeat(10000) step();
        $fatal(1,"Monitor bench watchdog");
    end
endmodule
