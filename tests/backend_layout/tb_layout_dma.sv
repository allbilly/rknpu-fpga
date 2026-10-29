// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_layout_dma;
    localparam logic [31:0] BASE=32'h10000000;
    logic clk;
    initial clk=0;
    always #5 clk=~clk;
    logic rst_n=0,start_valid=0,result_ready=0;
    logic [31:0] start_address=BASE+32'hf000,start_amount=9;
    wire start_ready,busy,done,error;
    wire [7:0] error_code;
    wire mem_req_valid,mem_req_write,mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic response_valid,mem_rsp_error;
    logic unsolicited=0;
    wire mem_rsp_valid=response_valid||unsolicited;
    logic [15:0] mem_rsp_rdata;
    logic hold_requests=0,hold_returns=0,pending;
    logic [15:0] pending_data;
    logic pending_error;
    logic [2:0] delay_cycles;
    logic [31:0] rng;
    wire mem_req_ready=rst_n&&!hold_requests&&!pending&&!mem_rsp_valid&&rng[0];
    rk_layout_dma #(.BYTES(33'd65536),.TIMEOUT_CYCLES(32)) dut(.*);
    logic [15:0] memory[0:32767],expected[0:32767];
    integer mode=0,wanted_error=0,wanted_count=0,requests,responses,writes;
    integer epochs=0;
    logic stalled;
    logic [48:0] held;
    string directory;

    always @(posedge clk)begin: model
        logic [14:0] offset;
        if(!rst_n)begin
            pending<=0;pending_data<=0;pending_error<=0;delay_cycles<=0;rng<=32'h3588;
            response_valid<=0;mem_rsp_error<=0;mem_rsp_rdata<=0;
            requests<=0;responses<=0;writes<=0;stalled<=0;held<=0;
        end else begin
            rng<=rng*32'd1664525+32'd1013904223;
            if(stalled&&(!mem_req_valid||{mem_req_write,mem_req_addr,mem_req_wdata}!==held))
                $fatal(1,"Layout withdrew or changed stalled request");
            stalled<=mem_req_valid&&!mem_req_ready;
            held<={mem_req_write,mem_req_addr,mem_req_wdata};
            if(done&&(pending||mem_rsp_valid||mem_req_valid||requests!=responses||writes!=wanted_count*epochs))
                $fatal(1,"Layout completed before final write response drained");
            if(mem_req_valid&&mem_req_ready)begin
                if(pending||mem_rsp_valid||mem_req_addr[0]||mem_req_addr<BASE||mem_req_addr>=BASE+32'h10000)
                    $fatal(1,"Layout escaped aperture or violated single ownership");
                offset=mem_req_addr[15:1];
                pending<=1;pending_data<=memory[offset];pending_error<=0;
                delay_cycles<=rng[3:1];requests<=requests+1;
                if(mode==3&&requests==0)pending_error<=1;
                if(mode==6&&mem_req_addr>=BASE+32'h1000&&mem_req_addr<BASE+32'h3000)pending_error<=1;
                if(mode==7&&mem_req_write)pending_error<=1;
                if(mem_req_write)begin memory[offset]<=mem_req_wdata;writes<=writes+1;end
`ifndef VERILATOR
                if(mode==4&&requests==0)pending_data<=16'hxxxx;
`endif
            end
            if(pending&&!hold_returns)begin
                if(delay_cycles!=0)delay_cycles<=delay_cycles-1'b1;
                else begin
                    pending<=0;response_valid<=1;mem_rsp_error<=pending_error;mem_rsp_rdata<=pending_data;
                end
            end
            if(mem_rsp_valid&&mem_rsp_ready)begin response_valid<=0;responses<=responses+1;end
        end
    end
    task automatic launch;
        integer cycles;
        epochs=epochs+1;
        @(negedge clk);start_valid=1;
        cycles=0;
        while(!start_ready)begin @(negedge clk);cycles=cycles+1;if(cycles>100)$fatal(1,"No start readiness");end
        @(negedge clk);start_valid=0;
    endtask
    task automatic terminal;
        integer cycles;
        cycles=0;
        while(!done&&!error)begin
            @(negedge clk);cycles=cycles+1;
            if(cycles>500000)$fatal(1,"Layout failed to terminate");
        end
        if(wanted_error!=0)begin
            if(!error||done||error_code!==8'(wanted_error))
                $fatal(1,"Wrong fault expected=%0d actual=%0d",wanted_error,error_code);
        end else if(!done||error||error_code!=0)$fatal(1,"Positive layout failed code=%0d",error_code);
    endtask
    task automatic compare_all;
        for(integer i=0;i<32768;i=i+1)
            if(memory[i]!==expected[i])$fatal(1,"Whole memory differs lane=%0d actual=%h expected=%h",i,memory[i],expected[i]);
    endtask
    initial begin
        if(!$value$plusargs("directory=%s",directory)||!$value$plusargs("count=%d",wanted_count)||
           !$value$plusargs("error=%d",wanted_error)||!$value$plusargs("mode=%d",mode))
            $fatal(1,"Missing layout fixture arguments");
        if($value$plusargs("amount=%d",start_amount))begin end
        if($value$plusargs("address=%h",start_address))begin end
        $readmemh({directory,"/memory.hex"},memory);
        $readmemh({directory,"/expected.hex"},expected);
        repeat(4)@(negedge clk);rst_n=1;
        if(mode==1)hold_requests=1;
        if(mode==2)hold_returns=1;
        if(mode==5)begin
            @(negedge clk);unsolicited=1;
            repeat(2)@(negedge clk);
            unsolicited=0;
        end else launch();
        terminal();
        if(wanted_error!=0)begin
            // A timeout cannot withdraw a held request or forget an accepted
            // response. Release the model only after inspecting quarantine.
            if(mode==1&&!mem_req_valid)$fatal(1,"Timeout discarded held VALID");
            if(mode==2&&(!pending||mem_req_valid))$fatal(1,"Timeout forgot accepted request");
            repeat(6)begin
                @(negedge clk);
                if(!error||error_code!==8'(wanted_error)||start_ready||done)$fatal(1,"Fault was not sticky");
            end
            hold_requests=0;hold_returns=0;
            repeat(40)@(negedge clk);
            if(pending||mem_rsp_valid||mem_req_valid||requests!=responses-(mode==5 ? 1 : 0))
                $fatal(1,"Fault did not drain held request/late response");
            if(writes!=0&&mode!=7)$fatal(1,"Invalid descriptor caused a write");
            start_valid=1;result_ready=1;
            repeat(6)@(negedge clk);
            if(start_ready||!error||error_code!==8'(wanted_error))$fatal(1,"Fault rearmed without joint reset");
        end else begin
            compare_all();
            start_valid=1;
            repeat(7)begin
                @(negedge clk);
                if(!done||error||start_ready||mem_req_valid)$fatal(1,"Completion did not retain ownership");
            end
            start_valid=0;result_ready=1;@(negedge clk);result_ready=0;
            // Successful ACK permits reuse without resetting or modifying RAM.
            launch();terminal();compare_all();
            result_ready=1;@(negedge clk);result_ready=0;
            if(!start_ready||busy||done||error)$fatal(1,"Success ACK did not release engine");
        end
        $display("PASS raw_layout mode=%0d error=%0d lanes=%0d epochs=%0d requests=%0d writes=%0d seed=3588",mode,wanted_error,wanted_count,epochs,requests,writes);
        $finish;
    end
    initial begin #10000000;$fatal(1,"Layout bench deadline");end
endmodule
