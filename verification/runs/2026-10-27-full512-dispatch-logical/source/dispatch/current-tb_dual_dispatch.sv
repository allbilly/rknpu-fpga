// CONTROL TEST ONLY. Child engines are deliberately handshake-only models from
// control_models.sv; this test does not qualify arithmetic, full512, MIG, DDR,
// ECC, CDC timing, or physical execution.
`timescale 1ns/1ps
module tb_dual_dispatch;
    logic ui_clk=0, core_clk=0;
    always #5 ui_clk=~ui_clk;
    always #7 core_clk=~core_clk;

    logic ui_rst_n=0, core_rst_n=0, ui_admission_enable=1, ui_rearm_permit=1;
    logic ui_start_valid=0, ui_start_cmac=0;
    logic [31:0] ui_start_address=0, ui_start_amount=0;
    wire ui_start_ready, ui_ew_start_ready, ui_cmac_start_ready;
    wire ui_result_valid, ui_result_error;
    wire [7:0] ui_result_code;
    wire [31:0] ui_result_tasks;
    logic ui_result_ready=0;
    wire ui_fault;
    wire ui_mem_req_valid, ui_mem_req_write;
    wire [31:0] ui_mem_req_addr;
    wire [15:0] ui_mem_req_wdata;
    logic ui_mem_req_ready=0, ui_mem_rsp_valid=0, ui_mem_rsp_error=0;
    logic [15:0] ui_mem_rsp_rdata=0;
    wire ui_mem_rsp_ready;
    logic simulated_readback_ack=0;

    rk_dual_async_dispatch #(.TIMEOUT_CYCLES(8),.MAX_TASKS(32),.SYNC_STAGES(3)) dut (
        .ui_clk,.ui_rst_n,.ui_admission_enable,.ui_rearm_permit,
        .ui_start_valid,.ui_start_cmac,.ui_start_ready,.ui_ew_start_ready,.ui_cmac_start_ready,
        .ui_start_address,.ui_start_amount,.ui_result_valid,.ui_result_error,
        .ui_result_code,.ui_result_tasks,.ui_result_ready,.ui_fault,
        .core_clk,.core_rst_n,.ui_mem_req_valid,.ui_mem_req_write,.ui_mem_req_addr,
        .ui_mem_req_wdata,.ui_mem_req_ready,.ui_mem_rsp_valid,.ui_mem_rsp_rdata,
        .ui_mem_rsp_error,.ui_mem_rsp_ready
    );

    task automatic joint_reset;
        begin
            @(negedge ui_clk);
            ui_start_valid=0;ui_result_ready=0;ui_mem_req_ready=0;
            ui_mem_rsp_valid=0;ui_mem_rsp_error=0;ui_mem_rsp_rdata=0;
            ui_admission_enable=1;ui_rearm_permit=1;simulated_readback_ack=0;
            ui_rst_n=0;core_rst_n=0;
            repeat(3)@(posedge ui_clk);
            @(negedge ui_clk);ui_rst_n=1;core_rst_n=1;
            repeat(3)@(posedge ui_clk);
            #1;
            if(ui_fault||ui_result_valid||ui_mem_req_valid||ui_mem_rsp_ready)
                $fatal(1,"joint reset failed to clear dispatcher/model controls");
        end
    endtask

    task automatic start_job(input logic cmac,input logic [31:0] address,input logic [31:0] amount);
        integer guard;
        begin
            @(negedge ui_clk);
            ui_start_cmac=cmac;ui_start_address=address;ui_start_amount=amount;ui_start_valid=1;
            #1;
            if(ui_start_ready!==1'b1)$fatal(1,"selected engine did not admit descriptor cmac=%b",cmac);
            if(cmac ? (ui_cmac_start_ready!==1'b1) : (ui_ew_start_ready!==1'b1))
                $fatal(1,"selected child not start-ready cmac=%b",cmac);
            @(posedge ui_clk);#1;
            @(negedge ui_clk);ui_start_valid=0;
            guard=0;
            while(!ui_mem_req_valid&&guard<30)begin @(negedge ui_clk);guard=guard+1;end
            if(!ui_mem_req_valid)$fatal(1,"selected model did not offer its request cmac=%b",cmac);
        end
    endtask

    task automatic stress_owned_request(input logic cmac,input logic [31:0] address,input logic [15:0] data);
        integer i;
        begin
            for(i=0;i<3;i=i+1)begin
                @(negedge ui_clk);
                ui_start_cmac=!cmac;ui_start_address=32'hface0000+i;ui_start_amount=32'hbad00000+i;
                ui_start_valid=1;
                #1;
                if(ui_start_ready!==1'b0)$fatal(1,"owned slot admitted competing descriptor");
                if(!ui_mem_req_valid||ui_mem_req_addr!==address||ui_mem_req_wdata!==data)
                    $fatal(1,"owned request rerouted/changed under selection and descriptor churn");
                @(posedge ui_clk);#1;
                @(negedge ui_clk);ui_start_valid=0;
            end
        end
    endtask

    task automatic finish_success(input logic cmac,input logic [31:0] address,input logic [31:0] amount,
                                  input logic [15:0] data,input logic write,
                                  input logic [31:0] tasks,input logic gate_until_ack);
        integer i;
        reg [31:0] req_address;
        begin
            req_address=address+(cmac?32'h20:32'h10);
            start_job(cmac,address,amount);
            if(ui_mem_req_valid!==1'b1||ui_mem_req_write!==write||
               ui_mem_req_addr!==req_address||ui_mem_req_wdata!==data)
                $fatal(1,"wrong selected request cmac=%b write=%b addr=%h data=%h",cmac,ui_mem_req_write,ui_mem_req_addr,ui_mem_req_wdata);
            stress_owned_request(cmac,req_address,data);

            @(negedge ui_clk);ui_mem_req_ready=1;
            @(posedge ui_clk);#1;
            if(ui_mem_req_valid!==1'b0)$fatal(1,"accepted memory request remained offered");
            @(negedge ui_clk);ui_mem_req_ready=0;
            for(i=0;i<20&&!ui_mem_rsp_ready;i=i+1)@(negedge ui_clk);
            if(ui_mem_rsp_ready!==1'b1)$fatal(1,"selected model did not accept memory response");
            @(negedge ui_clk);ui_mem_rsp_valid=1;ui_mem_rsp_rdata=cmac?16'hc002:16'he001;ui_mem_rsp_error=0;
            #1;if(ui_mem_rsp_ready!==1'b1)$fatal(1,"owned response ready dropped under valid");
            @(posedge ui_clk);#1;
            @(negedge ui_clk);ui_mem_rsp_valid=0;ui_mem_rsp_rdata=0;

            for(i=0;i<20&&!ui_result_valid;i=i+1)@(negedge ui_clk);
            if(ui_result_valid!==1'b1||ui_result_error!==1'b0||ui_result_code!==0||ui_result_tasks!==tasks)
                $fatal(1,"wrong result route cmac=%b valid=%b error=%b code=%0d tasks=%0d",cmac,ui_result_valid,ui_result_error,ui_result_code,ui_result_tasks);
            for(i=0;i<3;i=i+1)begin
                @(negedge ui_clk);ui_start_cmac=!cmac;ui_start_address=32'hdeadbeef-i;ui_start_amount=32'hcafe+i;
                if(gate_until_ack&&i==0)ui_admission_enable=0;
                #1;
                if(ui_start_ready!==1'b0||ui_result_valid!==1'b1||ui_result_error!==1'b0||
                   ui_result_code!==0||ui_result_tasks!==tasks)
                    $fatal(1,"result/owner changed while backpressured");
                @(posedge ui_clk);#1;
            end
            @(negedge ui_clk);ui_start_valid=0;ui_result_ready=1;
            if(gate_until_ack)ui_admission_enable=0;
            @(posedge ui_clk);#1;
            @(negedge ui_clk);ui_result_ready=0;
            if(ui_result_valid||ui_fault)$fatal(1,"successful result did not release owner cleanly");
            if(gate_until_ack)begin
                // Simulate parent DDR readback/ACK ownership. Admission stays
                // revoked after NUM status consumption until this event.
                simulated_readback_ack=0;ui_start_valid=1;ui_start_cmac=!cmac;
                #1;if(simulated_readback_ack!==1'b0||ui_start_ready!==1'b0)$fatal(1,"new start admitted before readback ACK");
                repeat(2)begin @(posedge ui_clk);#1;if(ui_start_ready!==1'b0)$fatal(1,"admission reopened before ACK");end
                @(negedge ui_clk);ui_start_valid=0;simulated_readback_ack=1;
                if(simulated_readback_ack===1'b1)ui_admission_enable=1;
                #1;if(ui_start_ready!==1'b1)$fatal(1,"admission not restored after simulated readback ACK");
                @(posedge ui_clk);#1;
                @(negedge ui_clk);simulated_readback_ack=0;
            end
        end
    endtask

    task automatic fail_timeout_with_late_drain;
        integer i;
        reg [31:0] held_address;
        reg [15:0] held_data;
        begin
            ui_mem_req_ready=0;
            start_job(1'b1,32'h40000000,32'h0000dead);
            if(!ui_mem_req_valid||ui_mem_req_write!==1'b0||ui_mem_req_addr!==32'h40000020||ui_mem_req_wdata!==16'hc200)
                $fatal(1,"CMAC timeout model did not offer expected held request");
            held_address=ui_mem_req_addr;held_data=ui_mem_req_wdata;
            for(i=0;i<30&&!ui_result_valid;i=i+1)begin
                @(negedge ui_clk);
                if(!ui_mem_req_valid||ui_mem_req_addr!==held_address||ui_mem_req_wdata!==held_data)
                    $fatal(1,"timeout withdrew/changed a held request");
            end
            if(ui_result_valid!==1'b1||ui_result_error!==1'b1||ui_result_code!==8||ui_result_tasks!==0||ui_fault!==1'b1)
                $fatal(1,"expected held-request E8 error, got valid=%b error=%b code=%0d tasks=%0d fault=%b",ui_result_valid,ui_result_error,ui_result_code,ui_result_tasks,ui_fault);
            @(negedge ui_clk);ui_result_ready=1;
            @(posedge ui_clk);#1;
            @(negedge ui_clk);ui_result_ready=0;
            if(ui_result_valid!==1'b0||ui_mem_req_valid!==1'b1||ui_mem_req_addr!==held_address||ui_mem_req_wdata!==held_data)
                $fatal(1,"failed owner/request was released after error consumption");
            ui_start_valid=1;ui_start_cmac=0;ui_start_address=32'h50000000;ui_start_amount=1;
            #1;if(ui_start_ready!==1'b0)$fatal(1,"failed CMAC owner was reselected before joint reset");
            @(posedge ui_clk);#1;
            @(negedge ui_clk);ui_start_valid=0;

            // The timeout does not cancel the offered bus word. Late request
            // acceptance and its response are drained only by the same CMAC.
            ui_mem_req_ready=1;
            @(posedge ui_clk);#1;
            @(negedge ui_clk);ui_mem_req_ready=0;
            if(ui_mem_req_valid!==1'b0||ui_mem_rsp_ready!==1'b1||ui_fault!==1'b1)
                $fatal(1,"late owned request did not remain on the failed owner");
            ui_mem_rsp_valid=1;ui_mem_rsp_rdata=16'hdead;ui_mem_rsp_error=0;
            #1;if(ui_mem_rsp_ready!==1'b1)$fatal(1,"late return was not offered to failed owner");
            @(posedge ui_clk);#1;
            @(negedge ui_clk);ui_mem_rsp_valid=0;ui_mem_rsp_rdata=0;
            repeat(2)begin
                @(posedge ui_clk);#1;
                if(ui_fault!==1'b1||ui_result_valid!==1'b0||ui_start_ready!==1'b0)
                    $fatal(1,"late return released or replaced failed owner");
            end
        end
    endtask

    task automatic unowned_response_fault;
        begin
            @(negedge ui_clk);ui_mem_rsp_valid=1;ui_mem_rsp_rdata=16'hbad0;
            #1;
            if(ui_mem_rsp_ready!==1'b0||ui_fault!==1'b1)$fatal(1,"unowned memory response was accepted or ignored");
            @(posedge ui_clk);#1;
            @(negedge ui_clk);ui_mem_rsp_valid=0;ui_mem_rsp_rdata=0;
            #1;if(ui_fault!==1'b1||ui_start_ready!==1'b0)$fatal(1,"unowned response fault did not latch");
        end
    endtask

    task automatic duplicate_offered_request_fault_without_ready;
        begin
            joint_reset();
            start_job(1'b0,32'h10000000,32'd22);
            @(negedge ui_clk);ui_mem_req_ready=1;
            @(posedge ui_clk);#1;
            @(negedge ui_clk);ui_mem_req_ready=0;
            if(dut.memory_pending!==1'b1)$fatal(1,"control did not own first response");
            force dut.ew_request=1'b1;
            #1;
            if(ui_fault!==1'b1||ui_start_ready!==1'b0||ui_mem_req_valid!==1'b1)
                $fatal(1,"second offered request was ignored while downstream READY was low");
            @(posedge ui_clk);#1;
            @(negedge ui_clk);release dut.ew_request;
            #1;
            if(ui_fault!==1'b1||dut.owned!==1'b1)
                $fatal(1,"duplicate-offer fault or owner did not remain latched");
            joint_reset();
        end
    endtask

    task automatic unknown_selection_fault;
        begin
            @(negedge ui_clk);ui_start_valid=1;ui_start_cmac=1'bx;
            #1;
            if(ui_start_ready!==1'b0||ui_fault!==1'b1)$fatal(1,"unknown engine selection did not fault closed");
            @(posedge ui_clk);#1;
            @(negedge ui_clk);ui_start_valid=0;
            #1;if(ui_fault!==1'b1||ui_start_ready!==1'b0)$fatal(1,"unknown-selection fault did not latch");
        end
    endtask

    initial begin
        ui_start_valid=0;ui_start_cmac=0;ui_start_address=0;ui_start_amount=0;
        ui_result_ready=0;ui_mem_req_ready=0;ui_mem_rsp_valid=0;ui_mem_rsp_error=0;
        ui_mem_rsp_rdata=0;
        joint_reset();
        finish_success(1'b0,32'h10000000,32'd22,16'he100,1'b1,32'd2,1'b1);
        finish_success(1'b1,32'h20000000,32'd22,16'hc200,1'b0,32'd1,1'b0);
        finish_success(1'b0,32'h30000000,32'd22,16'he100,1'b1,32'd2,1'b0);
        fail_timeout_with_late_drain();
        joint_reset();
        unowned_response_fault();
        joint_reset();
        duplicate_offered_request_fault_without_ready();
        unknown_selection_fault();
        joint_reset();
        $display("PASS dual_async_dispatch control_only=1 chain=EW-CMAC-EW req_result_backpressure=1 admission_readback_gate=1 failed_owner_late_drain=1 unowned_response=1 unknown_selection=1 duplicate_offer_without_ready=1");
        $finish;
    end

    initial begin #100000; $fatal(1,"control bench watchdog"); end
endmodule
