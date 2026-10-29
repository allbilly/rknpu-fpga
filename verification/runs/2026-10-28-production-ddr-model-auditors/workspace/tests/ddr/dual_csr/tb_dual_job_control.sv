`timescale 1ns/1ps
module tb_dual_job_control;
    logic clk;
    initial clk=0;
    always #5 clk=~clk;
    logic rst_n=0, memory_ready=1;
    logic [31:0] s_axil_awaddr=0, s_axil_wdata=0, s_axil_araddr=0;
    logic [2:0] s_axil_awprot=0, s_axil_arprot=0;
    logic [3:0] s_axil_wstrb=4'hf;
    logic s_axil_awvalid=0,s_axil_wvalid=0,s_axil_bready=0;
    logic s_axil_arvalid=0,s_axil_rready=0;
    wire s_axil_awready,s_axil_wready,s_axil_bvalid;
    wire s_axil_arready,s_axil_rvalid;
    wire [1:0] s_axil_bresp,s_axil_rresp;
    wire [31:0] s_axil_rdata;
    wire irq,scheduler_fault,control_owned,control_owner_cmac;
    wire core_start_valid,core_start_cmac;
    wire [31:0] core_start_address,core_start_amount;
    logic core_ew_start_ready=1,core_cmac_start_ready=1;
    logic core_busy=0,core_done=0,core_error=0;
    logic [7:0] core_error_code=0;
    logic [31:0] core_completed_tasks=0;
    integer launch_count;
    logic launched_cmac;
    logic [31:0] launched_address,launched_amount;

    rk_dual_job_control dut(.*);

    always @(posedge clk) begin
        if(!rst_n)begin
            launch_count<=0;launched_cmac<=0;launched_address<=0;launched_amount<=0;
        end else if(core_start_valid)begin
            launch_count<=launch_count+1;launched_cmac<=core_start_cmac;
            launched_address<=core_start_address;launched_amount<=core_start_amount;
        end
    end

    task automatic write_csr(input logic [31:0] address, input logic [31:0] data,
                             input logic [1:0] expected_resp=0,
                             input logic [3:0] strb=4'hf,
                             input logic [2:0] prot=0,
                             input bit split=0);
        logic [1:0] observed;
        @(negedge clk);
        s_axil_awaddr=address;s_axil_wdata=data;s_axil_awprot=prot;
        s_axil_wstrb=strb;s_axil_awvalid=1;s_axil_wvalid=!split;
        if(split)begin
            do @(posedge clk);while(!s_axil_awready);
            @(negedge clk);s_axil_awvalid=0;
            s_axil_wvalid=1;
            do @(posedge clk);while(!s_axil_wready);
            @(negedge clk);s_axil_wvalid=0;
        end else begin
            do @(posedge clk);while(!(s_axil_awready&&s_axil_wready));
            @(negedge clk);s_axil_awvalid=0;s_axil_wvalid=0;
        end
        wait(s_axil_bvalid);
        observed=s_axil_bresp;
        repeat(2)begin
            @(negedge clk);
            if(!s_axil_bvalid||s_axil_bresp!==observed)$fatal(1,"B response unstable under backpressure");
        end
        if(observed!==expected_resp)$fatal(1,"write %08x expected BRESP %b got %b",address,expected_resp,observed);
        @(negedge clk);s_axil_bready=1;
        @(posedge clk);
        @(negedge clk);s_axil_bready=0;
    endtask

    task automatic read_csr(input logic [31:0] address,input logic [31:0] expected_data,
                            input logic [1:0] expected_resp=0,input logic [2:0] prot=0);
        logic [31:0] observed_data;logic [1:0] observed_resp;
        @(negedge clk);s_axil_araddr=address;s_axil_arprot=prot;s_axil_arvalid=1;
        do @(posedge clk);while(!s_axil_arready);
        @(negedge clk);s_axil_arvalid=0;
        wait(s_axil_rvalid);observed_data=s_axil_rdata;observed_resp=s_axil_rresp;
        repeat(2)begin
            @(negedge clk);
            if(!s_axil_rvalid||s_axil_rresp!==observed_resp||s_axil_rdata!==observed_data)
                $fatal(1,"R response unstable under backpressure");
        end
        if(observed_resp!==expected_resp||observed_data!==expected_data)
            $fatal(1,"read %08x expected %b/%08x got %b/%08x",address,expected_resp,expected_data,observed_resp,observed_data);
        @(negedge clk);s_axil_rready=1;
        @(posedge clk);
        @(negedge clk);s_axil_rready=0;
    endtask

    task automatic descriptor(input bit cmac,input logic [31:0] address,
                              input logic [31:0] amount,input logic [31:0] tag);
        logic [31:0] base;
        base=cmac?32'h100:0;
        write_csr(base+32'h10,address,0,4'hf,0,1);
        write_csr(base+32'h14,amount);
        write_csr(base+32'h18,tag);
    endtask

    task automatic submit_and_check(input bit cmac,input logic [31:0] address,
                                    input logic [31:0] amount);
        logic [31:0] base;
        integer prior_launches;
        base=cmac?32'h100:0;
        prior_launches=launch_count;
        write_csr(base+32'h0c,1);
        repeat(2)@(negedge clk);
        if(launch_count!=prior_launches+1||launched_cmac!==cmac||launched_address!==address||
           launched_amount!==amount)$fatal(1,"wrong selected core launch namespace or descriptor");
        @(negedge clk);core_busy=1;
        @(posedge clk);
        @(negedge clk);
        if(!control_owned||control_owner_cmac!==cmac)$fatal(1,"global owner not captured");
    endtask

    task automatic complete_delayed(input bit cmac,input logic [31:0] tasks,
                                    input logic [31:0] tag);
        logic [31:0] base;
        base=cmac?32'h100:0;
        // Completion is reported while the modeled DDR engine is still busy;
        // ownership must remain held until the caller retires traffic and ACKs.
        @(negedge clk);core_completed_tasks=tasks;core_done=1;
        @(negedge clk);core_done=0;
        repeat(3)begin
            @(negedge clk);
            if(!control_owned||control_owner_cmac!==cmac||!irq)
                $fatal(1,"owner/result released before delayed core retirement");
        end
        core_busy=0;
        read_csr(base+32'h1c,tag);
        read_csr(base+32'h20,tasks);
        read_csr(base+32'h24,0);
    endtask

    task automatic reset_all;
        @(negedge clk);rst_n=0;
        s_axil_awvalid=0;s_axil_wvalid=0;s_axil_bready=0;
        s_axil_arvalid=0;s_axil_rready=0;
        core_busy=0;core_done=0;core_error=0;core_error_code=0;core_completed_tasks=0;
        core_ew_start_ready=1;core_cmac_start_ready=1;memory_ready=1;
        repeat(3)@(negedge clk);
        if(irq||scheduler_fault||control_owned||core_start_valid)$fatal(1,"stale state during joint reset");
        rst_n=1;
        repeat(2)@(negedge clk);
    endtask

    initial begin
        reset_all();
        read_csr(32'h00,32'h524b4144);read_csr(32'h04,32'h00010000);
        read_csr(32'h100,32'h524b4344);read_csr(32'h104,32'h00010000);

        // Namespace-specific readiness: only the selected engine may accept.
        core_ew_start_ready=0;core_cmac_start_ready=1;
        descriptor(1,32'h10200000,17,32'hc002);
        descriptor(0,32'h100e0000,35,32'he001);
        write_csr(32'h0c,1,2);
        if(control_owned||core_start_valid)$fatal(1,"unready EW bank acquired global owner");
        core_ew_start_ready=1;
        submit_and_check(0,32'h100e0000,35);

        // Wrong-bank ACK is rejected and must not transfer global ownership.
        write_csr(32'h10c,2,2);
        if(!control_owned||control_owner_cmac)$fatal(1,"wrong-bank ACK changed owner");
        // The competing descriptor write is required to be blocked while EW owns.
        write_csr(32'h110,32'h100e0100,2);
        // A competing submit must also fail without creating a launch.
        write_csr(32'h10c,1,2);

        complete_delayed(0,2,32'he001);
        if(!control_owned||control_owner_cmac)$fatal(1,"readback lost EW owner");
        // ACK from the selected bank releases only after completion/readback.
        write_csr(32'h0c,2);
        repeat(3)@(negedge clk);
        if(control_owned||irq)$fatal(1,"selected EW ACK did not release owner");

        // Reverse readiness and prove CMAC namespace/descriptor are selected.
        core_ew_start_ready=0;core_cmac_start_ready=1;
        descriptor(1,32'h10200000,17,32'hc002);
        submit_and_check(1,32'h10200000,17);
        complete_delayed(1,4,32'hc002);
        write_csr(32'h10c,2);
        repeat(3)@(negedge clk);
        if(control_owned||irq)$fatal(1,"selected CMAC ACK did not release owner");

        // Unsupported namespace, read-only writes, malformed strobes/protection.
        read_csr(32'h200,0,3);
        write_csr(32'h200,1,3);
        write_csr(0,1,2);
        write_csr(32'h110,1,2,4'h7);
        write_csr(32'h110,1,2,4'hf,3'b001);
        read_csr(32'h100,0,2,3'b001);

        // Shared late core/platform fault preserves an error result and forbids ACK.
        core_ew_start_ready=1;
        descriptor(0,32'h100e0000,35,32'he002);
        begin: check_late_launch
            integer prior;
            prior=launch_count;
        write_csr(32'h0c,1);
            if(launch_count!=prior+1||launched_address!==32'h100e0000||launched_amount!==35||launched_cmac)
                $fatal(1,"late-fault EW job failed to launch correctly");
        end
        @(negedge clk);core_busy=1;
        @(negedge clk);core_error=1;core_error_code=8'h2a;
        @(negedge clk);core_busy=0;
        repeat(2)@(negedge clk);
        if(!control_owned||!irq)$fatal(1,"fault result/owner missing");
        read_csr(32'h24,32'h2a);
        write_csr(32'h0c,2,2);
        if(!control_owned||!irq)$fatal(1,"fault result released by ACK");

        // Joint reset is the only recovery from the sticky failed result.
        reset_all();
        read_csr(32'h00,32'h524b4144);read_csr(32'h100,32'h524b4344);
        $display("PASS dual job control namespace identity readiness global owner result readback ACK errors late fault joint reset");
        $finish;
    end
    initial begin #1000000;$fatal(1,"dual job control timeout");end
endmodule
