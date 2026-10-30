// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Component integration bench only. No BSCANE2/TAP, PCIe, MIG, or board model.
module tb_retained_jtag_reset;
    localparam logic [31:0] MAGIC=32'h4f54504a;
    localparam logic [15:0] NORMAL_SEQ0=16'h1001;
    localparam logic [15:0] HELD_SEQ=16'h1002;
    localparam logic [15:0] NORMAL_SEQ1=16'h1003;
    localparam logic [15:0] SYS_SEQ=16'h2001;
    localparam logic [31:0] NORMAL_ADDR0=32'h00001000;
    localparam logic [31:0] NORMAL_ADDR1=32'h00002040;
    localparam logic [1:0] GATE_SEALED=2'b10;

    logic sys_clk;
    logic ui_enable,ui_clk;
    initial begin sys_clk=0;forever #10 sys_clk=~sys_clk;end
    initial begin
        ui_clk=0;
        forever begin #3.75;if(ui_enable)ui_clk=~ui_clk;else ui_clk=0;end
    end

    // One physical TCK/data/control bundle with independent USER2/USER3 SEL
    // and TDO selection. This tests the DR mailbox, not a BSCANE2 TAP model.
    logic tck=0,capture=0,shift=0,update=0,sel=0,tdi=0,user3_active=0;
    wire sel_user2=sel&&!user3_active;
    wire sel_user3=sel&&user3_active;
    wire tdo_user2,tdo_user3;
    wire tdo=user3_active?tdo_user3:tdo_user2;
    `include "tests/host/mailbox_scan.svh"

    logic ui_clients_rst_n=0;
    wire ui_power_rst_n,normal_req_valid;
    wire [603:0] normal_req;

    wire sys_power_rst_n,sys_req_valid;
    wire [603:0] sys_req;
    wire control_req_ready,control_rsp_valid;
    wire [511:0] control_rsp_data;
    wire [7:0] control_rsp_status;
    wire [15:0] control_rsp_seq;

    logic admission_block=0,parent_drained=1;
    wire gate_s_ready,gate_m_valid,gate_sealed_quiet,gate_fault;
    wire [603:0] gate_m_req;
    wire gate_rsp_valid;
    wire [511:0] gate_rsp_data;
    wire [7:0] gate_rsp_status;
    wire [15:0] gate_rsp_seq;

    logic backend_rsp_valid,backend_pending;
    wire backend_req_ready=1'b1;
    logic [511:0] backend_rsp_data;
    logic [7:0] backend_rsp_status;
    logic [15:0] backend_rsp_seq;
    logic [603:0] backend_req_hold;
    integer backend_delay,backend_accepts;

    logic quiesce_ack=0,quiescent=0,reset_ready=1,reset_asserted=0;
    logic reset_complete=0,reset_fault=0;
    logic [7:0] reset_fault_code=0;
    logic platform_ready=0;
    wire control_quiesce,control_reset_request;

    integer ui_edges,sys_edges,ui_startup_edges,sys_startup_edges;
    integer ui_startup_checks,sys_startup_checks;
    integer check_count=0,normal_success_count=0,normal_denial_count=0,sys_identity_reads=0,sys_control_accepts;
    logic [603:0] held_normal_req=0;

    rk_retained_jtag_mailbox #(.HOLD_CYCLES(64)) normal_mailbox (
        .clk(ui_clk),.tck,.capture,.shift,.update,.sel(sel_user2),.tdi,.tdo(tdo_user2),
        .power_rst_n(ui_power_rst_n),.req_valid(normal_req_valid),.req_ready(gate_s_ready),.req(normal_req),
        .rsp_valid(gate_rsp_valid),.rsp_data(gate_rsp_data),.rsp_status(gate_rsp_status),.rsp_seq(gate_rsp_seq));

    rk_retained_jtag_mailbox #(.HOLD_CYCLES(64)) sys_mailbox (
        .clk(sys_clk),.tck,.capture,.shift,.update,.sel(sel_user3),.tdi,.tdo(tdo_user3),
        .power_rst_n(sys_power_rst_n),.req_valid(sys_req_valid),.req_ready(control_req_ready),.req(sys_req),
        .rsp_valid(control_rsp_valid),.rsp_data(control_rsp_data),.rsp_status(control_rsp_status),.rsp_seq(control_rsp_seq));

    rk_whole_reset_frame_gate gate (
        .ui_clk,.power_rst_n(ui_power_rst_n),.ui_clients_rst_n,
        .admission_block,.parent_drained,
        .s_req_valid(normal_req_valid),.s_req_ready(gate_s_ready),.s_req(normal_req),
        .s_rsp_valid(gate_rsp_valid),.s_rsp_data(gate_rsp_data),.s_rsp_status(gate_rsp_status),.s_rsp_seq(gate_rsp_seq),
        .m_req_valid(gate_m_valid),.m_req_ready(backend_req_ready),.m_req(gate_m_req),
        .m_rsp_valid(backend_rsp_valid),.m_rsp_data(backend_rsp_data),.m_rsp_status(backend_rsp_status),.m_rsp_seq(backend_rsp_seq),
        .sealed_quiet(gate_sealed_quiet),.gate_fault);

    rk_whole_reset_control control (
        .sys_clk,.power_rst_n(sys_power_rst_n),
        .req_valid(sys_req_valid),.req_ready(control_req_ready),.req(sys_req),
        .rsp_valid(control_rsp_valid),.rsp_data(control_rsp_data),.rsp_status(control_rsp_status),.rsp_seq(control_rsp_seq),
        .quiesce_request(control_quiesce),.quiesce_ack,.quiescent,
        .reset_request(control_reset_request),.reset_ready,.reset_asserted,.reset_complete,.reset_fault,.reset_fault_code,
        .platform_ready);

    // Scripted raw backend: delayed address-echo reads only; no arithmetic,
    // memory, MIG, ECC, physical front end or completion-model claim.
    always @(posedge ui_clk or negedge ui_power_rst_n)begin
        if(!ui_power_rst_n)begin
            backend_rsp_valid<=0;backend_pending<=0;backend_delay<=0;
            backend_rsp_data<=0;backend_rsp_status<=0;backend_rsp_seq<=0;
            backend_req_hold<=0;backend_accepts<=0;
        end else begin
            backend_rsp_valid<=0;
            if(backend_pending)begin
                if(backend_delay<=1)begin
                    backend_rsp_valid<=1;backend_rsp_data<={480'd0,backend_req_hold[543:512]};
                    backend_rsp_status<=0;backend_rsp_seq<=backend_req_hold[571:556];backend_pending<=0;
                end else backend_delay<=backend_delay-1;
            end
            if(gate_m_valid&&backend_req_ready)begin
                if(backend_pending)$fatal(1,"scripted backend accepted overlapping request");
                backend_req_hold<=gate_m_req;
                backend_delay<=1+(int'(gate_m_req[571:556])%3);
                backend_pending<=1;backend_accepts<=backend_accepts+1;
            end
        end
    end

    initial begin ui_edges=0;forever begin @(posedge ui_clk);ui_edges=ui_edges+1;end end
    initial begin sys_edges=0;forever begin @(posedge sys_clk);sys_edges=sys_edges+1;end end
    initial begin
        ui_startup_checks=0;
        forever begin
            @(posedge ui_power_rst_n);#0.1;
            if(ui_edges!=65)$fatal(1,"USER2 configuration startup released after %0d UI edges, expected 65",ui_edges);
            ui_startup_edges=ui_edges;ui_startup_checks=ui_startup_checks+1;
        end
    end
    initial begin
        sys_startup_checks=0;
        forever begin
            @(posedge sys_power_rst_n);#0.1;
            if(sys_edges!=65)$fatal(1,"USER3 configuration startup released after %0d SYS edges, expected 65",sys_edges);
            sys_startup_edges=sys_edges;sys_startup_checks=sys_startup_checks+1;
        end
    end
    initial sys_control_accepts=0;
    always @(posedge sys_clk or negedge sys_power_rst_n)begin
        if(!sys_power_rst_n)sys_control_accepts<=0;
        else if(sys_req_valid&&control_req_ready)sys_control_accepts<=sys_control_accepts+1;
    end

    function automatic logic [639:0] make_read_frame(input logic [15:0] frame_seq,input logic [31:0] address);
        make_read_frame={36'b0,MAGIC,frame_seq,8'd1,4'hf,address,512'd0};
    endfunction
    task automatic check(input logic condition,input string note);
        begin check_count=check_count+1;if(condition!==1'b1)$fatal(1,"CHECK_FAILED %s",note);end
    endtask
    task automatic scan_chain(input bit use_user3,input logic [639:0] tx,output logic [639:0] rx);
        begin user3_active=use_user3;scan_frame(tx,rx);end
    endtask
    task automatic response_for(input bit use_user3,input logic [15:0] wanted_seq,output logic [639:0] rx);
        begin: response_wait
            for(integer poll=0;poll<10;poll=poll+1)begin
                scan_chain(use_user3,640'd0,rx);
                if(rx[567:536]===MAGIC&&rx[535:520]===wanted_seq)disable response_wait;
            end
            $fatal(1,"response timeout chain=%0d sequence=%h",use_user3,wanted_seq);
        end
    endtask
    task automatic check_response(input logic [639:0] rx,input logic [15:0] wanted_seq,
        input logic [7:0] wanted_status,input logic [511:0] wanted_data,input string note);
        begin
            check(rx[639:568]===72'd0,{note," high DR pad"});
            check(rx[567:536]===MAGIC,{note," magic"});
            check(rx[535:520]===wanted_seq,{note," sequence"});
            check(rx[519:512]===wanted_status,{note," status"});
            check(rx[511:0]===wanted_data,{note," payload"});
        end
    endtask
    task automatic wait_normal_held(input logic [603:0] expected_req,input integer max_edges);
        begin: wait_held
            for(integer n=0;n<max_edges;n=n+1)begin
                @(posedge ui_clk);#0.1;
                if(normal_req_valid===1'b1)begin
                    check(normal_req===expected_req,"normal held req exact 604-bit payload");disable wait_held;
                end
            end
            $fatal(1,"normal mailbox did not offer retained request");
        end
    endtask

    logic [639:0] tx,rx;
    integer stopped_edges;
    initial begin
        ui_enable=1;
        wait(ui_startup_checks==1&&sys_startup_checks==1);#0.2;
        check(ui_power_rst_n===1'b1&&sys_power_rst_n===1'b1,"both configuration startup resets released");
        ui_clients_rst_n=1;
        repeat(4)@(posedge ui_clk);#0.1;
        check(gate.state===2'b00,"normal gate initially OPEN");

        // USER2 sequence 1001 is forwarded unchanged and answered exactly once.
        tx=make_read_frame(NORMAL_SEQ0,NORMAL_ADDR0);scan_chain(0,tx,rx);
        response_for(0,NORMAL_SEQ0,rx);
        check_response(rx,NORMAL_SEQ0,8'd0,{480'd0,NORMAL_ADDR0},"normal seq1001 response");
        normal_success_count=normal_success_count+1;
        repeat(4)@(posedge ui_clk);#0.1;
        check(backend_accepts==1,"normal seq1001 accepted once by scripted raw backend");
        check(backend_req_hold===tx[603:0],"normal seq1001 backend frame unchanged");
        repeat(3)begin scan_chain(0,640'd0,rx);end
        check(backend_accepts==1,"normal zero-frame polls do not duplicate backend request");

        // Reach actual SEALED before offering seq 1002, then retain the complete
        // request in the mailbox through client reset and stopped UI clock.
        @(negedge ui_clk);admission_block=1;parent_drained=1;
        begin: wait_sealed
            for(integer n=0;n<16;n=n+1)begin @(posedge ui_clk);#0.1;if(gate.state===GATE_SEALED)disable wait_sealed;end
            $fatal(1,"actual frame gate did not reach SEALED");
        end
        check(gate_sealed_quiet===1'b1,"actual gate reports sealed quiet");
        tx=make_read_frame(HELD_SEQ,32'h00003080);scan_chain(0,tx,rx);held_normal_req=tx[603:0];
        wait_normal_held(held_normal_req,20);
        repeat(4)begin @(posedge ui_clk);#0.1;check(normal_req_valid===1'b1&&normal_req===held_normal_req&&gate_s_ready===1'b0,"sealed request held before client reset");end
        check(backend_accepts==1,"sealed request has not reached backend before reset");

        @(negedge ui_clk);ui_clients_rst_n=0;ui_enable=0;stopped_edges=ui_edges;
        #1000;
        check(ui_edges==stopped_edges,"UI clock remained stopped");
        check(ui_clients_rst_n===1'b0&&ui_power_rst_n===1'b1,"client reset independent of retained mailbox power reset");
        check(normal_req_valid===1'b1&&normal_req===held_normal_req,"normal request retained while UI stopped");
        check(backend_accepts==1,"no backend request while UI stopped");

        // USER3 reads the actual SYS reset controller identity while UI is stopped.
        tx=make_read_frame(SYS_SEQ,32'h00000000);scan_chain(1,tx,rx);
        response_for(1,SYS_SEQ,rx);
        check_response(rx,SYS_SEQ,8'd0,{480'd0,32'h524b5052},"SYS whole-reset identity while UI stopped");
        sys_identity_reads=sys_identity_reads+1;
        check(sys_control_accepts==1,"SYS response polls did not duplicate USER3 identity read");
        check(control_reset_request===1'b0&&control_quiesce===1'b0,"identity read issued no warm reset");
        check(ui_edges==stopped_edges,"SYS USER3 read did not require UI clock edges");
        check(normal_req_valid===1'b1&&normal_req===held_normal_req,"normal frame still held during SYS-only read");

        ui_enable=1;
        repeat(8)@(posedge ui_clk);#0.1;
        check(ui_clients_rst_n===1'b0&&normal_req_valid===1'b1&&backend_accepts==1,"UI restart under client reset retains held frame");
        @(negedge ui_clk);ui_clients_rst_n=1;
        repeat(8)begin @(posedge ui_clk);#0.1;check(gate.state===GATE_SEALED&&normal_req_valid===1'b1&&normal_req===held_normal_req&&backend_accepts==1,"client release under block remains sealed");end

        // Actual frame gate denies the stale held seq 1002 after barrier release.
        @(negedge ui_clk);admission_block=0;
        response_for(0,HELD_SEQ,rx);
        check_response(rx,HELD_SEQ,8'd2,512'd0,"held seq1002 denial after barrier release");
        normal_denial_count=normal_denial_count+1;
        repeat(4)begin scan_chain(0,640'd0,rx);@(posedge ui_clk);#0.1;end
        check(backend_accepts==1,"denied seq1002 was never accepted/retried by backend");
        check(gate_fault===1'b0,"expected stale-frame denial is not a gate fault");

        // A new USER2 sequence after the barrier reaches the backend once.
        tx=make_read_frame(NORMAL_SEQ1,NORMAL_ADDR1);scan_chain(0,tx,rx);
        response_for(0,NORMAL_SEQ1,rx);
        check_response(rx,NORMAL_SEQ1,8'd0,{480'd0,NORMAL_ADDR1},"fresh seq1003 response");
        normal_success_count=normal_success_count+1;
        repeat(4)begin scan_chain(0,640'd0,rx);@(posedge ui_clk);#0.1;end
        check(backend_accepts==2,"only successful seq1001 and seq1003 reached backend");
        check(backend_req_hold===tx[603:0],"fresh seq1003 raw frame unchanged");
        check(sys_identity_reads==1,"one SYS identity read during stopped UI");
        check(ui_startup_checks==1&&sys_startup_checks==1,"both startup edge checks ran once");
        if(backend_pending||backend_rsp_valid)$fatal(1,"scripted raw backend left outstanding response");
        $display("PASS retained mailbox warm-reset checks=%0d ui_startup_edges=%0d sys_startup_edges=%0d normal_successes=%0d backend_accepts=%0d sys_identity_reads=%0d sys_control_accepts=%0d held_denials=%0d",check_count,ui_startup_edges,sys_startup_edges,normal_success_count,backend_accepts,sys_identity_reads,sys_control_accepts,normal_denial_count);
        $finish;
    end
    initial begin #100000000;$fatal(1,"retained mailbox warm-reset bench watchdog");end
endmodule
