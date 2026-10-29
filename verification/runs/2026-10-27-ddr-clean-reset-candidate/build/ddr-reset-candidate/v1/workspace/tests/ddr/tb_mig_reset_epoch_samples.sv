// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Public input/output tests of stale status and short timeout boundaries.
module tb_mig_reset_epoch_samples;
    logic sys_clk,c0_ui_clk,c1_ui_clk,cfg_reset,reset_req_valid;
    logic c0_ui_clk_sync_rst,c1_ui_clk_sync_rst;
    wire reset_req_ready,mig_sys_rst_n,sys_clients_rst_n,c0_clients_rst_n,c1_clients_rst_n;
    wire c0_aresetn,c1_aresetn,sequence_busy,sequence_complete,admission_blocked,sequence_fault;
    wire [7:0] sequence_fault_code;
    wire short_ready,short_mig,short_sys,short_c0,short_c1,short_a0,short_a1;
    wire short_busy,short_complete,short_block,short_fault;
    wire [7:0] short_code;
    integer cases;
    always #10 sys_clk=~sys_clk;
    always #3.5 c0_ui_clk=~c0_ui_clk;
    always #5.5 c1_ui_clk=~c1_ui_clk;
    rk_mig_reset_coordinator #(.SYS_HOLD_CYCLES(1),.UI_FRESH_CYCLES(2),
        .SYNC_STAGES(5),.WAIT_TIMEOUT_CYCLES(96)) dut(.*);
    rk_mig_reset_coordinator #(.SYS_HOLD_CYCLES(1),.UI_FRESH_CYCLES(2),
        .SYNC_STAGES(8),.WAIT_TIMEOUT_CYCLES(2)) short_timeout (
        .sys_clk,.cfg_reset,.reset_req_valid(1'b0),.reset_req_ready(short_ready),
        .c0_ui_clk,.c1_ui_clk,.c0_ui_clk_sync_rst(1'b1),.c1_ui_clk_sync_rst(1'b1),
        .mig_sys_rst_n(short_mig),.sys_clients_rst_n(short_sys),
        .c0_clients_rst_n(short_c0),.c1_clients_rst_n(short_c1),
        .c0_aresetn(short_a0),.c1_aresetn(short_a1),.sequence_busy(short_busy),
        .sequence_complete(short_complete),.admission_blocked(short_block),
        .sequence_fault(short_fault),.sequence_fault_code(short_code));
    task automatic tick;
        @(posedge sys_clk);#1;
        if(sequence_complete && (sequence_fault||admission_blocked||
            !mig_sys_rst_n||sequence_busy||!reset_req_ready||
            !sys_clients_rst_n||!c0_clients_rst_n||!c1_clients_rst_n))
            $fatal(1,"Epoch completed before actual branch acknowledgments");
        if(c0_aresetn!==c0_clients_rst_n||c1_aresetn!==c1_clients_rst_n||
            short_a0!==short_c0||short_a1!==short_c1||short_sys||short_c0||short_c1||
            (short_ready&&short_busy))$fatal(1,"Reset branch/timeout lifecycle contract changed");
    endtask
    task automatic configure;
        @(negedge sys_clk);cfg_reset=1;reset_req_valid=0;
        c0_ui_clk_sync_rst=1;c1_ui_clk_sync_rst=1;
        repeat(3)tick();
        @(negedge sys_clk);cfg_reset=0;
    endtask
    task automatic healthy;
        configure();
        // SYNC_STAGES exceeds hold1: maintain actual assertions long enough.
        repeat(4)tick();
        if(!short_fault||short_code!=1||!short_block||short_complete||short_mig)
            $fatal(1,"Unqualified samples postponed the independent reset timeout");
        repeat(6)tick();
        @(negedge sys_clk);c0_ui_clk_sync_rst=0;c1_ui_clk_sync_rst=0;
        begin
            integer n=0;
            while(!sequence_complete&&!sequence_fault&&n<100)begin tick();n++;end
            if(!sequence_complete||sequence_fault)$fatal(1,"Fresh short-hold epoch failed");
        end
        cases++;
    endtask
    task automatic fault_code(input logic [7:0] expected);
        integer n=0;
        while(!sequence_fault&&!sequence_complete&&n<140)begin tick();n++;end
        if(!sequence_fault||sequence_fault_code!=expected||sequence_complete||!admission_blocked)
            $fatal(1,"Stale status admitted a new epoch expected_fault=%0d actual=%0d",expected,sequence_fault_code);
        cases++;
    endtask
    task automatic stale_recovery(input bit channel);
        if(!reset_req_ready)$fatal(1,"Previous healthy epoch is not requestable");
        // Leave a real HIGH in the previous epoch's status pipeline.
        @(negedge sys_clk);
        if(channel)c1_ui_clk_sync_rst=1;else c0_ui_clk_sync_rst=1;
        begin
            integer n=0;
            while(!sequence_fault&&n<30)begin tick();n++;end
            if(!sequence_fault||sequence_fault_code!=(channel?4:3))
                $fatal(1,"Previous epoch health fault missing");
        end
        // That channel never asserts HIGH during the next requested epoch.
        // The other channel supplies a real new HIGH throughout this trial.
        @(negedge sys_clk);c0_ui_clk_sync_rst=channel;c1_ui_clk_sync_rst=!channel;
        reset_req_valid=1;#1;
        if(sequence_complete||!admission_blocked)$fatal(1,"Old public completion survived request");
        tick();@(negedge sys_clk);reset_req_valid=0;
        repeat(12)tick();
        @(negedge sys_clk);c0_ui_clk_sync_rst=0;c1_ui_clk_sync_rst=0;
        fault_code(1);
    endtask
    initial begin
        sys_clk=0;c0_ui_clk=0;c1_ui_clk=0;cfg_reset=1;reset_req_valid=0;
        c0_ui_clk_sync_rst=1;c1_ui_clk_sync_rst=1;cases=0;
        healthy();stale_recovery(0);
        healthy();stale_recovery(1);
        healthy();
        $display("PASS mig_reset_epoch_samples cases=%0d hold=1 sync=5 timeout_sync8=2 scope=public_status_only",cases);
        $finish;
    end
    initial begin #200000;$fatal(1,"Epoch status bench hung");end
endmodule
