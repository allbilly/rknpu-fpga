// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Directed independent response model only. This does not qualify the archived
// MC ordering premise, a complete DDR controller, memory contents or hardware.
module tb_mig_write_fence #(
    parameter int unsigned DUT_TIMEOUT_CYCLES = 16
);
    logic clk;
    initial clk=0;
    always #5 clk=~clk;
    logic joint_rst_n,fence_valid,fence_result_ready;
    logic [31:0] final_write_address;
    logic epoch_has_write,epoch_sealed,writes_complete,upstream_quiescent,owner_exclusive;
    logic calib_complete,monitor_healthy,monitor_fault;
    wire fence_ready,fence_result_valid,fence_done,fault;
    wire [7:0] fault_code;
    wire [3:0] m_axi_arid,m_axi_arcache,m_axi_arqos;
    wire [30:0] m_axi_araddr;
    wire [7:0] m_axi_arlen;
    wire [2:0] m_axi_arsize,m_axi_arprot;
    wire [1:0] m_axi_arburst;
    wire m_axi_arlock,m_axi_arvalid,m_axi_rready;
    logic m_axi_arready,m_axi_rlast,m_axi_rvalid;
    logic [3:0] m_axi_rid;
    logic [1:0] m_axi_rresp;
    wire monitor_check_valid,monitor_snapshot_ready;
    logic monitor_check_ready,monitor_snapshot_valid;
    logic [31:0] monitor_snapshot_status,monitor_snapshot_onoff,monitor_snapshot_irq_mask;
    integer cases,ar_count,r_count,check_count,snapshot_count,done_count;
    logic ar_stalled,check_stalled,result_stalled;
    logic [30:0] prior_address,expected_address;

    rk_mig_write_fence #(.TIMEOUT_CYCLES(DUT_TIMEOUT_CYCLES)) dut(.*);
    always @(posedge clk) begin
        if(!joint_rst_n) begin
            ar_count<=0;r_count<=0;check_count<=0;snapshot_count<=0;done_count<=0;
            ar_stalled<=0;check_stalled<=0;result_stalled<=0;prior_address<=0;
        end else begin
            if(ar_stalled&&(!m_axi_arvalid||m_axi_araddr!==prior_address))
                $fatal(1,"Stalled AR changed/withdrawn");
            if(check_stalled&&!monitor_check_valid)$fatal(1,"Stalled monitor request withdrawn");
            if(result_stalled&&!fence_result_valid)$fatal(1,"Held fence receipt withdrawn");
            ar_stalled<=m_axi_arvalid&&!m_axi_arready;
            check_stalled<=monitor_check_valid&&!monitor_check_ready;
            result_stalled<=fence_result_valid&&!fence_result_ready;
            prior_address<=m_axi_araddr;
            if(m_axi_arvalid&&m_axi_arready)begin
                if(m_axi_araddr!==expected_address||m_axi_arid!==0||m_axi_arlen!==0||
                    m_axi_arsize!==6||m_axi_arburst!==1||m_axi_arlock!==0||
                    m_axi_arcache!==0||m_axi_arprot!==0||m_axi_arqos!==0)
                    $fatal(1,"Fence is not the exact final-address ordinary full beat");
                ar_count<=ar_count+1;
            end
            if(m_axi_rvalid&&m_axi_rready)r_count<=r_count+1;
            if(monitor_check_valid&&monitor_check_ready)check_count<=check_count+1;
            if(monitor_snapshot_valid&&monitor_snapshot_ready)snapshot_count<=snapshot_count+1;
            if(fence_done)done_count<=done_count+1;
        end
    end
    task automatic step;
        @(posedge clk);#1;
    endtask
    task automatic reset_case;
        @(negedge clk);
        joint_rst_n=0;fence_valid=0;fence_result_ready=0;final_write_address=32'h10000000;
        epoch_has_write=1;epoch_sealed=1;writes_complete=1;upstream_quiescent=1;owner_exclusive=1;
        calib_complete=1;monitor_healthy=1;monitor_fault=0;
        m_axi_arready=0;m_axi_rlast=1;m_axi_rvalid=0;m_axi_rid=0;m_axi_rresp=0;
        monitor_check_ready=0;monitor_snapshot_valid=0;
        monitor_snapshot_status=0;monitor_snapshot_onoff=1;monitor_snapshot_irq_mask=3;
        expected_address=31'h10000000;
        repeat(3)step();
        @(negedge clk);joint_rst_n=1;repeat(2)step();
        if(!fence_ready||fault||fence_result_valid||fence_done||m_axi_arvalid||monitor_check_valid)
            $fatal(1,"Joint reset failed");
    endtask
    task automatic request_fence;
        if(!fence_ready)$fatal(1,"Descriptor not ready");
        @(negedge clk);fence_valid=1;step();
        @(negedge clk);fence_valid=0;
    endtask
    task automatic accept_ar;
        if(!m_axi_arvalid||!m_axi_rready)$fatal(1,"AR absent");
        @(negedge clk);m_axi_arready=1;step();
        @(negedge clk);m_axi_arready=0;
        if(m_axi_arvalid||!m_axi_rready)$fatal(1,"AR did not complete");
    endtask
    task automatic read_response;
        @(negedge clk);m_axi_rvalid=1;step();
        @(negedge clk);m_axi_rvalid=0;
    endtask
    task automatic accept_check;
        if(!monitor_check_valid)$fatal(1,"Fresh check request absent");
        @(negedge clk);monitor_check_ready=1;step();
        @(negedge clk);monitor_check_ready=0;
        if(monitor_check_valid||!monitor_snapshot_ready)$fatal(1,"Check ownership not recorded");
    endtask
    task automatic snapshot_response;
        @(negedge clk);monitor_snapshot_valid=1;step();
        @(negedge clk);monitor_snapshot_valid=0;
    endtask
    task automatic reach_check;
        integer prior_ars,prior_rs;
        prior_ars=ar_count;prior_rs=r_count;
        request_fence();accept_ar();read_response();
        if(fault||ar_count!=prior_ars+1||r_count!=prior_rs+1||fence_result_valid||fence_done)
            $fatal(1,"Read response skipped fresh ECC check");
    endtask
    task automatic reach_result;
        integer prior_checks,prior_snapshots;
        prior_checks=check_count;prior_snapshots=snapshot_count;
        reach_check();accept_check();snapshot_response();
        if(fault||!fence_result_valid||fence_done||check_count!=prior_checks+1||snapshot_count!=prior_snapshots+1)
            $fatal(1,"Validated receipt missing");
    endtask
    task automatic accept_result;
        if(!fence_result_valid)$fatal(1,"No receipt");
        @(negedge clk);fence_result_ready=1;#1;
        if(!fence_done)$fatal(1,"Good receipt acceptance did not qualify");
        step();@(negedge clk);fence_result_ready=0;
        if(fence_result_valid||fence_done||fault||!fence_ready)$fatal(1,"Receipt did not finish");
        cases=cases+1;
    endtask
    task automatic expect_fault(input logic [7:0] code);
        integer n;
        n=0;while(!fault&&n<60)begin step();n=n+1;end
        if(!fault||fault_code!==code||fence_ready||fence_done)$fatal(1,"Expected fault%0d got %0d",code,fault_code);
        cases=cases+1;
    endtask
    task automatic check_sticky(input logic [7:0] code,input integer ars,input integer checks);
        repeat(3)step();
        if(!fault||fault_code!==code||fence_ready||fence_done||ar_count!=ars||check_count!=checks||done_count!=0)
            $fatal(1,"Fault recovered, changed cause or issued successful work");
    endtask
    integer k;
    initial begin
        cases=0;joint_rst_n=0;
        reset_case();@(negedge clk);calib_complete=0;monitor_healthy=0;repeat(20)step();
        if(fault||m_axi_arvalid||monitor_check_valid||fence_done)$fatal(1,"Idle generated work");
        cases=cases+1;

        reset_case();final_write_address=0;expected_address=0;reach_result();accept_result();
        reset_case();final_write_address=32'h7fffffc0;expected_address=31'h7fffffc0;reach_result();accept_result();

        reset_case();request_fence();
        @(negedge clk);final_write_address=32'h18000100;epoch_has_write=0;
        repeat(4)step();accept_ar();repeat(3)step();read_response();
        repeat(3)step();accept_check();repeat(4)step();snapshot_response();
        repeat(24)step();
        if(fault||!fence_result_valid||ar_count!=1||check_count!=1||done_count!=0)
            $fatal(1,"Captured descriptor, stalls or held receipt failed");
        accept_result();
        @(negedge clk);epoch_has_write=1;expected_address=31'h18000100;
        reach_result();accept_result();
        if(ar_count!=2||check_count!=2||done_count!=2)$fatal(1,"Repeated fences failed");

        // Each explicit caller seal condition is required; no AR repairs it.
        for(k=0;k<5;k=k+1)begin
            reset_case();
            case(k)0:epoch_has_write=0;1:epoch_sealed=0;2:writes_complete=0;
                3:upstream_quiescent=0;4:owner_exclusive=0;default:begin end endcase
            request_fence();expect_fault(1);
            if(m_axi_arvalid||monitor_check_valid)$fatal(1,"Invalid seal issued work");
            check_sticky(1,0,0);
        end
        for(k=0;k<7;k=k+1)begin
            reset_case();final_write_address=k==6?32'h80000000:32'h10000000|(32'h1<<k);
            request_fence();expect_fault(2);
            if(m_axi_arvalid)$fatal(1,"Bad address was truncated/aligned");
            check_sticky(2,0,0);
        end
        for(k=0;k<3;k=k+1)begin
            reset_case();case(k)0:calib_complete=0;1:monitor_healthy=0;2:monitor_fault=1;default:begin end endcase
            request_fence();expect_fault(3);check_sticky(3,0,0);
        end

        // Continuous ownership proof must survive through the final receipt.
        for(k=0;k<4;k=k+1)begin
            reset_case();request_fence();
            @(negedge clk);case(k)0:epoch_sealed=0;1:writes_complete=0;
                2:upstream_quiescent=0;3:owner_exclusive=0;default:begin end endcase
            expect_fault(1);if(!m_axi_arvalid)$fatal(1,"Ownership loss withdrew AR");
            accept_ar();read_response();check_sticky(1,1,0);
        end
        for(k=0;k<3;k=k+1)begin
            reset_case();request_fence();
            @(negedge clk);case(k)0:calib_complete=0;1:monitor_healthy=0;2:monitor_fault=1;default:begin end endcase
            expect_fault(3);if(!m_axi_arvalid)$fatal(1,"Health loss withdrew AR");
            accept_ar();read_response();
            @(negedge clk);calib_complete=1;monitor_healthy=1;monitor_fault=0;
            check_sticky(3,1,0);
        end
        for(k=0;k<5;k=k+1)begin
            reset_case();request_fence();accept_ar();
            case(k)0:m_axi_rid=1;1:m_axi_rresp=1;2:m_axi_rresp=2;
                3:m_axi_rresp=3;4:m_axi_rlast=0;default:begin end endcase
            read_response();expect_fault(4);
            if(k==4)begin
                if(!m_axi_rready)$fatal(1,"Missing RLAST response cannot drain");
                @(negedge clk);m_axi_rlast=1;read_response();
            end
            check_sticky(4,1,0);
        end

        reset_case();request_fence();read_response();expect_fault(4);
        if(!m_axi_arvalid)$fatal(1,"Premature response withdrew AR");
        accept_ar();read_response();check_sticky(4,1,0);
        reset_case();request_fence();
        @(negedge clk);m_axi_arready=1;m_axi_rvalid=1;step();
        @(negedge clk);m_axi_arready=0;m_axi_rvalid=0;
        expect_fault(4);read_response();check_sticky(4,1,0);

        reset_case();monitor_snapshot_valid=1;request_fence();expect_fault(5);
        @(negedge clk);monitor_snapshot_valid=0;check_sticky(5,0,0);
        reset_case();reach_check();snapshot_response();expect_fault(5);
        if(!monitor_check_valid)$fatal(1,"Premature snapshot withdrew check");
        accept_check();snapshot_response();check_sticky(5,1,1);
        reset_case();reach_check();
        @(negedge clk);monitor_check_ready=1;monitor_snapshot_valid=1;step();
        @(negedge clk);monitor_check_ready=0;monitor_snapshot_valid=0;
        expect_fault(5);snapshot_response();check_sticky(5,1,1);

        for(k=0;k<4;k=k+1)begin
            reset_case();reach_check();accept_check();
            case(k)0:monitor_snapshot_irq_mask=7;1:monitor_snapshot_onoff=0;
                2:monitor_snapshot_status=1;3:monitor_snapshot_status=2;default:begin end endcase
            snapshot_response();expect_fault(5);check_sticky(5,1,1);
        end

        // Every pending phase remains held/drainable after timeout.
        reset_case();request_fence();expect_fault(6);
        if(!m_axi_arvalid)$fatal(1,"AR timeout withdrew request");
        accept_ar();read_response();check_sticky(6,1,0);
        reset_case();request_fence();accept_ar();expect_fault(6);
        if(!m_axi_rready)$fatal(1,"R timeout stopped drain");
        read_response();check_sticky(6,1,0);
        reset_case();reach_check();expect_fault(6);
        if(!monitor_check_valid)$fatal(1,"Check timeout withdrew request");
        accept_check();snapshot_response();check_sticky(6,1,1);
        reset_case();reach_check();accept_check();expect_fault(6);
        if(!monitor_snapshot_ready)$fatal(1,"Snapshot timeout stopped drain");
        snapshot_response();check_sticky(6,1,1);

        reset_case();reach_check();@(negedge clk);monitor_fault=1;monitor_healthy=0;
        expect_fault(3);repeat(22)step();
        if(!monitor_check_valid||fault_code!==3)$fatal(1,"Faulted monitor request not retained");
        @(negedge clk);monitor_check_ready=1;step();@(negedge clk);monitor_check_ready=0;
        snapshot_response();check_sticky(3,1,1);

        // A late fault leaves the earlier held receipt stable; it cannot turn
        // a later acceptance into a new successful completion pulse.
        reset_case();reach_result();@(negedge clk);monitor_fault=1;
        expect_fault(3);if(!fence_result_valid)$fatal(1,"Late fault withdrew receipt");
        @(negedge clk);fence_result_ready=1;#1;if(fence_done)$fatal(1,"Fault became success");
        step();@(negedge clk);fence_result_ready=0;check_sticky(3,1,1);
        reset_case();reach_check();accept_check();
        @(negedge clk);monitor_snapshot_valid=1;monitor_fault=1;step();
        @(negedge clk);monitor_snapshot_valid=0;expect_fault(3);
        if(fence_result_valid)$fatal(1,"Same-edge snapshot/fault became receipt");
        reset_case();reach_result();
        @(negedge clk);owner_exclusive=0;fence_result_ready=1;#1;
        if(fence_done)$fatal(1,"Same-edge ACK/ownership loss became success");
        step();@(negedge clk);fence_result_ready=0;expect_fault(1);check_sticky(1,1,1);

        // Whole-domain reset is the only supported cancellation/recovery.
        reset_case();request_fence();reset_case();cases=cases+1;
        request_fence();accept_ar();reset_case();cases=cases+1;
        reach_check();reset_case();cases=cases+1;
        reach_check();accept_check();reset_case();cases=cases+1;
        reach_result();reset_case();cases=cases+1;
`ifndef VERILATOR
        // Four-state source contracts; these are not metastability detection.
        for(k=0;k<2;k=k+1)begin
            reset_case();final_write_address[16]=k==0?1'bx:1'bz;
            request_fence();expect_fault(2);
            reset_case();owner_exclusive=k==0?1'bx:1'bz;
            request_fence();expect_fault(1);
            reset_case();calib_complete=k==0?1'bx:1'bz;
            request_fence();expect_fault(3);
            reset_case();monitor_healthy=k==0?1'bx:1'bz;
            request_fence();expect_fault(3);
            reset_case();monitor_fault=k==0?1'bx:1'bz;
            request_fence();expect_fault(3);
        end
        for(k=0;k<4;k=k+1)begin
            reset_case();request_fence();accept_ar();
            case(k)0:m_axi_rid=4'bx;1:m_axi_rresp=2'bx;2:m_axi_rlast=1'bx;3:m_axi_rvalid=1'bx;default:begin end endcase
            if(k==3)begin step();@(negedge clk);m_axi_rvalid=0;end else read_response();
            expect_fault(4);
        end
        for(k=0;k<3;k=k+1)begin
            reset_case();reach_check();accept_check();
            case(k)0:monitor_snapshot_irq_mask=32'bx;1:monitor_snapshot_onoff=32'bx;
                2:monitor_snapshot_status=32'bx;default:begin end endcase
            snapshot_response();expect_fault(5);
        end
`endif
        $display("PASS mig_write_fence cases=%0d scope=independent_fence_protocol_only controller_ordering_unqualified",cases);
        $finish;
    end
    initial begin repeat(12000)step();$fatal(1,"Fence bench watchdog");end
endmodule
