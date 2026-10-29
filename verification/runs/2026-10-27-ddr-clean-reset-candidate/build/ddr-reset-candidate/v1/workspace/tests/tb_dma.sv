`timescale 1ns/1ps
module tb_dma;
    localparam logic [31:0] BASE=32'h10000000;
    localparam integer WORDS=524288;
    logic clk;
    initial clk=0;
    always #5 clk=~clk;
    logic rst_n=0, start_valid=0, start_ready, busy, done, task_done, error;
    logic [31:0] start_address, start_amount, completed_tasks;
    logic [7:0] error_code;
    logic mem_req_valid, mem_req_ready, mem_req_write, mem_rsp_valid, mem_rsp_ready, mem_rsp_error;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_req_wdata, mem_rsp_rdata;
    logic [15:0] memory [0:WORDS-1];
    `include "tests/memory_check.svh"
    integer expected_checks;
    logic mapped [0:WORDS-1];
    logic pending, pending_write;
    logic [31:0] pending_addr;
    logic [15:0] pending_data;
    logic [31:0] lfsr;
    integer delay_count, cycles, jobs, task_events, transactions;
    integer expected_error, expected_jobs, expected_tasks, expected_transactions, repeats;
    integer bus_error_at, drop_at, stall_at;
    integer reset_at, fault_before_restart;
    logic held;
    logic [48:0] held_request;
    string prefix, output_path;
    rk_ew_dma #(.TIMEOUT_CYCLES(128), .MAX_TASKS(4)) dut(.*);
    assign mem_req_ready = rst_n && transactions+1!=stall_at && !pending && !mem_rsp_valid && (lfsr[0] || lfsr[3]);
    always @(posedge clk) begin
        if (!rst_n) begin
            pending<=0; pending_write<=0; pending_addr<=0; pending_data<=0;
            mem_rsp_valid<=0; mem_rsp_error<=0; mem_rsp_rdata<=0; delay_count<=0;
            transactions<=0; cycles<=0; jobs<=0; task_events<=0; held<=0; held_request<=0;
            lfsr<=32'h35881234;
        end else begin
            cycles<=cycles+1;
            lfsr<={lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
            if (cycles>2000000) $fatal(1,"global timeout");
            if (done) jobs<=jobs+1;
            if (task_done) task_events<=task_events+1;
            if (done && error) $fatal(1,"done and error both asserted");
            if (done && (pending || mem_rsp_valid)) $fatal(1,"premature job completion");
            if (start_ready && (busy || error)) $fatal(1,"start accepted while busy/faulted");
            if ((mem_req_valid || mem_rsp_ready) && !busy) $fatal(1,"memory activity outside busy");
            if (held && !error && (!mem_req_valid ||
                {mem_req_write,mem_req_addr,mem_req_wdata} !== held_request))
                $fatal(1,"memory request changed under backpressure");
            held<=mem_req_valid && !mem_req_ready;
            held_request<={mem_req_write,mem_req_addr,mem_req_wdata};
            if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid<=0;
            if (mem_req_valid && mem_req_ready) begin
                if (pending || mem_rsp_valid) $fatal(1,"two outstanding requests");
                pending<=1; pending_write<=mem_req_write;
                pending_addr<=mem_req_addr; pending_data<=mem_req_wdata;
                delay_count<=int'(lfsr[6:4]); transactions<=transactions+1;
            end
            if (pending && transactions!=drop_at) begin
                if (delay_count!=0) delay_count<=delay_count-1;
                else begin
                    pending<=0; mem_rsp_valid<=1;
                    if (transactions==bus_error_at || pending_addr<BASE ||
                        ((pending_addr-BASE)>>1)>=WORDS || pending_addr[0]) begin
                        mem_rsp_error<=1; mem_rsp_rdata<=0;
                    end else if (!mapped[(pending_addr-BASE)>>1]) begin
                        mem_rsp_error<=1; mem_rsp_rdata<=0;
                    end else begin
                        mem_rsp_error<=0;
                        if (pending_write) begin
                            memory[(pending_addr-BASE)>>1]<=pending_data;
                            mem_rsp_rdata<=0;
                        end else mem_rsp_rdata<=memory[(pending_addr-BASE)>>1];
                    end
                end
            end
        end
    end
    initial begin
        if (!$value$plusargs("NCHECKS=%d",expected_checks)) $fatal(1,"missing NCHECKS");
        if (!$value$plusargs("CASE=%s",prefix)) $fatal(1,"missing CASE");
        if (!$value$plusargs("OUTPUT=%s",output_path)) output_path="";
        if (!$value$plusargs("START=%h",start_address)) $fatal(1,"missing START");
        if (!$value$plusargs("AMOUNT=%d",start_amount)) $fatal(1,"missing AMOUNT");
        if (!$value$plusargs("ECODE=%d",expected_error)) $fatal(1,"missing ECODE");
        if (!$value$plusargs("NJOBS=%d",expected_jobs)) $fatal(1,"missing NJOBS");
        if (!$value$plusargs("NTASKS=%d",expected_tasks)) $fatal(1,"missing NTASKS");
        if (!$value$plusargs("REPEATS=%d",repeats)) repeats=1;
        if (!$value$plusargs("BUS_ERROR_AT=%d",bus_error_at)) bus_error_at=0;
        if (!$value$plusargs("DROP_AT=%d",drop_at)) drop_at=0;
        if (!$value$plusargs("STALL_AT=%d",stall_at)) stall_at=0;
        if (!$value$plusargs("RESET_AT=%d",reset_at)) reset_at=0;
        if (!$value$plusargs("FAULT_BEFORE_RESTART=%d",fault_before_restart)) fault_before_restart=0;
        if (!$value$plusargs("NTRANS=%d",expected_transactions)) $fatal(1,"missing NTRANS");
        for (integer i=0; i<WORDS; i=i+1) mapped[i]=0;
        $readmemh({prefix,"/mapped.hex"},mapped);
        $readmemh({prefix,"/input.hex"},memory);
        repeat(4) @(negedge clk);
        rst_n=1;
        if (reset_at!=0 || fault_before_restart!=0) begin
            bus_error_at=fault_before_restart;
            @(negedge clk); start_valid=1;
            do @(posedge clk); while (!start_ready);
            @(negedge clk); start_valid=0;
            if (fault_before_restart!=0) begin
                wait(error);
                @(negedge clk);
                if (error_code!=5 || completed_tasks!=0 || jobs!=0)
                    $fatal(1,"bad pre-reset fault code=%0d tasks=%0d jobs=%0d",error_code,completed_tasks,jobs);
            end else wait(transactions==reset_at);
            @(negedge clk); rst_n=0;
            repeat(4) @(negedge clk);
            if (start_ready || busy || error || completed_tasks!=0) $fatal(1,"reset state not cleared");
            // Reset cancels the adapter together with the DUT; RAM is not rolled back.
            bus_error_at=0; rst_n=1;
        end
        for (integer job=0; job<repeats; job=job+1) begin
            @(negedge clk); start_valid=1;
            do @(posedge clk); while (!start_ready);
            @(negedge clk); start_valid=0;
            wait (error || jobs==job+1);
            repeat(3) @(negedge clk);
        end
        if (expected_error!=0) begin
            if (!error || int'(error_code)!=expected_error)
                $fatal(1,"wrong error: got %0d wanted %0d",error_code,expected_error);
            start_valid=1;
            repeat(8) begin
                @(negedge clk);
                if (start_ready || mem_req_valid || int'(error_code)!=expected_error || !error)
                    $fatal(1,"fault not sticky");
            end
            start_valid=0;
        end else if (error) $fatal(1,"unexpected error %0d",error_code);
        if (jobs!=expected_jobs || task_events!=expected_tasks*repeats || completed_tasks!=32'(expected_tasks))
            $fatal(1,"completion counts jobs=%0d tasks=%0d per_job=%0d",jobs,task_events,completed_tasks);
        if (transactions!=expected_transactions)
            $fatal(1,"transaction count %0d wanted %0d",transactions,expected_transactions);
        verify_memory({prefix,"/check.txt"},output_path,expected_checks,expected_error!=0);
        $display("PASS %s cycles=%0d transactions=%0d tasks=%0d jobs=%0d expected_error=%0d",
                 prefix,cycles,transactions,task_events,jobs,expected_error);
        $finish;
    end
endmodule
