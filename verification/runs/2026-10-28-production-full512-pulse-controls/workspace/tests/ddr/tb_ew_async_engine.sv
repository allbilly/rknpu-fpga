// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Complete original raw BOs, real EW DMA, opposite-direction clock crossings.
// The destination is a bounded halfword test memory, not MIG or board DDR.
module tb_ew_async_engine #(parameter integer DUT_STAGES=3);
    localparam logic [31:0] BASE=32'h10000000;
    localparam logic [32:0] BYTES=33'd1048576;
    logic ui_clk,core_clk,ui_run,core_run,ui_rst_n,core_rst_n;
    logic ui_admission_enable,ui_start_valid,ui_result_ready;
    logic [31:0] ui_start_address,ui_start_amount;
    wire ui_start_ready,ui_result_valid,ui_result_error,ui_fault;
    wire [7:0] ui_result_code;
    wire [31:0] ui_result_tasks;
    wire ui_mem_req_valid,ui_mem_req_write,ui_mem_rsp_ready;
    wire [31:0] ui_mem_req_addr;
    wire [15:0] ui_mem_req_wdata;
    logic ui_mem_rsp_valid,ui_mem_rsp_error;
    logic [15:0] ui_mem_rsp_rdata;
    logic hold_requests,hold_returns,model_pending,model_error;
    logic [15:0] model_data;
    logic [3:0] model_delay;
    logic [31:0] random_ui;
    wire ui_mem_req_ready=ui_rst_n&&!hold_requests&&!model_pending&&!ui_mem_rsp_valid&&random_ui[0];
    rk_ew_async_engine #(.TIMEOUT_CYCLES(256),.MAX_TASKS(4),
        .JOB_SYNC_STAGES(DUT_STAGES),.MEMORY_SYNC_STAGES(DUT_STAGES)) dut(.*);
    initial begin ui_clk=0;core_clk=0;ui_run=1;core_run=1;end
    always begin #3.75;if(ui_run)ui_clk=~ui_clk;end
    always begin #10;if(core_run)core_clk=~core_clk;end
    logic [15:0] memory [0:524287];
    bit [16383:0] mapped_lines;
    integer reads,writes,responses,admissions,result_consumptions;
    integer negative_mode,original_negative,stop_clocks,jobs,expected_tasks,expected_reads,expected_writes;
    integer line_count,total_submitted,total_consumed,recovered;
    logic stalled_request,stalled_result;
    logic [48:0] held_request;
    logic [40:0] held_result;
    logic [31:0] address;
    logic [511:0] line_data;
    string case_directory,output_path;
    `include `RK_DDR_LINE_IMAGE_HEADER

    always @(posedge ui_clk or negedge ui_rst_n)begin
        if(!ui_rst_n)begin
            random_ui<=32'h3588cdce;model_pending<=0;model_error<=0;model_data<=0;model_delay<=0;
            ui_mem_rsp_valid<=0;ui_mem_rsp_error<=0;ui_mem_rsp_rdata<=0;
            reads<=0;writes<=0;responses<=0;admissions<=0;result_consumptions<=0;
            stalled_request<=0;stalled_result<=0;held_request<=0;held_result<=0;
        end else begin
            random_ui<={random_ui[30:0],random_ui[31]^random_ui[21]^random_ui[1]^random_ui[0]};
            if(ui_start_valid&&ui_start_ready)admissions<=admissions+1;
            if(ui_result_valid&&ui_result_ready)result_consumptions<=result_consumptions+1;
            if(stalled_request&&(!ui_mem_req_valid||
               {ui_mem_req_write,ui_mem_req_addr,ui_mem_req_wdata}!==held_request))
                $fatal(1,"Owned destination memory request changed/withdrawn");
            stalled_request<=ui_mem_req_valid&&!ui_mem_req_ready;
            held_request<={ui_mem_req_write,ui_mem_req_addr,ui_mem_req_wdata};
            if(stalled_result&&(!ui_result_valid||{ui_result_error,ui_result_code,ui_result_tasks}!==held_result))
                $fatal(1,"Held UI terminal result changed/withdrawn");
            stalled_result<=ui_result_valid&&!ui_result_ready;
            held_result<={ui_result_error,ui_result_code,ui_result_tasks};
            if(ui_mem_req_valid&&ui_mem_req_ready)begin
                if(model_pending||ui_mem_rsp_valid)$fatal(1,"More than one modeled memory request");
                model_pending<=1;model_delay<={1'b0,random_ui[3:1]};model_data<=0;model_error<=0;
                if(ui_mem_req_write)writes<=writes+1;else reads<=reads+1;
                if((^ui_mem_req_addr)===1'bx||ui_mem_req_addr[0]||ui_mem_req_addr<BASE||
                    ({1'b0,ui_mem_req_addr}+33'd2)>({1'b0,BASE}+BYTES)||
                    !mapped_lines[14'((ui_mem_req_addr-BASE)>>6)])begin
                    model_error<=1;
                end else if(negative_mode==2&&reads==0&&writes==0)begin
                    model_error<=1;
                end else if(ui_mem_req_write)begin
                    memory[19'((ui_mem_req_addr-BASE)>>1)]<=ui_mem_req_wdata;
                end else model_data<=memory[19'((ui_mem_req_addr-BASE)>>1)];
            end
            if(model_pending&&!hold_returns)begin
                if(model_delay==0)begin
                    model_pending<=0;ui_mem_rsp_valid<=1;ui_mem_rsp_error<=model_error;ui_mem_rsp_rdata<=model_data;
                end else model_delay<=model_delay-1'b1;
            end
            if(ui_mem_rsp_valid&&ui_mem_rsp_ready)begin ui_mem_rsp_valid<=0;responses<=responses+1;end
        end
    end

    task automatic reset_epoch;
        ui_start_valid=0;ui_result_ready=0;ui_admission_enable=0;
        ui_rst_n=0;core_rst_n=0;hold_requests=0;hold_returns=0;
        repeat(6)@(negedge core_clk);
        core_rst_n=1;@(negedge ui_clk);ui_rst_n=1;
        repeat(8)@(negedge ui_clk);ui_admission_enable=1;
    endtask
    task automatic upload;
        integer fd;
        logic [31:0] previous;
        for(integer line_index=0;line_index<16384;line_index=line_index+1)mapped_lines[line_index]=0;
        previous=0;
        ddr_image_open({case_directory,"/upload.txt"},line_count,fd);
        for(integer row=0;row<line_count;row=row+1)begin
            ddr_image_read(fd,row,previous,address,line_data);previous=address;
            mapped_lines[14'((address-BASE)>>6)]=1;
            for(integer half=0;half<32;half=half+1)
                memory[19'(((address-BASE)>>1)+32'(half))]=line_data[16*half+:16];
        end
        ddr_image_finish(fd);
        if(negative_mode==1||negative_mode==5||negative_mode==7)
            memory[19'((ui_start_address+32'd6-BASE)>>1)]=16'hffff;
    endtask
    task automatic kick;
        integer guard;
        guard=0;@(negedge ui_clk);
        while(!ui_start_ready)begin
            @(negedge ui_clk);guard=guard+1;if(guard>2000)$fatal(1,"Raw descriptor admission timeout");
        end
        ui_start_valid=1;@(posedge ui_clk);
        if(!ui_start_ready)$fatal(1,"Raw descriptor did not transfer");
        @(negedge ui_clk);ui_start_valid=0;total_submitted=total_submitted+1;
    endtask
    task automatic await_result(input integer expected_code,input integer tasks);
        integer guard;
        guard=0;
        while(!ui_result_valid)begin
            @(negedge ui_clk);guard=guard+1;if(guard>500000)$fatal(1,"Raw job result timeout");
        end
        if(ui_result_error!==(expected_code!=0)||ui_result_code!==8'(expected_code)||
            ui_result_tasks!==32'(tasks)||ui_start_ready)
            $fatal(1,"Wrong raw terminal code/count/error or premature next admission");
        repeat(32)@(negedge ui_clk);
    endtask
    task automatic consume_result;
        @(negedge ui_clk);ui_result_ready=1;
        @(posedge ui_clk);if(!ui_result_valid)$fatal(1,"Terminal result disappeared before consumption");
        @(negedge ui_clk);ui_result_ready=0;total_consumed=total_consumed+1;
        repeat(4)@(negedge ui_clk);
        if(ui_result_valid)$fatal(1,"Duplicate terminal result");
    endtask
    task automatic compare_and_dump;
        integer fd,observed;
        logic [31:0] previous;
        logic [511:0] actual;
        previous=0;ddr_image_open({case_directory,"/expected.txt"},line_count,fd);
        observed=$fopen(output_path,"w");if(observed==0)$fatal(1,"Cannot create complete BO readback");
        for(integer row=0;row<line_count;row=row+1)begin
            ddr_image_read(fd,row,previous,address,line_data);previous=address;actual=0;
            for(integer half=0;half<32;half=half+1)
                actual[16*half+:16]=memory[19'(((address-BASE)>>1)+32'(half))];
            if(actual!==line_data)$fatal(1,"Complete original BO differs at %h",address);
            $fdisplay(observed,"%08h %0128h",address,actual);
        end
        ddr_image_finish(fd);$fclose(observed);
    endtask
    integer code,guard;
    initial begin
        ui_rst_n=0;core_rst_n=0;ui_admission_enable=0;ui_start_valid=0;ui_result_ready=0;
        ui_start_address=0;ui_start_amount=0;hold_requests=0;hold_returns=0;
        total_submitted=0;total_consumed=0;recovered=0;
        if(!$value$plusargs("CASE=%s",case_directory)||!$value$plusargs("OUTPUT=%s",output_path)||
           !$value$plusargs("START=%h",ui_start_address)||!$value$plusargs("AMOUNT=%d",ui_start_amount)||
           !$value$plusargs("NTASKS=%d",expected_tasks)||!$value$plusargs("NLINES=%d",line_count)||
           !$value$plusargs("READS=%d",expected_reads)||!$value$plusargs("WRITES=%d",expected_writes)||
           !$value$plusargs("JOBS=%d",jobs)||!$value$plusargs("NEGATIVE=%d",negative_mode)||
           !$value$plusargs("STOPCLOCKS=%d",stop_clocks))$fatal(1,"Missing explicit raw test arguments");
        original_negative=negative_mode;
        if(jobs<1||jobs>2||negative_mode<0||negative_mode>7||stop_clocks<0||stop_clocks>1)
            $fatal(1,"Unsupported raw test selection");
        reset_epoch();upload();
        if(negative_mode==3||negative_mode==6)hold_returns=1;
        if(negative_mode==4)hold_requests=1;
        kick();
        if(negative_mode==6)begin
            // This is an explicit joint epoch while an old read is owned;
            // all core/crossing/model state resets, then original BOs reload.
            wait(model_pending);repeat(4)@(negedge ui_clk);
            if(ui_result_valid||ui_fault)$fatal(1,"Inflight reset test did not retain an unfinished healthy job");
            negative_mode=0;recovered=1;reset_epoch();upload();kick();
        end
        if(stop_clocks!=0)begin
            wait(reads>=1);@(negedge core_clk);core_run=0;
            repeat(60)@(negedge ui_clk);
            if(ui_result_valid||ui_start_ready)$fatal(1,"Stopped core invented job completion");
            core_run=1;wait(reads>=3);@(negedge ui_clk);ui_run=0;
            repeat(60)@(negedge core_clk);ui_run=1;
        end
        if(negative_mode!=0)begin
            code=(negative_mode==1||negative_mode==5||negative_mode==7)?1:negative_mode==2?5:8;
            await_result(code,0);
            if(negative_mode==3||negative_mode==4)begin
                // Timeout cannot cancel an already owned/offered request.
                if(negative_mode==4&&!ui_mem_req_valid)$fatal(1,"Timeout withdrew offered memory request");
                hold_requests=0;hold_returns=0;guard=0;
                while(responses<1)begin
                    @(negedge ui_clk);guard=guard+1;if(guard>2000)$fatal(1,"Late memory return did not drain");
                end
                repeat(32)@(negedge ui_clk);
                if(!ui_result_valid||!ui_result_error||ui_result_code!=8||ui_result_tasks!=0)
                    $fatal(1,"Late response rewrote the held timeout result");
            end
            consume_result();repeat(80)@(negedge ui_clk);
            if(!ui_fault||ui_start_ready||ui_result_valid||writes!=0||admissions!=1||result_consumptions!=1)
                $fatal(1,"Failed job did not remain quarantined exactly once");
            if(reads!=((negative_mode==1||negative_mode==5||negative_mode==7)?4:1)||responses!=reads)
                $fatal(1,"Wrong failed-job memory ownership/count");
            if(negative_mode==5)begin
                negative_mode=0;recovered=1;reset_epoch();upload();kick();
            end
            if(negative_mode==7)begin
                // Prove a sticky DMA error clears even when reset asserts and
                // releases while its clock is stopped. Queue fresh work before
                // restarting that clock; the reset register must win first.
                @(negedge core_clk);core_run=0;
                ui_start_valid=0;ui_result_ready=0;ui_admission_enable=0;
                core_rst_n=0;ui_rst_n=0;hold_requests=0;hold_returns=0;
                repeat(8)@(negedge ui_clk);
                core_rst_n=1;@(negedge ui_clk);ui_rst_n=1;
                repeat(8)@(negedge ui_clk);ui_admission_enable=1;
                negative_mode=0;recovered=1;upload();kick();
                repeat(12)@(negedge ui_clk);
                if(ui_result_valid||ui_start_ready)$fatal(1,"Stopped-reset core invented fresh completion");
                core_run=1;
            end
        end
        if(negative_mode==0)begin
            for(integer job=0;job<jobs;job=job+1)begin
                if(job!=0)kick();await_result(0,expected_tasks);
                if(ui_fault||model_pending||ui_mem_rsp_valid||ui_mem_req_valid||reads!=(job+1)*expected_reads||
                   writes!=(job+1)*expected_writes||responses!=reads+writes)
                    $fatal(1,"Successful terminal preceded real memory drain or exact raw request count");
                compare_and_dump();consume_result();
            end
            if(admissions!=jobs||result_consumptions!=jobs)$fatal(1,"Wrong final-epoch job/result count");
        end
        $display("PASS async_ew_boundary negative=%0d submitted=%0d consumed=%0d recovered=%0d stopped=%0d reads=%0d writes=%0d responses=%0d seed=3588cdce raw_BO_two_clocks_only",
            original_negative,total_submitted,total_consumed,recovered,stop_clocks,reads,writes,responses);
        $finish;
    end
    initial begin #50000000;$fatal(1,"Async EW boundary watchdog");end
endmodule
