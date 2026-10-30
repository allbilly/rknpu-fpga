`timescale 1ns/1ps
module tb_pcie_bridge_reset #(
    parameter integer SYNC_STAGES=3,
    parameter integer RESET_EDGES=8,
    parameter integer SETTLE_EDGES=5
);
    logic epoch_rst_n=1'b1;
    logic s_clk,m_clk;
    logic s_enable=1'b0,m_enable=1'b0;
    wire s_aresetn,m_aresetn,s_ready,m_ready;
    integer s_edges,m_edges,s_post_edges,m_post_edges;
    integer checks=0,epochs=0;
    integer s_raw_edges,m_raw_edges;

    rk_pcie_bridge_reset #(.SYNC_STAGES(SYNC_STAGES),.RESET_EDGES(RESET_EDGES),
        .SETTLE_EDGES(SETTLE_EDGES)) dut(
        .epoch_rst_n(epoch_rst_n),.s_clk(s_clk),.m_clk(m_clk),
        .s_aresetn(s_aresetn),.m_aresetn(m_aresetn),.s_ready(s_ready),.m_ready(m_ready));

    // Unequal, nonharmonic startup clocks: source period 6 ns, destination 10 ns.
    // Disabling a clock holds it low without creating another positive edge.
    always begin #3; if(s_enable)s_clk=~s_clk;else s_clk=1'b0; end
    always begin #5; if(m_enable)m_clk=~m_clk;else m_clk=1'b0; end

    always @(posedge s_clk or negedge dut.s_local_rst_n) begin
        if(!dut.s_local_rst_n)begin s_edges<=0;s_post_edges<=0;end
        else begin s_edges<=s_edges+1;if(s_aresetn)s_post_edges<=s_post_edges+1;end
    end
    always @(posedge m_clk or negedge dut.m_local_rst_n) begin
        if(!dut.m_local_rst_n)begin m_edges<=0;m_post_edges<=0;end
        else begin m_edges<=m_edges+1;if(m_aresetn)m_post_edges<=m_post_edges+1;end
    end

    always @(posedge s_clk or negedge epoch_rst_n)
        if(!epoch_rst_n)s_raw_edges<=0;else s_raw_edges<=s_raw_edges+1;
    always @(posedge m_clk or negedge epoch_rst_n)
        if(!epoch_rst_n)m_raw_edges<=0;else m_raw_edges<=m_raw_edges+1;
    always @(posedge dut.s_local_rst_n)
        if(s_raw_edges!=SYNC_STAGES || s_clk!==1'b1 || s_edges!=0 || dut.s_reset_edges!=0 || dut.s_reset_seen!==1'b0)
            $fatal(1,"source local reset must release after exact fresh synchronizer edges before functional counting");
    always @(posedge dut.m_local_rst_n)
        if(m_raw_edges!=SYNC_STAGES || m_clk!==1'b1 || m_edges!=0 || dut.m_reset_edges!=0 || dut.m_reset_seen!==1'b0)
            $fatal(1,"destination local reset must release after exact fresh synchronizer edges before functional counting");

    always @(posedge s_aresetn)begin
        if(s_edges<RESET_EDGES || !dut.s_reset_seen || !dut.s_peer_reset[SYNC_STAGES-1])
            $fatal(1,"source reset released without fresh local edges and peer reset witness");
    end
    always @(posedge m_aresetn)begin
        if(m_edges<RESET_EDGES || !dut.m_reset_seen || !dut.m_peer_reset[SYNC_STAGES-1])
            $fatal(1,"destination reset released without fresh local edges and peer reset witness");
    end
    always @(posedge s_ready)begin
        if(!s_aresetn || s_post_edges<SETTLE_EDGES)
            $fatal(1,"source ready before local settle and peer settled witness");
    end
    always @(posedge m_ready)begin
        if(!m_aresetn || m_post_edges<SETTLE_EDGES)
            $fatal(1,"destination ready before local settle and peer settled witness");
    end

    task automatic require(input logic condition,input string message);
        begin checks=checks+1;if(condition!==1'b1)$fatal(1,"CHECK_FAIL %s",message);end
    endtask
    task automatic require_async_asserted(input string label);
        begin
            #1;
            require(s_aresetn===1'b0 && m_aresetn===1'b0,label);
            require(s_ready===1'b0 && m_ready===1'b0,{label," stale readiness cleared asynchronously"});
        end
    endtask
    task automatic stop_s;
        begin s_enable=1'b0;wait(s_clk===1'b0);#1;end
    endtask
    task automatic stop_m;
        begin m_enable=1'b0;wait(m_clk===1'b0);#1;end
    endtask
    task automatic wait_ready_pair(input string label);
        integer t;logic seen;
        begin
            seen=1'b0;
            for(t=0;t<4000;t=t+1)begin
                #1;
                if(s_ready===1'b1 && m_ready===1'b1)begin seen=1'b1; t=4000;end
            end
            require(seen,{label," both domains eventually ready"});
            require(s_edges>=RESET_EDGES && m_edges>=RESET_EDGES,{label," minimum fresh reset edges"});
            require(s_post_edges>=SETTLE_EDGES && m_post_edges>=SETTLE_EDGES,{label," minimum local settle edges"});
            require(dut.s_peer_reset[SYNC_STAGES-1] && dut.m_peer_reset[SYNC_STAGES-1],{label," peer reset witnesses"});
            require(dut.s_peer_settled[SYNC_STAGES-1] && dut.m_peer_settled[SYNC_STAGES-1],{label," peer settled witnesses"});
        end
    endtask
    task automatic pulse_joint_reset(input string label);
        begin
            epoch_rst_n=1'b0;epochs=epochs+1;require_async_asserted(label);
            epoch_rst_n=1'b1;
        end
    endtask
    task automatic exact_s_reset_count(input string label);
        begin
            wait(dut.s_local_rst_n===1'b1); #0.100;
            repeat(RESET_EDGES-1)@(posedge s_clk);
            #1;require(s_edges==RESET_EDGES-1 && dut.s_reset_seen===1'b0,{label," no early source reset seen"});
            @(posedge s_clk);#1;
            require(s_edges==RESET_EDGES && dut.s_reset_seen===1'b1,{label," source reset seen on exact edge"});
        end
    endtask
    task automatic exact_m_reset_count(input string label);
        begin
            wait(dut.m_local_rst_n===1'b1); #0.100;
            repeat(RESET_EDGES-1)@(posedge m_clk);
            #1;require(m_edges==RESET_EDGES-1 && dut.m_reset_seen===1'b0,{label," no early destination reset seen"});
            @(posedge m_clk);#1;
            require(m_edges==RESET_EDGES && dut.m_reset_seen===1'b1,{label," destination reset seen on exact edge"});
        end
    endtask
    task automatic exact_s_settle_count;
        integer edge_index;
        begin
            wait(s_aresetn===1'b1);#1;
            require(s_post_edges==0,"source settle count starts at reset release");
            for(edge_index=1;edge_index<=SETTLE_EDGES;edge_index=edge_index+1)begin
                @(posedge s_clk);#1;
                require(s_post_edges==edge_index,"source settle edge counted exactly once");
                if(edge_index<SETTLE_EDGES)require(dut.s_settled===1'b0,"source settle not early");
                else require(dut.s_settled===1'b1,"source settles on exact minimum edge");
            end
        end
    endtask
    task automatic exact_m_settle_count;
        integer edge_index;
        begin
            wait(m_aresetn===1'b1);#1;
            require(m_post_edges==0,"destination settle count starts at reset release");
            for(edge_index=1;edge_index<=SETTLE_EDGES;edge_index=edge_index+1)begin
                @(posedge m_clk);#1;
                require(m_post_edges==edge_index,"destination settle edge counted exactly once");
                if(edge_index<SETTLE_EDGES)require(dut.m_settled===1'b0,"destination settle not early");
                else require(dut.m_settled===1'b1,"destination settles on exact minimum edge");
            end
        end
    endtask

    initial begin
        if(SYNC_STAGES<3 || SYNC_STAGES>10 || RESET_EDGES<2*SYNC_STAGES+2 ||
           RESET_EDGES>65536 || SETTLE_EDGES<SYNC_STAGES+2 || SETTLE_EDGES>65536)begin
            #2;$fatal(1,"INVALID_PARAMETER_DUT_DID_NOT_FAIL");
        end else begin
            // A shared transaction epoch must be asserted before startup clocks run.
            s_clk=1'b0;m_clk=1'b0;s_enable=1'b0;m_enable=1'b0;epoch_rst_n=1'b0;#1;
            require_async_asserted("initial common reset");epochs=1;

            // Destination starts alone. Its local reset count reaches eight, but
            // neither bridge reset can release without the stopped source witness.
            m_enable=1'b1;epoch_rst_n=1'b1;
            exact_m_reset_count("initial source stopped");
            repeat(RESET_EDGES)@(posedge m_clk);
            #1;
            require(dut.m_reset_seen===1'b1 && dut.s_reset_seen===1'b0,"destination reset counted while source clock stopped");
            require(s_aresetn===1'b0 && m_aresetn===1'b0 && !s_ready && !m_ready,
                "stopped source blocks both reset releases and readiness");
            $display("PASS_STOPPED_SOURCE_STARTUP");

            // Start the faster source. Freeze it after local settle while the
            // slower destination has not settled; destination ready may rise first.
            s_enable=1'b1;exact_s_reset_count("initial peer witness pending");
            exact_s_settle_count();stop_s();
            require(s_ready===1'b0,"source readiness waits for destination settled witness");
            exact_m_settle_count();
            require(m_ready===1'b1 && s_ready===1'b0,"destination ready may precede source ready");
            $display("PASS_STAGGERED_READY");
            s_enable=1'b1;wait_ready_pair("epoch 1");

            // A stopped clock after readiness does not clear startup-history
            // ready. Clock liveness belongs to a separate health/quarantine guard.
            stop_m();stop_s();#20;
            require(s_ready===1'b1 && m_ready===1'b1,"ready remains high after both clocks stop");
            require(s_aresetn===1'b1 && m_aresetn===1'b1,"reset release remains high after startup");
            s_enable=1'b1;m_enable=1'b1;#12;
            $display("PASS_READY_IS_STARTUP_HISTORY");

            // Joint reset asserted while destination clock is stopped; its stale
            // ready state clears asynchronously and cannot recover alone.
            stop_m();pulse_joint_reset("epoch 2 destination stopped");
            exact_s_reset_count("epoch 2 destination stopped");
            repeat(RESET_EDGES)@(posedge s_clk);#1;
            require(s_aresetn===1'b0 && m_aresetn===1'b0 && !s_ready && !m_ready,
                "destination-stopped reset requires resumed peer edges");
            $display("PASS_STOPPED_DESTINATION_RESET_RECOVERY");
            m_enable=1'b1;
            fork exact_s_settle_count(); exact_m_settle_count(); join
            wait_ready_pair("epoch 2");

            // Symmetric joint reset with the source clock stopped.
            stop_s();pulse_joint_reset("epoch 3 source stopped");
            exact_m_reset_count("epoch 3 source stopped");
            repeat(RESET_EDGES)@(posedge m_clk);#1;
            require(s_aresetn===1'b0 && m_aresetn===1'b0 && !s_ready && !m_ready,
                "source-stopped reset requires resumed peer edges");
            $display("PASS_STOPPED_SOURCE_RESET_RECOVERY");
            s_enable=1'b1;
            fork exact_s_settle_count(); exact_m_settle_count(); join
            wait_ready_pair("epoch 3");

            require(epochs==3,"three distinct reset epochs");
            require(s_ready===1'b1 && m_ready===1'b1,"all final startup histories ready");
            $display("PASS_PCIE_BRIDGE_RESET checks=%0d epochs=%0d sync=%0d reset_edges=%0d settle_edges=%0d stagger=1 startup_history_only=1",
                checks,epochs,SYNC_STAGES,RESET_EDGES,SETTLE_EDGES);
            $finish;
        end
    end
endmodule
