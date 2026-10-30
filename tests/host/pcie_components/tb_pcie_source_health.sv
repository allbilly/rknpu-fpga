`timescale 1ns/1ps
module tb_pcie_source_health #(
    parameter integer SRC_HALF_PS=2000,
    parameter integer UI_HALF_PS=10000,
    parameter bit RUN_FOUR_STATE=0
);
    localparam integer SYNC_STAGES=3;
    localparam integer HEARTBEAT_BITS=6;
    localparam integer REQUIRED_TRANSITIONS=2;
    localparam integer TIMEOUT_UI_CYCLES=1024;
    localparam integer GUARD_FRESH_CYCLES=4;

    logic ui_clk,pcie_clk;
    logic ui_clock_run=1,pcie_clock_run=0;
    logic joint_reset_n=1;
    logic pcie_link_up=1,pcie_axi_aresetn=1,bridge_ready_ui=1;
    logic jtag_up=1;
    wire source_healthy,clock_alive;
    wire pcie_guard_ready,pcie_guard_failed,pcie_seen_up;
    wire jtag_guard_ready,jtag_guard_failed,jtag_seen_up;
    integer checks=0;

    initial begin
        pcie_clk=0;
        forever begin
            #(SRC_HALF_PS/1000.0);
            if(pcie_clock_run) pcie_clk=~pcie_clk;
            else pcie_clk=0;
        end
    end
    initial begin
        ui_clk=0;
        forever begin
            #(UI_HALF_PS/1000.0);
            if(ui_clock_run) ui_clk=~ui_clk;
            else ui_clk=0;
        end
    end

    rk_pcie_source_health #(
        .SYNC_STAGES(SYNC_STAGES),.HEARTBEAT_BITS(HEARTBEAT_BITS),
        .REQUIRED_TRANSITIONS(REQUIRED_TRANSITIONS),.TIMEOUT_UI_CYCLES(TIMEOUT_UI_CYCLES)
    ) dut (
        .ui_clk(ui_clk),.pcie_clk(pcie_clk),.joint_reset_n(joint_reset_n),
        .pcie_link_up(pcie_link_up),.pcie_axi_aresetn(pcie_axi_aresetn),
        .bridge_ready_ui(bridge_ready_ui),.source_healthy(source_healthy),.clock_alive(clock_alive)
    );
    rk_transport_epoch_guard #(.FRESH_CYCLES(GUARD_FRESH_CYCLES)) pcie_guard (
        .clk(ui_clk),.rst_n(joint_reset_n),.up(source_healthy),
        .ready(pcie_guard_ready),.failed(pcie_guard_failed),.seen_up(pcie_seen_up)
    );
    rk_transport_epoch_guard #(.FRESH_CYCLES(GUARD_FRESH_CYCLES)) jtag_guard (
        .clk(ui_clk),.rst_n(joint_reset_n),.up(jtag_up),
        .ready(jtag_guard_ready),.failed(jtag_guard_failed),.seen_up(jtag_seen_up)
    );

    initial begin
        #1000000;
        $fatal(1,"GLOBAL_TIMEOUT source-health testcase exceeded 1 ms");
    end

    task automatic check(input logic condition,input string label);
        begin checks=checks+1; if(condition!==1'b1) $fatal(1,"CHECK_FAIL %s",label); end
    endtask
    task automatic ui_edges(input integer count);
        integer n;
        begin for(n=0;n<count;n=n+1) begin @(posedge ui_clk); #0.001; end end
    endtask
    task automatic wait_source_health(input integer limit,input string label);
        integer n; logic found;
        begin
            found=0;
            for(n=0;n<limit;n=n+1) begin
                @(posedge ui_clk); #0.001;
                if(source_healthy===1'b1) begin found=1; n=limit; end
            end
            if(!found) $display("HEALTH_TIMEOUT %s alive=%b up=%b axi_reset=%b bridge=%b joint=%b pcie_local=%b ui_local=%b avail=%b count=%0d last=%b transitions=%0d age=%0d sync=%b",label,clock_alive,pcie_link_up,pcie_axi_aresetn,bridge_ready_ui,joint_reset_n,dut.pcie_local_rst_n,dut.ui_local_rst_n,dut.available_ui,dut.heartbeat_count,dut.heartbeat_last,dut.transitions,dut.age,dut.heartbeat_sync);
            check(found,label);
        end
    endtask
    task automatic wait_guard_ready(input integer limit,input string label);
        integer n; logic found;
        begin
            found=0;
            for(n=0;n<limit;n=n+1) begin
                @(posedge ui_clk); #0.001;
                if(pcie_guard_ready===1'b1) begin found=1; n=limit; end
            end
            check(found,label);
        end
    endtask

    initial begin
        joint_reset_n=0; #0.010;
        $display("CONFIG source_half_ps=%0d ui_half_ps=%0d divider_bits=%0d transitions=%0d timeout_ui=%0d stages=%0d four_state=%0d",
            SRC_HALF_PS,UI_HALF_PS,HEARTBEAT_BITS,REQUIRED_TRANSITIONS,TIMEOUT_UI_CYCLES,SYNC_STAGES,RUN_FOUR_STATE);
        // Clock absent during boot; JTAG guard remains usable independently.
        ui_edges(4);
        joint_reset_n=1;
        ui_edges(GUARD_FRESH_CYCLES+3);
        check(jtag_guard_ready===1'b1,"JTAG guard qualifies while PCIe clock absent");
        check(source_healthy===1'b0,"PCIe health stays low with source clock absent at boot");
        check(pcie_guard_ready===1'b0,"PCIe guard cannot qualify before source health");

        // Startup release requires source-clock edges and a fresh heartbeat.
        pcie_clock_run=1;
        wait_source_health(300,"startup heartbeat and bridge/link qualifiers");
        wait_guard_ready(20,"retained PCIe epoch guard arms after health freshness");
        check(clock_alive===1'b1,"heartbeat clock_alive asserted");
        check(pcie_seen_up===1'b1,"guard observed source healthy");

        // Stop PCIe while link/reset remain frozen high: UI timeout must revoke health.
        pcie_clock_run=0;
        ui_edges(TIMEOUT_UI_CYCLES+12);
        check(clock_alive===1'b0,"stopped PCIe clock times out");
        check(source_healthy===1'b0,"health revoked after clock timeout");
        check(pcie_guard_failed===1'b1,"retained guard faults on health loss after prior admission");
        check(pcie_guard_ready===1'b0,"retained guard does not rearm on clock loss");

        // Link-up short pulse while PCIe clock is stopped; async assertion is retained in UI pipe.
        pcie_link_up=0; #1.000;
        check(source_healthy===1'b0,"link loss invalidates health with PCIe clock stopped");
        pcie_link_up=1; #1.000;
        pcie_clock_run=1;
        wait_source_health(300,"requalify after link pulse and resumed PCIe clock");
        check(pcie_guard_failed===1'b1,"healthy level recovery does not clear retained epoch fault");
        check(pcie_guard_ready===1'b0,"healthy level recovery does not restore old epoch admission");

        // PERST pulse while UI clock is stopped: async invalidation, then fresh UI sampling.
        ui_clock_run=0; #1.000;
        pcie_axi_aresetn=0; #1.000;
        check(source_healthy===1'b0,"PERST assertion invalidates health while UI clock stopped");
        pcie_axi_aresetn=1; #20.000;
        check(source_healthy===1'b0,"source remains unqualified while UI clock stopped");
        ui_clock_run=1;
        wait_source_health(300,"fresh UI availability sampling after stopped-UI PERST pulse");
        check(pcie_guard_failed===1'b1,"source requalification still leaves guard failed");

        // Common epoch reset while the PCIe source clock is stopped requires fresh source edges.
        pcie_clock_run=0;
        joint_reset_n=0; #1.000;
        check(pcie_guard_failed===1'b0,"joint reset clears retained guard fault");
        check(source_healthy===1'b0,"joint reset clears PCIe health");
        ui_edges(8);
        joint_reset_n=1;
        ui_edges(12);
        check(source_healthy===1'b0,"stopped PCIe clock prevents local release after joint reset");
        check(pcie_guard_ready===1'b0,"guard remains closed after joint reset without source edges");
        pcie_clock_run=1;
        wait_source_health(300,"source fresh release and heartbeat after stopped-clock reset");
        wait_guard_ready(20,"new epoch qualifies after source resumes");

        // Common epoch reset while UI clock is stopped also requires fresh UI edges.
        ui_clock_run=0; #1.000;
        joint_reset_n=0; #1.000;
        check(source_healthy===1'b0,"UI-stopped joint reset asserts health low");
        joint_reset_n=1; #50.000;
        check(source_healthy===1'b0,"UI release pipe cannot advance while UI clock stopped");
        check(pcie_guard_ready===1'b0,"guard cannot rearm without UI clock edges");
        ui_clock_run=1;
        wait_source_health(300,"fresh UI release, availability, and heartbeat after reset");
        wait_guard_ready(20,"guard re-arms only in the reset new epoch");
        check(pcie_guard_failed===1'b0,"guard remains clear in healthy new epoch");

        if(RUN_FOUR_STATE) begin
            pcie_link_up=1'bx; #0.100;
            ui_edges(1);
            check(source_healthy===1'b0,"unknown link-up fails closed");
            pcie_link_up=1'bz; #0.100;
            ui_edges(1);
            check(source_healthy===1'b0,"high-impedance link-up fails closed");
            pcie_link_up=1;
            ui_edges(6);
            wait_source_health(300,"recover after known link-up restored");

            pcie_axi_aresetn=1'bx; #0.100;
            ui_edges(1);
            check(source_healthy===1'b0,"unknown PCIe AXI reset fails closed");
            pcie_axi_aresetn=1'bz; #0.100;
            ui_edges(1);
            check(source_healthy===1'b0,"high-impedance PCIe AXI reset fails closed");
            pcie_axi_aresetn=1;
            ui_edges(6);
            wait_source_health(300,"recover after known AXI reset release restored");

            bridge_ready_ui=1'bx; #0.100;
            check(source_healthy===1'b0,"unknown bridge readiness fails closed");
            bridge_ready_ui=1'bz; #0.100;
            check(source_healthy===1'b0,"high-impedance bridge readiness fails closed");
            bridge_ready_ui=1; #0.001;
            $display("BRIDGE_RESTORE health=%b alive=%b avail=%b locals=%b/%b link=%b reset=%b",source_healthy,clock_alive,dut.available_ui,dut.pcie_local_rst_n,dut.ui_local_rst_n,pcie_link_up,pcie_axi_aresetn);
            check(source_healthy===1'b1,"known bridge readiness restores only health level");
        end
        check(jtag_guard_ready===1'b1,"PCIe health events do not reset independent JTAG guard");
        check(jtag_guard_failed===1'b0,"JTAG guard remains healthy throughout PCIe events");
        check(jtag_seen_up===1'b1,"JTAG guard independently observed its source");
        $display("PASS_SOURCE_HEALTH checks=%0d pcie_guard_failed=%b pcie_seen_up=%b jtag_ready=%b",checks,pcie_guard_failed,pcie_seen_up,jtag_guard_ready);
        $finish;
    end
endmodule
