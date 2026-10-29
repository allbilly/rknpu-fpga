// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Independent clocks/reset-pin model; no MIG primitives, memory, drain or jobs.
module tb_mig_reset_coordinator #(
    parameter int unsigned DUT_SYS_HOLD_CYCLES=64,
    parameter int unsigned DUT_UI_FRESH_CYCLES=4,
    parameter int unsigned DUT_SYNC_STAGES=3,
    parameter int unsigned DUT_WAIT_TIMEOUT_CYCLES=96
);
    logic sys_clk,c0_ui_clk,c1_ui_clk;
    logic run0,run1,cfg_reset,reset_req_valid,c0_ui_clk_sync_rst,c1_ui_clk_sync_rst;
    wire reset_req_ready,mig_sys_rst_n,sys_clients_rst_n,c0_clients_rst_n,c1_clients_rst_n;
    wire c0_aresetn,c1_aresetn,sequence_busy,sequence_complete,admission_blocked,sequence_fault;
    wire [7:0] sequence_fault_code;
    integer cases;
    initial begin sys_clk=0;c0_ui_clk=0;c1_ui_clk=0;end
    always #10 sys_clk=~sys_clk;
    always #3.5 if(run0) c0_ui_clk=~c0_ui_clk; else c0_ui_clk=0;
    always #5.5 if(run1) c1_ui_clk=~c1_ui_clk; else c1_ui_clk=0;
    rk_mig_reset_coordinator #(.SYS_HOLD_CYCLES(DUT_SYS_HOLD_CYCLES),.UI_FRESH_CYCLES(DUT_UI_FRESH_CYCLES),
        .SYNC_STAGES(DUT_SYNC_STAGES),.WAIT_TIMEOUT_CYCLES(DUT_WAIT_TIMEOUT_CYCLES)) dut(.*);

    task automatic tick;
        @(posedge sys_clk);#1;
        if (c0_aresetn!==c0_clients_rst_n || c1_aresetn!==c1_clients_rst_n)
            $fatal(1,"MIG AXI reset branch alias changed");
        if (sequence_complete && (admission_blocked || sequence_fault || !mig_sys_rst_n ||
            !sys_clients_rst_n || !c0_clients_rst_n || !c1_clients_rst_n))
            $fatal(1,"Completion without every actual reset branch released");
        if (!sequence_complete && admission_blocked!==1'b1) $fatal(1,"Admission before completion");
    endtask
    task automatic configure;
        @(negedge sys_clk);
        cfg_reset=1;reset_req_valid=0;run0=1;run1=1;c0_ui_clk_sync_rst=1;c1_ui_clk_sync_rst=1;
        #1;
        if (mig_sys_rst_n!==0 || sys_clients_rst_n!==0 || c0_clients_rst_n!==0 || c1_clients_rst_n!==0 ||
            sequence_complete!==0 || admission_blocked!==1) $fatal(1,"Configuration reset not asserted");
        repeat(3) tick();
        @(negedge sys_clk);cfg_reset=0;
    endtask
    task automatic hold_interval;
        // cfg_reset/request release leaves the counter at zero. Exactly64 SYS edges.
        for (integer i=0;i<64;i=i+1) begin
            tick();
            if (i<63 && mig_sys_rst_n!==0) $fatal(1,"MIG reset hold shortened");
            if (sys_clients_rst_n || c0_clients_rst_n || c1_clients_rst_n || sequence_complete || !admission_blocked)
                $fatal(1,"Client reset released during global hold");
        end
        if (mig_sys_rst_n!==1 || !sequence_busy || sequence_fault) $fatal(1,"MIG release depended on UI status/clock");
    endtask
    task automatic lower_ui_resets;
        @(negedge sys_clk);c0_ui_clk_sync_rst=0;c1_ui_clk_sync_rst=0;
    endtask
    task automatic await_complete;
        integer n;
        n=0;
        while(!sequence_complete && !sequence_fault && n<120) begin tick();n=n+1;end
        if (!sequence_complete || sequence_fault || sequence_busy || admission_blocked || !reset_req_ready)
            $fatal(1,"No complete reset sequence code=%0d",sequence_fault_code);
        cases=cases+1;
    endtask
    task automatic healthy_sequence;
        configure();hold_interval();lower_ui_resets();await_complete();
    endtask
    task automatic request_epoch(input bit assert0,input bit assert1);
        if (!reset_req_ready) $fatal(1,"Reset request not ready");
        @(negedge sys_clk);
        c0_ui_clk_sync_rst=assert0;c1_ui_clk_sync_rst=assert1;reset_req_valid=1;
        #1;
        if (sequence_complete!==0 || admission_blocked!==1) $fatal(1,"Old completion survived request");
        tick();
        if (mig_sys_rst_n!==0 || sys_clients_rst_n!==0 || c0_clients_rst_n!==0 || c1_clients_rst_n!==0 || sequence_fault)
            $fatal(1,"Explicit request did not reset all owned domains");
        @(negedge sys_clk);reset_req_valid=0;
    endtask
    task automatic expect_fault(input logic [7:0] code,input bit released);
        integer n;
        n=0;
        while(!sequence_fault && n<140) begin tick();n=n+1;end
        if (!sequence_fault || sequence_fault_code!==code || sequence_complete || !admission_blocked || sequence_busy || !reset_req_ready)
            $fatal(1,"Fault mismatch expected%0d actual%0d",code,sequence_fault_code);
        if (!released && (mig_sys_rst_n || sys_clients_rst_n || c0_clients_rst_n || c1_clients_rst_n))
            $fatal(1,"Pre-release failure did not retain coordinated reset");
        if (released && (!mig_sys_rst_n || !sys_clients_rst_n || !c0_clients_rst_n || !c1_clients_rst_n))
            $fatal(1,"Health fault withdrew a released reset branch");
        repeat(5) begin
            tick();
            if (!sequence_fault || sequence_fault_code!==code || sequence_complete || !admission_blocked)
                $fatal(1,"Fault automatically retried or cleared");
        end
        cases=cases+1;
    endtask
    task automatic stop0;
        @(negedge c0_ui_clk);run0=0;
    endtask
    task automatic stop1;
        @(negedge c1_ui_clk);run1=0;
    endtask

    initial begin
        cases=0;run0=1;run1=1;cfg_reset=1;reset_req_valid=0;c0_ui_clk_sync_rst=1;c1_ui_clk_sync_rst=1;
        healthy_sequence();
        // Repeated explicit epochs keep reset history separate.
        request_epoch(1,1);hold_interval();lower_ui_resets();await_complete();
        // A previous successful epoch must not supply either new HIGH witness.
        request_epoch(0,1);hold_interval();lower_ui_resets();expect_fault(1,0);
        request_epoch(1,1);hold_interval();lower_ui_resets();await_complete();
        request_epoch(1,0);hold_interval();lower_ui_resets();expect_fault(1,0);

        // Global hold/release proceeds even when either UI clock is absent.
        configure();run0=0;hold_interval();lower_ui_resets();repeat(12) tick();
        if (sequence_complete || sys_clients_rst_n || c0_clients_rst_n || c1_clients_rst_n)
            $fatal(1,"Stopped UI0 bypassed fresh-edge barrier");
        run0=1;await_complete();
        configure();run1=0;hold_interval();lower_ui_resets();repeat(12) tick();
        if (sequence_complete || sys_clients_rst_n || c0_clients_rst_n || c1_clients_rst_n)
            $fatal(1,"Stopped UI1 bypassed fresh-edge barrier");
        run1=1;await_complete();
        configure();run0=0;run1=0;hold_interval();lower_ui_resets();expect_fault(1,0);
        // Good pin levels/clocks cannot automatically clear a failed epoch.
        run0=1;run1=1;c0_ui_clk_sync_rst=1;c1_ui_clk_sync_rst=1;repeat(8) tick();
        if (!sequence_fault || mig_sys_rst_n || sequence_complete) $fatal(1,"Automatic reset retry");
        request_epoch(1,1);hold_interval();lower_ui_resets();await_complete();

        // Assertion without subsequent reset release is also insufficient.
        configure();hold_interval();expect_fault(1,0);
        // A reset reassertion during qualification fails before any release.
        configure();run1=0;hold_interval();lower_ui_resets();repeat(6) tick();
        @(negedge sys_clk);c0_ui_clk_sync_rst=1;expect_fault(3,0);

        // Later reset-pin faults NEVER locally clear a potentially active client.
        healthy_sequence();@(negedge sys_clk);c0_ui_clk_sync_rst=1;expect_fault(3,1);
        @(negedge sys_clk);c0_ui_clk_sync_rst=0;repeat(6) tick();
        if (!sequence_fault || !c0_clients_rst_n || !c1_clients_rst_n || !mig_sys_rst_n)
            $fatal(1,"Pin recovery changed sticky fault/released reset");
        request_epoch(1,1);hold_interval();lower_ui_resets();await_complete();
        @(negedge sys_clk);c1_ui_clk_sync_rst=1;expect_fault(4,1);

        // Stop UI0 after fresh cycles, before it can consume the release permit.
        // Both fresh witnesses can cross SYS, but UI0's actual branch ACK cannot.
        configure();hold_interval();lower_ui_resets();
        // Local reset bridge + assertion synchronizer + four fresh cycles,
        // then one extra edge to make the witness stable before stopping.
        repeat(2*DUT_SYNC_STAGES+DUT_UI_FRESH_CYCLES+1) @(posedge c0_ui_clk);stop0();
        begin
            integer n;
            n=0;
            while(!sequence_fault && n<140) begin tick();n=n+1;end
            if (!sequence_fault || sequence_fault_code!==2 || sequence_complete || !admission_blocked ||
                !mig_sys_rst_n || !sys_clients_rst_n || c0_clients_rst_n || !c1_clients_rst_n)
                $fatal(1,"Missing release ACK was invented or partially reset released clients");
            repeat(5) tick();
            if (!mig_sys_rst_n || !sys_clients_rst_n || !c1_clients_rst_n) $fatal(1,"Timeout withdrew a released branch");
            cases=cases+1;
        end
        // A partly transferred permit must be revoked while its UI clock is
        // stopped. Observe only public branch outputs, then provide one UI0
        // edge: it can sample the grant but cannot yet release its branch.
        configure();hold_interval();lower_ui_resets();
        repeat(2*DUT_SYNC_STAGES+DUT_UI_FRESH_CYCLES+1) @(posedge c0_ui_clk);stop0();
        begin
            integer n;
            n=0;
            while(!(sys_clients_rst_n && c1_clients_rst_n) && !sequence_fault && n<60) begin tick();n=n+1;end
            if (!sys_clients_rst_n || !c1_clients_rst_n || c0_clients_rst_n || sequence_fault)
                $fatal(1,"Public release barrier not reached for stale-permit control");
            @(negedge sys_clk);#0.25;run0=1;
            @(posedge c0_ui_clk);stop0();
            if (c0_clients_rst_n) $fatal(1,"One permit-transfer edge released UI0");
            n=0;
            while(!sequence_fault && n<140) begin tick();n=n+1;end
            if (!sequence_fault || sequence_fault_code!==2 || sequence_complete || !admission_blocked ||
                !mig_sys_rst_n || !sys_clients_rst_n || c0_clients_rst_n || !c1_clients_rst_n)
                $fatal(1,"Partial-permit timeout changed coordinated-reset policy");
            cases=cases+1;
            @(negedge sys_clk);#0.25;run0=1;
            repeat(12) begin
                tick();
                if (c0_clients_rst_n || !c1_clients_rst_n || !sys_clients_rst_n || !mig_sys_rst_n ||
                    !sequence_fault || sequence_fault_code!==2 || sequence_complete || !admission_blocked)
                    $fatal(1,"Revoked stale permit released UI0 after fault");
            end
            cases=cases+1;
        end
        request_epoch(1,1);hold_interval();lower_ui_resets();await_complete();
        // Explicit reset must assert without a single UI edge, including stale ACKs.
        run0=1;healthy_sequence();stop0();stop1();request_epoch(1,1);
        hold_interval();lower_ui_resets();expect_fault(1,0);
        run0=1;run1=1;request_epoch(1,1);hold_interval();lower_ui_resets();await_complete();
        stop0();stop1();@(negedge sys_clk);cfg_reset=1;#1;
        if (mig_sys_rst_n!==0 || c0_clients_rst_n!==0 || c1_clients_rst_n!==0 || sys_clients_rst_n!==0 ||
            sequence_complete!==0 || admission_blocked!==1) $fatal(1,"Asynchronous cfg reset waited for a UI clock");
        cases=cases+1;

`ifdef __ICARUS__
        healthy_sequence();@(negedge sys_clk);c0_ui_clk_sync_rst=1'bx;expect_fault(5,1);
        healthy_sequence();@(negedge sys_clk);c0_ui_clk_sync_rst=1'bz;expect_fault(5,1);
        healthy_sequence();@(negedge sys_clk);c1_ui_clk_sync_rst=1'bx;expect_fault(6,1);
        healthy_sequence();@(negedge sys_clk);c1_ui_clk_sync_rst=1'bz;expect_fault(6,1);
        configure();run1=0;hold_interval();lower_ui_resets();
        @(negedge sys_clk);c0_ui_clk_sync_rst=1'bx;expect_fault(5,0);
`endif
        $display("PASS mig_reset_coordinator cases=%0d sys_hold=64 ui_fresh=4 sync=3 scope=owned_reset_sequence_model_only",cases);
        $finish;
    end
    initial begin repeat(8000) @(posedge sys_clk);$fatal(1,"Reset coordinator watchdog");end
endmodule
